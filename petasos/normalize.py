from __future__ import annotations

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

_EXTRA_INVISIBLE: frozenset[str] = frozenset(
    [
        chr(0x2800),  # BRAILLE PATTERN BLANK (So)
        chr(0x202F),  # NARROW NO-BREAK SPACE (Zs)
        chr(0x180E),  # MONGOLIAN VOWEL SEPARATOR (Cf — belt-and-suspenders)
    ]
)


def _is_strippable(ch: str) -> bool:
    return unicodedata.category(ch) in _STRIP_CATEGORIES or ch in _EXTRA_INVISIBLE


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


def normalize(text: str) -> NormalizedText:
    if not text:
        return NormalizedText(
            original=text,
            normalized=text,
            transformations_applied=(),
        )

    original = text
    transforms: list[str] = []

    # Step 1: RTL override detection (before stripping)
    rtl_detected = bool(RTL_OVERRIDES & set(text))
    if rtl_detected:
        transforms.append("rtl_override_detected")

    # Step 2: Invisible character stripping (category-based)
    stripped_count = sum(1 for ch in text if _is_strippable(ch))
    if stripped_count > 0:
        text_after_strip = "".join(ch for ch in text if not _is_strippable(ch))
        transforms.append("invisible_chars_stripped")
    else:
        text_after_strip = text

    # Step 3: NFKC normalization
    text_after_nfkc = unicodedata.normalize("NFKC", text_after_strip)
    if text_after_nfkc != text_after_strip:
        transforms.append("nfkc_normalized")

    # Step 4: Re-strip after NFKC (NORM-02)
    restrip_count = sum(1 for ch in text_after_nfkc if _is_strippable(ch))
    if restrip_count > 0:
        text_after_restrip = "".join(
            ch for ch in text_after_nfkc if not _is_strippable(ch)
        )
        stripped_count += restrip_count
        transforms.append("nfkc_restrip_applied")
    else:
        text_after_restrip = text_after_nfkc

    # Step 5: Combining mark removal (NORM-04)
    text_nfd = unicodedata.normalize("NFD", text_after_restrip)
    mn_count = sum(
        1 for ch in text_nfd if unicodedata.category(ch) == "Mn"
    )
    if mn_count > 0:
        text_stripped_mn = "".join(
            ch for ch in text_nfd if unicodedata.category(ch) != "Mn"
        )
        text_after_mn = unicodedata.normalize("NFC", text_stripped_mn)
        transforms.append("combining_marks_stripped")
    else:
        text_after_mn = text_after_restrip

    # Step 6: Homoglyph mapping (expanded table, NORM-03)
    text_after_homoglyph = text_after_mn.translate(_HOMOGLYPH_TABLE)
    if text_after_homoglyph != text_after_mn:
        transforms.append("homoglyph_mapped")

    confusables = text_after_homoglyph != text_after_mn

    return NormalizedText(
        original=original,
        normalized=text_after_homoglyph,
        transformations_applied=tuple(transforms),
        invisible_chars_stripped=stripped_count,
        confusables_normalized=confusables,
        rtl_overrides_detected=rtl_detected,
    )
