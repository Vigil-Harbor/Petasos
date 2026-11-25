"""Read protected paths and embedded commands in program text."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from petasos.guard.bounds import _TOO_LONG, _UNREADABLE, _UNWORKED
from petasos.guard.paths import _match_path, _Owned
from petasos.guard.shell_parse import _program
from petasos.guard.surface import GuardrailHit

if TYPE_CHECKING:
    from collections.abc import Mapping


_CODE_TOOLS = frozenset({"execute_code", "python"})
_READ_MODES = frozenset({"r", "rb", "rt"})
_PATH_READ_METHODS = frozenset({"read_text", "read_bytes", "exists", "is_file", "stat"})
# The call and the quote that opens its first argument. The argument itself
# is found by ``_system_call_bodies``, which reads forward only.
_SYSTEM_CALL = re.compile(
    r"""(?:os\.system|os\.popen|subprocess\.(?:run|call|check_call|check_output|Popen|getoutput|getstatusoutput))\s*\(\s*(['"])"""
)
# Quoted words, with a comma or white space between them. Each branch starts
# with a different character, so a list with no closing bracket fails in
# time linear in its length.
_ARGV_LIST = re.compile(
    r"""(?P<head>.{0,80})\[(?P<body>\s*['"][^'"]+['"]"""
    r"""(?:\s*(?:,\s*)?['"][^'"]+['"])*\s*,?)\]""",
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
    if owned.work.spent:
        # A use whose path was not worked out may be anything; it is never a read.
        return GuardrailHit("settings", _TOO_LONG)
    for start, end, hit in occurrences:
        if hit.target in _UNWORKED or not _is_plain_code_read(code, start, end):
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

    A use inside another is dropped, but never one whose path was not worked
    out (too long to inspect, or a path the system could not read). Quoted
    strings are found in order and do not overlap, so whether a bare path
    sits inside one is decided by walking both in step.
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
    """Path expressions (``expanduser``, ``Path.home``, env joins) with their spans.

    The reading ends at the first path the budget cannot pay for, reported
    as too long to inspect.
    """
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
            cursor = piece.end()
            # Building the next prefix costs its length, charged first, so a
            # long chain runs the budget out instead of costing quadratic time.
            # The first exhaustion ends the reading.
            if not owned.work.spend_path(len(built) + len(part) + 1):
                found.append((match.start(), cursor, GuardrailHit("settings", _TOO_LONG)))
                return found
            built = built + part if "+" in piece.group(0) else str(Path(built) / part)
            hit = _match_path(built, owned, env, cwd)
            if hit is not None and hit.target == _TOO_LONG:
                found.append((match.start(), cursor, hit))
                return found
            if hit is not None and hit.target == _UNREADABLE:
                # Kept as it is, never replaced by a longer prefix. The budget
                # is not spent, so the reading goes on.
                found.append((match.start(), cursor, hit))
            elif hit is not None:
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
    reaches further. Equal spans are all kept, and so is every use whose
    path was not worked out (``_UNWORKED``), wherever it stands.
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
        if (reach >= end or group_end > end) and hit.target not in _UNWORKED:
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


def _system_call_bodies(script: str) -> list[str]:
    """The first quoted argument of each ``os.system``, ``os.popen`` or ``subprocess`` call.

    The argument runs to the first quote of its kind that no backslash
    escapes. With no such quote it runs to the last quote of its kind in the
    text, where any earlier one is escaped; that is what the pattern this
    replaces matched after backtracking, so no argument is lost. Each call
    is read forward once, and reading resumes after its argument, so the
    cost is linear in the length of the text.
    """
    last = {quote: script.rfind(quote) for quote in "'\""}
    found: list[str] = []
    at = 0
    while (call := _SYSTEM_CALL.search(script, at)) is not None:
        quote = call.group(1)
        start = at = call.end()
        if last[quote] < start:
            continue
        close = _unescaped(script, start, quote)
        if close < 0:
            close = last[quote]
        found.append(script[start:close])
        at = close + 1
    return found


def _unescaped(text: str, start: int, quote: str) -> int:
    """The index of the first ``quote`` at or after ``start`` no backslash escapes, or -1."""
    index = start
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\" and index + 1 < length:
            index += 2
        elif char == quote:
            return index
        else:
            index += 1
    return -1


def _embedded(script: str) -> list[str]:
    found = _system_call_bodies(script)
    for match in _ARGV_LIST.finditer(script):
        head = match.group("head")
        if not any(token in head for token in ("subprocess", "os.exec", "Popen", "execv")):
            continue
        words = _QUOTED.findall(match.group("body"))
        if words:
            found.append(" ".join(words))
    return found
