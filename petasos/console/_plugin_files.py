"""Predict from files whether Hermes can load a Petasos hook for one home.

Applies Hermes's plugin selection rules to ``<home>/plugins`` and returns a closed
status (PET-236). ``hook_can_load`` is the strongest thing files can say: a plugin
that fails at load is not visible here, and ``verify.py`` compares the gateway's
load log. Same contract as ``_paths.py``: stdlib plus lazy PyYAML, no logging, and
``protection_status`` never raises.
"""

from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from petasos.console._paths import (
    HermesConfigResolution,
    _resolved_normcase,
    display_path,
    hermes_root,
)

Status = Literal["hook_can_load", "shadowed", "no_copy", "not_enabled", "unknown"]

_PLUGIN_NAME = "petasos"
_BACKUPS_DIRNAME = "petasos-plugin-backups"
# hermes_cli/plugins_discovery.py:35, foreign manifest conventions Hermes skips.
_FOREIGN_MANIFEST_DIRS = frozenset(
    {".claude-plugin", ".codex-plugin", ".cursor-plugin", ".devin-plugin", ".kimi-plugin"}
)
_PLAIN_PROFILE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
_INTENDED_SENTENCE = "If leaving this profile unguarded is intended, no action is needed."


@dataclass(frozen=True)
class ProtectionStatus:
    status: Status
    configured: bool  # petasos in plugins.enabled, or a petasos: mapping
    winner: Path | None  # the folder winning the petasos name, else None
    claimants: tuple[Path, ...]  # every folder claiming petasos except plugins/petasos
    detail: str  # one operator sentence, paths through display_path
    next_steps: str  # empty for hook_can_load; literal paths


def _has_duplicate_key(node: Any, visited: set[int]) -> bool:
    if id(node) in visited:  # an alias can make the node graph cyclic
        return False
    visited.add(id(node))
    if isinstance(node.value, str):
        return False
    pairs = node.value
    if node.id == "mapping":
        keys = [
            (key.tag, key.value)
            for key, _ in pairs
            if key.id == "scalar" and key.tag != "tag:yaml.org,2002:merge"
        ]
        if len(keys) != len(set(keys)):
            return True
        children = [child for pair in pairs for child in pair]
    else:
        children = pairs
    return any(_has_duplicate_key(child, visited) for child in children)


def _load_yaml(text: str) -> Any:
    """``yaml.safe_load`` that rejects duplicate keys at any depth, as Hermes's parser does.

    PyYAML keeps the last duplicate, where Hermes raises and the file counts as a parse
    failure. Without this a manifest with two ``name:`` lines would read as loadable.
    """
    import yaml

    root = yaml.compose(text, Loader=yaml.SafeLoader)
    if root is not None and _has_duplicate_key(root, set()):
        raise yaml.YAMLError("duplicate key")
    return yaml.safe_load(text)


def _claimed_name(folder: Path) -> tuple[bool, Any]:
    """``(has_manifest_file, claimed_name)``; the name is None when the manifest is unusable.

    Mirrors ``parse_manifest_file``: ``utf-8-sig``, an empty manifest is a valid ``{}``,
    a parse failure or non-mapping yields no manifest, and ``name`` defaults to the folder.
    """
    import yaml

    for filename in ("plugin.yaml", "plugin.yml"):
        manifest = folder / filename
        if manifest.exists():
            try:
                data = _load_yaml(manifest.read_text(encoding="utf-8-sig")) or {}
            except (OSError, ValueError, yaml.YAMLError):
                return True, None
            if not isinstance(data, dict):
                return True, None
            return True, data.get("name", folder.name)
    return False, None


def _children(path: Path) -> list[Path]:
    """Plugin candidates under *path* in Hermes's order; unreadable means none."""
    if not path.is_dir():
        return []
    try:
        children = sorted(path.iterdir())
    except OSError:
        return []
    return [
        child
        for child in children
        if not (child.name.startswith("__") and child.name.endswith("__"))
        and child.name not in _FOREIGN_MANIFEST_DIRS
    ]


def _scan_claims(plugins: Path) -> tuple[Path | None, list[Path]]:
    """Return ``(winner, every folder claiming the name)`` for one plugins folder.

    Each flat claimer replaces the winner, so the last one sorted wins. A nested
    claimer keys as ``cat/name`` in Hermes, so it never wins, but it would load as a
    second plugin. Folders holding ``plugin.json`` are not recursed, matching Hermes.
    """
    winner: Path | None = None
    claiming: list[Path] = []
    for child in _children(plugins):
        try:
            if not child.is_dir():
                continue
            has_manifest, name = _claimed_name(child)
            if has_manifest:
                if name == _PLUGIN_NAME:
                    winner = child
                    claiming.append(child)
                continue
            if (child / "plugin.json").exists():
                continue
            for grandchild in _children(child):
                if not grandchild.is_dir():
                    continue
                nested, nested_name = _claimed_name(grandchild)
                if nested and nested_name == _PLUGIN_NAME:
                    claiming.append(grandchild)
        except OSError:
            continue
    return winner, claiming


