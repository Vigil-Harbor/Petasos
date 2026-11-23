"""Decide a recognised guardrail change, and record it.

The rule key is ``petasos.guardrail.<generation>.<session>``. Each ask uses a
new generation, so a Hermes "always" entry, which is stored as
``plugin_rule:`` plus that key, cannot match a later ask or another session.
A "session" or "always" answer is remembered here, on the enforcer's clock,
for ``tools.self_change_minutes``. While that grant is live the enforcer does
not ask again. When it expires, the next ask uses a new generation.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from petasos.config.schema import to_mapping
from petasos.enforce.approvals import redact_display_text
from petasos.enforce.decisions import Approve, Block, Decision
from petasos.guard.guardrail import CheckFailure, recognize
from petasos.guard.surface import GuardrailHit, GuardrailSurface
from petasos.guard.tools import _READ_ONLY_CANON
from petasos.normalize import canonicalize_tool_name

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from petasos.config.sections import PetasosConfig
    from petasos.enforce.core import Core
    from petasos.enforce.types import ApprovalNotice, ToolCall

logger = logging.getLogger("petasos.enforce")

_PREFIX = "[BLOCKED by Petasos]"
_RULE_PREFIX = "petasos.guardrail."
_SESSION_CHOICES = frozenset({"session", "always"})
_ONCE_CHOICES = frozenset({"once"})
_DENIED_CHOICES = frozenset({"deny", "denied", "timeout", "cancelled", "canceled", "refused"})
_MAX_BUMP = 8
_MAX_ASKED = 16


@dataclass(frozen=True, slots=True)
class Ruling:
    """What to do with one guardrail change.

    ``decision`` is the guardrail floor. ``None`` means a live session grant
    covers the change and the rest of the ladder still runs. ``until`` is the
    wall-clock second the grant lasts until.
    """

    decision: Decision | None
    name: str
    until: float | None = None
    kind: str = ""
    target: str = ""


class Grants:
    """Session grants for guardrail changes. One enforcer, its own clock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until: dict[str, tuple[float, float]] = {}
        self._next: dict[str, int] = {}
        self._asked: dict[str, set[int]] = {}

    def issue(self, session_id: str, blocked: Callable[[str], bool]) -> str | None:
        """A key Hermes will not auto-approve, or ``None`` when every try would."""
        with self._lock:
            generation = self._next.get(session_id, 1)
            for _ in range(_MAX_BUMP):
                key = _rule_key(generation, session_id)
                try:
                    auto = blocked(key)
                except Exception:
                    auto = True
                if not auto:
                    self._next[session_id] = generation + 1
                    asked = self._asked.setdefault(session_id, set())
                    if len(asked) >= _MAX_ASKED:
                        asked.discard(min(asked))
                    asked.add(generation)
                    return key
                generation += 1
            self._next[session_id] = generation
            return None

    def claim(self, session_id: str, generation: int) -> bool:
        """True once for a key this enforcer issued and has not seen answered.

        An answer for a key that was never issued here, or was already
        answered, starts nothing.
        """
        with self._lock:
            asked = self._asked.get(session_id)
            if asked is None or generation not in asked:
                return False
            asked.discard(generation)
            if not asked:
                del self._asked[session_id]
            return True

    def accept(self, session_id: str, until_mono: float, until_wall: float) -> None:
        """Remember a session grant until ``until_mono`` on the enforcer clock."""
        with self._lock:
            self._until[session_id] = (until_mono, until_wall)

    def live(self, session_id: str, now: float) -> float | None:
        """The wall time a live grant lasts until, or ``None``."""
        with self._lock:
            row = self._until.get(session_id)
            if row is None or now >= row[0]:
                return None
            return row[1]

    def any_live(self, now: float) -> bool:
        """True when any session still has a grant."""
        with self._lock:
            return any(now < mono for mono, _wall in self._until.values())


def parse_rule_key(key: str) -> tuple[int, str] | None:
    """``(generation, session)`` from a guardrail rule key, or ``None``."""
    text = key.removeprefix("plugin_rule:")
    if not text.startswith(_RULE_PREFIX):
        return None
    rest = text[len(_RULE_PREFIX) :]
    generation, sep, session_id = rest.partition(".")
    if not sep or not generation.isdigit() or not session_id:
        return None
    return int(generation), session_id


