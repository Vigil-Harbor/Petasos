"""PET-112: egress-scoped PII enforcement in the reference plugin.

Covers the tool-class x finding-type x severity x degraded matrix for
``_pre_tool_call`` / ``_fallback_pre_tool_call``, the ``param_scan_degraded``
guard signal, and the ``egress_sink_tools`` config wiring. Backend-free — no
Presidio / no ML pipeline; the guard is stubbed and the pipeline's ``inspect``
is monkeypatched to return crafted results.

Regression for PET-112: an agent's own internal write/terminal/edit of PII must
not be hard-blocked; outbound secrets through egress sinks still are.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from petasos import (
    FrequencyTracker,
    GuardResult,
    PetasosConfig,
    Pipeline,
    PipelineResult,
    ScanFinding,
    ScanResult,
    Severity,
    ToolCallGuard,
)
from petasos.normalize import canonicalize_tool_name

if TYPE_CHECKING:
    import types


_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)

# A small egress set for the enforcement tests — distinct from the config default
# so the tests pin behavior on membership, not on the default names.
_EGRESS = frozenset({"send_email", "http_request", "clipboard_write"})


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PETASOS_LICENSE_KEY", "PETASOS_SESSION_SECRET", "PETASOS_HASH_KEY"):
        monkeypatch.delenv(var, raising=False)


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet112", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Finding + GuardResult builders
# ---------------------------------------------------------------------------


def _pii(severity: Severity, *, confidence: float = 0.9) -> ScanFinding:
    return ScanFinding(
        rule_id="petasos.presidio.person",
        finding_type="pii",
        severity=severity,
        confidence=confidence,
        message=f"PII detected: PERSON ({severity.name})",
        scanner_name="presidio",
    )


def _non_pii(finding_type: str, severity: Severity = Severity.HIGH) -> ScanFinding:
    return ScanFinding(
        rule_id=f"petasos.{finding_type or 'unknown'}.x",
        finding_type=finding_type,
        severity=severity,
        confidence=0.9,
        message=f"{finding_type or 'untyped'} finding",
        scanner_name="minimal",
    )


def _guard_result(
    *,
    findings: tuple[ScanFinding, ...] = (),
    tier: str = "none",
    allowed: bool = True,
    reason: str = "allowed",
    param_scan_unsafe: bool = False,
    param_scan_degraded: bool = False,
) -> GuardResult:
    return GuardResult(
        allowed=allowed,
        reason=reason,
        findings=findings,
        tier=tier,
        param_scan_unsafe=param_scan_unsafe,
        param_scan_degraded=param_scan_degraded,
    )


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    guard_result: GuardResult,
    *,
    egress: frozenset[str] = _EGRESS,
    args: dict[str, object] | None = None,
) -> Any:
    """Drive ``_pre_tool_call`` against a crafted GuardResult on a freshly imported,
    post-init, armed plugin module. Returns the block dict or None."""
    ref = _import_reference_plugin()
    monkeypatch.setattr(ref, "_initialized", True)
    monkeypatch.setattr(ref, "_init_error", None)
    monkeypatch.setattr(ref, "_is_armed", lambda: True)
    monkeypatch.setattr(ref, "_egress_sink_tools", egress)
    stub_guard = type("G", (), {"evaluate": lambda self, *a, **k: None})()
    monkeypatch.setattr(ref, "_guard", stub_guard)
    monkeypatch.setattr(ref, "_run_async", lambda coro: guard_result)
    return ref._pre_tool_call(tool_name, args or {"text": "x"}, task_id="s1")


# ---------------------------------------------------------------------------
# PII gate: internal tools exempt, egress sinks enforced
# ---------------------------------------------------------------------------


def test_pii_finding_does_not_block_internal_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    # The literal regression (MEDIUM) plus the live post-PET-109 friction (HIGH/CRITICAL):
    # a PII finding on an internal tool never blocks.
    for tool in ("write_file", "terminal", "execute_code"):
        for sev in (Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL):
            unsafe = sev in (Severity.HIGH, Severity.CRITICAL)
            gr = _guard_result(findings=(_pii(sev),), param_scan_unsafe=unsafe)
            assert _drive(monkeypatch, tool, gr) is None, f"{tool}/{sev.name} should not block"


def test_pii_finding_blocks_egress_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _drive(
        monkeypatch,
        "send_email",
        _guard_result(findings=(_pii(Severity.CRITICAL),), param_scan_unsafe=True),
    )
    assert out is not None and out["action"] == "block"
    assert out["message"].startswith("Security finding (PII, CRITICAL)")

    out_high = _drive(
        monkeypatch,
        "http_request",
        _guard_result(findings=(_pii(Severity.HIGH),), param_scan_unsafe=True),
    )
    assert out_high is not None and out_high["action"] == "block"
    assert out_high["message"].startswith("Security finding (PII, HIGH)")


# ---------------------------------------------------------------------------
# PET-118: classification canonicalizes to the guard's shared form
# ---------------------------------------------------------------------------

# Egress set holding only the canonical form of "send_email" (already canonical) — the
# variant tests prove a namespaced/cased/homoglyph name still matches it.
_SEND_EMAIL_CANON = frozenset({canonicalize_tool_name("send_email")})


def test_namespaced_egress_variant_still_pii_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-118: a namespaced / cased / homoglyph variant of a configured egress
    # tool still trips branch-3 PII-egress blocking (canonical membership, not raw match).
    variants = (
        "mcp__acme__Send_Email",  # namespace prefix + mixed case
        "SEND_EMAIL",  # upper case
        "sеnd_email",  # Cyrillic 'е' (U+0435) homoglyph -> folds to ASCII 'e'
    )
    for variant in variants:
        out = _drive(
            monkeypatch,
            variant,
            _guard_result(findings=(_pii(Severity.CRITICAL),), param_scan_unsafe=True),
            egress=_SEND_EMAIL_CANON,
        )
        assert out is not None and out["action"] == "block", f"{variant!r} should block"
        assert out["message"].startswith("Security finding (PII, CRITICAL)")


def test_namespaced_readonly_variant_not_dangerous(monkeypatch: pytest.MonkeyPatch) -> None:
    # PET-118: case/homoglyph/single-`__`-namespace variants of READ_ONLY members canonicalize
    # back into the read-only set -> not dangerous -> no false-positive quarantine.
    ref = _import_reference_plugin()
    # (a) bare double-`__` namespace over a bare read-only member (web_search).
    assert ref._is_dangerous("mcp__vigil__web_search") is False
    # (b) a case variant of an actual single-underscore mcp_* member.
    assert ref._is_dangerous("MCP_VIGIL_HARBOR_MEMORY_SEARCH") is False
    # _pre_tool_call short-circuits to None at the read-only gate, even with CRITICAL PII.
    out = _drive(
        monkeypatch,
        "mcp__vigil__web_search",
        _guard_result(findings=(_pii(Severity.CRITICAL),), param_scan_unsafe=True),
    )
    assert out is None


def test_readonly_wireform_limitation() -> None:
    # PET-118 D-READONLY-FORMS (honest pin): the hyphenated double-`__` wire form does NOT
    # canonicalize onto the stored single-underscore member, so it currently reads dangerous.
    # Deferred to the D-VERIFY follow-up (PET-121); update this test if the stored forms align.
    ref = _import_reference_plugin()
    assert ref._is_dangerous("mcp__vigil-harbor__memory_search") is True


def test_alias_collapse_does_not_reclassify(monkeypatch: pytest.MonkeyPatch) -> None:
    # PET-118 D-CANON: classification skips the guard's alias layer. web_search aliases to
    # `browser` alongside http_request/web_fetch, but classification must NOT pull web_search
    # into the egress set nor out of read-only.
    ref = _import_reference_plugin()
    egress_canon = frozenset(canonicalize_tool_name(t) for t in PetasosConfig().egress_sink_tools)
    assert "http_request" in egress_canon  # sanity: the alias sibling IS a default egress sink
    monkeypatch.setattr(ref, "_egress_sink_tools", egress_canon)
    assert ref._is_egress_sink("web_search") is False
    assert ref._is_dangerous("web_search") is False


@pytest.mark.parametrize(
    "raw",
    [
        "send_email",
        "SEND_EMAIL",
        "mcp__acme__send_email",
        "sеnd_email",  # Cyrillic 'е' homoglyph
        "web_search",
        "mcp__vigil__web_search",
        "read_file",
        "write_file",
        "",
    ],
)
def test_classification_shares_guard_canonical_form(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    # PET-118: _is_egress_sink / _is_dangerous agree exactly with canonical membership — no
    # divergent normalizer hides between the classifier and canonicalize_tool_name.
    ref = _import_reference_plugin()
    egress_canon = frozenset(canonicalize_tool_name(t) for t in PetasosConfig().egress_sink_tools)
    monkeypatch.setattr(ref, "_egress_sink_tools", egress_canon)
    canon = canonicalize_tool_name(raw)
    assert ref._is_egress_sink(raw) == (canon in egress_canon)
    assert ref._is_dangerous(raw) == (canon not in ref._READ_ONLY_CANON)


# ---------------------------------------------------------------------------
# Non-PII finding types block all dangerous tools (D3 / D-EGRESS partition)
# ---------------------------------------------------------------------------


def test_injection_still_blocks_all_dangerous_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    for tool in ("write_file", "terminal", "send_email"):
        gr = _guard_result(
            findings=(_non_pii("injection", Severity.HIGH),), param_scan_unsafe=True
        )
        out = _drive(monkeypatch, tool, gr)
        assert out is not None and out["action"] == "block", f"{tool} should block injection"
        assert out["message"].startswith("Parameter scan flagged unsafe content")


def test_non_pii_types_block_all_dangerous(monkeypatch: pytest.MonkeyPatch) -> None:
    # Locks the `finding_type != "pii"` partition across the full non-PII space, including
    # llm-guard `credential` and an empty finding_type (which also proves no crash).
    for ftype in ("command", "credential", ""):
        gr = _guard_result(findings=(_non_pii(ftype, Severity.HIGH),), param_scan_unsafe=True)
        out = _drive(monkeypatch, "write_file", gr)
        assert out is not None and out["action"] == "block", f"finding_type={ftype!r} should block"
        assert out["message"].startswith("Parameter scan flagged unsafe content")


# ---------------------------------------------------------------------------
# Ordinal severity gate (D-CAVEAT) at both plugin sites
# ---------------------------------------------------------------------------


def test_block_threshold_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate the ordinal gate on an egress tool so egress-scoping doesn't mask it.
    for sev in (Severity.MEDIUM, Severity.LOW, Severity.INFO):
        gr = _guard_result(findings=(_pii(sev),))
        assert _drive(monkeypatch, "send_email", gr) is None, f"{sev.name} must not block"
    for sev in (Severity.HIGH, Severity.CRITICAL):
        gr = _guard_result(findings=(_pii(sev),), param_scan_unsafe=True)
        out = _drive(monkeypatch, "send_email", gr)
        assert out is not None and out["action"] == "block", f"{sev.name} must block"

    # Lone CRITICAL non-PII on an internal tool → blocked (closes the inverted-comparison hole
    # where the old lexicographic compare let a lone CRITICAL through).
    out_crit = _drive(
        monkeypatch,
        "write_file",
        _guard_result(
            findings=(_non_pii("injection", Severity.CRITICAL),), param_scan_unsafe=True
        ),
    )
    assert out_crit is not None and out_crit["action"] == "block"


def test_fallback_ordinal_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _import_reference_plugin()

    def _make_scanner(finding: ScanFinding | None) -> object:
        class _Stub:
            name = "minimal"

            async def scan(
                self, text: str, *, direction: str = "inbound", session_id: str | None = None
            ) -> ScanResult:
                return ScanResult(scanner_name="minimal", findings=(finding,) if finding else ())

        return _Stub()

    monkeypatch.setattr(ref, "_run_async", lambda coro: asyncio.run(coro))

    # Lone CRITICAL syntactic finding → blocked.
    crit_scanner = _make_scanner(_non_pii("injection", Severity.CRITICAL))
    monkeypatch.setattr(ref, "_get_fallback_scanner", lambda: crit_scanner)
    out = ref._fallback_pre_tool_call("write_file", {"text": "x"}, "s1")
    assert out is not None and out["action"] == "block"
    assert out["message"].startswith("Security scan (init in progress)")

    # MEDIUM finding → no block (ordinal gate).
    med_scanner = _make_scanner(_non_pii("injection", Severity.MEDIUM))
    monkeypatch.setattr(ref, "_get_fallback_scanner", lambda: med_scanner)
    assert ref._fallback_pre_tool_call("write_file", {"text": "x"}, "s1") is None


# ---------------------------------------------------------------------------
# Robustness: unknown severity, empty findings
# ---------------------------------------------------------------------------


class _UnknownSeverity:
    name = "UNKNOWN"
    value = "unknown"


def test_unknown_severity_and_empty_findings_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    unknown = ScanFinding(
        rule_id="x",
        finding_type="pii",
        severity=cast("Severity", _UnknownSeverity()),
        confidence=0.9,
        message="weird",
        scanner_name="presidio",
    )
    # Unknown severity sorts to 999 → never blocks, on internal and egress tools, no crash.
    for tool in ("write_file", "send_email"):
        gr = _guard_result(findings=(unknown,), param_scan_unsafe=True)
        assert _drive(monkeypatch, tool, gr) is None, f"unknown severity must not block on {tool}"

    # Empty findings + not degraded → None (proves _worst/min is never reached empty).
    assert _drive(monkeypatch, "write_file", _guard_result(findings=())) is None


# ---------------------------------------------------------------------------
# Degraded-mode blocking (D-DEGRADED) — independent of finding type
# ---------------------------------------------------------------------------


def test_degraded_blocks_internal_even_with_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    # (a) internal tool, degraded, no findings → block (fail-mode policy).
    out_a = _drive(
        monkeypatch,
        "write_file",
        _guard_result(param_scan_unsafe=True, param_scan_degraded=True),
    )
    assert out_a is not None and out_a["action"] == "block"
    assert "degraded" in out_a["message"].lower()

    # (b) internal tool, degraded + HIGH/CRITICAL PII → block (degraded wins over egress-scoping).
    out_b = _drive(
        monkeypatch,
        "write_file",
        _guard_result(
            findings=(_pii(Severity.CRITICAL),), param_scan_unsafe=True, param_scan_degraded=True
        ),
    )
    assert out_b is not None and out_b["action"] == "block"
    assert "degraded" in out_b["message"].lower()

    # (c) not degraded, only HIGH PII on internal → allowed (degraded did not fire).
    out_c = _drive(
        monkeypatch,
        "write_file",
        _guard_result(findings=(_pii(Severity.HIGH),), param_scan_unsafe=True),
    )
    assert out_c is None


# ---------------------------------------------------------------------------
# Read-only + escalation paths unchanged
# ---------------------------------------------------------------------------


def test_readonly_tool_never_content_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    out_pii = _drive(
        monkeypatch,
        "read_file",
        _guard_result(findings=(_pii(Severity.CRITICAL),), param_scan_unsafe=True),
    )
    assert out_pii is None
    out_degraded = _drive(
        monkeypatch,
        "read_file",
        _guard_result(param_scan_unsafe=True, param_scan_degraded=True),
    )
    assert out_degraded is None


def test_tier3_and_not_allowed_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    # tier3 is checked before _is_dangerous: even a read-only tool is blocked (proves the
    # new read-only early return does not shadow the escalation blocks).
    out_t3 = _drive(
        monkeypatch,
        "read_file",
        _guard_result(tier="tier3", allowed=False, reason="session terminated (tier3)"),
    )
    assert out_t3 is not None and out_t3["action"] == "block"
    assert "Tier 3" in out_t3["message"]

    out_blocked = _drive(
        monkeypatch,
        "write_file",
        _guard_result(allowed=False, reason="tier2: tool calls blocked"),
    )
    assert out_blocked is not None and out_blocked["action"] == "block"
    assert out_blocked["message"] == "tier2: tool calls blocked"


# ---------------------------------------------------------------------------
# egress_sink_tools config field
# ---------------------------------------------------------------------------


def test_egress_classification_config_roundtrip() -> None:
    cfg = PetasosConfig()
    assert isinstance(cfg.egress_sink_tools, tuple)
    assert len(cfg.egress_sink_tools) > 0  # frozen non-empty default

    # to_dict emits a list; from_dict coerces back to a tuple.
    d = cfg.to_dict()
    assert isinstance(d["egress_sink_tools"], list)
    assert PetasosConfig.from_dict(d).egress_sink_tools == cfg.egress_sink_tools

    # Empty tuple is accepted and round-trips.
    empty = PetasosConfig(egress_sink_tools=())
    assert empty.egress_sink_tools == ()
    assert PetasosConfig.from_dict(empty.to_dict()).egress_sink_tools == ()

    # Bare string is rejected (would char-explode into a per-character set).
    with pytest.raises(ValueError):
        PetasosConfig(egress_sink_tools="send_email")  # type: ignore[arg-type]
    # Per-entry validation.
    with pytest.raises(ValueError):
        PetasosConfig(egress_sink_tools=("",))
    with pytest.raises(ValueError):
        PetasosConfig(egress_sink_tools=(1,))  # type: ignore[arg-type]


def test_egress_from_dict_ingestion() -> None:
    cfg = PetasosConfig.from_dict({"egress_sink_tools": ["send_email"]})
    assert cfg.egress_sink_tools == ("send_email",)
    with pytest.raises(ValueError):
        PetasosConfig.from_dict({"egress_sink_tools": "send_email"})
    with pytest.raises(ValueError):
        PetasosConfig.from_dict({"egress_sink_tools": ["a", ""]})


def _prep_init(mod: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_initialized", False)
    monkeypatch.setattr(mod, "_init_error", None)
    monkeypatch.setattr(mod, "_pipeline", None)
    monkeypatch.setattr(mod, "_guard", None)


def test_deferred_init_populates_egress_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # Live from_dict path: _config is the raw dict, not a tuple kwarg.
    ref = _import_reference_plugin()
    _prep_init(ref, monkeypatch)
    monkeypatch.setattr(ref, "_config", {"egress_sink_tools": ["send_email"]})
    ref._deferred_init()
    # PET-118: the set is now the CANONICALIZED config (equal to the literals today because
    # the defaults are already canonical, but the assertion states the post-PET-118 contract
    # and catches a future non-canonical default).
    assert ref._egress_sink_tools == frozenset(canonicalize_tool_name(t) for t in ["send_email"])

    # Default config → the non-empty default set (catches the F-4 global-shadow bug).
    ref2 = _import_reference_plugin()
    _prep_init(ref2, monkeypatch)
    monkeypatch.setattr(ref2, "_config", {})
    ref2._deferred_init()
    assert ref2._egress_sink_tools == frozenset(
        canonicalize_tool_name(t) for t in PetasosConfig().egress_sink_tools
    )
    assert len(ref2._egress_sink_tools) > 0


# ---------------------------------------------------------------------------
# Guard surfaces param_scan_degraded
# ---------------------------------------------------------------------------


def _guard_with(monkeypatch: pytest.MonkeyPatch, result: PipelineResult) -> ToolCallGuard:
    """Real Pipeline with inspect monkeypatched to a crafted result (backend-free)."""
    cfg = PetasosConfig()
    pipe = Pipeline(config=cfg)

    async def _fake_inspect(
        text: str, *, direction: str = "inbound", session_id: str | None = None
    ) -> PipelineResult:
        return result

    monkeypatch.setattr(pipe, "inspect", _fake_inspect)
    return ToolCallGuard(pipe, FrequencyTracker(cfg), cfg)


async def test_guard_surfaces_param_scan_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    # (i) default + to_dict carries the additive key.
    gr = GuardResult(allowed=True, reason="ok", findings=(), tier="none", param_scan_unsafe=False)
    assert gr.param_scan_degraded is False
    assert gr.to_dict()["param_scan_degraded"] is False

    high = _non_pii("injection", Severity.HIGH)

    # (ii) safe=False + a scanner error (no findings) → degraded True.
    _f, unsafe, degraded = await _guard_with(
        monkeypatch,
        PipelineResult(
            safe=False, findings=(), scanner_results=(ScanResult("llm_guard", (), error="boom"),)
        ),
    )._scan_params({"a": "x"}, "s1")
    assert unsafe is True and degraded is True

    # (iii) safe=False, finding-driven (no scanner error) → degraded False.
    _f, unsafe, degraded = await _guard_with(
        monkeypatch,
        PipelineResult(
            safe=False, findings=(high,), scanner_results=(ScanResult("presidio", (high,)),)
        ),
    )._scan_params({"a": "x"}, "s1")
    assert unsafe is True and degraded is False

    # (iv) fail_mode="open" arm: safe=True + scanner error → degraded False (no block).
    _f, unsafe, degraded = await _guard_with(
        monkeypatch,
        PipelineResult(
            safe=True, findings=(), scanner_results=(ScanResult("llm_guard", (), error="boom"),)
        ),
    )._scan_params({"a": "x"}, "s1")
    assert unsafe is False and degraded is False

    # (v) syntactic-only (minimal-only, ml_total==0) degraded → degraded True.
    _f, unsafe, degraded = await _guard_with(
        monkeypatch,
        PipelineResult(
            safe=False, findings=(), scanner_results=(ScanResult("minimal", (), error="boom"),)
        ),
    )._scan_params({"a": "x"}, "s1")
    assert unsafe is True and degraded is True
