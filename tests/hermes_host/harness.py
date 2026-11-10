"""In-process Hermes helpers.

Run this file with the sandbox interpreter, through ``bin/with-sandbox``, so
``HOME`` and ``HERMES_HOME`` are already inside the sandbox. Pytest drives it
as a subprocess and reads one JSON object from stdout.

The module does not import Hermes at import time. A default Petasos ``pytest``
run never executes it.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

if __name__ == "__main__" and __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.hermes_host.sandbox_guard import hermes_home, sandbox_root

ROOT = Path(__file__).resolve().parent
STANDIN_PKG = ROOT / "standin"
PLUGIN_DIR = STANDIN_PKG / "plugin"
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


def _sandbox() -> Path:
    return sandbox_root()


def _home() -> Path:
    return hermes_home()


def _import(name: str) -> Any:
    return importlib.import_module(name)


def _manager() -> Any:
    plugins = _import("hermes_cli.plugins")
    manager = plugins.get_plugin_manager()
    manager.discover_and_load()
    return manager


def _write_enabled(names: list[str]) -> None:
    config_mod = _import("hermes_cli.config")
    path = _home() / "config.yaml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("plugins:\n  enabled: []\n", encoding="utf-8")
    config = config_mod.load_config()
    plugins = config.setdefault("plugins", {})
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
    for name in names:
        if name not in enabled:
            enabled.append(name)
    plugins["enabled"] = enabled
    disabled = plugins.get("disabled")
    if isinstance(disabled, list):
        plugins["disabled"] = [item for item in disabled if item not in names]
    config_mod.save_config(
        config,
        preserve_keys={("plugins", "enabled"), ("plugins", "disabled")},
    )


def _copy_plugin(name: str) -> Path:
    dest = _home() / "plugins" / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PLUGIN_DIR, dest)
    text = (dest / "plugin.yaml").read_text(encoding="utf-8")
    renamed = text.replace("name: standin-hostfacts", f"name: {name}", 1)
    (dest / "plugin.yaml").write_text(renamed, encoding="utf-8")
    project = (dest / "pyproject.toml").read_text(encoding="utf-8")
    project = project.replace('name = "standin-hostfacts-plugin"', f'name = "{name}"', 1)
    (dest / "pyproject.toml").write_text(project, encoding="utf-8")
    return dest


def _standin_wheel() -> Path:
    """Build the stand-in wheel into the sandbox and return its path."""
    sandbox = _sandbox()
    dist = sandbox / "dist"
    if dist.exists():
        for stale in dist.glob("standin_hostfacts-*.whl"):
            stale.unlink()
    dist.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist)],
        cwd=STANDIN_PKG,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = sorted(dist.glob("standin_hostfacts-*.whl"))
    if not wheels:
        raise RuntimeError(f"no wheel in {dist}")
    return wheels[-1]


def install_standin_wheel(_request: dict[str, Any]) -> dict[str, Any]:
    """Install the stand-in wheel into the sandbox interpreter. No home is written."""
    wheel = _standin_wheel()
    subprocess.run(
        ["uv", "pip", "install", "--python", sys.executable, "--reinstall", str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    return {"ok": True, "wheel": str(wheel)}


def prepare_standin_home(_request: dict[str, Any]) -> dict[str, Any]:
    """Copy both stand-in directories into this home and enable them."""
    _sandbox()
    installed = [_copy_plugin("standin-hostfacts"), _copy_plugin("standin-b")]
    _write_enabled(["standin-hostfacts", "standin-b"])
    return {"ok": True, "plugins": [str(path) for path in installed]}


def ensure_plugin(request: dict[str, Any]) -> dict[str, Any]:
    """Wheel plus both directories. Tests use the two steps separately."""
    wheel = install_standin_wheel(request)
    home = prepare_standin_home(request)
    return {"ok": True, "wheel": wheel["wheel"], "plugins": home["plugins"]}


def validate(request: dict[str, Any]) -> dict[str, Any]:
    """Run the checker behind ``hermes plugins validate`` on ``path``.

    Calling ``validate_plugin_dir`` keeps the profile-override in ``hermes_cli.main``
    from retargeting ``HERMES_HOME`` when a sticky ``active_profile`` is set.
    """
    checker = _import("hermes_cli.plugin_validate")
    report = checker.validate_plugin_dir(Path(request["path"]))
    return {"ok": report.ok, "code": report.exit_code, "report": report.to_dict()}


def parse_kind(request: dict[str, Any]) -> dict[str, Any]:
    manifest_mod = _import("hermes_cli.plugins_manifest")
    path = Path(request["path"])
    manifest = manifest_mod.parse_manifest_file(path / "plugin.yaml", path, "user", "")
    if manifest is None:
        return {"kind": None}
    return {
        "kind": manifest.kind,
        "key": manifest.key,
        "provides_hooks": list(manifest.provides_hooks),
    }


def _context(plugin_id: str) -> Any:
    manager = _manager()
    plugins = _import("hermes_cli.plugins")
    loaded = manager._plugins[plugin_id]
    return plugins.PluginContext(loaded.manifest, manager), manager


def settings(request: dict[str, Any]) -> dict[str, Any]:
    """Read or write one plugin setting and return what ``ctx.get_config`` sees."""
    for key, value in (request.get("env") or {}).items():
        os.environ[str(key)] = str(value)
    ctx, _loaded = _context(request.get("plugin", "standin-hostfacts"))
    op = request.get("op", "get")
    key = str(request.get("key", "role"))
    form_error = ""
    if op == "set":
        ctx.set_config(key, request.get("value"))
    elif op == "form_set":
        settings_mod = _import("hermes_cli.plugins_settings")
        plugin = ctx._manager._plugins[ctx.plugin_id]
        try:
            settings_mod.save_plugin_settings(
                ctx.plugin_id,
                Path(plugin.manifest.path),
                request["values"],
            )
        except ValueError as exc:
            form_error = str(exc)
    default = request.get("default", "SENTINEL")
    return {
        "plugin_id": ctx.plugin_id,
        "value": ctx.get_config(key, default),
        "form_error": form_error,
        "yaml": (_home() / "config.yaml").read_text(encoding="utf-8"),
    }


def _log_path() -> Path:
    path = Path(os.environ.get("TMPDIR", "/tmp")) / "standin-hook-log.jsonl"
    path.unlink(missing_ok=True)
    return path


def _read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(cast("dict[str, Any]", json.loads(line)))
    return rows


def _apply_behavior(request: dict[str, Any], hook: str, log: Path) -> None:
    os.environ["STANDIN_LOG"] = str(log)
    if "behaviors" in request:
        os.environ["STANDIN_BEHAVIOR"] = json.dumps(request["behaviors"])
        return
    behavior = request.get("behavior") or {}
    os.environ["STANDIN_BEHAVIOR"] = json.dumps(
        {
            "standin-hostfacts": {hook: behavior},
            "standin-b": {hook: {}},
        }
    )


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    """Drive one hook through Hermes's dispatcher and return the host decision plus the kwargs."""
    hook = str(request["hook"])
    log = _log_path()
    _apply_behavior(request, hook, log)
    _manager()
    host: dict[str, Any]
    if hook == "pre_tool_call":
        plugins = _import("hermes_cli.plugins")
        block, modified = plugins._dispatch_pre_tool_call_hooks(
            request.get("tool_name", "read_file"),
            request.get("args") or {"path": "notes.txt"},
            task_id="task-1",
            session_id="session-1",
            tool_call_id=str(request.get("tool_call_id", "call-1")),
            turn_id="turn-1",
            api_request_id="api-1",
            conversation_id="conv-1",
        )
        host = {"block": block, "modified": modified}
    elif hook == "transform_tool_result":
        model_tools = _import("model_tools")
        ids = model_tools._CallIds("task-1", "session-1", "call-1", "turn-1", "api-1", "conv-1")
        original = request.get("result", "original-result")
        replaced = model_tools._apply_transform_tool_result_hook(
            "read_file",
            {"path": "notes.txt"},
            original,
            12,
            ids,
        )
        host = {"result": replaced, "original": original}
    elif hook == "post_tool_call":
        model_tools = _import("model_tools")
        model_tools._emit_post_tool_call_hook(
            function_name="read_file",
            function_args={"path": "notes.txt"},
            result='{"ok": true}',
            task_id="task-1",
            session_id="session-1",
            tool_call_id="call-1",
            turn_id="turn-1",
            api_request_id="api-1",
            duration_ms=12,
            conversation_id="conv-1",
        )
        host = {"emitted": True}
    else:
        lifecycle = _import("hermes_cli.lifecycle")
        payloads: dict[str, dict[str, Any]] = {
            "on_session_start": {"session_id": "session-1", "model": "none", "platform": "cli"},
            "subagent_start": {
                "parent_session_id": "session-1",
                "parent_turn_id": "turn-1",
                "parent_subagent_id": "",
                "child_session_id": "child-1",
                "child_subagent_id": "sub-1",
                "child_role": "leaf",
                "child_goal": "look",
            },
            "subagent_stop": {
                "parent_session_id": "session-1",
                "parent_turn_id": "turn-1",
                "child_session_id": "child-1",
                "child_role": "leaf",
                "child_summary": "done",
                "child_status": "completed",
                "tool_call_history": [],
                "duration_ms": 10,
            },
        }
        if hook == "pre_approval_request":
            approval = _import("tools.approval_context")
            approval._fire_approval_hook(
                hook,
                command="<read_file>",
                description="because",
                pattern_key="plugin_rule:demo",
                pattern_keys=["plugin_rule:demo"],
                session_key="session-1",
                surface="cli",
            )
            host = {"fired": True}
        elif hook == "post_approval_response":
            approval = _import("tools.approval_context")
            approval._fire_approval_hook(
                hook,
                command="<read_file>",
                description="because",
                pattern_key="plugin_rule:demo",
                pattern_keys=["plugin_rule:demo"],
                session_key="session-1",
                surface="cli",
                choice="deny",
            )
            host = {"fired": True}
        elif hook not in payloads:
            raise SystemExit(f"unknown hook {hook}")
        else:
            returned = lifecycle.invoke_hook(hook, **payloads[hook])
            host = {"returned": returned}
    rows = _read_log(log)
    sample: dict[str, Any] = {}
    for row in rows:
        if row.get("plugin") == "standin-hostfacts":
            sample = row
            break
    if not sample and rows:
        sample = rows[0]
    return {
        "hook": hook,
        "host": host,
        "kwargs": sample.get("kwargs", {}),
        "keys": sample.get("keys", []),
        "log": rows,
    }


