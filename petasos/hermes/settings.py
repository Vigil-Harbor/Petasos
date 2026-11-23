"""Read and write the Hermes plugin settings for the active profile.

The four settings are read on every call. Defaults live in
``petasos.config.layers``. Secrets are read with Hermes's env-file reader,
not from ``config.yaml``. Nothing here mutates a container Hermes returned.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

from petasos.config.layers import resolve
from petasos.config.schema import ConfigError
from petasos.config.secrets import Secrets
from petasos.enforce.types import SettingsSnapshot
from petasos.hermes.host import (
    load_mapping,
    managed_document,
    managed_overlay,
    read_env,
    save_env,
    save_plugin_settings,
)

PLUGIN_ID = "petasos"
# The record ``petasos hermes pin`` leaves in the managed file beside its values.
PIN_RECORD = "petasos_managed_pin"
PINNED_REFUSAL = (
    "These settings are pinned at machine level, so this was not saved. "
    "An administrator can remove the pin, starting with: petasos hermes unpin"
)
SESSION_ENV = "PETASOS_SESSION_SECRET"
HASH_ENV = "PETASOS_HASH_KEY"
_SECRET_KEYS = frozenset({"session_secret", "hash_key"})
# How many times the four settings are read while waiting for two passes to agree.
_READ_PASSES = 4
_KEYS = ("enabled", "role", "level", "overrides")
_DEFAULTS: Mapping[str, object] = {"enabled": True, "role": "general", "level": "balanced"}
# What the context returns for a key that is not stored. A stored null is ``None``.
_ABSENT = object()
_MISSING_BLOCK = "build failed: the Petasos settings block is missing"


class ConfigStore(Protocol):
    """The slice of a Hermes plugin context that reads settings."""

    def get_config(self, key: str, default: object = None) -> object:
        """The stored value, or ``default`` when the key was never set."""
        ...


def _plain(value: object) -> object:
    """A deep copy. Mappings and lists the caller still holds are not shared."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)):
        return [_plain(item) for item in value]
    return value


def _digest(raw: bytes | None) -> str:
    if raw is None:
        return ""
    return hashlib.sha256(raw).hexdigest()


def _token(
    enabled: object,
    role: object,
    level: object,
    overrides: object,
    secrets: Secrets,
) -> tuple[object, ...]:
    """The four settings, plus a digest of each secret.

    The enforcer applies secrets only when the token changes. A rotation has
    to be visible without putting the secret itself in the token.
    """
    blob = json.dumps(_plain(overrides), sort_keys=True, separators=(",", ":"), default=str)
    hash_key = None if secrets.hash_key is None else secrets.hash_key.encode()
    return (enabled, role, level, blob, _digest(secrets.session_secret), _digest(hash_key))


def _decode_session(raw: str | None) -> tuple[bytes | None, bool]:
    if raw is None:
        return None, False
    try:
        return base64.b64decode(raw, validate=True), False
    except Exception:
        return None, True


def _secrets_from(session_raw: str | None, hash_raw: str | None) -> tuple[Secrets, bool]:
    session, invalid = _decode_session(session_raw)
    return Secrets(session_secret=session, hash_key=hash_raw), invalid


def read_profile_env(home: Path, name: str) -> str | None:
    """One value from ``<home>/.env``. ``None`` when the file or the name is absent."""
    path = home / ".env"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    prefix = name + "="
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        if not stripped.startswith(prefix):
            continue
        raw = stripped[len(prefix) :]
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        return raw or None
    return None


def _plugin_settings(document: object) -> dict[str, object] | None:
    """A copy of ``plugins.entries.petasos.settings``, or ``None`` when absent."""
    if not isinstance(document, dict):
        return None
    plugins = document.get("plugins")
    if not isinstance(plugins, dict):
        return None
    entries = plugins.get("entries")
    if not isinstance(entries, dict):
        return None
    owned = entries.get(PLUGIN_ID)
    if not isinstance(owned, dict):
        return None
    settings = owned.get("settings")
    if not isinstance(settings, dict):
        return None
    copied = _plain(settings)
    if not isinstance(copied, dict):
        return None
    return copied


