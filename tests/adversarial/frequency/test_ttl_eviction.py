"""Pin expiry-ordered session eviction and bounded deque compaction."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from petasos.config.schema import from_mapping, merge
from petasos.config.sections import PetasosConfig
from petasos.session.frequency import FrequencyTracker


def _cfg(changes: dict[str, Any] | None = None) -> PetasosConfig:
    document: dict[str, Any] = {
        "frequency": {"enabled": True},
        "escalation": {"enabled": True},
    }
    if changes:
        document = merge(document, changes)
    return from_mapping(PetasosConfig, document)


class TestTtlEviction:
    def test_ttl_eviction_uses_deque(self) -> None:
        cfg = _cfg({"sessions": {"ttl_seconds": 100.0, "max": 200}})
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
        cfg = _cfg({"sessions": {"ttl_seconds": 100.0}})
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
        cfg = _cfg({"sessions": {"ttl_seconds": 1000.0, "max": 3}})
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

        assert len(tracker._ttl_deque) <= 2 * cfg.sessions.max

        expiries = [entry[0] for entry in tracker._ttl_deque]
        assert expiries == sorted(expiries)

    def test_clear_resets_deque(self) -> None:
        cfg = _cfg({"sessions": {"ttl_seconds": 100.0}})
        tracker = FrequencyTracker(cfg)
        t0 = 1000.0

        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        assert len(tracker._ttl_deque) > 0

        tracker.clear()
        assert len(tracker._ttl_deque) == 0
