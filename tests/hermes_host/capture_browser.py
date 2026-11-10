"""Drive the Petasos tab in a headless browser. Runs inside the sandbox.

Run only through the sandbox wrapper, with a Python that has Playwright
(``<sandbox>/shot/bin/python``; see ``capture_round.py``). One JSON object on
stdin, one on stdout. Two actions:

- ``check``: open each view and report script errors, failed API calls, and
  views that render nothing. The real-Hermes test reads this.
- ``capture``: take the fixed screenshot set for one design round.

It does not import Hermes. It talks to dashboards already started on
127.0.0.1 by the caller.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

VIEWS = ("overview", "activity", "tryit", "settings")
THEMES = (("teal", "Hermes Teal"), ("nous-blue", "Nous Blue"))
WIDTH = 1440
HEIGHT = 900


def _playwright() -> Any:
    return importlib.import_module("playwright.sync_api")


class Watch:
    """Script errors and failed Petasos API calls seen by one page."""

    def __init__(self, page: Any) -> None:
        self.errors: list[str] = []
        self.failed: list[str] = []
        page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        page.on("console", self._console)
        page.on("response", self._response)

    def _console(self, message: Any) -> None:
        if message.type == "error":
            self.errors.append("console: " + message.text)

    def _response(self, response: Any) -> None:
        if "/api/plugins/petasos/" in response.url and response.status >= 400:
            self.failed.append(f"{response.status} {response.url}")


def _open(page: Any, base: str, view: str, params: str = "") -> None:
    """Open the tab, then the view. Hermes drops a fragment on arrival."""
    if "/petasos" not in page.url:
        page.goto(base + "/petasos", wait_until="domcontentloaded")
        page.locator(".petasos-topbar").wait_for(timeout=30000)
    page.evaluate(
        "(h) => { window.location.hash = h; document.documentElement.scrollTop = 0; "
        "document.body.scrollTop = 0; }",
        view + params,
    )
    page.wait_for_timeout(300)
    page.locator(".petasos-view").wait_for(timeout=15000)


def _settle(page: Any, ms: int = 700) -> None:
    page.wait_for_load_state("networkidle")
    # Let Hermes's toast leave before the picture.
    page.locator("[role=status].fixed").wait_for(state="detached", timeout=8000)
    page.mouse.move(2, HEIGHT - 2)
    page.wait_for_timeout(ms)


def _theme(page: Any, base: str, label: str) -> None:
    """Pick a Hermes theme with Hermes's own switcher."""
    if "/petasos" not in page.url:
        page.goto(base + "/petasos", wait_until="domcontentloaded")
        page.locator(".petasos-topbar").wait_for(timeout=30000)
    switch = page.get_by_role("button", name="Switch theme")
    switch.first.click()
    page.wait_for_timeout(300)
    page.get_by_role("option", name=label).first.click()
    page.wait_for_timeout(900)


def check(request: dict[str, Any]) -> dict[str, Any]:
    """Load every view once and report what went wrong, if anything."""
    base = str(request["url"])
    report: dict[str, Any] = {"views": {}, "errors": [], "failed": []}
    sync = _playwright()
    with sync.sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        watch = Watch(page)
        for view in VIEWS:
            _open(page, base, view)
            _settle(page, 1200)
            panel = page.locator(".petasos-view")
            text = panel.inner_text().strip()
            selected = page.locator("[role=tab][aria-selected=true]").first.inner_text().strip()
            report["views"][view] = {
                "chars": len(text),
                "selected": selected,
                "loading": "Loading" in text[:40],
                "head": text[:160],
            }
        report["errors"] = watch.errors
        report["failed"] = watch.failed
        browser.close()
    return report


def _shot(page: Any, out: Path, name: str, shots: list[str]) -> None:
    path = out / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    shots.append(path.name)


_REVEAL = """(e, where) => {
  let node = e.parentElement;
  while (node && node !== document.body) {
    const style = getComputedStyle(node);
    if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) break;
    node = node.parentElement;
  }
  if (!node || node === document.body) return;
  const box = e.getBoundingClientRect();
  const frame = node.getBoundingClientRect();
  let offset = box.top - frame.top - 16;
  if (where === 'center') offset = box.top - frame.top - (frame.height - box.height) / 2;
  node.scrollTop += offset;
}"""


def _scroll_to(page: Any, selector: str, where: str = "start") -> None:
    """Scroll the tab's own container, never Hermes's page frame."""
    page.locator(selector).first.evaluate(_REVEAL, where)
    page.wait_for_timeout(250)


