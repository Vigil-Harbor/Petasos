"""Which Hermes home the dashboard is acting for.

The home is Hermes's own resolution: the context-local override, then
``HERMES_HOME``, then the active profile. A request cannot name a path.
Reads and writes both use that home, so a process that serves more than one
profile follows whichever one is active on this call.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from petasos.hermes.dashboard.errors import ApiError
from petasos.hermes.settings import (
    HASH_ENV,
    PLUGIN_ID,
    SESSION_ENV,
    profile_binding,
    read_profile_env,
)


@dataclass(frozen=True, slots=True)
class HomeState:
    """One active home, as far as the dashboard needs to read it.

    ``spool_key`` is the derived verification key, not the session secret.
    It is never placed in a response.
    """

    home: Path
    stored: dict[str, Any]
    secrets: dict[str, str]
    spool_key: bytes | None
    verification: str
    hermes_enabled: bool | None
    hermes_detail: str
    plugin_dir: Path
    spool: Path
    spool_rot: Path
    readable: bool


def active_home() -> Path:
    """The home Hermes is using for this call. Never a path from the client."""
    from petasos.hermes.home import resolve_hermes_config_path

    return resolve_hermes_config_path(use_override=True).path.parent


def load_home(home: Path) -> HomeState:
    """Read the active home's settings, switches, and spool location.

    A missing file is an empty settings document. An unreadable file is
    reported and not guessed.
    """
    config_path = home / "config.yaml"
    kind, settings = profile_binding(config_path)
    readable = kind != "broken"
    stored = settings if isinstance(settings, dict) else {}
    document = _document(config_path)
    enabled, detail = _hermes_switch(document, readable)
    session_state, spool_key, verification = _session(home)
    hash_state = "set" if read_profile_env(home, HASH_ENV) else "unset"
    spool = home / "petasos-enforcement.jsonl"
    return HomeState(
        home=home,
        stored=stored,
        secrets={"session_secret": session_state, "hash_key": hash_state},
        spool_key=spool_key,
        verification=verification,
        hermes_enabled=enabled,
        hermes_detail=detail,
        plugin_dir=home / "plugins" / PLUGIN_ID,
        spool=spool,
        spool_rot=Path(str(spool) + ".rot"),
        readable=readable,
    )


def require_plugin_dir(state: HomeState) -> Path:
    """The installed plugin directory, or an error a person can act on."""
    if not (state.plugin_dir / "plugin.yaml").is_file():
        raise ApiError(
            "not_installed",
            "Petasos is not installed for this profile, so settings cannot be saved.",
            status=409,
        )
    return state.plugin_dir


def _document(path: Path) -> object:
    from petasos.hermes.host import load_mapping

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return load_mapping(text)


def _hermes_switch(document: object, readable: bool) -> tuple[bool | None, str]:
    if not readable:
        return None, "The settings file could not be read, so the plugin switch is unknown."
    if not isinstance(document, dict):
        return False, "Petasos is not in Hermes's enabled plugins."
    plugins = document.get("plugins")
    if not isinstance(plugins, Mapping):
        return False, "Petasos is not in Hermes's enabled plugins."
    disabled = plugins.get("disabled")
    enabled = plugins.get("enabled")
    disabled_names = _names(disabled)
    enabled_names = _names(enabled)
    if PLUGIN_ID in disabled_names:
        return False, "Petasos is on Hermes's disabled list, so Hermes will not load it."
    if PLUGIN_ID not in enabled_names:
        return False, "Petasos is not in Hermes's enabled plugins."
    return True, "Hermes is loading Petasos."


def _names(value: object) -> set[str]:
    if not isinstance(value, (list, tuple)):
        return set()
    return {item for item in value if isinstance(item, str)}


def _session(home: Path) -> tuple[str, bytes | None, str]:
    raw = read_profile_env(home, SESSION_ENV)
    if not raw:
        return (
            "unset",
            None,
            "No session secret is set, so events are not signed and cannot be checked.",
        )
    try:
        secret = base64.b64decode(raw, validate=True)
    except Exception:
        return (
            "set",
            None,
            "The session secret is set but is not valid base64, so events cannot be checked.",
        )
    if not secret:
        return (
            "unset",
            None,
            "No session secret is set, so events are not signed and cannot be checked.",
        )
    from petasos.enforce.events import verification_key

    key = verification_key(secret)
    return "set", key, ""
