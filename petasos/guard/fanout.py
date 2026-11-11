"""Bound delegation fan-out with a rolling window."""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import TYPE_CHECKING

_logger = logging.getLogger("petasos.session.guard")

if TYPE_CHECKING:
    from petasos.guard.guard import ToolCallGuard


class SpawnBudget:
    """Per-session rolling-window spawn counter for the delegation fan-out gate.

    PET-107 Option C. ``try_consume`` prunes the session's window, compares the
    live count to the (tier-adjusted) cap, and on pass appends the timestamp —
    all in one critical section so the read-check-append is atomic (closes the
    concurrent-spawn TOCTOU two children racing against a budget of 1).

    The consumed session's deque is dropped once its window empties; an amortized
    global sweep (at most once per ``window_seconds``) drops the deques of
    sessions that delegated once and were never touched again. Together these
    bound memory by the count of sessions that spawned within roughly the last
    window, not by every distinct session ever seen.
    """

    def __init__(self, window_seconds: float) -> None:
        self._window = window_seconds
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = {}
        self._last_sweep = 0.0

    def set_window(self, seconds: float) -> None:
        """PET-126: rebind the rolling-window length in place.

        Rebinds ``_window`` only: never resets ``_last_sweep`` or ``_events``, so
        buffered spawn timestamps survive a reconfigure. A *shrink* simply
        re-interprets them against the smaller cutoff on the next ``try_consume``
        (older events expire sooner). Taken under ``_lock`` because ``try_consume``
        reads ``_window`` under the same lock.
        """
        with self._lock:
            self._window = seconds

    def try_consume(self, session_id: str, cap: int, now: float) -> bool:
        with self._lock:
            cutoff = now - self._window
            # Amortized global sweep (<= once per window): drop any session whose
            # entire window has expired. The per-session prune below only fires
            # when THAT session is consumed again, so without this a one-shot
            # delegate would leave a stale deque in _events forever and the map
            # would grow with distinct session IDs instead of active windows.
            if now - self._last_sweep >= self._window:
                stale = [sid for sid, ev in self._events.items() if not ev or ev[-1] <= cutoff]
                for sid in stale:
                    del self._events[sid]
                self._last_sweep = now
            dq = self._events.get(session_id)
            if dq is not None:
                while dq and dq[0] <= cutoff:
                    dq.popleft()
                if not dq:
                    del self._events[session_id]
                    dq = None
            count = len(dq) if dq is not None else 0
            if count >= cap:
                return False
            if dq is None:
                dq = deque()
                self._events[session_id] = dq
            dq.append(now)
            return True


def _fanout_cap(self: ToolCallGuard, tier: str) -> int:
    """Tier-adjusted fan-out cap. tier3 is already blocked at Step 3, so it
    never reaches here; tier2 is tightest (1) and is also blocked at Step 6,
    so Step 3.5 only accounts the attempt for a tier-2 delegate."""
    base = self._config.tools.fanout.max_per_window
    if tier == "tier1":
        return max(1, base // 2)
    if tier == "tier2":
        return 1
    return base  # none / below-threshold
