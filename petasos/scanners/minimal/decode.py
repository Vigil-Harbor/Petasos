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

# See docs/architecture/rationale.md, "Decoded finding budgets".
_BASE64_BLOB_DETECTOR = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
_HEX_BLOB_DETECTOR = re.compile(r"(?:[0-9a-fA-F]{2}){8,}")
_ROT13_TABLE = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm",
)
_DECODE_MAX_BLOBS = 16
_DECODE_MAX_BYTES = 8192
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
    """Decode a bounded byte prefix, rejecting invalid complete UTF-8."""
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
    """Rescan bounded reversible carriers and report injection co-occurrence.

    See docs/architecture/rationale.md, "Decoded finding budgets"."""
    if not self._decode_encoded_payloads:
        return False

    candidates: list[_DecodeCandidate] = []

    # See docs/architecture/rationale.md, "Decoded finding budgets".
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

    # See docs/architecture/rationale.md, "Decoded finding budgets".
    rot13_view = normalized.normalized[:_DECODE_MAX_BYTES].translate(_ROT13_TABLE)
    candidates.append(_DecodeCandidate("rot13", rot13_view, None, None, normalized.normalized))

    # See docs/architecture/rationale.md, "Decoded finding budgets".
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

    # See docs/architecture/rationale.md, "Decoded finding budgets".
    gated = [(text, extra) for text, extra in decode_views if _INJECTION_ANCHOR.search(text)]
    if gated:
        for slug, pattern in _INJECTION_PATTERNS:
            for text, extra in gated:
                m = pattern.search(text)
                if m is None:
                    continue
                # See docs/architecture/rationale.md, "Decoded finding budgets".
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

    # See docs/architecture/rationale.md, "Decoded finding budgets".
    if self._rescan_role_switch(cand, findings, seen_rule_ids, separator_extras):
        matched = True

    # See docs/architecture/rationale.md, "Decoded finding budgets".
    if self._rescan_agent_directive(cand, findings, nt):
        matched = True

    return matched
