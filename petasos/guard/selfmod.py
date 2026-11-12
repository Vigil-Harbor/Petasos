"""Recognize changes to guard-owned paths."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from petasos.guard.guardrail import recognize
from petasos.guard.paths import normalize_path_text
from petasos.guard.surface import GuardrailSurface
from petasos.guard.tools import _READ_ONLY_CANON

_logger = logging.getLogger("petasos.session.guard")

if TYPE_CHECKING:
    from petasos.guard.guard import ToolCallGuard
    from petasos.hermes.home import HermesConfigResolution


class _SelfmodMatch(NamedTuple):
    rule_id: str
    target: str
    kind: str | None = None


# See docs/architecture/rationale.md, "Guard overflow attribution".
SELFMOD_DEPTH_OVERFLOW_TARGET = "<argument-depth-overflow>"


def _owned_paths(raw_entries: list[str]) -> frozenset[str]:
    """Absolute, resolved, deep-enough paths, compared case-insensitively."""
    result: set[str] = set()
    for raw in raw_entries:
        path = Path(raw)
        if not path.is_absolute():
            continue
        try:
            resolved = str(path.resolve(strict=False))
        except OSError:
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
    try:
        value = supplier()
    except Exception:
        _logger.debug("guardrail surface failed", exc_info=True)
        return GuardrailSurface()
    if isinstance(value, GuardrailSurface):
        return value
    return GuardrailSurface()


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
        if not owned and not self._selfmod_empty_warned:
            _logger.warning("selfmod_target_paths: owned set is empty after hygiene")
            self._selfmod_empty_warned = True
        if owned:
            self._selfmod_empty_warned = False
        self._selfmod_owned_cache = (now, owned)
        return owned
    except Exception:
        _logger.debug("selfmod_target_paths: failed to build owned set", exc_info=True)
        return cached or frozenset()


def _raw_protected_entries(self: ToolCallGuard) -> list[str]:
    supplier = self._protected_paths
    if supplier is not None:
        return [str(item) for item in supplier()]
    from petasos.hermes.home import (
        HermesConfigResolution,
        hermes_root,
        list_hermes_profiles,
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
    for prof in list_hermes_profiles():
        raw_entries.extend(
            _beside(HermesConfigResolution(path=Path(prof["path"]), tier="profile"))
        )
    if self._selfmod_home is None:
        raw_entries.append(str(resolve_hermes_config_path().path))
        raw_entries.append(spool_path())
        raw_entries.append(spool_rot_path())
    return raw_entries


def _classify_selfmod(
    self: ToolCallGuard, canon_pre_alias: str, tool_params: dict[str, Any]
) -> _SelfmodMatch | None:
    """Total: never raises. Returns the match or None."""
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

        top_level_strs: list[str] = []
        all_parts: list[str] = []
        for value in tool_params.values():
            if value is None:
                continue
            if isinstance(value, str):
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
    except Exception:
        _logger.warning("selfmod classifier error for tool=%s", canon_pre_alias, exc_info=True)
        return None
