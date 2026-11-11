"""Disguises a guardrail command can wear, and the ones recognition leaves alone."""

from __future__ import annotations

from petasos.hermes.guardrail import hermes_surface
from petasos.session.guardrail import GuardrailHit, recognize

_SURFACE = hermes_surface(())


def _command(text: str) -> GuardrailHit | None:
    return recognize("terminal", {"command": text}, surface=_SURFACE, package=())


def test_cheap_disguises_still_name_the_plugin() -> None:
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
    for command in (
        "hermes plugins list",
        "hermes config get plugins.enabled",
        "petasos doctor",
        "echo hermes plugins disable petasos",
        "echo 'hermes plugins disable petasos' > /tmp/notes.txt",
    ):
        assert _command(command) is None, command


def test_encoded_and_indirect_forms_are_not_claimed() -> None:
    """These are real ways past a string match. Recognition does not catch them."""
    for command in (
        "echo aGVybWVzIHBsdWdpbnMgZGlzYWJsZSBwZXRhc29z | base64 -d | sh",
        "cmd=hermes; $cmd plugins disable petasos",
        'python -c \'import os; os.system("herm" + "es plugins disable petasos")\'',
    ):
        assert _command(command) is None, command
