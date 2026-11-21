"""Change one Petasos setting through Hermes's writer.

``petasos config set`` and ``hermes petasos config set`` both call
:func:`set_one`. A value that would leave Semgrep turned on is refused
before anything is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from petasos.config.layers import LEVEL_NAMES, ROLE_NAMES, Resolved, resolve
from petasos.config.schema import ConfigError, FieldInfo, leaves
from petasos.config.sections import PetasosConfig
from petasos.hermes import semgrep_host
from petasos.hermes.dashboard.catalog import combine, stored_document
from petasos.hermes.dashboard.changes import saved_message
from petasos.hermes.dashboard.values import copy_tree
from petasos.hermes.settings import (
    PINNED_REFUSAL,
    PLUGIN_ID,
    pinned_settings,
    profile_binding,
    write_settings,
)

if TYPE_CHECKING:
    from pathlib import Path

_TOP = frozenset({"enabled", "role", "level"})


def set_one(home: Path, path: str, raw: str) -> tuple[str, int]:
    """Set ``path`` to ``raw`` in ``home`` and return the text and exit status."""
    plugin = home / "plugins" / PLUGIN_ID
    if not (plugin / "plugin.yaml").is_file():
        return (
            "The Petasos plugin is not installed for this profile, so there is no "
            "settings file to change.\n"
            f"Next: petasos hermes install --home {_quote(home)}\n",
            2,
        )
    if pinned_settings() is not None:
        return PINNED_REFUSAL + "\n", 2
    kind, settings = profile_binding(home / "config.yaml")
    if kind == "broken":
        return ("The settings file could not be read, so nothing was changed.\n", 2)
    try:
        value = _coerce(path, raw)
    except ValueError as exc:
        return str(exc) + "\n", 2
    document = stored_document(settings if isinstance(settings, Mapping) else {})
    proposed = _apply(document, path, value)
    try:
        after = resolve(proposed)
    except ConfigError as exc:
        return exc.errors[0][1] + "\n", 2
    before = _resolved_or_none(document)
    blocked = semgrep_host.save_refusal(
        None if before is None else semgrep_host.semgrep_enabled(before.config),
        semgrep_host.semgrep_enabled(after.config),
    )
    if blocked is not None:
        return blocked + "\n", 2
    payload = {
        "enabled": proposed["enabled"],
        "role": proposed["role"],
        "level": proposed["level"],
        "overrides": proposed["overrides"] if isinstance(proposed["overrides"], dict) else {},
    }
    try:
        write_settings(payload, plugin_dir=plugin)
    except Exception as exc:
        return (
            "Hermes did not store the settings. "
            f"{exc} "
            "This command does not edit the config file itself.\n"
        ), 2
    return saved_message(before, after) + "\n", 0


def _resolved_or_none(document: Mapping[str, Any]) -> Resolved | None:
    try:
        return resolve(document)
    except ConfigError:
        return None


def _apply(document: dict[str, Any], path: str, value: object) -> dict[str, Any]:
    if path in _TOP:
        return combine(document, {path: value})
    return combine(document, {"overrides": _nest(path, value)})


def _coerce(path: str, raw: str) -> object:
    text = raw.strip()
    if path == "enabled":
        return _bool(text, path)
    if path == "role":
        return _choice(text, ROLE_NAMES, path)
    if path == "level":
        return _choice(text, LEVEL_NAMES, path)
    field = _field(path)
    if field is None:
        raise ValueError(f"There is no setting named {path}.")
    if field.type_name == "bool":
        return _bool(text, path)
    if field.type_name == "int":
        return _int(text, path)
    if field.type_name == "float":
        return _float(text, path)
    if field.type_name == "choice":
        names = tuple(str(choice) for choice in (field.choices or ()))
        return _choice(text, names, path)
    if field.type_name == "str":
        if text == "" and not field.nullable:
            raise ValueError(f"{field.label} needs a value.")
        return text
    raise ValueError(f"Set {field.label} in Settings. This command changes one simple value.")


def _field(path: str) -> FieldInfo | None:
    for row in leaves(PetasosConfig):
        if row.path == path:
            return row
    return None


def _bool(text: str, path: str) -> bool:
    if text.casefold() == "true":
        return True
    if text.casefold() == "false":
        return False
    raise ValueError(f"{path} is true or false.")


def _choice(text: str, names: tuple[str, ...], path: str) -> str:
    if text in names:
        return text
    listed = ", ".join(names)
    raise ValueError(f"{path} must be one of: {listed}.")


def _int(text: str, path: str) -> int:
    try:
        number = int(text)
    except ValueError as exc:
        raise ValueError(f"{path} needs a whole number.") from exc
    return number


def _float(text: str, path: str) -> float:
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"{path} needs a number.") from exc
    return number


def _nest(path: str, value: object) -> dict[str, Any]:
    parts = tuple(part for part in path.split(".") if part)
    if not parts or any(part == "" for part in path.split(".")):
        raise ValueError("Name the setting to change.")
    node: dict[str, Any] = {}
    cursor = node
    for part in parts[:-1]:
        child: dict[str, Any] = {}
        cursor[part] = child
        cursor = child
    cursor[parts[-1]] = copy_tree(value)
    return node


def _quote(path: Path) -> str:
    text = str(path)
    if any(character.isspace() for character in text):
        return "'" + text.replace("'", "'\\''") + "'"
    return text
