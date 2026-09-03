"""PET-191: the ``/api/events`` slot lease, on both console surfaces.

A slot reserved by the route used to be released only by the stream generator's
``finally``, which never runs when the generator is never started. This module
pins the replacement: the reservation is bound to the response's ASGI call, whose
``finally`` runs whether the generator started or not, and the idle arm's counter
moves onto the same primitive (retiring the PET-166 D9 check-then-act over-admit).

Discipline for this file, because every non-refusal call now reserves a real slot:

1. Every ``LeasedStreamingResponse`` a test builds is driven to teardown (or its
   counters reset) before the next assertion.
2. Tests that call ``__call__`` directly build the app or handlers OUTSIDE any
   ``TestClient`` context, on the test's own loop: ``asyncio.Queue`` is loop-bound
   and ``TestClient`` runs the app on a portal thread's loop. Startup (including
   the standalone ``_enforcement_tailer`` task) then does not run, which is what
   you want during a pool-count assertion.
3. No ``TestClient`` streaming of a live SSE route anywhere: the routes never
   complete by design, so a client-side read loop hangs the suite.
4. The ASGI scope handed to a direct ``__call__`` is explicit about
   ``asgi.spec_version`` (it selects the ``StreamingResponse.__call__`` branch),
   and every direct ``__call__`` gets an async ``send``: ``Response.__call__``
   sends two messages unconditionally even though it never reads ``receive``.
"""

import ast
import asyncio
import inspect
import json
import logging
import platform
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

import petasos.console._armed as armed_mod  # noqa: E402
import petasos.console._history as history_mod  # noqa: E402
import petasos.console._paths as paths_mod  # noqa: E402
import petasos.console.hermes.plugin_api as plugin_mod  # noqa: E402
import petasos.console.server as server_mod  # noqa: E402
from petasos.config import PetasosConfig  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402


def _make_pipeline() -> Pipeline:
    return Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="degraded"))


@pytest.fixture()
def profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Two real profile homes with alpha equipped (the sibling module's fixture shape)."""
    saved_spool = paths_mod._SPOOL_PATH_OVERRIDE
    saved_hist = history_mod._HISTORY_PATH_OVERRIDE
    paths_mod._SPOOL_PATH_OVERRIDE = None
    history_mod._HISTORY_PATH_OVERRIDE = None
    monkeypatch.delenv("HERMES_HOME", raising=False)
    if platform.system() == "Windows":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    else:
        monkeypatch.setenv("HOME", str(tmp_path))
    root = paths_mod.hermes_root()
    for name in ("alpha", "beta"):
        d = root / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text("petasos:\n  enabled: true\n", encoding="utf-8")
    (root / "active_profile").write_text("alpha", encoding="utf-8")
    armed_mod._reset_armed_cache()
    try:
        yield root
    finally:
        paths_mod._SPOOL_PATH_OVERRIDE = saved_spool
        history_mod._HISTORY_PATH_OVERRIDE = saved_hist
        armed_mod._reset_armed_cache()


def _handlers_of(app: Any) -> Any:
    """Reach build_app's handlers through a live route closure (the sibling idiom)."""
    for route in app.routes:
        closure = getattr(getattr(route, "endpoint", None), "__closure__", None) or ()
        for cell in closure:
            if isinstance(cell.cell_contents, server_mod.ConsoleHandlers):
                return cell.cell_contents
    raise AssertionError("handlers not reachable")


def _asgi_app(surface: str) -> tuple[Any, Any, str]:
    """(app, handlers, path) for a surface, built OUTSIDE TestClient (discipline 2)."""
    if surface == "standalone":
        app = server_mod.build_app(_make_pipeline())
        return app, _handlers_of(app), "/api/events"
    from fastapi import FastAPI

    plugin_mod.init_handlers(_make_pipeline())
    app = FastAPI()
    app.include_router(plugin_mod.router)
    return app, plugin_mod._handlers, "/events"


def _http_scope(path: str, spec_version: str, query: bytes = b"") -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 51234),
        "server": ("testserver", 80),
    }


