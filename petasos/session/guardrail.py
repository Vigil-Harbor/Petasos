"""Recognise a tool call that would change a guardrail.

The guard stays host-agnostic. A host supplies the paths and the command
patterns that belong to it. Petasos's own package files and its own commands
are recognised here. A shell command that names a protected path is a change
unless the program is a plain reader and is used as one. A redirect into a
protected path is always a change. A path that only appears inside text the
command writes somewhere else is not.

Program text (``execute_code``, ``python``, and ``python -c``) is not read as
a shell line. Embedded commands are judged as shell, and any protected path
the text names is a change. Python is not treated as read-only.

Recognition is the plain forms and the cheap disguises: quotes joined inside
a word, a backslash before an ordinary character, an environment-variable
prefix, ``sh -c``, a relative path, ``~``, ``$HERMES_HOME``, and commands
chained with ``&&``, ``||``, ``;`` or ``|``. It is not a sandbox. Encoded
payloads, aliases, command substitution, and a path assembled at runtime
from separate pieces are not matched.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_READ_TOOLS = frozenset(
    {
        "file_read",
        "read",
        "read_file",
        "read_terminal",
        "search_files",
        "vision_analyze",
        "web_extract",
        "web_search",
    }
)
_COMMAND_TOOLS = frozenset(
    {
        "bash",
        "exec",
        "execute_code",
        "python",
        "shell",
        "sh",
        "terminal",
    }
)
_PATH_KEYS = frozenset(
    {
        "dest",
        "destination",
        "dir",
        "directory",
        "file",
        "file_path",
        "filename",
        "filepath",
        "new_path",
        "old_path",
        "path",
        "source",
        "src",
        "target",
    }
)
_COMMAND_KEYS = frozenset({"cmd", "code", "command", "input", "script"})
_WRITE_TOOLS = frozenset(
    {
        "chmod",
        "create_file",
        "delete_file",
        "edit_file",
        "file_write",
        "move_file",
        "patch",
        "write",
        "write_file",
    }
)
# A shell program is a reader only when it is used as one. Anything else that
# names a protected path fails closed and asks. ``rg`` is included as a grep.
_READERS = frozenset(
    {
        "[",
        "b2sum",
        "bzgrep",
        "cat",
        "cksum",
        "cmp",
        "diff",
        "egrep",
        "fgrep",
        "file",
        "find",
        "grep",
        "head",
        "jq",
        "less",
        "ls",
        "md5",
        "md5sum",
        "more",
        "readlink",
        "realpath",
        "rg",
        "rgrep",
        "sha1sum",
        "sha224sum",
        "sha256sum",
        "sha384sum",
        "sha512sum",
        "shasum",
        "stat",
        "sum",
        "tail",
        "test",
        "wc",
        "xzgrep",
        "yq",
        "zegrep",
        "zfgrep",
        "zgrep",
    }
)
_IN_PLACE = frozenset({"-i", "--in-place", "--inplace"})
_FIND_WRITES = frozenset(
    {
        "-delete",
        "-exec",
        "-execdir",
        "-fls",
        "-fprint",
        "-fprint0",
        "-fprintf",
        "-ok",
        "-okdir",
    }
)
# Last positional is the path written, unless ``-t`` names it. A protected
# source with an unprotected destination is a read. ``install`` and ``ln``
# have that same shape. ``rsync --remove-source-files`` deletes the source.
_COPIES = frozenset({"cp", "install", "ln", "rsync", "scp"})
_COPY_DEST_FLAGS = frozenset({"-t", "--target-directory"})
_CODE_TOOLS = frozenset({"execute_code", "python"})
# PowerShell read cmdlets. A write cmdlet in the same command is not a read.
_PS_READS = frozenset(
    {
        "gc",
        "gci",
        "get-childitem",
        "get-content",
        "get-filehash",
        "get-item",
        "gi",
        "resolve-path",
        "select-string",
        "sls",
        "test-path",
    }
)
_PS_WRITES = frozenset(
    {
        "ac",
        "add-content",
        "clear-content",
        "clc",
        "copy-item",
        "del",
        "erase",
        "move-item",
        "new-item",
        "out-file",
        "rd",
        "remove-item",
        "rename-item",
        "ri",
        "rmdir",
        "sc",
        "set-content",
        "set-item",
    }
)
# Arguments are text or a number, never a file the program opens.
_TEXT_ONLY = frozenset(
    {
        ":",
        "basename",
        "dirname",
        "echo",
        "expr",
        "false",
        "printf",
        "pwd",
        "seq",
        "sleep",
        "true",
        "uname",
        "uptime",
        "whoami",
        "yes",
    }
)
_HELP_FLAGS = frozenset({"-h", "--help"})
_READ_MODES = frozenset({"r", "rb", "rt"})
_PATH_READ_METHODS = frozenset({"read_text", "read_bytes", "exists", "is_file", "stat"})
_SHELLS = frozenset({"ash", "bash", "dash", "ksh", "sh", "zsh"})
_WRAPPERS = frozenset({"command", "env", "nice", "nohup", "sudo", "time"})
_ALL_NAMES = frozenset({"*", "--all", "-a", "all"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_MAX_CHARS = 100_000
_MAX_COMMANDS = 64
_SYSTEM_CALL = re.compile(
    r"""(?:os\.system|os\.popen|subprocess\.(?:run|call|check_call|check_output|Popen|getoutput|getstatusoutput))\s*\(\s*(['"])(?P<body>(?:\\.|(?!\1).)*)\1""",
    re.DOTALL,
)
_ARGV_LIST = re.compile(
    r"""(?P<head>.{0,80})\[(?P<body>(?:\s*['"][^'"]+['"]\s*,?)+)\]""",
    re.DOTALL,
)
_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")

_KINDS = frozenset({"settings", "plugin", "package", "record"})


@dataclass(frozen=True, slots=True)
class CommandRule:
    """One host command that changes a guardrail.

    ``words`` is the program and the verbs, in order. ``name``, when set, must
    appear later in the command, or the command must name everything
    (``--all``, ``-a``, ``all``, ``*``). The program is compared by its file
    name, so a path to ``hermes`` still matches.
    """

    kind: str
    words: tuple[str, ...]
    label: str
    name: str | None = None
    tail: str | None = None
    # Match when no later word names a target. ``hermes plugins update``
    # with no name updates every plugin.
    bare: bool = False
    # The next positional word must be one of these (``auto-update on``).
    one_of: tuple[str, ...] = ()
    requires_flag: str | None = None
    unless_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"unknown guardrail kind {self.kind!r}")
        if not self.words or not self.label.strip():
            raise ValueError("a command rule needs words and a label")


@dataclass(frozen=True, slots=True)
class FlagRule:
    """A flag that changes a guardrail when the named program carries it."""

    kind: str
    program: str
    flag: str
    label: str


@dataclass(frozen=True, slots=True)
class EnvRule:
    """An environment assignment that changes a guardrail when it is turned on."""

    kind: str
    name: str
    label: str
    # When set, any assigned value counts, not only a turned-on one.
    any_value: bool = False
    # A prefix assignment counts only when this program is what runs.
    # An ``export`` of the name still counts.
    program: str | None = None


@dataclass(frozen=True, slots=True)
class GuardrailSurface:
    """What the host adds to the library's own recognition.

    ``paths`` maps a kind to filesystem paths. ``commands``, ``flags`` and
    ``env`` are the host's own command forms. An empty surface leaves the
    library's package files and commands in force, and any protected paths the
    caller passes are still checked.
    """

    paths: Mapping[str, frozenset[str]] = field(default_factory=dict)
    commands: tuple[CommandRule, ...] = ()
    flags: tuple[FlagRule, ...] = ()
    env: tuple[EnvRule, ...] = ()
    command_tools: frozenset[str] = field(default_factory=lambda: _COMMAND_TOOLS)


@dataclass(frozen=True, slots=True)
class GuardrailHit:
    """One recognised change. ``target`` is a short display form, not contents."""

    kind: str
    target: str


@dataclass(frozen=True, slots=True)
class _Simple:
    argv: tuple[str, ...]
    redirects: tuple[str, ...]
    assignments: tuple[tuple[str, str], ...]


def normalize_path_text(text: str) -> str:
    """The guard's path comparison: unicode escapes, slashes, then a resolved absolute path.

    A relative path is not resolved. That is the comparison the existing
    self-modification check uses, and this function stays identical to it.
    """
    cleaned = re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), text)
    cleaned = cleaned.replace("\\\\", "/").replace("\\", "/").replace("/", os.sep)
    cleaned = os.path.normcase(cleaned)
    try:
        path = Path(cleaned)
        if path.is_absolute():
            cleaned = os.path.normcase(str(path.resolve(strict=False)))
    except (OSError, ValueError):
        pass
    return cleaned


