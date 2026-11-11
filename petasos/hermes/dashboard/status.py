"""Whether protection is on, and the doctor's checks for the same home.

The doctor report is the computation. The summary fields are read from it,
so the tab and ``petasos doctor --json`` cannot disagree about scanners,
suggestions, or whether the settings resolved. The plugin is not started
again: Hermes's validator would import it in a subprocess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from petasos.hermes.dashboard.errors import envelope
from petasos.hermes.dashboard.words import (
    ADD_CHECK_WHERE,
    BASIC_CHECKS_COVER,
    CAPABILITY_WORDS,
    CHECKS_NOTE,
    OPERATING_WORDS,
    PROTECTION_SCOPE,
    WHO_CAN_CHANGE,
    choices_note,
)
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
    loaded = hermes_flag is True and valid and not environment_off
    paused = petasos_flag is False
    scanners = [
        dict(row, operating=operating(row, loaded=loaded, paused=paused))
        if isinstance(row, dict)
        else row
        for row in scanners
    ]
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
        paused=loaded and paused,
        scope=PROTECTION_SCOPE,
        checks_note=CHECKS_NOTE,
        choices_note=choices_note(
            usable=valid,
            running=hermes_flag is True and not environment_off,
            paused=paused,
        ),
        scanners=scanners,
        coverage=coverage(scanners, list(report.suggestions), registry=registry),
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


def operating(row: dict[str, Any], *, loaded: bool, paused: bool) -> dict[str, str]:
    """Whether one check is checking the agent's actions now, as ``{code, label}``.

    This is the one value every view draws a check's state from. It is not
    whether the check is installed or turned on: a working check is
    ``paused`` while protection is paused, and ``stopped`` while Hermes is
    not running Petasos or the saved settings cannot be used. A check that is
    not installed, or turned off, says so whatever the switches are.
    """
    state = row.get("state")
    if state == "not_installed":
        code = "not_installed"
    elif state == "off":
        code = "off"
    elif not loaded:
        code = "stopped"
    elif paused:
        code = "paused"
    elif state == "active":
        code = "running"
    else:
        code = "failed"
    return {"code": code, "label": OPERATING_WORDS[code]}


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


def coverage(
    scanners: list[Any],
    suggestions: list[str],
    *,
    registry: tuple[ScannerSpec, ...] | None = None,
) -> dict[str, Any]:
    """Which checks are running, which are not, and which of those the doctor recommends.

    ``complete`` is true only when every check in the list is active. A missing
    check is ``recommended`` when a doctor suggestion names its package extra.
    ``covers`` says in plain words what each check looks for, from the
    capabilities the registry lists, so a person reads what is missing before
    the product's name. ``held`` is true for a check that is turned on and
    cannot run: the doctor counts it as failed, and tool calls wait.
    ``consequence`` is what happens to tool calls while a held check cannot
    run, computed by the doctor from the fail mode and the dangerous-action
    setting. ``name`` leads with what the check does and puts the product
    after it. ``command``, when set, is the one command that adds the check, and
    ``add_where`` says where to run it. The front end says what is on and what
    is not from this, not from a guess.
    """
    from petasos.scanners.registry import REGISTRY

    specs = {spec.id: spec for spec in (REGISTRY if registry is None else registry)}
    running: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for row in scanners:
        if not isinstance(row, dict):
            continue
        entry = {
            "id": row.get("id"),
            "label": row.get("label"),
            "name": _name(row),
            "state": row.get("state"),
            "operating": row.get("operating"),
            "covers": _covers(row.get("id"), specs),
        }
        if row.get("state") == "active":
            running.append(entry)
            continue
        extra = row.get("extra")
        named = isinstance(extra, str) and any(f"petasos[{extra}]" in line for line in suggestions)
        fix = row.get("fix")
        entry["recommended"] = bool(named)
        entry["held"] = row.get("state") == "unavailable"
        entry["consequence"] = row.get("consequence")
        entry["reason"] = row.get("reason")
        entry["command"] = (
            fix if isinstance(fix, str) and fix.startswith("petasos scanner add ") else None
        )
        missing.append(entry)
    return {
        "complete": not missing and bool(running),
        "running": running,
        "missing": missing,
        "add_where": ADD_CHECK_WHERE,
    }


def _name(row: dict[str, Any]) -> str:
    """A check named by what it does, then its product: "Personal details check (Presidio)"."""
    label = row.get("label")
    purpose = row.get("purpose")
    if not isinstance(purpose, str) or not purpose or purpose == label:
        return label if isinstance(label, str) else ""
    return f"{purpose} ({label})" if isinstance(label, str) and label else purpose


def _covers(scanner_id: object, specs: dict[str, ScannerSpec]) -> str:
    if scanner_id == "syntactic":
        return BASIC_CHECKS_COVER
    spec = specs.get(scanner_id) if isinstance(scanner_id, str) else None
    if spec is None:
        return ""
    words = [CAPABILITY_WORDS[name] for name in sorted(spec.detects) if name in CAPABILITY_WORDS]
    return ", ".join(words)


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
