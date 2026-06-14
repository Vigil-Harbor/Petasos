"""PET-107: LineageRegistry unit tests + max_tier combinator.

Covers the spec's ``test_lineage_registry_*`` row: register/unregister
idempotency, self-edge + empty-id rejection, last-writer-wins re-parent
(in-place, no collateral eviction at the cap), bounded + cycle-safe chain walk,
monotonic edge-TTL prune, ``max_edges`` cap, ``is_pinned`` only on a live edge,
and ``max_tier`` raising on an unknown tier string.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from petasos.config import PetasosConfig
from petasos.session.escalation import max_tier
from petasos.session.lineage import LineageRegistry

_CLOCK = "petasos.session.lineage.time.monotonic"


def _cfg(**overrides: object) -> PetasosConfig:
    return PetasosConfig(**overrides)  # type: ignore[arg-type]


def _registry(**overrides: object) -> LineageRegistry:
    return LineageRegistry(_cfg(**overrides))


# ---------------------------------------------------------------------------
# max_tier — single ordering source
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# register / unregister
# ---------------------------------------------------------------------------


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
        # idempotent — a missed/duplicate stop is a no-op
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


# ---------------------------------------------------------------------------
# last-writer-wins re-parent
# ---------------------------------------------------------------------------


class TestReparent:
    def test_last_writer_wins(self) -> None:
        reg = _registry()
        reg.register("c", "stale_parent")
        reg.register("c", "fresh_parent")
        # newest parent wins — a stale clean parent cannot mask an escalating one
        assert reg.ancestors("c") == ["fresh_parent"]

    def test_reparent_in_place_does_not_evict_unrelated_edge_at_cap(self) -> None:
        # max_edges=2: fill with c1, c2; re-parenting c1 must NOT evict c2.
        reg = _registry(lineage_max_edges=2)
        with patch(_CLOCK, return_value=1.0):
            reg.register("c1", "p1")
        with patch(_CLOCK, return_value=2.0):
            reg.register("c2", "p2")
        with patch(_CLOCK, return_value=3.0):
            reg.register("c1", "p3")  # in-place update, not a new insertion
        with patch(_CLOCK, return_value=3.5):  # within TTL of the patched edges
            assert reg.ancestors("c1") == ["p3"]
            assert reg.ancestors("c2") == ["p2"]  # survived — no collateral eviction


# ---------------------------------------------------------------------------
# chain walk — bounded + cycle-safe
# ---------------------------------------------------------------------------


class TestAncestorsWalk:
    def test_multi_hop_nearest_first(self) -> None:
        reg = _registry()
        reg.register("c", "p")
        reg.register("p", "g")
        reg.register("g", "gg")
        assert reg.ancestors("c") == ["p", "g", "gg"]

    def test_bounded_by_max_depth(self) -> None:
        reg = _registry(lineage_max_depth=2)
        reg.register("c", "p")
        reg.register("p", "g")
        reg.register("g", "gg")
        assert reg.ancestors("c") == ["p", "g"]

    def test_cycle_is_safe(self) -> None:
        reg = _registry()
        reg.register("a", "b")
        reg.register("b", "a")  # cycle
        # terminates; b appended once, then a is already visited → stop
        assert reg.ancestors("a") == ["b"]
        assert reg.ancestors("b") == ["a"]

    def test_no_edge_returns_empty(self) -> None:
        reg = _registry()
        assert reg.ancestors("orphan") == []


# ---------------------------------------------------------------------------
# edge TTL (monotonic) + max_edges cap
# ---------------------------------------------------------------------------


class TestTtlAndCap:
    def test_expired_edge_skipped_in_walk(self) -> None:
        reg = _registry(lineage_edge_ttl_seconds=10.0)
        with patch(_CLOCK, return_value=0.0):
            reg.register("c", "p")
        with patch(_CLOCK, return_value=5.0):
            assert reg.ancestors("c") == ["p"]  # still live
        with patch(_CLOCK, return_value=20.0):
            assert reg.ancestors("c") == []  # expired

    def test_max_edges_evicts_oldest(self) -> None:
        reg = _registry(lineage_max_edges=2)
        with patch(_CLOCK, return_value=1.0):
            reg.register("c1", "p")
        with patch(_CLOCK, return_value=2.0):
            reg.register("c2", "p")
        with patch(_CLOCK, return_value=3.0):
            reg.register("c3", "p")  # over cap → evict oldest (c1)
        with patch(_CLOCK, return_value=3.5):  # within TTL of the patched edges
            assert reg.ancestors("c1") == []
            assert reg.ancestors("c2") == ["p"]
            assert reg.ancestors("c3") == ["p"]


# ---------------------------------------------------------------------------
# is_pinned — only a live edge
# ---------------------------------------------------------------------------


class TestIsPinned:
    def test_parent_of_live_edge_is_pinned(self) -> None:
        reg = _registry()
        reg.register("c", "p")
        assert reg.is_pinned("p") is True
        assert reg.is_pinned("c") is False  # a leaf child pins nobody

    def test_unregister_unpins_parent(self) -> None:
        reg = _registry()
        reg.register("c", "p")
        reg.unregister("c")
        assert reg.is_pinned("p") is False

    def test_expired_edge_does_not_pin(self) -> None:
        reg = _registry(lineage_edge_ttl_seconds=10.0)
        with patch(_CLOCK, return_value=0.0):
            reg.register("c", "p")
        with patch(_CLOCK, return_value=100.0):
            assert reg.is_pinned("p") is False
