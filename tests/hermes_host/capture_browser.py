"""Drive the Petasos tab in a headless browser. Runs inside the sandbox.

Run only through the sandbox wrapper, with a Python that has Playwright
(``<sandbox>/shot/bin/python``; see ``capture_round.py``). One JSON object on
stdin, one on stdout. Actions:

- ``check``: open each view and report script errors, failed API calls, and
  views that render nothing. The real-Hermes test reads this.
- ``capture``: take the fixed screenshot set for one design round.
- ``loop``: record and encode the README preview (requires Pillow in ``shot``).

It does not import Hermes. It talks to dashboards already started on
127.0.0.1 by the caller.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__" and __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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


_UNSCROLL = """() => {
  for (const node of document.querySelectorAll('*')) {
    if (node.scrollTop) node.scrollTop = 0;
  }
}"""


def _unscroll(page: Any) -> None:
    """Put every scrolled container back at its top, Hermes's frame included.

    Keyboard focus moving through Hermes's sidebar scrolls the app frame, and
    that scroll would carry into every later picture.
    """
    page.evaluate(_UNSCROLL)


def _open(page: Any, base: str, view: str, params: str = "") -> None:
    """Open the tab, then the view. Hermes drops a fragment on arrival."""
    if "/petasos" not in page.url:
        page.goto(base + "/petasos", wait_until="domcontentloaded")
        page.locator(".petasos-topbar").wait_for(timeout=30000)
    _unscroll(page)
    page.evaluate("(h) => { window.location.hash = h; }", view + params)
    page.wait_for_timeout(300)
    page.locator(".petasos-view").wait_for(timeout=15000)


def _settle(page: Any, ms: int = 700) -> None:
    page.wait_for_load_state("networkidle")
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


_FOCUS_WALK = """() => {
  const el = document.activeElement;
  if (!el || el === document.body) return {where: 'body'};
  const tab = document.querySelector('.petasos');
  const inside = Boolean(tab && tab.contains(el));
  const style = getComputedStyle(el);
  const visible = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0
    || (style.boxShadow && style.boxShadow !== 'none');
  const label = (el.getAttribute('aria-label') || el.innerText || el.value || el.id || el.tagName)
    .trim().slice(0, 60);
  return {
    where: inside ? 'tab' : 'page', label: label, tag: el.tagName, id: el.id, visible: visible,
  };
}"""

_FOCUSABLE = """() => {
  const tab = document.querySelector('.petasos');
  if (!tab) return 0;
  return Array.from(tab.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), '
    + 'select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
  )).filter((el) => el.offsetParent !== null).length;
}"""


def focus_walk(page: Any, limit: int = 120) -> dict[str, Any]:
    """Press Tab from the top of the page and report where focus went.

    ``entered`` is true when focus reached the tab, ``left`` when it went on
    past the tab's last control, ``stolen`` when a control inside the view had
    focus before any key was pressed, and ``invisible`` lists controls that
    took focus without a visible ring.
    """
    before = page.evaluate(_FOCUS_WALK)
    view = page.locator(".petasos-view").first
    stolen = before.get("where") == "tab" and bool(
        view.evaluate("(v) => v.contains(document.activeElement)")
    )
    page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); }")
    page.locator("body").focus()
    seen: list[str] = []
    invisible: list[str] = []
    entered = False
    left = False
    for _ in range(limit):
        page.keyboard.press("Tab")
        now = page.evaluate(_FOCUS_WALK)
        if now.get("where") == "tab":
            entered = True
            key = f"{now.get('tag')}#{now.get('id')}:{now.get('label')}"
            seen.append(key)
            if not now.get("visible"):
                invisible.append(key)
        elif entered:
            left = True
            break
    return {
        "entered": entered,
        "left": left,
        "stolen": stolen,
        "distinct": len(set(seen)),
        "focusable": page.evaluate(_FOCUSABLE),
        "invisible": sorted(set(invisible)),
    }


def check(request: dict[str, Any]) -> dict[str, Any]:
    """Load every view once and report what went wrong, if anything."""
    base = str(request["url"])
    report: dict[str, Any] = {"views": {}, "errors": [], "failed": [], "focus": {}}
    sync = _playwright()
    with sync.sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        watch = Watch(page)
        for view in VIEWS:
            _open(page, base, view)
            if view == "overview":
                page.get_by_text("Who can change these settings").wait_for(timeout=20000)
                page.get_by_text("Last 24 hours").wait_for(timeout=20000)
            elif view == "activity":
                page.get_by_text("signatures verified").wait_for(timeout=20000)
            elif view == "tryit":
                page.get_by_text("adds no Activity record").wait_for(timeout=20000)
            _settle(page, 1200)
            panel = page.locator(".petasos-view")
            text = panel.inner_text().strip()
            selected = page.locator("[role=tab][aria-selected=true]").first.inner_text().strip()
            report["views"][view] = {
                "chars": len(text),
                "selected": selected,
                "loading": "Loading" in text[:40],
                "head": text[:160],
                "text": text,
            }
            if view == "activity" and page.locator("#petasos-activity-search").count():
                field = page.locator("#petasos-activity-search")
                report["activity_search"] = {
                    "label": field.get_attribute("aria-label"),
                    "placeholder": field.get_attribute("placeholder"),
                }
            if view == "settings" and page.locator("#petasos-settings-search").count():
                field = page.locator("#petasos-settings-search")
                report["settings_search"] = {
                    "label": field.get_attribute("aria-label"),
                    "placeholder": field.get_attribute("placeholder"),
                }
            report["focus"][view] = focus_walk(page)
        report["paused"] = paused_states(page, base)
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


def _tab_to(page: Any, name: str, limit: int = 80) -> bool:
    """Move keyboard focus with Tab until it rests on a control named ``name``.

    Form buttons are set in upper case, so the rendered text is compared
    without regard to case.
    """
    page.locator("body").focus()
    for _ in range(limit):
        page.keyboard.press("Tab")
        label = page.evaluate(
            "() => (document.activeElement && (document.activeElement.innerText || '')).trim()"
        )
        if label.lower() == name.lower():
            return True
    return False


def _named(text: str) -> Any:
    """A whole, case-blind accessible name: form buttons render in upper case."""
    return re.compile("^" + re.escape(text) + "$", re.IGNORECASE)


_PROTECTED = ".petasos-verdict [data-petasos-state=protected]"


_STATES = """() => Array.from(document.querySelectorAll('.petasos-view [data-petasos-state]'))
  .filter((el) => el.closest('.petasos-scanners, .petasos-took-part'))
  .map((el) => el.getAttribute('data-petasos-state'))"""


def paused_states(page: Any, base: str) -> dict[str, Any]:
    """Pause protection through the tab, read every check's state, then resume.

    Returns the state codes the Overview's Checks panel and Try it's list of
    checks show while paused, and the sentences on the Overview.
    """
    _open(page, base, "overview")
    page.locator(_PROTECTED).first.wait_for(timeout=20000)
    page.get_by_role("button", name=_named("Pause protection")).click()
    page.get_by_role("alertdialog").get_by_role("button", name=_named("Pause")).click()
    page.get_by_text("Protection is paused").first.wait_for(timeout=20000)
    page.locator(".petasos-scanners [data-petasos-state]").first.wait_for(timeout=15000)
    _settle(page, 600)
    found: dict[str, Any] = {"overview": page.evaluate(_STATES)}
    found["overview_text"] = page.locator(".petasos-view").inner_text()
    _open(page, base, "tryit", "?example=notes")
    page.locator(".petasos-took-part [data-petasos-state]").first.wait_for(timeout=20000)
    _settle(page, 600)
    found["tryit"] = page.evaluate(_STATES)
    _open(page, base, "overview")
    page.get_by_role("button", name=_named("Resume protection")).click()
    page.locator(_PROTECTED).first.wait_for(timeout=20000)
    return found


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

    _open(page, demo, "overview")
    page.locator(_PROTECTED).first.wait_for(timeout=20000)
    page.locator(".petasos-figure").first.wait_for()
    _settle(page, 1500)
    _shot(page, out, f"{prefix}-01-overview-protected", shots)

    page.locator("#petasos-choose-job-research").click()
    page.locator(".petasos-preview .petasos-when").first.wait_for(timeout=15000)
    _scroll_to(page, ".petasos-topbar")
    _settle(page)
    _shot(page, out, f"{prefix}-03-overview-choice-preview", shots)
    page.locator(".petasos-preview").get_by_role("button", name=_named("Cancel")).click()
    page.wait_for_timeout(300)

    _scroll_to(page, ".petasos-topbar")
    page.get_by_role("button", name=_named("Pause protection")).click()
    page.get_by_role("alertdialog").get_by_role("button", name=_named("Pause")).click()
    page.get_by_text("Protection is paused").first.wait_for(timeout=20000)
    page.locator(".petasos-scanners [data-petasos-state=paused]").first.wait_for(timeout=20000)
    _settle(page, 1500)
    bottom = page.locator("#petasos-checks").evaluate("(e) => e.getBoundingClientRect().bottom")
    tall = max(HEIGHT, int(bottom) + 24)
    page.set_viewport_size({"width": WIDTH, "height": tall})
    _settle(page, 600)
    _shot(page, out, f"{prefix}-02-overview-paused", shots)
    page.set_viewport_size({"width": WIDTH, "height": HEIGHT})
    page.get_by_role("button", name=_named("Resume protection")).click()
    page.locator(_PROTECTED).first.wait_for(timeout=20000)

    _open(page, demo, "overview")
    page.locator(_PROTECTED).first.wait_for(timeout=20000)
    _settle(page, 800)
    if _tab_to(page, "Pause protection"):
        _unscroll(page)
        page.wait_for_timeout(300)
        _shot(page, out, f"{prefix}-x5-keyboard-focus", shots)

    _open(page, demo, "activity", "?range=all")
    page.locator(".petasos-event").first.wait_for(timeout=15000)
    _settle(page, 1000)
    _shot(page, out, f"{prefix}-04-activity-list", shots)

    row = page.locator(".petasos-event").filter(has_text="task-notes-2c91").first
    row.click()
    page.locator(".petasos-detail").wait_for(timeout=10000)
    _settle(page)
    _shot(page, out, f"{prefix}-05-activity-detail", shots)

    window = page.evaluate(
        """() => {
          const pad = (n) => String(n).padStart(2, '0');
          const fmt = (d) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
            + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
          const now = new Date();
          const from = new Date(now.getTime() - 26 * 3600 * 1000);
          return {from: fmt(from), to: fmt(now)};
        }"""
    )
    _open(
        page,
        demo,
        "activity",
        f"?range=custom&from={window['from']}&to={window['to']}&q=settings",
    )
    page.locator(".petasos-event").first.wait_for(timeout=15000)
    _settle(page, 1000)
    _shot(page, out, f"{prefix}-x4-activity-search", shots)

    _open(page, demo, "tryit", "?example=notes")
    page.locator(".petasos-decision").first.wait_for(timeout=20000)
    _settle(page)
    _shot(page, out, f"{prefix}-07-tryit-blocked", shots)

    _open(page, demo, "tryit", "?example=download")
    page.locator(".petasos-finding").first.wait_for(timeout=20000)
    for _attempt in range(3):
        page.get_by_role("button", name=_named("Try without this rule")).first.click()
        page.locator(".petasos-compare").wait_for(timeout=20000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        if page.locator(".petasos-compare-cell").first.get_by_text("Trial: Allowed").count():
            break
    page.locator(".petasos-compare-cell").first.get_by_text("Trial: Allowed").wait_for(
        timeout=20000
    )
    _settle(page)
    _shot(page, out, f"{prefix}-08-tryit-allowed", shots)

    _open(page, demo, "settings", "?path=tools.dangerous_posture")
    page.locator("#petasos-row-tools\\.dangerous_posture").wait_for(timeout=15000)
    page.locator("#petasos-field-tools-exempt").fill("web_search")
    page.get_by_text("1 unsaved change").first.wait_for(timeout=10000)
    _scroll_to(page, "#petasos-row-tools\\.dangerous_posture", "center")
    _settle(page)
    _shot(page, out, f"{prefix}-09-settings-override", shots)

    page.locator(".petasos-changecount").click()
    page.locator(".petasos-sheet").wait_for(timeout=10000)
    _settle(page)
    _shot(page, out, f"{prefix}-x1-settings-review", shots)
    page.locator(".petasos-sheet").get_by_role("button", name="Close the list of changes").click()
    page.get_by_role("button", name=re.compile("^Discard all", re.IGNORECASE)).click()

    _open(page, demo, "settings", "?path=escalation.tier3")
    page.locator("#petasos-field-escalation-tier3").fill("20")
    page.locator(".petasos-field-error").first.wait_for(timeout=10000)
    _scroll_to(page, "#petasos-row-escalation\\.tier3", "center")
    _settle(page)
    _shot(page, out, f"{prefix}-10-settings-error", shots)
    page.get_by_role("button", name=re.compile("^Discard all", re.IGNORECASE)).click()

    _open(page, demo, "settings", "?path=scanners.prompt_guard.enabled")
    page.locator("#petasos-field-scanners-prompt_guard-enabled").click()
    page.get_by_role("option", name="Required").click()
    page.get_by_text("1 unsaved change").first.wait_for(timeout=10000)
    page.locator(".petasos-consequence").first.wait_for(timeout=10000)
    page.locator(".petasos-savebox").get_by_role("button", name=_named("Save")).click()
    page.get_by_text("Saved at").first.wait_for(timeout=15000)
    _scroll_to(page, ".petasos-topbar")
    _settle(page)
    _shot(page, out, f"{prefix}-x2-settings-saved", shots)

    _open(page, demo, "overview")
    page.locator(".petasos-verdict").wait_for(timeout=20000)
    page.wait_for_timeout(1500)
    _settle(page, 1200)
    _shot(page, out, f"{prefix}-x3-overview-partial", shots)

    _open(page, demo, "settings", "?path=scanners.prompt_guard.enabled")
    page.locator("#petasos-row-scanners\\.prompt_guard\\.enabled").get_by_role(
        "button", name=re.compile("^Reset ", re.IGNORECASE)
    ).click()
    page.get_by_role("alertdialog").get_by_role("button", name=_named("Reset")).click()
    page.get_by_text("Saved at").first.wait_for(timeout=15000)

    empty_page = context.new_page()
    watch_empty = Watch(empty_page)
    _theme(empty_page, empty, label)
    _open(empty_page, empty, "activity", "?range=all")
    empty_page.get_by_text("Nothing recorded yet").wait_for(timeout=15000)
    _settle(empty_page)
    _shot(empty_page, out, f"{prefix}-06-activity-empty", shots)

    if prefix == "teal":
        page.set_viewport_size({"width": 900, "height": HEIGHT})
        _open(page, demo, "overview")
        page.locator(_PROTECTED).first.wait_for(timeout=20000)
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
        context = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
        page = context.new_page()
        _theme(page, demo, "Hermes Teal")
        empty_page = context.new_page()
        _theme(empty_page, empty, "Hermes Teal")
        context.close()
        browser.close()
    return {"shots": shots, "problems": problems}


def followups(request: dict[str, Any]) -> dict[str, Any]:
    """Exercise the new result blocks against a real sandbox API, and optionally capture."""
    base = str(request["url"])
    out = Path(str(request["out"])) if request.get("out") else None
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"shots": [], "states": [], "errors": [], "failed": []}
    sync = _playwright()
    with sync.sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        for prefix, label in THEMES:
            for width in (1440, 700):
                context = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
                page = context.new_page()
                watch = Watch(page)
                _theme(page, base, label)
                page.set_viewport_size({"width": width, "height": HEIGHT})
                _open(page, base, "tryit")
                page.get_by_role("button", name="Edit the input").click()
                page.get_by_role("radio", name="Text", exact=True).click()
                page.locator("#petasos-try-text").fill(
                    "Please contact someone@example.org about the meeting."
                )
                page.get_by_role("button", name=_named("Check"), exact=True).click()
                preview = page.get_by_label("Text with personal information hidden")
                preview.wait_for(timeout=20000)
                page.get_by_role("button", name="Hide the editor").click()
                explain = page.get_by_role("button", name="How conversation risk works")
                if explain.count():
                    explain.first.click()
                _unscroll(page)
                _settle(page)
                report["states"].append(
                    {
                        "theme": prefix,
                        "width": width,
                        "hidden": preview.inner_text(),
                        "result": page.locator(".petasos-result").inner_text(),
                        "version": page.locator(".petasos-topbar-side").inner_text(),
                        "check_rows": page.locator(".petasos-took-part li").evaluate_all(
                            "rows => rows.map(e => e.getBoundingClientRect().top)"
                        ),
                        "overflow": page.locator(".petasos").evaluate(
                            "e => e.scrollWidth > e.clientWidth"
                        ),
                    }
                )
                if out is not None:
                    bottom = page.locator(".petasos-result").evaluate(
                        "e => e.getBoundingClientRect().bottom"
                    )
                    page.set_viewport_size(
                        {"width": width, "height": max(HEIGHT, int(bottom) + 30)}
                    )
                    _unscroll(page)
                    _settle(page)
                    _shot(page, out, f"{prefix}-tryit-{width}", report["shots"])
                report["errors"].extend(watch.errors)
                report["failed"].extend(watch.failed)
                report["states"][-1]["focus"] = focus_walk(page)
                context.close()
        browser.close()
    return report


def main() -> None:
    from tests.hermes_host.capture_loop import record

    request = json.loads(sys.stdin.read() or "{}")
    action = str(request.get("action", ""))
    handlers = {"check": check, "capture": capture, "followups": followups, "loop": record}
    handler = handlers.get(action)
    if handler is None:
        raise SystemExit(f"unknown action {action}")
    json.dump(handler(request), sys.stdout)


if __name__ == "__main__":
    main()
