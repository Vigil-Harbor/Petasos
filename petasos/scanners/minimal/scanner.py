"""Run the syntactic rule families in order."""

from __future__ import annotations

import logging
import time

from petasos.model import (
    Direction,
    ScanFinding,
    ScanResult,
)
from petasos.normalize import normalize
from petasos.scanners.minimal.agent_directive import (
    _check_agent_directive,
    _rescan_agent_directive,
)
from petasos.scanners.minimal.command import _check_command
from petasos.scanners.minimal.decode import _check_encoded_payloads, _rescan_candidate
from petasos.scanners.minimal.encoding import _apply_escalation, _check_encoding
from petasos.scanners.minimal.injection import _check_injection
from petasos.scanners.minimal.role_switch import _check_role_switch, _rescan_role_switch
from petasos.scanners.minimal.structural import _check_json_depth, _check_structural
from petasos.scanners.minimal.taxonomy import _UNSUPPRESSIBLE_RULE_IDS

_logger = logging.getLogger("petasos.scanners.minimal")


class MinimalScanner:
    def __init__(
        self,
        *,
        max_payload_bytes: int = 524_288,
        max_json_depth: int = 10,
        suppress_rules: frozenset[str] = frozenset(),
        decode_encoded_payloads: bool = True,
    ) -> None:
        self._max_payload_bytes = max_payload_bytes
        self._max_json_depth = max_json_depth
        self._suppress_rules = suppress_rules - _UNSUPPRESSIBLE_RULE_IDS
        self._decode_encoded_payloads = decode_encoded_payloads

    def with_suppress_rules(self, additional: frozenset[str]) -> MinimalScanner:
        return MinimalScanner(
            max_payload_bytes=self._max_payload_bytes,
            max_json_depth=self._max_json_depth,
            suppress_rules=self._suppress_rules | additional,
            decode_encoded_payloads=self._decode_encoded_payloads,
        )

    def set_decode_encoded_payloads(self, flag: bool) -> None:
        """PET-126: flip the decode toggle in place (read live at scan time).

        The one targeted in-place mutation in the reconfigure path: MinimalScanner
        carries no session state, so a caller-supplied scanner keeps its other
        tunables (``max_payload_bytes``, ``max_json_depth``, ``suppress_rules``)
        and its object identity rather than being rebuilt (spec Decision 1).
        """
        self._decode_encoded_payloads = flag

    @property
    def name(self) -> str:
        return "minimal"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        start_time = time.perf_counter()
        try:
            findings = self._scan_impl(text, direction)
            elapsed = (time.perf_counter() - start_time) * 1000
            return ScanResult(
                scanner_name=self.name,
                findings=tuple(findings),
                duration_ms=elapsed,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start_time) * 1000
            return ScanResult(
                scanner_name=self.name,
                findings=(),
                duration_ms=elapsed,
                error=str(exc),
            )

    def _scan_impl(self, text: str, direction: Direction) -> list[ScanFinding]:
        findings: list[ScanFinding] = []

        # Step 1: Structural checks on raw input
        self._check_structural(text, findings)

        # Step 2: Normalize
        normalized = normalize(text)

        # Step 3: Injection patterns on normalized text + leet views (PET-97)
        # + separator views (PET-198) + composed views (PET-201). Named
        # families search canonical text plus separator views.
        injection_matched = self._check_injection(normalized, findings)

        # Step 4: Role-switch on canonical + separator views. Trigger and
        # grant must share one view (PET-211/212).
        self._check_role_switch(normalized, findings)

        # Step 4c: Agent-directed fetch/install directive (PET-154) — injection
        # class, direction-blind (Decision D2), exactly like Steps 3-4. The
        # boolean feeds the Step-7 escalation co-occurrence flag (Decision DS2).
        # Searches canonical + separator views (PET-211).
        agent_directive_matched = self._check_agent_directive(normalized, findings)

        # Step 4b: Destructive/obfuscated command family (PET-94) — outbound
        # only (Decision 2). The `direction` parameter goes from accepted-but-
        # ignored to used; the public scan() signature is unchanged. Searches
        # canonical + separator views (PET-211).
        if direction == "outbound":
            self._check_command(normalized, findings)
        elif direction not in ("inbound", "outbound"):
            # Silent-off is the worst failure mode for a security family: an
            # off-Literal direction from an untyped host (e.g. "OUTBOUND",
            # " outbound") would skip the family indistinguishably from clean
            # content. Emit a grep-able debug tripwire instead of hard-validating
            # — no other scanner validates direction, and raising would break
            # source-compatibility (Design §2).
            _logger.debug("command family skipped: unrecognized direction %r", direction)

        # Step 5: Decode-and-rescan reversible encodings (PET-98). Runs as its own
        # step (not inside the base64-in-text suppression guard), so the decoded
        # injection fires even when the LOW base64-in-text flag is suppressed.
        decoded_matched = self._check_encoded_payloads(text, normalized, findings)

        # Step 6: Encoding detection (LOW base64-in-text flag, etc.)
        self._check_encoding(text, normalized, findings)

        # Step 7: Invisible-chars escalation. OR the decode result and the
        # agent-directive result into the co-occurrence flag so a decode-only
        # injection or an agent-directive (plain or decoded) still escalates an
        # invisible-chars finding (consistency with the plain path; Decision DS2).
        self._apply_escalation(
            findings, injection_matched or decoded_matched or agent_directive_matched
        )

        return findings

    _check_structural = _check_structural

    _check_json_depth = _check_json_depth

    _check_injection = _check_injection

    _check_command = _check_command

    _check_role_switch = _check_role_switch

    _check_agent_directive = _check_agent_directive

    _check_encoded_payloads = _check_encoded_payloads

    _rescan_candidate = _rescan_candidate

    _rescan_role_switch = _rescan_role_switch

    _rescan_agent_directive = _rescan_agent_directive

    _check_encoding = _check_encoding

    _apply_escalation = _apply_escalation
