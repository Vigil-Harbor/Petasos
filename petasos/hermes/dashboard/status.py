"""Whether protection is on, and the doctor's checks for the same home.

The doctor report is the computation. The summary fields are read from it,
so the tab and ``petasos doctor --json`` cannot disagree about scanners,
suggestions, or whether the settings resolved. The plugin is not started
again: Hermes's validator would import it in a subprocess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from petasos.hermes.dashboard.errors import envelope
from petasos.hermes.dashboard.words import WHO_CAN_CHANGE
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
    armed = hermes_flag is True and petasos_flag is True and valid
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
        coverage=coverage(scanners, list(report.suggestions)),
        who_can_change=dict(WHO_CAN_CHANGE),
        record_signing=record_signing(secrets, home_label),
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


def record_signing(secrets: dict[str, Any], home_label: str) -> dict[str, Any]:
    """Whether activity records are signed, and how to start signing them.

    The steps name the profile's env file. No secret value is read or shown.
    """
    signed = secrets.get("session_secret") == "set"
    env_file = (home_label.rstrip("/") + "/.env") if home_label else ".env in the profile"
    return {
        "signed": signed,
        "env_file": env_file,
        "steps": []
        if signed
        else [
            "Make a random value: openssl rand -base64 32",
            f"Add a line to {env_file}: PETASOS_SESSION_SECRET=<that value>",
            "Restart Hermes (Restart Gateway in the sidebar).",
            "New records are signed from then on. Older records stay unsigned, and the "
            "check marks them as not matching.",
        ],
    }


def coverage(scanners: list[Any], suggestions: list[str]) -> dict[str, Any]:
    """Which checks are running, which are not, and which of those the doctor recommends.

    ``complete`` is true only when every check in the list is active. A missing
    check is ``recommended`` when a doctor suggestion names its package extra.
    The front end says what is on and what is not from this, not from a guess.
    """
    running: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for row in scanners:
        if not isinstance(row, dict):
            continue
        entry = {"id": row.get("id"), "label": row.get("label"), "state": row.get("state")}
        if row.get("state") == "active":
            running.append(entry)
            continue
        extra = row.get("extra")
        named = isinstance(extra, str) and any(f"petasos[{extra}]" in line for line in suggestions)
        entry["recommended"] = bool(named)
        entry["reason"] = row.get("reason")
        missing.append(entry)
    return {
        "complete": not missing and bool(running),
        "running": running,
        "missing": missing,
    }


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
