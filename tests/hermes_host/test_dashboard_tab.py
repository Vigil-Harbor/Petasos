"""The Petasos tab loads in a real Hermes dashboard and every view renders.

Skipped unless ``PETASOS_HERMES_SANDBOX`` names a prepared sandbox. The
browser is the sandbox's own (``<sandbox>/shot``; see ``capture_round.py``).
Without it the test is skipped with that reason.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests.hermes_host.capture_round import run_browser
from tests.hermes_host.dashboard_server import start, stop
from tests.hermes_host.demo_home import prepare
from tests.hermes_host.marks import requires_hermes_sandbox

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = requires_hermes_sandbox

_LABELS = {
    "overview": "Overview",
    "activity": "Activity",
    "tryit": "Try it",
    "settings": "Settings",
}


@pytest.fixture(scope="module")
def tab_report(petasos_wheel: Path) -> Iterator[dict[str, Any]]:
    """One demonstration home, one dashboard, one browser pass over every view."""
    sandbox = petasos_wheel
    if not (sandbox / "shot" / "bin" / "python").is_file():
        pytest.skip(f"no browser environment at {sandbox / 'shot'}; see capture_round.py")
    dist = sandbox / "src" / "hermes-agent" / "hermes_cli" / "web_dist" / "index.html"
    if not dist.is_file():
        pytest.fail(f"dashboard bundle is missing: {dist}")
    home = Path(prepare(sandbox, "tab")["home"])
    board = start(sandbox, home)
    try:
        yield run_browser(sandbox, {"action": "check", "url": board.url}, timeout=300)
    finally:
        assert stop(board.pid), f"dashboard {board.pid} is still running"


def test_no_script_error_and_no_failed_api_call(tab_report: dict[str, Any]) -> None:
    """The tab's script runs cleanly and every Petasos API call it makes succeeds."""
    assert tab_report["errors"] == []
    assert tab_report["failed"] == []


@pytest.mark.parametrize("view", sorted(_LABELS))
def test_each_view_renders_content(tab_report: dict[str, Any], view: str) -> None:
    """Each view is selected, finished loading, and shows real content."""
    seen = tab_report["views"][view]
    assert seen["selected"].lower().startswith(_LABELS[view].lower()), seen
    assert seen["loading"] is False, seen
    assert seen["chars"] > 200, seen


@pytest.mark.parametrize("view", sorted(_LABELS))
def test_each_view_takes_and_gives_focus_well(tab_report: dict[str, Any], view: str) -> None:
    """Tab reaches the view's controls, shows a ring on each, and moves on past them.

    A view that grabs focus when it opens, a control that takes focus without a
    visible ring, or a trap that keeps Tab inside the tab fails here.
    """
    focus = tab_report["focus"][view]
    assert focus["stolen"] is False, focus
    assert focus["entered"] is True, focus
    assert focus["distinct"] >= 4, focus
    assert focus["invisible"] == [], focus
    assert focus["left"] is True, focus


def test_a_paused_tab_shows_no_check_running(tab_report: dict[str, Any]) -> None:
    """While protection is paused, no check anywhere in the tab is drawn as running.

    The Overview's Checks panel and Try it's list of checks both draw a
    check's state from the API's operating value. Paused through the tab's
    own button, neither may show a check running, and no sentence may say
    the checks always run.
    """
    paused = tab_report["paused"]
    assert paused["overview"], paused
    assert "running" not in paused["overview"], paused
    assert "paused" in paused["overview"], paused
    assert paused["tryit"], paused
    assert "checked" not in paused["tryit"], paused
    assert "paused" in paused["tryit"], paused
    assert "always run" not in paused["overview_text"].lower()
    assert "These apply when protection resumes." in paused["overview_text"]
    assert "Every rule is on" not in paused["overview_text"]


def test_the_tab_says_what_the_record_can_show(tab_report: dict[str, Any]) -> None:
    """Overview, Activity and the search fields use the words the API serves."""
    overview = tab_report["views"]["overview"]["text"]
    activity = tab_report["views"]["activity"]["text"]
    assert "Uses every built-in rule" in overview
    assert "Review current settings" in overview
    assert "Show changed settings" not in overview
    assert "Setting changes not stopped" not in overview
    assert "signatures verified" in activity
    assert "Signed ·" not in activity
    assert "Conversation risk" in activity
    assert "No rule" in activity
    assert tab_report["activity_search"] == {
        "label": "Search activity",
        "placeholder": "Search activity",
    }
    assert tab_report["settings_search"] == {
        "label": "Search settings",
        "placeholder": "Search settings",
    }
    tryit = tab_report["views"]["tryit"]["text"]
    assert "adds no Activity record" in tryit
