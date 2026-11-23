"""Static pins on the reference plugin's dependency manifest (PET-242).

Hermes filters any requirement carrying a URL out of a plugin's declaration, with
no error, so a ``name @ url`` spaCy model would silently vanish from a rebuild.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

_MANIFEST = Path(__file__).resolve().parents[1] / "docs/deployment/reference_plugin/pyproject.toml"


def _document() -> dict[str, object]:
    with _MANIFEST.open("rb") as f:
        return tomllib.load(f)


def _requirements() -> list[Requirement]:
    project = _document()["project"]
    assert isinstance(project, dict)
    return [Requirement(spec) for spec in project["dependencies"]]


def test_manifest_declares_both_extras() -> None:
    petasos = next(r for r in _requirements() if r.name == "petasos")
    assert petasos.extras == {"presidio", "prompt-guard"}


def test_manifest_keeps_the_version_floor() -> None:
    # Without a floor a resolver can take an older petasos, warn about the unknown
    # extra and install no PromptGuard, and nothing blocks.
    petasos = next(r for r in _requirements() if r.name == "petasos")
    assert ">=0.5.0" in str(petasos.specifier)


def test_petasos_requirement_skips_android() -> None:
    # Hermes locks one workspace for every platform. torch has no Android wheel, so
    # an unmarked requirement fails that lock and Hermes drops the plugin everywhere.
    petasos = next(r for r in _requirements() if r.name == "petasos")
    assert petasos.marker is not None
    assert not petasos.marker.evaluate({"sys_platform": "android"})
    assert petasos.marker.evaluate({"sys_platform": "win32"})
    assert petasos.marker.evaluate({"sys_platform": "darwin"})


def test_no_requirement_carries_a_url() -> None:
    assert [r.name for r in _requirements() if r.url] == []


def test_spacy_model_comes_from_a_uv_source_url() -> None:
    assert "en-core-web-lg" in {r.name for r in _requirements()}
    tool = _document()["tool"]
    assert isinstance(tool, dict)
    source = tool["uv"]["sources"]["en-core-web-lg"]
    assert source["url"].startswith("https://github.com/explosion/spacy-models/releases/download/")
