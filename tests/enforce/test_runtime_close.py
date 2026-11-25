"""Closing a result loop cannot strand the synchronous hook waiting on it."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from typing import Literal

import pytest

from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.enforce import Enforcer, Limits, SettingsSnapshot, ToolCall
from petasos.model import Direction, ScanResult


class _HeldScanner:
    name = "held"

    def __init__(self) -> None:
        self.entered = threading.Event()

    async def scan(
        self, text: str, *, direction: Direction = "inbound", session_id: str | None = None
    ) -> ScanResult:
        self.entered.set()
        await asyncio.Event().wait()
        return ScanResult(scanner_name=self.name, findings=())


@pytest.mark.parametrize("mode", ["degraded", "closed"])
def test_ingestion_in_flight_at_close_finishes_with_failure_notice(
    mode: Literal["degraded", "closed"],
) -> None:
    base = PetasosConfig()
    config = replace(base, fail_mode=mode, scanners=replace(base.scanners, timeout_seconds=0.3))
    snapshot = SettingsSnapshot(armed=True, config=config, secrets=Secrets(), token=1)
    scanner = _HeldScanner()
    enforcer = Enforcer(
        lambda: snapshot, scanners=(scanner,), registry=(), limits=Limits(result_margin_s=0.0)
    )
    enforcer.start()
    assert enforcer.settle(10)
    done = threading.Event()
    returned: list[str | None] = []
    elapsed: list[float] = []

    def scan() -> None:
        start = time.monotonic()
        returned.append(enforcer.tool_result(ToolCall("read_file", session="s"), "original text"))
        elapsed.append(time.monotonic() - start)
        done.set()

    worker = threading.Thread(target=scan, daemon=True)
    worker.start()
    try:
        assert scanner.entered.wait(1.0)
        enforcer.close()
        assert done.wait(0.5), "in-flight result hook was stranded by close"
        assert elapsed[0] < 0.5
        assert returned[0] is not None and returned[0].endswith("original text")
        assert "unverified" in returned[0]
    finally:
        enforcer.close()
        # Also release the original broken implementation's stopped loop, so a
        # failing regression run does not leave its hook thread or tasks behind.
        loop = enforcer._core.runtime._ingest_loop
        if (
            worker.is_alive()
            and loop is not None
            and not loop.is_running()
            and not loop.is_closed()
        ):
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.wait(pending, timeout=0.2))
            loop.run_until_complete(asyncio.sleep(0))
            loop.close()
        worker.join(timeout=1.0)


def test_bridge_deadline_survives_a_blocked_result_loop() -> None:
    from petasos.enforce.runtime import AsyncBridge

    bridge = AsyncBridge()
    release = threading.Event()

    async def blocked() -> None:
        release.wait(1.0)

    start = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            bridge.run_ingest(blocked(), timeout=0.05)
        assert time.monotonic() - start < 0.3
    finally:
        release.set()
        bridge.close()


def test_close_between_loop_start_and_submission_rejects_the_coroutine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from petasos.enforce.runtime import AsyncBridge

    bridge = AsyncBridge()
    original = bridge._ensure_ingest
    ran = False

    def close_after_start() -> asyncio.AbstractEventLoop:
        loop = original()
        bridge.close()
        return loop

    async def work() -> None:
        nonlocal ran
        ran = True

    monkeypatch.setattr(bridge, "_ensure_ingest", close_after_start)
    with pytest.raises(RuntimeError, match="closed"):
        bridge.run_ingest(work(), timeout=0.1)
    assert not ran
