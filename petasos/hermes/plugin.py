"""Register Petasos with Hermes.

``register`` binds one enforcer's hooks on the context it was given and
translates. It does not decide a tool call. An empty block message is filled
in, because Hermes treats a block with no message as an allow.

Callbacks do not raise. ``pre_tool_call`` returns its own block when the
adapter fails, instead of relying on Hermes turning the exception into a
block: that host message includes the exception text, and the other hooks
fail open on an exception. One policy covers every hook.

Hermes keeps one plugin manager per resolved home and can serve several
homes in one process (``set_hermes_home_override``). A force reload unloads
a manager and calls ``register`` again. The table below is how a repeated
``register`` finds the enforcer it already built for that home.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from petasos.enforce import Allow, Approve, Block, Enforcer
from petasos.enforce.types import ApprovalNotice, HostInfo, ToolCall
from petasos.hermes.guardrail import hermes_surface
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
from petasos.hermes.settings import PLUGIN_ID, HermesSettings

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
)

_EMPTY_BLOCK = "Petasos blocked this tool call."
_INTERNAL_BLOCK = "Petasos could not evaluate this tool call."

# The only module-level mutable state in the adapter.
# ``_registrations`` has one entry per Hermes home this process has loaded.
# A repeated ``register`` for that home reuses the enforcer (session scores,
# tiers, taint, lineage, and the loaded scanners). ``close`` clears the table.
# ``_registration_lock`` serialises the lookup. Hooks read it at call time.
_registrations: dict[str, _Registration] = {}
_registration_lock = threading.Lock()


class PluginContext(Protocol):
    """The Hermes context methods ``register`` calls."""

    def get_config(self, key: str, default: object = None) -> object:
        """The stored setting, or ``default`` when it was never set."""
        ...

    def register_hook(self, name: str, handler: object) -> None:
        """Bind ``handler`` to the hook named ``name``."""
        ...


def _home_key(ctx: object) -> str:
    """The home this context's manager was built for.

    Hermes stores that path on the manager and does not share a manager
    across homes. A context with no manager — a unit-test double — uses one
    shared key.
    """
    manager = getattr(ctx, "_manager", None)
    home = getattr(manager, "home_path", None)
    if home is None:
        return ""
    try:
        return str(Path(home).resolve())
    except (OSError, RuntimeError, ValueError):
        return str(home)


def _hook_callbacks(ctx: object, name: str) -> list[object]:
    """Callbacks already stored for ``name`` on this context's manager.

    Hermes keeps them on the manager. A test double keeps them on the context.
    """
    manager = getattr(ctx, "_manager", None)
    hooks = getattr(manager, "_hooks", None)
    if not isinstance(hooks, dict):
        hooks = getattr(ctx, "hooks", None)
    if not isinstance(hooks, dict):
        return []
    found = hooks.get(name)
    if isinstance(found, list):
        return list(found)
    return []


def _is_ours(callback: object) -> bool:
    return getattr(callback, "__func__", None) is _Registration.pre_tool_call


class _Registration:
    """Hooks and the enforcer for one Hermes home.

    The methods are what the manager calls. They read the table at call time,
    so a ``register`` after ``close`` starts on a new enforcer without leaving
    a second copy of the hooks on a manager that still has these methods.
    """

    def __init__(self, home_key: str, enforcer: Enforcer, source: HermesSettings) -> None:
        self.home_key = home_key
        self.enforcer = enforcer
        self.source = source

    def live(self) -> _Registration | None:
        """The registration serving this home now, if ``close`` has not dropped it."""
        return _registrations.get(self.home_key)

    def pre_tool_call(
        self,
        tool_name: str = "",
        args: object = None,
        task_id: str = "",
        **kwargs: object,
    ) -> dict[str, str] | None:
        reg = self.live()
        if reg is None:
            return {"action": "block", "message": _INTERNAL_BLOCK}
        try:
            call = _tool_call(tool_name, args, task_id, kwargs)
            return directive(reg.enforcer.tool_call(call))
        except Exception:
            logger.exception("Petasos pre_tool_call failed")
            return {"action": "block", "message": _INTERNAL_BLOCK}

    def transform_tool_result(
        self,
        tool_name: str = "",
        args: object = None,
        result: object = None,
        task_id: str = "",
        **kwargs: object,
    ) -> str | None:
        reg = self.live()
        if reg is None:
            return None
        try:
            call = _tool_call(tool_name, args, task_id, kwargs)
            return reg.enforcer.tool_result(call, result)
        except Exception:
            logger.exception("Petasos transform_tool_result failed")
            return None

    def post_tool_call(
        self,
        tool_name: str = "",
        args: object = None,
        result: object = None,
        task_id: str = "",
        duration_ms: object = 0,
        **kwargs: object,
    ) -> None:
        reg = self.live()
        if reg is None:
            return
        try:
            call = _tool_call(tool_name, args, task_id, kwargs)
            text = result if isinstance(result, str) else ""
            duration = duration_ms if type(duration_ms) is int else 0
            reg.enforcer.tool_finished(call, text, duration_ms=duration)
        except Exception:
            logger.exception("Petasos post_tool_call failed")

    def on_session_start(self, session_id: str = "", **kwargs: object) -> None:
        del kwargs
        reg = self.live()
        if reg is None:
            return
        try:
            reg.enforcer.session_started(session_id if isinstance(session_id, str) else "")
        except Exception:
            logger.exception("Petasos on_session_start failed")

    def subagent_start(
        self,
        parent_session_id: str = "",
        child_session_id: str = "",
        **kwargs: object,
    ) -> None:
        del kwargs
        reg = self.live()
        if reg is None:
            return
        try:
            reg.enforcer.subagent_started(
                child_session_id if isinstance(child_session_id, str) else "",
                parent_session_id if isinstance(parent_session_id, str) else "",
            )
        except Exception:
            logger.exception("Petasos subagent_start failed")

    def subagent_stop(self, child_session_id: str = "", **kwargs: object) -> None:
        del kwargs
        reg = self.live()
        if reg is None:
            return
        try:
            child = child_session_id if isinstance(child_session_id, str) else ""
            reg.enforcer.subagent_stopped(child)
        except Exception:
            logger.exception("Petasos subagent_stop failed")

    def pre_approval_request(self, **kwargs: object) -> None:
        reg = self.live()
        if reg is None:
            return
        try:
            reg.enforcer.approval_requested(_notice(kwargs, choice=None))
        except Exception:
            logger.debug("PETASOS_APPROVAL emit failed")

    def post_approval_response(self, **kwargs: object) -> None:
        reg = self.live()
        if reg is None:
            return
        try:
            reg.enforcer.approval_answered(_notice(kwargs, choice=kwargs.get("choice")))
        except Exception:
            logger.debug("PETASOS_APPROVAL emit failed")

    def attach(self, ctx: PluginContext) -> None:
        """Bind these methods on ``ctx``. The caller has already checked."""
        ctx.register_hook("pre_tool_call", self.pre_tool_call)
        ctx.register_hook("transform_tool_result", self.transform_tool_result)
        ctx.register_hook("post_tool_call", self.post_tool_call)
        ctx.register_hook("on_session_start", self.on_session_start)
        _try_register(ctx, "subagent_start", self.subagent_start)
        _try_register(ctx, "subagent_stop", self.subagent_stop)
        ctx.register_hook("pre_approval_request", self.pre_approval_request)
        ctx.register_hook("post_approval_response", self.post_approval_response)


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


def guardrail_roots() -> frozenset[str]:
    """The Hermes home, and for a named profile the home above it."""
    home = resolve_hermes_config_path().path.parent
    root = home.parent.parent if home.parent.name == "profiles" else home
    return frozenset({str(home), str(root)})


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
        guardrail_surface=lambda: hermes_surface(protected_paths(), guardrail_roots()),
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


def _try_register(ctx: PluginContext, name: str, handler: object) -> None:
    try:
        ctx.register_hook(name, handler)
    except Exception as exc:
        logger.warning("register_hook(%s) rejected by host — skipping: %s", name, exc)


def _log_resolution() -> None:
    """The home and the config file this call bound to.

    During ``register`` Hermes has the manager's home as the context-local
    override, so the path is that home's ``config.yaml``. Plugin settings
    live in that file.
    """
    res = resolve_hermes_config_path()
    logger.info("PETASOS_ARMED_RESOLUTION tier=%s path=%s", res.tier, res.path)
    if res.tier == "override" and not res.path.is_absolute():
        logger.warning(
            "PETASOS_ARMED_RESOLUTION_WARNING tier=override path=%s reason=not_absolute",
            res.path,
        )


def _already_bound(ctx: object) -> bool:
    return any(_is_ours(callback) for callback in _hook_callbacks(ctx, "pre_tool_call"))


def register(ctx: PluginContext) -> None:
    """Bind hooks on ``ctx`` and reuse the enforcer already built for its home.

    A second call on a manager that still has the hooks does not add another
    copy. A call after Hermes has unloaded those hooks binds them again and
    does not build another enforcer.
    """
    key = _home_key(ctx)
    created = False
    attached = False
    with _registration_lock:
        reg = _registrations.get(key)
        if reg is None:
            source = HermesSettings(ctx)
            enforcer = Enforcer(source, host=host_info(), spool_path=spool_path())
            reg = _Registration(key, enforcer, source)
            _registrations[key] = reg
            created = True
        if not _already_bound(ctx):
            reg.attach(ctx)
            attached = True
        if created:
            reg.enforcer.start()
    if created or attached:
        _log_resolution()
        if created:
            logger.info(
                "PETASOS_HOST_CAPS approve_directive=%s subagent_hooks=%s",
                "available" if approve_directive_available() else "unavailable",
                "available" if subagent_hooks_available() else "unavailable",
            )
    _register_cli(ctx)


def _register_cli(ctx: object) -> None:
    """Offer ``hermes petasos`` when the host can register a command.

    A missing call, or a host that rejects the registration, is logged and
    ignored. Hook registration has already finished, so enforcement still starts.
    """
    register = getattr(ctx, "register_cli_command", None)
    if not callable(register):
        logger.info("PETASOS_CLI unavailable: this Hermes has no register_cli_command")
        return
    try:
        from petasos.hermes.commands import install_registered_cli, run_registered

        register(
            "petasos",
            "Check Petasos and update its settings.",
            install_registered_cli,
            run_registered,
            "Doctor, a file refresh, and settings migration for an installed Petasos plugin.",
        )
    except Exception as exc:
        logger.warning("PETASOS_CLI rejected: %s", exc)


def close() -> None:
    """Stop every registered enforcer. A later ``register`` starts a new one."""
    with _registration_lock:
        regs = list(_registrations.values())
        _registrations.clear()
    for reg in regs:
        reg.enforcer.close()
