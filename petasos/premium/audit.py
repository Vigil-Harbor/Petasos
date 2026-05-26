from __future__ import annotations

import time
import uuid
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from petasos._types import AuditEvent

if TYPE_CHECKING:
    from collections.abc import Callable

    from petasos._types import PipelineResult
    from petasos.config import PetasosConfig
    from petasos.premium.frequency import FrequencyUpdateResult

_NONE_SENTINEL: object = object()


class AuditEmitter:
    def __init__(
        self,
        config: PetasosConfig,
        *,
        on_audit: Callable[[AuditEvent], None] | None = None,
    ) -> None:
        self._config = config
        self._on_audit = on_audit
        self._sequence_counters: dict[object, int] = {}
        self._last_emit_time: dict[object, float] = {}

    def emit(
        self,
        result: PipelineResult,
        session_id: str | None,
        freq_result: FrequencyUpdateResult | None,
    ) -> AuditEvent:
        now_mono = time.monotonic()
        self._prune_stale(now_mono)

        session_key: object = session_id if session_id is not None else _NONE_SENTINEL
        seq = self._sequence_counters.get(session_key, 0)

        payload = self._build_payload(result, freq_result)

        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            timestamp=time.time(),
            session_id=session_id,
            event_type="scan_complete",
            payload=payload,
            sequence_number=seq,
        )

        self._sequence_counters[session_key] = seq + 1
        self._last_emit_time[session_key] = now_mono

        if self._on_audit is not None:
            try:
                self._on_audit(event)
            except Exception as exc:
                raise RuntimeError(f"on_audit callback failed: {exc}") from exc

        return event

    def _build_payload(
        self,
        result: PipelineResult,
        freq_result: FrequencyUpdateResult | None,
    ) -> MappingProxyType[str, Any]:
        verbosity = self._config.audit_verbosity
        data: dict[str, Any] = {
            "safe": result.safe,
            "finding_count": len(result.findings),
        }

        if verbosity in ("standard", "verbose"):
            data["findings"] = [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity.value,
                    "confidence": f.confidence,
                }
                for f in result.findings
            ]
            data["escalation_tier"] = freq_result.tier if freq_result is not None else None
            data["session_score"] = freq_result.current_score if freq_result is not None else None

        if verbosity == "verbose":
            data["scanner_results"] = [
                {
                    "scanner_name": sr.scanner_name,
                    "finding_count": len(sr.findings),
                    "duration_ms": sr.duration_ms,
                    "error": sr.error,
                }
                for sr in result.scanner_results
            ]
            data["config_snapshot"] = self._config.to_dict()
            data["timing"] = {
                "timestamp": time.time(),
            }

        return MappingProxyType(data)

    def _prune_stale(self, now: float) -> None:
        ttl = self._config.session_ttl_seconds
        stale_keys = [k for k, t in self._last_emit_time.items() if (now - t) > ttl]
        for k in stale_keys:
            del self._last_emit_time[k]
            self._sequence_counters.pop(k, None)
