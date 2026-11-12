"""Doctor checks for the install: Hermes, the plugin files, and the tab."""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

import petasos
from petasos.hermes.doctor_model import Check, HermesView
from petasos.hermes.doctor_support import install_command, plugin_lists, version_ok
from petasos.hermes.manifest import MIN_HERMES, render_manifest
from petasos.hermes.settings import PLUGIN_ID

if TYPE_CHECKING:
    from pathlib import Path

_INIT_IMPORT = "from petasos.hermes.plugin import register"
_DASHBOARD_IMPORT = "from petasos.hermes.dashboard import build_router"
_FORBIDDEN_INIT = (
    "MemoryProvider",
    "CronScheduler",
    "ComputerUseProvider",
    "register_provider",
)
_GUIDANCE = "security-guidance"


def hermes_view() -> HermesView:
    """Whether this Python can import Hermes, and whether the version is new enough."""
    from petasos.hermes.host import load_module

    manifest = load_module("hermes_cli.plugins_manifest")
    if manifest is None:
        return HermesView(
            status="warn",
            summary="Hermes is not installed in this Python.",
            meaning=(
                "The checks that read the profile files still ran. "
                "Loading the plugin, and whether Hermes would ask a person "
                "before a dangerous tool call, were not checked."
            ),
            next_step=(
                "Run hermes petasos doctor, which uses Hermes's own Python. Hermes "
                "offers that command once the plugin is turned on. "
                f"This Python is {sys.executable}."
            ),
        )
    version = _hermes_version(manifest)
    if version is None:
        return HermesView(
            status="warn",
            summary="Hermes is installed, but it did not report a version.",
            meaning=f"This plugin asks for Hermes {MIN_HERMES}.",
            next_step="Upgrade Hermes to 0.23.1 or newer, then run petasos doctor again.",
        )
    if not version_ok(version, MIN_HERMES):
        return HermesView(
            status="fail",
            summary=f"Hermes {version} is older than this plugin can use.",
            meaning=f"This plugin asks for Hermes {MIN_HERMES}.",
            next_step="Upgrade Hermes to 0.23.1 or newer, then run petasos doctor again.",
            version=version,
        )
    return HermesView(
        status="ok",
        summary=f"Hermes {version} is new enough for this plugin.",
        version=version,
    )


def plugin_load_view(plugin_dir: Path) -> Check:
    """Ask Hermes to validate the plugin directory. Skipped when Hermes is absent."""
    from petasos.hermes.host import load_module

    module = load_module("hermes_cli.plugin_validate")
    validate = getattr(module, "validate_plugin_dir", None) if module is not None else None
    if not callable(validate):
        return Check(
            id="plugin_load",
            status="warn",
            summary="The plugin was not loaded, because Hermes is not in this Python.",
            meaning="The files were checked on disk. Hermes itself did not load them.",
            next_step="Run hermes petasos doctor to confirm the plugin loads.",
        )
    try:
        report = validate(plugin_dir)
    except Exception as exc:
        return Check(
            id="plugin_load",
            status="fail",
            summary="Hermes could not check the plugin.",
            meaning=str(exc) or type(exc).__name__,
            next_step="Fix the plugin directory, then run petasos doctor again.",
        )
    if bool(getattr(report, "ok", False)):
        return Check(
            id="plugin_load",
            status="ok",
            summary="Hermes accepted the plugin files.",
        )
    failures = getattr(report, "failures", ())
    if failures:
        detail = "; ".join(str(item) for item in failures)
    else:
        detail = "Hermes rejected the plugin."
    return Check(
        id="plugin_load",
        status="fail",
        summary="Hermes did not accept the plugin, so it will not check tool calls.",
        meaning=detail,
        next_step="Run petasos hermes install again so the plugin files match this version.",
    )


def skipped_plugin_load() -> Check:
    """The plugin-load line when the caller must not start the plugin.

    Hermes's validator imports the plugin in a subprocess. The dashboard
    skips that. The files on disk are still checked.
    """
    return Check(
        id="plugin_load",
        status="info",
        summary="The plugin was not started again to re-check it.",
        meaning=(
            "Starting it would load Petasos a second time. "
            "The files on disk are checked above. Hermes loads them when it runs the plugin."
        ),
    )


def petasos_check() -> Check:
    """The Petasos version and the Python running this command."""
    version = petasos.__version__
    python = sys.version.split()[0]
    return Check(
        id="petasos",
        status="ok",
        summary=f"Petasos {version}, running under Python {python}.",
    )


