"""Bounded content projection with original-character coordinates.

No tool name, action, caller filename or trust decision participates here.
JSON is walked without building an object tree. Maps use packed 32-bit arrays,
not one Python object per source character.
"""

from __future__ import annotations

import asyncio
import json
import re
from array import array
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from petasos._limits import MAX_PARAM_TEXT_LEN

if TYPE_CHECKING:
    from petasos._coverage import Projection

LANGUAGES = ("python", "javascript", "typescript")
_LABELS = {
    "py": "python",
    "python": "python",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
}
_IDENTIFIER_RUN = re.compile(r"(?<![\w.$])([\w.$]++)([\s\ufeff]*+)(\(|/\*|//)")
_IDENTIFIER_START = re.compile(r"\b[A-Za-z_$]")
_SENSITIVE_END = re.compile(r"\b(?:eval|exec|Function)$")
# An explicit line continuation joins a callee to its arguments: eval \<newline>(x).
_CONTINUATION = re.compile(r"\\\r?\n")
# A call whose callee is itself an expression: (eval)(x), table[0](x), f()(x).
# One line break is allowed because JavaScript and bracketed Python continue there.
_EXPRESSION_CALL = re.compile(r"[)\]][ \t\ufeff]*+(?:\\?\r?\n[ \t\ufeff]*+)?\(")
_DECLARATION = re.compile(
    r"(?m:^[ \t]*(?:from[ \t]+\S+[ \t]+import|import|class|def|async[ \t]+def"
    r"|function|const|let|var)\b)"
)
_FENCE = re.compile(r"(?m)^ {0,3}(`{3,}+|~{3,}+)([^\r\n]*+)\r?$")
_DEF_PREFIX = re.compile(r"(?:async +)?def +[A-Za-z_]\w*+\s*+\(")
_CLASS_PREFIX = re.compile(r"class +[A-Za-z_]\w*+")
_RETURN_ANNOTATION = re.compile(r"\)\s*+->")
_LINE = re.compile(r"[^\n]*\n|[^\n]+$")
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_ESCAPE = re.compile(r"\\(?:u[0-9a-fA-F]{4}|[\"\\/bfnrt])")


def _is_candidate(text: str) -> bool:
    """Visit each maximal identifier once, never retry at every dotted segment."""
    if _DECLARATION.search(text):
        return True
    if "(" not in text and "/*" not in text and "//" not in text:
        return False
    if "\\" in text:
        text = _CONTINUATION.sub(" ", text)
    if _EXPRESSION_CALL.search(text):
        return True
    for run in _IDENTIFIER_RUN.finditer(text):
        token = run[1]
        start = _IDENTIFIER_START.search(token)
        if start is None:
            continue
        if run.start(2) == run.end(2) and run[3] == "(":
            return True
        dot = token.find(".", start.start())
        dotted = start.start() < dot < len(token) - 1
        if dotted or _SENSITIVE_END.search(token):
            return True
    return False


def _is_header(text: str) -> bool:
    """Recognize the existing declaration shape with disjoint linear scans."""
    if not text.endswith(":"):
        return False
    end = len(text) - 1
    prefix = _DEF_PREFIX.match(text)
    if prefix is not None:
        start = prefix.end()
        closing = len(text[:end].rstrip()) - 1
        if closing >= start and text[closing] == ")" and "\n" not in text[start:closing]:
            return True
        # A return annotation cannot contain ':'. Only consider suffixes after
        # the final interior colon, so repeated )-> fragments are never retried.
        after_colon = text.rfind(":", start, end) + 1
        annotation = _RETURN_ANNOTATION.search(text, max(start, after_colon), end)
        return (
            annotation is not None
            and annotation.end() < end
            and "\n" not in text[start : annotation.start()]
        )
    prefix = _CLASS_PREFIX.match(text)
    if prefix is None:
        return False
    tail = text[prefix.end() : end]
    if not tail.strip():
        return True
    tail = tail.rstrip()
    return tail.startswith("(") and tail.endswith(")") and "\n" not in tail


_NOT_PATH = frozenset("()[]{};=\"'`")


