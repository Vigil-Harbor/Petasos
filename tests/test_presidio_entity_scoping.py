"""PET-109: Presidio entity scoping — default-set, config round-trip/apply, and
real-backend regression (benign technical corpus + real-PII preservation).

The backend-free rows are module-level functions. The two `@requires_presidio`
rows live in class ``TestPresidioTightenedDefault`` — the ``target_class`` the
conftest non-skipping-lane guard pins for ``extras-presidio`` (D4).
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import pytest

from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import (
    _STRUCTURAL_RULE_IDS,
    _UNSUPPRESSIBLE_RULE_IDS,
    MinimalScanner,
)
from petasos.scanners.presidio import (
    DEFAULT_PRESIDIO_ENTITIES,
    NOISY_OPT_IN_ENTITIES,
    PresidioScanner,
    resolve_presidio_entities,
)

# ---------------------------------------------------------------------------
# Skip markers for optional-dependency tests (mirrors test_presidio_scanner.py)
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

requires_presidio = pytest.mark.skipif(
    not (_presidio_available and _spacy_model_available),
    reason="presidio + spaCy model required",
)


# ---------------------------------------------------------------------------
# Backend-free unit tests (run on every lane)
# ---------------------------------------------------------------------------


def test_default_entities_exclude_noisy_set() -> None:
    assert isinstance(DEFAULT_PRESIDIO_ENTITIES, tuple)  # frozen/immutable (D6)
    # The five noisy NER/loose-pattern entities are excluded from the default.
    for noisy in NOISY_OPT_IN_ENTITIES:
        assert noisy not in DEFAULT_PRESIDIO_ENTITIES
    # The 10-entity CRITICAL/HIGH security band is present.
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
    # extra is additive (opt back in URL)
    assert resolve_presidio_entities(None, ("URL",)) == list(DEFAULT_PRESIDIO_ENTITIES) + ["URL"]
    # explicit base replaces wholesale
    assert resolve_presidio_entities(("PERSON",)) == ["PERSON"]
    assert resolve_presidio_entities(("PERSON",), ("URL",)) == ["PERSON", "URL"]
    # order-preserving dedup
    assert resolve_presidio_entities(("EMAIL_ADDRESS", "EMAIL_ADDRESS"), ("EMAIL_ADDRESS",)) == [
        "EMAIL_ADDRESS"
    ]
    # a degenerate empty base + empty extra violates the non-empty contract
    with pytest.raises(ValueError):
        resolve_presidio_entities((), ())


def test_default_scanner_entities_wired() -> None:
    assert PresidioScanner()._entities == list(DEFAULT_PRESIDIO_ENTITIES)
    # contract change (D3): an explicit list is used verbatim
    assert PresidioScanner(entities=["PERSON"])._entities == ["PERSON"]


def test_config_round_trips_presidio_fields() -> None:
    cfg = PetasosConfig(
        presidio_entities=("EMAIL_ADDRESS", "US_SSN"),
        presidio_entities_extra=("URL",),
        presidio_score_threshold=0.5,
    )
    rt = PetasosConfig.from_dict(cfg.to_dict())
    assert rt.presidio_entities == ("EMAIL_ADDRESS", "US_SSN")
    assert rt.presidio_entities_extra == ("URL",)
    assert rt.presidio_score_threshold == 0.5

    # None -> to_dict -> from_dict -> None (no existing precedent; assert explicitly)
    base = PetasosConfig()
    assert base.presidio_entities is None
    rt_none = PetasosConfig.from_dict(base.to_dict())
    assert rt_none.presidio_entities is None

    # invalid threshold
    with pytest.raises(ValueError):
        PetasosConfig(presidio_score_threshold=1.5)
    with pytest.raises(ValueError):
        PetasosConfig(presidio_score_threshold=math.nan)
    # empty explicit presidio_entities is meaningless
    with pytest.raises(ValueError):
        PetasosConfig(presidio_entities=())
    # bare-string / empty-string entries
    with pytest.raises(ValueError):
        PetasosConfig(presidio_entities="EMAIL_ADDRESS")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        PetasosConfig(presidio_entities=("",))
    with pytest.raises(ValueError):
        PetasosConfig(presidio_entities_extra="URL")  # type: ignore[arg-type]


def test_presidio_entities_casing_normalized() -> None:
    # case-folded AND surrounding whitespace trimmed (a " URL " entry would otherwise
    # be a silent no-op — it matches no recognizer in analyzer.analyze).
    cfg = PetasosConfig(
        presidio_entities=(" person ", "url"),
        presidio_entities_extra=("ip_address ",),
        pii_entities=(" EMAIL_ADDRESS ",),
    )
    assert cfg.presidio_entities == ("PERSON", "URL")
    assert cfg.presidio_entities_extra == ("IP_ADDRESS",)
    assert cfg.pii_entities == ("EMAIL_ADDRESS",)  # trimmed (D7 filter uppercases at read)


def test_whitespace_only_entity_entries_rejected() -> None:
    # whitespace-only entries are non-empty but normalize to nothing — reject them
    # rather than let them silently disable a security-sensitive detector/filter.
    with pytest.raises(ValueError):
        PetasosConfig(presidio_entities=("   ",))
    with pytest.raises(ValueError):
        PetasosConfig(presidio_entities_extra=("\t",))
    with pytest.raises(ValueError):
        PetasosConfig(pii_entities=("  ",))


def test_structural_ids_subset_of_unsuppressible() -> None:
    # Tripwire (D6): the _is_floor_rule structural-prefix disjunct can never diverge
    # from the set, because every structural ID is already unsuppressible.
    assert _STRUCTURAL_RULE_IDS <= _UNSUPPRESSIBLE_RULE_IDS


def test_config_scopes_presidio_entities_and_threshold() -> None:
    # A scanner built the way plugin_api builds it yields the expected wiring.
    cfg = PetasosConfig(presidio_entities_extra=("URL",), presidio_score_threshold=0.4)
    scanner = PresidioScanner(
        entities=resolve_presidio_entities(cfg.presidio_entities, cfg.presidio_entities_extra),
        score_threshold=cfg.presidio_score_threshold,
    )
    assert scanner._entities == list(DEFAULT_PRESIDIO_ENTITIES) + ["URL"]
    assert scanner._score_threshold == 0.4


@requires_presidio
def test_presidio_entities_extra_url_fires() -> None:
    # Integration arm of the config-scoping row: opting URL in via the extra makes
    # URL fire on a URL string (it does not under the curated default).
    cfg = PetasosConfig(presidio_entities_extra=("URL",))
    scanner = PresidioScanner(
        entities=resolve_presidio_entities(cfg.presidio_entities, cfg.presidio_entities_extra),
    )
    import asyncio

    result = asyncio.run(scanner.scan("Visit https://example.com for the docs"))
    assert result.error is None
    assert any("url" in f.rule_id for f in result.findings)

    # control: under the curated default, URL does NOT fire
    default_scanner = PresidioScanner()
    default_result = asyncio.run(default_scanner.scan("Visit https://example.com for the docs"))
    assert default_result.error is None
    assert not any("url" in f.rule_id for f in default_result.findings)


# ---------------------------------------------------------------------------
# Real-backend regression — non-skipping on the extras-presidio lane (D4)
# ---------------------------------------------------------------------------


@requires_presidio
class TestPresidioTightenedDefault:
    def test_benign_technical_corpus_no_pii_findings(self) -> None:
        import asyncio

        scanner = PresidioScanner()  # curated default
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

        scanner = PresidioScanner()  # curated default
        # Phrasing chosen so each entity scores above the default 0.35 threshold:
        # the SSN needs its "social security number" context to clear the bar.
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


# ---------------------------------------------------------------------------
# PET-119: profile.pii_entities_extra → per-profile Presidio scoping
#
# These pins make the field load-bearing: each fails if a profile-set PII entity
# silently no-ops again. The scan-level and pipeline-level rows are backend-free
# (a recording fake stands in for the analyzer); the real-backend contract lives
# in TestProfilePresidioScoping below.
# ---------------------------------------------------------------------------


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


class _RecordingPresidio(PresidioScanner):
    """PresidioScanner subclass wired to a recording analyzer so the pipeline's
    ``isinstance(s, PresidioScanner)`` Presidio special-case holds (the extras are
    only threaded to scanners that are PresidioScanner instances)."""

    def __init__(self) -> None:
        super().__init__()
        self._rec = _RecordingAnalyzer()
        self._analyzer = self._rec
        self._loaded = True


# --- scan() additive channel (backend-free) --------------------------------


def test_scan_no_extra_uses_base() -> None:
    # Negative pin: no extras (omitted / None / empty) records exactly the base set.
    for extra in (None, ()):
        scanner, rec = _recording_scanner()
        asyncio.run(scanner.scan("text", extra_entities=extra))
        assert rec.entities == list(DEFAULT_PRESIDIO_ENTITIES)
    scanner, rec = _recording_scanner()
    asyncio.run(scanner.scan("text"))  # keyword omitted entirely
    assert rec.entities == list(DEFAULT_PRESIDIO_ENTITIES)


def test_scan_extra_entities_additive() -> None:
    scanner, rec = _recording_scanner()
    asyncio.run(scanner.scan("text", extra_entities=("PERSON",)))
    assert rec.entities == [*DEFAULT_PRESIDIO_ENTITIES, "PERSON"]


def test_scan_extra_entities_dedup() -> None:
    # EMAIL_ADDRESS is already in the base — the additive union must not duplicate it.
    scanner, rec = _recording_scanner()
    asyncio.run(scanner.scan("text", extra_entities=("EMAIL_ADDRESS",)))
    assert rec.entities == list(DEFAULT_PRESIDIO_ENTITIES)
    assert rec.entities.count("EMAIL_ADDRESS") == 1


def test_scan_does_not_mutate_self_entities() -> None:
    # Decision 6 concurrency invariant: the effective list is a per-call local;
    # self._entities is read-only after construction.
    scanner, rec = _recording_scanner()
    asyncio.run(scanner.scan("text", extra_entities=("PERSON",)))
    assert scanner._entities == list(DEFAULT_PRESIDIO_ENTITIES)
    assert "PERSON" not in scanner._entities


def test_scan_unknown_extra_threads_through() -> None:
    # Presidio is the filter — the wiring must not silently drop unknown names, or a
    # regression could hide behind a swallowed entity (Design note, edge-cases/F-2).
    scanner, rec = _recording_scanner()
    asyncio.run(scanner.scan("text", extra_entities=("NOT_A_REAL_ENTITY",)))
    assert rec.entities == [*DEFAULT_PRESIDIO_ENTITIES, "NOT_A_REAL_ENTITY"]


# --- pipeline threading (backend-free) -------------------------------------


def test_pipeline_passes_profile_extras_to_presidio() -> None:
    rec_presidio = _RecordingPresidio()
    pipeline = Pipeline([MinimalScanner(), rec_presidio])
    asyncio.run(pipeline.inspect("benign text", profile="customer_service"))
    # customer_service extras = [PERSON, EMAIL_ADDRESS, PHONE_NUMBER]; EMAIL_ADDRESS
    # and PHONE_NUMBER are already in the base, so the order-preserving union adds
    # only PERSON.
    assert rec_presidio._rec.entities == [*DEFAULT_PRESIDIO_ENTITIES, "PERSON"]


def test_pipeline_no_profile_uses_base() -> None:
    # Negative pin at the pipeline layer: no active profile -> keyword omitted ->
    # base set; no profile leakage.
    rec_presidio = _RecordingPresidio()
    pipeline = Pipeline([MinimalScanner(), rec_presidio])
    asyncio.run(pipeline.inspect("benign text"))
    assert rec_presidio._rec.entities == list(DEFAULT_PRESIDIO_ENTITIES)


def test_pipeline_general_profile_empty_extras_uses_base() -> None:
    # Empty-extras pin (edge-cases/F-1): general's pii_entities_extra == [] makes the
    # keyword present-but-empty, which must collapse to the base — structurally
    # distinct from the no-profile branch (keyword omitted) and the most common live
    # path whenever general is active.
    rec_presidio = _RecordingPresidio()
    pipeline = Pipeline([MinimalScanner(), rec_presidio])
    asyncio.run(pipeline.inspect("benign text", profile="general"))
    assert rec_presidio._rec.entities == list(DEFAULT_PRESIDIO_ENTITIES)


# ---------------------------------------------------------------------------
# Real-backend contract — non-skipping on the extras-presidio lane (PET-119)
# ---------------------------------------------------------------------------


@requires_presidio
class TestProfilePresidioScoping:
    """The load-bearing contract: a profile opt-in (PERSON) that is NOT in the config
    default fires under that profile and not under one without it. This is the exact
    assertion PET-117 declined to add (it would false-green while the field was inert);
    it fails if the profile→Presidio wiring ever regresses."""

    # NER-friendly corpus: a full name with a title + a "Customer name:" cue scores
    # PERSON comfortably above the 0.35 default threshold on en_core_web_lg. Phrasing
    # is pinned, not deferred — PERSON is spaCy-NER, not a deterministic pattern
    # recognizer, so a bare "John Smith" can fall below threshold and flake.
    _CORPUS = "Customer name: Dr. Margaret Thompson called about her account."

    def _pipeline(self) -> Pipeline:
        return Pipeline([MinimalScanner(), PresidioScanner()])

    def test_person_fires_under_customer_service_not_general(self) -> None:
        pipeline = self._pipeline()

        cs = asyncio.run(pipeline.inspect(self._CORPUS, profile="customer_service"))
        assert cs.errors == ()
        person = [f for f in cs.findings if f.rule_id == "petasos.presidio.person"]
        assert person, f"expected a PERSON finding under customer_service, got {cs.findings}"
        # Buffer above the 0.35 threshold so a marginal future model regression fails
        # loudly rather than flaking.
        assert max(f.confidence for f in person) > 0.45

        general = asyncio.run(pipeline.inspect(self._CORPUS, profile="general"))
        assert general.errors == ()
        assert not any(f.rule_id == "petasos.presidio.person" for f in general.findings), (
            f"PERSON must not fire under general (no opt-in), got {general.findings}"
        )

    def test_admin_person_fires(self) -> None:
        pipeline = self._pipeline()
        admin = asyncio.run(pipeline.inspect(self._CORPUS, profile="admin"))
        assert admin.errors == ()
        assert any(f.rule_id == "petasos.presidio.person" for f in admin.findings), (
            f"expected a PERSON finding under admin, got {admin.findings}"
        )
