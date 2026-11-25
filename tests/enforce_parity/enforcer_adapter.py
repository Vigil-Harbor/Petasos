"""Replay a scenario through ``petasos.enforce.Enforcer``.

The scenario's flat settings are translated here, with the migration and the
legacy secret split. The enforcer does not see a Hermes home, a hook return,
or the reference plugin.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from petasos.config.layers import resolve
from petasos.config.migrate import migrate
from petasos.config.secrets import Secrets
from petasos.enforce import (
    Allow,
    ApprovalGrant,
    ApprovalNotice,
    Approve,
    Block,
    Enforcer,
    EvaluationFault,
    HostInfo,
    InitGate,
    ManualClock,
    SettingsSnapshot,
    ToolCall,
)
from tests.enforce_parity.load import bind_paths, scrub_event, scrub_known

if TYPE_CHECKING:
    from petasos.config.sections import PetasosConfig

_ISOLATED_ENV = (
    "HERMES_HOME",
    "HERMES_YOLO_MODE",
    "PETASOS_AUDIT_FINDING",
    "PETASOS_HASH_KEY",
    "PETASOS_LICENSE_KEY",
    "PETASOS_SESSION_SECRET",
)
_RESULT_COMPACT_AT = 400
_CLOCK_ORIGIN = 1_000.0
_WINDOW = 31.0


class _LogCapture(logging.Handler):
    """Operator lines emitted while one step runs."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Keep ``PETASOS_`` lines and restart-required warnings."""
        try:
            message = record.getMessage()
        except Exception:
            return
        if "PETASOS_" in message or "restart required" in message:
            self.lines.append(message)


class _StubScanner:
    """A scanner the scenario declared. It never touches a real ML backend."""

    def __init__(self, spec: dict[str, Any]) -> None:
        name = spec.get("name")
        if not isinstance(name, str) or not name:
            raise TypeError("scanner name must be a non-empty string")
        self.name = name
        self._spec = spec

    async def scan(
        self,
        text: str,
        *,
        direction: str = "inbound",
        session_id: str | None = None,
    ) -> Any:
        """Return the findings ``spec`` names, or fail the way it asks."""
        import asyncio

        from petasos.model import ScanFinding, ScanResult, Severity

        del direction, session_id
        mode = self._spec.get("mode", "rules")
        if mode == "error":
            raise RuntimeError("stub scanner failed")
        if mode == "timeout":
            await asyncio.Event().wait()
        findings: list[ScanFinding] = []
        rules = self._spec.get("rules", [])
        if not isinstance(rules, list):
            raise TypeError("scanner rules must be a list")
        for rule in rules:
            if not isinstance(rule, dict):
                raise TypeError("scanner rule must be an object")
            needle = rule.get("contains", "")
            if not isinstance(needle, str) or needle not in text:
                continue
            severity = Severity(str(rule.get("severity", "high")))
            confidence = rule.get("confidence", 0.9)
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise TypeError("scanner confidence must be a number")
            findings.append(
                ScanFinding(
                    rule_id=str(rule.get("rule_id", f"petasos.{self.name}.stub")),
                    finding_type=str(rule.get("finding_type", "injection")),
                    severity=severity,
                    confidence=float(confidence),
                    message=str(rule.get("message", rule.get("rule_id", "stub finding"))),
                    scanner_name=self.name,
                )
            )
        return ScanResult(scanner_name=self.name, findings=tuple(findings))


class _Source:
    """The settings callable. Steps replace the snapshot; the token changes."""

    def __init__(self, snapshot: SettingsSnapshot) -> None:
        self.snapshot = snapshot

    def __call__(self) -> SettingsSnapshot:
        return self.snapshot


