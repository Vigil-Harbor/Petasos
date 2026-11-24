"""Recognize commands that change a guardrail."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from petasos.guard.bounds import _MAX_DEPTH, _MAX_QUOTE_DEPTH, _WORD_BUDGET
from petasos.guard.mutations import (
    _COPIES,
    _INTERPRETERS,
    _NAME_END,
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
from petasos.guard.paths import _expand_path, _Owned
from petasos.guard.program import _code_names_path, _embedded, _strip_python_comments
from petasos.guard.shell_parse import (
    _WRAPPERS,
    _assignment,
    _program,
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
_ALL_NAMES = frozenset({"*", "--all", "-a", "all"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})
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
_TOO_DEEP = "command nested too deeply to inspect"
_TOO_LONG = "command too long to inspect"
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
) -> GuardrailHit | None:
    """The first guardrail change ``text`` makes when a shell runs it.

    ``plain`` is the whole tool call's command text read as one plain
    command (see ``recognize``), or ``None``. Only a rule's ``except_exact``
    consults it.
    """
    rules = _index(library_rules() + surface.commands, surface)
    commands = _spelled(text)
    hit = _each_command(commands, owned, surface, rules, env, cwd, depth=0, plain=plain)
    if hit is None:
        hit = _heredoc_hit(text, owned, surface, env, cwd)
    if hit is None:
        hit = _quoted_hit(commands, surface, rules)
    return hit


def _quoted_hit(
    commands: list[tuple[_Simple, _Simple | None]],
    surface: GuardrailSurface,
    rules: _Rules,
) -> GuardrailHit | None:
    """A configuration write written inside a quoted word.

    A shell does not run a quoted argument, but the text may still be run
    later (written to a script, passed to ``ssh``, kept in an alias). So the
    text of every word that holds a blank and names a writer's program or
    verb is read again as commands, to any depth. There, a writer's program
    word, or the verb such a rule also matches after an unknown program
    (``config``), starts a match wherever it stands. This reading can only
    add a match.

    Each word that may start a match costs the words after it in its
    command, counted against one budget for the whole text, so the cost
    stays linear. Words in the command text itself are counted but not
    matched: the shell reading has judged them. A text that runs out of
    budget is reported as too long to inspect, and quoted text nested
    deeper than ``_MAX_QUOTE_DEPTH`` as too deep.
    """
    budget = _WORD_BUDGET
    pending = [(commands, 0)]
    while pending:
        parsed, depth = pending.pop()
        for command, spelled in parsed:
            for words in (command.argv,) if spelled is None else (command.argv, spelled.argv):
                for index, word in enumerate(words):
                    if words is command.argv and _names_writer(word, rules):
                        if depth == _MAX_QUOTE_DEPTH:
                            return GuardrailHit("settings", _TOO_DEEP)
                        pending.append((_spelled(word), depth + 1))
                    starts = _writer_starts(words, index, surface, rules)
                    if not starts:
                        continue
                    budget -= len(words) - index - 1
                    if budget < 0:
                        return GuardrailHit("settings", _TOO_LONG)
                    if depth == 0:
                        continue
                    for start in starts:
                        hit = _writer_at(words, index, start, surface, rules)
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
    words: tuple[str, ...], index: int, start: str, surface: GuardrailSurface, rules: _Rules
) -> GuardrailHit | None:
    if start == "verb":
        standing: dict[str, tuple[tuple[str, ...], ...]] = {}
        for rule in rules.unknown_writers:
            name = rule.words[0]
            if name not in standing:
                standing[name] = _readings((name, *words[index:]), surface)
            if any(_rule_matches(candidate, rule) for candidate in standing[name]):
                return GuardrailHit(rule.kind, rule.label)
        return None
    prepared = _invocation(words[index:], surface)
    readings = _readings(prepared, surface)
    for rule in rules.writers.get(_program(prepared[0]), ()):
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

    Every program on the opening line, in its shell reading and in its
    Windows-path spelling, adds the check for its language. Each check runs
    at most once and on its own, and a hit from any of them counts: the
    Python check removes comments, so finding Python on the line must not
    take the place of the check for another interpreter.
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
        hit = None
        if "python" in checks:
            hit = _judge_code(body, owned, surface, env, cwd)
        if hit is None and "names" in checks:
            hit = _code_names_path(body, owned, env, cwd)
        if hit is not None:
            return hit
    return None


def _heredocs(text: str) -> list[tuple[str, str]]:
    """The opening line and the body of each here-document.

    A document with no closing line runs to the end of the text.
    """
    lines = text.split("\n")
    found: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
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
    """
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
        return _mutation((), command.redirects, owned, env, cwd)
    exported = _export_hit(prepared, surface)
    if exported is not None:
        return exported
    module = _python_module(prepared) if program == "python" else None
    # The word after ``-m`` is a module name, not a file.
    acted = (prepared[0], *module[1:]) if module else prepared
    hit = _mutation(acted, command.redirects, owned, env, cwd)
    if hit is not None or depth > _MAX_DEPTH:
        return hit
    if checks_only or depth == _MAX_DEPTH:
        if depth == _MAX_DEPTH and not checks_only and _carries_script(prepared, program, module):
            # Text this deep is not read. It is not allowed unread either.
            return GuardrailHit("settings", _TOO_DEEP)
        if program in _TEXT_ONLY or program in _READERS:
            return None
        # Past the depth limit, the started command is judged without its scripts.
        return _started(prepared, owned, surface, rules, env, cwd, _MAX_DEPTH)
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
) -> GuardrailHit | None:
    """A command that this one starts, such as ``timeout 5 hermes ...``.

    The rest of the line is judged again from the first later word that is a
    program the rules name, a wrapper, a shell, ``python`` or ``eval``. That
    pass comes first, so reading PowerShell and cmd never hides a command it
    would have found. Then it is judged from the first later PowerShell or
    cmd. Each word's path is worked out once for the whole line, so the
    second pass costs little.
    """
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
    # A pass that ran out of depth is reported only when the other finds nothing.
    deep: GuardrailHit | None = None
    for index in (first, native):
        if index is None:
            continue
        rest = _Simple(argv[index:], (), ())
        hit = _one_command(rest, owned, surface, rules, env, cwd, depth=depth + 1)
        if hit is not None and hit.target == _TOO_DEEP:
            deep = deep or hit
        elif hit is not None:
            return hit
    return deep


