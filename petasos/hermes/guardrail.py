"""Hermes paths and commands that change a guardrail.

The library matches them. This module only names the ones that belong to Hermes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from petasos.guard.surface import CommandProgram, CommandRule, EnvRule, FlagRule, GuardrailSurface

if TYPE_CHECKING:
    from collections.abc import Iterable

_PLUGIN = "petasos"
_PLUGIN_TAILS = (
    "plugins.enabled",
    "plugins.disabled",
    "plugins.hook_callback_timeout",
    "plugins.auto_apply",
)
# ``approvals`` holds Hermes's approval settings (mode, timeout, deny list).
# ``petasos`` is the plugin's own top-level section. Petasos reads its
# settings elsewhere, but a write there is still treated as a change.
_SETTINGS_TAILS = ("plugins.entries.petasos", "command_allowlist", "approvals", "petasos")
# Hermes's top-level options (hermes_cli/_parser.py, ``_add_top_level_flags``),
# matched for ``hermes`` and for a program word that cannot be resolved.
# These take the next word as their value, rather than a verb. ``--config``
# is not one of Hermes's; Hermes refuses it, so the command does not run.
_GLOBAL_VALUES = frozenset(
    {
        "--profile",
        "-p",
        "--config",
        "--model",
        "-m",
        "--provider",
        "--reasoning",
        "--toolsets",
        "-t",
        "--resume",
        "-r",
        "--skills",
        "-s",
        "--oneshot",
        "-z",
        "--usage-file",
        "--in",
        "--cpu-profile",
    }
)
# ``--continue`` takes the next word unless it starts with ``-``.
_GLOBAL_OPTIONAL_VALUES = frozenset({"--continue", "-c"})
_GLOBAL_FLAGS = frozenset(
    {
        "--help",
        "-h",
        "--version",
        "-V",
        "--no-restore-cwd",
        "--worktree",
        "-w",
        "--accept-hooks",
        "--yolo",
        "--pass-session-id",
        "--checkpoints",
        "--ignore-user-config",
        "--ignore-rules",
        "--safe-mode",
        "--tui",
        "--native",
        "--tui-native",
        "--cli",
        "--dev",
    }
)
# Hermes removes ``-p``/``--profile`` and its value wherever it appears before
# ``--``, before argparse runs (hermes_cli/main.py, ``_scan_profile_flag``).
_PROFILE_OPTIONS = frozenset({"--profile", "-p"})
# ``hermes update`` restarts the processes that run agents unless the flag
# makes the invocation read-only. See hermes-host-facts.md.
_UPDATE_READS = ("--check", "--plan", "--list-venv-holders", "--install-id")


def hermes_surface(paths: Iterable[str], roots: Iterable[str] = ()) -> GuardrailSurface:
    """Label ``paths`` and add the Hermes commands that change a guardrail."""
    labelled: dict[str, set[str]] = {"settings": set(), "plugin": set(), "record": set()}
    for raw in paths:
        labelled[_kind(str(raw))].add(str(raw))
    commands: list[CommandRule] = []
    # A command marked ``help_clears=False`` writes Hermes's configuration.
    for verb in ("disable", "remove", "rm", "uninstall"):
        commands.append(
            CommandRule(
                "plugin",
                ("hermes", "plugins", verb),
                f"hermes plugins {verb}",
                name=_PLUGIN,
                help_clears=False,
            )
        )
    # Enabling still writes the plugin's entry when it grants or revokes
    # the tool-override permission (plugins.entries.petasos.allow_tool_override).
    for full, shortest in (
        ("--allow-tool-override", "--a"),
        ("--no-allow-tool-override", "--n"),
    ):
        for flag in _prefixes(full, shortest):
            commands.append(
                CommandRule(
                    "settings",
                    ("hermes", "plugins", "enable"),
                    f"hermes plugins enable {full}",
                    name=_PLUGIN,
                    requires_flag=flag,
                    help_clears=False,
                )
            )
    # Enabling the plugin by its plain name only turns enforcement on. Every
    # other spelling that names it or everything (``all``, ``-a``, ``*``, a
    # version, an extra, a source or a built file, another plugin beside it,
    # ``--force``, another case, a global option) may install different code
    # or enable more, so it is a change. Enabling writes ``plugins.enabled``,
    # so a help flag does not clear it.
    commands.append(
        CommandRule(
            "plugin",
            ("hermes", "plugins", "enable"),
            "hermes plugins enable",
            name=_PLUGIN,
            help_clears=False,
            except_exact=("hermes", "plugins", "enable", _PLUGIN),
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
    # ``--enable`` adds the installed plugin to Hermes's enabled list.
    for flag in _prefixes("--enable", "--e"):
        commands.append(
            CommandRule(
                "plugin",
                ("hermes", "plugins", "install"),
                "hermes plugins install --enable",
                name=_PLUGIN,
                requires_flag=flag,
                help_clears=False,
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
                help_clears=False,
            )
        )
    # A pack may seed plugins.entries for the plugins it installs.
    commands.append(
        CommandRule(
            "plugin",
            ("hermes", "plugins", "pack", "install"),
            "hermes plugins pack install",
            help_clears=False,
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
    for length in range(3, len("--force-config") + 1):
        commands.append(
            CommandRule(
                "settings",
                ("hermes", "profile", "update"),
                "hermes profile update --force-config",
                requires_flag="--force-config"[:length],
                help_clears=False,
            )
        )
    commands.append(
        CommandRule(
            "settings", ("hermes", "config", "edit"), "hermes config edit", help_clears=False
        )
    )
    commands.append(
        CommandRule("settings", ("hermes", "import"), "hermes import", help_clears=False)
    )
    for flag in ("--res", "--rese", "--reset"):
        commands.append(
            CommandRule(
                "settings",
                ("hermes", "setup"),
                "hermes setup --reset",
                requires_flag=flag,
                help_clears=False,
            )
        )
    for flag in ("--f", "--fo", "--for", "--forc", "--force"):
        commands.append(
            CommandRule(
                "settings",
                ("hermes", "profile", "install"),
                "hermes profile install --force",
                requires_flag=flag,
                help_clears=False,
            )
        )
    commands.append(
        CommandRule(
            "settings",
            ("hermes", "config", "migrate"),
            "hermes config migrate",
            help_clears=False,
        )
    )
    # argparse accepts every unambiguous abbreviation, with a separate or
    # equals-joined value. Without --apply this command only proposes entries.
    for flag in ("--a", "--ap", "--app", "--appl", "--apply"):
        commands.append(
            CommandRule(
                "settings",
                ("hermes", "approvals", "suggest"),
                "hermes approvals suggest --apply",
                requires_flag=flag,
                help_clears=False,
            )
        )
    for verb in ("set", "unset"):
        for tail in _PLUGIN_TAILS:
            commands.append(
                CommandRule(
                    "plugin",
                    ("hermes", "config", verb),
                    f"hermes config {verb} {tail}",
                    tail=tail,
                    unknown_program=True,
                    help_clears=False,
                )
            )
        for tail in _SETTINGS_TAILS:
            commands.append(
                CommandRule(
                    "settings",
                    ("hermes", "config", verb),
                    f"hermes config {verb} {tail}",
                    tail=tail,
                    unknown_program=True,
                    help_clears=False,
                )
            )
    return GuardrailSurface(
        paths={kind: frozenset(values) for kind, values in labelled.items()},
        roots=frozenset(str(root) for root in roots),
        commands=tuple(commands),
        programs=(
            CommandProgram(
                "hermes",
                aliases=("ai.hermes", "hermes.exe"),
                modules=("hermes_cli", "hermes_cli.main"),
                value_options=_GLOBAL_VALUES,
                optional_value_options=_GLOBAL_OPTIONAL_VALUES,
                flag_options=_GLOBAL_FLAGS,
                stripped_options=_PROFILE_OPTIONS,
            ),
        ),
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


def _prefixes(flag: str, shortest: str) -> tuple[str, ...]:
    """``flag`` and each abbreviation argparse accepts for it, from ``shortest`` up."""
    return tuple(flag[:length] for length in range(len(shortest), len(flag) + 1))


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
