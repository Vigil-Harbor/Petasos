from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from types import MappingProxyType
from typing import TYPE_CHECKING

from petasos._types import Alert, Severity
from petasos.session.escalation import evaluate_tier

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from petasos._types import PipelineResult
    from petasos.config import PetasosConfig
    from petasos.session.frequency import FrequencyUpdateResult

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


class AlertManager:
    def __init__(
        self,
        config: PetasosConfig,
        *,
        on_alert: Callable[[Alert], None] | None = None,
    ) -> None:
        self._config = config
        self._on_alert = on_alert
        self._listeners: list[Callable[[Alert], None]] = []
        self._rule_cooldowns: dict[tuple[str, str | None], float] = {}
        self._per_minute_timestamps: dict[str, deque[float]] = {}
        self._per_hour_timestamps: dict[str, deque[float]] = {}
        self._critical_per_minute_timestamps: dict[str, deque[float]] = {}
        self._ring_buffers: dict[str, deque[tuple[float, str]]] = {}
        self._pii_ring_buffer: deque[tuple[float, int]] = deque(
            maxlen=config.alert_ring_buffer_capacity
        )
        self._per_session_minute_timestamps: dict[tuple[str, str | None], deque[float]] = {}
        self._alert_count: int = 0
        self._suppressed_count: int = 0
        self._rate_limited_count: int = 0
        self._session_rate_limited_count: int = 0
        self._cross_session_tracker: dict[str, float] = {}
        self._callback_errors: list[str] = []

    @property
    def callback_errors(self) -> tuple[str, ...]:
        return tuple(self._callback_errors)

    @property
    def alert_count(self) -> int:
        return self._alert_count

    @property
    def suppressed_count(self) -> int:
        return self._suppressed_count

    @property
    def rate_limited_count(self) -> int:
        return self._rate_limited_count

    @property
    def session_rate_limited_count(self) -> int:
        return self._session_rate_limited_count

    def add_listener(self, callback: Callable[[Alert], None]) -> None:
        """Register an additional alert listener (fires after on_alert)."""
        self._listeners.append(callback)

    def evaluate(
        self,
        result: PipelineResult,
        session_id: str | None,
        freq_result: FrequencyUpdateResult | None,
    ) -> list[Alert]:
        now = time.monotonic()
        self._prune_stale(now)
        self._callback_errors = []

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

            if is_critical:
                crit_deque = self._critical_per_minute_timestamps.setdefault(
                    candidate.rule_id, deque()
                )
                self._evict_old(crit_deque, now, 60.0)
                if len(crit_deque) >= self._config.alert_critical_per_minute_cap:
                    self._rate_limited_count += 1
                    continue
                crit_deque.append(now)
            else:
                dedup_key = (candidate.rule_id, session_id)

                last_fire = self._rule_cooldowns.get(dedup_key)
                cooldown = self._config.alert_cooldown_seconds
                if last_fire is not None and (now - last_fire) < cooldown:
                    self._suppressed_count += 1
                    continue

                session_minute_key = (candidate.rule_id, session_id)
                if (
                    session_minute_key not in self._per_session_minute_timestamps
                    and len(self._per_session_minute_timestamps)
                    >= self._config.alert_max_session_contribution_entries
                ):
                    self._session_rate_limited_count += 1
                    continue

                session_minute_deque = self._per_session_minute_timestamps.setdefault(
                    session_minute_key, deque()
                )
                self._evict_old(session_minute_deque, now, 60.0)
                if len(session_minute_deque) >= self._config.alert_per_session_contribution_cap:
                    self._session_rate_limited_count += 1
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
                session_minute_deque.append(now)

            self._alert_count += 1
            surviving.append(candidate)

            if self._on_alert is not None:
                try:
                    self._on_alert(candidate)
                except BaseException as exc:
                    _logger.exception(
                        "on_alert callback failed for rule_id=%s",
                        candidate.rule_id,
                    )
                    self._callback_errors.append(
                        f"on_alert callback ({candidate.rule_id}, {type(exc).__name__}): {exc}"
                        if str(exc)
                        else f"on_alert callback ({candidate.rule_id}, {type(exc).__name__})"
                    )

            for listener in list(self._listeners):
                try:
                    listener(candidate)
                except BaseException as exc:
                    _logger.exception(
                        "alert listener failed for rule_id=%s",
                        candidate.rule_id,
                    )
                    self._callback_errors.append(
                        f"alert listener ({candidate.rule_id}, {type(exc).__name__}): {exc}"
                        if str(exc)
                        else f"alert listener ({candidate.rule_id}, {type(exc).__name__})"
                    )

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

        self._cross_session_tracker[session_id] = now
        window = self._config.alert_cross_session_burst_window_seconds
        stale_sids = [
            sid for sid, ts in self._cross_session_tracker.items() if (now - ts) > window
        ]
        for sid in stale_sids:
            del self._cross_session_tracker[sid]
        tracker_cap = max(
            2 * self._config.alert_ring_buffer_capacity,
            self._config.alert_cross_session_burst_count,
        )
        if len(self._cross_session_tracker) > tracker_cap:
            sorted_entries = sorted(self._cross_session_tracker.items(), key=lambda x: x[1])
            for sid, _ in sorted_entries[: len(self._cross_session_tracker) - tracker_cap]:
                del self._cross_session_tracker[sid]

        distinct_count = len(self._cross_session_tracker)
        if distinct_count >= self._config.alert_cross_session_burst_count:
            return Alert(
                alert_id=uuid.uuid4().hex,
                timestamp=time.time(),
                rule_id="cross_session_burst",
                severity="high",
                session_id=session_id,
                message=(f"Cross-session burst: {distinct_count} distinct sessions in {window}s"),
                context=MappingProxyType(
                    {
                        "distinct_sessions": distinct_count,
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
        for mk, md in self._per_minute_timestamps.items():
            self._evict_old(md, now, 60.0)
            if not md:
                stale_minute_keys.append(mk)
        for mk in stale_minute_keys:
            del self._per_minute_timestamps[mk]

        stale_hour_keys: list[str] = []
        for hk, hd in self._per_hour_timestamps.items():
            self._evict_old(hd, now, 3600.0)
            if not hd:
                stale_hour_keys.append(hk)
        for hk in stale_hour_keys:
            del self._per_hour_timestamps[hk]

        stale_session_keys: list[tuple[str, str | None]] = []
        for sk, sd in self._per_session_minute_timestamps.items():
            self._evict_old(sd, now, 60.0)
            if not sd:
                stale_session_keys.append(sk)
        for sk in stale_session_keys:
            del self._per_session_minute_timestamps[sk]

        stale_crit_keys: list[str] = []
        for ck, cd in self._critical_per_minute_timestamps.items():
            self._evict_old(cd, now, 60.0)
            if not cd:
                stale_crit_keys.append(ck)
        for ck in stale_crit_keys:
            del self._critical_per_minute_timestamps[ck]

        ring_ttl = max(
            self._config.alert_rapid_fire_window_seconds,
            self._config.alert_cross_session_burst_window_seconds,
            self._config.alert_pii_volume_window_seconds,
        )
        stale_ring_keys: list[str] = []
        for rk, buf in self._ring_buffers.items():
            if not buf or (now - buf[-1][0]) > ring_ttl:
                stale_ring_keys.append(rk)
        for rk in stale_ring_keys:
            del self._ring_buffers[rk]

        burst_window = self._config.alert_cross_session_burst_window_seconds
        stale_tracker_keys = [
            sid for sid, ts in self._cross_session_tracker.items() if (now - ts) > burst_window
        ]
        for sid in stale_tracker_keys:
            del self._cross_session_tracker[sid]
