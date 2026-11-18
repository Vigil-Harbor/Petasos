"""Guardrail changes are refused, asked, or covered, and the score still rises."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.enforce import (
    Allow,
    ApprovalNotice,
    Block,
    Enforcer,
    HostInfo,
    ManualClock,
    SettingsSnapshot,
    ToolCall,
)
from petasos.enforce.decisions import Approve
from petasos.enforce.types import ApprovalGrant
from petasos.guard.surface import GuardrailSurface
from petasos.hermes.guardrail import hermes_surface

if TYPE_CHECKING:
    from pathlib import Path


class _Source:
    def __init__(self, snapshot: SettingsSnapshot) -> None:
        self.snapshot = snapshot

    def __call__(self) -> SettingsSnapshot:
        return self.snapshot


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, event: object) -> bool:
        if isinstance(event, dict):
            self.events.append(dict(event))
        return True


def _config(**tools: object) -> PetasosConfig:
    base = PetasosConfig()
    return replace(base, tools=replace(base.tools, **tools))  # type: ignore[arg-type]


def _path(tmp_path: Path) -> str:
    target = tmp_path / "profiles" / "demo" / "config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    return str(target)


def _enforcer(
    tmp_path: Path,
    sink: _Sink,
    *,
    mode: str = "approve",
    directive: bool = True,
    grant: ApprovalGrant | None = None,
    always: set[str] | None = None,
    clock: ManualClock | None = None,
    tiers: tuple[float, float, float] | None = None,
    surface: GuardrailSurface | None = None,
) -> tuple[Enforcer, _Source, str]:
    path = _path(tmp_path)
    config = _config(self_change=mode)
    if tiers is not None:
        one, two, three = tiers
        config = replace(
            config,
            escalation=replace(config.escalation, tier1=one, tier2=two, tier3=three),
        )
    source = _Source(SettingsSnapshot(armed=True, config=config, secrets=Secrets(), token=1))
    host = HostInfo(
        approve_directive=directive,
        approval_grant=lambda: grant if grant is not None else ApprovalGrant(),
        rule_always_approved=lambda rule: rule in (always or set()),
        subagent_hooks=False,
        protected_paths=lambda: frozenset({path}),
        guardrail_surface=lambda: surface if surface is not None else GuardrailSurface(),
    )
    enforcer = Enforcer(
        source,
        host=host,
        clock=clock if clock is not None else ManualClock(monotonic=1_000.0, wall=1_700_000_000.0),
        events=sink,
    )
    enforcer.start()
    assert enforcer.settle(10)
    return enforcer, source, path


def _write(path: str, session: str = "s1") -> ToolCall:
    return ToolCall(
        tool="write_file",
        args={"path": path, "content": "enabled: false"},
        session=session,
    )


def _kinds(sink: _Sink) -> list[str]:
    return [str(event.get("event_type")) for event in sink.events]


def _score(enforcer: Enforcer, session: str = "s1") -> float:
    engine = enforcer._core.engine
    assert engine is not None
    state = engine.tracker.get_state(session)
    assert state is not None
    return state.last_score


def test_never_blocks_and_the_score_rises(tmp_path: Path) -> None:
    sink = _Sink()
    enforcer, _source, path = _enforcer(tmp_path, sink, mode="never", directive=True)
    decision = enforcer.tool_call(_write(path))

    assert isinstance(decision, Block)
    assert "refused" in decision.message
    assert "outside the agent" in decision.message
    assert "impossible" not in decision.message.casefold()
    assert _score(enforcer) > 0
    guardrail = [event for event in sink.events if event.get("event_type") == "guardrail"]
    assert guardrail[-1]["decision"] == "refused"
    assert guardrail[-1]["kind"] == "settings"
    assert "selfmod_attempt" in _kinds(sink)


def test_approve_asks_when_a_person_can_answer(tmp_path: Path) -> None:
    sink = _Sink()
    enforcer, _source, path = _enforcer(tmp_path, sink)
    decision = enforcer.tool_call(_write(path))

    assert isinstance(decision, Approve)
    assert decision.rule_key == "petasos.guardrail.1.s1"
    assert "asks for approval" in decision.message
    assert _score(enforcer) > 0
    decisions = [
        event["decision"] for event in sink.events if event.get("event_type") == "guardrail"
    ]
    assert decisions == ["held"]


@pytest.mark.parametrize(
    "grant",
    [ApprovalGrant(mode_off=True), ApprovalGrant(yolo=True), ApprovalGrant(context=True)],
)
def test_an_auto_grant_blocks(tmp_path: Path, grant: ApprovalGrant) -> None:
    sink = _Sink()
    enforcer, _source, path = _enforcer(tmp_path, sink, grant=grant)
    decision = enforcer.tool_call(_write(path))

    assert isinstance(decision, Block)
    assert "nobody can be asked" in decision.message
    assert any(event.get("decision") == "unattended" for event in sink.events)


def test_no_approve_directive_blocks(tmp_path: Path) -> None:
    sink = _Sink()
    enforcer, _source, path = _enforcer(tmp_path, sink, directive=False)
    decision = enforcer.tool_call(_write(path))

    assert isinstance(decision, Block)
    assert "nobody can be asked" in decision.message


def test_a_live_session_grant_covers_the_same_session_until_it_expires(tmp_path: Path) -> None:
    sink = _Sink()
    clock = ManualClock(monotonic=1_000.0, wall=1_700_000_000.0)
    enforcer, _source, path = _enforcer(tmp_path, sink, clock=clock)
    first = enforcer.tool_call(_write(path))
    assert isinstance(first, Approve)
    enforcer.approval_answered(
        ApprovalNotice(
            pattern_key="plugin_rule:" + first.rule_key,
            choice="session",
            session_id="s1",
        )
    )
    before = _score(enforcer)
    second = enforcer.tool_call(_write(path))
    assert isinstance(second, Allow)
    assert _score(enforcer) > before
    covered = [event for event in sink.events if event.get("decision") == "covered"]
    assert covered and covered[-1]["until"] == 1_700_000_000.0 + 30 * 60

    clock.advance(30 * 60)
    third = enforcer.tool_call(_write(path))
    assert isinstance(third, Approve)
    assert third.rule_key == "petasos.guardrail.2.s1"


def test_another_session_is_not_covered(tmp_path: Path) -> None:
    sink = _Sink()
    enforcer, _source, path = _enforcer(tmp_path, sink)
    first = enforcer.tool_call(_write(path))
    assert isinstance(first, Approve)
    enforcer.approval_answered(ApprovalNotice(pattern_key=first.rule_key, choice="always"))
    other = enforcer.tool_call(_write(path, session="s2"))

    assert isinstance(other, Approve)
    assert other.rule_key == "petasos.guardrail.1.s2"


def test_an_always_entry_for_the_old_key_does_not_auto_approve(tmp_path: Path) -> None:
    sink = _Sink()
    always = {"petasos.guardrail.1.s1"}
    enforcer, _source, path = _enforcer(tmp_path, sink, always=always)
    decision = enforcer.tool_call(_write(path))

    assert isinstance(decision, Approve)
    assert decision.rule_key == "petasos.guardrail.2.s1"


def test_a_stopped_conversation_stays_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "petasos.session.frequency.time", SimpleNamespace(monotonic=lambda: 1000.0)
    )
    sink = _Sink()
    enforcer, _source, path = _enforcer(tmp_path, sink, mode="never", tiers=(10.0, 29.0, 30.0))
    for _ in range(3):
        blocked = enforcer.tool_call(_write(path))
        assert isinstance(blocked, Block)
        assert "refused" in blocked.message
    stopped = enforcer.tool_call(_write(path))

    assert isinstance(stopped, Block)
    assert "tier3" in stopped.message
    assert "refused" not in stopped.message
    assert _score(enforcer) >= 30


def test_a_denied_answer_is_recorded_and_the_next_call_asks_again(tmp_path: Path) -> None:
    sink = _Sink()
    enforcer, _source, path = _enforcer(tmp_path, sink)
    first = enforcer.tool_call(_write(path))
    assert isinstance(first, Approve)
    enforcer.approval_answered(ApprovalNotice(pattern_key=first.rule_key, choice="timeout"))
    assert any(event.get("decision") == "denied" for event in sink.events)
    second = enforcer.tool_call(_write(path))
    assert isinstance(second, Approve)


def test_an_applied_settings_change_is_recorded(tmp_path: Path) -> None:
    sink = _Sink()
    enforcer, source, path = _enforcer(tmp_path, sink)
    source.snapshot = SettingsSnapshot(
        armed=True,
        config=_config(self_change_minutes=12),
        secrets=Secrets(),
        token=2,
    )
    plain = ToolCall(tool="write_file", args={"path": "notes.txt", "content": "hi"}, session="s1")
    decision = enforcer.tool_call(plain)

    assert isinstance(decision, Allow)
    changed = [event for event in sink.events if event.get("event_type") == "settings_changed"]
    assert changed
    paths = changed[-1]["paths"]
    values = changed[-1]["values"]
    assert isinstance(paths, list)
    assert "tools.self_change_minutes" in paths
    assert values == {"tools.self_change_minutes": 12}
    assert changed[-1]["approval_live"] is False


def test_an_answer_for_a_key_that_was_never_asked_starts_nothing(tmp_path: Path) -> None:
    """A session grant needs an ask this enforcer made. A made-up key is ignored."""
    sink = _Sink()
    enforcer, _source, path = _enforcer(tmp_path, sink)
    enforcer.approval_answered(
        ApprovalNotice(pattern_key="plugin_rule:petasos.guardrail.1.s1", choice="session")
    )
    assert not [event for event in sink.events if event.get("decision") == "session"]

    decision = enforcer.tool_call(_write(path))
    assert isinstance(decision, Approve)


def test_an_answer_counts_once(tmp_path: Path) -> None:
    """Replaying the answer to an expired ask does not start a second grant."""
    sink = _Sink()
    clock = ManualClock(monotonic=1_000.0, wall=1_700_000_000.0)
    enforcer, _source, path = _enforcer(tmp_path, sink, clock=clock)
    first = enforcer.tool_call(_write(path))
    assert isinstance(first, Approve)
    answer = ApprovalNotice(pattern_key=first.rule_key, choice="session")
    enforcer.approval_answered(answer)
    clock.advance(30 * 60)

    enforcer.approval_answered(answer)
    after = enforcer.tool_call(_write(path))
    assert isinstance(after, Approve)
    assert len([event for event in sink.events if event.get("decision") == "session"]) == 1


@pytest.mark.parametrize("mode", ["never", "approve"])
@pytest.mark.parametrize(
    "command",
    [
        "hermes config set command_allowlist '[ordinary]'",
        "hermes config unset command_allowlist",
        "hermes config set command_allowlist.0 ordinary",
        "hermes config unset command_allowlist.0",
        "hermes approvals suggest --apply=1",
        "hermes setup --reset --non-interactive",
        "hermes import /tmp/backup.zip --force",
        "hermes profile install /tmp/profile --force",
    ],
)
def test_list_changes_follow_self_change_policy(tmp_path: Path, mode: str, command: str) -> None:
    sink = _Sink()
    enforcer, _source, _path = _enforcer(tmp_path, sink, mode=mode, surface=hermes_surface(()))
    decision = enforcer.tool_call(
        ToolCall(tool="terminal", args={"command": command}, session="s1")
    )
    assert isinstance(decision, Block if mode == "never" else Approve)
    assert _score(enforcer) > 0
    assert any(event.get("event_type") == "guardrail" for event in sink.events)
