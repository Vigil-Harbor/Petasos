"""The Petasos plugin loaded by Hermes v0.23.1 inside the sandbox."""

from __future__ import annotations

from typing import Any

import pytest

from tests.hermes_host.client import PETASOS_HARNESS, Sandbox, call
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox

_HARNESS = PETASOS_HARNESS


def _invoke(box: Sandbox, request: dict[str, Any], *, timeout: float = 180) -> dict[str, Any]:
    return call(box, request, harness=_HARNESS, timeout=timeout)


def test_plugin_validates_and_loads(installed: Sandbox) -> None:
    """Hermes validates the directory, discovers it, and loads it as standalone."""
    report = _invoke(installed, {"action": "validate"})
    assert report["ok"] is True
    loaded = _invoke(installed, {"action": "discover"})
    assert loaded["loaded"] is True
    assert loaded["error"] in (None, "")
    assert loaded["kind"] == "standalone"
    assert "pre_tool_call" in loaded["hooks"]
    assert "transform_tool_result" in loaded["hooks"]


def test_injection_is_blocked_and_settings_change_live(installed: Sandbox) -> None:
    """A finding blocks with a message. Hermes's writer changes the next call."""
    result = _invoke(installed, {"action": "behaviour"}, timeout=120)
    injected = result["injected"]["block"]
    assert isinstance(injected, str) and injected.strip()
    assert result["clean"]["block"] is None
    assert isinstance(result["dangerous"]["block"], str) and result["dangerous"]["block"].strip()
    assert isinstance(result["kept"]["block"], str) and result["kept"]["block"].strip()
    assert result["disarmed"]["block"] is None
    asked = result["asked"]["block"]
    assert isinstance(asked, str) and "no interactive user" in asked
    still = result["still"]["block"]
    assert isinstance(still, str) and still.strip()


def test_tool_result_with_a_finding_is_annotated(installed: Sandbox) -> None:
    """An ingestion result that contains an injection is not returned unchanged."""
    result = _invoke(installed, {"action": "tool_result"}, timeout=120)
    text = result["result"]
    assert isinstance(text, str)
    assert text != result["original"]
    assert result["original"] in text


def test_reload_and_a_second_profile_keep_enforcement(installed: Sandbox) -> None:
    """A force reload rebinds hooks on the same enforcer. Each home has its own.

    ``register`` is not called again by a discovery that has already run. It is
    called again by ``discover_and_load(force=True)`` and by the manager for a
    second home. ``close`` fail-closes the old hooks, and the next load starts
    a new enforcer.
    """
    result = _invoke(installed, {"action": "registration"}, timeout=180)
    assert result["unknown_hook"] == []
    assert result["before_callbacks"] == 1
    assert isinstance(result["before_block"], str) and result["before_block"].strip()
    assert result["quiet_same_callbacks"] is True
    assert result["manual_callbacks"] == 1
    assert result["same_manager"] is True
    assert result["same_enforcer"] is True
    assert result["same_engine"] is True
    assert result["tier_before"] == result["tier_after"] == "none"
    assert result["after_callbacks"] == 1
    assert isinstance(result["after_block"], str) and "ignore-previous" in result["after_block"]
    alpha = result["alpha"]
    assert alpha["other_manager"] is True
    assert alpha["loaded"] is True
    assert alpha["error"] in (None, "")
    assert alpha["callbacks"] == 1
    assert alpha["block"] is None
    assert alpha["enabled"] is False
    assert alpha["role"] == "coding"
    assert alpha["kept_enabled"] is False
    assert alpha["kept_role"] == "coding"
    assert alpha["profile_name"] == "alpha"
    assert alpha["enforcer"] != alpha["root_enforcer"]
    root_again = result["root_again"]
    closed = result["closed_block"]
    restarted = result["restarted_block"]
    assert isinstance(root_again, str) and "ignore-previous" in root_again
    assert isinstance(closed, str) and "could not evaluate" in closed
    assert result["fresh_enforcer"] is True
    assert isinstance(restarted, str) and "ignore-previous" in restarted
    path = result["config_path"]
    named = [line for line in result["resolution"] if path in line]
    assert any(line.startswith("PETASOS_ARMED_RESOLUTION ") for line in named)


def test_secrets_come_from_the_env_file(installed: Sandbox) -> None:
    """The profile env file is the secret store. Plugin settings do not carry it."""
    result = _invoke(installed, {"action": "secrets"})
    assert result["session_set"] is True
    assert result["hash_key"] == "sandbox-hash"
    assert result["config_secret"] == "SENTINEL"
    assert result["env_absent"] is True


@pytest.mark.parametrize(
    ("case", "proceeds", "asks"),
    [
        ("smart", False, True),
        ("manual", False, True),
        ("approve_string", False, True),
        ("off", False, False),
        ("yolo", False, False),
        ("single_query", False, False),
        ("cron", False, False),
        ("unattended", False, False),
        ("allowlist", True, False),
    ],
)
def test_approve_follows_the_host_state(
    installed: Sandbox, case: str, proceeds: bool, asks: bool
) -> None:
    """An approve is handed to Hermes only when a person would be asked."""
    result = _invoke(installed, {"action": "approve", "case": case}, timeout=120)
    block = result["block"]
    if proceeds:
        assert block is None
        return
    assert isinstance(block, str) and block.strip()
    if asks:
        assert "no interactive user" in block or "no interactive" in block
    else:
        assert "Petasos" in block
