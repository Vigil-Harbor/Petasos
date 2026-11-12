"""Hermes home, profile, and config-path resolution.

Resolves the effective config.yaml path across the v0.15 root layout and
the per-profile home. Stdlib only, plus PyYAML when a config file is read.
No logging. The resolver never raises.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

_SPOOL_FILENAME = "petasos-enforcement.jsonl"
_ROT_SUFFIX = ".rot"

_SPOOL_PATH_OVERRIDE: str | None = None

Tier = Literal["override", "hermes_home", "profile", "root"]


@dataclass(frozen=True)
class HermesConfigResolution:
    """Record a resolved config path with warnings only for root fallback."""

    path: Path
    tier: Tier
    warning: str | None = None


def hermes_root() -> Path:
    """Return the Hermes platform root, or None when the home cannot be resolved.

    Windows uses LOCALAPPDATA with the AppData/Local fallback. Other hosts
    use the account home. This function resolves paths without reading them."""
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


def _override_home() -> Path | None:
    """Usable Hermes context-local home, or None to fall through.

    A missing module, ``sys.modules["hermes_constants"] is None``, a missing
    attribute, a non-str, an empty or whitespace-only value, or any exception
    falls through. A usable string is expanded with ``expandvars`` then
    ``expanduser``. A relative result is still usable.
    """
    try:
        import hermes_constants  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        fn = getattr(hermes_constants, "get_hermes_home_override", None)
        if not callable(fn):
            return None
        value = fn()
    except Exception:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        expanded = os.path.expanduser(os.path.expandvars(stripped))
    except Exception:
        return None
    return Path(expanded)


def resolve_hermes_config_path(*, use_override: bool = True) -> HermesConfigResolution:
    """Resolve the effective Hermes config.yaml path.

    Precedence: context-local override (when *use_override*) -> HERMES_HOME
    env -> active-profile pointer -> v0.15 root.  Total: never raises.
    """
    if use_override:
        override = _override_home()
        if override is not None:
            return HermesConfigResolution(
                path=override / "config.yaml",
                tier="override",
                warning=None,
            )

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
    """Return normalized resolved identity, or None when the OS refuses resolution.

    Windows case, trailing slashes and symlinks collapse before comparison.
    An unresolved target takes the persist-only branch."""
    try:
        return os.path.normcase(str(path.resolve(strict=False)))
    except OSError:
        return None


def list_hermes_profiles(*, use_override: bool = True) -> list[dict[str, Any]]:
    """Return sorted profile config paths and normalized active-binding identity.

    Unreadable or absent profile directories yield an empty list without
    logging or raising. The reserved default home is not a profile entry."""
    try:
        base = hermes_root() / "profiles"
        base_resolved = base.resolve(strict=False)
        active_norm = _resolved_normcase(
            resolve_hermes_config_path(use_override=use_override).path
        )
        out: list[dict[str, Any]] = []
        for child in sorted(base.iterdir()):
            # The reserved default selector resolves only the unprofiled home.
            if not child.is_dir() or child.name == "default":
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


def _default_profile_home() -> Path:
    """The home Hermes means by the profile name ``default``.

    A ``HERMES_HOME`` that is ``<root>/profiles/<name>`` belongs to that root; any other
    value is itself the default home (a Docker or custom deployment), as in Hermes's
    ``get_default_hermes_root``.
    """
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        home = Path(env_home)
        return home.parent.parent if home.parent.name == "profiles" else home
    return hermes_root()


def resolve_profile_config_path(name: str) -> HermesConfigResolution | None:
    """Resolve only a listed profile or the reserved default home, without raising.

    Membership in simple leaf names prevents traversal and absolute selectors.
    Unknown or deleted profiles return None. Default resolves at root tier."""
    try:
        if name == "default":
            return HermesConfigResolution(
                path=_default_profile_home() / "config.yaml",
                tier="root",
                warning=None,
            )
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
    """Read settings and distinguish an empty section from an unreadable one.

    Missing or empty files and null sections return ({}, True). Malformed
    YAML or non-mapping documents/sections return ({}, False), allowing
    writers to reject a save rather than overwrite a damaged profile."""
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
    """Return the resolved settings section or an empty mapping without raising.

    Use read_petasos_section_checked to distinguish empty from unreadable."""
    section, _ = read_petasos_section_checked(res)
    return section


def spool_path(res: HermesConfigResolution | None = None, *, use_override: bool = True) -> str:
    """Resolve the enforcement-spool path beside the resolved config.

    *res* selects the file. When *res* is omitted, the path is resolved again
    on this call (``use_override`` selects the override probe). A caller that
    passes a captured resolution and a caller that resolves the process
    binding can name different files. Shared single source for the guard
    owned-set, the spool writer, and tests. It never introduces a cache, and
    the test override keeps winning unconditionally.
    """
    if _SPOOL_PATH_OVERRIDE is not None:
        return _SPOOL_PATH_OVERRIDE
    r = res if res is not None else resolve_hermes_config_path(use_override=use_override)
    return os.path.join(str(r.path.parent), _SPOOL_FILENAME)


def spool_rot_path(res: HermesConfigResolution | None = None, *, use_override: bool = True) -> str:
    """The ``.rot`` sibling of the resolved spool path."""
    return spool_path(res, use_override=use_override) + _ROT_SUFFIX


def display_path(path: Path | str) -> str:
    """Collapse the operator's home-directory prefix to ``~`` for display.

    Case-insensitive on Windows (``normcase``); never raises.
    """
    s = str(path)
    try:
        home = os.path.expanduser("~")
    except Exception:
        return s
    if not home or home == "~":
        return s
    n_s, n_home = os.path.normcase(s), os.path.normcase(home)
    if n_s == n_home:
        return "~"
    for sep in (os.sep, "/"):
        if n_s.startswith(n_home + os.path.normcase(sep)):
            return "~" + s[len(home) :]
    return s
