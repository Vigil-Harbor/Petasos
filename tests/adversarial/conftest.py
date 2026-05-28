"""Shared fixtures for PET-14 adversarial corpus (Bucket B)."""

from __future__ import annotations

import pytest

from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner


@pytest.fixture
def minimal_pipeline() -> Pipeline:
    return Pipeline([MinimalScanner()], config=PetasosConfig())


@pytest.fixture
def degraded_pipeline() -> Pipeline:
    return Pipeline(
        [MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded"),
    )
