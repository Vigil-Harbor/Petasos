"""Join the dashboard tab's sources into the one script Hermes loads.

Petasos ships no JavaScript toolchain. The tab is written as plain script
files in ``hermes-plugin/petasos/dashboard/src/``; this joins them, in name
order, inside one function, and embeds ``style.css`` as text the script
adds to the page. The result is ``hermes-plugin/petasos/dashboard/index.js``.

    python scripts/build_dashboard.py          # write index.js
    python scripts/build_dashboard.py --check  # exit 1 when index.js is stale

``tests/hermes/dashboard/test_bundle.py`` fails when the committed file is
not what this produces.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1] / "hermes-plugin" / "petasos" / "dashboard"
SOURCES = DASHBOARD / "src"
TARGET = DASHBOARD / "index.js"
STYLE_ID = "petasos-tab-style"

_HEADER = """\
/*
 * Petasos tab for the Hermes dashboard.
 *
 * Generated from src/ by scripts/build_dashboard.py. Edit the files in src/
 * and run that script; a test fails when this file is stale.
 *
 * Plain script, no build step: React, the components and the API client
 * all come from window.__HERMES_PLUGIN_SDK__. Every Petasos fact shown here
 * comes from /api/plugins/petasos/.
 */
"""

_STYLE = """\
// ---------------------------------------------------------------------------
// The layout rules from src/style.css, added once. Hermes's manifest can name
// a style sheet, but the installer copies only this script, so it carries
// the rules itself.
// ---------------------------------------------------------------------------

var STYLE = {css};

(function addStyle() {{
  if (document.getElementById("{style_id}")) return;
  var element = document.createElement("style");
  element.id = "{style_id}";
  element.textContent = STYLE;
  document.head.appendChild(element);
}})();
"""


def _indent(text: str) -> str:
    lines = text.rstrip("\n").split("\n")
    return "\n".join(("  " + line) if line else "" for line in lines)


def render_index(sources: Path = SOURCES) -> str:
    """The text of index.js for the sources in ``sources``."""
    scripts = sorted(sources.glob("*.js"))
    if not scripts:
        raise FileNotFoundError(f"no dashboard sources in {sources}")
    css = (sources / "style.css").read_text(encoding="utf-8")
    parts: list[str] = []
    for index, path in enumerate(scripts):
        parts.append(f"// ===== src/{path.name} =====\n" + path.read_text(encoding="utf-8"))
        if index == 0:
            parts.append(_STYLE.format(css=json.dumps(css), style_id=STYLE_ID))
    body = "\n".join(_indent(part) for part in parts)
    return _HEADER + '(function () {\n  "use strict";\n\n' + body + "\n})();\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Join the dashboard tab sources.")
    parser.add_argument("--check", action="store_true", help="exit 1 when index.js is stale")
    args = parser.parse_args(argv)
    text = render_index()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            sys.stderr.write("index.js is stale. Run: python scripts/build_dashboard.py\n")
            return 1
        return 0
    TARGET.write_text(text, encoding="utf-8")
    sys.stdout.write(f"wrote {TARGET} ({len(text.splitlines())} lines)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
