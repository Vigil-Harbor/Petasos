"""Read protected paths and embedded commands in program text."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from petasos.guard.paths import _match_path, _Owned
from petasos.guard.shell_parse import _program

if TYPE_CHECKING:
    from collections.abc import Mapping

    from petasos.guard.surface import GuardrailHit


_CODE_TOOLS = frozenset({"execute_code", "python"})
_READ_MODES = frozenset({"r", "rb", "rt"})
_PATH_READ_METHODS = frozenset({"read_text", "read_bytes", "exists", "is_file", "stat"})
_SYSTEM_CALL = re.compile(
    r"""(?:os\.system|os\.popen|subprocess\.(?:run|call|check_call|check_output|Popen|getoutput|getstatusoutput))\s*\(\s*(['"])(?P<body>(?:\\.|(?!\1).)*)\1""",
    re.DOTALL,
)
_ARGV_LIST = re.compile(
    r"""(?P<head>.{0,80})\[(?P<body>(?:\s*['"][^'"]+['"]\s*,?)+)\]""",
    re.DOTALL,
)
_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")


def _is_code_tool(tool: str) -> bool:
    return _program(tool) in _CODE_TOOLS or tool in _CODE_TOOLS


_QUOTED_STRING = re.compile(r"""(?s)(?:'''(.*?)'''|\"\"\"(.*?)\"\"\"|'([^']*)'|\"([^\"]*)\")""")
# An absolute path, a ~/path, a $VAR/path, or on Windows a drive path such
# as C:/x. The prefix is optional so ``/tmp/config.yaml`` matches, not only
# ``~/tmp`` and ``//tmp``.
_DRIVE = r"|(?<![A-Za-z0-9_])[A-Za-z]:" if os.name == "nt" else ""
_BARE_PATH = re.compile(
    r"""(?:~|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?""" + _DRIVE + r""")?(?:/[^\s'\"`,;)\]}<>]+)+"""
)
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
# What follows a path given to ``open``: no mode, or a literal one.
_OPEN_TAIL = re.compile(r"""\s*(?:\)|,\s*(?:(['"])([^'"]*)\1\s*)?\))""")
_PATH_READ_TAIL = re.compile(r"\s*\)\s*\.(?:" + "|".join(sorted(_PATH_READ_METHODS)) + r")\s*\(")


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
    owned: _Owned,
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
    """True when the use at ``start:end`` is the argument of a plain read.

    Only the text next to the use is looked at, so each use costs the
    length of the call around it, not of the whole program.
    """
    called = _call_before(code, start).rsplit(".", 1)[-1]
    if called == "open":
        tail = _OPEN_TAIL.match(code, end)
        return tail is not None and (tail.group(2) is None or tail.group(2) in _READ_MODES)
    if called == "Path":
        return _PATH_READ_TAIL.match(code, end) is not None
    return False


def _call_before(code: str, start: int) -> str:
    """The dotted name whose call bracket opens just before ``start``, or ``""``."""
    index = start
    while index > 0 and code[index - 1].isspace():
        index -= 1
    if index == 0 or code[index - 1] != "(":
        return ""
    index -= 1
    while index > 0 and code[index - 1].isspace():
        index -= 1
    end = index
    while index > 0 and (code[index - 1].isalnum() or code[index - 1] in "_."):
        index -= 1
    return code[index:end]


def _protected_uses(
    code: str,
    owned: _Owned,
    env: Mapping[str, str],
    cwd: str,
) -> list[tuple[int, int, GuardrailHit]]:
    """Each protected path use as ``(start, end, hit)``, in source order.

    A use inside another is dropped. Quoted strings are found in order and do
    not overlap, so whether a bare path sits inside one is decided by walking
    both in step.
    """
    found: list[tuple[int, int, GuardrailHit]] = []
    quoted: list[tuple[int, int]] = []
    for match in _QUOTED_STRING.finditer(code):
        quoted.append(match.span())
        text = next((group for group in match.groups() if group is not None), "")
        hit = _match_path(text, owned, env, cwd) if text else None
        if hit is not None:
            found.append((match.start(), match.end(), hit))
    at = 0
    for match in _BARE_PATH.finditer(code):
        start, end = match.span()
        while at + 1 < len(quoted) and quoted[at + 1][0] <= start:
            at += 1
        if quoted and quoted[at][0] <= start and end <= quoted[at][1]:
            continue
        hit = _match_path(match.group(0), owned, env, cwd)
        if hit is not None:
            found.append((start, end, hit))
    found.extend(_expression_uses(code, owned, env, cwd))
    return _outer_uses(found)


def _expression_uses(
    code: str,
    owned: _Owned,
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
    """Drop a use that sits strictly inside another, so the outer call is judged.

    The uses are sorted by start, the longest first among those that start
    together, and then read once. A use is inside another when one that
    started earlier reaches at least as far, or one that starts with it
    reaches further. Equal spans are all kept.
    """
    ordered = sorted(found, key=lambda use: (use[0], -use[1]))
    kept: list[tuple[int, int, GuardrailHit]] = []
    # The furthest end of the uses that started before the current start.
    reach = -1
    group_start = -1
    group_end = -1
    for start, end, hit in ordered:
        if start != group_start:
            reach = max(reach, group_end)
            group_start, group_end = start, end
        if reach >= end or group_end > end:
            continue
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