def library_rules() -> tuple[CommandRule, ...]:
    """Commands that change Petasos itself. They are not host-specific."""
    settings = (
        ("petasos", "config", "migrate", "petasos config migrate"),
        ("petasos", "config", "set", "petasos config set"),
        ("petasos", "config", "unset", "petasos config unset"),
        ("petasos", "config", "edit", "petasos config edit"),
        ("hermes", "petasos", "config", "migrate", "hermes petasos config migrate"),
        ("hermes", "petasos", "config", "set", "hermes petasos config set"),
        ("hermes", "petasos", "config", "unset", "hermes petasos config unset"),
        ("hermes", "petasos", "config", "edit", "hermes petasos config edit"),
    )
    scanners = (
        ("petasos", "scanner", "add", "petasos scanner add"),
        ("petasos", "scanner", "remove", "petasos scanner remove"),
        ("hermes", "petasos", "scanner", "add", "hermes petasos scanner add"),
        ("hermes", "petasos", "scanner", "remove", "hermes petasos scanner remove"),
    )
    plugin = (
        ("petasos", "hermes", "install", "petasos hermes install"),
        ("petasos", "hermes", "pin", "petasos hermes pin"),
        ("petasos", "hermes", "unpin", "petasos hermes unpin"),
        ("hermes", "petasos", "install", "hermes petasos install"),
        ("hermes", "petasos", "pin", "hermes petasos pin"),
        ("hermes", "petasos", "unpin", "hermes petasos unpin"),
    )
    rules: list[CommandRule] = []
    for item in settings:
        *words, label = item
        rules.append(CommandRule("settings", tuple(words), label))
    for item in scanners:
        *words, label = item
        rules.append(CommandRule("settings", tuple(words), label))
    for item in plugin:
        *words, label = item
        rules.append(CommandRule("plugin", tuple(words), label))
    for program in ("pip", "uv"):
        pip_words = ("uv", "pip", "uninstall") if program == "uv" else ("pip", "uninstall")
        install = ("uv", "pip", "install") if program == "uv" else ("pip", "install")
        rules.append(
            CommandRule("package", pip_words, " ".join(pip_words) + " petasos", name="petasos")
        )
        rules.append(
            CommandRule("package", install, " ".join(install) + " petasos", name="petasos")
        )
    return tuple(rules)


