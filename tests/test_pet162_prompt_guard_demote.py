"""PET-162 Part 1 regression: demote LlamaFirewall PromptGuard under code_generation.

Triage of the live gibson audit spools (2026-06-26) showed the on-state is very
quiet once the profile is correct, with a sharply-defined ML residual: one
`petasos.llamafirewall.prompt-guard` HIGH at p=0.998, on a `terminal` tool call
running a heredoc that *handled an attack string as data*. That is a coding
agent operating on injection-shaped text on its OWN outbound tool call, not
untrusted content being injected into the model: a false positive.

PromptGuard is a non-floor ML rule (`petasos.llamafirewall.prompt-guard`,
finding_type "injection", HIGH), structurally identical to the LLM Guard
injection verdict PET-135 already demoted. So the same proven lever applies: a
`severity_overrides` entry remaps it to LOW, which keeps the finding visible for
audit while it no longer blocks.

These tests pin both sides of the change with a deterministic stub standing in
for the (nondeterministic, model-gated) LlamaFirewall backend:
  * non-blocking + retained-at-LOW under code_generation (the fix), and
  * STILL blocking under general AND customer_service (no collateral disarm of
    the inbound-facing profile that exists precisely to distrust its input).

The injection-floor scoping that would also clear the residual *syntactic*
`ignore-previous` block (PET-162 Part 2) is a separate, net-new capability and
is out of scope here.
"""

from __future__ import annotations

from petasos._types import Direction, ScanFinding, ScanResult, Severity
from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline

# The real residual rule_id / severity / confidence from the triage.
_PROMPT_GUARD_RULE = "petasos.llamafirewall.prompt-guard"
_BLOCKING_SEVERITIES = {Severity.CRITICAL, Severity.HIGH}


def _blocking(findings: tuple[ScanFinding, ...]) -> list[ScanFinding]:
    return [f for f in findings if f.severity in _BLOCKING_SEVERITIES and f.finding_type != "pii"]


class _StubPromptGuardScanner:
    """Deterministic stand-in for the LlamaFirewall PromptGuard component.

    Emits exactly the finding that drove the live residual:
    petasos.llamafirewall.prompt-guard at HIGH / confidence 0.998. Mirrors the
    real `_COMPONENT_TAXONOMY` mapping (rule_id, "injection", Severity.HIGH) so
    this test does not need the gated PromptGuard 2 model installed.
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
                    message="LlamaFirewall PromptGuard injection verdict",
                    scanner_name=self.name,
                ),
            ),
            duration_ms=1.0,
        )


class TestPromptGuardDowngradedUnderCodegen:
    """The load-bearing change: PromptGuard's HIGH verdict is downgraded to a
    non-blocking LOW under code_generation, but kept (retained for audit)."""

    async def test_prompt_guard_is_nonblocking_under_codegen(self) -> None:
        pipe = Pipeline(
            config=PetasosConfig(profile_name="code_generation"),
            scanners=[_StubPromptGuardScanner()],
        )
        # Benign input on purpose: the Pipeline always runs MinimalScanner, so any
        # literal syntactic injection phrase (e.g. "ignore previous instructions")
        # would trip the unsuppressible syntactic floor and block regardless of
        # this profile. That residual is exactly PET-162 Part 2's scope, NOT Part 1.
        # Here we isolate the ML PromptGuard verdict (the stub) and prove the Part 1
        # demote alone makes a coder's own outbound tool call non-blocking.
        res = await pipe.inspect("git status && ls -la ~", direction="outbound")
        hit = [f for f in res.findings if f.rule_id == _PROMPT_GUARD_RULE]
        assert hit, "expected the prompt-guard finding to be retained for audit"
        assert hit[0].severity == Severity.LOW, "should be downgraded to LOW"
        assert not _blocking(res.findings), "downgraded finding must not block"
        assert res.safe is True


class TestPromptGuardStillBlocksElsewhere:
    """No collateral disarm: profiles that do NOT override prompt-guard must keep
    it blocking. customer_service is the inbound-facing profile that exists to
    distrust its input, so it is the important non-regression here."""

    async def test_prompt_guard_still_blocks_under_general(self) -> None:
        pipe = Pipeline(
            config=PetasosConfig(profile_name="general"),
            scanners=[_StubPromptGuardScanner()],
        )
        res = await pipe.inspect("anything", direction="outbound")
        blocking = _blocking(res.findings)
        assert any(f.rule_id == _PROMPT_GUARD_RULE for f in blocking), (
            "general must NOT downgrade prompt-guard; it should still block"
        )

    async def test_prompt_guard_still_blocks_under_customer_service_inbound(self) -> None:
        pipe = Pipeline(
            config=PetasosConfig(profile_name="customer_service"),
            scanners=[_StubPromptGuardScanner()],
        )
        res = await pipe.inspect("anything", direction="inbound")
        blocking = _blocking(res.findings)
        assert any(f.rule_id == _PROMPT_GUARD_RULE for f in blocking), (
            "customer_service must keep prompt-guard blocking on inbound (the threat surface)"
        )
        assert res.safe is False
