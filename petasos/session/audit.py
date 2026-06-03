from __future__ import annotations

import logging
import time
import uuid
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from petasos._types import AuditEvent

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from petasos._types import PipelineResult
    from petasos.config import PetasosConfig
    from petasos.session.frequency import FrequencyUpdateResult


class AuditEmitter:
    def __init__(
        self,
        config: PetasosConfig,
        *,
        on_audit: Callable[[AuditEvent], None] | None = None,
    ) -> None:
        self._config = config
        self._on_audit = on_audit
        self._global_sequence: int = 0
        self._last_callback_error: str | None = None
        self._listeners: list[Callable[[AuditEvent], None]] = []

    @property
    def last_callback_error(self) -> str | None:
        return self._last_callback_error

    def emit(
        self,
        result: PipelineResult,
        session_id: str | None,
        freq_result: FrequencyUpdateResult | None,
    ) -> AuditEvent:
        self._last_callback_error = None
        seq = self._global_sequence

        payload = self._build_payload(result, freq_result)

        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            timestamp=time.time(),
            session_id=session_id,
            event_type="scan_complete",
            payload=payload,
            sequence_number=seq,
        )

        self._global_sequence = seq + 1

        if self._on_audit is not None:
            try:
                self._on_audit(event)
            except BaseException as exc:
                _logger.error("on_audit callback failed: %s", exc, exc_info=True)
                self._last_callback_error = (
                    f"on_audit callback ({type(exc).__name__}): {exc}"
                    if str(exc)
                    else f"on_audit callback ({type(exc).__name__})"
                )

        for listener in list(self._listeners):
            try:
                listener(event)
            except BaseException as exc:
                _logger.error("audit listener failed: %s", exc, exc_info=True)
                self._last_callback_error = (
                    f"audit listener ({type(exc).__name__}): {exc}"
                    if str(exc)
                    else f"audit listener ({type(exc).__name__})"
                )

        return event

    def add_listener(self, callback: Callable[[AuditEvent], None]) -> None:
        """Register an additional audit event listener (fires after on_audit)."""
        self._listeners.append(callback)

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
            data["config_snapshot"] = self._config.to_dict(redact_secrets=True)
            data["timing"] = {
                "timestamp": time.time(),
            }

        return MappingProxyType(data)
