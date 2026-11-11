"""The Hermes modules the adapter calls.

Every Hermes import in this package goes through ``load_module``. A missing
module returns ``None``; callers treat that as "this fact is unavailable".
"""

from __future__ import annotations

import importlib
import os
from typing import Protocol, cast

from petasos.enforce.types import ApprovalGrant

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_MODES = frozenset({"off", "smart", "manual"})
# Platforms Hermes treats as an unattended session. Checked against v0.23.1.
_UNATTENDED_PLATFORMS = frozenset({"api_server", "webhook"})


class _Plugins(Protocol):
    VALID_HOOKS: object

    def get_pre_tool_call_directive(self, value: object = None) -> object: ...


class _Approval(Protocol):
    def is_approved(self, command: str, pattern: str) -> bool: ...

    def _get_approval_mode(self) -> str: ...

    def _yolo_active(self) -> bool: ...


class _Config(Protocol):
    def get_env_value(self, name: str) -> str | None: ...

    def save_env_value(self, name: str, value: str) -> None: ...

    def load_config(self) -> dict[str, object]: ...


class _PluginSettings(Protocol):
    def save_plugin_settings(
        self, plugin_id: str, manifest_path: object, values: object
    ) -> None: ...


class _Redact(Protocol):
    def redact_sensitive_text(self, text: str, **options: object) -> str: ...


def load_module(name: str) -> object | None:
    """Import ``name``. ``None`` when the module is absent or raises."""
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _plugins() -> _Plugins | None:
    module = load_module("hermes_cli.plugins")
    if module is None:
        return None
    return cast("_Plugins", module)


def _approval() -> _Approval | None:
    module = load_module("tools.approval")
    if module is None:
        return None
    return cast("_Approval", module)


def _config() -> _Config | None:
    module = load_module("hermes_cli.config")
    if module is None:
        return None
    return cast("_Config", module)


def _settings_writer() -> _PluginSettings | None:
    module = load_module("hermes_cli.plugins_settings")
    if module is None:
        return None
    return cast("_PluginSettings", module)


def _redact() -> _Redact | None:
    module = load_module("agent.redact")
    if module is None:
        return None
    return cast("_Redact", module)


def approve_directive_available() -> bool:
    """True when this Hermes build can route an approve directive."""
    module = _plugins()
    if module is None:
        return False
    return callable(getattr(module, "get_pre_tool_call_directive", None))


def subagent_hooks_available() -> bool:
    """True when this build's hook table includes both sub-agent hooks."""
    module = _plugins()
    if module is None:
        return False
    hooks = getattr(module, "VALID_HOOKS", None)
    try:
        return hooks is not None and "subagent_start" in hooks and "subagent_stop" in hooks
    except Exception:
        return False


def load_redactor() -> object | None:
    """Hermes's redactor, or ``None`` when that module is absent."""
    module = _redact()
    if module is None:
        return None
    fn = getattr(module, "redact_sensitive_text", None)
    return fn if callable(fn) else None


def _approvals() -> dict[str, object]:
    module = _config()
    if module is None:
        return {}
    try:
        document = module.load_config()
    except Exception:
        return {}
    if not isinstance(document, dict):
        return {}
    block = document.get("approvals")
    if not isinstance(block, dict):
        return {}
    return {str(key): value for key, value in block.items()}


def _approval_mode() -> str:
    """The normalised mode: ``off``, ``smart``, or ``manual``."""
    module = _approval()
    if module is not None:
        try:
            raw = module._get_approval_mode()
        except Exception:
            raw = None
        if raw in _MODES:
            return str(raw)
    configured = _approvals().get("mode", "smart")
    if configured == "off" or configured == "smart":
        return str(configured)
    return "manual"


def _yolo() -> bool:
    """True when Hermes would grant a tool call without asking."""
    module = _approval()
    if module is not None:
        try:
            return bool(module._yolo_active())
        except Exception:
            return False
    return os.environ.get("HERMES_YOLO_MODE", "").strip().lower() in _TRUTHY


