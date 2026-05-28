"""Circular-safe, depth-limited JSON stringification."""

from __future__ import annotations

import json
from typing import Any

_DEFAULT_MAX_DEPTH = 32
_DEFAULT_MAX_SIZE = 1_000_000


def safe_json_dumps(
    value: Any,
    *,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    max_size: int = _DEFAULT_MAX_SIZE,
) -> str:
    """Stringify *value* without raising on circular refs, deep nesting, or
    non-serializable types.  Returns a truncated/placeholder string on any
    failure -- never throws."""
    seen: set[int] = set()

    def _default(obj: object) -> str:
        return f"[Unserializable: {type(obj).__name__}]"

    def _walk(obj: Any, depth: int) -> Any:
        if depth > max_depth:
            return "[Depth limit]"
        if isinstance(obj, dict):
            obj_id = id(obj)
            if obj_id in seen:
                return "[Circular]"
            seen.add(obj_id)
            try:
                return {k: _walk(v, depth + 1) for k, v in obj.items()}
            finally:
                seen.discard(obj_id)
        if isinstance(obj, (list, tuple)):
            obj_id = id(obj)
            if obj_id in seen:
                return "[Circular]"
            seen.add(obj_id)
            try:
                return [_walk(item, depth + 1) for item in obj]
            finally:
                seen.discard(obj_id)
        return obj

    try:
        sanitized = _walk(value, 0)
        text = json.dumps(sanitized, default=_default)
    except Exception:
        return '"[Unserializable]"'

    if len(text) > max_size:
        return text[:max_size] + "...[truncated]"
    return text