def package_roots() -> frozenset[str]:
    """The installed Petasos package directory, resolved the way paths are compared."""
    root = Path(__file__).resolve().parent.parent
    try:
        resolved = os.path.normcase(str(root.resolve(strict=False)))
    except OSError:
        resolved = os.path.normcase(str(root))
    return frozenset({resolved})


def recognize(
    tool: str,
    params: Mapping[str, object],
    *,
    protected: Iterable[str] = (),
    surface: GuardrailSurface | None = None,
    package: Iterable[str] | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: str | None = None,
) -> GuardrailHit | None:
    """The first guardrail change in ``params``, or ``None``.

    ``protected`` is the host's path set, used when ``surface`` does not label
    a path. A labelled path keeps its label. ``package`` defaults to the
    installed package directory.
    """
    if _program(tool) in _READ_TOOLS or tool in _READ_TOOLS:
        return None
    host = surface if surface is not None else GuardrailSurface()
    env = os.environ if environ is None else environ
    work = os.getcwd() if cwd is None else cwd
    owned = _owned(protected, host, package if package is not None else package_roots())
    if _is_code_tool(tool):
        for text in _command_texts(params):
            hit = _judge_code(text, owned, host, env, work)
            if hit is not None:
                return hit
        return None
    path_hit = _path_change(tool, params, owned, env, work, host.command_tools)
    if path_hit is not None:
        return path_hit
    if _program(tool) not in host.command_tools and tool not in host.command_tools:
        return None
    for text in _command_texts(params):
        hit = _command_change(text, owned, host, env, work)
        if hit is not None:
            return hit
    return None


def _owned(
    protected: Iterable[str],
    surface: GuardrailSurface,
    package: Iterable[str],
) -> dict[str, str]:
    """Normalised path to its kind. A later label does not hide an earlier one."""
    found: dict[str, str] = {}
    for raw in package:
        key = normalize_path_text(str(raw))
        found.setdefault(key, "package")
    for raw in protected:
        key = normalize_path_text(str(raw))
        found.setdefault(key, _infer_kind(key))
    for kind, paths in surface.paths.items():
        if kind not in _KINDS:
            continue
        for raw in paths:
            found[normalize_path_text(str(raw))] = kind
    return found


def _infer_kind(path: str) -> str:
    name = Path(path).name.casefold()
    parts = [part.casefold() for part in Path(path).parts]
    if name in {"config.yaml", ".env"}:
        return "settings"
    if "petasos-enforcement" in name or name.endswith(".jsonl") or name.endswith(".jsonl.rot"):
        return "record"
    if name == "active_profile" or "plugins" in parts:
        return "plugin"
    return "settings"


