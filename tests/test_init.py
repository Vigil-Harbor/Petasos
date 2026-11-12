"""Pin root exports and imports without optional host or scanner dependencies."""

from __future__ import annotations

import importlib
import importlib.metadata

import pytest

import petasos


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
        import spacy  # noqa: F811
        import transformers  # noqa: F811

        import petasos  # noqa: F811

        assert petasos is not None
        assert spacy is not None
        assert transformers is not None

    async def test_version_accessible(self) -> None:
        import petasos

        assert hasattr(petasos, "__version__")
        assert isinstance(petasos.__version__, str)


class TestImportWithoutHermesDeps:
    async def test_petasos_imports_standalone(self) -> None:
        import petasos

        assert petasos.__version__ is not None


def test_package_version_single_source() -> None:
    # Distribution metadata is absent in source-only checkouts; editable installs can verify
    # version consistency.
    try:
        dist_version = importlib.metadata.version("petasos")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("petasos has no dist metadata (source-only checkout); D7")
    assert dist_version == petasos.__version__
