from __future__ import annotations

import time
import uuid
from collections import deque
from types import MappingProxyType
from typing import TYPE_CHECKING

from petasos._types import Alert, Severity
from petasos.premium.escalation import evaluate_tier

if TYPE_CHECKING:
    from collections.abc import Callable

    from petasos._types import PipelineResult
    from petasos.config import PetasosConfig
    from petasos.premium.frequency import FrequencyUpdateResult

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}

_NONE_KEY = "__none__"


class AlertManager:
    def __init__(
        self,
        config: PetasosConfig,
        *,
        on_alert: Callable[[Alert], None] | None = None,
    ) -> None:
        self._config = config
        self._on_alert = on_alert
        self._rule_cooldowns: dict[str, float] = {}
        self._per_minute_timestamps: dict[str, deque[float]] = {}
        self._per_hour_timestamps: dict[str, deque[float]] = {}
        self._ring_buffers: dict[str, deque[tuple[float, str]]] = {}
        self._pii_ring_buffer: deque[tuple[float, int]] = deque(
            maxlen=config.alert_ring_buffer_capacity
        )
        self._alert_count: int = 0
        self._suppressed_count: int = 0
        self._rate_limited_count: int = 0

    @property
    def alert_count(self) -> int:
        return self._alert_count

    @property
    def suppressed_count(self) -> int:
        return self._suppressed_count

    @property
    def rate_limited_count(self) -> int:
        return self._rate_limited_count

    def evaluate(
        self,
        result: PipelineResult,
        session_id: str | None,
        freq_result: FrequencyUpdateResult | None,
    ) -> list[Alert]:
        now = time.monotonic()
        self._prune_stale(now)

        candidates: list[Alert] = []

        alert = self._check_tier_escalation(freq_result, session_id)
        if alert is not None:
            candidates.append(alert)

        alert = self._check_high_severity_finding(result, session_id)
        if alert is not None:
            candidates.append(alert)

        alert = self._check_rapid_fire(session_id, now)
        if alert is not None:
            candidates.append(alert)

        alert = self._check_cross_session_burst(result, session_id, now)
        if alert is not None:
            candidates.append(alert)

        alert = self._check_pii_volume_spike(result, session_id, now)
        if alert is not None:
            candidates.append(alert)

        surviving: list[Alert] = []
        for candidate in candidates:
            is_critical = candidate.severity == "critical"

            if not is_critical:
                session_key = session_id if session_id is not None else _NONE_KEY
                dedup_key = f"{candidate.rule_id}|{session_key}"

                last_fire = self._rule_cooldowns.get(dedup_key)
                cooldown = self._config.alert_cooldown_seconds
                if last_fire is not None and (now - last_fire) < cooldown:
                    self._suppressed_count += 1
                    continue

                minute_deque = self._per_minute_timestamps.setdefault(candidate.rule_id, deque())
                self._evict_old(minute_deque, now, 60.0)
                if len(minute_deque) >= self._config.alert_per_minute_cap:
                    self._rate_limited_count += 1
                    continue

                hour_deque = self._per_hour_timestamps.setdefault(candidate.rule_id, deque())
                self._evict_old(hour_deque, now, 3600.0)
                if len(hour_deque) >= self._config.alert_per_hour_cap:
                    self._rate_limited_count += 1
                    continue

                self._rule_cooldowns[dedup_key] = now
                minute_deque.append(now)
                hour_deque.append(now)

            self._alert_count += 1
            surviving.append(candidate)

            if self._on_alert is not None:
                try:
                    self._on_alert(candidate)
                except Exception as exc:
                    raise RuntimeError(f"on_alert callback failed: {exc}") from exc

        return surviving

    def _check_tier_escalation(
        self,
        freq_result: FrequencyUpdateResult | None,
        session_id: str | None,
    ) -> Alert | None:
        if freq_result is None:
            return None
        if session_id is None:
            return None

        previous_tier = evaluate_tier(freq_result.previous_score, self._config)
        current_tier = freq_result.tier

        if current_tier == previous_tier:
            return None

        severity_map: dict[str, str] = {
            "tier1": "warning",
            "tier2": "high",
            "tier3": "critical",
        }
        severity = severity_map.get(current_tier)
        if severity is None:
            return None

        return Alert(
            alert_id=uuid.uuid4().hex,
            timestamp=time.time(),
            rule_id="tier_escalation",
            severity=severity,
            session_id=session_id,
            message=f"Tier escalation: {previous_tier} -> {current_tier}",
            context=MappingProxyType(
                {
                    "previous_tier": previous_tier,
                    "current_tier": current_tier,
                    "previous_score": freq_result.previous_score,
                    "current_score": freq_result.current_score,
                }
            ),
        )

    def _check_high_severity_finding(
        self,
        result: PipelineResult,
        session_id: str | None,
    ) -> Alert | None:
        threshold = Severity(self._config.alert_high_severity_threshold)
        threshold_rank = _SEVERITY_RANK[threshold]

        for finding in result.findings:
            finding_rank = _SEVERITY_RANK.get(finding.severity, 999)
            if finding_rank <= threshold_rank:
                return Alert(
                    alert_id=uuid.uuid4().hex,
                    timestamp=time.time(),
                    rule_id="high_severity_finding",
                    severity="high",
                    session_id=session_id,
                    message=(
                        f"Finding with severity {finding.severity.value}"
                        f" at or above threshold {threshold.value}"
                    ),
                    context=MappingProxyType(
                        {
                            "rule_id": finding.rule_id,
                            "severity": finding.severity.value,
                            "threshold": threshold.value,
                            "confidence": finding.confidence,
                        }
                    ),
                )
        return None

    def _check_rapid_fire(
        self,
        session_id: str | None,
        now: float,
    ) -> Alert | None:
        if session_id is None:
            return None

        buf_key = f"rapid_fire|{session_id}"
        buf = self._ring_buffers.setdefault(
            buf_key, deque(maxlen=self._config.alert_ring_buffer_capacity)
        )
        buf.append((now, session_id))

        window = self._config.alert_rapid_fire_window_seconds
        count = sum(1 for ts, _ in buf if (now - ts) <= window)

        if count >= self._config.alert_rapid_fire_count:
            return Alert(
                alert_id=uuid.uuid4().hex,
                timestamp=time.time(),
                rule_id="rapid_fire",
                severity="warning",
                session_id=session_id,
                message=f"Rapid fire: {count} scans from session in {window}s window",
                context=MappingProxyType(
                    {
                        "session_id": session_id,
                        "count": count,
                        "window_seconds": window,
                        "threshold": self._config.alert_rapid_fire_count,
                    }
                ),
            )
        return None

    def _check_cross_session_burst(
        self,
        result: PipelineResult,
        session_id: str | None,
        now: float,
    ) -> Alert | None:
        if session_id is None:
            return None

        if not result.findings:
            return None

        buf_key = "cross_session_burst"
        buf = self._ring_buffers.setdefault(
            buf_key, deque(maxlen=self._config.alert_ring_buffer_capacity)
        )
        buf.append((now, session_id))

        window = self._config.alert_cross_session_burst_window_seconds
        recent_sessions = {sid for ts, sid in buf if (now - ts) <= window}

        if len(recent_sessions) >= self._config.alert_cross_session_burst_count:
            return Alert(
                alert_id=uuid.uuid4().hex,
                timestamp=time.time(),
                rule_id="cross_session_burst",
                severity="high",
                session_id=session_id,
                message=(
                    f"Cross-session burst: {len(recent_sessions)} distinct sessions in {window}s"
                ),
                context=MappingProxyType(
                    {
                        "distinct_sessions": len(recent_sessions),
                        "window_seconds": window,
                        "threshold": self._config.alert_cross_session_burst_count,
                    }
                ),
            )
        return None

    def _check_pii_volume_spike(
        self,
        result: PipelineResult,
        session_id: str | None,
        now: float,
    ) -> Alert | None:
        entity_count = sum(1 for f in result.findings if f.finding_type == "pii")

        if entity_count > 0:
            self._pii_ring_buffer.append((now, entity_count))

        window = self._config.alert_pii_volume_window_seconds
        total = sum(count for ts, count in self._pii_ring_buffer if (now - ts) <= window)

        if total >= self._config.alert_pii_volume_threshold:
            return Alert(
                alert_id=uuid.uuid4().hex,
                timestamp=time.time(),
                rule_id="pii_volume_spike",
                severity="warning",
                session_id=session_id,
                message=f"PII volume spike: {total} entities in {window}s window",
                context=MappingProxyType(
                    {
                        "entity_count": total,
                        "window_seconds": window,
                        "threshold": self._config.alert_pii_volume_threshold,
                    }
                ),
            )
        return None

    @staticmethod
    def _evict_old(d: deque[float], now: float, window: float) -> None:
        while d and (now - d[0]) > window:
            d.popleft()

    def _prune_stale(self, now: float) -> None:
        cooldown_ttl = 2 * self._config.alert_cooldown_seconds
        stale_cooldown_keys = [
            k for k, t in self._rule_cooldowns.items() if (now - t) > cooldown_ttl
        ]
        for k in stale_cooldown_keys:
            del self._rule_cooldowns[k]

        stale_minute_keys: list[str] = []
        for k, d in self._per_minute_timestamps.items():
            self._evict_old(d, now, 60.0)
            if not d:
                stale_minute_keys.append(k)
        for k in stale_minute_keys:
            del self._per_minute_timestamps[k]

        stale_hour_keys: list[str] = []
        for k, d in self._per_hour_timestamps.items():
            self._evict_old(d, now, 3600.0)
            if not d:
                stale_hour_keys.append(k)
        for k in stale_hour_keys:
            del self._per_hour_timestamps[k]
