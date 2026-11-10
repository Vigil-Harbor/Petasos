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


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _choices(names: tuple[str, ...]) -> list[str]:
    return [f"      - {name}" for name in names]


def render_manifest() -> str:
    """The ``plugin.yaml`` text ``register`` and the schema agree on."""
    lines = [
        f"name: {PLUGIN_ID}",
        f"version: {_quote(petasos.__version__)}",
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


def write_manifest(path: Path | None = None) -> Path:
    """Write the manifest and return the path."""
    target = MANIFEST_PATH if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_manifest(), encoding="utf-8")
    return target
