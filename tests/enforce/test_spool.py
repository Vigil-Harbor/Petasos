"""The signed spool is an object. Two of them do not share a path or a key."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from petasos.enforce.events import EventSpool, emit_enforcement_event

if TYPE_CHECKING:
    from pathlib import Path


def test_two_spools_do_not_share_a_key_or_a_path(tmp_path: Path) -> None:
    """A signature written by one spool does not appear in the other."""
    first = EventSpool(str(tmp_path / "a.jsonl"), secret=b"one")
    second = EventSpool(str(tmp_path / "b.jsonl"), secret=b"two")
    assert first.emit({"event_type": "block", "session_id": "s"})
    assert second.emit({"event_type": "allow", "session_id": "s"})
    left = json.loads((tmp_path / "a.jsonl").read_text(encoding="utf-8"))
    right = json.loads((tmp_path / "b.jsonl").read_text(encoding="utf-8"))
    assert left["event_type"] == "block"
    assert right["event_type"] == "allow"
    assert left["sig"] != right["sig"]
    assert "scan_id" in left and "timestamp" in left


def test_unsigned_spool_omits_the_signature(tmp_path: Path) -> None:
    """A spool constructed without a secret writes an unsigned line."""
    spool = EventSpool(str(tmp_path / "plain.jsonl"))
    assert spool.emit({"event_type": "block"})
    row = json.loads((tmp_path / "plain.jsonl").read_text(encoding="utf-8"))
    assert "sig" not in row


def test_spool_emit_does_not_use_the_legacy_writer(tmp_path: Path) -> None:
    """The legacy writer has no resolver here, and the object still appends."""
    spool = EventSpool(str(tmp_path / "own.jsonl"), secret=b"k")
    assert spool.emit({"event_type": "tier3"})
    emit_enforcement_event({"event_type": "block"}, path=str(tmp_path / "legacy.jsonl"))
    text = (tmp_path / "own.jsonl").read_text(encoding="utf-8")
    assert "tier3" in text
    assert "block" not in text
