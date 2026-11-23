"""Recognize commands that change a guardrail."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from petasos.guard.bounds import _MAX_CHARS, _MAX_COMMANDS
from petasos.guard.mutations import (
    _COPIES,
    _INTERPRETERS,
    _NAME_END,
    _READERS,
    _TEXT_ONLY,
    _mutation,
    _operands,
)
from petasos.guard.native_shell import _native_parse, _native_reads, _native_script, _native_shell
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
# These programs have known meanings here even though they have no command
# rule. In particular git/npm config writes are not host settings writes.
_KNOWN_PROGRAMS = (
    _READERS
    | _TEXT_ONLY
    | _INTERPRETERS
    | _COPIES
    | _WRAPPERS
    | _SHELLS
    | {"python", "eval", "git", "npm", "npx", "pnpm", "yarn", "dd", "mv", "rm", "chmod"}
)


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


def _after_cd(command: _Simple, env: Mapping[str, str], cwd: str, *, native: bool = False) -> str:
    """The working directory after ``command``, when it is a ``cd``.

    On Windows a relative directory has two readings. Git Bash's own ``cd``
    takes the shell's, and ``cd`` inside a PowerShell or cmd script
    (``native``) takes the system's.
    """
    argv, _assignments = _strip_wrappers(command.argv)
    if not argv or _program(argv[0]) not in {"cd", "pushd"}:
        return cwd
    targets = _operands(argv)
    if not targets:
        return env.get("HOME") or cwd
    if len(targets) != 1 or targets[0] == "-":
        return cwd
    readings = _expand_path(targets[0], env, cwd, hedge=False)
    return readings[0] if native else readings[-1]


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
    known_program: bool = False,
) -> GuardrailHit | None:
    prepared, assignments = _strip_wrappers(command.argv)
    prepared = _invocation(prepared, surface)
    program = _program(prepared[0]) if prepared else ""
    helping = program in {"hermes", "petasos"} and _asks_help(prepared)
    if not helping:
        for name, value in (*command.assignments, *assignments):
            hit = _env_hit(name, value, surface.env, program=program or None, exporting=False)
            if hit is not None:
                return hit
    if not prepared:
        return _mutation((), command.redirects, owned, env, cwd)
    if not helping:
        for flag in surface.flags:
            if program == flag.program.casefold() and _carries(prepared, flag.flag):
                return GuardrailHit(flag.kind, flag.label)
    rule_argv = _without_global_options(prepared, surface)
    unknown = (
        not known_program
        and program not in _KNOWN_PROGRAMS
        and _native_shell(prepared[0]) is None
        and not any(program == rule.words[0].casefold() for rule in rules)
        and not any(program == flag.program.casefold() for flag in surface.flags)
    )
    for command_rule in rules:
        if helping and command_rule.help_clears:
            continue
        candidate = rule_argv
        fallback = unknown and command_rule.unknown_program and command_rule.tail is not None
        if fallback:
            candidate = (command_rule.words[0], *prepared[1:])
        if _rule_matches(candidate, command_rule):
            return GuardrailHit(command_rule.kind, command_rule.label)
    if helping:
        # Nothing else that changes a guardrail runs, but a redirect still writes.
        return _mutation((), command.redirects, owned, env, cwd)
    exported = _export_hit(prepared, surface)
    if exported is not None:
        return exported
    module = _python_module(prepared) if program == "python" else None
    # The word after ``-m`` is a module name, not a file.
    acted = (prepared[0], *module[1:]) if module else prepared
    hit = _mutation(acted, command.redirects, owned, env, cwd)
    if hit is not None or depth >= 3:
        return hit
    found: GuardrailHit | None = None
    if program == "python":
        script = _c_argument(prepared)
        if script is not None:
            found = _judge_code(script, owned, surface, env, cwd)
        if found is None and module:
            rewritten = _Simple(module, (), ())
            found = _one_command(
                rewritten, owned, surface, rules, env, cwd, depth=depth + 1, known_program=True
            )
    elif program in _SHELLS:
        script = _c_argument(prepared)
        if script is not None:
            found = _nested(script, owned, surface, rules, env, cwd, depth)
    elif program == "eval":
        found = _nested(" ".join(prepared[1:]), owned, surface, rules, env, cwd, depth)
    elif (shell := _native_shell(prepared[0])) is not None:
        script = _native_script(shell, prepared)
        if script is not None:
            found = _native(script, shell, owned, surface, rules, env, cwd, depth)
    if found is not None or program in _TEXT_ONLY or program in _READERS:
        return found
    return _started(prepared, owned, surface, rules, env, cwd, depth)


def _asks_help(argv: tuple[str, ...]) -> bool:
    """True when a help flag comes before ``--`` and before a word that starts with ``#``.

    After ``--`` the word is an operand. The parser does not model comments
    and keeps every word, so a word starting with ``#`` may begin a comment
    the program never receives. A help word after it does not count, which
    can only keep a command from being cleared.
    """
    for word in argv[1:]:
        if word == "--" or word.startswith("#"):
            return False
        if word in _HELP_FLAGS:
            return True
    return False


def _python_module(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    """The module and its arguments for Python's ``-m``, after any interpreter options.

    ``-m`` may be separate, joined to the module (``-mpkg``) or the last letter
    of a cluster (``-um pkg``). ``-W`` and ``-X`` take the next word. ``-c``
    runs code, not a module.
    """
    index = 1
    while index < len(argv):
        word = argv[index]
        if not word.startswith("-") or word in ("-", "--") or word.startswith("--"):
            return None
        letters = word[1:]
        if "m" in letters and letters.isalpha():
            at = letters.index("m")
            if "c" in letters[:at]:
                return None
            joined = letters[at + 1 :]
            rest = argv[index + 1 :]
            return (joined, *rest) if joined else (rest or None)
        if letters.startswith("m"):
            return (letters[1:], *argv[index + 1 :])
        if letters.startswith("c"):
            return None
        index += 2 if word in ("-W", "-X") else 1
    return None


def _invocation(argv: tuple[str, ...], surface: GuardrailSurface) -> tuple[str, ...]:
    """Canonicalise only host-declared executable and Python module forms."""
    if not argv:
        return argv
    name = argv[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    module = _python_module(argv) if _program(argv[0]) == "python" else None
    for program in surface.programs:
        if name in (program.name, *program.aliases):
            return (program.name, *argv[1:])
        if module and module[0] in program.modules:
            return (program.name, *module[1:])
    return argv


def _without_global_options(argv: tuple[str, ...], surface: GuardrailSurface) -> tuple[str, ...]:
    """Set aside options between a declared program and its first verb."""
    for program in surface.programs:
        if _program(argv[0]) != program.name:
            continue
        index = 1
        while index < len(argv) and argv[index].startswith("-"):
            word = argv[index]
            index += 1
            if word in program.value_options and index < len(argv):
                index += 1
        return (argv[0], *argv[index:])
    return argv


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
    program the rules name, a wrapper, a shell, ``python`` or ``eval``. That
    pass comes first, so reading PowerShell and cmd never hides a command it
    would have found. Then it is judged from the first later PowerShell or
    cmd. Each word's path is worked out once for the whole line, so the
    second pass costs little.
    """
    starters = {rule.words[0].casefold() for rule in rules}
    starters.update(flag.program.casefold() for flag in surface.flags)
    starters.update(_WRAPPERS, _SHELLS, {"python", "eval"})
    first = next(
        (
            i
            for i in range(1, len(argv))
            if _program(_invocation((argv[i],), surface)[0]) in starters
        ),
        None,
    )
    native = next((i for i in range(1, len(argv)) if _native_shell(argv[i]) is not None), None)
    for index in (first, native):
        if index is None:
            continue
        rest = _Simple(argv[index:], (), ())
        hit = _one_command(rest, owned, surface, rules, env, cwd, depth=depth + 1)
        if hit is not None:
            return hit
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


