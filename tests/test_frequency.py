from __future__ import annotations

from unittest.mock import patch

import pytest

from petasos.config import PetasosConfig
from petasos.premium.frequency import (
    DEFAULT_FREQUENCY_WEIGHTS,
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


# ---------------------------------------------------------------------------
# Decay math
# ---------------------------------------------------------------------------


class TestDecayMath:
    def test_score_halves_after_one_half_life(self) -> None:
        cfg = _cfg(frequency_half_life_seconds=10.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.test"])

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 10.0):
            result = tracker.update("s1", [])

        assert abs(result.previous_score - 5.0) < 1e-9

    def test_score_decays_to_near_zero_after_many_half_lives(self) -> None:
        cfg = _cfg(frequency_half_life_seconds=10.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.test"])

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 500.0):
            result = tracker.update("s1", [])

        assert result.current_score < 1e-6

    def test_zero_elapsed_no_decay(self) -> None:
        cfg = _cfg(frequency_half_life_seconds=10.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            r1 = tracker.update("s1", ["petasos.syntactic.injection.test"])

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            r2 = tracker.update("s1", ["petasos.syntactic.injection.test"])

        assert r2.previous_score == r1.current_score

    def test_decay_with_zero_initial_score(self) -> None:
        cfg = _cfg(frequency_half_life_seconds=10.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 10.0):
            result = tracker.update("s1", [])

        assert result.current_score == 0.0

    def test_multiple_updates_produce_reference_sequence(self) -> None:
        cfg = _cfg(
            frequency_half_life_seconds=10.0,
            frequency_weights={"test.rule": 10.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            r1 = tracker.update("s1", ["test.rule"])
        assert r1.current_score == 10.0

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 10.0):
            r2 = tracker.update("s1", ["test.rule"])
        assert abs(r2.current_score - 15.0) < 1e-9

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 20.0):
            r3 = tracker.update("s1", [])
        assert abs(r3.current_score - 7.5) < 1e-9


# ---------------------------------------------------------------------------
# Weight matching
# ---------------------------------------------------------------------------


class TestWeightMatching:
    def test_exact_match_takes_priority_over_glob(self) -> None:
        cfg = _cfg(
            frequency_weights={
                "petasos.syntactic.injection.role-switch": 20.0,
                "petasos.syntactic.injection.*": 10.0,
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["petasos.syntactic.injection.role-switch"])
        assert result.current_score == 20.0

    def test_glob_match_longest_prefix_wins(self) -> None:
        cfg = _cfg(
            frequency_weights={
                "petasos.syntactic.*": 1.0,
                "petasos.syntactic.injection.*": 10.0,
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["petasos.syntactic.injection.test"])
        assert result.current_score == 10.0

    def test_no_match_returns_zero(self) -> None:
        cfg = _cfg(frequency_weights={"petasos.syntactic.injection.*": 10.0})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["unknown.rule.test"])
        assert result.current_score == 0.0

    def test_multiple_rule_ids_weights_summed(self) -> None:
        cfg = _cfg(
            frequency_weights={
                "petasos.syntactic.injection.*": 10.0,
                "petasos.syntactic.structural.*": 5.0,
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            result = tracker.update(
                "s1",
                [
                    "petasos.syntactic.injection.test",
                    "petasos.syntactic.structural.test",
                ],
            )
        assert result.current_score == 15.0

    def test_empty_rule_ids_only_decays(self) -> None:
        cfg = _cfg(
            frequency_half_life_seconds=10.0,
            frequency_weights={"test.rule": 10.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["test.rule"])

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 10.0):
            result = tracker.update("s1", [])
        assert abs(result.current_score - 5.0) < 1e-9


# ---------------------------------------------------------------------------
# Rolling window
# ---------------------------------------------------------------------------


class TestRollingWindow:
    def test_findings_within_window_counted(self) -> None:
        cfg = _cfg(
            rolling_window_seconds=60.0,
            rolling_threshold=3,
            frequency_weights={"r": 1.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        for i in range(3):
            with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + i):
                tracker.update("s1", ["r"])

        state = tracker.get_state("s1")
        assert state is not None
        assert len(state.rolling_findings) == 3

    def test_findings_outside_window_pruned(self) -> None:
        cfg = _cfg(
            rolling_window_seconds=10.0,
            rolling_threshold=100,
            frequency_weights={"r": 1.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 20.0):
            tracker.update("s1", ["r"])

        state = tracker.get_state("s1")
        assert state is not None
        assert len(state.rolling_findings) == 1

    def test_rolling_threshold_promotes_to_tier1(self) -> None:
        cfg = _cfg(
            rolling_window_seconds=60.0,
            rolling_threshold=3,
            tier1_threshold=100.0,
            tier2_threshold=200.0,
            tier3_threshold=300.0,
            frequency_weights={"r": 0.01},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        for i in range(3):
            with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + i):
                result = tracker.update("s1", ["r"])

        assert result.tier == "tier1"
        assert result.current_score < cfg.tier1_threshold

    def test_empty_rolling_window_after_expiry(self) -> None:
        cfg = _cfg(
            rolling_window_seconds=5.0,
            rolling_threshold=100,
            frequency_weights={"r": 1.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 10.0):
            tracker.update("s1", [])

        state = tracker.get_state("s1")
        assert state is not None
        assert len(state.rolling_findings) == 0


# ---------------------------------------------------------------------------
# Session eviction
# ---------------------------------------------------------------------------


class TestSessionEviction:
    def test_ttl_eviction_removes_stale_sessions(self) -> None:
        cfg = _cfg(
            session_ttl_seconds=10.0,
            max_sessions=100,
            frequency_weights={"r": 1.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("stale", ["r"])

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 20.0):
            tracker.update("fresh", ["r"])

        assert tracker.get_state("stale") is None
        assert tracker.get_state("fresh") is not None

    def test_max_sessions_evicts_oldest_prefers_terminated(self) -> None:
        cfg = _cfg(
            max_sessions=3,
            max_new_sessions_per_minute=100,
            frequency_weights={"r": 1.0},
            tier3_threshold=50.0,
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 1):
            tracker.update("s2", ["r"])

        tracker.terminate_session("s1")

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 2):
            tracker.update("s3", ["r"])

        # s1 (terminated) should have been evicted when s4 joins
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 3):
            tracker.update("s4", ["r"])

        assert tracker.get_state("s1") is None
        assert tracker.size == 3

    def test_eviction_never_removes_current_session(self) -> None:
        cfg = _cfg(
            max_sessions=2,
            max_new_sessions_per_minute=100,
            frequency_weights={"r": 1.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 1):
            tracker.update("s2", ["r"])
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 2):
            tracker.update("s3", ["r"])

        assert tracker.get_state("s3") is not None
        assert tracker.size == 2

    def test_over_1000_sessions_no_crash(self) -> None:
        cfg = _cfg(
            max_sessions=1200,
            max_new_sessions_per_minute=2000,
            frequency_weights={"r": 0.001},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            for i in range(1100):
                tracker.update(f"s{i}", ["r"])

        assert tracker.size <= 1200


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_new_session_rejected_at_capacity(self) -> None:
        cfg = _cfg(
            max_sessions=2,
            max_new_sessions_per_minute=2,
            frequency_weights={"r": 1.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
            tracker.update("s2", ["r"])
            result = tracker.update("s3", ["r"])

        assert result is RATE_LIMITED_RESULT

    def test_new_session_accepted_under_capacity(self) -> None:
        cfg = _cfg(
            max_sessions=10,
            max_new_sessions_per_minute=10,
            frequency_weights={"r": 1.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["r"])

        assert result is not RATE_LIMITED_RESULT
        assert result.current_score == 1.0

    def test_rate_limit_window_rolls_forward(self) -> None:
        cfg = _cfg(
            max_sessions=2,
            max_new_sessions_per_minute=2,
            frequency_weights={"r": 1.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
            tracker.update("s2", ["r"])
            rate_limited = tracker.update("s3", ["r"])
        assert rate_limited is RATE_LIMITED_RESULT

        # After 61 seconds the creation timestamps have expired
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 61):
            result = tracker.update("s3", ["r"])
        assert result is not RATE_LIMITED_RESULT


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_terminated_session_returns_immediately(self) -> None:
        cfg = _cfg(frequency_weights={"r": 100.0}, tier3_threshold=50.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            r1 = tracker.update("s1", ["r"])
        assert r1.tier == "tier3"
        assert r1.terminated

        with patch("petasos.premium.frequency.time.monotonic", return_value=t0 + 1):
            r2 = tracker.update("s1", ["r"])
        assert r2.tier == "tier3"
        assert r2.terminated
        assert r2.current_score == r1.current_score

    def test_get_state_unknown_session_returns_none(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)
        assert tracker.get_state("nonexistent") is None

    def test_reset_removes_session(self) -> None:
        cfg = _cfg(frequency_weights={"r": 1.0})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
        assert tracker.get_state("s1") is not None

        tracker.reset("s1")
        assert tracker.get_state("s1") is None

    def test_clear_removes_all_sessions_and_timestamps(self) -> None:
        cfg = _cfg(frequency_weights={"r": 1.0})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.premium.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
            tracker.update("s2", ["r"])
        assert tracker.size == 2

        tracker.clear()
        assert tracker.size == 0
        assert len(tracker._creation_timestamps) == 0


# ---------------------------------------------------------------------------
# Static results
# ---------------------------------------------------------------------------


class TestStaticResults:
    def test_disabled_result_is_frozen(self) -> None:
        assert DISABLED_RESULT.current_score == 0.0
        assert DISABLED_RESULT.tier == "none"
        assert DISABLED_RESULT.terminated is False

    def test_rate_limited_result_is_frozen(self) -> None:
        assert RATE_LIMITED_RESULT.current_score == 0.0
        assert RATE_LIMITED_RESULT.tier == "none"
        assert RATE_LIMITED_RESULT.terminated is False


# ---------------------------------------------------------------------------
# Weight validation
# ---------------------------------------------------------------------------


class TestWeightValidation:
    def test_glob_key_with_non_terminal_star_raises(self) -> None:
        with pytest.raises(ValueError, match="non-terminal"):
            FrequencyTracker(_cfg(frequency_weights={"petasos.*.injection": 1.0}))

    def test_default_weights_used_when_none(self) -> None:
        cfg = _cfg(frequency_weights=None)
        tracker = FrequencyTracker(cfg)
        assert tracker._exact_weights == {}
        assert len(tracker._glob_weights) == len(DEFAULT_FREQUENCY_WEIGHTS)


# ---------------------------------------------------------------------------
# Session token (FREQ-03)
# ---------------------------------------------------------------------------

_SECRET = b"test-secret-key-32-bytes-long!!!"


class TestSessionToken:
    def test_backward_compat_no_secret(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)
        with patch("petasos.premium.frequency.time.monotonic", return_value=1000.0):
            tracker.update("s1", [])
        assert tracker.get_state("s1") is not None
        tracker.terminate_session("s1")
        state = tracker.get_state("s1")
        assert state is not None and state.terminated
        tracker.reset("s1")
        assert tracker.get_state("s1") is None

    def test_valid_token_accepted(self) -> None:
        cfg = _cfg(session_secret=_SECRET)
        tracker = FrequencyTracker(cfg)
        token = tracker.mint_token("s1", "host-a")
        with patch("petasos.premium.frequency.time.monotonic", return_value=1000.0):
            result = tracker.update(token, ["petasos.syntactic.injection.ignore-previous"])
        assert result.current_score > 0
        state = tracker.get_state(token)
        assert state is not None
        assert state.last_score == result.current_score

    def test_mint_token_without_secret_raises(self) -> None:
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)
        with pytest.raises(ValueError, match="no session_secret configured"):
            tracker.mint_token("s1", "host")

    def test_mint_token_rejects_null_bytes(self) -> None:
        cfg = _cfg(session_secret=_SECRET)
        tracker = FrequencyTracker(cfg)
        with pytest.raises(ValueError, match="null bytes"):
            tracker.mint_token("\x00abc", "host")
        with pytest.raises(ValueError, match="null bytes"):
            tracker.mint_token("s1", "host\x00evil")
