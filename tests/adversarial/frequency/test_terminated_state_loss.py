"""PET-30 FREQ-02: Terminated session state loss via TTL/LRU eviction."""

from __future__ import annotations

from collections import deque
from unittest.mock import patch

from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.premium.frequency import FrequencyTracker, SessionState
from petasos.premium.guard import ToolCallGuard


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "frequency_enabled": True,
        "escalation_enabled": True,
        "tool_guard_enabled": True,
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 1: Tombstone survives TTL eviction
# ---------------------------------------------------------------------------


class TestTerminatedSurvivesTtlEviction:
    def test_terminated_survives_ttl_eviction(self) -> None:
        cfg = _cfg(session_ttl_seconds=100.0, tier3_threshold=50.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        state = tracker.get_state("s1")
        assert state is not None
        assert state.terminated is True
        assert tracker.is_terminated("s1") is True

        # Advance past TTL and trigger eviction via update on a different session
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 200.0):
            tracker.update("s2", [])

        # Session state evicted
        assert tracker.get_state("s1") is None
        # Tombstone persists
        assert tracker.is_terminated("s1") is True


# ---------------------------------------------------------------------------
# Test 2: Tombstone survives LRU eviction
# ---------------------------------------------------------------------------


class TestTerminatedSurvivesLruEviction:
    def test_terminated_survives_lru_eviction(self) -> None:
        cfg = _cfg(max_sessions=3, tier3_threshold=50.0, session_ttl_seconds=9999.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        assert tracker.is_terminated("s1") is True

        # Flood with new sessions to trigger _evict_one
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 1.0):
            tracker.update("s2", [])
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 2.0):
            tracker.update("s3", [])
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 3.0):
            tracker.update("s4", [])

        # s1 should be evicted from _sessions (terminated sessions evicted first)
        assert tracker.get_state("s1") is None
        # But tombstone persists
        assert tracker.is_terminated("s1") is True


# ---------------------------------------------------------------------------
# Test 3: Guard blocks after TTL eviction
# ---------------------------------------------------------------------------


class TestGuardBlocksAfterTtlEviction:
    async def test_guard_blocks_after_ttl_eviction(self, valid_key: str) -> None:
        cfg = _cfg(session_ttl_seconds=100.0, tier3_threshold=50.0)
        pipe = Pipeline(config=cfg)
        pipe.activate(valid_key)
        tracker = FrequencyTracker(cfg)
        guard = ToolCallGuard(pipe, tracker, cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        # Evict via TTL
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 200.0):
            tracker.update("s2", [])

        assert tracker.get_state("s1") is None

        result = await guard.evaluate("bash", {}, "s1")
        assert result.allowed is False
        assert result.tier == "tier3"


# ---------------------------------------------------------------------------
# Test 4: Guard blocks after LRU eviction
# ---------------------------------------------------------------------------


class TestGuardBlocksAfterLruEviction:
    async def test_guard_blocks_after_lru_eviction(self, valid_key: str) -> None:
        cfg = _cfg(max_sessions=3, tier3_threshold=50.0, session_ttl_seconds=9999.0)
        pipe = Pipeline(config=cfg)
        pipe.activate(valid_key)
        tracker = FrequencyTracker(cfg)
        guard = ToolCallGuard(pipe, tracker, cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        # Flood to trigger LRU eviction of s1
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 1.0):
            tracker.update("s2", [])
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 2.0):
            tracker.update("s3", [])
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 3.0):
            tracker.update("s4", [])

        assert tracker.get_state("s1") is None

        result = await guard.evaluate("bash", {}, "s1")
        assert result.allowed is False
        assert result.tier == "tier3"


# ---------------------------------------------------------------------------
# Test 5: Reset does not resurrect terminated session
# ---------------------------------------------------------------------------


class TestResetDoesNotResurrect:
    async def test_reset_does_not_resurrect_terminated(self, valid_key: str) -> None:
        cfg = _cfg(tier3_threshold=50.0)
        pipe = Pipeline(config=cfg)
        pipe.activate(valid_key)
        tracker = FrequencyTracker(cfg)
        guard = ToolCallGuard(pipe, tracker, cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        tracker.reset("s1")
        assert tracker.get_state("s1") is None
        assert tracker.is_terminated("s1") is True

        result = await guard.evaluate("bash", {}, "s1")
        assert result.allowed is False
        assert result.tier == "tier3"


# ---------------------------------------------------------------------------
# Test 6: update() returns tier3 for tombstoned session
# ---------------------------------------------------------------------------


class TestUpdateReturnsTier3ForTombstoned:
    def test_update_returns_tier3_for_tombstoned_session(self) -> None:
        cfg = _cfg(session_ttl_seconds=100.0, tier3_threshold=50.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        # Evict via TTL
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 200.0):
            tracker.update("s2", [])

        assert tracker.get_state("s1") is None

        # Call update with non-empty rule_ids on tombstoned session
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 201.0):
            result = tracker.update("s1", ["petasos.syntactic.injection.a"])

        assert result.tier == "tier3"
        assert result.terminated is True
        assert result.current_score == cfg.tier3_threshold
        # Session must NOT be re-created
        assert "s1" not in tracker._sessions


# ---------------------------------------------------------------------------
# Test 7a: No spurious tier-escalation alert for tombstoned session
# ---------------------------------------------------------------------------


class TestTombstonedUpdateNoSpuriousAlert:
    def test_tombstoned_update_no_spurious_alert(self) -> None:
        cfg = _cfg(session_ttl_seconds=100.0, tier3_threshold=50.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["petasos.syntactic.injection.a"] * 6)

        assert result.tier == "tier3"

        # Evict via TTL
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 200.0):
            tracker.update("s2", [])

        # Tombstone early-return: both scores should be tier3_threshold
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 201.0):
            result = tracker.update("s1", [])

        from petasos.premium.escalation import evaluate_tier

        previous_tier = evaluate_tier(result.previous_score, cfg)
        current_tier = evaluate_tier(result.current_score, cfg)
        assert previous_tier == "tier3"
        assert current_tier == "tier3"
        assert previous_tier == current_tier


# ---------------------------------------------------------------------------
# Test 7: Defensive tombstone write in _evict_one
# ---------------------------------------------------------------------------


class TestEvictOneDefensiveTombstone:
    def test_evict_one_defensive_tombstone_write(self) -> None:
        cfg = _cfg(max_sessions=2, tier3_threshold=50.0, session_ttl_seconds=9999.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        # Directly inject a terminated session WITHOUT a tombstone
        tracker._sessions["injected"] = SessionState(
            last_score=60.0,
            last_update=t0,
            rolling_findings=deque(),
            terminated=True,
        )

        assert "injected" not in tracker._terminated_ids

        # Add sessions to trigger _evict_one
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 1.0):
            tracker.update("s2", [])
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 2.0):
            tracker.update("s3", [])

        # injected should be evicted from _sessions (terminated preferred)
        assert "injected" not in tracker._sessions
        # But defensive tombstone write should have persisted it
        assert tracker.is_terminated("injected") is True