async def _disconnect_receive() -> dict[str, Any]:
    """A ``receive`` that reports the client is already gone, without suspending.

    This is uvicorn 0.48.0's own behaviour once ``RequestResponseCycle.disconnected``
    is set: the ``message_event.wait()`` is skipped and ``http.disconnect`` returns
    immediately (``h11_impl.py``). It is what an early client abort looks like to the app.
    """
    return {"type": "http.disconnect"}


async def _noop_send(message: dict[str, Any]) -> None:
    return None


# ── T-5 / T-6: ASGI-level reachability (Decision 7) ────────────────────────
#
# These two drive the REAL route, not the builder, so they are the only tests in
# this module that can run against the pre-fix tree; their pre-fix outcome is
# recorded in docs/specs/TODO/PET-191.test-output.txt.
#
# Measured pre-fix at c5ef6d9, and it revises the spec's Decision 7 hypothesis:
#
#   spec_version 2.3, working send  -> generator STARTS, pool 0   (no leak)
#   spec_version 2.3, send raises   -> generator never starts, pool 1  (LEAK)
#   spec_version 2.4, working send  -> generator starts, pool 0
#   spec_version 2.4, send raises   -> generator never starts, pool 1  (LEAK)
#
# So an immediate disconnect on the shipped host does NOT strand a generator:
# starlette's task group lets the ``start_soon``'d ``stream_response`` reach its
# first ``send`` before the cancel lands. The never-started generator comes from a
# ``send`` that fails at ``http.response.start``, and that leaks on BOTH branches,
# the shipped 2.3 one included. uvicorn 0.48.0's own h11 ``send`` returns early
# when ``disconnected`` is set rather than raising, so this is not reachable from
# a bare uvicorn client abort; it is reachable through any host, ASGI middleware,
# or transport whose ``send`` raises there. T-5 stays as the regression pin for
# the disconnect path.


@pytest.mark.parametrize("surface", ["standalone", "plugin"])
async def test_early_disconnect_leaves_no_leaked_slot(profiles: Path, surface: str) -> None:
    """T-5: an immediate client disconnect on the shipped host (uvicorn 0.48.0 h11
    advertises spec_version "2.3", so starlette takes the anyio task-group branch).

    Measured green pre-fix: ``stream_response`` reaches ``send`` and the body
    generator starts, so its own ``finally`` unsubscribes. Kept as the pin that the
    lease does not regress the path that already worked."""
    plugin_mod._handlers = None
    try:
        app, handlers, path = _asgi_app(surface)
        await app(_http_scope(path, "2.3"), _disconnect_receive, _noop_send)
        assert len(handlers.sse._subscribers) == 0
    finally:
        plugin_mod._handlers = None


@pytest.mark.parametrize("surface", ["standalone", "plugin"])
@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_failing_response_start_leaves_no_leaked_slot(
    profiles: Path, surface: str, spec_version: str
) -> None:
    """T-6: ``send`` raising at ``http.response.start``. This is the trigger that
    actually strands a never-started generator, and it does so on both starlette
    branches: on 2.4 the ``OSError`` becomes ``ClientDisconnect`` before ``async
    for`` begins, on 2.3 it escapes the task group from the same point. Pre-fix both
    leaked one slot on both surfaces.

    The load-bearing assertion is the post-call pool count, not the exception type."""
    from starlette.requests import ClientDisconnect

    plugin_mod._handlers = None
    try:
        app, handlers, path = _asgi_app(surface)

        async def _broken_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                raise OSError("client gone")

        with pytest.raises((ClientDisconnect, OSError)):
            await app(_http_scope(path, spec_version), _disconnect_receive, _broken_send)
        assert len(handlers.sse._subscribers) == 0
    finally:
        plugin_mod._handlers = None


# ── Builder-level behaviour ────────────────────────────────────────────────


def _handlers_only() -> Any:
    """Bare handlers on the test's own loop (no app, no TestClient)."""
    return server_mod.ConsoleHandlers(_make_pipeline())


async def _tear_down(response: Any, spec_version: str = "2.3") -> None:
    """Drive a built response through one ASGI call so its lease releases."""
    await response(_http_scope("/api/events", spec_version), _disconnect_receive, _noop_send)


