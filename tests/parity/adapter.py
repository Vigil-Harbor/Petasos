"""The only module in the parity oracle that imports Petasos.

``scan_text``, ``evaluate_tool_call`` and ``run_session`` return plain
verdicts. A later cutover re-points this file at the new interfaces and
leaves the corpus, the recorded verdicts and the replay test alone.

Single-shot calls inside :func:`batch` share one pipeline per profile and
clear its frequency table before every call, so cases cannot influence each
other. :func:`run_session` always builds a new pipeline and keeps it for
the whole sequence. Verdicts omit timings, scores and free-text reasons.

A profile label ``plugin:<name>`` binds ``<name>`` to the pipeline only.
The guard is constructed without a profile, as the reference plugin does.
A bare built-in name is passed to both. ``none`` binds neither.
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
from tests.parity.load import ALL_PROFILES, expand_args, text_of

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
    def build(cls, profile: str | None, *, guard_profile: bool = True) -> _Engine:
        """Build a pipeline bound to ``profile`` and a guard.

        ``guard_profile`` false leaves the guard's profile argument unset even
        when the pipeline is bound. The reference plugin always does that.
        """
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
                profile=resolved if guard_profile else None,
                home=PARITY_HOME,
            )
            return cls(pipeline, guard, tracker)
        finally:
            if saved is not None:
                os.environ["PETASOS_LICENSE_KEY"] = saved

    @classmethod
    def from_label(cls, label: str) -> _Engine:
        """Build the engine a corpus profile label names."""
        name, use_guard = _arrangement(label)
        return cls.build(name, guard_profile=use_guard)


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


def _arrangement(label: str) -> tuple[str | None, bool]:
    """Return the pipeline profile and whether the guard receives it.

    ``none`` binds neither. ``plugin:<name>`` binds the pipeline only.
    A bare built-in name binds both.
    """
    if label == "none":
        return None, False
    if label.startswith("plugin:"):
        name = label.removeprefix("plugin:")
        if name not in _PROFILE_NAMES:
            raise ValueError(f"unknown profile {label!r}")
        return name, False
    if label not in _PROFILE_NAMES:
        raise ValueError(f"unknown profile {label!r}")
    return label, True


def _label(profile: str | None) -> str:
    if profile is None or profile == "none":
        return "none"
    _arrangement(profile)
    return profile


def _direction(value: str) -> Direction:
    if value == "inbound":
        return "inbound"
    if value == "outbound":
        return "outbound"
    raise ValueError(f"direction must be inbound or outbound, got {value!r}")


def _bind(profile: str | None) -> tuple[_Engine, str]:
    """Return an engine and a session id that no earlier single-shot used."""
    label = _label(profile)
    active = _batch.get()
    if active is None:
        return _Engine.from_label(label), "parity-oneshot"
    engine = active.engines.get(label)
    if engine is None:
        engine = _Engine.from_label(label)
        active.engines[label] = engine
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
    result = await engine.guard.evaluate(tool, expand_args(dict(args)), session_id)
    return _tool_verdict(result)


async def _run_session(
    steps: list[dict[str, Any]], *, profile: str | None
) -> list[dict[str, Any]]:
    # A new engine, not the batch cache: the sequence is one session, and
    # it must not see single-shot state or another sequence's state.
    engine = _Engine.from_label(_label(profile))
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
            guard_result = await engine.guard.evaluate(tool, expand_args(dict(args)), session_id)
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


def _require_cases(corpus: dict[str, Any], kind: str) -> list[Any]:
    cases = corpus.get(kind)
    if not isinstance(cases, list):
        raise TypeError(f"corpus {kind} section must be an array")
    return cases


async def _replay_corpus(corpus: dict[str, Any]) -> dict[str, Any]:
    """Replay every case under every profile label on one event loop."""
    text_cases = _require_cases(corpus, "text")
    tool_cases = _require_cases(corpus, "tool")
    session_cases = _require_cases(corpus, "session")
    text_out: dict[str, dict[str, Any]] = {}
    tool_out: dict[str, dict[str, Any]] = {}
    session_out: dict[str, dict[str, Any]] = {}
    token = _batch.set(_Batch())
    try:
        for label in ALL_PROFILES:
            name, use_guard = _arrangement(label)
            # Text never reaches the guard. A plugin label's pipeline profile
            # was already scanned under the bare name, which is built first.
            if not use_guard and name is not None:
                copied = text_out.get(name)
                if copied is None:
                    raise RuntimeError(f"{label} replayed before pipeline profile {name}")
                text_out[label] = dict(copied)
            else:
                per_text: dict[str, Any] = {}
                for case in text_cases:
                    if not isinstance(case, dict) or not isinstance(case.get("id"), str):
                        raise TypeError("text case needs a string id")
                    scanned = text_of(case)
                    per_text[case["id"]] = {
                        "inbound": await _scan_text(scanned, direction="inbound", profile=label),
                        "outbound": await _scan_text(scanned, direction="outbound", profile=label),
                    }
                text_out[label] = per_text

            per_tool: dict[str, Any] = {}
            for case in tool_cases:
                if not isinstance(case, dict) or not isinstance(case.get("id"), str):
                    raise TypeError("tool case needs a string id")
                tool = case.get("tool")
                args = case.get("args")
                if not isinstance(tool, str) or not isinstance(args, dict):
                    raise TypeError("tool case needs a string tool and an args object")
                per_tool[case["id"]] = await _evaluate_tool_call(tool, args, profile=label)
            tool_out[label] = per_tool

            per_session: dict[str, Any] = {}
            for case in session_cases:
                if not isinstance(case, dict) or not isinstance(case.get("id"), str):
                    raise TypeError("session case needs a string id")
                steps = case.get("steps")
                if not isinstance(steps, list):
                    raise TypeError("session case needs a steps array")
                per_session[case["id"]] = await _run_session(steps, profile=label)
            session_out[label] = per_session
    finally:
        _batch.reset(token)
    return {"session": session_out, "text": text_out, "tool": tool_out}


def replay_corpus(corpus: dict[str, Any]) -> dict[str, Any]:
    """Replay ``corpus`` and return verdicts keyed by kind, profile, then case id."""
    return asyncio.run(_replay_corpus(corpus))


def run_session(steps: list[dict[str, Any]], *, profile: str | None) -> list[dict[str, Any]]:
    """Run ``steps`` in one new session and return one verdict per step.

    Text steps record the pipeline tier after that step. Tool steps record
    the guard tier at the start of that step. Scores are not recorded.
    """
    return asyncio.run(_run_session(steps, profile=profile))
