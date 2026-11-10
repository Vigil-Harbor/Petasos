"""What Petasos would do with one input, without touching a live session.

The dashboard is a different process from the gateway. Each call builds a
pipeline from the resolved settings and throws it away. It does not write
the enforcement spool, and it does not download a model.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from petasos._types import Direction, ScanFinding, Severity
from petasos.config.layers import resolve
from petasos.config.schema import ConfigError
from petasos.config.secrets import Secrets
from petasos.enforce.approvals import redact_display_text
from petasos.enforce.decisions import (
    Allow,
    Approve,
    Block,
    blocks,
    dangerous_tool_decision,
    guard_denial,
    is_dangerous,
    is_egress_sink,
    worst,
)
from petasos.enforce.messages import format_content_block, format_result_notice
from petasos.hermes.dashboard.catalog import combine
from petasos.hermes.dashboard.errors import ApiError, envelope
from petasos.hermes.dashboard.words import looks_for
from petasos.normalize import canonicalize_tool_name, normalize
from petasos.scanners.registry import REGISTRY, BuildContext, ScannerSpec, ScannerStatus, compose

logger = logging.getLogger("petasos.hermes.dashboard")

MAX_CHARS = 20_000
COMPOSE_BUDGET_S = 2.0
SCAN_BUDGET_S = 2.0
_SESSION = "petasos-playground"
_DISPLAY_LIMIT = 500
# A tool's name in a message when the input was text, not a tool call.
_ANY_TOOL = "<tool>"

# What each decision means, in words. ``text`` is said of a tool call;
# ``text_in`` and ``text_out`` of text coming in or going out.
_OUTCOMES: dict[str, dict[str, str]] = {
    "block": {
        "label": "Blocked",
        "sentence": "The tool call would not run. The agent is told why.",
        "text_out": ("A tool call carrying this text would not run. The agent is told why."),
    },
    "approve": {
        "label": "Asks a person",
        "sentence": (
            "Hermes would ask a person before the tool call runs. It runs only if they say yes."
        ),
    },
    "flag": {
        "label": "Flagged",
        "sentence": (
            "The agent would get this text with a warning above it, and it counts toward "
            "the conversation's risk score. The text itself is not withheld."
        ),
    },
    "allow": {
        "label": "Allowed",
        "sentence": "Petasos would let this through unchanged.",
    },
    "none": {
        "label": "No decision",
        "sentence": "The check did not finish in time, so this preview has no decision.",
    },
}

CONFIDENCE_HELP = (
    "Match strength is how closely the text matched the rule, from 0 to 100%. "
    "It is not the chance that this is an attack."
)
_TIME_LIMIT = "Did not finish within Try it's time limit."
# Why an optional check took no part, in words. A check that is on but not
# working keeps the registry's own reason, which names the fault.
_PLAIN_REASON = {
    "not_installed": "Not installed, so it took no part. Overview says how to add it.",
    "off": "Turned off in Settings, so it took no part.",
}

_Redactor = Callable[..., str]


async def try_input(
    stored: Mapping[str, Any],
    *,
    text: str | None = None,
    direction: str | None = None,
    tool: str | None = None,
    arguments: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
    registry: tuple[ScannerSpec, ...] | None = None,
    redactor: _Redactor | None = None,
    protected_paths: Callable[[], Iterable[str]] | None = None,
    time_budget: float = SCAN_BUDGET_S,
    max_chars: int = MAX_CHARS,
) -> dict[str, Any]:
    """The decision for one text or one tool call.

    Pass ``text`` or ``tool``, not both. ``candidate`` is a settings patch
    that is not saved. ``registry`` defaults to the real scanners. A scanner
    whose weights are not on disk does not take part and does not start a
    download. ``protected_paths`` defaults to an empty set so this call does
    not discover a Hermes home.
    """
    if (text is None) == (tool is None):
        raise ApiError("invalid_input", "Send either a piece of text or a tool call.")
    if text is not None and not isinstance(text, str):
        raise ApiError("invalid_input", "Text must be a string.")
    if tool is not None and (not isinstance(tool, str) or not tool.strip()):
        raise ApiError("invalid_input", "A tool call needs a name.")
    if arguments is not None and not isinstance(arguments, Mapping):
        raise ApiError("invalid_input", "Tool arguments must be an object.")
    _bound_size(text, arguments, max_chars)
    document = combine(stored, candidate or {})
    try:
        resolved = resolve(document)
    except ConfigError as exc:
        first = exc.errors[0]
        raise ApiError("invalid_settings", first[1], path=first[0] or None) from exc
    specs, skipped = _registry(registry)
    paths = protected_paths if protected_paths is not None else (lambda: ())
    try:
        composition = await asyncio.wait_for(
            asyncio.to_thread(compose, resolved.config, BuildContext(), registry=specs),
            timeout=COMPOSE_BUDGET_S,
        )
    except TimeoutError:
        logger.warning("playground scanner composition exceeded %ss", COMPOSE_BUDGET_S)
        return await _syntactic_only(
            resolved,
            text=text,
            direction=direction,
            tool=tool,
            arguments=arguments,
            redactor=redactor,
            protected_paths=paths,
            time_budget=time_budget,
            skipped=skipped,
            reason="Did not finish starting within Try it's time limit.",
        )
    if text is not None:
        return await _text(
            resolved,
            composition.scanners,
            composition.statuses,
            skipped,
            text,
            direction,
            redactor,
            time_budget,
        )
    return await _tool(
        resolved,
        composition.scanners,
        composition.statuses,
        skipped,
        tool or "",
        arguments or {},
        redactor,
        paths,
        time_budget,
    )


def _bound_size(text: str | None, arguments: Mapping[str, Any] | None, max_chars: int) -> None:
    if text is not None and len(text) > max_chars:
        raise ApiError(
            "too_large",
            f"That text is longer than {max_chars} characters. Shorten it and try again.",
        )
    if arguments is not None:
        try:
            encoded = json.dumps(arguments)
        except (TypeError, ValueError) as exc:
            raise ApiError("invalid_input", "Tool arguments must be JSON.") from exc
        if len(encoded) > max_chars:
            raise ApiError(
                "too_large",
                f"Those arguments are longer than {max_chars} characters. "
                "Shorten them and try again.",
            )


def _registry(
    registry: tuple[ScannerSpec, ...] | None,
) -> tuple[tuple[ScannerSpec, ...], list[dict[str, Any]]]:
    chosen = REGISTRY if registry is None else registry
    if registry is not None:
        return chosen, []
    from petasos.scanners.prompt_guard import would_download

    if not would_download():
        return chosen, []
    kept = tuple(spec for spec in chosen if spec.id != "prompt_guard")
    skipped = [
        {
            "id": "prompt_guard",
            "label": "PromptGuard",
            "participated": False,
            "state": "unavailable",
            "reason": "Its model is not downloaded, and Try it does not download one.",
        }
    ]
    return kept, skipped


async def _syntactic_only(
    resolved: Any,
    *,
    text: str | None,
    direction: str | None,
    tool: str | None,
    arguments: Mapping[str, Any] | None,
    redactor: _Redactor | None,
    protected_paths: Callable[[], Iterable[str]],
    time_budget: float,
    skipped: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    # An empty registry still builds the syntactic scanner, inside compose.
    composition = compose(resolved.config, BuildContext(), registry=())
    notes = list(skipped)
    for spec in REGISTRY:
        if any(row["id"] == spec.id for row in notes):
            continue
        notes.append(
            {
                "id": spec.id,
                "label": spec.label,
                "participated": False,
                "state": "unavailable",
                "reason": reason,
            }
        )
    if text is not None:
        return await _text(
            resolved,
            composition.scanners,
            composition.statuses,
            notes,
            text,
            direction,
            redactor,
            time_budget,
        )
    return await _tool(
        resolved,
        composition.scanners,
        composition.statuses,
        notes,
        tool or "",
        arguments or {},
        redactor,
        protected_paths,
        time_budget,
    )


async def _text(
    resolved: Any,
    scanners: tuple[Any, ...],
    statuses: tuple[ScannerStatus, ...],
    skipped: list[dict[str, Any]],
    text: str,
    direction: str | None,
    redactor: _Redactor | None,
    time_budget: float,
) -> dict[str, Any]:
    from petasos.pipeline import Pipeline

    way: Direction | None
    if direction is None:
        way = None
    elif direction == "inbound":
        way = "inbound"
    elif direction == "outbound":
        way = "outbound"
    else:
        raise ApiError("invalid_input", "Direction must be inbound or outbound.")
    pipeline = Pipeline(scanners, config=resolved.config, secrets=Secrets())
    timed_out = False
    try:
        result = await asyncio.wait_for(
            pipeline.inspect(text, direction=way),
            timeout=time_budget,
        )
    except TimeoutError:
        timed_out = True
        result = None
        logger.warning("playground text scan exceeded %ss", time_budget)
    findings = () if result is None else result.findings
    blocking = tuple(finding for finding in findings if blocks(finding.severity))
    if result is not None and "CancelledError" in result.errors:
        # The pipeline catches cancellation and returns it as an error. That is
        # the time limit firing, not a decision.
        timed_out = True
    # Text coming in is a tool result: Petasos never withholds it. It puts a
    # warning above it when a non-personal-detail finding would block, the same
    # test the result hook uses. Text going out is what the agent writes into a
    # tool call, and a call carrying it is blocked.
    flagged = tuple(item for item in blocking if item.finding_type != "pii")
    unsafe = bool(blocking) or (result is not None and not result.safe)
    inbound = way != "outbound"
    if timed_out:
        decision = "allow"
        message = _OUTCOMES["none"]["sentence"]
    elif inbound and flagged:
        decision = "flag"
        top = worst(flagged)
        message = format_result_notice("findings", _ANY_TOOL, top, len(flagged))
    elif not inbound and unsafe:
        decision = "block"
        message = format_content_block("non_pii_param", _ANY_TOOL, blocking or findings)
    else:
        decision = "allow"
        message = ""
    return _body(
        resolved,
        decision,
        message,
        findings,
        text,
        _scanner_rows(statuses, skipped, timed_out),
        timed_out,
        redactor,
        subject="text_out" if way == "outbound" else "text_in",
    )


async def _tool(
    resolved: Any,
    scanners: tuple[Any, ...],
    statuses: tuple[ScannerStatus, ...],
    skipped: list[dict[str, Any]],
    tool: str,
    arguments: Mapping[str, Any],
    redactor: _Redactor | None,
    protected_paths: Callable[[], Iterable[str]],
    time_budget: float,
) -> dict[str, Any]:
    from petasos.pipeline import Pipeline
    from petasos.session.frequency import FrequencyTracker
    from petasos.session.guard import READ_ONLY_TOOLS, ToolCallGuard
    from petasos.session.taint import SessionTaintStore

    config = resolved.config
    secrets = Secrets()
    tracker = FrequencyTracker(config, secrets=secrets)
    pipeline = Pipeline(
        scanners,
        config=config,
        secrets=secrets,
        frequency_tracker=tracker,
    )
    guard = ToolCallGuard(
        pipeline,
        tracker,
        config,
        secrets=secrets,
        protected_paths=protected_paths,
    )
    read_only = frozenset(
        canon for canon in (canonicalize_tool_name(name) for name in READ_ONLY_TOOLS) if canon
    )
    timed_out = False
    try:
        evaluated = await asyncio.wait_for(
            guard.evaluate(tool, dict(arguments), _SESSION),
            timeout=time_budget,
        )
    except TimeoutError:
        timed_out = True
        evaluated = None
        logger.warning("playground tool check exceeded %ss", time_budget)
    findings: tuple[ScanFinding, ...] = ()
    decision = "allow"
    message = ""
    if timed_out:
        message = "The check did not finish in time, so this preview has no decision."
    elif evaluated is not None:
        findings = tuple(evaluated.findings)
        denied = guard_denial(tool, _SESSION, evaluated, logger=logger, emit=_discard)
        if isinstance(denied, Block):
            decision = "block"
            message = denied.message
        elif not is_dangerous(tool, read_only):
            decision = "allow"
        else:
            sinks = _names(config.egress.sink_tools)
            namespaces = _names(config.egress.taint_namespaces)
            chosen = dangerous_tool_decision(
                tool,
                dict(arguments),
                _SESSION,
                evaluated,
                is_egress_sink(tool, sinks),
                config.tools.dangerous_posture,
                True,
                False,
                namespaces=namespaces,
                taint_store=SessionTaintStore(config),
                always_approved=lambda _rule: False,
                degraded_recorded=lambda _session: False,
                excerpt_for=lambda: "",
                logger=logger,
                emit=_discard,
            )
            if isinstance(chosen, Block):
                decision = "block"
                message = chosen.message
            elif isinstance(chosen, Approve):
                decision = "approve"
                message = chosen.message
            elif chosen is None or isinstance(chosen, Allow):
                decision = "allow"
    rendered = _argument_text(arguments)
    return _body(
        resolved,
        decision,
        message,
        findings,
        rendered,
        _scanner_rows(statuses, skipped, timed_out),
        timed_out,
        redactor,
    )


def _body(
    resolved: Any,
    decision: str,
    message: str,
    findings: tuple[ScanFinding, ...],
    source: str,
    scanners: list[dict[str, Any]],
    timed_out: bool,
    redactor: _Redactor | None,
    subject: str = "sentence",
) -> dict[str, Any]:
    flags = resolved.config.normalization
    normalised = normalize(
        source,
        nfkc=flags.nfkc,
        strip_zero_width=flags.zero_width,
        map_homoglyphs=flags.homoglyphs,
    ).normalized
    changed = normalised != source
    shown = _show(message, redactor)
    words = _OUTCOMES["none" if timed_out else decision]
    return envelope(
        decision=decision,
        outcome={
            "code": "none" if timed_out else decision,
            "label": words["label"],
            "sentence": words.get(subject, words["sentence"]),
        },
        confidence_help=CONFIDENCE_HELP,
        message=shown,
        findings=[_finding(item) for item in findings[:50]],
        findings_omitted=max(0, len(findings) - 50),
        normalized=_show(normalised, redactor) if changed else None,
        normalized_changed=changed,
        scanners=scanners,
        timed_out=timed_out,
    )


def _finding(finding: ScanFinding) -> dict[str, Any]:
    span = None
    if finding.position is not None:
        span = {"start": finding.position.start, "end": finding.position.end}
    if isinstance(finding.severity, Severity):
        severity = finding.severity.value
    else:
        severity = str(finding.severity)
    return {
        "rule": finding.rule_id,
        "severity": severity,
        "confidence": finding.confidence,
        "span": span,
        "sentence": looks_for(finding.rule_id, finding.message),
    }


def _scanner_rows(
    statuses: tuple[ScannerStatus, ...],
    skipped: list[dict[str, Any]],
    timed_out: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "id": "syntactic",
            "label": "Basic checks",
            "participated": not timed_out,
            "state": "active" if not timed_out else "unavailable",
            "reason": _TIME_LIMIT if timed_out else None,
        }
    ]
    for status in statuses:
        participated = status.state == "active" and not timed_out
        reason = _PLAIN_REASON.get(status.state, status.reason)
        if status.state == "active" and timed_out:
            reason = _TIME_LIMIT
        rows.append(
            {
                "id": status.id,
                "label": status.label,
                "participated": participated,
                "state": "unavailable" if timed_out and status.state == "active" else status.state,
                "reason": reason,
            }
        )
    rows.extend(skipped)
    return rows


def _names(values: Iterable[str]) -> frozenset[str]:
    return frozenset(canon for canon in (canonicalize_tool_name(name) for name in values) if canon)


def _argument_text(arguments: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for value in arguments.values():
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def _show(value: str, redactor: _Redactor | None) -> str:
    if not value:
        return ""
    shown, _status = redact_display_text(value, _DISPLAY_LIMIT, redact=redactor)
    return shown


def _discard(**_kwargs: object) -> None:
    return None
