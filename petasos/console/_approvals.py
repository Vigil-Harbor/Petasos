"""Refused-approvals queue and the per-profile reviewed set (PET-223).

Pure derivation plus the reviewed-file reader and writer. Stdlib only. The
queue never raises on a list of dicts. The reviewed reader never raises.
The writer returns False on any failure and never raises.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import tempfile
from typing import Any

from petasos.console._history import orderable_key
from petasos.console._paths import resolve_hermes_config_path

_REVIEWED_FILENAME = "petasos-approvals-reviewed.json"
_REVIEWED_LABEL = b"petasos/approvals-reviewed/v1"
_REVIEWED_MAX_BYTES = 1_000_000
_MAX_QUEUE_ITEMS = 1000
_MAX_ITEM_ID_LEN = 128

# Test seam. Wins unconditionally, mirroring _HISTORY_PATH_OVERRIDE.
_REVIEWED_PATH_OVERRIDE: str | None = None

REFUSAL_CHOICES = frozenset({"deny", "timeout", "cancelled", "notify_failed", "smart_deny"})
APPROVAL_CHOICES = frozenset({"once", "session", "always", "smart_approve"})
_ANSWER_CHOICES = REFUSAL_CHOICES | APPROVAL_CHOICES
_TRUSTED = frozenset({"genuine", "unattested", "foreign"})
_PETASOS_PREFIX = "plugin_rule:petasos."
_PLUGIN_PREFIX = "plugin_rule:"


def reviewed_path(res: Any = None) -> str:
    """Reviewed-file path beside the profile config. The test override wins."""
    if _REVIEWED_PATH_OVERRIDE is not None:
        return _REVIEWED_PATH_OVERRIDE
    resolved = res if res is not None else resolve_hermes_config_path(use_override=False)
    return os.path.join(str(resolved.path.parent), _REVIEWED_FILENAME)


def reviewed_key(secret: bytes) -> bytes:
    """Domain-separated HMAC key, same mechanism as the scan-history subkey."""
    return hmac.new(secret, _REVIEWED_LABEL, hashlib.sha256).digest()


def _empty_queue() -> dict[str, Any]:
    return {
        "items": [],
        "items_by_id": {},
        "total": 0,
        "pending": 0,
        "unknown": 0,
        "window_oldest": None,
        "approval_rows": 0,
        "unverifiable_count": 0,
    }


def _caps() -> tuple[int, int]:
    from petasos.console.server import _MAX_APPROVAL_DESCRIPTION_LEN, _MAX_REASON_LEN

    return _MAX_REASON_LEN, _MAX_APPROVAL_DESCRIPTION_LEN


def _cap_str(value: object, cap: int) -> str:
    if not isinstance(value, str):
        return ""
    return value[:cap]


def _cap_opt(value: object, cap: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:cap]


def _sanitize(row: dict[str, Any], field_cap: int, description_cap: int) -> dict[str, Any]:
    """Typed copy of the fields the queue reads. Non-strings become "" or None."""
    return {
        "scan_id": row.get("scan_id") if isinstance(row.get("scan_id"), str) else "",
        "timestamp": row.get("timestamp"),
        "source": row.get("source") if isinstance(row.get("source"), str) else "",
        "event_type": row.get("event_type") if isinstance(row.get("event_type"), str) else "",
        "phase": row.get("phase") if isinstance(row.get("phase"), str) else "",
        "choice": _cap_str(row.get("choice"), field_cap),
        "provenance": _cap_str(row.get("provenance"), field_cap),
        "session_key": _cap_str(row.get("session_key"), field_cap),
        "turn_id": _cap_str(row.get("turn_id"), field_cap),
        "tool_call_id": _cap_str(row.get("tool_call_id"), field_cap),
        "rule_id": _cap_opt(row.get("rule_id"), field_cap),
        "tool": _cap_opt(row.get("tool"), field_cap),
        "command": _cap_opt(row.get("command"), field_cap),
        "session_id": _cap_opt(row.get("session_id"), field_cap),
        "surface": _cap_opt(row.get("surface"), field_cap),
        "decided_by": _cap_opt(row.get("decided_by"), field_cap),
        "description": _cap_opt(row.get("description"), description_cap),
        "credential_redaction": (
            row.get("credential_redaction")
            if row.get("credential_redaction") in ("unchanged", "redacted", "withheld")
            else None
        ),
        "coalesced": row.get("coalesced") is True,
    }


def _origin(pattern_key: str | None) -> str:
    if isinstance(pattern_key, str) and pattern_key.startswith(_PETASOS_PREFIX):
        return "petasos"
    if isinstance(pattern_key, str) and pattern_key.startswith(_PLUGIN_PREFIX):
        return "plugin"
    return "hermes"


def _petasos_rule(origin: str, pattern_key: str | None) -> str | None:
    if origin != "petasos" or not isinstance(pattern_key, str):
        return None
    return pattern_key[len(_PLUGIN_PREFIX) :]


def _item(
    row: dict[str, Any],
    *,
    reviewed: frozenset[str],
    overrode: bool,
) -> dict[str, Any]:
    pattern_key = row["rule_id"]
    origin = _origin(pattern_key if isinstance(pattern_key, str) else None)
    item_id = row["scan_id"]
    return {
        "item_id": item_id,
        "choice": row["choice"],
        "at": row["timestamp"],
        "session_id": row["session_id"],
        "session_key": row["session_key"],
        "turn_id": row["turn_id"],
        "tool_call_id": row["tool_call_id"],
        "surface": row["surface"],
        "decided_by": row["decided_by"],
        "coalesced": row["coalesced"],
        "tool": row["tool"],
        "pattern_key": pattern_key,
        "origin": origin,
        "petasos_rule": _petasos_rule(
            origin, pattern_key if isinstance(pattern_key, str) else None
        ),
        "command": row["command"],
        "description": row["description"],
        "credential_redaction": row["credential_redaction"],
        "provenance": row["provenance"],
        "overrode_smart_deny": overrode,
        "reviewed": item_id in reviewed,
    }


def _prompt_key(row: dict[str, Any]) -> tuple[str, str, str] | None:
    session_key = row["session_key"]
    turn_id = row["turn_id"]
    tool_call_id = row["tool_call_id"]
    if session_key and turn_id and tool_call_id:
        return (session_key, turn_id, tool_call_id)
    return None


def _is_smart(row: dict[str, Any]) -> bool:
    surface = row.get("surface")
    return surface == "smart" if isinstance(surface, str) else False


def _override_human(deny: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Earliest qualifying human answer, or None. Ignores list order."""
    best: dict[str, Any] | None = None
    deny_at = deny["timestamp"]
    for human in rows:
        if human is deny or human["phase"] != "response" or _is_smart(human):
            continue
        if human["rule_id"] != deny["rule_id"]:
            continue
        if human["choice"] not in _ANSWER_CHOICES:
            continue
        if human["timestamp"] < deny_at:
            continue
        between = False
        for other in rows:
            if not _is_smart(other):
                continue
            if deny_at < other["timestamp"] < human["timestamp"]:
                between = True
                break
        if between:
            continue
        if best is None or (human["timestamp"], human["scan_id"]) < (
            best["timestamp"],
            best["scan_id"],
        ):
            best = human
    return best