def _capture_theme(
    browser: Any, demo: str, empty: str, out: Path, prefix: str, label: str
) -> tuple[list[str], list[str]]:
    shots: list[str] = []
    context = browser.new_context(
        viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1
    )
    page = context.new_page()
    watch = Watch(page)
    _theme(page, demo, label)

    # 01 Overview, protected.
    _open(page, demo, "overview")
    page.get_by_text("Petasos is checking this agent").first.wait_for(timeout=20000)
    page.locator(".petasos-tile").first.wait_for()
    _settle(page, 1500)
    _shot(page, out, f"{prefix}-01-overview-protected", shots)

    # 03 A job change being previewed.
    page.locator("label[for='petasos-job-research']").click()
    page.locator(".petasos-preview .petasos-change").first.wait_for(timeout=15000)
    _scroll_to(page, ".petasos-grid-2")
    _settle(page)
    _shot(page, out, f"{prefix}-03-overview-choice-preview", shots)
    page.get_by_role("button", name="Cancel").first.click()
    page.wait_for_timeout(300)

    # 02 Paused, through the tab's own pause and its confirmation.
    _scroll_to(page, ".petasos-topbar")
    page.get_by_role("button", name="Pause protection").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Pause").click()
    page.get_by_text("Protection is paused").first.wait_for(timeout=20000)
    _settle(page, 1500)
    _shot(page, out, f"{prefix}-02-overview-paused", shots)
    page.get_by_role("button", name="Resume protection").click()
    page.get_by_text("Petasos is checking this agent").first.wait_for(timeout=20000)

    # 04 Activity list, everything recorded.
    _open(page, demo, "activity", "?range=all")
    page.locator(".petasos-event").first.wait_for(timeout=15000)
    _settle(page, 1000)
    _shot(page, out, f"{prefix}-04-activity-list", shots)

    # 05 One event opened: the hidden instruction in a file the agent wrote.
    row = page.locator(".petasos-event").filter(has_text="task-notes-2c91").first
    row.click()
    page.locator(".petasos-detail").wait_for(timeout=10000)
    _settle(page)
    _shot(page, out, f"{prefix}-05-activity-detail", shots)

    # 07 Try it: a hidden instruction, blocked.
    _open(page, demo, "tryit", "?example=hidden")
    page.locator(".petasos-decision").wait_for(timeout=20000)
    _settle(page)
    _shot(page, out, f"{prefix}-07-tryit-blocked", shots)

    # 08 Try it: a download piped into a shell, held for a person by saved settings, then
    # tried without that rule (not saved) and shown beside the saved answer.
    _open(page, demo, "tryit", "?example=download")
    page.locator(".petasos-finding").first.wait_for(timeout=20000)
    # Lifting one command rule can leave another underneath; lift each in turn.
    for _attempt in range(3):
        page.get_by_role("button", name="Try without this rule").first.click()
        page.locator(".petasos-compare").wait_for(timeout=20000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        if page.locator(".petasos-decision-success").count():
            break
    page.locator(".petasos-decision-success").wait_for(timeout=20000)
    _settle(page)
    _shot(page, out, f"{prefix}-08-tryit-allowed", shots)

    # 09 Settings: a value the user changed, with where each value comes from,
    # and one more change staged for review.
    _open(page, demo, "settings", "?path=tools.dangerous_posture")
    page.locator("#petasos-row-tools\\.dangerous_posture").wait_for(timeout=15000)
    page.locator("#petasos-field-tools-exempt").fill("web_search")
    page.locator(".petasos-savebar").wait_for(timeout=10000)
    page.get_by_text("ready to save").first.wait_for(timeout=10000)
    _scroll_to(page, "#petasos-row-tools\\.dangerous_posture", "center")
    _settle(page)
    _shot(page, out, f"{prefix}-09-settings-override", shots)
    page.get_by_role("button", name="Discard").click()

    # 10 Settings: an invalid value explained at the field.
    _open(page, demo, "settings", "?path=escalation.tier3")
    page.locator("#petasos-field-escalation-tier3").fill("20")
    page.locator(".petasos-field-error").first.wait_for(timeout=10000)
    _scroll_to(page, "#petasos-row-escalation\\.tier3", "center")
    _settle(page)
    _shot(page, out, f"{prefix}-10-settings-error", shots)
    page.get_by_role("button", name="Discard").click()

    # 06 Activity on a home with no record yet.
    empty_page = context.new_page()
    watch_empty = Watch(empty_page)
    _theme(empty_page, empty, label)
    _open(empty_page, empty, "activity", "?range=all")
    empty_page.get_by_text("Nothing recorded yet").wait_for(timeout=15000)
    _settle(empty_page)
    _shot(empty_page, out, f"{prefix}-06-activity-empty", shots)

    # 11 Overview at 900 pixels wide, dark theme only.
    if prefix == "teal":
        page.set_viewport_size({"width": 900, "height": HEIGHT})
        _open(page, demo, "overview")
        page.get_by_text("Petasos is checking this agent").first.wait_for(timeout=20000)
        _scroll_to(page, ".petasos-topbar")
        _settle(page, 1200)
        _shot(page, out, "11-overview-narrow", shots)

    context.close()
    return shots, watch.errors + watch_empty.errors + watch.failed + watch_empty.failed


def capture(request: dict[str, Any]) -> dict[str, Any]:
    """The fixed screenshot set, in both Hermes themes."""
    out = Path(str(request["out"]))
    out.mkdir(parents=True, exist_ok=True)
    demo = str(request["demo_url"])
    empty = str(request["empty_url"])
    shots: list[str] = []
    problems: list[str] = []
    sync = _playwright()
    with sync.sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        for prefix, label in THEMES:
            taken, seen = _capture_theme(browser, demo, empty, out, prefix, label)
            shots.extend(taken)
            problems.extend(seen)
        # Leave the demo home on the default theme for the next run.
        context = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
        page = context.new_page()
        _theme(page, demo, "Hermes Teal")
        empty_page = context.new_page()
        _theme(empty_page, empty, "Hermes Teal")
        context.close()
        browser.close()
    return {"shots": shots, "problems": problems}


def main() -> None:
    request = json.loads(sys.stdin.read() or "{}")
    action = str(request.get("action", ""))
    handlers = {"check": check, "capture": capture}
    handler = handlers.get(action)
    if handler is None:
        raise SystemExit(f"unknown action {action}")
    json.dump(handler(request), sys.stdout)


if __name__ == "__main__":
    main()