def _native(
    script: str,
    shell: str,
    owned: _Owned,
    surface: GuardrailSurface,
    rules: tuple[CommandRule, ...],
    env: Mapping[str, str],
    cwd: str,
    depth: int,
) -> GuardrailHit | None:
    """A script given to PowerShell or cmd, judged command by command.

    A reader of that shell is judged by its redirects only. ``Invoke-Expression``
    is PowerShell's ``eval``.
    """
    for pipeline in _native_parse(script, shell, env):
        for index, (command, plain) in enumerate(pipeline):
            argv = command.argv
            if plain and _native_reads(shell, argv, pipeline[index + 1 :]):
                hit = _mutation((), command.redirects, owned, env, cwd)
            else:
                hit = _one_command(command, owned, surface, rules, env, cwd, depth=depth + 1)
            evaluates = (
                shell != "cmd" and bool(argv) and _program(argv[0]) in {"iex", "invoke-expression"}
            )
            if hit is None and evaluates and depth + 1 < 3:
                rest = " ".join(argv[1:])
                hit = _native(rest, shell, owned, surface, rules, env, cwd, depth + 1)
            if hit is not None:
                return hit
            cwd = _after_cd(command, env, cwd, native=True)
    return None


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
    if rule.requires_flag is not None and not any(
        word == rule.requires_flag or word.startswith(rule.requires_flag + "=") for word in argv
    ):
        return False
    if rule.unless_flags and any(flag in argv for flag in rule.unless_flags):
        return False
    rest = argv[len(rule.words) :]
    positionals = [word for word in rest if not word.startswith("-")]
    if rule.tail is not None:
        # Hermes splits a key at each ``.``: ``approvals_backup`` is another key.
        key = positionals[0].casefold() if positionals else ""
        tail = rule.tail.casefold()
        if key != tail and not key.startswith(tail + "."):
            return False
    if rule.one_of:
        allowed = {item.casefold() for item in rule.one_of}
        if not positionals or positionals[0].casefold() not in allowed:
            return False
    if rule.name is None:
        return True
    if any(_names_plugin(word, rule.name) for word in rest):
        return True
    return rule.bare and not _targets(positionals)


def _targets(positionals: list[str]) -> list[str]:
    """The positionals before the first word that starts with ``#``.

    The parser does not model comments and keeps every word, so such a word
    may begin a comment that holds the rest. Neither it nor what follows is
    taken as naming a target. This only decides whether a command with no
    target matches; a word anywhere that names the plugin still matches.
    """
    for index, word in enumerate(positionals):
        if word.startswith("#"):
            return positionals[:index]
    return positionals


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
