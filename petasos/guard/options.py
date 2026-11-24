"""Read a declared program's options before its first verb."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.guard.shell_parse import _program

if TYPE_CHECKING:
    from petasos.guard.surface import CommandProgram, GuardrailSurface


def _readings(argv: tuple[str, ...], surface: GuardrailSurface) -> tuple[tuple[str, ...], ...]:
    """``argv`` with the options before a declared program's first verb set aside.

    The first reading sets aside every word that starts with ``-`` and gives
    a value only to an exact value option. The second reads them as the
    program's parser does (see :func:`_parsed_options`). A rule matches when
    either reading does, so the second can only add a match.
    """
    name = _program(argv[0]) if argv else ""
    for program in surface.programs:
        if name != program.name:
            continue
        loose = _past_options(argv, program, parsed=False)
        parsed = _past_options(_without_stripped(argv, program), program, parsed=True)
        return (loose,) if parsed == loose else (loose, parsed)
    return (argv,)


def _past_options(
    argv: tuple[str, ...], program: CommandProgram, *, parsed: bool
) -> tuple[str, ...]:
    index = 1
    while index < len(argv) and argv[index].startswith("-"):
        word = argv[index]
        index += 1
        if index >= len(argv) or (parsed and word == "--"):
            break
        if parsed:
            taken = _parsed_options(word, program)
        else:
            taken = "value" if word in program.value_options else None
        if taken == "value" or (taken == "optional" and not argv[index].startswith("-")):
            index += 1
    return (argv[0], *argv[index:])


def _parsed_options(word: str, program: CommandProgram) -> str | None:
    """Whether option ``word`` takes the next word, as argparse reads it.

    ``"value"`` when it does, ``"optional"`` when it does unless that word
    starts with ``-``, and ``None`` when it does not. A long option may be
    abbreviated to any prefix no other long option shares. Short options may
    be clustered (``-wm``): the letters before the last take no value, and
    the last takes the next word as its value. A value joined with ``=`` or
    to a short option leaves the next word alone.
    """
    if "=" in word:
        return None
    options = program.value_options | program.optional_value_options | program.flag_options
    if word.startswith("--"):
        if word not in options:
            longer = [option for option in options if option.startswith(word)]
            if len(longer) != 1:
                return None
            word = longer[0]
        return _option_kind(word, program)
    for position in range(1, len(word)):
        option = "-" + word[position]
        if option in program.flag_options:
            continue
        return _option_kind(option, program) if position == len(word) - 1 else None
    return None


def _option_kind(option: str, program: CommandProgram) -> str | None:
    if option in program.value_options:
        return "value"
    if option in program.optional_value_options:
        return "optional"
    return None


def _without_stripped(argv: tuple[str, ...], program: CommandProgram) -> tuple[str, ...]:
    """``argv`` without the first stripped option and its value before ``--``."""
    for index in range(1, len(argv)):
        word = argv[index]
        if word == "--":
            break
        if word in program.stripped_options and index + 1 < len(argv):
            return (*argv[:index], *argv[index + 2 :])
        if "=" in word and word.split("=", 1)[0] in program.stripped_options:
            return (*argv[:index], *argv[index + 1 :])
    return argv
