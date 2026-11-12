"""Pin bounded scan waits and consecutive-timeout circuit breaking."""

from __future__ import annotations

import asyncio
import time

import pytest

from petasos.config.schema import ConfigError, from_mapping
from petasos.config.sections import PetasosConfig
from petasos.model import Direction, ScanResult
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
        """Return the fixture scanner name."""
        return self._name

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        """Supply the configured scanner response for this fixture."""
        self.calls += 1
        await asyncio.sleep(self._delay)
        return ScanResult(scanner_name=self._name, findings=())


class _FlakyThenHealthyScanner:
    """Times out on the first call, then succeeds — exercises breaker reset."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        """Return the fixture scanner name."""
        return "flaky"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        """Supply the configured scanner response for this fixture."""
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(5.0)
        return ScanResult(scanner_name="flaky", findings=())


@pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan"), 60.001, 100.0])
def test_scanner_timeout_seconds_rejects_invalid(bad: float) -> None:
    """Pin scanner timeout seconds rejects invalid."""
    with pytest.raises(ConfigError, match="scanners.timeout_seconds"):
        from_mapping(PetasosConfig, {"scanners": {"timeout_seconds": bad}})


def test_scanner_timeout_seconds_accepts_boundary() -> None:
    """Pin scanner timeout seconds accepts boundary."""
    at_cap = from_mapping(PetasosConfig, {"scanners": {"timeout_seconds": 60.0}})
    near_zero = from_mapping(PetasosConfig, {"scanners": {"timeout_seconds": 0.01}})
    assert at_cap.scanners.timeout_seconds == 60.0
    assert near_zero.scanners.timeout_seconds == 0.01


@pytest.mark.parametrize("bad", [0, -1, True])
def test_circuit_breaker_threshold_rejects_invalid(bad: object) -> None:
    """Pin circuit breaker threshold rejects invalid."""
    with pytest.raises(ConfigError, match="scanners.breaker_threshold"):
        from_mapping(PetasosConfig, {"scanners": {"breaker_threshold": bad}})


@pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan")])
def test_circuit_breaker_cooldown_rejects_invalid(bad: float) -> None:
    """Pin circuit breaker cooldown rejects invalid."""
    with pytest.raises(ConfigError, match="scanners.breaker_cooldown_seconds"):
        from_mapping(PetasosConfig, {"scanners": {"breaker_cooldown_seconds": bad}})


async def test_hanging_scanner_times_out_not_hangs() -> None:
    """Pin hanging scanner times out not hangs."""
    cfg = from_mapping(
        PetasosConfig,
        {
            "fail_mode": "degraded",
            "scanners": {"timeout_seconds": 0.05, "breaker_threshold": 5},
        },
    )
    scanner = _HangingScanner(delay=5.0)
    pipe = Pipeline([MinimalScanner(), scanner], config=cfg)

    t0 = time.perf_counter()
    result = await pipe.inspect("benign text")
    elapsed = time.perf_counter() - t0

    assert elapsed < 2.0
    sr = next(s for s in result.scanner_results if s.scanner_name == "hanging")
    assert sr.error is not None
    assert sr.error.startswith("ScannerTimeout")
    assert result.safe is False


async def test_circuit_breaker_trips_after_threshold() -> None:
    """Pin circuit breaker trips after threshold."""
    cfg = from_mapping(
        PetasosConfig,
        {
            "fail_mode": "degraded",
            "scanners": {
                "timeout_seconds": 0.05,
                "breaker_threshold": 2,
                "breaker_cooldown_seconds": 30.0,
            },
        },
    )
    scanner = _HangingScanner(delay=5.0)
    pipe = Pipeline([MinimalScanner(), scanner], config=cfg)

    await pipe.inspect("x")
    await pipe.inspect("x")
    result = await pipe.inspect("x")

    sr = next(s for s in result.scanner_results if s.scanner_name == "hanging")
    assert sr.error is not None
    assert sr.error.startswith("ScannerCircuitOpen")
    assert scanner.calls == 2


async def test_circuit_breaker_streak_clears_after_cooldown() -> None:
    """Cooldown expiry resets the consecutive-timeout count.

    After the breaker opens and the cooldown elapses, the scanner must be
    re-invoked (not short-circuited) and must accumulate a fresh streak to
    reopen — a single timeout post-cooldown must not immediately re-trip.
    """
    cfg = from_mapping(
        PetasosConfig,
        {
            "fail_mode": "degraded",
            "scanners": {
                "timeout_seconds": 0.05,
                "breaker_threshold": 2,
                "breaker_cooldown_seconds": 0.05,
            },
        },
    )
    scanner = _HangingScanner(delay=5.0)
    pipe = Pipeline([MinimalScanner(), scanner], config=cfg)

    await pipe.inspect("x")
    await pipe.inspect("x")

    await asyncio.sleep(0.1)

    calls_before = scanner.calls
    result = await pipe.inspect("x")

    assert scanner.calls > calls_before

    # A cooldown resets the streak; one subsequent timeout cannot reopen a threshold-two breaker.
    sr = next(s for s in result.scanner_results if s.scanner_name == "hanging")
    assert sr.error is not None
    assert sr.error.startswith("ScannerTimeout"), (
        f"Expected fresh ScannerTimeout after cooldown reset, got: {sr.error!r}"
    )

    calls_before2 = scanner.calls
    result2 = await pipe.inspect("x")
    assert scanner.calls > calls_before2, "scanner was not invoked on second post-cooldown call"
    sr2 = next(s for s in result2.scanner_results if s.scanner_name == "hanging")
    assert sr2.error is not None
    assert sr2.error.startswith("ScannerTimeout"), (
        f"Expected ScannerTimeout on second post-cooldown call, got: {sr2.error!r}"
    )


async def test_circuit_breaker_resets_on_success() -> None:
    """Pin circuit breaker resets on success."""
    cfg = from_mapping(
        PetasosConfig,
        {
            "fail_mode": "degraded",
            "scanners": {"timeout_seconds": 0.05, "breaker_threshold": 2},
        },
    )
    scanner = _FlakyThenHealthyScanner()
    pipe = Pipeline([MinimalScanner(), scanner], config=cfg)

    await pipe.inspect("x")
    result = await pipe.inspect("x")

    sr = next(s for s in result.scanner_results if s.scanner_name == "flaky")
    assert sr.error is None
    assert scanner.calls == 2
