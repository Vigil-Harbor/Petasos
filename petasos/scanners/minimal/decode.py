"""Decode bounded carriers and rescan their plaintext."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.scanners.minimal.injection import _INJECTION_ANCHOR, _INJECTION_PATTERNS
from petasos.scanners.minimal.views import (
    _decode_view_shape,
    _DecodeCandidate,
    _extra_match_views,
    _separator_extras,
)

if TYPE_CHECKING:
    from petasos.scanners.minimal.scanner import MinimalScanner


import base64
import binascii
import re

from petasos.model import (
    NormalizedText,
    Position,
    ScanFinding,
    Severity,
)
from petasos.normalize import normalize

# --- Decode-and-rescan (PET-98) ---
#
# Separate detector battery with lower floors than _BASE64_PATTERN's 40-char
# LOW-flag threshold (Decision 6): decode + injection-match is self-validating, so
# a short blob that does not decode to an injection phrase emits nothing and adds
# no false positive. Span discovery runs off the base64 detector only — the hex
# alphabet [0-9a-fA-F] is a strict subset of the base64 alphabet at the same
# 16-char floor, so every hex run is contained in a base64 span and each physical
# span costs exactly one budget slot while being attempted under both codecs
# (Decision 4 / § Design step 2).
_BASE64_BLOB_DETECTOR = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
_HEX_BLOB_DETECTOR = re.compile(r"(?:[0-9a-fA-F]{2}){8,}")
_ROT13_TABLE = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm",
)
_DECODE_MAX_BLOBS = 16  # per-input detected-span attempt cap (base64+hex)
_DECODE_MAX_BYTES = 8192  # per-blob decoded-size cap (scan first N bytes)
_DECODE_SNIPPET_CAP = 80  # message snippet cap (matches leet [:80])


def _try_b64decode(span: str) -> bytes | None:
    try:
        return base64.b64decode(span, validate=True)
    except (binascii.Error, ValueError):
        return None


def _try_hexdecode(span: str) -> bytes | None:
    try:
        return bytes.fromhex(span)
    except ValueError:
        return None


def _decode_bytes(raw: bytes) -> str | None:
    """Bytes → text under Decision 5's size-cap-aware rule.

    Under the per-blob cap: strict UTF-8 — the FP discipline that keeps binary
    assets (image/font data, random tokens, gzip) quiet. Over the cap: decode the
    first cap bytes with ``errors="ignore"`` so a code point split by the hard
    byte truncation drops only its trailing partial sequence, never an in-prefix
    injection. The ``errors=`` divergence is deliberate and applies only to the
    truncated tail.
    """
    if len(raw) <= _DECODE_MAX_BYTES:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return raw[:_DECODE_MAX_BYTES].decode("utf-8", errors="ignore")


def _check_encoded_payloads(
    self: MinimalScanner,
    raw_text: str,
    normalized: NormalizedText,
    findings: list[ScanFinding],
) -> bool:
    """Decode reversible-encoding blobs and rescan the plaintext (PET-98).

    Locates base64/hex blob spans in the raw text and computes one ROT13 view
    of the normalized text, decodes each under strict DoS bounds (Decision 4),
    then runs the injection battery (anchor-gated) and the role-switch battery
    (unconditional, Decision 2 / § step 5) over every decoded candidate. A
    match emits the underlying injection / role-switch finding at its native
    severity, reusing the existing rule_id — no new rule_id is minted. Runs
    independently of base64-in-text suppression (Decision 3). Returns whether
    any candidate matched (feeds the escalation co-occurrence flag).
    """
    if not self._decode_encoded_payloads:
        return False

    candidates: list[_DecodeCandidate] = []

    # base64-detector spans are the physical spans (§ Design step 2): the hex
    # alphabet is a strict subset of the base64 alphabet at the same 16-char
    # floor, so every hex run is contained in a base64 span. One budget slot
    # per physical span; both codecs are attempted per span (<=2 decodes), so
    # a delimited hex blob — which the base64 detector also matches — still
    # decodes. The cap counts attempted spans, not successful decodes, so a
    # malformed-blob flood stays bounded.
    attempts = 0
    for m in _BASE64_BLOB_DETECTOR.finditer(raw_text):
        if attempts >= _DECODE_MAX_BLOBS:
            break
        attempts += 1
        span = m.group()
        blob_position = Position(start=m.start(), end=m.end())
        blob_matched = span[:_DECODE_SNIPPET_CAP]
        for carrier, raw in (("base64", _try_b64decode(span)), ("hex", _try_hexdecode(span))):
            if raw is None:
                continue
            decoded = _decode_bytes(raw)
            if decoded is None:
                continue
            candidates.append(_DecodeCandidate(carrier, decoded, blob_position, blob_matched, ""))

    # ROT13: a single always-on, length-preserving view, bounded to the
    # per-blob byte cap (Decision 4) so the translate + scan stays O(cap).
    # ROT13 has no structural signature, so it is decoded unconditionally as
    # one extra view rather than detected (Decision 7). Offsets map 1:1 onto
    # normalized.normalized, so a match span there is valid in normalized space.
    rot13_view = normalized.normalized[:_DECODE_MAX_BYTES].translate(_ROT13_TABLE)
    candidates.append(_DecodeCandidate("rot13", rot13_view, None, None, normalized.normalized))

    # PET-160: seed the per-rule_id cap from the Step-3/4 findings, which MUST
    # run before this step, so the cap is cross-path (plain + decoded collapse to
    # one finding per rule_id). Reordering Step 5 ahead of the injection/role-
    # switch batteries would seed an empty set and silently un-cap the plain-vs-
    # decoded pair (the plain batteries do not consult seen_rule_ids).
    # test_decode_dedups_against_plain_path pins the behavior; this comment pins
    # the why. The set is mutated in place by the per-candidate calls, so it also
    # collapses duplicates across decoded candidates within the same scan.
    seen_rule_ids = {f.rule_id for f in findings}
    matched = False
    for cand in candidates:
        if self._rescan_candidate(cand, findings, seen_rule_ids):
            matched = True
    return matched


def _rescan_candidate(
    self: MinimalScanner,
    cand: _DecodeCandidate,
    findings: list[ScanFinding],
    seen_rule_ids: set[str],
) -> bool:
    matched = False
    nt = normalize(cand.scan_text)
    extras = _extra_match_views(cand.scan_text, nt)
    separator_extras = _separator_extras(cand.scan_text, nt)
    decode_views: tuple[tuple[str, bool], ...] = (
        (cand.scan_text, False),
        *tuple((v, True) for v in extras),
    )

    # Injection battery — anchor-gated per view exactly as _check_injection
    # gates candidates. Extra separator/composed views of the decoded text
    # (PET-201) are searched after scan_text. The suppress check is omitted
    # because injection rule_ids are stripped from _suppress_rules at
    # construction (Decision 3).
    gated = [(text, extra) for text, extra in decode_views if _INJECTION_ANCHOR.search(text)]
    if gated:
        for slug, pattern in _INJECTION_PATTERNS:
            for text, extra in gated:
                m = pattern.search(text)
                if m is None:
                    continue
                # PET-160 (D1/D2/D3): one injection finding per rule_id per scan.
                # injection.* carries the 10.0 frequency weight (frequency.py), so N
                # repeated base64/hex carriers of one slug would otherwise emit N
                # findings -> the 50.0 Tier-3 floor -> terminate a session from a
                # single crafted payload. matched is set BEFORE the dedup continue
                # (D3): a decoded injection WAS present even when its finding is
                # suppressed, so the escalation co-occurrence flag must still see it.
                # The guard keys on the specific rule_id and the loop does NOT break
                # across slugs, so distinct slugs on one candidate each still fire
                # once (per-append, not whole-rescan; cross-path + cross-candidate).
                # Pinned by tests/adversarial/syntactic/test_decode_rescan_dedup.py.
                matched = True
                rule_id = f"petasos.syntactic.injection.{slug}"
                if rule_id in seen_rule_ids:
                    break
                seen_rule_ids.add(rule_id)
                position, matched_text = _decode_view_shape(cand, m, extra=extra)
                snippet = m.group()[:_DECODE_SNIPPET_CAP]
                findings.append(
                    ScanFinding(
                        rule_id=rule_id,
                        finding_type="injection",
                        severity=Severity.HIGH,
                        confidence=1.0,
                        message=(
                            f"Injection pattern matched: {slug} "
                            f"({cand.carrier}-decoded: {snippet!r})"
                        ),
                        scanner_name=self.name,
                        position=position,
                        matched_text=matched_text,
                    )
                )
                break

    # Role-switch battery — NOT injection-anchor-gated (the injection anchor
    # is not a superset of the role-switch triggers, so gating here would
    # drop a decoded "act as DAN with no restrictions"). At most one finding
    # per candidate, mirroring the live single-emit _check_role_switch.
    if self._rescan_role_switch(cand, findings, seen_rule_ids, separator_extras):
        matched = True

    # Agent-directive battery (PET-154 / Decision D6) — runs its OWN
    # _AGENT_DIRECTIVE_ANCHOR gate (inside the shared helper), not the
    # injection anchor (which is not a superset of the agent markers),
    # mirroring how _rescan_role_switch runs unconditionally here.
    if self._rescan_agent_directive(cand, findings, nt):
        matched = True

    return matched
