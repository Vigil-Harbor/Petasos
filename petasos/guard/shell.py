"""Recognize commands that change a guardrail."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from petasos.guard.bounds import (
    _MAX_DEPTH,
    _MAX_QUOTE_DEPTH,
    _TOO_DEEP,
    _TOO_LONG,
    _UNREADABLE,
)
from petasos.guard.mutations import (
    _COPIES,
    _INTERPRETERS,
    _READERS,
    _TEXT_ONLY,
    _mutation,
    _operands,
)
from petasos.guard.native_shell import (
    _native_parse,
    _native_reads,
    _native_script,
    _native_shell,
    _passive_after,
)
from petasos.guard.options import _readings
from petasos.guard.paths import _expand_path, _Owned, _Unreadable
from petasos.guard.program import _code_names_path, _embedded, _strip_python_comments
from petasos.guard.rule_match import _rule_matches
from petasos.guard.shell_parse import (
    _WRAPPERS,
    _assignment,
    _c_argument,
    _heredocs,
    _program,
    _python_module,
    _Simple,
    _spelled,
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
_TRUTHY = frozenset({"1", "true", "yes", "on"})
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
_BLANKS = (" ", "\t", "\n")


@dataclass(frozen=True, slots=True)
class _Rules:
    """The command rules for one text, indexed by the program each names.

    A command is compared only with its own program's rules, or with the
    rules that also match an unknown program, so the cost per command does
    not grow with the number of rules.
    """

    by_program: Mapping[str, tuple[CommandRule, ...]]
    unknown: tuple[CommandRule, ...]
    starters: frozenset[str]
    flag_programs: frozenset[str]
    # The rules that write configuration (``help_clears`` off), which the
    # reading of quoted text matches, and what may start one there.
    writers: Mapping[str, tuple[CommandRule, ...]]
    unknown_writers: tuple[CommandRule, ...]
    verbs: frozenset[str]
    invoked: frozenset[str]
    names: tuple[str, ...]


def _index(rules: tuple[CommandRule, ...], surface: GuardrailSurface) -> _Rules:
    grouped: dict[str, list[CommandRule]] = {}
    writing: dict[str, list[CommandRule]] = {}
    for rule in rules:
        grouped.setdefault(rule.words[0].casefold(), []).append(rule)
        if not rule.help_clears:
            writing.setdefault(rule.words[0].casefold(), []).append(rule)
    flag_programs = frozenset(flag.program.casefold() for flag in surface.flags)
    unknown = tuple(rule for rule in rules if rule.unknown_program and rule.tail is not None)
    unknown_writers = tuple(rule for rule in unknown if not rule.help_clears)
    verbs = frozenset(rule.words[1].casefold() for rule in unknown_writers if len(rule.words) > 1)
    invoked = set(writing)
    for program in surface.programs:
        if program.name in writing:
            invoked.update(program.aliases)
    names = invoked | verbs
    for program in surface.programs:
        if program.name in writing:
            names.update(program.modules)
    return _Rules(
        by_program={program: tuple(found) for program, found in grouped.items()},
        unknown=unknown,
        starters=frozenset(grouped) | flag_programs | _WRAPPERS | _SHELLS | {"python", "eval"},
        flag_programs=flag_programs,
        writers={program: tuple(found) for program, found in writing.items()},
        unknown_writers=unknown_writers,
        verbs=verbs,
        invoked=frozenset(name.casefold() for name in invoked),
        names=tuple(sorted(name.casefold() for name in names)),
    )


def _command_change(
    text: str,
    owned: _Owned,
    surface: GuardrailSurface,
    env: Mapping[str, str],
    cwd: str,
    *,
    plain: tuple[str, ...] | None = None,
    depth: int = 0,
) -> GuardrailHit | None:
    """The first guardrail change ``text`` makes when a shell runs it.

    ``plain`` is the whole tool call's command text read as one plain
    command (see ``recognize``), or ``None``. Only a rule's ``except_exact``
    consults it. ``depth`` is how deep in other text ``text`` was found
    (see ``_MAX_DEPTH``).
    """
    rules = _index(library_rules() + surface.commands, surface)
    commands = _spelled(text)
    hit = _each_command(commands, owned, surface, rules, env, cwd, depth=depth, plain=plain)
    if hit is None:
        hit = _heredoc_hit(text, owned, surface, env, cwd, depth)
    if hit is None:
        hit = _quoted_hit(commands, owned, surface, rules, depth=depth, plain=plain)
    return hit


def _quoted_hit(
    commands: list[tuple[_Simple, _Simple | None]],
    owned: _Owned,
    surface: GuardrailSurface,
    rules: _Rules,
    *,
    depth: int,
    plain: tuple[str, ...] | None,
) -> GuardrailHit | None:
    """A configuration write written as words a shell does not run as one.

    A shell does not run a quoted argument, but the text may still be run
    later (written to a script, passed to ``ssh``, kept in an alias). So the
    text of every word that holds a blank and names a writer's program or
    verb is read again as commands, and so on inside it. There, and among
    the words of the command text itself, a writer's program word, or the
    verb such a rule also matches after an unknown program (``config``),
    starts a match wherever it stands: ``printf %s hermes config edit`` is
    a change, as in the 0.5.0 guard. This reading can only add a match. The
    exact plain command a rule exempts (see ``except_exact``) stays exempt.

    Each word that may start a match costs the words after it in its
    command, spent from the recognition's one word budget, so the cost stays
    linear. A text that runs out of budget is reported as too long to
    inspect. Each level of quoting adds one to ``depth``; quoted text
    deeper than ``_MAX_QUOTE_DEPTH`` is reported as too deep.
    """
    work = owned.work
    pending = [(commands, depth)]
    while pending:
        parsed, level = pending.pop()
        exempt = plain if level == depth else None
        for command, spelled in parsed:
            for words in (command.argv,) if spelled is None else (command.argv, spelled.argv):
                for index, word in enumerate(words):
                    if words is command.argv and _names_writer(word, rules):
                        if level >= _MAX_QUOTE_DEPTH:
                            return GuardrailHit("settings", _TOO_DEEP)
                        pending.append((_spelled(word), level + 1))
                    starts = _writer_starts(words, index, surface, rules)
                    if not starts:
                        continue
                    if not work.spend_words(len(words) - index - 1):
                        return GuardrailHit("settings", _TOO_LONG)
                    for start in starts:
                        hit = _writer_at(words, index, start, surface, rules, exempt)
                        if hit is not None:
                            return hit
    return None


def _names_writer(word: str, rules: _Rules) -> bool:
    """True when ``word`` holds a blank and a writer's program, alias, module or verb."""
    if not any(blank in word for blank in _BLANKS):
        return False
    folded = word.casefold()
    return any(name in folded for name in rules.names)


