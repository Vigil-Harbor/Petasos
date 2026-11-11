"""Show, and optionally store, the settings an old ``petasos:`` section becomes.

The old section is never deleted. Secret values are never printed and never
written: the library migration drops them and names the environment variable.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from petasos.config.layers import resolve
from petasos.config.migrate import Migration, migrate
from petasos.config.schema import ConfigError
from petasos.hermes.settings import HASH_ENV, SESSION_ENV, write_settings

if TYPE_CHECKING:
    from pathlib import Path

_INTENTIONAL = (
    "does not change a scan result",
    "is not a setting",
    "was removed",
    "were not applied",
    "disabled wins",
    "does not start asking",
)


@dataclass(frozen=True, slots=True)
class MigrateResult:
    """Text to print and the exit status. Nothing was written when ``wrote`` is false."""

    text: str
    exit_code: int
    wrote: bool


def migrate_profile(
    home: Path,
    *,
    home_reason: str,
    write: bool,
    proceed: bool,
) -> MigrateResult:
    """Show the migration for ``home``. ``write`` stores it through Hermes."""
    loaded = _load_section(home)
    if isinstance(loaded, str):
        return MigrateResult(
            text=_absent_text(home, home_reason, loaded),
            exit_code=_absent_code(loaded),
            wrote=False,
        )
    try:
        result = migrate(loaded)
    except ConfigError as exc:
        return MigrateResult(
            text=(
                f"The old petasos: section in {home / 'config.yaml'} could not be converted.\n"
                f"{exc}\n"
            ),
            exit_code=2,
            wrote=False,
        )
    problems = migration_problems(result)
    body = _render(home, home_reason, result, problems)
    if not write:
        body += (
            "\nNothing was written. Add --write to store these settings through Hermes.\n"
            "The old petasos: section is left as it is either way.\n"
        )
        return MigrateResult(text=body, exit_code=0, wrote=False)
    if problems and not proceed:
        body += (
            "\nNothing was written. The conversion left some of the old section out, "
            "and those items are listed above. Read them, then run the same command "
            "with --write --proceed if you still want the settings stored.\n"
        )
        return MigrateResult(text=body, exit_code=2, wrote=False)
    stored, store_message = _store(home, result)
    body += "\n" + store_message + "\n"
    if stored:
        body += (
            f"\nThe old petasos: section is still in {home / 'config.yaml'}. "
            "Petasos does not remove it. Open that file and delete the petasos: block, "
            "leaving the plugins: block in place.\n"
        )
    return MigrateResult(text=body, exit_code=0 if stored else 2, wrote=stored)


def migration_problems(result: Migration) -> tuple[str, ...]:
    """Notes that mean something the user set was not carried over.

    Intentional removals, such as a secret or a removed scanner, are not
    problems. A settings document ``resolve`` rejects is a problem.
    """
    problems = [note for note in result.notes if not _intentional(note)]
    try:
        resolve(result.settings)
    except ConfigError as exc:
        problems.append(str(exc))
    return tuple(problems)


def _intentional(note: str) -> bool:
    return any(part in note for part in _INTENTIONAL)


def _load_section(home: Path) -> dict[str, Any] | str:
    path = home / "config.yaml"
    if not path.is_file():
        return "missing"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "broken"
    from petasos.hermes.host import load_mapping

    document = load_mapping(text)
    if not isinstance(document, dict):
        if document is None:
            return "absent"
        if _reader_available():
            return "broken"
        return "no-reader"
    section = document.get("petasos")
    if section is None:
        return "absent"
    if not isinstance(section, dict) or len(section) == 0:
        return "absent"
    copied: dict[str, Any] = {}
    for key, value in section.items():
        copied[key] = value
    return copied


def _reader_available() -> bool:
    from petasos.hermes.host import load_module

    for module_name, attr in (
        ("utils", "fast_safe_load"),
        ("hermes_yaml", "safe_load"),
        ("yaml", "safe_load"),
    ):
        module = load_module(module_name)
        if module is not None and callable(getattr(module, attr, None)):
            return True
    return False


def _absent_text(home: Path, home_reason: str, kind: str) -> str:
    path = home / "config.yaml"
    where = f"{home} ({home_reason})"
    if kind == "missing":
        return (
            f"No config file at {path}.\n"
            f"There is no old petasos: section to convert for {where}.\n"
        )
    if kind == "absent":
        return (
            f"No old petasos: section in {path}.\n"
            "Nothing to convert. Settings already live under the plugin, or were never written.\n"
        )
    if kind == "no-reader":
        return (
            f"The config at {path} could not be read. This Python has no YAML reader.\n"
            "Run petasos config migrate with the same Python Hermes uses.\n"
        )
    return (
        f"The config file at {path} is damaged, so the old section could not be read.\n"
        "Repair the file and run petasos config migrate again.\n"
    )


def _absent_code(kind: str) -> int:
    if kind in {"missing", "absent"}:
        return 0
    return 2


def _render(home: Path, home_reason: str, result: Migration, problems: tuple[str, ...]) -> str:
    settings = result.settings
    lines = [
        f"Old settings for {home} ({home_reason}) convert to the following.",
        "",
        _plain_settings(settings),
        "",
        "Paste into the plugin settings:",
        "",
        paste_block(settings).rstrip(),
        "",
    ]
    if result.dropped:
        lines.append("Not copied:")
        for name in result.dropped:
            lines.append(f"- {name}")
        lines.append("")
    if result.notes:
        lines.append("Notes:")
        for note in result.notes:
            lines.append(f"- {note}")
        lines.append("")
    if problems:
        lines.append("Needs a look before storing:")
        for problem in problems:
            lines.append(f"- {problem}")
        lines.append("")
    if _mentions_secret(result):
        lines.append(
            f"Secrets were not copied and are not shown. "
            f"Set {SESSION_ENV} and {HASH_ENV} in {home / '.env'} yourself if you still want them."
        )
        lines.append("")
    return "\n".join(lines)


def _plain_settings(settings: Mapping[str, Any]) -> str:
    enabled = settings.get("enabled")
    armed = "Protection would be on." if enabled is True else "Protection would be off."
    role = settings.get("role")
    level = settings.get("level")
    overrides = settings.get("overrides")
    custom = "No custom settings." if not overrides else "Custom settings are in the block below."
    return f"{armed} Job: {role}. Strictness: {level}. {custom}"


def paste_block(settings: Mapping[str, Any]) -> str:
    """Four settings a person can paste. Overrides are JSON. No secrets."""
    enabled = "true" if settings.get("enabled") is True else "false"
    overrides = settings.get("overrides")
    if not isinstance(overrides, Mapping):
        overrides = {}
    block = {
        "enabled": enabled == "true",
        "role": settings.get("role"),
        "level": settings.get("level"),
        "overrides": dict(overrides),
    }
    # A YAML-shaped block. The overrides value is JSON, which is what the settings form stores.
    return (
        f"enabled: {enabled}\n"
        f"role: {settings.get('role')}\n"
        f"level: {settings.get('level')}\n"
        "overrides: " + json.dumps(block["overrides"], sort_keys=True, ensure_ascii=False) + "\n"
    )


def _mentions_secret(result: Migration) -> bool:
    text = " ".join(result.notes)
    dropped = result.dropped
    return (
        SESSION_ENV in text
        or HASH_ENV in text
        or "session_secret" in dropped
        or "hash_key" in dropped
    )


def _store(home: Path, result: Migration) -> tuple[bool, str]:
    plugin = home / "plugins" / "petasos"
    manifest = plugin / "plugin.yaml"
    if not manifest.is_file():
        return False, (
            "The new settings were not stored. The Petasos plugin is not installed "
            f"for this profile, and Hermes reads the plugin description from {manifest}. "
            "Run petasos hermes install first, then petasos config migrate --write."
        )
    try:
        write_settings(dict(result.settings), plugin_dir=plugin)
    except Exception as exc:
        return False, (
            "Hermes did not store the settings. "
            f"{exc} "
            "This command does not edit the config file itself."
        )
    return True, "Hermes stored the new settings. Secret values were not written."
