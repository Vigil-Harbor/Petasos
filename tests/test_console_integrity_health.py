"""PET-157: the self-diagnosing ``get_health["integrity"]`` field.

Today an all-Unverified Observability board is, from the UI alone, indistinguishable between
the benign config-skew case and a genuinely forged row. This field surfaces the discriminator
the system already computes (``sig-missing`` vs ``sig-mismatch``), the dominant verdict over a
bounded recent window, and the actionable remediation, so an operator can tell integrity
off-vs-on and (when on) genuine vs legacy-unsigned vs actively-mismatched without grepping the
WARNING log. No verification math changes (D1).

Harness mirrors ``tests/test_enforcement_integrity.py`` (the ``_keyed_handlers`` /
``_unkeyed_handlers`` / ``_block`` / ``_append_raw`` / ``_drain`` helpers). The enforcement spool +
history sink are redirected to temp files by the autouse conftest fixtures; the writer key is
reset around each test here.
Async tests bind to the anyio runner via ``anyio_mode = "auto"`` (no inline marker, PET-149).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

import petasos.console._events as ev
import petasos.console.server as server_mod
from petasos import PetasosConfig, Pipeline
from petasos.console.server import ConsoleHandlers
from petasos.scanners.minimal import MinimalScanner

_SECRET = b"pet157-session-secret-0123456789ABCDEF"


@pytest.fixture(autouse=True)
def _reset_spool_key_around_test() -> Iterator[None]:
    """Contain the module-global writer key within each test (the conftest spool-isolation
    fixture resets path/cap but not the key)."""
    ev._reset_spool_key()
    yield
    ev._reset_spool_key()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _keyed_handlers(secret: bytes = _SECRET) -> ConsoleHandlers:
    pipeline = Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded", session_secret=secret),
        host_id="petasos-test",  # required when session_secret is set
    )
    return ConsoleHandlers(pipeline)


def _unkeyed_handlers() -> ConsoleHandlers:
    pipeline = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="degraded"))
    return ConsoleHandlers(pipeline)


def _append_raw(path: str, rec: dict[str, Any]) -> None:
    """Append a raw JSON line (bypasses emit's signing — for forged / legacy lines)."""
    import json

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _block(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "sess-1",
        "tool": "send_email",
        "event_type": "block",
        "tier": "tier2",
        "reason": "blocked by escalation",
        "armed": True,
        "direction": "tool_call",
    }
    base.update(over)
    return base


async def _drain(h: ConsoleHandlers) -> None:
    await h._drain_enforcement_into_history()


async def _integrity_of(h: ConsoleHandlers) -> dict[str, Any]:
    health = await h.get_health()
    assert "integrity" in health, "get_health must carry the additive integrity field"
    return health["integrity"]


# ---------------------------------------------------------------------------
# State 1 — all-genuine
# ---------------------------------------------------------------------------


async def test_all_genuine_reports_genuine_no_remediation() -> None:
    ev.set_spool_key(_SECRET)
    for i in range(3):
        ev.emit_enforcement_event(_block(session_id="sess-A", scan_id=f"e-g{i}"))
    handlers = _keyed_handlers()
    await _drain(handlers)
    integ = await _integrity_of(handlers)
    assert integ["key_on"] is True
    assert integ["dominant_verdict"] == "genuine"
    assert integ["failure_class"] is None
    assert integ["remediation"] is None
    assert integ["counts"]["genuine"] == 3
    assert integ["counts"]["unverifiable"] == 0
    assert integ["window_size"] == 3


# ---------------------------------------------------------------------------
# State 2 — sig-missing (legacy/unsigned writer under a configured key)
# ---------------------------------------------------------------------------


async def test_sig_missing_reports_unverifiable_with_upgrade_remediation() -> None:
    handlers = _keyed_handlers()
    path = ev._spool_path()
    for i in range(2):
        _append_raw(path, _block(session_id="sess-M", scan_id=f"e-m{i}"))  # no sig
    await _drain(handlers)
    integ = await _integrity_of(handlers)
    assert integ["key_on"] is True
    assert integ["dominant_verdict"] == "unverifiable"
    assert integ["failure_class"] == "sig-missing"
    assert integ["counts"]["unverifiable"] == 2
    rem = integ["remediation"]
    assert rem == server_mod._INTEGRITY_REMEDIATION["sig-missing"]
    assert "upgrade the writer" in rem
    assert "PETASOS_SESSION_SECRET" in rem


# ---------------------------------------------------------------------------
# State 3 — sig-mismatch (must NOT assert forgery; names config skew)
# ---------------------------------------------------------------------------


async def test_sig_mismatch_reports_align_secret_and_does_not_assert_forgery() -> None:
    handlers = _keyed_handlers()
    path = ev._spool_path()
    for i in range(2):
        _append_raw(path, _block(session_id="sess-X", scan_id=f"e-x{i}", sig="0" * 64))
    await _drain(handlers)
    integ = await _integrity_of(handlers)
    assert integ["dominant_verdict"] == "unverifiable"
    assert integ["failure_class"] == "sig-mismatch"
    rem = integ["remediation"]
    assert rem == server_mod._INTEGRITY_REMEDIATION["sig-mismatch"]
    assert "PETASOS_SESSION_SECRET" in rem
    assert "restart" in rem
    # Does NOT flatly assert forgery: it names config skew as the *likely* cause and hedges
    # the forgery possibility ("rare but possible"), per D9 / brief other-implications bullet 1.
    assert "most likely" in rem
    assert "rare but possible" in rem


# ---------------------------------------------------------------------------
# State 4 — key-off (no alarm, no preflight)
# ---------------------------------------------------------------------------


async def test_key_off_reports_off_no_alarm_no_preflight(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ev._reset_spool_key()  # writer key off too
    handlers = _unkeyed_handlers()
    ev.emit_enforcement_event(_block(session_id="sess-K"))
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        await _drain(handlers)
    integ = await _integrity_of(handlers)
    assert integ["key_on"] is False
    assert integ["dominant_verdict"] == "unattested"  # never "unverifiable" with key off
    assert integ["failure_class"] is None
    assert integ["counts"]["unattested"] == 1
    assert integ["counts"]["unverifiable"] == 0
    assert integ["counts"]["genuine"] == 0
    # Mode-neutral invalid-base64 note, never an alarm.
    assert integ["remediation"] == server_mod._INTEGRITY_KEY_OFF_NOTE
    assert "not be valid base64" in integ["remediation"]
    assert handlers._integrity_preflight_emitted is False
    assert "PETASOS_INTEGRITY_PREFLIGHT" not in caplog.text


# ---------------------------------------------------------------------------
# State 5 — cry-wolf visibility in-window (one bad row among genuines)
# ---------------------------------------------------------------------------


async def test_cry_wolf_single_bad_row_visible_in_counts() -> None:
    ev.set_spool_key(_SECRET)
    handlers = _keyed_handlers()
    path = ev._spool_path()
    for i in range(8):
        ev.emit_enforcement_event(_block(session_id="sess-W", scan_id=f"e-ok{i}"))
    _append_raw(path, _block(session_id="sess-W", scan_id="e-bad", sig="0" * 64))
    await _drain(handlers)
    integ = await _integrity_of(handlers)
    # Dominant stays genuine, but the single recent bad row is NOT masked.
    assert integ["dominant_verdict"] == "genuine"
    assert integ["counts"]["genuine"] == 8
    assert integ["counts"]["unverifiable"] == 1


# ---------------------------------------------------------------------------
# State 5b — cry-wolf durability across window churn (D8 eviction trade-off)
# ---------------------------------------------------------------------------


async def test_cry_wolf_durable_across_window_eviction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # One sig-mismatch (oldest), then _INTEGRITY_WINDOW + 1 genuine rows so the mismatch tuple
    # ages out of the bounded window. The 257-row DRIVE (not a monkeypatched smaller window):
    # deque(maxlen=...) binds maxlen at __init__ construction, so a post-construction monkeypatch
    # would silently leave maxlen=256 and pass vacuously (round-2 edge F-2).
    ev.set_spool_key(_SECRET)
    handlers = _keyed_handlers()
    path = ev._spool_path()
    _append_raw(path, _block(session_id="sess-D", scan_id="e-mm", sig="0" * 64))  # oldest
    for i in range(server_mod._INTEGRITY_WINDOW + 1):  # 257 genuine, newest
        ev.emit_enforcement_event(_block(session_id="sess-D", scan_id=f"e-d{i}"))
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        await _drain(handlers)
    integ = await _integrity_of(handlers)
    # The window honestly ages the mismatch out of the live counts...
    assert integ["counts"]["unverifiable"] == 0
    assert integ["window_size"] == server_mod._INTEGRITY_WINDOW
    # ...but the DURABLE record survived: the one-shot preflight fired and never un-fires.
    assert handlers._integrity_preflight_emitted is True
    preflight = [r for r in caplog.records if "PETASOS_INTEGRITY_PREFLIGHT" in r.getMessage()]
    assert len(preflight) == 1


# ---------------------------------------------------------------------------
# State 6 — empty window (fresh keyed handler, no drain)
# ---------------------------------------------------------------------------


async def test_empty_window_reports_key_on_null_verdict() -> None:
    handlers = _keyed_handlers()
    integ = await _integrity_of(handlers)
    assert integ["key_on"] is True
    assert integ["dominant_verdict"] is None
    assert integ["failure_class"] is None
    assert integ["remediation"] is None
    assert integ["counts"] == {"genuine": 0, "unattested": 0, "unverifiable": 0}
    assert integ["window_size"] == 0


# ---------------------------------------------------------------------------
# State 7 — failure-class agreement: the health field and the D3 helper cannot disagree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row", "expected_class"),
    [
        (_block(session_id="sess-fc1", scan_id="e-fc1"), "sig-missing"),  # no sig
        (_block(session_id="sess-fc2", scan_id="e-fc2", sig="deadbeef"), "sig-mismatch"),
    ],
)
async def test_failure_class_health_field_agrees_with_helper(
    row: dict[str, Any], expected_class: str, caplog: pytest.LogCaptureFixture
) -> None:
    # Fresh keyed handler + exactly one row of the class (a single-row window, so the dominant
    # failure_class is unambiguous). The log path AND the health field both consume the D3
    # helper, so asserting the health field against the helper directly is the robust form.
    handlers = _keyed_handlers()
    handlers._integrity_log_last = 0.0  # ensure the per-row tripwire window is open
    _append_raw(ev._spool_path(), row)
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        await _drain(handlers)
    integ = await _integrity_of(handlers)
    assert integ["failure_class"] == ev.classify_integrity_failure(row) == expected_class
    # Companion: the single drained row's per-row tripwire names the same class.
    assert f"class={expected_class}" in caplog.text


# ---------------------------------------------------------------------------
# State 8 — characterization: classifier + tally byte-identical pre/post (D1)
# ---------------------------------------------------------------------------


async def test_characterization_provenance_and_tally_unchanged() -> None:
    # genuine -> tally bumps; unverifiable -> tally does NOT; unattested -> bumps. Guards
    # against the accumulator/preflight additions perturbing the classifier or the trust tally.

    # genuine (keyed, signed)
    ev.set_spool_key(_SECRET)
    ev.emit_enforcement_event(_block(session_id="sess-gen", scan_id="e-c-gen"))
    h_gen = _keyed_handlers()
    await _drain(h_gen)
    gen = h_gen.scan_history.to_list(500)[-1]
    assert gen["provenance"] == "genuine"
    assert h_gen.block_tally_for("sess-gen") == 1

    # unverifiable (keyed, bad sig) — surfaced but NOT tallied
    h_unv = _keyed_handlers()
    _append_raw(ev._spool_path(), _block(session_id="sess-unv", scan_id="e-c-unv", sig="0" * 64))
    await _drain(h_unv)
    unv = next(s for s in h_unv.scan_history.to_list(500) if s.get("scan_id") == "e-c-unv")
    assert unv["provenance"] == "unverifiable"
    assert h_unv.block_tally_for("sess-unv") == 0

    # unattested (key off) — surfaced AND tallied, exactly as pre-PET-139/157
    ev._reset_spool_key()
    h_un = _unkeyed_handlers()
    ev.emit_enforcement_event(_block(session_id="sess-un", scan_id="e-c-un"))
    await _drain(h_un)
    un = next(s for s in h_un.scan_history.to_list(500) if s.get("scan_id") == "e-c-un")
    assert un["provenance"] == "unattested"
    assert h_un.block_tally_for("sess-un") == 1