def _writer_starts(
    words: tuple[str, ...], index: int, surface: GuardrailSurface, rules: _Rules
) -> tuple[str, ...]:
    """How a writer may start at ``words[index]``: ``"verb"``, ``"program"``, both or neither.

    A word that is both a verb and a writer's program is read both ways.
    """
    word = words[index]
    folded = word.casefold()
    starts = ("verb",) if folded in rules.verbs else ()
    return (*starts, "program") if _starts_program(words, index, surface, rules) else starts


def _starts_program(
    words: tuple[str, ...], index: int, surface: GuardrailSurface, rules: _Rules
) -> bool:
    word = words[index]
    # The name ``_invocation`` compares, then the program's own name.
    if word.casefold().replace("\\", "/").rsplit("/", 1)[-1] in rules.invoked:
        return True
    program = _program(word)
    if program in rules.writers:
        return True
    if program == "python":
        # Interpreter options come first; a few words are enough to find ``-m``.
        window = _invocation(words[index : index + 8], surface)
        return window[0] != word and _program(window[0]) in rules.writers
    return False


def _writer_at(
    words: tuple[str, ...],
    index: int,
    start: str,
    surface: GuardrailSurface,
    rules: _Rules,
    exempt: tuple[str, ...] | None,
) -> GuardrailHit | None:
    if start == "verb":
        standing: dict[str, tuple[tuple[str, ...], ...]] = {}
        for rule in rules.unknown_writers:
            if rule.except_exact and exempt == rule.except_exact:
                continue
            name = rule.words[0]
            if name not in standing:
                standing[name] = _readings((name, *words[index:]), surface)
            if any(_rule_matches(candidate, rule) for candidate in standing[name]):
                return GuardrailHit(rule.kind, rule.label)
        return None
    prepared = _invocation(words[index:], surface)
    readings = _readings(prepared, surface)
    for rule in rules.writers.get(_program(prepared[0]), ()):
        if rule.except_exact and exempt == rule.except_exact:
            continue
        if any(_rule_matches(candidate, rule) for candidate in readings):
            return GuardrailHit(rule.kind, rule.label)
    return None


