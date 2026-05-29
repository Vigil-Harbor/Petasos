"""PIPE-03 (PET-50): scanner timeout + consecutive-timeout circuit breaker."""

from __future__ import annotations

import asyncio
import time

import pytest

from petasos._types import Direction, ScanResult
from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner


class _HangingScanner:
    """ML-style scanner that sleeps far longer than any sane timeout."""

    def __init__(self, name: str = "hanging", delay: float = 5.0) -> None:
        self._name = name
        self._delay = delay
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        self.calls += 1
        await asyncio.sleep(self._delay)
        return ScanResult(scanner_name=self._name, findings=())


class _FlakyThenHealthyScanner:
    """Times out on the first call, then succeeds — exercises breaker reset."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "flaky"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(5.0)
        return ScanResult(scanner_name="flaky", findings=())


# --- config validation -----------------------------------------------------


@pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan"), 60.001, 100.0])
def test_scanner_timeout_seconds_rejects_invalid(bad: float) -> None:
    with pytest.raises(ValueError, match="scanner_timeout_seconds"):
        PetasosConfig(scanner_timeout_seconds=bad)


def test_scanner_timeout_seconds_accepts_boundary() -> None:
    assert PetasosConfig(scanner_timeout_seconds=60.0).scanner_timeout_seconds == 60.0
    assert PetasosConfig(scanner_timeout_seconds=0.01).scanner_timeout_seconds == 0.01


@pytest.mark.parametrize("bad", [0, -1, True])
def test_circuit_breaker_threshold_rejects_invalid(bad: object) -> None:
    with pytest.raises(ValueError, match="scanner_circuit_breaker_threshold"):
        PetasosConfig(scanner_circuit_breaker_threshold=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan")])
def test_circuit_breaker_cooldown_rejects_invalid(bad: float) -> None:
    with pytest.raises(ValueError, match="scanner_circuit_breaker_cooldown_seconds"):
        PetasosConfig(scanner_circuit_breaker_cooldown_seconds=bad)


# --- timeout behavior -------------------------------------------------------


@pytest.mark.asyncio
async def test_hanging_scanner_times_out_not_hangs() -> None:
    cfg = PetasosConfig(
        fail_mode="degraded",
        scanner_timeout_seconds=0.05,
        scanner_circuit_breaker_threshold=5,  # high enough not to trip here
    )
    scanner = _HangingScanner(delay=5.0)
    pipe = Pipeline([MinimalScanner(), scanner], config=cfg)

    t0 = time.perf_counter()
    result = await pipe.inspect("benign text")
    elapsed = time.perf_counter() - t0

    assert elapsed < 2.0  # did not wait the full 5s hang
    sr = next(s for s in result.scanner_results if s.scanner_name == "hanging")
    assert sr.error is not None
    assert sr.error.startswith("ScannerTimeout")
    # degraded mode: an ML scanner error blocks content
    assert result.safe is False


# --- circuit breaker --------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_trips_after_threshold() -> None:
    cfg = PetasosConfig(
        fail_mode="degraded",
        scanner_timeout_seconds=0.05,
        scanner_circuit_breaker_threshold=2,
        scanner_circuit_breaker_cooldown_seconds=30.0,
    )
    scanner = _HangingScanner(delay=5.0)
    pipe = Pipeline([MinimalScanner(), scanner], config=cfg)

    await pipe.inspect("x")  # timeout 1
    await pipe.inspect("x")  # timeout 2 -> breaker opens
    result = await pipe.inspect("x")  # short-circuited

    sr = next(s for s in result.scanner_results if s.scanner_name == "hanging")
    assert sr.error is not None
    assert sr.error.startswith("ScannerCircuitOpen")
    # the third scan() was short-circuited — the scanner was never invoked again
    assert scanner.calls == 2


@pytest.mark.asyncio
async def test_circuit_breaker_streak_clears_after_cooldown() -> None:
    """Cooldown expiry resets the consecutive-timeout count.

    After the breaker opens and the cooldown elapses, the scanner must be
    re-invoked (not short-circuited) and must accumulate a fresh streak to
    reopen — a single timeout post-cooldown must not immediately re-trip.
    """
    cfg = PetasosConfig(
        fail_mode="degraded",
        scanner_timeout_seconds=0.05,
        scanner_circuit_breaker_threshold=2,
        scanner_circuit_breaker_cooldown_seconds=0.05,
    )
    scanner = _HangingScanner(delay=5.0)
    pipe = Pipeline([MinimalScanner(), scanner], config=cfg)

    await pipe.inspect("x")  # timeout 1 (count=1)
    await pipe.inspect("x")  # timeout 2 → breaker opens (count=2)

    # Wait for the cooldown to expire.
    await asyncio.sleep(0.1)

    calls_before = scanner.calls
    result = await pipe.inspect("x")  # cooldown expired → scanner re-invoked (streak=1)

    # The scanner must have been called again (not short-circuited).
    assert scanner.calls > calls_before

    # The error is a fresh timeout, not a circuit-open error, because the
    # streak was cleared — the single timeout post-cooldown did not re-trip.
    sr = next(s for s in result.scanner_results if s.scanner_name == "hanging")
    assert sr.error is not None
    assert sr.error.startswith("ScannerTimeout"), (
        f"Expected fresh ScannerTimeout after cooldown reset, got: {sr.error!r}"
    )

    # Second immediate post-cooldown call: streak=1 < threshold=2, so the
    # breaker is still closed and the scanner must be invoked again. If the
    # old stale-streak bug were present the breaker would already be open and
    # this call would be short-circuited (ScannerCircuitOpen), failing both
    # assertions below.
    calls_before2 = scanner.calls
    result2 = await pipe.inspect("x")  # streak hits threshold on this call, breaker re-opens
    assert scanner.calls > calls_before2, "scanner was not invoked on second post-cooldown call"
    sr2 = next(s for s in result2.scanner_results if s.scanner_name == "hanging")
    assert sr2.error is not None
    assert sr2.error.startswith("ScannerTimeout"), (
        f"Expected ScannerTimeout on second post-cooldown call, got: {sr2.error!r}"
    )


@pytest.mark.asyncio
async def test_circuit_breaker_resets_on_success() -> None:
    cfg = PetasosConfig(
        fail_mode="degraded",
        scanner_timeout_seconds=0.05,
        scanner_circuit_breaker_threshold=2,
    )
    scanner = _FlakyThenHealthyScanner()
    pipe = Pipeline([MinimalScanner(), scanner], config=cfg)

    await pipe.inspect("x")  # timeout (count=1, below threshold 2)
    result = await pipe.inspect("x")  # success -> resets streak

    sr = next(s for s in result.scanner_results if s.scanner_name == "flaky")
    assert sr.error is None  # healthy; breaker never opened
    assert scanner.calls == 2
