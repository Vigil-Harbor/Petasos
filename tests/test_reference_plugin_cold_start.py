"""PET-167: bounded init wait + durable cold-start visibility in the deployment shim.

Before this ticket the first tool call of a cold process queued on ``_init_lock`` for the
full remaining backend verification (measured: unbounded, roughly 12s in production) and
then took the main path. Two consequences, both load-bearing:

  - ``_fallback_pre_tool_call`` was unreachable dead code, so the syntactic-only guard the
    cold window advertises never ran;
  - a one-shot invocation could start and finish inside that window having been enforced by
    nothing, and leave no record saying so.

The regression class guarded here is "a security control that reports itself active while
its enforcement path is unreachable". Tests 1, 7, 18 and 24 fail against 3f17365.

Backend-free: no ML pipeline. The reference plugin is not importable as a package, so each
test loads a FRESH module via ``spec_from_file_location`` — ``_init_done`` is sticky and
irreversible, so a shared module would leak state between tests.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import petasos.console._events as ev
from petasos import GuardResult, PetasosConfig, ScanFinding, ScanResult, Severity

if TYPE_CHECKING:
    import types
    from collections.abc import Iterator

_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)

_FAIL_MODES = ("open", "degraded", "closed")


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet167", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PETASOS_LICENSE_KEY", "PETASOS_SESSION_SECRET", "PETASOS_HASH_KEY"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _set(ref: types.ModuleType, name: str, value: Any) -> None:
    """Write a module global on the freshly imported shim.

    Direct attribute assignment on a ModuleType is rejected by ``mypy --strict``, and a
    setattr call with a literal attribute name by ruff's B010, so the name goes through a
    parameter. Used from background threads too, where a monkeypatch undo record would be
    the wrong shape anyway.
    """
    setattr(ref, name, value)


def _read_spool() -> list[dict[str, Any]]:
    """Every event on the (conftest-isolated) enforcement spool."""
    out: list[dict[str, Any]] = []
    try:
        with open(ev._spool_path(), encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    out.append(json.loads(s))
    except FileNotFoundError:
        return []
    return out


def _of_type(event_type: str) -> list[dict[str, Any]]:
    return [e for e in _read_spool() if e.get("event_type") == event_type]


def _finding(severity: Severity = Severity.CRITICAL) -> ScanFinding:
    return ScanFinding(
        rule_id="petasos.injection.x",
        finding_type="injection",
        severity=severity,
        confidence=0.9,
        message="injection finding",
        scanner_name="minimal",
    )


class _GuardSpy:
    """Permissive guard double. Required by test 38: ``_pre_tool_call`` wraps
    ``_guard.evaluate`` in an ``except Exception`` that logs and returns None, so a
    fall-through that crashes on ``_guard is None`` looks identical to "not blocked"."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def evaluate(self, tool_name: str, args: dict[str, Any], session_id: str) -> GuardResult:
        self.calls.append(tool_name)
        return GuardResult(
            allowed=True, reason="allowed", findings=(), tier="none", param_scan_unsafe=False
        )


def _open_window(
    monkeypatch: pytest.MonkeyPatch,
    ref: types.ModuleType,
    *,
    fail_mode: str | None = "degraded",
    budget: float = 0.05,
    thread_started: bool = True,
) -> None:
    """Put a freshly imported module into the cold window: init in flight, nothing done."""
    ref._reset_init_state()
    ref._reset_cold_start_records()
    config: dict[str, Any] = {"init_wait_timeout_seconds": budget}
    if fail_mode is not None:
        config["fail_mode"] = fail_mode
    monkeypatch.setattr(ref, "_is_armed", lambda: True)
    monkeypatch.setattr(ref, "_maybe_reconfigure", lambda: None)
    monkeypatch.setattr(ref, "_config", config)
    monkeypatch.setattr(ref, "_init_thread_started", thread_started)


def _install_fallback_scanner(
    monkeypatch: pytest.MonkeyPatch,
    ref: types.ModuleType,
    *,
    findings: tuple[ScanFinding, ...] = (),
    raises: bool = False,
    on_scan: Any = None,
) -> None:
    """Wire a stub MinimalScanner behind the fallback and run coroutines inline."""

    class _Stub:
        name = "minimal"

        async def scan(
            self, text: str, *, direction: str = "inbound", session_id: str | None = None
        ) -> ScanResult:
            if on_scan is not None:
                on_scan()
            if raises:
                raise RuntimeError("scan boom")
            return ScanResult(scanner_name="minimal", findings=findings)

    monkeypatch.setattr(ref, "_get_fallback_scanner", lambda: _Stub())
    monkeypatch.setattr(ref, "_run_async", lambda coro: asyncio.run(coro))


