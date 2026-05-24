from __future__ import annotations

import unicodedata

from petasos._types import NormalizedText

RTL_OVERRIDES = frozenset(
    [
        "‪",  # LRE
        "‫",  # RLE
        "‬",  # PDF
        "‭",  # LRO
        "‮",  # RLO
        "⁦",  # LRI
        "⁧",  # RLI
        "⁨",  # FSI
        "⁩",  # PDI
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

_HOMOGLYPH_TABLE = str.maketrans(
    {
        "а": "a",  # Cyrillic a
        "е": "e",  # Cyrillic e
        "о": "o",  # Cyrillic o
        "р": "p",  # Cyrillic p
        "с": "c",  # Cyrillic c
        "у": "y",  # Cyrillic y
        "і": "i",  # Cyrillic i
        "ѕ": "s",  # Cyrillic s
        "α": "a",  # Greek alpha
        "ε": "e",  # Greek epsilon
        "ο": "o",  # Greek omicron
        "ρ": "p",  # Greek rho
        "κ": "k",  # Greek kappa
        "ι": "i",  # Greek iota
        "ν": "v",  # Greek nu
        "ı": "i",  # Latin dotless i
        "ɡ": "g",  # IPA g
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

    # Step 2: Invisible character stripping
    stripped_count = sum(1 for ch in text if ch in INVISIBLE_CHARS)
    if stripped_count > 0:
        text_after_strip = "".join(ch for ch in text if ch not in INVISIBLE_CHARS)
        transforms.append("invisible_chars_stripped")
    else:
        text_after_strip = text

    # Step 3: NFKC normalization
    text_after_nfkc = unicodedata.normalize("NFKC", text_after_strip)
    if text_after_nfkc != text_after_strip:
        transforms.append("nfkc_normalized")

    # Step 4: Homoglyph mapping
    text_after_homoglyph = text_after_nfkc.translate(_HOMOGLYPH_TABLE)
    if text_after_homoglyph != text_after_nfkc:
        transforms.append("homoglyph_mapped")

    # confusables_normalized: true if text after steps 3+4 differs from text after step 2
    confusables = text_after_homoglyph != text_after_strip

    return NormalizedText(
        original=original,
        normalized=text_after_homoglyph,
        transformations_applied=tuple(transforms),
        invisible_chars_stripped=stripped_count,
        confusables_normalized=confusables,
        rtl_overrides_detected=rtl_detected,
    )
