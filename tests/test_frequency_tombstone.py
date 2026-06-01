"""PET-30: FrequencyTracker tombstone set unit tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from petasos.config import PetasosConfig
from petasos.session.frequency import FrequencyTracker


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "frequency_enabled": True,
        "escalation_enabled": True,
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 8: terminate_session sets tombstone
# ---------------------------------------------------------------------------


class TestTerminateSessionSetsTombstone:
    def test_terminate_session_sets_tombstone(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        tracker.terminate_session("s1")
        assert tracker.is_terminated("s1") is True


# ---------------------------------------------------------------------------
# Test 9: terminate_session tombstone when state missing
# ---------------------------------------------------------------------------


class TestTerminateSessionTombstoneWhenStateMissing:
    def test_terminate_session_tombstone_when_state_missing(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        # Session never existed in _sessions
        tracker.terminate_session("phantom")
        assert tracker.is_terminated("phantom") is True
        assert tracker.get_state("phantom") is None


# ---------------------------------------------------------------------------
# Test 10: tier3 update sets tombstone
# ---------------------------------------------------------------------------


class TestTier3UpdateSetsTombstone:
    def test_tier3_update_sets_tombstone(self) -> None:
        cfg = _cfg(tier3_threshold=50.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        assert result.tier == "tier3"
        assert result.terminated is True
        assert tracker.is_terminated("s1") is True
        assert tracker.tombstone_count == 1


# ---------------------------------------------------------------------------
# Test 11: reset preserves tombstone
# ---------------------------------------------------------------------------


class TestResetPreservesTombstone:
    def test_reset_preserves_tombstone(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        tracker.terminate_session("s1")
        tracker.reset("s1")

        assert tracker.get_state("s1") is None
        assert tracker.is_terminated("s1") is True


# ---------------------------------------------------------------------------
# Test 12: force_reset clears tombstone
# ---------------------------------------------------------------------------


class TestForceResetClearsTombstone:
    def test_force_reset_clears_tombstone(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        tracker.terminate_session("s1")
        assert tracker.is_terminated("s1") is True

        tracker.force_reset("s1")
        assert tracker.is_terminated("s1") is False
        assert tracker.get_state("s1") is None


# ---------------------------------------------------------------------------
# Test 13: tombstone bounded FIFO
# ---------------------------------------------------------------------------


class TestTombstoneBoundedFifo:
    def test_tombstone_bounded_fifo(self) -> None:
        cfg = _cfg(max_terminated_tombstones=3)
        tracker = FrequencyTracker(cfg)

        tracker.terminate_session("s1")
        tracker.terminate_session("s2")
        tracker.terminate_session("s3")
        tracker.terminate_session("s4")

        assert tracker.tombstone_count == 3
        # s1 evicted (oldest), s2/s3/s4 remain
        assert tracker.is_terminated("s1") is False
        assert tracker.is_terminated("s2") is True
        assert tracker.is_terminated("s3") is True
        assert tracker.is_terminated("s4") is True


# ---------------------------------------------------------------------------
# Test 14: tombstone cap at one
# ---------------------------------------------------------------------------


class TestTombstoneCapAtOne:
    def test_tombstone_cap_at_one(self) -> None:
        cfg = _cfg(max_terminated_tombstones=1)
        tracker = FrequencyTracker(cfg)

        tracker.terminate_session("s1")
        tracker.terminate_session("s2")

        assert tracker.tombstone_count == 1
        assert tracker.is_terminated("s1") is False
        assert tracker.is_terminated("s2") is True


# ---------------------------------------------------------------------------
# Test 15: clear clears tombstones
# ---------------------------------------------------------------------------


class TestClearClearsTombstones:
    def test_clear_clears_tombstones(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        tracker.terminate_session("s1")
        tracker.terminate_session("s2")
        assert tracker.tombstone_count == 2

        tracker.clear()
        assert tracker.is_terminated("s1") is False
        assert tracker.is_terminated("s2") is False
        assert tracker.tombstone_count == 0


# ---------------------------------------------------------------------------
# Test 16: is_terminated false for unknown
# ---------------------------------------------------------------------------


class TestIsTerminatedFalseForUnknown:
    def test_is_terminated_false_for_unknown(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        assert tracker.is_terminated("never_seen") is False


# ---------------------------------------------------------------------------
# Test 17: is_terminated true for live terminated
# ---------------------------------------------------------------------------


class TestIsTerminatedTrueForLiveTerminated:
    def test_is_terminated_true_for_live_terminated(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        tracker.terminate_session("s1")

        # State still in _sessions
        assert tracker.get_state("s1") is not None
        # is_terminated checks live state first
        assert tracker.is_terminated("s1") is True


# ---------------------------------------------------------------------------
# Test 18: tombstone_count property
# ---------------------------------------------------------------------------


class TestTombstoneCountProperty:
    def test_tombstone_count_property(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        assert tracker.tombstone_count == 0
        tracker.terminate_session("s1")
        assert tracker.tombstone_count == 1
        tracker.terminate_session("s2")
        assert tracker.tombstone_count == 2
        tracker.force_reset("s1")
        assert tracker.tombstone_count == 1


# ---------------------------------------------------------------------------
# Test 19: double termination idempotent
# ---------------------------------------------------------------------------


class TestDoubleTerminationIdempotent:
    def test_double_termination_idempotent(self) -> None:
        cfg = _cfg(max_terminated_tombstones=10)
        tracker = FrequencyTracker(cfg)

        tracker.terminate_session("s1")
        tracker.terminate_session("s2")
        # Re-terminate s1
        tracker.terminate_session("s1")

        assert tracker.is_terminated("s1") is True
        assert tracker.tombstone_count == 2

        # s1 should now be at the end (FIFO position refreshed)
        keys = list(tracker._terminated_ids.keys())
        assert keys[-1] == "s1"


# ---------------------------------------------------------------------------
# Test 20: config validation
# ---------------------------------------------------------------------------


class TestConfigMaxTerminatedTombstonesValidation:
    def test_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="max_terminated_tombstones"):
            PetasosConfig(max_terminated_tombstones=0)

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="max_terminated_tombstones"):
            PetasosConfig(max_terminated_tombstones=-1)

    def test_bool_raises(self) -> None:
        with pytest.raises(ValueError, match="max_terminated_tombstones"):
            PetasosConfig(max_terminated_tombstones=True)

    def test_string_raises(self) -> None:
        with pytest.raises(
            (ValueError, TypeError),
        ):
            PetasosConfig(max_terminated_tombstones="foo")  # type: ignore[arg-type]

    def test_valid_positive_integer(self) -> None:
        cfg = PetasosConfig(max_terminated_tombstones=500)
        assert cfg.max_terminated_tombstones == 500
