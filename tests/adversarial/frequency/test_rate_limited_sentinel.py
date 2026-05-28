"""PET-75 FREQ-04: RATE_LIMITED_RESULT distinguishable from DISABLED_RESULT."""

from __future__ import annotations

from unittest.mock import patch

from petasos.config import PetasosConfig
from petasos.premium.frequency import (
    DISABLED_RESULT,
    RATE_LIMITED_RESULT,
    FrequencyTracker,
)


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "frequency_enabled": True,
        "escalation_enabled": True,
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


class TestRateLimitedSentinel:
    def test_rate_limited_distinct_from_disabled(self) -> None:
        assert RATE_LIMITED_RESULT.rate_limited is True
        assert DISABLED_RESULT.rate_limited is False
        assert RATE_LIMITED_RESULT.tier == DISABLED_RESULT.tier == "none"

    def test_rate_limited_result_fields(self) -> None:
        assert RATE_LIMITED_RESULT.tier == "none"
        assert RATE_LIMITED_RESULT.rate_limited is True
        assert RATE_LIMITED_RESULT.terminated is False
        assert RATE_LIMITED_RESULT.current_score == 0.0
        assert RATE_LIMITED_RESULT.previous_score == 0.0

    def test_disabled_result_fields(self) -> None:
        assert DISABLED_RESULT.tier == "none"
        assert DISABLED_RESULT.rate_limited is False
        assert DISABLED_RESULT.terminated is False
        assert DISABLED_RESULT.current_score == 0.0
        assert DISABLED_RESULT.previous_score == 0.0

    def test_update_returns_rate_limited_at_cap(self) -> None:
        cfg = _cfg(max_sessions=2, max_new_sessions_per_minute=2)
        tracker = FrequencyTracker(cfg)
        t0 = 1000.0

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 0.1):
            tracker.update("s2", [])
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 0.2):
            result = tracker.update("s3", [])

        assert result.rate_limited is True
        assert result.tier == "none"
        assert result is RATE_LIMITED_RESULT
