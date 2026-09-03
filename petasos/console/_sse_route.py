"""The /api/events route builder shared by both console surfaces (PET-166 D13, PET-191).

One decision path for the standalone app and the Hermes bridge: scope resolution,
the two capacity refusals, and the stream response whose teardown releases the
slot it reserved. Top-level fastapi import is fine here: this module is only
imported from inside a route body or ``build_app``, after fastapi is known present
(the same shape as ``hermes/plugin_api.py``).
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse, Response, StreamingResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from starlette.types import Receive, Scope, Send

    from petasos.console.server import ConsoleHandlers

_logger = logging.getLogger(__name__)

_STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class LeasedStreamingResponse(StreamingResponse):
    """A StreamingResponse that releases a reserved slot when its ASGI call tears down.

    FastAPI's route wrapper awaits ``response(scope, receive, send)`` for every
    response an endpoint returns (see PET-191 spec, Decision 1), so this
    ``finally`` runs whether the body generator started or not. That is the
    property the route needs: a client that disconnects before the first body
    pull leaves the generator never started and its ``finally`` never runs, which
    is how the slot used to leak.

    ``release`` must be synchronous and must not raise; it is invoked exactly once
    per response call and need not be idempotent (the live arm's ``unsubscribe``
    happens to be, which is why a started generator's own ``finally`` is harmless;
    the idle arm's ``release_idle_slot`` is a counting operation and is not). It
    must close over the object it reserved from (the broadcaster instance, the
    handlers instance), never over a path through a mutable attribute.
    """

    def __init__(
        self,
        content: AsyncIterator[str],
        release: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(content, **kwargs)
        self._release = release

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # The base class's websocket branch drains the body iterator with no
        # disconnect listener and would never return for an endless stream, so this
        # `finally` would never be reached on it. Unreachable here: both events routes
        # are HTTP GET only, and a websocket scope with no matching route is denied by
        # the router before any endpoint runs.
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                self._release()
            except Exception:  # a broken release must never eat a CancelledError
                _logger.exception(
                    "PETASOS_STREAM_RELEASE_FAILED release=%r; a stream slot is now leaked "
                    "for the life of the process",
                    self._release,
                )


def events_response(handlers: ConsoleHandlers, profile: str | None) -> Response:
    """Build the /api/events response for BOTH surfaces (PET-166 D13, PET-191).

    Plain ``def`` with no suspension point: on each arm the capacity check and the
    reservation run back to back under the event loop, so no concurrent request
    can interleave (Decision 2; pinned by test). Every refusal is a JSON response
    built before any stream object exists (PET-166 D7/D9): the 422 for a
    non-member profile, the idle-arm 503 carrying ``scope_refusal: capacity`` (the
    D9 terminal marker), and the equipped-arm 503 left unmarked so the client's
    shipped retry-then-fallback path fires.
    """
    from petasos.console.server import ProfileNotFoundError

    try:
        scope = handlers.resolve_events_scope(profile)
    except ProfileNotFoundError as exc:
        # Both arguments by keyword, matching every shipped 422 site.
        return JSONResponse(
            status_code=422,
            content={"detail": [{"field": "profile", "message": str(exc)}]},
        )
    if scope.state != "equipped":
        if not handlers.reserve_idle_slot():
            return JSONResponse(
                status_code=503,
                content={
                    "detail": [{"field": "profile", "message": "idle scope streams at capacity"}],
                    "scope_refusal": "capacity",
                },
            )
        return LeasedStreamingResponse(
            handlers.idle_scope_stream(scope),
            handlers.release_idle_slot,
            media_type="text/event-stream",
            headers=_STREAM_HEADERS,
        )
    sse = handlers.sse  # captured now: the release must target the pool it reserved from
    try:
        q = sse.subscribe()
    except RuntimeError:
        # PET-166: a full subscriber pool used to 500 out of this route; it is an
        # honest 503 (unmarked -- the client's shipped retry path is correct here).
        return JSONResponse(
            status_code=503,
            content={"detail": [{"field": "profile", "message": "event stream at capacity"}]},
        )
    return LeasedStreamingResponse(
        sse.stream(q),
        functools.partial(sse.unsubscribe, q),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )
