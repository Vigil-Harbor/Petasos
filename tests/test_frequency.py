from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from petasos.config import PetasosConfig
from petasos.session.frequency import (
    DEFAULT_FREQUENCY_WEIGHTS,
    DISABLED_RESULT,
    RATE_LIMITED_RESULT,
    FrequencyTracker,
    SessionState,
)
from petasos.session.lineage import LineageRegistry


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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.test"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 10.0):
            result = tracker.update("s1", [])

        assert abs(result.previous_score - 5.0) < 1e-9

    def test_score_decays_to_near_zero_after_many_half_lives(self) -> None:
        cfg = _cfg(frequency_half_life_seconds=10.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.test"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 500.0):
            result = tracker.update("s1", [])

        assert result.current_score < 1e-6

    def test_zero_elapsed_no_decay(self) -> None:
        cfg = _cfg(frequency_half_life_seconds=10.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            r1 = tracker.update("s1", ["petasos.syntactic.injection.test"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            r2 = tracker.update("s1", ["petasos.syntactic.injection.test"])

        assert r2.previous_score == r1.current_score

    def test_decay_with_zero_initial_score(self) -> None:
        cfg = _cfg(frequency_half_life_seconds=10.0)
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", [])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 10.0):
            result = tracker.update("s1", [])

        assert result.current_score == 0.0

    def test_multiple_updates_produce_reference_sequence(self) -> None:
        cfg = _cfg(
            frequency_half_life_seconds=10.0,
            frequency_weights={"test.rule": 10.0},
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            result = tracker.update("s1", ["petasos.syntactic.injection.test"])
        assert result.current_score == 10.0

    def test_no_match_returns_zero(self) -> None:
        cfg = _cfg(frequency_weights={"petasos.syntactic.injection.*": 10.0})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
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
        cfg = _cfg(
            frequency_half_life_seconds=10.0,
            frequency_weights={"test.rule": 10.0},
        )
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["test.rule"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 10.0):
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
            with patch("petasos.session.frequency.time.monotonic", return_value=t0 + i):
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 20.0):
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
            with patch("petasos.session.frequency.time.monotonic", return_value=t0 + i):
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 10.0):
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("stale", ["r"])

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 20.0):
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 1):
            tracker.update("s2", ["r"])

        tracker.terminate_session("s1")

        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 2):
            tracker.update("s3", ["r"])

        # s1 (terminated) should have been evicted when s4 joins
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 3):
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 1):
            tracker.update("s2", ["r"])
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 2):
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
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
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
            tracker.update("s2", ["r"])
            rate_limited = tracker.update("s3", ["r"])
        assert rate_limited is RATE_LIMITED_RESULT

        # After 61 seconds the creation timestamps have expired
        with patch("petasos.session.frequency.time.monotonic", return_value=t0 + 61):
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
        cfg = _cfg()
        tracker = FrequencyTracker(cfg)
        assert tracker.get_state("nonexistent") is None

    def test_reset_removes_session(self) -> None:
        cfg = _cfg(frequency_weights={"r": 1.0})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["r"])
        assert tracker.get_state("s1") is not None

        tracker.reset("s1")
        assert tracker.get_state("s1") is None

    def test_clear_removes_all_sessions_and_timestamps(self) -> None:
        cfg = _cfg(frequency_weights={"r": 1.0})
        tracker = FrequencyTracker(cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
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
        assert DISABLED_RESULT.rate_limited is False

    def test_rate_limited_result_is_frozen(self) -> None:
        assert RATE_LIMITED_RESULT.current_score == 0.0
        assert RATE_LIMITED_RESULT.tier == "none"
        assert RATE_LIMITED_RESULT.terminated is False
        assert RATE_LIMITED_RESULT.rate_limited is True


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

    def test_command_family_default_weight(self) -> None:
        # Regression for PET-94 (Decision 3.2): the command family carries the
        # default frequency weight 3.0 (encoding parity). _match_weight binds
        # weights at construction, so build over the defaults (frequency_weights=
        # None) — the existing weight tests never exercise the defaults.
        tracker = FrequencyTracker(_cfg(frequency_weights=None))
        assert tracker._match_weight("petasos.syntactic.command.fetch-exec") == 3.0


# ---------------------------------------------------------------------------
# Session token (FREQ-03)
# ---------------------------------------------------------------------------

_SECRET = b"test-secret-key-32-bytes-long!!!"


class TestSessionToken:
    def test_backward_compat_no_secret(self) -> None:
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
        cfg = _cfg(session_secret=_SECRET)
        tracker = FrequencyTracker(cfg)
        token = tracker.mint_token("s1", "host-a")
        with patch("petasos.session.frequency.time.monotonic", return_value=1000.0):
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


# ---------------------------------------------------------------------------
# PET-107 D6: lineage pinning, hard ceiling, termination unpin
# ---------------------------------------------------------------------------


def _pinned_tracker(cfg: PetasosConfig) -> tuple[FrequencyTracker, LineageRegistry]:
    registry = LineageRegistry(cfg)
    tracker = FrequencyTracker(cfg, is_pinned=registry.is_pinned, on_terminate=registry.unregister)
    return tracker, registry


class TestLineagePinning:
    def test_terminated_child_unpins_parent(self) -> None:
        # D6: tombstoning a child fires on_terminate → its edge drops → the
        # parent is no longer pinned.
        tracker, registry = _pinned_tracker(_cfg())
        registry.register("child", "parent")
        assert registry.is_pinned("parent") is True
        tracker.terminate_session("child")
        assert registry.is_pinned("parent") is False

    def test_passive_eviction_retries_after_unpin(self) -> None:
        # D6: a pinned session is skipped (and re-appended, no spin) by passive
        # TTL eviction, then reaped once it unpins on a later update().
        cfg = _cfg(session_ttl_seconds=10.0)
        tracker, registry = _pinned_tracker(cfg)
        clock = {"t": 0.0}

        def _now() -> float:
            return clock["t"]

        with patch("petasos.session.frequency.time.monotonic", _now):
            tracker.update("parent", [])  # created at t=0
            registry.register("child", "parent")  # parent pinned
            clock["t"] = 100.0  # past session_ttl
            tracker.update("trigger", [])  # step-1: parent expired but pinned → skip
            assert tracker.get_state("parent") is not None  # retained, no spin
            registry.unregister("child")  # unpin
            clock["t"] = 200.0
            tracker.update("trigger2", [])  # step-1: parent now reaped
            assert tracker.get_state("parent") is None

    def test_terminated_parent_ttl_evicted_unpins(self) -> None:
        # D6 (4th tombstone path): a terminated session reaped on the step-1 TTL
        # path fires on_terminate → drops its outgoing edge → unpins its parent.
        cfg = _cfg(session_ttl_seconds=10.0)
        tracker, registry = _pinned_tracker(cfg)
        clock = {"t": 0.0}

        def _now() -> float:
            return clock["t"]

        with patch("petasos.session.frequency.time.monotonic", _now):
            # Directly mark terminated to bypass the on_terminate-firing paths,
            # isolating the TTL reap path with a still-live outgoing edge.
            tracker._sessions["parent"] = SessionState(
                last_score=0.0, last_update=0.0, terminated=True
            )
            tracker._ttl_deque.append((10.0, "parent"))
            registry.register("parent", "grandparent")  # grandparent pinned
            assert registry.is_pinned("grandparent") is True
            clock["t"] = 100.0
            tracker.update("trigger", [])  # step-1 reaps the terminated parent
            assert tracker.get_state("parent") is None
            assert registry.is_pinned("grandparent") is False  # edge dropped on reap

    def test_pinning_hard_ceiling(self, caplog: pytest.LogCaptureFixture) -> None:
        # D6: under an all-pinned spray, _sessions never exceeds 2×max_sessions;
        # the smallest-last_update pinned session is force-evicted (logged, no
        # raise) and degrades to OWN-tier (non-tombstoned), while a *terminated*
        # ancestor's tombstone still survives (tier-3 floor unaffected, D4).
        cfg = _cfg(max_sessions=2)
        tracker, registry = _pinned_tracker(cfg)
        parents = [f"p{i}" for i in range(5)]
        with caplog.at_level(logging.WARNING):
            for p in parents:
                registry.register(f"c_{p}", p)  # pin p (child edge)
                tracker.update(p, [])
                assert tracker.size <= 2 * cfg.max_sessions  # bounded, never exceeds 4

        # p0 (smallest last_update) was force-evicted and is NOT tombstoned →
        # its sub-tree reads own-tier, not tier3.
        assert tracker.get_state("p0") is None
        assert tracker.is_terminated("p0") is False
        assert any("hard ceiling" in r.getMessage().lower() for r in caplog.records)

        # Contrast: the tier-3 floor is unaffected — a terminated session's
        # tombstone survives removal from _sessions.
        tracker.terminate_session("survivor")
        tracker.reset("survivor")  # drop the live state; tombstone must remain
        assert tracker.is_terminated("survivor") is True

    def test_feature_off_eviction_is_unchanged(self) -> None:
        # is_pinned=None / on_terminate=None → eviction is byte-for-byte today's:
        # an over-cap insert evicts the oldest, no pinning consulted.
        cfg = _cfg(max_sessions=1)
        tracker = FrequencyTracker(cfg)  # no callbacks
        tracker.update("a", [])
        tracker.update("b", [])  # over cap → 'a' evicted (no pin protection)
        assert tracker.size == 1
        assert tracker.get_state("a") is None
        assert tracker.get_state("b") is not None
