"""Whether the environment Hermes runs can import this Petasos.

The check asks that environment's Python. It does not trust the interpreter
that happens to be running the doctor.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from petasos.hermes.dependencies import petasos_requirement
from petasos.hermes.doctor_model import Check
from petasos.hermes.doctor_support import install_command
from petasos.hermes.environment import probe_petasos, runtime_python
from petasos.hermes.settings import PLUGIN_ID
from petasos.hermes.wheel import wheel_source

if TYPE_CHECKING:
    from pathlib import Path

_OPS = ("==", "!=", ">=", "<=", ">", "<")


def environment_check(home: Path, *, plugin_enabled: bool) -> Check:
    """Whether a new Hermes process for ``home`` can import a usable Petasos.

    No committed environment is reported and does not change the verdict: Hermes
    has not chosen an environment yet. A committed environment that cannot
    import a compatible Petasos is a failure, and the next step is one install
    command.
    """
    if not plugin_enabled:
        return Check(
            id="hermes_environment",
            status="info",
            summary=(
                "The environment Hermes runs was not the reason protection is off. "
                "The plugin is not turned on."
            ),
        )
    runtime = runtime_python(home)
    if runtime is None:
        return Check(
            id="hermes_environment",
            status="info",
            summary=(
                "Hermes has not committed an environment for this profile. "
                "A new Hermes process uses the Python it was started with."
            ),
        )
    probe = probe_petasos(runtime.python)
    project = home / "plugins" / PLUGIN_ID / "pyproject.toml"
    if not probe.ok:
        return Check(
            id="hermes_environment",
            status="fail",
            summary=(
                "Petasos is not in the environment a new Hermes process uses, "
                "so that process will not check tool calls."
            ),
            meaning=_meaning(probe.error, runtime.note),
            next_step=install_command(home),
        )
    if not _compatible(probe.version, project):
        return Check(
            id="hermes_environment",
            status="fail",
            summary=(
                f"The environment Hermes runs has Petasos {probe.version}, "
                "which this plugin cannot use."
            ),
            meaning=_meaning(
                "A new Hermes process would load that copy, not this one.",
                runtime.note,
            ),
            next_step=install_command(home),
        )
    source = wheel_source(project)
    if source is not None and probe.matches_wheel(source) is False:
        return Check(
            id="hermes_environment",
            status="warn",
            summary=(
                "New Hermes processes run an older build of Petasos "
                "than the plugin directory holds."
            ),
            meaning=_meaning("The older build still protects tool calls.", runtime.note),
            next_step=install_command(home),
        )
    meaning = runtime.note
    return Check(
        id="hermes_environment",
        status="ok",
        summary=(f"Petasos {probe.version} is in the environment a new Hermes process uses."),
        meaning=meaning,
    )


def _meaning(detail: str, note: str) -> str:
    parts = [part for part in (detail.strip(), note.strip()) if part]
    return " ".join(parts)


def _compatible(version: str, project: Path) -> bool:
    import petasos

    requirement = petasos_requirement(project) if project.is_file() else None
    specifier = requirement[1] if requirement is not None else f"=={petasos.__version__}"
    if specifier.strip() == "":
        specifier = f"=={petasos.__version__}"
    return _satisfies(version, specifier)


def _satisfies(version: str, specifier: str) -> bool:
    have = _numbers(version)
    if have is None:
        return False
    for part in specifier.split(","):
        text = part.strip()
        if text == "":
            continue
        op = next((item for item in _OPS if text.startswith(item)), "")
        if op == "":
            return False
        need = _numbers(text[len(op) :])
        if need is None or not _compare(have, op, need):
            return False
    return True


def _numbers(text: str) -> tuple[int, ...] | None:
    match = re.search(r"(\d+(?:\.\d+)*)", text)
    if match is None:
        return None
    return tuple(int(piece) for piece in match.group(1).split("."))


def _compare(have: tuple[int, ...], op: str, need: tuple[int, ...]) -> bool:
    width = max(len(have), len(need))
    left = have + (0,) * (width - len(have))
    right = need + (0,) * (width - len(need))
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left < right
