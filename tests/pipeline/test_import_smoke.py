"""Pin imports and the CLI without optional Hermes dependencies."""

from __future__ import annotations

import importlib

import pytest

from petasos.config.sections import PetasosConfig
from petasos.model import PipelineResult
from petasos.pipeline import Pipeline


def _hermes_deps_available() -> bool:
    try:
        importlib.import_module("spacy")
        importlib.import_module("transformers")
        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not _hermes_deps_available(),
    reason="Hermes deps (spaCy, transformers) not installed",
)
class TestHermesSmoke:
    """Pin Hermes Smoke."""

    async def test_pipeline_construction(self) -> None:
        """Pin pipeline construction."""
        pipe = Pipeline(config=PetasosConfig())
        assert pipe is not None

    async def test_basic_scan(self) -> None:
        """Pin basic scan."""
        pipe = Pipeline(config=PetasosConfig())
        result = await pipe.inspect("test message", session_id="smoke")
        assert isinstance(result, PipelineResult)


class TestImportWithoutHermesDeps:
    """Pin Import Without Hermes Deps."""

    async def test_pipeline_works_without_hermes_deps(self) -> None:
        """Pin pipeline works without hermes deps."""
        pipe = Pipeline(config=PetasosConfig())
        result = await pipe.inspect("hello", session_id="standalone")
        assert isinstance(result, PipelineResult)
        assert result.errors == ()
