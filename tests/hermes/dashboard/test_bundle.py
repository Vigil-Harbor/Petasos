"""The shipped tab script is what its sources produce, and fetches nothing else."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "build_dashboard.py"
_DASHBOARD = _ROOT / "hermes-plugin" / "petasos" / "dashboard"


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_dashboard", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("build_dashboard", module)
    spec.loader.exec_module(module)
    return module


def test_committed_index_js_matches_its_sources() -> None:
    """Edit src/ and run scripts/build_dashboard.py; this fails until you do."""
    builder = _builder()
    committed = (_DASHBOARD / "index.js").read_text(encoding="utf-8")
    assert committed == builder.render_index(), (
        "hermes-plugin/petasos/dashboard/index.js is stale. Run: python scripts/build_dashboard.py"
    )


def test_check_mode_reports_a_stale_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--check exits 1 when the shipped file differs from the sources, 0 when it matches."""
    builder = _builder()
    sources = tmp_path / "src"
    sources.mkdir()
    (sources / "00-a.js").write_text("var a = 1;\n", encoding="utf-8")
    (sources / "style.css").write_text(".petasos {}\n", encoding="utf-8")
    text = builder.render_index(sources)
    assert text.startswith("/*")
    assert '"use strict";' in text
    assert "var a = 1;" in text
    assert "petasos-tab-style" in text
    target = tmp_path / "index.js"
    monkeypatch.setattr(builder, "SOURCES", sources)
    monkeypatch.setattr(builder, "TARGET", target)
    monkeypatch.setattr(builder, "render_index", lambda: text)
    target.write_text("// old\n", encoding="utf-8")
    assert builder.main(["--check"]) == 1
    assert builder.main([]) == 0
    assert target.read_text(encoding="utf-8") == text
    assert builder.main(["--check"]) == 0


def test_the_tab_uses_only_hermes_and_its_own_api() -> None:
    """No network asset, no second fetch path, no font or image of its own."""
    sources = _DASHBOARD / "src"
    script = "\n".join(path.read_text(encoding="utf-8") for path in sorted(sources.glob("*.js")))
    css = (sources / "style.css").read_text(encoding="utf-8")
    assert re.search(r"(?<![.\w])fetch\(", script) is None, "use SDK.fetchJSON"
    assert "__HERMES_SESSION_TOKEN__" not in script
    assert "import(" not in script
    assert "@import" not in css
    assert "url(" not in css
    assert "@font-face" not in css
    # Colours come from Hermes's variables. A literal hex colour is a palette of our own.
    assert re.search(r"#[0-9a-fA-F]{3,8}\b", css) is None
    assert 'var API = "/api/plugins/petasos";' in script


# Strings Hermes's plugin guard (tools/plugin_guard.py at v0.23.1) reads as an
# attack. A plugin directory that holds one gets a "dangerous" verdict, and
# Hermes refuses to load the plugin. Sample attacks for Try it are served by
# the API from the wheel instead.
_GUARD_TRIPS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "rm -rf",
    "| bash",
    "| sh",
    "~/.ssh",
    "system override",
    "developer mode",
)


def test_the_plugin_directory_holds_no_sample_attack() -> None:
    """Nothing Hermes scans before loading the plugin looks like an attack."""
    plugin = _DASHBOARD.parent
    found = []
    for path in sorted(plugin.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        found.extend(
            f"{path.relative_to(plugin)}: {trip}" for trip in _GUARD_TRIPS if trip in text
        )
    assert found == []
