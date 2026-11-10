"""``python -m petasos`` runs the command.

The Hermes adapter is imported by name so this module does not depend on it
at import time.
"""

from __future__ import annotations

import importlib
import sys


def main() -> int:
    """Run the command and return its exit status."""
    commands = importlib.import_module("petasos.hermes.commands")
    return int(commands.main(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
