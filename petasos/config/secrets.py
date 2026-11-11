"""Secrets the host loads and passes beside the config.

These values are not settings. They have no mapping form, and their repr
never includes a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from petasos.config.sections import PetasosConfig


def require_hash_key(config: PetasosConfig, secrets: Secrets) -> None:
    """Reject hash-mode anonymization that has no hash key.

    The config tree does not carry the key. The check runs where a config
    and a ``Secrets`` meet.
    """
    anonymization = config.anonymization
    if anonymization.enabled and anonymization.mode == "hash" and not secrets.hash_key:
        raise ValueError(
            "hash_key is required and must be non-empty when "
            "redaction_mode='hash' and anonymize=True"
        )


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


SESSION_SECRET_HELP = (
    "Secret that binds session tokens. The profile env file holds it, not config."
)
HASH_KEY_HELP = "Key for hash-mode anonymization. The profile env file holds it, not config."
