from __future__ import annotations

import re
import unicodedata

from petasos._types import NormalizedText

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

# vestigial: superseded by INVISIBLE_NON_CF for stripping; retained only for test imports
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

# Canonical enumeration of invisible non-Cf code points (PET-90; relocated from
# petasos/console/_validation.py where PET-85 introduced it as
# _INVISIBLE_PRINTABLE). Invisible/zero-width code points that
# str.isprintable() returns True for and NFKC does not remove. Enumerated, not
# predicate-derived: CPython's unicodedata exposes no
# Default_Ignorable_Code_Point accessor (only category()), and the residue
# spans Mn/Lo/So, so no single category test isolates it — contrast NORM-01
# (PET-43) where category()=="Cf" WAS the semantic predicate. Three groups:
#   1. The assigned-non-Cf Default_Ignorable residue (isprintable() already
#      rejects every Cf and unassigned-Cn Default_Ignorable, leaving only this
#      small, slow-growing set). Source: DerivedCoreProperties.txt (Unicode 14+).
#      U+180F (FVS4) is unassigned (Cn) before Unicode 14.0; included by code
#      point, stripped regardless of UCD version.
#   2. Non-DI zero-glyph fillers Unicode chose not to mark Default_Ignorable
#      but which still render no glyph (PET-85 round-3 finding).
#   3. Zero-glyph/space renderers formerly enumerated here as _EXTRA_INVISIBLE.
#      U+180E is intentionally triply covered (Cf category test + group-1
#      Mongolian range + this group) — do not "clean up" the dup; the console
#      set-identity guarantee depends on verbatim membership.
# Extend a group if a future Unicode version adds a member;
# test_default_ignorable_sweep_normalize and test_default_ignorable_rejected
# (independently derived) guard group 1.
INVISIBLE_NON_CF: frozenset[str] = frozenset(
    {
        # Group 1 — assigned-non-Cf Default_Ignorable residue
        chr(0x034F),  # COMBINING GRAPHEME JOINER (Mn)
        chr(0x115F),  # HANGUL CHOSEONG FILLER (Lo)
        chr(0x1160),  # HANGUL JUNGSEONG FILLER (Lo)
        chr(0x17B4),  # KHMER VOWEL INHERENT AQ (Mn)
        chr(0x17B5),  # KHMER VOWEL INHERENT AA (Mn)
        chr(0x3164),  # HANGUL FILLER (Lo; NFKC → U+1160)
        chr(0xFFA0),  # HALFWIDTH HANGUL FILLER (Lo; NFKC → U+1160)
        # Group 2 — non-DI zero-glyph fillers
        chr(0x16FE4),  # KHITAN SMALL SCRIPT FILLER (Mn; non-DI zero-glyph)
        chr(0x1BC9D),  # DUPLOYAN THICK LETTER SELECTOR (Mn; non-DI zero-glyph)
        # Group 3 — zero-glyph/space renderers (former _EXTRA_INVISIBLE)
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

# Relocated from petasos/session/guard.py (PET-118): single definition, shared by
# ToolCallGuard's normalizer and the reference plugin's classification. Strips a
# SINGLE leading namespace prefix — `mcp__<ns>__` or `hermes__`. Co-located with
# _HOMOGLYPH_TABLE because canonicalize_tool_name composes both.
_NAMESPACE_PREFIX_RE = re.compile(r"^(?:mcp__[a-zA-Z0-9_]+?__|hermes__)")

# PET-121: split at a TRUE camel boundary only — a lowercase/digit immediately followed
# by an uppercase. Boundary-guarded, NOT Hermes's naive `(?<!^)(?=[A-Z])` (which mangles
# all-caps/snake-with-capital names: SEND_EMAIL -> s_e_n_d__e_m_a_i_l). Hermes survives its
# own naive split because it is one candidate in a registry-guarded set; Petasos emits a
# SINGLE canonical form and has no registry, so it must reproduce Hermes's *resolved
# outcome* for snake tools without mangling (D-CAMEL).
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _strip_tool_suffix(name: str) -> str:
    """PET-121 (D-SUFFIX): strip a trailing ``_tool`` / ``-tool``, looped twice to mirror
    Hermes's ``range(2)`` (``TodoTool_tool`` -> ``todo``). The empty-guard never strips to
    ``""`` (Hermes guards via ``if c``). Bare ``tool`` (no separator) is deliberately NOT
    stripped: Hermes only strips it when the result is a registered tool, and Petasos has no
    registry — an unconditional strip would over-canonicalize (``dbtool`` -> ``db``) and
    break PET-118's ``mcp__mcp__tool`` -> ``tool`` fixtures. ``name`` is already casefolded
    and namespace-stripped here."""
    for _ in range(2):
        for suffix in ("_tool", "-tool"):
            if name.endswith(suffix):
                stripped = name[: -len(suffix)].rstrip("_-")
                if stripped:  # empty-guard: never strip to "" (keeps prior value)
                    name = stripped
                break
        else:
            break  # no separator-suffix matched this pass -> done
    return name


def canonicalize_tool_name(name: str) -> str:
    """Alias-free canonical form for tool-name matching, shared by ToolCallGuard's
    normalizer (under its alias layer) and the reference plugin's classification.

    Mirrors the deterministic shapes Hermes resolves at dispatch (PET-121): a
    boundary-guarded CamelCase->snake split (BEFORE casefold — the case info is
    load-bearing) and a trailing _tool/-tool suffix strip. It does NOT reproduce
    Hermes's naive single-regex camel (which mangles all-caps names as a single
    form), its registry-guarded bare-`tool` strip, its single-underscore mcp_
    namespace stripping, or its fuzzy fallback — see D-CAMEL/D-SUFFIX/D-NS/D-FUZZY.

    Strips a SINGLE leading namespace prefix (matching the guard's existing behavior,
    D-EQUIV / D6) — not a fixed-point loop. Stacked/alternate prefix shapes remain a D6
    coverage item gated on the verified Hermes grammar (D-VERIFY)."""
    name = name.strip()
    name = unicodedata.normalize("NFKC", name)
    name = name.translate(_HOMOGLYPH_TABLE)
    name = _CAMEL_BOUNDARY_RE.sub("_", name)  # PET-121 D-CAMEL/D1: BEFORE casefold
    name = name.casefold()
    name = _NAMESPACE_PREFIX_RE.sub("", name)
    name = _strip_tool_suffix(name)  # PET-121 D-SUFFIX: after ns-strip
    return name.strip()


# Leet-fold tables (PET-97). Common ASCII digit/symbol→letter substitutions,
# decoded onto match-only candidate views — never onto ``normalized`` itself:
# digits are ubiquitous in benign text, so folding in place would corrupt the
# canonical output for every downstream consumer (ML input, PII spans, audit).
# ``1`` is ambiguous ("i" in 1gn0r3, "l" in 411) and str.translate is
# one-to-one, so two variant tables produce a candidate set instead of
# guessing.
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


def normalize(
    text: str,
    *,
    nfkc: bool = True,
    strip_zero_width: bool = True,
    map_homoglyphs: bool = True,
    detect_rtl: bool = True,
    fold_leet: bool = True,
) -> NormalizedText:
    """Normalize text for pattern matching.

    Each stage is independently gated (PIPE-05): disabling one toggle (e.g.
    ``nfkc=False``) does not suppress the others, and ``transformations_applied``
    reflects only the stages that actually ran. The five flags map 1:1 to the
    ``normalize_nfkc`` / ``strip_zero_width`` / ``map_homoglyphs`` /
    ``detect_rtl_override`` / ``fold_leet`` config toggles. The post-NFKC
    re-strip (NORM-02) rides on ``strip_zero_width`` and combining-mark removal
    (NORM-04) rides on ``nfkc``, since each is only meaningful when its parent
    stage runs.

    The leet fold (PET-97) is a side channel, not a transform: it emits
    length-preserving decoded candidate views into ``leet_views`` for the
    injection pass to match against, leaves ``normalized`` untouched, and
    records no ``transformations_applied`` entry (digit-bearing benign text
    would flag on every input — the observability carrier is the injection
    finding's message instead).
    """
    if not text:
        return NormalizedText(
            original=text,
            normalized=text,
            transformations_applied=(),
        )

    original = text
    transforms: list[str] = []

    # Step 1: RTL override detection (before stripping)
    rtl_detected = detect_rtl and bool(RTL_OVERRIDES & set(text))
    if rtl_detected:
        transforms.append("rtl_override_detected")

    # Step 2: Invisible character stripping (category-based)
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

    # Step 3: NFKC normalization
    if nfkc:
        text_after_nfkc = unicodedata.normalize("NFKC", text_after_strip)
        if text_after_nfkc != text_after_strip:
            transforms.append("nfkc_normalized")
    else:
        text_after_nfkc = text_after_strip

    # Step 4: Re-strip after NFKC (NORM-02) — only when both stripping and NFKC
    # ran, since NFKC is what can reintroduce a strippable char.
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

    # Step 5: Combining mark removal (NORM-04) — normalization-family, gated on nfkc
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

    # Step 6: Homoglyph mapping (expanded table, NORM-03)
    if map_homoglyphs:
        text_after_homoglyph = text_after_mn.translate(_HOMOGLYPH_TABLE)
        if text_after_homoglyph != text_after_mn:
            transforms.append("homoglyph_mapped")
    else:
        text_after_homoglyph = text_after_mn

    confusables = text_after_homoglyph != text_after_mn

    # Step 7: Leet fold (PET-97) — match-only candidate views. Runs on the
    # final normalized text so homoglyph+leet compositions decode correctly.
    # ``view_l`` can only differ from the base when ``view_i`` does (both
    # tables map the identical character set), so the equality check below
    # doubles as the no-foldable-chars early-out.
    leet_views: tuple[str, ...] = ()
    if fold_leet:
        view_i = text_after_homoglyph.translate(_LEET_TABLE_I)
        if view_i != text_after_homoglyph:
            view_l = text_after_homoglyph.translate(_LEET_TABLE_L)
            leet_views = (view_i,) if view_l == view_i else (view_i, view_l)

    return NormalizedText(
        original=original,
        normalized=text_after_homoglyph,
        transformations_applied=tuple(transforms),
        invisible_chars_stripped=stripped_count,
        confusables_normalized=confusables,
        rtl_overrides_detected=rtl_detected,
        leet_views=leet_views,
    )
