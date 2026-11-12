"""Pin approval-secret masking before event signing.

See docs/architecture/rationale.md, "Test timing and backend qualification"."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import petasos.enforce.events as events
from petasos.enforce.approvals import approval_event, redact_display_text

if TYPE_CHECKING:
    from pathlib import Path


def test_the_signed_approval_line_does_not_contain_the_secret(tmp_path: Path) -> None:
    secret = "synthetic-password-" + "x" * 80

    def redact(text: str, **options: bool) -> str:
        assert options == {"force": True, "redact_url_credentials": True}
        return text.replace(secret, "[masked]")

    shown, status = redact_display_text(secret, 500, redact=redact)
    event = approval_event(
        "response",
        choice="deny",
        armed=True,
        command=shown,
        description=shown,
        redaction=status,
        fields={
            "pattern_key": "plugin_rule:petasos.test",
            "session_id": "profile-A-session",
            "surface": "cli",
        },
    )
    path = tmp_path / "spool.jsonl"
    events._reset_spool_key()
    try:
        events.set_spool_key(b"synthetic-test-key", path=str(path))
        assert events.emit_enforcement_event(event, path=str(path)) is True
    finally:
        events._reset_spool_key()
    raw = path.read_text(encoding="utf-8")
    assert secret not in raw
    row = json.loads(raw)
    assert row["command"] == "[masked]"
    assert row["credential_redaction"] == "redacted"
    assert "exposure unconfirmed" in row["reason"]
    assert events.verify_event(row, events._derive_spool_key(b"synthetic-test-key")) is True
