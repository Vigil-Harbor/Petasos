"""Pin termination persistence across state eviction and reset."""

from __future__ import annotations

from unittest.mock import patch

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.session.frequency import FrequencyTracker


def _cfg(partial: dict[str, object] | None = None) -> PetasosConfig:
    """Build a config tree from a partial document."""
    if not partial:
        return PetasosConfig()
    return from_mapping(PetasosConfig, partial)


class TestTerminateSessionSetsTombstone:
    """Pin Terminate Session Sets Tombstone."""

    def test_terminate_session_sets_tombstone(self) -> None:
        """Pin terminate session sets tombstone."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        tracker.terminate_session("s1")
        assert tracker.is_terminated("s1") is True


class TestTerminateSessionTombstoneWhenStateMissing:
    """Pin Terminate Session Tombstone When State Missing."""

    def test_terminate_session_tombstone_when_state_missing(self) -> None:
        """Pin terminate session tombstone when state missing."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        tracker.terminate_session("phantom")
        assert tracker.is_terminated("phantom") is True
        assert tracker.get_state("phantom") is None


class TestTier3UpdateSetsTombstone:
    """Pin Tier3 Update Sets Tombstone."""

    def test_tier3_update_sets_tombstone(self) -> None:
        """Pin tier3 update sets tombstone."""
        cfg = _cfg(
            {
                "escalation": {
                    "tier3": 50.0,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        assert result.tier == "tier3"
        assert result.terminated is True
        assert tracker.is_terminated("s1") is True
        assert tracker.tombstone_count == 1


class TestResetPreservesTombstone:
    """Pin Reset Preserves Tombstone."""

    def test_reset_preserves_tombstone(self) -> None:
        """Pin reset preserves tombstone."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        tracker.terminate_session("s1")
        tracker.reset("s1")

        assert tracker.get_state("s1") is None
        assert tracker.is_terminated("s1") is True


class TestForceResetClearsTombstone:
    """Pin Force Reset Clears Tombstone."""

    def test_force_reset_clears_tombstone(self) -> None:
        """Pin force reset clears tombstone."""
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


class TestTombstoneBoundedFifo:
    """Pin Tombstone Bounded Fifo."""

    def test_tombstone_bounded_fifo(self) -> None:
        """Pin tombstone bounded fifo."""
        cfg = _cfg(
            {
                "sessions": {
                    "max_tombstones": 3,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        tracker.terminate_session("s1")
        tracker.terminate_session("s2")
        tracker.terminate_session("s3")
        tracker.terminate_session("s4")

        assert tracker.tombstone_count == 3
        assert tracker.is_terminated("s1") is False
        assert tracker.is_terminated("s2") is True
        assert tracker.is_terminated("s3") is True
        assert tracker.is_terminated("s4") is True


class TestTombstoneCapAtOne:
    """Pin Tombstone Cap At One."""

    def test_tombstone_cap_at_one(self) -> None:
        """Pin tombstone cap at one."""
        cfg = _cfg(
            {
                "sessions": {
                    "max_tombstones": 1,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        tracker.terminate_session("s1")
        tracker.terminate_session("s2")

        assert tracker.tombstone_count == 1
        assert tracker.is_terminated("s1") is False
        assert tracker.is_terminated("s2") is True


class TestClearClearsTombstones:
    """Pin Clear Clears Tombstones."""

    def test_clear_clears_tombstones(self) -> None:
        """Pin clear clears tombstones."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        tracker.terminate_session("s1")
        tracker.terminate_session("s2")
        assert tracker.tombstone_count == 2

        tracker.clear()
        assert tracker.is_terminated("s1") is False
        assert tracker.is_terminated("s2") is False
        assert tracker.tombstone_count == 0


class TestIsTerminatedFalseForUnknown:
    """Pin Is Terminated False For Unknown."""

    def test_is_terminated_false_for_unknown(self) -> None:
        """Pin is terminated false for unknown."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        assert tracker.is_terminated("never_seen") is False


class TestIsTerminatedTrueForLiveTerminated:
    """Pin Is Terminated True For Live Terminated."""

    def test_is_terminated_true_for_live_terminated(self) -> None:
        """Pin is terminated true for live terminated."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        tracker.terminate_session("s1")

        assert tracker.get_state("s1") is not None
        assert tracker.is_terminated("s1") is True


class TestTombstoneCountProperty:
    """Pin Tombstone Count Property."""

    def test_tombstone_count_property(self) -> None:
        """Pin tombstone count property."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)

        assert tracker.tombstone_count == 0
        tracker.terminate_session("s1")
        assert tracker.tombstone_count == 1
        tracker.terminate_session("s2")
        assert tracker.tombstone_count == 2
        tracker.force_reset("s1")
        assert tracker.tombstone_count == 1


class TestDoubleTerminationIdempotent:
    """Pin Double Termination Idempotent."""

    def test_double_termination_idempotent(self) -> None:
        """Pin double termination idempotent."""
        cfg = _cfg(
            {
                "sessions": {
                    "max_tombstones": 10,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        tracker.terminate_session("s1")
        tracker.terminate_session("s2")
        tracker.terminate_session("s1")

        assert tracker.is_terminated("s1") is True
        assert tracker.tombstone_count == 2

        keys = list(tracker._terminated_ids.keys())
        assert keys[-1] == "s1"
