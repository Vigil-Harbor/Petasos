"""Edit the petasos requirement in a plugin's dependency list.

Hermes installs that list into the environment it runs. The edit keeps the
version specifier and every other requirement, and only changes the extras
on the petasos requirement.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_DEPENDENCIES = re.compile(r"(?m)^dependencies\s*=\s*\[.*\]\s*$")
_NAME = "petasos"


@dataclass(frozen=True, slots=True)
class DependencyEdit:
    """What a change to the petasos requirement did.

    ``changed`` is false when the extras were already as requested.
    ``extras`` is the list after the edit. ``summary`` is the sentence to print.
    """

    changed: bool
    extras: tuple[str, ...]
    summary: str


def set_extra(project: Path, extra: str, *, label: str, present: bool) -> DependencyEdit:
    """Add or remove ``extra`` on the petasos requirement in ``project``.

    Raises ``ValueError`` when the file has no one-line dependency list, or
    that list does not name Petasos. The message is the sentence to print.
    """
    try:
        text = project.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"The plugin's dependency list could not be read ({exc}).") from exc
    matches = list(_DEPENDENCIES.finditer(text))
    if len(matches) != 1:
        raise ValueError(
            "The plugin's dependency list is not on one line, so it was left unchanged. "
            "Run petasos hermes install to write it again."
        )
    line = matches[0].group(0)
    specs = _specs(line)
    index = _petasos_index(specs)
    if index is None:
        raise ValueError(
            "The plugin's dependency list does not name Petasos, so nothing was added. "
            "Run petasos hermes install, then this command."
        )
    name, extras, specifier = _split(specs[index])
    wanted = list(extras)
    if present:
        if extra not in wanted:
            wanted.append(extra)
        summary = (
            f"{label} was added to the plugin's dependency list."
            if extra not in extras
            else f"{label} was already in the plugin's dependency list."
        )
    else:
        wanted = [item for item in wanted if item != extra]
        summary = (
            f"{label} was removed from the plugin's dependency list."
            if extra in extras
            else f"{label} was not in the plugin's dependency list."
        )
    specs[index] = _join(name, wanted, specifier)
    replacement = "dependencies = [" + ", ".join(json.dumps(item) for item in specs) + "]"
    updated = text[: matches[0].start()] + replacement + text[matches[0].end() :]
    if updated != text:
        project.write_text(updated, encoding="utf-8")
    return DependencyEdit(
        changed=updated != text,
        extras=tuple(wanted),
        summary=summary,
    )


def petasos_requirement(project: Path) -> tuple[tuple[str, ...], str] | None:
    """The extras and version specifier of the petasos requirement, if it is listed."""
    try:
        text = project.read_text(encoding="utf-8")
    except OSError:
        return None
    matches = list(_DEPENDENCIES.finditer(text))
    if len(matches) != 1:
        return None
    try:
        specs = _specs(matches[0].group(0))
    except ValueError:
        return None
    index = _petasos_index(specs)
    if index is None:
        return None
    _name, extras, specifier = _split(specs[index])
    return extras, specifier


def _specs(line: str) -> list[str]:
    start = line.index("[")
    end = line.rindex("]")
    try:
        value = json.loads(line[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(
            "The plugin's dependency list could not be read, so it was left unchanged."
        ) from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(
            "The plugin's dependency list could not be read, so it was left unchanged."
        )
    return list(value)


def _petasos_index(specs: list[str]) -> int | None:
    for index, spec in enumerate(specs):
        name, _extras, _specifier = _split(spec)
        if name.casefold() == _NAME:
            return index
    return None


def _split(spec: str) -> tuple[str, tuple[str, ...], str]:
    text = spec.strip()
    index = 0
    while index < len(text) and (text[index].isalnum() or text[index] in "._-"):
        index += 1
    name = text[:index]
    extras: tuple[str, ...] = ()
    if index < len(text) and text[index] == "[":
        end = text.index("]", index)
        extras = tuple(part.strip() for part in text[index + 1 : end].split(",") if part.strip())
        index = end + 1
    return name, extras, text[index:]


def _join(name: str, extras: list[str], specifier: str) -> str:
    bracket = "" if not extras else "[" + ",".join(extras) + "]"
    return f"{name}{bracket}{specifier}"
