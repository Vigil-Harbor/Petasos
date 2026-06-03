"""Thread-safe ring buffer backed by collections.deque."""

from __future__ import annotations

from collections import deque
from typing import Generic, TypeVar

T = TypeVar("T")


class RingBuffer(Generic[T]):
    """Fixed-capacity ring buffer. Oldest items drop on overflow."""

    __slots__ = ("_buf",)

    def __init__(self, maxlen: int = 500) -> None:
        self._buf: deque[T] = deque(maxlen=maxlen)

    def push(self, item: T) -> None:
        self._buf.append(item)

    def to_list(self, limit: int | None = None) -> list[T]:
        if limit is not None:
            if limit < 0:
                raise ValueError(f"limit must be non-negative, got {limit}")
            if limit == 0:
                return []
        items = list(self._buf)
        if limit is not None and limit < len(items):
            return items[-limit:]
        return items

    def __len__(self) -> int:
        return len(self._buf)
