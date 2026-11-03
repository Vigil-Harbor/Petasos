"""Credential display boundaries: real spool/history, synthetic host secrets."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from petasos.console import _approvals, _events, _history
from petasos.console.server import _enforcement_summary, _history_disk_row


@pytest.fixture
def plugin() -> Any:
    path = Path(__file__).resolve().parents[1] / "docs/deployment/reference_plugin/__init__.py"
    spec = importlib.util.spec_from_file_location("pet250_reference_plugin", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_redactor(monkeypatch: pytest.MonkeyPatch, function: Any) -> None:
    module: Any = types.ModuleType("agent.redact")
    module.redact_sensitive_text = function
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.redact", module)


def read_spool() -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(_events._spool_path()).read_text().splitlines()]


def test_approval_redacted_before_clipping_signing_and_history(
    plugin: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "synthetic-password-" + "x" * 220

    def redact(text: str, **options: bool) -> str:
        assert options == {"force": True, "redact_url_credentials": True}
        return text.replace(secret, "[masked]")

    install_redactor(monkeypatch, redact)
    _events.set_spool_key(b"synthetic-test-key")
    payload = {
        "command": secret,
        "description": secret,
        "session_id": "profile-A-session",
        "session_key": "profile-A-session",
        "turn_id": "turn-1",
        "tool_call_id": "call-1",
        "pattern_key": "plugin_rule:petasos.test",
        "choice": "deny",
    }
    original = dict(payload)
    plugin._post_approval_response(**payload)
    row = read_spool()[0]
    assert row["command"] == row["description"] == "[masked]"
    assert row["credential_redaction"] == "redacted"
    assert "exposure unconfirmed" in row["reason"]
    assert _events.verify_event(row, _events._derive_spool_key(b"synthetic-test-key"))
    assert payload == original
    summary = _enforcement_summary(row, provenance="genuine")
    key = _history._derive_history_key(b"synthetic-test-key")
    assert _history.append_history_row(_history_disk_row(summary), key)
    disk = Path(_history._history_path()).read_text()
    assert "synthetic-password" not in disk
    saved = json.loads(disk)
    assert _history.verify_history_row(saved, key)
    queued = _approvals.refused_items([saved], frozenset())["items"][0]
    assert queued["credential_redaction"] == "redacted"
    assert queued["choice"] == "deny"
    assert queued["session_key"] == payload["session_key"]


@pytest.mark.parametrize("failure", ["missing", "raises", "wrong_type", "oversized"])
def test_failure_withholds_without_losing_refusal(
    plugin: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    secret = "synthetic-password-never-persist"

    def redact(_text: str, **_options: bool) -> Any:
        if failure == "raises":
            raise RuntimeError(secret)
        if failure == "oversized":
            return "x" * (plugin._MAX_PARAM_TEXT_LEN + 1)
        return None

    if failure == "missing":
        monkeypatch.setitem(sys.modules, "agent.redact", None)
    else:
        install_redactor(monkeypatch, redact)
    plugin._post_approval_response(command=secret, description=secret, choice="timeout")
    row = read_spool()[0]
    assert row["choice"] == "timeout"
    assert row["credential_redaction"] == "withheld"
    assert row["command"].startswith("withheld")
    assert secret not in json.dumps(row)


def test_enforcement_reason_uses_forced_redaction(
    plugin: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "synthetic-error-secret"
    install_redactor(monkeypatch, lambda text, **_kwargs: text.replace(secret, "[masked]"))
    assert plugin._emit_enforcement_event(
        session_id="s", tool="terminal", event_type="quarantine", reason=secret
    )
    row = read_spool()[0]
    assert row["credential_redaction"] == "redacted"
    assert secret not in row["reason"]
    assert "[masked]" in row["reason"]


def test_model_notice_does_not_claim_exposure(
    plugin: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "synthetic-vault-value"
    install_redactor(monkeypatch, lambda text, **_kwargs: text.replace(secret, "[masked]"))
    args = {"command": secret}
    excerpt = plugin._approval_command_excerpt(args, types.SimpleNamespace(findings=()))
    directive = plugin._approve_return("terminal", "s", "petasos.test", excerpt)
    assert "masked locally; exposure unconfirmed" in directive["message"]
    assert secret not in directive["message"]
    assert args["command"] == secret


def test_redacted_reason_retains_full_display_budget(
    plugin: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "synthetic-error-secret"
    safe_reason = "r" * 188 + "evidence-end"
    assert len(safe_reason) == 200
    install_redactor(monkeypatch, lambda text, **_kwargs: text.replace(secret, safe_reason))
    assert plugin._emit_enforcement_event(
        session_id="s", tool="terminal", event_type="quarantine", reason=secret
    )
    row = read_spool()[0]
    assert row["credential_redaction"] == "redacted"
    assert row["reason"] == safe_reason
    assert _enforcement_summary(row)["reason"] == safe_reason


def test_secret_references_stay_references(plugin: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    install_redactor(monkeypatch, lambda text, **_kwargs: text)
    reference = "op://test-vault/test-item/password"
    safe, status = plugin._redact_display_text(reference, 200)
    assert (safe, status) == (reference, "unchanged")


def test_unknown_redaction_status_is_not_forwarded() -> None:
    row = {"event_type": "approval", "credential_redaction": {"unsafe": "value"}}
    assert _enforcement_summary(row)["credential_redaction"] is None
