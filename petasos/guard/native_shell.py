"""Read a script handed to PowerShell or cmd as one argument.

On Windows Hermes runs every terminal command through Git Bash, and from
there an agent can start ``powershell -Command "..."`` or ``cmd /c "..."``.
The script is split into commands with that shell's own quoting rules, where
a backslash is an ordinary character. See docs/architecture/hermes-host-facts.md,
section 19.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from petasos.guard.mutations import _PS_READS
from petasos.guard.shell_parse import _program, _Simple

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


_NATIVE_SHELLS = frozenset({"cmd", "powershell", "pwsh"})
# PowerShell takes an en dash, an em dash and a horizontal bar as a dash.
_PS_DASHES = "-/–—―"
# Options that take a value: the full name and the shortest prefix accepted.
_PS_VALUED = (
    ("configurationname", "config"),
    ("custompipename", "cus"),
    ("executionpolicy", "ex"),
    ("inputformat", "in"),
    ("outputformat", "ou"),
    ("psconsolefile", "psc"),
    ("settingsfile", "settings"),
    ("version", "v"),
    ("windowstyle", "w"),
    ("workingdirectory", "wo"),
)
_PS_SINGLE = frozenset("'‘’‚‛")
_PS_DOUBLE = frozenset('"“”„')
_PS_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_PS_VARIABLE = re.compile(r"\$(?:\{env:([^}]+)\}|env:([A-Za-z0-9_]+)|(home)\b)", re.IGNORECASE)
_PS_BOUND = re.compile(r"(-[A-Za-z_][\w-]*:)(.+)", re.DOTALL)
_CMD_VARIABLE = re.compile(r"%([^%\s]+)%")
# Aliases and cmdlets that only read, beside the read cmdlets in ``_PS_READS``.
_PS_SCRIPT_READS = _PS_READS | frozenset(
    {
        "cat",
        "dir",
        "get-acl",
        "get-itemproperty",
        "gp",
        "join-path",
        "rvpa",
        "split-path",
        "type",
        "write-host",
        "write-output",
    }
)
# Cmdlets that take objects from a pipeline without acting on the path they carry.
_PS_PASSIVE = frozenset(
    {
        "?",
        "convertto-json",
        "format-list",
        "format-table",
        "format-wide",
        "fl",
        "ft",
        "fw",
        "group",
        "group-object",
        "measure",
        "measure-object",
        "oh",
        "out-default",
        "out-host",
        "out-null",
        "out-string",
        "select",
        "select-object",
        "sort",
        "sort-object",
        "where",
        "where-object",
    }
)
_CMD_READS = frozenset(
    {"chdir", "comp", "dir", "fc", "find", "findstr", "more", "tree", "type", "where"}
)

_Pipeline = list[tuple[_Simple, bool]]


def _native_shell(word: str) -> str | None:
    """``powershell``, ``pwsh`` or ``cmd`` when ``word`` starts one, with or without ``.exe``.

    The ``.exe`` form counts on every system: from WSL it starts the Windows shell.
    """
    name = _program(word).removesuffix(".exe")
    return name if name in _NATIVE_SHELLS else None


def _native_script(shell: str, argv: Sequence[str]) -> str | None:
    """The script ``argv`` hands to the shell, or ``None`` when it hands none that can be read."""
    if shell == "cmd":
        return _cmd_script(argv)
    return _powershell_script(argv, file_first=shell == "pwsh")


def _cmd_script(argv: Sequence[str]) -> str | None:
    """The words after ``/c``, ``/k`` or ``/r``. Git Bash users write ``//c``.

    cmd also reads text glued to the switch: ``/cdel x`` runs ``del x``.
    """
    for index, word in enumerate(argv[1:], start=1):
        key = word.lstrip("/")
        if key != word and key[:1].casefold() in {"c", "k", "r"}:
            return " ".join((key[1:], *argv[index + 1 :])).strip()
    return None


def _powershell_script(argv: Sequence[str], *, file_first: bool) -> str | None:
    """The words after ``-Command`` or any prefix of it, joined by spaces.

    Without ``-Command`` Windows PowerShell runs the first word that is not an
    option and the words after it as a command, and ``pwsh`` runs it as a
    file. ``-File`` and ``-EncodedCommand`` give no script text to read.
    """
    index = 1
    while index < len(argv):
        word = argv[index]
        if word[:1] not in _PS_DASHES or word == "-":
            if word == "-" or file_first:
                return None
            return " ".join(argv[index:])
        key = word[1:].casefold()
        if key and "command".startswith(key):
            return " ".join(argv[index + 1 :])
        if key and ("encodedcommand".startswith(key) or key == "ec" or "file".startswith(key)):
            return None
        if key in {"commandwithargs", "cwa"}:
            return argv[index + 1] if index + 1 < len(argv) else None
        valued = key in {"ep", "wd"} or any(
            name.startswith(key) and key.startswith(shortest) for name, shortest in _PS_VALUED
        )
        index += 2 if valued else 1
    return None


def _native_reads(
    shell: str, argv: tuple[str, ...], later: Sequence[tuple[_Simple, bool]]
) -> bool:
    """True when the program only reads, inside a script given to ``shell``.

    In PowerShell a reader whose objects go on to a cmdlet that is not a
    reader can hand that cmdlet the path (``Get-Item x | Remove-Item``).
    """
    program = _program(argv[0]) if argv else ""
    if shell == "cmd":
        return program in _CMD_READS
    if program not in _PS_SCRIPT_READS:
        return False
    for command, plain in later:
        name = _program(command.argv[0]) if command.argv else ""
        if not plain or name not in _PS_SCRIPT_READS | _PS_PASSIVE:
            return False
    return True


def _native_parse(text: str, shell: str, env: Mapping[str, str]) -> list[_Pipeline]:
    """Pipelines of ``(command, plain)``. ``plain`` is false when brackets were inside.

    A bracketed command can call a method on what it reads, as in
    ``(Get-Item x).Delete()``, so it is never taken as a plain read.
    """
    ps = shell != "cmd"
    singles = _PS_SINGLE if ps else frozenset()
    doubles = _PS_DOUBLE if ps else frozenset('"')
    if not ps:
        # cmd replaces %NAME% before it reads the line.
        text = _CMD_VARIABLE.sub(
            lambda match: _lookup(env, match.group(1)) or match.group(0), text
        )
    pipelines: list[_Pipeline] = [[]]
    words: list[str] = []
    redirects: list[str] = []
    buf: list[str] = []
    quote = ""
    started = False
    redirect = False
    plain = True
    index = 0
    length = len(text)

    def finish_word() -> None:
        nonlocal started, redirect
        if not started:
            return
        word = "".join(buf)
        buf.clear()
        started = False
        if redirect:
            redirects.append(_ps_home(word, env) if ps else word)
            redirect = False
            return
        if not ps and not words:
            word = word.removeprefix("@")
        bound = _PS_BOUND.fullmatch(word) if ps else None
        pieces = [bound.group(1), bound.group(2)] if bound else [word]
        words.extend(_ps_home(piece, env) if ps else piece for piece in pieces if piece)

    def finish_command(*, piped: bool) -> None:
        nonlocal plain, redirect
        finish_word()
        if words or redirects:
            pipelines[-1].append((_Simple(tuple(words), tuple(redirects), ()), plain))
        words.clear()
        redirects.clear()
        redirect = False
        plain = True
        if not piped and pipelines[-1]:
            pipelines.append([])

    while index < length:
        char = text[index]
        nxt = text[index + 1 : index + 2]
        if quote == "'":
            if char in singles:
                if nxt and nxt in singles:
                    buf.append("'")
                    index += 2
                    continue
                quote = ""
            else:
                buf.append(char)
            index += 1
            continue
        if quote == '"':
            if char in doubles:
                if ps and nxt and nxt in doubles:
                    buf.append('"')
                    index += 2
                    continue
                quote = ""
                index += 1
                continue
            if ps and char in {"`", "$"}:
                index = _ps_special(text, index, buf, env)
                continue
            buf.append(char)
            index += 1
            continue
        if ps and char in {"`", "$"}:
            started = True
            index = _ps_special(text, index, buf, env)
            continue
        if not ps and char == "^" and nxt:
            started = True
            if nxt != "\n":
                buf.append(nxt)
            index += 2
            continue
        if char in singles or char in doubles:
            quote = "'" if char in singles else '"'
            started = True
            index += 1
            continue
        if ps and text.startswith("<#", index):
            # A block comment ends at ``#>``, and what follows it still runs.
            finish_word()
            end = text.find("#>", index + 2)
            index = length if end < 0 else end + 2
            continue
        if ps and char == "#" and not started:
            while index < length and text[index] != "\n":
                index += 1
            continue
        if (
            char in " \t\r,"
            or (not ps and char in ";=")
            or (ps and char != "\n" and char.isspace())
        ):
            finish_word()
            index += 1
            continue
        if char in "()" or (ps and char in "{}"):
            finish_word()
            plain = False
            index += 1
            continue
        if text.startswith(("&&", "||"), index):
            finish_command(piped=False)
            index += 2
            continue
        if char == "|":
            finish_command(piped=True)
            index += 1
            continue
        if char in "\n&" or (ps and char == ";"):
            # In PowerShell a lone ``&`` is the call operator.
            finish_command(piped=False)
            index += 1
            continue
        if char in "<>":
            if "".join(buf).isdigit() or buf == ["*"]:
                # A stream number, as in ``2>`` or ``*>``.
                buf.clear()
                started = False
            finish_word()
            while index < length and text[index] in "<>&":
                index += 1
            redirect = char == ">"
            continue
        buf.append(char)
        started = True
        index += 1
    finish_command(piped=False)
    return [pipeline for pipeline in pipelines if pipeline]


def _ps_special(text: str, index: int, buf: list[str], env: Mapping[str, str]) -> int:
    """A backtick escape or an environment variable at ``index``. Returns the next index."""
    if text[index] == "`":
        nxt = text[index + 1 : index + 2]
        if nxt and nxt != "\n":
            buf.append(_PS_ESCAPES.get(nxt, nxt))
        return index + 2
    match = _PS_VARIABLE.match(text, index)
    if match is None:
        buf.append("$")
        return index + 1
    name = match.group(1) or match.group(2)
    if name:
        # PowerShell expands a variable that is not set to nothing.
        buf.append(_lookup(env, name) or "")
        return match.end()
    home = _home(env)
    buf.append(match.group(0) if home is None else home)
    return match.end()


def _ps_home(word: str, env: Mapping[str, str]) -> str:
    """``~`` at the start of a path is the user's home, as PowerShell's file provider reads it."""
    home = _home(env)
    if home is None or not (word == "~" or word.startswith(("~/", "~\\"))):
        return word
    return home + word[1:]


def _home(env: Mapping[str, str]) -> str | None:
    return _lookup(env, "USERPROFILE") or _lookup(env, "HOME")


def _lookup(env: Mapping[str, str], name: str) -> str | None:
    """An environment variable by name, ignoring case as Windows does."""
    if name in env:
        return env[name]
    folded = name.casefold()
    return next((value for key, value in env.items() if key.casefold() == folded), None)
