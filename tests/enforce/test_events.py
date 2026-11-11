"""The enforcement-event writer: signing, rotation, and a failed write.

These pins lived on the module-level writer. They do not need the console
resolver: every call passes a path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import TYPE_CHECKING

import pytest

import petasos.enforce.events as events

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SECRET = b"synthetic-test-key"


@pytest.fixture(autouse=True)
def _clear_writer_keys() -> Iterator[None]:
    events._reset_spool_key()
    yield
    events._reset_spool_key()


def _read(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if not text:
        return []
    return [json.loads(line) for line in text.splitlines() if line]


def _block(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "event_type": "block",
        "session_id": "s",
        "tool": "terminal",
        "armed": True,
    }
    base.update(over)
    return base


def test_a_keyed_write_stamps_a_signature_and_an_unkeyed_write_does_not(tmp_path: Path) -> None:
    signed = tmp_path / "signed.jsonl"
    events.set_spool_key(_SECRET, path=str(signed))
    assert events.emit_enforcement_event(_block(scan_id="e-signed"), path=str(signed)) is True
    row = _read(signed)[0]
    signature = row.get("sig")
    assert isinstance(signature, str) and signature
    assert events.verify_event(row, events._derive_spool_key(_SECRET)) is True

    plain = tmp_path / "plain.jsonl"
    assert events.emit_enforcement_event(_block(scan_id="e-plain"), path=str(plain)) is True
    assert "sig" not in _read(plain)[0]


def test_the_signature_is_the_only_field_signing_adds(tmp_path: Path) -> None:
    path = tmp_path / "both.jsonl"
    payload = _block(scan_id="e-fixed", timestamp=1.0)
    assert events.emit_enforcement_event(dict(payload), path=str(path)) is True
    events.set_spool_key(_SECRET, path=str(path))
    assert events.emit_enforcement_event(dict(payload), path=str(path)) is True
    rows = _read(path)
    assert set(rows[1]) - set(rows[0]) == {"sig"}


def test_verify_event_never_raises() -> None:
    key = events._derive_spool_key(_SECRET)
    assert events.verify_event({"sig": 123}, key) is False
    assert events.verify_event({"event_type": "block"}, key) is False
    assert events.verify_event("not-a-dict", key) is False
    assert events.verify_event(None, key) is False
    assert events.verify_event({"sig": "abc"}, None) is False


def test_a_signing_failure_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "spool.jsonl"
    monkeypatch.setattr(events, "_SPOOL_KEY", 12345)
    assert events.emit_enforcement_event(_block(), path=str(path)) is False
    assert _read(path) == []


def test_the_spool_key_is_domain_separated() -> None:
    secret = b"some-session-secret"
    derived = events._derive_spool_key(secret)
    assert derived == events._derive_spool_key(secret)
    assert derived != secret
    other = hmac.new(secret, b"petasos/some-other-label/v1", hashlib.sha256).digest()
    assert derived != other


def test_a_path_keeps_its_own_key(tmp_path: Path) -> None:
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    events.set_spool_key(b"key-a", path=str(first))
    events.set_spool_key(b"key-b", path=str(second))
    assert events.emit_enforcement_event(_block(scan_id="e-a"), path=str(first)) is True
    assert events.emit_enforcement_event(_block(scan_id="e-b"), path=str(second)) is True
    assert events.verify_event(_read(first)[0], events._derive_spool_key(b"key-a")) is True
    assert events.verify_event(_read(first)[0], events._derive_spool_key(b"key-b")) is False
    assert events.verify_event(_read(second)[0], events._derive_spool_key(b"key-b")) is True


def test_rotation_refuses_to_overwrite_a_leftover(tmp_path: Path) -> None:
    live = tmp_path / "spool.jsonl"
    rotated = tmp_path / "spool.jsonl.rot"
    live.write_text('{"event_type":"block"}\n', encoding="utf-8")
    assert events.rotate_spool(str(live)) is True
    assert rotated.read_text(encoding="utf-8").startswith('{"event_type"')
    live.write_text('{"event_type":"allow"}\n', encoding="utf-8")
    assert events.rotate_spool(str(live)) is False
    assert "allow" not in rotated.read_text(encoding="utf-8")
    assert live.exists()


def test_a_drain_reads_each_complete_line_once(tmp_path: Path) -> None:
    path = tmp_path / "spool.jsonl"
    path.write_text('{"n":1}\n{"n":2}\n{"n":', encoding="utf-8")
    got, offset = events.drain_enforcement_events(str(path), 0)
    assert [row["n"] for row in got] == [1, 2]
    again, same = events.drain_enforcement_events(str(path), offset)
    assert again == []
    assert same == offset
    with path.open("a", encoding="utf-8") as handle:
        handle.write("3}\n")
    rest, _end = events.drain_enforcement_events(str(path), offset)
    assert rest == [{"n": 3}]


def test_module_key_sig_class_and_console_row(tmp_path: Path) -> None:
    events.set_spool_key(b"secret")
    assert events._SPOOL_KEY is not None
    slot = tmp_path / "one.jsonl"
    events.set_spool_key(b"secret", path=str(slot))
    events.set_spool_key(None, path=str(slot))
    assert str(slot) not in events._SPOOL_KEYS and events._SPOOL_KEYS == {}
    assert events.classify_integrity_failure({"event_type": "block"}) == "sig-missing"
    assert events.classify_integrity_failure("nope") == "sig-missing"

    wrote = events.emit_console_event({"event_type": "approval", "armed": True}, key=b"k")
    assert wrote is True
    missing, offset = events.drain_enforcement_events(str(tmp_path / "absent.jsonl"), 0)
    assert missing == []
    assert offset == 0
    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    none, stayed = events.drain_enforcement_events(str(empty), 0)
    assert none == []
    assert stayed == 0
    assert events.spool_size(str(empty)) == 0
    assert events.spool_size(str(tmp_path / "absent.jsonl")) == 0

    saved = events._resolver
    events._resolver = None
    try:
        with pytest.raises(RuntimeError, match="resolver is not installed"):
            events.spool_size()
    finally:
        events._resolver = saved