def _each_command(
    commands: list[tuple[_Simple, _Simple | None]],
    owned: _Owned,
    surface: GuardrailSurface,
    rules: _Rules,
    env: Mapping[str, str],
    cwd: str,
    *,
    depth: int,
    plain: tuple[str, ...] | None = None,
) -> GuardrailHit | None:
    """Judge commands in order. A ``cd`` moves the directory the later ones run in.

    A command's Windows-path spelling (see ``_spelled``) is checked for what
    it names, not for what it runs, so it adds no nested work.
    """
    for command, spelled in commands:
        hit = _one_command(command, owned, surface, rules, env, cwd, depth=depth, plain=plain)
        if hit is None and spelled is not None:
            hit = _one_command(
                spelled,
                owned,
                surface,
                rules,
                env,
                cwd,
                depth=depth,
                plain=plain,
                checks_only=True,
            )
        if hit is not None:
            return hit
        moved = _after_cd(command, owned, env, cwd)
        if moved is None:
            return GuardrailHit("settings", _UNREADABLE)
        cwd = moved
        if owned.work.spent:
            return GuardrailHit("settings", _TOO_LONG)
    return None


def _after_cd(
    command: _Simple, owned: _Owned, env: Mapping[str, str], cwd: str, *, native: bool = False
) -> str | None:
    """The working directory after ``command``, when it is a ``cd``.

    On Windows a relative directory has two readings. Git Bash's own ``cd``
    takes the shell's, and ``cd`` inside a PowerShell or cmd script
    (``native``) takes the system's. Working out the directory spends the
    recognition's path budget; the caller reports a spent budget. ``None``
    means the system could not work the directory out (see ``_Unreadable``).
    """
    argv, _assignments = _strip_wrappers(command.argv)
    if not argv or _program(argv[0]) not in {"cd", "pushd"}:
        return cwd
    targets = _operands(argv)
    if not targets:
        return env.get("HOME") or cwd
    if len(targets) != 1 or targets[0] == "-":
        return cwd
    if not owned.work.spend_path(len(targets[0]) + len(cwd)):
        return cwd
    try:
        readings = _expand_path(targets[0], env, cwd, hedge=False)
    except _Unreadable:
        return None
    return readings[0] if native else readings[-1]


