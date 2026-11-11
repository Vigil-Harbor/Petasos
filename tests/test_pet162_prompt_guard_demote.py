"""code_generation demotes PromptGuard's injection verdict to a non-blocking LOW.

PromptGuard emits ``petasos.promptguard.injection`` (finding_type ``injection``,
HIGH). ``severity_overrides`` remaps that rule to LOW under ``code_generation``,
which keeps the finding visible for audit while it no longer blocks. Profiles
that do not override it, including ``general`` and ``customer_service``, still
block.

These tests pin both sides with a deterministic stub. The injection-floor
scoping that relaxes outbound syntactic injection is a separate behavior and is
not what these tests isolate.
"""

from __future__ import annotations

from petasos.config.layers import resolve
from petasos.model import Direction, ScanFinding, ScanResult, Severity
from petasos.pipeline import Pipeline
from petasos.scanners.prompt_guard import _RULE_ID

# The rule_id the code_generation severity_override targets.
_PROMPT_GUARD_RULE = _RULE_ID
_BLOCKING_SEVERITIES = {Severity.CRITICAL, Severity.HIGH}


def _blocking(findings: tuple[ScanFinding, ...]) -> list[ScanFinding]:
    return [f for f in findings if f.severity in _BLOCKING_SEVERITIES and f.finding_type != "pii"]


class _StubPromptGuardScanner:
    """Deterministic stand-in for PromptGuard.

    Emits the production rule id at confidence 0.998. Needs no model installed.
    """

    name = "stub_promptguard"

    async def scan(
        self, text: str, *, direction: Direction = "inbound", session_id: str | None = None
    ) -> ScanResult:
        return ScanResult(
            scanner_name=self.name,
            findings=(
                ScanFinding(
                    rule_id=_PROMPT_GUARD_RULE,
                    finding_type="injection",
                    severity=Severity.HIGH,
                    confidence=0.998,
                    message="PromptGuard injection verdict",
                    scanner_name=self.name,
                ),
            ),
            duration_ms=1.0,
        )


class TestPromptGuardDowngradedUnderCodegen:
    """PromptGuard's HIGH verdict is downgraded to a non-blocking LOW under
    code_generation, and kept for audit."""

    async def test_prompt_guard_is_nonblocking_under_codegen(self) -> None:
        pipe = Pipeline(
            config=resolve({"role": "coding"}).config,
            scanners=[_StubPromptGuardScanner()],
        )
        # Benign input on purpose: the Pipeline always runs MinimalScanner, so a
        # literal syntactic injection phrase would trip the syntactic floor and
        # block regardless of this override.
        res = await pipe.inspect("git status && ls -la ~", direction="outbound")
        hit = [f for f in res.findings if f.rule_id == _PROMPT_GUARD_RULE]
        assert hit, "expected the prompt-guard finding to be retained for audit"
        assert hit[0].severity == Severity.LOW, "should be downgraded to LOW"
        assert not _blocking(res.findings), "downgraded finding must not block"
        assert res.safe is True


class TestPromptGuardStillBlocksElsewhere:
    """Profiles that do not override prompt-guard keep it blocking."""

    async def test_prompt_guard_still_blocks_under_general(self) -> None:
        pipe = Pipeline(
            config=resolve({"role": "general"}).config,
            scanners=[_StubPromptGuardScanner()],
        )
        res = await pipe.inspect("anything", direction="outbound")
        blocking = _blocking(res.findings)
        assert any(f.rule_id == _PROMPT_GUARD_RULE for f in blocking), (
            "general must NOT downgrade prompt-guard; it should still block"
        )
        assert res.safe is False

    async def test_prompt_guard_still_blocks_under_customer_service_inbound(self) -> None:
        pipe = Pipeline(
            config=resolve({"role": "support"}).config,
            scanners=[_StubPromptGuardScanner()],
        )
        res = await pipe.inspect("anything", direction="inbound")
        blocking = _blocking(res.findings)
        assert any(f.rule_id == _PROMPT_GUARD_RULE for f in blocking), (
            "customer_service must keep prompt-guard blocking on inbound (the threat surface)"
        )
        assert res.safe is False