def _is_search_header(text: str) -> bool:
    # Headers are dropped from the selected source, so anything that could be
    # code (calls, statements, strings) disqualifies the whole presentation.
    return (
        bool(text)
        and not text[0].isspace()
        and "\r" not in text
        and "\n" not in text
        and any(text.find(separator, 1) >= 0 for separator in (".", "/", "\\"))
        and _NOT_PATH.isdisjoint(text)
        and not _is_candidate(text)
    )


def _scan_string(text: str, start: int, strict: bool) -> tuple[str, int]:
    return cast("tuple[str, int]", json.decoder.scanstring(text, start, strict))  # type: ignore[attr-defined]


class ProjectionError(ValueError):
    pass


@dataclass
class MapBudget:
    used: int = 0

    def charge(self, length: int) -> None:
        self.used += length * 8
        if self.used > 8 * 1024 * 1024:
            raise ProjectionError("projection_limit")


@dataclass
class Region:
    text: str
    start: int
    end: int
    projection: Projection = "raw"
    starts: array[int] | None = None
    ends: array[int] | None = None
    tentative: bool = False
    clipped: bool = False
    clamped: bool = False

    def interval(self, start: int, end: int) -> tuple[int, int]:
        if not 0 <= start <= end <= len(self.text):
            raise ProjectionError("offset_invalid")
        if self.starts is None or self.ends is None:
            return self.start + start, self.start + end
        if start == end:
            point = self.starts[start] if start < len(self.starts) else self.end
            return point, point
        return self.starts[start], self.ends[end - 1]

    def slice(self, start: int, end: int, budget: MapBudget | None = None) -> Region:
        if self.starts is not None and budget is not None:
            budget.charge(end - start)
        a, b = self.interval(start, end)
        return Region(
            self.text[start:end],
            a,
            b,
            self.projection,
            None if self.starts is None else self.starts[start:end],
            None if self.ends is None else self.ends[start:end],
            self.tentative,
            self.clipped,
            self.clamped,
        )


@dataclass
class Target:
    region: Region
    language: str | None = None
    asserted: bool = False
    incomplete: bool = False


@dataclass
class Selection:
    targets: list[Target] = field(default_factory=list)
    reasons: set[str] = field(default_factory=set)
    error: str | None = None
    examined: int = 0
    total: int = 0
    tail: int | None = None
    unsupported: bool = False


def validate_envelope(
    text: str,
    segments: tuple[tuple[int, int], ...] | None,
    total: int | None,
) -> tuple[tuple[tuple[int, int], ...], int]:
    if not isinstance(text, str):
        raise ProjectionError("invalid_envelope")
    total = len(text) if total is None else total
    if type(total) is not int or total < len(text):
        raise ProjectionError("invalid_envelope")
    if segments is None:
        return (((0, len(text)),) if text else ()), total
    previous = 0
    checked = []
    for a, b in segments:
        if type(a) is not int or type(b) is not int or not previous <= a < b <= len(text):
            raise ProjectionError("invalid_envelope")
        if text[previous:a].strip("\n"):
            raise ProjectionError("invalid_envelope")
        checked.append((a, b))
        previous = b
        if len(checked) > 4096:
            raise ProjectionError("projection_limit")
    if text[previous:].strip("\n"):
        raise ProjectionError("invalid_envelope")
    return tuple(checked), total


_SPACE_RUN = re.compile(r"[\s\ufeff]+")
_TRAILING_WORD = re.compile(r"(?<![\w.$])[\w.$]+[ \n]?$")


def _compact_whitespace(text: str) -> str:
    # Most plain prose already uses single ASCII spaces. Avoid allocating one
    # regex replacement per word when compaction would return identical text.
    if (
        text.isascii()
        and "  " not in text
        and not any(char in text for char in "\t\n\r\v\f\x1c\x1d\x1e\x1f")
    ):
        return text
    return (
        _SPACE_RUN.sub(lambda match: "\n" if "\n" in match[0] else " ", text)
        if "\n" in text
        else _SPACE_RUN.sub(" ", text)
    )


def _unescape(match: re.Match[str]) -> str:
    value = match[0]
    return (
        chr(int(value[2:], 16))
        if value.startswith("\\u")
        else {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}.get(value[1], value[1])
    )


