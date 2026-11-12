"""A deterministic personal-information check for sandbox dashboard evidence.

The real dashboard calls the real Try it API and pipeline. Only detection is
stood in, so the harness needs neither optional packages nor a model download.
"""

from __future__ import annotations

import os
from pathlib import Path

from petasos.hermes.dashboard import playground
from petasos.model import Direction, Position, ScanFinding, ScanResult, Severity
from petasos.scanners.registry import ScannerSpec


class PersonalInformation:
    """Provide Personal Information test data."""

    name = "presidio"

    def availability(self) -> tuple[bool, str | None, str | None]:
        """Provide availability for the test fixture."""
        return True, None, None

    async def scan(
        self, text: str, *, direction: Direction = "inbound", session_id: str | None = None
    ) -> ScanResult:
        """Supply the configured scanner response for this fixture."""
        address = "someone@example.org"
        start = text.find(address)
        findings: tuple[ScanFinding, ...] = ()
        if start >= 0:
            findings = (
                ScanFinding(
                    rule_id="petasos.presidio.email_address",
                    finding_type="pii",
                    severity=Severity.HIGH,
                    confidence=1.0,
                    message="Personal information.",
                    scanner_name=self.name,
                    position=Position(start, start + len(address)),
                ),
            )
        return ScanResult(scanner_name=self.name, findings=findings, duration_ms=0)


def activate() -> None:
    """Provide activate for the test fixture."""
    root = Path(os.environ["PETASOS_SANDBOX_ROOT"]).resolve()
    home = Path(os.environ["HERMES_HOME"]).resolve()
    if root not in home.parents or root not in Path(__file__).resolve().parents:
        raise RuntimeError("The trial fixture must be copied into a sandbox home.")
    vars(playground)["REGISTRY"] = (
        ScannerSpec(
            id="presidio",
            label="Presidio",
            extra="presidio",
            detects=frozenset({"pii"}),
            section="presidio",
            default_enabled="auto",
            build=lambda _section, _context: PersonalInformation(),
        ),
    )
