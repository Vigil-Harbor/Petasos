"""Pin termination tombstones across TTL, LRU eviction and state reset."""

from __future__ import annotations

from collections import deque
from typing import Any
from unittest.mock import patch

from petasos.config.schema import from_mapping, merge
from petasos.config.sections import PetasosConfig
from petasos.guard.guard import ToolCallGuard
from petasos.pipeline import Pipeline
from petasos.session.frequency import FrequencyTracker, SessionState


def _cfg(changes: dict[str, Any] | None = None) -> PetasosConfig:
    document: dict[str, Any] = {
        "frequency": {"enabled": True},
        "escalation": {"enabled": True},
        "tools": {"enabled": True},
    }
    if changes:
        document = merge(document, changes)
    return from_mapping(PetasosConfig, document)


class TestTerminatedSurvivesTtlEviction:
    """Pin Terminated Survives Ttl Eviction."""

    def test_terminated_survives_ttl_eviction(self) -> None:
        """Pin terminated survives ttl eviction."""
        cfg = _cfg({"sessions": {"ttl_seconds": 100.0}, "escalation": {"tier3": 50.0}})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        state = tracker.get_state("s1")
        assert state is not None
        assert state.terminated is True
        assert tracker.is_terminated("s1") is True

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 200.0):
            tracker.update("s2", [])

        assert tracker.get_state("s1") is None
        assert tracker.is_terminated("s1") is True


class TestTerminatedSurvivesLruEviction:
    """Pin Terminated Survives Lru Eviction."""

    def test_terminated_survives_lru_eviction(self) -> None:
        """Pin terminated survives lru eviction."""
        cfg = _cfg({"sessions": {"max": 3, "ttl_seconds": 9999.0}, "escalation": {"tier3": 50.0}})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        assert tracker.is_terminated("s1") is True

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 1.0):
            tracker.update("s2", [])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 2.0):
            tracker.update("s3", [])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 3.0):
            tracker.update("s4", [])

        assert tracker.get_state("s1") is None
        assert tracker.is_terminated("s1") is True


class TestGuardBlocksAfterTtlEviction:
    """Pin Guard Blocks After Ttl Eviction."""

    async def test_guard_blocks_after_ttl_eviction(self) -> None:
        """Pin guard blocks after ttl eviction."""
        cfg = _cfg({"sessions": {"ttl_seconds": 100.0}, "escalation": {"tier3": 50.0}})
        pipe = Pipeline(config=cfg)
        tracker = FrequencyTracker(cfg)
        guard = ToolCallGuard(pipe, tracker, cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 200.0):
            tracker.update("s2", [])

        assert tracker.get_state("s1") is None

        result = await guard.evaluate("bash", {}, "s1")
        assert result.allowed is False
        assert result.tier == "tier3"


class TestGuardBlocksAfterLruEviction:
    """Pin Guard Blocks After Lru Eviction."""

    async def test_guard_blocks_after_lru_eviction(self) -> None:
        """Pin guard blocks after lru eviction."""
        cfg = _cfg({"sessions": {"max": 3, "ttl_seconds": 9999.0}, "escalation": {"tier3": 50.0}})
        pipe = Pipeline(config=cfg)
        tracker = FrequencyTracker(cfg)
        guard = ToolCallGuard(pipe, tracker, cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 1.0):
            tracker.update("s2", [])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 2.0):
            tracker.update("s3", [])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 3.0):
            tracker.update("s4", [])

        assert tracker.get_state("s1") is None

        result = await guard.evaluate("bash", {}, "s1")
        assert result.allowed is False
        assert result.tier == "tier3"


class TestResetDoesNotResurrect:
    """Pin Reset Does Not Resurrect."""

    async def test_reset_does_not_resurrect_terminated(self) -> None:
        """Pin reset does not resurrect terminated."""
        cfg = _cfg({"escalation": {"tier3": 50.0}})
        pipe = Pipeline(config=cfg)
        tracker = FrequencyTracker(cfg)
        guard = ToolCallGuard(pipe, tracker, cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        tracker.reset("s1")
        assert tracker.get_state("s1") is None
        assert tracker.is_terminated("s1") is True

        result = await guard.evaluate("bash", {}, "s1")
        assert result.allowed is False
        assert result.tier == "tier3"


class TestUpdateReturnsTier3ForTombstoned:
    """Pin Update Returns Tier3 For Tombstoned."""

    def test_update_returns_tier3_for_tombstoned_session(self) -> None:
        """Pin update returns tier3 for tombstoned session."""
        cfg = _cfg({"sessions": {"ttl_seconds": 100.0}, "escalation": {"tier3": 50.0}})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 200.0):
            tracker.update("s2", [])

        assert tracker.get_state("s1") is None

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 201.0):
            result = tracker.update("s1", ["petasos.syntactic.injection.a"])

        assert result.tier == "tier3"
        assert result.terminated is True
        assert result.current_score == cfg.escalation.tier3
        assert "s1" not in tracker._sessions


class TestTombstonedUpdateNoSpuriousAlert:
    """Pin Tombstoned Update No Spurious Alert."""

    def test_tombstoned_update_no_spurious_alert(self) -> None:
        """Pin tombstoned update no spurious alert."""
        cfg = _cfg({"sessions": {"ttl_seconds": 100.0}, "escalation": {"tier3": 50.0}})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        assert result.tier == "tier3"

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 200.0):
            tracker.update("s2", [])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 201.0):
            result = tracker.update("s1", [])

        from petasos.session.escalation import evaluate_tier

        previous_tier = evaluate_tier(result.previous_score, cfg)
        current_tier = evaluate_tier(result.current_score, cfg)
        assert previous_tier == "tier3"
        assert current_tier == "tier3"
        assert previous_tier == current_tier


class TestTtlEvictionDefensiveTombstone:
    """Pin Ttl Eviction Defensive Tombstone."""

    def test_ttl_eviction_defensive_tombstone(self) -> None:
        """Pin ttl eviction defensive tombstone."""
        cfg = _cfg(
            {
                "sessions": {"max_tombstones": 2, "ttl_seconds": 100.0},
                "escalation": {"tier3": 50.0},
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        assert tracker.is_terminated("s1") is True
        assert tracker.tombstone_count == 1

        tracker.terminate_session("phantom1")
        tracker.terminate_session("phantom2")
        assert tracker.tombstone_count == 2
        assert "s1" in tracker._sessions
        assert tracker._sessions["s1"].terminated is True
        assert "s1" not in tracker._terminated_ids

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 200.0):
            tracker.update("s3", [])

        assert tracker.get_state("s1") is None
        assert tracker.is_terminated("s1") is True


class TestEvictOneDefensiveTombstone:
    """Pin Evict One Defensive Tombstone."""

    def test_evict_one_defensive_tombstone_write(self) -> None:
        """Pin evict one defensive tombstone write."""
        cfg = _cfg({"sessions": {"max": 2, "ttl_seconds": 9999.0}, "escalation": {"tier3": 50.0}})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        tracker._sessions["injected"] = SessionState(
            last_score=60.0,
            last_update=t0,
            rolling_findings=deque(),
            terminated=True,
        )

        assert "injected" not in tracker._terminated_ids

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 1.0):
            tracker.update("s2", [])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 2.0):
            tracker.update("s3", [])

        assert "injected" not in tracker._sessions
        assert tracker.is_terminated("injected") is True
