from __future__ import annotations

import importlib

import pytest

from petasos._types import PipelineResult
from petasos.config import PetasosConfig
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
    async def test_import_coexistence(self) -> None:
        import petasos  # noqa: F811
        import spacy  # noqa: F811
        import transformers  # noqa: F811

        assert petasos is not None
        assert spacy is not None
        assert transformers is not None

    async def test_pipeline_construction(self) -> None:
        pipe = Pipeline(config=PetasosConfig())
        assert pipe is not None

    async def test_basic_scan(self) -> None:
        pipe = Pipeline(config=PetasosConfig())
        result = await pipe.inspect("test message", session_id="smoke")
        assert isinstance(result, PipelineResult)

    async def test_version_accessible(self) -> None:
        import petasos

        assert hasattr(petasos, "__version__")
        assert isinstance(petasos.__version__, str)


class TestImportWithoutHermesDeps:
    async def test_petasos_imports_standalone(self) -> None:
        import petasos

        assert petasos.__version__ is not None

    async def test_pipeline_works_without_hermes_deps(self) -> None:
        pipe = Pipeline(config=PetasosConfig())
        result = await pipe.inspect("hello", session_id="standalone")
        assert isinstance(result, PipelineResult)
        assert result.errors == ()