def load_state(_request: dict[str, Any]) -> dict[str, Any]:
    manager = _manager()
    plugins: dict[str, Any] = {}
    for key, plugin in manager._plugins.items():
        if plugin.manifest.source != "user":
            continue
        plugins[key] = {
            "enabled": plugin.enabled,
            "error": plugin.error,
            "kind": plugin.manifest.kind,
            "hooks": list(plugin.hooks_registered),
        }
    return {"plugins": plugins}


def timeout_probe(_request: dict[str, Any]) -> dict[str, Any]:
    """Fire a slow ``pre_tool_call`` against a shortened ``plugins.hook_callback_timeout``."""
    import time

    config_mod = _import("hermes_cli.config")
    config = config_mod.load_config()
    plugins_cfg = config.setdefault("plugins", {})
    previous = plugins_cfg.get("hook_callback_timeout", 30)
    plugins_cfg["hook_callback_timeout"] = 0.25
    config_mod.save_config(config, preserve_keys={("plugins", "hook_callback_timeout")})
    try:
        started = time.monotonic()
        decision = dispatch(
            {
                "hook": "pre_tool_call",
                "tool_call_id": "call-timeout",
                "behavior": {"sleep": 2, "return": {"action": "block", "message": "too late"}},
            }
        )
        elapsed = round(time.monotonic() - started, 3)
    finally:
        config = config_mod.load_config()
        config.setdefault("plugins", {})["hook_callback_timeout"] = previous
        config_mod.save_config(config, preserve_keys={("plugins", "hook_callback_timeout")})
    return {"elapsed_s": elapsed, "decision": decision}


def main() -> None:
    _sandbox()
    request = cast("dict[str, Any]", json.load(sys.stdin))
    action = str(request.get("action", ""))
    handlers = {
        "ensure_plugin": ensure_plugin,
        "install_standin_wheel": install_standin_wheel,
        "prepare_standin_home": prepare_standin_home,
        "validate": validate,
        "parse_kind": parse_kind,
        "settings": settings,
        "dispatch": dispatch,
        "load_state": load_state,
        "timeout_probe": timeout_probe,
    }
    if action not in handlers:
        raise SystemExit(f"unknown action {action}")
    json.dump(handlers[action](request), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
