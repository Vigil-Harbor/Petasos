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
)
_SETTINGS_TAILS = ("plugins.entries.petasos",)


def hermes_surface(paths: Iterable[str]) -> GuardrailSurface:
    """Label ``paths`` and add the Hermes commands that change a guardrail."""
    labelled: dict[str, set[str]] = {"settings": set(), "plugin": set(), "record": set()}
    for raw in paths:
        labelled[_kind(str(raw))].add(str(raw))
    commands: list[CommandRule] = []
    for verb in ("disable", "enable", "remove"):
        commands.append(
            CommandRule(
                "plugin",
                ("hermes", "plugins", verb),
                f"hermes plugins {verb}",
                name=_PLUGIN,
            )
        )
    commands.append(
        CommandRule("plugin", ("hermes", "gateway", "restart"), "hermes gateway restart")
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
        flags=(FlagRule("plugin", "hermes", "--safe-mode", "hermes --safe-mode"),),
        env=(EnvRule("plugin", "HERMES_SAFE_MODE", "HERMES_SAFE_MODE"),),
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
