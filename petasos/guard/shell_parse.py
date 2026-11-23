"""Read bounded shell words, redirects, and assignments."""

from __future__ import annotations

import bisect
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
_HEREDOC_OPEN = re.compile(r"""<<-?[ \t]*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")


@dataclass(frozen=True, slots=True)
class _Simple:
    argv: tuple[str, ...]
    redirects: tuple[str, ...]
    assignments: tuple[tuple[str, str], ...]
    # The command's text as written, from its first word to its end, without
    # surrounding blanks. Empty for a command this module did not read.
    source: str = ""
    # True only for a command of its own in a tool call's top-level shell
    # text: not inside a substitution, a subshell or a here-document, and not
    # read again from a script, ``eval``, an argument list or program code.
    direct: bool = False


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


def _file_name(word: str) -> str:
    """The last part of ``word`` as a path, by this host's separators."""
    return os.path.basename(word)


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


def _parse(text: str, *, top: bool = False) -> list[_Simple]:
    """Read ``text`` into simple commands.

    ``top`` says ``text`` is a tool call's own shell text. Only then may a
    command be marked direct, and only when separators that the shell reads
    between commands surround it (the start or end of the text, a newline,
    ``;``, ``&``, ``|``, ``&&`` or ``||``), no ``(``, ``$(`` or backquote is
    open around it and it does not start inside a here-document's body.
    """
    commands: list[_Simple] = []
    words: list[str] = []
    redirects: list[str] = []
    buf: list[str] = []
    quote = ""
    redirect = False
    index = 0
    length = len(text)
    # Where the current command's text begins, once it has a word or redirect.
    start: int | None = None
    # Open parentheses and backquote, and whether a separator came before
    # the current command.
    depth = 0
    backquote = False
    separated = True
    begins, ends = _heredoc_bodies(text) if top and "<<" in text else ([], [])

    def in_body(offset: int) -> bool:
        at = bisect.bisect_right(begins, offset) - 1
        return at >= 0 and offset < ends[at]

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

    def finish_command(*, separator: bool) -> None:
        nonlocal redirect, start, separated
        finish_word()
        if words or redirects:
            assignments, argv = _leading_assignments(words)
            source = text[start:index].strip() if start is not None else ""
            direct = (
                top
                and separated
                and separator
                and depth == 0
                and not backquote
                and start is not None
                and not in_body(start)
            )
            commands.append(
                _Simple(tuple(argv), tuple(redirects), tuple(assignments), source, direct)
            )
        words.clear()
        redirects.clear()
        redirect = False
        start = None
        separated = separator

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
        if start is None and char not in {" ", "\t", "\n", ";", "|", "&", "(", ")", "`"}:
            start = index
        if char == "\\" and index + 1 < length:
            nxt = text[index + 1]
            # A pasted Windows drive path is also a possible program word on
            # other hosts. Keep its separators rather than joining its parts.
            if len(buf) >= 2 and buf[0].isalpha() and buf[1] == ":" and nxt.isalnum():
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
            finish_command(separator=True)
            index += 1
            continue
        if text.startswith("&&", index) or text.startswith("||", index):
            finish_command(separator=True)
            index += 2
            continue
        if char in {";", "|", "&"}:
            finish_command(separator=True)
            index += 1
            continue
        if char in {"(", ")", "`"}:
            finish_command(separator=False)
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(depth - 1, 0)
            else:
                backquote = not backquote
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
    finish_command(separator=True)
    return commands


def _heredoc_bodies(text: str) -> tuple[list[int], list[int]]:
    """Where here-document bodies lie in ``text``: sorted begin and end offsets.

    Every opener line counts, with no bound on how many, and the bodies of
    several documents opened on one line are taken together. A body with no
    closing line runs to the end of the text. An opener the shell would not
    read, such as one inside quotes, only widens what is taken as a body.
    """
    lines = text.split("\n")
    offsets = [0]
    for line in lines[:-1]:
        offsets.append(offsets[-1] + len(line) + 1)
    begins: list[int] = []
    ends: list[int] = []
    index = 0
    while index < len(lines):
        tags = [opened.group(2) for opened in _HEREDOC_OPEN.finditer(lines[index])]
        if not tags:
            index += 1
            continue
        end = index
        for tag in tags:
            end += 1
            while end < len(lines) and lines[end].strip() != tag:
                end += 1
        if index + 1 < len(lines):
            begins.append(offsets[index + 1])
            ends.append(offsets[end] if end < len(lines) else len(text))
        index = end + 1
    return begins, ends


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
