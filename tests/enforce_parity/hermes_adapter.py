"""Replay a scenario through ``petasos.hermes.plugin.register`` and its hooks.

The Hermes context and the host modules are fakes. The enforcer, the settings
source, and the hook callbacks are the ones the plugin registers. Flat
scenario settings are presented as the four Hermes settings, with the same
scanner and anonymization adjustments the enforcer oracle applies, so the
decision record stays comparable.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

from petasos.config.layers import resolve
from petasos.config.migrate import migrate
from petasos.config.schema import leaves, to_mapping
from petasos.config.sections import PetasosConfig
from petasos.enforce import Enforcer, EvaluationFault, InitGate, ManualClock
from petasos.hermes import plugin as plugin_mod
from tests.enforce_parity.enforcer_adapter import _read_spool, _StubScanner, snapshot_from_section
from tests.enforce_parity.load import bind_paths, scrub_event, scrub_known

_ISOLATED_ENV = (
    "HERMES_HOME",
    "HERMES_YOLO_MODE",
    "PETASOS_AUDIT_FINDING",
    "PETASOS_HASH_KEY",
    "PETASOS_LICENSE_KEY",
    "PETASOS_SESSION_SECRET",
)
_HOST_MODULES = (
    "agent",
    "agent.redact",
    "hermes_cli",
    "hermes_cli.config",
    "hermes_cli.plugins",
    "tools",
    "tools.approval",
    "yaml",
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


class _Ctx:
    """The Hermes context methods ``register`` calls, over an in-memory store."""

    def __init__(self, *, subagent: bool) -> None:
        self.subagent = subagent
        self.values: dict[str, Any] = {}
        self.hooks: dict[str, list[Any]] = {}
        self.broken = False

    def get_config(self, key: str, default: object = None) -> object:
        if self.broken:
            raise RuntimeError("malformed settings")
        if key in self.values:
            return self.values[key]
        return default

    def register_hook(self, name: str, handler: Any) -> None:
        if not self.subagent and name in ("subagent_start", "subagent_stop"):
            raise RuntimeError(f"hook {name} is not available")
        self.hooks.setdefault(name, []).append(handler)

    def call(self, name: str, *args: object, **kwargs: object) -> Any:
        handlers = self.hooks.get(name, [])
        if not handlers:
            return None
        return handlers[0](*args, **kwargs)


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


def _settings(scenario: dict[str, Any]) -> dict[str, Any]:
    raw = scenario.get("settings", {})
    if not isinstance(raw, dict):
        raise TypeError("settings must be an object")
    return dict(raw)


def _dig(doc: object, path: str) -> object:
    node = doc
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _put(doc: dict[str, Any], path: str, value: object) -> None:
    parts = path.split(".")
    node = doc
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def _overrides_matching(role: str, level: str, target: PetasosConfig) -> dict[str, Any]:
    """Overrides that make ``resolve`` reproduce ``target``."""
    base = resolve({"role": role, "level": level, "overrides": {}}).config
    base_map = to_mapping(base)
    target_map = to_mapping(target)
    overrides: dict[str, Any] = {}
    for info in leaves(PetasosConfig):
        left = _dig(base_map, info.path)
        right = _dig(target_map, info.path)
        if left != right:
            _put(overrides, info.path, right)
    return overrides


def settings_document(section: dict[str, Any]) -> dict[str, Any]:
    """The four Hermes settings whose resolution matches the enforcer snapshot."""
    migrated = migrate(section)
    raw = migrated.settings
    document = {
        "enabled": raw.get("enabled", True),
        "role": raw.get("role", "general"),
        "level": raw.get("level", "balanced"),
        "overrides": dict(raw.get("overrides", {})),
    }
    try:
        resolve(document)
    except Exception:
        return document
    snap = snapshot_from_section(section, 1)
    if snap.config is None:
        return document
    document["overrides"] = _overrides_matching(
        str(document["role"]), str(document["level"]), snap.config
    )
    resolved = resolve(document).config
    if resolved != snap.config:
        raise RuntimeError("Hermes settings did not resolve to the enforcer snapshot")
    return document


def _env_from(section: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    secret = section.get("session_secret")
    if isinstance(secret, str) and secret:
        env["PETASOS_SESSION_SECRET"] = secret
    hash_key = section.get("hash_key")
    if isinstance(hash_key, str) and hash_key:
        env["PETASOS_HASH_KEY"] = hash_key
    return env


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


class HermesOracle:
    """Replay one scenario through the registered Hermes hooks."""

    def replay(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        """Run ``scenario`` against a temporary home and return its outcomes."""
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise TypeError("scenario id must be a non-empty string")
        home_dir = Path(tempfile.mkdtemp(prefix="petasos-hermes-parity-"))
        try:
            return _Runner(scenario, home_dir).run()
        finally:
            shutil.rmtree(home_dir, ignore_errors=True)


class _Runner:
    """One scenario. Host modules and the enforcer class are restored on the way out."""

    def __init__(self, scenario: dict[str, Any], home: Path) -> None:
        self.scenario = scenario
        self.home = home.resolve()
        self.config_path = self.home / "config.yaml"
        self.spool_path = self.home / "petasos-enforcement.jsonl"
        self.host = _host_view(scenario)
        self.ctx = _Ctx(subagent=bool(self.host["subagent_hooks"]))
        self.homes: list[str] = []
        self.configs: list[str] = []
        self._offset = 0
        self._section: dict[str, Any] = {}
        self._env: dict[str, str] = {}
        self._handler = _LogCapture()
        self._saved_modules: dict[str, Any] = {}
        self._saved_env: dict[str, str | None] = {}
        self._saved_enforcer: Any = None
        self._clock = ManualClock(monotonic=_CLOCK_ORIGIN, wall=_CLOCK_ORIGIN)
        self._fault = EvaluationFault()
        self._gate: InitGate | None = None

    def run(self) -> list[dict[str, Any]]:
        """Register the plugin, run every step, and restore process globals."""
        self._remember(self.home, self.config_path)
        self._isolate_env()
        self._install_host()
        logger = logging.getLogger("petasos")
        saved_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(self._handler)
        try:
            self._section = _settings(self.scenario)
            self._publish()
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
            plugin_mod.close()
            logger.removeHandler(self._handler)
            logger.setLevel(saved_level)
            if self._saved_enforcer is not None:
                plugin_mod.Enforcer = self._saved_enforcer  # type: ignore[attr-defined]
            for name in _ISOLATED_ENV:
                os.environ.pop(name, None)
                saved = self._saved_env.get(name)
                if saved is not None:
                    os.environ[name] = saved
            for name, module in self._saved_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

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

    def _install_host(self) -> None:
        for name in _HOST_MODULES:
            self._saved_modules[name] = sys.modules.get(name)
        hooks = {
            "on_session_start",
            "post_approval_response",
            "post_tool_call",
            "pre_approval_request",
            "pre_tool_call",
            "transform_tool_result",
        }
        if self.host["subagent_hooks"]:
            hooks.update({"subagent_start", "subagent_stop"})
        plugins = types.ModuleType("hermes_cli.plugins")
        plugins.VALID_HOOKS = frozenset(hooks)  # type: ignore[attr-defined]
        if self.host["approve_directive"]:
            plugins.get_pre_tool_call_directive = lambda value=None: "approve"  # type: ignore[attr-defined]
        cli = types.ModuleType("hermes_cli")
        cli.plugins = plugins  # type: ignore[attr-defined]
        config = types.ModuleType("hermes_cli.config")

        def get_env_value(name: str) -> str | None:
            value = self._env.get(name)
            return value if value else None

        config.get_env_value = get_env_value  # type: ignore[attr-defined]
        config.load_config = lambda: {"approvals": {"mode": "smart"}}  # type: ignore[attr-defined]
        config.save_env_value = lambda name, value: self._env.__setitem__(name, value)  # type: ignore[attr-defined]
        cli.config = config  # type: ignore[attr-defined]
        sys.modules["hermes_cli"] = cli
        sys.modules["hermes_cli.plugins"] = plugins
        sys.modules["hermes_cli.config"] = config

        always = {f"plugin_rule:{rule}" for rule in self.host["always_approved"]}
        approval = types.ModuleType("tools.approval")
        approval.is_approved = lambda _command, pattern: pattern in always  # type: ignore[attr-defined]
        approval._yolo_active = lambda: bool(self.host["auto_approve"])  # type: ignore[attr-defined]
        approval._get_approval_mode = lambda: "smart"  # type: ignore[attr-defined]
        tools = types.ModuleType("tools")
        tools.approval = approval  # type: ignore[attr-defined]
        sys.modules["tools"] = tools
        sys.modules["tools.approval"] = approval
        self._install_redactor()

    def _install_redactor(self) -> None:
        redactor = self.host["redactor"]
        if redactor == "unavailable":
            sys.modules.pop("agent", None)
            sys.modules.pop("agent.redact", None)
            return
        masks: list[str] = []
        if isinstance(redactor, dict):
            raw = redactor.get("mask", [])
            if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                raise TypeError("redactor.mask must be a list of strings")
            masks = raw
        elif redactor != "identity":
            raise TypeError("redactor must be identity, unavailable, or {mask: [...]}")

        def redact_sensitive_text(text: str, **_options: Any) -> str:
            masked = text
            for needle in masks:
                masked = masked.replace(needle, "[masked]")
            return masked

        agent = types.ModuleType("agent")
        redact = types.ModuleType("agent.redact")
        redact.redact_sensitive_text = redact_sensitive_text  # type: ignore[attr-defined]
        agent.redact = redact  # type: ignore[attr-defined]
        sys.modules["agent"] = agent
        sys.modules["agent.redact"] = redact

    def _publish(self) -> None:
        self.ctx.broken = False
        self.ctx.values = settings_document(self._section)
        self._env = _env_from(self._section)

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
        real = plugin_mod.Enforcer  # type: ignore[attr-defined]
        self._saved_enforcer = real
        clock = self._clock
        fault = self._fault
        scanners = tuple(_stubs(self.scenario))
        spool = str(self.spool_path)

        def factory(
            source: Any,
            *,
            host: Any,
            spool_path: str | None = None,
            **_kwargs: Any,
        ) -> Any:
            del spool_path
            return real(
                source,
                host=host,
                spool_path=spool,
                clock=clock,
                scanners=scanners,
                init=gate,
                evaluation=fault,
            )

        plugin_mod.Enforcer = factory  # type: ignore[attr-defined, assignment]
        plugin_mod.register(self.ctx)
        enforcer = _enforcer()
        if state != "starting" and enforcer is not None and not enforcer.settle(30):
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
        kind = step.get("do")
        if kind == "tool_call":
            return _decision_from_call(self._tool_call(step))
        if kind == "tool_result":
            return _decision_from_result(self._tool_result(step), step.get("result"))
        if kind == "tool_finished":
            self._tool_finished(step)
            return None
        if kind == "session_start":
            self.ctx.call("on_session_start", session_id=str(step.get("session", "")))
            return None
        if kind == "subagent_start":
            self.ctx.call(
                "subagent_start",
                parent_session_id=str(step.get("parent", "")),
                child_session_id=str(step.get("child", "")),
            )
            return None
        if kind == "subagent_stop":
            self.ctx.call("subagent_stop", child_session_id=str(step.get("child", "")))
            return None
        if kind == "approval_request":
            self.ctx.call("pre_approval_request", **_approval_fields(step))
            return None
        if kind == "approval_answer":
            self.ctx.call("post_approval_response", **_approval_fields(step))
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
            enforcer = _enforcer()
            if enforcer is not None:
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

    def _tool_call(self, step: dict[str, Any]) -> Any:
        args = step.get("args", {})
        if not isinstance(args, dict):
            raise TypeError("tool_call args must be an object")
        kwargs: dict[str, Any] = {}
        if "turn_id" in step:
            kwargs["turn_id"] = step["turn_id"]
        if "tool_call_id" in step:
            kwargs["tool_call_id"] = step["tool_call_id"]
        if "hermes_session" in step:
            kwargs["session_id"] = step["hermes_session"]
        return self.ctx.call(
            "pre_tool_call",
            tool_name=str(step.get("tool", "")),
            args=args,
            task_id=str(step.get("session", "")),
            **kwargs,
        )

    def _tool_result(self, step: dict[str, Any]) -> Any:
        return self.ctx.call(
            "transform_tool_result",
            tool_name=str(step.get("tool", "")),
            result=step.get("result", ""),
            task_id=str(step.get("session", "")),
        )

    def _tool_finished(self, step: dict[str, Any]) -> None:
        result = step.get("result", "")
        if not isinstance(result, str):
            result = "" if result is None else str(result)
        self.ctx.call(
            "post_tool_call",
            tool_name=str(step.get("tool", "")),
            args=step.get("args") if isinstance(step.get("args"), dict) else {},
            result=result,
            task_id=str(step.get("session", "")),
            duration_ms=0,
        )

    def _apply_settings(self, step: dict[str, Any]) -> None:
        raw = step.get("raw")
        if isinstance(raw, str):
            self.ctx.broken = True
            return
        patch = step.get("set", {})
        if not isinstance(patch, dict):
            raise TypeError("settings set must be an object")
        self._section.update(patch)
        self._publish()

    def _profile_change(self, step: dict[str, Any]) -> None:
        """Apply settings the way this host exposes them: on the active context.

        Hermes has no profile-change hook. The old handler was only reached by
        calling it directly, so its log lines are not reproduced. A step that
        names a home and no settings, or a home that is not a directory the
        process is serving, changes nothing. A step that carries settings is
        the active profile's new settings. ``refresh`` applies them on this
        step, which is where a restart-only change is logged.
        """
        given = step.get("home")
        if isinstance(given, str):
            return
        section = step.get("settings", {})
        if not isinstance(section, dict):
            raise TypeError("profile settings must be an object")
        if not section:
            return
        self._section = dict(section)
        self._publish()
        enforcer = _enforcer()
        if enforcer is not None:
            enforcer.refresh()

    def _tier(self, session: str | None) -> str | None:
        if not session:
            return None
        enforcer = _enforcer()
        if enforcer is None:
            return None
        return enforcer.session_tier(session)


def _enforcer() -> Enforcer | None:
    regs = getattr(plugin_mod, "_registrations", None)
    if not isinstance(regs, dict) or len(regs) != 1:
        return None
    reg = next(iter(regs.values()))
    enforcer = getattr(reg, "enforcer", None)
    if isinstance(enforcer, Enforcer):
        return enforcer
    return None


def _session_of(step: dict[str, Any]) -> str | None:
    kind = step.get("do")
    if kind in ("subagent_start", "subagent_stop"):
        child = step.get("child")
        return child if isinstance(child, str) and child else None
    session = step.get("session")
    if isinstance(session, str) and session:
        return session
    return None


def _approval_fields(step: dict[str, Any]) -> dict[str, Any]:
    fields = step.get("fields", {})
    if not isinstance(fields, dict):
        fields = {}
    payload = dict(fields)
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
            payload[key] = step[key]
    if "session" in step and "session_id" not in payload:
        payload["session_id"] = step["session"]
    return payload


def _decision_from_call(returned: Any) -> dict[str, Any]:
    if returned is None:
        return {"action": "allow"}
    if not isinstance(returned, dict):
        return {"action": "block", "message": str(returned)}
    action = returned.get("action")
    message = returned.get("message")
    if action == "approve":
        decision: dict[str, Any] = {"action": "approve"}
        if message is not None:
            decision["message"] = message
        rule_key = returned.get("rule_key")
        if rule_key:
            decision["rule_key"] = rule_key
        return decision
    if action == "block":
        decision = {"action": "block"}
        if message is not None:
            decision["message"] = message
        return decision
    return {"action": str(action), "message": message}


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
