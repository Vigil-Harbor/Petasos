"""Read managed scope through Hermes, keeping an unavailable reader distinct."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from petasos.hermes.host import load_module, managed_keys


@dataclass(frozen=True, slots=True)
class Managed:
    """The managed document Hermes uses and the machine location it may bypass."""

    directory: Path | None
    machine: Path | None
    document: dict[str, Any]
    machine_document: dict[str, Any]
    keys: frozenset[str]
    in_force: bool


def writable(directory: Path) -> bool:
    """Replacing a file takes write access to its directory, even for a read-only file."""
    return directory.is_dir() and os.access(directory, os.W_OK | os.X_OK)


def read_managed() -> Managed:
    """Fail closed when Hermes's reader is missing, raises, or ignores this backend."""
    if os.name == "nt" and not os.environ.get("HERMES_MANAGED_DIR", "").strip():
        return Managed(None, None, {}, {}, frozenset(), False)
    module = load_module("hermes_cli.managed_scope")
    directory_fn = getattr(module, "get_managed_dir", None)
    document_fn = getattr(module, "load_managed_config", None)
    if not callable(directory_fn) or not callable(document_fn):
        raise ValueError("This Python cannot tell which settings Hermes fixes at machine level.")
    machine = getattr(module, "_DEFAULT_MANAGED_DIR", None)
    if not isinstance(machine, Path):
        raise ValueError("Hermes does not say where its machine-level settings belong.")
    override = os.environ.get("HERMES_MANAGED_DIR", "").strip()
    # Hermes has one POSIX default, including macOS, and no native Windows location.
    target = Path(override) if override else machine if os.name != "nt" else None
    try:
        active = directory_fn()
        if active is not None and not isinstance(active, Path):
            raise ValueError("Hermes returned an unreadable managed directory.")
        document = document_fn()
        keys = managed_keys()
        if not isinstance(document, dict) or keys is None:
            raise ValueError("Hermes could not read its machine-level settings.")
        physical = _read_file(module, target) if target is not None else {}
        if physical != document:
            raise ValueError(
                "Hermes is not applying the managed file. Its settings are uncertain."
            )
        machine_document = _read_file(module, machine) if target != machine else dict(document)
    except Exception as exc:
        raise ValueError(
            "This Python cannot tell which settings Hermes fixes at machine level. "
            "Run hermes petasos doctor, which uses Hermes's own Python."
        ) from exc
    return Managed(target, machine, document, machine_document, keys, active == target)


def _read_file(module: object, directory: Path) -> dict[str, Any]:
    path = directory / "config.yaml"
    if not path.exists():
        return {}
    # Use Hermes's parser and file reader for the inactive machine location too.
    reader = getattr(module, "_cached_read", None)
    parser = getattr(module, "fast_safe_load", None)
    if not callable(reader) or not callable(parser):
        raise ValueError("Hermes's managed file reader is unavailable.")
    parsed = reader(path, {}, lambda p: parser(p.read_text(encoding="utf-8-sig")))
    if not isinstance(parsed, dict):
        raise ValueError("The managed file is damaged or unreadable.")
    return dict(parsed)


def effective_config() -> dict[str, Any]:
    """The same overlaid config used by PluginContext.get_config, without saving."""
    module = load_module("hermes_cli.config")
    reader = getattr(module, "load_config_readonly", None)
    if not callable(reader):
        raise ValueError("This Python cannot read the settings Hermes is using.")
    try:
        document = reader()
    except Exception as exc:
        raise ValueError("Hermes could not read this profile's settings.") from exc
    if not isinstance(document, dict):
        raise ValueError("Hermes could not read this profile's settings.")
    return dict(document)


def hook_timeout() -> float:
    """Ask Hermes for its effective timeout, including its default and clamp."""
    module = load_module("hermes_cli.plugins")
    reader = getattr(module, "_resolve_hook_callback_timeout", None)
    if not callable(reader):
        raise ValueError("This Hermes cannot say how long plugin checks may run.")
    try:
        value = reader()
    except Exception as exc:
        raise ValueError("Hermes could not read the time limit for plugin checks.") from exc
    if not isinstance(value, (int, float)):
        raise ValueError("Hermes returned an unreadable time limit for plugin checks.")
    return float(value)