def _spy_fallback(monkeypatch: pytest.MonkeyPatch, ref: types.ModuleType) -> list[str]:
    """Record every ``_fallback_pre_tool_call`` invocation, delegating to the real one."""
    seen: list[str] = []
    real = ref._fallback_pre_tool_call

    def spy(tool_name: str, args: dict[str, Any], task_id: str, **kwargs: Any) -> Any:
        seen.append(tool_name)
        return real(tool_name, args, task_id, **kwargs)

    monkeypatch.setattr(ref, "_fallback_pre_tool_call", spy)
    return seen


def _complete_init_after(ref: types.ModuleType, delay: float) -> Iterator[threading.Thread]:
    def worker() -> None:
        time.sleep(delay)
        _set(ref, "_initialized", True)
        ref._init_done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    yield t


# ---------------------------------------------------------------------------
# Bounded wait (Decision 1)
# ---------------------------------------------------------------------------


def test_wait_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-167: the first cold call queued on _init_lock for the whole
    # remaining init. `_deferred_init` is stubbed to a 5s block so the pre-PET-167
    # implementation (which calls it synchronously) takes 5s where this one takes one
    # budget. The wall time is asserted from BOTH sides: > 0 so a zero-wait implementation
    # cannot pass, and well under the simulated init so an unbounded one cannot either.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, budget=0.2)
    monkeypatch.setattr(ref, "_deferred_init", lambda: time.sleep(5.0))

    t0 = time.monotonic()
    assert ref._ensure_initialized() is False
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.1, "a zero-wait implementation gives the scanners no chance at all"
    assert elapsed < 2.0, f"wait was not bounded by the budget: {elapsed:.2f}s"


def test_init_completing_inside_budget_takes_main_path(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, budget=5.0)
    guard = _GuardSpy()
    monkeypatch.setattr(ref, "_guard", guard)
    monkeypatch.setattr(ref, "_run_async", lambda coro: asyncio.run(coro))
    thread = next(_complete_init_after(ref, 0.05))

    t0 = time.monotonic()
    assert ref._ensure_initialized() is True
    assert time.monotonic() - t0 < 4.0, "returned as soon as init signalled, not at the deadline"
    thread.join(timeout=2.0)

    assert ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1") is None
    assert guard.calls == ["write_file"], "the main path ran, not the fallback"
    assert _of_type("cold_start_degraded") == []


def test_no_init_thread_runs_synchronously(monkeypatch: pytest.MonkeyPatch) -> None:
    # The escape hatch: a host that never called register() (or a rolled-back thread start)
    # has no background init to wait on, so today's synchronous in-line behavior is
    # preserved rather than waiting on an Event nobody will ever set.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, thread_started=False)
    ran: list[bool] = []

    def fake_init() -> None:
        ran.append(True)
        _set(ref, "_initialized", True)

    monkeypatch.setattr(ref, "_deferred_init", fake_init)

    assert ref._ensure_initialized() is True
    assert ran == [True]


def test_budget_is_process_wide_not_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    # A naive per-call budget charges N calls N budgets inside one cold window — on the
    # short-lived unattended surfaces this targets, a latency regression against today,
    # where the process pays the remaining init once and zero thereafter.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, budget=0.3)

    t0 = time.monotonic()
    for _ in range(3):
        assert ref._ensure_initialized() is False
    elapsed = time.monotonic() - t0
    assert elapsed < 0.9, f"three cold calls spent more than one budget: {elapsed:.2f}s"
    assert ref._init_wait_expired is True


