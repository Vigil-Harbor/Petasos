"""A repeated host hook is the same call only with its complete identity."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from petasos.enforce import Allow, ApprovalNotice, Block, ManualClock, ToolCall
from petasos.enforce.decisions import Approve
from petasos.enforce.replays import Replays
from tests.enforce.test_guardrail import _enforcer, _score, _Sink, _write


def _call() -> ToolCall:
    return ToolCall(
        "terminal",
        {"command": "echo ok"},
        session="task",
        host_session="host",
        turn_id="turn",
        tool_call_id="call",
    )


def _notice(**fields: object) -> ApprovalNotice:
    return replace(
        ApprovalNotice(
            pattern_key="plugin_rule:rule",
            session_id="host",
            turn_id="turn",
            tool_call_id="call",
            surface="cli",
            session_key="host",
            choice="once",
        ),
        **fields,  # type: ignore[arg-type]
    )


def test_replays_allow_and_human_granted_asks_only() -> None:
    replay = Replays(ManualClock())
    key = replay.key(_call(), "task")
    replay.remember(key, Approve("ask", "rule"))
    assert not replay.allowed(key)
    # A response without the matching request is not proof of a fresh prompt.
    replay.answer(_notice())
    assert not replay.allowed(key)
    replay.request(_notice(choice=None))
    replay.answer(_notice())
    assert replay.allowed(key)


@pytest.mark.parametrize(
    "fields",
    [
        {"choice": "deny"},
        {"choice": "smart_approve", "decided_by": "aux_llm"},
        {"decided_by": "aux_llm"},
        {"pattern_key": "plugin_rule:other"},
        {"session_id": "other"},
        {"turn_id": "other"},
        {"tool_call_id": "other"},
        {"turn_id": ""},
        {"tool_call_id": ""},
        {"session_key": "other"},
        {"surface": "other"},
    ],
)
def test_unmatched_or_nonhuman_response_does_not_grant(fields: dict[str, object]) -> None:
    replay = Replays(ManualClock())
    key = replay.key(_call(), "task")
    replay.remember(key, Approve("ask", "rule"))
    replay.request(_notice(choice=None))
    replay.answer(_notice(**fields))
    assert not replay.allowed(key)


def test_record_never_turns_a_block_into_allow() -> None:
    replay = Replays(ManualClock())
    key = replay.key(_call(), "task")
    replay.remember(key, Block("stopped"))
    replay.remember(key, Approve("ask", "rule"))
    replay.request(_notice(choice=None))
    replay.answer(_notice())
    replay.remember(key, Allow())
    assert not replay.allowed(key)


@pytest.mark.parametrize(
    "fields",
    [
        {"session": "other"},
        {"host_session": "other"},
        {"turn_id": "other"},
        {"tool_call_id": "other"},
        {"tool": "write_file"},
        {"args": {"command": "echo changed"}},
        {"turn_id": ""},
        {"turn_id": None},
        {"tool_call_id": ""},
        {"tool_call_id": None},
        {"args": {"value": object()}},
        {"args": {"value": float("nan")}},
    ],
)
def test_any_identity_or_argument_mismatch_is_fresh(fields: dict[str, object]) -> None:
    replay = Replays(ManualClock())
    call = _call()
    key = replay.key(call, "task")
    replay.remember(key, Allow())
    changed = replace(call, **fields)  # type: ignore[arg-type]
    assert not replay.allowed(replay.key(changed, changed.session))


def test_arguments_are_order_independent_and_tool_is_canonical() -> None:
    replay = Replays(ManualClock())
    first = replace(_call(), args={"one": 1, "two": [False]})
    key = replay.key(first, "task")
    replay.remember(key, Allow())
    assert replay.allowed(
        replay.key(replace(first, tool="Terminal", args={"two": [False], "one": 1}), "task")
    )


def test_records_expire_and_are_size_capped() -> None:
    clock = ManualClock()
    replay = Replays(clock)
    first = replay.key(_call(), "task")
    replay.remember(first, Allow())
    clock.advance(301)
    assert not replay.allowed(first)
    replay.remember(first, Allow())
    for index in range(1024):
        replay.remember(replay.key(replace(_call(), tool_call_id=str(index)), "task"), Allow())
    assert not replay.allowed(first)
    assert replay.allowed(replay.key(replace(_call(), tool_call_id="1023"), "task"))


def test_granted_guardrail_repeat_does_not_ask_or_score_twice(tmp_path: Path) -> None:
    sink = _Sink()
    enforcer, _source, path = _enforcer(tmp_path, sink)
    try:
        call = replace(_write(path), host_session="host", turn_id="turn", tool_call_id="call")
        decision = enforcer.tool_call(call)
        assert isinstance(decision, Approve)
        score = _score(enforcer)
        assert score > 0
        notice = _notice(pattern_key="plugin_rule:" + decision.rule_key)
        enforcer.approval_requested(replace(notice, choice=None))
        enforcer.approval_answered(notice)
        assert isinstance(enforcer.tool_call(call), Allow)
        assert _score(enforcer) == score
        assert len([event for event in sink.events if event.get("decision") == "held"]) == 1
        # Another call id is a new decision and raises risk again.
        assert isinstance(enforcer.tool_call(replace(call, tool_call_id="next")), Approve)
        assert _score(enforcer) > score
    finally:
        enforcer.close()


def test_one_response_cannot_approve_two_argument_versions() -> None:
    replay = Replays(ManualClock())
    first = replay.key(_call(), "task")
    changed = replay.key(replace(_call(), args={"command": "echo changed"}), "task")
    replay.remember(first, Approve("ask", "rule"))
    replay.remember(changed, Approve("ask", "rule"))
    replay.request(_notice(choice=None))
    replay.answer(_notice())
    assert not replay.allowed(first)
    assert not replay.allowed(changed)


def test_a_denied_first_ask_cannot_be_revived_by_a_later_response() -> None:
    replay = Replays(ManualClock())
    key = replay.key(_call(), "task")
    replay.remember(key, Approve("ask", "rule"))
    replay.request(_notice(choice=None))
    replay.answer(_notice(choice="deny"))
    replay.request(_notice(choice=None))
    replay.answer(_notice())
    assert not replay.allowed(key)


def test_close_during_a_replay_still_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.enforce.test_enforcer import _enforcer as build
    from tests.enforce.test_enforcer import _snapshot, _Source

    enforcer = build(tmp_path, _Source(_snapshot()))
    enforcer.start()
    assert enforcer.settle(10)

    def closing(_key: object) -> bool:
        enforcer.close()
        return True

    monkeypatch.setattr(enforcer._core.replays, "allowed", closing)
    assert isinstance(enforcer.tool_call(_call()), Block)


def test_a_later_evaluation_cannot_replace_the_reserved_first_block() -> None:
    replay = Replays(ManualClock())
    key = replay.key(_call(), "task")
    first = replay.reserve(key)
    later = replay.reserve(key)
    assert first is not None and later is None
    replay.finish(key, later, Allow())
    replay.finish(key, first, Block("stopped"))
    replay.finish(key, first, Allow())
    assert not replay.allowed(key)


def test_slow_call_does_not_hold_up_an_unrelated_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from petasos.enforce.decisions import Decision
    from tests.enforce.test_enforcer import _enforcer as build
    from tests.enforce.test_enforcer import _snapshot, _Source

    entered = threading.Event()
    release = threading.Event()

    def decide(_core: object, call: ToolCall) -> Decision:
        if call.tool == "slow":
            entered.set()
            release.wait(10)
            return Block("stopped")
        return Allow()

    monkeypatch.setattr("petasos.enforce.enforcer.decide", decide)
    enforcer = build(tmp_path, _Source(_snapshot()))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(enforcer.tool_call, replace(_call(), tool="slow"))
            assert entered.wait(5)
            try:
                other = pool.submit(enforcer.tool_call, replace(_call(), tool_call_id="other"))
                assert isinstance(other.result(timeout=2), Allow)
            finally:
                release.set()
            assert isinstance(slow.result(timeout=5), Block)
    finally:
        release.set()
        enforcer.close()
