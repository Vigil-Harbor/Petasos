"""Boundary validation for caller-supplied values entering the console API."""

from __future__ import annotations

import unicodedata

from petasos.normalize import _HOMOGLYPH_TABLE, _is_strippable

_MAX_SESSION_ID_LEN = 128

# Invisible/zero-width code points that str.isprintable() returns True for and
# NFKC does not remove. Enumerated, not predicate-derived: CPython's
# unicodedata exposes no Default_Ignorable_Code_Point accessor (only
# category()), and the residue spans Mn/Lo/So, so no single category test
# isolates it — contrast NORM-01 (PET-43) where category()=="Cf" WAS the
# semantic predicate. Two groups:
#   1. The assigned-non-Cf Default_Ignorable residue (isprintable() already
#      rejects every Cf and unassigned-Cn Default_Ignorable, leaving only this
#      small, slow-growing set). Source: DerivedCoreProperties.txt (Unicode 14+).
#   2. Non-DI zero-glyph fillers Unicode chose not to mark Default_Ignorable
#      but which still render no glyph (PET-85 round-3 finding).
# Extend either group if a future Unicode version adds a member;
# test_default_ignorable_rejected (independently derived) guards group 1.
_INVISIBLE_PRINTABLE: frozenset[str] = frozenset(
    {
        chr(0x034F),  # COMBINING GRAPHEME JOINER (Mn)
        chr(0x115F),  # HANGUL CHOSEONG FILLER (Lo)
        chr(0x1160),  # HANGUL JUNGSEONG FILLER (Lo)
        chr(0x17B4),  # KHMER VOWEL INHERENT AQ (Mn)
        chr(0x17B5),  # KHMER VOWEL INHERENT AA (Mn)
        chr(0x3164),  # HANGUL FILLER (Lo; NFKC → U+1160)
        chr(0xFFA0),  # HALFWIDTH HANGUL FILLER (Lo; NFKC → U+1160)
        chr(0x16FE4),  # KHITAN SMALL SCRIPT FILLER (Mn; non-DI zero-glyph)
        chr(0x1BC9D),  # DUPLOYAN THICK LETTER SELECTOR (Mn; non-DI zero-glyph)
    }
    | {chr(c) for c in range(0x180B, 0x1810)}  # MONGOLIAN FVS1–4 (180E is Cf; harmless dup)
    | {chr(c) for c in range(0xFE00, 0xFE10)}  # VARIATION SELECTORS 1–16 (Mn)
    | {chr(c) for c in range(0xE0100, 0xE01F0)}  # VARIATION SELECTORS SUPPLEMENT 17–256 (Mn)
)

_COMBINING_CATEGORIES: frozenset[str] = frozenset({"Mn", "Mc", "Me"})


class SessionIdError(ValueError):
    """Raised when a session_id fails boundary validation."""


def _has_invisible(s: str) -> bool:
    """True if s contains a non-printable or invisible-but-printable char."""
    return not s.isprintable() or any(_is_strippable(ch) or ch in _INVISIBLE_PRINTABLE for ch in s)


def sanitize_session_id(raw: object) -> str | None:
    """Validate and canonicalize a session_id at the console boundary.

    Returns the canonical id, or None for null input. Raises
    SessionIdError(message) for every rejection class. The canonical id —
    not the raw one — becomes the FrequencyTracker key, the audit-event
    field, and the ALRT-02 alert-dedup pair, so visually identical variants
    must either be rejected (the invisible class) or collapse here (printable
    confusables) (PET-85).
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise SessionIdError("Must be a string or null")
    sid = raw.strip()
    if not sid:
        raise SessionIdError("Must be non-empty")
    if len(sid) > _MAX_SESSION_ID_LEN:
        raise SessionIdError(f"Exceeds {_MAX_SESSION_ID_LEN} character limit")
    if _has_invisible(sid):
        raise SessionIdError("Contains non-printable or invisible characters")
    canonical = unicodedata.normalize("NFKC", sid).translate(_HOMOGLYPH_TABLE).strip()
    if not canonical:
        raise SessionIdError("Must be non-empty")
    if _has_invisible(canonical):
        raise SessionIdError("Contains non-printable or invisible characters")
    if unicodedata.category(canonical[0]) in _COMBINING_CATEGORIES:
        raise SessionIdError("Begins with a combining mark")
    if len(canonical) > _MAX_SESSION_ID_LEN:
        raise SessionIdError(f"Exceeds {_MAX_SESSION_ID_LEN} character limit")
    return canonical
