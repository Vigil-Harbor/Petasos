"""Exercise managed scope only inside the sandbox, including its machine stand-in."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__" and __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.hermes_host.petasos_harness import _context, _import
from tests.hermes_host.sandbox_guard import hermes_home, require_inside_sandbox, sandbox_root


def _setup() -> tuple[Path, Any]:
    sandbox_root()
    managed = require_inside_sandbox(hermes_home() / "managed", label="managed config")
    managed.mkdir(exist_ok=True)
    os.environ["HERMES_MANAGED_DIR"] = str(managed)
    module = _import("hermes_cli.managed_scope")
    module._DEFAULT_MANAGED_DIR = hermes_home() / "machine-standin"
    return managed, module


def _cli(*args: str) -> dict[str, Any]:
    from petasos.hermes.commands import main

    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        code = main(list(args))
    return {"code": code, "text": output.getvalue()}


def _four(ctx: Any) -> dict[str, Any]:
    return {key: ctx.get_config(key) for key in ("enabled", "role", "level", "overrides")}


def pin(_request: dict[str, Any]) -> dict[str, Any]:
    """Provide pin for the test fixture."""
    managed, module = _setup()
    (managed / "config.yaml").write_text(json.dumps({"model": {"default": "sandbox-only"}}))
    result = _cli("hermes", "pin", "--write")
    module.invalidate_managed_cache()
    ctx = _context()
    from petasos.hermes.doctor import examine

    return {
        **result,
        "keys": sorted(module.managed_config_keys()),
        "values": _four(ctx),
        "document": module.load_managed_config(),
        "doctor": examine(hermes_home(), home_reason="sandbox", probe_plugin=False).detail["pin"],
        "timeout": _import("hermes_cli.plugins")._resolve_hook_callback_timeout(),
    }


def partial(_request: dict[str, Any]) -> dict[str, Any]:
    """Provide partial for the test fixture."""
    managed, _ = _setup()
    document = {
        "plugins": {
            "entries": {
                "petasos": {
                    "settings": {"overrides": {"tools": {"self_change": "never", "aliases": {}}}}
                }
            }
        }
    }
    (managed / "config.yaml").write_text(json.dumps(document))
    ctx = _context()
    ctx.set_config("overrides.tools.enabled", False)
    ctx.set_config("overrides.tools.aliases.probe", "terminal")
    api_child = ctx.get_config("overrides.tools.aliases.probe")
    path = hermes_home() / "config.yaml"
    raw = _import("hermes_cli.config").read_user_config_raw()
    raw.setdefault("plugins", {}).setdefault("entries", {}).setdefault("petasos", {}).setdefault(
        "settings", {}
    ).setdefault("overrides", {}).setdefault("tools", {})["aliases"] = {"probe": "terminal"}
    path.write_text(json.dumps(raw))
    return {
        "api_empty_mapping_child": api_child,
        "sibling": ctx.get_config("overrides.tools.enabled"),
        "empty_mapping_child": ctx.get_config("overrides.tools.aliases.probe"),
        "pinned_leaf": ctx.get_config("overrides.tools.self_change"),
    }


def writes(request: dict[str, Any]) -> dict[str, Any]:
    """Provide writes for the test fixture."""
    _setup()
    from petasos.config.schema import leaves
    from petasos.config.sections import PetasosConfig
    from petasos.hermes.config_set import set_one
    from petasos.hermes.dashboard.changes import save_settings
    from petasos.hermes.doctor_support import settings_mapping
    from petasos.hermes.host import managed_keys
    from petasos.hermes.settings import write_settings

    ctx = _context()
    before = _four(ctx)
    method = request["method"]
    failures: list[str] = []
    attempts = []
    rows = leaves(PetasosConfig)
    for key in ["enabled", "role", "level", *("overrides." + row.path for row in rows)]:
        # Hermes ignores null over a mapping, so the fixture must exercise that overlay.
        value: Any = {"pin_probe": "terminal"} if ctx.get_config(key) is None else "changed"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                if method == "api":
                    ctx.set_config(key, value)
                elif method == "hermes_config":
                    _import("hermes_cli.config").set_config_value(
                        "plugins.entries.petasos.settings." + key, json.dumps(value), force=True
                    )
                elif method == "petasos_config":
                    raw = (
                        "false"
                        if key == "enabled"
                        else "general"
                        if key == "role"
                        else "relaxed"
                        if key == "level"
                        else "0"
                    )
                    text, code = set_one(hermes_home(), key.removeprefix("overrides."), raw)
                    attempts.append({"key": key, "code": code, "text": text})
                elif method == "form":
                    current = settings_mapping(
                        _import("hermes_cli.config").load_config_readonly(), "petasos"
                    )
                    candidate = (
                        {"enabled": False}
                        if key == "enabled"
                        else {"role": "research"}
                        if key == "role"
                        else {"level": "relaxed"}
                        if key == "level"
                        else {"overrides": _nest(key.removeprefix("overrides."), value)}
                    )
                    save_settings(
                        current,
                        candidate,
                        plugin_dir=hermes_home() / "plugins/petasos",
                        write=lambda values, path: write_settings(values, plugin_dir=path),
                        secrets={},
                        managed=managed_keys(),
                    )
            except (Exception, SystemExit) as exc:
                failures.append(type(exc).__name__)
    actual_cli = None
    if method == "hermes_config":
        result = _command(
            ["hermes", "config", "set", "plugins.entries.petasos.settings.enabled", "false"]
        )
        actual_cli = result.returncode
    elif method == "petasos_config":
        result = _command([sys.executable, "-m", "petasos", "config", "set", "enabled", "false"])
        actual_cli = result.returncode
    return {
        "before": before,
        "after": _four(ctx),
        "refusals": failures,
        "attempts": attempts,
        "actual_cli": actual_cli,
    }


def _nest(path: str, value: object) -> dict[str, Any]:
    result: dict[str, Any] = {}
    cursor = result
    parts = path.split(".")
    for part in parts[:-1]:
        child: dict[str, Any] = {}
        cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value
    return result


def hand_edit(_request: dict[str, Any]) -> dict[str, Any]:
    """Provide hand edit for the test fixture."""
    _setup()
    from petasos.hermes.settings import HermesSettings

    ctx = _context()
    before = _four(ctx)
    profile = copy.deepcopy(before)
    profile.update(enabled=False, role="research", level="relaxed")
    profile["overrides"] = {key: "changed" for key in before["overrides"]}
    profile["overrides"]["rules"] = {"severity_overrides": {"probe": "low"}}
    profile["overrides"]["tools"] = {"aliases": {"probe": "terminal"}}
    profile["overrides"]["frequency"] = {"weights": {"probe": 0.0}}
    path = hermes_home() / "config.yaml"
    path.write_text(
        json.dumps(
            {
                "plugins": {
                    "enabled": [],
                    "disabled": ["petasos"],
                    "entries": {"petasos": {"settings": profile}},
                }
            }
        )
    )
    after = _four(ctx)
    source = HermesSettings(ctx)
    source.bind_profile(hermes_home())
    snapshot = source()
    unbound = HermesSettings(ctx)()
    used = [
        {
            "severity_overrides": dict(item.config.rules.severity_overrides),
            "aliases": dict(item.config.tools.aliases),
            "weights": item.config.frequency.weights,
            "armed": item.armed,
        }
        if item.config is not None
        else None
        for item in (snapshot, unbound)
    ]
    from petasos.hermes.doctor import examine

    report = examine(hermes_home(), home_reason="sandbox", probe_plugin=False)
    return {
        "before": before,
        "after": after,
        "bound_armed": snapshot.armed,
        "bound_error": snapshot.error,
        "used_bound": used[0],
        "used_unbound": used[1],
        "pin": report.detail["pin"],
        "switch": report.detail["hermes_enabled"],
    }


def _command(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    root = sandbox_root()
    return subprocess.run(
        [
            str(root / "bin/with-sandbox"),
            "env",
            "HERMES_MANAGED_DIR=" + os.environ["HERMES_MANAGED_DIR"],
            *arguments,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


def disable(_request: dict[str, Any]) -> dict[str, Any]:
    """Provide disable for the test fixture."""
    _setup()
    result = _command(["hermes", "plugins", "disable", "petasos"])
    return {"code": result.returncode, "out": result.stdout, "err": result.stderr}


def loaded(_request: dict[str, Any]) -> dict[str, Any]:
    """Provide loaded for the test fixture."""
    _setup()
    ctx = _context()
    return {"loaded": ctx is not None, "values": _four(ctx)}


def unpin(request: dict[str, Any]) -> dict[str, Any]:
    """Provide unpin for the test fixture."""
    _setup()
    args = ["hermes", "unpin", "--write"]
    if request.get("accept"):
        args.append("--accept-profile-changes")
    return _cli(*args)


def unpinned(_request: dict[str, Any]) -> dict[str, Any]:
    """Provide unpinned for the test fixture."""
    _, module = _setup()
    path = hermes_home() / "config.yaml"
    document = _import("hermes_cli.config").read_user_config_raw()
    document["plugins"]["enabled"] = ["petasos"]
    document["plugins"]["disabled"] = []
    document["plugins"].setdefault("entries", {}).setdefault("petasos", {})["settings"] = {
        "enabled": True
    }
    path.write_text(json.dumps(document))
    ctx = _context()
    ctx.set_config("enabled", False)
    return {
        "enabled": ctx.get_config("enabled"),
        "keys": sorted(module.managed_config_keys()),
        "managed": module.load_managed_config(),
    }


def nullable(_request: dict[str, Any]) -> dict[str, Any]:
    """Provide nullable for the test fixture."""
    _setup()
    ctx = _context()
    from petasos.hermes.dashboard.values import hermes_merge
    from petasos.hermes.doctor_support import at_path
    from petasos.hermes.pinning import leaf_paths

    before = _four(ctx)
    patches: dict[str, Any] = {}
    for parts in leaf_paths(before["overrides"]):
        if at_path(before["overrides"], ".".join(parts)) is None:
            patches = hermes_merge(patches, _nest(".".join(parts), {"probe": 0.0}))
    raw = _import("hermes_cli.config").read_user_config_raw()
    raw.setdefault("plugins", {}).setdefault("entries", {}).setdefault("petasos", {})[
        "settings"
    ] = {"overrides": patches}
    (hermes_home() / "config.yaml").write_text(json.dumps(raw))
    return {"before": before, "after": _four(ctx)}


def timeout(request: dict[str, Any]) -> dict[str, Any]:
    """Provide timeout for the test fixture."""
    _setup()
    config = _import("hermes_cli.config")
    raw = config.read_user_config_raw()
    raw["plugins"]["hook_callback_timeout"] = request["raw"]
    (hermes_home() / "config.yaml").write_text(json.dumps(raw))
    result = _cli("hermes", "pin", "--write")
    raw["plugins"]["hook_callback_timeout"] = 0.001
    (hermes_home() / "config.yaml").write_text(json.dumps(raw))
    refused = False
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            config.set_config_value("plugins.hook_callback_timeout", "0")
    except SystemExit:
        refused = True
    return {
        **result,
        "effective": _import("hermes_cli.plugins")._resolve_hook_callback_timeout(),
        "refused": refused,
    }


def redirect(_request: dict[str, Any]) -> dict[str, Any]:
    """Provide redirect for the test fixture."""
    managed, module = _setup()
    machine = module._DEFAULT_MANAGED_DIR
    machine.mkdir()
    (machine / "config.yaml").write_bytes((managed / "config.yaml").read_bytes())
    other = hermes_home() / "other-managed"
    other.mkdir()
    os.environ["HERMES_MANAGED_DIR"] = str(other)
    from petasos.hermes.doctor import examine

    report = examine(hermes_home(), home_reason="sandbox", probe_plugin=False)
    return {
        "pin": report.detail["pin"],
        "checks": [{"id": c.id, "status": c.status, "summary": c.summary} for c in report.checks],
    }


def references(request: dict[str, Any]) -> dict[str, Any]:
    """Provide references for the test fixture."""
    managed, _ = _setup()
    config = _import("hermes_cli.config")
    raw = config.read_user_config_raw()
    raw["plugins"].setdefault("entries", {}).setdefault("petasos", {})["settings"] = {
        "overrides": {"scanners": {"presidio": {"language": "${env:S1B_PIN_LANGUAGE}"}}}
    }
    (hermes_home() / "config.yaml").write_text(json.dumps(raw))
    if request["defined"]:
        os.environ["S1B_PIN_LANGUAGE"] = "fr"
    else:
        os.environ.pop("S1B_PIN_LANGUAGE", None)
    result = _cli("hermes", "pin", "--write")
    os.environ["S1B_PIN_LANGUAGE"] = "de"
    return {
        **result,
        "wrote": (managed / "config.yaml").exists(),
        "language": config.load_config_readonly()["plugins"]["entries"]["petasos"]["settings"][
            "overrides"
        ]["scanners"]["presidio"]["language"],
    }


def main() -> None:
    """Run the isolated test harness."""
    request = json.loads(sys.stdin.read())
    actions = {
        "pin": pin,
        "partial": partial,
        "nullable": nullable,
        "timeout": timeout,
        "redirect": redirect,
        "references": references,
        "writes": writes,
        "hand_edit": hand_edit,
        "disable": disable,
        "loaded": loaded,
        "unpin": unpin,
        "unpinned": unpinned,
    }
    json.dump(actions[request["action"]](request), sys.stdout)


if __name__ == "__main__":
    main()
