"""Build the managed document and compare it with a profile's own values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from petasos.config.layers import resolve
from petasos.config.schema import leaves, to_mapping
from petasos.config.sections import PetasosConfig
from petasos.hermes.doctor_support import at_path, plugin_lists, settings_mapping
from petasos.hermes.settings import PIN_RECORD

SETTINGS = "plugins.entries.petasos.settings"
LISTS = ("plugins.enabled", "plugins.disabled")
TIMEOUT = "plugins.hook_callback_timeout"
OWNER = PIN_RECORD
LIMITS = (
    "The plugin's files, the Python environment and the event record still belong to "
    "this account. A pin fixes settings and the plugin list; it is not a guarantee."
)
MAP_FIELDS = tuple(row for row in leaves(PetasosConfig) if row.type_name.startswith("mapping["))


def pin_values(document: Mapping[str, Any], *, timeout: float) -> dict[str, Any]:
    """Every resolved setting, both plugin lists, and the effective hook timeout."""
    resolved = resolve(settings_mapping(document, "petasos"))
    enabled, disabled = plugin_lists(document)
    if "petasos" not in enabled or "petasos" in disabled:
        raise ValueError("Petasos must be on in Hermes's plugin list before it can be pinned.")
    values = {
        "plugins": {
            "enabled": list(enabled),
            "disabled": list(disabled),
            "hook_callback_timeout": timeout,
            "entries": {
                "petasos": {
                    "settings": {
                        "enabled": resolved.settings.enabled,
                        "role": resolved.settings.role,
                        "level": resolved.settings.level,
                        "overrides": to_mapping(resolved.config),
                    }
                }
            },
        }
    }

    if has_references(values):
        raise ValueError(
            "A setting still contains an environment reference. "
            "Replace it with a plain value before pinning."
        )
    return values


def has_references(value: object) -> bool:
    """An unresolved reference could change under a later process environment."""
    if isinstance(value, str):
        return re.search(r"\$\{[^}]+\}", value) is not None
    if isinstance(value, Mapping):
        return any(has_references(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_references(item) for item in value)
    return False


def leaf_paths(document: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> list[list[str]]:
    """Segment paths preserve mapping keys that themselves contain dots."""
    paths: list[list[str]] = []
    for key, value in document.items():
        path = (*prefix, key)
        if isinstance(value, Mapping) and value:
            paths.extend(leaf_paths(value, path))
        else:
            paths.append(list(path))
    return paths


def merge_pin(existing: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
    """Keep unrelated managed keys and remember exactly which keys this pin writes."""
    from petasos.hermes.dashboard.values import hermes_merge

    result = hermes_merge(existing, values)
    paths = leaf_paths(values)
    previous = existing.get(OWNER)
    if previous is not None:
        paths = owned_paths(existing) + paths
    result[OWNER] = {
        "version": 1,
        "paths": [list(path) for path in dict.fromkeys(map(tuple, paths))],
    }
    return result


def owned_paths(document: Mapping[str, Any]) -> list[list[str]]:
    """Reject damaged ownership rather than deleting an uncertain set of keys."""
    marker = document.get(OWNER)
    if not isinstance(marker, Mapping) or marker.get("version") != 1:
        raise ValueError(
            "This managed file has no readable Petasos pin record. Nothing was removed."
        )
    paths = marker.get("paths")
    if not isinstance(paths, list) or not paths:
        raise ValueError("The Petasos pin record is damaged. Nothing was removed.")
    result: list[list[str]] = []
    for path in paths:
        if (
            not isinstance(path, list)
            or not path
            or not all(isinstance(p, str) and p for p in path)
        ):
            raise ValueError("The Petasos pin record is damaged. Nothing was removed.")
        dotted = ".".join(path)
        if dotted not in (*LISTS, TIMEOUT) and not dotted.startswith(SETTINGS + "."):
            raise ValueError("The Petasos pin record names an unrelated key. Nothing was removed.")
        result.append(path)
    return result


def remove_pin(document: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only recorded keys, pruning the empty groups they leave behind."""
    from petasos.hermes.dashboard.values import copy_tree

    result = copy_tree(document)
    for path in owned_paths(document):
        _remove(result, path)
    result.pop(OWNER, None)
    return dict(result)