async def preflight(text: str) -> bool:
    """Bounded streaming candidate check; chunk boundaries cannot erase calls.

    Carry incomplete escapes through two decode layers. Compact whitespace across
    chunks, not independently inside each chunk. Very long trailing identifiers
    retain a dotted/non-dotted sentinel, sufficient for this conservative filter;
    selection and the engine always receive the unmodified original source.
    """
    pending = ["", ""]
    tails = ["", "", ""]
    limit = min(len(text), MAX_PARAM_TEXT_LEN)
    layers = 3 if "\\" in text[:limit] else 1
    for start in range(0, limit, 8192):
        chunk = text[start : min(start + 8192, limit)]
        final = start + 8192 >= limit
        for layer in range(layers):
            if layer:
                encoded = pending[layer - 1] + chunk
                cut = len(encoded) if final else max(0, len(encoded) - 6)
                # Never split a valid escape across the retained suffix. Six
                # characters also retain any incomplete unicode escape.
                for match in _ESCAPE.finditer(encoded):
                    if match.start() < cut < match.end():
                        cut = match.start()
                        break
                pending[layer - 1] = encoded[cut:]
                chunk = _ESCAPE.sub(_unescape, encoded[:cut])
            # Preserve a newline in each run for the declaration alternative's
            # line anchor, while keeping arbitrarily long call gaps bounded.
            window = tails[layer] + chunk.replace('"', "\n")
            window = _compact_whitespace(window)
            if _is_candidate(window) or "```" in window or "~~~" in window:
                return True
            # Ordinary short words need only the carry suffix. Revisit the
            # entire window for a long run so an earlier dot is not discarded.
            word = _TRAILING_WORD.search(window[-256:])
            if word is not None and len(word[0]) > 128:
                word = _TRAILING_WORD.search(window)
                assert word is not None
                sentinel = "x.y" if "." in word[0] else "x"
                suffix = word[0][-1] if word[0].endswith((" ", "\n")) else ""
                window = window[: word.start()] + sentinel + suffix
            tails[layer] = window[-256:]
        await asyncio.sleep(0)
    return False


def _mapped(
    region: Region, spans: list[tuple[int, int]], projection: Projection, budget: MapBudget
) -> Region:
    length = sum(b - a for a, b in spans)
    budget.charge(length)
    starts, ends = array("I"), array("I")
    chunks = []
    for a, b in spans:
        chunks.append(region.text[a:b])
        if region.starts is None:
            starts.extend(range(region.start + a, region.start + b))
            ends.extend(range(region.start + a + 1, region.start + b + 1))
        else:
            assert region.ends is not None
            starts.extend(region.starts[a:b])
            ends.extend(region.ends[a:b])
    return Region(
        "".join(chunks),
        starts[0] if starts else region.start,
        ends[-1] if ends else region.end,
        projection,
        starts,
        ends,
        True,
        region.clipped,
        region.clamped,
    )