async def test_equipped_responses_torn_down_leave_pool_empty(profiles: Path) -> None:
    """T-2: max_subscribers + 2 equipped-arm responses. The first max_subscribers are
    leases, the last two are the unmarked 503. Tearing all of them down empties the
    live pool and the next subscribe() succeeds."""
    from petasos.console._sse_route import LeasedStreamingResponse, events_response

    h = _handlers_only()
    bound = h.sse.max_subscribers
    built = [events_response(h, None) for _ in range(bound + 2)]

    assert all(isinstance(r, LeasedStreamingResponse) for r in built[:bound])
    assert len(h.sse._subscribers) == bound
    for overflow in built[bound:]:
        assert overflow.status_code == 503
        assert b"scope_refusal" not in overflow.body  # equipped arm stays unmarked

    for response in built:
        await _tear_down(response)

    assert len(h.sse._subscribers) == 0
    h.sse.unsubscribe(h.sse.subscribe())  # the pool admits again


async def test_idle_responses_torn_down_leave_counter_at_zero(profiles: Path) -> None:
    """T-3: the idle arm, same shape. Replaces the deleted
    ``test_abandoned_idle_response_holds_no_slot``, whose meaning this carries."""
    from petasos.console._sse_route import LeasedStreamingResponse, events_response

    h = _handlers_only()
    bound = h.sse.max_subscribers
    built = [events_response(h, "beta") for _ in range(bound + 2)]

    assert all(isinstance(r, LeasedStreamingResponse) for r in built[:bound])
    assert h._idle_stream_count == bound
    for overflow in built[bound:]:
        assert overflow.status_code == 503
        assert json.loads(overflow.body)["scope_refusal"] == "capacity"

    for response in built:
        await _tear_down(response)

    assert h._idle_stream_count == 0
    assert len(h.sse._subscribers) == 0  # the idle arm never touches the live pool


@pytest.mark.parametrize("arm", ["idle", "equipped"])
async def test_started_then_closed_releases_exactly_once(profiles: Path, arm: str) -> None:
    """T-4: the normal path. Drive a lease to a first body frame, then disconnect, and
    assert the pool is empty afterwards. On the idle arm the generator no longer touches
    the counter at all, so the started and never-started paths land on a single
    ``release_idle_slot()`` from the teardown; on the live arm the generator's own
    ``unsubscribe`` is the harmless (idempotent) second call."""
    from petasos.console._sse_route import events_response

    h = _handlers_only()
    response = events_response(h, "beta" if arm == "idle" else None)
    if arm == "equipped":
        assert len(h.sse._subscribers) == 1
    else:
        assert h._idle_stream_count == 1

    gone = asyncio.Event()
    frames: list[bytes] = []
    polled = False

    async def receive() -> dict[str, Any]:
        # First call answers immediately so listen_for_disconnect keeps waiting; every
        # later call SUSPENDS on `gone` (a receive that never suspends busy-loops the
        # task group and the stream task never gets to run).
        nonlocal polled
        if not polled:
            polled = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            frames.append(message["body"])
            gone.set()

    if arm == "equipped":
        # The live arm only yields once something is broadcast to its queue.
        async def feed() -> None:
            await asyncio.sleep(0)
            await h.sse.broadcast("ping", {"hello": "world"})

        await asyncio.gather(response(_http_scope("/api/events", "2.3"), receive, send), feed())
    else:
        await response(_http_scope("/api/events", "2.3"), receive, send)

    assert frames  # the generator really started
    assert h._idle_stream_count == 0
    assert len(h.sse._subscribers) == 0


async def test_idle_over_admit_is_retired(profiles: Path) -> None:
    """T-8: check and reserve are one step, so the second concurrent open is refused
    rather than admitted. Pre-fix both would have been admitted."""
    from petasos.console._sse_route import LeasedStreamingResponse, events_response

    h = _handlers_only()
    bound = h.sse.max_subscribers
    h._idle_stream_count = bound - 1

    first = events_response(h, "beta")
    assert isinstance(first, LeasedStreamingResponse)
    assert h._idle_stream_count == bound  # reserved by the builder, not the generator

    second = events_response(h, "beta")
    assert second.status_code == 503
    assert json.loads(second.body)["scope_refusal"] == "capacity"

    await _tear_down(first)
    assert h._idle_stream_count == bound - 1