def _path_change(
    tool: str,
    params: Mapping[str, object],
    owned: Mapping[str, str],
    env: Mapping[str, str],
    cwd: str,
    command_tools: frozenset[str],
) -> GuardrailHit | None:
    if _program(tool) in command_tools or tool in command_tools:
        return None
    keys = _PATH_KEYS if _program(tool) not in _WRITE_TOOLS else _PATH_KEYS
    for key, value in params.items():
        if key not in keys or not isinstance(value, str):
            continue
        hit = _match_path(value, owned, env, cwd)
        if hit is not None:
            return hit
    return None


def _match_path(
    raw: str, owned: Mapping[str, str], env: Mapping[str, str], cwd: str
) -> GuardrailHit | None:
    for candidate in _expand_path(raw, env, cwd):
        located = _kind_of(candidate, owned)
        if located is None:
            continue
        kind, entry = located
        return GuardrailHit(kind, entry)
    return None


def _kind_of(candidate: str, owned: Mapping[str, str]) -> tuple[str, str] | None:
    direct = owned.get(candidate)
    if direct is not None:
        return direct, candidate
    for entry, kind in owned.items():
        prefix = entry if entry.endswith(os.sep) else entry + os.sep
        if candidate.startswith(prefix):
            return kind, candidate
    return None


def _expand_path(raw: str, env: Mapping[str, str], cwd: str) -> list[str]:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    text = _expand_vars(text, env)
    if text == "~" or text.startswith("~/"):
        home = env.get("HOME", "")
        if home:
            text = str(Path(home) / text[2:]) if text.startswith("~/") else home
        else:
            text = os.path.expanduser(text)
    elif text.startswith("~"):
        text = os.path.expanduser(text)
    bases = [text]
    if not os.path.isabs(text):
        bases = [os.path.join(cwd, text)]
        for key in ("HERMES_HOME", "HOME"):
            root = env.get(key, "")
            if root:
                bases.append(os.path.join(root, text))
    return [normalize_path_text(item) for item in bases]


