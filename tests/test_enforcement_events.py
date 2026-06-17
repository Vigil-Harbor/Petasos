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