def _heredoc_hit(
    text: str,
    owned: _Owned,
    surface: GuardrailSurface,
    env: Mapping[str, str],
    cwd: str,
    depth: int = 0,
) -> GuardrailHit | None:
    """Program text handed to an interpreter as a here-document.

    The body's lines were already judged as shell commands, which is what a
    shell reading the document would run. This adds the reading for Python and
    the other interpreters, where a line is not a command.

    Every program on the opening line, in its shell reading and in its
    Windows-path spelling, adds the check for its language. Each check runs
    at most once and on its own, and a hit from any of them counts: the
    Python check removes comments, so finding Python on the line must not
    take the place of the check for another interpreter. The body read as
    a program is one level deeper than ``text``; past the limit a body left
    unread is reported as too deep to inspect.
    """
    for line, body in _heredocs(text):
        pairs = _spelled(line)
        checks: set[str] = set()
        for commands in ([s for s, _ in pairs], [d or s for s, d in pairs]):
            programs = set()
            for command in commands:
                argv, _assignments = _strip_wrappers(command.argv)
                if argv:
                    programs.add(_program(argv[0]))
            if "python" in programs:
                checks.add("python")
            if programs & _INTERPRETERS:
                checks.add("names")
        if checks and depth >= _MAX_DEPTH and body.strip():
            return GuardrailHit("settings", _TOO_DEEP)
        hit = None
        if "python" in checks:
            hit = _judge_code(body, owned, surface, env, cwd, depth=depth + 1)
        if hit is None and "names" in checks:
            hit = _code_names_path(body, owned, env, cwd)
        if hit is not None:
            return hit
    return None


def _one_command(
    command: _Simple,
    owned: _Owned,
    surface: GuardrailSurface,
    rules: _Rules,
    env: Mapping[str, str],
    cwd: str,
    *,
    depth: int,
    known_program: bool = False,
    plain: tuple[str, ...] | None = None,
    checks_only: bool = False,
) -> GuardrailHit | None:
    """The first guardrail change ``command`` makes.

    ``checks_only`` judges what the command names (its program, rules, flags,
    paths and redirects, and a command it starts) without entering a script
    or program text it carries.

    ``depth`` counts the steps into nested text that led here, one for each
    (see ``_MAX_DEPTH``). A command at the limit is still judged by what it
    names, and a command it starts one level further; a script it carries
    is not read, and is reported as too deep to inspect.
    """
    written, assignments = _strip_wrappers(command.argv)
    prepared = _invocation(written, surface)
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
    readings = _readings(prepared, surface)
    unknown = (
        not known_program
        and program not in _KNOWN_PROGRAMS
        and _native_shell(prepared[0]) is None
        and program not in rules.by_program
        and program not in rules.flag_programs
    )
    # An unknown program word is read as each rule's own program, options and all.
    standing: dict[str, tuple[tuple[str, ...], ...]] = {}
    for command_rule in rules.unknown if unknown else rules.by_program.get(program, ()):
        if helping and command_rule.help_clears:
            continue
        if command_rule.except_exact and plain == command_rule.except_exact:
            continue
        candidates = readings
        if unknown:
            name = command_rule.words[0]
            if name not in standing:
                standing[name] = _readings((name, *prepared[1:]), surface)
            candidates = standing[name]
        if any(_rule_matches(candidate, command_rule) for candidate in candidates):
            return GuardrailHit(command_rule.kind, command_rule.label)
    if helping:
        # Nothing else that changes a guardrail runs, but a redirect still writes.
        hit = _mutation((), command.redirects, owned, env, cwd)
        return hit or _as_written(written, program, owned, env, cwd)
    exported = _export_hit(prepared, surface)
    if exported is not None:
        return exported
    module = _python_module(prepared) if program == "python" else None
    # The word after ``-m`` is a module name, not a file.
    acted = (prepared[0], *module[1:]) if module else prepared
    hit = _mutation(acted, command.redirects, owned, env, cwd)
    hit = hit or _as_written(written, program, owned, env, cwd)
    if hit is not None:
        return hit
    if checks_only or depth >= _MAX_DEPTH:
        return _at_limit(
            prepared, program, module, owned, surface, rules, env, cwd, depth, checks_only
        )
    found: GuardrailHit | None = None
    if program == "python":
        script = _c_argument(prepared)
        if script is not None:
            found = _judge_code(script, owned, surface, env, cwd, depth=depth + 1)
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
            found = _native(script, shell, owned, surface, rules, env, cwd, depth + 1)
    if found is not None or program in _TEXT_ONLY or program in _READERS:
        return found
    return _started(prepared, owned, surface, rules, env, cwd, depth)


