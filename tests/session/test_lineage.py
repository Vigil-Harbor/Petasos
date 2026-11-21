"""Pin bounded ancestry, reparenting and most-restrictive tier combination.

See docs/architecture/rationale.md, "Lineage lock order"."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.session.escalation import max_tier
from petasos.session.lineage import LineageRegistry

_CLOCK = "petasos.session.lineage.time.monotonic"


def _cfg(partial: dict[str, object] | None = None) -> PetasosConfig:
    """Build a config tree from a partial document."""
    if not partial:
        return PetasosConfig()
    return from_mapping(PetasosConfig, partial)


def _registry(partial: dict[str, object] | None = None) -> LineageRegistry:
    return LineageRegistry(_cfg(partial))


class TestMaxTier:
    def test_returns_highest_rank(self) -> None:
        assert max_tier("none", "tier2", "tier1") == "tier2"
        assert max_tier("tier3", "none") == "tier3"
        assert max_tier("tier1", "tier1") == "tier1"

    def test_no_args_is_none(self) -> None:
        assert max_tier() == "none"
        assert max_tier("none") == "none"

    def test_raises_on_unknown(self) -> None:
        with pytest.raises(ValueError, match="unknown tier"):
            max_tier("bogus")
        with pytest.raises(ValueError, match="unknown tier"):
            max_tier("none", "tier4")


class TestRegisterUnregister:
    def test_basic_edge_and_ancestors(self) -> None:
        reg = _registry()
        reg.register("child", "parent")
        assert reg.ancestors("child") == ["parent"]

    def test_unregister_drops_edge_and_is_idempotent(self) -> None:
        reg = _registry()
        reg.register("child", "parent")
        reg.unregister("child")
        assert reg.ancestors("child") == []
        reg.unregister("child")
        reg.unregister("never-seen")

    def test_self_edge_rejected(self) -> None:
        reg = _registry()
        reg.register("x", "x")
        assert reg.ancestors("x") == []

    def test_empty_ids_rejected(self) -> None:
        reg = _registry()
        reg.register("", "parent")
        reg.register("child", "")
        assert reg.ancestors("child") == []
        assert reg.ancestors("") == []

    def test_register_is_idempotent_same_parent(self) -> None:
        reg = _registry()
        reg.register("c", "p")
        reg.register("c", "p")
        assert reg.ancestors("c") == ["p"]


class TestReparent:
    def test_last_writer_wins(self) -> None:
        reg = _registry()
        reg.register("c", "stale_parent")
        reg.register("c", "fresh_parent")
        assert reg.ancestors("c") == ["fresh_parent"]

    def test_reparent_in_place_does_not_evict_unrelated_edge_at_cap(self) -> None:
        reg = _registry(
            {
                "tools": {
                    "lineage": {
                        "max_edges": 2,
                    },
                },
            }
        )
        with patch(_CLOCK, return_value=1.0):
            reg.register("c1", "p1")
        with patch(_CLOCK, return_value=2.0):
            reg.register("c2", "p2")
        with patch(_CLOCK, return_value=3.0):
            reg.register("c1", "p3")
        with patch(_CLOCK, return_value=3.5):
            assert reg.ancestors("c1") == ["p3"]
            assert reg.ancestors("c2") == ["p2"]


class TestAncestorsWalk:
    def test_multi_hop_nearest_first(self) -> None:
        reg = _registry()
        reg.register("c", "p")
        reg.register("p", "g")
        reg.register("g", "gg")
        assert reg.ancestors("c") == ["p", "g", "gg"]

    def test_bounded_by_max_depth(self) -> None:
        reg = _registry(
            {
                "tools": {
                    "lineage": {
                        "max_depth": 2,
                    },
                },
            }
        )
        reg.register("c", "p")
        reg.register("p", "g")
        reg.register("g", "gg")
        assert reg.ancestors("c") == ["p", "g"]

    def test_cycle_is_safe(self) -> None:
        reg = _registry()
        reg.register("a", "b")
        reg.register("b", "a")
        assert reg.ancestors("a") == ["b"]
        assert reg.ancestors("b") == ["a"]

    def test_no_edge_returns_empty(self) -> None:
        reg = _registry()
        assert reg.ancestors("orphan") == []


class TestTtlAndCap:
    def test_expired_edge_skipped_in_walk(self) -> None:
        reg = _registry(
            {
                "tools": {
                    "lineage": {
                        "edge_ttl_seconds": 10.0,
                    },
                },
            }
        )
        with patch(_CLOCK, return_value=0.0):
            reg.register("c", "p")
        with patch(_CLOCK, return_value=5.0):
            assert reg.ancestors("c") == ["p"]
        with patch(_CLOCK, return_value=20.0):
            assert reg.ancestors("c") == []

    def test_max_edges_evicts_oldest(self) -> None:
        reg = _registry(
            {
                "tools": {
                    "lineage": {
                        "max_edges": 2,
                    },
                },
            }
        )
        with patch(_CLOCK, return_value=1.0):
            reg.register("c1", "p")
        with patch(_CLOCK, return_value=2.0):
            reg.register("c2", "p")
        with patch(_CLOCK, return_value=3.0):
            reg.register("c3", "p")
        with patch(_CLOCK, return_value=3.5):
            assert reg.ancestors("c1") == []
            assert reg.ancestors("c2") == ["p"]
            assert reg.ancestors("c3") == ["p"]


class TestIsPinned:
    def test_parent_of_live_edge_is_pinned(self) -> None:
        reg = _registry()
        reg.register("c", "p")
        assert reg.is_pinned("p") is True
        assert reg.is_pinned("c") is False

    def test_unregister_unpins_parent(self) -> None:
        reg = _registry()
        reg.register("c", "p")
        reg.unregister("c")
        assert reg.is_pinned("p") is False

    def test_expired_edge_does_not_pin(self) -> None:
        reg = _registry(
            {
                "tools": {
                    "lineage": {
                        "edge_ttl_seconds": 10.0,
                    },
                },
            }
        )
        with patch(_CLOCK, return_value=0.0):
            reg.register("c", "p")
        with patch(_CLOCK, return_value=100.0):
            assert reg.is_pinned("p") is False
