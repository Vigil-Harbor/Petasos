"""Tests for petasos.console._sse."""

import json

import pytest

from petasos.console._sse import SSEBroadcaster

pytestmark = pytest.mark.asyncio


async def test_subscribe_and_broadcast() -> None:
    sse = SSEBroadcaster()
    q = sse.subscribe()
    await sse.broadcast("test_event", {"key": "value"})
    msg = q.get_nowait()
    assert "event: test_event" in msg
    data_line = [line for line in msg.split("\n") if line.startswith("data:")][0]
    payload = json.loads(data_line[len("data: ") :])
    assert payload["key"] == "value"
    assert "seq" in payload


async def test_unsubscribe_removes_queue() -> None:
    sse = SSEBroadcaster()
    q = sse.subscribe()
    sse.unsubscribe(q)
    await sse.broadcast("test_event", {"x": 1})
    assert q.empty()


async def test_full_queue_silently_dropped() -> None:
    sse = SSEBroadcaster(max_subscribers=5)
    q = sse.subscribe()
    for i in range(300):
        await sse.broadcast("flood", {"i": i})
    assert q.qsize() == 256


async def test_subscriber_limit() -> None:
    sse = SSEBroadcaster(max_subscribers=2)
    sse.subscribe()
    sse.subscribe()
    with pytest.raises(RuntimeError, match="Too many"):
        sse.subscribe()


async def test_shutdown_sends_sentinel() -> None:
    sse = SSEBroadcaster()
    q = sse.subscribe()
    await sse.shutdown()
    assert not q.empty()


async def test_broadcast_includes_monotonic_seq() -> None:
    sse = SSEBroadcaster()
    q = sse.subscribe()
    await sse.broadcast("a", {})
    await sse.broadcast("b", {})
    msg1 = json.loads(q.get_nowait().split("data: ")[1].split("\n")[0])
    msg2 = json.loads(q.get_nowait().split("data: ")[1].split("\n")[0])
    assert msg2["seq"] > msg1["seq"]


async def test_multiple_subscribers_receive() -> None:
    sse = SSEBroadcaster()
    q1 = sse.subscribe()
    q2 = sse.subscribe()
    await sse.broadcast("ev", {"v": 42})
    assert not q1.empty()
    assert not q2.empty()
