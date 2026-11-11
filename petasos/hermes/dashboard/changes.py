"""Save and clear settings through the caller's writer.

The writer is Hermes's plugin-settings writer. This module does not open
``config.yaml``. An invalid document is refused before the writer is called.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from petasos.config.layers import resolve
from petasos.config.schema import ConfigError, leaves
from petasos.config.sections import PetasosConfig
from petasos.hermes import semgrep_host
from petasos.hermes.dashboard.catalog import (
    combine,
    preview_settings,
    read_settings,
    setting_changes,
    stored_document,
)
from petasos.hermes.dashboard.errors import ApiError, envelope
from petasos.hermes.dashboard.values import copy_tree, has_path, hermes_merge, without_path
from petasos.hermes.dashboard.words import saved_effect
from petasos.hermes.settings import PINNED_REFUSAL, pinned_settings

logger = logging.getLogger("petasos.hermes.dashboard")

Writer = Callable[[Mapping[str, object], Path], None]

_SECRET_KEYS = frozenset({"session_secret", "hash_key"})


def save_settings(
    stored: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    plugin_dir: Path,
    write: Writer,
    secrets: Mapping[str, str],
    managed: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Validate ``candidate``, then write it.

    ``overrides`` in the candidate is a patch. Keys it omits stay. Nothing is
    written when the merged document does not resolve. A restart-required
    change is reported and still saved: the running gateway keeps the previous
    value of those fields until it restarts.
    """
    _reject_secrets(candidate)
    proposed = combine(stored, candidate)
    before = _resolved_or_none(stored_document(stored))
    after = _require_resolved(proposed)
    _refuse_pinned()
    _refuse_semgrep(before, after)
    current = _overrides(stored_document(stored))
    desired = _overrides(proposed)
    _write_document(proposed, current, desired, plugin_dir, write)
    restart, also_live = _effect(before, after)
    body = read_settings(proposed, secrets=secrets, managed=managed)
    body["saved"] = True
    body["restart"] = restart
    body["restart_message"] = _when_message("Saved.", restart, also_live=also_live)
    return body


def saved_message(before: Any, after: Any) -> str:
    """``Saved.`` and when the change takes effect, for a save made outside the form."""
    restart, also_live = _effect(before, after)
    return _when_message("Saved.", restart, also_live=also_live)


