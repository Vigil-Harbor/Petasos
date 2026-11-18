"""Per-enforcer counters, latches, and rate-limited operator logs.

Counter maps are capped; agent identities live only as long as their objects.
Dropping the oldest counter entry can repeat a line. It does not silence one.
The clocks come from the enforcer, so a test opens a window by advancing time.
"""

from __future__ import annotations

import threading
import uuid
import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from petasos.enforce.types import Clock

_MAX_SESSIONS = 10_000
_MAX_COLD_KEYS = 10_000
_MAX_INGEST_KEYS = 512
_INGEST_KEY_LEN = 64
_MAX_DEGRADED = 10_000
_MAX_EVAL_KEYS = 10_000

_RECONFIGURED = "PETASOS_RECONFIGURED: live config.yaml change applied to the running session"


class Cadence:
    """One rate-limited log clock."""

    def __init__(self, clock: Clock, interval: float) -> None:
        self._clock = clock
        self._interval = interval
        self._lock = threading.Lock()
        self._last = 0.0

    def due(self) -> bool:
        """True when the interval has elapsed, and this call consumes it."""
        now = self._clock.monotonic()
        with self._lock:
            if now - self._last < self._interval:
                return False
            self._last = now
            return True


class KeyCadence:
    """A rate limit per key, capped by dropping the oldest key."""

    def __init__(self, clock: Clock, interval: float, cap: int) -> None:
        self._clock = clock
        self._interval = interval
        self._cap = cap
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def due(self, key: str) -> bool:
        """True when ``key`` may log, and this call consumes that slot."""
        now = self._clock.monotonic()
        with self._lock:
            last = self._last.get(key, 0.0)
            if now - last < self._interval:
                return False
            self._last[key] = now
            if len(self._last) > self._cap:
                del self._last[next(iter(self._last))]
            return True


