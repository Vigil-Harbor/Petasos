"""Recognize commands that change a guardrail."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from petasos.guard.bounds import _MAX_CHARS, _MAX_COMMANDS
from petasos.guard.mutations import (
    _INTERPRETERS,
    _NAME_END,
    _READERS,
    _TEXT_ONLY,
    _mutation,
    _operands,
)
from petasos.guard.paths import _expand_path, _Owned
from petasos.guard.program import _code_names_path, _embedded, _strip_python_comments
from petasos.guard.shell_parse import (
    _WRAPPERS,
    _assignment,
    _parse,
    _program,
    _Simple,
    _strip_wrappers,
)
from petasos.guard.surface import (
    CommandRule,
    EnvRule,
    GuardrailHit,
    GuardrailSurface,
    library_rules,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


# Arguments are text or a number, never a file the program opens.
_HELP_FLAGS = frozenset({"-h", "--help"})
_SHELLS = frozenset({"ash", "bash", "dash", "ksh", "sh", "zsh"})
_ALL_NAMES = frozenset({"*", "--all", "-a", "all"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_MAX_HEREDOCS = 8
_HEREDOC_OPEN = re.compile(r"""<<-?[ \t]*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")


def _command_change(
    text: str,
    owned: _Owned,
    surface: GuardrailSurface,
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS]
    rules = library_rules() + surface.commands
    hit = _each_command(_parse(text), owned, surface, rules, env, cwd, depth=0)
    if hit is not None:
        return hit
    return _heredoc_hit(text, owned, surface, env, cwd)


def _each_command(
    commands: list[_Simple],
    owned: _Owned,
    surface: GuardrailSurface,
    rules: tuple[CommandRule, ...],
    env: Mapping[str, str],
    cwd: str,
    *,
    depth: int,
) -> GuardrailHit | None:
    """Judge commands in order. A ``cd`` moves the directory the later ones run in."""
    for command in commands[:_MAX_COMMANDS]:
        hit = _one_command(command, owned, surface, rules, env, cwd, depth=depth)
        if hit is not None:
            return hit
        cwd = _after_cd(command, env, cwd)
    return None


def _after_cd(command: _Simple, env: Mapping[str, str], cwd: str) -> str:
    argv, _assignments = _strip_wrappers(command.argv)
    if not argv or _program(argv[0]) not in {"cd", "pushd"}:
        return cwd
    targets = _operands(argv)
    if not targets:
        return env.get("HOME") or cwd
    if len(targets) != 1 or targets[0] == "-":
        return cwd
    return _expand_path(targets[0], env, cwd)[0]