def _host_view(scenario: dict[str, Any]) -> dict[str, Any]:
    raw = scenario.get("host", {})
    if not isinstance(raw, dict):
        raise TypeError("host must be an object")
    always = raw.get("always_approved", [])
    if not isinstance(always, list) or not all(isinstance(item, str) for item in always):
        raise TypeError("always_approved must be a list of strings")
    return {
        "always_approved": always,
        "approve_directive": bool(raw.get("approve_directive", False)),
        "auto_approve": bool(raw.get("auto_approve", False)),
        "redactor": raw.get("redactor", "identity"),
        "subagent_hooks": bool(raw.get("subagent_hooks", True)),
    }


def _lifecycle(scenario: dict[str, Any]) -> tuple[str, str]:
    raw = scenario.get("lifecycle", "ready")
    if isinstance(raw, str):
        return raw, ""
    if not isinstance(raw, dict):
        raise TypeError("lifecycle must be a string or an object")
    state = raw.get("state")
    error = raw.get("error", "")
    if not isinstance(state, str) or not isinstance(error, str):
        raise TypeError("lifecycle state and error must be strings")
    return state, error


def _disabled(section: dict[str, Any]) -> set[str]:
    raw = section.get("disabled_scanners", [])
    if not isinstance(raw, list):
        return set()
    return {item for item in raw if isinstance(item, str)}


def _force_registered(config: PetasosConfig, disabled: set[str]) -> PetasosConfig:
    """Map a scanner that the old bootstrap would have registered to ``on``.

    ``auto`` leaves a missing package out. The record was made when a missing
    package still failed every scan, which is what ``on`` does.
    """
    scanners = config.scanners
    presidio = scanners.presidio
    prompt_guard = scanners.prompt_guard
    if "presidio" not in disabled and presidio.enabled != "on":
        presidio = replace(presidio, enabled="on")
    if "prompt_guard" not in disabled and prompt_guard.enabled != "on":
        prompt_guard = replace(prompt_guard, enabled="on")
    if presidio is scanners.presidio and prompt_guard is scanners.prompt_guard:
        return config
    return replace(
        config, scanners=replace(scanners, presidio=presidio, prompt_guard=prompt_guard)
    )


def _secrets(section: dict[str, Any]) -> tuple[Secrets, bool]:
    raw = section.get("session_secret")
    secret: bytes | None = None
    invalid = False
    if isinstance(raw, str) and raw:
        try:
            secret = base64.b64decode(raw, validate=True)
        except Exception:
            invalid = True
    elif isinstance(raw, bytes):
        secret = raw
    hash_key = section.get("hash_key")
    if not isinstance(hash_key, str) or not hash_key:
        hash_key = None
    return Secrets(session_secret=secret, hash_key=hash_key), invalid


def _defang(config: PetasosConfig, secrets: Secrets) -> PetasosConfig:
    anonymization = config.anonymization
    if anonymization.mode == "hash" and not secrets.hash_key and anonymization.enabled:
        return replace(config, anonymization=replace(anonymization, enabled=False))
    return config


def absolute_engine_path(section: dict[str, Any]) -> dict[str, Any]:
    """The section with its Semgrep engine path absolute on this system.

    A scenario writes ``/tmp/...``. That has no drive on Windows, where newer
    Pythons no longer call it absolute, and the settings then fail to build.
    """
    engine = section.get("semgrep_engine_path")
    if not isinstance(engine, str):
        return section
    return {**section, "semgrep_engine_path": os.path.abspath(engine)}


def snapshot_from_section(
    section: dict[str, Any],
    token: int,
    *,
    armed: bool | None = None,
) -> SettingsSnapshot:
    """Translate one flat ``petasos:`` section into a settings snapshot."""
    if armed is None:
        enabled = section.get("enabled", True)
        armed_value = enabled if isinstance(enabled, bool) else True
    else:
        armed_value = armed
    secrets, invalid = _secrets(section)
    try:
        migrated = migrate(absolute_engine_path(section))
        resolved = resolve(migrated.settings).config
        config = _defang(_force_registered(resolved, _disabled(section)), secrets)
    except Exception as exc:
        return SettingsSnapshot(
            armed=armed_value,
            config=None,
            secrets=Secrets(),
            token=token,
            error=f"build failed: {exc}",
            secret_invalid=invalid,
        )
    return SettingsSnapshot(
        armed=armed_value,
        config=config,
        secrets=secrets,
        token=token,
        secret_invalid=invalid,
    )


