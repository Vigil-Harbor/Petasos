"""PET-153 packaging / layout + recurrence-prevention guards.

This is the load-bearing recurrence guard and it **must not import fastapi**: it
runs unskipped on the default ``[dev]`` CI lane (pure file reads plus a
module-level import of ``petasos.console.__main__``, whose module top is
fastapi-free by design). The fastapi-dependent ``serve()`` smoke + auth +
entrypoint-contract assertions live in ``test_console_standalone_entrypoint.py``.

Covers the invariants a future regression of the "console backend silently
unmounts after a Hermes update" bug class would have to touch:

- D4: the shipped manifest keeps a safe-relative ``api`` (no auto-import
  traversal primitive reopened).
- D5: no second hook loader / armed-bit source ships in the package.
- The launchable entrypoint is wired and its module top stays fastapi-free.
- The deployment runbook names the supervised standalone console as the durable
  path and the in-tree bundled copy only as the fragile interim (two-marker
  contract).
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

# Module-level import of the entrypoint (the spec's fastapi-free contract): this
# import must succeed with no fastapi installed, so it may NOT live behind an
# importorskip and proves the module top imports no fastapi.
import petasos.console.__main__ as console_main

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PETASOS_DIR = _REPO_ROOT / "petasos"
_MANIFEST = _PETASOS_DIR / "console" / "hermes" / "manifest.json"
_RUNBOOK = _REPO_ROOT / "docs" / "deployment" / "hermes-desktop.md"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

_DURABLE_MARKER = "<!-- PET-153-DURABLE-PATH -->"
_FRAGILE_MARKER = (
    "<!-- PET-153-D2-FRAGILE: in-tree dashboard copy is wiped every Hermes update; "
    "not the durable path -->"
)


# --------------------------------------------------------------------------- #
# D4 — shipped manifest keeps a safe-relative `api`
# --------------------------------------------------------------------------- #


def test_manifest_api_is_safe_relative() -> None:
    """The shipped dashboard manifest's ``api`` is a bare relative filename, so the
    durable path never depends on (and cannot reopen) the GHSA-5qr3-c538-wm9j
    absolute-path / ``..`` traversal importer primitive. Asserts the ``api`` field
    ONLY — ``version`` is the bundle version, deliberately decoupled from
    ``petasos.__version__`` (PET-141), so it is out of scope here."""
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    api = manifest["api"]
    assert api == "plugin_api.py"
    assert "/" not in api
    assert "\\" not in api
    assert ".." not in api
    assert not pathlib.PurePosixPath(api).is_absolute()
    assert not pathlib.PureWindowsPath(api).is_absolute()


# --------------------------------------------------------------------------- #
# D5 — no second hook loader / armed-bit source in the package
# --------------------------------------------------------------------------- #


def test_no_plugin_yaml_packaged_under_petasos() -> None:
    """No ``plugin.yaml`` ships inside the ``petasos`` package, so the out-of-process
    console cannot introduce a second Hermes hook loader or a second armed-bit
    source. The single hook loader stays the operator's user-copy agent plugin."""
    offenders = [str(p.relative_to(_REPO_ROOT)) for p in _PETASOS_DIR.rglob("plugin.yaml")]
    assert offenders == [], f"unexpected plugin.yaml under petasos/: {offenders}"


def test_console_exposes_no_hook_register_symbol() -> None:
    """``petasos.console`` exposes no plugin ``register`` entrypoint a Hermes hook
    loader would discover, so adding the console entrypoint adds no hook surface."""
    import petasos.console as console

    assert not hasattr(console, "register")


# --------------------------------------------------------------------------- #
# Entrypoint wired + fastapi-free module top
# --------------------------------------------------------------------------- #


def test_entrypoint_main_is_callable() -> None:
    assert callable(console_main.main)


def test_pyproject_declares_console_script() -> None:
    """Static-read smoke: ``pyproject.toml`` declares the ``petasos-console``
    console-script mapping the spec adds (the package's first ``[project.scripts]``
    surface)."""
    text = _PYPROJECT.read_text(encoding="utf-8")
    assert 'petasos-console = "petasos.console.__main__:main"' in text


def test_main_module_top_is_fastapi_free_subprocess() -> None:
    """Process-isolated proof that ``petasos.console.__main__``'s module top imports
    no fastapi. An in-process ``assert "fastapi" not in sys.modules`` would
    false-RED on the ``[dev,console]`` lane, where a sibling console test that
    imports fastapi at module scope (e.g. ``test_console_auth.py``) sorts earlier
    and has already populated ``sys.modules``. A fresh subprocess has a clean
    ``sys.modules``, so importing the entrypoint there and checking ``fastapi`` is
    absent is the honest, lane-independent assertion."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, petasos.console.__main__; "
            "raise SystemExit(1 if 'fastapi' in sys.modules else 0)",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "petasos.console.__main__ imported fastapi at module top "
        f"(rc={result.returncode}); stderr:\n{result.stderr}"
    )


# --------------------------------------------------------------------------- #
# Recurrence guard — two-marker DURABLE-PATH / D2-FRAGILE runbook contract
# --------------------------------------------------------------------------- #


def _runbook_blocks() -> tuple[str, str]:
    """Return (durable_block, fragile_block) extracted from the runbook.

    The durable block runs from the DURABLE marker to the FRAGILE marker; the
    fragile block runs from the FRAGILE marker to the next ``## `` (h2) heading or
    end of file. Only content between the markers is inspected, so the agent-hook
    ``~/.hermes/plugins/petasos`` install text elsewhere in the doc never
    false-REDs the guard."""
    doc = _RUNBOOK.read_text(encoding="utf-8")
    assert _DURABLE_MARKER in doc, "DURABLE-PATH marker missing from runbook"
    assert _FRAGILE_MARKER in doc, "D2-FRAGILE marker missing from runbook"

    durable_start = doc.index(_DURABLE_MARKER) + len(_DURABLE_MARKER)
    fragile_at = doc.index(_FRAGILE_MARKER)
    assert durable_start < fragile_at, "DURABLE marker must precede the FRAGILE marker"

    durable_block = doc[durable_start:fragile_at]

    fragile_start = fragile_at + len(_FRAGILE_MARKER)
    next_h2 = doc.find("\n## ", fragile_start)
    fragile_block = doc[fragile_start:] if next_h2 == -1 else doc[fragile_start:next_h2]
    return durable_block, fragile_block


def test_durable_block_names_supervised_standalone_and_no_in_tree_path() -> None:
    """The DURABLE block names the supervised standalone server and contains NO
    ``plugins/`` token: naming an in-tree ``<hermes-agent>/plugins/...`` path as the
    durable answer is exactly the regression this guard catches."""
    durable_block, _ = _runbook_blocks()
    assert "127.0.0.1:8384" in durable_block
    assert "petasos-console" in durable_block
    assert any(token in durable_block for token in ("Task Scheduler", "launchd", "supervisor")), (
        "durable block must name the OS supervisor"
    )
    assert "plugins/" not in durable_block, (
        "DURABLE block names an in-tree plugins/ path — that is the regression"
    )


def test_fragile_block_names_in_tree_path_as_interim() -> None:
    """The D2-FRAGILE block IS allowed to name the in-tree path (it must, to warn
    against it) and flags it as wiped every Hermes update."""
    _, fragile_block = _runbook_blocks()
    assert "plugins/petasos" in fragile_block
    assert "wiped" in fragile_block