def test_failed_thread_start_rolls_back_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    # register() sets _init_thread_started BEFORE start(). Unwrapped, a failed start latches
    # the flag with no _deferred_init behind it: _init_done is never set and every cold call
    # burns the budget on an init that will never happen.
    ref = _import_reference_plugin()
    ref._reset_init_state()
    monkeypatch.setattr(ref, "_load_config", lambda res=None: {})

    class _BoomThread:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("can't start new thread")

    class _Ctx:
        def __init__(self) -> None:
            self.hooks: list[str] = []

        def register_hook(self, name: str, handler: Any) -> None:
            self.hooks.append(name)

    # A namespace, not the real threading module: patching threading.Thread globally would
    # reach every other thread this process starts.
    fake_threading = type("T", (), {"Thread": _BoomThread})
    monkeypatch.setattr(ref, "threading", fake_threading)
    ref.register(_Ctx())

    assert ref._init_thread_started is False
    ran: list[bool] = []

    def fake_init() -> None:
        ran.append(True)
        _set(ref, "_initialized", True)

    monkeypatch.setattr(ref, "_deferred_init", fake_init)
    assert ref._ensure_initialized() is True
    assert ran == [True], "the escape hatch must apply, so the process self-heals"


def test_concurrent_first_callers_share_one_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    # The deadline is read ONCE into a local and `remaining` is computed from that local:
    # re-reading the global after assignment lets two threads racing the first wait compose
    # into a window of nearly two budgets.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, budget=0.3)
    results: list[bool] = []
    barrier = threading.Barrier(2)

    def caller() -> None:
        barrier.wait()
        results.append(ref._ensure_initialized())

    threads = [threading.Thread(target=caller) for _ in range(2)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    elapsed = time.monotonic() - t0

    assert results == [False, False]
    assert elapsed < 0.9, f"concurrent first callers composed past one budget: {elapsed:.2f}s"


def test_late_init_success_upgrades_to_main_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # The `_initialized` check must stay the FIRST statement in _ensure_initialized.
    # Hoisting the expiry latch above it would pin the process to the syntactic fallback
    # forever, even after every ML scanner came up — an indefinite silent enforcement
    # downgrade on a long-lived gateway or dashboard process.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)
    _install_fallback_scanner(monkeypatch, ref)
    seen = _spy_fallback(monkeypatch, ref)
    guard = _GuardSpy()
    monkeypatch.setattr(ref, "_guard", guard)

    assert ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1") is not None
    assert len(seen) == 1
    assert len(_of_type("cold_start_degraded")) == 1

    _set(ref, "_initialized", True)
    ref._init_done.set()

    assert ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1") is None
    assert len(seen) == 1, "the fallback must not run once init has landed"
    assert guard.calls == ["write_file"]
    assert len(_of_type("cold_start_degraded")) == 1, "no further marker after the upgrade"


# ---------------------------------------------------------------------------
# Fallback reachability (Decision 1)
# ---------------------------------------------------------------------------


def test_expired_wait_reaches_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-167: against 3f17365 this spy records ZERO calls — the fallback
    # was unreachable dead code.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)
    _install_fallback_scanner(monkeypatch, ref)
    seen = _spy_fallback(monkeypatch, ref)

    ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert seen == ["write_file"]


# ---------------------------------------------------------------------------
# fail_mode governance (Decision 2b) — one test per cell
# ---------------------------------------------------------------------------


def test_read_only_tool_never_blocks_in_window(monkeypatch: pytest.MonkeyPatch) -> None:
    # The block decision is _is_dangerous-gated BEFORE fail_mode is consulted, mirroring
    # the warm path. Without that gate the cold window would block read_file / search /
    # web_search / list_directory for its whole duration under the DEFAULT fail_mode —
    # strictly more aggressive than the warm path, on the tool class the warm path exempts
    # by design, and on the very first call of a typical one-shot session.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode="degraded")
    _install_fallback_scanner(monkeypatch, ref)

    assert ref._pre_tool_call("read_file", {"path": "x"}, task_id="s1") is None


def test_open_allows_clean_dangerous_call(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode="open")
    _install_fallback_scanner(monkeypatch, ref)

    assert ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1") is None


@pytest.mark.parametrize("fail_mode", ["degraded", "closed"])
def test_degraded_and_closed_block_clean_dangerous_call(
    monkeypatch: pytest.MonkeyPatch, fail_mode: str
) -> None:
    # The clean-scan row is the all_ml_failure case: during the window all three ML
    # scanners are unavailable, which _compute_safe maps to safe=False under
    # degraded/closed. Cold-window blocking is CONSISTENT with the steady state, not
    # harsher than it.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode=fail_mode)
    _install_fallback_scanner(monkeypatch, ref)

    out = ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert out is not None and out["action"] == "block"
    assert out["message"].startswith("[BLOCKED by Petasos]")


@pytest.mark.parametrize("fail_mode", _FAIL_MODES)
def test_scan_error_blocks_under_every_fail_mode(
    monkeypatch: pytest.MonkeyPatch, fail_mode: str
) -> None:
    # fail_mode-INDEPENDENT, `open` included. The warm-path analogue is guard.py's
    # `if result.errors and not result.findings: return (), True, True` — reached via the
    # inspect boundary in pipeline.py, which constructs errors with empty findings — a
    # deliberate fail-safe per its own comment, NOT pipeline.py's fail_mode-dependent
    # `syntactic_error` rule. Mirroring the latter would let the cold window allow a
    # dangerous call whose parameters were never successfully scanned while the warm path
    # on identical input blocks.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode=fail_mode)
    _install_fallback_scanner(monkeypatch, ref, raises=True)

    out = ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert out is not None and out["action"] == "block"


@pytest.mark.parametrize("fail_mode", _FAIL_MODES)
def test_syntactic_finding_blocks_under_every_fail_mode(
    monkeypatch: pytest.MonkeyPatch, fail_mode: str
) -> None:
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode=fail_mode)
    _install_fallback_scanner(monkeypatch, ref, findings=(_finding(),))

    out = ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert out is not None and out["action"] == "block"
    assert "Top finding:" in out["message"], "a finding-driven block names its finding"


