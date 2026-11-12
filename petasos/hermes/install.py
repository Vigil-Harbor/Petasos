"""Put the Petasos plugin in place for one Hermes profile.

The development route writes the plugin files and the dashboard tab from
this install, and turns the plugin on through Hermes. The released route
prints Hermes's own install command, and runs it only when asked. Neither
route writes ``config.yaml`` itself.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import petasos
from petasos.hermes.dashboard.manifest import DASHBOARD_DIR, render_dashboard_manifest
from petasos.hermes.doctor import Report, examine, render_text
from petasos.hermes.doctor_support import use_home
from petasos.hermes.environment import probe_petasos, republish, runtime_python
from petasos.hermes.manifest import render_manifest
from petasos.hermes.settings import PLUGIN_ID
from petasos.hermes.wheel import place_wheel, wheel_filename

if TYPE_CHECKING:
    from pathlib import Path

RELEASED_SPEC = "https://github.com/Vigil-Harbor/Petasos.git#hermes-plugin/petasos"
RELEASED_COMMAND = f"hermes plugins install {RELEASED_SPEC} --enable --yes-deps"
_INIT_SOURCE = "from petasos.hermes.plugin import register\n"
_NAME_LINE = re.compile(r"(?m)^name:\s*(\S+)\s*$")


@dataclass(frozen=True, slots=True)
class InstallResult:
    """What an install did, plus the doctor report when one was run.

    ``exit_code`` is 0 when a dry run finished or the doctor verdict is
    protected. A refusal to overwrite, or a doctor verdict that is not
    protected, is 2. Warnings from the doctor are 1.
    """

    text: str
    exit_code: int
    report: Report | None = None


def install_plugin(
    home: Path,
    *,
    home_reason: str,
    dry_run: bool,
    force: bool,
    released: bool,
    run: bool,
    color: bool,
) -> InstallResult:
    """Install or refresh Petasos for ``home`` and return the text to print."""
    if released:
        return _released(home, home_reason=home_reason, dry_run=dry_run, run=run, color=color)
    return _development(
        home,
        home_reason=home_reason,
        dry_run=dry_run,
        force=force,
        color=color,
    )


def render_project(wheel_name: str | None = None) -> str:
    """The plugin ``pyproject.toml`` for a copy this Petasos wrote.

    The dependency is this version, taken from the wheel file next to the
    plugin. Hermes installs that file into the environment it runs. A bare
    name would let a package index supply a different build of the same
    version.
    """
    name = wheel_filename() if wheel_name is None else wheel_name
    version = petasos.__version__
    return (
        "[project]\n"
        'name = "petasos-hermes-plugin"\n'
        f'version = "{version}"\n'
        'description = "Hermes directory plugin. Behaviour lives in the petasos wheel."\n'
        'requires-python = ">=3.11"\n'
        f'dependencies = ["petasos=={version}"]\n'
        "\n"
        "[tool.uv]\n"
        "package = false\n"
        "\n"
        "[tool.uv.sources]\n"
        f'petasos = {{ path = "wheels/{name}" }}\n'
    )


def plugin_dir(home: Path) -> Path:
    """The directory Hermes loads for this profile."""
    return home / "plugins" / PLUGIN_ID


def _development(
    home: Path,
    *,
    home_reason: str,
    dry_run: bool,
    force: bool,
    color: bool,
) -> InstallResult:
    target = plugin_dir(home)
    owned, why = _owned(target)
    lines = [
        f"Petasos will set up protection for {home} ({home_reason}).",
        "",
        "This is the development install, for a copy of Petasos that is not the "
        "published package. It writes the plugin files and this copy's wheel, and "
        "Hermes installs that wheel into the environment a new Hermes process runs.",
        "For a published release, run: petasos hermes install --released",
        "",
        "It will write:",
        f"  {target / 'plugin.yaml'}",
        f"  {target / '__init__.py'}",
        f"  {target / 'pyproject.toml'}",
        f"  {target / 'wheels' / wheel_filename()}",
        *[f"  {target / 'dashboard' / name}" for name in dashboard_texts()],
        "It will turn the plugin on through Hermes.",
        "Running this again refreshes those files to this version of Petasos.",
        "A Hermes process that is already running keeps its old environment "
        "until it starts again.",
    ]
    if not owned and not force:
        lines.extend(
            [
                "",
                "Nothing was written.",
                why,
                f"Next: petasos hermes install --home {_quote(home)} --force",
            ]
        )
        text = "\n".join(lines) + "\n"
        report = examine(home, home_reason=home_reason)
        text += "\n" + render_text(report, verbose=False, color=color)
        return InstallResult(text=text, exit_code=2, report=report)
    if dry_run:
        lines.extend(["", "Dry run. Nothing was written."])
        text = "\n".join(lines) + "\n"
        report = examine(home, home_reason=home_reason)
        text += "\nCurrent check, before any change:\n\n"
        text += render_text(report, verbose=False, color=color)
        return InstallResult(text=text, exit_code=0, report=report)
    wheel, problem = place_wheel(target / "wheels")
    if wheel is None:
        lines.extend(["", problem, "Nothing was turned on."])
        text = "\n".join(lines) + "\n\n"
        report = examine(home, home_reason=home_reason)
        text += render_text(report, verbose=False, color=color)
        return InstallResult(text=text, exit_code=2, report=report)
    written = _write_tree(target, wheel_name=wheel.name)
    if written:
        lines.append("")
        lines.append("Wrote the plugin files.")
    else:
        lines.append("")
        lines.append("The plugin files already match this version of Petasos.")
    with use_home(home):
        enabled, enable_message = enable_plugin()
        lines.append(enable_message)
        if enabled and "already" in enable_message:
            runtime = runtime_python(home)
            broken = runtime is None or not probe_petasos(runtime.python).ok
            _ok, refresh = republish(repair=broken)
            lines.append(refresh)
    if not enabled:
        lines.append(
            "The files are in place. Hermes did not turn the plugin on, "
            "so tool calls are not checked yet. Hermes's own command turns it on "
            "and installs the wheel."
        )
        lines.append(f"Next: {_enable_command(home)}")
    text = "\n".join(lines) + "\n\n"
    report = examine(home, home_reason=home_reason)
    text += render_text(report, verbose=False, color=color)
    return InstallResult(text=text, exit_code=report.exit_code, report=report)


def _released(
    home: Path,
    *,
    home_reason: str,
    dry_run: bool,
    run: bool,
    color: bool,
) -> InstallResult:
    lines = [
        f"Profile: {home} ({home_reason}).",
        "",
        "This is the released install. Hermes clones the plugin directory and installs",
        "the published Petasos package from a package index into the environment",
        "a new Hermes process runs. It is not the development install.",
        "Hermes picks the new environment up the next time it starts.",
        "",
        RELEASED_COMMAND,
    ]
    if dry_run or not run:
        lines.extend(
            [
                "",
                "Nothing was run. Add --run to ask Hermes to run that command from this Python.",
            ]
        )
        text = "\n".join(lines) + "\n"
        return InstallResult(text=text, exit_code=0, report=None)
    ok, message = run_released_install()
    lines.extend(["", message])
    text = "\n".join(lines) + "\n\n"
    report = examine(home, home_reason=home_reason)
    text += render_text(report, verbose=False, color=color)
    code = report.exit_code if ok else 2
    return InstallResult(text=text, exit_code=code, report=report)


def enable_plugin() -> tuple[bool, str]:
    """Turn the plugin on through Hermes. The second value is the sentence to print.

    Hermes's own enable is used. This function does not write ``config.yaml``.
    """
    from petasos.hermes.host import load_module

    module = load_module("hermes_cli.plugins_cmd")
    enable = None
    if module is not None:
        enable = getattr(module, "dashboard_set_agent_plugin_enabled", None)
    if not callable(enable):
        return False, (
            "Hermes is not available in this Python, so the plugin was not turned on. "
            "This command does not edit Hermes's config file itself."
        )
    try:
        result = enable(PLUGIN_ID, enabled=True)
    except SystemExit as exc:
        return False, f"Hermes stopped while turning the plugin on (exit {exc.code})."
    except Exception as exc:
        return False, f"Hermes could not turn the plugin on: {exc}"
    if isinstance(result, dict) and result.get("ok") is True:
        if result.get("unchanged") is True:
            return True, "Hermes already had the plugin turned on."
        return True, "Hermes turned the plugin on."
    error = result.get("error") if isinstance(result, dict) else result
    return False, f"Hermes did not turn the plugin on: {error}"


def run_released_install() -> tuple[bool, str]:
    """Run Hermes's installer for the published plugin. Nothing is written here."""
    from petasos.hermes.host import load_module

    module = load_module("hermes_cli.plugins_cmd")
    command = getattr(module, "cmd_install", None) if module is not None else None
    if not callable(command):
        return False, (
            "Hermes is not available in this Python, so the installer was not run. "
            f"Run this in your terminal: {RELEASED_COMMAND}"
        )
    try:
        command(RELEASED_SPEC, enable=True, yes_deps=True)
    except SystemExit as exc:
        if exc.code in (0, None):
            return True, "Hermes finished the install."
        return False, f"Hermes's installer stopped (exit {exc.code})."
    except Exception as exc:
        return False, f"Hermes's installer failed: {exc}"
    return True, "Hermes finished the install."


