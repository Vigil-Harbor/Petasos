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
        --out .ux-reference/rounds/round-03
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
from tests.hermes_host.demo_home import build_wheel, prepare

ROOT = Path(__file__).resolve().parents[2]
BROWSER = Path(__file__).resolve().parent / "capture_browser.py"

DESCRIPTIONS = {
    "01-overview-protected": (
        "Overview with protection on: the status names what runs (basic checks) and what "
        "does not, by what each extra check looks for; the job and strictness controls sit "
        "in the same panel, each with its selected option in one line; then the last 24 "
        "hours with repeats grouped."
    ),
    "02-overview-paused": (
        "Overview after Pause protection was confirmed: the paused status, the Resume "
        "button, which checks are suspended and that they resume when protection is back "
        "on, and a Paused badge beside the tabs."
    ),
    "03-overview-choice-preview": (
        "The job switched to Research but not applied: the new job's description under the "
        "control, and an inset panel with the usual strictness for it and what that does, "
        "when the change applies, the settings it changes folded away, and Apply."
    ),
    "04-activity-list": (
        "Activity over all time: range, search and filters on the page; the count of events "
        "and blocked tool calls; one sentence per event with date, tool, conversation, a "
        "quiet severity mark and an outcome badge; nine repeats grouped into one row."
    ),
    "05-activity-detail": (
        "One event opened: its row stays marked in the list beside the detail, which names "
        "its time and conversation, the rule in words, why the matched text is not kept, and "
        "what the signature proves. Technical fields are folded away."
    ),
    "06-activity-empty": (
        "Activity on a freshly installed profile, drawn as Sessions draws an empty list."
    ),
    "07-tryit-blocked": (
        "Try it with an example chosen: a file write carrying a hidden instruction, blocked, "
        "in one sentence; the match marked in the input; the checks. The input editor and "
        "the agent's message are folded away."
    ),
    "08-tryit-allowed": (
        "A download piped into a shell, tried with its rules turned off (not saved): the "
        "trial result beside the live result, which asks a person; the trial names each "
        "rule it turns off; the trial settings below."
    ),
    "09-settings-override": (
        "Settings, Tool calls: Config's field layout; a value the user set, with the value a "
        "reset restores, and a tool exemption staged and not saved, counted beside Save."
    ),
    "10-settings-error": (
        "Settings, Escalation: stop-the-conversation set to 20, below its floor; the field "
        "says to enter 30 or higher, and its description says why. Save is not offered."
    ),
    "11-overview-narrow": "Overview at 900 pixels wide, Hermes Teal.",
    "x1-settings-review": (
        "The list of staged changes, opened from the count beside Save over the page: what "
        "changes, from what to what, and when it applies. Nothing is saved yet."
    ),
    "x2-settings-saved": (
        "After saving PromptGuard as always on: a check-marked confirmation with the time, "
        "and beneath it, separately, the setting that waits for a Hermes restart."
    ),
    "x3-overview-partial": (
        "Overview while PromptGuard is set to always on but is not installed: a failed check "
        "holding tool calls, where to run the command that adds it, the command to copy, and "
        "a link to turn it off in Settings."
    ),
    "x4-activity-search": (
        "Activity with a custom range (the last 26 hours, written year-month-day) and a "
        "search for 'settings': two attempts to change the settings, one blocked and one "
        "not stopped, and a count that agrees with them."
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sandbox", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / ".ux-reference/rounds/round-03")
    parser.add_argument("--skip-wheel", action="store_true")
    args = parser.parse_args(argv)
    sandbox = args.sandbox.resolve()
    os.environ["PETASOS_HERMES_SANDBOX"] = str(sandbox)
    if not args.skip_wheel:
        build_wheel(sandbox)
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