async def _json_strings(
    region: Region,
) -> tuple[list[tuple[int, int, int]], set[str], list[tuple[int, int]], int | None]:
    """Validate one JSON value, storing only bounded string-token coordinates."""
    text = region.text
    leaves: list[tuple[int, int, int]] = []
    reasons: set[str] = set()
    clamps: list[tuple[int, int]] = []
    # Each frame: kind, state, start, current key, clamped. Root expects one value.
    frames: list[list[object]] = [["root", "value", 0, "", False]]
    i = 0
    yielded = 0
    while frames:
        if i - yielded >= 8192:
            await asyncio.sleep(0)
            yielded = i
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        f = frames[-1]
        kind, state = f[0], f[1]
        if kind == "root" and state == "done":
            if i != len(text):
                raise ValueError("trailing JSON")
            break
        if i >= len(text):
            raise ValueError("incomplete JSON")
        char = text[i]
        if state in ("key_end", "value_end", "comma") and char == (
            "}" if kind == "object" else "]"
        ):
            if f[4]:
                clamps.append((cast("int", f[2]), i + 1))
            frames.pop()
            i += 1
            continue
        if state == "comma":
            if char != ",":
                raise ValueError("JSON comma")
            f[1] = "key" if kind == "object" else "value"
            i += 1
            continue
        if state == "colon":
            if char != ":":
                raise ValueError("JSON colon")
            f[1] = "value"
            i += 1
            continue
        if state in ("key", "key_end"):
            if char != '"':
                raise ValueError("JSON key")
            value, end = _scan_string(text, i + 1, True)
            if await preflight(value):
                if len(leaves) >= 4096:
                    raise ProjectionError("projection_limit_code")
                leaves.append((i, end, len(frames) - 1))
            f[3], f[1], i = value, "colon", end
            continue
        f[1] = "done" if kind == "root" else "comma"
        if char in "{[":
            if len(frames) > 128:
                # Stop retaining stack frames, but examine every remaining
                # string token (including escaped identifiers) before calling
                # this a non-code depth limit. No recursive JSON tree.
                # Do not let malformed strings or quote alignment hide later
                # escaped code. This is evidence of missing coverage, not a
                # claim that the remaining document is valid JSON.
                code = await preflight(text)
                reasons.add("projection_limit_code" if code else "projection_depth_limit")
                return leaves, reasons, clamps, i
            frames.append(
                [
                    "object" if char == "{" else "array",
                    "key_end" if char == "{" else "value_end",
                    i,
                    "",
                    False,
                ]
            )
            i += 1
            continue
        if char == '"':
            value, end = _scan_string(text, i + 1, True)
            if len(leaves) < 4096:
                leaves.append((i, end, len(frames) - 1))
            elif await preflight(value):
                raise ProjectionError("projection_limit_code")
            else:
                reasons.add("projection_limit")
            if f[3] == "truncated_by":
                reasons.add("host_paged")
            i = end
            continue
        token = next(
            (literal for literal in ("true", "false", "null") if text.startswith(literal, i)), None
        )
        if token is not None:
            if token == "true" and f[3] == "truncated_lines":
                f[4] = True
                reasons.add("host_clamped")
            elif token == "true" and f[3] in ("truncated", "total_count_is_lower_bound"):
                reasons.add("host_paged")
            i += len(token)
            continue
        number = _NUMBER.match(text, i)
        if number is None:
            raise ValueError("JSON value")
        i = number.end()
    return leaves, reasons, clamps, None


def _decode_string(region: Region, a: int, b: int, limit: int, budget: MapBudget) -> Region:
    decoded = _scan_string(region.text, a + 1, True)[0]
    clipped = len(decoded) > limit
    decoded = decoded[:limit]
    budget.charge(len(decoded))
    starts, ends = array("I"), array("I")
    raw, pos, cursor = region.text, a + 1, 0
    while cursor < len(decoded):
        if raw[pos] == "\\":
            match = _ESCAPE.match(raw, pos)
            if match is None:
                raise ProjectionError("invalid_encoding")
            end = match.end()
            if (
                raw[pos : pos + 2] == "\\u"
                and 0xD800 <= int(raw[pos + 2 : pos + 6], 16) <= 0xDBFF
                and raw[end : end + 2] == "\\u"
                and 0xDC00 <= int(raw[end + 2 : end + 6], 16) <= 0xDFFF
            ):
                end += 6
            start_origin, end_origin = region.interval(pos, end)
            starts.append(start_origin)
            ends.append(end_origin)
            cursor += 1
            pos = end
        else:
            end = raw.find("\\", pos, b - 1)
            if end < 0:
                end = b - 1
            end = min(end, pos + len(decoded) - cursor)
            if region.starts is None:
                starts.extend(range(region.start + pos, region.start + end))
                ends.extend(range(region.start + pos + 1, region.start + end + 1))
            else:
                assert region.ends is not None
                starts.extend(region.starts[pos:end])
                ends.extend(region.ends[pos:end])
            cursor += end - pos
            pos = end
    a0, b0 = region.interval(a, b)
    return Region(
        decoded,
        a0,
        b0,
        "json_string",
        starts,
        ends,
        True,
        clipped or region.clipped,
        region.clamped,
    )


