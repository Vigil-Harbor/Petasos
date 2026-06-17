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

    forbidden = (
        "exempt-with-scan",
        "tier2: tool calls blocked",
        "invalid tool name",
        "param_scan_unsafe",
        "Security finding (PII,",
        "Parameter scan flagged",
        "Security scan (init in progress)",
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
    # Regression for PET-77: each of the six block sites must route through the formatter.
    # Counting call occurrences closes the hole B2 leaves open (a NEW ad-hoc f-string at a
    # single site would pass B2 but drop the count below six).
    src = _shim_source()
    call_sites = src.count("format_block_message(") + src.count("format_content_block(")
    assert call_sites >= 6, f"expected >=6 formatter call sites in the shim, found {call_sites}"
