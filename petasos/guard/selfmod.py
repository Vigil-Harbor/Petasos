"""Recognize changes to guard-owned paths."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NamedTuple

from petasos.guard.guardrail import CheckFailure, recognize
from petasos.guard.paths import normalize_path_text
from petasos.guard.surface import GuardrailSurface
from petasos.guard.tools import _READ_ONLY_CANON

_logger = logging.getLogger("petasos.session.guard")

if TYPE_CHECKING:
    from collections.abc import Mapping

    from petasos.guard.guard import ToolCallGuard
    from petasos.hermes.home import HermesConfigResolution


class _SelfmodMatch(NamedTuple):
    rule_id: str
    target: str
    kind: str | None = None


# See docs/architecture/rationale.md, "Guard overflow attribution".
SELFMOD_DEPTH_OVERFLOW_TARGET = "<argument-depth-overflow>"
# The parameters of Hermes's write and patch tools that carry file content,
# not the file written (tools/file_tools.py). A protected path in one of them
# is a reference, not a write. Any other parameter may name the file written.
_CONTENT_KEYS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "write_file": frozenset({"content"}),
        "patch": frozenset({"old_string", "new_string", "patch"}),
    }
)


def _owned_paths(raw_entries: list[str]) -> frozenset[str]:
    """Absolute, resolved, deep-enough paths, compared case-insensitively."""
    result: set[str] = set()
    for raw in raw_entries:
        path = Path(raw)
        if not path.is_absolute():
            continue
        try:
            resolved = str(path.resolve(strict=False))
        except (OSError, RuntimeError):
            continue
        if len(Path(resolved).parts) < 3:
            continue
        result.add(os.path.normcase(resolved))
    return frozenset(result)


def _surface(self: ToolCallGuard) -> GuardrailSurface:
    """The host's command patterns, or an empty surface when none was supplied."""
    supplier = self._guardrail_surface
    if supplier is None:
        return GuardrailSurface()
    value = supplier()
    if isinstance(value, GuardrailSurface):
        return value
    raise TypeError("guardrail surface is not a GuardrailSurface")


def selfmod_target_paths(self: ToolCallGuard) -> frozenset[str]:
    """The paths a tool call must not modify, cached for one second.

    A caller that supplied ``protected_paths`` is the source. Otherwise the
    set is discovered from the host layout, which is what existing callers
    still get.
    """
    now = time.monotonic()
    ts, cached = self._selfmod_owned_cache
    if now - ts < 1.0 and cached:
        return cached
    try:
        owned = _owned_paths(self._raw_protected_entries())
    except Exception:
        # The last good set still names the same files. Keep protecting them
        # rather than refuse every write; with no earlier set the check fails.
        if not cached:
            raise
        _logger.warning("selfmod_target_paths: read failed, keeping the last set", exc_info=True)
        return cached
    if not owned and not self._selfmod_empty_warned:
        _logger.warning("selfmod_target_paths: owned set is empty after hygiene")
        self._selfmod_empty_warned = True
    if owned:
        self._selfmod_empty_warned = False
    self._selfmod_owned_cache = (now, owned)
    return owned


def _raw_protected_entries(self: ToolCallGuard) -> list[str]:
    supplier = self._protected_paths
    if supplier is not None:
        return [str(item) for item in supplier()]
    from petasos.hermes.home import (
        HermesConfigResolution,
        hermes_root,
        profile_directories,
        resolve_hermes_config_path,
        spool_path,
        spool_rot_path,
    )

    def _beside(res: HermesConfigResolution) -> list[str]:
        return [str(res.path), spool_path(res), spool_rot_path(res)]

    raw_entries: list[str] = []
    if self._selfmod_home is not None:
        raw_entries.extend(_beside(self._selfmod_home))
    raw_entries.extend(_beside(resolve_hermes_config_path(use_override=False)))
    raw_entries.extend(
        _beside(HermesConfigResolution(path=hermes_root() / "config.yaml", tier="root"))
    )
    # Exact files, never the profiles directory: the agent's own home can sit
    # under it. A directory without an identity marker can become a profile,
    # so its settings files are protected before it does.
    for child in profile_directories(hermes_root()):
        raw_entries.extend(
            _beside(HermesConfigResolution(path=child / "config.yaml", tier="profile"))
        )
    if self._selfmod_home is None:
        raw_entries.append(str(resolve_hermes_config_path().path))
        raw_entries.append(spool_path())
        raw_entries.append(spool_rot_path())
    return raw_entries


def _classify_selfmod(
    self: ToolCallGuard, canon_pre_alias: str, tool_params: dict[str, Any]
) -> _SelfmodMatch | CheckFailure | None:
    """Total: return a match, a failed check, or a clean no-hit."""
    try:
        if canon_pre_alias in _READ_ONLY_CANON:
            return None
        hit = recognize(
            canon_pre_alias,
            tool_params,
            protected=self.selfmod_target_paths(),
            surface=self._surface(),
        )
        if hit is not None:
            return _SelfmodMatch(
                rule_id="petasos.selfmod.config_write",
                target=hit.target,
                kind=hit.kind,
            )
        owned = self.selfmod_target_paths()
        if not owned:
            return None

        def _has_sep(s: str) -> bool:
            return "/" in s or "\\" in s or os.sep in s

        content_keys = _CONTENT_KEYS.get(canon_pre_alias, frozenset())
        top_level_strs: list[str] = []
        all_parts: list[str] = []
        for key, value in tool_params.items():
            if value is None:
                continue
            if isinstance(value, str):
                if key not in content_keys:
                    top_level_strs.append(value)
                all_parts.append(value)
            else:
                all_parts.extend(self._extract_leaf_strings(value))

        overflow = self._EXTRACT_OVERFLOW in all_parts
        if overflow:
            return _SelfmodMatch(
                rule_id="petasos.selfmod.config_ref",
                target=SELFMOD_DEPTH_OVERFLOW_TARGET,
            )

        any_sep = any(_has_sep(p) for p in all_parts)
        if not any_sep:
            return None

        def _normalize_for_compare(s: str) -> str:
            return normalize_path_text(s)

        for tls in top_level_strs:
            normed = _normalize_for_compare(tls)
            for entry in owned:
                if normed == entry:
                    return _SelfmodMatch(rule_id="petasos.selfmod.config_write", target=entry)

        for part in all_parts:
            normed = _normalize_for_compare(part)
            for entry in owned:
                if entry in normed:
                    return _SelfmodMatch(rule_id="petasos.selfmod.config_ref", target=entry)

        return None
    except Exception as exc:
        return CheckFailure(f"{type(exc).__name__}: {exc}")
