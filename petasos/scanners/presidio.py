from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import threading
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

from petasos._types import (
    Direction,
    Position,
    ScanFinding,
    ScanResult,
    Severity,
)

_SEVERITY_MAP: dict[str, Severity] = {
    "CREDIT_CARD": Severity.CRITICAL,
    "IBAN_CODE": Severity.CRITICAL,
    "US_SSN": Severity.CRITICAL,
    "US_BANK_NUMBER": Severity.CRITICAL,
    "CRYPTO": Severity.CRITICAL,
    "EMAIL_ADDRESS": Severity.HIGH,
    "PHONE_NUMBER": Severity.HIGH,
    "US_DRIVER_LICENSE": Severity.HIGH,
    "US_PASSPORT": Severity.HIGH,
    "IP_ADDRESS": Severity.HIGH,
    "PERSON": Severity.MEDIUM,
    "LOCATION": Severity.MEDIUM,
    "DATE_TIME": Severity.MEDIUM,
    "NRP": Severity.MEDIUM,
}

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}

_module_anonymizer: Any = None
_module_anonymizer_lock = threading.Lock()


def _get_module_anonymizer() -> Any:
    global _module_anonymizer
    if _module_anonymizer is not None:
        return _module_anonymizer
    with _module_anonymizer_lock:
        if _module_anonymizer is not None:
            return _module_anonymizer
        from presidio_anonymizer import AnonymizerEngine

        engine = AnonymizerEngine()  # type: ignore[no-untyped-call]
        engine.add_anonymizer(_make_hmac_operator_class())
        _module_anonymizer = engine
        return _module_anonymizer


def _make_hmac_operator_class() -> type:
    from presidio_anonymizer.operators import Operator, OperatorType

    class _HmacSha256Operator(Operator):
        def operator_name(self) -> str:
            return "hmac_sha256"

        def operator_type(self) -> OperatorType:
            return OperatorType.Anonymize

        def validate(self, params: dict[str, Any] | None = None) -> None:
            if not params or not isinstance(params.get("hmac_key"), str):
                raise ValueError("hmac_key (str) is required")
            if not params["hmac_key"]:
                raise ValueError("hmac_key must be non-empty")

        def operate(self, text: str, params: dict[str, Any] | None = None) -> str:
            if not params or "hmac_key" not in params:
                raise ValueError("hmac_key is required")
            key = params["hmac_key"].encode("utf-8")
            return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()

    return _HmacSha256Operator


class PresidioScanner:
    def __init__(
        self,
        *,
        entities: list[str] | None = None,
        language: str = "en",
        score_threshold: float = 0.35,
    ) -> None:
        self._entities = entities
        self._language = language
        self._score_threshold = score_threshold
        self._analyzer: Any = None
        self._anonymizer: Any = None
        self._loaded = False
        self._load_error: BaseException | None = None
        self._load_lock = threading.Lock()

    @property
    def name(self) -> str:
        return "presidio"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._load_error is not None:
            raise self._load_error
        with self._load_lock:
            if self._loaded:
                return
            if self._load_error is not None:
                raise self._load_error
            try:
                from presidio_analyzer import AnalyzerEngine
                from presidio_anonymizer import AnonymizerEngine

                self._analyzer = AnalyzerEngine()
                self._anonymizer = AnonymizerEngine()  # type: ignore[no-untyped-call]
                self._anonymizer.add_anonymizer(_make_hmac_operator_class())
                self._loaded = True
            except Exception as exc:
                self._load_error = exc
                raise

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        start_time = time.perf_counter()
        try:
            self._ensure_loaded()
            findings = await asyncio.to_thread(self._scan_sync, text)
            elapsed = (time.perf_counter() - start_time) * 1000
            return ScanResult(
                scanner_name=self.name,
                findings=tuple(findings),
                duration_ms=elapsed,
            )
        except ImportError:
            elapsed = (time.perf_counter() - start_time) * 1000
            return ScanResult(
                scanner_name=self.name,
                findings=(),
                duration_ms=elapsed,
                error="presidio not installed. pip install petasos[presidio]",
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start_time) * 1000
            msg = str(exc)
            if "spacy" in msg.lower() or "model" in msg.lower():
                msg = "spaCy model not found. Run: python -m spacy download en_core_web_lg"
            return ScanResult(
                scanner_name=self.name,
                findings=(),
                duration_ms=elapsed,
                error=msg,
            )

    def _scan_sync(self, text: str) -> list[ScanFinding]:
        results = self._analyzer.analyze(
            text=text,
            entities=self._entities,
            language=self._language,
            score_threshold=self._score_threshold,
        )
        findings: list[ScanFinding] = []
        for r in results:
            entity_type: str = r.entity_type
            severity = _SEVERITY_MAP.get(entity_type, Severity.LOW)
            _clamped = 0.0 if not math.isfinite(r.score) else max(0.0, min(1.0, r.score))
            findings.append(
                ScanFinding(
                    rule_id=f"petasos.presidio.{entity_type.lower()}",
                    finding_type="pii",
                    severity=severity,
                    confidence=_clamped,
                    message=f"PII detected: {entity_type}",
                    scanner_name=self.name,
                    position=Position(start=r.start, end=r.end),
                    matched_text=text[r.start : r.end],
                )
            )
        return findings


