"""PET-139: keyed-HMAC attestation on the cross-process enforcement spool.

The gateway (writer) stamps each enforcement event with an HMAC over a canonical
serialization of the record; the dashboard (reader) recomputes and verifies before
trusting the row. A row that fails verification is surfaced but flagged ``unverifiable``
and is never counted as a trusted block. With no ``session_secret`` configured integrity
is off and behavior is exactly pre-PET-139 (``unattested``, still counted) — the PET-131
no-regression path.

These tests cover both construction paths (standalone ``build_app``-style direct
``ConsoleHandlers`` and the embedded ``plugin_api.init_handlers`` path), the writer/reader
round-trip, the forgery/legacy-unsigned/replay cases, the fail-safe/fail-open posture, and
key-derivation domain separation. The enforcement spool is redirected to a temp file by the
autouse ``_isolate_enforcement_spool`` conftest fixture; the writer key is reset around each
test here so it never leaks across tests (the conftest fixture only resets path/cap).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

import petasos.console._events as ev
import petasos.console.server as server_mod
from petasos import PetasosConfig, Pipeline
from petasos.console.hermes import plugin_api
from petasos.console.server import ConsoleHandlers
from petasos.scanners.minimal import MinimalScanner

# A real 32-byte-ish secret; both the writer (set_spool_key) and the reader
# (PetasosConfig.session_secret) derive their key from THIS value, so they agree.
_SECRET = b"pet139-session-secret-0123456789ABCDEF"


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
    """A reader whose pipeline config carries *secret* (key on)."""
    pipeline = Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded", session_secret=secret),
        host_id="petasos-test",  # required when session_secret is set
    )
    return ConsoleHandlers(pipeline)


def _unkeyed_handlers() -> ConsoleHandlers:
    """A reader with no session_secret (key off → unattested)."""
    pipeline = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="degraded"))
    return ConsoleHandlers(pipeline)


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


def _append_raw(path: str, rec: dict[str, Any]) -> None:
    """Append a raw JSON line (bypasses emit's signing — for forged / legacy lines)."""
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


async def _drain(h: ConsoleHandlers) -> list[dict[str, Any]]:
    await h._drain_enforcement_into_history()
    return h.scan_history.to_list(500)


def _find(summaries: list[dict[str, Any]], **match: Any) -> dict[str, Any]:
    for s in summaries:
        if all(s.get(k) == v for k, v in match.items()):
            return s
    raise AssertionError(f"no summary matching {match} in {summaries}")


# ---------------------------------------------------------------------------
# Writer: keyed write stamps a real sig on disk (silent no-op guard, D6)
# ---------------------------------------------------------------------------


def test_keyed_write_produces_nonempty_sig_on_disk() -> None:
    # Asserts the LITERAL on-disk line carries a `sig` string — catches a swallowed
    # NameError from a missing `import hmac` (which would write unsigned forever).
    ev.set_spool_key(_SECRET)
    assert ev.emit_enforcement_event(_block()) is True
    rows = _read_spool(ev._spool_path())
    assert len(rows) == 1
    assert isinstance(rows[0].get("sig"), str) and rows[0]["sig"], "keyed write must stamp a sig"


def test_unkeyed_write_stamps_no_sig() -> None:
    ev._reset_spool_key()
    assert ev.emit_enforcement_event(_block()) is True
    rows = _read_spool(ev._spool_path())
    assert len(rows) == 1
    assert "sig" not in rows[0]


def test_sig_is_the_only_added_record_field() -> None:
    # Compare an unkeyed vs a keyed write of the IDENTICAL payload (fixed scan_id/timestamp):
    # the only key PET-139 adds is `sig`. No matched_text, no other new field.
    path = ev._spool_path()
    payload = _block(scan_id="e-fixed", timestamp=1.0)
    ev._reset_spool_key()
    ev.emit_enforcement_event(dict(payload))
    ev.set_spool_key(_SECRET)
    ev.emit_enforcement_event(dict(payload))
    rows = _read_spool(path)
    assert set(rows[1]) - set(rows[0]) == {"sig"}


# ---------------------------------------------------------------------------
# Reader: genuine round-trips in both construction paths (D5)
# ---------------------------------------------------------------------------


async def test_genuine_event_round_trips_direct_construction() -> None:
    ev.set_spool_key(_SECRET)
    ev.emit_enforcement_event(_block(session_id="sess-A"))
    handlers = _keyed_handlers()
    summaries = await _drain(handlers)
    s = _find(summaries, event_type="block", session_id="sess-A")
    assert s["provenance"] == "genuine"
    assert handlers.block_tally_for("sess-A") == 1


async def test_genuine_event_round_trips_embedded_drain_on_read() -> None:
    # The embedded Hermes path: plugin_api.init_handlers(pipeline) -> ConsoleHandlers(pipeline),
    # surfaced through get_scan_history's drain-on-read (server.py drain-on-read floor).
    ev.set_spool_key(_SECRET)
    ev.emit_enforcement_event(_block(session_id="sess-B"))
    pipeline = Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded", session_secret=_SECRET),
        host_id="dashboard",
    )
    plugin_api.init_handlers(pipeline)
    handlers = plugin_api._handlers
    assert handlers._spool_key is not None
    await handlers.get_scan_history()  # drains on read
    s = _find(handlers.scan_history.to_list(500), event_type="block", session_id="sess-B")
    assert s["provenance"] == "genuine"
    assert handlers.block_tally_for("sess-B") == 1