def dashboard_texts() -> dict[str, str]:
    """The dashboard files for a copy this Petasos wrote.

    Every file in the plugin's dashboard directory is copied. The manifest is
    rendered for this version, so a tab script or a style sheet added beside
    it is included without being named here.
    """
    texts: dict[str, str] = {}
    for path in sorted(DASHBOARD_DIR.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name != "manifest.json":
            texts[path.name] = path.read_text(encoding="utf-8")
    texts["manifest.json"] = render_dashboard_manifest()
    return texts


def _write_tree(target: Path, *, wheel_name: str) -> bool:
    """Write the plugin files and the dashboard tab. Return True when a byte changed."""
    target.mkdir(parents=True, exist_ok=True)
    changed = _write_if_changed(target / "plugin.yaml", render_manifest())
    changed = _write_if_changed(target / "__init__.py", _INIT_SOURCE) or changed
    changed = _write_if_changed(target / "pyproject.toml", render_project(wheel_name)) or changed
    changed = _copy_dashboard(target / "dashboard") or changed
    return changed


def _copy_dashboard(dest: Path) -> bool:
    dest.mkdir(parents=True, exist_ok=True)
    changed = False
    for name, text in dashboard_texts().items():
        changed = _write_if_changed(dest / name, text) or changed
    return changed


def _write_if_changed(path: Path, text: str) -> bool:
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass
    path.write_text(text, encoding="utf-8")
    return True


def _owned(target: Path) -> tuple[bool, str]:
    """True when the directory is missing or is already Petasos's."""
    if not target.exists():
        return True, ""
    if not target.is_dir():
        return False, f"{target} exists and is not a directory. Nothing was replaced."
    manifest = target / "plugin.yaml"
    if not manifest.exists() and not any(target.iterdir()):
        return True, ""
    if manifest.is_file():
        try:
            text = manifest.read_text(encoding="utf-8")
        except OSError as exc:
            return False, f"The plugin directory could not be read ({exc}). Nothing was replaced."
        match = _NAME_LINE.search(text)
        name = match.group(1) if match is not None else ""
        if name == PLUGIN_ID:
            return True, ""
        return False, (
            f"{target} belongs to {name or 'another plugin'}, not Petasos. Nothing was replaced."
        )
    return False, (
        f"{target} already has files, and none of them is a Petasos plugin description. "
        "Nothing was replaced."
    )


def _enable_command(home: Path) -> str:
    """Hermes's own enable for ``home``, as a person would type it."""
    if os.name == "nt":
        return f"hermes plugins enable {PLUGIN_ID}, with HERMES_HOME set to {home}"
    return f"HERMES_HOME={_quote(home)} hermes plugins enable {PLUGIN_ID}"


def _quote(path: Path) -> str:
    text = str(path)
    if any(character.isspace() for character in text):
        return "'" + text.replace("'", "'\\''") + "'"
    return text
