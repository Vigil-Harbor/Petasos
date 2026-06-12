"""Boundary validation for caller-supplied values entering the console API."""

from __future__ import annotations

import unicodedata

from petasos.normalize import _HOMOGLYPH_TABLE, _is_strippable

_MAX_SESSION_ID_LEN = 128

_COMBINING_CATEGORIES: frozenset[str] = frozenset({"Mn", "Mc", "Me"})


class SessionIdError(ValueError):
    """Raised when a session_id fails boundary validation."""


def _has_invisible(s: str) -> bool:
    """True if s contains a non-printable or invisible-but-printable char.

    The invisible-but-printable enumeration lives in
    petasos.normalize.INVISIBLE_NON_CF (canonical since PET-90) and is reached
    through _is_strippable, which covers Cf by category plus the enumerated
    non-Cf residue by membership.
    """
    return not s.isprintable() or any(_is_strippable(ch) for ch in s)


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
