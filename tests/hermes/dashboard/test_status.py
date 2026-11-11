"""Status from a temporary home. No Hermes process is started."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from petasos.hermes.dashboard.scope import load_home
from petasos.hermes.dashboard.status import status

if TYPE_CHECKING:
    from pathlib import Path

    from petasos._types import Scanner


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
    served = [{k: v for k, v in row.items() if k != "operating"} for row in body["scanners"]]
    assert served == body["doctor"]["detail"]["scanners"]
    assert body["scanners"][0]["operating"] == {"code": "running", "label": "Running"}
    assert body["paused"] is False
    assert body["choices_note"] is None
    assert "this profile" in body["scope"]
    assert body["recommendations"] == body["doctor"]["suggestions"]
    joined = " ".join(body["recommendations"])
    assert "No injection scanner is active" not in joined
    assert "pip install" not in joined
    assert "petasos scanner add prompt_guard" in joined


def test_a_paused_switch_says_which_one_is_off(tmp_path: Path) -> None:
    """Petasos's own switch is named when Hermes is loading the plugin."""
    home = _home(tmp_path, _PAUSED)
    body = status(load_home(home))
    assert body["protection"] == "off"
    assert body["switches"]["hermes"]["on"] is True
    assert body["switches"]["petasos"]["on"] is False
    assert "paused" in body["switches"]["petasos"]["detail"]
    assert body["choices_note"] == "These apply when protection resumes."


def test_hermes_disabled_list_is_the_other_switch(tmp_path: Path) -> None:
    """A plugin on Hermes's disabled list is not loaded, and the sentence says so."""
    home = _home(tmp_path, _DISABLED)
    body = status(load_home(home))
    assert body["switches"]["hermes"]["on"] is False
    assert "disabled" in body["switches"]["hermes"]["detail"]
    assert body["choices_note"] == "These apply when Hermes runs Petasos."


def test_invalid_settings_are_reported(tmp_path: Path) -> None:
    """A bad role is an error on the status, and protection stays off."""
    home = _home(tmp_path, _BAD_ROLE)
    body = status(load_home(home))
    assert body["protection"] == "off"
    assert body["choices_note"] == "These are not in use until the settings can be used."
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
    assert found["running"][0]["covers"].startswith("Hidden instructions")
    assert missing["prompt_guard"]["covers"] == "reworded hidden instructions"
    assert missing["semgrep"]["covers"] == "risky code"
    assert "terminal" in found["add_where"]
    body = status(load_home(_home(tmp_path, _RESEARCH)))
    assert "coverage" in body
    assert body["coverage"]["running"][0]["id"] == "syntactic"


def test_a_check_turned_on_that_cannot_run_is_held_with_its_command() -> None:
    """``held`` marks a check whose failure holds tool calls; the add command is served alone."""
    from petasos.hermes.dashboard.status import coverage

    rows = [
        {"id": "syntactic", "label": "Basic checks", "state": "active", "extra": None},
        {
            "id": "prompt_guard",
            "label": "PromptGuard",
            "state": "unavailable",
            "extra": "prompt-guard",
            "reason": "PromptGuard is not installed.",
            "fix": "petasos scanner add prompt_guard",
        },
        {
            "id": "semgrep",
            "label": "Semgrep",
            "state": "unavailable",
            "extra": "semgrep",
            "reason": "semgrep.host_lifecycle_unavailable",
            "fix": "Semgrep needs Hermes to run it, and this process cannot.",
        },
    ]
    missing = {row["id"]: row for row in coverage(rows, [])["missing"]}
    assert missing["prompt_guard"]["held"] is True
    assert missing["prompt_guard"]["command"] == "petasos scanner add prompt_guard"
    assert missing["semgrep"]["held"] is True
    assert missing["semgrep"]["command"] is None


def test_status_says_who_can_change_settings_and_how_to_sign_records(tmp_path: Path) -> None:
    """The agent's attempts are recorded, not stopped; unsigned records come with steps."""
    body = status(load_home(_home(tmp_path, _RESEARCH)), home_label="~/hermes")
    assert "Open." in body["who_can_change"]["agent"]
    assert "fresh approval" in body["who_can_change"]["agent"]


def test_a_support_profile_says_guardrail_changes_are_blocked(tmp_path: Path) -> None:
    """Support refuses guardrail changes, and the panel says a shell can still get round that."""
    text = _RESEARCH.replace("role: research", "role: support")
    body = status(load_home(_home(tmp_path, text)), home_label="~/hermes")
    agent = body["who_can_change"]["agent"]
    assert agent.startswith("Blocked.")
    assert "shell" in agent
    signing = body["record_signing"]
    assert signing["signed"] is False
    assert signing["env_file"] == "~/hermes/.env"
    assert any("PETASOS_SESSION_SECRET" in step for step in signing["steps"])


