"""PET-75 FREQ-05: O(k) TTL eviction via sorted deque with compaction."""

from __future__ import annotations

from unittest.mock import patch

from petasos.config import PetasosConfig
from petasos.session.frequency import FrequencyTracker


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "frequency_enabled": True,
        "escalation_enabled": True,
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


class TestTtlEviction:
    def test_ttl_eviction_uses_deque(self) -> None:
        cfg = _cfg(session_ttl_seconds=100.0, max_sessions=200)
        tracker = FrequencyTracker(cfg)
        t0 = 1000.0

        for i in range(100):
            with patch("petasos.session.frequency.time.monotonic", return_value=t0 + i * 0.01):
                tracker.update(f"s{i}", [])

        assert tracker.size == 100

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 200.0):
            tracker.update("trigger", [])

        assert tracker.size == 1
        assert tracker.get_state("trigger") is not None
        for i in range(100):
            assert tracker.get_state(f"s{i}") is None

    def test_refreshed_session_survives_stale_deque_entry(self) -> None:
        cfg = _cfg(session_ttl_seconds=100.0)
        tracker = FrequencyTracker(cfg)
        t0 = 1000.0

        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 80.0):
            tracker.update("s1", [])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 110.0):
            tracker.update("s2", [])

        assert tracker.get_state("s1") is not None

    def test_compaction_triggers_at_threshold(self) -> None:
        cfg = _cfg(session_ttl_seconds=1000.0, max_sessions=3)
        tracker = FrequencyTracker(cfg)
        t0 = 1000.0

        for i in range(3):
            with patch("petasos.session.frequency.time.monotonic", return_value=t0 + i * 0.01):
                tracker.update(f"s{i}", [])

        assert len(tracker._ttl_deque) == 3

        for cycle in range(10):
            for i in range(3):
                with patch(
                    "petasos.session.frequency.time.monotonic",
                    return_value=t0 + 1.0 + cycle + i * 0.01,
                ):
                    tracker.update(f"s{i}", [])

        assert len(tracker._ttl_deque) <= 2 * cfg.max_sessions

        expiries = [entry[0] for entry in tracker._ttl_deque]
        assert expiries == sorted(expiries)

    def test_clear_resets_deque(self) -> None:
        cfg = _cfg(session_ttl_seconds=100.0)
        tracker = FrequencyTracker(cfg)
        t0 = 1000.0

        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        assert len(tracker._ttl_deque) > 0

        tracker.clear()
        assert len(tracker._ttl_deque) == 0
