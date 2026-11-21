"""Stand-in wheel. The directory plugin imports ``register`` from here."""

from standin_hostfacts.plugin import HOOKS, register  # type: ignore[import-not-found]

__all__ = ["HOOKS", "register"]
