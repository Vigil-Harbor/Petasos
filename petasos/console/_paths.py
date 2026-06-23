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


def _resolved_normcase(path: Path) -> str | None:
    """``os.path.normcase`` of the ``strict=False`` resolution, or None on OSError.

    The single normalization primitive for active-vs-target identity (D4):
    Windows case-fold, trailing-slash, and symlink collapse all happen here so a
    selected profile is compared to the live binding as the *same file*, never as
    a raw string or leaf name.  Returns None when the OS cannot resolve the name
    (a malformed path or an inaccessible reparse point can raise on Windows); the
    caller treats a None as "not the active path" — the safe persist-only branch.
    """
    try:
        return os.path.normcase(str(path.resolve(strict=False)))
    except OSError:
        return None


def list_hermes_profiles() -> list[dict[str, Any]]:
    """Enumerate ``profiles/*/config.yaml`` under the Hermes root.

    Returns ``[{name, path, is_active, tier}]`` — one entry per profile dir that
    holds a ``config.yaml``, sorted by leaf name, each marked ``is_active`` by the
    normalized-path comparison (D4) against the live binding, never a raw string
    compare.  Fail-soft: a missing or unreadable ``profiles/`` dir (and any other
    failure) yields ``[]`` so the caller folds in the active binding as a single
    entry.  Never raises (D3); stays logging-free to preserve this module's
    pure-stdlib, no-logging contract — the caller (``server.get_config``) owns the
    diagnostic WARNING for an unreadable-but-present ``profiles/`` dir.
    """
    try:
        base = hermes_root() / "profiles"
        base_resolved = base.resolve(strict=False)
        active_norm = _resolved_normcase(resolve_hermes_config_path().path)
        out: list[dict[str, Any]] = []
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            cfg = child / "config.yaml"
            if not cfg.is_file():
                continue
            try:
                child_resolved = child.resolve(strict=False)
            except OSError:
                continue
            if not child_resolved.is_relative_to(base_resolved):
                continue
            cfg_norm = _resolved_normcase(cfg)
            out.append(
                {
                    "name": child.name,
                    "path": str(cfg),
                    "is_active": active_norm is not None and cfg_norm == active_norm,
                    "tier": "profile",
                }
            )
        return out
    except Exception:
        return []


def resolve_profile_config_path(name: str) -> HermesConfigResolution | None:
    """Resolve one named profile's config path, traversal-guarded.

    Returns ``HermesConfigResolution(<root>/profiles/<name>/config.yaml,
    tier="profile", warning=None)`` when *name* is a current
    ``list_hermes_profiles()`` member — a full resolution (not a bare ``Path``) so
    it feeds ``read_petasos_section`` directly.  Returns None when *name* is not a
    member (unknown or deleted) or escapes the ``profiles/`` base.  The membership
    gate is the traversal guard: ``list_hermes_profiles`` only ever emits simple
    leaf names from ``iterdir``, so a ``../`` or absolute *name* is never a member.
    Never raises (D3).
    """
    try:
        if name not in {p["name"] for p in list_hermes_profiles()}:
            return None
        base = (hermes_root() / "profiles").resolve(strict=False)
        candidate = (hermes_root() / "profiles" / name).resolve(strict=False)
        if not candidate.is_relative_to(base):
            return None
        return HermesConfigResolution(
            path=hermes_root() / "profiles" / name / "config.yaml",
            tier="profile",
            warning=None,
        )
    except Exception:
        return None


def read_petasos_section_checked(res: HermesConfigResolution) -> tuple[dict[str, Any], bool]:
    """Read the ``petasos:`` section AND report whether the read succeeded.

    Returns ``(section, ok)``.  ``ok`` is False ONLY when the file exists but is
    unreadable *as* a petasos section: malformed YAML, a top-level non-dict, or a
    ``petasos:`` value that is not a dict.  A missing file, an empty file, a
    missing ``petasos:`` key, or a ``petasos:`` with no value are all ``ok=True``
    with ``{}`` — legitimately empty, not a failure.  This lets a caller tell
    "intentionally empty" apart from "broken": warn on GET, reject on PUT so a
    dirty save can't merge ``{}`` with a patch and silently persist all-defaults
    over a malformed profile (PET-146 D4 data-loss guard).  Never raises (D3).
    """
    import yaml

    if not res.path.is_file():
        return {}, True
    try:
        with open(res.path, encoding="utf-8") as f:
            full_config = yaml.safe_load(f)
    except Exception:
        return {}, False
    if full_config is None:
        return {}, True
    if not isinstance(full_config, dict):
        return {}, False
    if "petasos" not in full_config:
        return {}, True
    section = full_config["petasos"]
    if section is None:
        return {}, True
    if not isinstance(section, dict):
        return {}, False
    return section, True


def read_petasos_section(res: HermesConfigResolution) -> dict[str, Any]:
    """Read the ``petasos:`` YAML section from the resolved config path.

    Returns ``{}`` on missing file, unreadable file, malformed YAML,
    YAML parsing to a non-dict, or a ``petasos:`` value that is not a
    dict.  Never raises (D3).  Use ``read_petasos_section_checked`` when the
    empty-vs-unreadable distinction matters.
    """
    section, _ = read_petasos_section_checked(res)
    return section
