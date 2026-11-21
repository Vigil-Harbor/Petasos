"""The ``petasos`` command.

The command itself lives in ``petasos.hermes``. This module is the script
entry so the rest of the package does not import the Hermes adapter.
"""

from __future__ import annotations

import importlib


def main(argv: list[str] | None = None) -> int:
    """Run one ``petasos`` subcommand and return its exit status."""
    commands = importlib.import_module("petasos.hermes.commands")
    result = commands.main(argv)
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
