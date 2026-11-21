"""Doctor checks for settings, secrets, and which values are really custom."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

from petasos.config.layers import LEVELS, ROLES, Resolved, resolve
from petasos.config.schema import ConfigError, leaves, to_mapping
from petasos.config.sections import PetasosConfig
from petasos.hermes.doctor_model import Check, Status
from petasos.hermes.doctor_support import (
    at_path,
    expansions,
    legacy_present,
    migrate_command,
    sentence,
    settings_mapping,
)
from petasos.hermes.settings import HASH_ENV, PLUGIN_ID, SESSION_ENV, read_profile_env

if TYPE_CHECKING:
    from pathlib import Path

_LEVEL_PLAIN = {
    "relaxed": "fewer interruptions and less protection",
    "balanced": "the usual protection",
    "strict": "stricter checks and earlier blocking",
}
_LEVEL_DETAIL = {
    "relaxed": (
        "Checks are looser than usual. If an extra check breaks, "
        "that text is blocked and Petasos keeps going."
    ),
    "balanced": (
        "Checks are at the usual strictness. If an extra check breaks, "
        "that text is blocked and Petasos keeps going."
    ),
    "strict": (
        "Checks are strict. If an extra check breaks, the text is blocked and "
        "Petasos stops. Personal information a check reports is hidden."
    ),
}
_FAIL_PLAIN = {
    "open": "if an extra check breaks, the text is let through",
    "degraded": "if an extra check breaks, that text is blocked and Petasos keeps going",
    "closed": "if an extra check breaks, the text is blocked and Petasos stops",
}
_POSTURE_PLAIN = {
    "block": "dangerous tool calls are blocked",
    "approve": "dangerous tool calls wait for a person to confirm them",
}


def settings_check(
    document: object,
    read_problem: str | None,
    home: Path,
) -> tuple[Resolved | None, Check, bool, dict[str, object]]:
    """The settings check, whether an old section remains, and facts for status.

    The facts are ``readable``, ``role``, ``level``, ``petasos_enabled``, and
    ``settings_error``. An override that does not change the role and level
    is left out of the summary.
    """
    raw = settings_mapping(document, PLUGIN_ID)
    stored_role = raw.get("role")
    stored_level = raw.get("level")
    stored_enabled = raw.get("enabled", True)
    facts: dict[str, object] = {
        "readable": read_problem is None,
        "role": stored_role if isinstance(stored_role, str) else None,
        "level": stored_level if isinstance(stored_level, str) else None,
        "petasos_enabled": stored_enabled is True if read_problem is None else None,
        "settings_error": None,
    }
    if read_problem == "no-reader":
        facts["settings_error"] = {
            "path": "",
            "message": "The settings file could not be read.",
        }
        return (
            None,
            Check(
                id="settings",
                status="fail",
                summary="The config file could not be read.",
                meaning=(
                    "This Python cannot read Hermes's config file. "
                    "Hermes's own Python can. Settings were not checked."
                ),
                next_step="Run hermes petasos doctor, which uses Hermes's own Python.",
            ),
            False,
            facts,
        )
    if read_problem == "broken":
        facts["settings_error"] = {
            "path": "",
            "message": "The settings file could not be read.",
        }
        return (
            None,
            Check(
                id="settings",
                status="fail",
                summary="The config file is damaged, so the settings could not be read.",
                meaning="Petasos cannot trust a config file it cannot read.",
                next_step=f"Repair {home / 'config.yaml'} and run petasos doctor again.",
            ),
            False,
            facts,
        )
    legacy = legacy_present(document)
    found = expansions(raw)
    try:
        resolved = resolve(raw)
    except ConfigError as exc:
        path, message = exc.errors[0]
        facts["settings_error"] = {"path": path, "message": message}
        meaning = str(exc)
        if meaning[:1].islower():
            meaning = meaning[0].upper() + meaning[1:]
        steps = [
            "Set role to general, coding, research, support, or admin, "
            "and level to relaxed, balanced, or strict."
        ]
        if legacy:
            meaning = "An old petasos: section is in the config and is not used. " + meaning
            steps.insert(0, migrate_command(home))
        if found:
            listed = ", ".join(found)
            meaning += (
                f" A setting contains {listed}. Hermes replaces that with an "
                "environment value when it reads the file. Write the value itself."
            )
            steps.append("Replace the ${...} text with the value you actually want.")
        return (
            None,
            Check(
                id="settings",
                status="warn",
                summary="The settings were rejected, so Petasos falls back to its usual settings.",
                meaning=meaning,
                next_step=" Then ".join(steps),
            ),
            legacy,
            facts,
        )
    facts["role"] = resolved.settings.role
    facts["level"] = resolved.settings.level
    facts["petasos_enabled"] = resolved.settings.enabled
    lines: list[str] = []
    detail: list[str] = []
    actions: list[str] = []
    status: Status = "ok"
    if resolved.settings.enabled:
        role = ROLES[resolved.settings.role]
        level = _LEVEL_DETAIL.get(
            resolved.settings.level,
            LEVELS[resolved.settings.level].description,
        )
        purpose = role.description.partition(".")[0]
        lines.append(f"{purpose}, with {_LEVEL_PLAIN[resolved.settings.level]}.")
        detail.extend((role.description, level, *extra_lines(resolved)))
    if not resolved.settings.enabled:
        status = "fail"
        lines.append("Tool calls are not checked until protection is turned on.")
        actions.append(
            "Turn protection on in Hermes's plugin settings. The switch is called enabled."
        )
    if legacy:
        if status != "fail":
            status = "warn"
        lines.append(
            "An old petasos: section is still in the config. Petasos does not read it. "
            "The settings in this report are the ones in use, not that section."
        )
        actions.append(migrate_command(home))
    if found:
        if status != "fail":
            status = "warn"
        listed = ", ".join(found)
        lines.append(
            f"A setting contains {listed}. Hermes replaces that with an environment "
            "value when it reads the file. Petasos settings should be plain text."
        )
        actions.append("Replace the ${...} text with the value you actually want.")
    return (
        resolved,
        Check(
            id="settings",
            status=status,
            summary=settings_summary(resolved),
            meaning="\n".join(lines),
            next_step=" Then ".join(actions),
            detail=tuple(detail),
        ),
        legacy,
        facts,
    )


def secret_checks(home: Path, resolved: Resolved | None) -> tuple[Check, Check, dict[str, str]]:
    """The session secret and the hash key. Values are never included."""
    session_raw = read_profile_env(home, SESSION_ENV)
    hash_raw = read_profile_env(home, HASH_ENV)
    session = _session_check(session_raw)
    needed = resolved is not None and resolved.config.anonymization.mode == "hash"
    if hash_raw:
        hashed = Check(
            id="hash_key",
            status="ok",
            summary="The hash key is set. Its value is not shown.",
        )
    elif needed:
        hashed = Check(
            id="hash_key",
            status="warn",
            summary="Hashed hiding of personal information is on, and the hash key is not set.",
            meaning=(
                f"Set {HASH_ENV} in the profile's env file. "
                "The value is not stored in the config file."
            ),
            next_step=f"Add {HASH_ENV} to {home / '.env'} and run petasos doctor again.",
        )
    else:
        hashed = Check(
            id="hash_key",
            status="ok",
            summary="The hash key is not set. Nothing you have turned on asks for it.",
        )
    state = {
        "session_secret": "unset" if session_raw is None else "set",
        "hash_key": "unset" if not hash_raw else "set",
    }
    return session, hashed, state


def settings_summary(resolved: Resolved) -> str:
    """The one-line settings summary."""
    if not resolved.settings.enabled:
        return "Protection is off."
    return f"Job: {resolved.settings.role}. Strictness: {resolved.settings.level}."


def extra_lines(resolved: Resolved) -> tuple[str, ...]:
    """Lines for values the role or level changed, and for real customisations.

    An override whose value equals what the role and level already produce is
    not a customisation. It is left out.
    """
    current = to_mapping(resolved.config)
    stock = to_mapping(PetasosConfig())
    layered = to_mapping(
        resolve(
            {
                "enabled": resolved.settings.enabled,
                "role": resolved.settings.role,
                "level": resolved.settings.level,
                "overrides": {},
            }
        ).config
    )
    help_text = {info.path: info.help for info in leaves(PetasosConfig)}
    lines: list[str] = []
    for path, source in resolved.origin.items():
        value = at_path(current, path)
        usual = at_path(stock, path)
        from_layers = at_path(layered, path)
        if value == from_layers and (source == "override" or value == usual):
            continue
        lines.append(_leaf_line(path, value, source, help_text.get(path, path), resolved))
    return tuple(lines)


def _leaf_line(
    path: str,
    value: object,
    source: str,
    help_text: str,
    resolved: Resolved,
) -> str:
    where = _where(source, resolved)
    if path == "tools.dangerous_posture" and isinstance(value, str):
        plain = _POSTURE_PLAIN.get(value, value)
        return f"{sentence(plain)} This comes from {where}."
    if path == "fail_mode" and isinstance(value, str):
        return f"{sentence(_FAIL_PLAIN.get(value, value))} This comes from {where}."
    if path == "rules.suppress" and isinstance(value, list):
        return f"{len(value)} built-in checks are quieted. This comes from {where}."
    shown = json.dumps(value, ensure_ascii=False, default=str)
    lead = sentence(help_text) if help_text[:1].islower() else help_text
    return f"{lead} It is {shown}. This comes from {where}."


def _where(source: str, resolved: Resolved) -> str:
    if source == "role":
        return f"the {resolved.settings.role} job"
    if source == "level":
        return f"the {resolved.settings.level} strictness"
    if source == "override":
        return "a custom setting"
    return "the usual setting"


def _session_check(raw: str | None) -> Check:
    if raw is None:
        return Check(
            id="session_secret",
            status="ok",
            summary=(
                "The session secret is not set. Session tokens are not tied to this profile."
            ),
        )
    try:
        base64.b64decode(raw, validate=True)
    except Exception:
        return Check(
            id="session_secret",
            status="warn",
            summary="The session secret is set, but Petasos cannot read it.",
            meaning=f"{SESSION_ENV} has to be base64. The value is not shown.",
            next_step=f"Replace {SESSION_ENV} in the profile env file with a base64 value.",
        )
    return Check(
        id="session_secret",
        status="ok",
        summary="The session secret is set. Its value is not shown.",
    )