# ---------------------------------------------------------------------------
# Reader: attribute always bound — no embedded AttributeError (D6)
# ---------------------------------------------------------------------------


async def test_spool_key_attribute_always_bound_no_secret() -> None:
    handlers = _unkeyed_handlers()
    assert handlers._spool_key is None  # bound, not missing
    ev._reset_spool_key()
    ev.emit_enforcement_event(_block())
    # The drain path must not raise AttributeError on self._spool_key.
    await handlers._drain_enforcement_into_history()


# ---------------------------------------------------------------------------
# No-key deployment still surfaces (PET-131 no-regression)
# ---------------------------------------------------------------------------


async def test_no_key_deployment_surfaces_and_counts(caplog: pytest.LogCaptureFixture) -> None:
    ev._reset_spool_key()  # writer key off too
    handlers = _unkeyed_handlers()
    ev.emit_enforcement_event(_block(session_id="sess-C"))
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        summaries = await _drain(handlers)
    s = _find(summaries, event_type="block", session_id="sess-C")
    assert s["provenance"] == "unattested"
    assert handlers.block_tally_for("sess-C") == 1  # still counted, exactly as pre-PET-139
    assert "PETASOS_INTEGRITY_UNVERIFIABLE" not in caplog.text  # no integrity log when key off


# ---------------------------------------------------------------------------
# Forged line is not trusted; integrity tripwire fires with the right class (D4/D9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("forged", "expected_class"),
    [
        (_block(session_id="sess-F1", scan_id="e-forge-1"), "sig-missing"),
        (_block(session_id="sess-F2", scan_id="e-forge-2", sig="deadbeef"), "sig-mismatch"),
    ],
)
async def test_forged_block_is_unverifiable_and_logs(
    forged: dict[str, Any], expected_class: str, caplog: pytest.LogCaptureFixture
) -> None:
    # Fresh handler per case so the rate-limited tripwire (D9) is open (clock at 0.0).
    handlers = _keyed_handlers()
    _append_raw(ev._spool_path(), forged)
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        summaries = await _drain(handlers)
    s = _find(summaries, event_type="block", session_id=forged["session_id"])
    assert s["provenance"] == "unverifiable"
    assert handlers.block_tally_for(forged["session_id"]) == 0  # never counted as a trusted block
    assert "PETASOS_INTEGRITY_UNVERIFIABLE" in caplog.text
    assert f"class={expected_class}" in caplog.text


async def test_forged_lines_both_surface_neither_counts() -> None:
    # Both a no-sig and a wrong-sig block drain, both surface unverifiable, neither tallies.
    handlers = _keyed_handlers()
    path = ev._spool_path()
    _append_raw(path, _block(session_id="sess-G", scan_id="e-g1"))  # no sig
    _append_raw(path, _block(session_id="sess-G", scan_id="e-g2", sig="0" * 64))  # wrong sig
    summaries = await _drain(handlers)
    s1 = _find(summaries, scan_id="e-g1")
    s2 = _find(summaries, scan_id="e-g2")
    assert s1["provenance"] == "unverifiable"
    assert s2["provenance"] == "unverifiable"
    assert handlers.block_tally_for("sess-G") == 0


# ---------------------------------------------------------------------------
# Legacy unsigned event over a configured key (transitional, D4)
# ---------------------------------------------------------------------------


async def test_legacy_unsigned_event_under_key_is_unverifiable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handlers = _keyed_handlers()
    _append_raw(ev._spool_path(), _block(session_id="sess-L", scan_id="e-legacy"))  # pre-PET-139
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        summaries = await _drain(handlers)
    s = _find(summaries, scan_id="e-legacy")
    assert s["provenance"] == "unverifiable"
    # missing tag is untrusted, not silently counted:
    assert handlers.block_tally_for("sess-L") == 0
    assert "class=sig-missing" in caplog.text


# ---------------------------------------------------------------------------
# Tag is event-bound — cross-event lifting fails (D7)
# ---------------------------------------------------------------------------


