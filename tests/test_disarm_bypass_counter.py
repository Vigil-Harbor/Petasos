"""PET-138: per-session disarmed-bypass counter (plugin side).

While Petasos is disarmed (Unequipped), ``_pre_tool_call`` short-circuits with no
scan and emits a ``bypassed_disarmed`` heartbeat only when the 30s rate-limiter
opens — a sample, not a count. PET-138 adds an in-process per-session counter
bumped on EVERY disarmed call (decoupled from the heartbeat) and carries the
cumulative count on the heartbeat so the dashboard can surface an authoritative
tally.

Regression for PET-138: the operator could not see how many tool calls were
bypassed while disarmed (the heartbeat is a 30s sample); "off means off" was
unverifiable from the UI. The counter must not weaken the zero-overhead disarm
invariant (no scan, no ``_guard.evaluate``).

Backend-free: the guard is stubbed; the spool is redirected by the autouse
``_isolate_enforcement_spool`` conftest fixture.
"""

from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("fastapi")

import petasos.console._events as ev  # noqa: E402
from petasos import GuardResult  # noqa: E402

if TYPE_CHECKING:
    import types

_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet138", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _raise_on_scan(self: Any, *a: Any, **k: Any) -> None:
    raise AssertionError("a scan ran while disarmed (zero-overhead invariant violated)")


