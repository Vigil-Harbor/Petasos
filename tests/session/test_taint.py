"""Pin bounded source-span capture, session isolation and outbound matching.

See docs/architecture/rationale.md, "Source taint bounds"."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
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

_ZWSP = "​"
_CYRILLIC_O = "о"


def _store(min_span_length: int = 12) -> SessionTaintStore:
    return SessionTaintStore(
        from_mapping(
            PetasosConfig,
            {
                "egress": {
                    "taint_min_span_length": min_span_length,
                },
            },
        )
    )


def test_taint_minlength_floor_no_false_positive() -> None:
    # The minimum span length prevents short, low-entropy values poisoning unrelated arguments.
    """Pin taint minlength floor no false positive."""
    store = _store()
    store.capture("s1", "$5.00", "ns")
    store.capture("s1", "2026", "ns")
    assert store.tainted_source("s1", {"body": "I paid $5.00 back in 2026"}) is None


def test_taint_floor_measured_on_normalized_codepoints() -> None:
    # The floor counts normalized codepoints.
    """Pin taint floor measured on normalized codepoints."""
    store = _store(12)
    sharp_s = "ß" * 11
    store.capture("s1", sharp_s, "ns")
    assert store.tainted_source("s1", {"v": sharp_s}) == "ns"
    raw = "abcdefghij" + _ZWSP + "k"
    store.capture("s2", raw, "ns")
    assert store.tainted_source("s2", {"v": "abcdefghijk"}) is None


def test_taint_per_session_isolation() -> None:
    # Session-keyed isolation does not depend on a session-end hook.
    """Pin taint per session isolation."""
    store = _store()
    store.capture("A", "sensitive-balance-12345", "ns")
    assert store.tainted_source("A", {"v": "sensitive-balance-12345"}) == "ns"
    assert store.tainted_source("B", {"v": "sensitive-balance-12345"}) is None


def test_taint_set_bounded_per_session() -> None:
    """Pin taint set bounded per session."""
    store = _store()
    total = _TAINT_MAX_SPANS_PER_SESSION + 50
    for i in range(total):
        store.capture("s1", f"sensitive-span-value-{i:05d}", "ns")
    newest = f"sensitive-span-value-{total - 1:05d}"
    oldest = "sensitive-span-value-00000"
    assert store.tainted_source("s1", {"v": newest}) == "ns"
    assert store.tainted_source("s1", {"v": oldest}) is None


def test_taint_set_bounded_sessions_lru() -> None:
    """Pin taint set bounded sessions lru."""
    store = _store()
    span = "shared-sensitive-value-xyz"
    store.capture("first", span, "ns")
    for i in range(_TAINT_MAX_SESSIONS + 5):
        store.capture(f"sess-{i}", f"other-sensitive-value-{i:05d}", "ns")
    assert store.tainted_source("first", {"v": span}) is None
    recent_i = _TAINT_MAX_SESSIONS + 4
    recent = f"sess-{recent_i}"
    assert store.tainted_source(recent, {"v": f"other-sensitive-value-{recent_i:05d}"}) == "ns"


def test_taint_json_leaf_granularity() -> None:
    """Pin taint json leaf granularity."""
    store = _store(12)
    result = json.dumps(
        {
            "ref": 20260617400012,
            "amount": 4000.0,
            "memo": "Whole Foods groceries run",
        }
    )
    store.capture("s1", result, "ns")
    assert store.tainted_source("s1", {"v": "ref 20260617400012 posted"}) == "ns"
    assert store.tainted_source("s1", {"v": "the amount was 4000.0 even"}) is None
    assert store.tainted_source("s1", {"v": "see Whole Foods groceries run today"}) == "ns"

    assert list(_iter_leaf_strings({"a": True, "b": False})) == ["true", "false"]

    store.capture("s3", {"outer": {"inner": "deep-sensitive-token-9988"}}, "ns")
    assert store.tainted_source("s3", {"v": "relay deep-sensitive-token-9988 now"}) == "ns"
    assert store.tainted_source("s3", {"v": "{'outer': {'inner':"}) is None

    store.capture("s4", json.dumps({"note": 'say "hello world" to all'}), "ns")
    assert store.tainted_source("s4", {"v": 'say "hello world" to all'}) == "ns"


def test_taint_capture_non_str_and_oversize() -> None:
    """Pin taint capture non str and oversize."""
    store = _store(12)
    store.capture("s1", None, "ns")
    store.capture("s1", 4000.0, "ns")
    store.capture("s1", 12345678901234, "ns")
    assert store.tainted_source("s1", {"v": "ref 12345678901234 x"}) == "ns"

    big = json.dumps({"k": "S" + "a" * (_MAX_SCAN_TEXT + 5000)})
    store.capture("s2", big, "ns")
    assert store.tainted_source("s2", {"v": "a" * 200}) is None

    last_walked = _MAX_SCAN_LEAVES - 1
    past_cap = _MAX_SCAN_LEAVES + 150
    huge = {f"k{i}": f"sensitive-leaf-value-{i:06d}" for i in range(_MAX_SCAN_LEAVES + 200)}
    store.capture("s3", huge, "ns")
    assert store.tainted_source("s3", {"v": f"sensitive-leaf-value-{last_walked:06d}"}) == "ns"
    assert store.tainted_source("s3", {"v": f"sensitive-leaf-value-{past_cap:06d}"}) is None

    store.capture("s4", "z" * (_MAX_TAINT_SPAN_LEN + 10), "ns")
    assert store.tainted_source("s4", {"v": "z" * (_MAX_TAINT_SPAN_LEN + 10)}) is None


def test_taint_span_multi_namespace_collision() -> None:
    # First-source attribution stays stable for deterministic operator records.
    """Pin taint span multi namespace collision."""
    store = _store()
    span_text = "shared-collision-value-001"
    store.capture("s1", span_text, "mcp_bank_")
    store.capture("s1", span_text, "mcp_health_")
    assert store.tainted_source("s1", {"v": span_text}) == "mcp_bank_"


def test_taint_common_phrase_blocks() -> None:
    # The length floor is not an entropy floor; common long phrases can still block.
    """Pin taint common phrase blocks."""
    store = _store()
    store.capture("s1", "Amazon Web Services", "ns")
    assert store.tainted_source("s1", {"v": "invoice from Amazon Web Services"}) == "ns"


def test_taint_normalized_match() -> None:
    # Normalization catches homoglyph and invisible-character variants, but not base64 re-encoding.
    """Pin taint normalized match."""
    store = _store()
    store.capture("s1", "Sensitive Account Holder", "ns")
    homoglyph = "sensitive acc" + _CYRILLIC_O + "unt holder"
    assert store.tainted_source("s1", {"v": homoglyph}) == "ns"
    zero_width = "Sensitive" + _ZWSP + " Account Holder"
    assert store.tainted_source("s1", {"v": zero_width}) == "ns"
    b64 = base64.b64encode(b"Sensitive Account Holder").decode()
    assert store.tainted_source("s1", {"v": b64}) is None


def test_taint_apply_config_updates_floor() -> None:
    """Pin taint apply config updates floor."""
    store = _store(20)
    store.capture("s1", "fifteen-chars12", "ns")
    assert store.tainted_source("s1", {"v": "fifteen-chars12"}) is None
    store.apply_config(
        from_mapping(
            PetasosConfig,
            {
                "egress": {
                    "taint_min_span_length": 10,
                },
            },
        )
    )
    store.capture("s1", "fifteen-chars99", "ns")
    assert store.tainted_source("s1", {"v": "fifteen-chars99"}) == "ns"


def test_taint_apply_config_floor_not_retroactive() -> None:
    """Pin taint apply config floor not retroactive."""
    store = _store(10)
    store.capture("s1", "twelve-chars1", "ns")
    store.apply_config(
        from_mapping(
            PetasosConfig,
            {
                "egress": {
                    "taint_min_span_length": 50,
                },
            },
        )
    )
    assert store.tainted_source("s1", {"v": "twelve-chars1"}) == "ns"

    store2 = _store(50)
    store2.capture("s2", "short-twelve", "ns")
    store2.apply_config(
        from_mapping(
            PetasosConfig,
            {
                "egress": {
                    "taint_min_span_length": 5,
                },
            },
        )
    )
    assert store2.tainted_source("s2", {"v": "short-twelve"}) is None


def test_taint_block_off_hot_path_cost() -> None:
    """Pin taint block off hot path cost."""
    store = _store()
    for i in range(_TAINT_MAX_SPANS_PER_SESSION):
        store.capture("s1", f"sensitive-span-value-{i:05d}", "ns")

    # See docs/architecture/rationale.md, "Test timing and backend qualification".
    args = {"a": "no tainted content here at all, just benign text", "b": 12345}
    start = time.perf_counter()
    for _ in range(50):
        store.tainted_source("s1", args)
    check_avg = (time.perf_counter() - start) / 50
    assert check_avg < 0.005, f"tainted_source too slow: {check_avg * 1000:.2f}ms"

    # See docs/architecture/rationale.md, "Test timing and backend qualification".
    payload = json.dumps({"rows": [f"row-value-{i}-xxxxxxxx" for i in range(50)]})
    start = time.perf_counter()
    for _ in range(50):
        store.capture("s2", payload, "ns")
    capture_avg = (time.perf_counter() - start) / 50
    assert capture_avg < 0.05, f"capture too slow: {capture_avg * 1000:.2f}ms"


def test_taint_deeply_nested_no_recursion_error() -> None:
    """Pin taint deeply nested no recursion error."""
    store = _store(12)
    deep: Any = "sensitive-deep-leaf-value-xyz"
    for _ in range(_MAX_TAINT_DEPTH + 50):
        deep = [deep]
    store.capture("s1", deep, "ns")
    assert store.tainted_source("s1", {"v": deep}) is None
    json_bomb = "[" * 50000 + "]" * 50000
    store.capture("s2", json_bomb, "ns")