def _nested(
    script: str,
    owned: _Owned,
    surface: GuardrailSurface,
    rules: _Rules,
    env: Mapping[str, str],
    cwd: str,
    depth: int,
) -> GuardrailHit | None:
    return _each_command(_spelled(script), owned, surface, rules, env, cwd, depth=depth + 1)


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

    A reader of that shell is judged by its redirects only. ``Invoke-Expression``
    is PowerShell's ``eval``. Whether every later command in a pipeline only
    reads is worked out once per pipeline, from its end.
    """
    for pipeline in _native_parse(script, shell, env):
        passive = _passive_after(shell, pipeline)
        for index, (command, plain) in enumerate(pipeline):
            argv = command.argv
            if plain and _native_reads(shell, argv, passive[index + 1]):
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
    """True when ``argv`` matches ``rule``. The caller has matched the program."""
    if len(argv) < len(rule.words):
        return False
    for index in range(1, len(rule.words)):
        if argv[index].casefold() != rule.words[index].casefold():
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
    for piece in (folded, folded.rstrip("/").rsplit("/", 1)[-1], *_repository(folded)):
        head = _NAME_END.split(piece, maxsplit=1)[0].removesuffix(".git")
        if head == wanted or re.match(re.escape(wanted) + r"-\d", head):
            return True
    return False


def _repository(source: str) -> tuple[str, str]:
    """The last part of a source's repository path, with its revision set aside.

    A revision follows the repository after ``@`` or ``#`` and may itself
    hold ``/`` (``.../petasos@feature/x``). The path starts after a URL's
    host or an scp-style ``host:``, so a user before the host is not taken
    for a revision. Both the first ``@`` or ``#`` in the path and pip's
    reading, the fragment and then the last ``@``, are tried.
    """
    scheme = source.find("://")
    if scheme >= 0:
        slash = source.find("/", scheme + 3)
        path = source[slash:] if slash >= 0 else ""
    else:
        colon, slash = source.find(":"), source.find("/")
        path = source[colon + 1 :] if colon >= 0 and (slash < 0 or colon < slash) else source
    first = re.split(r"[@#]", path, maxsplit=1)[0]
    last = path.split("#", 1)[0].rsplit("@", 1)[0]
    return first.rstrip("/").rsplit("/", 1)[-1], last.rstrip("/").rsplit("/", 1)[-1]


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
    visible = _strip_python_comments(text)
    for piece in _embedded(visible):
        hit = _command_change(piece, owned, surface, env, cwd)
        if hit is not None:
            return hit
    return _code_names_path(visible, owned, env, cwd)
