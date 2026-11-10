"""Shared reading and wording helpers for the doctor checks.

Nothing here decides a verdict. The checks call these and keep the sentences.
"""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_ENV_PATTERN = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


def sentence(text: str) -> str:
    """``text`` as a sentence: a capital letter and a closing stop."""
    if not text:
        return text
    body = text[0].upper() + text[1:]
    if body.endswith((".", "!", "?")):
        return body
    return body + "."


def join_reasons(parts: list[str]) -> str:
    """A list of reasons as one clause."""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def quote_path(path: Path) -> str:
    """A path safe to paste into a shell command."""
    text = str(path)
    if any(character.isspace() for character in text):
        return "'" + text.replace("'", "'\\''") + "'"
    return text


def install_command(home: Path) -> str:
    """The install command for ``home``."""
    return f"petasos hermes install --home {quote_path(home)}"


def migrate_command(home: Path) -> str:
    """The migrate command for ``home``."""
    return f"petasos config migrate --home {quote_path(home)}"


def at_path(document: object, path: str) -> object:
    """The value at a dotted path, or None when a step is missing."""
    node = document
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def plugin_settings(document: object, plugin_id: str) -> dict[str, object] | None:
    """The plugin's settings mapping, or None when the document has none."""
    if not isinstance(document, dict):
        return None
    plugins = document.get("plugins")
    if not isinstance(plugins, dict):
        return None
    entries = plugins.get("entries")
    if not isinstance(entries, dict):
        return None
    owned = entries.get(plugin_id)
    if not isinstance(owned, dict):
        return None
    settings = owned.get("settings")
    if not isinstance(settings, dict):
        return None
    return {str(key): value for key, value in settings.items()}


def settings_mapping(document: object, plugin_id: str) -> dict[str, object]:
    """The four settings keys that are actually stored."""
    settings = plugin_settings(document, plugin_id)
    if settings is None:
        return {}
    chosen: dict[str, object] = {}
    for key in ("enabled", "role", "level", "overrides"):
        if key in settings:
            chosen[key] = settings[key]
    return chosen


def plugin_lists(document: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(enabled names, disabled names)`` from a config document."""
    if not isinstance(document, dict):
        return (), ()
    plugins = document.get("plugins")
    if not isinstance(plugins, dict):
        return (), ()
    return _names(plugins.get("enabled")), _names(plugins.get("disabled"))


def _names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def legacy_present(document: object) -> bool:
    """True when a non-empty top-level ``petasos:`` section is still in the file."""
    if not isinstance(document, dict):
        return False
    section = document.get("petasos")
    return isinstance(section, dict) and len(section) > 0


def expansions(settings: Mapping[str, object]) -> tuple[str, ...]:
    """``${NAME}`` sequences Hermes would replace when it reads the file."""
    found: list[str] = []
    _walk_expansions(settings, found)
    return tuple(dict.fromkeys(found))


def _walk_expansions(value: object, found: list[str]) -> None:
    if isinstance(value, str):
        found.extend(_ENV_PATTERN.findall(value))
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _walk_expansions(item, found)
        return
    if isinstance(value, list):
        for item in value:
            _walk_expansions(item, found)


def read_config(path: Path) -> tuple[object, str | None]:
    """The config document and a problem code.

    The problem is None when the file is missing or readable, ``broken`` when
    it cannot be parsed, and ``no-reader`` when this Python has no YAML reader.
    """
    if not path.is_file():
        return None, None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, "broken"
    from petasos.hermes.host import load_mapping

    document = load_mapping(text)
    if isinstance(document, dict) or document is None:
        return document, None
    if reader_available():
        return None, "broken"
    return None, "no-reader"


def reader_available() -> bool:
    """True when this Python can parse a Hermes config file."""
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


def version_ok(found: str, spec: str) -> bool:
    """True when ``found`` satisfies a ``>=`` requirement."""
    requirement = spec.strip()
    if not requirement.startswith(">="):
        return False
    have = _version_tuple(found)
    need = _version_tuple(requirement[2:])
    if have is None or need is None:
        return False
    return have >= need


def _version_tuple(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or "0")


def paths_summary(paths: tuple[str, ...]) -> str:
    """The one line the default output uses for the protected-path list."""
    count = len(paths)
    if count == 0:
        return "Petasos could not list the places an agent could change to turn protection off."
    if count == 1:
        return "Petasos watches 1 place an agent could change to turn protection off."
    return f"Petasos watches {count} places an agent could change to turn protection off."


@contextlib.contextmanager
def use_home(home: Path) -> Iterator[None]:
    """Point Hermes lookups at ``home`` for one report.

    A context-local override is used when Hermes provides one, so a dashboard
    request does not change the process environment. Without that override the
    ``HERMES_HOME`` variable is set and restored.
    """
    token = _set_override(home)
    previous = os.environ.get("HERMES_HOME")
    changed = False
    if token is None:
        os.environ["HERMES_HOME"] = str(home)
        changed = True
    try:
        yield
    finally:
        if token is not None:
            _reset_override(token)
        if changed:
            if previous is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous


def _set_override(home: Path) -> object | None:
    try:
        import hermes_constants  # type: ignore[import-not-found]
    except Exception:
        return None
    setter = getattr(hermes_constants, "set_hermes_home_override", None)
    if not callable(setter):
        return None
    try:
        token: object = setter(home)
        return token
    except Exception:
        return None


def _reset_override(token: object) -> None:
    try:
        import hermes_constants
    except Exception:
        return
    reset = getattr(hermes_constants, "reset_hermes_home_override", None)
    if not callable(reset):
        return
    try:
        reset(token)
    except Exception:
        return
