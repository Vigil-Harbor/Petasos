"""Recognize role switches and capability grants in one view."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.scanners.minimal.views import (
    _decode_view_shape,
    _DecodeCandidate,
    _family_search_views,
)

if TYPE_CHECKING:
    from petasos.scanners.minimal.scanner import MinimalScanner


import re

from petasos.model import (
    NormalizedText,
    Position,
    ScanFinding,
    Severity,
)

# --- Role-switch detection ---

_ROLE_TRIGGERS: list[re.Pattern[str]] = [
    re.compile(r"you\s+are\s+a", re.IGNORECASE),
    re.compile(r"act\s+as", re.IGNORECASE),
    re.compile(r"pretend\s+you\s+are", re.IGNORECASE),
    re.compile(r"roleplay\s+as", re.IGNORECASE),
    # PET-93 additions: contraction and from-now-on forms. The [,;]? admits
    # the canonical comma form ("From now on, you will be DAN"); other
    # punctuation separators are documented INTENTIONAL.
    re.compile(r"pretend\s+to\s+be", re.IGNORECASE),
    re.compile(r"you['’ʼ]re\s+an?\b", re.IGNORECASE),
    re.compile(r"from\s+now\s+on[,;]?\s+you(?:['’ʼ]re|\s+(?:are|will\s+be))", re.IGNORECASE),
]

_ROLE_GRANTS: list[re.Pattern[str]] = [
    re.compile(r"no\s+restrictions", re.IGNORECASE),
    re.compile(r"no\s+limits", re.IGNORECASE),
    re.compile(r"without\s+filters", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
    re.compile(r"developer\s+mode", re.IGNORECASE),
    # PET-93 additions (mirrored in benign_corpus.SANCTIONED_NEW_GRANTS for
    # the MIGRATED attribution check).
    re.compile(r"without\s+(?:restrictions|limits)", re.IGNORECASE),
    re.compile(r"no\s+filters", re.IGNORECASE),
    re.compile(r"jailbreak\s+mode", re.IGNORECASE),
]


def _search_role_grant(text: str) -> re.Match[str] | None:
    """First ``_ROLE_GRANTS`` hit on one string."""
    for pat in _ROLE_GRANTS:
        grant_match = pat.search(text)
        if grant_match:
            return grant_match
    return None


def _same_view_role_switch(
    views: tuple[str, ...],
) -> tuple[bool, int, re.Match[str]] | None:
    """First same-view trigger+grant pair, else the first trigger-only view.

    Each view is searched alone. ``True`` means that view holds both halves
    (capability). ``False`` means no view held both, and this is the first
    trigger-only view. A later complete pair wins over an earlier trigger-only
    view. An earlier complete pair stops the walk. Returns None when no view
    has a trigger.
    """
    trigger_only: tuple[int, re.Match[str]] | None = None
    for idx, text in enumerate(views):
        trigger_match: re.Match[str] | None = None
        for pat in _ROLE_TRIGGERS:
            found = pat.search(text)
            if found:
                trigger_match = found
                break
        if trigger_match is None:
            continue
        if _search_role_grant(text) is not None:
            return (True, idx, trigger_match)
        if trigger_only is None:
            trigger_only = (idx, trigger_match)
    if trigger_only is None:
        return None
    only_idx, only_match = trigger_only
    return (False, only_idx, only_match)


def _check_role_switch(
    self: MinimalScanner, normalized: NormalizedText, findings: list[ScanFinding]
) -> None:
    cap_rule_id = "petasos.syntactic.injection.role-switch-capability"
    only_rule_id = "petasos.syntactic.injection.role-switch-only"

    # Same-view walk (PET-211/212): emit capability HIGH from the first
    # view that contains both a trigger and a grant. If no view contains
    # both, emit role-switch-only LOW from the first trigger-only view.
    # Never pair a trigger on one view with a grant on another. A
    # suppressed capability does not fall through to LOW. Span is the
    # canonical trigger only when index 0 itself is the winner.
    hit = _same_view_role_switch(_family_search_views(normalized))
    if hit is None:
        return
    complete, idx, trigger_match = hit
    if idx == 0:
        position: Position | None = Position(start=trigger_match.start(), end=trigger_match.end())
        matched_text: str | None = trigger_match.group()
    else:
        position = None
        matched_text = None

    if complete:
        if cap_rule_id not in self._suppress_rules:
            findings.append(
                ScanFinding(
                    rule_id=cap_rule_id,
                    finding_type="injection",
                    severity=Severity.HIGH,
                    confidence=1.0,
                    message="Role-switch with capability grant detected",
                    scanner_name=self.name,
                    position=position,
                    matched_text=matched_text,
                )
            )
    elif only_rule_id not in self._suppress_rules:
        findings.append(
            ScanFinding(
                rule_id=only_rule_id,
                finding_type="injection",
                severity=Severity.LOW,
                confidence=1.0,
                message="Role-switch trigger detected without capability grant",
                scanner_name=self.name,
                position=position,
                matched_text=matched_text,
            )
        )


def _rescan_role_switch(
    self: MinimalScanner,
    cand: _DecodeCandidate,
    findings: list[ScanFinding],
    seen_rule_ids: set[str],
    extra_views: tuple[str, ...] = (),
) -> bool:
    # Same-view walk as _check_role_switch: capability HIGH from the first
    # view that holds both halves, else role-switch-only LOW from the first
    # trigger-only view. Extras are separator-only. Span follows the
    # winning view via _decode_view_shape (blob keeps the carrier span).
    hit = _same_view_role_switch((cand.scan_text, *extra_views))
    if hit is None:
        return False
    complete, idx, trigger_match = hit
    position, matched_text = _decode_view_shape(cand, trigger_match, extra=idx > 0)
    if complete:
        rule_id = "petasos.syntactic.injection.role-switch-capability"
        severity = Severity.HIGH
        message = f"Role-switch with capability grant detected ({cand.carrier}-decoded)"
    else:
        rule_id = "petasos.syntactic.injection.role-switch-only"
        severity = Severity.LOW
        message = f"Role-switch trigger detected without capability grant ({cand.carrier}-decoded)"
    # PET-160 (D1/D3): one role-switch finding per rule_id per scan. Same
    # 10.0-weight / Tier-3-floor safety argument as the injection battery above —
    # N repeated carriers of one role-switch payload would otherwise stack to
    # terminate the session. Return True BEFORE the dedup so decoded_matched stays
    # set for the escalation co-occurrence flag even when the finding itself is
    # suppressed as a duplicate of one already emitted (plain-path or an earlier
    # candidate). Pinned by
    # test_decoded_duplicate_suppressed_still_escalates_cooccurrence.
    if rule_id in seen_rule_ids:
        return True
    seen_rule_ids.add(rule_id)
    findings.append(
        ScanFinding(
            rule_id=rule_id,
            finding_type="injection",
            severity=severity,
            confidence=1.0,
            message=message,
            scanner_name=self.name,
            position=position,
            matched_text=matched_text,
        )
    )
    return True
