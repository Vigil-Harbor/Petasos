"""PET-141: version-sourcing drift guards.

Single-source invariant: the repo holds exactly one package-version literal
(``petasos/__init__.py:__version__``); the console reads it at runtime and the
build derives it via Hatch. These guards run in the default (fastapi-free) CI
lane, so a reintroduced hardcoded literal fails the gate where it has teeth.

There is NO ``importorskip("fastapi")`` here on purpose (spec D6): every console
test file skips entirely in the default CI lane (no fastapi installed), so the
drift tripwire must live in this module, which imports only the stdlib plus
``petasos``.
"""

from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

import pytest

import petasos

# A quoted three-segment integer literal: "0.1.0" / '2.3.4'. The pattern requires
# the surrounding quotes and exactly three dotted integer segments, so it matches
# a reintroduced Python version literal (always a quoted string) while it does
# NOT match a bare or quoted dotted-quad such as ``127.0.0.1`` / ``"127.0.0.1"``
# (the closing quote does not sit after the third segment), nor a two-segment
# numeric (``1.0``), nor a version-shaped number in prose. See spec § Test
# details — this is the one authoritative regex for the guard.
_VERSION_LITERAL = re.compile(r"""['\"]\d+\.\d+\.\d+['\"]""")

_SERVER_PY = Path(petasos.__file__).resolve().parent / "console" / "server.py"


def _literal_hits(text: str) -> list[str]:
    # Line-wise scan mirroring tests/test_ci_extras_lanes.py: skip comment lines
    # (``lstrip`` starts with ``#``), return every non-comment line that bears a
    # quoted version literal.
    hits: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if _VERSION_LITERAL.search(line):
            hits.append(line.strip())
    return hits


def test_no_hardcoded_version_literal_in_console() -> None:
    # Regression for PET-141: no quoted version literal may re-enter the console
    # server source; the version must be sourced from ``petasos.__version__``.
    source = _SERVER_PY.read_text(encoding="utf-8")
    hits = _literal_hits(source)
    assert hits == [], f"hardcoded version literal(s) in console/server.py: {hits}"

    # Synthetic negative case pinning the dotted-quad exclusion (mirrors the
    # test_ci_extras_lanes.py synthetic suite): the guard must NOT fire on a host
    # literal, so a future widening of the pattern cannot silently regress it.
    assert _literal_hits('    host = "127.0.0.1"') == []


def test_package_version_single_source() -> None:
    # Regression for PET-141: build/dist metadata cannot diverge from the single
    # source ``__version__``. Skips on a source-only checkout where no dist
    # metadata exists (D7); runs in CI where ``pip install -e .`` provides
    # editable dist metadata, exactly where the build-derived invariant must hold.
    try:
        dist_version = importlib.metadata.version("petasos")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("petasos has no dist metadata (source-only checkout); D7")
    assert dist_version == petasos.__version__