def _redactor(spec: object) -> Any:
    if spec == "unavailable":
        return None
    if spec == "identity":

        def identity(text: str, **_options: object) -> str:
            return text

        return identity
    if isinstance(spec, dict):
        raw = spec.get("mask", [])
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise TypeError("redactor.mask must be a list of strings")
        needles = tuple(raw)

        def redact(text: str, **_options: object) -> str:
            masked = text
            for needle in needles:
                masked = masked.replace(needle, "[masked]")
            return masked

        return redact
    raise TypeError("redactor must be identity, unavailable, or {mask: [...]}")


def _protected(home: Path, config: Path) -> frozenset[str]:
    """The paths the plugin's guard would have discovered under this home."""
    names = [
        str(config),
        str(home / "petasos-enforcement.jsonl"),
        str(home / "petasos-enforcement.jsonl.rot"),
    ]
    profiles = home / "profiles"
    if profiles.is_dir():
        for profile in profiles.iterdir():
            if not profile.is_dir():
                continue
            profile_config = profile / "config.yaml"
            names.append(str(profile_config))
            names.append(str(profile / "petasos-enforcement.jsonl"))
            names.append(str(profile / "petasos-enforcement.jsonl.rot"))
    return frozenset(names)


class EnforcerOracle:
    """Replay a scenario through one new enforcer."""

    def replay(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        """Run ``scenario`` against a temporary spool and return its outcomes."""
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise TypeError("scenario id must be a non-empty string")
        home_dir = Path(tempfile.mkdtemp(prefix="petasos-enforce-parity-"))
        try:
            return _Runner(scenario, home_dir).run()
        finally:
            shutil.rmtree(home_dir, ignore_errors=True)


class _Runner:
    """One scenario against one enforcer."""

    def __init__(self, scenario: dict[str, Any], home: Path) -> None:
        self.scenario = scenario
        self.home = home.resolve()
        self.config_path = self.home / "config.yaml"
        self.spool_path = self.home / "petasos-enforcement.jsonl"
        self.host = _host_view(scenario)
        self.homes: list[str] = []
        self.configs: list[str] = []
        self._offset = 0
        self._token = 1
        self._section: dict[str, Any] = {}
        self._handler = _LogCapture()
        self._saved_env: dict[str, str | None] = {}
        self._clock = ManualClock(monotonic=_CLOCK_ORIGIN, wall=_CLOCK_ORIGIN)
        self._fault = EvaluationFault()
        self._source = _Source(
            SettingsSnapshot(armed=True, config=None, secrets=Secrets(), token=0, error="unset")
        )
        self._enforcer: Enforcer | None = None
        self._gate: InitGate | None = None

    def run(self) -> list[dict[str, Any]]:
        """Boot the enforcer, run every step, and restore the process environment."""
        self._remember(self.home, self.config_path)
        self._isolate_env()
        logger = logging.getLogger("petasos")
        saved_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(self._handler)
        try:
            self._section = _settings(self.scenario)
            self._source.snapshot = snapshot_from_section(self._section, self._token)
            self._boot()
            outcomes: list[dict[str, Any]] = []
            steps = self.scenario.get("steps")
            if not isinstance(steps, list):
                raise TypeError("steps must be a list")
            for step in steps:
                if not isinstance(step, dict):
                    raise TypeError("step must be an object")
                outcomes.append(self._step(step))
            return outcomes
        finally:
            if self._enforcer is not None:
                self._enforcer.close()
            logger.removeHandler(self._handler)
            logger.setLevel(saved_level)
            for name in _ISOLATED_ENV:
                os.environ.pop(name, None)
                saved = self._saved_env.get(name)
                if saved is not None:
                    os.environ[name] = saved

    def _remember(self, home: Path, config: Path) -> None:
        for path in (home, config):
            bucket = self.configs if path == config else self.homes
            for item in (str(path), str(path.resolve())):
                if item not in bucket:
                    bucket.append(item)

    def _isolate_env(self) -> None:
        for name in _ISOLATED_ENV:
            self._saved_env[name] = os.environ.pop(name, None)
        os.environ["HERMES_HOME"] = str(self.home)

    def _boot(self) -> None:
        state, error = _lifecycle(self.scenario)
        if state == "ready":
            gate = None
        elif state == "starting":
            gate = InitGate.held(skip_wait=True)
        elif state == "failed":
            gate = InitGate.failed(error or "initialization failed")
        else:
            raise ValueError(f"unknown lifecycle {state!r}")
        self._gate = gate
        always = set(self.host["always_approved"])
        auto = bool(self.host["auto_approve"])
        enforcer = Enforcer(
            self._source,
            host=HostInfo(
                host_id="petasos",
                approve_directive=bool(self.host["approve_directive"]),
                approval_grant=lambda: ApprovalGrant(yolo=auto),
                rule_always_approved=lambda rule: rule in always,
                subagent_hooks=bool(self.host["subagent_hooks"]),
                redactor=_redactor(self.host["redactor"]),
                protected_paths=lambda: _protected(self.home, self.config_path),
            ),
            clock=self._clock,
            scanners=tuple(_stubs(self.scenario)),
            init=gate,
            evaluation=self._fault,
            spool_path=str(self.spool_path),
        )
        self._enforcer = enforcer
        enforcer.start()
        if state != "starting" and not enforcer.settle(30):
            raise RuntimeError("enforcer init did not finish")

    def _step(self, step: dict[str, Any]) -> dict[str, Any]:
        self._handler.lines.clear()
        bound = bind_paths(step, home=str(self.home), config=str(self.config_path))
        if not isinstance(bound, dict):
            raise TypeError("step must bind to an object")
        try:
            decision = self._dispatch(bound)
        except Exception as exc:
            decision = {"action": "error", "message": f"{type(exc).__name__}: {exc}"}
        events, self._offset = _read_spool(self.spool_path, self._offset)
        return {
            "decision": _scrub_decision(decision, homes=self.homes, configs=self.configs),
            "events": [
                scrub_event(event, homes=self.homes, configs=self.configs) for event in events
            ],
            "id": bound.get("id"),
            "logs": [
                scrub_known(line, homes=self.homes, configs=self.configs)
                for line in self._handler.lines
            ],
            "tier": self._tier(_session_of(bound)),
        }

    def _dispatch(self, step: dict[str, Any]) -> dict[str, Any] | None:
        enforcer = self._enforcer
        if enforcer is None:
            raise RuntimeError("enforcer was not started")
        kind = step.get("do")
        if kind == "tool_call":
            return _decision_from_call(enforcer.tool_call(_call(step)))
        if kind == "tool_result":
            returned = enforcer.tool_result(_call(step), step.get("result", ""))
            return _decision_from_result(returned, step.get("result"))
        if kind == "tool_finished":
            enforcer.tool_finished(_call(step), _text(step.get("result")))
            return None
        if kind == "session_start":
            enforcer.session_started(str(step.get("session", "")))
            return None
        if kind == "subagent_start":
            enforcer.subagent_started(str(step.get("child", "")), str(step.get("parent", "")))
            return None
        if kind == "subagent_stop":
            enforcer.subagent_stopped(str(step.get("child", "")))
            return None
        if kind == "approval_request":
            enforcer.approval_requested(_notice(step))
            return None
        if kind == "approval_answer":
            enforcer.approval_answered(_notice(step))
            return None
        if kind == "settings":
            self._apply_settings(step)
            return None
        if kind == "arm":
            self._section["enabled"] = bool(step.get("armed", True))
            self._publish()
            return None
        if kind == "init_complete":
            if self._gate is not None:
                self._gate.release()
            enforcer.settle(30)
            return None
        if kind == "evaluation_fault":
            fault = step.get("kind")
            if fault not in ("error", "timeout"):
                raise ValueError("evaluation_fault kind must be error or timeout")
            timeout = 0.05 if fault == "timeout" else None
            self._fault.arm(str(fault), timeout_s=timeout)
            return None
        if kind == "open_log_window":
            self._clock.advance(_WINDOW)
            return None
        if kind == "profile_change":
            self._profile_change(step)
            return None
        raise ValueError(f"unknown step {kind!r}")

    def _publish(self) -> None:
        self._token += 1
        self._source.snapshot = snapshot_from_section(self._section, self._token)

    def _apply_settings(self, step: dict[str, Any]) -> None:
        raw = step.get("raw")
        if isinstance(raw, str):
            self._token += 1
            self._source.snapshot = SettingsSnapshot(
                armed=True,
                config=None,
                secrets=Secrets(),
                token=self._token,
                error="build failed: malformed settings",
            )
            return
        patch = step.get("set", {})
        if not isinstance(patch, dict):
            raise TypeError("settings set must be an object")
        self._section.update(patch)
        self._publish()

    def _profile_change(self, step: dict[str, Any]) -> None:
        name = str(step.get("name", ""))
        given = step.get("home")
        if isinstance(given, str):
            target = Path(given)
            if not target.is_absolute() or not target.is_dir():
                return
            home = target
        else:
            home = self.home / "profiles" / (name or "unnamed")
        section = step.get("settings", {})
        if not isinstance(section, dict):
            raise TypeError("profile settings must be an object")
        if isinstance(given, str):
            pass
        else:
            home.mkdir(parents=True, exist_ok=True)
            self._remember(home, home / "config.yaml")
        if not section:
            return
        self._section = dict(section)
        self._publish()
        enforcer = self._enforcer
        if enforcer is not None:
            enforcer.refresh()

    def _tier(self, session: str | None) -> str | None:
        if not session or self._enforcer is None:
            return None
        return self._enforcer.session_tier(session)


def _settings(scenario: dict[str, Any]) -> dict[str, Any]:
    raw = scenario.get("settings", {})
    if not isinstance(raw, dict):
        raise TypeError("settings must be an object")
    return dict(raw)


def _stubs(scenario: dict[str, Any]) -> list[_StubScanner]:
    specs = scenario.get("scanners", [])
    if not isinstance(specs, list):
        raise TypeError("scanners must be a list")
    stubs: list[_StubScanner] = []
    for spec in specs:
        if not isinstance(spec, dict):
            raise TypeError("scanner must be an object")
        stubs.append(_StubScanner(spec))
    return stubs


def _call(step: dict[str, Any]) -> ToolCall:
    args = step.get("args", {})
    if not isinstance(args, dict):
        args = {}
    return ToolCall(
        tool=str(step.get("tool", "")),
        args=args,
        session=str(step.get("session", "")),
        turn_id=step.get("turn_id") if isinstance(step.get("turn_id"), str) else None,
        tool_call_id=step.get("tool_call_id")
        if isinstance(step.get("tool_call_id"), str)
        else None,
        host_session=step.get("hermes_session")
        if isinstance(step.get("hermes_session"), str)
        else None,
    )


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _notice(step: dict[str, Any]) -> ApprovalNotice:
    fields = step.get("fields", {})
    if not isinstance(fields, dict):
        fields = {}
    merged = dict(fields)
    for key in (
        "choice",
        "command",
        "decided_by",
        "description",
        "pattern_key",
        "pattern_keys",
        "session_id",
        "session_key",
        "surface",
        "tool_call_id",
        "turn_id",
    ):
        if key in step:
            merged[key] = step[key]
    if "session" in step and "session_id" not in merged:
        merged["session_id"] = step["session"]
    keys = merged.get("pattern_keys", ())
    if not isinstance(keys, list):
        keys = ()
    choice = merged.get("choice")
    decided = merged.get("decided_by")
    return ApprovalNotice(
        command=str(merged.get("command", "")) if isinstance(merged.get("command"), str) else "",
        description=str(merged.get("description", ""))
        if isinstance(merged.get("description"), str)
        else "",
        pattern_key=str(merged.get("pattern_key", ""))
        if isinstance(merged.get("pattern_key"), str)
        else "",
        pattern_keys=tuple(item for item in keys if isinstance(item, str)),
        session_key=str(merged.get("session_key", ""))
        if isinstance(merged.get("session_key"), str)
        else "",
        session_id=str(merged.get("session_id", ""))
        if isinstance(merged.get("session_id"), str)
        else "",
        surface=str(merged.get("surface", "")) if isinstance(merged.get("surface"), str) else "",
        turn_id=str(merged.get("turn_id", "")) if isinstance(merged.get("turn_id"), str) else "",
        tool_call_id=str(merged.get("tool_call_id", ""))
        if isinstance(merged.get("tool_call_id"), str)
        else "",
        choice=choice if isinstance(choice, str) else None,
        decided_by=decided if isinstance(decided, str) else None,
        coalesced=merged.get("coalesced") is True,
    )


def _session_of(step: dict[str, Any]) -> str | None:
    kind = step.get("do")
    if kind in ("subagent_start", "subagent_stop"):
        child = step.get("child")
        return child if isinstance(child, str) and child else None
    session = step.get("session")
    if isinstance(session, str) and session:
        return session
    return None


def _decision_from_call(returned: Any) -> dict[str, Any]:
    if isinstance(returned, Allow) or returned is None:
        return {"action": "allow"}
    if isinstance(returned, Approve):
        decision: dict[str, Any] = {"action": "approve", "message": returned.message}
        if returned.rule_key:
            decision["rule_key"] = returned.rule_key
        return decision
    if isinstance(returned, Block):
        return {"action": "block", "message": returned.message}
    return {"action": "block", "message": str(returned)}


def _decision_from_result(returned: Any, original: Any) -> dict[str, Any]:
    if returned is None:
        return {"action": "unchanged"}
    if not isinstance(returned, str):
        return {"action": "annotate", "result": returned}
    if isinstance(original, str) and original and returned.endswith(original):
        head = returned[: -len(original)]
        if head.endswith("\n\n"):
            notice = head[:-2]
            if notice:
                return {"action": "annotate", "result": {"body": "input", "notice": notice}}
    if len(returned) > _RESULT_COMPACT_AT:
        return {"action": "annotate", "result": {"head": returned[:200], "length": len(returned)}}
    return {"action": "annotate", "result": returned}


def _scrub_decision(
    decision: dict[str, Any] | None, *, homes: list[str], configs: list[str]
) -> dict[str, Any] | None:
    if decision is None:
        return None
    scrubbed: dict[str, Any] = {}
    for key, value in decision.items():
        if isinstance(value, str):
            scrubbed[key] = scrub_known(value, homes=homes, configs=configs)
        elif isinstance(value, dict):
            scrubbed[key] = {
                item_key: scrub_known(item, homes=homes, configs=configs)
                if isinstance(item, str)
                else item
                for item_key, item in value.items()
            }
        else:
            scrubbed[key] = value
    return scrubbed


def _read_spool(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    if not path.is_file():
        return [], offset
    data = path.read_bytes()
    if len(data) <= offset:
        return [], offset
    chunk = data[offset:]
    newline = chunk.rfind(b"\n")
    if newline < 0:
        return [], offset
    import json

    events: list[dict[str, Any]] = []
    for raw in chunk[: newline + 1].split(b"\n"):
        if not raw.strip():
            continue
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            events.append(parsed)
    return events, offset + newline + 1
