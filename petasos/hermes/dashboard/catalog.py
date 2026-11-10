"""Settings the front end can render without knowing the config tree.

Rows come from ``describe`` and ``resolve``. This module does not read a
home and does not write.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from petasos.config.layers import LEVELS, ROLES, SETTING_HELP, SETTING_LABEL, Resolved, resolve
from petasos.config.schema import ConfigError, FieldInfo, SectionInfo, describe, to_mapping
from petasos.config.sections import PetasosConfig
from petasos.hermes.dashboard.errors import envelope, problems_of
from petasos.hermes.dashboard.values import copy_tree, dig, json_value

if TYPE_CHECKING:
    from petasos.scanners.registry import ScannerSpec

_FOUR = ("enabled", "role", "level", "overrides")
_SETTINGS_KEY = "plugins.entries.petasos.settings"


def role_choices() -> list[dict[str, str]]:
    """Roles in the order a settings screen offers them."""
    return [
        {
            "name": role.name,
            "label": role.label,
            "description": role.description,
            "suggests": role.suggests,
        }
        for role in ROLES.values()
    ]


def level_choices() -> list[dict[str, str]]:
    """Levels in the order a settings screen offers them."""
    return [
        {"name": level.name, "label": level.label, "description": level.description}
        for level in LEVELS.values()
    ]


def sections() -> list[dict[str, Any]]:
    """Section headings in declaration order, with the help text on each field."""
    rows: list[dict[str, Any]] = []
    for item in describe(PetasosConfig):
        if isinstance(item, SectionInfo):
            rows.append(
                {
                    "path": item.path,
                    "label": item.label,
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
                "choice_labels": None if item.choice_labels is None else dict(item.choice_labels),
                "entry_labels": None if item.entry_labels is None else list(item.entry_labels),
                "bounds": {"ge": item.ge, "gt": item.gt, "le": item.le, "lt": item.lt},
                "label": item.label,
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


def locked_paths(managed: frozenset[str] | None) -> dict[str, Any]:
    """Which of Petasos's settings an administrator pinned, read-only.

    ``managed`` is Hermes's set of pinned dotted keys, or None when Hermes
    cannot say. ``stored`` lists pinned keys among the four; ``settings``
    lists pinned leaf paths inside ``overrides``. ``plugin`` is true when the
    administrator pinned Hermes's own plugin list.
    """
    if managed is None:
        return {"known": False, "stored": [], "settings": [], "plugin": False}
    prefix = _SETTINGS_KEY + "."
    stored: set[str] = set()
    leaves: set[str] = set()
    for key in managed:
        if key == _SETTINGS_KEY:
            stored.update(_FOUR)
            continue
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix) :]
        head, _, tail = rest.partition(".")
        if head not in _FOUR:
            continue
        if head == "overrides" and tail:
            leaves.add(tail)
        else:
            stored.add(head)
    return {
        "known": True,
        "stored": [key for key in _FOUR if key in stored],
        "settings": sorted(leaves),
        "plugin": "plugins.enabled" in managed or "plugins.disabled" in managed,
    }


def required_consequences(
    resolved: Resolved | None,
    *,
    registry: tuple[ScannerSpec, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """For each check set to Required that cannot run, what happens to tool calls.

    Keyed by the setting's path, such as ``scanners.prompt_guard.enabled``.
    Only checks set to Required are built, so the common case builds none.
    The sentence is the doctor's, computed from the fail mode and the
    dangerous-action setting in ``resolved``.
    """
    if resolved is None:
        return {}
    from petasos.hermes.doctor_advice import scanner_report
    from petasos.scanners.registry import REGISTRY

    specs = REGISTRY if registry is None else registry
    required = tuple(
        spec
        for spec in specs
        if getattr(getattr(resolved.config.scanners, spec.section, None), "enabled", None) == "on"
    )
    if not required:
        return {}
    _checks, _suggestions, rows = scanner_report(resolved, registry=required)
    sections = {spec.id: spec.section for spec in required}
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        consequence = row.get("consequence")
        section = sections.get(str(row.get("id")))
        if isinstance(consequence, dict) and section is not None:
            found[f"scanners.{section}.enabled"] = dict(consequence)
    return found


def read_settings(
    stored: Mapping[str, Any],
    *,
    secrets: Mapping[str, str],
    managed: frozenset[str] | None = None,
    registry: tuple[ScannerSpec, ...] | None = None,
) -> dict[str, Any]:
    """The settings screen for one stored document.

    ``secrets`` maps ``session_secret`` and ``hash_key`` to ``set`` or
    ``unset``. The values themselves are not accepted. ``managed`` is the set
    of keys Hermes's managed config pins, or None when it cannot be read.
    """
    document = stored_document(stored)
    resolved, problems = _try_resolve(document)
    rows = setting_rows(resolved)
    _add_reset_targets(rows, document)
    return envelope(
        stored=document,
        labels={key: SETTING_LABEL[key] for key in _FOUR},
        help={key: SETTING_HELP[key] for key in _FOUR},
        locked=locked_paths(managed),
        roles=role_choices(),
        levels=level_choices(),
        sections=sections(),
        settings=rows,
        secrets={
            "session_secret": secrets.get("session_secret", "unset"),
            "hash_key": secrets.get("hash_key", "unset"),
        },
        valid=not problems,
        problems=problems,
        consequences=required_consequences(resolved, registry=registry),
    )


def _add_reset_targets(rows: list[dict[str, Any]], document: Mapping[str, Any]) -> None:
    """For each value you set, what removing your change would leave, as ``reset_to``.

    ``reset_to`` is ``{value, origin}``: the value the job, the strictness or
    the default gives once the override is gone. Rows you did not set get none.
    """
    overrides = document.get("overrides")
    if not isinstance(overrides, Mapping):
        return
    from petasos.hermes.dashboard.values import has_path, without_path

    for row in rows:
        if row.get("origin") != "override":
            continue
        path = row["path"]
        try:
            if not has_path(overrides, path):
                continue
            remainder = without_path(overrides, path)
        except ValueError:
            continue
        candidate = dict(document)
        candidate["overrides"] = remainder
        resolved, problems = _try_resolve(candidate)
        if resolved is None or problems:
            continue
        tree = to_mapping(resolved.config)
        row["reset_to"] = {
            "value": json_value(dig(tree, path)),
            "origin": resolved.origin.get(path),
        }


def preview_settings(
    stored: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    registry: tuple[ScannerSpec, ...] | None = None,
) -> dict[str, Any]:
    """What ``candidate`` would resolve to, and what would differ from now.

    Nothing is written. An invalid candidate returns ``valid`` false and an
    empty change list. ``consequences`` says, for each check the candidate
    makes Required that cannot run, what would happen to tool calls on save.
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
        consequences=required_consequences(after, registry=registry),
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
