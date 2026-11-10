"""Plain-data helpers, including the merge Hermes uses when it saves settings.

Hermes ``v0.23.1`` ``_deep_merge`` (``hermes_cli/config.py``) keeps a key the
new document omits, and it ignores ``None`` when the stored value is a
mapping. A list replaces a mapping, because a list is not a mapping. Clearing
an override writes a list and then the mapping that should remain, so the
second write replaces the list instead of merging into the old mapping.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def copy_tree(value: object) -> Any:
    """A deep copy of JSON-shaped data. The input is not shared."""
    if isinstance(value, Mapping):
        return {str(key): copy_tree(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)):
        return [copy_tree(item) for item in value]
    return value


def json_value(value: object) -> Any:
    """A JSON value. Mappings and tuples become objects and arrays."""
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [json_value(item) for item in value]
    if isinstance(value, list):
        return [json_value(item) for item in value]
    return value


def dig(tree: Mapping[str, Any] | None, path: str) -> Any:
    """The value at a dotted path, or None when a step is missing."""
    current: object = tree
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def hermes_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Merge ``override`` onto ``base`` the way Hermes saves a plugin setting.

    A mapping merged onto a mapping keeps keys the override does not mention.
    ``None`` does not replace a mapping. Every other value, including a list,
    replaces the stored value. The result shares nothing with either input.
    """
    result = {str(key): copy_tree(item) for key, item in base.items()}
    for key, value in override.items():
        name = str(key)
        current = result.get(name)
        if isinstance(current, dict) and isinstance(value, Mapping):
            result[name] = hermes_merge(current, value)
        elif isinstance(current, dict) and value is None:
            continue
        else:
            result[name] = copy_tree(value)
    return result


def has_path(document: Mapping[str, Any], path: str) -> bool:
    """True when every segment of ``path`` is present."""
    current: object = document
    for part in _parts(path):
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current[part]
    return True


def without_path(document: Mapping[str, Any], path: str) -> dict[str, Any]:
    """``document`` with ``path`` removed. Empty mappings left behind are removed."""
    result = copy_tree(document)
    if not isinstance(result, dict):
        return {}
    _drop(result, _parts(path))
    return result


def _parts(path: str) -> tuple[str, ...]:
    parts = tuple(part for part in path.split(".") if part)
    if not parts or any(part == "" for part in path.split(".")):
        raise ValueError("path must name a setting")
    return parts


def _drop(node: dict[str, Any], parts: tuple[str, ...]) -> None:
    key = parts[0]
    if key not in node:
        return
    if len(parts) == 1:
        node.pop(key, None)
        return
    child = node.get(key)
    if not isinstance(child, dict):
        node.pop(key, None)
        return
    _drop(child, parts[1:])
    if child == {}:
        node.pop(key, None)
