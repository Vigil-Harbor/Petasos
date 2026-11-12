"""Pin guard reload while preserving risk, spawn history and secret binding.

See docs/architecture/rationale.md, "Inherited guard tiers"."""

from __future__ import annotations

import pytest

from petasos.config.schema import from_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.guard.fanout import SpawnBudget
from petasos.guard.guard import ToolCallGuard
from petasos.pipeline import Pipeline
from petasos.session.frequency import FrequencyTracker


def _cfg(partial: dict[str, object] | None = None) -> PetasosConfig:
    """Build a config tree from a partial document."""
    if not partial:
        return PetasosConfig()
    return from_mapping(PetasosConfig, partial)


def _guard(
    *,
    config: PetasosConfig | None = None,
    secrets: Secrets | None = None,
) -> ToolCallGuard:
    cfg = config or _cfg()
    pipe = Pipeline(config=cfg, secrets=secrets, host_id="host-1" if secrets else "")
    tracker = FrequencyTracker(cfg, secrets=secrets)
    return ToolCallGuard(pipe, tracker, cfg, secrets=secrets)


async def test_guard_apply_config_updates_delegate_set() -> None:
    """Pin guard apply config updates delegate set."""
    guard = _guard(
        config=_cfg(
            {
                "tools": {
                    "fanout": {
                        "enabled": True,
                        "max_per_window": 1,
                    },
                    "delegate_names": ("delegate_task",),
                },
            }
        )
    )
    guard.apply_config(
        _cfg(
            {
                "tools": {
                    "fanout": {
                        "enabled": True,
                        "max_per_window": 1,
                    },
                    "delegate_names": ("spawn_agent",),
                },
            }
        )
    )

    assert (await guard.evaluate("delegate_task", {}, "s1")).allowed
    assert (await guard.evaluate("delegate_task", {}, "s1")).allowed

    assert (await guard.evaluate("spawn_agent", {}, "s2")).allowed
    blocked = await guard.evaluate("spawn_agent", {}, "s2")
    assert not blocked.allowed
    assert "fan-out" in blocked.reason


def test_guard_apply_config_resizes_fanout_window_preserving_counters() -> None:
    """Pin guard apply config resizes fanout window preserving counters."""
    guard = _guard(
        config=_cfg(
            {
                "tools": {
                    "fanout": {
                        "window_seconds": 60.0,
                    },
                },
            }
        )
    )
    budget = guard._spawn_budget
    assert budget.try_consume("sess", cap=5, now=100.0) is True
    assert "sess" in budget._events
    assert budget._last_sweep == 100.0

    guard.apply_config(
        _cfg(
            {
                "tools": {
                    "fanout": {
                        "window_seconds": 10.0,
                    },
                },
            }
        )
    )

    assert budget._window == 10.0
    assert "sess" in budget._events
    assert budget._last_sweep == 100.0

    assert budget.try_consume("sess", cap=1, now=111.0) is True


def test_guard_set_window_evicts_under_shrunk_window_directly() -> None:
    """Pin guard set window evicts under shrunk window directly."""
    budget = SpawnBudget(60.0)
    assert budget.try_consume("s", cap=1, now=100.0) is True
    assert budget.try_consume("s", cap=1, now=130.0) is False
    budget.set_window(10.0)
    assert budget.try_consume("s", cap=1, now=130.0) is True


def test_guard_apply_config_propagates_to_its_tracker() -> None:
    """Pin guard apply config propagates to its tracker."""
    guard = _guard(
        config=_cfg(
            {
                "frequency": {
                    "weights": {"x": 5.0},
                },
            }
        )
    )
    tracker = guard._frequency_tracker
    r1 = tracker.update("s1", ["x"])
    assert r1.current_score == 5.0

    guard.apply_config(
        _cfg(
            {
                "frequency": {
                    "weights": {"x": 25.0},
                },
            }
        )
    )

    assert tracker._config is guard._config
    r2 = tracker.update("s1", ["x"])
    assert r2.current_score > r1.current_score + 20


def test_guard_validate_config_d8_violation_is_atomic() -> None:
    """Pin guard validate config violation is atomic."""
    guard = _guard(
        config=_cfg(
            {
                "tools": {
                    "delegate_names": ("delegate_task",),
                    "exempt": ("spawn_agent",),
                },
            }
        )
    )
    bad = _cfg(
        {
            "tools": {
                "delegate_names": ("spawn_agent",),
                "exempt": ("spawn_agent",),
            },
        }
    )

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
    # Session secrets stay fixed so existing tokens remain valid after reconfiguration.
    """Pin guard apply config preserves session secret."""
    secret = b"k" * 32
    secrets = Secrets(session_secret=secret)
    cfg = _cfg()
    pipe = Pipeline(config=cfg, secrets=secrets, host_id="host-1")
    tracker = FrequencyTracker(cfg, secrets=secrets)
    guard = ToolCallGuard(pipe, tracker, cfg, secrets=secrets)

    token = tracker.mint_token("sess", "host-1")
    tracker.update(token, [])
    assert guard._read_state("sess") is not None

    guard.apply_config(_cfg({"frequency": {"half_life_seconds": 30.0}}))
    assert tracker._session_secret == secret
    assert guard._secrets.session_secret == secret
    assert tracker.get_state(token) is not None
    assert guard._derive_tier("sess") != "tier3"