def refused_items(rows: list[Any], reviewed: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Derive the queue. Never raises on a list whose elements are dicts or not."""
    try:
        return _refused_items(rows, reviewed)
    except Exception:
        return _empty_queue()


def _refused_items(rows: list[Any], reviewed: frozenset[str]) -> dict[str, Any]:
    field_cap, description_cap = _caps()
    kept: list[dict[str, Any]] = []
    window: float | None = None
    approval_rows = 0
    if not isinstance(rows, list):
        return _empty_queue()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        key = orderable_key(raw)
        if key is None:
            continue
        scan_id = key[1]
        if not 1 <= len(scan_id) <= _MAX_ITEM_ID_LEN:
            continue
        row = _sanitize(raw, field_cap, description_cap)
        row["scan_id"] = scan_id
        row["timestamp"] = key[0]
        kept.append(row)
        if row["provenance"] != "unverifiable" and (window is None or key[0] < window):
            window = key[0]
        if (
            row["source"] == "enforcement"
            and row["event_type"] == "approval"
            and row["phase"] in {"request", "response"}
        ):
            approval_rows += 1

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    paired_keys: set[tuple[Any, ...]] = set()
    items: list[dict[str, Any]] = []
    unknown = 0
    for row in kept:
        if row["source"] != "enforcement" or row["event_type"] != "approval":
            continue
        if row["provenance"] == "unverifiable":
            if row["phase"] == "response" and row["choice"] in REFUSAL_CHOICES:
                items.append(_item(row, reviewed=reviewed, overrode=False))
            continue
        if row["phase"] not in {"request", "response"}:
            continue
        prompt = _prompt_key(row)
        if prompt is None:
            group_key: tuple[Any, ...] = ("unpaired", row["scan_id"])
        else:
            group_key = prompt
            paired_keys.add(group_key)
        groups.setdefault(group_key, []).append(row)

    pending = 0
    for group_key, group in groups.items():
        overridden: set[str] = set()
        overrode_by: set[str] = set()
        for row in group:
            if row["phase"] == "response" and row["choice"] == "smart_deny" and _is_smart(row):
                human = _override_human(row, group)
                if human is not None:
                    overridden.add(row["scan_id"])
                    if human["choice"] in REFUSAL_CHOICES:
                        overrode_by.add(human["scan_id"])
        for row in group:
            if row["phase"] != "response":
                continue
            choice = row["choice"]
            if choice in REFUSAL_CHOICES:
                if row["scan_id"] in overridden:
                    continue
                items.append(
                    _item(
                        row,
                        reviewed=reviewed,
                        overrode=row["scan_id"] in overrode_by,
                    )
                )
            elif choice not in APPROVAL_CHOICES:
                unknown += 1
        if group_key in paired_keys:
            requests = sum(1 for row in group if row["phase"] == "request" and not _is_smart(row))
            responses = sum(
                1 for row in group if row["phase"] == "response" and not _is_smart(row)
            )
            if requests > responses:
                pending += 1

    def _band(item: dict[str, Any]) -> int:
        if item["provenance"] == "unverifiable":
            return 2
        if item["reviewed"]:
            return 1
        return 0

    items.sort(key=lambda item: item["item_id"], reverse=True)
    items.sort(key=lambda item: item["at"], reverse=True)
    items.sort(key=_band)
    unverifiable_count = sum(1 for item in items if item["provenance"] == "unverifiable")
    return {
        "items": items[:_MAX_QUEUE_ITEMS],
        "items_by_id": {item["item_id"]: item for item in items},
        "total": len(items),
        "pending": pending,
        "unknown": unknown,
        "window_oldest": window,
        "approval_rows": approval_rows,
        "unverifiable_count": unverifiable_count,
    }


def _reviewed_preimage(ids: list[str]) -> bytes:
    payload = json.dumps({"v": 1, "ids": ids}, sort_keys=True, separators=(",", ":"))
    return payload.encode("utf-8")


def read_reviewed(path: str, key: bytes | None, *, foreign: bool = False) -> tuple[set[str], str]:
    """Read the reviewed id set. Never raises. See the spec table for statuses."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return set(), "absent"
    except OSError:
        return set(), "io_error"
    if st.st_size > _REVIEWED_MAX_BYTES:
        return set(), "unreadable"
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except OSError:
        return set(), "io_error"
    except Exception:
        return set(), "unreadable"
    if not isinstance(loaded, dict):
        return set(), "unreadable"
    raw_ids = loaded.get("ids")
    if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
        return set(), "unreadable"
    ids = list(raw_ids)
    if loaded.get("v") != 1:
        return set(), "unsupported_version"
    if foreign:
        return set(ids), "foreign"
    if key is None:
        return set(ids), "unattested"
    sig = loaded.get("sig")
    if not isinstance(sig, str):
        return set(), "unverifiable"
    expected = hmac.new(key, _reviewed_preimage(ids), hashlib.sha256).hexdigest()
    try:
        # compare_digest rejects a non-ASCII str. A bad signature is unverifiable.
        sig_bytes = sig.encode("ascii")
    except UnicodeEncodeError:
        return set(), "unverifiable"
    if not hmac.compare_digest(sig_bytes, expected.encode("ascii")):
        return set(), "unverifiable"
    return set(ids), "genuine"


def write_reviewed(path: str, ids: set[str] | list[str], key: bytes | None) -> bool:
    """Atomic temp-fsync-replace write. False on any failure. Never raises."""
    try:
        sorted_ids = sorted(ids)
        payload: dict[str, Any] = {"v": 1, "ids": sorted_ids}
        if key is not None:
            payload["sig"] = hmac.new(
                key, _reviewed_preimage(sorted_ids), hashlib.sha256
            ).hexdigest()
        parent = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    except Exception:
        return False
    return True