def test_a_paused_status_reports_no_check_as_running(tmp_path: Path) -> None:
    """While protection is paused, every check that would run is served as paused.

    Every view draws a check's state from ``operating``. A paused status with
    any check served as running is the contradiction this guards against.
    """
    body = status(load_home(_home(tmp_path, _PAUSED)))
    assert body["paused"] is True
    codes = {row["id"]: row["operating"]["code"] for row in body["scanners"]}
    assert "running" not in codes.values(), codes
    assert codes["syntactic"] == "paused"
    for row in body["coverage"]["running"] + body["coverage"]["missing"]:
        assert row["operating"]["code"] != "running", row
    assert "always" not in body["checks_note"].lower()
    summaries = [check["summary"] for check in body["doctor"]["checks"]]
    assert not [line for line in summaries if "checks are running" in line], summaries


def test_a_check_is_not_running_while_hermes_does_not_load_petasos(tmp_path: Path) -> None:
    """Hermes's own switch off: no check is served as running or paused."""
    body = status(load_home(_home(tmp_path, _DISABLED)))
    assert body["paused"] is False
    assert {row["operating"]["code"] for row in body["scanners"]} <= {
        "stopped",
        "not_installed",
        "off",
    }


def _required(fail_mode: str | None, posture: str | None) -> str:
    lines = [
        "plugins:",
        "  enabled:",
        "    - petasos",
        "  entries:",
        "    petasos:",
        "      settings:",
        "        overrides:",
        "          scanners:",
        "            prompt_guard:",
        '              enabled: "on"',
    ]
    if fail_mode is not None:
        lines.append(f"          fail_mode: {fail_mode}")
    if posture is not None:
        lines += ["          tools:", f"            dangerous_posture: {posture}"]
    return "\n".join(lines) + "\n"


def _missing_prompt_guard() -> tuple[object, ...]:
    """A registry whose PromptGuard is required and absent, whatever is installed here."""
    from petasos.scanners.registry import REGISTRY, BuildContext, ScannerSpec

    def absent(section: Any, context: BuildContext) -> Scanner:
        raise ImportError("No module named 'transformers'")

    spec = next(item for item in REGISTRY if item.id == "prompt_guard")
    return (
        ScannerSpec(
            id=spec.id,
            label=spec.label,
            extra=spec.extra,
            detects=spec.detects,
            section=spec.section,
            default_enabled=spec.default_enabled,
            build=absent,
            purpose=spec.purpose,
        ),
    )


@pytest.mark.parametrize(
    ("fail_mode", "posture", "holds", "words"),
    [
        (None, None, True, "a person is asked"),
        ("degraded", "block", True, "are blocked"),
        ("closed", "block", True, "are blocked"),
        ("degraded", "approve", True, "a person is asked"),
        ("closed", "approve", True, "a person is asked"),
        ("open", "block", False, "still run without it"),
        ("open", "approve", False, "still run without it"),
    ],
)
def test_what_a_required_check_that_cannot_run_does_is_computed(
    tmp_path: Path, fail_mode: str | None, posture: str | None, holds: bool, words: str
) -> None:
    """The sentence follows the fail mode and the dangerous-action setting, never a fixed text."""
    home = _home(tmp_path, _required(fail_mode, posture))
    body = status(load_home(home), registry=_missing_prompt_guard())  # type: ignore[arg-type]
    held = [row for row in body["coverage"]["missing"] if row["held"]]
    assert [row["id"] for row in held] == ["prompt_guard"]
    consequence = held[0]["consequence"]
    assert consequence["holds"] is holds
    assert words in consequence["sentence"]
    assert held[0]["operating"]["code"] == "failed"
    doctor = {check["id"]: check for check in body["doctor"]["checks"]}
    assert consequence["sentence"] in doctor["scanner_prompt_guard"]["meaning"]
    if not holds:
        assert "held" not in doctor["scanner_prompt_guard"]["meaning"]
        assert "blocked" not in consequence["sentence"]


def test_checks_are_named_by_what_they_do_first() -> None:
    """Plain first, product second, from the registry's purpose names."""
    from petasos.hermes.dashboard.status import coverage

    rows = [
        {"id": "syntactic", "label": "Basic checks", "purpose": "Basic checks", "state": "active"},
        {
            "id": "presidio",
            "label": "Presidio",
            "purpose": "Personal details check",
            "state": "not_installed",
            "extra": "presidio",
        },
    ]
    found = coverage(rows, [])
    assert found["running"][0]["name"] == "Basic checks"
    assert found["missing"][0]["name"] == "Personal details check (Presidio)"