async def test_idle_refusal_logs_a_warning(
    profiles: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """T-11: a refused idle open leaves the same log evidence the live pool already
    does (``SSEBroadcaster.subscribe``'s limit WARNING). It was silent before."""
    from petasos.console._sse_route import events_response

    h = _handlers_only()
    h._idle_stream_count = h.sse.max_subscribers
    with caplog.at_level(logging.WARNING):
        refused = events_response(h, "beta")
    assert refused.status_code == 503
    assert any("idle scope stream limit reached" in r.getMessage() for r in caplog.records)


# ── Structural pins ───────────────────────────────────────────────────────


def _routes_under_test() -> list[tuple[str, Any]]:
    """(label, route) for every /api/events route surface this repo defines."""

    def events_route(app: Any, path: str) -> Any:
        for route in app.routes:
            if getattr(route, "path", None) == path:
                return route
        raise AssertionError(f"no route at {path}")

    plugin_mod._handlers = None
    try:
        return [
            ("standalone", events_route(server_mod.build_app(_make_pipeline()), "/api/events")),
            (
                "standalone-token",
                events_route(
                    server_mod.build_app(_make_pipeline(), auth_token="t"), "/api/events"
                ),
            ),
            ("plugin", events_route(plugin_mod.router, "/events")),
        ]
    finally:
        plugin_mod._handlers = None


def test_check_and_reserve_have_no_suspension_point(profiles: Path) -> None:
    """T-9: atomicity as an AST fact, not prose. A plain ``def`` whose body contains no
    await/async-for/async-with cannot be interleaved between its check and its
    reservation under a single event loop."""
    from petasos.console._sse_route import events_response

    for fn in (events_response, server_mod.ConsoleHandlers.reserve_idle_slot):
        assert inspect.iscoroutinefunction(fn) is False, fn
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        offenders = [
            type(n).__name__
            for n in ast.walk(tree)
            if isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith))
        ]
        assert offenders == [], f"{fn.__qualname__} gained a suspension point: {offenders}"


def test_both_routes_delegate_to_the_shared_builder(profiles: Path) -> None:
    """T-10: with one builder, equal behaviour on both surfaces is structural. T-7 is
    the behavioural half."""
    for label, route in _routes_under_test():
        tree = ast.parse(textwrap.dedent(inspect.getsource(route.endpoint)))
        called = {
            n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        }
        assert "events_response" in called, f"{label} does not delegate: {called}"
        assert "subscribe" not in called, f"{label} kept the old inline shape"
        assert "idle_scope_stream" not in called, f"{label} kept the old inline shape"


def test_no_events_route_has_a_function_scoped_generator_dependency(profiles: Path) -> None:
    """T-12: the Decision 1 precondition, pinned. FastAPI awaits a returned response
    unconditionally only because the route's function-scoped exit stack is empty; a
    ``Depends`` with ``yield`` and ``scope="function"`` would put a suspension point (and
    a raise site) between the endpoint returning and ``await response(...)``.

    Limit, stated plainly: this covers this repo's route definitions and the standalone
    app's own composition. A host that mounts the bridge router with its own
    function-scoped ``yield`` dependency would reopen the leak on both arms, and that
    composition is outside what this repo can pin."""

    def walk(dependant: Any) -> list[Any]:
        found = [dependant]
        for sub in dependant.dependencies:
            found.extend(walk(sub))
        return found

    for label, route in _routes_under_test():
        for dep in walk(route.dependant):
            is_gen = getattr(dep, "is_gen_callable", False) or getattr(
                dep, "is_async_gen_callable", False
            )
            assert not (is_gen and getattr(dep, "scope", None) == "function"), (
                f"{label}: {dep.call!r} is a function-scoped generator dependency; "
                "the PET-191 lease no longer releases unconditionally"
            )
