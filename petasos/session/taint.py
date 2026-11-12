"""Retain bounded source spans per session for outbound relay checks.

See docs/architecture/rationale.md, "Source taint bounds"."""

from __future__ import annotations

import itertools
import json
import threading
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from petasos.normalize import normalize

if TYPE_CHECKING:
    from petasos.config.sections import PetasosConfig

# Internal safety ceilings bound hostile input independently of operator settings.
_TAINT_MAX_SPANS_PER_SESSION = 256
_TAINT_MAX_SESSIONS = 1024
_MAX_TAINT_SPAN_LEN = 4096  # never store a leaf longer than this (raw codepoints)
_MAX_SCAN_TEXT = 100_000
_MAX_SCAN_LEAVES = 2048
_MAX_TAINT_DEPTH = 64


def _iter_leaf_strings(obj: object, _depth: int = 0) -> Iterator[str]:
    """Yield the leaf string candidates of an arbitrary JSON-ish value.

    Recurses ``Mapping`` values and ``list``/``tuple`` items. ``str`` leaves are
    yielded as-is; non-string scalar leaves (``int`` / ``float`` / ``bool``) are
    stringified via ``json.dumps(v, default=str)`` — the JSON-wire form a relayed
    value carries (``json.dumps(True)`` -> ``"true"``, not ``str(True)``'s
    ``"True"``) — so capture and check see one canonical leaf shape. ``None`` is
    skipped. ``default=str`` matches the house never-raise idiom (``_events.py``
    / the plugin's ``json.dumps(..., default=str)``).

    Recursion is bounded by ``_MAX_TAINT_DEPTH``: a hostile deeply-nested payload
    (in a tool result or in outbound args) is a documented walk-miss past the cap,
    never a ``RecursionError`` — preserving the never-raise invariant on both the
    post-call capture and the pre-call enforcement path.
    """
    if _depth > _MAX_TAINT_DEPTH:
        return
    if obj is None:
        return
    if isinstance(obj, str):
        yield obj
        return
    if isinstance(obj, Mapping):
        for value in obj.values():
            yield from _iter_leaf_strings(value, _depth + 1)
        return
    if isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _iter_leaf_strings(item, _depth + 1)
        return
    # JSON-wire scalars keep capture and outbound matching in the same representation.
    try:
        yield json.dumps(obj, default=str)
    except (TypeError, ValueError):
        yield str(obj)


def _result_leaf_strings(result: object) -> Iterator[str]:
    """Leaf candidates from a tool ``result``, without a lossy round-trip.

    A ``dict`` / ``list`` (a host that passes a structured object) is walked
    directly — never ``str()``-flattened to one unmatchable Python-repr blob. A
    ``str`` is ``json.loads``-parsed (capped at ``_MAX_SCAN_TEXT``) and walked on
    success; on ``JSONDecodeError`` (including a valid-JSON result truncated
    mid-structure by the cap) the capped text is one leaf. Any other type
    (``None``, a bare scalar) routes through ``_iter_leaf_strings``. Never raises.
    """
    if isinstance(result, str):
        capped = result[:_MAX_SCAN_TEXT]
        try:
            parsed = json.loads(capped)
        except (ValueError, TypeError, RecursionError):
            # See docs/architecture/rationale.md, "Source taint bounds".
            yield capped
            return
        yield from _iter_leaf_strings(parsed)
        return
    yield from _iter_leaf_strings(result)


class SessionTaintStore:
    """Thread-safe per-session store of normalized tainted spans -> source namespace."""

    def __init__(self, config: PetasosConfig) -> None:
        self._config = config
        self._min_span_len = config.egress.taint_min_span_length
        self._lock = threading.Lock()
        # session_id -> ordered { normalized span -> source namespace it came from }.
        # The outer OrderedDict is the global session LRU; the inner one is the
        # per-session insertion-ordered span set (front = oldest).
        self._store: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()

    @property
    def config(self) -> PetasosConfig:
        """The config tree this store reads."""
        return self._config

    def apply_config(self, new_config: PetasosConfig) -> None:
        """Apply the normalized-span floor to future captures under the store lock."""
        with self._lock:
            self._config = new_config
            self._min_span_len = new_config.egress.taint_min_span_length

    def capture(self, session_id: str, result: object, source_ns: str) -> None:
        """Taint each floor-clearing leaf of ``result`` for ``session_id``.

        Granularity is per JSON-leaf value (never the whole blob). The leaf walk
        is capped at ``_MAX_SCAN_LEAVES``; an over-cap leaf is a documented
        capture-miss, not a crash. **Collision: first-source-wins** — an already
        present span keeps its original namespace and insertion position. Never
        raises (the caller wraps this too, but the store is the floor).
        """
        with self._lock:
            min_span_len = self._min_span_len
            spans = self._store.get(session_id)
            if spans is None:
                spans = OrderedDict()
                self._store[session_id] = spans
            else:
                self._store.move_to_end(session_id)

            for index, leaf in enumerate(_result_leaf_strings(result)):
                if index >= _MAX_SCAN_LEAVES:
                    break  # Content beyond the leaf budget is unexamined.
                if len(leaf) > _MAX_TAINT_SPAN_LEN:
                    continue
                span = self._normalize(leaf)
                if len(span) < min_span_len:
                    continue  # The false-positive floor applies after normalization.
                if span in spans:
                    continue  # The first source retains attribution and insertion order.
                spans[span] = source_ns
                if len(spans) > _TAINT_MAX_SPANS_PER_SESSION:
                    spans.popitem(last=False)

            while len(self._store) > _TAINT_MAX_SESSIONS:
                self._store.popitem(last=False)

    def tainted_source(self, session_id: str, args: dict[str, Any]) -> str | None:
        """Return the source namespace of the first live span an ``args`` leaf carries.

        Walks ``args`` leaves the same way capture walks a result (shared
        extraction, identical leaf shapes), normalizes each, and returns the
        source namespace of the **first** tainted span (by insertion order, stable
        under first-source-wins) that is a normalized substring of any argument
        leaf — else ``None`` (the no-match / allow result). Marks the session
        most-recently-used so an actively-checked session is never LRU-evicted out
        from under itself.

        The candidate leaves are normalized **outside** the lock and bounded by
        ``_MAX_SCAN_LEAVES``: normalization touches no shared state, so a hostile
        wide/deep ``args`` payload cannot amplify lock-hold on the pre-call
        enforcement path (the lock guards only the span comparison).
        """
        candidates = [
            self._normalize(leaf)
            for leaf in itertools.islice(_iter_leaf_strings(args), _MAX_SCAN_LEAVES)
        ]
        with self._lock:
            spans = self._store.get(session_id)
            if not spans:
                return None
            self._store.move_to_end(session_id)
            for span, source_ns in spans.items():
                for candidate in candidates:
                    if span in candidate:
                        return source_ns
        return None

    def clear_session(self, session_id: str) -> None:
        """Drop a session's spans. Idempotent. Wired for a future host that gains
        an ``on_session_end`` signal; nothing calls it today (per-session keying +
        the LRU cap already bound memory without it)."""
        with self._lock:
            self._store.pop(session_id, None)

    @staticmethod
    def _normalize(text: str) -> str:
        """Canonical form for both capture and check: the pipeline's normalizer
        (NFKC + zero-width strip + homoglyph fold) then casefold, capped at
        ``_MAX_SCAN_TEXT`` so an oversized argument leaf cannot blow the budget."""
        return normalize(text[:_MAX_SCAN_TEXT]).normalized.casefold()
