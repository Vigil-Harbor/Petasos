"""Whether protection is on, and the doctor's checks for the same home.

The doctor report is the computation. The summary fields are read from it,
so the tab and ``petasos doctor --json`` cannot disagree about scanners,
suggestions, or whether the settings resolved. The plugin is not started
again: Hermes's validator would import it in a subprocess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from petasos.hermes.dashboard.errors import envelope
from petasos.hermes.doctor import examine, report_payload

if TYPE_CHECKING:
    from petasos.hermes.dashboard.scope import HomeState
    from petasos.scanners.registry import ScannerSpec

STATUS_VERSION = 2


def status(
    state: HomeState,
    *,
    registry: tuple[ScannerSpec, ...] | None = None,
    home_label: str = "",
) -> dict[str, Any]:
    """Protection, the two switches, and the doctor report for ``state``."""
    import petasos

    report = examine(
        state.home,
        home_reason="the home Hermes is using",
        probe_plugin=False,
        registry=registry,
    )
    detail = report.detail
    settings_error = detail.get("settings_error")
    readable = detail.get("readable") is True
    hermes_on = detail.get("hermes_enabled")
    hermes_flag = hermes_on if isinstance(hermes_on, bool) or hermes_on is None else None
    petasos_raw = detail.get("petasos_enabled")
    petasos_flag = petasos_raw if isinstance(petasos_raw, bool) or petasos_raw is None else None
    valid = settings_error is None and readable
    environment_off = any(
        check.id == "hermes_environment" and check.status == "fail" for check in report.checks
    )
    armed = hermes_flag is True and petasos_flag is True and valid and not environment_off
    scanners = detail.get("scanners")
    if not isinstance(scanners, list):
        scanners = []
    role = detail.get("role")
    level = detail.get("level")
    secrets = detail.get("secrets")
    if not isinstance(secrets, dict):
        secrets = {"session_secret": "unset", "hash_key": "unset"}
    body = envelope(
        protection="on" if armed else "off",
        switches={
            "hermes": {"on": hermes_flag, "detail": _hermes_detail(detail)},
            "petasos": {"on": petasos_flag, "detail": _petasos_detail(petasos_flag, readable)},
        },
        settings={
            "valid": valid,
            "error": settings_error if isinstance(settings_error, dict) else None,
        },
        scanners=scanners,
        recommendations=list(report.suggestions),
        role=role if isinstance(role, str) else None,
        level=level if isinstance(level, str) else None,
        secrets=dict(secrets),
        home=home_label,
        petasos_version=petasos.__version__,
        doctor=report_payload(report),
    )
    body["version"] = STATUS_VERSION
    return body


def _hermes_detail(detail: object) -> str:
    if not isinstance(detail, dict):
        return "The settings file could not be read, so the plugin switch is unknown."
    if detail.get("readable") is not True:
        return "The settings file could not be read, so the plugin switch is unknown."
    if detail.get("hermes_disabled") is True:
        return "Petasos is on Hermes's disabled list, so Hermes will not load it."
    if detail.get("hermes_enabled") is True:
        return "Hermes is loading Petasos."
    return "Petasos is not in Hermes's enabled plugins."


def _petasos_detail(flag: bool | None, readable: bool) -> str:
    if not readable or flag is None:
        return "Petasos's own switch could not be read."
    if flag:
        return "Petasos enforcement is on."
    return "Petasos is paused. Tool calls are allowed through, and the pause is recorded."