def clear_overrides(
    stored: Mapping[str, Any],
    path: str | None,
    *,
    plugin_dir: Path,
    write: Writer,
    secrets: Mapping[str, str],
    managed: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Remove one override, or every override when ``path`` is None.

    Hermes's writer keeps a mapping key the new document omits. Removal
    writes a list first, which replaces the mapping, then writes the mapping
    that should remain. A reader between the two writes sees a list and the
    enforcer keeps the last settings that resolved.
    """
    document = stored_document(stored)
    current = _overrides(document)
    if path is None:
        desired: dict[str, Any] = {}
        removed = bool(current)
    else:
        try:
            if not has_path(current, path):
                return envelope(
                    cleared=False,
                    message="That setting has no change of yours to reset.",
                    **_view(document, secrets, managed),
                )
            desired = without_path(current, path)
        except ValueError as exc:
            raise ApiError("invalid_path", "Name the setting to reset.", path=path) from exc
        removed = True
    proposed = combine(document, {"overrides": desired})
    # combine treats overrides as a patch. desired is the full remainder, so
    # replace rather than patch.
    proposed["overrides"] = desired
    before = _resolved_or_none(document)
    after = _require_resolved(proposed)
    if not removed:
        return envelope(
            cleared=False,
            message="You have no changes of your own to reset.",
            **_view(document, secrets, managed),
        )
    _refuse_pinned()
    _refuse_semgrep(before, after)
    _write_overrides(current, desired, plugin_dir, write)
    restart, also_live = _effect(before, after)
    return envelope(
        cleared=True,
        message=(
            "Reset. The job and strictness decide this again."
            if path is not None
            else "Reset. The job and strictness decide every setting again."
        ),
        restart=restart,
        restart_message=_when_message("Reset.", restart, also_live=also_live),
        **_view(proposed, secrets, managed),
    )


def preview(stored: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    """The preview body. ``candidate`` is not saved."""
    _reject_secrets(candidate)
    return preview_settings(stored, candidate)


def _view(
    document: Mapping[str, Any],
    secrets: Mapping[str, str],
    managed: frozenset[str] | None,
) -> dict[str, Any]:
    # read_settings already wraps a version. The clear response uses one envelope.
    body = read_settings(document, secrets=secrets, managed=managed)
    body.pop("version", None)
    return {"settings": body}


def _effect(before: Any, after: Any) -> tuple[list[str], bool]:
    """Restart-bound paths that changed, and whether another change is live."""
    changed = setting_changes(before, after)
    restart = [row["path"] for row in changed if row["restart"] is True]
    return restart, any(row["restart"] is not True for row in changed)


def _when_message(lead: str, restart: list[str], *, also_live: bool) -> str:
    """When a saved change takes effect, naming restart settings by label.

    The dashboard cannot see whether an agent already running has restarted
    since the save, so the sentence says what each kind of agent does.
    """
    labels = {row.path: row.label for row in leaves(PetasosConfig)}
    names = [labels.get(path, path) for path in restart]
    return saved_effect(lead, names, also_live=also_live)


def _refuse_pinned() -> None:
    """A pin is read whole, so a save would be stored and then have no effect."""
    if pinned_settings() is not None:
        raise ApiError("pinned", PINNED_REFUSAL)


def _refuse_semgrep(before: Any, after: Any) -> None:
    """Refuse a document that would leave Semgrep turned on inside Hermes."""
    message = semgrep_host.save_refusal(
        None if before is None else semgrep_host.semgrep_enabled(before.config),
        semgrep_host.semgrep_enabled(after.config),
    )
    if message is not None:
        raise ApiError("semgrep_cannot_run", message, path=semgrep_host.SEMGREP_ENABLED)


def _reject_secrets(candidate: Mapping[str, Any]) -> None:
    found = sorted(key for key in candidate if key in _SECRET_KEYS)
    if found:
        raise ApiError(
            "secret",
            "The session secret and the hash key live in the profile's .env file, "
            "and cannot be set from this page.",
            path=found[0],
        )


def _overrides(document: Mapping[str, Any]) -> dict[str, Any]:
    raw = document.get("overrides", {})
    if isinstance(raw, Mapping):
        copied = copy_tree(raw)
        if isinstance(copied, dict):
            return copied
    return {}


def _resolved_or_none(document: Mapping[str, Any]) -> Any:
    try:
        return resolve(document)
    except ConfigError:
        return None


def _require_resolved(document: Mapping[str, Any]) -> Any:
    try:
        return resolve(document)
    except ConfigError as exc:
        first = exc.errors[0]
        raise ApiError(
            "invalid_settings",
            first[1],
            path=first[0] or None,
        ) from exc


def _write_document(
    proposed: Mapping[str, Any],
    current: Mapping[str, Any],
    desired: Mapping[str, Any],
    plugin_dir: Path,
    write: Writer,
) -> None:
    scalars = {
        "enabled": proposed["enabled"],
        "role": proposed["role"],
        "level": proposed["level"],
    }
    if hermes_merge(current, desired) == desired:
        payload = dict(scalars)
        payload["overrides"] = desired
        _call(write, payload, plugin_dir)
        return
    _call(write, scalars, plugin_dir)
    _write_overrides(current, desired, plugin_dir, write)


def _write_overrides(
    current: Mapping[str, Any],
    desired: Mapping[str, Any],
    plugin_dir: Path,
    write: Writer,
) -> None:
    if hermes_merge(current, desired) == desired:
        _call(write, {"overrides": desired}, plugin_dir)
        return
    try:
        _call(write, {"overrides": []}, plugin_dir)
    except ApiError:
        raise
    try:
        _call(write, {"overrides": desired}, plugin_dir)
    except ApiError:
        _restore(current, plugin_dir, write)
        raise


def _restore(current: Mapping[str, Any], plugin_dir: Path, write: Writer) -> None:
    try:
        write({"overrides": copy_tree(current)}, plugin_dir)
    except Exception:
        logger.exception("could not restore overrides after a refused save")


def _call(write: Writer, values: Mapping[str, object], plugin_dir: Path) -> None:
    try:
        write(values, plugin_dir)
    except PermissionError as exc:
        raise ApiError(
            "managed",
            "Not saved: an administrator has locked this setting in Hermes's managed "
            "configuration. Ask them to change it there.",
            status=403,
        ) from exc
    except RuntimeError as exc:
        raise ApiError(
            "writer_unavailable",
            "Not saved: Hermes's settings writer is not available in this dashboard.",
            status=503,
        ) from exc
    except ValueError as exc:
        raise ApiError("refused", _plain(exc), status=400) from exc
    except OSError as exc:
        logger.exception("settings write failed")
        raise ApiError(
            "write_failed",
            "Not saved: the settings file could not be written. "
            "The dashboard's log has the detail.",
            status=500,
        ) from exc


def _plain(exc: ValueError) -> str:
    text = str(exc).strip()
    if not text or "Traceback" in text:
        return "Hermes refused that value."
    return text