def files_check(plugin_dir: Path, home: Path) -> Check:
    """Whether the plugin directory is present and is Petasos's."""
    if not plugin_dir.is_dir():
        return Check(
            id="plugin_files",
            status="fail",
            summary="The Petasos plugin is not installed for this profile.",
            meaning=(
                "Hermes only runs a plugin that has a directory here. "
                "Without it, tool calls are not checked."
            ),
            next_step=install_command(home),
        )
    init = plugin_dir / "__init__.py"
    project = plugin_dir / "pyproject.toml"
    if not init.is_file():
        return Check(
            id="plugin_files",
            status="fail",
            summary="The plugin directory has no Python file, so Hermes cannot load it.",
            next_step=install_command(home),
        )
    try:
        text = init.read_text(encoding="utf-8")
    except OSError as exc:
        return Check(
            id="plugin_files",
            status="fail",
            summary="The plugin's Python file could not be read.",
            meaning=str(exc),
            next_step=install_command(home),
        )
    if _INIT_IMPORT not in text:
        return Check(
            id="plugin_files",
            status="fail",
            summary="The plugin directory is not Petasos's.",
            meaning="Hermes would load whatever is there instead of Petasos.",
            next_step=f"{install_command(home)} --force",
        )
    forbidden = [word for word in _FORBIDDEN_INIT if word in text]
    if forbidden:
        return Check(
            id="plugin_files",
            status="fail",
            summary="The plugin's Python file would make Hermes skip it.",
            meaning="It contains " + ", ".join(forbidden) + ".",
            next_step=install_command(home),
        )
    if not project.is_file():
        return Check(
            id="plugin_files",
            status="warn",
            summary="The plugin is missing the file that lists its Python package.",
            meaning=(
                "Hermes can still load it when Petasos is already installed. "
                "Hermes's own installer uses that file to install Petasos."
            ),
            next_step=install_command(home),
        )
    return Check(
        id="plugin_files",
        status="ok",
        summary="The plugin files are in place.",
    )


