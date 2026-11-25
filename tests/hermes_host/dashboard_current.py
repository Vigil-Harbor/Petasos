"""Exercise current-reading claims with failed status reads in the real tab."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from tests.hermes_host.capture_browser import HEIGHT, WIDTH, _named, _open, _playwright, _settle
from tests.hermes_host.dashboard_server import TOKEN


def check_current(request: dict[str, Any]) -> dict[str, Any]:
    """Inject only status facts/failures; saves still go through real Hermes."""
    base = str(request["url"])
    case = request["case"]
    report: dict[str, Any] = {"errors": [], "failed_reads": 0}
    state: dict[str, Any] = {"fail": False, "unknown": False, "secret": "signed"}
    sync = _playwright()
    with sync.sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.on("pageerror", lambda error: report["errors"].append(str(error)))
        reset = page.request.put(
            base + "/api/plugins/petasos/settings",
            headers={"X-Hermes-Session-Token": TOKEN},
            data={"enabled": True},
        )
        assert reset.ok, reset.text()

        def status(route: Any) -> None:
            if state["fail"]:
                report["failed_reads"] += 1
                route.fulfill(status=503, json={"detail": "Injected status read failure"})
                return
            response = route.fetch()
            body = response.json()
            if state["unknown"]:
                body["switches"]["hermes"]["on"] = None
            if state["secret"] != "signed":
                body["record_signing"]["signed"] = False
                checks = body["doctor"]["checks"]
                if state["secret"] == "absent":
                    body["doctor"]["checks"] = [c for c in checks if c["id"] != "session_secret"]
                else:
                    body["doctor"]["verdict"] = "protected_with_warnings"
                    for item in checks:
                        if item["id"] == "session_secret":
                            item["status"] = "warn"
            route.fulfill(response=response, json=body)

        page.route(re.compile(r"/api/plugins/petasos/status(?:\?|$)"), status)
        _open(page, base, "overview")
        page.locator(".petasos-verdict [data-petasos-state=protected]").wait_for()

        def refresh(code: str) -> None:
            page.get_by_role("button", name="Refresh now").click()
            page.locator(f".petasos [data-petasos-state={code}]").first.wait_for()
            _settle(page, 50)

        def pause() -> None:
            page.get_by_role("button", name=_named("Pause protection")).click()
            page.get_by_role("alertdialog").get_by_role("button", name=_named("Pause")).click()
            page.locator(".petasos-verdict [data-petasos-state=paused]").wait_for()
            _settle(page, 50)

        def signing_line() -> str:
            return str(
                page.locator("dt")
                .filter(has_text=_named("Session secret"))
                .locator("xpath=following-sibling::dd[1]")
                .inner_text()
            )

        if case == "scope":
            panel = page.locator(".petasos-verdict")
            report["current_rows"] = panel.locator(".petasos-coverage dt").all_text_contents()
            state["unknown"] = True
            refresh("unknown")
            report["unknown_rows"] = panel.locator(".petasos-coverage dt").all_text_contents()
            state["unknown"] = False
            refresh("protected")
            report["recovered_rows"] = panel.locator(".petasos-coverage dt").all_text_contents()
        elif case == "signing":
            _open(page, base, "settings")
            page.locator("#petasos-basic-enabled").wait_for()
            report["signed"] = signing_line()
            state["secret"] = "failed"
            refresh("warn")
            report["failed"] = signing_line()
            state["secret"] = "absent"
            refresh("protected")
            report["absent"] = signing_line()
            state["secret"] = "signed"
            refresh("protected")
            report["recovered"] = signing_line()
            # A successful save followed by a failed status read must date this line.
            state["fail"] = True
            page.locator("#petasos-basic-enabled").click()
            page.get_by_role("button", name=_named("Save")).click()
            page.locator(".petasos-statechip [data-petasos-state=paused]").wait_for()
            _settle(page, 50)
            report["stale"] = signing_line()
            state["fail"] = False
            refresh("paused")
            report["after_save"] = signing_line()
        elif case == "saved_pause":
            state["fail"] = True
            pause()
            panel = page.locator(".petasos-verdict")
            report["verdict_title"] = panel.locator(".petasos-verdict-title").inner_text()
            report["verdict_reason"] = panel.locator(".petasos-verdict-reason").inner_text()
            _open(page, base, "settings")
            banner = page.locator(".petasos > .petasos-notice").filter(
                has=page.get_by_role("button", name=_named("Resume"))
            )
            report["banner_title"] = banner.locator(".petasos-notice-title").inner_text()
            report["banner_reason"] = banner.locator(".petasos-notice-body").inner_text()
        else:
            pause()
            note = page.locator(".petasos-setup [role=status]")
            report["paused_setup_notes"] = note.all_text_contents()
            params = "?example=notes"
            if case == "resume_compare":
                params += "&settings=" + quote(json.dumps({"role": "coding"}))
            _open(page, base, "tryit", params)
            result = page.locator("#petasos-try-result")
            result.locator(".petasos-took-part [data-petasos-state]").first.wait_for()
            _settle(page, 50)
            if case == "resume_compare":
                live_note = result.locator("[data-petasos-run=live] .petasos-compare-note").last
                report["paused_live_note"] = live_note.inner_text()
            else:
                report["paused_result_notices"] = result.locator(
                    ".petasos-notice-title"
                ).all_text_contents()
            state["fail"] = True
            page.locator(".petasos > .petasos-notice").get_by_role(
                "button", name=_named("Resume")
            ).click()
            page.locator(".petasos-statechip [data-petasos-state=saved]").wait_for()
            _settle(page, 50)
            report["stale_result_notices"] = result.locator(
                ".petasos-notice-title"
            ).all_text_contents()
            report["result_retained"] = result.locator(".petasos-took-part").count() > 0
            if case == "resume_compare":
                report["stale_live_notes"] = result.locator(
                    "[data-petasos-run=live] .petasos-compare-note"
                ).all_text_contents()
            _open(page, base, "overview")
            report["saved_setup_notes"] = note.all_text_contents()
            state["fail"] = False
            refresh("protected")
            report["recovered_setup_notes"] = note.all_text_contents()
        browser.close()
    return report
