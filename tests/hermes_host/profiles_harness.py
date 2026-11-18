"""Compare live Hermes discovery with Petasos's watched paths in a sandbox."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__" and __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.hermes_host.sandbox_guard import hermes_home


def main() -> None:
    """Read profile identities and check writes without executing a tool."""
    root = hermes_home()
    os.environ["HERMES_MANAGED_DIR"] = str(root / "managed")
    managed: Any = importlib.import_module("hermes_cli.managed_scope")
    managed._DEFAULT_MANAGED_DIR = root / "machine-standin"
    profiles = importlib.import_module("hermes_cli.profiles")

    from petasos.guard.guardrail import recognize
    from petasos.hermes.doctor import examine, render_text
    from petasos.hermes.home import list_hermes_profiles
    from petasos.hermes.plugin import protected_paths

    names = profiles.list_profile_names()
    paths = protected_paths()
    watched = {}
    for name in names:
        home = root if name == "default" else root / "profiles" / name
        watched[name] = all(
            recognize("write_file", {"path": str(home / tail)}, protected=paths) is not None
            for tail in ("config.yaml", ".env", "petasos-enforcement.jsonl")
        )
    first_write = recognize(
        "write_file", {"path": str(root / "profiles" / "empty" / "SOUL.md")}, protected=paths
    )
    report = examine(root, home_reason="sandbox", probe_plugin=False)
    json.dump(
        {
            "hermes": names,
            "petasos": [p["name"] for p in list_hermes_profiles(root=root)],
            "watched": watched,
            "first_write": first_write is not None,
            "paths": sorted(paths),
            "verbose": render_text(report, verbose=True, color=False),
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