def pinned_settings() -> dict[str, object] | None:
    """The settings from a pin that ``petasos hermes pin`` wrote, or None.

    Hermes lays the managed file over a profile and merges groups key by key.
    A profile can therefore add an entry to a pinned group, such as a lower
    severity for one rule, and can put a group where the pin has no value.
    So a pin is read whole: while one is in force the profile's own Petasos
    settings are not used at all. A managed file without the pin's record is
    left to Hermes's overlay, which fixes only the exact values it names.
    """
    document = managed_document()
    if document is None or not isinstance(document.get(PIN_RECORD), dict):
        return None
    settings = _plugin_settings(document)
    if settings is None or not isinstance(settings.get("overrides"), dict):
        return None
    return settings


def profile_binding(path: Path) -> tuple[str, dict[str, object] | None]:
    """How ``path`` holds Petasos settings.

    The kind is ``settings`` (the plugin block is present), ``legacy`` (a
    non-empty top-level ``petasos:`` section and no plugin block), ``empty``,
    or ``broken``. The legacy section's contents are not returned.
    """
    if not path.is_file():
        return "empty", None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "broken", None
    document = load_mapping(text)
    if document is None:
        return "empty", None
    if not isinstance(document, dict):
        return "broken", None
    pinned = pinned_settings()
    if pinned is not None:
        return "settings", pinned
    document = managed_overlay(document)
    settings = _plugin_settings(document)
    if settings is not None:
        return "settings", settings
    legacy = document.get("petasos")
    if isinstance(legacy, dict) and len(legacy) > 0:
        return "legacy", None
    return "empty", None


def _four_from_mapping(values: Mapping[str, object]) -> tuple[object, object, object, object]:
    enabled = values.get("enabled", True)
    role = values.get("role", "general")
    level = values.get("level", "balanced")
    overrides = values.get("overrides", {})
    if isinstance(overrides, Mapping):
        overrides = _plain(overrides)
    return enabled, role, level, overrides


def _read_pass(ctx: ConfigStore) -> tuple[object, object, object, object]:
    enabled, role, level, overrides = (ctx.get_config(key, _ABSENT) for key in _KEYS)
    if isinstance(overrides, Mapping):
        overrides = _plain(overrides)
    return enabled, role, level, overrides


def _with_defaults(
    four: tuple[object, object, object, object],
) -> tuple[object, object, object, object]:
    enabled, role, level, overrides = (
        _DEFAULTS.get(key, {}) if value is _ABSENT else value
        for key, value in zip(_KEYS, four, strict=True)
    )
    return enabled, role, level, overrides


def _spelled(four: tuple[object, object, object, object]) -> str:
    """One pass as text, so ``True`` and ``1`` are different settings."""
    marked = [{"absent": True} if value is _ABSENT else {"value": value} for value in four]
    return json.dumps(_plain(marked), sort_keys=True, separators=(",", ":"), default=str)


def _four_from_store(ctx: ConfigStore) -> tuple[object, object, object, object]:
    """The four settings as one stored document held them.

    Hermes reads one key per call and has no read of the whole mapping, so a
    write can land between two of the four reads and mix two documents. A
    pass counts only when the next pass reads the same values. Settings that
    never hold still raise, which the caller reports as an unusable read.
    """
    seen = _read_pass(ctx)
    for _ in range(_READ_PASSES - 1):
        again = _read_pass(ctx)
        if _spelled(again) == _spelled(seen):
            return again
        seen = again
    raise RuntimeError("the settings kept changing while they were read")


def _snapshot(
    enabled: object,
    role: object,
    level: object,
    overrides: object,
    secrets: Secrets,
    invalid: bool,
) -> SettingsSnapshot:
    armed = enabled if type(enabled) is bool else True
    token = _token(enabled, role, level, overrides, secrets)
    try:
        resolved = resolve(
            {"enabled": enabled, "role": role, "level": level, "overrides": overrides}
        )
    except ConfigError as exc:
        return SettingsSnapshot(
            armed=armed,
            config=None,
            secrets=secrets,
            token=token,
            error=f"build failed: {exc}",
            secret_invalid=invalid,
        )
    except Exception as exc:
        return SettingsSnapshot(
            armed=armed,
            config=None,
            secrets=Secrets(),
            token=token,
            error=f"build failed: {exc}",
            secret_invalid=invalid,
        )
    return SettingsSnapshot(
        armed=resolved.settings.enabled,
        config=resolved.config,
        origin=resolved.origin,
        secrets=secrets,
        token=token,
        secret_invalid=invalid,
    )