def _dedent(region: Region, budget: MapBudget) -> Region:
    common: str | None = None
    for count, line in enumerate(_LINE.finditer(region.text)):
        if count >= 16384:
            raise ProjectionError("projection_limit")
        value = line.group()
        if not value.strip():
            continue
        whitespace = value[: len(value) - len(value.lstrip(" \t"))]
        if common is None:
            common = whitespace
        else:
            length = 0
            for left, right in zip(common, whitespace, strict=False):
                if left != right:
                    break
                length += 1
            common = common[:length]
        if not common:
            return region
    if not common:
        return region
    return _mapped(
        region,
        [
            (m.start() + (len(common) if m.group().strip() else 0), m.end())
            for m in _LINE.finditer(region.text)
        ],
        "dedented",
        budget,
    )


def _presentation(region: Region, budget: MapBudget) -> list[Region]:
    spans: list[tuple[int, int]] = []
    previous = -1
    for line in _LINE.finditer(region.text):
        if len(spans) >= 16384:
            raise ProjectionError("projection_limit")
        if not line.group().strip():
            spans.append(line.span())
            continue
        m = re.match(r"[ \t]*(\d{1,9})\|", line.group())
        if m is None or int(m[1]) <= previous:
            break
        previous = int(m[1])
        spans.append((line.start() + m.end(), line.end()))
    else:
        if previous >= 0:
            mapped = _mapped(region, spans, "numbered_lines", budget)
            mapped.clamped |= bool(re.search(r"\.\.\. \[truncated\](?:\r?\n|$)", mapped.text))
            return [mapped]
    # Dense search output must consist entirely of path headers and numbered rows.
    groups: list[list[tuple[int, int]]] = []
    previous = -1
    have_header = False
    row_count = 0
    for line in _LINE.finditer(region.text):
        row_count += 1
        if row_count > 16384:
            raise ProjectionError("projection_limit")
        value = line.group().rstrip("\r\n")
        if not value:
            continue
        m = re.match(r"[ \t]+(\d{1,9}):[ ]?", value)
        if m is not None and have_header:
            number = int(m[1])
            if not groups or number != previous + 1:
                groups.append([])
            groups[-1].append((line.start() + m.end(), line.end()))
            previous = number
        elif _is_search_header(value):
            have_header = True
            previous = -1
        else:
            return [region]
    if groups:
        return [_mapped(region, group, "search_rows", budget) for group in groups]
    return [region]


