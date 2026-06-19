"""PET-131: cross-process enforcement-event surfacing on the Observability tab.

The gateway (``reference_plugin._pre_tool_call``) emits a structured enforcement
event onto a file spool beside each block/quarantine/tier3/disarmed-bypass
decision; the dashboard (``ConsoleHandlers``) drains the spool into its
``scan_history`` ring buffer + ``scan_result`` SSE stream so live enforcement
reaches the operator. Each test pins a vector that silently failed before PET-131.

Backend-free: no Presidio / ML pipeline. The guard is stubbed and the spool is
redirected to a temp file via ``_events._reset_events_state``.

Regression for PET-131: enforcement that blocks without surfacing is a trust
failure (the operator is flown blind while ~45% of tool calls are blocked).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("fastapi")

import petasos.console._events as ev  # noqa: E402
from petasos import GuardResult, PetasosConfig, Pipeline, ScanFinding, Severity  # noqa: E402
from petasos.console.server import ConsoleHandlers  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402

if TYPE_CHECKING:
    import types

_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)
_EGRESS = frozenset({"send_email", "http_request", "clipboard_write"})


# ---------------------------------------------------------------------------
# Fixtures / harness
# ---------------------------------------------------------------------------


@pytest.fixture()
def spool() -> str:
    """The per-test enforcement-spool path.

    The autouse ``_isolate_enforcement_spool`` conftest fixture already redirected
    the spool to a throwaway temp path (and restores the override + cap on teardown);
    this returns that path for tests that read/write/assert on the spool directly.
    """
    return ev._spool_path()


@pytest.fixture()
def handlers() -> ConsoleHandlers:
    pipeline = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="degraded"))
    return ConsoleHandlers(pipeline)


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet131", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _guard_result(
    *,
    findings: tuple[ScanFinding, ...] = (),
    tier: str = "none",
    allowed: bool = True,
    reason: str = "allowed",
    param_scan_unsafe: bool = False,
    param_scan_degraded: bool = False,
) -> GuardResult:
    return GuardResult(
        allowed=allowed,
        reason=reason,
        findings=findings,
        tier=tier,
        param_scan_unsafe=param_scan_unsafe,
        param_scan_degraded=param_scan_degraded,
    )


def _finding(finding_type: str, severity: Severity = Severity.HIGH) -> ScanFinding:
    return ScanFinding(
        rule_id=f"petasos.{finding_type}.x",
        finding_type=finding_type,
        severity=severity,
        confidence=0.9,
        message=f"{finding_type} finding",
        scanner_name="minimal" if finding_type != "pii" else "presidio",
    )


def _setup_plugin(ref: Any, monkeypatch: pytest.MonkeyPatch, *, armed: bool = True) -> None:
    monkeypatch.setattr(ref, "_initialized", True)
    monkeypatch.setattr(ref, "_init_error", None)
    monkeypatch.setattr(ref, "_is_armed", lambda: armed)
    monkeypatch.setattr(ref, "_egress_sink_tools", _EGRESS)
    monkeypatch.setattr(ref, "_guard", type("G", (), {"evaluate": lambda self, *a, **k: None})())
    monkeypatch.setattr(ref, "_maybe_reconfigure", lambda: None)


def _read_spool(path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    out.append(json.loads(s))
    except FileNotFoundError:
        pass
    return out


# ---------------------------------------------------------------------------
# Break 1: every gateway decision emits a structured enforcement event
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "tool", "guard", "expect"),
    [
        (
            "tier3",
            "send_email",
            _guard_result(tier="tier3"),
            {"event_type": "tier3", "tier": "tier3"},
        ),
        (
            "block",
            "send_email",
            _guard_result(allowed=False, reason="blocked by escalation", tier="tier2"),
            {"event_type": "block", "tier": "tier2"},
        ),
        (
            "degraded",
            "send_email",
            _guard_result(param_scan_degraded=True),
            {"event_type": "quarantine"},
        ),
        (
            "non_pii_high",
            "send_email",
            _guard_result(
                findings=(_finding("injection", Severity.HIGH),), param_scan_unsafe=True
            ),
            {"event_type": "quarantine", "severity": "HIGH", "rule_id": "petasos.injection.x"},
        ),
        (
            "pii_egress",
            "send_email",
            _guard_result(findings=(_finding("pii", Severity.CRITICAL),), param_scan_unsafe=True),
            {"event_type": "quarantine", "severity": "CRITICAL"},
        ),
    ],
)
def test_block_emits_enforcement_event(
    spool: str,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    tool: str,
    guard: GuardResult,
    expect: dict[str, Any],
) -> None:
    # The headline regression (Break 1): a _pre_tool_call that blocks emits exactly
    # one enforcement event carrying session + tool + the attribution in scope.
    ref = _import_reference_plugin()
    _setup_plugin(ref, monkeypatch)
    monkeypatch.setattr(ref, "_run_async", lambda coro: guard)

    out = ref._pre_tool_call(tool, {"text": "x"}, task_id="sess-A")
    assert out is not None and out["action"] == "block", f"{kind} should block"

    events = _read_spool(spool)
    assert len(events) == 1, f"{kind}: expected exactly one enforcement event"
    e = events[0]
    assert e["session_id"] == "sess-A"
    assert e["tool"] == tool
    assert e["direction"] == "tool_call"
    assert e["scan_id"].startswith("e-")
    for key, val in expect.items():
        assert e[key] == val, f"{kind}: {key}"


def test_allowed_call_emits_no_event(spool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # A clean pass-through (armed, allowed, no findings) writes nothing to the spool.
    ref = _import_reference_plugin()
    _setup_plugin(ref, monkeypatch)
    monkeypatch.setattr(ref, "_run_async", lambda coro: _guard_result())
    assert ref._pre_tool_call("send_email", {"text": "x"}, task_id="s") is None
    assert _read_spool(spool) == []


# ---------------------------------------------------------------------------
# Break 2: drained events land on the scanHistory surface, not auditLog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforcement_event_reaches_observability_buffer(
    spool: str, handlers: ConsoleHandlers
) -> None:
    ev.emit_enforcement_event(
        {"session_id": "s1", "tool": "send_email", "event_type": "quarantine", "severity": "HIGH"}
    )
    await handlers._drain_enforcement_into_history()

    rows = handlers.scan_history.to_list()
    assert len(rows) == 1
    row = rows[0]
    # Lands on the scanHistory surface the tiles read; tagged enforcement; counts
    # as blocked (safe is False -> the *blocked* tile increments via `safe===false`).
    assert row["source"] == "enforcement"
    assert row["safe"] is False
    assert row["tool"] == "send_email"
    assert row["direction"] == "tool_call"


# ---------------------------------------------------------------------------
# Break 3: surfaced across the process / pipeline-instance boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_observes_gateway_enforcement(spool: str) -> None:
    # The dashboard self-initialized its own host_id="dashboard" pipeline — a separate
    # instance from any gateway pipeline. The event still surfaces because the channel
    # is transport-level (the spool), not pipeline-instance-scoped.
    dash = ConsoleHandlers(
        Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(), host_id="dashboard")
    )
    ev.emit_enforcement_event({"session_id": "s1", "tool": "http_request", "event_type": "block"})
    await dash._drain_enforcement_into_history()
    assert any(r.get("source") == "enforcement" for r in dash.scan_history.to_list())


# ---------------------------------------------------------------------------
# D4: reconciliation — block tally == N == block-class log-line count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_block_count_reconciles_with_log(
    spool: str,
    handlers: ConsoleHandlers,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ref = _import_reference_plugin()
    _setup_plugin(ref, monkeypatch)
    gr = _guard_result(findings=(_finding("injection", Severity.HIGH),), param_scan_unsafe=True)
    monkeypatch.setattr(ref, "_run_async", lambda coro: gr)

    n = 5
    with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
        for _ in range(n):
            ref._pre_tool_call("send_email", {"text": "x"}, task_id="sess-R")

    await handlers._drain_enforcement_into_history()

    log_blocks = sum(
        1
        for rec in caplog.records
        if any(
            p in rec.getMessage() for p in ("PETASOS_QUARANTINE", "PETASOS_BLOCK", "PETASOS_TIER3")
        )
        and "sess-R" in rec.getMessage()
    )
    assert log_blocks == n
    assert handlers.block_tally_for("sess-R") == n
    assert len(_read_spool(spool)) == n


@pytest.mark.asyncio
async def test_block_count_survives_ring_eviction(spool: str, handlers: ConsoleHandlers) -> None:
    # The per-session tally is independent of the 500-entry ring's eviction — the
    # case that distinguishes the running tally from a buffer-scoped count (D4).
    n = 560
    for _ in range(n):
        ev.emit_enforcement_event(
            {"session_id": "sess-long", "tool": "send_email", "event_type": "quarantine"}
        )
    await handlers._drain_enforcement_into_history()

    assert len(handlers.scan_history.to_list()) == 500  # ring evicted to its cap
    assert handlers.block_tally_for("sess-long") == n  # tally survived the rollover


# ---------------------------------------------------------------------------
# Independence from armed state (PET-130 tie-in) + across profiles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observability_correct_when_disarmed(
    spool: str, handlers: ConsoleHandlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _import_reference_plugin()
    _setup_plugin(ref, monkeypatch, armed=False)
    ref._reset_disarm_log()

    # A burst of disarmed pass-throughs in one 30s window emits exactly ONE
    # distinguishable bypassed_disarmed event (1:1 with the PETASOS_DISARMED log line).
    for _ in range(4):
        assert ref._pre_tool_call("send_email", {"text": "x"}, task_id="sess-D") is None

    events = _read_spool(spool)
    assert len(events) == 1
    assert events[0]["event_type"] == "bypassed_disarmed"
    assert events[0]["armed"] is False

    await handlers._drain_enforcement_into_history()
    rows = handlers.scan_history.to_list()
    assert len(rows) == 1
    assert rows[0]["safe"] is True  # a bypass is visible but NOT counted as blocked
    assert handlers.block_tally_for("sess-D") == 0  # the bypass does not move the tally


# ---------------------------------------------------------------------------
# PET-137: the F3 correction, frozen — disarmed is a HARD bypass (no scan runs)
# ---------------------------------------------------------------------------


def test_disarmed_pre_tool_call_runs_no_scan(spool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-137: a disarmed _pre_tool_call performs NO scan — _guard.evaluate
    # is never called, the async guard path is never entered, and the call returns None (a
    # hard bypass). Freezes the fact the optimistic first pass got wrong ("disarmed still
    # scans") so no future change silently reintroduces it. The emitted heartbeat carries
    # only tool/event_type/armed; the structured-decision fields stay unset.
    ref = _import_reference_plugin()
    _setup_plugin(ref, monkeypatch, armed=False)
    ref._reset_disarm_log()

    eval_calls: list[Any] = []
    run_calls: list[Any] = []
    monkeypatch.setattr(
        ref,
        "_guard",
        type("SpyGuard", (), {"evaluate": lambda self, *a, **k: eval_calls.append(a)})(),
    )
    monkeypatch.setattr(ref, "_run_async", lambda coro: run_calls.append(coro))

    out = ref._pre_tool_call("send_email", {"text": "x"}, task_id="sess-D")

    assert out is None  # hard bypass: no decision returned
    assert eval_calls == []  # NO scan ran
    assert run_calls == []  # the async guard path was never entered

    events = _read_spool(spool)
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "bypassed_disarmed"
    assert e["armed"] is False
    assert e["tool"] == "send_email"
    # Structured-decision fields are unset (the emit helper always builds the full dict,
    # so assert field VALUES, not key-set equality).
    assert e["rule_id"] is None
    assert e["severity"] is None
    assert e["reason"] == ""


def test_armed_pre_tool_call_invokes_guard_evaluate(
    spool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pins the D6 invariant precondition: the armed branch DOES run the guard. A block-class
    # event can only be emitted after a real _guard.evaluate (which only runs while armed),
    # so armed-at-decision is soundly derivable from event_type as a fallback.
    ref = _import_reference_plugin()
    _setup_plugin(ref, monkeypatch, armed=True)

    eval_calls: list[Any] = []
    monkeypatch.setattr(
        ref,
        "_guard",
        type("SpyGuard", (), {"evaluate": lambda self, *a, **k: eval_calls.append(a)})(),
    )
    # _run_async ignores the (recorded) coroutine arg and returns an allowed result.
    monkeypatch.setattr(ref, "_run_async", lambda coro: _guard_result())

    ref._pre_tool_call("send_email", {"text": "x"}, task_id="sess-E")
    assert eval_calls, "_guard.evaluate must run on the armed branch"


@pytest.mark.asyncio
async def test_observability_correct_across_profiles(
    spool: str, handlers: ConsoleHandlers
) -> None:
    # No profile-scoped filtering on the event path: enforcement from a non-default
    # profile's session surfaces identically and tallies independently.
    for sess in ("default-sess", "gibson-sess"):
        ev.emit_enforcement_event(
            {"session_id": sess, "tool": "send_email", "event_type": "quarantine"}
        )
    await handlers._drain_enforcement_into_history()
    assert handlers.block_tally_for("default-sess") == 1
    assert handlers.block_tally_for("gibson-sess") == 1
    assert len(handlers.scan_history.to_list()) == 2


# ---------------------------------------------------------------------------
# D5: fail-open telemetry floor
# ---------------------------------------------------------------------------


def test_telemetry_emission_never_blocks_toolcall(
    spool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _import_reference_plugin()
    _setup_plugin(ref, monkeypatch)
    gr = _guard_result(findings=(_finding("injection", Severity.HIGH),), param_scan_unsafe=True)
    monkeypatch.setattr(ref, "_run_async", lambda coro: gr)

    # A raising sink must not change the verdict nor throw out of _pre_tool_call.
    def _boom(event: dict[str, Any]) -> bool:
        raise RuntimeError("spool on fire")

    monkeypatch.setattr(ev, "emit_enforcement_event", _boom)
    out = ref._pre_tool_call("send_email", {"text": "x"}, task_id="s")
    assert out is not None and out["action"] == "block"

    # A slow sink must also leave the verdict and the call path intact.
    import time as _time

    def _slow(event: dict[str, Any]) -> bool:
        _time.sleep(0.02)
        return False

    monkeypatch.setattr(ev, "emit_enforcement_event", _slow)
    out2 = ref._pre_tool_call("send_email", {"text": "x"}, task_id="s")
    assert out2 is not None and out2["action"] == "block"


# ---------------------------------------------------------------------------
# Spool primitive: bounding, rotation, restart, paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforcement_spool_bounded(spool: str, handlers: ConsoleHandlers) -> None:
    # A tiny cap forces reader-owned rotation; every event still surfaces exactly once
    # and the live spool is bounded (rotated away), not grown without bound.
    ev.SPOOL_CAP_BYTES = 1
    n = 10
    ids = []
    for i in range(n):
        ev.emit_enforcement_event(
            {"scan_id": f"e-{i:04d}", "session_id": "s", "tool": "t", "event_type": "quarantine"}
        )
        ids.append(f"e-{i:04d}")
    await handlers._drain_enforcement_into_history()

    surfaced = [r["scan_id"] for r in handlers.scan_history.to_list()]
    assert sorted(surfaced) == sorted(ids)  # all n, none lost, none duplicated
    assert ev.spool_size(spool) == 0  # rotated + cleared -> live spool bounded


@pytest.mark.asyncio
async def test_enforcement_survives_gateway_seq_reset(
    spool: str, handlers: ConsoleHandlers
) -> None:
    # The reader cursors on a byte offset, not a producer seq. A gateway restart
    # (its per-process counter resetting) cannot make the dashboard drop new events:
    # appends simply continue and the byte offset advances past them.
    for i in range(3):
        ev.emit_enforcement_event(
            {"scan_id": f"e-a{i}", "session_id": "s", "tool": "t", "event_type": "block"}
        )
    await handlers._drain_enforcement_into_history()
    assert len(handlers.scan_history.to_list()) == 3

    # "Gateway restart": a fresh producer keeps appending to the same spool.
    for i in range(3):
        ev.emit_enforcement_event(
            {"scan_id": f"e-b{i}", "session_id": "s", "tool": "t", "event_type": "block"}
        )
    await handlers._drain_enforcement_into_history()
    ids = {r["scan_id"] for r in handlers.scan_history.to_list()}
    assert ids == {"e-a0", "e-a1", "e-a2", "e-b0", "e-b1", "e-b2"}


@pytest.mark.asyncio
async def test_reader_rotation_captures_inflight_and_no_doublecount(
    spool: str, handlers: ConsoleHandlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A line the gateway appends in the window between the reader's last read and the
    # rename is captured by the .rot drain (forward from the committed offset), not
    # lost; nothing is double-pushed and the tally is unchanged by the rotation.
    ev.SPOOL_CAP_BYTES = 1
    ev.emit_enforcement_event(
        {"scan_id": "e-A", "session_id": "s", "tool": "t", "event_type": "block"}
    )

    orig_rotate = ev.rotate_spool

    def _rotate_with_inflight(path: str | None = None) -> bool:
        # The gateway appends B after the reader's last read but before the rename.
        ev.emit_enforcement_event(
            {"scan_id": "e-B", "session_id": "s", "tool": "t", "event_type": "block"}
        )
        return orig_rotate(path)

    monkeypatch.setattr(ev, "rotate_spool", _rotate_with_inflight)
    await handlers._drain_enforcement_into_history()

    ids = [r["scan_id"] for r in handlers.scan_history.to_list()]
    assert sorted(ids) == ["e-A", "e-B"]  # in-flight B captured, A not re-pushed
    assert handlers.block_tally_for("s") == 2  # exactly two, no rotation double-count


@pytest.mark.asyncio
async def test_orphan_rot_recovered_not_overwritten(spool: str, handlers: ConsoleHandlers) -> None:
    # A .rot left by a reader that crashed mid-rotation is recovered (drained +
    # unlinked) before any new rotation, so its events are never overwritten/lost.
    rot = spool + ev._ROT_SUFFIX
    with open(rot, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({"scan_id": "e-X", "session_id": "s", "tool": "t", "event_type": "block"})
            + "\n"
        )
        f.write(
            json.dumps({"scan_id": "e-Y", "session_id": "s", "tool": "t", "event_type": "block"})
            + "\n"
        )
    ev.emit_enforcement_event(
        {"scan_id": "e-Z", "session_id": "s", "tool": "t", "event_type": "block"}
    )

    await handlers._drain_enforcement_into_history()
    ids = {r["scan_id"] for r in handlers.scan_history.to_list()}
    assert ids == {"e-X", "e-Y", "e-Z"}
    assert not os.path.exists(rot)  # orphan recovered + cleared


@pytest.mark.asyncio
async def test_drain_exactly_once_under_concurrency(spool: str, handlers: ConsoleHandlers) -> None:
    # The background tailer and a concurrent get_scan_history drain against one spool
    # each yield every scan_id exactly once (one asyncio.Lock; forward offset). Includes
    # an over-cap spool so the concurrent path exercises rotation under the lock.
    ev.SPOOL_CAP_BYTES = 1
    for i in range(8):
        ev.emit_enforcement_event(
            {"scan_id": f"e-{i}", "session_id": "s", "tool": "t", "event_type": "block"}
        )

    await asyncio.gather(
        handlers._drain_enforcement_into_history(),
        handlers._drain_enforcement_into_history(),
        handlers.get_scan_history(),
    )
    ids = [r["scan_id"] for r in handlers.scan_history.to_list()]
    assert sorted(ids) == [f"e-{i}" for i in range(8)]  # each exactly once
    assert handlers.block_tally_for("s") == 8


@pytest.mark.asyncio
async def test_enforcement_visible_on_polling_fallback(
    spool: str, handlers: ConsoleHandlers
) -> None:
    # Drain-on-read: get_scan_history surfaces enforcement with no live SSE and no
    # background tailer running (the gated-mode polling fallback floor, PET-83).
    ev.emit_enforcement_event(
        {"session_id": "s", "tool": "send_email", "event_type": "quarantine"}
    )
    res = await handlers.get_scan_history()
    assert any(e.get("source") == "enforcement" for e in res["entries"])


@pytest.mark.asyncio
async def test_live_enforcement_row_survives_a_poll(spool: str, handlers: ConsoleHandlers) -> None:
    # A row delivered "live" (drain) is still present after a subsequent poll, because
    # the server ring is the single source of truth and get_scan_history serves it.
    ev.emit_enforcement_event(
        {"scan_id": "e-live", "session_id": "s", "tool": "t", "event_type": "block"}
    )
    await handlers._drain_enforcement_into_history()
    res = await handlers.get_scan_history()
    assert any(e.get("scan_id") == "e-live" for e in res["entries"])


@pytest.mark.asyncio
async def test_enforcement_visible_via_embedded_plugin_route(
    spool: str, handlers: ConsoleHandlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The embedded Hermes plugin route delegates to the same drained get_scan_history,
    # so the D-WIN gated-Windows floor holds with no FastAPI startup tailer.
    import petasos.console.hermes.plugin_api as papi

    monkeypatch.setattr(papi, "_require_handlers", lambda: handlers)
    ev.emit_enforcement_event({"session_id": "s", "tool": "send_email", "event_type": "block"})
    res = await papi.get_scan_history(100)
    assert any(e.get("source") == "enforcement" for e in res["entries"])


def test_spool_path_identical_under_dangling_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Gateway-emit and dashboard-drain resolve to the SAME spool file even under a
    # dangling active_profile (root-tier fallback), because both compute the path from
    # the one resolve_hermes_config_path() recomputed per call.
    from petasos.console._paths import HermesConfigResolution

    ev._reset_events_state(None)  # use the real resolver path for this test
    root_cfg = tmp_path / "config.yaml"
    res = HermesConfigResolution(path=root_cfg, tier="root", warning="active_profile dangling")
    monkeypatch.setattr(ev, "resolve_hermes_config_path", lambda: res)

    p1 = ev._spool_path()  # "gateway"
    p2 = ev._spool_path()  # "dashboard"
    assert p1 == p2 == os.path.join(str(tmp_path), ev._SPOOL_FILENAME)


# ---------------------------------------------------------------------------
# CodeRabbit follow-ups (PR #117)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spool_path_change_resets_offset(handlers: ConsoleHandlers, tmp_path: Path) -> None:
    # A Hermes profile/config path switch points the drain at a different (smaller)
    # spool. The stale byte offset must reset to 0 so the new spool's events are not
    # skipped (CodeRabbit PR #117).
    p1 = str(tmp_path / "a.jsonl")
    ev._reset_events_state(p1)
    ev.emit_enforcement_event(
        {"scan_id": "e-1", "session_id": "s", "tool": "t", "event_type": "block"}
    )
    await handlers._drain_enforcement_into_history()
    assert {r["scan_id"] for r in handlers.scan_history.to_list()} == {"e-1"}

    p2 = str(tmp_path / "b.jsonl")  # a fresh, smaller spool at a new path
    ev._reset_events_state(p2)
    ev.emit_enforcement_event(
        {"scan_id": "e-2", "session_id": "s", "tool": "t", "event_type": "block"}
    )
    await handlers._drain_enforcement_into_history()
    # Without the offset reset, the stale (larger) offset would skip e-2.
    assert "e-2" in {r["scan_id"] for r in handlers.scan_history.to_list()}


@pytest.mark.asyncio
async def test_long_reason_is_capped(spool: str, handlers: ConsoleHandlers) -> None:
    # A long scanner/guard message must not bloat the ring buffer / SSE frame
    # (CodeRabbit PR #117). The raw matched value is never in `reason` to begin with.
    ev.emit_enforcement_event(
        {"session_id": "s", "tool": "t", "event_type": "quarantine", "reason": "x" * 500}
    )
    await handlers._drain_enforcement_into_history()
    assert len(handlers.scan_history.to_list()[0]["reason"]) == 200


def test_fallback_init_window_block_emits_event(
    spool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A cold-start (init-window) block via _fallback_pre_tool_call is still a gateway
    # block and must surface to the operator (CodeRabbit PR #117).
    ref = _import_reference_plugin()
    monkeypatch.setattr(ref, "_init_error", None)
    monkeypatch.setattr(ref, "_is_armed", lambda: True)
    monkeypatch.setattr(ref, "_maybe_reconfigure", lambda: None)
    monkeypatch.setattr(ref, "_ensure_initialized", lambda: False)  # init in progress
    monkeypatch.setattr(
        ref, "_get_fallback_scanner", lambda: type("S", (), {"scan": lambda self, *a, **k: None})()
    )
    scan_result = type("R", (), {"findings": (_finding("injection", Severity.CRITICAL),)})()
    monkeypatch.setattr(ref, "_run_async", lambda coro: scan_result)

    out = ref._pre_tool_call("send_email", {"text": "x"}, task_id="sess-F")
    assert out is not None and out["action"] == "block"
    events = _read_spool(spool)
    assert len(events) == 1
    assert events[0]["event_type"] == "quarantine"
    assert events[0]["session_id"] == "sess-F"
    assert events[0]["tool"] == "send_email"
    assert events[0]["rule_id"] == "petasos.injection.x"


# ---------------------------------------------------------------------------
# PET-138: per-session disarmed-bypass counter — event payload, dashboard tally,
# summary passthrough, and the cross-process (both-modes) round trip.
# ---------------------------------------------------------------------------


def _emit_bypass(session_id: str, **kw: Any) -> None:
    """Emit a bypassed_disarmed event directly onto the spool (dashboard-side tests)."""
    ev.emit_enforcement_event(
        {
            "session_id": session_id,
            "tool": "send_email",
            "event_type": "bypassed_disarmed",
            "armed": False,
            **kw,
        }
    )


def test_bypassed_event_carries_count(spool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # PET-138 (T5): the bypassed_disarmed heartbeat carries an integer
    # bypassed_count >= 1 alongside tool/event_type/armed, and no matched_text leaks.
    ref = _import_reference_plugin()
    _setup_plugin(ref, monkeypatch, armed=False)
    ref._reset_disarm_log()
    ref._reset_bypass_counts()

    assert ref._pre_tool_call("send_email", {"text": "x"}, task_id="sess-C") is None

    events = _read_spool(spool)
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "bypassed_disarmed"
    assert isinstance(e["bypassed_count"], int) and not isinstance(e["bypassed_count"], bool)
    assert e["bypassed_count"] >= 1
    assert "matched_text" not in e


@pytest.mark.asyncio
async def test_bypass_tally_monotonic_max_and_isolated(
    spool: str, handlers: ConsoleHandlers
) -> None:
    # PET-138 (T6): the dashboard bypass tally takes the monotonic max of the carried
    # cumulative count, ignores non-int / bool / zero, and is isolated from the block
    # tally (both directions).
    _emit_bypass("s", bypassed_count=3)
    _emit_bypass("s", bypassed_count=7)
    _emit_bypass("s", bypassed_count=5)  # re-surfaced lower value must NOT lower it
    _emit_bypass("s", bypassed_count=True)  # bool ignored (isinstance(True, int) is True)
    _emit_bypass("s", bypassed_count=0)  # zero ignored (no-op slot)
    await handlers._drain_enforcement_into_history()
    assert handlers.bypass_tally_for("s") == 7
    assert handlers.block_tally_for("s") == 0  # a bypass never touches the block tally

    # And a block event never touches the bypass tally.
    ev.emit_enforcement_event({"session_id": "s", "tool": "t", "event_type": "block"})
    await handlers._drain_enforcement_into_history()
    assert handlers.bypass_tally_for("s") == 7
    assert handlers.block_tally_for("s") == 1


@pytest.mark.asyncio
async def test_bypass_tally_refresh_preserves_insertion_order(
    spool: str, handlers: ConsoleHandlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PET-138 (T6): refreshing an existing session's tally must assign IN PLACE (not
    # del+reinsert), so drop-oldest still evicts the genuine oldest. A del+reinsert
    # bug would move the refreshed key to the end and evict the wrong session.
    import petasos.console.server as srv

    monkeypatch.setattr(srv, "_MAX_TALLY_SESSIONS", 2)
    _emit_bypass("s0", bypassed_count=1)
    _emit_bypass("s1", bypassed_count=1)
    await handlers._drain_enforcement_into_history()
    _emit_bypass("s0", bypassed_count=9)  # refresh the OLDEST key (must not move it)
    await handlers._drain_enforcement_into_history()
    _emit_bypass("s2", bypassed_count=1)  # over bound -> drop genuine oldest (s0)
    await handlers._drain_enforcement_into_history()

    assert handlers.bypass_tally_for("s0") == 0  # s0 evicted despite the refresh
    assert handlers.bypass_tally_for("s1") == 1
    assert handlers.bypass_tally_for("s2") == 1


def test_enforcement_summary_normalizes_bypassed_count() -> None:
    # PET-138 (T7): _enforcement_summary passes a positive int through, normalizes
    # any non-int / bool / non-positive to None, keeps safe=True / finding_count=0,
    # and never carries matched_text.
    from petasos.console.server import _enforcement_summary

    ok = _enforcement_summary(
        {"event_type": "bypassed_disarmed", "session_id": "s", "bypassed_count": 4, "armed": False}
    )
    assert ok["bypassed_count"] == 4
    assert ok["safe"] is True and ok["finding_count"] == 0
    assert "matched_text" not in ok

    for bad in (0, -1, 3.5, True, "4", None):
        s = _enforcement_summary({"event_type": "bypassed_disarmed", "bypassed_count": bad})
        assert s["bypassed_count"] is None, f"{bad!r} should normalize to None"

    # A block event has no bypassed_count -> None.
    assert _enforcement_summary({"event_type": "block"})["bypassed_count"] is None


@pytest.mark.asyncio
async def test_bypass_count_round_trips_in_process(
    spool: str, handlers: ConsoleHandlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PET-138 (T-plugin-mode): the plugin emit -> spool -> dashboard drain -> tally
    # path is identical in standalone and Hermes-plugin modes. Exercise it end-to-end
    # in-process, satisfying the brief's "both modes" recurrence test via the shared
    # drain path.
    ref = _import_reference_plugin()
    _setup_plugin(ref, monkeypatch, armed=False)
    ref._reset_disarm_log()
    ref._reset_bypass_counts()

    assert ref._pre_tool_call("send_email", {"text": "x"}, task_id="sess-P") is None
    await handlers._drain_enforcement_into_history()

    assert handlers.bypass_tally_for("sess-P") == 1
    rows = handlers.scan_history.to_list()
    assert rows[0]["bypassed_count"] == 1
    assert rows[0]["safe"] is True
