"""Persistent scan-history sink — newest member of the cross-process file-sink family.

PET-148: the console scan history is an in-memory ``RingBuffer(maxlen=500)`` (the fast
path for the most recent window). This module is the *append-only, size/rotation-bounded
on-disk sink* that gives the Observability tab real back-pages: a cursor on
``get_scan_history`` seeks past the ring into here for scans older than the 500-entry
window. Modeled line-for-line on ``_events.py`` (the PET-139 enforcement spool) — same
O(1)-append / fail-open writer / fail-safe reader / single-``.rot`` rotation / stdlib-only
mechanics — with its own filename, domain label, and byte cap (no shared cursor, no shared
key).

Posture (matches the family):

* **Writer is fail-open.** ``append_history_row`` returns ``False`` on any error and never
  raises — a persistence error must never gate or slow a scan (D-CHOKEPOINT). It is an O(1)
  append (no full-file rewrite, no ``fsync``).
* **Reader is fail-safe.** ``read_history_page`` returns ``([], False)`` (or what it
  gathered) on any error and never raises; it parses both segments (live + ``.rot``) and
  orders by ``(timestamp, scan_id)`` key, not by segment, so a row appended during a
  rotation race stays correctly placed.
* **Path recomputed per call** over ``resolve_hermes_config_path()`` so the sink is
  per-Hermes-profile automatically (one profile's rows cannot land in another's state dir).

Two deliberate divergences from ``_events.py``:

* **Rotation reclaims** (``rotate_history`` unlinks any existing ``.rot`` first, then renames
  live -> ``.rot``). The spool *refuses* to rotate when a ``.rot`` exists (its undrained
  enforcement events must never be dropped); the history sink is a queryable store whose
  oldest rows are *meant* to age out (D-ROTATION, bounded-retention contract).
* **The HMAC key is a parameter**, not a module global. The caller (``ConsoleHandlers``)
  derives it once from ``session_secret`` and passes it on every append/verify, so this
  module holds no key state of its own.

Never raises out of any public function.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

from petasos.console._paths import resolve_hermes_config_path

_HISTORY_FILENAME = "petasos-scan-history.jsonl"
_ROT_SUFFIX = ".rot"

# Hard cap; mirrors the spool's SPOOL_CAP_BYTES value so the two sinks share one footprint
# story, but decoupled in its own constant so either can change without the other. At the
# documented PII-minimized row size (~400 B serialized) this implies ~5,000 rows per segment
# and, with the single .rot, ~10,000 rows of retained depth (~20x the 500-entry ring) while
# staying < 2 x _HISTORY_CAP_BYTES (~4 MB) on disk. NOT a config field — a cap is not a
# tuning dial (the same caps-aren't-config rule that forbade scan_history_capacity in
# PET-144). Module-level so a test seam can shrink it to force rotation.
_HISTORY_CAP_BYTES = 2_000_000

# Test seam (mirrors _events._SPOOL_PATH_OVERRIDE): point the sink at a temp file. None =>
# resolve beside the live config.
_HISTORY_PATH_OVERRIDE: str | None = None


def _history_path() -> str:
    """Resolve the sink path beside the active config (recomputed per call)."""
    if _HISTORY_PATH_OVERRIDE is not None:
        return _HISTORY_PATH_OVERRIDE
    res = resolve_hermes_config_path()
    return os.path.join(str(res.path.parent), _HISTORY_FILENAME)


def _reset_history_state(path: str | None = None, cap: int | None = None) -> None:
    """Test seam: point the sink at *path* (and optionally set the byte cap)."""
    global _HISTORY_PATH_OVERRIDE, _HISTORY_CAP_BYTES
    _HISTORY_PATH_OVERRIDE = path
    if cap is not None:
        _HISTORY_CAP_BYTES = cap


def _derive_history_key(secret: bytes) -> bytes:
    """Domain-separated subkey for scan-history attestation (D-ATTEST).

    HMAC-SHA256(secret, ``b"petasos/scan-history/v1"``). A *new* domain label — never the
    raw secret, never the enforcement-spool subkey (``b"petasos/enforcement-spool/v1"``) —
    so the two on-disk sinks' attestations cannot cross-interfere. The ``v1`` label leaves
    room for a future rotation without ambiguity. Reimplements PET-139's
    ``_derive_spool_key`` *mechanism* with this label (one HMAC line); a shared
    ``_derive_subkey(secret, label)`` is deliberately NOT extracted now — it would touch the
    shipped PET-139 path for no present need, and co-locating each label with its module
    keeps the domain separation auditable.
    """
    return hmac.new(secret, b"petasos/scan-history/v1", hashlib.sha256).digest()


def verify_history_row(row: object, key: bytes | None) -> bool:
    """True iff *key* is set and ``row["sig"]`` matches the recomputed HMAC. Never raises.

    Pure and total (mirrors ``verify_event``): a ``None`` key, a non-dict input, a
    missing/non-string ``sig``, or any serialization error all resolve to ``False``. A
    ``None`` key returns ``False`` so the caller can map "no key configured" to "unattested"
    (still trusted) and distinguish it from a real verify failure ("unverifiable"); the
    *caller* owns that trust decision. The ``object`` annotation + explicit ``isinstance``
    guard keep it total under ``mypy --strict``.
    """
    if key is None or not isinstance(row, dict):
        return False  # None-key => caller maps to "unattested", not "unverifiable"
    try:
        sig = row.get("sig")
        if not isinstance(sig, str):
            return False
        rest = {k: v for k, v in row.items() if k != "sig"}
        preimage = json.dumps(rest, sort_keys=True, separators=(",", ":"), default=str)
        expected = hmac.new(key, preimage.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def append_history_row(row: dict[str, Any], key: bytes | None) -> bool:
    """Append one persisted scan-history row as a JSONL line. O(1), fail-open.

    Defensively stamps ``scan_id`` / ``timestamp`` if absent (the summary already carries
    both). When *key* is set, stamps ``rec["sig"]`` over the canonical serialization
    (``sort_keys=True``, before ``sig`` is added) exactly as ``emit_enforcement_event`` does,
    so the reader can attest provenance; a ``None`` key writes an unsigned line (read as
    "unattested"). Returns ``False`` on ANY exception — which includes the parent dir not
    existing (unlike the spool, the gateway does not pre-create this sink's dir): on a profile
    whose state dir is absent the append is a fail-open no-op, surfaced by the caller's
    one-shot tripwire, never a crash. No ``fsync``, no full-file rewrite.
    """
    try:
        rec = dict(row)
        # Full uuid hex (the playground id is also widened to full hex at the call site):
        # scan_id is the cursor's tie-breaker and the dedup key, so it must not collide
        # within the ~10 k-row retention. The `s-`/`e-` prefixes keep the keyspaces distinct.
        rec.setdefault("scan_id", f"s-{uuid.uuid4().hex}")
        rec.setdefault("timestamp", time.time())
        if key is not None:
            preimage = json.dumps(rec, sort_keys=True, separators=(",", ":"), default=str)
            rec["sig"] = hmac.new(key, preimage.encode("utf-8"), hashlib.sha256).hexdigest()
        line = json.dumps(rec, default=str) + "\n"
        with open(_history_path(), "a", encoding="utf-8") as f:
            f.write(line)
        return True
    except Exception:
        return False


def history_size(path: str | None = None) -> int:
    """Byte size of the live sink segment, or 0 if absent/unstattable. Never raises."""
    try:
        return os.path.getsize(path if path is not None else _history_path())
    except OSError:
        return 0


def read_history_page(
    path: str, *, before: tuple[float, str] | None, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    """Return the page of rows immediately older than *before*, newest-first. Fail-safe.

    Reads BOTH segments (the live ``path`` and ``path + .rot``; either may be absent),
    parses complete JSON lines (a malformed or torn line ANYWHERE is skipped per-line, not
    only a trailing partial), filters rows whose ``(timestamp, scan_id)`` is strictly
    ``< before`` (or all rows when ``before is None``), sorts the survivors by
    ``(timestamp, scan_id)`` DESCENDING, and returns the newest *limit*. Segment boundaries
    are NOT assumed chronological (a row appended during a rotation race can land in
    ``.rot``), so ordering is by key, not by segment.

    Returns ``(rows, older_truncated)``. ``older_truncated`` is ``True`` iff *before* is
    non-None, the page is empty, AND *before* is strictly older than the global oldest
    retained row (the cursor's segment was reclaimed by a concurrent rotation — D-ROTATION),
    so the caller can tell a reclaimed cursor from a true bottom. When the sink is empty
    (no global oldest to compare against) ``older_truncated`` is ``False`` (the bottom is
    simply empty, not truncated). Rows missing a numeric ``timestamp`` or string ``scan_id``
    are skipped (cannot be ordered). Any read/parse error degrades to "return what was
    gathered"; never raises.

    Cost: O(retained) — parses the whole retained sink (<= 2 x _HISTORY_CAP_BYTES, ~10 k
    lines) and sorts it. Acceptable because it runs on the operator's paging click, not the
    scan hot path, and the sink is hard-capped.
    """
    survivors: list[tuple[tuple[float, str], dict[str, Any]]] = []
    global_oldest: tuple[float, str] | None = None
    for segment in (path, path + _ROT_SUFFIX):
        try:
            with open(segment, "rb") as f:
                data = f.read()
        except OSError:
            continue  # segment absent / unreadable -> contribute nothing
        for raw in data.split(b"\n"):
            if not raw:
                continue
            try:
                obj = json.loads(raw.decode("utf-8"))
            except Exception:
                continue  # skip a malformed / torn line anywhere in the segment
            if not isinstance(obj, dict):
                continue
            ts = obj.get("timestamp")
            sid = obj.get("scan_id")
            # bool is an int subclass; a True/False timestamp is not orderable telemetry.
            if isinstance(ts, bool) or not isinstance(ts, (int, float)):
                continue
            if not isinstance(sid, str):
                continue
            key = (float(ts), sid)
            if global_oldest is None or key < global_oldest:
                global_oldest = key
            if before is None or key < before:
                survivors.append((key, obj))
    survivors.sort(key=lambda kv: kv[0], reverse=True)
    page = [obj for _, obj in survivors[: limit if limit > 0 else 0]]
    older_truncated = (
        before is not None and not page and global_oldest is not None and before < global_oldest
    )
    return page, older_truncated


def rotate_history(path: str | None = None) -> bool:
    """Reclaim the oldest segment, then rename the live sink to ``<sink>.rot``. Never raises.

    THE deliberate divergence from ``_events.rotate_spool``: it unlinks any existing ``.rot``
    FIRST (dropping the oldest retained segment — the bounded-retention contract), then
    renames the live segment to ``.rot``. At any instant the sink is ``live + at most one
    .rot``, so the on-disk footprint stays ``< 2 x _HISTORY_CAP_BYTES``. Returns ``False``
    (no-op) when the live segment is absent or the OS refuses (e.g. a Windows sharing
    violation while an append handle is briefly open) — retried next cycle.
    """
    p = path if path is not None else _history_path()
    rot = p + _ROT_SUFFIX
    try:
        if os.path.exists(rot):
            os.remove(rot)  # reclaim the oldest retained segment (D-ROTATION)
        if not os.path.exists(p):
            return False
        os.replace(p, rot)
        return True
    except OSError:
        return False