@pytest.mark.parametrize("raw", [None, "Open", 0, "absent"])
def test_fail_mode_normalization(monkeypatch: pytest.MonkeyPatch, raw: Any) -> None:
    # fail_mode is read in the window from the RAW config dict, so it may be any YAML
    # scalar (or absent — _load_config returns {}). Anything that is not exactly the
    # string "open" is treated as degraded, mirroring _compute_safe's invalid-value
    # fallback: garbage fails secure by construction.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode=None if raw == "absent" else raw)
    _install_fallback_scanner(monkeypatch, ref)

    out = ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert out is not None and out["action"] == "block"


def test_fallback_state_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    # The fallback's signature and return type are unchanged — three distinct outcomes
    # still collapse to None in its RETURN value — so the branch reads them out of band.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)

    _install_fallback_scanner(monkeypatch, ref)
    assert ref._fallback_pre_tool_call("read_file", {"p": "x"}, "s1") is None
    assert ref._fallback_state.outcome == "skipped"

    assert ref._fallback_pre_tool_call("write_file", {"text": "x"}, "s1") is None
    assert ref._fallback_state.outcome == "clean"

    _install_fallback_scanner(monkeypatch, ref, findings=(_finding(),))
    assert ref._fallback_pre_tool_call("write_file", {"text": "x"}, "s1") is not None
    assert ref._fallback_state.outcome == "blocked"

    _install_fallback_scanner(monkeypatch, ref, raises=True)
    assert ref._fallback_pre_tool_call("write_file", {"text": "x"}, "s1") is None
    assert ref._fallback_state.outcome == "errored"


def test_missing_fallback_outcome_fails_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    # A threading.local() has no attribute until written, so a bare read would raise
    # AttributeError in a region of _pre_tool_call with no try around it and propagate into
    # the host. The read defaults to "errored", not "skipped" or "clean": a patched-out
    # fallback, a future unrecorded return path, or an escaping BaseException must not make
    # the expired-wait branch silently behave like `open`.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode="degraded")
    monkeypatch.setattr(ref, "_fallback_pre_tool_call", lambda *a, **k: None)

    out = ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert out is not None and out["action"] == "block"
    assert getattr(ref._fallback_state, "outcome", None) is None

    # ...but the read-only allow does NOT depend on the channel: _is_dangerous gates ahead
    # of the outcome read, so the fail-secure default can never mass-block read-only tools.
    assert ref._pre_tool_call("read_file", {"path": "x"}, task_id="s1") is None
    assert getattr(ref._fallback_state, "outcome", None) is None, (
        "a stale 'skipped' on a pooled thread maps to ALLOW, routing a later dangerous "
        "call around the fail-secure default"
    )