def _remove(node: dict[str, Any], parts: list[str]) -> None:
    key = parts[0]
    if len(parts) == 1:
        # Entries added after an empty group was pinned belong to their writer.
        if isinstance(node.get(key), dict) and node[key]:
            return
        node.pop(key, None)
        return
    child = node.get(key)
    if not isinstance(child, dict):
        return
    _remove(child, parts[1:])
    if not child:
        node.pop(key)


def required_keys(document: object) -> frozenset[str]:
    """The fixed setting leaves, with current entries of open mappings included."""
    try:
        config = to_mapping(resolve(settings_mapping(document, "petasos")).config)
    except ValueError:
        config = to_mapping(PetasosConfig())
    settings = {"enabled": True, "role": "general", "level": "balanced", "overrides": config}
    return frozenset(
        (*LISTS, TIMEOUT, *(SETTINGS + "." + ".".join(path) for path in leaf_paths(settings)))
    )


def mapping_limits() -> str:
    """Hermes deep-merges maps, so new entries cannot be fixed by a leaf pin."""
    names = ", ".join(row.label for row in MAP_FIELDS)
    return (
        f"New entries can still be added to these settings: {names}. "
        "Hermes merges these groups, even when the pinned group is empty. "
        "Those settings are not fully fixed."
    )


def unset_limits(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Null does not replace a profile mapping in Hermes's deep merge."""
    from petasos.hermes.dashboard.values import has_path

    return tuple(
        row.label
        for row in leaves(PetasosConfig)
        if has_path(document, SETTINGS + ".overrides." + row.path)
        and at_path(document, SETTINGS + ".overrides." + row.path) is None
    )


def unset_words(names: tuple[str, ...]) -> str:
    """Why an unset managed value is not a complete pin."""
    return (
        "An unset value can still be replaced by a group in these settings: "
        + ", ".join(names)
        + ". Hermes keeps a profile group when the pin has no value. "
        "Those settings are not fully fixed."
    )


def differences(profile: object, pinned: Mapping[str, Any]) -> tuple[str, ...]:
    """Compare effective profile-only settings; omitted defaults do not count as changes."""
    from petasos.hermes.dashboard.values import has_path

    lines: list[str] = []
    for path, label in zip(LISTS, ("Plugins kept on", "Plugins kept off"), strict=True):
        actual = list(plugin_lists(profile)[0 if path == LISTS[0] else 1])
        expected = at_path(pinned, path)
        if expected is not None and actual != expected:
            lines.append(f"{label}: the profile has {actual!r}; the pin has {expected!r}.")
    try:
        raw = resolve(settings_mapping(profile, "petasos"))
        held = resolve(settings_mapping(pinned, "petasos"))
    except ValueError:
        lines.append("The profile or the pin has settings that cannot be used.")
        return tuple(lines)
    for key, label in (("enabled", "Protection"), ("role", "Job"), ("level", "Strictness")):
        expected = at_path(pinned, SETTINGS + "." + key)
        actual = getattr(raw.settings, key)
        if expected is not None and actual != expected:
            lines.append(f"{label}: the profile has {actual!r}; the pin has {expected!r}.")
    actual_config = to_mapping(raw.config)
    held_config = to_mapping(held.config)
    for row in leaves(PetasosConfig):
        if not has_path(pinned, SETTINGS + ".overrides." + row.path):
            continue
        actual_value = at_path(actual_config, row.path)
        expected = at_path(held_config, row.path)
        if actual_value != expected:
            lines.append(
                f"{row.label}: the profile has {actual_value!r}; the pin has {expected!r}."
            )
    expected_timeout = at_path(pinned, TIMEOUT)
    actual_timeout = at_path(profile, TIMEOUT)
    if expected_timeout is not None and normalize_timeout(actual_timeout) != expected_timeout:
        lines.append(
            f"Time limit for plugin checks: the profile has {normalize_timeout(actual_timeout)!r} "
            f"seconds; the pin has {expected_timeout!r} seconds."
        )
    return tuple(lines)


def normalize_timeout(raw: object) -> float:
    """Hermes v0.23.1 defaults to 30 seconds and caps the setting at 600 seconds."""
    try:
        value = float(raw) if isinstance(raw, (str, int, float)) else 30.0
    except ValueError:
        return 30.0
    return 30.0 if value < 0 else min(value, 600.0)
