"""Provide syntactic and degraded pipelines for adversarial tests."""

from __future__ import annotations

import pytest

from petasos.config.sections import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner


@pytest.fixture
def minimal_pipeline() -> Pipeline:
    """Provide minimal pipeline for the test fixture."""
    return Pipeline([MinimalScanner()], config=PetasosConfig())


@pytest.fixture
def degraded_pipeline() -> Pipeline:
    """Provide degraded pipeline for the test fixture."""
    return Pipeline(
        [MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded"),
    )
