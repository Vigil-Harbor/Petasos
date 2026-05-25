from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from petasos.premium.escalation import evaluate_tier

if TYPE_CHECKING:
    from collections.abc import Sequence

    from petasos.config import PetasosConfig

DEFAULT_FREQUENCY_WEIGHTS: dict[str, float] = {
    "petasos.syntactic.injection.*": 10.0,
    "petasos.syntactic.structural.*": 5.0,
    "petasos.syntactic.encoding.*": 3.0,
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


DISABLED_RESULT = FrequencyUpdateResult(
    previous_score=0.0, current_score=0.0, tier="none", terminated=False
)
RATE_LIMITED_RESULT = FrequencyUpdateResult(
    previous_score=0.0, current_score=0.0, tier="none", terminated=False
)


class FrequencyTracker:
    def __init__(self, config: PetasosConfig) -> None:
        self._half_life = config.frequency_half_life_seconds
        self._rolling_window = config.rolling_window_seconds
        self._rolling_threshold = config.rolling_threshold
        self._max_sessions = config.max_sessions
        self._session_ttl = config.session_ttl_seconds
        self._max_new_per_minute = config.max_new_sessions_per_minute
        self._config = config

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

    def update(self, session_id: str, rule_ids: Sequence[str]) -> FrequencyUpdateResult:
        now = time.monotonic()

        # Step 1: Passive TTL eviction
        stale = [
            sid for sid, state in self._sessions.items()
            if now - state.last_update > self._session_ttl
        ]
        for sid in stale:
            del self._sessions[sid]

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

        # Step 3: Enforce max-sessions cap
        if is_new and len(self._sessions) > self._max_sessions:
            self._evict_one(session_id)

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
            decayed = state.last_score * math.exp(
                (-elapsed * math.log(2)) / self._half_life
            )
        else:
            decayed = state.last_score

        # Step 7: Update score
        previous_score = decayed
        current_score = decayed + total_weight

        # Step 8: Update rolling window
        while state.rolling_findings and (now - state.rolling_findings[0]) > self._rolling_window:
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
        if tier == "tier3":
            state.terminated = True

        # Step 11: Return
        return FrequencyUpdateResult(
            previous_score=previous_score,
            current_score=current_score,
            tier=tier,
            terminated=state.terminated,
        )

    def get_state(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def clear(self) -> None:
        self._sessions.clear()
        self._creation_timestamps.clear()

    @property
    def size(self) -> int:
        return len(self._sessions)

    def _match_weight(self, finding_type: str) -> float:
        w = self._exact_weights.get(finding_type)
        if w is not None:
            return w
        for prefix, weight in self._glob_weights:
            if finding_type.startswith(prefix + "."):
                return weight
        return 0.0

    def _evict_one(self, protect_id: str) -> None:
        terminated_candidate: tuple[str, float] | None = None
        oldest_candidate: tuple[str, float] | None = None

        for sid, state in self._sessions.items():
            if sid == protect_id:
                continue
            if state.terminated and (
                terminated_candidate is None or state.last_update < terminated_candidate[1]
            ):
                terminated_candidate = (sid, state.last_update)
            if oldest_candidate is None or state.last_update < oldest_candidate[1]:
                oldest_candidate = (sid, state.last_update)

        if terminated_candidate is not None:
            del self._sessions[terminated_candidate[0]]
        elif oldest_candidate is not None:
            del self._sessions[oldest_candidate[0]]
