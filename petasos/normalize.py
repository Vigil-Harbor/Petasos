"""Normalize canonical text while retaining separate match-only evasion views."""

from __future__ import annotations

import re
import unicodedata

from petasos.model import NormalizedText

RTL_OVERRIDES = frozenset(
    [
        chr(0x202A),  # LRE
        chr(0x202B),  # RLE
        chr(0x202C),  # PDF
        chr(0x202D),  # LRO
        chr(0x202E),  # RLO
        chr(0x2066),  # LRI
        chr(0x2067),  # RLI
        chr(0x2068),  # FSI
        chr(0x2069),  # PDI
    ]
)

# Tests import this vocabulary; stripping uses INVISIBLE_NON_CF and Unicode categories.
INVISIBLE_CHARS = frozenset(
    [
        "­",  # soft hyphen
        "​",  # zero-width space
        "‌",  # ZWNJ
        "‍",  # ZWJ
        "‎",  # LRM
        "‏",  # RLM
        "‪",  # LRE
        "‫",  # RLE
        "‬",  # PDF
        "‭",  # LRO
        "‮",  # RLO
        " ",  # narrow no-break space
        "⁠",  # word joiner
        "⁡",  # function application
        "⁢",  # invisible times
        "⁣",  # invisible separator
        "⁤",  # invisible plus
        "⁦",  # LRI
        "⁧",  # RLI
        "⁨",  # FSI
        "⁩",  # PDI
        "﻿",  # BOM / ZWNBSP
    ]
)

_STRIP_CATEGORIES: frozenset[str] = frozenset({"Cf"})

# See docs/architecture/rationale.md, "Normalization views".
INVISIBLE_NON_CF: frozenset[str] = frozenset(
    {
        # Assigned non-Cf Default_Ignorable residue.
        chr(0x034F),  # COMBINING GRAPHEME JOINER (Mn)
        chr(0x115F),  # HANGUL CHOSEONG FILLER (Lo)
        chr(0x1160),  # HANGUL JUNGSEONG FILLER (Lo)
        chr(0x17B4),  # KHMER VOWEL INHERENT AQ (Mn)
        chr(0x17B5),  # KHMER VOWEL INHERENT AA (Mn)
        chr(0x3164),  # HANGUL FILLER (Lo; NFKC → U+1160)
        chr(0xFFA0),  # HALFWIDTH HANGUL FILLER (Lo; NFKC → U+1160)
        # Non-default-ignorable zero-glyph fillers.
        chr(0x16FE4),  # KHITAN SMALL SCRIPT FILLER (Mn; non-DI zero-glyph)
        chr(0x1BC9D),  # DUPLOYAN THICK LETTER SELECTOR (Mn; non-DI zero-glyph)
        # Blank and space renderers.
        chr(0x2800),  # BRAILLE PATTERN BLANK (So)
        chr(0x202F),  # NARROW NO-BREAK SPACE (Zs)
        chr(0x180E),  # MONGOLIAN VOWEL SEPARATOR (Cf — belt-and-suspenders)
    }
    | {chr(c) for c in range(0x180B, 0x1810)}  # MONGOLIAN FVS1–4 (180E is Cf; harmless dup)
    | {chr(c) for c in range(0xFE00, 0xFE10)}  # VARIATION SELECTORS 1–16 (Mn)
    | {chr(c) for c in range(0xE0100, 0xE01F0)}  # VARIATION SELECTORS SUPPLEMENT 17–256 (Mn)
)


def _is_strippable(ch: str) -> bool:
    return unicodedata.category(ch) in _STRIP_CATEGORIES or ch in INVISIBLE_NON_CF


def _replace_strippable_runs_with_space(text: str) -> str:
    """Collapse each maximal run of ``_is_strippable`` characters to one U+0020."""
    out: list[str] = []
    in_run = False
    for ch in text:
        if _is_strippable(ch):
            if not in_run:
                out.append(" ")
                in_run = True
        else:
            out.append(ch)
            in_run = False
    return "".join(out)


