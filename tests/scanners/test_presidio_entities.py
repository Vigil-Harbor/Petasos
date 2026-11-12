"""Pin curated personal-information scope and additive per-call entity selection.

See docs/architecture/rationale.md, "Test timing and backend qualification"."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.scanners.minimal.taxonomy import _STRUCTURAL_RULE_IDS, _UNSUPPRESSIBLE_RULE_IDS
from petasos.scanners.presidio import (
    DEFAULT_PRESIDIO_ENTITIES,
    NOISY_OPT_IN_ENTITIES,
    PresidioScanner,
    resolve_presidio_entities,
)

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

requires_presidio = pytest.mark.skipif(
    not (_presidio_available and _spacy_model_available),
    reason="presidio + spaCy model required",
)


class _RecordingAnalyzer:
    """Backend-free stand-in for presidio's AnalyzerEngine. Records the exact
    ``entities`` list ``analyzer.analyze`` is handed, with no spaCy dependency, so
    the per-call effective-entity computation can be asserted on every lane."""

    def __init__(self) -> None:
        self.entities: list[str] | None = None

    def analyze(
        self,
        *,
        text: str,
        entities: list[str],
        language: str,
        score_threshold: float,
    ) -> list[Any]:
        self.entities = list(entities)
        return []


def _recording_scanner(**kw: Any) -> tuple[PresidioScanner, _RecordingAnalyzer]:
    s = PresidioScanner(**kw)
    rec = _RecordingAnalyzer()
    s._analyzer = rec
    s._loaded = True
    return s, rec


def test_default_entities_exclude_noisy_set() -> None:
    assert isinstance(DEFAULT_PRESIDIO_ENTITIES, tuple)
    for noisy in NOISY_OPT_IN_ENTITIES:
        assert noisy not in DEFAULT_PRESIDIO_ENTITIES
    expected = {
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
    }
    assert set(DEFAULT_PRESIDIO_ENTITIES) == expected
    assert len(DEFAULT_PRESIDIO_ENTITIES) == 10


def test_resolve_entities_default_and_extra() -> None:
    assert resolve_presidio_entities(None) == list(DEFAULT_PRESIDIO_ENTITIES)
    assert resolve_presidio_entities(None, ("URL",)) == list(DEFAULT_PRESIDIO_ENTITIES) + ["URL"]
    assert resolve_presidio_entities(("PERSON",)) == ["PERSON"]
    assert resolve_presidio_entities(("PERSON",), ("URL",)) == ["PERSON", "URL"]
    assert resolve_presidio_entities(("EMAIL_ADDRESS", "EMAIL_ADDRESS"), ("EMAIL_ADDRESS",)) == [
        "EMAIL_ADDRESS"
    ]
    with pytest.raises(ValueError):
        resolve_presidio_entities((), ())


def test_default_scanner_entities_wired() -> None:
    assert PresidioScanner()._entities == list(DEFAULT_PRESIDIO_ENTITIES)
    assert PresidioScanner(entities=["PERSON"])._entities == ["PERSON"]


def test_structural_ids_subset_of_unsuppressible() -> None:
    assert _STRUCTURAL_RULE_IDS <= _UNSUPPRESSIBLE_RULE_IDS


@requires_presidio
def test_presidio_entities_extra_url_fires() -> None:
    cfg = from_mapping(
        PetasosConfig,
        {
            "scanners": {
                "presidio": {
                    "entities_extra": ("URL",),
                },
            },
        },
    )
    scanner = PresidioScanner(
        entities=resolve_presidio_entities(
            cfg.scanners.presidio.entities, cfg.scanners.presidio.entities_extra
        ),
    )
    import asyncio

    result = asyncio.run(scanner.scan("Visit https://example.com for the docs"))
    assert result.error is None
    assert any("url" in f.rule_id for f in result.findings)

    default_scanner = PresidioScanner()
    default_result = asyncio.run(default_scanner.scan("Visit https://example.com for the docs"))
    assert default_result.error is None
    assert not any("url" in f.rule_id for f in default_result.findings)


@requires_presidio
class TestPresidioTightenedDefault:
    def test_benign_technical_corpus_no_pii_findings(self) -> None:
        import asyncio

        scanner = PresidioScanner()
        corpus = "\n".join(
            [
                "Vigil Harbor Wiki Location",
                "$WIKI/projects/petasos/state.md and $WIKI/index.md",
                'node wiki-lint.mjs . --repos "petasos,dynasty"',
                "version 2.1.0",
                "tickets: DYN RAD MCP PET",
                "See https://vigilharbor.com/docs/petasos for details",
            ]
        )
        result = asyncio.run(scanner.scan(corpus))
        assert result.error is None
        assert result.findings == (), f"expected zero findings, got {result.findings}"

    def test_real_pii_still_detected(self) -> None:
        import asyncio

        scanner = PresidioScanner()
        # The SSN context raises the recognizer score above its 0.35 threshold.
        corpus = (
            "Please update records: social security number 219-09-9999 on file, "
            "card 4111 1111 1111 1111, email john@example.com, call 555-123-4567."
        )
        result = asyncio.run(scanner.scan(corpus))
        assert result.error is None
        rule_ids = {f.rule_id for f in result.findings}
        assert any("us_ssn" in r for r in rule_ids), rule_ids
        assert any("credit_card" in r for r in rule_ids), rule_ids
        assert any("email" in r for r in rule_ids), rule_ids
        assert any("phone" in r for r in rule_ids), rule_ids


def test_scan_no_extra_uses_base() -> None:
    for extra in (None, ()):
        scanner, rec = _recording_scanner()
        asyncio.run(scanner.scan("text", extra_entities=extra))
        assert rec.entities == list(DEFAULT_PRESIDIO_ENTITIES)
    scanner, rec = _recording_scanner()
    asyncio.run(scanner.scan("text"))
    assert rec.entities == list(DEFAULT_PRESIDIO_ENTITIES)


def test_scan_extra_entities_additive() -> None:
    scanner, rec = _recording_scanner()
    asyncio.run(scanner.scan("text", extra_entities=("PERSON",)))
    assert rec.entities == [*DEFAULT_PRESIDIO_ENTITIES, "PERSON"]


def test_scan_extra_entities_dedup() -> None:
    scanner, rec = _recording_scanner()
    asyncio.run(scanner.scan("text", extra_entities=("EMAIL_ADDRESS",)))
    assert rec.entities == list(DEFAULT_PRESIDIO_ENTITIES)
    assert rec.entities.count("EMAIL_ADDRESS") == 1


def test_scan_does_not_mutate_self_entities() -> None:
    scanner, rec = _recording_scanner()
    asyncio.run(scanner.scan("text", extra_entities=("PERSON",)))
    assert scanner._entities == list(DEFAULT_PRESIDIO_ENTITIES)
    assert "PERSON" not in scanner._entities


def test_scan_unknown_extra_threads_through() -> None:
    # Unknown entities must reach Presidio rather than vanish silently in wrapper filtering.
    scanner, rec = _recording_scanner()
    asyncio.run(scanner.scan("text", extra_entities=("NOT_A_REAL_ENTITY",)))
    assert rec.entities == [*DEFAULT_PRESIDIO_ENTITIES, "NOT_A_REAL_ENTITY"]
