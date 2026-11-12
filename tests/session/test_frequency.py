"""Pin bounded decaying risk, rolling windows and token-authenticated session updates."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from petasos.config.schema import from_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.session.frequency import (
    DEFAULT_FREQUENCY_WEIGHTS,
    DISABLED_RESULT,
    RATE_LIMITED_RESULT,
    FrequencyTracker,
    SessionState,
)
from petasos.session.lineage import LineageRegistry


def _cfg(partial: dict[str, object] | None = None) -> PetasosConfig:
    """Build a config tree from a partial document."""
    if not partial:
        return PetasosConfig()
    return from_mapping(PetasosConfig, partial)


class TestDecayMath:
    """Pin Decay Math."""

    def test_score_halves_after_one_half_life(self) -> None:
        """Pin score halves after one half life."""
        cfg = _cfg(
            {
                "frequency": {
                    "half_life_seconds": 10.0,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.test"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 10.0):
            result = tracker.update("s1", [])

        assert abs(result.previous_score - 5.0) < 1e-9

    def test_score_decays_to_near_zero_after_many_half_lives(self) -> None:
        """Pin score decays to near zero after many half lives."""
        cfg = _cfg(
            {
                "frequency": {
                    "half_life_seconds": 10.0,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.test"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 500.0):
            result = tracker.update("s1", [])

        assert result.current_score < 1e-6

    def test_zero_elapsed_no_decay(self) -> None:
        """Pin zero elapsed no decay."""
        cfg = _cfg(
            {
                "frequency": {
                    "half_life_seconds": 10.0,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            r1 = tracker.update("s1", ["petasos.syntactic.injection.test"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            r2 = tracker.update("s1", ["petasos.syntactic.injection.test"])

        assert r2.previous_score == r1.current_score

    def test_decay_with_zero_initial_score(self) -> None:
        """Pin decay with zero initial score."""
        cfg = _cfg(
            {
                "frequency": {
                    "half_life_seconds": 10.0,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 10.0):
            result = tracker.update("s1", [])

        assert result.current_score == 0.0

    def test_multiple_updates_produce_reference_sequence(self) -> None:
        """Pin multiple updates produce reference sequence."""
        cfg = _cfg(
            {
                "frequency": {
                    "half_life_seconds": 10.0,
                    "weights": {"test.rule": 10.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            r1 = tracker.update("s1", ["test.rule"])
        assert r1.current_score == 10.0

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 10.0):
            r2 = tracker.update("s1", ["test.rule"])
        assert abs(r2.current_score - 15.0) < 1e-9

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 20.0):
            r3 = tracker.update("s1", [])
        assert abs(r3.current_score - 7.5) < 1e-9


class TestWeightMatching:
    """Pin Weight Matching."""

    def test_exact_match_takes_priority_over_glob(self) -> None:
        """Pin exact match takes priority over glob."""
        cfg = _cfg(
            {
                "frequency": {
                    "weights": {
                        "petasos.syntactic.injection.role-switch": 20.0,
                        "petasos.syntactic.injection.*": 10.0,
                    },
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["petasos.syntactic.injection.role-switch"])
        assert result.current_score == 20.0

    def test_glob_match_longest_prefix_wins(self) -> None:
        """Pin glob match longest prefix wins."""
        cfg = _cfg(
            {
                "frequency": {
                    "weights": {
                        "petasos.syntactic.*": 1.0,
                        "petasos.syntactic.injection.*": 10.0,
                    },
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["petasos.syntactic.injection.test"])
        assert result.current_score == 10.0

    def test_no_match_returns_zero(self) -> None:
        """Pin no match returns zero."""
        cfg = _cfg(
            {
                "frequency": {
                    "weights": {"petasos.syntactic.injection.*": 10.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["unknown.rule.test"])
        assert result.current_score == 0.0

    def test_multiple_rule_ids_weights_summed(self) -> None:
        """Pin multiple rule ids weights summed."""
        cfg = _cfg(
            {
                "frequency": {
                    "weights": {
                        "petasos.syntactic.injection.*": 10.0,
                        "petasos.syntactic.structural.*": 5.0,
                    },
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            result = tracker.update(
                "s1",
                [
                    "petasos.syntactic.injection.test",
                    "petasos.syntactic.structural.test",
                ],
            )
        assert result.current_score == 15.0

    def test_empty_rule_ids_only_decays(self) -> None:
        """Pin empty rule ids only decays."""
        cfg = _cfg(
            {
                "frequency": {
                    "half_life_seconds": 10.0,
                    "weights": {"test.rule": 10.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["test.rule"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 10.0):
            result = tracker.update("s1", [])
        assert abs(result.current_score - 5.0) < 1e-9


class TestRollingWindow:
    """Pin Rolling Window."""

    def test_findings_within_window_counted(self) -> None:
        """Pin findings within window counted."""
        cfg = _cfg(
            {
                "frequency": {
                    "rolling_window_seconds": 60.0,
                    "rolling_threshold": 3,
                    "weights": {"r": 1.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        for i in range(3):
            with patch("petasos.session.frequency.time.monotonic", return_value=t0 + i):
                tracker.update("s1", ["r"])

        state = tracker.get_state("s1")
        assert state is not None
        assert len(state.rolling_findings) == 3

    def test_findings_outside_window_pruned(self) -> None:
        """Pin findings outside window pruned."""
        cfg = _cfg(
            {
                "frequency": {
                    "rolling_window_seconds": 10.0,
                    "rolling_threshold": 100,
                    "weights": {"r": 1.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 20.0):
            tracker.update("s1", ["r"])

        state = tracker.get_state("s1")
        assert state is not None
        assert len(state.rolling_findings) == 1

    def test_rolling_threshold_promotes_to_tier1(self) -> None:
        """Pin rolling threshold promotes to tier1."""
        cfg = _cfg(
            {
                "frequency": {
                    "rolling_window_seconds": 60.0,
                    "rolling_threshold": 3,
                    "weights": {"r": 0.01},
                },
                "escalation": {
                    "tier1": 100.0,
                    "tier2": 200.0,
                    "tier3": 300.0,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        for i in range(3):
            with patch("petasos.session.frequency.time.monotonic", return_value=t0 + i):
                result = tracker.update("s1", ["r"])

        assert result.tier == "tier1"
        assert result.current_score < cfg.escalation.tier1

    def test_empty_rolling_window_after_expiry(self) -> None:
        """Pin empty rolling window after expiry."""
        cfg = _cfg(
            {
                "frequency": {
                    "rolling_window_seconds": 5.0,
                    "rolling_threshold": 100,
                    "weights": {"r": 1.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 10.0):
            tracker.update("s1", [])

        state = tracker.get_state("s1")
        assert state is not None
        assert len(state.rolling_findings) == 0


class TestSessionEviction:
    """Pin Session Eviction."""

    def test_ttl_eviction_removes_stale_sessions(self) -> None:
        """Pin ttl eviction removes stale sessions."""
        cfg = _cfg(
            {
                "sessions": {
                    "ttl_seconds": 10.0,
                    "max": 100,
                },
                "frequency": {
                    "weights": {"r": 1.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("stale", ["r"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 20.0):
            tracker.update("fresh", ["r"])

        assert tracker.get_state("stale") is None
        assert tracker.get_state("fresh") is not None

    def test_max_sessions_evicts_oldest_prefers_terminated(self) -> None:
        """Pin max sessions evicts oldest prefers terminated."""
        cfg = _cfg(
            {
                "sessions": {
                    "max": 3,
                    "max_new_per_minute": 100,
                },
                "frequency": {
                    "weights": {"r": 1.0},
                },
                "escalation": {
                    "tier3": 50.0,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 1):
            tracker.update("s2", ["r"])

        tracker.terminate_session("s1")

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 2):
            tracker.update("s3", ["r"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 3):
            tracker.update("s4", ["r"])

        assert tracker.get_state("s1") is None
        assert tracker.size == 3

    def test_eviction_never_removes_current_session(self) -> None:
        """Pin eviction never removes current session."""
        cfg = _cfg(
            {
                "sessions": {
                    "max": 2,
                    "max_new_per_minute": 100,
                },
                "frequency": {
                    "weights": {"r": 1.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 1):
            tracker.update("s2", ["r"])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 2):
            tracker.update("s3", ["r"])

        assert tracker.get_state("s3") is not None
        assert tracker.size == 2

    def test_over_1000_sessions_no_crash(self) -> None:
        """Pin over 1000 sessions no crash."""
        cfg = _cfg(
            {
                "sessions": {
                    "max": 1200,
                    "max_new_per_minute": 2000,
                },
                "frequency": {
                    "weights": {"r": 0.001},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            for i in range(1100):
                tracker.update(f"s{i}", ["r"])

        assert tracker.size <= 1200


class TestRateLimiting:
    """Pin Rate Limiting."""

    def test_new_session_rejected_at_capacity(self) -> None:
        """Pin new session rejected at capacity."""
        cfg = _cfg(
            {
                "sessions": {
                    "max": 2,
                    "max_new_per_minute": 2,
                },
                "frequency": {
                    "weights": {"r": 1.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
            tracker.update("s2", ["r"])
            result = tracker.update("s3", ["r"])

        assert result is RATE_LIMITED_RESULT

    def test_new_session_accepted_under_capacity(self) -> None:
        """Pin new session accepted under capacity."""
        cfg = _cfg(
            {
                "sessions": {
                    "max": 10,
                    "max_new_per_minute": 10,
                },
                "frequency": {
                    "weights": {"r": 1.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["r"])

        assert result is not RATE_LIMITED_RESULT
        assert result.current_score == 1.0

    def test_rate_limit_window_rolls_forward(self) -> None:
        """Pin rate limit window rolls forward."""
        cfg = _cfg(
            {
                "sessions": {
                    "max": 2,
                    "max_new_per_minute": 2,
                },
                "frequency": {
                    "weights": {"r": 1.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
            tracker.update("s2", ["r"])
            rate_limited = tracker.update("s3", ["r"])
        assert rate_limited is RATE_LIMITED_RESULT

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 61):
            result = tracker.update("s3", ["r"])
        assert result is not RATE_LIMITED_RESULT


class TestEdgeCases:
    """Pin Edge Cases."""

    def test_terminated_session_returns_immediately(self) -> None:
        """Pin terminated session returns immediately."""
        cfg = _cfg(
            {
                "frequency": {
                    "weights": {"r": 100.0},
                },
                "escalation": {
                    "tier3": 50.0,
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            r1 = tracker.update("s1", ["r"])
        assert r1.tier == "tier3"
        assert r1.terminated

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 1):
            r2 = tracker.update("s1", ["r"])
        assert r2.tier == "tier3"
        assert r2.terminated
        assert r2.current_score == r1.current_score

    def test_get_state_unknown_session_returns_none(self) -> None:
        """Pin get state unknown session returns none."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)
        assert tracker.get_state("nonexistent") is None

    def test_reset_removes_session(self) -> None:
        """Pin reset removes session."""
        cfg = _cfg(
            {
                "frequency": {
                    "weights": {"r": 1.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
        assert tracker.get_state("s1") is not None

        tracker.reset("s1")
        assert tracker.get_state("s1") is None

    def test_clear_removes_all_sessions_and_timestamps(self) -> None:
        """Pin clear removes all sessions and timestamps."""
        cfg = _cfg(
            {
                "frequency": {
                    "weights": {"r": 1.0},
                },
            }
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
            tracker.update("s2", ["r"])
        assert tracker.size == 2

        tracker.clear()
        assert tracker.size == 0
        assert len(tracker._creation_timestamps) == 0


class TestStaticResults:
    """Pin Static Results."""

    def test_disabled_result_is_frozen(self) -> None:
        """Pin disabled result is frozen."""
        assert DISABLED_RESULT.current_score == 0.0
        assert DISABLED_RESULT.tier == "none"
        assert DISABLED_RESULT.terminated is False
        assert DISABLED_RESULT.rate_limited is False

    def test_rate_limited_result_is_frozen(self) -> None:
        """Pin rate limited result is frozen."""
        assert RATE_LIMITED_RESULT.current_score == 0.0
        assert RATE_LIMITED_RESULT.tier == "none"
        assert RATE_LIMITED_RESULT.terminated is False
        assert RATE_LIMITED_RESULT.rate_limited is True


class TestWeightValidation:
    """Pin Weight Validation."""

    def test_glob_key_with_non_terminal_star_raises(self) -> None:
        """Pin glob key with non terminal star raises."""
        with pytest.raises(ValueError, match="frequency.weights"):
            FrequencyTracker(
                _cfg(
                    {
                        "frequency": {
                            "weights": {"petasos.*.injection": 1.0},
                        },
                    }
                )
            )

    def test_default_weights_used_when_none(self) -> None:
        """Pin default weights used when none."""
        cfg = _cfg(
            {
                "frequency": {
                    "weights": None,
                },
            }
        )
        tracker = FrequencyTracker(cfg)
        expected_exact = {
            "petasos.selfmod.config_write": 10.0,
            "petasos.selfmod.config_ref": 3.0,
        }
        assert tracker._exact_weights == expected_exact
        assert len(tracker._glob_weights) == len(DEFAULT_FREQUENCY_WEIGHTS) - len(expected_exact)

    def test_command_family_default_weight(self) -> None:
        # Build from default weights because construction caches the weight map.
        """Pin command family default weight."""
        tracker = FrequencyTracker(
            _cfg(
                {
                    "frequency": {
                        "weights": None,
                    },
                }
            )
        )
        assert tracker._match_weight("petasos.syntactic.command.fetch-exec") == 3.0


_SECRET = b"test-secret-key-32-bytes-long!!!"


class TestSessionToken:
    """Pin Session Token."""

    def test_backward_compat_no_secret(self) -> None:
        """Pin backward compat no secret."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)
        with patch("petasos.session.frequency.time.monotonic", return_value=1000.0):
            tracker.update("s1", [])
        assert tracker.get_state("s1") is not None
        tracker.terminate_session("s1")
        state = tracker.get_state("s1")
        assert state is not None and state.terminated
        tracker.reset("s1")
        assert tracker.get_state("s1") is None

    def test_valid_token_accepted(self) -> None:
        """Pin valid token accepted."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg, secrets=Secrets(session_secret=_SECRET))
        token = tracker.mint_token("s1", "host-a")
        with patch("petasos.session.frequency.time.monotonic", return_value=1000.0):
            result = tracker.update(token, ["petasos.syntactic.injection.ignore-previous"])
        assert result.current_score > 0
        state = tracker.get_state(token)
        assert state is not None
        assert state.last_score == result.current_score

    def test_mint_token_without_secret_raises(self) -> None:
        """Pin mint token without secret raises."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)
        with pytest.raises(ValueError, match="no session_secret configured"):
            tracker.mint_token("s1", "host")

    def test_mint_token_rejects_null_bytes(self) -> None:
        """Pin mint token rejects null bytes."""
        cfg = _cfg()
        tracker = FrequencyTracker(cfg, secrets=Secrets(session_secret=_SECRET))
        with pytest.raises(ValueError, match="null bytes"):
            tracker.mint_token("\x00abc", "host")
        with pytest.raises(ValueError, match="null bytes"):
            tracker.mint_token("s1", "host\x00evil")


def _pinned_tracker(cfg: PetasosConfig) -> tuple[FrequencyTracker, LineageRegistry]:
    registry = LineageRegistry(cfg)
    tracker = FrequencyTracker(cfg, is_pinned=registry.is_pinned, on_terminate=registry.unregister)
    return tracker, registry


class TestLineagePinning:
    """Pin Lineage Pinning."""

    def test_terminated_child_unpins_parent(self) -> None:
        """Pin terminated child unpins parent."""
        tracker, registry = _pinned_tracker(_cfg())
        registry.register("child", "parent")
        assert registry.is_pinned("parent") is True
        tracker.terminate_session("child")
        assert registry.is_pinned("parent") is False

    def test_passive_eviction_retries_after_unpin(self) -> None:
        """Pin passive eviction retries after unpin."""
        cfg = _cfg(
            {
                "sessions": {
                    "ttl_seconds": 10.0,
                },
            }
        )
        tracker, registry = _pinned_tracker(cfg)
        clock = {"t": 0.0}

        def _now() -> float:
            return clock["t"]

        with patch("petasos.session.frequency.time.monotonic", _now):
            tracker.update("parent", [])
            registry.register("child", "parent")
            clock["t"] = 100.0
            tracker.update("trigger", [])
            assert tracker.get_state("parent") is not None
            registry.unregister("child")
            clock["t"] = 200.0
            tracker.update("trigger2", [])
            assert tracker.get_state("parent") is None

    def test_terminated_parent_ttl_evicted_unpins(self) -> None:
        """Pin terminated parent ttl evicted unpins."""
        cfg = _cfg(
            {
                "sessions": {
                    "ttl_seconds": 10.0,
                },
            }
        )
        tracker, registry = _pinned_tracker(cfg)
        clock = {"t": 0.0}

        def _now() -> float:
            return clock["t"]

        with patch("petasos.session.frequency.time.monotonic", _now):
            tracker._sessions["parent"] = SessionState(
                last_score=0.0, last_update=0.0, terminated=True
            )
            tracker._ttl_deque.append((10.0, "parent"))
            registry.register("parent", "grandparent")
            assert registry.is_pinned("grandparent") is True
            clock["t"] = 100.0
            tracker.update("trigger", [])
            assert tracker.get_state("parent") is None
            assert registry.is_pinned("grandparent") is False

    def test_pinning_hard_ceiling(self, caplog: pytest.LogCaptureFixture) -> None:
        # See docs/architecture/rationale.md, "Lineage lock order".
        """Pin pinning hard ceiling."""
        cfg = _cfg(
            {
                "sessions": {
                    "max": 2,
                },
            }
        )
        tracker, registry = _pinned_tracker(cfg)
        parents = [f"p{i}" for i in range(5)]
        with caplog.at_level(logging.WARNING):
            for p in parents:
                registry.register(f"c_{p}", p)
                tracker.update(p, [])
                assert tracker.size <= 2 * cfg.sessions.max

        assert tracker.get_state("p0") is None
        assert tracker.is_terminated("p0") is False
        assert any("hard ceiling" in r.getMessage().lower() for r in caplog.records)

        tracker.terminate_session("survivor")
        tracker.reset("survivor")
        assert tracker.is_terminated("survivor") is True

    def test_feature_off_eviction_is_unchanged(self) -> None:
        """Pin feature off eviction is unchanged."""
        cfg = _cfg(
            {
                "sessions": {
                    "max": 1,
                },
            }
        )
        tracker = FrequencyTracker(cfg)
        tracker.update("a", [])
        tracker.update("b", [])
        assert tracker.size == 1
        assert tracker.get_state("a") is None
        assert tracker.get_state("b") is not None


class TestWeightCapQuantization:
    """Pin Weight Cap Quantization."""

    def test_raw_below_cap_contributes_nothing(self) -> None:
        """Pin raw below cap contributes nothing."""
        tracker = FrequencyTracker(_cfg())
        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            res = tracker.update("s1", ["petasos.syntactic.encoding.base64"], weight_cap=3.75)
        assert res.current_score == 0.0
        state = tracker.get_state("s1")
        assert state is not None
        assert state.last_score == 0.0

    def test_raw_at_or_above_cap_contributes_exactly_the_cap(self) -> None:
        """Pin raw at or above cap contributes exactly the cap."""
        tracker = FrequencyTracker(_cfg())
        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            res = tracker.update("s1", ["petasos.syntactic.injection.x"], weight_cap=3.75)
            assert res.current_score == 3.75
            res = tracker.update("s2", ["petasos.syntactic.injection.x"], weight_cap=10.0)
            assert res.current_score == 10.0

    def test_omitting_the_keyword_is_byte_identical(self) -> None:
        """Pin omitting the keyword is byte identical."""
        capped = FrequencyTracker(_cfg())
        plain = FrequencyTracker(_cfg())
        rids = ["petasos.syntactic.injection.x", "petasos.syntactic.encoding.y"]
        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            a = plain.update("s", rids)
            b = capped.update("s", rids, weight_cap=None)
        assert a == b
        assert a.current_score == 13.0

    def test_step8_suppressed_when_capped_contribution_is_zero(self) -> None:
        # Zero-weight capped scans must not arm count-based rolling promotion.
        """Pin step8 suppressed when capped contribution is zero."""
        tracker = FrequencyTracker(
            _cfg(
                {
                    "frequency": {
                        "rolling_threshold": 3,
                    },
                }
            )
        )
        t0 = 1000.0
        for n in range(6):
            with patch("petasos.session.frequency.time.monotonic", return_value=t0 + n):
                res_sub = tracker.update(
                    "s-sub", ["petasos.syntactic.encoding.b64"], weight_cap=3.75
                )
                res_unmapped = tracker.update(
                    "s-ml", ["petasos.promptguard.injection"], weight_cap=3.75
                )
        assert res_sub.tier == "none"
        assert res_unmapped.tier == "none"
        for sid in ("s-sub", "s-ml"):
            state = tracker.get_state(sid)
            assert state is not None
            assert len(state.rolling_findings) == 0

    def test_step8_unchanged_for_uncapped_callers(self) -> None:
        # Uncapped zero-weight findings still enter the count window.
        """Pin step8 unchanged for uncapped callers."""
        tracker = FrequencyTracker(
            _cfg(
                {
                    "frequency": {
                        "rolling_threshold": 3,
                    },
                }
            )
        )
        t0 = 1000.0
        for n in range(3):
            with patch("petasos.session.frequency.time.monotonic", return_value=t0 + n):
                res = tracker.update("s-un", ["petasos.promptguard.injection"])
        assert res.tier == "tier1"
        assert res.current_score == 0.0
