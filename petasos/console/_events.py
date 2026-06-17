"""Cross-process enforcement-event spool — sibling of ``_armed.py`` / ``_reload.py`` (PET-131).

The Hermes gateway runs in a separate process from the dashboard. On every
block / quarantine / tier3 / disarmed-bypass decision the gateway appends a
structured enforcement event here; the dashboard drains the spool into its
``scan_history`` ring buffer + ``scan_result`` SSE stream so live enforcement
reaches the Observability tab. The only cross-process primitive in this codebase
is file-based (``_armed.py``/``_reload.py``); this is the third member of that
family.

Identity model (spec D3): the cross-process event identity is the writer-stamped
unique ``scan_id`` (prefix ``e-``); the reader's cursor is a **byte offset** into
the spool, NOT a producer-process seq. A gateway restart would reset a per-process
seq to 0 and a surviving dashboard high-water marker would then drop every
post-restart event; a byte offset is restart-independent.

Posture (matches the family):

* **Writer is fail-open.** ``emit_enforcement_event`` returns ``False`` on any
  error and never raises — surfacing a block must never gate, delay, or break the
  tool call (spec D5). It is an O(1) append (no full-file rewrite, no ``fsync``);
  telemetry durability is not worth a per-call fsync, and trimming is the reader's
  job, off the hot path.
* **Reader is fail-safe.** ``drain_enforcement_events`` returns
  ``([], after_offset)`` (keep last-good) on any error and reads strictly forward,
  so a drained event is surfaced exactly once and no ``scan_id`` seen-set is needed.
* **Path recomputed per call** over ``resolve_hermes_config_path()`` so a transient
  dangling-``active_profile`` fallback to the ``root`` tier cannot leave the writer
  and reader on different files (spec edge F-6).

Never raises out of any public function.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from petasos.console._paths import resolve_hermes_config_path

_SPOOL_FILENAME = "petasos-enforcement.jsonl"
_ROT_SUFFIX = ".rot"

# Sized well above the motivating burst (~40 blocks / 2h18m, ~300 B/line) and far
# above one tailer interval's worth at peak rate (spec D4). Module-level so a test
# can shrink it via _reset_events_state to force rotation.
SPOOL_CAP_BYTES = 2_000_000

# Test seams (mirror _reset_armed_cache / _reset_reload_cache): point the spool at
# a temp file and optionally shrink the cap. None => resolve beside the live config.
_SPOOL_PATH_OVERRIDE: str | None = None


def _spool_path() -> str:
    """Resolve the spool path beside the active config (recomputed per call)."""
    if _SPOOL_PATH_OVERRIDE is not None:
        return _SPOOL_PATH_OVERRIDE
    res = resolve_hermes_config_path()
    return os.path.join(str(res.path.parent), _SPOOL_FILENAME)


def _reset_events_state(path: str | None = None, cap: int | None = None) -> None:
    """Test seam: point the spool at *path* (and optionally set the byte cap)."""
    global _SPOOL_PATH_OVERRIDE, SPOOL_CAP_BYTES
    _SPOOL_PATH_OVERRIDE = path
    if cap is not None:
        SPOOL_CAP_BYTES = cap


def emit_enforcement_event(event: dict[str, Any]) -> bool:
    """Append one enforcement event as a JSONL line. O(1), fail-open.

    Stamps a unique ``scan_id`` (prefix ``e-``) and a ``timestamp`` if absent.
    Returns ``False`` on any error and never raises (spec D5). No ``fsync``, no
    full-file rewrite.
    """
    try:
        rec = dict(event)
        rec.setdefault("scan_id", f"e-{uuid.uuid4().hex[:6]}")
        rec.setdefault("timestamp", time.time())
        line = json.dumps(rec, default=str) + "\n"
        with open(_spool_path(), "a", encoding="utf-8") as f:
            f.write(line)
        return True
    except Exception:
        return False


def spool_size(path: str | None = None) -> int:
    """Byte size of the spool, or 0 if absent/unstattable. Never raises."""
    try:
        return os.path.getsize(path if path is not None else _spool_path())
    except OSError:
        return 0


def drain_enforcement_events(path: str, after_offset: int) -> tuple[list[dict[str, Any]], int]:
    """Read complete JSONL records strictly forward from *after_offset* in *path*.

    Returns ``(events, new_offset)``. A trailing partial line (a torn mid-append
    write) is NOT consumed: *new_offset* is the byte position after the last
    COMPLETE record, so the partial line is re-read once finished. Never re-reads
    a record before *after_offset*, so each event is surfaced exactly once (no
    ``scan_id`` seen-set needed). A malformed (non-JSON / non-dict) line is skipped
    but still advances the offset past it. **Fail-safe:** any stat/read error
    returns ``([], after_offset)`` (keep last-good). Pure peek — commits no cursor
    state; the caller owns the offset and commits after a successful push.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], after_offset
    if size <= after_offset:
        return [], after_offset
    try:
        with open(path, "rb") as f:
            f.seek(after_offset)
            data = f.read()
    except OSError:
        return [], after_offset
    nl = data.rfind(b"\n")
    if nl == -1:
        return [], after_offset  # no complete record yet (only a partial line)
    complete = data[: nl + 1]
    new_offset = after_offset + len(complete)
    events: list[dict[str, Any]] = []
    for raw in complete.split(b"\n"):
        if not raw:
            continue
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception:
            continue  # skip a malformed line; offset still advances past it
        if isinstance(obj, dict):
            events.append(obj)
    return events, new_offset


def rotate_spool(path: str | None = None) -> bool:
    """Atomically rename the live spool to ``<spool>.rot``. The dashboard is the sole rotator.

    Returns ``False`` without renaming if a ``.rot`` already exists (the caller
    must recover/clear that leftover first, so its undrained events are never
    overwritten — spec edge F-2) or if the OS refuses (e.g. a Windows sharing
    violation while the gateway holds a write handle). Never raises.
    """
    p = path if path is not None else _spool_path()
    rot = p + _ROT_SUFFIX
    try:
        if os.path.exists(rot):
            return False
        if not os.path.exists(p):
            return False
        os.replace(p, rot)
        return True
    except OSError:
        return False
