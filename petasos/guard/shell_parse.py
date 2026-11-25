"""Read shell words, redirects, and assignments."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

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
# What the shell's reading gives a meaning of its own outside quotes: a blank,
# a line break, a quote, another backslash, a separator or a redirect.
_SHELL_SPECIAL = frozenset(" \t\n'\"\\;|&()`<>")
_EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".com")
_HEREDOC_OPEN = re.compile(r"""<<-?[ \t]*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")


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
    # A word with no separator is its own base name on every system.
    plain = "/" not in token and "\\" not in token and ":" not in token
    base = (token if plain else os.path.basename(token)).casefold()
    # Windows runs "hermes.exe" and "hermes" as the same program. Elsewhere
    # the suffix is part of the name of some other program.
    if os.name == "nt" and base.endswith(_EXECUTABLE_SUFFIXES):
        base = base.rsplit(".", 1)[0]
    if base.startswith("pip"):
        return "pip"
    if base.startswith("python"):
        return "python"
    return base


def _spelled(text: str) -> list[tuple[_Simple, _Simple | None]]:
    """Each command as the shell reads it, with its Windows-path spelling when that differs.

    A shell drops an unquoted backslash, so ``C:\\Tools\\hermes.exe`` names
    ``C:Toolshermes.exe`` and ``C:/x/conf\\ig.yaml`` names ``C:/x/config.yaml``.
    The spelling keeps the separators of a drive-letter word, for a native
    path that reaches Windows without a shell, as program text's argument
    lists do. A folder name need not start with a letter, so a folder whose
    name starts with a dot (``C:\\Users\\x\\.hermes``) and a step up
    (``\\..``) are read as Windows reads them. Callers check it as well and
    keep any match: it may add a match, never remove one. A backslash
    before a character in ``_SHELL_SPECIAL`` is read as the shell reads it,
    so both parses hold the same commands and words in the same order.
    """
    shell = _parse(text)
    if "\\" not in text or ":" not in text:
        return [(command, None) for command in shell]
    spelled = _parse(text, drive_paths=True)
    if len(spelled) != len(shell):
        return [(command, None) for command in shell]
    return [(s, None if d == s else d) for s, d in zip(shell, spelled, strict=True)]


def _parse(text: str, *, drive_paths: bool = False) -> list[_Simple]:
    """Shell words, redirects and assignments, as a POSIX shell reads them.

    ``drive_paths`` keeps a backslash in a word that starts with a drive
    letter, unless the character after it is in ``_SHELL_SPECIAL``. Use it
    only through ``_spelled``.
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

    while index < length:
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
            # separators rather than joining its parts. The character after
            # a kept backslash is an ordinary one, which the loop adds to
            # the word on its next turn.
            if (
                drive_paths
                and len(buf) >= 2
                and buf[0].isalpha()
                and buf[1] == ":"
                and nxt not in _SHELL_SPECIAL
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