def _expand_vars(text: str, env: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        return env.get(name, match.group(0))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", replace, text)


def _command_texts(params: Mapping[str, object]) -> list[str]:
    texts: list[str] = []
    for key, value in params.items():
        if key not in _COMMAND_KEYS:
            continue
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
            texts.append(" ".join(value))
    return texts


def _command_change(
    text: str,
    owned: Mapping[str, str],
    surface: GuardrailSurface,
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS]
    rules = library_rules() + surface.commands
    for command in _parse(text)[:_MAX_COMMANDS]:
        hit = _one_command(command, owned, surface, rules, env, cwd, depth=0)
        if hit is not None:
            return hit
    return None


def _one_command(
    command: _Simple,
    owned: Mapping[str, str],
    surface: GuardrailSurface,
    rules: tuple[CommandRule, ...],
    env: Mapping[str, str],
    cwd: str,
    *,
    depth: int,
) -> GuardrailHit | None:
    prepared, assignments = _strip_wrappers(command.argv)
    program = _program(prepared[0]) if prepared else ""
    if program in {"hermes", "petasos"} and _HELP_FLAGS.intersection(prepared):
        return None
    for name, value in (*command.assignments, *assignments):
        hit = _env_hit(name, value, surface.env, program=program or None, exporting=False)
        if hit is not None:
            return hit
    if not prepared:
        return None
    program = _program(prepared[0])
    for flag in surface.flags:
        if program == flag.program.casefold() and flag.flag in prepared[1:]:
            return GuardrailHit(flag.kind, flag.label)
    for command_rule in rules:
        if _rule_matches(prepared, command_rule):
            return GuardrailHit(command_rule.kind, command_rule.label)
    exported = _export_hit(prepared, surface)
    if exported is not None:
        return exported
    hit = _mutation(prepared, command.redirects, owned, env, cwd)
    if hit is not None:
        return hit
    if program == "python" and depth < 3:
        script = _c_argument(prepared)
        if script is not None:
            found = _judge_code(script, owned, surface, env, cwd)
            if found is not None:
                return found
        if len(prepared) >= 3 and prepared[1] == "-m":
            rewritten = (prepared[2], *prepared[3:])
            return _one_command(
                _Simple(rewritten, command.redirects, ()),
                owned,
                surface,
                rules,
                env,
                cwd,
                depth=depth + 1,
            )
        return None
    if program in _SHELLS and depth < 3:
        script = _c_argument(prepared)
        if script is not None:
            found = _nested(script, owned, surface, rules, env, cwd, depth)
            if found is not None:
                return found
    return None


def _nested(
    script: str,
    owned: Mapping[str, str],
    surface: GuardrailSurface,
    rules: tuple[CommandRule, ...],
    env: Mapping[str, str],
    cwd: str,
    depth: int,
) -> GuardrailHit | None:
    for nested in _parse(script)[:_MAX_COMMANDS]:
        found = _one_command(nested, owned, surface, rules, env, cwd, depth=depth + 1)
        if found is not None:
            return found
    return None


def _strip_wrappers(
    argv: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    assignments: list[tuple[str, str]] = []
    words = list(argv)
    while words:
        name, value, consumed = _assignment(words[0])
        if consumed:
            if name is not None and value is not None:
                assignments.append((name, value))
            words = words[1:]
            continue
        program = _program(words[0])
        if program not in _WRAPPERS:
            break
        words = words[1:]
        while words and words[0].startswith("-") and words[0] != "-c":
            flag = words.pop(0)
            if program == "sudo" and flag in {"-u", "-g"} and words:
                words.pop(0)
            if program == "nice" and flag == "-n" and words:
                words.pop(0)
    return tuple(words), tuple(assignments)


def _assignment(word: str) -> tuple[str | None, str | None, bool]:
    if not word or word.startswith("-") or "=" not in word:
        return None, None, False
    name, value = word.split("=", 1)
    if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return None, None, False
    return name, value, True


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
    """True when ``word`` names the plugin, everything, or a source for it."""
    folded = word.casefold()
    wanted = name.casefold()
    if folded == wanted or folded in _ALL_NAMES:
        return True
    if "#" in word and word.rsplit("#", 1)[-1].strip("/").casefold() == wanted:
        return True
    return folded.rstrip("/").rsplit("/", 1)[-1] == wanted


def _mutation(
    argv: tuple[str, ...],
    redirects: tuple[str, ...],
    owned: Mapping[str, str],
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    """A protected path this command acts on, unless the program only reads it."""
    for target in redirects:
        hit = _match_path(target, owned, env, cwd)
        if hit is not None:
            return hit
    if not argv:
        return None
    program = _program(argv[0])
    if program in _TEXT_ONLY or _powershell_reads(program, argv):
        return None
    if program == "dd":
        return _dd_hit(argv, owned, env, cwd)
    if program in _COPIES:
        return _copy_hit(argv, owned, env, cwd)
    if _reads(program, argv):
        return None
    for word in _operands(argv):
        hit = _operand_path(word, owned, env, cwd)
        if hit is not None:
            return hit
    return _match_path(argv[0], owned, env, cwd)


def _powershell_reads(program: str, argv: tuple[str, ...]) -> bool:
    """True when ``powershell`` or ``pwsh`` is only running a read cmdlet."""
    name = program[:-4] if program.endswith(".exe") else program
    if name not in {"powershell", "pwsh"}:
        return False
    words = [word.casefold() for word in argv[1:]]
    if any(word in _PS_WRITES for word in words):
        return False
    return any(word in _PS_READS for word in words)


def _reads(program: str, argv: tuple[str, ...]) -> bool:
    """True when ``program`` is on the reader list and this invocation only reads."""
    if program not in _READERS:
        return False
    if program in {"jq", "yq"} and _in_place(argv):
        return False
    writing = program == "find" and any(word in _FIND_WRITES for word in argv[1:])
    return not writing


def _in_place(argv: tuple[str, ...]) -> bool:
    for word in argv[1:]:
        if word in _IN_PLACE or word.startswith("--in-place=") or word.startswith("--inplace="):
            return True
    return False


def _dd_hit(
    argv: tuple[str, ...],
    owned: Mapping[str, str],
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    """``of=`` writes. ``if=`` only reads."""
    for word in argv[1:]:
        if word.startswith("of="):
            hit = _match_path(word[3:], owned, env, cwd)
            if hit is not None:
                return hit
    return None


def _copy_hit(
    argv: tuple[str, ...],
    owned: Mapping[str, str],
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    """A read only when every protected path is a source and the destination is not."""
    destination, sources, removes_source = _copy_ends(argv)
    if destination:
        hit = _match_path(destination, owned, env, cwd)
        if hit is not None:
            return hit
    if removes_source:
        for source in sources:
            hit = _match_path(source, owned, env, cwd)
            if hit is not None:
                return hit
    if not destination:
        for source in sources:
            hit = _match_path(source, owned, env, cwd)
            if hit is not None:
                return hit
    return None


def _copy_ends(argv: tuple[str, ...]) -> tuple[str | None, list[str], bool]:
    """Destination, sources, and whether the source is deleted afterwards."""
    positionals: list[str] = []
    destination: str | None = None
    removes_source = False
    index = 1
    while index < len(argv):
        word = argv[index]
        if word == "--":
            positionals.extend(argv[index + 1 :])
            break
        if word == "--remove-source-files":
            removes_source = True
            index += 1
            continue
        if word.startswith("--") and "=" in word:
            flag, value = word.split("=", 1)
            if flag in _COPY_DEST_FLAGS:
                destination = value
            index += 1
            continue
        if word in _COPY_DEST_FLAGS and index + 1 < len(argv):
            destination = argv[index + 1]
            index += 2
            continue
        if word.startswith("-"):
            index += 1
            continue
        positionals.append(word)
        index += 1
    if destination is None and positionals:
        destination = positionals[-1]
        positionals = positionals[:-1]
    return destination, positionals, removes_source


def _operands(argv: tuple[str, ...]) -> list[str]:
    """Words the program receives, skipping flags. ``--`` ends the flags."""
    words: list[str] = []
    index = 1
    while index < len(argv):
        word = argv[index]
        if word == "--":
            words.extend(argv[index + 1 :])
            break
        if word.startswith("-"):
            bound = _bound_path(word)
            if bound:
                words.append(bound)
            index += 1
            continue
        words.append(word)
        index += 1
    return words


def _bound_path(word: str) -> str | None:
    """The path glued to an option (``--output=path``, ``-o/path``), if any."""
    if word.startswith("--") and "=" in word:
        return word.split("=", 1)[1]
    if word.startswith("-") and not word.startswith("--") and len(word) > 2:
        rest = word[2:]
        return rest[1:] if rest.startswith("=") else rest
    return None


def _operand_path(
    word: str,
    owned: Mapping[str, str],
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    """The word itself when it is a protected path. Text that merely contains one is not."""
    return _match_path(word, owned, env, cwd)


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


def _is_code_tool(tool: str) -> bool:
    return _program(tool) in _CODE_TOOLS or tool in _CODE_TOOLS


def _judge_code(
    text: str,
    owned: Mapping[str, str],
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


_QUOTED_STRING = re.compile(r"""(?s)(?:'''(.*?)'''|\"\"\"(.*?)\"\"\"|'([^']*)'|\"([^\"]*)\")""")
# An absolute path, a ~/path, or a $VAR/path. The prefix is optional so
# ``/tmp/config.yaml`` matches, not only ``~/tmp`` and ``//tmp``.
_BARE_PATH = re.compile(r"""(?:~|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)?(?:/[^\s'\"`,;)\]}<>]+)+""")
_HOME_JOIN = re.compile(r"""(?:pathlib\.)?Path\.home\(\)((?:\s*/\s*(['"])([^'"]+)\2)+)""")
_EXPANDUSER = re.compile(r"""(?:os\.path\.)?expanduser\(\s*(['"])([^'"]+)\1\s*\)""")
_ENV_LOOKUP = re.compile(
    r"""(?:os\.environ\[\s*(['"])([A-Za-z_][A-Za-z0-9_]*)\1\s*\]"""
    r"""|os\.environ\.get\(\s*(['"])([A-Za-z_][A-Za-z0-9_]*)\3\s*\)"""
    r"""|os\.getenv\(\s*(['"])([A-Za-z_][A-Za-z0-9_]*)\5\s*\))"""
)
_JOINED = re.compile(r"""\s*(?:\+|/)\s*(['"])([^'"]+)\1""")
_JOIN_HEAD = re.compile(
    r"""os\.path\.join\(\s*(?P<head>"""
    r"""os\.environ\[\s*(['"])(?P<var>[A-Za-z_][A-Za-z0-9_]*)\2\s*\]"""
    r"""|os\.environ\.get\(\s*(['"])(?P<var2>[A-Za-z_][A-Za-z0-9_]*)\4\s*\)"""
    r"""|os\.getenv\(\s*(['"])(?P<var3>[A-Za-z_][A-Za-z0-9_]*)\6\s*\)"""
    r"""|(?:pathlib\.)?Path\.home\(\)"""
    r"""|(?:os\.path\.)?expanduser\(\s*(['"])~(?P<tilde>[^'"]*)\8\s*\)"""
    r""")"""
)
_JOIN_PART = re.compile(r"""\s*,\s*(['"])([^'"]+)\1""")
_JOIN_END = re.compile(r"""\s*\)""")


def _strip_python_comments(code: str) -> str:
    """Drop comments. A ``#`` inside a string stays; one outside runs to the line end.

    Strings are ``'...'``, ``"..."``, and the triple-quoted forms, including a
    ``r``/``b``/``f``/``u`` prefix. A backslash keeps the next character inside
    a non-triple string, so ``"foo\\" # "`` does not end the string at the
    escaped quote. Approximate: an unclosed string swallows the rest of the
    text, and a backslash-newline line continuation is not joined.
    """
    out: list[str] = []
    index = 0
    length = len(code)
    while index < length:
        if code[index] in {"'", '"'}:
            end = _string_end(code, index)
            out.append(code[index:end])
            index = end
            continue
        if code[index] == "#":
            while index < length and code[index] != "\n":
                index += 1
            continue
        out.append(code[index])
        index += 1
    return "".join(out)


def _string_end(code: str, start: int) -> int:
    """Index just after the string that begins at ``start``, or the text length."""
    if code.startswith(("'''", '"""'), start):
        quote = code[start : start + 3]
        end = code.find(quote, start + 3)
        return len(code) if end < 0 else end + 3
    quote = code[start]
    index = start + 1
    length = len(code)
    while index < length:
        if code[index] == "\\" and index + 1 < length:
            index += 2
            continue
        if code[index] == quote:
            return index + 1
        index += 1
    return length


def _code_names_path(
    code: str,
    owned: Mapping[str, str],
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    """A protected path in ``code`` that is not only a plain read.

    A plain read is ``open`` with no mode or a literal ``r``/``rb``/``rt``, or
    ``Path``/``pathlib.Path`` followed directly by ``read_text``, ``read_bytes``,
    ``exists``, ``is_file`` or ``stat``. Any other use is a change. A path
    built in a variable and used later is still not visible.
    """
    occurrences = _protected_uses(code, owned, env, cwd)
    for start, end, hit in occurrences:
        if not _is_plain_code_read(code, start, end):
            return hit
    return None


def _is_plain_code_read(code: str, start: int, end: int) -> bool:
    prefix = code[:start]
    if re.search(r"(?:\bopen)\s*\(\s*$", prefix) and _open_tail_is_read(code[end:]):
        return True
    if re.search(r"(?:\bpathlib\.Path|\bPath)\s*\(\s*$", prefix):
        rest = code[end:].lstrip()
        method = "|".join(sorted(_PATH_READ_METHODS))
        if re.match(rf"\)\s*\.(?:{method})\s*\(", rest):
            return True
    return False


def _open_tail_is_read(rest: str) -> bool:
    """True when what follows the path is no mode, or a literal read mode."""
    body = rest.lstrip()
    if body.startswith(")"):
        return True
    match = re.match(r""",\s*(?:(['"])([^'"]*)\1\s*)?\)""", body)
    if match is None:
        return False
    mode = match.group(2)
    return mode is None or mode in _READ_MODES


def _protected_uses(
    code: str,
    owned: Mapping[str, str],
    env: Mapping[str, str],
    cwd: str,
) -> list[tuple[int, int, GuardrailHit]]:
    """Each protected path use as ``(start, end, hit)``. A use inside another is dropped."""
    found: list[tuple[int, int, GuardrailHit]] = []
    quoted: list[tuple[int, int]] = []
    for match in _QUOTED_STRING.finditer(code):
        quoted.append(match.span())
        text = next((group for group in match.groups() if group is not None), "")
        hit = _match_path(text, owned, env, cwd) if text else None
        if hit is not None:
            found.append((match.start(), match.end(), hit))
    for match in _BARE_PATH.finditer(code):
        start, end = match.span()
        if any(left <= start and end <= right for left, right in quoted):
            continue
        hit = _match_path(match.group(0), owned, env, cwd)
        if hit is not None:
            found.append((start, end, hit))
    found.extend(_expression_uses(code, owned, env, cwd))
    return _outer_uses(found)


def _expression_uses(
    code: str,
    owned: Mapping[str, str],
    env: Mapping[str, str],
    cwd: str,
) -> list[tuple[int, int, GuardrailHit]]:
    """Path expressions (``expanduser``, ``Path.home``, env joins) with their spans."""
    found: list[tuple[int, int, GuardrailHit]] = []
    for match in _EXPANDUSER.finditer(code):
        hit = _match_path(match.group(2), owned, env, cwd)
        if hit is not None:
            found.append((match.start(), match.end(), hit))
    home = env.get("HOME", "")
    for match in _HOME_JOIN.finditer(code):
        if not home:
            continue
        parts = re.findall(r"""['"]([^'"]+)['"]""", match.group(1))
        hit = _match_path(str(Path(home, *parts)), owned, env, cwd)
        if hit is not None:
            found.append((match.start(), match.end(), hit))
    for match in _ENV_LOOKUP.finditer(code):
        var = next((group for group in match.groups()[1::2] if group), "")
        root = env.get(var, "")
        if not root:
            continue
        built = root
        cursor = match.end()
        last: tuple[int, GuardrailHit] | None = None
        while True:
            piece = _JOINED.match(code, cursor)
            if piece is None:
                break
            part = piece.group(2)
            if "+" in piece.group(0):
                built += part
            else:
                built = str(Path(built) / part)
            hit = _match_path(built, owned, env, cwd)
            cursor = piece.end()
            if hit is not None:
                last = (cursor, hit)
        if last is not None:
            found.append((match.start(), last[0], last[1]))
    for match in _JOIN_HEAD.finditer(code):
        root = _join_root(match, env)
        if not root:
            continue
        segments: list[str] = []
        cursor = match.end()
        while True:
            piece = _JOIN_PART.match(code, cursor)
            if piece is None:
                break
            segments.append(piece.group(2))
            cursor = piece.end()
        closing = _JOIN_END.match(code, cursor)
        if closing is None:
            continue
        hit = _match_path(str(Path(root, *segments)), owned, env, cwd)
        if hit is not None:
            found.append((match.start(), closing.end(), hit))
    return found


def _outer_uses(
    found: list[tuple[int, int, GuardrailHit]],
) -> list[tuple[int, int, GuardrailHit]]:
    """Drop a use that sits strictly inside another, so the outer call is judged."""
    kept: list[tuple[int, int, GuardrailHit]] = []
    for index, (start, end, hit) in enumerate(found):
        inner = False
        for other, (left, right, _other) in enumerate(found):
            if other == index:
                continue
            if left <= start and end <= right and (left < start or end < right):
                inner = True
                break
        if not inner:
            kept.append((start, end, hit))
    return kept


def _join_root(match: re.Match[str], env: Mapping[str, str]) -> str:
    head = match.group("head")
    if "Path.home" in head:
        return env.get("HOME", "")
    if "expanduser" in head:
        home = env.get("HOME", "")
        tilde = match.group("tilde") or ""
        return str(Path(home) / tilde) if home else ""
    var = match.group("var") or match.group("var2") or match.group("var3") or ""
    return env.get(var, "")


def _embedded(script: str) -> list[str]:
    found = [match.group("body") for match in _SYSTEM_CALL.finditer(script)]
    for match in _ARGV_LIST.finditer(script):
        head = match.group("head")
        if not any(token in head for token in ("subprocess", "os.exec", "Popen", "execv")):
            continue
        words = _QUOTED.findall(match.group("body"))
        if words:
            found.append(" ".join(words))
    return found


def _program(token: str) -> str:
    base = os.path.basename(_expand_vars(token, {})).casefold()
    if base.startswith("pip"):
        return "pip"
    if base.startswith("python"):
        return "python"
    return base


def _parse(text: str) -> list[_Simple]:
    commands: list[_Simple] = []
    words: list[str] = []
    redirects: list[str] = []
    buf: list[str] = []
    quote = ""
    redirect = False
    index = 0
    length = len(text)

    def finish_word() -> None:
        nonlocal redirect
        if not buf and not quote:
            return
        word = "".join(buf)
        buf.clear()
        if redirect:
            redirects.append(word)
            redirect = False
            return
        words.append(word)

    def finish_command() -> None:
        nonlocal redirect
        finish_word()
        if words or redirects:
            assignments, argv = _leading_assignments(words)
            commands.append(_Simple(tuple(argv), tuple(redirects), tuple(assignments)))
        words.clear()
        redirects.clear()
        redirect = False

    while index < length and len(commands) < _MAX_COMMANDS:
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
                index += 1
                continue
            if quote == '"' and char == "\\" and index + 1 < length:
                buf.append(text[index + 1])
                index += 2
                continue
            buf.append(char)
            index += 1
            continue
        if char == "\\" and index + 1 < length:
            nxt = text[index + 1]
            if nxt != "\n":
                buf.append(nxt)
            index += 2
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char in {" ", "\t"}:
            finish_word()
            index += 1
            continue
        if char == "\n":
            finish_command()
            index += 1
            continue
        if text.startswith("&&", index) or text.startswith("||", index):
            finish_command()
            index += 2
            continue
        if char in {";", "|"}:
            finish_command()
            index += 1
            continue
        if char in {">", "<"}:
            finish_word()
            while index < length and text[index] in {">", "<", "&", "|"}:
                index += 1
            redirect = char == ">"
            continue
        buf.append(char)
        index += 1
    if quote:
        finish_word()
    finish_command()
    return commands


def _leading_assignments(
    words: list[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    assignments: list[tuple[str, str]] = []
    index = 0
    while index < len(words):
        name, value, consumed = _assignment(words[index])
        if not consumed or name is None or value is None:
            break
        assignments.append((name, value))
        index += 1
    return assignments, words[index:]