def _setup_disarmed(ref: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the plugin into a disarmed, initialized state with a guard that SCREAMS
    if anything tries to scan on the disarm fast path."""
    monkeypatch.setattr(ref, "_initialized", True)
    monkeypatch.setattr(ref, "_init_error", None)
    monkeypatch.setattr(ref, "_is_armed", lambda: False)
    monkeypatch.setattr(ref, "_guard", type("SpyGuard", (), {"evaluate": _raise_on_scan})())
    monkeypatch.setattr(ref, "_maybe_reconfigure", lambda: None)
    ref._reset_disarm_log()
    ref._reset_bypass_counts()


def _allowed() -> GuardResult:
    return GuardResult(
        allowed=True,
        reason="allowed",
        findings=(),
        tier="none",
        param_scan_unsafe=False,
        param_scan_degraded=False,
    )


def _read_spool(spool: str) -> list[dict[str, Any]]:
    if not Path(spool).exists():
        return []
    with open(spool, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture()
def spool() -> str:
    return ev._spool_path()


def test_t1_full_count_in_one_window(spool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # K disarmed calls in one 30s window are ALL counted in-process, even though the
    # rate-limited heartbeat fires at most once. The single heartbeat carries the
    # count at emit time (1 — the first call opened the window).
    ref = _import_reference_plugin()
    _setup_disarmed(ref, monkeypatch)
    k = 5
    for _ in range(k):
        assert ref._pre_tool_call("send_email", {"text": "x"}, task_id="sess-A") is None
    assert ref._bypass_counts["sess-A"] == k  # in-process count is exact

    events = _read_spool(spool)
    assert len(events) == 1  # heartbeat is rate-limited to <=1 per window
    assert events[0]["event_type"] == "bypassed_disarmed"
    assert events[0]["bypassed_count"] == 1  # count at emit time (first call)


def test_t2_zero_overhead_no_scan(spool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-138: counting must NOT introduce a scan. A disarmed
    # _pre_tool_call runs no scanner, never enters the async guard path, returns None
    # — but the call IS counted.
    ref = _import_reference_plugin()
    _setup_disarmed(ref, monkeypatch)
    run_calls: list[Any] = []
    monkeypatch.setattr(ref, "_run_async", lambda coro: run_calls.append(coro))

    out = ref._pre_tool_call("send_email", {"text": "x"}, task_id="sess-B")

    assert out is None  # hard bypass
    assert run_calls == []  # async guard path never entered (the spy guard would also raise)
    assert ref._bypass_counts["sess-B"] == 1  # counted without scanning


def test_t4_count_advances_with_window_closed_then_next_window_carries_total(
    spool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The count advances on every call (window open or closed); a later window's
    # heartbeat carries the running cumulative total — decoupled from the 1/window
    # heartbeat cadence.
    ref = _import_reference_plugin()
    _setup_disarmed(ref, monkeypatch)
    # First call opens the window -> 1 event (count 1). Two more in the same window:
    # counted in-process, no new event.
    for _ in range(3):
        ref._pre_tool_call("t", {}, task_id="s")
    assert ref._bypass_counts["s"] == 3
    assert len(_read_spool(spool)) == 1

    # Window reopens (simulate 30s elapsed); the next heartbeat carries the total.
    ref._reset_disarm_log()
    ref._pre_tool_call("t", {}, task_id="s")
    assert ref._bypass_counts["s"] == 4
    events = _read_spool(spool)
    assert len(events) == 2
    assert events[1]["bypassed_count"] == 4  # cumulative, not a per-window delta


def test_t3_counts_bounded_drop_oldest(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _import_reference_plugin()
    _setup_disarmed(ref, monkeypatch)
    monkeypatch.setattr(ref, "_MAX_DISARM_SESSIONS", 3)
    for i in range(5):
        ref._pre_tool_call("t", {}, task_id=f"s{i}")
    assert len(ref._bypass_counts) == 3
    assert set(ref._bypass_counts) == {"s2", "s3", "s4"}  # s0, s1 dropped (oldest)


def test_tconc_concurrent_desktop_agent_single_id(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-138 / edge F-3: _derive_session_id's _session_ids write now
    # runs on the disarm hot path. N threads racing one fresh desktop _agent (empty
    # task_id) must mint exactly ONE id and count every call (locked check-then-set;
    # no split count, no dict-resize error).
    ref = _import_reference_plugin()
    _setup_disarmed(ref, monkeypatch)  # also resets _session_ids + _bypass_counts
    agent = object()
    n = 50
    ids: list[str] = []
    ids_lock = threading.Lock()
    barrier = threading.Barrier(n)

    def worker() -> None:
        barrier.wait()  # maximize contention on the fresh-agent insert
        ref._pre_tool_call("t", {}, task_id="", _agent=agent)
        sid = ref._derive_session_id("", {"_agent": agent})
        with ids_lock:
            ids.append(sid)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(ids)) == 1  # exactly one desktop-* id across all threads
    sid = ids[0]
    assert sid.startswith("desktop-")
    assert len(ref._session_ids) == 1  # one entry for the agent (race collapsed)
    assert ref._bypass_counts[sid] == n  # every call counted, no split


def test_trearm_cumulative_across_rearm(spool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # The per-session count is cumulative across disarm episodes within a session
    # (no reset on re-arm); an armed call does NOT bump the bypass counter.
    ref = _import_reference_plugin()
    _setup_disarmed(ref, monkeypatch)

    ref._pre_tool_call("t", {}, task_id="s")
    ref._pre_tool_call("t", {}, task_id="s")
    assert ref._bypass_counts["s"] == 2

    # Re-arm: an armed (allowed) call must NOT touch the bypass counter.
    monkeypatch.setattr(ref, "_is_armed", lambda: True)
    monkeypatch.setattr(ref, "_guard", type("G", (), {"evaluate": lambda self, *a, **k: None})())
    monkeypatch.setattr(ref, "_run_async", lambda coro: _allowed())
    assert ref._pre_tool_call("t", {}, task_id="s") is None
    assert ref._bypass_counts["s"] == 2  # unchanged by the armed call

    # Disarm again: cumulative continues from 2, not reset.
    monkeypatch.setattr(ref, "_is_armed", lambda: False)
    monkeypatch.setattr(ref, "_guard", type("SpyGuard", (), {"evaluate": _raise_on_scan})())
    ref._reset_disarm_log()
    ref._pre_tool_call("t", {}, task_id="s")
    assert ref._bypass_counts["s"] == 3  # no reset on re-arm