def manifest_check(plugin_dir: Path, home: Path) -> Check:
    """Whether ``plugin.yaml`` matches the manifest this version would write."""
    path = plugin_dir / "plugin.yaml"
    if not path.is_file():
        return Check(
            id="plugin_manifest",
            status="fail",
            summary="The plugin description file is missing.",
            meaning="Hermes reads plugin.yaml for the plugin's name and the checks it provides.",
            next_step=install_command(home),
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return Check(
            id="plugin_manifest",
            status="fail",
            summary="The plugin description file could not be read.",
            meaning=str(exc),
            next_step=install_command(home),
        )
    if text == render_manifest():
        return Check(
            id="plugin_manifest",
            status="ok",
            summary="The plugin description matches this version of Petasos.",
        )
    if not re.search(r"(?m)^name:\s*petasos\s*$", text) or "provides_hooks:" not in text:
        return Check(
            id="plugin_manifest",
            status="fail",
            summary="The plugin description is damaged, so Hermes may not load Petasos.",
            next_step=install_command(home),
        )
    return Check(
        id="plugin_manifest",
        status="warn",
        summary="The plugin description does not match this version of Petasos.",
        meaning=(
            "The installed copy and this Petasos disagree. "
            "Enforcement follows the installed copy, which may be older or edited."
        ),
        next_step=install_command(home),
    )


def absent_manifest() -> Check:
    """The manifest line when there is no plugin directory."""
    return Check(
        id="plugin_manifest",
        status="info",
        summary="The plugin description was not checked. There is no plugin directory.",
    )


def enabled_check(document: object, home: Path) -> Check:
    """Whether Hermes's enabled list includes Petasos."""
    enabled, disabled = plugin_lists(document)
    on = PLUGIN_ID in enabled
    off = PLUGIN_ID in disabled
    if off:
        return Check(
            id="plugin_enabled",
            status="fail",
            summary="Petasos is on Hermes's switched-off list.",
            meaning=(
                "A plugin on that list does not run, even when it is also on the switched-on list."
            ),
            next_step=f"Run hermes plugins enable {PLUGIN_ID}, then petasos doctor.",
        )
    if not on:
        return Check(
            id="plugin_enabled",
            status="fail",
            summary="Petasos is not turned on in Hermes.",
            meaning="Hermes skips a plugin that is not on its switched-on list, with no error.",
            next_step=install_command(home),
        )
    return Check(
        id="plugin_enabled",
        status="ok",
        summary="Hermes is set to run the Petasos plugin.",
    )


def dashboard_check(plugin_dir: Path, document: object, home: Path) -> Check:
    """Whether the Petasos tab should appear in Hermes's dashboard.

    Hermes lists a tab when the dashboard manifest is present, the plugin is
    enabled, and the plugin is not on the switched-off list. A hidden tab in
    the dashboard settings is a separate switch this check does not read.
    """
    enabled, disabled = plugin_lists(document)
    running = PLUGIN_ID in enabled and PLUGIN_ID not in disabled
    folder = plugin_dir / "dashboard"
    manifest = folder / "manifest.json"
    api = folder / "plugin_api.py"
    script = folder / "index.js"
    if not plugin_dir.is_dir():
        return Check(
            id="dashboard",
            status="info",
            summary="The Petasos tab will not appear. The plugin is not installed.",
        )
    missing = [
        name
        for name, path in (
            ("manifest.json", manifest),
            ("plugin_api.py", api),
            ("index.js", script),
        )
        if not path.is_file()
    ]
    if missing:
        listed = ", ".join(missing)
        return Check(
            id="dashboard",
            status="warn",
            summary="The Petasos tab will not appear in Hermes's dashboard.",
            meaning=f"The dashboard files are missing: {listed}.",
            next_step=install_command(home),
        )
    try:
        manifest_text = manifest.read_text(encoding="utf-8")
        api_text = api.read_text(encoding="utf-8")
        script_text = script.read_text(encoding="utf-8")
    except OSError as exc:
        return Check(
            id="dashboard",
            status="warn",
            summary="The Petasos tab will not appear. The dashboard files could not be read.",
            meaning=str(exc),
            next_step=install_command(home),
        )
    if not script_text.strip() or _DASHBOARD_IMPORT not in api_text:
        return Check(
            id="dashboard",
            status="warn",
            summary="The Petasos tab will not appear. The dashboard files are incomplete.",
            meaning="Hermes needs the page script and the API module that imports the router.",
            next_step=install_command(home),
        )
    from petasos.hermes.dashboard.manifest import render_dashboard_manifest

    if manifest_text != render_dashboard_manifest():
        return Check(
            id="dashboard",
            status="warn",
            summary="The Petasos tab may appear, but its description does not match this version.",
            meaning="Install this version again so the tab and the plugin agree.",
            next_step=install_command(home),
        )
    if not running:
        return Check(
            id="dashboard",
            status="info",
            summary="The Petasos tab will not appear until Hermes is set to run Petasos.",
            meaning="Hermes only lists a tab for a plugin it is set to run.",
        )
    return Check(
        id="dashboard",
        status="ok",
        summary="The Petasos tab should appear in Hermes's dashboard.",
    )


def rewriter_check(document: object) -> Check:
    """Warn when security-guidance would keep Petasos's tool-result notes out.

    Hermes keeps the first string returned from ``transform_tool_result``.
    Plugins with no dependency between them load in alphabetical order, so
    ``security-guidance`` runs before ``petasos``.
    """
    enabled, disabled = plugin_lists(document)
    both = PLUGIN_ID in enabled and _GUIDANCE in enabled
    blocked = PLUGIN_ID in disabled or _GUIDANCE in disabled
    if not both or blocked:
        return Check(
            id="result_notes",
            status="ok",
            summary="No other plugin is set to replace Petasos's notes on tool results.",
        )
    return Check(
        id="result_notes",
        status="warn",
        summary=(
            "Hermes's security-guidance plugin and Petasos both add a note to tool results. "
            "Hermes keeps only the first note, and security-guidance runs first, "
            "so Petasos's note is left out."
        ),
        meaning="Tool calls are still checked. Only the note added to a tool result is affected.",
        next_step=(
            "Run hermes plugins disable security-guidance if you want Petasos's notes. "
            "Leave security-guidance on if you want its notes instead."
        ),
    )


def _hermes_version(manifest: object) -> str | None:
    fn = getattr(manifest, "running_hermes_version", None)
    if not callable(fn):
        return None
    try:
        value = fn()
    except Exception:
        return None
    if not isinstance(value, str) or value.strip() == "":
        return None
    return value.strip()
