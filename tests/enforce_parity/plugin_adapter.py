"""The only enforcement-oracle module that loads the reference plugin.

``PluginOracle.replay`` stands up a fresh copy of the plugin against a
temporary Hermes home, drives the scenario's steps through the plugin's
hook callbacks, and returns outcomes in the recorded shape. A later
``Enforcer`` adapter implements the same :class:`EnforcementAdapter`
method without importing this module.

Reaching into the plugin is limited to putting it in a starting lifecycle
the hooks cannot reach on their own, reading the session tier, and opening
a rate-limit window the plugin already exposes. Each of those is named in
the README.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any

import yaml

from tests.enforce_parity.load import bind_paths, scrub_event, scrub_known

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)
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
    "hermes_cli.plugins",
    "hermes_constants",
    "tools",
    "tools.approval",
)
_RESULT_COMPACT_AT = 400
_LOADS = 0


class _HostCtx:
    """The slice of a Hermes plugin context ``register`` actually calls."""

    def __init__(self, *, subagent: bool) -> None:
        self.subagent = subagent
        self.hooks: dict[str, list[Any]] = {}

    def register_hook(self, name: str, handler: Any) -> None:
        """Store ``handler``, or reject a sub-agent hook the host does not have."""
        if not self.subagent and name in ("subagent_start", "subagent_stop"):
            raise RuntimeError(f"hook {name} is not available")
        self.hooks.setdefault(name, []).append(handler)


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
        from petasos._types import ScanFinding, ScanResult, Severity

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


def _load_plugin(scenario_id: str) -> Any:
    """Import a new copy of the reference plugin. Copies do not share globals."""
    global _LOADS
    _LOADS += 1
    safe = "".join(ch if ch.isalnum() else "_" for ch in scenario_id)
    name = f"petasos_enforce_parity_{safe}_{_LOADS}"
    spec = importlib.util.spec_from_file_location(name, _PLUGIN_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the reference plugin from {_PLUGIN_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


class PluginOracle:
    """Replay a scenario through one freshly loaded reference plugin."""

    def replay(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        """Run ``scenario`` in its own temporary home and return its outcomes."""
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise TypeError("scenario id must be a non-empty string")
        home_dir = Path(tempfile.mkdtemp(prefix="petasos-enforce-parity-"))
        try:
            return _Runner(scenario, home_dir).run()
        finally:
            shutil.rmtree(home_dir, ignore_errors=True)


class _Runner:
    """One scenario. Everything it mutates is restored on the way out."""

    def __init__(self, scenario: dict[str, Any], home: Path) -> None:
        self.scenario = scenario
        self.home = home.resolve()
        self.config_path = self.home / "config.yaml"
        self.spool_path = home / "petasos-enforcement.jsonl"
        self.host = _host_view(scenario)
        self.ref: Any = None
        self.homes: list[str] = []
        self.configs: list[str] = []
        self._stamp = time.time_ns()
        self._offset = 0
        self._fault: str | None = None
        self._run_async: Any = None
        self._handler = _LogCapture()
        self._saved_modules: dict[str, Any] = {}
        self._saved_env: dict[str, str | None] = {}
        self._saved_root: Any = None
        self._saved_spool: str | None = None
        self._saved_level = logging.NOTSET
        self._plugin_name = ""

    def run(self) -> list[dict[str, Any]]:
        """Boot the plugin, run every step, and restore process globals."""
        self._remember_paths(self.home, self.config_path)
        self.ref = _load_plugin(str(self.scenario["id"]))
        self._plugin_name = self.ref.__name__
        self._install_host()
        self._isolate_env()
        self._isolate_spool_and_root()
        logger = logging.getLogger("petasos")
        self._saved_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(self._handler)
        try:
            self._write_settings(_settings(self.scenario))
            self._boot()
            self._install_scanners()
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
            self._restore()

    def _remember_paths(self, home: Path, config: Path) -> None:
        for path in (home, config):
            text = str(path)
            resolved = str(path.resolve())
            bucket = self.configs if path == config else self.homes
            for item in (text, resolved):
                if item not in bucket:
                    bucket.append(item)

    def _install_host(self) -> None:
        """Publish the host modules the plugin probes, and nothing else."""
        for name in _HOST_MODULES:
            self._saved_modules[name] = sys.modules.get(name)
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home_override = lambda: None  # type: ignore[attr-defined]
        sys.modules["hermes_constants"] = constants

        plugins = types.ModuleType("hermes_cli.plugins")
        plugins.VALID_HOOKS = frozenset(  # type: ignore[attr-defined]
            {
                "on_profile_change",
                "on_session_start",
                "post_approval_response",
                "post_tool_call",
                "pre_approval_request",
                "pre_tool_call",
                "subagent_start",
                "subagent_stop",
                "transform_tool_result",
            }
        )
        plugins.has_hook = lambda _name: False  # type: ignore[attr-defined]
        if self.host["approve_directive"]:
            plugins.get_pre_tool_call_directive = lambda: "approve"  # type: ignore[attr-defined]
        cli = types.ModuleType("hermes_cli")
        cli.plugins = plugins  # type: ignore[attr-defined]
        sys.modules["hermes_cli"] = cli
        sys.modules["hermes_cli.plugins"] = plugins

        approval = types.ModuleType("tools.approval")
        always = {f"plugin_rule:{rule}" for rule in self.host["always_approved"]}
        approval._is_permanently_approved = lambda key: key in always  # type: ignore[attr-defined]
        approval.is_current_session_yolo_enabled = lambda: bool(  # type: ignore[attr-defined]
            self.host["auto_approve"]
        )
        tools = types.ModuleType("tools")
        tools.approval = approval  # type: ignore[attr-defined]
        sys.modules["tools"] = tools
        sys.modules["tools.approval"] = approval

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

    def _isolate_env(self) -> None:
        for name in _ISOLATED_ENV:
            self._saved_env[name] = os.environ.pop(name, None)
        os.environ["HERMES_HOME"] = str(self.home)
        if self.host["auto_approve"]:
            os.environ["HERMES_YOLO_MODE"] = "1"

    def _isolate_spool_and_root(self) -> None:
        import petasos.console._armed as armed
        import petasos.console._reload as reload
        import petasos.enforce.events as events
        import petasos.hermes.home as paths

        armed._reset_armed_cache()
        reload._reset_reload_cache()
        self._saved_root = paths.hermes_root
        # selfmod path discovery calls hermes_root() and lists its profiles.
        # Point that at the temporary home so a real ~/.hermes is never read.
        paths.hermes_root = lambda: self.home
        self._saved_spool = paths._SPOOL_PATH_OVERRIDE
        events._reset_events_state(str(self.spool_path))

    def _restore(self) -> None:
        logger = logging.getLogger("petasos")
        logger.removeHandler(self._handler)
        logger.setLevel(self._saved_level)
        if self._saved_root is not None:
            import petasos.hermes.home as paths

            paths.hermes_root = self._saved_root
        if self.ref is not None:
            self._stop_loops()
        try:
            import petasos.console._armed as armed
            import petasos.console._reload as reload
            import petasos.enforce.events as events

            events._reset_events_state(self._saved_spool)
            armed._reset_armed_cache()
            reload._reset_reload_cache()
        except Exception:
            pass
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
        if self._plugin_name:
            sys.modules.pop(self._plugin_name, None)

    def _stop_loops(self) -> None:
        ref = self.ref
        for loop_name, thread_name in (
            ("_async_loop", "_async_thread"),
            ("_ingest_loop", "_ingest_thread"),
        ):
            loop = getattr(ref, loop_name, None)
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
            thread = getattr(ref, thread_name, None)
            if thread is not None and thread.is_alive():
                thread.join(timeout=1.0)

    def _boot(self) -> None:
        state, error = _lifecycle(self.scenario)
        ref = self.ref
        if state == "ready":
            ref.register(_HostCtx(subagent=bool(self.host["subagent_hooks"])))
            if not ref._init_done.wait(30):
                raise RuntimeError("plugin init did not finish")
            if not ref._initialized:
                raise RuntimeError(f"plugin init failed: {ref._init_error}")
            return
        if state not in ("starting", "failed"):
            raise ValueError(f"unknown lifecycle {state!r}")
        # The hooks cannot park a process in 'still starting' or 'init failed'
        # without the background init either finishing or never having been
        # asked. These are the flags _ensure_initialized already consults.
        from petasos.hermes.home import HermesConfigResolution

        ref._session_resolution = HermesConfigResolution(path=self.config_path, tier="hermes_home")
        ref._config = ref._load_config(ref._session_resolution)
        ref._init_thread_started = True
        ref._initialized = False
        ref._approve_directive_available = bool(self.host["approve_directive"])
        ref._subagent_hooks_available = bool(self.host["subagent_hooks"])
        if state == "starting":
            # The budget is marked spent so a step does not block on the
            # real wait. The decision is the one the cold window makes after
            # that wait returns with init still unfinished.
            ref._init_error = None
            ref._init_wait_expired = True
            return
        ref._init_error = error or "initialization failed"
        ref._init_done.set()

    def _install_scanners(self) -> None:
        pipeline = getattr(self.ref, "_pipeline", None)
        if pipeline is None:
            return
        specs = self.scenario.get("scanners", [])
        if not isinstance(specs, list):
            raise TypeError("scanners must be a list")
        present = {getattr(scanner, "name", "") for scanner in pipeline._ml_scanners}
        for spec in specs:
            if not isinstance(spec, dict):
                raise TypeError("scanner must be an object")
            stub = _StubScanner(spec)
            if stub.name in present:
                continue
            pipeline._ml_scanners.append(stub)
            present.add(stub.name)

    def _arm_fault(self, kind: str) -> None:
        """Make later evaluations raise, or never return.

        A scanner fault does not escape ``ToolCallGuard.evaluate``. The
        evaluation-failure arm only runs when that call raises. The outer
        wait is 15s and has no setting, so a timeout fault also shortens
        that wait; the exception the hook sees is the same class.
        """
        self._fault = kind
        guard = getattr(self.ref, "_guard", None)
        if guard is None:
            return

        async def fail(_tool_name: str, _tool_params: dict[str, Any], _session_id: str) -> Any:
            raise RuntimeError("guard evaluation failed")

        async def hang(_tool_name: str, _tool_params: dict[str, Any], _session_id: str) -> Any:
            await asyncio.Event().wait()

        guard.evaluate = hang if kind == "timeout" else fail
        if kind != "timeout" or self._run_async is not None:
            return
        real = self.ref._run_async

        def bounded(coro: Any, timeout: float = 15) -> Any:
            return real(coro, timeout=0.05)

        self._run_async = real
        self.ref._run_async = bounded

    def _write_settings(self, section: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump({"petasos": section}, sort_keys=True)
        self.config_path.write_text(text, encoding="utf-8")
        self._touch(self.config_path)

    def _touch(self, path: Path) -> None:
        self._stamp += 1_000_000
        os.utime(path, ns=(self._stamp, self._stamp))

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
            self.ref._on_session_start(session_id=step.get("session", ""))
            return None
        if kind == "subagent_start":
            self.ref._subagent_start(
                parent_session_id=str(step.get("parent", "")),
                child_session_id=str(step.get("child", "")),
            )
            return None
        if kind == "subagent_stop":
            self.ref._subagent_stop(child_session_id=str(step.get("child", "")))
            return None
        if kind == "approval_request":
            self.ref._pre_approval_request(**_approval_fields(step))
            return None
        if kind == "approval_answer":
            self.ref._post_approval_response(**_approval_fields(step))
            return None
        if kind == "settings":
            self._apply_settings(step)
            return None
        if kind == "arm":
            self._set_armed(bool(step.get("armed", True)))
            return None
        if kind == "init_complete":
            self.ref._deferred_init()
            self._install_scanners()
            if self._fault is not None:
                self._arm_fault(self._fault)
            return None
        if kind == "evaluation_fault":
            fault = step.get("kind")
            if fault not in ("error", "timeout"):
                raise ValueError("evaluation_fault kind must be error or timeout")
            self._arm_fault(str(fault))
            return None
        if kind == "open_log_window":
            self._open_window(str(step.get("clock", "")))
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
        return self.ref._pre_tool_call(
            step.get("tool", ""),
            args,
            task_id=str(step.get("session", "")),
            **kwargs,
        )

    def _tool_result(self, step: dict[str, Any]) -> Any:
        return self.ref._transform_tool_result(
            tool_name=str(step.get("tool", "")),
            result=step.get("result", ""),
            task_id=str(step.get("session", "")),
        )

    def _tool_finished(self, step: dict[str, Any]) -> None:
        args = step.get("args", {})
        if not isinstance(args, dict):
            args = {}
        result = step.get("result", "")
        if not isinstance(result, str):
            result = "" if result is None else str(result)
        self.ref._post_tool_call(
            str(step.get("tool", "")),
            args,
            result,
            task_id=str(step.get("session", "")),
            duration_ms=0,
        )

    def _apply_settings(self, step: dict[str, Any]) -> None:
        raw = step.get("raw")
        if isinstance(raw, str):
            self.config_path.write_text(raw, encoding="utf-8")
            self._touch(self.config_path)
            return
        patch = step.get("set", {})
        if not isinstance(patch, dict):
            raise TypeError("settings set must be an object")
        current = self._read_section()
        current.update(patch)
        self._write_settings(current)

    def _set_armed(self, armed: bool) -> None:
        current = self._read_section()
        current["enabled"] = armed
        self._write_settings(current)

    def _read_section(self) -> dict[str, Any]:
        if not self.config_path.is_file():
            return {}
        try:
            loaded = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if isinstance(loaded, dict) and isinstance(loaded.get("petasos"), dict):
            return dict(loaded["petasos"])
        return {}

    def _profile_change(self, step: dict[str, Any]) -> None:
        name = str(step.get("name", ""))
        given = step.get("home")
        if isinstance(given, str):
            target = given
        else:
            profile_home = self.home / "profiles" / (name or "unnamed")
            profile_home.mkdir(parents=True, exist_ok=True)
            section = step.get("settings", {})
            if not isinstance(section, dict):
                raise TypeError("profile settings must be an object")
            config = profile_home / "config.yaml"
            config.write_text(
                yaml.safe_dump({"petasos": section}, sort_keys=True), encoding="utf-8"
            )
            self._touch(config)
            target = str(profile_home)
        self.ref._on_profile_change(profile_name=name, profile_home=target)
        # The hook schedules the apply and returns. A yield on the same loop
        # runs after that apply's commit callback.
        self.ref._run_async(_yield_once())

    def _open_window(self, clock: str) -> None:
        ref = self.ref
        if clock == "disarm":
            ref._reset_disarm_log()
        elif clock == "ingest":
            ref._reset_ingest_unscanned_log()
        elif clock == "reload":
            ref._reset_reload_logs()
        elif clock == "rebind":
            ref._reset_rebind_log()
        else:
            raise ValueError(f"unknown log clock {clock!r}")

    def _tier(self, session: str | None) -> str | None:
        if not session:
            return None
        guard = getattr(self.ref, "_guard", None)
        if guard is None:
            return None
        try:
            tier = guard._derive_tier(session)
        except Exception:
            return None
        if not isinstance(tier, str):
            return None
        return tier


def _yield_once() -> Any:
    async def _once() -> None:
        await asyncio.sleep(0)

    return _once()


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
        raise TypeError("approval fields must be an object")
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
        return {
            "action": "annotate",
            "result": {"head": returned[:200], "length": len(returned)},
        }
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
    events: list[dict[str, Any]] = []
    for raw in chunk[: newline + 1].split(b"\n"):
        if not raw.strip():
            continue
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            events.append(parsed)
    return events, offset + newline + 1
