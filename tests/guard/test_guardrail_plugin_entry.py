"""Hermes entry points that can skip or change plugin loading."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.guard.test_guardrail import _hit

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("full", "shortest"),
    [("--safe-mode", "--sa"), ("--ignore-user-config", "--ignore-u")],
)
@pytest.mark.parametrize("verb", ["", "chat "])
@pytest.mark.parametrize("suffix", ["", "=1", "=false"])
def test_plugin_bypass_prefixes_are_changes(
    tmp_path: Path, full: str, shortest: str, verb: str, suffix: str
) -> None:
    for length in range(len(shortest), len(full) + 1):
        command = f"hermes {verb}{full[:length]}{suffix}"
        hit = _hit(tmp_path, "terminal", {"command": command})
        assert hit is not None and hit.kind == "plugin", command


@pytest.mark.parametrize(
    "command",
    [
        "hermes plugins",
        "hermes plugins --unknown-option",
        "hermes --profile work plugins",
        "python -m hermes_cli plugins",
        "hermes plugins # note",
        "hermes plugins #note list",
        "hermes plugins # --help",
        "echo $(hermes plugins)",
    ],
)
def test_plugin_menu_is_a_change(tmp_path: Path, command: str) -> None:
    hit = _hit(tmp_path, "terminal", {"command": command})
    assert hit is not None and hit.kind == "plugin"


@pytest.mark.parametrize(
    "command",
    [
        "hermes plugins list",
        "hermes plugins ls",
        "hermes plugins show other",
        "hermes plugins unknown",
        "hermes plugins --unknown-option list",
        "hermes plugins list # note",
        "hermes plugins --help",
        "hermes plugins -h",
        "hermes --help plugins",
        "hermes plugins enable petasos",
        "hermes --prof work",
        "hermes chat --prof work",
    ],
)
def test_plugin_menu_rule_leaves_verbs_help_and_profile_abbreviations_alone(
    tmp_path: Path, command: str
) -> None:
    assert _hit(tmp_path, "terminal", {"command": command}) is None
