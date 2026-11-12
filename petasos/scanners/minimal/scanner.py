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
    """Detect syntactic threats without optional scanner dependencies."""

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
        """Return a copy with additional suppressions, preserving unsuppressible rules."""
        return MinimalScanner(
            max_payload_bytes=self._max_payload_bytes,
            max_json_depth=self._max_json_depth,
            suppress_rules=self._suppress_rules | additional,
            decode_encoded_payloads=self._decode_encoded_payloads,
        )

    def set_decode_encoded_payloads(self, flag: bool) -> None:
        """Set the live decode toggle without replacing the scanner."""
        self._decode_encoded_payloads = flag

    @property
    def name(self) -> str:
        """Return the stable scanner id."""
        return "minimal"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        """Return syntactic findings or an error result without raising."""
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

        self._check_structural(text, findings)

        normalized = normalize(text)

        injection_matched = self._check_injection(normalized, findings)

        self._check_role_switch(normalized, findings)

        agent_directive_matched = self._check_agent_directive(normalized, findings)

        if direction == "outbound":
            self._check_command(normalized, findings)
        elif direction not in ("inbound", "outbound"):
            # See docs/architecture/rationale.md, "Invalid scan directions".
            _logger.debug("command family skipped: unrecognized direction %r", direction)

        # Decode detection is independent of suppression of the LOW base64 flag.
        decoded_matched = self._check_encoded_payloads(text, normalized, findings)

        self._check_encoding(text, normalized, findings)

        # Decoded injections and agent directives also establish invisible-character co-occurrence.
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
