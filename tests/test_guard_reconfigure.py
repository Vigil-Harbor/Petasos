"""PET-126: ToolCallGuard / SpawnBudget / LineageRegistry live reconfigure.

The gateway constructs its OWN tracker, guard, and lineage registry beyond the
pipeline (Decision 4), so a live reload must reconfigure all of them. These tests
pin: delegate-set recognition, fan-out window resize (counters preserved), tracker
propagation, the two-phase D8 validation gate, the immutable session_secret, and
lineage-bound rebinding with edge preservation.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.session.frequency import FrequencyTracker
from petasos.session.guard import SpawnBudget, ToolCallGuard
from petasos.session.lineage import LineageRegistry
from petasos.session.profiles import ResolvedProfile


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "frequency_enabled": True,
        "escalation_enabled": True,
        "tool_guard_enabled": True,
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


def _profile(*, tool_exempt_list: frozenset[str] = frozenset()) -> ResolvedProfile:
    return ResolvedProfile(
        name="test",
        suppress_rules=frozenset(),
        severity_overrides=MappingProxyType({}),
        confidence_floor=0.0,
        tier_thresholds=None,
        pii_entities_extra=(),
        tool_exempt_list=tool_exempt_list,
        tool_alias_map=MappingProxyType({}),
    )


def _guard(
    *, config: PetasosConfig | None = None, profile: ResolvedProfile | None = None
) -> ToolCallGuard:
    cfg = config or _cfg()
    pipe = Pipeline(config=cfg)
    tracker = FrequencyTracker(cfg)
    return ToolCallGuard(pipe, tracker, cfg, profile=profile)


async def test_guard_apply_config_updates_delegate_set() -> None:
    # Regression for PET-126: the gateway guard caches the normalized delegate set
    # at construction; a reload must recompute it so the fan-out gate tracks the
    # new tool name and releases the old one.
    guard = _guard(
        config=_cfg(
            delegate_fanout_enabled=True,
            delegate_max_fanout_per_window=1,
            delegate_tool_names=("delegate_task",),
        )
    )
    guard.apply_config(
        _cfg(
            delegate_fanout_enabled=True,
            delegate_max_fanout_per_window=1,
            delegate_tool_names=("spawn_agent",),
        )
    )

    # The old delegate is no longer gated: repeated calls stay allowed.
    assert (await guard.evaluate("delegate_task", {}, "s1")).allowed
    assert (await guard.evaluate("delegate_task", {}, "s1")).allowed

    # The new delegate is gated: the 2nd call exceeds the budget of 1.
    assert (await guard.evaluate("spawn_agent", {}, "s2")).allowed
    blocked = await guard.evaluate("spawn_agent", {}, "s2")
    assert not blocked.allowed
    assert "fan-out" in blocked.reason


def test_guard_apply_config_resizes_fanout_window_preserving_counters() -> None:
    guard = _guard(config=_cfg(delegate_fanout_window_seconds=60.0))
    budget = guard._spawn_budget
    assert budget.try_consume("sess", cap=5, now=100.0) is True
    assert "sess" in budget._events
    assert budget._last_sweep == 100.0

    guard.apply_config(_cfg(delegate_fanout_window_seconds=10.0))

    # set_window rebinds _window only; counters/sweep state are preserved.
    assert budget._window == 10.0
    assert "sess" in budget._events
    assert budget._last_sweep == 100.0

    # An event from t=100 is in-window under the old 60s window but expires under
    # the shrunk 10s window: at t=111 it is evicted, so a cap-1 consume succeeds.
    assert budget.try_consume("sess", cap=1, now=111.0) is True


def test_guard_set_window_evicts_under_shrunk_window_directly() -> None:
    # Focused SpawnBudget unit: a timestamp inside the old window is evicted once
    # the window shrinks below its age (post-resize eviction).
    budget = SpawnBudget(60.0)
    assert budget.try_consume("s", cap=1, now=100.0) is True
    # Under the 60s window, t=130 still sees the t=100 event -> cap-1 blocks.
    assert budget.try_consume("s", cap=1, now=130.0) is False
    budget.set_window(10.0)
    # Under the 10s window, the t=100 event is 30s stale at t=130 -> evicted.
    assert budget.try_consume("s", cap=1, now=130.0) is True


def test_guard_apply_config_propagates_to_its_tracker() -> None:
    # Decision 4: the guard owns a SEPARATE tracker; apply_config must reconfigure
    # it (a frequency_weights change must change the guard tracker's scoring).
    guard = _guard(config=_cfg(frequency_weights={"x": 5.0}))
    tracker = guard._frequency_tracker
    r1 = tracker.update("s1", ["x"])
    assert r1.current_score == 5.0

    guard.apply_config(_cfg(frequency_weights={"x": 25.0}))

    assert tracker._config is guard._config  # tracker rebound to the guard's config
    r2 = tracker.update("s1", ["x"])
    assert r2.current_score > r1.current_score + 20  # ~5 (decayed) + 25 new weight


def test_guard_validate_config_d8_violation_is_atomic() -> None:
    # A delegate that is also profile-exempt would skip the tier ladder (D8).
    # validate_config raises; apply_config (which calls it first) mutates nothing.
    prof = _profile(tool_exempt_list=frozenset({"spawn_agent"}))
    guard = _guard(config=_cfg(delegate_tool_names=("delegate_task",)), profile=prof)
    bad = _cfg(delegate_tool_names=("spawn_agent",))

    with pytest.raises(ValueError):
        guard.validate_config(bad)

    before_config = guard._config
    before_delegates = guard._delegate_tool_names
    with pytest.raises(ValueError):
        guard.apply_config(bad)

    assert guard._config is before_config
    assert guard._delegate_tool_names == before_delegates
    assert "spawn_agent" not in guard._delegate_tool_names


def test_guard_apply_config_preserves_session_secret() -> None:
    # A reload cfg carrying a differing/None session_secret must NOT rebind the
    # guard tracker's _session_secret (FREQ-03, Decision 2): live tokens still
    # verify and sessions do not flip to tier3.
    secret = b"k" * 32
    cfg = _cfg(session_secret=secret)
    pipe = Pipeline(config=cfg, host_id="host-1")
    tracker = FrequencyTracker(cfg)
    guard = ToolCallGuard(pipe, tracker, cfg)

    token = tracker.mint_token("sess", "host-1")
    tracker.update(token, [])
    assert guard._read_state("sess") is not None  # mint path works

    # Presence flip to None.
    guard.apply_config(_cfg(session_secret=None))
    assert tracker._session_secret == secret  # immutable
    assert guard._config.session_secret == secret  # merge-preserved
    assert tracker.get_state(token) is not None  # token still verifies
    assert guard._derive_tier("sess") != "tier3"  # no fail-secure flip

    # A differing non-None secret is likewise preserved.
    guard.apply_config(_cfg(session_secret=b"different" * 4))
    assert tracker._session_secret == secret
    assert guard._config.session_secret == secret
    assert guard._derive_tier("sess") != "tier3"


def test_lineage_registry_apply_config_updates_bounds() -> None:
    # Changing lineage bounds via apply_config is observed by the next ancestor
    # walk; existing edges survive.
    reg = LineageRegistry(PetasosConfig(lineage_max_depth=2))
    reg.register("a", "b")
    reg.register("b", "c")
    reg.register("c", "d")
    assert reg.ancestors("a") == ["b", "c"]  # bounded to depth 2

    reg.apply_config(PetasosConfig(lineage_max_depth=8))

    assert reg._max_depth == 8
    assert reg.ancestors("a") == ["b", "c", "d"]  # deeper walk after reconfigure
    assert reg._edges  # edges preserved across reconfigure