# ---------------------------------------------------------------------------
# Budget resolution (Decision 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("__missing__", 2.0),
        (None, 2.0),
        ("soon", 2.0),
        ([2], 2.0),
        (0, 2.0),
        (-1, 2.0),
        (float("nan"), 2.0),
        (float("inf"), 2.0),
        (1e300, 60.0),
        (0.001, 0.05),
        (120, 60.0),
        ("2.0", 2.0),
    ],
)
def test_init_wait_budget_sanitizes_raw_config(
    monkeypatch: pytest.MonkeyPatch, raw: Any, expected: float
) -> None:
    # The clamp is load-bearing, not belt-and-braces: Event.wait raises OverflowError on
    # inf / 1e300 and TypeError on a str, and this value reaches it directly. Note the
    # asymmetry the surface documents: 0 or negative falls back to the DEFAULT (2.0), not
    # to the 0.05 floor, so an operator writing 0 to mean "do not wait" gets the longest
    # commonly-configured value instead.
    ref = _import_reference_plugin()
    config: dict[str, Any] = {} if raw == "__missing__" else {"init_wait_timeout_seconds": raw}
    monkeypatch.setattr(ref, "_config", config)

    got = ref._init_wait_budget()
    assert got == expected
    assert isinstance(got, float) and math.isfinite(got)
    assert 0.05 <= got <= 60.0
    # ...and nothing raises when the value reaches the wait. An UNCONTENDED
    # Lock.acquire(True, timeout) runs the same _PyTime_t conversion Event.wait delegates
    # to (it is what Condition.wait calls), so it raises OverflowError on inf / 1e300
    # exactly as Event.wait does — but returns instantly instead of sleeping the budget.
    lock = threading.Lock()
    assert lock.acquire(True, got) is True
    lock.release()