def ruling_for(
    core: Core,
    call: ToolCall,
    session_id: str,
    *,
    kind: str,
    target: str,
) -> Ruling:
    """Decide one recognised change. Emits the decision event except a covered one.

    A covered change is emitted by the caller after combining both policies.
    """
    shown = _shown(core, target)
    mode = _mode(core)
    if mode == "never":
        _emit(core, call, session_id, name="refused", kind=kind, target=shown)
        logger.info(
            "PETASOS_GUARDRAIL decision=refused tool=%s session=%s kind=%s",
            call.tool,
            session_id,
            kind,
        )
        return Ruling(Block(refused_message(call.tool)), "refused", kind=kind, target=shown)
    if _cannot_ask(core):
        _emit(core, call, session_id, name="unattended", kind=kind, target=shown)
        logger.info(
            "PETASOS_GUARDRAIL decision=unattended tool=%s session=%s kind=%s",
            call.tool,
            session_id,
            kind,
        )
        return Ruling(Block(_unattended(call.tool)), "unattended", kind=kind, target=shown)
    until = core.grants.live(session_id, core.clock.monotonic())
    if until is not None:
        return Ruling(None, "covered", until=until, kind=kind, target=shown)
    key = core.grants.issue(session_id, lambda rule: _always(core, rule))
    if key is None:
        _emit(core, call, session_id, name="unattended", kind=kind, target=shown)
        logger.info(
            "PETASOS_GUARDRAIL decision=unattended tool=%s session=%s kind=%s",
            call.tool,
            session_id,
            kind,
        )
        return Ruling(Block(_unattended(call.tool)), "unattended", kind=kind, target=shown)
    _emit(core, call, session_id, name="held", kind=kind, target=shown, rule_id=key)
    logger.info(
        "PETASOS_GUARDRAIL decision=held tool=%s session=%s rule_key=%s",
        call.tool,
        session_id,
        key,
    )
    return Ruling(Approve(_ask(call.tool, shown), key), "held", kind=kind, target=shown)


def note_covered(core: Core, call: ToolCall, session_id: str, ruling: Ruling) -> None:
    """Record that a live session grant covered the guardrail part of a call."""
    _emit(
        core,
        call,
        session_id,
        name="covered",
        kind=ruling.kind,
        target=ruling.target,
        until=ruling.until,
        scope="session",
    )
    logger.info(
        "PETASOS_GUARDRAIL decision=covered tool=%s session=%s until=%s",
        call.tool,
        session_id,
        "" if ruling.until is None else ruling.until,
    )


def note_blocked(core: Core, call: ToolCall, session_id: str, *, kind: str, target: str) -> None:
    """Record an attempt stopped by the content or session ladder."""
    _emit(core, call, session_id, name="blocked", kind=kind, target=_shown(core, target))


def note_answer(core: Core, notice: ApprovalNotice) -> None:
    """Remember a session answer, and record once, session, and denied."""
    parsed = parse_rule_key(notice.pattern_key)
    if parsed is None:
        return
    generation, session_id = parsed
    if not core.grants.claim(session_id, generation):
        logger.info(
            "PETASOS_GUARDRAIL answer ignored session=%s generation=%s (not an open ask)",
            session_id,
            generation,
        )
        return
    choice = notice.choice.strip().lower() if isinstance(notice.choice, str) else ""
    if choice in _SESSION_CHOICES:
        minutes = _minutes(core)
        now = core.clock.monotonic()
        wall = core.clock.time()
        until = wall + minutes * 60
        core.grants.accept(session_id, now + minutes * 60, until)
        _emit(
            core,
            None,
            session_id,
            name="session",
            kind="",
            target="",
            until=until,
            scope="always" if choice == "always" else "session",
            tool="",
        )
        return
    if choice in _ONCE_CHOICES:
        _emit(core, None, session_id, name="once", kind="", target="", scope="once", tool="")
        return
    if choice in _DENIED_CHOICES:
        _emit(core, None, session_id, name="denied", kind="", target="", scope=choice, tool="")


def hit_for(core: Core, call: ToolCall, session_id: str) -> GuardrailHit | CheckFailure | None:
    """Recognise a change when the guard did not run. Never raises."""
    if canonicalize_tool_name(call.tool) in _READ_ONLY_CANON:
        return None
    try:
        surface = core.host.guardrail_surface()
        if not isinstance(surface, GuardrailSurface):
            raise TypeError("guardrail surface is not a GuardrailSurface")
        protected = core.host.protected_paths()
        return recognize(
            call.tool if isinstance(call.tool, str) else "",
            call.args,
            protected=protected,
            surface=surface,
        )
    except Exception as exc:
        failure = CheckFailure(f"{type(exc).__name__}: {exc}")
        core.check_failures.note(session_id, failure)
        return failure


def record_applied_settings(
    core: Core, before: PetasosConfig, *, before_armed: bool | None = None
) -> None:
    """Record the settings the enforcer just applied. Secret values are not included."""
    engine = core.engine
    if engine is None:
        return
    try:
        changed = _changed(to_mapping(before), to_mapping(engine.config))
        if before_armed is not None and before_armed != core.armed:
            changed["enabled"] = core.armed
    except Exception:
        logger.debug("settings-change diff failed", exc_info=True)
        return
    if not changed:
        return
    try:
        live = core.grants.any_live(core.clock.monotonic())
    except Exception:
        live = False
    paths = tuple(changed)
    _emit_raw(
        core,
        {
            "event_type": "settings_changed",
            "armed": core.armed,
            "session_id": "",
            "tool": "",
            "rule_id": None,
            "severity": None,
            "tier": None,
            "reason": _settings_reason(paths, live),
            "direction": "tool_call",
            "param_scan_degraded": False,
            "bypassed_count": None,
            "credential_redaction": "unchanged",
            "paths": list(paths),
            "values": {path: changed[path] for path in paths},
            "approval_live": live,
        },
    )


