"""Append signed events and drain complete records with restart-independent cursors.

See docs/architecture/rationale.md, "Enforcement spool integrity"."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

# Hosts locate the rotated sibling by appending this suffix.
_ROT_SUFFIX = ".rot"

# The host installs both. The resolver returns the spool path; the setter is how
# ``_reset_events_state`` retargets that resolver's override. Neither is imported
# from a host package.
_SpoolResolver = Callable[..., str]
_OverrideSetter = Callable[[str | None], None]
_resolver: _SpoolResolver | None = None
_override_setter: _OverrideSetter | None = None

# See docs/architecture/rationale.md, "Enforcement spool integrity".
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


# See docs/architecture/rationale.md, "Enforcement spool integrity".
_SPOOL_KEY: bytes | None = None
_SPOOL_KEYS: dict[str, bytes] = {}


def _derive_spool_key(secret: bytes) -> bytes:
    """Derive an attestation key separated from session-token authentication."""
    return hmac.new(secret, b"petasos/enforcement-spool/v1", hashlib.sha256).digest()


class EventSpool:
    """Append events with a path, signing key and cap isolated to this instance."""

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
    """Set a path-specific or fallback signing key derived from the session secret.

    Path/cap resets preserve signing keys. None removes the selected key."""
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


def verification_key(secret: bytes | None) -> bytes | None:
    """The spool HMAC key for ``secret``, or None when events are unsigned.

    This is the same derivation the writer uses. It does not store the secret
    and it does not change the process-wide writer key.
    """
    if not secret:
        return None
    return _derive_spool_key(secret)


def verify_event(ev: object, key: bytes | None) -> bool:
    """Return whether a configured key authenticates the record, without raising.

    Absent keys, invalid records and serialization failures return False.
    The caller decides whether an absent key means unattested or untrusted."""
    if key is None or not isinstance(ev, dict):
        return False  # The caller distinguishes unattested deployment from failed verification.
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
    """Classify a failed signature as missing or mismatched without raising.

    Any string signature, including an empty string, is mismatched after
    verification fails; absent and non-string signatures are missing."""
    if not isinstance(record, dict) or not isinstance(record.get("sig"), str):
        return "sig-missing"
    return "sig-mismatch"


def _append_record(rec: dict[str, Any], spool: str, key: bytes | None) -> None:
    """Stamp, sign and append one JSONL record, raising on write failure."""
    # See docs/architecture/rationale.md, "Enforcement spool integrity".
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
    """Append one event or return False on failure without raising."""
    try:
        rec = dict(event)
        spool = path if path is not None else _spool_path(res)
        _append_record(rec, spool, _spool_key_for(spool))
        return True
    except Exception:
        return False


def emit_console_event(event: dict[str, Any], *, key: bytes | None) -> bool:
    """Append an audit event using its explicit key without changing plugin signing."""
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
        return [], after_offset
    complete = data[: nl + 1]
    new_offset = after_offset + len(complete)
    events: list[dict[str, Any]] = []
    for raw in complete.split(b"\n"):
        if not raw:
            continue
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events, new_offset


def rotate_spool(path: str | None = None) -> bool:
    """Rotate the live spool only when no undrained rotated sibling exists.

    OS refusal returns False without raising."""
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
