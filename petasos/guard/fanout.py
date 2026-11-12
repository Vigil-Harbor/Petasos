"""Bound delegation fan-out with a rolling window."""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from petasos.guard.guard import ToolCallGuard


class SpawnBudget:
    """Consume per-session spawn capacity atomically within a rolling window.

    See docs/architecture/rationale.md, "Spawn budget atomicity"."""

    def __init__(self, window_seconds: float) -> None:
        self._window = window_seconds
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = {}
        self._last_sweep = 0.0

    def set_window(self, seconds: float) -> None:
        """Change the window under lock while preserving buffered timestamps."""
        with self._lock:
            self._window = seconds

    def try_consume(self, session_id: str, cap: int, now: float) -> bool:
        """Atomically consume one spawn slot if the live count is below the cap."""
        with self._lock:
            cutoff = now - self._window
            # See docs/architecture/rationale.md, "Spawn budget atomicity".
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
    """Return the tier-adjusted fan-out cap; tier-two attempts use a cap of one."""
    base = self._config.tools.fanout.max_per_window
    if tier == "tier1":
        return max(1, base // 2)
    if tier == "tier2":
        return 1
    return base