_HOMOGLYPH_TABLE = str.maketrans(
    {
        # Cyrillic lowercase
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "і": "i",
        "ѕ": "s",
        "к": "k",
        "х": "x",
        "н": "h",
        "т": "t",
        "м": "m",
        # Cyrillic uppercase
        "А": "A",
        "Е": "E",
        "О": "O",
        "Р": "P",
        "С": "C",
        "К": "K",
        "Х": "X",
        "Н": "H",
        "Т": "T",
        "М": "M",
        # Greek lowercase
        "α": "a",
        "ε": "e",
        "ο": "o",
        "ρ": "p",
        "κ": "k",
        "ι": "i",
        "ν": "v",
        "τ": "t",
        "η": "n",
        "μ": "u",
        # Greek uppercase
        "Α": "A",
        "Ε": "E",
        "Ο": "O",
        "Ρ": "P",
        "Κ": "K",
        "Ι": "I",
        "Ν": "N",
        "Τ": "T",
        "Η": "H",
        # Latin / IPA
        "ı": "i",
        "ɡ": "g",
    }
)

# See docs/architecture/rationale.md, "Hermes tool-name shapes".
_NAMESPACE_PREFIX_RE = re.compile(r"^(?:mcp__[a-zA-Z0-9_]+?__|hermes__)")

# See docs/architecture/rationale.md, "Hermes tool-name shapes".
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _strip_tool_suffix(name: str) -> str:
    """Strip up to two separated tool suffixes without returning an empty name.

    See docs/architecture/rationale.md, "Hermes tool-name shapes"."""
    for _ in range(2):
        for suffix in ("_tool", "-tool"):
            if name.endswith(suffix):
                stripped = name[: -len(suffix)].rstrip("_-")
                if stripped:
                    name = stripped
                break
        else:
            break
    return name


def canonicalize_tool_name(name: str) -> str:
    """Return one alias-free tool name shared by classification and guard matching.

    See docs/architecture/rationale.md, "Hermes tool-name shapes"."""
    name = name.strip()
    name = unicodedata.normalize("NFKC", name)
    name = name.translate(_HOMOGLYPH_TABLE)
    name = _CAMEL_BOUNDARY_RE.sub("_", name)  # Case boundaries disappear after casefolding.
    name = name.casefold()
    name = _NAMESPACE_PREFIX_RE.sub("", name)
    name = _strip_tool_suffix(name)
    return name.strip()


# See docs/architecture/rationale.md, "Normalization views".
_LEET_COMMON = {
    ord("0"): "o",
    ord("3"): "e",
    ord("4"): "a",
    ord("5"): "s",
    ord("7"): "t",
    ord("8"): "b",
    ord("9"): "g",
    ord("@"): "a",
    ord("$"): "s",
    ord("!"): "i",
}
_LEET_TABLE_I = str.maketrans({**_LEET_COMMON, ord("1"): "i"})
_LEET_TABLE_L = str.maketrans({**_LEET_COMMON, ord("1"): "l"})


def _leet_fold(text: str) -> tuple[str, ...]:
    """Return distinct i-then-l leet views, or none when no character folds."""
    view_i = text.translate(_LEET_TABLE_I)
    if view_i == text:
        return ()
    view_l = text.translate(_LEET_TABLE_L)
    return (view_i,) if view_l == view_i else (view_i, view_l)


