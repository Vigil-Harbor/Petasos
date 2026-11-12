"""Pin per-enforcer cold-start markers and retry after failed writes."""

from __future__ import annotations

import logging

from petasos.enforce.book import _MAX_COLD_KEYS, Book
from petasos.enforce.types import ManualClock


def _book() -> Book:
    return Book(ManualClock(monotonic=0.0), 30.0, logging.getLogger("petasos.test.cold"))


def test_a_session_gets_one_marker_until_it_is_released() -> None:
    """Pin a session gets one marker until it is released."""
    book = _book()
    assert book.claim_cold("s", "cold_degraded") is True
    assert book.claim_cold("s", "cold_degraded") is False
    assert book.claim_cold("s", "init_failed") is True
    book.release_cold("s", "cold_degraded")
    assert book.claim_cold("s", "cold_degraded") is True


def test_an_anonymous_marker_is_once_per_book() -> None:
    """Pin an anonymous marker is once per book."""
    book = _book()
    assert book.claim_cold(None, "cold_degraded") is True
    assert book.claim_cold(None, "cold_degraded") is False
    assert book.claim_cold(None, "init_failed") is True
    book.release_cold(None, "cold_degraded")
    assert book.claim_cold(None, "cold_degraded") is True
    other = _book()
    assert other.claim_cold(None, "cold_degraded") is True


def test_the_marker_table_is_capped() -> None:
    """Pin the marker table is capped."""
    book = _book()
    assert book.claim_cold("s-0", "cold_degraded") is True
    for index in range(1, _MAX_COLD_KEYS + 1):
        assert book.claim_cold(f"s-{index}", "cold_degraded") is True
    assert book.claim_cold("s-0", "cold_degraded") is True
