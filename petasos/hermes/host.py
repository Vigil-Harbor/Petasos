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
