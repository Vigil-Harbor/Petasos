"""Track bounded session risk with token binding and durable termination tombstones."""

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

from petasos.config.secrets import Secrets
from petasos.session.escalation import evaluate_tier

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from petasos.config.sections import PetasosConfig

_logger = logging.getLogger(__name__)

DEFAULT_FREQUENCY_WEIGHTS: dict[str, float] = {
    "petasos.syntactic.injection.*": 10.0,
    "petasos.syntactic.structural.*": 5.0,
    "petasos.syntactic.encoding.*": 3.0,
    # See docs/architecture/rationale.md, "Quantized scan contributions".
    "petasos.syntactic.command.*": 3.0,
    "petasos.selfmod.config_write": 10.0,
    "petasos.selfmod.config_ref": 3.0,
}

_RATE_LIMIT_WINDOW_SECONDS: float = 60.0


@dataclass
class SessionState:
    """Record a session score, termination state and rolling finding window."""

    last_score: float
    last_update: float
    rolling_findings: deque[float] = field(default_factory=deque)
    terminated: bool = False


@dataclass(frozen=True)
class FrequencyUpdateResult:
    """Report score and tier changes from one session update."""

    previous_score: float
    current_score: float
    tier: str
    terminated: bool
    rate_limited: bool = False


@dataclass(frozen=True)
class SessionToken:
    """Bind a session and host identity to an authentication digest."""

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
    """Bound session state and retain terminated-session tombstones."""

    def __init__(
        self,
        config: PetasosConfig,
        *,
        is_pinned: Callable[[str], bool] | None = None,
        on_terminate: Callable[[str], None] | None = None,
        secrets: Secrets | None = None,
    ) -> None:
        held = secrets if secrets is not None else Secrets()
        frequency = config.frequency
        sessions = config.sessions
        self._half_life = frequency.half_life_seconds
        self._rolling_window = frequency.rolling_window_seconds
        self._rolling_threshold = frequency.rolling_threshold
        self._max_sessions = sessions.max
        self._session_ttl = sessions.ttl_seconds
        self._max_new_per_minute = sessions.max_new_per_minute
        self._config = config
        self._secrets = held
        self._session_secret: bytes | None = held.session_secret

        # The reentrant lock guards sessions, tombstones and deques across delegated children.
        self._lock = threading.RLock()
        # See docs/architecture/rationale.md, "Lineage lock order".
        self._is_pinned = is_pinned
        self._on_terminate = on_terminate

        raw_weights = (
            frequency.weights if frequency.weights is not None else DEFAULT_FREQUENCY_WEIGHTS
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
        self._max_terminated: int = sessions.max_tombstones
        self._ttl_deque: deque[tuple[float, str]] = deque()

    @property
    def config(self) -> PetasosConfig:
        """The config tree this tracker reads."""
        return self._config

    def apply_config(self, new_config: PetasosConfig) -> None:
        """Apply validated risk settings while preserving sessions and token binding.

        See docs/architecture/rationale.md, "Quantized scan contributions"."""
        # Parse before mutation so invalid weights leave the live tracker intact.
        frequency = new_config.frequency
        sessions = new_config.sessions
        raw_weights = (
            frequency.weights if frequency.weights is not None else DEFAULT_FREQUENCY_WEIGHTS
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

        # The session secret remains fixed so existing tokens still verify.
        with self._lock:
            self._half_life = frequency.half_life_seconds
            self._rolling_window = frequency.rolling_window_seconds
            self._rolling_threshold = frequency.rolling_threshold
            self._max_sessions = sessions.max
            self._session_ttl = sessions.ttl_seconds
            self._max_new_per_minute = sessions.max_new_per_minute
            self._max_terminated = sessions.max_tombstones
            self._exact_weights = new_exact_weights
            self._glob_weights = new_glob_entries
            self._config = new_config
            self._enforce_tombstone_cap()

    @property
    def requires_token(self) -> bool:
        """Return whether updates require authenticated session tokens."""
        return self._session_secret is not None

    def mint_token(self, session_id: str, host_id: str) -> SessionToken:
        """Return an authenticated token for a session and host."""
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
        self,
        session: str | SessionToken,
        rule_ids: Sequence[str],
        *,
        weight_cap: float | None = None,
    ) -> FrequencyUpdateResult:
        """Score one scan and return its session tier.

        A finite nonnegative cap quantizes contributions to the cap or zero.
        Zero contributions under a cap do not enter the rolling count window.
        None applies uncapped scoring."""
        if weight_cap is not None and (weight_cap < 0 or not math.isfinite(weight_cap)):
            raise ValueError(f"weight_cap must be non-negative and finite: {weight_cap!r}")
        with self._lock:
            session_id = self._resolve_session_id(session)
            now = time.monotonic()

            # See docs/architecture/rationale.md, "Lineage lock order".
            n = len(self._ttl_deque)
            while n > 0 and self._ttl_deque and self._ttl_deque[0][0] <= now:
                n -= 1
                _expiry, sid = self._ttl_deque.popleft()
                if sid not in self._sessions:
                    continue
                state_ev = self._sessions[sid]
                if state_ev.last_update + self._session_ttl > now:
                    continue
                # See docs/architecture/rationale.md, "Lineage lock order".
                if self._is_pinned is not None and self._is_pinned(sid):
                    self._ttl_deque.append((state_ev.last_update + self._session_ttl, sid))
                    continue
                if state_ev.terminated and sid not in self._terminated_ids:
                    self._terminated_ids[sid] = None
                    self._enforce_tombstone_cap()
                del self._sessions[sid]
                # Removed sessions drop their outgoing lineage edge, including terminated sessions.
                self._fire_on_terminate(sid)

            if len(self._ttl_deque) > 2 * self._max_sessions:
                self._compact_ttl_deque(now)

            if session_id not in self._sessions and session_id in self._terminated_ids:
                sentinel = self._config.escalation.tier3
                return FrequencyUpdateResult(
                    previous_score=sentinel,
                    current_score=sentinel,
                    tier="tier3",
                    terminated=True,
                )

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

            # See docs/architecture/rationale.md, "Lineage lock order".
            if is_new and len(self._sessions) > self._max_sessions:
                self._evict_one(session_id)
                if self._is_pinned is not None and len(self._sessions) > 2 * self._max_sessions:
                    self._force_evict_pinned(session_id)

            if state.terminated:
                return FrequencyUpdateResult(
                    previous_score=state.last_score,
                    current_score=state.last_score,
                    tier="tier3",
                    terminated=True,
                )

            total_weight = 0.0
            for rid in rule_ids:
                total_weight += self._match_weight(rid)
            if weight_cap is not None:
                # See docs/architecture/rationale.md, "Quantized scan contributions".
                total_weight = weight_cap if total_weight >= weight_cap else 0.0

            elapsed = max(0.0, now - state.last_update)
            if elapsed > 0 and state.last_score > 0:
                decayed = state.last_score * math.exp((-elapsed * math.log(2)) / self._half_life)
            else:
                decayed = state.last_score

            previous_score = decayed
            current_score = decayed + total_weight

            while (
                state.rolling_findings and (now - state.rolling_findings[0]) > self._rolling_window
            ):
                state.rolling_findings.popleft()
            # See docs/architecture/rationale.md, "Quantized scan contributions".
            if rule_ids and (weight_cap is None or total_weight > 0.0):
                state.rolling_findings.append(now)

            state.last_score = current_score
            state.last_update = now
            tier = self.tier_for_state(state)
            self._ttl_deque.append((now + self._session_ttl, session_id))
            if tier == "tier3":
                state.terminated = True
                self._add_tombstone(session_id)
                self._fire_on_terminate(session_id)

            return FrequencyUpdateResult(
                previous_score=previous_score,
                current_score=current_score,
                tier=tier,
                terminated=state.terminated,
            )

    def tier_for_state(self, state: SessionState | None) -> str:
        """The tier of a retained snapshot, including its rolling-count promotion.

        Scores and rolling windows advance together on update. Every consumer
        reads that same snapshot until the next update or reconfiguration.
        """
        with self._lock:
            if state is None:
                return "none"
            if state.terminated:
                return "tier3"
            tier = evaluate_tier(state.last_score, self._config)
            if tier == "none" and len(state.rolling_findings) >= self._rolling_threshold:
                return "tier1"
            return tier

    def get_state(self, session: str | SessionToken) -> SessionState | None:
        """Return live session state, or None when it is not retained."""
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
        """Return whether a session is live-terminated or tombstoned."""
        with self._lock:
            state = self._sessions.get(session_id)
            if state is not None:
                return state.terminated
            return session_id in self._terminated_ids

    def terminate_session(self, session: str | SessionToken) -> None:
        """Mark the session terminated and retain its tombstone."""
        with self._lock:
            session_id = self._resolve_session_id(session)
            state = self._sessions.get(session_id)
            if state is not None:
                state.terminated = True
            self._add_tombstone(session_id)
            self._fire_on_terminate(session_id)

    def reset(self, session: str | SessionToken) -> None:
        """Reset session state while preserving termination tombstones."""
        with self._lock:
            session_id = self._resolve_session_id(session)
            if self._sessions.pop(session_id, None) is not None:
                self._fire_on_terminate(session_id)

    def force_reset(self, session_id: str) -> None:
        """Remove session state and its termination tombstone."""
        with self._lock:
            removed = self._sessions.pop(session_id, None)
            self._terminated_ids.pop(session_id, None)
            if removed is not None:
                self._fire_on_terminate(session_id)

    def clear(self) -> None:
        """Clear session state and tombstones, releasing lineage pins."""
        with self._lock:
            removed_ids = tuple(self._sessions)
            self._sessions.clear()
            self._creation_timestamps.clear()
            self._terminated_ids.clear()
            self._ttl_deque.clear()
            for session_id in removed_ids:
                self._fire_on_terminate(session_id)

    @property
    def size(self) -> int:
        """Return the number of retained live sessions."""
        with self._lock:
            return len(self._sessions)

    @property
    def tombstone_count(self) -> int:
        """Return the number of retained termination tombstones."""
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
            resolved = w
        else:
            resolved = 0.0
            for prefix, weight in self._glob_weights:
                if finding_type.startswith(prefix + "."):
                    resolved = weight
                    break
        if finding_type == "petasos.selfmod.config_write":
            return max(resolved, 10.0)
        if finding_type == "petasos.selfmod.config_ref":
            return max(resolved, 3.0)
        return resolved

    def _fire_on_terminate(self, session_id: str) -> None:
        """Notify lineage of removal while containing callback failures.

        See docs/architecture/rationale.md, "Lineage lock order"."""
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
            # Live children require pinned session tiers until the hard memory ceiling binds.
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
            # Refreshing an existing tombstone would incorrectly extend its FIFO lifetime.
            if sid not in self._terminated_ids:
                self._terminated_ids[sid] = None
                self._enforce_tombstone_cap()
            del self._sessions[sid]
            self._fire_on_terminate(sid)
        elif oldest_candidate is not None:
            # See docs/architecture/rationale.md, "Lineage lock order".
            sid = oldest_candidate[0]
            del self._sessions[sid]
            self._fire_on_terminate(sid)

    def _force_evict_pinned(self, protect_id: str) -> None:
        """Enforce the hard session ceiling while preserving termination tombstones.

        See docs/architecture/rationale.md, "Lineage lock order"."""
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
        # Dropping an outgoing edge unpins the parent; child edges retain own-tier fallback.
        self._fire_on_terminate(sid)
