"""Secrets the host loads and passes beside the config.

These values are not settings. They have no mapping form, and their repr
never includes a value.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Secrets:
    """Session-binding and hash secrets supplied beside a config.

    ``session_secret`` binds session tokens. ``hash_key`` is required, by the
    pipeline that applies the config, when anonymization mode is ``hash``.
    Either value may be absent. ``repr`` names which ones are present and
    never prints a value.
    """

    session_secret: bytes | None = None
    hash_key: str | None = None

    def __repr__(self) -> str:
        session = "set" if self.session_secret is not None else "unset"
        digest = "set" if self.hash_key is not None else "unset"
        return f"Secrets(session_secret={session}, hash_key={digest})"