def _as_written(
    argv: tuple[str, ...], program: str, owned: _Owned, env: Mapping[str, str], cwd: str
) -> GuardrailHit | None:
    """The operand check of ``argv``'s program word as written, when it was read as ``program``.

    A host-declared alias, path or module form is judged as the host's
    program, whose operands may be verbs and names rather than files. The
    word as written keeps its own operand check too, which can only add a
    match: ``ai.hermes.exe --version name`` names the file ``name``.
    """
    if not argv or _program(argv[0]) == program:
        return None
    module = _python_module(argv) if _program(argv[0]) == "python" else None
    return _mutation((argv[0], *module[1:]) if module else argv, (), owned, env, cwd)


def _at_limit(
    argv: tuple[str, ...],
    program: str,
    module: tuple[str, ...] | None,
    owned: _Owned,
    surface: GuardrailSurface,
    rules: _Rules,
    env: Mapping[str, str],
    cwd: str,
    depth: int,
    checks_only: bool,
) -> GuardrailHit | None:
    """The rest of a command at the depth limit, or one judged only by what it names.

    Text this deep is not read. It is not allowed unread either: a script
    the command carries is reported as too deep, and so, past the limit, is
    a command it would start. A ``checks_only`` reading reports neither; the
    reading it accompanies has judged them.
    """
    if not checks_only and _carries_script(argv, program, module):
        return GuardrailHit("settings", _TOO_DEEP)
    if program in _TEXT_ONLY or program in _READERS:
        return None
    if depth > _MAX_DEPTH:
        if not checks_only and _start_indexes(argv, surface, rules) != (None, None):
            return GuardrailHit("settings", _TOO_DEEP)
        return None
    # The started command is judged one level further, without its scripts.
    return _started(
        argv, owned, surface, rules, env, cwd, max(depth, _MAX_DEPTH), checks_only=checks_only
    )


def _carries_script(argv: tuple[str, ...], program: str, module: tuple[str, ...] | None) -> bool:
    """True when ``argv`` hands text to a shell, ``eval`` or Python that is read as commands."""
    if (program in _SHELLS or program == "python") and _c_argument(argv) is not None:
        return True
    if program == "python" and module:
        return True
    if program == "eval":
        return len(argv) > 1
    shell = _native_shell(argv[0])
    return shell is not None and _native_script(shell, argv) is not None


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


def _carries(argv: tuple[str, ...], flag: str) -> bool:
    """True when ``flag`` is a word of its own or is written ``--flag=value``."""
    glued = flag + "=" if flag.startswith("--") else None
    return any(word == flag or (glued is not None and word.startswith(glued)) for word in argv[1:])


def _started(
    argv: tuple[str, ...],
    owned: _Owned,
    surface: GuardrailSurface,
    rules: _Rules,
    env: Mapping[str, str],
    cwd: str,
    depth: int,
    *,
    checks_only: bool = False,
) -> GuardrailHit | None:
    """A command that this one starts, such as ``timeout 5 hermes ...``.

    The rest of the line is judged again from the first later word that is a
    program the rules name, a wrapper, a shell, ``python`` or ``eval``. That
    pass comes first, so reading PowerShell and cmd never hides a command it
    would have found. Then it is judged from the first later PowerShell or
    cmd. Each word's path is worked out once for the whole line, so the
    second pass costs little. The started command is one level deeper.
    """
    # A pass that ran out of depth is reported only when the other finds nothing.
    deep: GuardrailHit | None = None
    for index in _start_indexes(argv, surface, rules):
        if index is None:
            continue
        rest = _Simple(argv[index:], (), ())
        hit = _one_command(
            rest, owned, surface, rules, env, cwd, depth=depth + 1, checks_only=checks_only
        )
        if hit is not None and hit.target == _TOO_DEEP:
            deep = deep or hit
        elif hit is not None:
            return hit
    return deep