class HermesSettings:
    """The enforcer's settings source for one Hermes process.

    ``bind_profile`` points later calls at a profile directory the host named,
    so a profile switch is visible before the process home changes.

    Once a stored block has loaded, a read that finds none of the four keys
    is an error snapshot, so the enforcer keeps the last good settings. Only
    a source that has never loaded a block falls back to the defaults.
    """

    def __init__(self, ctx: ConfigStore) -> None:
        self._ctx = ctx
        self._profile: Path | None = None
        self._loaded_block = False

    def bind_profile(self, home: Path | None) -> None:
        """Read later snapshots from ``home``."""
        self._profile = home

    @property
    def profile(self) -> Path | None:
        """The profile directory later reads use, or ``None`` for the context."""
        return self._profile

    def __call__(self) -> SettingsSnapshot:
        """The snapshot as of this call. An unusable observation carries ``error``."""
        try:
            return self._read()
        except Exception as exc:
            return SettingsSnapshot(
                armed=True,
                config=None,
                secrets=Secrets(),
                token=("error", type(exc).__name__),
                error=f"build failed: {exc}",
            )

    def _secret_pair(self, home: Path | None) -> tuple[Secrets, bool]:
        if home is not None:
            session_raw = read_profile_env(home, SESSION_ENV)
            hash_raw = read_profile_env(home, HASH_ENV)
        else:
            session_raw = read_env(SESSION_ENV)
            hash_raw = read_env(HASH_ENV)
        return _secrets_from(session_raw, hash_raw)

    def _read(self) -> SettingsSnapshot:
        home = self._profile
        pinned = pinned_settings()
        if pinned is not None:
            # Before the profile is read at all: a missing or damaged profile
            # file does not unpin anything.
            four, stored = _four_from_mapping(pinned), True
        elif home is not None:
            kind, settings = profile_binding(home / "config.yaml")
            if kind == "broken" or settings is None:
                return self._unusable(
                    home, ("unreadable", str(home)), "build failed: malformed settings"
                )
            four, stored = _four_from_mapping(settings), any(key in settings for key in _KEYS)
        else:
            read = _four_from_store(self._ctx)
            four, stored = _with_defaults(read), any(value is not _ABSENT for value in read)
        # One rule for the pin, a named profile and the plugin context: once a
        # stored block has loaded by any of them, finding none is not a reset.
        if not stored and self._loaded_block:
            return self._unusable(home, ("missing",), _MISSING_BLOCK)
        snap = _snapshot(*four, *self._secret_pair(home))
        if stored and snap.error is None:
            self._loaded_block = True
        return snap

    def _unusable(self, home: Path | None, token: tuple[str, ...], error: str) -> SettingsSnapshot:
        secrets, invalid = self._secret_pair(home)
        return SettingsSnapshot(
            armed=True,
            config=None,
            secrets=secrets,
            token=token,
            error=error,
            secret_invalid=invalid,
        )


def write_settings(
    values: Mapping[str, object],
    *,
    plugin_dir: Path,
    plugin_id: str = PLUGIN_ID,
) -> None:
    """Write settings through Hermes.

    ``plugin_dir`` is the installed plugin directory. Hermes reads
    ``plugin.yaml`` there. Non-secret keys use the form writer, which rejects
    a value outside the manifest's choices and refuses to put a secret in
    ``config.yaml``. The two secrets are written to the profile env file
    under their ``env:`` names.
    """
    if not isinstance(values, Mapping):
        raise TypeError("settings must be a mapping")
    plain: dict[str, object] = {}
    secrets: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str):
            raise TypeError("a setting name must be text")
        if key in _SECRET_KEYS:
            if not isinstance(value, str):
                raise TypeError(f"{key} must be text")
            secrets[key] = value
            continue
        copied = _plain(value)
        plain[key] = copied
    if plain:
        save_plugin_settings(plugin_id, plugin_dir, plain)
    for key, value in secrets.items():
        env_name = SESSION_ENV if key == "session_secret" else HASH_ENV
        save_env(env_name, value)
