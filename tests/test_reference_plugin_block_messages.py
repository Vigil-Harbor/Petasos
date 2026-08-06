"""PET-77: the reference plugin shim must return the [BLOCKED by Petasos] contract.

The block-message formatter (``petasos/session/formatting.py``) was built and tested
as a library module in PR #50, but the shim that actually returns block messages to
the model was never wired to it: every block site emitted a raw, unattributed string
(``Security finding (PII, ...)``, ``Parameter scan flagged unsafe content: ...``,
``result.reason``, ...). The model could not tell a tool was blocked and confabulated.

This module is the regression + deploy-parity guard the original close lacked:

  A. Contract tests drive ``_pre_tool_call`` / ``_fallback_pre_tool_call`` down each of
     the six block sites and assert the formatted, attributed message.
  B. Deploy-parity tests read the in-repo shim source and assert the formatter is
     imported and called at every site, so a future edit cannot silently regress the
     contract (mirrors the PET-106 ``tests/test_ci_extras_lanes.py`` invariant style).

Backend-free: the guard is stubbed and ``_run_async`` is monkeypatched, exactly like
``tests/test_reference_plugin_egress.py``.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from petasos import GuardResult, ScanFinding, ScanResult, Severity
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

_PREFIX = "[BLOCKED by Petasos]"
_EGRESS = frozenset({canonicalize_tool_name(t) for t in ("send_email", "http_request")})


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PETASOS_LICENSE_KEY", "PETASOS_SESSION_SECRET", "PETASOS_HASH_KEY"):
        monkeypatch.delenv(var, raising=False)


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet77", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Finding + GuardResult builders (mirror tests/test_reference_plugin_egress.py)
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


def _non_pii(
    finding_type: str, severity: Severity = Severity.HIGH, *, message: str | None = None
) -> ScanFinding:
    return ScanFinding(
        rule_id=f"petasos.{finding_type or 'unknown'}.x",
        finding_type=finding_type,
        severity=severity,
        confidence=0.9,
        message=message if message is not None else f"{finding_type or 'untyped'} finding",
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
    monkeypatch.setattr(ref, "_maybe_reconfigure", lambda: None)
    return ref._pre_tool_call(tool_name, args or {"text": "x"}, task_id="s1")


def _drive_cold_window_no_finding(
    monkeypatch: pytest.MonkeyPatch, tool_name: str = "write_file", fail_mode: str = "degraded"
) -> Any:
    """PET-167: drive ``_pre_tool_call`` down the cold-window NO-finding block — the wait
    expired, the syntactic fallback scanned clean, and ``fail_mode`` blocks the dangerous
    call. This is the eighth formatter site."""
    ref = _import_reference_plugin()
    monkeypatch.setattr(ref, "_is_armed", lambda: True)
    monkeypatch.setattr(ref, "_ensure_initialized", lambda: False)
    monkeypatch.setattr(ref, "_init_error", None)
    monkeypatch.setattr(ref, "_initialized", False)
    monkeypatch.setattr(ref, "_config", {"fail_mode": fail_mode})

    class _Clean:
        name = "minimal"

        async def scan(
            self, text: str, *, direction: str = "inbound", session_id: str | None = None
        ) -> ScanResult:
            return ScanResult(scanner_name="minimal", findings=())

    monkeypatch.setattr(ref, "_run_async", lambda coro: asyncio.run(coro))
    monkeypatch.setattr(ref, "_get_fallback_scanner", lambda: _Clean())
    return ref._pre_tool_call(tool_name, {"text": "x"}, task_id="s-cold")


def _drive_fallback(
    monkeypatch: pytest.MonkeyPatch, tool_name: str, finding: ScanFinding | None
) -> Any:
    """Drive ``_fallback_pre_tool_call`` (the init-window path) with a stub scanner."""
    ref = _import_reference_plugin()

    class _Stub:
        name = "minimal"

        async def scan(
            self, text: str, *, direction: str = "inbound", session_id: str | None = None
        ) -> ScanResult:
            return ScanResult(scanner_name="minimal", findings=(finding,) if finding else ())

    monkeypatch.setattr(ref, "_run_async", lambda coro: asyncio.run(coro))
    monkeypatch.setattr(ref, "_get_fallback_scanner", lambda: _Stub())
    return ref._fallback_pre_tool_call(tool_name, {"text": "x"}, "s1")


# ---------------------------------------------------------------------------
# A. Contract tests — one per enforcement path
# ---------------------------------------------------------------------------


def test_tier3_block_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-77: tier3 termination carries the contract (was raw
    # "All tool calls blocked ... (Tier 3 escalation).").
    out = _drive(
        monkeypatch,
        "read_file",  # tier3 is checked before the dangerous-tool gate
        _guard_result(tier="tier3", allowed=False, reason="session terminated (tier3)"),
    )
    assert out is not None and out["action"] == "block"
    msg = out["message"]
    assert msg.startswith(_PREFIX)
    assert "read_file" in msg and "NOT executed" in msg
    assert "tier3" in msg and "All tool calls are blocked" in msg
    assert "Tier 3 escalation" not in msg  # the old raw string is gone


def test_explicit_block_tier2_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-77: an explicit (not-allowed) tier2 block routes through the
    # formatter; the internal reason string must not appear.
    out = _drive(
        monkeypatch,
        "write_file",
        _guard_result(
            allowed=False,
            tier="tier2",
            reason="tier2: tool calls blocked",
            findings=(_non_pii("injection", Severity.HIGH),),
        ),
    )
    assert out is not None and out["action"] == "block"
    msg = out["message"]
    assert msg.startswith(_PREFIX)
    assert "write_file" in msg and "NOT executed" in msg
    assert "tier2" in msg
    assert "Top finding:" in msg and "(HIGH)" in msg
    assert "tier2: tool calls blocked" not in msg


def test_explicit_block_catch_all_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-77: the L763 result.reason leak (exempt-with-scan, allowed, ...)
    # is replaced by a contract message via the catch-all formatter branch.
    out = _drive(
        monkeypatch,
        "write_file",
        _guard_result(allowed=False, reason="exempt-with-scan"),
    )
    assert out is not None and out["action"] == "block"
    msg = out["message"]
    assert msg.startswith(_PREFIX)
    assert "write_file" in msg and "NOT executed" in msg
    assert "exempt-with-scan" not in msg


def test_degraded_block_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-77: the scanner-degraded fail-mode block carries the contract.
    out = _drive(
        monkeypatch,
        "write_file",
        _guard_result(param_scan_unsafe=True, param_scan_degraded=True),
    )
    assert out is not None and out["action"] == "block"
    msg = out["message"]
    assert msg.startswith(_PREFIX)
    assert "write_file" in msg and "NOT executed" in msg
    assert "degraded" in msg.lower()
    assert "Top finding:" not in msg  # no blocking findings on this sub-path


def test_non_pii_param_block_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-77: a non-PII HIGH+ param finding blocks with the contract
    # (was raw "Parameter scan flagged unsafe content: ...").
    out = _drive(
        monkeypatch,
        "write_file",
        _guard_result(findings=(_non_pii("injection", Severity.HIGH),), param_scan_unsafe=True),
    )
    assert out is not None and out["action"] == "block"
    msg = out["message"]
    assert msg.startswith(_PREFIX)
    assert "write_file" in msg and "NOT executed" in msg
    assert "injection" in msg and "(HIGH)" in msg
    assert "Parameter scan flagged unsafe content" not in msg


def test_pii_egress_block_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-77: a PII finding to an egress sink blocks with the contract
    # (was raw "Security finding (PII, ...)").
    out = _drive(
        monkeypatch,
        "send_email",
        _guard_result(findings=(_pii(Severity.CRITICAL),), param_scan_unsafe=True),
    )
    assert out is not None and out["action"] == "block"
    msg = out["message"]
    assert msg.startswith(_PREFIX)
    assert "send_email" in msg and "NOT executed" in msg
    assert "(CRITICAL)" in msg and "PII" in msg
    assert "Security finding (PII," not in msg


def test_init_fallback_block_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-77: the init-window fallback block carries the contract
    # (was raw "Security scan (init in progress): ...").
    out = _drive_fallback(monkeypatch, "write_file", _non_pii("injection", Severity.CRITICAL))
    assert out is not None and out["action"] == "block"
    msg = out["message"]
    assert msg.startswith(_PREFIX)
    assert "write_file" in msg and "NOT executed" in msg
    assert "Top finding:" in msg
    assert "Security scan (init in progress)" not in msg


def test_cold_window_no_finding_block_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-167: the cold-window block that has NO syntactic finding behind it
    # (clean or errored scan under degraded/closed) still carries the PET-77 contract. It
    # reuses the existing "degraded" ContentBlockPath rather than minting a new token: this
    # and the warm-path param_scan_degraded block are the same decision under the same
    # policy. No "Top finding:" clause — there is no finding on this sub-path.
    out = _drive_cold_window_no_finding(monkeypatch)
    assert out is not None and out["action"] == "block"
    msg = out["message"]
    assert msg.startswith(_PREFIX)
    assert "write_file" in msg and "NOT executed" in msg
    assert "degraded" in msg.lower()
    assert "Top finding:" not in msg


def test_no_internal_reason_strings_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-77: no internal reason string or raw block string reaches the
    # model across every enforcement path, AND a unique sentinel reason is never echoed
    # (pins the structural "reason is never echoed" property, not just the known strings).
    messages: list[str] = []
    messages.append(
        _drive(
            monkeypatch,
            "read_file",
            _guard_result(tier="tier3", allowed=False, reason="session terminated (tier3)"),
        )["message"]
    )
    messages.append(
        _drive(
            monkeypatch,
            "write_file",
            _guard_result(
                allowed=False,
                tier="tier2",
                reason="tier2: tool calls blocked",
                findings=(_non_pii("injection", Severity.HIGH),),
            ),
        )["message"]
    )
    messages.append(
        _drive(monkeypatch, "write_file", _guard_result(allowed=False, reason="exempt-with-scan"))[
            "message"
        ]
    )
    messages.append(
        _drive(
            monkeypatch,
            "write_file",
            _guard_result(param_scan_unsafe=True, param_scan_degraded=True),
        )["message"]
    )
    messages.append(
        _drive(
            monkeypatch,
            "write_file",
            _guard_result(
                findings=(_non_pii("injection", Severity.HIGH),), param_scan_unsafe=True
            ),
        )["message"]
    )
    messages.append(
        _drive(
            monkeypatch,
            "send_email",
            _guard_result(findings=(_pii(Severity.CRITICAL),), param_scan_unsafe=True),
        )["message"]
    )
    messages.append(
        _drive_fallback(monkeypatch, "write_file", _non_pii("injection", Severity.CRITICAL))[
            "message"
        ]
    )
    # PET-167: the cold-window no-finding block joins the catalogue.
    messages.append(_drive_cold_window_no_finding(monkeypatch)["message"])
    # PET-170: the two ingestion-annotation notices are model-facing too, so they join the
    # catalogue that is checked AGAINST `forbidden`. They must not also go into `forbidden`
    # — that tuple is a deny-list checked against these very messages, so a string in both
    # halves would assert itself absent from itself.
    ref = _import_reference_plugin()
    messages.append(ref.format_result_notice("findings", "read_file", _non_pii("injection"), 3))
    messages.append(ref.format_result_notice("scan_unavailable", "read_file"))

    forbidden = (
        "exempt-with-scan",
        "tier2: tool calls blocked",
        "invalid tool name",
        "param_scan_unsafe",
        "Security finding (PII,",
        "Parameter scan flagged",
        "Security scan (init in progress)",
        # PET-170: the operator-facing half of the ingestion split. It rides the
        # enforcement event's `reason` to the dashboard and must never reach the model.
        ref._RESULT_SCAN_ERROR_REASON,
    )
    for msg in messages:
        for token in forbidden:
            assert token not in msg, f"internal/raw string {token!r} leaked into: {msg!r}"

    # Structural canary: an arbitrary reason on a not-allowed result is never echoed.
    sentinel = _drive(
        monkeypatch,
        "write_file",
        _guard_result(allowed=False, reason="SENTINEL_LEAK_CANARY_xyz"),
    )["message"]
    assert "SENTINEL_LEAK_CANARY_xyz" not in sentinel


def test_finding_message_truncated_in_shim_output(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-77: the 200-char finding-message truncation is enforced end-to-end
    # through the shim. Homogeneous fill makes the boundary assertion deterministic.
    out = _drive(
        monkeypatch,
        "write_file",
        _guard_result(
            findings=(_non_pii("injection", Severity.HIGH, message="X" * 500),),
            param_scan_unsafe=True,
        ),
    )
    assert out is not None and out["action"] == "block"
    msg = out["message"]
    assert "X" * 200 in msg
    assert "…" in msg
    assert "X" * 201 not in msg


# ---------------------------------------------------------------------------
# B. Deploy-parity guard — the shim source must import AND call the formatter
# ---------------------------------------------------------------------------


def _shim_source() -> str:
    return _REF_PLUGIN_PATH.read_text(encoding="utf-8")


def test_shim_imports_formatter() -> None:
    # Regression for PET-77: the in-repo shim imports the library formatter.
    src = _shim_source()
    assert "from petasos.session.formatting import" in src
    assert "format_block_message" in src
    assert "format_content_block" in src
    # PET-170: the ingestion-annotation notice is the same contract in the other
    # direction — an ad-hoc f-string banner in the shim would bypass the no-matched-text
    # guarantee the library formatter enforces.
    assert "format_result_notice" in src


def test_shim_emits_branding() -> None:
    # Regression for PET-77: no surviving raw block string from the six-site catalog
    # (the original close shipped these; their reappearance is a silent regression).
    src = _shim_source()
    raw_catalog = (
        "Security finding (PII,",
        "Parameter scan flagged unsafe content:",
        "Security scan (init in progress):",
        "Tier 3 escalation",
        '"message": result.reason',
    )
    for raw in raw_catalog:
        assert raw not in src, f"raw block string {raw!r} survives in the shim"


def test_shim_routes_every_block_site_through_formatter() -> None:
    # Regression for PET-77: each block site must route through the formatter. Counting
    # call sites closes the hole B2 leaves open (a NEW ad-hoc f-string at a single site
    # would pass B2 but drop the count). Parse the AST and count real Call nodes so the
    # names appearing in the import, comments, or string literals are not miscounted (a raw
    # src.count() would inflate the total and could mask a removed site).
    #
    # Regression for PET-167: bumped 6 -> 8. The tree already had SEVEN sites — PET-134's
    # taint_egress site was added without bumping the assertion, leaving it unguarded — and
    # PET-167's cold-window no-finding block is the eighth. The reconciliation is done here
    # so the number is exact rather than merely non-decreasing.
    #
    # Regression for PET-170: bumped 8 -> 10, and `format_result_notice` joins the watched
    # set. Its two sites are the ingestion handler's findings and scan_unavailable returns.
    # Watching it here is what stops a future edit from hand-rolling a banner and quietly
    # re-injecting the attacker's decoded payload, which is exactly what the formatter's
    # no-matched-text rule exists to prevent.
    tree = ast.parse(_shim_source())
    targets = {"format_block_message", "format_content_block", "format_result_notice"}
    call_sites = sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in targets
    )
    assert call_sites == 10, f"expected 10 formatter call sites in the shim, found {call_sites}"


def test_manifest_and_runbook_hook_lists_agree() -> None:
    """Regression for PET-170: the shipped ``plugin.yaml`` and the runbook's copy of it
    must list the same hooks.

    Both are documentation, not parser input — the host reads ``provides_hooks``, never
    ``hooks:`` — which is precisely why they drift silently. The runbook block is fenced by
    HTML-comment markers so this parity check has an anchor that does not depend on which
    of the runbook's four yaml fences comes first (the PET-153 markers elsewhere in that
    file are a different pair and are untouched).
    """
    manifest = (_REF_PLUGIN_PATH.parent / "plugin.yaml").read_text(encoding="utf-8")
    runbook = (_REF_PLUGIN_PATH.parent.parent / "hermes-desktop.md").read_text(encoding="utf-8")

    start, end = "<!-- PET-170-MANIFEST-START -->", "<!-- PET-170-MANIFEST-END -->"
    assert start in runbook and end in runbook, "the runbook manifest markers are missing"
    block = runbook.split(start, 1)[1].split(end, 1)[0]

    def hooks(text: str) -> list[str]:
        out = []
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("- ") and not line.startswith("- #"):
                out.append(line[2:].strip())
        return out

    manifest_hooks, runbook_hooks = hooks(manifest), hooks(block)
    assert manifest_hooks, "no hooks parsed out of plugin.yaml"
    assert manifest_hooks == runbook_hooks, (
        f"plugin.yaml lists {manifest_hooks} but the runbook lists {runbook_hooks}"
    )
    assert "transform_tool_result" in manifest_hooks