async def select_sources(
    text: str,
    *,
    segments: tuple[tuple[int, int], ...] | None = None,
    total: int | None = None,
    max_bytes: int = 65536,
) -> Selection:
    segments, total = validate_envelope(text, segments, total)
    selection = Selection(examined=min(len(text), MAX_PARAM_TEXT_LEN), total=total)
    budget = MapBudget()
    remaining = max_bytes
    if not await preflight(text) and not text.lstrip().startswith(("{", "[", '"')):
        if total > selection.examined:
            selection.error = "semgrep.incomplete"
            selection.reasons.add("upstream_truncated")
            selection.tail = selection.examined
        return selection

    def add(
        region: Region,
        language: str | None = None,
        asserted: bool = False,
        incomplete: bool = False,
    ) -> None:
        nonlocal remaining
        if not region.text.strip():
            return
        if language is None and not _is_candidate(region.text):
            selection.unsupported |= region.tentative
            return
        if len(selection.targets) >= 16 or remaining == 0:
            selection.tail = (
                region.start if selection.tail is None else min(selection.tail, region.start)
            )
            selection.reasons.add(
                "target_limit_tentative"
                if len(selection.targets) >= 16
                else "source_limit_tentative"
            )
            if asserted:
                selection.error = "semgrep.incomplete"
                selection.reasons.add("asserted_target_omitted")
            return
        region = _dedent(region, budget)
        encoded = region.text.encode("utf-8")
        if len(encoded) > remaining:
            prefix = encoded[:remaining].decode("utf-8", errors="ignore")
            tail = region.interval(len(prefix), len(prefix))[0]
            selection.tail = tail if selection.tail is None else min(selection.tail, tail)
            region = region.slice(0, len(prefix), budget)
            region.clipped = True
            encoded = prefix.encode("utf-8")
        remaining -= len(encoded)
        selection.targets.append(Target(region, language, asserted, incomplete))

    async def project(region: Region, layers: int = 0) -> None:
        if layers < 2 and region.text.lstrip().startswith(("{", "[", '"')):
            try:
                leaves, reasons, clamps, stopped = await _json_strings(region)
            except ProjectionError:
                raise
            except (ValueError, json.JSONDecodeError):
                pass  # malformed envelopes remain raw, never certified JSON
            else:
                selection.reasons.update(reasons)
                if stopped is not None:
                    tail = region.interval(stopped, stopped)[0]
                    selection.tail = tail if selection.tail is None else min(selection.tail, tail)
                    selection.unsupported = True
                    if "projection_limit_code" in reasons:
                        selection.error = "semgrep.projection_limit_code"
                for a, b, depth in leaves:
                    if depth > 8:
                        raw = _scan_string(region.text, a + 1, True)[0]
                        if await preflight(raw):
                            raise ProjectionError("projection_limit_code")
                        selection.unsupported = True
                        selection.reasons.add("projection_depth_limit")
                        continue
                    full = _scan_string(region.text, a + 1, True)[0]
                    if not await preflight(full):
                        continue  # Proven non-candidate leaves need no source maps.
                    decoded = _decode_string(region, a, b, max_bytes, budget)
                    if len(full) > max_bytes:
                        # The retained prefix may be blank or non-code and then
                        # vanish in add(); record the omitted suffix here.
                        tail = decoded.ends[-1] if decoded.ends else decoded.start
                        selection.tail = (
                            tail if selection.tail is None else min(selection.tail, tail)
                        )
                        selection.reasons.add("source_limit_tentative")
                        omitted = full[max_bytes:]
                        if any(
                            _LABELS.get(f[2].strip().lower()) for f in _FENCE.finditer(omitted)
                        ):
                            selection.error = "semgrep.incomplete"
                            selection.reasons.add("asserted_target_omitted")
                    decoded.clamped |= any(x <= a and b <= y for x, y in clamps)
                    await project(decoded, layers + 1)
                    await asyncio.sleep(0)
                return
        for part in _presentation(region, budget):
            cursor = 0
            fences = iter(_FENCE.finditer(part.text))
            for fence in fences:
                if fence.start() < cursor:
                    continue
                add_raw(part.slice(cursor, fence.start(), budget))
                label = fence[2].strip().lower()
                language = _LABELS.get(label)
                close = next(
                    (
                        f
                        for f in fences
                        if f[1][0] == fence[1][0]
                        and len(f[1]) >= len(fence[1])
                        and not f[2].strip()
                    ),
                    None,
                )
                end = close.start() if close else len(part.text)
                body_start = min(
                    len(part.text),
                    fence.end() + (1 if part.text[fence.end() : fence.end() + 1] == "\n" else 0),
                )
                body = part.slice(body_start, end, budget)
                if language is None:
                    body.tentative = True
                    selection.unsupported = True
                add(body, language, language is not None, close is None and language is not None)
                cursor = close.end() if close else len(part.text)
            add_raw(part.slice(cursor, len(part.text), budget))
        await asyncio.sleep(0)

    def add_raw(region: Region) -> None:
        asserted = False
        if not region.tentative:
            for line in _LINE.finditer(region.text):
                value = line.group().rstrip("\r\n")
                if not value.strip() or (
                    value.startswith("#") and not value.startswith(("#!", "#include", "#define"))
                ):
                    continue
                asserted = _is_header(value)
                break
        add(region, "python" if asserted else None, asserted)

    try:
        for a, b in segments:
            if a >= MAX_PARAM_TEXT_LEN:
                break
            await project(
                Region(text[a : min(b, MAX_PARAM_TEXT_LEN)], a, min(b, MAX_PARAM_TEXT_LEN))
            )
        if total > selection.examined:
            selection.error = "semgrep.incomplete"
            selection.reasons.add("upstream_truncated")
            selection.tail = selection.examined
    except UnicodeError:
        selection.error = "semgrep.invalid_encoding"
        selection.reasons.add("invalid_encoding")
    except ProjectionError as exc:
        reason = str(exc)
        if reason == "projection_depth_limit":
            selection.unsupported = True
        else:
            selection.error = "semgrep." + reason
        selection.reasons.add(reason)
        selection.tail = 0 if selection.tail is None else selection.tail
    return selection
