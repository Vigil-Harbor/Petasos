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
        --out .ux-reference/rounds/round-01
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
        "Overview with protection on: the verdict, the job and strictness choices, the last "
        "24 hours, what is doing the checking, and who can change the settings."
    ),
    "02-overview-paused": (
        "Overview after Pause protection was confirmed: the paused verdict, what pausing "
        "means, and the Resume button."
    ),
    "03-overview-choice-preview": (
        "The job switched to Research but not applied: the preview beside the choices lists "
        "each setting that would change, before and after, and suggests the matching strictness."
    ),
    "04-activity-list": (
        "Activity over all time: filters, the signed-record badge, and one plain sentence per "
        "event with when, tool, conversation, seriousness and outcome."
    ),
    "05-activity-detail": (
        "One event opened: a blocked file write that carried hidden instructions, with the "
        "rule in plain words, the record's signature status, and links to its settings."
    ),
    "06-activity-empty": (
        "Activity on a freshly installed profile: what will appear here and a way to see it work."
    ),
    "07-tryit-blocked": (
        "Try it with the hidden-instruction example: blocked, what the agent would be told, "
        "the finding marked in the text, and the checks that ran."
    ),
    "08-tryit-allowed": (
        "The same input tried without that rule (not saved): allowed, shown beside the "
        "saved settings' answer (blocked)."
    ),
    "09-settings-override": (
        "Settings, Tools section: a value the user changed (Your change) beside values from "
        "the default, and a second change (a tool exemption) staged and waiting for review."
    ),
    "10-settings-error": (
        "Settings, Escalation section: an invalid value (tier 3 below its floor) explained at "
        "the field with the API's sentence; Save is disabled."
    ),
    "11-overview-narrow": "Overview at 900 pixels wide, Hermes Teal.",
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
        "# Round 01 screenshots",
        "",
        "The Petasos tab in a sandboxed Hermes `v0.23.1` dashboard, 1440 by 900 unless noted.",
        "Activity comes from the plugin's real hooks (`tests/hermes_host/demo_harness.py`),",
        "spread over the last day. Retake with `tests/hermes_host/capture_round.py`.",
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
    parser.add_argument("--out", type=Path, default=ROOT / ".ux-reference/rounds/round-01")
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