def _context_grants() -> bool:
    """True when the active unattended context's mode is ``approve``."""
    block = _approvals()
    single = os.environ.get("HERMES_SINGLE_QUERY_SESSION")
    if single and block.get("single_query_mode") == "approve":
        return True
    if os.environ.get("HERMES_CRON_SESSION") and block.get("cron_mode") == "approve":
        return True
    platform = os.environ.get("HERMES_SESSION_PLATFORM", "")
    return platform in _UNATTENDED_PLATFORMS and block.get("unattended_mode") == "approve"


def approval_grant() -> ApprovalGrant:
    """Why an approve would be granted with nobody attached.

    Any one flag means the enforcer must not hand Hermes an approve. When the
    approval module is loaded and a probe raises, the grant is reported as
    yolo so that failure is not turned into an unattended allow.
    """
    if _approval() is None and _config() is None:
        return ApprovalGrant()
    try:
        return ApprovalGrant(
            mode_off=_approval_mode() == "off",
            yolo=_yolo(),
            context=_context_grants(),
        )
    except Exception:
        return ApprovalGrant(yolo=True)


def command_will_be_asked(command: str) -> bool:
    """True when Hermes will put this terminal command to a person.

    False when ``detect_dangerous_command`` cannot be imported, has moved, or
    raises, when it does not flag the command, and when Hermes would approve
    or refuse the command without asking. A hardline command is a refusal.

    Only ``approvals.mode: manual`` is an ask. In ``smart`` mode, which is
    Hermes's default, a model looks at the command first and can approve it
    with nobody asked, and which way it will go is not known here.
    """
    if not isinstance(command, str) or command == "":
        return False
    try:
        return _command_will_be_asked(command)
    except Exception:
        return False


def _command_will_be_asked(command: str) -> bool:
    detection = load_module("tools.approval_detection")
    approval = load_module("tools.approval")
    if detection is None or approval is None:
        return False
    detect = getattr(detection, "detect_dangerous_command", None)
    if not callable(detect):
        return False
    flagged = detect(command)
    if not (isinstance(flagged, tuple) and flagged and flagged[0] is True):
        return False
    env_type, host_access = _terminal_backend()
    skip = getattr(approval, "_should_skip_container_guards", None)
    if not callable(skip) or skip(env_type, has_host_access=host_access):
        return False
    floor = getattr(approval, "_floor_block", None)
    if not callable(floor) or floor(command, sudo_guard=True) is not None:
        return False
    context = load_module("tools.approval_context")
    mode = getattr(context, "_get_approval_mode", None) if context is not None else None
    if not callable(mode):
        return False
    if mode() != "manual":
        return False
    yolo = getattr(approval, "_yolo_active", None)
    if not callable(yolo) or yolo():
        return False
    allowlisted = getattr(approval, "_command_matches_permanent_allowlist", None)
    if not callable(allowlisted) or allowlisted(command):
        return False
    presence = getattr(approval, "_presence", None)
    if not callable(presence):
        return False
    present = presence(None)
    if not isinstance(present, tuple) or len(present) < 4:
        return False
    if not (present[1] or present[2] or present[3]):
        return False
    return not _already_covered(approval, command)


def _terminal_backend() -> tuple[str, bool]:
    """The backend and host-access bit the command gate will use."""
    terminal = load_module("tools.terminal_tool")
    if terminal is None:
        raise RuntimeError("terminal tool is unavailable")
    config_fn = getattr(terminal, "_get_env_config", None)
    access_fn = getattr(terminal, "_docker_has_host_access", None)
    if not callable(config_fn) or not callable(access_fn):
        raise RuntimeError("terminal backend facts moved")
    config = config_fn()
    if not isinstance(config, dict):
        raise RuntimeError("terminal config is not a mapping")
    env_type = config.get("env_type")
    if not isinstance(env_type, str) or env_type == "":
        raise RuntimeError("terminal env type missing")
    return env_type, bool(access_fn(config))


