"""Status from a temporary home. No Hermes process is started."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.hermes.dashboard.scope import load_home
from petasos.hermes.dashboard.status import status

if TYPE_CHECKING:
    from pathlib import Path


def _home(tmp_path: Path, text: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.yaml").write_text(text, encoding="utf-8")
    return tmp_path


_RESEARCH = """\
plugins:
  enabled:
    - petasos
  entries:
    petasos:
      settings:
        enabled: true
        role: research
        level: strict
"""

_PAUSED = """\
plugins:
  enabled:
    - petasos
  entries:
    petasos:
      settings:
        enabled: false
"""

_DISABLED = """\
plugins:
  enabled:
    - petasos
  disabled:
    - petasos
"""

_BAD_ROLE = """\
plugins:
  enabled:
    - petasos
  entries:
    petasos:
      settings:
        role: nope
"""


def test_both_switches_on_is_protection_on(tmp_path: Path) -> None:
    """Protection is on only when Hermes loads the plugin and Petasos is armed."""
    home = _home(tmp_path, _RESEARCH)
    body = status(load_home(home), home_label="sandbox")
    assert body["protection"] == "on"
    assert body["switches"]["hermes"]["on"] is True
    assert body["switches"]["petasos"]["on"] is True
    assert body["role"] == "research"
    assert body["level"] == "strict"
    assert body["settings"]["valid"] is True
    assert body["scanners"][0]["id"] == "syntactic"
    assert body["secrets"]["session_secret"] == "unset"
    assert body["home"] == "sandbox"
    assert isinstance(body["recommendations"], list)
    assert body["version"] == 2
    assert body["doctor"]["checks"]
    assert body["scanners"] == body["doctor"]["detail"]["scanners"]
    assert body["recommendations"] == body["doctor"]["suggestions"]
    joined = " ".join(body["recommendations"])
    assert "No injection scanner is active" not in joined
    assert "pip install" not in joined
    assert "prompt-guard" in joined


def test_a_paused_switch_says_which_one_is_off(tmp_path: Path) -> None:
    """Petasos's own switch is named when Hermes is loading the plugin."""
    home = _home(tmp_path, _PAUSED)
    body = status(load_home(home))
    assert body["protection"] == "off"
    assert body["switches"]["hermes"]["on"] is True
    assert body["switches"]["petasos"]["on"] is False
    assert "paused" in body["switches"]["petasos"]["detail"]


def test_hermes_disabled_list_is_the_other_switch(tmp_path: Path) -> None:
    """A plugin on Hermes's disabled list is not loaded, and the sentence says so."""
    home = _home(tmp_path, _DISABLED)
    body = status(load_home(home))
    assert body["switches"]["hermes"]["on"] is False
    assert "disabled" in body["switches"]["hermes"]["detail"]


def test_invalid_settings_are_reported(tmp_path: Path) -> None:
    """A bad role is an error on the status, and protection stays off."""
    home = _home(tmp_path, _BAD_ROLE)
    body = status(load_home(home))
    assert body["protection"] == "off"
    assert body["settings"]["valid"] is False
    assert body["settings"]["error"]["path"] == "role"


def test_coverage_says_which_checks_run_and_which_do_not(tmp_path: Path) -> None:
    """Protected is never read as complete when an optional check is missing."""
    from petasos.hermes.dashboard.status import coverage

    rows = [
        {"id": "syntactic", "label": "Basic checks", "state": "active", "extra": None},
        {
            "id": "prompt_guard",
            "label": "PromptGuard",
            "state": "not_installed",
            "extra": "prompt-guard",
            "reason": "Not installed.",
        },
        {
            "id": "semgrep",
            "label": "Semgrep",
            "state": "off",
            "extra": "semgrep",
            "reason": "Off.",
        },
    ]
    found = coverage(rows, ["Add petasos[prompt-guard] to the plugin's dependency list."])
    assert found["complete"] is False
    assert [row["label"] for row in found["running"]] == ["Basic checks"]
    missing = {row["id"]: row for row in found["missing"]}
    assert missing["prompt_guard"]["recommended"] is True
    assert missing["semgrep"]["recommended"] is False
    whole = coverage(rows[:1], [])
    assert whole["complete"] is True
    body = status(load_home(_home(tmp_path, _RESEARCH)))
    assert "coverage" in body
    assert body["coverage"]["running"][0]["id"] == "syntactic"
