from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import math
import sys
import threading
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

from petasos._types import (
    AVAILABILITY_CAUSE_ABSENT,
    AVAILABILITY_CAUSE_LOAD_FAILED,
    AvailabilityCause,
    Direction,
    Position,
    ScanFinding,
    ScanResult,
    Severity,
)

_REQUIRED_PACKAGES: tuple[str, ...] = ("presidio_analyzer", "presidio_anonymizer")

_INSTALL_HINT = "presidio not installed. pip install petasos[presidio]"

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

# PET-109: the security-relevant default detection set (the CRITICAL/HIGH band
# of _SEVERITY_MAP). spaCy-NER (PERSON/LOCATION) and loose pattern (URL/DATE_TIME/
# NRP) recognizers are noisy on technical text and are opt-in, not default.
DEFAULT_PRESIDIO_ENTITIES: tuple[str, ...] = (
    "CREDIT_CARD",
    "IBAN_CODE",
    "US_SSN",
    "US_BANK_NUMBER",
    "CRYPTO",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_DRIVER_LICENSE",
    "US_PASSPORT",
    "IP_ADDRESS",
)
NOISY_OPT_IN_ENTITIES: tuple[str, ...] = ("PERSON", "LOCATION", "DATE_TIME", "NRP", "URL")


def resolve_presidio_entities(
    base: tuple[str, ...] | None, extra: tuple[str, ...] = ()
) -> list[str]:
    """Resolve the effective detection entity list for a build path.

    None base -> DEFAULT_PRESIDIO_ENTITIES; an explicit base is used verbatim.
    ``extra`` is appended (additive opt-ins like ("URL",)). Order-preserving dedup.
    Always returns a non-empty concrete list (never the analyzer's all-recognizers
    sentinel), so a build path cannot accidentally re-enable everything.
    """
    chosen = DEFAULT_PRESIDIO_ENTITIES if base is None else base
    return list(dict.fromkeys((*chosen, *extra)))


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
        # PET-109 D3: entities=None now means the curated default detection set
        # (not "all recognizers"). Defensive copy keeps the frozen module tuple
        # immutable shared state; _scan_sync therefore always passes a concrete
        # entity list to analyzer.analyze(), never the all-recognizers sentinel.
        self._entities = list(DEFAULT_PRESIDIO_ENTITIES) if entities is None else list(entities)
        self._language = language
        self._score_threshold = score_threshold
        self._analyzer: Any = None
        self._anonymizer: Any = None
        self._loaded = False
        self._load_error: BaseException | None = None
        self._load_error_retryable: bool = False
        self._load_lock = threading.Lock()

    @property
    def name(self) -> str:
        return "presidio"

    def availability(self) -> tuple[bool, str | None, AvailabilityCause | None]:
        """Cheap backend-presence probe. Never imports the backend.

        Returns ``(ok, reason, cause)`` (PET-103). presidio's ``_load_error`` is
        a ``BaseException`` that may itself be a missing-package ``ImportError``
        surfaced at load; the owning scanner classifies that sub-case as
        ``absent`` by comparing the formatted message against its own
        ``_INSTALL_HINT`` constant (this is the scanner classifying its own
        state, not the pipeline reaching into privates). Every other terminal
        ``_load_error`` is a genuine load crash → ``load_failed``. ``find_spec``
        misses are ``absent``.
        """
        if self._load_error is not None and not self._load_error_retryable:
            msg = self._load_error_message(self._load_error)
            cause: AvailabilityCause = (
                AVAILABILITY_CAUSE_ABSENT
                if msg == _INSTALL_HINT
                else AVAILABILITY_CAUSE_LOAD_FAILED
            )
            return (False, msg, cause)
        for pkg in _REQUIRED_PACKAGES:
            if pkg in sys.modules and sys.modules[pkg] is not None:
                continue
            try:
                spec = importlib.util.find_spec(pkg)
            except Exception:
                return (False, _INSTALL_HINT, AVAILABILITY_CAUSE_ABSENT)
            if spec is None or spec.origin is None:
                return (False, _INSTALL_HINT, AVAILABILITY_CAUSE_ABSENT)
        return (True, None, None)

    @staticmethod
    def _load_error_message(exc: BaseException) -> str:
        if isinstance(exc, ImportError):
            from petasos.scanners import _is_missing_package

            if _is_missing_package(exc, set(_REQUIRED_PACKAGES)):
                return _INSTALL_HINT
            return str(exc)
        msg = str(exc)
        if "spacy" in msg.lower() or "model" in msg.lower():
            return "spaCy model not found. Run: python -m spacy download en_core_web_lg"
        return msg

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._load_error is not None:
            if not self._load_error_retryable:
                raise self._load_error
            with self._load_lock:
                if self._loaded:
                    return
                if self._load_error is not None and not self._load_error_retryable:
                    raise self._load_error
                if self._load_error is not None and self._load_error_retryable:
                    avail, _reason, _cause = self.availability()
                    if not avail:
                        raise self._load_error
                    self._load_error = None
                    self._load_error_retryable = False
                    self._loaded = False
                self._do_load()
            return
        with self._load_lock:
            if self._loaded:
                return
            if self._load_error is not None:
                raise self._load_error
            self._do_load()

    def _do_load(self) -> None:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine

            self._analyzer = AnalyzerEngine()
            self._anonymizer = AnonymizerEngine()  # type: ignore[no-untyped-call]
            self._anonymizer.add_anonymizer(_make_hmac_operator_class())
            self._loaded = True
        except Exception as exc:
            from petasos.scanners import _is_missing_package

            if isinstance(exc, ImportError) and _is_missing_package(exc, set(_REQUIRED_PACKAGES)):
                self._load_error = exc
                self._load_error_retryable = True
            else:
                avail, _, _ = self.availability()
                if avail:
                    self._load_error = exc
                    self._load_error_retryable = False
                else:
                    self._load_error = exc
                    self._load_error_retryable = True
            raise

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        """Scan ``text`` for PII and return a ScanResult (never raises).

        Cancellation residual (SCAN-03): analysis runs in a worker thread via
        ``asyncio.to_thread``. Cancelling the awaiting task frees the event loop
        promptly, but the worker thread runs to completion on the default
        executor — cancellation does not interrupt in-flight analysis. A
        cancellable-executor path is future work.
        """
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
    """Anonymize PII spans in ``text`` using positioned findings.

    Contract (PET-60 / SCAN-06): ``findings`` must already be overlap-resolved by
    the pipeline's ``merge_findings()`` before being passed here — this function
    does not re-run the pipeline's overlap resolution. The engine path
    (``redact``/``hash``) defers to Presidio's own span handling; the manual path
    (``replace``/``mask``) applies a severity-first tiebreaker via
    ``_resolve_overlaps`` for any residual overlaps (higher severity wins; on a
    severity tie, higher confidence wins). Callers invoking ``anonymize()``
    directly should call ``merge_findings()`` first.

    ``mode='hash'`` requires a non-empty ``hash_key`` — unkeyed hashing is
    reversible on low-entropy PII — and raises ``ValueError`` otherwise.
    """
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
