from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from petasos._types import (
    Position,
    ScanFinding,
    Scanner,
    Severity,
)
from petasos.scanners.presidio import (
    _SEVERITY_MAP,
    PresidioScanner,
    _make_hmac_operator_class,
    _recover_entity_type,
    anonymize,
)

# ---------------------------------------------------------------------------
# Skip markers for optional-dependency tests
# ---------------------------------------------------------------------------

_presidio_available = True
try:
    import presidio_analyzer  # noqa: F401
    import presidio_anonymizer  # noqa: F401
except ImportError:
    _presidio_available = False

_spacy_model_available = False
if _presidio_available:
    try:
        import spacy

        spacy.load("en_core_web_lg")
        _spacy_model_available = True
    except (ImportError, OSError):
        pass

requires_presidio_libs = pytest.mark.skipif(
    not _presidio_available,
    reason="presidio-analyzer + presidio-anonymizer required",
)

requires_presidio = pytest.mark.skipif(
    not (_presidio_available and _spacy_model_available),
    reason="presidio + spaCy model required",
)

# ---------------------------------------------------------------------------
# Unit tests — no Presidio dependency required
# ---------------------------------------------------------------------------


class TestSeverityMapping:
    def test_critical_entities(self) -> None:
        for et in ("CREDIT_CARD", "IBAN_CODE", "US_SSN", "US_BANK_NUMBER", "CRYPTO"):
            assert _SEVERITY_MAP[et] == Severity.CRITICAL

    def test_high_entities(self) -> None:
        for et in (
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "US_DRIVER_LICENSE",
            "US_PASSPORT",
            "IP_ADDRESS",
        ):
            assert _SEVERITY_MAP[et] == Severity.HIGH

    def test_medium_entities(self) -> None:
        for et in ("PERSON", "LOCATION", "DATE_TIME", "NRP"):
            assert _SEVERITY_MAP[et] == Severity.MEDIUM

    def test_unknown_defaults_to_low(self) -> None:
        assert _SEVERITY_MAP.get("SOME_UNKNOWN_TYPE", Severity.LOW) == Severity.LOW


class TestEntityTypeRecovery:
    def test_presidio_prefix(self) -> None:
        assert _recover_entity_type("petasos.presidio.person") == "PERSON"

    def test_presidio_prefix_with_hyphen(self) -> None:
        assert _recover_entity_type("petasos.presidio.us-ssn") == "US_SSN"

    def test_non_presidio_rule(self) -> None:
        assert (
            _recover_entity_type("petasos.syntactic.injection.role-switch-capability")
            == "ROLE_SWITCH_CAPABILITY"
        )

    def test_simple_dotted(self) -> None:
        assert _recover_entity_type("scanner.email_address") == "EMAIL_ADDRESS"


class TestScannerProtocol:
    def test_satisfies_protocol(self) -> None:
        scanner = PresidioScanner()
        assert isinstance(scanner, Scanner)

    def test_name_property(self) -> None:
        scanner = PresidioScanner()
        assert scanner.name == "presidio"


# ---------------------------------------------------------------------------
# Error-path tests (mocked)
# ---------------------------------------------------------------------------


class TestLazyLoadFailure:
    async def test_import_error_returns_errored_result(self) -> None:
        scanner = PresidioScanner()
        with patch.dict("sys.modules", {"presidio_analyzer": None}):
            scanner._loaded = False
            scanner._load_error = None
            scanner._analyzer = None
            scanner._anonymizer = None
            result = await scanner.scan("test")
            assert result.error is not None
            assert "presidio not installed" in result.error
            assert result.findings == ()

    async def test_spacy_model_missing(self) -> None:
        scanner = PresidioScanner()

        scanner._load_error = None
        scanner._loaded = False
        err = OSError("Can't find model 'en_core_web_lg'")
        with patch.object(scanner, "_ensure_loaded", side_effect=err):
            result = await scanner.scan("test")
            assert result.error is not None
            assert "spaCy model" in result.error
            assert result.findings == ()

    async def test_backend_exception_during_analyze(self) -> None:
        scanner = PresidioScanner()
        scanner._loaded = True
        scanner._analyzer = type(
            "MockAnalyzer",
            (),
            {"analyze": lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))},
        )()
        result = await scanner.scan("test")
        assert result.error is not None
        assert result.findings == ()


# ---------------------------------------------------------------------------
# Anonymization unit tests (no real Presidio scanning needed)
# ---------------------------------------------------------------------------


