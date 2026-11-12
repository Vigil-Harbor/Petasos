"""Detect and anonymize personal information through optional Presidio backends."""

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

from petasos.model import (
    AVAILABILITY_CAUSE_ABSENT,
    AVAILABILITY_CAUSE_LOAD_FAILED,
    AvailabilityCause,
    Direction,
    Position,
    ScanFinding,
    ScanResult,
    Severity,
    severity_rank,
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

# Technical-text recognizers are noisy and opt-in; defaults use the HIGH/CRITICAL band.
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

# See docs/architecture/rationale.md, "Presidio entity vocabulary".
KNOWN_PII_ENTITIES: frozenset[str] = (
    frozenset(_SEVERITY_MAP)
    | frozenset(DEFAULT_PRESIDIO_ENTITIES)
    | frozenset(NOISY_OPT_IN_ENTITIES)
)


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
    resolved = list(dict.fromkeys((*chosen, *extra)))
    if not resolved:
        # Enforce the documented non-empty contract: a degenerate base=() with no
        # extra would otherwise silently disable detection (the config layer already
        # rejects an empty explicit presidio_entities; this guards direct callers).
        raise ValueError("effective Presidio entity set must be non-empty")
    return resolved


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
    """Detect configured personal-information entities without mutating per-scan scope."""

    def __init__(
        self,
        *,
        entities: list[str] | None = None,
        language: str = "en",
        score_threshold: float = 0.35,
    ) -> None:
        # A concrete entity list prevents Presidio from enabling all recognizers.
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
        """Return the stable scanner id."""
        return "presidio"

    def availability(self) -> tuple[bool, str | None, AvailabilityCause | None]:
        """Report backend presence or terminal load failure without importing the backend.

        Returns ``(ok, reason, cause)``; a missing-package load error is absent,
        while other terminal load errors are load_failed."""
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
        extra_entities: Sequence[str] | None = None,
    ) -> ScanResult:
        """Return personal-information findings or an error result without raising.

        Per-call entity additions preserve the scanner base and concurrent scope.
        Loading and analysis run off the event loop; cancelled loads do not analyze
        abandoned text. In-flight analysis threads still run to completion."""
        start_time = time.perf_counter()
        try:
            await asyncio.to_thread(self._ensure_loaded)
            effective = self._effective_entities(extra_entities)
            findings = await asyncio.to_thread(self._scan_sync, text, effective)
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

    def _effective_entities(self, extra_entities: Sequence[str] | None) -> list[str]:
        """Return the base entities plus per-call additions without mutating the base."""
        if not extra_entities:
            return self._entities
        return resolve_presidio_entities(tuple(self._entities), tuple(extra_entities))

    def _scan_sync(self, text: str, entities: list[str] | None = None) -> list[ScanFinding]:
        results = self._analyzer.analyze(
            text=text,
            entities=self._entities if entities is None else entities,
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
            cur_sev = severity_rank(current_finding.severity)
            prev_sev = severity_rank(prev_finding.severity)
            if cur_sev > prev_sev or (
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
    """Anonymize positioned, overlap-resolved personal-information findings.

    Callers must resolve overlaps with ``merge_findings`` first. Manual modes
    resolve residual overlaps by severity then confidence. Hash mode requires
    a nonempty key because unkeyed hashes expose low-entropy values."""
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