def _start_indexes(
    argv: tuple[str, ...], surface: GuardrailSurface, rules: _Rules
) -> tuple[int | None, int | None]:
    """Where ``_started`` starts again: the first later starter, then native shell."""
    starters = rules.starters
    first = next(
        (
            i
            for i in range(1, len(argv))
            if _program(_invocation((argv[i],), surface)[0]) in starters
        ),
        None,
    )
    native = next((i for i in range(1, len(argv)) if _native_shell(argv[i]) is not None), None)
    return first, native


def _nested(
    script: str,
    owned: _Owned,
    surface: GuardrailSurface,
    rules: _Rules,
    env: Mapping[str, str],
    cwd: str,
    depth: int,
) -> GuardrailHit | None:
    """A script handed to a shell or ``eval``, one level deeper than ``depth``.

    Its commands are judged in order, and a here-document in it is read as
    the program its opening line feeds, as in the command text itself.
    """
    hit = _each_command(_spelled(script), owned, surface, rules, env, cwd, depth=depth + 1)
    return hit or _heredoc_hit(script, owned, surface, env, cwd, depth + 1)


def _native(
    script: str,
    shell: str,
    owned: _Owned,
    surface: GuardrailSurface,
    rules: _Rules,
    env: Mapping[str, str],
    cwd: str,
    depth: int,
) -> GuardrailHit | None:
    """A script given to PowerShell or cmd, judged command by command.

    ``depth`` is the script's own depth. A reader of that shell is judged by
    its redirects only. ``Invoke-Expression`` is PowerShell's ``eval``; the
    text it runs is one level deeper, and is reported as too deep to inspect
    past the limit. Whether every later command in a pipeline only reads is
    worked out once per pipeline, from its end.
    """
    for pipeline in _native_parse(script, shell, env):
        passive = _passive_after(shell, pipeline)
        for index, (command, plain) in enumerate(pipeline):
            argv = command.argv
            if plain and _native_reads(shell, argv, passive[index + 1]):
                hit = _mutation((), command.redirects, owned, env, cwd)
            else:
                hit = _one_command(command, owned, surface, rules, env, cwd, depth=depth)
            evaluates = (
                shell != "cmd" and bool(argv) and _program(argv[0]) in {"iex", "invoke-expression"}
            )
            if hit is None and evaluates and len(argv) > 1:
                if depth >= _MAX_DEPTH:
                    return GuardrailHit("settings", _TOO_DEEP)
                rest = " ".join(argv[1:])
                hit = _native(rest, shell, owned, surface, rules, env, cwd, depth + 1)
            if hit is not None:
                return hit
            moved = _after_cd(command, owned, env, cwd, native=True)
            if moved is None:
                return GuardrailHit("settings", _UNREADABLE)
            cwd = moved
            if owned.work.spent:
                return GuardrailHit("settings", _TOO_LONG)
    return None


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
    *,
    depth: int = 0,
) -> GuardrailHit | None:
    """Embedded shell commands, then any protected path the program text names.

    Comments are removed first. A ``#`` outside a string starts a comment;
    one inside a string does not. See :func:`_strip_python_comments`.
    ``depth`` is the program text's own depth; a command written inside it
    is one level deeper, and is reported as too deep to inspect past the
    limit. Program text itself past the limit is not read.
    """
    if depth > _MAX_DEPTH and text.strip():
        return GuardrailHit("settings", _TOO_DEEP)
    visible = _strip_python_comments(text)
    for piece in _embedded(visible):
        if depth >= _MAX_DEPTH:
            return GuardrailHit("settings", _TOO_DEEP)
        hit = _command_change(piece, owned, surface, env, cwd, depth=depth + 1)
        if hit is not None:
            return hit
    return _code_names_path(visible, owned, env, cwd)
