"""Equipped/Unequipped (``petasos.enabled``) read/write — the single source of truth.

Anchored on ``_paths.resolve_hermes_config_path()`` so the gateway and the
dashboard agree on which ``config.yaml`` holds the bit. Keeps ``_paths.py`` pure
(PET-111 Decision 4 — no cache, no writes added there). Fail-secure: read errors
arm. Never raises out of ``read_armed``/``write_armed``.

PET-130: ``read_armed`` takes an optional ``res`` resolution. The gateway passes
its boot-pinned resolution so a profile session never re-resolves to the global
config mid-session; the standalone console passes ``None`` and re-resolves from
environment. Precondition: the ``(mtime_ns, size)`` cache is keyed by stat
metadata, not path, so a single process must use one binding consistently
(gateway always pinned, console always ``None``). If a future surface ever runs
both in one process, the cache must be re-keyed to include ``res.path``.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from petasos.console._paths import (
    HermesConfigResolution,
    read_petasos_section,
    resolve_hermes_config_path,
)

_ARMED_LOCK = threading.Lock()
_ARMED_TTL_S = 1.0
# (key, armed, monotonic_ts) | None  — key is (st_mtime_ns, st_size)
_ARMED_CACHE: tuple[tuple[int, int], bool, float] | None = None


def _reset_armed_cache() -> None:
    """Test seam: drop the cache so a new (mtime, size) key can't be served stale."""
    global _ARMED_CACHE
    with _ARMED_LOCK:
        _ARMED_CACHE = None


def read_armed(res: HermesConfigResolution | None = None) -> bool:
    """Return the effective ``petasos.enabled`` bit. Fail-secure ``True`` on any error.

    TTL+mtime+size cache: a hit requires an unchanged ``(mtime_ns, size)`` key AND
    age < ``_ARMED_TTL_S``, so a same-size same-tick rewrite is still observed within
    the TTL. Steady-state cost is one ``os.stat`` per call plus at most one YAML
    parse per second — never a parse per tool call.

    ``res``: when supplied (the PET-130 gateway path), the read uses this
    boot-pinned resolution and skips the per-call ambient resolve. When ``None``
    (the standalone console path), it re-resolves from environment as before.
    """
    global _ARMED_CACHE
    res = res if res is not None else resolve_hermes_config_path()
    try:
        st = res.path.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return True  # cannot stat (missing/locked) -> armed (Decision 5)
    now = time.monotonic()
    with _ARMED_LOCK:
        c = _ARMED_CACHE
        if c is not None and c[0] == key and (now - c[2]) < _ARMED_TTL_S:
            return c[1]
    section = read_petasos_section(res)  # never raises (D3)
    raw = section.get("enabled", True)
    armed = raw if isinstance(raw, bool) else True  # non-bool -> armed
    with _ARMED_LOCK:
        _ARMED_CACHE = (key, armed, now)
    return armed


def write_armed(armed: bool) -> bool:
    """Set ``petasos.enabled`` atomically, preserving every other key/section.

    Returns ``True`` on success, ``False`` on any failure (Windows file lock,
    missing parent dir, etc.) — never raises out to the caller.
    """
    global _ARMED_CACHE
    import contextlib
    import os
    import tempfile

    import yaml

    res = resolve_hermes_config_path()
    try:
        full: dict[str, Any] = {}
        if res.path.is_file():
            with open(res.path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                full = loaded
        section = full.get("petasos")
        if not isinstance(section, dict):
            section = {}
        section["enabled"] = bool(armed)
        full["petasos"] = section
        # mkstemp in the target dir; a missing parent dir raises (caught -> False).
        fd, tmp = tempfile.mkstemp(dir=str(res.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(full, f, default_flow_style=False, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(res.path))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    except Exception:
        return False
    # Refresh this process's cache so a same-process read reflects the write at once.
    try:
        st = res.path.stat()
        with _ARMED_LOCK:
            _ARMED_CACHE = ((st.st_mtime_ns, st.st_size), bool(armed), time.monotonic())
    except OSError:
        _reset_armed_cache()
    return True
