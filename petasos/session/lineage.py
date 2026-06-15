"""Sub-agent delegation lineage registry (PET-107, Option A).

A thread-safe ``child_session_id -> parent_session_id`` edge store that lets the
``ToolCallGuard`` derive a child's tier as ``max(own, parent-chain)``. Edges are
asserted by the *host* (Hermes) on its ``subagent_start``/``subagent_stop``
hooks; the child agent never registers its own edge and never chooses its parent
(see spec D2 — the untrusted surface is the child's tool *content*, already
scanned, not the lineage edge).

Invariant (load-bearing): **no method here ever calls into ``FrequencyTracker``.**
The lock order across the two structures is always tracker → registry (the only
nested case is eviction calling ``is_pinned``/``on_terminate``); because the
registry never reaches back into the tracker, no opposite-order nesting exists
and no deadlock cycle is possible (spec D10).

The clock is ``time.monotonic()`` — the *same* clock ``FrequencyTracker`` uses —
so edge-TTL comparisons here and session-TTL comparisons there agree.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from petasos.config import PetasosConfig

_logger = logging.getLogger(__name__)


class LineageRegistry:
    """Thread-safe store of ``child -> (parent, registered_monotonic)`` edges."""

    def __init__(self, config: PetasosConfig) -> None:
        self._max_depth = config.lineage_max_depth
        self._max_edges = config.lineage_max_edges
        self._edge_ttl = config.lineage_edge_ttl_seconds
        self._lock = threading.Lock()
        self._edges: dict[str, tuple[str, float]] = {}

    def apply_config(self, new_config: PetasosConfig) -> None:
        """PET-126: rebind the cached bounds in place, preserving ``_edges``.

        ``_max_depth`` / ``_max_edges`` / ``_edge_ttl`` are cached at construction
        and read live in ``register`` / ``ancestors`` / ``is_pinned``. The rebind
        runs under ``_lock`` (the same lock those reads take), which is the
        happens-before for the next live scalar read. The load-bearing lock-order
        invariant is preserved: this method touches only registry state and never
        calls into ``FrequencyTracker`` (spec D10).
        """
        with self._lock:
            self._max_depth = new_config.lineage_max_depth
            self._max_edges = new_config.lineage_max_edges
            self._edge_ttl = new_config.lineage_edge_ttl_seconds

    def register(self, child: str, parent: str) -> None:
        """Record (or re-parent) the ``child -> parent`` edge.

        Rejects empty ids and a self-edge (``child == parent``). If ``child``
        already has an edge it is updated **in place** (last-writer-wins, so a
        re-parented child points at its newest parent and a stale clean parent
        cannot mask an escalating one) — an in-place update is *not* a new
        insertion, so it never evicts an unrelated oldest edge. A genuinely new
        ``child`` key enforces ``lineage_max_edges`` by evicting the oldest edge
        by timestamp. Expired edges are opportunistically pruned first.
        """
        if not child or not parent:
            _logger.warning(
                "lineage.register rejected empty id (child=%r parent=%r)", child, parent
            )
            return
        if child == parent:
            _logger.warning("lineage.register rejected self-edge (id=%r)", child)
            return
        now = time.monotonic()
        with self._lock:
            self._prune_expired_locked(now)
            if child in self._edges:
                # Re-parent in place — last-writer-wins, no eviction.
                self._edges[child] = (parent, now)
                return
            if len(self._edges) >= self._max_edges:
                oldest = min(self._edges, key=lambda c: self._edges[c][1])
                del self._edges[oldest]
            self._edges[child] = (parent, now)

    def unregister(self, child: str) -> None:
        """Drop ``child``'s edge. Idempotent — a missed/duplicate stop is a no-op."""
        with self._lock:
            self._edges.pop(child, None)

    def ancestors(self, session_id: str) -> list[str]:
        """Return a **snapshot** list of ancestor ids, nearest-first.

        Built entirely under the lock and returned by value (the lock is
        released on return — the guard then reads the tracker per ancestor with
        no registry lock held, keeping the two locks strictly sequential).
        Bounded by ``lineage_max_depth`` and a ``visited`` set (cycle-safe), and
        stops at the first edge older than ``lineage_edge_ttl_seconds``.
        """
        now = time.monotonic()
        result: list[str] = []
        with self._lock:
            visited: set[str] = {session_id}
            current = session_id
            while len(result) < self._max_depth:
                edge = self._edges.get(current)
                if edge is None:
                    break
                parent, registered = edge
                if now - registered > self._edge_ttl:
                    break
                if parent in visited:
                    break  # cycle guard
                result.append(parent)
                visited.add(parent)
                current = parent
        return result

    def is_pinned(self, session_id: str) -> bool:
        """True iff ``session_id`` is the parent of >=1 *live* edge.

        "Live" = non-expired (monotonic TTL) and the child still registered
        (an unregistered child has no entry in ``_edges``). Cheap; takes only
        the registry lock. Shares ``time.monotonic()`` with ``FrequencyTracker``
        so the pin window and the session-TTL window agree.

        This is the predicate ``FrequencyTracker`` consults to keep a tier-1/2
        parent alive while a child references it. It MUST stay O(small) and
        non-blocking, and must never call back into the tracker.
        """
        now = time.monotonic()
        with self._lock:
            for parent, registered in self._edges.values():
                if parent == session_id and (now - registered) <= self._edge_ttl:
                    return True
        return False

    def _prune_expired_locked(self, now: float) -> None:
        expired = [child for child, (_p, ts) in self._edges.items() if (now - ts) > self._edge_ttl]
        for child in expired:
            del self._edges[child]
