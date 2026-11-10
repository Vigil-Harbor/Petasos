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
    assert seen["selected"].startswith(_LABELS[view]), seen
    assert seen["loading"] is False, seen
    assert seen["chars"] > 200, seen
