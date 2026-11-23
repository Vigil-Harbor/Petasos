"""Host guardrail surface types and library command rules."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


_COMMAND_TOOLS = frozenset(
    {
        "bash",
        "exec",
        "execute_code",
        "python",
        "shell",
        "sh",
        "terminal",
    }
)

_KINDS = frozenset({"settings", "plugin", "package", "record"})


@dataclass(frozen=True, slots=True)
class CommandRule:
    """One host command that changes a guardrail.

    ``words`` is the program and the verbs, in order. ``name``, when set, must
    appear later in the command, or the command must name everything
    (``--all``, ``-a``, ``all``, ``*``). The program is compared by its file
    name, so a path to ``hermes`` still matches.
    """

    kind: str
    words: tuple[str, ...]
    label: str
    name: str | None = None
    tail: str | None = None
    # Match when no later word names a target. ``hermes plugins update``
    # with no name updates every plugin.
    bare: bool = False
    # The next positional word must be one of these (``auto-update on``).
    one_of: tuple[str, ...] = ()
    requires_flag: str | None = None
    unless_flags: tuple[str, ...] = ()
    # Also match an unknown program carrying these verbs and a guarded tail.
    unknown_program: bool = False

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"unknown guardrail kind {self.kind!r}")
        if not self.words or not self.label.strip():
            raise ValueError("a command rule needs words and a label")


@dataclass(frozen=True, slots=True)
class FlagRule:
    """A flag that changes a guardrail when the named program carries it."""

    kind: str
    program: str
    flag: str
    label: str


@dataclass(frozen=True, slots=True)
class EnvRule:
    """An environment assignment that changes a guardrail when it is turned on."""

    kind: str
    name: str
    label: str
    # When set, any assigned value counts, not only a turned-on one.
    any_value: bool = False
    # A prefix assignment counts only when this program is what runs.
    # An ``export`` of the name still counts.
    program: str | None = None


@dataclass(frozen=True, slots=True)
class CommandProgram:
    """Host-supplied executable names, Python modules and global value options."""

    name: str
    aliases: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    value_options: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class GuardrailSurface:
    """What the host adds to the library's own recognition.

    ``paths`` maps a kind to filesystem paths. ``roots`` are the directories
    the host keeps them in: a command that names a directory at or inside a
    root is a change when that directory holds a protected path. ``commands``,
    ``flags`` and ``env`` are the host's own command forms. An empty surface
    leaves the library's package files and commands in force, and any
    protected paths the caller passes are still checked. ``programs`` names
    equivalent invocations and the global options that consume a value.
    """

    paths: Mapping[str, frozenset[str]] = field(default_factory=dict)
    roots: frozenset[str] = frozenset()
    commands: tuple[CommandRule, ...] = ()
    flags: tuple[FlagRule, ...] = ()
    env: tuple[EnvRule, ...] = ()
    command_tools: frozenset[str] = field(default_factory=lambda: _COMMAND_TOOLS)
    programs: tuple[CommandProgram, ...] = ()


@dataclass(frozen=True, slots=True)
class GuardrailHit:
    """One recognised change. ``target`` is a short display form, not contents."""

    kind: str
    target: str


def library_rules() -> tuple[CommandRule, ...]:
    """Commands that change Petasos itself. They are not host-specific."""
    settings = (
        ("petasos", "config", "migrate", "petasos config migrate"),
        ("petasos", "config", "set", "petasos config set"),
        ("petasos", "config", "unset", "petasos config unset"),
        ("petasos", "config", "edit", "petasos config edit"),
        ("hermes", "petasos", "config", "migrate", "hermes petasos config migrate"),
        ("hermes", "petasos", "config", "set", "hermes petasos config set"),
        ("hermes", "petasos", "config", "unset", "hermes petasos config unset"),
        ("hermes", "petasos", "config", "edit", "hermes petasos config edit"),
    )
    scanners = (
        ("petasos", "scanner", "add", "petasos scanner add"),
        ("petasos", "scanner", "remove", "petasos scanner remove"),
        ("hermes", "petasos", "scanner", "add", "hermes petasos scanner add"),
        ("hermes", "petasos", "scanner", "remove", "hermes petasos scanner remove"),
    )
    plugin = (
        ("petasos", "hermes", "install", "petasos hermes install"),
        ("petasos", "hermes", "pin", "petasos hermes pin"),
        ("petasos", "hermes", "unpin", "petasos hermes unpin"),
        ("hermes", "petasos", "install", "hermes petasos install"),
        ("hermes", "petasos", "pin", "hermes petasos pin"),
        ("hermes", "petasos", "unpin", "hermes petasos unpin"),
    )
    rules: list[CommandRule] = []
    for item in settings:
        *words, label = item
        rules.append(CommandRule("settings", tuple(words), label))
    for item in scanners:
        *words, label = item
        rules.append(CommandRule("settings", tuple(words), label))
    for item in plugin:
        *words, label = item
        rules.append(CommandRule("plugin", tuple(words), label))
    for program in ("pip", "uv"):
        pip_words = ("uv", "pip", "uninstall") if program == "uv" else ("pip", "uninstall")
        install = ("uv", "pip", "install") if program == "uv" else ("pip", "install")
        rules.append(
            CommandRule("package", pip_words, " ".join(pip_words) + " petasos", name="petasos")
        )
        rules.append(
            CommandRule("package", install, " ".join(install) + " petasos", name="petasos")
        )
    for verbs in (
        ("uv", "add"),
        ("uv", "remove"),
        ("uv", "tool", "install"),
        ("uv", "tool", "uninstall"),
        ("uv", "tool", "upgrade"),
    ):
        rules.append(CommandRule("package", verbs, " ".join(verbs) + " petasos", name="petasos"))
    return tuple(rules)


def package_roots() -> frozenset[str]:
    """The installed Petasos package directory, resolved the way paths are compared."""
    root = Path(__file__).resolve().parent.parent
    try:
        resolved = os.path.normcase(str(root.resolve(strict=False)))
    except OSError:
        resolved = os.path.normcase(str(root))
    return frozenset({resolved})
