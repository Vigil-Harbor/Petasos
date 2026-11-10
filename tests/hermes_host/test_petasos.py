"""The Petasos plugin loaded by Hermes v0.23.1 inside the sandbox."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox

_ROOT = Path(__file__).resolve().parents[2]
_HARNESS = Path(__file__).resolve().parent / "petasos_harness.py"


def _invoke(sandbox: Path, request: dict[str, Any], *, timeout: float = 180) -> dict[str, Any]:
    wrapper = sandbox / "bin" / "with-sandbox"
    python = sandbox / "venv" / "bin" / "python"
    completed = subprocess.run(
        [str(wrapper), str(python), str(_HARNESS)],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"harness {request.get('action')} exited {completed.returncode}\n"
            f"stdout:\n{completed.stdout[-2000:]}\nstderr:\n{completed.stderr[-4000:]}"
        )
    parsed = json.loads(completed.stdout)
    if not isinstance(parsed, dict):
        raise AssertionError("harness did not return an object")
    return parsed


@pytest.fixture(scope="module")
def installed(hermes_sandbox: Path) -> Path:
    """Install this worktree's wheel and plugin directory once per module."""
    _invoke(hermes_sandbox, {"action": "install", "worktree": str(_ROOT)}, timeout=180)
    return hermes_sandbox


def test_plugin_validates_and_loads(installed: Path) -> None:
    """Hermes validates the directory, discovers it, and loads it as standalone."""
    report = _invoke(installed, {"action": "validate"})
    assert report["ok"] is True
    loaded = _invoke(installed, {"action": "discover"})
    assert loaded["loaded"] is True
    assert loaded["error"] in (None, "")
    assert loaded["kind"] == "standalone"
    assert "pre_tool_call" in loaded["hooks"]
    assert "transform_tool_result" in loaded["hooks"]


def test_injection_is_blocked_and_settings_change_live(installed: Path) -> None:
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


def test_tool_result_with_a_finding_is_annotated(installed: Path) -> None:
    """An ingestion result that contains an injection is not returned unchanged."""
    result = _invoke(installed, {"action": "tool_result"}, timeout=120)
    text = result["result"]
    assert isinstance(text, str)
    assert text != result["original"]
    assert result["original"] in text


def test_secrets_come_from_the_env_file(installed: Path) -> None:
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
    installed: Path, case: str, proceeds: bool, asks: bool
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