def normalize(
    text: str,
    *,
    nfkc: bool = True,
    strip_zero_width: bool = True,
    map_homoglyphs: bool = True,
    detect_rtl: bool = True,
    fold_leet: bool = True,
) -> NormalizedText:
    """Return canonical text, applied transformations and independent match-only views.

    See docs/architecture/rationale.md, "Normalization views"."""
    if not text:
        return NormalizedText(
            original=text,
            normalized=text,
            transformations_applied=(),
        )

    original = text
    transforms: list[str] = []

    # RTL detection precedes stripping so removed controls remain observable.
    rtl_detected = detect_rtl and bool(RTL_OVERRIDES & set(text))
    if rtl_detected:
        transforms.append("rtl_override_detected")

    stripped_count = 0
    if strip_zero_width:
        stripped_count = sum(1 for ch in text if _is_strippable(ch))
        if stripped_count > 0:
            text_after_strip = "".join(ch for ch in text if not _is_strippable(ch))
            transforms.append("invisible_chars_stripped")
        else:
            text_after_strip = text
    else:
        text_after_strip = text

    if nfkc:
        text_after_nfkc = unicodedata.normalize("NFKC", text_after_strip)
        if text_after_nfkc != text_after_strip:
            transforms.append("nfkc_normalized")
    else:
        text_after_nfkc = text_after_strip

    # NFKC can introduce strippable characters, requiring a second stripping pass.
    if strip_zero_width and nfkc:
        restrip_count = sum(1 for ch in text_after_nfkc if _is_strippable(ch))
        if restrip_count > 0:
            text_after_restrip = "".join(ch for ch in text_after_nfkc if not _is_strippable(ch))
            stripped_count += restrip_count
            transforms.append("nfkc_restrip_applied")
        else:
            text_after_restrip = text_after_nfkc
    else:
        text_after_restrip = text_after_nfkc

    if nfkc:
        text_nfd = unicodedata.normalize("NFD", text_after_restrip)
        mn_count = sum(1 for ch in text_nfd if unicodedata.category(ch) == "Mn")
        if mn_count > 0:
            text_stripped_mn = "".join(ch for ch in text_nfd if unicodedata.category(ch) != "Mn")
            text_after_mn = unicodedata.normalize("NFC", text_stripped_mn)
            transforms.append("combining_marks_stripped")
        else:
            text_after_mn = text_after_restrip
    else:
        text_after_mn = text_after_restrip

    if map_homoglyphs:
        text_after_homoglyph = text_after_mn.translate(_HOMOGLYPH_TABLE)
        if text_after_homoglyph != text_after_mn:
            transforms.append("homoglyph_mapped")
    else:
        text_after_homoglyph = text_after_mn

    confusables = text_after_homoglyph != text_after_mn

    # See docs/architecture/rationale.md, "Normalization views".
    leet_views: tuple[str, ...] = _leet_fold(text_after_homoglyph) if fold_leet else ()

    # See docs/architecture/rationale.md, "Normalization views".
    separator_views: tuple[str, ...] = ()
    composed_views: tuple[str, ...] = ()
    if stripped_count > 0:
        view = _replace_strippable_runs_with_space(original)
        if nfkc:
            view = unicodedata.normalize("NFKC", view)
            view = _replace_strippable_runs_with_space(view)
            view_nfd = unicodedata.normalize("NFD", view)
            mn_count = sum(1 for ch in view_nfd if unicodedata.category(ch) == "Mn")
            if mn_count > 0:
                view = unicodedata.normalize(
                    "NFC",
                    "".join(ch for ch in view_nfd if unicodedata.category(ch) != "Mn"),
                )
        if map_homoglyphs:
            view = view.translate(_HOMOGLYPH_TABLE)
        if view != text_after_homoglyph:
            separator_views = (view,)
            if fold_leet:
                already = {text_after_homoglyph, *leet_views, view}
                composed_views = tuple(v for v in _leet_fold(view) if v not in already)

    return NormalizedText(
        original=original,
        normalized=text_after_homoglyph,
        transformations_applied=tuple(transforms),
        invisible_chars_stripped=stripped_count,
        confusables_normalized=confusables,
        rtl_overrides_detected=rtl_detected,
        leet_views=leet_views,
        separator_views=separator_views,
        composed_views=composed_views,
    )
