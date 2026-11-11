"""Values a host passes to an enforcer, and the values an enforcer returns.

Nothing here decides a tool call. The types are frozen data plus the small
mutable seams a test uses instead of sleeping or reaching into the enforcer:
a clock, an init gate, and an evaluation fault.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from petasos.guard.surface import GuardrailSurface

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from petasos.config.secrets import Secrets
    from petasos.config.sections import PetasosConfig


class Clock(Protocol):
    """The time an enforcer reads. ``monotonic`` orders windows and deadlines."""

    def monotonic(self) -> float:
        """A clock that only moves forward, in seconds."""
        ...

    def time(self) -> float:
        """Wall time, in seconds since the epoch."""
        ...


class SystemClock:
    """The process clock."""

    def monotonic(self) -> float:
        """``time.monotonic``."""
        return time.monotonic()

    def time(self) -> float:
        """``time.time``."""
        return time.time()


class ManualClock:
    """A clock a test advances. It does not move on its own."""

    def __init__(self, *, monotonic: float = 0.0, wall: float = 0.0) -> None:
        self._monotonic = monotonic
        self._wall = wall
        self._lock = threading.Lock()

    def monotonic(self) -> float:
        """The monotonic reading."""
        with self._lock:
            return self._monotonic

    def time(self) -> float:
        """The wall reading."""
        with self._lock:
            return self._wall

    def advance(self, seconds: float) -> None:
        """Move both readings forward by ``seconds``."""
        with self._lock:
            self._monotonic += seconds
            self._wall += seconds


@dataclass(frozen=True, slots=True)
class Limits:
    """The enforcer's own deadlines, all below the host's hook timeout.

    ``init_wait_s`` is how long one cold start waits for scanners.
    ``eval_timeout_s`` bounds one guard evaluation. ``result_margin_s`` is
    added to the configured scanner timeout for a tool-result scan.
    ``log_every_s`` is the operator-log cadence.
    """

    init_wait_s: float = 2.0
    eval_timeout_s: float = 15.0
    result_margin_s: float = 5.0
    log_every_s: float = 30.0


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    """One observation of the host's settings.

    ``token`` is compared with ``==``. A different token is a change.
    ``error`` set means this observation is not usable: ``config`` is ignored
    and the previous good tree stays. ``armed`` is the operator switch.
    """

    armed: bool
    config: PetasosConfig | None
    secrets: Secrets
    token: object
    error: str | None = None
    secret_invalid: bool = False


class SettingsSource(Protocol):
    """Return the current settings. Called on each host-facing call."""

    def __call__(self) -> SettingsSnapshot:
        """The snapshot as of this call."""
        ...


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    """Why an approve would be granted with nobody attached.

    These are independent. Any one of them means the host would not ask a
    person: approvals are off, yolo is on, or this process is a single-query,
    cron, or unattended session whose matching mode grants the call. A rule
    that is permanently approved is a separate question.
    """

    mode_off: bool = False
    yolo: bool = False
    context: bool = False

    @property
    def unattended(self) -> bool:
        """True when the host would grant the directive without a person."""
        return self.mode_off or self.yolo or self.context


def _no_grant() -> ApprovalGrant:
    return ApprovalGrant()


def _never_approved(_rule_key: str) -> bool:
    return False


def _command_not_asked(_command: str) -> bool:
    return False


def _identity_text(text: str, **_options: object) -> str:
    return text


def _identity_path(path: str) -> str:
    return path


def _no_paths() -> frozenset[str]:
    return frozenset()


def _no_surface() -> GuardrailSurface:
    return GuardrailSurface()


@dataclass(frozen=True, slots=True)
class HostInfo:
    """What the host can do, and how the enforcer should ask it.

    Callables are read on each decision, so a live host change is visible
    without a settings token change. ``command_will_be_asked`` is true only
    when the host will put that command string to a person. The default
    answers no. ``redactor`` of ``None`` means the host has no redactor.
    ``protected_paths`` is the set of filesystem paths the agent must not
    modify.
    """

    host_id: str = "petasos"
    approve_directive: bool = False
    approval_grant: Callable[[], ApprovalGrant] = _no_grant
    rule_always_approved: Callable[[str], bool] = _never_approved
    command_will_be_asked: Callable[[str], bool] = _command_not_asked
    subagent_hooks: bool = True
    redactor: Callable[..., str] | None = _identity_text
    display_path: Callable[[str], str] = _identity_path
    protected_paths: Callable[[], frozenset[str]] = _no_paths
    guardrail_surface: Callable[[], GuardrailSurface] = _no_surface


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool call the host is about to run, or has just finished.

    ``session`` is the host's task id. An empty session with no ``agent``
    cannot be correlated across calls. ``host_session`` is the host's own
    session id when it is distinct from the task id.
    """

    tool: str
    args: Mapping[str, object] = field(default_factory=dict)
    session: str = ""
    turn_id: str | None = None
    tool_call_id: str | None = None
    host_session: str | None = None
    agent: object | None = None


