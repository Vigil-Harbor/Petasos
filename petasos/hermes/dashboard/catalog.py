"""Settings the front end can render without knowing the config tree.

Rows come from ``describe`` and ``resolve``. This module does not read a
home and does not write.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from petasos.config.layers import LEVELS, ROLES, SETTING_HELP, Resolved, resolve
from petasos.config.schema import ConfigError, FieldInfo, SectionInfo, describe, to_mapping
from petasos.config.sections import PetasosConfig
from petasos.hermes.dashboard.errors import envelope, problems_of
from petasos.hermes.dashboard.values import copy_tree, dig, json_value

_FOUR = ("enabled", "role", "level", "overrides")


def role_choices() -> list[dict[str, str]]:
    """Roles in the order a settings screen offers them."""
    return [
        {"name": role.name, "description": role.description, "suggests": role.suggests}
        for role in ROLES.values()
    ]


def level_choices() -> list[dict[str, str]]:
    """Levels in the order a settings screen offers them."""
    return [{"name": level.name, "description": level.description} for level in LEVELS.values()]


def sections() -> list[dict[str, Any]]:
    """Section headings in declaration order, with the help text on each field."""
    rows: list[dict[str, Any]] = []
    for item in describe(PetasosConfig):
        if isinstance(item, SectionInfo):
            rows.append(
                {
                    "path": item.path,
                    "help": item.help,
                    "audience": item.audience,
                    "restart": item.restart,
                }
            )
    return rows


def setting_rows(resolved: Resolved | None) -> list[dict[str, Any]]:
    """One row per leaf. ``resolved`` None leaves value and origin empty."""
    tree = to_mapping(resolved.config) if resolved is not None else None
    origin = resolved.origin if resolved is not None else {}
    rows: list[dict[str, Any]] = []
    for item in describe(PetasosConfig):
        if not isinstance(item, FieldInfo):
            continue
        value = dig(tree, item.path) if tree is not None else None
        rows.append(
            {
                "path": item.path,
                "section": item.path.rpartition(".")[0],
                "value": json_value(value) if tree is not None else None,
                "default": json_value(item.default),
                "type": item.type_name,
                "choices": None if item.choices is None else [json_value(c) for c in item.choices],
                "bounds": {"ge": item.ge, "gt": item.gt, "le": item.le, "lt": item.lt},
                "help": item.help,
                "audience": item.audience,
                "restart": item.restart,
                "origin": origin.get(item.path) if tree is not None else None,
                "nullable": item.nullable,
            }
        )
    return rows


def stored_document(values: Mapping[str, Any]) -> dict[str, Any]:
    """The four settings, with defaults for keys the document omits.

    A non-mapping ``overrides`` is kept as it was stored so a later resolve
    can report it. Secret keys are dropped and never copied out.
    """
    enabled = values.get("enabled", True)
    role = values.get("role", "general")
    level = values.get("level", "balanced")
    overrides = values.get("overrides", {})
    if isinstance(overrides, Mapping):
        overrides = copy_tree(overrides)
    return {
        "enabled": enabled if type(enabled) is bool else enabled,
        "role": role,
        "level": level,
        "overrides": overrides,
    }


def combine(stored: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    """``stored`` with the candidate's present keys replacing those four.

    ``overrides``, when present, is a patch merged the way a save would land,
    not a replacement. Omitted keys stay. Use :func:`petasos.hermes.dashboard.changes.clear`
    to remove one.
    """
    base = stored_document(stored)
    for key in _FOUR:
        if key not in candidate:
            continue
        if key == "overrides":
            patch = candidate[key]
            current = base["overrides"] if isinstance(base["overrides"], Mapping) else {}
            if isinstance(patch, Mapping):
                from petasos.hermes.dashboard.values import hermes_merge

                base["overrides"] = hermes_merge(current, patch)
            else:
                base["overrides"] = patch
            continue
        base[key] = candidate[key]
    return base


def _try_resolve(document: Mapping[str, Any]) -> tuple[Resolved | None, list[dict[str, str]]]:
    try:
        return resolve(document), []
    except ConfigError as exc:
        return None, problems_of(exc.errors)


def read_settings(
    stored: Mapping[str, Any],
    *,
    secrets: Mapping[str, str],
) -> dict[str, Any]:
    """The settings screen for one stored document.

    ``secrets`` maps ``session_secret`` and ``hash_key`` to ``set`` or
    ``unset``. The values themselves are not accepted.
    """
    document = stored_document(stored)
    resolved, problems = _try_resolve(document)
    return envelope(
        stored=document,
        help={key: SETTING_HELP[key] for key in _FOUR},
        roles=role_choices(),
        levels=level_choices(),
        sections=sections(),
        settings=setting_rows(resolved),
        secrets={
            "session_secret": secrets.get("session_secret", "unset"),
            "hash_key": secrets.get("hash_key", "unset"),
        },
        valid=not problems,
        problems=problems,
    )


def preview_settings(
    stored: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """What ``candidate`` would resolve to, and what would differ from now.

    Nothing is written. An invalid candidate returns ``valid`` false and an
    empty change list.
    """
    current = stored_document(stored)
    proposed = combine(stored, candidate)
    before, before_problems = _try_resolve(current)
    after, after_problems = _try_resolve(proposed)
    changes: list[dict[str, Any]] = []
    if after is not None and not before_problems:
        changes = _changes(before, after)
    return envelope(
        stored=proposed,
        sections=sections(),
        settings=setting_rows(after),
        changes=changes,
        valid=not after_problems,
        problems=after_problems,
    )


def _changes(before: Resolved | None, after: Resolved) -> list[dict[str, Any]]:
    before_rows = {row["path"]: row for row in setting_rows(before)}
    found: list[dict[str, Any]] = []
    for row in setting_rows(after):
        old = before_rows.get(row["path"], {})
        if old.get("value") == row["value"] and old.get("origin") == row["origin"]:
            continue
        found.append(
            {
                "path": row["path"],
                "before": old.get("value"),
                "after": row["value"],
                "origin_before": old.get("origin"),
                "origin_after": row["origin"],
                "restart": row["restart"],
            }
        )
    return found


def restart_paths(before: Resolved | None, after: Resolved) -> list[str]:
    """Leaf paths whose value changed and whose spec needs a process restart."""
    return [row["path"] for row in _changes(before, after) if row["restart"] is True]