def _already_covered(approval: object, command: str) -> bool:
    """True when Hermes would approve the command from an earlier answer.

    A missing helper answers yes, so the caller does not stand aside.
    """
    findings_fn = getattr(approval, "_command_findings", None)
    pending_fn = getattr(approval, "_pending_findings", None)
    scope_fn = getattr(approval, "_approval_scope", None)
    session_fn = getattr(approval, "get_current_session_key", None)
    if not callable(findings_fn) or not callable(pending_fn):
        return True
    if not callable(scope_fn) or not callable(session_fn):
        return True
    findings = findings_fn(command)
    if not isinstance(findings, list):
        return True
    session_key = session_fn()
    scopes: dict[str, object] = {}
    for item in findings:
        if not isinstance(item, tuple) or not item or not isinstance(item[0], str):
            return True
        scopes[item[0]] = scope_fn(session_key, item[0])
    pending = pending_fn(findings, lambda key: scopes.get(key) is not None)
    return pending is None


def rule_always_approved(rule_key: str) -> bool:
    """True when ``plugin_rule:<rule_key>`` is on the permanent allow-list."""
    module = _approval()
    if module is None:
        return False
    try:
        return bool(module.is_approved("", "plugin_rule:" + rule_key))
    except Exception:
        return False


def read_env(name: str) -> str | None:
    """The profile env value, via Hermes's reader. ``None`` when it is absent."""
    module = _config()
    if module is None:
        return None
    try:
        value = module.get_env_value(name)
    except Exception:
        return None
    if not isinstance(value, str) or value.strip() == "":
        return None
    return value


def save_env(name: str, value: str) -> None:
    """Write one env value through Hermes. Raises when the writer is absent."""
    module = _config()
    if module is None:
        raise RuntimeError("Hermes env writer is not available")
    module.save_env_value(name, value)


def save_plugin_settings(plugin_id: str, manifest: object, values: dict[str, object]) -> None:
    """Write non-secret settings through Hermes's form writer."""
    module = _settings_writer()
    if module is None:
        raise RuntimeError("Hermes settings writer is not available")
    module.save_plugin_settings(plugin_id, manifest, values)


def load_mapping(text: str) -> object:
    """Parse a Hermes config document. ``_BROKEN`` when no loader can read it."""
    for module_name, attr in (
        ("utils", "fast_safe_load"),
        ("hermes_yaml", "safe_load"),
        ("yaml", "safe_load"),
    ):
        module = load_module(module_name)
        fn = getattr(module, attr, None) if module is not None else None
        if not callable(fn):
            continue
        try:
            return fn(text)
        except Exception:
            return _BROKEN
    return _BROKEN


class _Broken:
    """A document that could not be parsed."""


_BROKEN = _Broken()


def managed_keys() -> frozenset[str] | None:
    """Dotted config keys an administrator pinned in Hermes's managed config.

    Read with ``hermes_cli.managed_scope.managed_config_keys`` (Hermes
    ``v0.23.1``). ``None`` when this Hermes has no managed scope module, so a
    caller can tell "nothing is pinned" from "cannot tell".
    """
    module = load_module("hermes_cli.managed_scope")
    if module is None:
        return None
    reader = getattr(module, "managed_config_keys", None)
    if not callable(reader):
        return None
    try:
        keys = reader()
    except Exception:
        return None
    if not isinstance(keys, (set, frozenset, list, tuple)):
        return None
    return frozenset(key for key in keys if isinstance(key, str))


def managed_overlay(document: dict[str, object]) -> dict[str, object]:
    """Apply Hermes's managed overlay to a profile read outside PluginContext."""
    module = load_module("hermes_cli.managed_scope")
    if module is None:
        return document
    apply = getattr(module, "apply_managed_overlay", None)
    if not callable(apply):
        raise RuntimeError("Hermes's managed settings reader is unavailable")
    value = apply(document)
    if not isinstance(value, dict):
        raise RuntimeError("Hermes returned unreadable managed settings")
    return value


def managed_config_path() -> str | None:
    """The managed file is a guardrail path too, when Hermes names one."""
    module = load_module("hermes_cli.managed_scope")
    reader = getattr(module, "get_managed_dir", None)
    if not callable(reader):
        return None
    try:
        directory = reader()
    except Exception:
        return None
    from pathlib import Path

    return str(directory / "config.yaml") if isinstance(directory, Path) else None
