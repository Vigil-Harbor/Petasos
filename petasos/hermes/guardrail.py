"""Hermes paths and commands that change a guardrail.

The library matches them. This module only names the ones that belong to Hermes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from petasos.session.guardrail import CommandRule, EnvRule, FlagRule, GuardrailSurface

if TYPE_CHECKING:
    from collections.abc import Iterable

_PLUGIN = "petasos"
_PLUGIN_TAILS = (
    "plugins.enabled",
    "plugins.disabled",
    "plugins.hook_callback_timeout",
    "plugins.auto_apply",
)
_SETTINGS_TAILS = ("plugins.entries.petasos",)
# ``hermes update`` restarts the processes that run agents unless the flag
# makes the invocation read-only. See hermes-host-facts.md.
_UPDATE_READS = ("--check", "--plan", "--list-venv-holders", "--install-id")


def hermes_surface(paths: Iterable[str]) -> GuardrailSurface:
    """Label ``paths`` and add the Hermes commands that change a guardrail."""
    labelled: dict[str, set[str]] = {"settings": set(), "plugin": set(), "record": set()}
    for raw in paths:
        labelled[_kind(str(raw))].add(str(raw))
    commands: list[CommandRule] = []
    for verb in ("disable", "enable", "remove", "rm", "uninstall"):
        commands.append(
            CommandRule(
                "plugin",
                ("hermes", "plugins", verb),
                f"hermes plugins {verb}",
                name=_PLUGIN,
            )
        )
    commands.append(
        CommandRule(
            "plugin",
            ("hermes", "plugins", "install"),
            "hermes plugins install",
            name=_PLUGIN,
        )
    )
    # No name updates every installed plugin.
    commands.append(
        CommandRule(
            "plugin",
            ("hermes", "plugins", "update"),
            "hermes plugins update",
            name=_PLUGIN,
            bare=True,
        )
    )
    for verb in ("adopt", "trust-update-url"):
        commands.append(
            CommandRule(
                "plugin",
                ("hermes", "plugins", verb),
                f"hermes plugins {verb}",
                name=_PLUGIN,
            )
        )
    for verb in ("auto-update", "autoupdate"):
        commands.append(
            CommandRule(
                "plugin",
                ("hermes", "plugins", verb),
                f"hermes plugins {verb}",
                one_of=("on", "off"),
            )
        )
    commands.append(
        CommandRule(
            "plugin",
            ("hermes", "plugins", "pack", "install"),
            "hermes plugins pack install",
        )
    )
    commands.append(
        CommandRule("plugin", ("hermes", "gateway", "restart"), "hermes gateway restart")
    )
    commands.append(CommandRule("plugin", ("hermes", "gateway", "start"), "hermes gateway start"))
    commands.append(
        CommandRule(
            "plugin",
            ("hermes", "gateway", "run"),
            "hermes gateway run --replace",
            requires_flag="--replace",
        )
    )
    commands.append(
        CommandRule(
            "plugin",
            ("hermes", "update"),
            "hermes update",
            unless_flags=_UPDATE_READS,
        )
    )
    for verb in ("use", "delete", "rename"):
        commands.append(
            CommandRule("plugin", ("hermes", "profile", verb), f"hermes profile {verb}")
        )
    commands.append(
        CommandRule(
            "settings",
            ("hermes", "profile", "update"),
            "hermes profile update --force-config",
            requires_flag="--force-config",
        )
    )
    commands.append(CommandRule("settings", ("hermes", "config", "edit"), "hermes config edit"))
    commands.append(
        CommandRule("settings", ("hermes", "config", "migrate"), "hermes config migrate")
    )
    for verb in ("set", "unset"):
        for tail in _PLUGIN_TAILS:
            commands.append(
                CommandRule(
                    "plugin",
                    ("hermes", "config", verb),
                    f"hermes config {verb} {tail}",
                    tail=tail,
                )
            )
        for tail in _SETTINGS_TAILS:
            commands.append(
                CommandRule(
                    "settings",
                    ("hermes", "config", verb),
                    f"hermes config {verb} {tail}",
                    tail=tail,
                )
            )
    return GuardrailSurface(
        paths={kind: frozenset(values) for kind, values in labelled.items()},
        commands=tuple(commands),
        flags=(
            FlagRule("plugin", "hermes", "--safe-mode", "hermes --safe-mode"),
            FlagRule("plugin", "hermes", "--ignore-user-config", "hermes --ignore-user-config"),
            FlagRule("plugin", "hermes", "--profile", "hermes --profile"),
            FlagRule("plugin", "hermes", "-p", "hermes -p"),
        ),
        env=(
            EnvRule("plugin", "HERMES_SAFE_MODE", "HERMES_SAFE_MODE"),
            EnvRule("plugin", "HERMES_IGNORE_USER_CONFIG", "HERMES_IGNORE_USER_CONFIG"),
            EnvRule("plugin", "HERMES_HOME", "HERMES_HOME", any_value=True, program="hermes"),
            EnvRule(
                "plugin",
                "HERMES_MANAGED_DIR",
                "HERMES_MANAGED_DIR",
                any_value=True,
                program="hermes",
            ),
        ),
    )


def _kind(path: str) -> str:
    name = Path(path).name.casefold()
    parts = [part.casefold() for part in Path(path).parts]
    if "petasos-enforcement" in name or name.endswith(".jsonl") or name.endswith(".jsonl.rot"):
        return "record"
    if name == "active_profile" or "plugins" in parts:
        return "plugin"
    if name in {"config.yaml", ".env"}:
        return "settings"
    return "settings"
