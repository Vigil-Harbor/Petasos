"""Prepare a sandbox Hermes home that shows the Petasos tab with real data.

This module never imports Hermes. It asks the sandbox harnesses to build and
install this worktree's wheel, install the plugin into a new home under
``<sandbox>/homes``, and (unless ``--empty``) drive the plugin's real hooks
through a day of activity.

    python tests/hermes_host/demo_home.py --sandbox /tmp/petasos-u1-sbx
    python tests/hermes_host/demo_home.py --sandbox /tmp/petasos-u1-sbx --empty

It prints the home path as JSON. Start a dashboard on that home with
``dashboard.py`` in this directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__" and __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.hermes_host.client import PETASOS_HARNESS, fresh_home, invoke

ROOT = Path(__file__).resolve().parents[2]
DEMO_HARNESS = Path(__file__).resolve().parent / "demo_harness.py"


def build_wheel(sandbox: Path) -> None:
    """Build this worktree's wheel and install it into the sandbox interpreter."""
    result = invoke(
        sandbox,
        {"action": "install_wheel", "worktree": str(ROOT)},
        harness=PETASOS_HARNESS,
        timeout=300,
    )
    if not result.get("ok"):
        raise RuntimeError(f"install_wheel failed: {result}")


def prepare(sandbox: Path, label: str, *, populate: bool = True) -> dict[str, Any]:
    """A new home with the plugin installed, and activity unless ``populate`` is false."""
    home = fresh_home(sandbox, label)
    installed = invoke(
        sandbox,
        {"action": "install_home", "worktree": str(ROOT)},
        home=home,
        harness=PETASOS_HARNESS,
        timeout=300,
    )
    if not installed.get("ok"):
        raise RuntimeError(f"install_home failed: {installed}")
    report: dict[str, Any] = {"home": str(home), "events": 0, "steps": []}
    if populate:
        filled = invoke(
            sandbox,
            {"action": "populate"},
            home=home,
            harness=DEMO_HARNESS,
            timeout=300,
        )
        report.update(filled)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sandbox", required=True, type=Path)
    parser.add_argument("--label", default="demo")
    parser.add_argument("--empty", action="store_true", help="install only, no activity")
    parser.add_argument("--skip-wheel", action="store_true", help="reuse the built wheel")
    args = parser.parse_args(argv)
    sandbox = args.sandbox.resolve()
    import os

    os.environ["PETASOS_HERMES_SANDBOX"] = str(sandbox)
    if not args.skip_wheel:
        build_wheel(sandbox)
    report = prepare(sandbox, args.label, populate=not args.empty)
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
