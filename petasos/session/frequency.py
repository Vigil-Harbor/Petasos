from __future__ import annotations

import hashlib
import hmac as _hmac
import logging
import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from petasos.session.escalation import evaluate_tier

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from petasos.config import PetasosConfig

_logger = logging.getLogger(__name__)

DEFAULT_FREQUENCY_WEIGHTS: dict[str, float] = {
    "petasos.syntactic.injection.*": 10.0,
    "petasos.syntactic.structural.*": 5.0,
    "petasos.syntactic.encoding.*": 3.0,
    # PET-94 Decision 3.2 — encoding parity (both are suppressible content-shaped
    # heuristics). Bound: <=5 command rules fire per scan x 3.0 = 15 points, ==
    # default tier1_threshold and well below the 50.0 tier3 termination floor, so
    # a single shell-heavy param cannot terminate a session. The weight is a
    # documented constraint, not a free parameter: a nudge above 3.0 would cross
    # the maximally-stacked single scan into tier2 territory.
    "petasos.syntactic.command.*": 3.0,
}

_RATE_LIMIT_WINDOW_SECONDS: float = 60.0


@dataclass
class SessionState:
    last_score: float
    last_update: float
    rolling_findings: deque[float] = field(default_factory=deque)
    terminated: bool = False


@dataclass(frozen=True)
class FrequencyUpdateResult:
    previous_score: float
    current_score: float
    tier: str
    terminated: bool
    rate_limited: bool = False


@dataclass(frozen=True)
class SessionToken:
    session_id: str
    host_id: str
    hmac_digest: str


DISABLED_RESULT = FrequencyUpdateResult(
    previous_score=0.0, current_score=0.0, tier="none", terminated=False
)
RATE_LIMITED_RESULT = FrequencyUpdateResult(
    previous_score=0.0, current_score=0.0, tier="none", terminated=False, rate_limited=True
)