def test_init_wait_budget_tolerates_none_config(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _import_reference_plugin()
    monkeypatch.setattr(ref, "_config", None)
    assert ref._init_wait_budget() == 2.0


@pytest.mark.parametrize("bad", [0, -1.0, 61.0, float("nan"), float("inf")])
def test_init_wait_timeout_seconds_validation(bad: float) -> None:
    with pytest.raises(ValueError, match="init_wait_timeout_seconds"):
        PetasosConfig(init_wait_timeout_seconds=bad)


def test_init_wait_timeout_seconds_default_accepted() -> None:
    assert PetasosConfig().init_wait_timeout_seconds == 2.0
    assert PetasosConfig(init_wait_timeout_seconds=60.0).init_wait_timeout_seconds == 60.0


# ---------------------------------------------------------------------------
# Visibility (Decisions 4, 5)
# ---------------------------------------------------------------------------


def test_cold_start_degraded_emitted_once_per_session(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-167: against 3f17365 the spool stays empty — the session ran with
    # no ML scanners and left no evidence of it.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)
    _install_fallback_scanner(monkeypatch, ref)

    for _ in range(3):
        ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert len(_of_type("cold_start_degraded")) == 1


def test_read_only_only_session_still_records(monkeypatch: pytest.MonkeyPatch) -> None:
    # The marker is emitted BEFORE the dispatch and independent of _is_dangerous: the
    # fallback returns early for read-only tools without scanning, so keying the record on
    # the dispatch's outcome would leave a read_file-only cold session with no record.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)
    _install_fallback_scanner(monkeypatch, ref)

    assert ref._pre_tool_call("read_file", {"path": "x"}, task_id="s1") is None
    assert len(_of_type("cold_start_degraded")) == 1


def test_escape_hatch_path_still_records(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keying on "the wait just expired" would miss the no-init-in-flight escape hatch,
    # where a synchronous _deferred_init left _initialized False. That is a one-shot
    # invocation that neither completed with full scanners nor left a record.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, thread_started=False)
    _install_fallback_scanner(monkeypatch, ref)
    monkeypatch.setattr(ref, "_deferred_init", lambda: None)

    ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    markers = _of_type("cold_start_degraded")
    assert len(markers) == 1
    assert "no init in flight" in markers[0]["reason"], (
        "the opener must name this trigger: no wait ever ran here, and a cause-neutral "
        "opener alone sends an operator chasing a timeout that never happened"
    )


def test_uncorrelatable_session_emits_exactly_once_per_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With no task_id and no _agent, _derive_session_id mints a fresh anon-<uuid> per call,
    # which would defeat the latch entirely. Asserted as == 1, not "does not scale with
    # call count": the weaker phrasing is satisfied by ZERO, so it would go green against
    # an implementation that never emits for the uncorrelatable shape at all.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)
    _install_fallback_scanner(monkeypatch, ref)

    for _ in range(5):
        ref._pre_tool_call("write_file", {"text": "x"})
    assert len(_of_type("cold_start_degraded")) == 1


def test_latch_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    # Driven through the helper directly: 10,001 full _pre_tool_call invocations through
    # _run_async would be a multi-minute test.
    ref = _import_reference_plugin()
    ref._reset_cold_start_records()
    cap = ref._MAX_COLD_START_KEYS

    for i in range(cap + 5):
        assert ref._note_cold_start_session(f"s{i}", "cold_start_degraded") is True
    assert len(ref._cold_start_records) <= cap
    assert ("s0", "cold_start_degraded") not in ref._cold_start_records, "oldest key evicted"
    assert (f"s{cap + 4}", "cold_start_degraded") in ref._cold_start_records


def test_degraded_then_init_failed_records_both(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keyed on (session_id, event_type), not session_id: a single per-session key silently
    # swallows the more severe state. The wait expires and records cold_start_degraded;
    # init then FAILS; the session's next call wants init_failed and would be suppressed,
    # leaving the operator with "ran without ML scanners" for a session that actually ran
    # with no enforcement at all.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)
    _install_fallback_scanner(monkeypatch, ref)

    ref._pre_tool_call("read_file", {"path": "x"}, task_id="s1")
    _set(ref, "_init_error", "boom")
    assert ref._pre_tool_call("read_file", {"path": "x"}, task_id="s1") is None

    assert len(_of_type("cold_start_degraded")) == 1
    assert len(_of_type("init_failed")) == 1


def test_blocking_cold_call_emits_block_class_event(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-167: block-class or the console renders a real enforcement block
    # as a green "safe" row. _BLOCK_EVENT_TYPES drives the blocked tile, the per-session
    # block tally and the red badge.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode="degraded")
    _install_fallback_scanner(monkeypatch, ref)

    out = ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert out is not None and out["action"] == "block"
    quarantines = _of_type("quarantine")
    assert len(quarantines) == 1
    assert quarantines[0]["param_scan_degraded"] is True
    assert quarantines[0]["tool"] == "write_file"


def test_syntactic_finding_block_emits_exactly_one_quarantine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The finding-driven path already emits its own quarantine inside the fallback; adding
    # the no-finding block's event there would double-count the block tally and the tile.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode="degraded")
    _install_fallback_scanner(monkeypatch, ref, findings=(_finding(),))

    out = ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert out is not None and out["action"] == "block"
    assert len(_of_type("quarantine")) == 1


def test_init_failed_emits_record_and_still_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    # The allow/deny behavior of this branch is UNCHANGED: this makes a total, silent
    # enforcement loss visible, it does not start blocking.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)
    _set(ref, "_init_error", "No module named 'x'")

    assert ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1") is None
    records = _of_type("init_failed")
    assert len(records) == 1
    assert "No module named 'x'" in records[0]["reason"]


def test_empty_exception_message_still_latches_visibly(monkeypatch: pytest.MonkeyPatch) -> None:
    # `str(exc)` is "" for a bare `raise ImportError()`, and an empty string is falsy: a
    # truthiness test would read the latch as "still initializing" forever, recording
    # cold_start_degraded for a session whose init has permanently failed and never
    # recording init_failed.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)

    class _BoomConfig(dict):  # type: ignore[type-arg]
        def pop(self, *args: Any, **kwargs: Any) -> Any:
            raise ImportError

    monkeypatch.setattr(ref, "_config", _BoomConfig({"x": 1}))
    ref._deferred_init()

    assert ref._init_error == "ImportError"
    assert ref._init_done.is_set(), "the finally wraps the WHOLE body, including this exit"

    monkeypatch.setattr(ref, "_config", {})
    assert ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1") is None
    assert len(_of_type("init_failed")) == 1
    assert _of_type("cold_start_degraded") == [], "a failed init is not 'still starting'"


def test_session_starting_and_ending_inside_window(monkeypatch: pytest.MonkeyPatch) -> None:
    # The ticket's explicit acceptance test: a whole one-shot session lives and dies inside
    # the cold window. Asserts BEHAVIOR, not merely the absence of a crash.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode="degraded")
    _install_fallback_scanner(monkeypatch, ref)

    assert ref._pre_tool_call("read_file", {"path": "a"}, task_id="one-shot") is None
    blocked = ref._pre_tool_call("write_file", {"text": "x"}, task_id="one-shot")
    assert blocked is not None and blocked["action"] == "block"
    assert ref._pre_tool_call("search", {"q": "x"}, task_id="one-shot") is None

    assert len(_of_type("cold_start_degraded")) == 1, "one durable record for the session"
    assert len(_of_type("quarantine")) == 1, "the block is separately visible"


def test_record_reason_fits_and_states_caveats(monkeypatch: pytest.MonkeyPatch) -> None:
    # Asserted against the DRAINED summary, not the raw emit, so the read path's 200-char
    # hard slice is actually exercised. The slice is a PREFIX, so it amputates from the end:
    # the clause the authored copy must keep inside the cap is the trailing
    # "syntactic only, dangerous tools only, params only (100k cap)" scope caveat.
    pytest.importorskip("fastapi")
    from petasos.console.server import _enforcement_summary

    ref = _import_reference_plugin()

    # 1. cold_start_degraded, wait-expired variant + the 4a quarantine.
    _open_window(monkeypatch, ref, fail_mode="degraded")
    _install_fallback_scanner(monkeypatch, ref)
    ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    # 2. cold_start_degraded, escape-hatch variant (a fresh module: the latch is per key).
    ref2 = _import_reference_plugin()
    _open_window(monkeypatch, ref2, thread_started=False)
    _install_fallback_scanner(monkeypatch, ref2)
    monkeypatch.setattr(ref2, "_deferred_init", lambda: None)
    ref2._pre_tool_call("read_file", {"path": "x"}, task_id="s2")
    # 3. init_failed, with a long third-party error to exercise the 60-char truncation.
    ref3 = _import_reference_plugin()
    _open_window(monkeypatch, ref3)
    _set(ref3, "_init_error", "Z" * 400)
    ref3._pre_tool_call("read_file", {"path": "x"}, task_id="s3")

    summaries = [_enforcement_summary(e) for e in _read_spool()]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for s in summaries:
        by_type.setdefault(str(s["event_type"]), []).append(s)
    assert set(by_type) == {"cold_start_degraded", "init_failed", "quarantine"}
    assert len(by_type["cold_start_degraded"]) == 2, "both variants present"

    # All four classes: within the cap, and no em dash in the authored copy.
    for rows in by_type.values():
        for row in rows:
            reason = str(row["reason"])
            assert len(reason) <= 200
            assert "—" not in reason

    # The caveats are carried by the two cold_start_degraded variants only; init_failed and
    # the 4a quarantine carry none by design.
    for row in by_type["cold_start_degraded"]:
        reason = str(row["reason"])
        # PET-170 re-worded this assertion; PET-167's Done-when 8 is RESTATED, not dropped.
        # The cold window must still record that tool results went unscanned DURING it.
        # The "(warm path too)" parenthetical came out because PET-170 made it false: the
        # warm path now scans ingestion-tool results at transform_tool_result.
        assert "tool results unscanned" in reason, (
            "Done-when 8 (PET-167, restated by PET-170): the cold window records that tool "
            "results went unscanned during it"
        )
        assert "warm path too" not in reason, (
            "PET-170: the warm path scans ingestion-tool results now, so the claim is stale"
        )
        assert "syntactic only" in reason
        assert "dangerous tools only" in reason
        assert "100k cap" in reason


# ---------------------------------------------------------------------------
# Invariants (Decisions 1d, 4)
# ---------------------------------------------------------------------------


def test_emission_failure_does_not_change_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    # The WRITER is forced to raise, not the shim's _emit_enforcement_event: monkeypatching
    # the shim function replaces the very try/except the design relies on, and the new call
    # sites sit in an unguarded region of _pre_tool_call, so the weaker version of this test
    # would propagate into the host.
    def boom(_rec: dict[str, Any]) -> bool:
        raise OSError("spool is on fire")

    monkeypatch.setattr(ev, "emit_enforcement_event", boom)

    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode="degraded")
    _install_fallback_scanner(monkeypatch, ref)

    out = ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert out is not None and out["action"] == "block"
    assert ref._pre_tool_call("read_file", {"path": "x"}, task_id="s1") is None


def test_disarmed_skips_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    # _is_armed() still gates ABOVE the init check, so a disarmed boot pays no wait, runs
    # no fallback scan, and leaves no cold-start record.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)
    monkeypatch.setattr(ref, "_is_armed", lambda: False)
    _install_fallback_scanner(monkeypatch, ref)
    seen = _spy_fallback(monkeypatch, ref)

    assert ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1") is None
    assert seen == []
    assert ref._init_wait_deadline is None, "no wait was entered"
    assert _of_type("cold_start_degraded") == []
    assert _of_type("init_failed") == []


def test_failed_spool_write_does_not_consume_the_latch(monkeypatch: pytest.MonkeyPatch) -> None:
    # Claim-then-release. A plain claim-then-emit would consume the key, land no row, and
    # deduplicate every later call in that session away — the session ran degraded with
    # zero durable evidence, the exact silent failure the record class exists to prevent.
    monkeypatch.setattr(ev, "emit_enforcement_event", lambda _rec: False)

    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref)
    _install_fallback_scanner(monkeypatch, ref)
    attempts: list[str] = []
    real = ref._emit_enforcement_event

    def spy(**kwargs: Any) -> bool:
        attempts.append(str(kwargs.get("event_type")))
        return bool(real(**kwargs))

    monkeypatch.setattr(ref, "_emit_enforcement_event", spy)

    # (a) a keyed session retries on the next call.
    ref._pre_tool_call("read_file", {"path": "x"}, task_id="s1")
    ref._pre_tool_call("read_file", {"path": "x"}, task_id="s1")
    assert attempts.count("cold_start_degraded") == 2

    # (b) the uncorrelatable shape must release its process-wide boolean too; without that,
    # one failed write latches the process out of ever recording the marker again.
    attempts.clear()
    ref._pre_tool_call("read_file", {"path": "x"})
    ref._pre_tool_call("read_file", {"path": "x"})
    assert attempts.count("cold_start_degraded") == 2

    # (c) a key the cap already evicted: the release must pop, never del, or the KeyError
    # propagates through a region with no try around it.
    assert ref._note_cold_start_session("gone", "cold_start_degraded") is True
    ref._cold_start_records.clear()
    ref._release_cold_start_claim("gone", "cold_start_degraded")


def test_init_completing_during_fallback_scan_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The TOCTOU window spans the whole fallback scan (its _run_async carries a 15s
    # timeout), not microseconds. Blocking a dangerous call on the grounds that scanners
    # were not up, seconds after they came up, is a user-visible false block whose
    # model-facing message is untrue when emitted.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode="degraded")
    guard = _GuardSpy()
    monkeypatch.setattr(ref, "_guard", guard)

    def land_init() -> None:
        _set(ref, "_initialized", True)
        ref._init_done.set()

    _install_fallback_scanner(monkeypatch, ref, on_scan=land_init)

    out = ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert out is None, "init landed mid-scan; the block would be false"
    # Required: _pre_tool_call wraps _guard.evaluate in an except Exception that logs and
    # returns None, so a fall-through that crashes on `_guard is None` looks identical.
    assert guard.calls == ["write_file"], "the main path actually ran"


def test_finding_driven_block_survives_the_same_race(monkeypatch: pytest.MonkeyPatch) -> None:
    # Scoped to the 4a no-finding block only. The finding-driven path shares the return
    # site but has already written its quarantine, so falling through there would discard
    # the block while leaving a block-class row on the console for a call that was allowed.
    ref = _import_reference_plugin()
    _open_window(monkeypatch, ref, fail_mode="degraded")
    guard = _GuardSpy()
    monkeypatch.setattr(ref, "_guard", guard)

    def land_init() -> None:
        _set(ref, "_initialized", True)
        ref._init_done.set()

    _install_fallback_scanner(monkeypatch, ref, findings=(_finding(),), on_scan=land_init)

    out = ref._pre_tool_call("write_file", {"text": "x"}, task_id="s1")
    assert out is not None and out["action"] == "block"
    assert len(_of_type("quarantine")) == 1
    assert guard.calls == [], "a justified block is returned, not re-decided by the guard"
