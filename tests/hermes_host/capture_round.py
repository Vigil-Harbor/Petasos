"""Take one design round's screenshots of the Petasos tab against real Hermes.

This module never imports Hermes. It builds this worktree's wheel, prepares
two sandbox homes (one with a day of real activity, one empty), starts a
dashboard on each (127.0.0.1, free ports, own process groups), drives them
with ``capture_browser.py`` inside the sandbox, stops both dashboards, and
writes ``INDEX.md`` beside the images.

The browser lives in the sandbox, not in this repository's environment:

    uv venv -p 3.11 <sandbox>/shot
    uv pip install -p <sandbox>/shot/bin/python playwright
    PLAYWRIGHT_BROWSERS_PATH=<sandbox>/opt/ms-playwright \\
        <sandbox>/shot/bin/python -m playwright install chromium-headless-shell

Then:

    python tests/hermes_host/capture_round.py --sandbox <sandbox> \\
        --out .ux-reference/rounds/round-04
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__" and __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.hermes_host.client import sandbox_env
from tests.hermes_host.dashboard_server import start, stop
from tests.hermes_host.demo_home import build_wheel, prepare, prepare_trial

ROOT = Path(__file__).resolve().parents[2]
BROWSER = Path(__file__).resolve().parent / "capture_browser.py"

DESCRIPTIONS = {
    "01-overview-protected": (
        "Overview with protection on: a Protection panel with an On badge in its header and "
        "Pause protection at the header's end; one line for the state, then compact rows for "
        "what protection covers, what runs and what does not (each check named by what it "
        "does, product after it); the job and strictness choices beneath. Then the last 24 "
        "hours: figures with labels above the values, adding up to the event total, and "
        "recent events with repeats grouped, including a settings change and an attempt the "
        "agent was not allowed to make. Who can change these settings is below this view."
    ),
    "02-overview-paused": (
        "Overview after Pause protection was confirmed, taken taller than the window (1440 by "
        "the height that reaches the Checks panel): the Paused badge beside the tabs and in "
        "the Protection header, Resume protection, which checks are paused; the Checks panel "
        "shows Basic checks as Paused and the extra checks as Not installed or Off."
    ),
    "03-overview-choice-preview": (
        "The job switched to Research but not applied: the new job's description under the "
        "control, and a panel saying when the change applies, the settings it changes folded "
        "away, what Relaxed strictness trades in one sentence, and buttons: Apply Research "
        "with Balanced, Try it first, Cancel."
    ),
    "04-activity-list": (
        "Activity over all time: range, search and filters; the count of events and blocked "
        "tool calls with the time zone named once; one sentence per event saying what the "
        "agent tried to do, with the tool and conversation on one line beneath, a 24-hour "
        "time, severity as a word (Conversation risk, or No rule, where a rank does not "
        "apply) and an outcome badge; a badge of how many signatures were verified, with "
        "what that does not prove one click away; nine repeats grouped into one row."
    ),
    "05-activity-detail": (
        "One event opened: its row stays marked in the list beside the detail, which names "
        "its time with the time zone, the rule in words, that the matched text is not kept, "
        "and what the signature proves; Try this rule opens Try it on that rule. Technical "
        "fields are folded away."
    ),
    "06-activity-empty": (
        "Activity on a freshly installed profile, drawn as Sessions draws an empty list: what "
        "is recorded (blocks, approval requests and warnings) and that clean actions are not."
    ),
    "07-tryit-blocked": (
        "Try it with an example chosen: a file write carrying a hidden instruction, blocked, "
        "in one sentence; the match marked in the input; the rule with a Try without this "
        "rule button; beneath, full width, the checks in this run, each named by what it does."
    ),
    "08-tryit-allowed": (
        "A download piped into a shell, tried with its two rules turned off (not saved): the "
        "trial result beside the live result, which asks a person; one Check with trial "
        "settings button; the trial settings beneath, one row per rule turned off (its "
        "sentence, its id, Turn back on), the JSON folded under Technical detail, and Copy to "
        "Settings."
    ),
    "09-settings-override": (
        "Settings, Tool calls: Config's field layout; under each control one line with the "
        "value and where it comes from (On · Default; Ask a person for approval · Your "
        "setting · Reset to Block it); a tool exemption staged and not saved, with Undo; an "
        "empty mapping with Add; the count of unsaved changes beside Discard all, Try it "
        "first and Save."
    ),
    "10-settings-error": (
        "Settings, Escalation: stop-the-conversation set to 20, below its floor; the field "
        "says to enter 30 or higher, and its description says what a stopped conversation "
        "means and how to carry on. Save is not offered."
    ),
    "11-overview-narrow": "Overview at 900 pixels wide, Hermes Teal.",
    "x1-settings-review": (
        "The list of staged changes, opened from the count beside Save as a panel under the "
        "toolbar that pushes the form down: what changes, from what to what, and when it "
        "applies. Nothing is saved yet."
    ),
    "x2-settings-saved": (
        "After saving PromptGuard as Required while it is not installed: a check-marked "
        "confirmation with the time. It says an agent started from now on uses the saved "
        "value, and an agent already running keeps the previous value until it restarts. "
        "Under the control, the consequence is attached with Once in use."
    ),
    "x3-overview-partial": (
        "Overview while PromptGuard is Required but not installed: a failed check, what that "
        "does to tool calls under the current settings, where to run the command that adds "
        "it, the command to copy, and a link to turn it off in Settings."
    ),
    "x4-activity-search": (
        "Activity with a custom range (the last 26 hours, written year-month-day) and a "
        "search for 'settings': blocked attempts (nobody could be asked, and a change the "
        "agent is not allowed to make) and the applied settings changes, with a count that "
        "agrees with the rows."
    ),
    "x5-keyboard-focus": "Overview with keyboard focus, reached with Tab, on Pause protection.",
}

THEME_NAMES = {"teal": "Hermes Teal (dark)", "nous-blue": "Nous Blue (light)"}


def run_browser(sandbox: Path, request: dict[str, Any], *, timeout: float = 900) -> dict[str, Any]:
    """Run ``capture_browser.py`` inside the sandbox wrapper and return its JSON."""
    python = sandbox / "shot" / "bin" / "python"
    if not python.is_file():
        raise FileNotFoundError(f"no browser environment at {python}; see this module's docstring")
    env = sandbox_env(None)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(sandbox / "opt" / "ms-playwright")
    completed = subprocess.run(
        [str(sandbox / "bin" / "with-sandbox"), str(python), str(BROWSER)],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"browser {request.get('action')} exited {completed.returncode}\n"
            f"{completed.stdout[-2000:]}\n{completed.stderr[-4000:]}"
        )
    result: dict[str, Any] = json.loads(completed.stdout)
    return result


def write_index(out: Path, shots: list[str]) -> Path:
    """Provide write index for the test fixture."""
    lines = [
        "# Petasos tab screenshots",
        "",
        "The Petasos tab in a sandboxed Hermes `v0.23.1` dashboard, 1440 by 900 unless noted.",
        "Activity comes from the plugin's real hooks (`tests/hermes_host/demo_harness.py`),",
        "spread over the last day.",
        "",
        "| File | Theme | What it shows |",
        "|---|---|---|",
    ]
    for name in shots:
        stem = name.removesuffix(".png")
        theme = "teal"
        key = stem
        for prefix in THEME_NAMES:
            if stem.startswith(prefix + "-"):
                theme = prefix
                key = stem[len(prefix) + 1 :]
        lines.append(f"| `{name}` | {THEME_NAMES[theme]} | {DESCRIPTIONS.get(key, '')} |")
    path = out / "INDEX.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    """Run the isolated test harness."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sandbox", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / ".ux-reference/rounds/round-04")
    parser.add_argument("--skip-wheel", action="store_true")
    parser.add_argument("--tryit-followups", action="store_true")
    args = parser.parse_args(argv)
    sandbox = args.sandbox.resolve()
    os.environ["PETASOS_HERMES_SANDBOX"] = str(sandbox)
    if not args.skip_wheel:
        build_wheel(sandbox)
    if args.tryit_followups:
        home = prepare_trial(sandbox)
        board = start(sandbox, home)
        try:
            result = run_browser(
                sandbox, {"action": "followups", "url": board.url, "out": str(args.out.resolve())}
            )
        finally:
            stopped_trial = stop(board.pid)
        result["dashboard_stopped"] = stopped_trial
        print(json.dumps(result, indent=2))
        return 0 if stopped_trial and not result["errors"] and not result["failed"] else 1
    demo = Path(prepare(sandbox, "round-demo")["home"])
    empty = Path(prepare(sandbox, "round-empty", populate=False)["home"])
    boards = []
    try:
        boards.append(start(sandbox, demo))
        boards.append(start(sandbox, empty))
        result = run_browser(
            sandbox,
            {
                "action": "capture",
                "demo_url": boards[0].url,
                "empty_url": boards[1].url,
                "out": str(args.out.resolve()),
            },
        )
    finally:
        stopped = []
        for board in boards:
            try:
                stopped.append(stop(board.pid))
            except Exception:
                stopped.append(False)
    index = write_index(args.out.resolve(), list(result["shots"]))
    json.dump(
        {
            "shots": result["shots"],
            "problems": result["problems"],
            "index": str(index),
            "dashboards_stopped": all(stopped),
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0 if all(stopped) and not result["problems"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
