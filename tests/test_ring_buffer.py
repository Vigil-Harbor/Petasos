"""Tests for petasos.console._ring_buffer."""

from petasos.console._ring_buffer import RingBuffer


def test_push_within_capacity():
    buf = RingBuffer[int](maxlen=5)
    for i in range(5):
        buf.push(i)
    assert buf.to_list() == [0, 1, 2, 3, 4]
    assert len(buf) == 5


def test_push_beyond_capacity_drops_oldest():
    buf = RingBuffer[int](maxlen=3)
    for i in range(6):
        buf.push(i)
    assert buf.to_list() == [3, 4, 5]
    assert len(buf) == 3


def test_to_list_with_limit():
    buf = RingBuffer[int](maxlen=10)
    for i in range(10):
        buf.push(i)
    assert buf.to_list(limit=3) == [7, 8, 9]


def test_to_list_limit_larger_than_buffer():
    buf = RingBuffer[int](maxlen=5)
    buf.push(1)
    buf.push(2)
    assert buf.to_list(limit=10) == [1, 2]


def test_empty_buffer():
    buf = RingBuffer[str](maxlen=10)
    assert buf.to_list() == []
    assert len(buf) == 0


def test_to_list_no_limit():
    buf = RingBuffer[int](maxlen=5)
    for i in range(3):
        buf.push(i)
    assert buf.to_list() == [0, 1, 2]