class FrequencyTracker:
    def __init__(
        self,
        config: PetasosConfig,
        *,
        is_pinned: Callable[[str], bool] | None = None,
        on_terminate: Callable[[str], None] | None = None,
    ) -> None:
        self._half_life = config.frequency_half_life_seconds
        self._rolling_window = config.rolling_window_seconds
        self._rolling_threshold = config.rolling_threshold
        self._max_sessions = config.max_sessions
        self._session_ttl = config.session_ttl_seconds
        self._max_new_per_minute = config.max_new_sessions_per_minute
        self._config = config
        self._session_secret: bytes | None = config.session_secret

        # PET-107: cross-thread access from concurrent delegated children. The
        # RLock guards ALL mutable state (sessions, tombstones, deques). Internal
        # helpers assume it is held (RLock tolerates re-entry).
        self._lock = threading.RLock()
        # PET-107 D6: lineage pinning + termination unpin. Both run INSIDE this
        # tracker's critical section during eviction/tombstoning — by contract
        # they are O(1), non-blocking, must not acquire this lock or call any
        # FrequencyTracker method, and only touch the lineage registry. The
        # shipped wiring (registry.is_pinned / registry.unregister) satisfies
        # this, and the registry never calls back into the tracker, so the only
        # nesting is tracker -> registry (no deadlock cycle, spec D10).
        self._is_pinned = is_pinned
        self._on_terminate = on_terminate

        raw_weights = (
            config.frequency_weights
            if config.frequency_weights is not None
            else DEFAULT_FREQUENCY_WEIGHTS
        )

        self._exact_weights: dict[str, float] = {}
        glob_entries: list[tuple[str, float]] = []
        for key, weight in raw_weights.items():
            if key.endswith(".*"):
                prefix = key[:-2]
                if "*" in prefix:
                    raise ValueError(f"glob key has '*' in non-terminal position: {key!r}")
                glob_entries.append((prefix, weight))
            elif "*" in key:
                raise ValueError(f"weight key has '*' in non-terminal position: {key!r}")
            else:
                self._exact_weights[key] = weight

            if weight < 0 or not math.isfinite(weight):
                raise ValueError(f"weight must be non-negative and finite: {key!r}={weight!r}")

        glob_entries.sort(key=lambda e: len(e[0]), reverse=True)
        self._glob_weights: list[tuple[str, float]] = glob_entries

        self._sessions: dict[str, SessionState] = {}
        self._creation_timestamps: deque[float] = deque()
        self._terminated_ids: OrderedDict[str, None] = OrderedDict()
        self._max_terminated: int = config.max_terminated_tombstones
        self._ttl_deque: deque[tuple[float, str]] = deque()

    def apply_config(self, new_config: PetasosConfig) -> None:
        """Re-read tunables from ``new_config`` in place, preserving session state.

        PET-126: the live-reconfigure hook. Re-parses ``frequency_weights`` and
        re-reads the seven cached scalars without reconstructing the tracker, so
        accumulated per-session scores, tombstones, and rolling-window deques
        survive a Config Editor save or a cross-process reload.

        Atomicity (spec Decision 5): the full ``frequency_weights`` validation
        lives here, not in ``PetasosConfig.__post_init__``, so a malformed glob
        key or a negative/non-finite weight passes ``from_dict`` but must abort
        ``reconfigure`` before any live state is touched. The parse is therefore
        *staged* into locals first (may raise) and only then *committed* under
        ``_lock``; the rebind and the on-shrink tombstone trim share that one
        critical section (``_enforce_tombstone_cap`` assumes the lock is held).

        ``_session_secret`` is treated as immutable (spec Decision 2): it is never
        rebound here, at either the pipeline or the guard tracker, so HMAC-bound
        session tokens minted before the reload still verify afterward.
        """
        # Stage: re-run the full weight parse (mirrors __init__). May raise
        # ValueError on a malformed glob key or a negative/non-finite weight;
        # nothing has been mutated yet, so reconfigure aborts cleanly.
        raw_weights = (
            new_config.frequency_weights
            if new_config.frequency_weights is not None
            else DEFAULT_FREQUENCY_WEIGHTS
        )
        new_exact_weights: dict[str, float] = {}
        new_glob_entries: list[tuple[str, float]] = []
        for key, weight in raw_weights.items():
            if key.endswith(".*"):
                prefix = key[:-2]
                if "*" in prefix:
                    raise ValueError(f"glob key has '*' in non-terminal position: {key!r}")
                new_glob_entries.append((prefix, weight))
            elif "*" in key:
                raise ValueError(f"weight key has '*' in non-terminal position: {key!r}")
            else:
                new_exact_weights[key] = weight

            if weight < 0 or not math.isfinite(weight):
                raise ValueError(f"weight must be non-negative and finite: {key!r}={weight!r}")

        new_glob_entries.sort(key=lambda e: len(e[0]), reverse=True)

        # Commit: rebind scalars + weights + _config under the lock, then trim
        # tombstones (a no-op unless _max_terminated shrank below the live count).
        # _session_secret is intentionally NOT rebound (Decision 2).
        with self._lock:
            self._half_life = new_config.frequency_half_life_seconds
            self._rolling_window = new_config.rolling_window_seconds
            self._rolling_threshold = new_config.rolling_threshold
            self._max_sessions = new_config.max_sessions
            self._session_ttl = new_config.session_ttl_seconds
            self._max_new_per_minute = new_config.max_new_sessions_per_minute
            self._max_terminated = new_config.max_terminated_tombstones
            self._exact_weights = new_exact_weights
            self._glob_weights = new_glob_entries
            self._config = new_config
            self._enforce_tombstone_cap()

    @property
    def requires_token(self) -> bool:
        return self._session_secret is not None

    def mint_token(self, session_id: str, host_id: str) -> SessionToken:
        if self._session_secret is None:
            raise ValueError("cannot mint token: no session_secret configured")
        if not session_id:
            raise ValueError("session_id must be non-empty")
        if not host_id:
            raise ValueError("host_id must be non-empty")
        if "\x00" in session_id or "\x00" in host_id:
            raise ValueError("session_id and host_id must not contain null bytes")
        digest = _hmac.new(
            self._session_secret,
            session_id.encode() + b"\x00" + host_id.encode(),
            hashlib.sha256,
        ).hexdigest()
        return SessionToken(session_id=session_id, host_id=host_id, hmac_digest=digest)

    def _resolve_session_id(self, session: str | SessionToken) -> str:
        if isinstance(session, str):
            if self._session_secret is not None:
                raise ValueError(
                    "session_secret is configured: pass a SessionToken, not a bare string"
                )
            return session
        if self._session_secret is not None:
            expected = _hmac.new(
                self._session_secret,
                session.session_id.encode() + b"\x00" + session.host_id.encode(),
                hashlib.sha256,
            ).hexdigest()
            if not _hmac.compare_digest(expected, session.hmac_digest):
                raise ValueError("invalid session token: HMAC verification failed")
        return session.session_id

    def update(
        self, session: str | SessionToken, rule_ids: Sequence[str]
    ) -> FrequencyUpdateResult:
        with self._lock:
            session_id = self._resolve_session_id(session)
            now = time.monotonic()

            # Step 1: Passive TTL eviction (O(n) amortized via sorted deque).
            # Bounded to a snapshot of the deque length so a re-appended
            # (still-pinned) entry is never re-examined within the same call.
            n = len(self._ttl_deque)
            while n > 0 and self._ttl_deque and self._ttl_deque[0][0] <= now:
                n -= 1
                _expiry, sid = self._ttl_deque.popleft()
                if sid not in self._sessions:
                    continue
                state_ev = self._sessions[sid]
                if state_ev.last_update + self._session_ttl > now:
                    continue
                # D6: a pinned session is retained (a live child still
                # references its tier). Re-queue it with its real expiry key so
                # a later update() reaps it once it unpins; the snapshot bound n
                # guarantees this re-appended entry is not revisited this call.
                if self._is_pinned is not None and self._is_pinned(sid):
                    self._ttl_deque.append((state_ev.last_update + self._session_ttl, sid))
                    continue
                if state_ev.terminated and sid not in self._terminated_ids:
                    self._terminated_ids[sid] = None
                    self._enforce_tombstone_cap()
                del self._sessions[sid]
                # Any session removed here is gone, terminated or not: drop its
                # OWN outgoing lineage edge so it stops pinning its parent. A
                # terminated session was additionally tombstoned above.
                self._fire_on_terminate(sid)

            # Step 1b: Deque compaction
            if len(self._ttl_deque) > 2 * self._max_sessions:
                self._compact_ttl_deque(now)

            # Step 1.5: Tombstone early-return
            if session_id not in self._sessions and session_id in self._terminated_ids:
                sentinel = self._config.tier3_threshold
                return FrequencyUpdateResult(
                    previous_score=sentinel,
                    current_score=sentinel,
                    tier="tier3",
                    terminated=True,
                )

            # Step 2: Get or create session
            is_new = session_id not in self._sessions
            if is_new:
                while (
                    self._creation_timestamps
                    and (now - self._creation_timestamps[0]) > _RATE_LIMIT_WINDOW_SECONDS
                ):
                    self._creation_timestamps.popleft()

                if (
                    len(self._sessions) >= self._max_sessions
                    and len(self._creation_timestamps) >= self._max_new_per_minute
                ):
                    return RATE_LIMITED_RESULT

                self._sessions[session_id] = SessionState(
                    last_score=0.0, last_update=now, rolling_findings=deque()
                )
                self._creation_timestamps.append(now)

            state = self._sessions[session_id]

            # Step 3: Enforce max-sessions cap. _evict_one skips pinned sessions
            # (D6); if pins prevent eviction and the table has grown to the hard
            # 2x ceiling, force-evict the smallest-last_update pinned session.
            if is_new and len(self._sessions) > self._max_sessions:
                self._evict_one(session_id)
                if self._is_pinned is not None and len(self._sessions) > 2 * self._max_sessions:
                    self._force_evict_pinned(session_id)

            # Step 4: Terminated sessions
            if state.terminated:
                return FrequencyUpdateResult(
                    previous_score=state.last_score,
                    current_score=state.last_score,
                    tier="tier3",
                    terminated=True,
                )

            # Step 5: Compute weight
            total_weight = 0.0
            for rid in rule_ids:
                total_weight += self._match_weight(rid)

            # Step 6: Decay previous score
            elapsed = max(0.0, now - state.last_update)
            if elapsed > 0 and state.last_score > 0:
                decayed = state.last_score * math.exp((-elapsed * math.log(2)) / self._half_life)
            else:
                decayed = state.last_score

            # Step 7: Update score
            previous_score = decayed
            current_score = decayed + total_weight

            # Step 8: Update rolling window
            while (
                state.rolling_findings and (now - state.rolling_findings[0]) > self._rolling_window
            ):
                state.rolling_findings.popleft()
            if rule_ids:
                state.rolling_findings.append(now)

            # Step 9: Evaluate tier
            tier = evaluate_tier(current_score, self._config)
            if tier == "none" and len(state.rolling_findings) >= self._rolling_threshold:
                tier = "tier1"

            # Step 10: Update state
            state.last_score = current_score
            state.last_update = now
            self._ttl_deque.append((now + self._session_ttl, session_id))
            if tier == "tier3":
                state.terminated = True
                self._add_tombstone(session_id)
                # Tombstone path (2/4): newly terminated session unpins its parent.
                self._fire_on_terminate(session_id)

            # Step 11: Return
            return FrequencyUpdateResult(
                previous_score=previous_score,
                current_score=current_score,
                tier=tier,
                terminated=state.terminated,
            )

    def get_state(self, session: str | SessionToken) -> SessionState | None:
        with self._lock:
            session_id = self._resolve_session_id(session)
            state = self._sessions.get(session_id)
            if state is None:
                return None
            return SessionState(
                last_score=state.last_score,
                last_update=state.last_update,
                rolling_findings=deque(state.rolling_findings),
                terminated=state.terminated,
            )

    def is_terminated(self, session_id: str) -> bool:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is not None:
                return state.terminated
            return session_id in self._terminated_ids

    def terminate_session(self, session: str | SessionToken) -> None:
        with self._lock:
            session_id = self._resolve_session_id(session)
            state = self._sessions.get(session_id)
            if state is not None:
                state.terminated = True
            self._add_tombstone(session_id)
            # Tombstone path (3/4): explicit termination unpins the parent.
            self._fire_on_terminate(session_id)

    def reset(self, session: str | SessionToken) -> None:
        with self._lock:
            session_id = self._resolve_session_id(session)
            if self._sessions.pop(session_id, None) is not None:
                # Removed session drops its own outgoing lineage edge.
                self._fire_on_terminate(session_id)

    def force_reset(self, session_id: str) -> None:
        with self._lock:
            removed = self._sessions.pop(session_id, None)
            self._terminated_ids.pop(session_id, None)
            if removed is not None:
                # Removed session drops its own outgoing lineage edge.
                self._fire_on_terminate(session_id)

    def clear(self) -> None:
        with self._lock:
            removed_ids = tuple(self._sessions)
            self._sessions.clear()
            self._creation_timestamps.clear()
            self._terminated_ids.clear()
            self._ttl_deque.clear()
            # Every removed session drops its own outgoing lineage edge.
            for session_id in removed_ids:
                self._fire_on_terminate(session_id)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._sessions)

    @property
    def tombstone_count(self) -> int:
        with self._lock:
            return len(self._terminated_ids)

    def _compact_ttl_deque(self, now: float) -> None:
        entries: list[tuple[float, str]] = []
        for sid, state in self._sessions.items():
            expiry = state.last_update + self._session_ttl
            if expiry > now:
                entries.append((expiry, sid))
        entries.sort()
        self._ttl_deque = deque(entries)

    def _match_weight(self, finding_type: str) -> float:
        w = self._exact_weights.get(finding_type)
        if w is not None:
            return w
        for prefix, weight in self._glob_weights:
            if finding_type.startswith(prefix + "."):
                return weight
        return 0.0

    def _fire_on_terminate(self, session_id: str) -> None:
        """Notify the lineage registry that ``session_id`` is gone.

        Runs inside the tracker's critical section; by contract the callback is
        O(1), non-blocking, touches only the lineage registry, and never calls
        back into this tracker (preserving the PET-30/34 direct-write tombstone
        discipline — it must not touch ``_terminated_ids``). Wrapped so a buggy
        callback cannot break tombstoning.
        """
        if self._on_terminate is None:
            return
        try:
            self._on_terminate(session_id)
        except Exception:
            _logger.exception("on_terminate callback failed for session %s", session_id)

    def _add_tombstone(self, session_id: str) -> None:
        if session_id in self._terminated_ids:
            self._terminated_ids.move_to_end(session_id)
        else:
            self._terminated_ids[session_id] = None
        self._enforce_tombstone_cap()

    def _enforce_tombstone_cap(self) -> None:
        while len(self._terminated_ids) > self._max_terminated:
            self._terminated_ids.popitem(last=False)

    def _evict_one(self, protect_id: str) -> None:
        terminated_candidate: tuple[str, float] | None = None
        oldest_candidate: tuple[str, float] | None = None

        for sid, state in self._sessions.items():
            if sid == protect_id:
                continue
            # D6: never evict a pinned session on the normal path — a live child
            # still references its tier. The hard ceiling handles the all-pinned
            # overflow case separately.
            if self._is_pinned is not None and self._is_pinned(sid):
                continue
            if state.terminated and (
                terminated_candidate is None or state.last_update < terminated_candidate[1]
            ):
                terminated_candidate = (sid, state.last_update)
            if oldest_candidate is None or state.last_update < oldest_candidate[1]:
                oldest_candidate = (sid, state.last_update)

        if terminated_candidate is not None:
            sid = terminated_candidate[0]
            # Intentionally not using _add_tombstone(): that calls move_to_end()
            # for existing keys, which would refresh the FIFO position and make
            # the tombstone appear younger than it is.
            if sid not in self._terminated_ids:
                self._terminated_ids[sid] = None
                self._enforce_tombstone_cap()
            del self._sessions[sid]
            # Tombstone path (4/4): an evicted terminated session unpins its parent.
            self._fire_on_terminate(sid)
        elif oldest_candidate is not None:
            # Plain LRU eviction of a non-terminated session: not a tombstone,
            # but the evicted session is gone, so it must still drop its own
            # outgoing edge (mirrors _force_evict_pinned) rather than leave its
            # parent pinned by a session that no longer exists.
            sid = oldest_candidate[0]
            del self._sessions[sid]
            self._fire_on_terminate(sid)

    def _force_evict_pinned(self, protect_id: str) -> None:
        """Hard-ceiling overflow: force-evict the smallest-last_update pinned session.

        Reached only when every eligible session is pinned and the table has
        grown beyond ``2 * max_sessions``. Bounding memory under a spray takes
        precedence over tier-1/2 inheritance: the sacrificed parent is dropped
        (it is non-terminated, so it is NOT tombstoned) and its sub-tree degrades
        to own-tier — a *terminated* ancestor's tombstone survives ``del``, so
        the tier-3 floor (D4) is unaffected. Logs once at WARNING; never raises.
        """
        victim: tuple[str, float] | None = None
        for sid, state in self._sessions.items():
            if sid == protect_id:
                continue
            if victim is None or state.last_update < victim[1]:
                victim = (sid, state.last_update)
        if victim is None:
            return
        sid = victim[0]
        del self._sessions[sid]
        _logger.warning(
            "FrequencyTracker hard ceiling hit (>2x max_sessions=%d): force-evicted "
            "pinned session %s (smallest last_update); its sub-tree degrades to own-tier "
            "per the overflow policy (tier-3 termination is unaffected)",
            self._max_sessions,
            sid,
        )
        # Non-terminated force-evict: fire on_terminate so the evicted session's
        # OWN outgoing edge drops (unpinning ITS parent). The children's inbound
        # edges remain; they read get_state=None -> "none" (own-tier).
        self._fire_on_terminate(sid)