def _make_finding(
    rule_id: str,
    start: int,
    end: int,
    confidence: float = 0.9,
    matched_text: str | None = None,
) -> ScanFinding:
    return ScanFinding(
        rule_id=rule_id,
        finding_type="pii",
        severity=Severity.HIGH,
        confidence=confidence,
        message="test",
        scanner_name="presidio",
        position=Position(start=start, end=end),
        matched_text=matched_text,
    )


class TestAnonymizeEmptyInputs:
    def test_empty_findings_returns_original(self) -> None:
        assert anonymize("Hello world", []) == "Hello world"

    def test_empty_text_returns_empty(self) -> None:
        assert anonymize("", []) == ""

    def test_all_unpositioned_findings_returns_original(self) -> None:
        finding = ScanFinding(
            rule_id="petasos.presidio.person",
            finding_type="pii",
            severity=Severity.MEDIUM,
            confidence=0.9,
            message="test",
            scanner_name="presidio",
            position=None,
            matched_text="John",
        )
        assert anonymize("John is here", [finding]) == "John is here"


@requires_presidio_libs
class TestAnonymizeRedact:
    def test_single_entity_redacted(self) -> None:
        text = "Call John Smith please"
        finding = _make_finding("petasos.presidio.person", 5, 15, matched_text="John Smith")
        result = anonymize(text, [finding], mode="redact")
        assert "<PERSON>" in result
        assert "John Smith" not in result

    def test_multiple_entity_types(self) -> None:
        text = "Email john@example.com or call 555-1234"
        f1 = _make_finding(
            "petasos.presidio.email_address", 6, 22, matched_text="john@example.com"
        )
        f2 = _make_finding("petasos.presidio.phone_number", 31, 39, matched_text="555-1234")
        result = anonymize(text, [f1, f2], mode="redact")
        assert "<EMAIL_ADDRESS>" in result
        assert "<PHONE_NUMBER>" in result


class TestAnonymizeReplace:
    def test_counter_based_labels(self) -> None:
        text = "John and Jane are friends"
        f1 = _make_finding("petasos.presidio.person", 0, 4, matched_text="John")
        f2 = _make_finding("petasos.presidio.person", 9, 13, matched_text="Jane")
        result = anonymize(text, [f1, f2], mode="replace")
        assert "<PERSON_1>" in result
        assert "<PERSON_2>" in result
        assert "John" not in result
        assert "Jane" not in result

    def test_counter_resets_across_calls(self) -> None:
        text = "John is here"
        finding = _make_finding("petasos.presidio.person", 0, 4, matched_text="John")
        r1 = anonymize(text, [finding], mode="replace")
        r2 = anonymize(text, [finding], mode="replace")
        assert r1 == r2


@requires_presidio_libs
class TestAnonymizeHash:
    def test_hmac_deterministic(self) -> None:
        text = "John Smith lives here"
        finding = _make_finding("petasos.presidio.person", 0, 10, matched_text="John Smith")
        r1 = anonymize(text, [finding], mode="hash", hash_key="secret")
        r2 = anonymize(text, [finding], mode="hash", hash_key="secret")
        assert r1 == r2
        assert "John Smith" not in r1

    def test_different_keys_produce_different_hashes(self) -> None:
        text = "John Smith lives here"
        finding = _make_finding("petasos.presidio.person", 0, 10, matched_text="John Smith")
        r1 = anonymize(text, [finding], mode="hash", hash_key="key1")
        r2 = anonymize(text, [finding], mode="hash", hash_key="key2")
        assert r1 != r2

    def test_hash_without_key_raises(self) -> None:
        text = "John Smith lives here"
        finding = _make_finding("petasos.presidio.person", 0, 10, matched_text="John Smith")
        with pytest.raises(ValueError, match="hash_key"):
            anonymize(text, [finding], mode="hash")

    def test_hash_mode_rejects_empty_key(self) -> None:
        text = "John Smith lives here"
        finding = _make_finding("petasos.presidio.person", 0, 10, matched_text="John Smith")
        with pytest.raises(ValueError, match="hash_key"):
            anonymize(text, [finding], mode="hash", hash_key="")

    def test_hash_mode_with_valid_key_works(self) -> None:
        text = "John Smith lives here"
        finding = _make_finding("petasos.presidio.person", 0, 10, matched_text="John Smith")
        result = anonymize(text, [finding], mode="hash", hash_key="secret")
        assert "John Smith" not in result

    def test_hmac_operator_rejects_empty_key(self) -> None:
        cls = _make_hmac_operator_class()
        op = cls()
        with pytest.raises(ValueError, match="non-empty"):
            op.validate({"hmac_key": ""})

    def test_hmac_operator_rejects_missing_key(self) -> None:
        cls = _make_hmac_operator_class()
        op = cls()
        with pytest.raises(ValueError):
            op.validate({})

    def test_redact_mode_ignores_hash_key(self) -> None:
        text = "John Smith lives here"
        finding = _make_finding("petasos.presidio.person", 0, 10, matched_text="John Smith")
        result = anonymize(text, [finding], mode="redact", hash_key=None)
        assert "John Smith" not in result
        assert "<PERSON>" in result


