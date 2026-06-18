"""Unit tests for SessionTaintStore (PET-134).

Backend-free: the store depends only on ``petasos.normalize`` + ``PetasosConfig``
(no ML extras), so this file runs in the default ``ci.yml`` lane. Covers the FP
floor (measured on the normalized span), per-session isolation, the two memory
bounds (per-session span cap + global session LRU), JSON-leaf granularity,
first-source-wins collision, the verbatim-only matching residual, and the
non-retroactive ``apply_config`` semantics.

Invisible / look-alike characters are written as explicit ``\\u`` escapes so the
test intent is legible and the source survives reformatting.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from petasos import PetasosConfig
from petasos.session.taint import (
    _MAX_SCAN_LEAVES,
    _MAX_SCAN_TEXT,
    _MAX_TAINT_DEPTH,
    _MAX_TAINT_SPAN_LEN,
    _TAINT_MAX_SESSIONS,
    _TAINT_MAX_SPANS_PER_SESSION,
    SessionTaintStore,
    _iter_leaf_strings,
)

_ZWSP = "​"  # ZERO WIDTH SPACE (category Cf, stripped by normalize)
_CYRILLIC_O = "о"  # Cyrillic small letter o (folds to ASCII 'o')


def _store(min_span_length: int = 12) -> SessionTaintStore:
    return SessionTaintStore(PetasosConfig(taint_min_span_length=min_span_length))


# ---------------------------------------------------------------------------
# FP floor
# ---------------------------------------------------------------------------


def test_taint_minlength_floor_no_false_positive() -> None:
    # A span below taint_min_span_length is never stored, so a low-entropy value
    # cannot poison an unrelated later argument.
    store = _store()
    store.capture("s1", "$5.00", "ns")  # 5 chars, below floor
    store.capture("s1", "2026", "ns")  # parses to int 2026 -> "2026", below floor
    assert store.tainted_source("s1", {"body": "I paid $5.00 back in 2026"}) is None


def test_taint_floor_measured_on_normalized_codepoints() -> None:
    # F-3: the floor is a codepoint count on the NORMALIZED span, not the raw input.
    store = _store(12)
    # 11 sharp-s (U+00DF, raw 11, below the floor) casefolds to 22 's' (>= floor): STORED,
    # because the floor is measured after normalization. A raw-length floor would drop it.
    sharp_s = "ß" * 11
    store.capture("s1", sharp_s, "ns")
    assert store.tainted_source("s1", {"v": sharp_s}) == "ns"
    # Converse: a value whose RAW length clears the floor but whose NORMALIZED length falls
    # below it (zero-width stripping shrinks it) is dropped.
    raw = "abcdefghij" + _ZWSP + "k"  # raw 12; normalized 11 < 12
    store.capture("s2", raw, "ns")
    assert store.tainted_source("s2", {"v": "abcdefghijk"}) is None


# ---------------------------------------------------------------------------
# Per-session isolation + memory bounds
# ---------------------------------------------------------------------------


def test_taint_per_session_isolation() -> None:
    # A span captured under session A never matches a check for session B (keyed
    # isolation delivers the brief's "cleared on session end" guarantee since no
    # session-end hook exists, D1a).
    store = _store()
    store.capture("A", "sensitive-balance-12345", "ns")
    assert store.tainted_source("A", {"v": "sensitive-balance-12345"}) == "ns"
    assert store.tainted_source("B", {"v": "sensitive-balance-12345"}) is None


def test_taint_set_bounded_per_session() -> None:
    # Over the per-session span cap, the oldest spans are evicted (memory bound).
    store = _store()
    total = _TAINT_MAX_SPANS_PER_SESSION + 50
    for i in range(total):
        store.capture("s1", f"sensitive-span-value-{i:05d}", "ns")
    newest = f"sensitive-span-value-{total - 1:05d}"
    oldest = "sensitive-span-value-00000"
    assert store.tainted_source("s1", {"v": newest}) == "ns"
    assert store.tainted_source("s1", {"v": oldest}) is None  # evicted


def test_taint_set_bounded_sessions_lru() -> None:
    # Over the global session cap, the least-recently-active session's whole set is
    # evicted (the no-session-end backstop; total memory hard-bounded).
    store = _store()
    span = "shared-sensitive-value-xyz"
    store.capture("first", span, "ns")
    for i in range(_TAINT_MAX_SESSIONS + 5):
        store.capture(f"sess-{i}", f"other-sensitive-value-{i:05d}", "ns")
    # 'first' is the least-recently-active key and was evicted whole.
    assert store.tainted_source("first", {"v": span}) is None
    recent_i = _TAINT_MAX_SESSIONS + 4
    recent = f"sess-{recent_i}"
    assert store.tainted_source(recent, {"v": f"other-sensitive-value-{recent_i:05d}"}) == "ns"


# ---------------------------------------------------------------------------
# JSON-leaf granularity + leaf shape
# ---------------------------------------------------------------------------


def test_taint_json_leaf_granularity() -> None:
    store = _store(12)
    # (a) A JSON-object string taints per leaf. A floor-clearing numeric leaf is
    # json.dumps-stringified and captured; a short bare number is below the floor and
    # dropped like a short string (F-9 / F-1: the headline amount is fenced via a longer
    # descriptive field, not as a bare number).
    result = json.dumps(
        {
            "ref": 20260617400012,  # 14-digit int -> "20260617400012" (>= floor)
            "amount": 4000.0,  # -> "4000.0" (6 chars, dropped)
            "memo": "Whole Foods groceries run",  # >= floor string leaf
        }
    )
    store.capture("s1", result, "ns")
    assert store.tainted_source("s1", {"v": "ref 20260617400012 posted"}) == "ns"
    assert store.tainted_source("s1", {"v": "the amount was 4000.0 even"}) is None
    assert store.tainted_source("s1", {"v": "see Whole Foods groceries run today"}) == "ns"

    # (b) A bool leaf is extracted as its JSON-wire form ("true"/"false"), not Python's
    # str() ("True"/"False") -- the shared canonical shape for capture and check.
    assert list(_iter_leaf_strings({"a": True, "b": False})) == ["true", "false"]

    # (c) A dict result (NOT a JSON string) is walked per leaf, never str()-flattened to one
    # Python-repr blob; the bare leaf value is fenced (F-2).
    store.capture("s3", {"outer": {"inner": "deep-sensitive-token-9988"}}, "ns")
    assert store.tainted_source("s3", {"v": "relay deep-sensitive-token-9988 now"}) == "ns"
    assert store.tainted_source("s3", {"v": "{'outer': {'inner':"}) is None  # repr is not a span

    # (d) Unescaped-value symmetry: a quoted JSON leaf still matches an unescaped relay
    # (both sides are the post-parse value, so JSON quote-escaping never breaks the match).
    store.capture("s4", json.dumps({"note": 'say "hello world" to all'}), "ns")
    assert store.tainted_source("s4", {"v": 'say "hello world" to all'}) == "ns"


def test_taint_capture_non_str_and_oversize() -> None:
    store = _store(12)
    # (a) non-str / None result: no raise, nothing harmful stored; a long bare scalar is
    # eligible (stringified), a short one is dropped.
    store.capture("s1", None, "ns")
    store.capture("s1", 4000.0, "ns")  # -> "4000.0" (6 chars, dropped)
    store.capture("s1", 12345678901234, "ns")  # -> "12345678901234" (14 chars, stored)
    assert store.tainted_source("s1", {"v": "ref 12345678901234 x"}) == "ns"

    # (b) a valid-JSON result larger than _MAX_SCAN_TEXT degrades to a capture-miss (the cut
    # truncates mid-structure -> one over-max leaf -> dropped; no crash).
    big = json.dumps({"k": "S" + "a" * (_MAX_SCAN_TEXT + 5000)})
    store.capture("s2", big, "ns")
    assert store.tainted_source("s2", {"v": "a" * 200}) is None

    # (c) an oversized STRUCTURED result with > _MAX_SCAN_LEAVES leaves: bounded walk. The
    # last leaf within the walk cap is captured; a leaf past the cap is a documented miss.
    last_walked = _MAX_SCAN_LEAVES - 1
    past_cap = _MAX_SCAN_LEAVES + 150
    huge = {f"k{i}": f"sensitive-leaf-value-{i:06d}" for i in range(_MAX_SCAN_LEAVES + 200)}
    store.capture("s3", huge, "ns")
    assert store.tainted_source("s3", {"v": f"sensitive-leaf-value-{last_walked:06d}"}) == "ns"
    assert store.tainted_source("s3", {"v": f"sensitive-leaf-value-{past_cap:06d}"}) is None

    # (d) an over-_MAX_TAINT_SPAN_LEN leaf is dropped, not stored whole.
    store.capture("s4", "z" * (_MAX_TAINT_SPAN_LEN + 10), "ns")
    assert store.tainted_source("s4", {"v": "z" * (_MAX_TAINT_SPAN_LEN + 10)}) is None


# ---------------------------------------------------------------------------
# Collision, common-phrase residual, normalization parity
# ---------------------------------------------------------------------------


def test_taint_span_multi_namespace_collision() -> None:
    # First-source-wins: the same span captured from two namespaces reports a STABLE
    # namespace so the operator block reason is deterministic (F-1).
    store = _store()
    span_text = "shared-collision-value-001"
    store.capture("s1", span_text, "mcp_bank_")
    store.capture("s1", span_text, "mcp_health_")  # same span, later source -> ignored
    assert store.tainted_source("s1", {"v": span_text}) == "mcp_bank_"


def test_taint_common_phrase_blocks() -> None:
    # F-4 (accepted residual, pinned as intended): a 12+ char common phrase over the floor
    # DOES block a later arg containing it -- the length floor is not an entropy floor.
    store = _store()
    store.capture("s1", "Amazon Web Services", "ns")  # 19 chars, a common phrase
    assert store.tainted_source("s1", {"v": "invoice from Amazon Web Services"}) == "ns"


def test_taint_normalized_match() -> None:
    # A homoglyph / cased / zero-width variant of a captured span in the outbound arg still
    # matches (normalization parity); a base64 re-encoding does NOT (D-EVASION verbatim-only).
    store = _store()
    store.capture("s1", "Sensitive Account Holder", "ns")
    homoglyph = "sensitive acc" + _CYRILLIC_O + "unt holder"  # Cyrillic 'o' + lowercased
    assert store.tainted_source("s1", {"v": homoglyph}) == "ns"
    zero_width = "Sensitive" + _ZWSP + " Account Holder"
    assert store.tainted_source("s1", {"v": zero_width}) == "ns"
    b64 = base64.b64encode(b"Sensitive Account Holder").decode()
    assert store.tainted_source("s1", {"v": b64}) is None


# ---------------------------------------------------------------------------
# apply_config (PET-126 parity): live floor change, non-retroactive
# ---------------------------------------------------------------------------


def test_taint_apply_config_updates_floor() -> None:
    store = _store(20)
    store.capture("s1", "fifteen-chars12", "ns")  # 15 chars < 20 -> dropped
    assert store.tainted_source("s1", {"v": "fifteen-chars12"}) is None
    store.apply_config(PetasosConfig(taint_min_span_length=10))  # lower the floor live
    store.capture("s1", "fifteen-chars99", "ns")  # 15 chars >= 10 -> stored
    assert store.tainted_source("s1", {"v": "fifteen-chars99"}) == "ns"


def test_taint_apply_config_floor_not_retroactive() -> None:
    # F-5: a live floor change applies to FUTURE captures only.
    store = _store(10)
    store.capture("s1", "twelve-chars1", "ns")  # 13 chars >= 10 -> stored
    store.apply_config(PetasosConfig(taint_min_span_length=50))  # raise the floor
    assert store.tainted_source("s1", {"v": "twelve-chars1"}) == "ns"  # not retroactively removed

    store2 = _store(50)
    store2.capture("s2", "short-twelve", "ns")  # 12 chars < 50 -> never stored
    store2.apply_config(PetasosConfig(taint_min_span_length=5))  # lower the floor
    assert store2.tainted_source("s2", {"v": "short-twelve"}) is None  # not retroactively admitted


# ---------------------------------------------------------------------------
# Performance (bounded-work checks, loose to avoid CI flake)
# ---------------------------------------------------------------------------


def test_taint_block_off_hot_path_cost() -> None:
    store = _store()
    for i in range(_TAINT_MAX_SPANS_PER_SESSION):
        store.capture("s1", f"sensitive-span-value-{i:05d}", "ns")

    # (a) check side: tainted_source IS the pre-call enforcement hot path (syntactic-only
    # budget < 5ms), and it is a few-microsecond op (normalize a couple of arg leaves, then
    # substring-scan a full span set), so a 5ms ceiling holds ~1000x headroom and tightly
    # catches a gross regression (e.g. an accidental O(n^2) blow-up).
    args = {"a": "no tainted content here at all, just benign text", "b": 12345}
    start = time.perf_counter()
    for _ in range(50):
        store.tainted_source("s1", args)
    check_avg = (time.perf_counter() - start) / 50
    assert check_avg < 0.005, f"tainted_source too slow: {check_avg * 1000:.2f}ms"

    # (b) capture side: a deliberately loose bound. capture runs on _post_tool_call (after
    # the tool ran), NOT on the < 5ms pre-call enforcement path, and it NFKC-normalizes
    # every leaf, which on a contended CI runner approaches single-digit ms. Per spec
    # § Performance this stays a flake-resistant bounded-work check, not a 5ms budget assert
    # (a real latency budget needs a benchmark harness, not an averaged wall-clock assert).
    payload = json.dumps({"rows": [f"row-value-{i}-xxxxxxxx" for i in range(50)]})
    start = time.perf_counter()
    for _ in range(50):
        store.capture("s2", payload, "ns")
    capture_avg = (time.perf_counter() - start) / 50
    assert capture_avg < 0.05, f"capture too slow: {capture_avg * 1000:.2f}ms"


def test_taint_deeply_nested_no_recursion_error() -> None:
    # Finding 2 regression: a hostile deeply-nested payload must not raise RecursionError
    # on EITHER path (bounded leaf walk); content past _MAX_TAINT_DEPTH is a documented
    # walk-miss, not a crash.
    store = _store(12)
    deep: Any = "sensitive-deep-leaf-value-xyz"
    for _ in range(_MAX_TAINT_DEPTH + 50):
        deep = [deep]
    store.capture("s1", deep, "ns")  # structured-walk recursion: must not raise
    # the buried leaf sits past the depth cap, so it is never reached (no match, no crash).
    assert store.tainted_source("s1", {"v": deep}) is None
    # a deeply-nested JSON STRING result exercises json.loads's own recursion guard.
    json_bomb = "[" * 50000 + "]" * 50000
    store.capture("s2", json_bomb, "ns")  # must not raise
