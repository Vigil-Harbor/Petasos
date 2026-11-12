"""PET-109: Presidio entity scoping — default-set, config round-trip/apply, and
real-backend regression (benign technical corpus + real-PII preservation).

The backend-free rows are module-level functions. The two `@requires_presidio`
rows live in class ``TestPresidioTightenedDefault`` — the ``target_class`` the
conftest non-skipping-lane guard pins for ``extras-presidio`` (D4).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from petasos.config.layers import resolve
from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner
from petasos.scanners.presidio import (
    DEFAULT_PRESIDIO_ENTITIES,
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


class _RecordingPresidio(PresidioScanner):
    """PresidioScanner subclass wired to a recording analyzer so the pipeline's
    ``isinstance(s, PresidioScanner)`` Presidio special-case holds (the extras are
    only threaded to scanners that are PresidioScanner instances)."""

    def __init__(self) -> None:
        super().__init__()
        self._rec = _RecordingAnalyzer()
        self._analyzer = self._rec
        self._loaded = True


def test_config_scopes_presidio_entities_and_threshold() -> None:
    # A scanner built the way plugin_api builds it yields the expected wiring.
    cfg = from_mapping(
        PetasosConfig,
        {
            "scanners": {
                "presidio": {
                    "entities_extra": ("URL",),
                    "score_threshold": 0.4,
                },
            },
        },
    )
    scanner = PresidioScanner(
        entities=resolve_presidio_entities(
            cfg.scanners.presidio.entities, cfg.scanners.presidio.entities_extra
        ),
        score_threshold=cfg.scanners.presidio.score_threshold,
    )
    assert scanner._entities == list(DEFAULT_PRESIDIO_ENTITIES) + ["URL"]
    assert scanner._score_threshold == 0.4


# --- pipeline threading (backend-free) -------------------------------------


def test_pipeline_passes_profile_extras_to_presidio() -> None:
    rec_presidio = _RecordingPresidio()
    pipeline = Pipeline(
        [MinimalScanner(), rec_presidio],
        config=resolve({"role": "support"}).config,
    )
    asyncio.run(pipeline.inspect("benign text"))
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
    pipeline = Pipeline(
        [MinimalScanner(), rec_presidio],
        config=resolve({"role": "general"}).config,
    )
    asyncio.run(pipeline.inspect("benign text"))
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

    def _pipeline(self, role: str) -> Pipeline:
        return Pipeline(
            [MinimalScanner(), PresidioScanner()],
            config=resolve({"role": role}).config,
        )

    def test_person_fires_under_customer_service_not_general(self) -> None:
        cs = asyncio.run(self._pipeline("support").inspect(self._CORPUS))
        assert cs.errors == ()
        person = [f for f in cs.findings if f.rule_id == "petasos.presidio.person"]
        assert person, f"expected a PERSON finding under customer_service, got {cs.findings}"
        # Buffer above the 0.35 threshold so a marginal future model regression fails
        # loudly rather than flaking.
        assert max(f.confidence for f in person) > 0.45

        general = asyncio.run(self._pipeline("general").inspect(self._CORPUS))
        assert general.errors == ()
        assert not any(f.rule_id == "petasos.presidio.person" for f in general.findings), (
            f"PERSON must not fire under general (no opt-in), got {general.findings}"
        )

    def test_admin_person_fires(self) -> None:
        admin = asyncio.run(self._pipeline("admin").inspect(self._CORPUS))
        assert admin.errors == ()
        assert any(f.rule_id == "petasos.presidio.person" for f in admin.findings), (
            f"expected a PERSON finding under admin, got {admin.findings}"
        )