class Book:
    """The counters and latches one enforcer keeps beside its pipeline."""

    def __init__(self, clock: Clock, interval: float, logger: logging.Logger) -> None:
        self._clock = clock
        self._logger = logger
        self._lock = threading.Lock()
        self.disarm = Cadence(clock, interval)
        self.reload_fail = Cadence(clock, interval)
        self.reconfigured = Cadence(clock, interval)
        self.cold_fail = Cadence(clock, interval)
        self.ingest_unscanned = KeyCadence(clock, interval, _MAX_SESSIONS)
        self._bypass: dict[str, int] = {}
        self._agents: dict[int, tuple[weakref.ReferenceType[object], str]] = {}
        self._cold: dict[tuple[str, str], None] = {}
        self._cold_anon_degraded = False
        self._cold_anon_failed = False
        self._no_arm_guard = False
        self._no_arm_uncorrelated = False
        self._degraded_sessions: set[str] = set()
        self._degraded_pending: dict[tuple[str, str, str], str] = {}
        self._eval_logged: dict[str | None, None] = {}
        self._ingest_seen: dict[tuple[str, str], None] = {}
        self._ingest_excluded: set[str] = set()
        self._fallback: threading.local = threading.local()

    def session_id(self, task_id: str, agent: object | None) -> str:
        """Use a task id, a live weak-referenceable agent, or a fresh anonymous id.

        Opaque agents that cannot be weakly referenced are uncorrelated. Their
        addresses cannot safely identify a conversation after they are freed.
        """
        if task_id:
            return task_id
        if agent is not None:
            key = id(agent)
            with self._lock:
                found = self._agents.get(key)
                if found is not None and found[0]() is agent:
                    return found[1]
                owner = weakref.ref(self)

                def forget(reference: weakref.ReferenceType[object]) -> None:
                    book = owner()
                    if book is not None:
                        with book._lock:
                            current = book._agents.get(key)
                            if current is not None and current[0] is reference:
                                del book._agents[key]

                try:
                    reference = weakref.ref(agent, forget)
                except TypeError:
                    # An opaque object gives us no lifetime notification. Never
                    # retain it or trust its reusable address as a conversation.
                    reference = None
                if reference is not None:
                    session = f"desktop-{uuid.uuid4().hex[:12]}"
                    self._agents[key] = (reference, session)
                    return session
            if self.claim_uncorrelated("uncorrelatable"):
                self._logger.warning(
                    "PETASOS_INGEST_UNCORRELATED cause=agent_not_weak_referenceable "
                    "-- session risk cannot be accumulated for this agent"
                )
        return f"anon-{uuid.uuid4().hex[:8]}"

    def bump_bypass(self, session_id: str) -> int:
        """Count one disarmed call and return the session total."""
        with self._lock:
            count = self._bypass.get(session_id, 0) + 1
            self._bypass[session_id] = count
            if len(self._bypass) > _MAX_SESSIONS:
                del self._bypass[next(iter(self._bypass))]
            return count

    def claim_cold(self, session_id: str | None, event_type: str) -> bool:
        """Reserve one cold-start marker. True when this call won it."""
        with self._lock:
            if session_id is None:
                if event_type == "init_failed":
                    if self._cold_anon_failed:
                        return False
                    self._cold_anon_failed = True
                else:
                    if self._cold_anon_degraded:
                        return False
                    self._cold_anon_degraded = True
                return True
            key = (session_id, event_type)
            if key in self._cold:
                return False
            self._cold[key] = None
            if len(self._cold) > _MAX_COLD_KEYS:
                self._cold.pop(next(iter(self._cold)), None)
            return True

    def release_cold(self, session_id: str | None, event_type: str) -> None:
        """Give a marker back after the spool write failed."""
        with self._lock:
            if session_id is None:
                if event_type == "init_failed":
                    self._cold_anon_failed = False
                else:
                    self._cold_anon_degraded = False
                return
            self._cold.pop((session_id, event_type), None)

    def claim_uncorrelated(self, cause: str) -> bool:
        """True the first time ``cause`` is seen in this process."""
        with self._lock:
            if cause == "no_guard":
                if self._no_arm_guard:
                    return False
                self._no_arm_guard = True
                return True
            if self._no_arm_uncorrelated:
                return False
            self._no_arm_uncorrelated = True
            return True

    def note_ingest_skip(self, canon: str, kind: str, excluded: bool) -> bool:
        """True the first time this skip should be logged."""
        short = canon[:_INGEST_KEY_LEN]
        with self._lock:
            if kind == "excluded" and excluded:
                if short in self._ingest_excluded:
                    return False
                self._ingest_excluded.add(short)
                return True
            key = (short, kind)
            if key in self._ingest_seen:
                return False
            if len(self._ingest_seen) >= _MAX_INGEST_KEYS:
                del self._ingest_seen[next(iter(self._ingest_seen))]
            self._ingest_seen[key] = None
            return True

    def note_eval(self, key: str | None) -> bool:
        """True the first time this evaluation failure should be logged at error."""
        with self._lock:
            first = key not in self._eval_logged
            if first:
                self._eval_logged[key] = None
                if len(self._eval_logged) > _MAX_EVAL_KEYS:
                    self._eval_logged.pop(next(iter(self._eval_logged)), None)
            return first

    def degraded_recorded(self, session_id: str) -> bool:
        """True when a confirmed degraded approve already covers ``session_id``."""
        with self._lock:
            return session_id in self._degraded_sessions

    def note_degraded_pending(
        self,
        session_id: str,
        key: tuple[str, str, str] | None,
    ) -> None:
        """Remember a degraded approve until the host confirms it."""
        if key is None:
            return
        with self._lock:
            self._degraded_pending[key] = session_id
            if len(self._degraded_pending) > _MAX_DEGRADED:
                del self._degraded_pending[next(iter(self._degraded_pending))]

    def apply_degraded(
        self,
        key: tuple[str, str, str] | None,
        confirmed: bool,
    ) -> None:
        """Record the session when ``confirmed`` and a pending ask exists."""
        if key is None:
            return
        with self._lock:
            session = self._degraded_pending.pop(key, None)
            if confirmed and session is not None:
                self._degraded_sessions.add(session)

    def log_reconfigured(self, logger: logging.Logger | None = None) -> None:
        """The live-change line, at most once per interval."""
        if self.reconfigured.due():
            (logger or self._logger).warning(_RECONFIGURED)

    def log_reload_failure(self, detail: str) -> None:
        """The keep-last-good line, at most once per interval."""
        if self.reload_fail.due():
            self._logger.warning("PETASOS_RELOAD_FAILED: %s; keeping last-good config", detail)

    def set_fallback(self, outcome: str | None) -> None:
        """Record the syntactic-scan outcome for this thread."""
        self._fallback.outcome = outcome

    def take_fallback(self) -> str | None:
        """Read and clear this thread's syntactic-scan outcome."""
        outcome = getattr(self._fallback, "outcome", None)
        self._fallback.outcome = None
        if isinstance(outcome, str):
            return outcome
        return None


Log = Callable[[str], None]