class TestAnonymizeMask:
    def test_mask_hides_leading(self) -> None:
        text = "SSN 123-45-6789"
        finding = _make_finding("petasos.presidio.us_ssn", 4, 15, matched_text="123-45-6789")
        result = anonymize(text, [finding], mode="mask")
        assert "123-45-6789" not in result
        assert "6789" in result
        assert "*" in result

    def test_mask_short_value_fully_masked(self) -> None:
        text = "Age 25 here"
        finding = _make_finding("petasos.presidio.date_time", 4, 6, matched_text="25")
        result = anonymize(text, [finding], mode="mask")
        assert result == "Age ** here"

    def test_mask_matched_text_none_fallback(self) -> None:
        text = "SSN 123-45-6789"
        finding = _make_finding("petasos.presidio.us_ssn", 4, 15, matched_text=None)
        result = anonymize(text, [finding], mode="mask")
        assert "123-45-6789" not in result
        assert "6789" in result


class TestAnonymizeOverlap:
    def test_overlapping_manual_path_deduplicates(self) -> None:
        text = "John Smith Jr is here"
        f1 = _make_finding(
            "petasos.presidio.person", 0, 10, confidence=0.9, matched_text="John Smith"
        )
        f2 = _make_finding(
            "petasos.presidio.person", 5, 18, confidence=0.85, matched_text="Smith Jr is"
        )
        result = anonymize(text, [f1, f2], mode="replace")
        assert result.count("<PERSON_") == 1

    def test_overlapping_higher_confidence_wins(self) -> None:
        text = "John Smith Jr is here"
        f1 = _make_finding(
            "petasos.presidio.person", 0, 10, confidence=0.7, matched_text="John Smith"
        )
        f2 = _make_finding(
            "petasos.presidio.person", 5, 18, confidence=0.95, matched_text="Smith Jr is"
        )
        result = anonymize(text, [f1, f2], mode="replace")
        assert "<PERSON_1>" in result
        assert "John " in result


class TestAnonymizeUnsortedFindings:
    def test_reverse_order_input_handled(self) -> None:
        text = "John and Jane"
        f1 = _make_finding("petasos.presidio.person", 9, 13, matched_text="Jane")
        f2 = _make_finding("petasos.presidio.person", 0, 4, matched_text="John")
        result = anonymize(text, [f2, f1], mode="replace")
        assert "<PERSON_1>" in result
        assert "<PERSON_2>" in result


@requires_presidio_libs
class TestAnonymizeMixedPositioned:
    def test_unpositioned_findings_skipped(self) -> None:
        text = "John is at john@test.com"
        positioned = _make_finding("petasos.presidio.person", 0, 4, matched_text="John")
        unpositioned = ScanFinding(
            rule_id="petasos.syntactic.injection.ignore-previous",
            finding_type="injection",
            severity=Severity.HIGH,
            confidence=1.0,
            message="test",
            scanner_name="minimal",
            position=None,
            matched_text=None,
        )
        result = anonymize(text, [positioned, unpositioned], mode="redact")
        assert "<PERSON>" in result
        assert "john@test.com" in result


# ---------------------------------------------------------------------------
# Integration tests — require presidio-analyzer + presidio-anonymizer + spaCy
# ---------------------------------------------------------------------------