def _read_config(home: Path) -> tuple[dict[str, Any], bool]:
    """``(config, ok)``. Missing or empty is ok; a parse error or non-mapping is not."""
    import yaml

    try:
        text = (home / "config.yaml").read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, True
    except (OSError, ValueError):
        return {}, False
    try:
        data = _load_yaml(text) or {}
    except yaml.YAMLError:
        return {}, False
    if not isinstance(data, dict):
        return {}, False
    return data, True


def _listed(plugins_section: Any, key: str) -> set[Any]:
    """Hermes counts ``plugins.enabled``/``disabled`` only as lists of hashable entries."""
    if not isinstance(plugins_section, dict):
        return set()
    value = plugins_section.get(key)
    if not isinstance(value, list):
        return set()
    try:
        return set(value)
    except TypeError:
        return set()


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _quote(value: str) -> str:
    """Single-quote for the operator's shell, so ``$`` is never expanded on paste."""
    if _is_windows():
        return "'" + value.replace("'", "''") + "'"
    return "'" + value.replace("'", "'\\''") + "'"


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _same_folder(a: Path, b: Path) -> bool:
    norm_a, norm_b = _resolved_normcase(a), _resolved_normcase(b)
    return norm_a is not None and norm_a == norm_b


def _profile_flag(home: Path, profile: str | None) -> str | None:
    """The explicit ``-p`` target. A bare ``hermes`` re-homes to ``active_profile``."""
    if profile is not None:
        shown = profile if _PLAIN_PROFILE_RE.match(profile) else _quote(profile)
        return f"-p {shown}"
    if _same_folder(home, hermes_root()):
        return "-p default"
    return None


def _mkdir_command(path: Path) -> str:
    if _is_windows():
        return f"New-Item -ItemType Directory -Force {_quote(str(path))} | Out-Null"
    return f"mkdir -p {_quote(str(path))}"


def _copy_command(source: Path, target: Path) -> str:
    if _is_windows():
        # -LiteralPath: a folder name holding [ or ] is otherwise a wildcard pattern.
        return (
            f"Copy-Item -Recurse -LiteralPath {_quote(str(source))}"
            f" -Destination {_quote(str(target))}"
        )
    return f"cp -R {_quote(str(source))} {_quote(str(target))}"


def _move_command(source: Path, dest_dir: Path) -> str:
    if _is_windows():
        return f"Move-Item -LiteralPath {_quote(str(source))} -Destination {_quote(str(dest_dir))}"
    return f"mv {_quote(str(source))} {_quote(str(dest_dir))}"


def _custom_home_steps(home: Path, *, needs_copy: bool) -> str:
    """No ``hermes`` command can be trusted to reach an unnamed custom home."""
    config = home / "config.yaml"
    plugins = home / "plugins"
    steps = [f"Add {_PLUGIN_NAME} to plugins.enabled in {config} by hand."]
    if needs_copy:
        steps.insert(
            0,
            f"Place a {_PLUGIN_NAME} folder in {plugins} from this installation's own source.",
        )
    steps.append("Restart the gateway.")
    steps.append(_INTENDED_SENTENCE)
    return "\n".join(steps)


def _no_copy_steps(home: Path, profile: str | None) -> str:
    # PET-233 replaces the copy command with the install command; this is the one place.
    flag = _profile_flag(home, profile)
    if flag is None:
        return _custom_home_steps(home, needs_copy=True)
    plugins = home / "plugins"
    target = plugins / _PLUGIN_NAME
    source = _absolute(hermes_root()) / "plugins" / _PLUGIN_NAME
    lines: list[str] = []
    if _same_folder(source, target) or not (source / "__init__.py").is_file():
        lines.append(f"Install Petasos in the root first: {source} has no usable copy.")
    else:
        if target.exists():
            backups = home / _BACKUPS_DIRNAME
            lines.append(
                f"Remove {target} or move it to {backups} first: a recursive copy would"
                " nest inside it, and a renamed folder would still claim the name."
            )
        lines.append(_mkdir_command(plugins))
        lines.append(_copy_command(source, target))
    lines.append(f"hermes {flag} plugins enable {_PLUGIN_NAME}")
    lines.append("Restart the gateway.")
    lines.append(_INTENDED_SENTENCE)
    return "\n".join(lines)


