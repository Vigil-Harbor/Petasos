"""Hermes config-path resolver — shared by plugin_api and reference_plugin.

Resolves the effective config.yaml path across Hermes v0.15 (root) and
v0.16+ (per-profile home) layouts.  Uses stdlib (pathlib, os, platform)
and PyYAML for config parsing; no logging, no fastapi.  The resolver
never raises (D3).
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Tier = Literal["hermes_home", "profile", "root"]


@dataclass(frozen=True)
class HermesConfigResolution:
    """Result of config-path resolution.

    Invariant: ``warning`` is non-None only when ``tier == "root"``
    (the D2 dangling-pointer case).
    """

    path: Path
    tier: Tier
    warning: str | None = None


def hermes_root() -> Path:
    """v0.15 root: %LOCALAPPDATA%\\hermes (Windows) | ~/.hermes (else).

    Empty/unset LOCALAPPDATA mirrors Hermes's own fallback —
    Path.home() / "AppData" / "Local" / "hermes".  An unresolvable
    home (Path.home() raising) is absorbed per D3.
    """
    if platform.system() == "Windows":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        if local:
            return Path(local) / "hermes"
        try:
            return Path.home() / "AppData" / "Local" / "hermes"
        except (RuntimeError, KeyError):
            return Path("hermes")
    try:
        return Path.home() / ".hermes"
    except (RuntimeError, KeyError):
        return Path(".hermes")


def read_active_profile(root: Path) -> str | None:
    """Stripped content of ``<root>/active_profile``, or None.

    Returns None when the file is absent, empty, whitespace-only,
    equals ``"default"``, or is unreadable.  Mirrors the guarded read
    in ``hermes_constants.get_hermes_home`` byte-for-byte — no explicit
    encoding argument on ``read_text()`` (system default).
    """
    try:
        p = root / "active_profile"
        if not p.is_file():
            return None
        content = p.read_text().strip()
        if not content or content == "default":
            return None
        return content
    except (UnicodeDecodeError, OSError):
        return None


def resolve_active_profile_dir(
    root: Path,
) -> tuple[Path | None, str | None]:
    """Resolve the active profile directory under *root*.

    Returns ``(<root>/profiles/<name>, None)`` when the pointer names
    an existing directory; ``(None, "<warning>")`` when it names a
    missing one (or a file); ``(None, None)`` when there is no usable
    pointer.
    """
    name = read_active_profile(root)
    if name is None:
        return None, None
    try:
        root_profiles = (root / "profiles").resolve(strict=False)
        candidate = (root_profiles / name).resolve(strict=False)
    except (OSError, RuntimeError):
        return None, (
            f"active_profile {name!r} could not be resolved — falling back to root config"
        )
    if not candidate.is_relative_to(root_profiles):
        return None, (
            f"active_profile {name!r} resolves to {candidate} which "
            f"escapes {root_profiles} — falling back to root config"
        )
    if candidate.is_dir():
        return candidate, None
    return None, (
        f"active_profile points to {name!r} but "
        f"{candidate} is not an existing directory — "
        f"falling back to root config"
    )


def resolve_hermes_config_path() -> HermesConfigResolution:
    """Resolve the effective Hermes config.yaml path.

    Precedence: HERMES_HOME env (tier 1) -> active-profile pointer
    (tier 2) -> v0.15 root (tier 3).  Total: never raises.
    """
    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        return HermesConfigResolution(
            path=Path(hermes_home) / "config.yaml",
            tier="hermes_home",
        )

    root = hermes_root()

    profile_dir, warning = resolve_active_profile_dir(root)
    if profile_dir is not None:
        return HermesConfigResolution(
            path=profile_dir / "config.yaml",
            tier="profile",
        )
    if warning is not None:
        return HermesConfigResolution(
            path=root / "config.yaml",
            tier="root",
            warning=warning,
        )

    return HermesConfigResolution(
        path=root / "config.yaml",
        tier="root",
    )


def read_petasos_section(res: HermesConfigResolution) -> dict[str, Any]:
    """Read the ``petasos:`` YAML section from the resolved config path.

    Returns ``{}`` on missing file, unreadable file, malformed YAML,
    YAML parsing to a non-dict, or a ``petasos:`` value that is not a
    dict.  Never raises (D3).
    """
    import yaml

    if not res.path.is_file():
        return {}
    try:
        with open(res.path, encoding="utf-8") as f:
            full_config = yaml.safe_load(f)
    except Exception:
        return {}
    if not isinstance(full_config, dict):
        return {}
    section = full_config.get("petasos", {})
    if not isinstance(section, dict):
        return {}
    return section
