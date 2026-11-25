"""Share normalized search views and decoded finding shapes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import re

    pass


from dataclasses import dataclass

from petasos.model import (
    NormalizedText,
    Position,
)


@dataclass(frozen=True)
class _DecodeCandidate:
    """A decoded plaintext to rescan through the injection/role-switch batteries.

    ``scan_text`` is what the patterns search. For a base64/hex blob,
    ``position``/``matched_text`` are the fixed raw-space blob span (consistent
    with base64-in-text / binary-content raw-space positions). For the ROT13
    view they are ``None`` and resolved per-match against ``origin_text`` (=
    ``normalized.normalized``) in normalized-space coordinates — consistent with
    the _check_injection leet path, which reports the original attack bytes in
    matched_text and names the decoded form in the message.
    """

    carrier: str
    scan_text: str
    position: Position | None
    matched_text: str | None
    origin_text: str


def _resolve_finding_shape(cand: _DecodeCandidate, m: re.Match[str]) -> tuple[Position, str]:
    """Resolve (position, matched_text) for a match on a decoded candidate.

    Blob candidates carry a fixed raw-space span; the ROT13 view resolves per
    match against its origin text in normalized-space coordinates.
    """
    if cand.position is not None:
        assert cand.matched_text is not None
        return cand.position, cand.matched_text
    return Position(start=m.start(), end=m.end()), cand.origin_text[m.start() : m.end()]


def _family_search_views(normalized: NormalizedText) -> tuple[str, ...]:
    """Canonical text, then unique separator extras."""
    views: list[str] = [normalized.normalized]
    seen = {normalized.normalized}
    for extra in normalized.separator_views:
        if extra not in seen:
            views.append(extra)
            seen.add(extra)
    return tuple(views)


def _extra_match_views(scan_text: str, nt: NormalizedText) -> tuple[str, ...]:
    """Unique separator/composed strings that differ from ``scan_text``."""
    extras: list[str] = []
    seen = {scan_text}
    for extra in (*nt.separator_views, *nt.composed_views):
        if extra not in seen:
            extras.append(extra)
            seen.add(extra)
    return tuple(extras)


def _separator_extras(scan_text: str, nt: NormalizedText) -> tuple[str, ...]:
    """Unique separator views that differ from ``scan_text``. No composed arm."""
    extras: list[str] = []
    seen = {scan_text}
    for extra in nt.separator_views:
        if extra not in seen:
            extras.append(extra)
            seen.add(extra)
    return tuple(extras)


def _decode_view_shape(
    cand: _DecodeCandidate,
    m: re.Match[str],
    *,
    extra: bool,
) -> tuple[Position | None, str | None]:
    """Return a carrier span or omit offsets for a non-length-preserving view."""
    if extra and cand.position is None:
        return None, None
    return _resolve_finding_shape(cand, m)
