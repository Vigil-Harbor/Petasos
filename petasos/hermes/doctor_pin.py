"""What a managed pin fixes, and whether this account can change it."""

from __future__ import annotations

from typing import Any

from petasos.hermes.doctor_model import Check
from petasos.hermes.doctor_support import at_path, plugin_lists
from petasos.hermes.managed import Managed, effective_config, read_managed, writable
from petasos.hermes.pinning import (
    LIMITS,
    LISTS,
    MAP_FIELDS,
    SETTINGS,
    TIMEOUT,
    differences,
    has_references,
    leaf_paths,
    mapping_limits,
    required_keys,
    unset_limits,
    unset_words,
)


def pin_report(profile: object) -> tuple[tuple[Check, ...], dict[str, Any], object]:
    """Checks, API facts, and the effective document. Unknown never means pinned."""
    try:
        scope = read_managed()
    except ValueError as exc:
        return (
            (Check(id="pin", status="info", summary=str(exc)),),
            {"state": "unknown", "known": False},
            profile,
        )
    machine_keys = [".".join(path) for path in leaf_paths(scope.machine_document)]
    machine_has_pin = any(
        key in (*LISTS, TIMEOUT, SETTINGS) or key.startswith(SETTINGS + ".")
        for key in machine_keys
    )
    relevant = frozenset(
        key
        for key in scope.keys
        if key in (*LISTS, TIMEOUT, SETTINGS) or key.startswith(SETTINGS + ".")
    )
    if machine_has_pin and scope.directory != scope.machine:
        check = Check(
            id="pin",
            status="fail",
            summary="Pin not in force. Hermes was pointed at a different managed directory.",
            meaning=(
                "The machine-level file has Petasos settings, but Hermes is not using it. "
                "Changing the managed-directory environment variable bypasses that pin. " + LIMITS
            ),
            next_step="Remove the managed-directory override and run petasos doctor again.",
        )
        try:
            redirected: object = effective_config()
        except ValueError:
            redirected = profile
        return (check,), {"state": "not_in_force", "known": True}, redirected
    if not relevant:
        return (), {"state": "unpinned", "known": True}, profile
    try:
        effective = effective_config()
    except (ValueError, RuntimeError, OSError):
        return (
            (
                Check(
                    id="pin",
                    status="warn",
                    summary="The pin's effective settings could not be checked.",
                ),
            ),
            {"state": "unknown", "known": False},
            profile,
        )
    # See docs/architecture/rationale.md, "Managed pin overlays".
    whole = _read_whole(scope)
    if whole:
        missing = sorted(key for key in (*LISTS, TIMEOUT) if key not in scope.keys)
        open_groups: list[str] = []
        unset: tuple[str, ...] = ()
    else:
        missing = sorted(required_keys(effective) - scope.keys)
        open_groups = [row.label for row in MAP_FIELDS]
        unset = unset_limits(scope.document)
    references = any(
        has_references(at_path(scope.document, key)) for key in (SETTINGS, *LISTS, TIMEOUT)
    )
    checks: list[Check] = []
    can_write = scope.directory is not None and (
        writable(scope.directory) or _file_writable(scope)
    )
    if can_write:
        state = "writable"
        summary = (
            "Pinned where this account can write. "
            "This does not protect settings from this account."
        )
    elif missing or open_groups or unset or references:
        state = "partly_pinned"
        summary = "Partly pinned. Some settings are not fixed at machine level."
    else:
        state = "pinned"
        summary = (
            "Pinned. Settings are fixed at machine level. Only an administrator can change them."
        )
    details = []
    if missing:
        details.append("Not pinned: " + ", ".join(_label(key) for key in missing) + ".")
    if open_groups:
        details.append(mapping_limits())
    if unset:
        details.append(unset_words(unset))
    if references:
        details.append(
            "Some pinned values still depend on environment variables. "
            "Replace them with plain values before pinning."
        )
    details.append(LIMITS)
    checks.append(
        Check(
            id="pin",
            status="warn" if state != "pinned" else "ok",
            summary=summary,
            meaning=" ".join(details),
        )
    )
    enabled, disabled = plugin_lists(effective)
    if (
        "petasos" not in enabled
        or "petasos" in disabled
        or at_path(effective, SETTINGS + ".enabled") is False
    ):
        checks.append(
            Check(
                id="pin_disabled",
                status="fail",
                summary="The pin leaves Petasos turned off. It is not protecting this agent.",
                meaning=(
                    "The managed file must keep Petasos on in both the plugin list "
                    "and its protection switch."
                ),
                next_step=(
                    "Have the administrator correct the managed file, then run petasos doctor."
                ),
            )
        )
    changed = differences(profile, scope.document)
    if changed:
        checks.append(
            Check(
                id="pin_profile",
                status="warn",
                summary="The profile differs from the pin. Something tried to change a guardrail.",
                meaning=(
                    "Pinned values are in force. These profile changes would take effect "
                    "when the pin is removed"
                    + (".\n" if whole else "; new entries in groups may already take effect.\n")
                    + "\n".join(changed)
                ),
                next_step="Review the profile changes before removing the pin.",
            )
        )
    return (
        tuple(checks),
        {
            "state": state,
            "known": True,
            "directory": str(scope.directory),
            "missing": [_label(key) for key in missing],
            "open_groups": open_groups,
            "unset_values": list(unset),
            "environment_references": references,
            "profile_differences": list(changed),
            "summary": summary,
            "meaning": " ".join(details),
        },
        effective,
    )


def _read_whole(scope: Managed) -> bool:
    """True when Petasos takes its settings from this pin and not from the profile."""
    from petasos.hermes.settings import PIN_RECORD

    settings = at_path(scope.document, SETTINGS)
    return (
        isinstance(scope.document.get(PIN_RECORD), dict)
        and isinstance(settings, dict)
        and isinstance(settings.get("overrides"), dict)
    )


def _file_writable(scope: Managed) -> bool:
    import os

    return scope.directory is not None and os.access(scope.directory / "config.yaml", os.W_OK)


def _label(key: str) -> str:
    from petasos.config.schema import leaves
    from petasos.config.sections import PetasosConfig

    labels = {
        LISTS[0]: "Plugins kept on",
        LISTS[1]: "Plugins kept off",
        TIMEOUT: "Time limit for plugin checks",
        SETTINGS + ".enabled": "Protection",
        SETTINGS + ".role": "Job",
        SETTINGS + ".level": "Strictness",
    }
    labels.update(
        {SETTINGS + ".overrides." + row.path: row.label for row in leaves(PetasosConfig)}
    )
    if key in labels:
        return labels[key]
    for row in MAP_FIELDS:
        if key.startswith(SETTINGS + ".overrides." + row.path + "."):
            return row.label
    return "A Petasos setting"
