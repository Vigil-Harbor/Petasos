"""Choose the Hermes profile a command reads.

``--home`` and ``--profile`` win. With neither, the choice is the same one
the plugin makes, and the returned sentence says which home that was.
"""

from __future__ import annotations

import os
from pathlib import Path

from petasos.hermes.home import resolve_hermes_config_path


def resolve_target(*, home: str | None, profile: str | None) -> tuple[Path, str]:
    """The profile directory to use, and a sentence saying why it was chosen."""
    if home is not None and home.strip() != "":
        base = Path(home).expanduser().resolve()
        reason = "the home you named with --home"
    else:
        env_home = os.environ.get("HERMES_HOME", "").strip()
        if env_home:
            base = Path(env_home).expanduser().resolve()
            reason = "the HERMES_HOME environment variable"
        else:
            resolution = resolve_hermes_config_path()
            base = resolution.path.parent
            if resolution.tier == "profile":
                reason = "the active Hermes profile"
            elif resolution.tier == "hermes_home":
                reason = "the HERMES_HOME environment variable"
            elif resolution.tier == "override":
                reason = "the home Hermes named for this process"
            else:
                reason = "the Hermes root, because no profile is selected"
            if resolution.warning:
                reason = f"{reason}. {resolution.warning}"
    if profile is None or profile.strip() == "":
        return base, reason
    chosen = profile_home(base, profile.strip())
    return chosen, f"profile {profile.strip()}, under {reason}"


def profile_home(base: Path, name: str) -> Path:
    """The directory for profile ``name`` under ``base``.

    ``default`` is the home with no profile. Any other name is one path
    segment under ``profiles/``. A name that could leave that directory
    is rejected.
    """
    if name != "default" and not _single_segment(name):
        raise ValueError(
            f"Profile name {name!r} is not a single directory name. "
            "Use the name under profiles/, or default for the home with no profile."
        )
    if name == "default":
        if base.parent.name == "profiles":
            return base.parent.parent
        return base
    root = base.parent.parent if base.parent.name == "profiles" else base
    return root / "profiles" / name


def _single_segment(name: str) -> bool:
    if name in {"", ".", ".."}:
        return False
    # A colon is a drive letter on Windows: "D:elsewhere" joined to
    # profiles/ is a path on drive D, outside the Hermes home.
    return not any(mark in name for mark in ("/", "\\", "\x00", ":"))
