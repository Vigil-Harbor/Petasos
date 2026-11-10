"""The only module in the parity oracle that imports Petasos.

``scan_text``, ``evaluate_tool_call`` and ``run_session`` return plain
verdicts. A later cutover re-points this file at the new interfaces and
leaves the corpus, the recorded verdicts and the replay test alone.

Single-shot calls inside :func:`batch` share one pipeline per profile and
clear its frequency table before every call, so cases cannot influence each
other. :func:`run_session` always builds a new pipeline and keeps it for
the whole sequence. Verdicts omit timings, scores and free-text reasons.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any

from petasos.config import PetasosConfig
from petasos.console._paths import HermesConfigResolution
from petasos.pipeline import Pipeline
from petasos.session.frequency import FrequencyTracker
from petasos.session.guard import GuardResult, ToolCallGuard
from petasos.session.profiles import ProfileResolver, ResolvedProfile

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from petasos._types import Direction, PipelineResult

# Absolute, and long enough for the self-modification owned-path check.
# The corpus uses this same path. It does not need to exist on disk.
PARITY_HOME = HermesConfigResolution(
    path=Path("/tmp/petasos-parity-home/config.yaml"),
    tier="root",
)

_PROFILE_NAMES = frozenset({"general", "code_generation", "research", "customer_service", "admin"})

_FindingPairs = list[list[str]]


class _Engine:
    """One syntactic pipeline and the guard that shares its tracker."""

    def __init__(
        self,
        pipeline: Pipeline,
        guard: ToolCallGuard,
        tracker: FrequencyTracker,
    ) -> None:
        self.pipeline = pipeline
        self.guard = guard
        self.tracker = tracker

    @classmethod
    def build(cls, profile: str | None) -> _Engine:
        saved = os.environ.pop("PETASOS_LICENSE_KEY", None)
        try:
            config = PetasosConfig()
            tracker = FrequencyTracker(config)
            resolved: ResolvedProfile | None = None
            if profile is not None:
                resolved = ProfileResolver().resolve(profile)
            pipeline = Pipeline(
                config=config,
                profile=resolved,
                frequency_tracker=tracker,
            )
            guard = ToolCallGuard(
                pipeline,
                tracker,
                config,
                profile=resolved,
                home=PARITY_HOME,
            )
            return cls(pipeline, guard, tracker)
        finally:
            if saved is not None:
                os.environ["PETASOS_LICENSE_KEY"] = saved


class _Batch:
    def __init__(self) -> None:
        self.engines: dict[str, _Engine] = {}
        self.n = 0


_batch: ContextVar[_Batch | None] = ContextVar("petasos_parity_batch", default=None)


@contextmanager
def batch() -> Iterator[None]:
    """Reuse one engine per profile for the calls made inside the block.

    The token is reset on the way out, so nothing is retained after the
    block. Outside a batch every call builds a fresh engine.
    """
    token = _batch.set(_Batch())
    try:
        yield
    finally:
        _batch.reset(token)


def _normalize_profile(profile: str | None) -> str | None:
    if profile is None or profile == "none":
        return None
    if profile not in _PROFILE_NAMES:
        raise ValueError(f"unknown profile {profile!r}")
    return profile


def _direction(value: str) -> Direction:
    if value == "inbound":
        return "inbound"
    if value == "outbound":
        return "outbound"
    raise ValueError(f"direction must be inbound or outbound, got {value!r}")


def _bind(profile: str | None) -> tuple[_Engine, str]:
    """Return an engine and a session id that no earlier single-shot used."""
    normalized = _normalize_profile(profile)
    active = _batch.get()
    if active is None:
        return _Engine.build(normalized), "parity-oneshot"
    key = "none" if normalized is None else normalized
    engine = active.engines.get(key)
    if engine is None:
        engine = _Engine.build(normalized)
        active.engines[key] = engine
    engine.tracker.clear()
    active.n += 1
    return engine, f"parity-{active.n}"


def _finding_pairs(findings: tuple[Any, ...]) -> _FindingPairs:
    pairs = [[item.rule_id, item.severity.value] for item in findings]
    pairs.sort()
    return pairs


def _error_strings(result: PipelineResult) -> list[str]:
    errors = list(result.errors)
    for scan in result.scanner_results:
        if scan.error is not None:
            errors.append(f"{scan.scanner_name}: {scan.error}")
    errors.sort()
    return errors


def _text_verdict(result: PipelineResult) -> dict[str, Any]:
    return {
        "errors": _error_strings(result),
        "findings": _finding_pairs(result.findings),
        "safe": result.safe,
    }


def _tool_verdict(result: GuardResult) -> dict[str, Any]:
    selfmod: list[str] | None = None
    if result.selfmod_finding is not None:
        selfmod = [result.selfmod_finding.rule_id, result.selfmod_finding.severity.value]
    return {
        "allowed": result.allowed,
        "findings": _finding_pairs(result.findings),
        "param_scan_unsafe": result.param_scan_unsafe,
        "selfmod": selfmod,
        "tier": result.tier,
    }


async def _scan_text(text: str, *, direction: str, profile: str | None) -> dict[str, Any]:
    engine, session_id = _bind(profile)
    result = await engine.pipeline.inspect(
        text,
        direction=_direction(direction),
        session_id=session_id,
    )
    return _text_verdict(result)


async def _evaluate_tool_call(
    tool: str,
    args: Mapping[str, Any],
    *,
    profile: str | None,
) -> dict[str, Any]:
    engine, session_id = _bind(profile)
    result = await engine.guard.evaluate(tool, dict(args), session_id)
    return _tool_verdict(result)


async def _run_session(
    steps: list[dict[str, Any]], *, profile: str | None
) -> list[dict[str, Any]]:
    # A new engine, not the batch cache: the sequence is one session, and
    # it must not see single-shot state or another sequence's state.
    engine = _Engine.build(_normalize_profile(profile))
    session_id = "parity-session"
    out: list[dict[str, Any]] = []
    for step in steps:
        kind = step.get("kind")
        if kind == "text":
            text = step.get("text")
            direction = step.get("direction")
            if not isinstance(text, str) or not isinstance(direction, str):
                raise TypeError("text step needs string text and direction")
            result = await engine.pipeline.inspect(
                text,
                direction=_direction(direction),
                session_id=session_id,
            )
            verdict = _text_verdict(result)
            verdict["kind"] = "text"
            verdict["tier"] = result.escalation_tier
            out.append(verdict)
        elif kind == "tool":
            tool = step.get("tool")
            args = step.get("args")
            if not isinstance(tool, str) or not isinstance(args, dict):
                raise TypeError("tool step needs a string tool and an args object")
            guard_result = await engine.guard.evaluate(tool, dict(args), session_id)
            verdict = _tool_verdict(guard_result)
            verdict["kind"] = "tool"
            out.append(verdict)
        else:
            raise ValueError(f"unknown session step kind {kind!r}")
    return out


def scan_text(text: str, *, direction: str, profile: str | None) -> dict[str, Any]:
    """Scan ``text`` once and return ``safe``, sorted findings and errors.

    ``profile`` is a built-in name or ``None`` / ``"none"`` for no profile.
    The call uses a session that no other single-shot call is still using.
    """
    return asyncio.run(_scan_text(text, direction=direction, profile=profile))


def evaluate_tool_call(
    tool: str,
    args: Mapping[str, Any],
    *,
    profile: str | None,
) -> dict[str, Any]:
    """Evaluate one tool call and return the guard verdict without its reason.

    The recorded fields are ``allowed``, ``tier``, ``param_scan_unsafe``,
    the sorted parameter-scan findings, and the self-modification rule when
    one fired. A fresh session is used, so ``tier`` is the tier at entry.
    """
    return asyncio.run(_evaluate_tool_call(tool, args, profile=profile))


def run_session(steps: list[dict[str, Any]], *, profile: str | None) -> list[dict[str, Any]]:
    """Run ``steps`` in one new session and return one verdict per step.

    Text steps record the pipeline tier after that step. Tool steps record
    the guard tier at the start of that step. Scores are not recorded.
    """
    return asyncio.run(_run_session(steps, profile=profile))
