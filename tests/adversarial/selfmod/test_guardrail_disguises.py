"""Disguises a guardrail command can wear, and the ones recognition leaves alone."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.guard.guardrail import recognize
from petasos.hermes.guardrail import hermes_surface

if TYPE_CHECKING:
    from petasos.guard.surface import GuardrailHit

_SURFACE = hermes_surface(())


def _command(text: str) -> GuardrailHit | None:
    return recognize("terminal", {"command": text}, surface=_SURFACE, package=())


def test_cheap_disguises_still_name_the_plugin() -> None:
    """Pin cheap disguises still name the plugin."""
    for command in (
        "hermes plugins disable petasos",
        "sh -c 'hermes plugins disable petasos'",
        "FOO=bar hermes plugins disable petasos",
        "echo ready && hermes plugins disable petasos",
        'hermes plugins disable "petasos"',
    ):
        hit = _command(command)
        assert hit is not None and hit.kind == "plugin", command


def test_mentions_and_reads_are_not_changes() -> None:
    """Pin mentions and reads are not changes."""
    for command in (
        "hermes plugins list",
        "hermes config get plugins.enabled",
        "petasos doctor",
        "echo hermes plugins disable petasos",
        "echo 'hermes plugins disable petasos' > /tmp/notes.txt",
    ):
        assert _command(command) is None, command


def test_a_backslash_and_joined_quotes_still_name_the_command() -> None:
    """Pin a backslash and joined quotes still name the command."""
    for command in (
        r"her\mes plugins disable petasos",
        'her""mes plugins disable petasos',
        "h'e'rmes plugins disable petasos",
        r"hermes plu\gins disable petasos",
    ):
        hit = _command(command)
        assert hit is not None and hit.kind == "plugin", command


def test_encoded_and_indirect_forms_are_not_claimed() -> None:
    """These are real ways past a string match. Recognition does not catch them."""
    for command in (
        "echo aGVybWVzIHBsdWdpbnMgZGlzYWJsZSBwZXRhc29z | base64 -d | sh",
        "cmd=hermes; $cmd plugins disable petasos",
        'python -c \'import os; os.system("herm" + "es plugins disable petasos")\'',
    ):
        assert _command(command) is None, command
