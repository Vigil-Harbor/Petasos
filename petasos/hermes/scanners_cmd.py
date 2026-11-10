"""Add or remove one scanner's packages in the environment Hermes runs.

The command takes a scanner name. The registry knows which extra that name
uses. Hermes installs the extra because it is named in the plugin's
dependency list, which is how Hermes installs a plugin's Python packages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.hermes.dependencies import set_extra
from petasos.hermes.doctor_support import use_home
from petasos.hermes.environment import republish
from petasos.hermes.settings import PLUGIN_ID
from petasos.scanners.registry import REGISTRY, spec_for

if TYPE_CHECKING:
    from pathlib import Path

    from petasos.scanners.registry import ScannerSpec

_AFTER = {
    "prompt_guard": (
        "The packages are large, on the order of a gigabyte, and the install can take "
        "several minutes. The first time the check runs it downloads the model, about "
        "1.1 GB. That download needs a Hugging Face token, and the model terms have to "
        "be accepted once."
    ),
    "presidio": (
        "The packages are a few hundred megabytes. The English language model is about "
        "425 MB and is fetched the first time Presidio needs it, if it is not already "
        "on disk."
    ),
    "semgrep": (
        "The helper package is small. The Semgrep program itself is separate and is "
        "not installed by this command."
    ),
}
_RESTART = (
    "Restart Hermes so a running agent uses the new environment. "
    "A process that is already running keeps the old one until it starts again."
)


def scanner_names() -> str:
    """The scanner ids a person can pass, in registry order."""
    return ", ".join(spec.id for spec in REGISTRY if spec.extra is not None)


def change_scanner(home: Path, name: str, *, present: bool) -> tuple[str, int]:
    """Add or remove ``name`` and return the text to print and the exit status."""
    spec = spec_for(name)
    if spec is None or spec.extra is None:
        known = scanner_names()
        return (
            f"There is no scanner named {name.strip() or '(blank)'}.\nScanners: {known}.\n",
            2,
        )
    project = home / "plugins" / PLUGIN_ID / "pyproject.toml"
    if not project.is_file():
        return (
            "The Petasos plugin is not installed for this profile, so there is no "
            "dependency list to change.\n"
            f"Next: petasos hermes install --home {_quote(home)}\n",
            2,
        )
    try:
        edit = set_extra(project, spec.extra, label=spec.label, present=present)
    except ValueError as exc:
        return str(exc) + "\n", 2
    with use_home(home):
        ok, rebuilt = republish()
    lines = [
        edit.summary,
        rebuilt,
    ]
    if ok:
        lines.append(_follow(spec, present=present))
    else:
        lines.append(
            "The dependency list was updated. The environment Hermes runs was not, "
            "so a new Hermes process does not have this change yet."
        )
    return "\n".join(lines) + "\n", 0 if ok else 2


def _follow(spec: ScannerSpec, *, present: bool) -> str:
    if not present:
        return (
            f"{spec.label} will be left out of the checks once Hermes starts again. "
            "A package Hermes itself needs is kept. " + _RESTART
        )
    extra = _AFTER.get(spec.id, "")
    body = f"{spec.label} checks for {_job(spec.id)}. " + _RESTART
    if extra:
        body += " " + extra
    return body


def _job(scanner_id: str) -> str:
    jobs = {
        "presidio": "personal information",
        "prompt_guard": "hidden instructions, with a model",
        "semgrep": "risky code",
    }
    return jobs.get(scanner_id, "what that scanner looks for")


def _quote(path: Path) -> str:
    text = str(path)
    if any(character.isspace() for character in text):
        return "'" + text.replace("'", "'\\''") + "'"
    return text