@requires_presidio
class TestPresidioScannerIntegration:
    @pytest.fixture
    def scanner(self) -> PresidioScanner:
        return PresidioScanner()

    def test_detect_email(self, scanner: PresidioScanner) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            scanner.scan("Contact us at john@example.com for details")
        )
        assert result.error is None
        assert len(result.findings) > 0
        emails = [f for f in result.findings if "email" in f.rule_id]
        assert len(emails) > 0
        f = emails[0]
        assert f.position is not None
        assert f.matched_text == "john@example.com"

    def test_detect_phone(self, scanner: PresidioScanner) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            scanner.scan("Call me at 555-123-4567")
        )
        assert result.error is None
        phone_findings = [f for f in result.findings if "phone" in f.rule_id]
        assert len(phone_findings) > 0

    def test_detect_person(self, scanner: PresidioScanner) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            scanner.scan("My name is John Smith and I live in New York")
        )
        assert result.error is None
        persons = [f for f in result.findings if "person" in f.rule_id]
        assert len(persons) > 0

    def test_detect_credit_card(self, scanner: PresidioScanner) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            scanner.scan("My credit card is 4111-1111-1111-1111")
        )
        assert result.error is None
        cc = [f for f in result.findings if "credit_card" in f.rule_id]
        assert len(cc) > 0
        assert cc[0].severity == Severity.CRITICAL

    def test_no_pii_clean(self, scanner: PresidioScanner) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            scanner.scan("The weather is nice today")
        )
        assert result.error is None
        assert len(result.findings) == 0

    def test_empty_text(self, scanner: PresidioScanner) -> None:
        result = asyncio.get_event_loop().run_until_complete(scanner.scan(""))
        assert result.error is None
        assert len(result.findings) == 0

    def test_position_accuracy(self, scanner: PresidioScanner) -> None:
        text = "Email john@example.com now"
        result = asyncio.get_event_loop().run_until_complete(scanner.scan(text))
        for f in result.findings:
            if f.position is not None and f.matched_text is not None:
                assert text[f.position.start : f.position.end] == f.matched_text

    def test_confidence_range(self, scanner: PresidioScanner) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            scanner.scan("john@example.com, 555-1234, John Smith")
        )
        for f in result.findings:
            assert 0.0 < f.confidence <= 1.0

    def test_duration_tracked(self, scanner: PresidioScanner) -> None:
        result = asyncio.get_event_loop().run_until_complete(scanner.scan("john@example.com"))
        assert result.duration_ms > 0

    def test_score_threshold_filtering(self) -> None:
        scanner = PresidioScanner(score_threshold=0.9)
        result = asyncio.get_event_loop().run_until_complete(
            scanner.scan("Maybe John from somewhere")
        )
        assert result.error is None
        for f in result.findings:
            assert f.confidence >= 0.9

    def test_custom_entities_filter(self) -> None:
        scanner = PresidioScanner(entities=["EMAIL_ADDRESS"])
        result = asyncio.get_event_loop().run_until_complete(
            scanner.scan("John at john@example.com")
        )
        assert result.error is None
        for f in result.findings:
            assert "email" in f.rule_id

    def test_multi_finding_message(self, scanner: PresidioScanner) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            scanner.scan("Contact John Smith at john@example.com or 555-123-4567")
        )
        assert result.error is None
        assert len(result.findings) >= 2

    def test_scanner_name_in_findings(self, scanner: PresidioScanner) -> None:
        result = asyncio.get_event_loop().run_until_complete(scanner.scan("john@example.com"))
        for f in result.findings:
            assert f.scanner_name == "presidio"


@requires_presidio
class TestAnonymizeIntegration:
    def _scan_and_anonymize(
        self,
        text: str,
        mode: str = "redact",
        hash_key: str | None = None,
    ) -> str:
        scanner = PresidioScanner()
        result = asyncio.get_event_loop().run_until_complete(scanner.scan(text))
        return anonymize(
            text,
            list(result.findings),
            mode=mode,  # type: ignore[arg-type]
            hash_key=hash_key,
        )

    def test_redact_removes_pii(self) -> None:
        text = "Email john@example.com please"
        result = self._scan_and_anonymize(text, mode="redact")
        assert "john@example.com" not in result
        assert "<" in result

    def test_replace_with_counters(self) -> None:
        text = "Contact John Smith or Jane Doe"
        result = self._scan_and_anonymize(text, mode="replace")
        assert "John Smith" not in result or "Jane Doe" not in result

    def test_hash_with_key_deterministic(self) -> None:
        text = "Email john@example.com please"
        r1 = self._scan_and_anonymize(text, mode="hash", hash_key="test-key")
        r2 = self._scan_and_anonymize(text, mode="hash", hash_key="test-key")
        assert r1 == r2
        assert "john@example.com" not in r1

    def test_mask_shows_trailing(self) -> None:
        text = "SSN is 123-45-6789"
        scanner = PresidioScanner()
        result = asyncio.get_event_loop().run_until_complete(scanner.scan(text))
        ssn_findings = [f for f in result.findings if f.position is not None]
        if ssn_findings:
            masked = anonymize(text, list(result.findings), mode="mask")
            assert "*" in masked
