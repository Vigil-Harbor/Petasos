"""PET-157: the one-shot boot/preflight WARNING (``PETASOS_INTEGRITY_PREFLIGHT``).

The preflight fires exactly once per run, the first time the live drain surfaces a key-on spool
row whose provenance is ``unverifiable`` (D7). It names the failure class + remediation (D9) and
is distinct from the per-row, rate-limited ``PETASOS_INTEGRITY_UNVERIFIABLE`` tripwire. Nothing
fires when integrity is off or when the tail verifies.

Both modes are covered: standalone drives the explicit boot drain through the real ``build_app``
``startup`` lifespan (not a bare ``_drain_*`` call), and embedded fires on the first
``get_scan_history`` drain-on-read. Async tests bind via ``anyio_mode = "auto"`` (PET-149).
"""

from __future__ import annotations

import json
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

_SECRET = b"pet157-preflight-secret-0123456789ABCDEF"


@pytest.fixture(autouse=True)
def _reset_spool_key_around_test() -> Iterator[None]:
    ev._reset_spool_key()
    yield
    ev._reset_spool_key()


def _keyed_handlers(secret: bytes = _SECRET) -> ConsoleHandlers:
    pipeline = Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded", session_secret=secret),
        host_id="petasos-test",
    )
    return ConsoleHandlers(pipeline)


def _unkeyed_handlers() -> ConsoleHandlers:
    pipeline = Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="degraded"))
    return ConsoleHandlers(pipeline)


def _append_raw(path: str, rec: dict[str, Any]) -> None:
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


def _preflight_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "PETASOS_INTEGRITY_PREFLIGHT" in r.getMessage()]


# ---------------------------------------------------------------------------
# 1 — fires once, key-on + unverifiable (holds across two drain calls)
# ---------------------------------------------------------------------------


async def test_preflight_fires_once_key_on_unverifiable(caplog: pytest.LogCaptureFixture) -> None:
    handlers = _keyed_handlers()
    path = ev._spool_path()
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        _append_raw(path, _block(session_id="sess-1", scan_id="e-p1"))  # no sig -> sig-missing
        await handlers._drain_enforcement_into_history()
        _append_raw(path, _block(session_id="sess-1", scan_id="e-p2", sig="0" * 64))  # mismatch
        await handlers._drain_enforcement_into_history()
    records = _preflight_records(caplog)
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "class=sig-missing" in msg  # the FIRST surfaced unverifiable row drives it
    # Names the remediation (D9).
    assert server_mod._INTEGRITY_REMEDIATION["sig-missing"] in msg
    assert handlers._integrity_preflight_emitted is True


# ---------------------------------------------------------------------------
# 2 — silent when key-off
# ---------------------------------------------------------------------------


async def test_preflight_silent_key_off(caplog: pytest.LogCaptureFixture) -> None:
    ev._reset_spool_key()
    handlers = _unkeyed_handlers()
    path = ev._spool_path()
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        _append_raw(path, _block(session_id="sess-2", scan_id="e-k1"))  # no sig, but key off
        _append_raw(path, _block(session_id="sess-2", scan_id="e-k2", sig="0" * 64))
        await handlers._drain_enforcement_into_history()
    assert _preflight_records(caplog) == []
    assert handlers._integrity_preflight_emitted is False


# ---------------------------------------------------------------------------
# 3 — silent when every row verifies
# ---------------------------------------------------------------------------


async def test_preflight_silent_all_genuine(caplog: pytest.LogCaptureFixture) -> None:
    ev.set_spool_key(_SECRET)
    handlers = _keyed_handlers()
    for i in range(3):
        ev.emit_enforcement_event(_block(session_id="sess-3", scan_id=f"e-v{i}"))
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        await handlers._drain_enforcement_into_history()
    assert _preflight_records(caplog) == []
    assert handlers._integrity_preflight_emitted is False


# ---------------------------------------------------------------------------
# 4 — standalone boot drain via the real lifespan (exercises the _startup await-drain edit)
# ---------------------------------------------------------------------------


async def test_preflight_standalone_boot_via_lifespan(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pytest.importorskip("fastapi")
    import asyncio

    from petasos.console.server import build_app

    # Pre-seed an unverifiable (unsigned) tail BEFORE the app exists, so the boot drain classifies
    # it. Key on via the pipeline's session_secret; the row carries no sig -> unverifiable.
    _append_raw(ev._spool_path(), _block(session_id="sess-boot", scan_id="e-boot"))
    pipeline = Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded", session_secret=_SECRET),
        host_id="dashboard",
    )
    # Shrink the tailer interval so it ticks several times during the test, proving the one-shot
    # holds across the explicit-drain -> tailer handoff and does not double-fire.
    monkeypatch.setattr(server_mod, "_ENFORCEMENT_TAIL_INTERVAL_S", 0.01)
    app = build_app(pipeline)
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        # Drive the REGISTERED startup callbacks (runs the real _startup: explicit await-drain
        # then spawns the tailer) — the spec-sanctioned "invoke the app.router.on_startup
        # callback" path, not a bare handlers._drain_* call.
        for handler in app.router.on_startup:
            await handler()
        try:
            await asyncio.sleep(0.08)  # ~8 tailer ticks at the 0.01s interval
        finally:
            for handler in app.router.on_shutdown:
                await handler()  # cancels the tailer, closes SSE
    records = _preflight_records(caplog)
    assert len(records) == 1  # one-shot across explicit drain + every tailer tick
    assert "class=sig-missing" in records[0].getMessage()


# ---------------------------------------------------------------------------
# 5 — embedded first-read fires on the first get_scan_history drain-on-read, not before
# ---------------------------------------------------------------------------


async def test_preflight_embedded_first_read(caplog: pytest.LogCaptureFixture) -> None:
    pytest.importorskip("fastapi")
    from petasos.console.hermes import plugin_api

    _append_raw(ev._spool_path(), _block(session_id="sess-5", scan_id="e-e1"))  # unsigned tail
    pipeline = Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded", session_secret=_SECRET),
        host_id="dashboard",
    )
    plugin_api.init_handlers(pipeline)
    handlers = plugin_api._handlers
    assert handlers is not None
    assert handlers._integrity_preflight_emitted is False  # nothing fires before the first read
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        await handlers.get_scan_history()  # drain-on-read is the embedded floor
    assert handlers._integrity_preflight_emitted is True
    assert len(_preflight_records(caplog)) == 1