def _not_enabled_steps(home: Path, profile: str | None) -> str:
    flag = _profile_flag(home, profile)
    if flag is None:
        return _custom_home_steps(home, needs_copy=False)
    return "\n".join(
        [
            f"hermes {flag} plugins enable {_PLUGIN_NAME}",
            "Restart the gateway.",
            _INTENDED_SENTENCE,
        ]
    )


def _shadowed_steps(home: Path, claimants: tuple[Path, ...]) -> str:
    backups = home / _BACKUPS_DIRNAME
    lines = [_mkdir_command(backups)]
    lines.extend(_move_command(claimant, backups) for claimant in claimants)
    lines.append(f"If a same-named folder is already in {backups}, rename one first.")
    lines.append("Restart the gateway.")
    lines.append("A backup anywhere under plugins/ still loads, so keep it beside plugins/.")
    return "\n".join(lines)


def _status_from_files(home: Path, profile: str | None) -> ProtectionStatus:
    plugins = home / "plugins"
    expected = plugins / _PLUGIN_NAME
    winner, claiming = _scan_claims(plugins)
    config, config_ok = _read_config(home)
    plugins_section = config.get("plugins")
    enabled = _listed(plugins_section, "enabled")
    disabled = _listed(plugins_section, "disabled")
    configured = _PLUGIN_NAME in enabled or isinstance(config.get(_PLUGIN_NAME), dict)

    def result(
        status: Status, detail: str, claimants: tuple[Path, ...], steps: str
    ) -> ProtectionStatus:
        return ProtectionStatus(status, configured, winner, claimants, detail, steps)

    # None on both sides must not compare equal, so an unresolvable name is unknown.
    expected_norm = _resolved_normcase(expected)
    claiming_norms = [_resolved_normcase(folder) for folder in claiming]
    if claiming and (expected_norm is None or any(n is None for n in claiming_norms)):
        return result(
            "unknown",
            f"Could not resolve the plugin folders under {display_path(plugins)}.",
            (),
            f"Read the folders under {plugins}, then re-run verify.py.",
        )
    claimants = tuple(
        folder
        for folder, norm in zip(claiming, claiming_norms, strict=True)
        if norm != expected_norm
    )
    if claimants:
        names = ", ".join(display_path(folder) for folder in claimants)
        return result(
            "shadowed",
            f"Another folder claims the {_PLUGIN_NAME} name: {names}.",
            claimants,
            _shadowed_steps(home, claimants),
        )
    if not config_ok:
        config_path = home / "config.yaml"
        return result(
            "unknown",
            f"Could not read {display_path(config_path)}.",
            (),
            f"Read {config_path} and fix it, then re-run verify.py.",
        )
    if winner is None or not (winner / "__init__.py").is_file():
        return result(
            "no_copy",
            f"No loadable {_PLUGIN_NAME} folder under {display_path(plugins)}.",
            (),
            _no_copy_steps(home, profile),
        )
    if _PLUGIN_NAME in disabled or _PLUGIN_NAME not in enabled:
        return result(
            "not_enabled",
            f"{_PLUGIN_NAME} is not enabled in {display_path(home / 'config.yaml')}.",
            (),
            _not_enabled_steps(home, profile),
        )
    return result("hook_can_load", f"A hook can load from {display_path(winner)}.", (), "")


def protection_status(home: Path, *, profile: str | None = None) -> ProtectionStatus:
    """Apply Hermes's selection rules to *home*. Never raises; a surprise is ``unknown``."""
    try:
        return _status_from_files(_absolute(home), profile)
    except Exception as exc:
        return ProtectionStatus(
            "unknown",
            False,
            None,
            (),
            f"Could not check the plugin files: {type(exc).__name__}.",
            "Read the plugin folder and config.yaml of this home, then re-run verify.py.",
        )


def is_hermes_home(binding: HermesConfigResolution) -> bool:
    """True when the binding's home, or outside the ``hermes_home`` tier the root, is Hermes's.

    Petasos writes none of these markers, unlike ``config.yaml``, which its own arm and
    save paths create. A never-run profile has only its bootstrapped folders, so
    ``sessions/`` and ``memories/`` are what mark it. Never raises.
    """
    try:
        homes = [binding.path.parent]
        if binding.tier != "hermes_home":
            homes.append(hermes_root())
        for home in homes:
            if any((home / d).is_dir() for d in ("plugins", "profiles", "sessions", "memories")):
                return True
            if (home / "gateway_state.json").is_file() or (home / "logs/agent.log").is_file():
                return True
        return False
    except Exception:
        return False