@dataclass(frozen=True, slots=True)
class ApprovalNotice:
    """The fields of one approval request or answer. Missing text is empty."""

    command: str = ""
    description: str = ""
    pattern_key: str = ""
    pattern_keys: tuple[str, ...] = ()
    session_key: str = ""
    session_id: str = ""
    surface: str = ""
    turn_id: str = ""
    tool_call_id: str = ""
    choice: str | None = None
    decided_by: str | None = None
    coalesced: bool = False


LifecycleState = Literal["disarmed", "starting", "ready", "failed"]


@dataclass(frozen=True, slots=True)
class Status:
    """The operator-visible lifecycle. One state, not a set of flags.

    ``disarmed`` is the switch. The other three are initialisation.
    ``init_error`` is set only when the state is ``failed``.
    """

    state: LifecycleState
    armed: bool
    init_error: str | None = None


class EventSink(Protocol):
    """Accept one enforcement event. ``False`` means it was not written."""

    def emit(self, event: Mapping[str, object]) -> bool:
        """Append ``event``. Never raises."""
        ...


class InitGate:
    """Hold background initialisation until a test releases it.

    ``held`` stays in ``starting`` until ``release`` or ``fail``. ``failed``
    finishes initialisation in the failed state without building a pipeline.
    ``skip_wait`` marks the cold-start budget already spent, so a call does
    not block. A test that wants initialisation to finish during a call leaves
    ``skip_wait`` false and calls ``release`` from another thread.
    """

    def __init__(
        self,
        *,
        hold: bool = False,
        error: str | None = None,
        skip_wait: bool = False,
    ) -> None:
        self._event = threading.Event()
        self._error = error
        self.skip_wait = skip_wait
        self._lock = threading.Lock()
        if error is not None or not hold:
            self._event.set()

    @classmethod
    def held(cls, *, skip_wait: bool = False) -> InitGate:
        """Initialisation waits until ``release`` or ``fail``."""
        return cls(hold=True, skip_wait=skip_wait)

    @classmethod
    def failed(cls, error: str) -> InitGate:
        """Initialisation finishes failed with ``error``."""
        return cls(error=error)

    def wait(self) -> str | None:
        """Block until released. The return value is the failure, if any."""
        self._event.wait()
        with self._lock:
            return self._error

    def release(self) -> None:
        """Let initialisation build the pipeline."""
        with self._lock:
            self._error = None
            self.skip_wait = False
        self._event.set()

    def fail(self, error: str) -> None:
        """Finish initialisation as failed."""
        with self._lock:
            if self._error is None:
                self._error = error
        self._event.set()


class EvaluationFault:
    """Make later guard evaluations fail. ``None`` uses the real guard.

    ``timeout_s`` overrides the evaluation deadline while the fault is armed,
    so a test does not wait out the production deadline.
    """

    def __init__(self) -> None:
        self._kind: str | None = None
        self._timeout: float | None = None
        self._lock = threading.Lock()

    def arm(self, kind: str, *, timeout_s: float | None = None) -> None:
        """``kind`` is ``error`` or ``timeout``."""
        if kind not in ("error", "timeout"):
            raise ValueError("evaluation fault must be error or timeout")
        with self._lock:
            self._kind = kind
            self._timeout = timeout_s

    def current(self) -> tuple[str | None, float | None]:
        """The armed fault, or ``(None, None)`` when evaluation is real."""
        with self._lock:
            return self._kind, self._timeout
