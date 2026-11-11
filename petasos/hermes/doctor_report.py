"""Build one doctor report. Rendering is a separate step."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import petasos
from petasos.config.schema import to_mapping
from petasos.hermes.doctor_advice import (
    approval_check,
    current_paths,
    guardrail_check,
    scanner_report,
)
from petasos.hermes.doctor_environment import environment_check
from petasos.hermes.doctor_install import (
    absent_manifest,
    dashboard_check,
    enabled_check,
    files_check,
    hermes_view,
    manifest_check,
    petasos_check,
    plugin_load_view,
    rewriter_check,
    skipped_plugin_load,
)
from petasos.hermes.doctor_model import Check, HermesView, Report
from petasos.hermes.doctor_settings import secret_checks, settings_check
from petasos.hermes.doctor_support import (
    at_path,
    paths_summary,
    plugin_lists,
    read_config,
    use_home,
)
from petasos.hermes.manifest import MIN_HERMES
from petasos.hermes.settings import PLUGIN_ID
from petasos.scanners.registry import REGISTRY, ScannerSpec

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from petasos.config.layers import Resolved


def build_report(
    home: Path,
    *,
    home_reason: str,
    hermes_view_fn: Callable[[], HermesView] | None = None,
    plugin_load_fn: Callable[[Path], Check] | None = None,
    probe_plugin: bool = True,
    registry: tuple[ScannerSpec, ...] | None = None,
) -> Report:
    """Read ``home`` and return the report. Nothing is written.

    ``probe_plugin`` asks Hermes to validate the plugin directory. The
    dashboard passes false so a status poll does not start the plugin.
    The view callables default to this package's checks. Callers that need
    a test double pass their own.
    """
    view = hermes_view if hermes_view_fn is None else hermes_view_fn
    if not probe_plugin:
        load: Callable[[Path], Check] | None = None
    elif plugin_load_fn is None:
        load = plugin_load_view
    else:
        load = plugin_load_fn
    specs = REGISTRY if registry is None else registry
    with use_home(home):
        return _build(
            home,
            home_reason=home_reason,
            hermes_view_fn=view,
            plugin_load_fn=load,
            registry=specs,
        )


def _build(
    home: Path,
    *,
    home_reason: str,
    hermes_view_fn: Callable[[], HermesView],
    plugin_load_fn: Callable[[Path], Check] | None,
    registry: tuple[ScannerSpec, ...],
) -> Report:
    document, read_problem = read_config(home / "config.yaml")
    hermes = hermes_view_fn()
    checks: list[Check] = [
        petasos_check(),
        Check(
            id="hermes",
            status=hermes.status,
            summary=hermes.summary,
            meaning=hermes.meaning,
            next_step=hermes.next_step,
        ),
    ]
    plugin_dir = home / "plugins" / PLUGIN_ID
    checks.append(files_check(plugin_dir, home))
    if plugin_dir.is_dir():
        checks.append(manifest_check(plugin_dir, home))
    else:
        checks.append(absent_manifest())
    checks.append(enabled_check(document, home))
    enabled_names, disabled_names = plugin_lists(document)
    plugin_on = PLUGIN_ID in enabled_names and PLUGIN_ID not in disabled_names
    checks.append(environment_check(home, plugin_enabled=plugin_on))
    checks.append(dashboard_check(plugin_dir, document, home))
    if plugin_dir.is_dir() and (plugin_dir / "__init__.py").is_file():
        if plugin_load_fn is None:
            checks.append(skipped_plugin_load())
        else:
            checks.append(plugin_load_fn(plugin_dir))
    else:
        checks.append(
            Check(
                id="plugin_load",
                status="info",
                summary="The plugin was not loaded, because its files are not in place.",
            )
        )
    resolved, settings_line, legacy, setting_facts = settings_check(document, read_problem, home)
    checks.append(settings_line)
    session, hashed, secrets = secret_checks(home, resolved)
    checks.extend((session, hashed))
    scanner_lines, suggestions, scanner_rows = scanner_report(resolved, registry=registry)
    checks.extend(scanner_lines)
    hermes_available = hermes.version is not None or hermes.status == "ok"
    checks.append(approval_check(resolved, hermes_available=hermes_available))
    checks.append(rewriter_check(document))
    paths = current_paths()
    if resolved is None:
        mode, minutes = "approve", 30
    else:
        mode = resolved.config.tools.self_change
        minutes = resolved.config.tools.self_change_minutes
    checks.append(guardrail_check(paths, mode=mode, minutes=minutes))
    detail = _detail(
        home,
        document=document,
        hermes_version=hermes.version,
        resolved=resolved,
        legacy=legacy,
        read_problem=read_problem,
        scanners=scanner_rows,
        setting_facts=setting_facts,
        secrets=secrets,
    )
    return Report(
        home=home,
        home_reason=home_reason,
        checks=tuple(checks),
        suggestions=suggestions,
        protected_paths=paths,
        paths_summary=paths_summary(paths),
        detail=detail,
    )


def _detail(
    home: Path,
    *,
    document: object,
    hermes_version: str | None,
    resolved: Resolved | None,
    legacy: bool,
    read_problem: str | None,
    scanners: tuple[dict[str, object], ...],
    setting_facts: dict[str, object],
    secrets: dict[str, str],
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    if resolved is not None:
        current = to_mapping(resolved.config)
        for path, source in resolved.origin.items():
            rows.append({"path": path, "value": at_path(current, path), "origin": source})
    enabled_names, disabled_names = plugin_lists(document)
    readable = read_problem is None
    if not readable:
        hermes_enabled: bool | None = None
        hermes_disabled = False
    else:
        hermes_disabled = PLUGIN_ID in disabled_names
        hermes_enabled = PLUGIN_ID in enabled_names and not hermes_disabled
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
        "role": setting_facts.get("role"),
        "level": setting_facts.get("level"),
        "readable": readable,
        "hermes_enabled": hermes_enabled,
        "hermes_disabled": hermes_disabled,
        "petasos_enabled": setting_facts.get("petasos_enabled"),
        "settings_error": setting_facts.get("settings_error"),
        "secrets": secrets,
        "resolved": rows,
        "scanners": list(scanners),
    }
