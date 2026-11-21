"""Retain host-asserted ancestry without calling back into the risk tracker.

See docs/architecture/rationale.md, "Lineage lock order"."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from petasos.config.sections import PetasosConfig

_logger = logging.getLogger(__name__)


class LineageRegistry:
    """Thread-safe store of ``child -> (parent, registered_monotonic)`` edges."""

    def __init__(self, config: PetasosConfig) -> None:
        self._config = config
        self._apply_bounds(config)
        self._lock = threading.Lock()
        self._edges: dict[str, tuple[str, float]] = {}

    @property
    def config(self) -> PetasosConfig:
        """The config tree this registry reads."""
        return self._config

    def _apply_bounds(self, config: PetasosConfig) -> None:
        lineage = config.tools.lineage
        self._max_depth = lineage.max_depth
        self._max_edges = lineage.max_edges
        self._edge_ttl = lineage.edge_ttl_seconds

    def apply_config(self, new_config: PetasosConfig) -> None:
        """Apply cached lineage bounds under the registry lock, preserving edges."""
        with self._lock:
            self._config = new_config
            self._apply_bounds(new_config)

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
                # Reparenting must not evict an unrelated edge.
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
                    break
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
