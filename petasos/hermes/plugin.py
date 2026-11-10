"""Register Petasos with Hermes.

``register`` builds one enforcer, registers the hooks, and translates.
It does not decide a tool call. An empty block message is filled in, because
Hermes treats a block with no message as an allow.

Callbacks do not raise. ``pre_tool_call`` returns its own block when the
adapter fails, instead of relying on Hermes turning the exception into a
block: that host message includes the exception text, and the other hooks
fail open on an exception. One policy covers every hook.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from petasos.enforce import Allow, Approve, Block, Enforcer
from petasos.enforce.types import ApprovalNotice, HostInfo, ToolCall
from petasos.hermes.home import (
    display_path,
    resolve_hermes_config_path,
    spool_path,
    spool_rot_path,
)
from petasos.hermes.host import (
    approval_grant,
    approve_directive_available,
    load_redactor,
    rule_always_approved,
    subagent_hooks_available,
)
from petasos.hermes.settings import PLUGIN_ID, HermesSettings, profile_binding

if TYPE_CHECKING:
    from petasos.enforce.decisions import Decision

logger = logging.getLogger("petasos.hermes")

HOOKS: tuple[str, ...] = (
    "pre_tool_call",
    "transform_tool_result",
    "post_tool_call",
    "on_session_start",
    "subagent_start",
    "subagent_stop",
    "pre_approval_request",
    "post_approval_response",
    "on_profile_change",
)

_EMPTY_BLOCK = "Petasos blocked this tool call."
_INTERNAL_BLOCK = "Petasos could not evaluate this tool call."
_STALE = "no petasos: section at new profile; keeping last-good policy"
_MIGRATE = (
    "this profile has a petasos: section and no plugin settings; run `petasos config migrate`"
)
_REBIND_WINDOW_S = 30.0

# The one enforcer a registered plugin holds. ``register`` assigns it.
_registration: _Registration | None = None


class PluginContext(Protocol):
    """The Hermes context methods ``register`` calls."""

    def get_config(self, key: str, default: object = None) -> object:
        """The stored setting, or ``default`` when it was never set."""
        ...

    def register_hook(self, name: str, handler: object) -> None:
        """Bind ``handler`` to the hook named ``name``."""
        ...


class _Registration:
    """The enforcer and the settings source for this process."""

    def __init__(self, enforcer: Enforcer, source: HermesSettings) -> None:
        self.enforcer = enforcer
        self.source = source
        self.hooks = False
        self._rebind_at: dict[str, float] = {}

    def warn_rebind(self, message: str) -> None:
        """Log one rebind warning at most once per window. A different reason still logs."""
        now = time.monotonic()
        last = self._rebind_at.get(message, 0.0)
        if now - last < _REBIND_WINDOW_S:
            return
        if len(self._rebind_at) >= 32:
            self._rebind_at.pop(next(iter(self._rebind_at)))
        self._rebind_at[message] = now
        logger.warning("%s", message)


def directive(decision: Decision) -> dict[str, str] | None:
    """The Hermes directive for ``decision``. A block always carries a message."""
    if isinstance(decision, Allow):
        return None
    if isinstance(decision, Approve):
        message = decision.message.strip() if isinstance(decision.message, str) else ""
        payload = {"action": "approve", "message": message or _EMPTY_BLOCK}
        if decision.rule_key:
            payload["rule_key"] = decision.rule_key
        return payload
    if isinstance(decision, Block):
        message = decision.message.strip() if isinstance(decision.message, str) else ""
        return {"action": "block", "message": message or _EMPTY_BLOCK}
    return {"action": "block", "message": _INTERNAL_BLOCK}


def protected_paths() -> frozenset[str]:
    """Paths the agent must not modify, under the resolved Hermes home.

    The set is the profile config and env file, the plugin directory, the
    event spool and its rotation, and the profile pointer. Resolution follows
    ``HERMES_HOME`` when it is set, so a caller that has not pointed the
    process at a home is the one that falls through to the account default.
    """
    res = resolve_hermes_config_path()
    home = res.path.parent
    root = home.parent.parent if home.parent.name == "profiles" else home
    paths = [
        res.path,
        home / ".env",
        home / "plugins" / PLUGIN_ID,
        Path(spool_path(res)),
        Path(spool_rot_path(res)),
        root / "active_profile",
        root / "config.yaml",
        root / ".env",
        root / "plugins" / PLUGIN_ID,
    ]
    profiles = root / "profiles"
    if profiles.is_dir():
        try:
            children = list(profiles.iterdir())
        except OSError:
            children = []
        for child in children:
            if not child.is_dir() or child.name == "default":
                continue
            paths.extend(
                (
                    child / "config.yaml",
                    child / ".env",
                    child / "petasos-enforcement.jsonl",
                    child / "petasos-enforcement.jsonl.rot",
                )
            )
    return frozenset(str(path) for path in paths)


def host_info() -> HostInfo:
    """What this Hermes process can answer. Callables are read on each decision.

    ``host_id`` is the stable product id. Hermes does not expose a separate
    installation id, and a hash of the home would change the session token
    when the profile changes.
    """
    redactor = load_redactor()
    return HostInfo(
        host_id="petasos",
        approve_directive=approve_directive_available(),
        approval_grant=approval_grant,
        rule_always_approved=rule_always_approved,
        subagent_hooks=subagent_hooks_available(),
        redactor=redactor if callable(redactor) else None,
        display_path=display_path,
        protected_paths=protected_paths,
    )


def _tool_call(
    tool_name: object,
    args: object,
    task_id: object,
    kwargs: Mapping[str, object],
) -> ToolCall:
    """Hook arguments as a tool call. The mapping is copied, not reused."""
    if isinstance(args, Mapping):
        copied: Mapping[str, object] = dict(args)
    else:
        copied = {}
    turn = kwargs.get("turn_id")
    call_id = kwargs.get("tool_call_id")
    host_session = kwargs.get("session_id")
    return ToolCall(
        tool=tool_name if isinstance(tool_name, str) else "",
        args=copied,
        session=task_id if isinstance(task_id, str) else "",
        turn_id=turn if isinstance(turn, str) else None,
        tool_call_id=call_id if isinstance(call_id, str) else None,
        host_session=host_session if isinstance(host_session, str) else None,
        agent=kwargs.get("_agent"),
    )


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _notice(fields: Mapping[str, object], *, choice: object) -> ApprovalNotice:
    raw_keys = fields.get("pattern_keys")
    if isinstance(raw_keys, (list, tuple)):
        keys = tuple(item for item in raw_keys if isinstance(item, str))
    else:
        keys = ()
    stored = None if choice is None else choice if isinstance(choice, str) else str(choice)
    decided = fields.get("decided_by")
    return ApprovalNotice(
        command=_text(fields.get("command")),
        description=_text(fields.get("description")),
        pattern_key=_text(fields.get("pattern_key")),
        pattern_keys=keys,
        session_key=_text(fields.get("session_key")),
        session_id=_text(fields.get("session_id")),
        surface=_text(fields.get("surface")),
        turn_id=_text(fields.get("turn_id")),
        tool_call_id=_text(fields.get("tool_call_id")),
        choice=stored,
        decided_by=decided if isinstance(decided, str) else None,
        coalesced=fields.get("coalesced") is True,
    )


def _validated_home(profile_home: object) -> tuple[Path | None, str]:
    """An absolute existing directory, or a reason the payload was rejected."""
    if not profile_home:
        return None, "empty profile_home"
    if not isinstance(profile_home, (str, os.PathLike)):
        return None, f"non-path profile_home type={type(profile_home).__name__}"
    candidate = Path(profile_home)
    if not candidate.is_absolute():
        return None, f"non-absolute profile_home {str(profile_home)!r}"
    try:
        home = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None, f"unresolvable profile_home {str(profile_home)!r}"
    if not home.is_dir():
        return None, f"profile_home is not an existing directory: {home}"
    return home, ""


def _pre_tool_call(
    tool_name: str = "",
    args: object = None,
    task_id: str = "",
    **kwargs: object,
) -> dict[str, str] | None:
    reg = _registration
    if reg is None:
        return {"action": "block", "message": _INTERNAL_BLOCK}
    try:
        call = _tool_call(tool_name, args, task_id, kwargs)
        return directive(reg.enforcer.tool_call(call))
    except Exception:
        logger.exception("Petasos pre_tool_call failed")
        return {"action": "block", "message": _INTERNAL_BLOCK}


def _transform_tool_result(
    tool_name: str = "",
    args: object = None,
    result: object = None,
    task_id: str = "",
    **kwargs: object,
) -> str | None:
    reg = _registration
    if reg is None:
        return None
    try:
        call = _tool_call(tool_name, args, task_id, kwargs)
        return reg.enforcer.tool_result(call, result)
    except Exception:
        logger.exception("Petasos transform_tool_result failed")
        return None


def _post_tool_call(
    tool_name: str = "",
    args: object = None,
    result: object = None,
    task_id: str = "",
    duration_ms: object = 0,
    **kwargs: object,
) -> None:
    reg = _registration
    if reg is None:
        return
    try:
        call = _tool_call(tool_name, args, task_id, kwargs)
        text = result if isinstance(result, str) else ""
        duration = duration_ms if type(duration_ms) is int else 0
        reg.enforcer.tool_finished(call, text, duration_ms=duration)
    except Exception:
        logger.exception("Petasos post_tool_call failed")


def _on_session_start(session_id: str = "", **kwargs: object) -> None:
    del kwargs
    reg = _registration
    if reg is None:
        return
    try:
        reg.enforcer.session_started(session_id if isinstance(session_id, str) else "")
    except Exception:
        logger.exception("Petasos on_session_start failed")


def _subagent_start(
    parent_session_id: str = "",
    child_session_id: str = "",
    **kwargs: object,
) -> None:
    del kwargs
    reg = _registration
    if reg is None:
        return
    try:
        reg.enforcer.subagent_started(
            child_session_id if isinstance(child_session_id, str) else "",
            parent_session_id if isinstance(parent_session_id, str) else "",
        )
    except Exception:
        logger.exception("Petasos subagent_start failed")


def _subagent_stop(child_session_id: str = "", **kwargs: object) -> None:
    del kwargs
    reg = _registration
    if reg is None:
        return
    try:
        child = child_session_id if isinstance(child_session_id, str) else ""
        reg.enforcer.subagent_stopped(child)
    except Exception:
        logger.exception("Petasos subagent_stop failed")


def _pre_approval_request(**kwargs: object) -> None:
    reg = _registration
    if reg is None:
        return
    try:
        reg.enforcer.approval_requested(_notice(kwargs, choice=None))
    except Exception:
        logger.debug("PETASOS_APPROVAL emit failed")


def _post_approval_response(**kwargs: object) -> None:
    reg = _registration
    if reg is None:
        return
    try:
        reg.enforcer.approval_answered(_notice(kwargs, choice=kwargs.get("choice")))
    except Exception:
        logger.debug("PETASOS_APPROVAL emit failed")


def _on_profile_change(profile_name: str = "", profile_home: str = "", **kwargs: object) -> None:
    """A profile switch. Settings are re-read; the old ``petasos:`` section is not."""
    del kwargs
    reg = _registration
    if reg is None:
        return
    try:
        _apply_profile(reg, profile_name, profile_home)
    except Exception:
        logger.exception("Petasos on_profile_change failed")


def _apply_profile(reg: _Registration, profile_name: object, profile_home: object) -> None:
    name = profile_name if isinstance(profile_name, str) and profile_name else "<unnamed>"
    logger.info("PETASOS_PROFILE_CHANGE name=%r", name)
    home, reason = _validated_home(profile_home)
    if home is None:
        reg.warn_rebind(f"PETASOS_REBIND_SKIPPED reason={reason}")
        return
    config = home / "config.yaml"
    logger.info("PETASOS_ARMED_RESOLUTION tier=profile path=%s", config)
    kind, _settings = profile_binding(config)
    if kind == "legacy":
        logger.warning("PETASOS_CONFIG_MIGRATE path=%s: %s", config, _MIGRATE)
        return
    if kind != "settings":
        reg.warn_rebind(f"PETASOS_REBIND_CONFIG_STALE path={config}: {_STALE}")
        return
    reg.source.bind_profile(home)
    reg.enforcer.refresh()


def _try_register(ctx: PluginContext, name: str, handler: object) -> None:
    try:
        ctx.register_hook(name, handler)
    except Exception as exc:
        logger.warning("register_hook(%s) rejected by host — skipping: %s", name, exc)


def _log_resolution() -> None:
    res = resolve_hermes_config_path()
    logger.info("PETASOS_ARMED_RESOLUTION tier=%s path=%s", res.tier, res.path)
    if res.tier == "override" and not res.path.is_absolute():
        logger.warning(
            "PETASOS_ARMED_RESOLUTION_WARNING tier=override path=%s reason=not_absolute",
            res.path,
        )


def _bind(ctx: PluginContext) -> None:
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("transform_tool_result", _transform_tool_result)
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("on_session_start", _on_session_start)
    _try_register(ctx, "subagent_start", _subagent_start)
    _try_register(ctx, "subagent_stop", _subagent_stop)
    ctx.register_hook("pre_approval_request", _pre_approval_request)
    ctx.register_hook("post_approval_response", _post_approval_response)
    _try_register(ctx, "on_profile_change", _on_profile_change)


def register(ctx: PluginContext) -> None:
    """Build one enforcer, start it, and register the hooks on ``ctx``.

    A second call refreshes settings and does not register the hooks again.
    """
    global _registration
    if _registration is None:
        source = HermesSettings(ctx)
        enforcer = Enforcer(source, host=host_info(), spool_path=spool_path())
        _registration = _Registration(enforcer, source)
        enforcer.start()
        _log_resolution()
        logger.info(
            "PETASOS_HOST_CAPS approve_directive=%s subagent_hooks=%s",
            "available" if approve_directive_available() else "unavailable",
            "available" if subagent_hooks_available() else "unavailable",
        )
    if _registration.hooks:
        _registration.enforcer.refresh()
        return
    _bind(ctx)
    _registration.hooks = True


def close() -> None:
    """Stop the registered enforcer. A later ``register`` starts a new one."""
    global _registration
    reg = _registration
    _registration = None
    if reg is not None:
        reg.enforcer.close()
