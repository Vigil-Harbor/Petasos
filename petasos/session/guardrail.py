"""Recognise a tool call that would change a guardrail.

The guard stays host-agnostic. A host supplies the paths and the command
patterns that belong to it. Petasos's own package files and its own commands
are recognised here. Reading a path is not a change. A command that only
mentions the words, or writes them into some other file, is not a change.

Recognition is the plain forms and the cheap disguises: quotes, an
environment-variable prefix, ``sh -c``, a relative path, ``~``, ``$HERMES_HOME``,
and commands chained with ``&&``, ``||``, ``;`` or ``|``. It is not a sandbox.
Encoded payloads, aliases, and commands built at runtime are not matched.
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
_MUTATE_ANY = frozenset(
    {
        "chmod",
        "chown",
        "chgrp",
        "rm",
        "rmdir",
        "shred",
        "truncate",
        "unlink",
    }
)
_MUTATE_BOTH = frozenset({"mv"})
_MUTATE_DEST = frozenset({"cp", "install", "ln", "tee"})
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
    for name, value in command.assignments:
        for rule in surface.env:
            if name == rule.name and value.strip().casefold() in _TRUTHY:
                return GuardrailHit(rule.kind, rule.label)
    prepared, assignments = _strip_wrappers(command.argv)
    for name, value in assignments:
        for rule in surface.env:
            if name == rule.name and value.strip().casefold() in _TRUTHY:
                return GuardrailHit(rule.kind, rule.label)
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
    if program in _SHELLS or program == "python":
        script = _c_argument(prepared)
        if script is not None and depth < 3:
            if program == "python":
                for piece in _embedded(script):
                    found = _nested(piece, owned, surface, rules, env, cwd, depth)
                    if found is not None:
                        return found
            found = _nested(script, owned, surface, rules, env, cwd, depth)
            if found is not None:
                return found
    if program == "python" and len(prepared) >= 3 and prepared[1] == "-m":
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
    if rule.tail is not None:
        if len(argv) <= len(rule.words):
            return False
        if not argv[len(rule.words)].casefold().startswith(rule.tail.casefold()):
            return False
    if rule.name is None:
        return True
    rest = [word.casefold() for word in argv[len(rule.words) :]]
    wanted = rule.name.casefold()
    return wanted in rest or any(word in _ALL_NAMES for word in rest)


def _mutation(
    argv: tuple[str, ...],
    redirects: tuple[str, ...],
    owned: Mapping[str, str],
    env: Mapping[str, str],
    cwd: str,
) -> GuardrailHit | None:
    for target in redirects:
        hit = _match_path(target, owned, env, cwd)
        if hit is not None:
            return hit
    if not argv:
        return None
    program = _program(argv[0])
    args = [word for word in argv[1:] if not word.startswith("-")]
    if program == "dd":
        for word in argv[1:]:
            if word.startswith("of="):
                hit = _match_path(word[3:], owned, env, cwd)
                if hit is not None:
                    return hit
        return None
    if program in _MUTATE_ANY or program in _MUTATE_BOTH:
        for word in args:
            hit = _match_path(word, owned, env, cwd)
            if hit is not None:
                return hit
        return None
    if program in _MUTATE_DEST and args:
        return _match_path(args[-1], owned, env, cwd)
    return None


def _export_hit(argv: tuple[str, ...], surface: GuardrailSurface) -> GuardrailHit | None:
    if not argv or _program(argv[0]) != "export":
        return None
    for word in argv[1:]:
        name, value, consumed = _assignment(word)
        if not consumed or name is None or value is None:
            continue
        if value.strip().casefold() not in _TRUTHY:
            continue
        for rule in surface.env:
            if name == rule.name:
                return GuardrailHit(rule.kind, rule.label)
    return None


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
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "\\" and index + 1 < length and text[index + 1] in {" ", "\t"}:
            buf.append(text[index + 1])
            index += 2
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