def _recover_entity_type(rule_id: str) -> str:
    prefix = "petasos.presidio."
    raw = rule_id[len(prefix) :] if rule_id.startswith(prefix) else rule_id.rsplit(".", 1)[-1]
    return raw.upper().replace("-", "_")


def _resolve_overlaps(
    findings: list[tuple[ScanFinding, str]],
) -> list[tuple[ScanFinding, str]]:
    if len(findings) <= 1:
        return findings
    sorted_findings = sorted(findings, key=lambda x: x[0].position.start)  # type: ignore[union-attr]
    result: list[tuple[ScanFinding, str]] = [sorted_findings[0]]
    for current_finding, current_entity in sorted_findings[1:]:
        prev_finding, prev_entity = result[-1]
        assert prev_finding.position is not None
        assert current_finding.position is not None
        if current_finding.position.start < prev_finding.position.end:
            cur_sev = _SEVERITY_RANK.get(current_finding.severity, 999)
            prev_sev = _SEVERITY_RANK.get(prev_finding.severity, 999)
            if cur_sev < prev_sev or (
                cur_sev == prev_sev and current_finding.confidence > prev_finding.confidence
            ):
                result[-1] = (current_finding, current_entity)
        else:
            result.append((current_finding, current_entity))
    return result


def anonymize(
    text: str,
    findings: Sequence[ScanFinding],
    *,
    mode: Literal["redact", "replace", "hash", "mask"] = "redact",
    hash_key: str | None = None,
) -> str:
    if mode == "hash" and not hash_key:
        raise ValueError(
            "hash_key is required and must be non-empty for mode='hash'. "
            "Unkeyed hashing is reversible on low-entropy PII."
        )

    positioned = [(f, _recover_entity_type(f.rule_id)) for f in findings if f.position is not None]
    if not positioned:
        return text

    if mode == "redact" or mode == "hash":
        return _anonymize_engine_path(text, positioned, mode=mode, hash_key=hash_key)
    else:
        return _anonymize_manual_path(text, positioned, mode=mode)


def _anonymize_engine_path(
    text: str,
    positioned: list[tuple[ScanFinding, str]],
    *,
    mode: Literal["redact", "hash"],
    hash_key: str | None,
) -> str:
    from presidio_analyzer import RecognizerResult
    from presidio_anonymizer.entities import OperatorConfig

    engine = _get_module_anonymizer()

    recognizer_results = []
    entity_types_seen: set[str] = set()
    for finding, entity_type in positioned:
        assert finding.position is not None
        recognizer_results.append(
            RecognizerResult(
                entity_type=entity_type,
                start=finding.position.start,
                end=finding.position.end,
                score=finding.confidence,
            )
        )
        entity_types_seen.add(entity_type)

    operators: dict[str, OperatorConfig] = {}
    if mode == "redact":
        for et in entity_types_seen:
            operators[et] = OperatorConfig("replace", {"new_value": f"<{et}>"})
    elif mode == "hash":
        if not hash_key:
            raise ValueError("hash_key must be non-empty (enforced by anonymize())")
        for et in entity_types_seen:
            operators[et] = OperatorConfig("hmac_sha256", {"hmac_key": hash_key})

    result = engine.anonymize(
        text=text,
        analyzer_results=recognizer_results,
        operators=operators,
    )
    return str(result.text)


def _anonymize_manual_path(
    text: str,
    positioned: list[tuple[ScanFinding, str]],
    *,
    mode: Literal["replace", "mask"],
) -> str:
    resolved = _resolve_overlaps(positioned)

    if mode == "replace":
        counter: dict[str, int] = defaultdict(int)
        sorted_forward = sorted(
            resolved,
            key=lambda x: x[0].position.start,  # type: ignore[union-attr]
        )
        labels: list[tuple[ScanFinding, str, str]] = []
        for finding, entity_type in sorted_forward:
            counter[entity_type] += 1
            label = f"<{entity_type}_{counter[entity_type]}>"
            labels.append((finding, entity_type, label))
        labels.sort(
            key=lambda x: x[0].position.start,  # type: ignore[union-attr]
            reverse=True,
        )
        for finding, _et, label in labels:
            assert finding.position is not None
            text = text[: finding.position.start] + label + text[finding.position.end :]
        return text

    # mask mode
    sorted_reverse = sorted(
        resolved,
        key=lambda x: x[0].position.start,  # type: ignore[union-attr]
        reverse=True,
    )
    for finding, _entity_type in sorted_reverse:
        assert finding.position is not None
        start = finding.position.start
        end = finding.position.end
        resolved_text = finding.matched_text or text[start:end]
        length = len(resolved_text)
        visible = 4
        chars_to_mask = length if length <= visible else length - visible
        masked = "*" * chars_to_mask + resolved_text[chars_to_mask:]
        text = text[:start] + masked + text[end:]
    return text
