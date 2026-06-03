"""Server-Sent Events broadcaster with asyncio Queue fan-out."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_logger = logging.getLogger(__name__)

_SENTINEL = object()


class SSEBroadcaster:
    """Fan-out SSE events to multiple subscriber queues."""

    def __init__(self, *, max_subscribers: int = 10) -> None:
        self._subscribers: list[asyncio.Queue[Any]] = []
        self._max_subscribers = max_subscribers
        self._seq = 0

    def subscribe(self) -> asyncio.Queue[Any]:
        if len(self._subscribers) >= self._max_subscribers:
            _logger.warning("SSE subscriber limit reached (%d), rejecting", self._max_subscribers)
            raise RuntimeError("Too many SSE subscribers")
        q: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Any]) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(q)

    async def broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        self._seq += 1
        payload = {**data, "seq": self._seq}
        msg = f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
        for q in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(msg)

    async def stream(self, q: asyncio.Queue[Any]) -> AsyncIterator[str]:
        """Yield SSE-formatted lines. Sends keepalive every 15s."""
        first_keepalive = True
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    if msg is _SENTINEL:
                        return
                    yield msg
                except TimeoutError:
                    if first_keepalive:
                        yield "retry: 5000\n:keepalive\n\n"
                        first_keepalive = False
                    else:
                        yield ":keepalive\n\n"
        finally:
            self.unsubscribe(q)

    async def shutdown(self) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                while not q.empty():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(_SENTINEL)
        self._subscribers.clear()
