"""Generate the Hermes plugin manifest from the settings the library owns.

Choices come from the role and level tables. Help text comes from
``SETTING_HELP`` and the secret help constants, which is the same source
the docs read. Schema defaults are what the form displays. The running
defaults live in ``petasos.config.layers``.
"""

from __future__ import annotations

import json
from pathlib import Path

import petasos
from petasos.config.layers import LEVEL_NAMES, ROLE_NAMES, SETTING_HELP
from petasos.config.secrets import HASH_KEY_HELP, SESSION_SECRET_HELP
from petasos.hermes.plugin import HOOKS
from petasos.hermes.settings import HASH_ENV, PLUGIN_ID, SESSION_ENV

DESCRIPTION = "Content security for Hermes agent tool calls and tool results."
MIN_HERMES = ">=0.23.1"

_PLUGIN_DIR = Path(__file__).resolve().parents[2] / "hermes-plugin" / "petasos"
MANIFEST_PATH = _PLUGIN_DIR / "plugin.yaml"
PROJECT_PATH = _PLUGIN_DIR / "pyproject.toml"
_PROJECT_NAME = "petasos-hermes-plugin"
_PROJECT_DESCRIPTION = "Hermes directory plugin for Petasos. Behaviour lives in the petasos wheel."


def release_version() -> str:
    """The package version both generated plugin files ship."""
    return petasos.__version__


def plugin_requirement() -> str:
    """The wheel range for this minor line, derived from :func:`release_version`.

    ``0.4.0`` is ``petasos>=0.4,<0.5``. A release that bumps the version and
    forgets the range fails the manifest test, because both strings come from
    here.
    """
    version = release_version()
    major_text, minor_text, *_rest = version.split(".")
    major = int(major_text)
    minor = int(minor_text)
    return f"petasos>={major}.{minor},<{major}.{minor + 1}"


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _choices(names: tuple[str, ...]) -> list[str]:
    return [f"      - {name}" for name in names]


def render_manifest() -> str:
    """The ``plugin.yaml`` text ``register`` and the schema agree on."""
    lines = [
        f"name: {PLUGIN_ID}",
        f"version: {_quote(release_version())}",
        f"description: {_quote(DESCRIPTION)}",
        f"requires_hermes: {_quote(MIN_HERMES)}",
        "provides_hooks:",
    ]
    lines.extend(f"  - {hook}" for hook in HOOKS)
    lines.extend(
        [
            "config_schema:",
            "  enabled:",
            "    type: bool",
            f"    description: {_quote(SETTING_HELP['enabled'])}",
            "    default: true",
            "  role:",
            "    type: string",
            f"    description: {_quote(SETTING_HELP['role'])}",
            "    choices:",
            *_choices(ROLE_NAMES),
            "    default: general",
            "  level:",
            "    type: string",
            f"    description: {_quote(SETTING_HELP['level'])}",
            "    choices:",
            *_choices(LEVEL_NAMES),
            "    default: balanced",
            "  overrides:",
            "    type: dict",
            f"    description: {_quote(SETTING_HELP['overrides'])}",
            "    default: {}",
            "  session_secret:",
            "    type: secret",
            f"    env: {SESSION_ENV}",
            f"    description: {_quote(SESSION_SECRET_HELP)}",
            "  hash_key:",
            "    type: secret",
            f"    env: {HASH_ENV}",
            f"    description: {_quote(HASH_KEY_HELP)}",
            "",
        ]
    )
    return "\n".join(lines)


def render_plugin_project() -> str:
    """The directory ``pyproject.toml``. Version and the wheel range share one source."""
    requirement = plugin_requirement()
    lines = [
        "[project]",
        f"name = {_quote(_PROJECT_NAME)}",
        f"version = {_quote(release_version())}",
        f"description = {_quote(_PROJECT_DESCRIPTION)}",
        'requires-python = ">=3.11"',
        f"dependencies = [{_quote(requirement)}]",
        "",
    ]
    return "\n".join(lines)


def write_manifest(path: Path | None = None) -> Path:
    """Write the manifest and return the path."""
    target = MANIFEST_PATH if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_manifest(), encoding="utf-8")
    return target


def write_plugin_project(path: Path | None = None) -> Path:
    """Write the directory ``pyproject.toml`` and return the path."""
    target = PROJECT_PATH if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_plugin_project(), encoding="utf-8")
    return target