def _rule_key(generation: int, session_id: str) -> str:
    return f"{_RULE_PREFIX}{generation}.{session_id}"


def _mode(core: Core) -> str:
    engine = core.engine
    if engine is None:
        return "never"
    try:
        mode = engine.config.tools.self_change
    except Exception:
        return "never"
    return mode if mode == "approve" else "never"


def _minutes(core: Core) -> int:
    engine = core.engine
    if engine is None:
        return 30
    try:
        minutes = engine.config.tools.self_change_minutes
    except Exception:
        return 30
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
        return 30
    return minutes


def _cannot_ask(core: Core) -> bool:
    if not core.host.approve_directive:
        return True
    # Only an explicit False is a person attached. Any other answer is not.
    try:
        return core.host.approval_grant().unattended is not False
    except Exception:
        return True


def _always(core: Core, rule_key: str) -> bool:
    # A key is handed out only on an explicit False. Any other answer may be
    # a rule the host grants without asking.
    try:
        return core.host.rule_always_approved(rule_key) is not False
    except Exception:
        return True


def _shown(core: Core, target: str) -> str:
    try:
        text = core.host.display_path(target)
    except Exception:
        text = target
    if not isinstance(text, str):
        text = target
    shown, _status = redact_display_text(text, 160, redact=core.host.redactor)
    return shown or text[:160]


def refused_message(tool: str) -> str:
    """The refusal for a guardrail change the agent may not make."""
    return (
        f"{_PREFIX} Tool '{tool}' was NOT executed. "
        "Changing Petasos or Hermes guardrails from the agent was refused. "
        "The operator makes those changes from outside the agent."
    )


def _unattended(tool: str) -> str:
    return (
        f"{_PREFIX} Tool '{tool}' was NOT executed. "
        "Changing Petasos or Hermes guardrails needs a person to approve it, "
        "and nobody can be asked. The change was refused."
    )


def _ask(tool: str, target: str) -> str:
    return (
        f"Petasos asks for approval before changing guardrails with '{tool}'. "
        f"Target: {target}. "
        "A session approval covers later guardrail changes in this conversation "
        "only until it expires."
    )


def _emit(
    core: Core,
    call: ToolCall | None,
    session_id: str,
    *,
    name: str,
    kind: str,
    target: str,
    until: float | None = None,
    scope: str | None = None,
    rule_id: str | None = None,
    tool: str | None = None,
) -> None:
    _emit_raw(
        core,
        {
            "event_type": "guardrail",
            "decision": name,
            "kind": kind,
            "target": target,
            "until": until,
            "scope": scope,
            "armed": core.armed,
            "session_id": session_id,
            "tool": call.tool if tool is None and call is not None else (tool or ""),
            "rule_id": rule_id,
            "severity": _severity(name),
            "tier": None,
            "reason": _reason(name, kind, target, until, scope),
            "direction": "tool_call",
            "param_scan_degraded": False,
            "bypassed_count": None,
            "credential_redaction": "unchanged",
        },
    )


def _severity(name: str) -> str | None:
    if name in {"refused", "unattended", "held", "covered", "blocked"}:
        return "critical"
    return None


def _reason(name: str, kind: str, target: str, until: float | None, scope: str | None) -> str:
    if name == "blocked":
        return f"guardrail change stopped by content or session policy ({kind}): {target}".strip()
    if name == "refused":
        return f"guardrail refused ({kind}): {target}".strip()
    if name == "unattended":
        return f"guardrail unattended ({kind}): {target}".strip()
    if name == "held":
        return f"guardrail held ({kind}): {target}".strip()
    if name == "covered":
        return f"guardrail covered until {until} ({kind}): {target}".strip()
    if name == "session":
        return f"guardrail session until {until} scope={scope}"
    if name == "once":
        return "guardrail once"
    if name == "denied":
        return f"guardrail denied scope={scope}"
    return f"guardrail {name}"


def _settings_reason(paths: tuple[str, ...], live: bool) -> str:
    listed = ", ".join(paths)
    if live:
        return f"settings changed: {listed}; a session approval was live"
    return f"settings changed: {listed}; no session approval was live"


def _emit_raw(core: Core, event: dict[str, Any]) -> None:
    sink = core._sink
    if sink is None:
        return
    try:
        sink.emit(event)
    except Exception:
        logger.debug("guardrail event failed", exc_info=True)


def _changed(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, object]:
    left = _flatten(before)
    right = _flatten(after)
    changed: dict[str, object] = {}
    for path in sorted(set(left) | set(right)):
        if left.get(path) != right.get(path):
            changed[path] = right.get(path)
    return changed


def _flatten(node: Mapping[str, Any], prefix: str = "") -> dict[str, object]:
    found: dict[str, object] = {}
    for key, value in node.items():
        if not isinstance(key, str):
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            found.update(_flatten(value, path))
        else:
            found[path] = value
    return found
