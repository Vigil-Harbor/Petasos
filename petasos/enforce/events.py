"""Signed enforcement-event spool.

The writer and the reader run in separate processes. On every block, quarantine,
tier-3, or disarmed-bypass decision the writer appends a structured enforcement
event here; a reader drains the spool forward from a byte offset. The spool is
the file. Path resolution belongs to the host: this module never chooses a
directory.

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
* **Writer path.** A caller passes ``path`` or a ``res`` the installed resolver
  understands. ``use_override=False`` asks the resolver for the process binding.

Never raises out of any public function.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

# The rotated sibling keeps the historical suffix. Hosts that name the live file
# name the rotated file by appending this.
_ROT_SUFFIX = ".rot"

# The host installs both. The resolver returns the spool path; the setter is how
# ``_reset_events_state`` retargets that resolver's override. Neither is imported
# from a host package.
_SpoolResolver = Callable[..., str]
_OverrideSetter = Callable[[str | None], None]
_resolver: _SpoolResolver | None = None
_override_setter: _OverrideSetter | None = None

# Sized well above the motivating burst (~40 blocks / 2h18m, ~300 B/line) and far
# above one tailer interval's worth at peak rate. Module-level so a test
# can shrink it via _reset_events_state to force rotation.
SPOOL_CAP_BYTES = 2_000_000


def install_spool_resolver(resolver: _SpoolResolver, override_setter: _OverrideSetter) -> None:
    """Bind the host's path function and the setter for its test override.

    The resolver is called as ``resolver(res, use_override=...)``. ``res`` is
    whatever the host uses to name a config file; this module does not look
    inside it. The setter receives the override path, or ``None`` to clear it.
    """
    global _resolver, _override_setter
    _resolver = resolver
    _override_setter = override_setter


def _spool_path(res: object | None = None, *, use_override: bool = True) -> str:
    """Resolve the spool path through the installed host resolver."""
    if _resolver is None:
        raise RuntimeError("enforcement spool path resolver is not installed")
    return _resolver(res, use_override=use_override)


def _reset_events_state(path: str | None = None, cap: int | None = None) -> None:
    """Test seam: point the spool at *path* (and optionally set the byte cap)."""
    global SPOOL_CAP_BYTES
    if _override_setter is None:
        raise RuntimeError("enforcement spool path resolver is not installed")
    _override_setter(path)
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
# Path-keyed writer keys. Lookup is this map, then the fallback ``_SPOOL_KEY``.
_SPOOL_KEYS: dict[str, bytes] = {}


def _derive_spool_key(secret: bytes) -> bytes:
    """Domain-separated subkey for spool attestation (D3): HMAC-SHA256(secret, label).

    The ``v1`` label leaves room for a future rotation without ambiguity and keeps this
    key distinct from any other HMAC use of the same ``session_secret``.
    """
    return hmac.new(secret, b"petasos/enforcement-spool/v1", hashlib.sha256).digest()


class EventSpool:
    """A signed enforcement spool at one explicit path.

    ``secret`` is the session secret. The file key is derived from it, and
    ``None`` writes unsigned lines. The path, the key and the byte cap belong
    to this object. Two spools in one process do not share them, and this
    object does not read or write the legacy module-level writer.
    """

    def __init__(
        self,
        path: str,
        *,
        secret: bytes | None = None,
        cap: int = SPOOL_CAP_BYTES,
    ) -> None:
        self._path = os.fspath(path)
        self._cap = cap
        self._key = _derive_spool_key(secret) if secret else None

    @property
    def path(self) -> str:
        """The live spool file."""
        return self._path

    @property
    def cap(self) -> int:
        """The byte cap a reader uses when it decides to rotate."""
        return self._cap

    def set_secret(self, secret: bytes | None) -> None:
        """Replace the signing key. ``None`` leaves later lines unsigned."""
        self._key = _derive_spool_key(secret) if secret else None

    def emit(self, event: Mapping[str, Any]) -> bool:
        """Append one event. Returns ``False`` on any error and never raises."""
        try:
            _append_record(dict(event), self._path, self._key)
            return True
        except Exception:
            return False


def set_spool_key(secret: bytes | None, *, path: str | None = None) -> None:
    """Install the spool HMAC key derived from *secret*, or ``None`` to disable integrity.

    *path* stores the derived key under ``normcase(path)``. Omitting *path* stores the
    fallback ``_SPOOL_KEY`` so single-home callers keep working. Idempotent: re-deriving
    from the same secret installs identical bytes (session_secret is restart-required and
    env-reinjected, so the derived key is invariant for a process lifetime, D3). Order
    note: ``_reset_events_state`` does NOT touch the key, so a test that needs both should
    call ``_reset_events_state(...)`` first, then ``set_spool_key(...)``.
    """
    global _SPOOL_KEY
    derived = _derive_spool_key(secret) if secret else None
    if path is None:
        _SPOOL_KEY = derived
        return
    slot = os.path.normcase(path)
    if derived is None:
        _SPOOL_KEYS.pop(slot, None)
    else:
        _SPOOL_KEYS[slot] = derived


def _reset_spool_key() -> None:
    """Test seam: clear the writer keys independently of path/cap reset."""
    global _SPOOL_KEY
    _SPOOL_KEY = None
    _SPOOL_KEYS.clear()


def _spool_key_for(path: str) -> bytes | None:
    """Key for *path*, else the fallback. Never raises."""
    return _SPOOL_KEYS.get(os.path.normcase(path), _SPOOL_KEY)


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


def _append_record(rec: dict[str, Any], spool: str, key: bytes | None) -> None:
    """Stamp, sign, and append one JSONL record. Raises on failure; callers fail open.

    PET-139 signing is unchanged: HMAC over the canonical serialization of the whole
    record after the identity fields and before ``sig``. A ``None`` key writes an
    unsigned line.
    """
    # Full uuid hex (not a 6-char prefix): enforcement is high-volume (a 45%-block
    # session mints thousands of ids) and scan_id feeds the frontend seed-dedup, so
    # adequate entropy avoids cross-event collisions. The `e-` prefix keeps it
    # distinct from the playground `s-<hex>` keyspace.
    rec.setdefault("scan_id", f"e-{uuid.uuid4().hex}")
    rec.setdefault("timestamp", time.time())
    if key is not None:
        preimage = json.dumps(rec, sort_keys=True, separators=(",", ":"), default=str)
        rec["sig"] = hmac.new(key, preimage.encode("utf-8"), hashlib.sha256).hexdigest()
    line = json.dumps(rec, default=str) + "\n"
    with open(spool, "a", encoding="utf-8") as handle:
        handle.write(line)


def emit_enforcement_event(
    event: dict[str, Any],
    *,
    path: str | None = None,
    res: object | None = None,
) -> bool:
    """Append one enforcement event as a JSONL line. O(1), fail-open.

    Stamps a unique ``scan_id`` (prefix ``e-``) and a ``timestamp`` if absent.
    Returns ``False`` on any error and never raises (spec D5). No ``fsync``, no
    full-file rewrite.
    """
    try:
        rec = dict(event)
        spool = path if path is not None else _spool_path(res)
        _append_record(rec, spool, _spool_key_for(spool))
        return True
    except Exception:
        return False


def emit_console_event(event: dict[str, Any], *, key: bytes | None) -> bool:
    """Append one console audit row to the process-binding spool (PET-223).

    The key is passed in. This does not touch the process-wide writer map, so a
    console that shares a process with the plugin cannot retarget plugin signing.
    """
    try:
        rec = dict(event)
        _append_record(rec, _spool_path(use_override=False), key)
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
