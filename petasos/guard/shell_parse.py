"""Read bounded shell words, redirects, and assignments."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from petasos.guard.bounds import _MAX_COMMANDS
from petasos.guard.paths import _expand_vars

# Programs and shell keywords that run the command written after them.
_WRAPPERS = frozenset(
    {
        "!",
        "builtin",
        "command",
        "do",
        "elif",
        "else",
        "env",
        "exec",
        "if",
        "nice",
        "nohup",
        "setsid",
        "stdbuf",
        "sudo",
        "then",
        "time",
        "timeout",
        "until",
        "while",
        "{",
    }
)
# A wrapper option that takes the next word as its value.
_WRAPPER_VALUES = {
    "env": frozenset({"-u", "-C"}),
    "nice": frozenset({"-n"}),
    "sudo": frozenset({"-u", "-g"}),
    "timeout": frozenset({"-s", "-k"}),
}


_DQ_ESCAPED = frozenset({"$", "`", '"', "\\", "\n"})
_EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".com")


@dataclass(frozen=True, slots=True)
class _Simple:
    argv: tuple[str, ...]
    redirects: tuple[str, ...]
    assignments: tuple[tuple[str, str], ...]


def _strip_wrappers(
    argv: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    assignments: list[tuple[str, str]] = []
    # An index, not a shorter copy per word: a long chain of wrappers stays linear.
    index = 0
    while index < len(argv):
        name, value, consumed = _assignment(argv[index])
        if consumed:
            if name is not None and value is not None:
                assignments.append((name, value))
            index += 1
            continue
        program = _program(argv[index])
        if program not in _WRAPPERS:
            break
        index += 1
        valued = _WRAPPER_VALUES.get(program, frozenset())
        while index < len(argv) and argv[index].startswith("-") and argv[index] != "-c":
            flag = argv[index]
            index += 1
            if flag in valued and index < len(argv):
                index += 1
        if program == "timeout" and index < len(argv):
            # The duration.
            index += 1
    return argv[index:], tuple(assignments)


def _assignment(word: str) -> tuple[str | None, str | None, bool]:
    if not word or word.startswith("-") or "=" not in word:
        return None, None, False
    name, value = word.split("=", 1)
    if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return None, None, False
    return name, value, True


def _program(token: str) -> str:
    base = os.path.basename(_expand_vars(token, {})).casefold()
    # Windows runs "hermes.exe" and "hermes" as the same program. Elsewhere
    # the suffix is part of the name of some other program.
    if os.name == "nt" and base.endswith(_EXECUTABLE_SUFFIXES):
        base = base.rsplit(".", 1)[0]
    if base.startswith("pip"):
        return "pip"
    if base.startswith("python"):
        return "python"
    return base


def _readings(text: str) -> tuple[list[_Simple], ...]:
    """The shell's reading of ``text``, then its Windows-path reading when that differs.

    A shell drops an unquoted backslash, so ``C:\\Tools\\hermes.exe`` names
    ``C:Toolshermes.exe`` and ``C:/x/conf\\ig.yaml`` names ``C:/x/config.yaml``.
    The second reading keeps the separators of a drive-letter word, for a
    pasted Windows path. Callers judge both and keep any match: the second
    reading may add a match, never remove one.
    """
    shell = _parse(text)
    if "\\" not in text or ":" not in text:
        return (shell,)
    windows = _parse(text, drive_paths=True)
    return (shell,) if windows == shell else (shell, windows)


def _parse(text: str, *, drive_paths: bool = False) -> list[_Simple]:
    """Shell words, redirects and assignments, as a POSIX shell reads them.

    ``drive_paths`` keeps a backslash before a letter or digit in a word that
    starts with a drive letter. Use it only through ``_readings``.
    """
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
            # Inside double quotes a backslash escapes only these characters.
            # Before anything else the shell keeps it, as in "C:\Users\name".
            if quote == '"' and char == "\\" and text[index + 1 : index + 2] in _DQ_ESCAPED:
                if text[index + 1] != "\n":
                    buf.append(text[index + 1])
                index += 2
                continue
            buf.append(char)
            index += 1
            continue
        if char == "\\" and index + 1 < length:
            nxt = text[index + 1]
            # The Windows-path reading of a pasted drive path keeps its
            # separators rather than joining its parts.
            if (
                drive_paths
                and len(buf) >= 2
                and buf[0].isalpha()
                and buf[1] == ":"
                and nxt.isalnum()
            ):
                buf.append(char)
                index += 1
                continue
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
        if char in {";", "|", "&", "(", ")", "`"}:
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