def test_tag_is_event_bound() -> None:
    ev.set_spool_key(_SECRET)
    ev.emit_enforcement_event(_block(session_id="sess-T", scan_id="e-bound-1", timestamp=111.0))
    genuine = _read_spool(ev._spool_path())[0]
    key = ev._derive_spool_key(_SECRET)
    assert ev.verify_event(genuine, key) is True

    # Lift the genuine sig onto a different event (new scan_id + tool).
    forged = dict(genuine)
    forged["scan_id"] = "e-bound-2"
    forged["tool"] = "http_request"
    forged["sig"] = genuine["sig"]
    assert ev.verify_event(forged, key) is False


# ---------------------------------------------------------------------------
# Schema-evolution coverage — the MAC covers every present field (D1)
# ---------------------------------------------------------------------------


async def test_schema_evolution_bypassed_count_inside_mac() -> None:
    ev.set_spool_key(_SECRET)
    ev.emit_enforcement_event(
        {
            "session_id": "sess-S",
            "tool": "send_email",
            "event_type": "bypassed_disarmed",
            "bypassed_count": 5,
            "armed": False,
            "direction": "tool_call",
        }
    )
    rec = _read_spool(ev._spool_path())[0]
    key = ev._derive_spool_key(_SECRET)
    assert ev.verify_event(rec, key) is True

    # Mutating bypassed_count after signing breaks verification (the count is inside the MAC).
    mutated = dict(rec)
    mutated["bypassed_count"] = 999
    assert ev.verify_event(mutated, key) is False

    # The PET-138 bypass-tally branch still updates for the genuine heartbeat (not regressed).
    handlers = _keyed_handlers()
    await _drain(handlers)
    assert handlers.bypass_tally_for("sess-S") == 5


# ---------------------------------------------------------------------------
# Fail-safe / fail-open (D6)
# ---------------------------------------------------------------------------


def test_verify_event_total_never_raises() -> None:
    key = ev._derive_spool_key(_SECRET)
    assert ev.verify_event({"sig": 123}, key) is False  # non-str sig
    assert ev.verify_event({"event_type": "block"}, key) is False  # missing sig
    assert ev.verify_event("not-a-dict", key) is False  # non-dict input
    assert ev.verify_event(None, key) is False
    assert ev.verify_event({"sig": "abc"}, None) is False  # None key → not genuine


def test_writer_signing_exception_returns_false_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force a signing-path exception: a non-bytes key makes hmac.new raise inside the
    # fail-open try. emit must return False and write NOTHING (the write follows signing).
    monkeypatch.setattr(ev, "_SPOOL_KEY", 12345)  # not bytes → hmac.new raises
    assert ev.emit_enforcement_event(_block()) is False
    assert _read_spool(ev._spool_path()) == []


# ---------------------------------------------------------------------------
# No payload via the tag (D5 / brief)
# ---------------------------------------------------------------------------


async def test_no_matched_text_and_reason_capped() -> None:
    ev.set_spool_key(_SECRET)
    long_reason = "x" * (server_mod._MAX_REASON_LEN + 250)
    ev.emit_enforcement_event(
        _block(session_id="sess-P", reason=long_reason, matched_text="SECRET-VALUE-LEAK")
    )
    handlers = _keyed_handlers()
    summaries = await _drain(handlers)
    s = _find(summaries, session_id="sess-P", event_type="block")
    assert "matched_text" not in s
    assert isinstance(s["reason"], str)
    assert len(s["reason"]) <= server_mod._MAX_REASON_LEN
    assert s["provenance"] == "genuine"  # matched_text in the source dict is inside the MAC


# ---------------------------------------------------------------------------
# _enforcement_summary provenance default (additive, callers untouched)
# ---------------------------------------------------------------------------


def test_enforcement_summary_provenance_defaults_unattested() -> None:
    s = server_mod._enforcement_summary({"event_type": "block", "session_id": "x"})
    assert s["provenance"] == "unattested"
    s2 = server_mod._enforcement_summary({"event_type": "block"}, provenance="genuine")
    assert s2["provenance"] == "genuine"


# ---------------------------------------------------------------------------
# Key derivation determinism + domain separation (D3)
# ---------------------------------------------------------------------------


def test_key_derivation_deterministic_and_domain_separated() -> None:
    s = b"some-session-secret"
    assert ev._derive_spool_key(s) == ev._derive_spool_key(s)  # stable for equal input
    assert ev._derive_spool_key(s) != s  # not the raw secret
    other_label = hmac.new(s, b"petasos/some-other-label/v1", hashlib.sha256).digest()
    assert ev._derive_spool_key(s) != other_label  # domain-separated from other labels
