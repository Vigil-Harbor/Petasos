"""Scanner, approval, and suggestion lines for the doctor.

Suggestions are written for a Hermes home. The registry's own wording stays
host-agnostic and is not shown here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.hermes import semgrep_host
from petasos.hermes.doctor_model import Check, Status
from petasos.hermes.doctor_support import join_reasons, paths_summary
from petasos.hermes.plugin import protected_paths
from petasos.scanners.registry import REGISTRY, BuildContext, compose, fix_for

if TYPE_CHECKING:
    from petasos.config.layers import Resolved
    from petasos.scanners.registry import Composition, ScannerSpec, ScannerStatus

_SCANNER_JOB = {
    "presidio": "personal information",
    "prompt_guard": "hidden instructions, with a model",
    "semgrep": "risky code",
}
_PII_ROLES = frozenset({"support", "admin"})
_HOST_ONLY = "semgrep.host_lifecycle_unavailable"


def _add_command(scanner_id: str) -> str:
    return f"petasos scanner add {scanner_id}"


def scanner_report(
    resolved: Resolved | None,
    *,
    registry: tuple[ScannerSpec, ...] = REGISTRY,
) -> tuple[tuple[Check, ...], tuple[str, ...], tuple[dict[str, object], ...]]:
    """Scanner checks, Hermes-worded suggestions, and the status rows.

    One composition feeds all three, so the text, the JSON, and the dashboard
    cannot disagree about what is running.
    """
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
            (_syntactic_row(),),
        )
    try:
        composition = compose(resolved.config, BuildContext(), registry=registry)
    except Exception as exc:
        row: dict[str, object] = {
            "id": "scanners",
            "label": "Optional scanners",
            "state": "unavailable",
            "reason": "The scanners could not be checked.",
            "fix": "Try again. If it keeps happening, the detail is in the log.",
            "extra": None,
        }
        none: tuple[str, ...] = ()
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
            none,
            (_syntactic_row(), row),
        )
    paused = resolved.settings.enabled is False
    consequence = held_consequence(
        resolved.config.fail_mode, resolved.config.tools.dangerous_posture
    )
    checks = [
        Check(
            id="scanner_builtin",
            status="ok",
            summary=(
                "The built-in text checks are paused, with the rest of protection."
                if paused
                else "The built-in text checks are running. They look for hidden instructions."
            ),
        )
    ]
    rows: list[dict[str, object]] = [_syntactic_row()]
    for status in composition.statuses:
        enabled = _enabled_of(resolved, status.id)
        kind, summary, meaning, step = _scanner_line(
            status, consequence, paused=paused, enabled=enabled
        )
        checks.append(
            Check(
                id=f"scanner_{status.id}",
                status=kind,
                summary=summary,
                meaning=meaning,
                next_step=step,
            )
        )
        rows.append(_scanner_row(status, consequence))
    return tuple(checks), hermes_suggestions(composition, resolved.settings.role), tuple(rows)


def held_consequence(fail_mode: object, posture: object) -> dict[str, object]:
    """What happens to tool calls while a required check cannot run.

    Computed from the two settings that decide it, so the sentence is true
    under each value. A required check that cannot run errors on every scan.
    Under ``open`` that error does not make a scan unsafe, so nothing is held.
    Otherwise a tool call that can change things is blocked, or handed to a
    person when dangerous actions are set to ask; a read-only tool call runs.
    An unrecognised fail mode is treated as ``degraded``, as the engine does.
    """
    if fail_mode == "open":
        return {
            "holds": False,
            "title": "A required check cannot run",
            "sentence": (
                "Tool calls still run without it, because a check that breaks is set "
                "to let text through."
            ),
        }
    if posture == "approve":
        return {
            "holds": True,
            "title": "Tool calls that change things wait for a person",
            "sentence": (
                "Until it is added or turned off, a person is asked before a tool call "
                "that can change things runs. Read-only tool calls still run."
            ),
        }
    return {
        "holds": True,
        "title": "Tool calls that change things are blocked",
        "sentence": (
            "Until it is added or turned off, tool calls that can change things are "
            "blocked. Read-only tool calls still run."
        ),
    }


def approval_check(resolved: Resolved | None, *, hermes_available: bool) -> Check:
    """Whether a dangerous tool call is blocked, or handed to Hermes to ask."""
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
                "This Python cannot see Hermes, so it cannot tell whether Hermes "
                "would ask, refuse, or allow the call without asking."
            ),
            next_step="Run hermes petasos doctor, which uses Hermes's own Python.",
        )
    from petasos.hermes.host import GUARDIAN_NAME, approval_grant, approval_mode

    grant = approval_grant()
    reasons: list[str] = []
    if grant.mode_off:
        reasons.append("approvals are turned off")
    if grant.yolo:
        reasons.append("confirmation is switched off for this process")
    if grant.context:
        reasons.append("this is a scheduled or unattended run that approves on its own")
    if reasons:
        because = join_reasons(reasons)
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
    if approval_mode() == "smart":
        return Check(
            id="approval",
            status="ok",
            summary=(
                f"Dangerous tool calls are handed to Hermes. {GUARDIAN_NAME} judges a risky "
                "command first, except commands Hermes reserves for a person or refuses unread. "
                "Once a conversation looks risky, Petasos asks a person itself. "
                "If nobody is there to answer, Hermes refuses the call."
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


def guardrail_words(mode: str, minutes: int) -> tuple[str, str]:
    """The recognition policy when no machine-level pin is in force."""
    if mode == "never":
        return (
            "Blocked. The agent is not allowed to change guardrails from the conversation.",
            (
                "Changes are refused wherever Petasos recognises them. "
                "A determined agent with a shell could still find a way round. "
                "The operator changes them from outside the agent."
            ),
        )
    return (
        "Open. The agent can change guardrails with a fresh approval.",
        (
            "A person approves the change for that action or for this session. "
            f"A session approval lasts {minutes} minutes and does not carry into "
            "another conversation."
        ),
    )


def guardrail_check(paths: tuple[str, ...], *, mode: str = "approve", minutes: int = 30) -> Check:
    """The recognition policy for an unpinned profile.

    ``mode`` is ``approve`` (open) or ``never`` (blocked). The path list stays
    in the meaning, after the state, so the default report still names it.
    """
    summary, meaning = guardrail_words(mode, minutes)
    places = paths_summary(paths)
    return Check(
        id="guardrail",
        status="info",
        summary=summary,
        meaning=f"{meaning} {places}",
    )


def current_paths() -> tuple[str, ...]:
    """Protected paths for the home the caller has already selected."""
    try:
        return tuple(sorted(protected_paths()))
    except Exception:
        return ()


def hermes_suggestions(composition: Composition, role: str | None) -> tuple[str, ...]:
    """What is missing, in the same plain register as the rest of the report.

    The built-in checks already look for hidden instructions. The prompt-guard
    line says the model is missing, and how to add it where Hermes will see it.
    """
    lines: list[str] = []
    if not _capability_active(composition, "injection"):
        lines.append(
            "The extra model that looks for hidden instructions is not installed. "
            "The built-in checks still run. "
            "Add it: " + _add_command("prompt_guard")
        )
    if role in _PII_ROLES and not _capability_active(composition, "pii"):
        lines.append(
            f"The {role} job has no extra check for personal information. "
            "The built-in checks do not look for it. "
            "Add it: " + _add_command("presidio")
        )
    return tuple(lines)


def _capability_active(composition: Composition, capability: str) -> bool:
    return any(
        status.state == "active" and capability in status.detects
        for status in composition.statuses
    )


def _enabled_of(resolved: Resolved, scanner_id: str) -> str:
    section = getattr(resolved.config.scanners, scanner_id, None)
    value = getattr(section, "enabled", None)
    return value if isinstance(value, str) else ""


def _scanner_line(
    status: ScannerStatus,
    consequence: dict[str, object],
    *,
    paused: bool = False,
    enabled: str = "",
) -> tuple[Status, str, str, str]:
    if status.id == "semgrep" and status.reason == _HOST_ONLY and status.state == "unavailable":
        if semgrep_host.semgrep_can_run():
            return (
                "warn",
                "Semgrep cannot run in this process yet.",
                "The check was asked for and did not start.",
                semgrep_host.SEMGREP_OFF_COMMAND,
            )
        return _semgrep_line(enabled, consequence)
    job = _SCANNER_JOB.get(status.id, status.label)
    if status.state == "active" and paused:
        return (
            "ok",
            f"{status.label} is paused, with the rest of protection. It checks for {job}.",
            "",
            "",
        )
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
    if _package_missing(status):
        return (
            "warn",
            f"{status.label} is turned on but not installed.",
            f"It would check for {job}. It is required and cannot run. {consequence['sentence']}",
            f"Add it: {_add_command(status.id)}. Or turn it off in Settings.",
        )
    reason = status.reason or "no reason was reported"
    return (
        "warn",
        f"{status.label} is installed but cannot be used.",
        reason,
        "Fix that check, or turn it off, then run petasos doctor again.",
    )


def _syntactic_row() -> dict[str, object]:
    return {
        "id": "syntactic",
        "label": "Basic checks",
        "purpose": "Basic checks",
        "state": "active",
        "reason": None,
        "fix": None,
        "extra": None,
    }


def _scanner_row(status: ScannerStatus, consequence: dict[str, object]) -> dict[str, object]:
    # Unavailable means the check errors on every scan. That holds tool calls
    # under the usual fail mode, including Semgrep, which Hermes cannot run.
    held = status.state == "unavailable"
    return {
        "id": status.id,
        "label": status.label,
        "purpose": status.purpose,
        "state": status.state,
        "reason": _hermes_reason(status),
        "fix": _hermes_fix(status),
        "extra": status.extra,
        "consequence": dict(consequence) if held else None,
    }


def _package_missing(status: ScannerStatus) -> bool:
    # ``missing`` also covers a model that has not been downloaded. Only a
    # missing package carries the registry's pip instruction.
    return status.missing and "pip install" in (status.reason or "")


def _semgrep_line(enabled: str, consequence: dict[str, object]) -> tuple[Status, str, str, str]:
    lead = semgrep_host.SEMGREP_SET_AS.get(enabled, "It is turned on")
    title = str(consequence.get("title") or "")
    if consequence.get("holds") is True and title:
        # The title already says what happens under this fail mode and posture.
        effect = title[0].lower() + title[1:]
        meaning = f"{lead}, so {effect}. Read-only tool calls still run."
    else:
        meaning = f"{lead}. {consequence.get('sentence') or ''}".strip()
    return (
        "warn",
        semgrep_host.SEMGREP_CANNOT_RUN,
        meaning,
        semgrep_host.SEMGREP_OFF_COMMAND,
    )


def _hermes_reason(status: ScannerStatus) -> str | None:
    # The registry's reason for a missing package names pip, which is the
    # wrong instruction inside Hermes. The fix carries the right one.
    if status.reason == _HOST_ONLY and not semgrep_host.semgrep_can_run():
        return semgrep_host.SEMGREP_CANNOT_RUN
    if status.reason == _HOST_ONLY:
        return "Semgrep cannot run in this process yet."
    if _package_missing(status):
        return f"{status.label} is not installed."
    return status.reason


def _hermes_fix(status: ScannerStatus) -> str | None:
    text = fix_for(status)
    if text is None:
        return None
    if status.reason == _HOST_ONLY:
        return semgrep_host.SEMGREP_OFF_COMMAND
    if status.extra is not None and "pip install" in text:
        return _add_command(status.id)
    return text
