"""Cross-process config-change reader: sibling of ``_armed.py`` (PET-126).

A TTL + ``(mtime_ns, size)``-gated reader over ``resolve_hermes_config_path()``
that surfaces a *changed*, non-empty ``petasos:`` section so the gateway can
hot-apply a Config Editor save to a running session. It differs from
``read_armed`` in two load-bearing ways (spec Decision 3):

* **Fail-safe, not fail-secure.** Any stat/read error, or an empty/missing/wiped
  section, returns ``None`` ("no change, keep last-good"); it never builds an
  all-defaults config from a wiped section (D-WIN, Decision 9). ``read_armed``
  instead fails *secure* (errors arm). The two keep separate caches over the same
  resolver so neither posture is forced onto the other; a test pins that they
  resolve to the identical path.
* **Emits change, not state.** ``read_armed`` may re-emit the same bool;
  ``read_changed_section`` returns a section only when it actually changed.

Peek + commit-on-success (Decision 3): ``read_changed_section`` does NOT advance
the seen key by itself. It returns ``(section, key)`` and the caller calls
``commit_seen(key)`` only after a successful apply. A failed apply leaves the key
uncommitted, so the same change is re-attempted on the next call after the TTL: a
failed apply can never silently pin a stale config. Never raises.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from petasos.console._paths import read_petasos_section, resolve_hermes_config_path

_RELOAD_LOCK = threading.Lock()
_RELOAD_TTL_S = 1.0
# (seen_key, seen_section, monotonic_ts) | None — seen_key is the
# (st_mtime_ns, st_size) of the last COMMITTED section; written only by
# commit_seen / _reset_reload_cache. read_changed_section is a pure reader of it.
_RELOAD_CACHE: tuple[tuple[int, int], dict[str, Any], float] | None = None


def _reset_reload_cache() -> None:
    """Test seam: drop the cache (mirrors ``_reset_armed_cache``)."""
    global _RELOAD_CACHE
    with _RELOAD_LOCK:
        _RELOAD_CACHE = None


def read_changed_section() -> tuple[dict[str, Any], tuple[int, int]] | None:
    """Return ``(section, key)`` when the ``petasos:`` section changed, else ``None``.

    ``key = (mtime_ns, size)``. Logic:

    * stat fails (missing/locked) -> ``None`` (fail-safe, keep last-good).
    * key matches the committed key and age < TTL -> ``None`` (no re-parse).
    * otherwise re-read; an empty ``{}`` from ``read_petasos_section``
      (missing/wiped/malformed) -> ``None`` and the cache is NOT advanced
      (D-WIN + the stat-then-read TOCTOU collapse into one "empty -> None" path).
    * key matches the committed key and the parsed dict equals the committed
      section -> ``None`` (the timestamp is refreshed to throttle re-parsing). This
      is the same-tick guard: a same-size, same-mtime-tick rewrite on coarse-mtime
      Windows/FAT is still observed once the content differs.
    * anything else is a real change -> ``(section, key)``.

    Does not self-advance the seen key; the caller commits via ``commit_seen``.
    Never raises.
    """
    global _RELOAD_CACHE
    try:
        res = resolve_hermes_config_path()
        try:
            st = res.path.stat()
            key = (st.st_mtime_ns, st.st_size)
        except OSError:
            return None  # cannot stat -> keep last-good (fail-safe)

        now = time.monotonic()
        with _RELOAD_LOCK:
            cache = _RELOAD_CACHE
            if cache is not None and cache[0] == key and (now - cache[2]) < _RELOAD_TTL_S:
                return None  # within TTL at the committed key -> no work

        section = read_petasos_section(res)  # never raises (D3)
        if not section:
            # Empty/missing/wiped/malformed -> no change, keep last-good (D-WIN).
            # The cache is NOT advanced, so a later non-empty write is still seen.
            return None

        with _RELOAD_LOCK:
            cache = _RELOAD_CACHE
            if cache is not None and cache[0] == key and section == cache[1]:
                # Same key, identical content: not a change. Refresh the timestamp
                # so a steady state re-parses at most once per TTL (mirrors
                # read_armed's steady-state cost).
                _RELOAD_CACHE = (cache[0], cache[1], now)
                return None
            return section, key
    except Exception:
        return None  # never raises out (fail-safe)


def commit_seen(key: tuple[int, int]) -> None:
    """Advance the seen key after a successful apply (commit-on-success).

    Re-reads the resolved section so the cached ``(key, section, ts)`` lets a
    subsequent same-key call short-circuit (and feeds the same-tick content
    compare). Re-applying the same already-validated config is idempotent, so the
    rare race where the file changes again between read and commit costs at most
    one redundant re-apply on the next call rather than a correctness bug.
    """
    global _RELOAD_CACHE
    try:
        res = resolve_hermes_config_path()
        section = read_petasos_section(res)
    except Exception:
        section = {}
    with _RELOAD_LOCK:
        _RELOAD_CACHE = (key, section, time.monotonic())
