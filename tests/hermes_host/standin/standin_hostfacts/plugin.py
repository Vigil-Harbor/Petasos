"""``register`` for the directory plugin that fronts this wheel."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

HOOKS = (
    "pre_tool_call",
    "post_tool_call",
    "transform_tool_result",
    "on_session_start",
    "subagent_start",
    "subagent_stop",
    "pre_approval_request",
    "post_approval_response",
)


def _short(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        text: object = value
    else:
        text = repr(value)
    if isinstance(text, str) and len(text) > 600:
        return text[:600] + "..."
    return text


def register(ctx: Any) -> None:
    """Register one callback per hook. Each callback reads ``STANDIN_BEHAVIOR`` at call time."""
    plugin_id = str(ctx.plugin_id)

    def behavior_for(hook: str) -> dict[str, Any]:
        raw = os.environ.get("STANDIN_BEHAVIOR", "")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        plugin_spec = data.get(plugin_id, {})
        if not isinstance(plugin_spec, dict):
            return {}
        hook_spec = plugin_spec.get(hook, {})
        return hook_spec if isinstance(hook_spec, dict) else {}

    def log(hook: str, kwargs: dict[str, Any], returned: object) -> None:
        path = os.environ.get("STANDIN_LOG", "")
        if not path:
            return
        record = {
            "plugin": plugin_id,
            "hook": hook,
            "keys": sorted(kwargs),
            "kwargs": {key: _short(val) for key, val in kwargs.items()},
            "returned": _short(returned),
        }
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def make(hook: str) -> Any:
        def callback(**kwargs: Any) -> Any:
            spec = behavior_for(hook)
            delay = spec.get("sleep")
            if isinstance(delay, (int, float)) and delay > 0:
                time.sleep(float(delay))
            if spec.get("raise"):
                raise RuntimeError(str(spec["raise"]))
            returned = spec.get("return") if "return" in spec else None
            log(hook, kwargs, returned)
            return returned

        callback.__name__ = f"on_{hook}"
        return callback

    for hook in HOOKS:
        ctx.register_hook(hook, make(hook))
