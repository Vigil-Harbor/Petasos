"""Say whether Petasos is protecting one Hermes profile.

The report is read-only. A missing Hermes install, or a missing YAML reader,
is a line in the report. The checks that do not need them still run.

The checks and the sentences they print stay in this module so a sentence
cannot drift from the fact it reports.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import petasos
from petasos.config.layers import LEVELS, ROLES, Resolved, resolve
from petasos.config.schema import ConfigError, leaves, to_mapping
from petasos.config.sections import PetasosConfig
from petasos.hermes.manifest import MIN_HERMES, render_manifest
from petasos.hermes.plugin import protected_paths
from petasos.hermes.settings import HASH_ENV, PLUGIN_ID, SESSION_ENV, read_profile_env
from petasos.scanners.registry import BuildContext, ScannerStatus, compose, recommendations

if TYPE_CHECKING:
    from pathlib import Path

Status = Literal["ok", "warn", "fail", "info"]
EXIT_PROTECTED = 0
EXIT_WARNINGS = 1
EXIT_NOT_PROTECTED = 2

_INIT_IMPORT = "from petasos.hermes.plugin import register"
_FORBIDDEN_INIT = (
    "MemoryProvider",
    "CronScheduler",
    "ComputerUseProvider",
    "register_provider",
)
_LEVEL_PLAIN = {
    "relaxed": (
        "Checks are looser than usual. If an extra check breaks, "
        "that text is blocked and Petasos keeps going."
    ),
    "balanced": (
        "Checks are at the usual strictness. If an extra check breaks, "
        "that text is blocked and Petasos keeps going."
    ),
    "strict": (
        "Checks are strict. If an extra check breaks, the text is blocked and "
        "Petasos stops. Personal information a check reports is hidden."
    ),
}
_FAIL_PLAIN = {
    "open": "if an extra check breaks, the text is let through",
    "degraded": "if an extra check breaks, that text is blocked and Petasos keeps going",
    "closed": "if an extra check breaks, the text is blocked and Petasos stops",
}
_POSTURE_PLAIN = {
    "block": "dangerous tool calls are blocked",
    "approve": "dangerous tool calls wait for a person to confirm them",
}
_SCANNER_JOB = {
    "presidio": "personal information",
    "prompt_guard": "hidden instructions, with the PromptGuard model",
    "semgrep": "risky code",
}
_SOURCE_PLAIN = {
    "role": "the job",
    "level": "the strictness",
    "override": "a custom setting",
    "default": "the usual setting",
}
_MARK = {"ok": "[ok]", "warn": "[~~]", "fail": "[!!]", "info": "[??]"}
_COLOUR = {"ok": "32", "warn": "33", "fail": "31", "info": "36"}
_ENV_PATTERN = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


@dataclass(frozen=True, slots=True)
class Check:
    """One doctor line.

    ``status`` is ``ok``, ``warn``, ``fail``, or ``info``. ``info`` does not
    change the verdict. ``meaning`` says what the line implies. ``next_step``
    is the command or action that addresses it, and is empty when none is due.
    """

    id: str
    status: Status
    summary: str
    meaning: str = ""
    next_step: str = ""


@dataclass(frozen=True, slots=True)
class HermesView:
    """What this Python can see of Hermes. ``version`` is None when unknown."""

    status: Status
    summary: str
    meaning: str = ""
    next_step: str = ""
    version: str | None = None


@dataclass(frozen=True, slots=True)
class Report:
    """The doctor result for one profile directory.

    ``verdict`` is ``protected``, ``protected_with_warnings``, or
    ``not_protected``. ``exit_code`` is 0, 1, or 2 in that order.
    """

    home: Path
    home_reason: str
    checks: tuple[Check, ...]
    suggestions: tuple[str, ...]
    protected_paths: tuple[str, ...]
    detail: Mapping[str, object]

    @property
    def verdict(self) -> str:
        """``protected``, ``protected_with_warnings``, or ``not_protected``."""
        if any(check.status == "fail" for check in self.checks):
            return "not_protected"
        if any(check.status == "warn" for check in self.checks):
            return "protected_with_warnings"
        return "protected"

    @property
    def exit_code(self) -> int:
        """0 protected, 1 warnings, 2 not protected."""
        if self.verdict == "protected":
            return EXIT_PROTECTED
        if self.verdict == "protected_with_warnings":
            return EXIT_WARNINGS
        return EXIT_NOT_PROTECTED


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
                "Install Petasos into the same Python Hermes uses, then run "
                f"petasos doctor with that Python. This one is {sys.executable}."
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
    if not _version_ok(version, MIN_HERMES):
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
            next_step=(
                "Run petasos doctor with the same Python Hermes uses to confirm the plugin loads."
            ),
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


def examine(home: Path, *, home_reason: str) -> Report:
    """Read ``home`` and return the doctor report. Nothing is written."""
    with _use_home(home):
        return _examine(home, home_reason=home_reason)


def render_text(report: Report, *, verbose: bool, color: bool) -> str:
    """The report a person reads. Colour is applied only to the marks."""
    lines = [_headline(report), f"Home: {report.home} ({report.home_reason})", ""]
    for check in report.checks:
        lines.append(f"{_paint(_MARK[check.status], check.status, color=color)}  {check.summary}")
        if check.id == "guardrail":
            lines.append(f"      {check.meaning}")
            if report.protected_paths:
                lines.append("      Paths protected today:")
                for path in report.protected_paths:
                    lines.append(f"      - {path}")
            else:
                lines.append("      No protected paths could be listed.")
            continue
        if check.meaning:
            for extra in check.meaning.splitlines():
                lines.append(f"      {extra}")
    if report.suggestions:
        lines.append("")
        lines.append("Suggestions")
        for suggestion in report.suggestions:
            lines.append(f"- {suggestion}")
    problems = [
        check for check in report.checks if check.status in {"warn", "fail"} and check.next_step
    ]
    if problems:
        lines.append("")
        lines.append("What to do")
        for check in problems:
            lines.append(f"- {check.summary}")
            if check.meaning:
                lines.append(f"  {check.meaning}")
            lines.append(f"  Next: {check.next_step}")
    if verbose:
        lines.append("")
        lines.extend(_verbose_lines(report))
    return "\n".join(lines) + "\n"


def render_json(report: Report) -> str:
    """The same report as a JSON object, including the verbose detail."""
    payload = {
        "verdict": report.verdict,
        "exit_code": report.exit_code,
        "summary": _headline(report),
        "home": str(report.home),
        "home_reason": report.home_reason,
        "checks": [
            {
                "id": check.id,
                "status": check.status,
                "summary": check.summary,
                "meaning": check.meaning,
                "next_step": check.next_step,
            }
            for check in report.checks
        ],
        "suggestions": list(report.suggestions),
        "protected_paths": list(report.protected_paths),
        "detail": report.detail,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _examine(home: Path, *, home_reason: str) -> Report:
    document, read_problem = _read_config(home / "config.yaml")
    hermes = hermes_view()
    checks: list[Check] = [
        _petasos_check(),
        Check(
            id="hermes",
            status=hermes.status,
            summary=hermes.summary,
            meaning=hermes.meaning,
            next_step=hermes.next_step,
        ),
    ]
    plugin_dir = home / "plugins" / PLUGIN_ID
    checks.append(_files_check(plugin_dir, home))
    if plugin_dir.is_dir():
        checks.append(_manifest_check(plugin_dir, home))
    else:
        checks.append(
            Check(
                id="plugin_manifest",
                status="info",
                summary="The plugin description was not checked. There is no plugin directory.",
            )
        )
    checks.append(_enabled_check(document, home))
    if plugin_dir.is_dir() and (plugin_dir / "__init__.py").is_file():
        checks.append(plugin_load_view(plugin_dir))
    else:
        checks.append(
            Check(
                id="plugin_load",
                status="info",
                summary="The plugin was not loaded, because its files are not in place.",
            )
        )
    resolved, settings_check, legacy = _settings_check(document, read_problem, home)
    checks.append(settings_check)
    checks.extend(_secret_checks(home, resolved))
    scanner_checks, suggestions, scanner_detail = _scanner_checks(resolved)
    checks.extend(scanner_checks)
    hermes_available = hermes.version is not None or hermes.status == "ok"
    checks.append(_approval_check(resolved, hermes_available=hermes_available))
    paths = _paths()
    checks.append(_guardrail_check())
    detail = _detail(
        home,
        hermes_version=hermes.version,
        resolved=resolved,
        legacy=legacy,
        read_problem=read_problem,
        scanners=scanner_detail,
    )
    return Report(
        home=home,
        home_reason=home_reason,
        checks=tuple(checks),
        suggestions=suggestions,
        protected_paths=paths,
        detail=detail,
    )


def _petasos_check() -> Check:
    version = petasos.__version__
    python = sys.version.split()[0]
    return Check(
        id="petasos",
        status="ok",
        summary=f"Petasos {version}, running under Python {python}.",
    )


def _files_check(plugin_dir: Path, home: Path) -> Check:
    if not plugin_dir.is_dir():
        return Check(
            id="plugin_files",
            status="fail",
            summary="The Petasos plugin is not installed for this profile.",
            meaning=(
                "Hermes only runs a plugin that has a directory here. "
                "Without it, tool calls are not checked."
            ),
            next_step=_install_command(home),
        )
    init = plugin_dir / "__init__.py"
    project = plugin_dir / "pyproject.toml"
    if not init.is_file():
        return Check(
            id="plugin_files",
            status="fail",
            summary="The plugin directory has no Python file, so Hermes cannot load it.",
            next_step=_install_command(home),
        )
    try:
        text = init.read_text(encoding="utf-8")
    except OSError as exc:
        return Check(
            id="plugin_files",
            status="fail",
            summary="The plugin's Python file could not be read.",
            meaning=str(exc),
            next_step=_install_command(home),
        )
    if _INIT_IMPORT not in text:
        return Check(
            id="plugin_files",
            status="fail",
            summary="The plugin directory is not Petasos's.",
            meaning="Hermes would load whatever is there instead of Petasos.",
            next_step=f"{_install_command(home)} --force",
        )
    forbidden = [word for word in _FORBIDDEN_INIT if word in text]
    if forbidden:
        return Check(
            id="plugin_files",
            status="fail",
            summary="The plugin's Python file would make Hermes skip it.",
            meaning="It contains " + ", ".join(forbidden) + ".",
            next_step=_install_command(home),
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
            next_step=_install_command(home),
        )
    return Check(
        id="plugin_files",
        status="ok",
        summary="The plugin files are in place.",
    )


def _manifest_check(plugin_dir: Path, home: Path) -> Check:
    path = plugin_dir / "plugin.yaml"
    if not path.is_file():
        return Check(
            id="plugin_manifest",
            status="fail",
            summary="The plugin description file is missing.",
            meaning="Hermes reads plugin.yaml for the plugin's name and the checks it provides.",
            next_step=_install_command(home),
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return Check(
            id="plugin_manifest",
            status="fail",
            summary="The plugin description file could not be read.",
            meaning=str(exc),
            next_step=_install_command(home),
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
            next_step=_install_command(home),
        )
    return Check(
        id="plugin_manifest",
        status="warn",
        summary="The plugin description does not match this version of Petasos.",
        meaning=(
            "The installed copy and this Petasos disagree. "
            "Enforcement follows the installed copy, which may be older or edited."
        ),
        next_step=_install_command(home),
    )


def _enabled_check(document: object, home: Path) -> Check:
    enabled, disabled = _plugin_lists(document)
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
            next_step=_install_command(home),
        )
    return Check(
        id="plugin_enabled",
        status="ok",
        summary="Hermes is set to run the Petasos plugin.",
    )


def _settings_check(
    document: object,
    read_problem: str | None,
    home: Path,
) -> tuple[Resolved | None, Check, bool]:
    if read_problem == "no-reader":
        return (
            None,
            Check(
                id="settings",
                status="fail",
                summary="The config file could not be read.",
                meaning=(
                    "This Python has no YAML reader. Hermes's Python has one. "
                    "Settings were not checked."
                ),
                next_step="Run petasos doctor with the same Python Hermes uses.",
            ),
            False,
        )
    if read_problem == "broken":
        return (
            None,
            Check(
                id="settings",
                status="fail",
                summary="The config file is damaged, so the settings could not be read.",
                meaning="Petasos cannot trust a config file it cannot read.",
                next_step=f"Repair {home / 'config.yaml'} and run petasos doctor again.",
            ),
            False,
        )
    legacy = _legacy_present(document)
    raw = _settings_mapping(document)
    expansions = _expansions(raw)
    try:
        resolved = resolve(raw)
    except ConfigError as exc:
        meaning = str(exc)
        steps = [
            "Set role to general, coding, research, support, or admin, "
            "and level to relaxed, balanced, or strict."
        ]
        if legacy:
            meaning = "An old petasos: section is in the config and is not used. " + meaning
            steps.insert(0, _migrate_command(home))
        if expansions:
            listed = ", ".join(expansions)
            meaning += (
                f" A setting contains {listed}. Hermes replaces that with an "
                "environment value when it reads the file. Write the value itself."
            )
            steps.append("Replace the ${...} text with the value you actually want.")
        return (
            None,
            Check(
                id="settings",
                status="warn",
                summary="The settings were rejected, so Petasos falls back to its usual settings.",
                meaning=meaning,
                next_step=" Then ".join(steps),
            ),
            legacy,
        )
    lines: list[str] = []
    actions: list[str] = []
    status: Status = "ok"
    if resolved.settings.enabled:
        role = ROLES[resolved.settings.role]
        level = _LEVEL_PLAIN.get(
            resolved.settings.level,
            LEVELS[resolved.settings.level].description,
        )
        lines.append(role.description)
        lines.append(level)
    if not resolved.settings.enabled:
        status = "fail"
        lines.append("Tool calls are not checked until protection is turned on.")
        actions.append(
            "Turn protection on in Hermes's plugin settings. The switch is called enabled."
        )
    if legacy:
        if status != "fail":
            status = "warn"
        lines.append(
            "An old petasos: section is still in the config. Petasos does not read it. "
            "The settings in this report are the ones in use, not that section."
        )
        actions.append(_migrate_command(home))
    if expansions:
        if status != "fail":
            status = "warn"
        listed = ", ".join(expansions)
        lines.append(
            f"A setting contains {listed}. Hermes replaces that with an environment "
            "value when it reads the file. Petasos settings should be plain text."
        )
        actions.append("Replace the ${...} text with the value you actually want.")
    if resolved.settings.enabled:
        lines.extend(_extra_lines(resolved))
    return (
        resolved,
        Check(
            id="settings",
            status=status,
            summary=_settings_summary(resolved),
            meaning="\n".join(lines),
            next_step=" Then ".join(actions),
        ),
        legacy,
    )


def _secret_checks(home: Path, resolved: Resolved | None) -> tuple[Check, Check]:
    session_raw = read_profile_env(home, SESSION_ENV)
    hash_raw = read_profile_env(home, HASH_ENV)
    session = _session_check(session_raw)
    needed = resolved is not None and resolved.config.anonymization.mode == "hash"
    if hash_raw:
        hashed = Check(
            id="hash_key",
            status="ok",
            summary="The hash key is set. Its value is not shown.",
        )
    elif needed:
        hashed = Check(
            id="hash_key",
            status="warn",
            summary="Hashed hiding of personal information is on, and the hash key is not set.",
            meaning=(
                f"Set {HASH_ENV} in the profile's env file. "
                "The value is not stored in the config file."
            ),
            next_step=f"Add {HASH_ENV} to {home / '.env'} and run petasos doctor again.",
        )
    else:
        hashed = Check(
            id="hash_key",
            status="ok",
            summary="The hash key is not set. Nothing you have turned on asks for it.",
        )
    return session, hashed


def _session_check(raw: str | None) -> Check:
    if raw is None:
        return Check(
            id="session_secret",
            status="ok",
            summary=(
                "The session secret is not set. Session tokens are not tied to this profile."
            ),
        )
    try:
        import base64

        base64.b64decode(raw, validate=True)
    except Exception:
        return Check(
            id="session_secret",
            status="warn",
            summary="The session secret is set, but Petasos cannot read it.",
            meaning=f"{SESSION_ENV} has to be base64. The value is not shown.",
            next_step=f"Replace {SESSION_ENV} in the profile env file with a base64 value.",
        )
    return Check(
        id="session_secret",
        status="ok",
        summary="The session secret is set. Its value is not shown.",
    )


def _scanner_checks(
    resolved: Resolved | None,
) -> tuple[tuple[Check, ...], tuple[str, ...], tuple[dict[str, object], ...]]:
    if resolved is None:
        return (
            (
                Check(
                    id="scanners",
                    status="info",
                    summary="The checks were not listed, because the settings could not be used.",
                ),
            ),
            (),
            (),
        )
    try:
        composition = compose(resolved.config, BuildContext())
    except Exception as exc:
        return (
            (
                Check(
                    id="scanners",
                    status="fail",
                    summary="The checks could not be built.",
                    meaning=str(exc) or type(exc).__name__,
                    next_step="Run petasos doctor again after the message above is fixed.",
                ),
            ),
            (),
            (),
        )
    checks: list[Check] = [
        Check(
            id="scanner_builtin",
            status="ok",
            summary="The built-in text checks are running. They look for hidden instructions.",
        )
    ]
    detail: list[dict[str, object]] = []
    for status in composition.statuses:
        kind, summary, meaning, step = _scanner_line(status)
        checks.append(
            Check(
                id=f"scanner_{status.id}",
                status=kind,
                summary=summary,
                meaning=meaning,
                next_step=step,
            )
        )
        detail.append(
            {
                "id": status.id,
                "state": status.state,
                "reason": status.reason,
                "extra": status.extra,
            }
        )
    lines = recommendations(composition, resolved.settings.role)
    return tuple(checks), lines, tuple(detail)


def _scanner_line(status: ScannerStatus) -> tuple[Status, str, str, str]:
    job = _SCANNER_JOB.get(status.id, status.label)
    if status.state == "active":
        return "ok", f"{status.label} is running. It checks for {job}.", "", ""
    if status.state == "off":
        return "ok", f"{status.label} is turned off. It would check for {job}.", "", ""
    if status.state == "not_installed":
        return (
            "ok",
            f"{status.label} is not installed, so it is not part of the checks.",
            f"It would check for {job}. The built-in checks still run.",
            "",
        )
    reason = status.reason or "no reason was reported"
    return (
        "warn",
        f"{status.label} is installed but cannot be used.",
        reason,
        "Fix that check, or turn it off, then run petasos doctor again.",
    )


def _approval_check(resolved: Resolved | None, *, hermes_available: bool) -> Check:
    if resolved is None:
        return Check(
            id="approval",
            status="info",
            summary="Dangerous tool calls were not checked. The settings could not be used.",
        )
    posture = resolved.config.tools.dangerous_posture
    if posture != "approve":
        return Check(
            id="approval",
            status="ok",
            summary="Dangerous tool calls are blocked. Hermes is not asked to approve them.",
        )
    if not hermes_available:
        return Check(
            id="approval",
            status="warn",
            summary="Dangerous tool calls are handed to Hermes for a person to confirm.",
            meaning=(
                "This Python cannot see Hermes, so I cannot tell whether Hermes "
                "would ask, refuse, or allow the call without asking."
            ),
            next_step="Run petasos doctor with the same Python Hermes uses.",
        )
    from petasos.hermes.host import approval_grant

    grant = approval_grant()
    reasons: list[str] = []
    if grant.mode_off:
        reasons.append("approvals are turned off")
    if grant.yolo:
        reasons.append("confirmation is switched off for this process")
    if grant.context:
        reasons.append("this is a scheduled or unattended run that approves on its own")
    if reasons:
        because = _join(reasons)
        return Check(
            id="approval",
            status="warn",
            summary=(
                "You asked for a person to confirm dangerous tool calls. "
                f"Hermes would allow them without asking, because {because}."
            ),
            meaning="A person who expects to be asked will not be asked.",
            next_step=(
                "Turn Hermes approvals back on, and turn off unattended approval, "
                "or change the job so dangerous tool calls are blocked."
            ),
        )
    return Check(
        id="approval",
        status="ok",
        summary=(
            "Dangerous tool calls are handed to Hermes. "
            "Hermes would ask a person. If nobody is there to answer, Hermes refuses the call."
        ),
    )


def _guardrail_check() -> Check:
    return Check(
        id="guardrail",
        status="info",
        summary="Whether this agent can change its own safety settings is not reported yet.",
        meaning=(
            "A later version will say if a change needs a person's approval, "
            "is refused, or is locked by an administrator."
        ),
    )


def _settings_summary(resolved: Resolved) -> str:
    if not resolved.settings.enabled:
        return "Protection is off."
    return f"Job: {resolved.settings.role}. Strictness: {resolved.settings.level}."


def _extra_lines(resolved: Resolved) -> tuple[str, ...]:
    current = to_mapping(resolved.config)
    stock = to_mapping(PetasosConfig())
    help_text = {info.path: info.help for info in leaves(PetasosConfig)}
    lines: list[str] = []
    for path, source in resolved.origin.items():
        value = _at(current, path)
        usual = _at(stock, path)
        if source != "override" and value == usual:
            continue
        lines.append(_leaf_line(path, value, source, help_text.get(path, path), resolved))
    return tuple(lines)


def _leaf_line(
    path: str,
    value: object,
    source: str,
    help_text: str,
    resolved: Resolved,
) -> str:
    where = _where(source, resolved)
    if path == "tools.dangerous_posture" and isinstance(value, str):
        return f"{_POSTURE_PLAIN.get(value, value)}. This comes from {where}."
    if path == "fail_mode" and isinstance(value, str):
        return f"{_sentence(_FAIL_PLAIN.get(value, value))} This comes from {where}."
    if path == "rules.suppress" and isinstance(value, list):
        return f"{len(value)} built-in checks are quieted. This comes from {where}."
    shown = json.dumps(value, ensure_ascii=False, default=str)
    return f"{help_text} It is {shown}. This comes from {where}."


def _where(source: str, resolved: Resolved) -> str:
    if source == "role":
        return f"the {resolved.settings.role} job"
    if source == "level":
        return f"the {resolved.settings.level} strictness"
    if source == "override":
        return "a custom setting"
    return _SOURCE_PLAIN.get(source, source)


def _settings_mapping(document: object) -> dict[str, object]:
    settings = _plugin_settings(document)
    if settings is None:
        return {}
    chosen: dict[str, object] = {}
    for key in ("enabled", "role", "level", "overrides"):
        if key in settings:
            chosen[key] = settings[key]
    return chosen


def _plugin_settings(document: object) -> dict[str, object] | None:
    if not isinstance(document, dict):
        return None
    plugins = document.get("plugins")
    if not isinstance(plugins, dict):
        return None
    entries = plugins.get("entries")
    if not isinstance(entries, dict):
        return None
    owned = entries.get(PLUGIN_ID)
    if not isinstance(owned, dict):
        return None
    settings = owned.get("settings")
    if not isinstance(settings, dict):
        return None
    return {str(key): value for key, value in settings.items()}


def _plugin_lists(document: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
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


def _legacy_present(document: object) -> bool:
    if not isinstance(document, dict):
        return False
    section = document.get("petasos")
    return isinstance(section, dict) and len(section) > 0


def _expansions(settings: Mapping[str, object]) -> tuple[str, ...]:
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


def _read_config(path: Path) -> tuple[object, str | None]:
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
    if _reader_available():
        return None, "broken"
    return None, "no-reader"


def _reader_available() -> bool:
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


def _version_ok(found: str, spec: str) -> bool:
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


def _paths() -> tuple[str, ...]:
    try:
        return tuple(sorted(protected_paths()))
    except Exception:
        return ()


def _detail(
    home: Path,
    *,
    hermes_version: str | None,
    resolved: Resolved | None,
    legacy: bool,
    read_problem: str | None,
    scanners: tuple[dict[str, object], ...],
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    if resolved is not None:
        current = to_mapping(resolved.config)
        for path, source in resolved.origin.items():
            rows.append({"path": path, "value": _at(current, path), "origin": source})
    return {
        "petasos_version": petasos.__version__,
        "python": sys.version.split()[0],
        "python_path": sys.executable,
        "hermes_version": hermes_version,
        "minimum_hermes": MIN_HERMES,
        "plugin_dir": str(home / "plugins" / PLUGIN_ID),
        "config_path": str(home / "config.yaml"),
        "env_path": str(home / ".env"),
        "legacy_section": legacy,
        "config_read": read_problem or "ok",
        "enabled": None if resolved is None else resolved.settings.enabled,
        "role": None if resolved is None else resolved.settings.role,
        "level": None if resolved is None else resolved.settings.level,
        "resolved": rows,
        "scanners": list(scanners),
    }


def _at(document: object, path: str) -> object:
    node = document
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _headline(report: Report) -> str:
    if report.verdict == "protected":
        return "Protected. Petasos is checking tool calls for this agent."
    if report.verdict == "protected_with_warnings":
        return (
            "Protected, with warnings. Petasos is checking tool calls, "
            "and something below needs a look."
        )
    return "Not protected. Petasos is not checking tool calls for this agent."


def _verbose_lines(report: Report) -> list[str]:
    lines = ["Detail"]
    detail = report.detail
    for key in ("petasos_version", "python", "python_path", "hermes_version", "minimum_hermes"):
        lines.append(f"  {key}: {detail.get(key)}")
    for key in ("plugin_dir", "config_path", "env_path"):
        lines.append(f"  {key}: {detail.get(key)}")
    resolved = detail.get("resolved")
    if isinstance(resolved, list) and resolved:
        lines.append("  Resolved settings (path, value, where it came from):")
        for row in resolved:
            if not isinstance(row, dict):
                continue
            lines.append(
                "    "
                f"{row.get('path')} = {json.dumps(row.get('value'), default=str)} "
                f"({row.get('origin')})"
            )
    return lines


def _install_command(home: Path) -> str:
    return f"petasos hermes install --home {_quote(home)}"


def _migrate_command(home: Path) -> str:
    return f"petasos config migrate --home {_quote(home)}"


def _quote(path: Path) -> str:
    text = str(path)
    if any(character.isspace() for character in text):
        return "'" + text.replace("'", "'\\''") + "'"
    return text


def _paint(mark: str, status: Status, *, color: bool) -> str:
    if not color:
        return mark
    code = _COLOUR[status]
    return f"\033[{code}m{mark}\033[0m"


def _sentence(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:] + ("." if not text.endswith(".") else "")


def _join(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


@contextlib.contextmanager
def _use_home(home: Path) -> Iterator[None]:
    """Point process-wide Hermes lookups at ``home`` for one report."""
    previous = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(home)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = previous