def _heredoc_hit(
    text: str,
    owned: _Owned,
    surface: GuardrailSurface,
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    """Program text handed to an interpreter as a here-document.

    The body's lines were already judged as shell commands, which is what a
    shell reading the document would run. This adds the reading for Python and
    the other interpreters, where a line is not a command.
    """
    for line, body in _heredocs(text):
        programs = set()
        for command in _parse(line):
            argv, _assignments = _strip_wrappers(command.argv)
            if argv:
                programs.add(_program(argv[0]))
        if "python" in programs:
            hit = _judge_code(body, owned, surface, env, cwd)
        elif programs & _INTERPRETERS:
            hit = _code_names_path(body, owned, env, cwd)
        else:
            continue
        if hit is not None:
            return hit
    return None


def _heredocs(text: str) -> list[tuple[str, str]]:
    """The opening line and the body of each here-document, up to a small bound.

    A document with no closing line runs to the end of the text.
    """
    lines = text.split("\n")
    found: list[tuple[str, str]] = []
    index = 0
    while index < len(lines) and len(found) < _MAX_HEREDOCS:
        opened = _HEREDOC_OPEN.search(lines[index])
        if opened is None:
            index += 1
            continue
        tag = opened.group(2)
        end = index + 1
        while end < len(lines) and lines[end].strip() != tag:
            end += 1
        found.append((lines[index], "\n".join(lines[index + 1 : end])))
        index = end + 1
    return found


def _one_command(
    command: _Simple,
    owned: _Owned,
    surface: GuardrailSurface,
    rules: tuple[CommandRule, ...],
    env: Mapping[str, str],
    cwd: str,
    *,
    depth: int,
) -> GuardrailHit | None:
    prepared, assignments = _strip_wrappers(command.argv)
    program = _program(prepared[0]) if prepared else ""
    helping = program in {"hermes", "petasos"} and bool(_HELP_FLAGS.intersection(prepared))
    if not helping:
        for name, value in (*command.assignments, *assignments):
            hit = _env_hit(name, value, surface.env, program=program or None, exporting=False)
            if hit is not None:
                return hit
    if helping or not prepared:
        # Nothing that changes a guardrail runs, but a redirect still writes.
        return _mutation((), command.redirects, owned, env, cwd)
    for flag in surface.flags:
        if program == flag.program.casefold() and _carries(prepared, flag.flag):
            return GuardrailHit(flag.kind, flag.label)
    for command_rule in rules:
        if _rule_matches(prepared, command_rule):
            return GuardrailHit(command_rule.kind, command_rule.label)
    exported = _export_hit(prepared, surface)
    if exported is not None:
        return exported
    module = program == "python" and len(prepared) >= 3 and prepared[1] == "-m"
    # The word after ``-m`` is a module name, not a file.
    acted = (prepared[0], *prepared[3:]) if module else prepared
    hit = _mutation(acted, command.redirects, owned, env, cwd)
    if hit is not None or depth >= 3:
        return hit
    found: GuardrailHit | None = None
    if program == "python":
        script = _c_argument(prepared)
        if script is not None:
            found = _judge_code(script, owned, surface, env, cwd)
        if found is None and module:
            rewritten = _Simple((prepared[2], *prepared[3:]), (), ())
            found = _one_command(rewritten, owned, surface, rules, env, cwd, depth=depth + 1)
    elif program in _SHELLS:
        script = _c_argument(prepared)
        if script is not None:
            found = _nested(script, owned, surface, rules, env, cwd, depth)
    elif program == "eval":
        found = _nested(" ".join(prepared[1:]), owned, surface, rules, env, cwd, depth)
    if found is not None or program in _TEXT_ONLY or program in _READERS:
        return found
    return _started(prepared, owned, surface, rules, env, cwd, depth)


def _carries(argv: tuple[str, ...], flag: str) -> bool:
    """True when ``flag`` is a word of its own or is written ``--flag=value``."""
    glued = flag + "=" if flag.startswith("--") else None
    return any(word == flag or (glued is not None and word.startswith(glued)) for word in argv[1:])


def _started(
    argv: tuple[str, ...],
    owned: _Owned,
    surface: GuardrailSurface,
    rules: tuple[CommandRule, ...],
    env: Mapping[str, str],
    cwd: str,
    depth: int,
) -> GuardrailHit | None:
    """A command that this one starts, such as ``timeout 5 hermes ...``.

    The rest of the line is judged again from the first later word that is a
    program the rules name, a wrapper, a shell, ``python`` or ``eval``.
    """
    starters = {rule.words[0].casefold() for rule in rules}
    starters.update(flag.program.casefold() for flag in surface.flags)
    starters.update(_WRAPPERS, _SHELLS, {"python", "eval"})
    for index in range(1, len(argv)):
        if _program(argv[index]) in starters:
            rest = _Simple(argv[index:], (), ())
            return _one_command(rest, owned, surface, rules, env, cwd, depth=depth + 1)
    return None


def _nested(
    script: str,
    owned: _Owned,
    surface: GuardrailSurface,
    rules: tuple[CommandRule, ...],
    env: Mapping[str, str],
    cwd: str,
    depth: int,
) -> GuardrailHit | None:
    return _each_command(_parse(script), owned, surface, rules, env, cwd, depth=depth + 1)


def _c_argument(argv: tuple[str, ...]) -> str | None:
    for index, word in enumerate(argv[1:], start=1):
        if word == "--":
            return None
        short = word.startswith("-") and not word.startswith("--") and "c" in word[1:]
        if word == "-c" or short:
            if index + 1 < len(argv):
                return argv[index + 1]
            return None
    return None


def _rule_matches(argv: tuple[str, ...], rule: CommandRule) -> bool:
    if len(argv) < len(rule.words):
        return False
    for index, expected in enumerate(rule.words):
        actual = _program(argv[index]) if index == 0 else argv[index].casefold()
        if actual != expected.casefold():
            return False
    if rule.requires_flag is not None and rule.requires_flag not in argv:
        return False
    if rule.unless_flags and any(flag in argv for flag in rule.unless_flags):
        return False
    rest = argv[len(rule.words) :]
    if rule.tail is not None and (
        not rest or not rest[0].casefold().startswith(rule.tail.casefold())
    ):
        return False
    positionals = [word for word in rest if not word.startswith("-")]
    if rule.one_of:
        allowed = {item.casefold() for item in rule.one_of}
        if not positionals or positionals[0].casefold() not in allowed:
            return False
    if rule.name is None:
        return True
    if any(_names_plugin(word, rule.name) for word in rest):
        return True
    return rule.bare and not positionals


def _names_plugin(word: str, name: str) -> bool:
    """True when ``word`` names the plugin, everything, or a source for it.

    A version, an extra or a reference after the name still names it
    (``petasos==0.1``, ``petasos[all]``, ``.../petasos.git@main``), and so
    does a built file for it (``petasos-0.1-py3-none-any.whl``).
    """
    folded = word.casefold()
    wanted = name.casefold()
    if folded in _ALL_NAMES:
        return True
    if "#" in word and word.rsplit("#", 1)[-1].strip("/").casefold() == wanted:
        return True
    for piece in (folded, folded.rstrip("/").rsplit("/", 1)[-1]):
        head = _NAME_END.split(piece, maxsplit=1)[0].removesuffix(".git")
        if head == wanted or re.match(re.escape(wanted) + r"-\d", head):
            return True
    return False


def _env_hit(
    name: str,
    value: str,
    rules: tuple[EnvRule, ...],
    *,
    program: str | None,
    exporting: bool,
) -> GuardrailHit | None:
    for rule in rules:
        if name != rule.name:
            continue
        if rule.program is not None and not exporting and program != rule.program:
            continue
        if rule.any_value or value.strip().casefold() in _TRUTHY:
            return GuardrailHit(rule.kind, rule.label)
    return None


def _export_hit(argv: tuple[str, ...], surface: GuardrailSurface) -> GuardrailHit | None:
    if not argv or _program(argv[0]) != "export":
        return None
    for word in argv[1:]:
        if word.startswith("-"):
            continue
        name, value, consumed = _assignment(word)
        if consumed and name is not None:
            hit = _env_hit(name, value or "", surface.env, program=None, exporting=True)
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", word):
            hit = _env_hit(word, "", surface.env, program=None, exporting=True)
        else:
            continue
        if hit is not None:
            return hit
    return None


def _judge_code(
    text: str,
    owned: _Owned,
    surface: GuardrailSurface,
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    """Embedded shell commands, then any protected path the program text names.

    Comments are removed first. A ``#`` outside a string starts a comment;
    one inside a string does not. See :func:`_strip_python_comments`.
    """
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS]
    visible = _strip_python_comments(text)
    for piece in _embedded(visible)[:_MAX_COMMANDS]:
        hit = _command_change(piece, owned, surface, env, cwd)
        if hit is not None:
            return hit
    return _code_names_path(visible, owned, env, cwd)
