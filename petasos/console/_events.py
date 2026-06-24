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

import hashlib
import hmac
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


# PET-139: enforcement-event integrity. The spool key is a *domain-separated subkey*
# derived from session_secret (D3), never the raw secret — so the FREQ-03 session-binding
# use and this spool-attestation use cannot cross-interfere. ``None`` => integrity off: no
# ``sig`` is stamped and the reader maps an unkeyed deployment to "unattested" (the PET-131
# no-regression path). Held in its OWN global with a dedicated reset, decoupled from
# _reset_events_state's path/cap reset, so a `_reset_events_state` call after `set_spool_key`
# cannot silently disarm signing.
_SPOOL_KEY: bytes | None = None


def _derive_spool_key(secret: bytes) -> bytes:
    """Domain-separated subkey for spool attestation (D3): HMAC-SHA256(secret, label).

    The ``v1`` label leaves room for a future rotation without ambiguity and keeps this
    key distinct from any other HMAC use of the same ``session_secret``.
    """
    return hmac.new(secret, b"petasos/enforcement-spool/v1", hashlib.sha256).digest()


def set_spool_key(secret: bytes | None) -> None:
    """Install the spool HMAC key derived from *secret*, or ``None`` to disable integrity.

    Idempotent: re-deriving from the same secret installs identical bytes (session_secret is
    restart-required and env-reinjected, so the derived key is invariant for a process
    lifetime, D3). Order note: ``_reset_events_state`` does NOT touch the key, so a test that
    needs both should call ``_reset_events_state(...)`` first, then ``set_spool_key(...)``.
    """
    global _SPOOL_KEY
    _SPOOL_KEY = _derive_spool_key(secret) if secret else None


def _reset_spool_key() -> None:
    """Test seam: clear the writer key independently of path/cap reset."""
    global _SPOOL_KEY
    _SPOOL_KEY = None


def verify_event(ev: object, key: bytes | None) -> bool:
    """True iff *key* is set and ``ev["sig"]`` matches the recomputed HMAC. Never raises (D6).

    Pure and total: a ``None`` key, a non-dict input, a missing/non-string ``sig``, or any
    serialization error all resolve to ``False``. A ``None`` key returns ``False`` so the
    caller can distinguish "no key configured" (which it maps to "unattested" — still trusted
    and counted) from a real verify failure (mapped to "unverifiable"); the *caller* owns that
    trust decision, not this function. The ``object`` annotation + explicit ``isinstance`` guard
    keep it total under ``mypy --strict`` even though the live drain only ever passes dicts.
    """
    if key is None or not isinstance(ev, dict):
        return False  # None-key => caller maps to "unattested", not "unverifiable"
    try:
        sig = ev.get("sig")
        if not isinstance(sig, str):
            return False
        rest = {k: v for k, v in ev.items() if k != "sig"}
        preimage = json.dumps(rest, sort_keys=True, separators=(",", ":"), default=str)
        expected = hmac.new(key, preimage.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def classify_integrity_failure(record: object) -> str:
    """Name the failure class of a record that failed verification (PET-157 D3).

    The single source of truth for the ``sig-missing`` / ``sig-mismatch`` split, consumed by
    the live drain's log tripwire (``_log_integrity_failure``), the ``get_health`` integrity
    field, and the boot preflight, so the three can never drift. Pure and total, mirroring
    ``verify_event``'s posture: a non-dict input or a missing/non-string ``sig`` is
    ``"sig-missing"``; a present string ``sig`` that nonetheless failed verification is
    ``"sig-mismatch"``. The *caller* owns the trust decision — this only names the class
    once verification has already failed.

    Empty-string ``sig`` corner (preserved, not refined): ``sig == ""`` classifies as
    ``"sig-mismatch"`` (``isinstance("", str)`` is ``True``), byte-identical to the
    pre-PET-157 inline expression it replaces.
    """
    if not isinstance(record, dict) or not isinstance(record.get("sig"), str):
        return "sig-missing"
    return "sig-mismatch"


def emit_enforcement_event(event: dict[str, Any]) -> bool:
    """Append one enforcement event as a JSONL line. O(1), fail-open.

    Stamps a unique ``scan_id`` (prefix ``e-``) and a ``timestamp`` if absent.
    Returns ``False`` on any error and never raises (spec D5). No ``fsync``, no
    full-file rewrite.
    """
    try:
        rec = dict(event)
        # Full uuid hex (not a 6-char prefix): enforcement is high-volume (a 45%-block
        # session mints thousands of ids) and scan_id feeds the frontend seed-dedup, so
        # adequate entropy avoids cross-event collisions. The `e-` prefix keeps it
        # distinct from the playground `s-<hex>` keyspace.
        rec.setdefault("scan_id", f"e-{uuid.uuid4().hex}")
        rec.setdefault("timestamp", time.time())
        # PET-139: stamp a keyed HMAC over the canonical serialization of the whole record
        # (after the identity fields above, before `sig` is added), so the reader can attest
        # provenance (D1). Signing the whole record — not a field whitelist — makes the tag
        # cover every present and future field (e.g. PET-138's `bypassed_count`) automatically.
        # `sort_keys=True` makes writer and reader agree regardless of insertion order;
        # `default=str` mirrors the on-disk serialization below so preimage and line share one
        # discipline. `None` key => integrity off (unsigned line, read as "unattested"). Stays
        # inside the fail-open try (D6): a signing error returns False, never raises into the
        # tool call. CPU-only microseconds — no fsync, no extra handle, O(1) append preserved.
        if _SPOOL_KEY is not None:
            preimage = json.dumps(rec, sort_keys=True, separators=(",", ":"), default=str)
            rec["sig"] = hmac.new(_SPOOL_KEY, preimage.encode("utf-8"), hashlib.sha256).hexdigest()
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
