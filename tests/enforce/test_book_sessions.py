"""Desktop session identity follows agent lifetime rather than recycled addresses."""

from __future__ import annotations

import gc
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from petasos.enforce.book import Book
from petasos.enforce.types import ManualClock


class _Agent:
    __hash__ = None  # type: ignore[assignment]

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Agent)


def _book() -> Book:
    return Book(ManualClock(), 30.0, logging.getLogger(__name__))


def test_different_agent_lifetimes_never_reuse_a_session() -> None:
    book = _book()
    sessions = set()
    for _ in range(200):
        agent = _Agent()
        session = book.session_id("", agent)
        assert book.session_id("", agent) == session
        sessions.add(session)
        del agent
    assert len(sessions) == 200
    gc.collect()
    assert not book._agents


def test_equal_unhashable_live_agents_have_distinct_stable_sessions() -> None:
    book = _book()
    left, right = _Agent(), _Agent()
    first = book.session_id("", left)
    second = book.session_id("", right)
    assert first != second
    assert book.session_id("", left) == first
    assert book.session_id("", right) == second
    assert book.session_id("task", left) == "task"


def test_non_weak_referenceable_agent_is_uncorrelated_without_retention() -> None:
    book = _book()
    agent = object()
    assert book.session_id("", agent) != book.session_id("", agent)
    assert not book._agents


def test_identity_formats_and_opaque_agent_warning(caplog: pytest.LogCaptureFixture) -> None:
    book = _book()
    assert re.fullmatch(r"desktop-[0-9a-f]{12}", book.session_id("", _Agent()))
    assert re.fullmatch(r"anon-[0-9a-f]{8}", book.session_id("", None))
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert re.fullmatch(r"anon-[0-9a-f]{8}", book.session_id("", object()))
    assert len(caplog.records) == 1
    assert "risk" in caplog.records[0].message
    assert "agent" in caplog.records[0].message
