"""Tool-call guard: argument blocking, result scanning, and session escalation.

Two classification axes live on one table (``_TOOL_AXES``) and never share a
vocabulary with PET-134's ``source_taint_namespaces``:

- ``acts`` governs argument-side content blocking. Unknown names default to
  acting (fail-secure). ``READ_ONLY_TOOLS`` is the ``acts=False`` derivation.
- ``ingests`` governs result-side scanning of what a tool returns. Unknown
  names default to ingesting (fail toward scrutiny; PET-181 closed the
  fail-open). ``INGESTION_TOOLS`` is the named ``ingests=True AND
  reaches_hook=True`` subset the ``transform_tool_result`` seam *used to*
  select; the seam now gates on ``NON_INGESTING_TOOLS``. Gate 2 still drops
  a non-string result, so of the four tools scanned before PET-179 only
  three (``read_file``, ``web_extract``, ``web_search``) are reliably
  string-shaped; ``vision_analyze`` (and ``browser_vision``) return a
  multimodal dict on the default native-vision path. Widening gate 2 is
  a residual (not PET-178).
- ``source_taint_namespaces`` governs whether already-scanned content may
  leave via an egress sink. No tool is classified twice for the same question.

Vintage of the per-row evidence anchors: ``_TOOL_AXES_VERIFIED_AGAINST``.
All ten ``mcp_*`` rows are known-dead on both axes (shape-mismatch): Hermes
registers ``mcp__<server>__<tool>``, which canonicalizes to the bare tool
name, while each row is a single-underscore literal that canonicalizes to
itself. They keep their ``READ_ONLY_TOOLS`` seats (no silent drop of a
published set) and carry ``reaches_hook=False`` so they cannot appear in
``INGESTION_TOOLS``. Canonicalization work is PET-118 / PET-121.
"""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

from petasos.normalize import canonicalize_tool_name

_logger = logging.getLogger("petasos.session.guard")

if TYPE_CHECKING:
    from collections.abc import Mapping


class ToolAxes(NamedTuple):
    """Per-tool classification. A row exists where a tool **deviates** from the
    defaults (``acts=True``, ``ingests=True``, ``reaches_hook=True``) **or**
    already carries a per-row evidence pin (the PET-179 browser family, which
    now matches the default and must not be dropped)."""

    acts: bool
    ingests: bool
    reaches_hook: bool
    evidence: str


def _build_axes(rows: tuple[tuple[str, ToolAxes], ...]) -> MappingProxyType[str, ToolAxes]:
    built: dict[str, ToolAxes] = {}
    for name, axes in rows:
        if name in built:
            raise ValueError(f"duplicate tool axis row: {name!r}")
        built[name] = axes
    return MappingProxyType(built)


def _derive(
    table: Mapping[str, ToolAxes],
    *,
    acts: bool | None = None,
    ingests: bool | None = None,
    reaches_hook: bool | None = None,
) -> frozenset[str]:
    """Rows matching ALL supplied filters. Raises if none is supplied."""
    if acts is None and ingests is None and reaches_hook is None:
        raise ValueError("at least one filter is required")
    return frozenset(
        name
        for name, axes in table.items()
        if (acts is None or axes.acts is acts)
        and (ingests is None or axes.ingests is ingests)
        and (reaches_hook is None or axes.reaches_hook is reaches_hook)
    )


_TOOL_AXES_ROWS: tuple[tuple[str, ToolAxes], ...] = (
    (
        "read_file",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/file_tools.py::_handle_read_file",
        ),
    ),
    (
        "vision_analyze",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/vision_tools.py::_handle_vision_analyze",
        ),
    ),
    (
        "web_extract",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/web_tools.py::web_extract_tool",
        ),
    ),
    (
        "web_search",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/web_tools.py::web_search_tool",
        ),
    ),
    (
        "search_files",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/file_tools.py::_handle_search_files",
        ),
    ),
    (
        "browser_navigate",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_tool.py::browser_navigate",
        ),
    ),
    (
        "browser_snapshot",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_tool.py::browser_snapshot",
        ),
    ),
    (
        "browser_click",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_tool.py::browser_click",
        ),
    ),
    (
        "browser_type",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_tool.py::browser_type",
        ),
    ),
    (
        "browser_scroll",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_tool.py::browser_scroll",
        ),
    ),
    (
        "browser_back",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_tool.py::browser_back",
        ),
    ),
    (
        "browser_press",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_tool.py::browser_press",
        ),
    ),
    (
        "browser_get_images",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_tool.py::browser_get_images",
        ),
    ),
    (
        "browser_vision",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_tool.py::browser_vision",
        ),
    ),
    (
        "browser_console",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_tool.py::browser_console",
        ),
    ),
    (
        "browser_cdp",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_cdp_tool.py::browser_cdp",
        ),
    ),
    (
        "browser_dialog",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=True,
            evidence="hermes tools/browser_dialog_tool.py::browser_dialog",
        ),
    ),
    (
        "mcp_vigil_harbor_memory_search",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="live-registry 2026-09-15: absent",
        ),
    ),
    (
        "mcp_vigil_harbor_memory_fetch",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="live-registry 2026-09-15: absent",
        ),
    ),
    (
        "mcp_vigil_harbor_memory_list",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="live-registry 2026-09-15: absent",
        ),
    ),
    (
        "mcp_vigil_harbor_memory_query",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="live-registry 2026-09-15: absent",
        ),
    ),
    (
        "mcp_vigil_harbor_memory_sources",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="live-registry 2026-09-15: absent",
        ),
    ),
    (
        "mcp_vigil_harbor_memory_status",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="live-registry 2026-09-15: absent",
        ),
    ),
    (
        "mcp_plane_list_work_items",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="live-registry 2026-09-15: absent",
        ),
    ),
    (
        "mcp_plane_retrieve_work_item",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="live-registry 2026-09-15: absent",
        ),
    ),
    (
        "mcp_plane_retrieve_work_item_by_identifier",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="live-registry 2026-09-15: absent",
        ),
    ),
    (
        "mcp_plane_list_projects",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="live-registry 2026-09-15: absent",
        ),
    ),
    (
        "session_search",
        ToolAxes(
            acts=False,
            ingests=True,
            reaches_hook=False,
            evidence="hermes tools/session_search_tool.py::session_search",
        ),
    ),
    (
        "read_terminal",
        ToolAxes(
            acts=True,
            ingests=True,
            reaches_hook=False,
            evidence="hermes tools/read_terminal_tool.py::read_terminal_tool",
        ),
    ),
    (
        "todo",
        ToolAxes(
            acts=True,
            ingests=False,
            reaches_hook=False,
            evidence="hermes tools/todo_tool.py::todo_tool",
        ),
    ),
    (
        "memory",
        ToolAxes(
            acts=True,
            ingests=False,
            reaches_hook=False,
            evidence="hermes tools/memory_tool.py::memory_tool",
        ),
    ),
    (
        "clarify",
        ToolAxes(
            acts=True,
            ingests=False,
            reaches_hook=False,
            evidence="hermes tools/clarify_tool.py::clarify_tool",
        ),
    ),
    (
        "delegate_task",
        ToolAxes(
            acts=True,
            ingests=False,
            reaches_hook=False,
            evidence="hermes tools/delegate_tool.py::delegate_task",
        ),
    ),
    (
        "write_file",
        ToolAxes(
            acts=True,
            ingests=False,
            reaches_hook=True,
            evidence="hermes tools/file_tools.py::_handle_write_file",
        ),
    ),
    (
        "kanban_create",
        ToolAxes(
            acts=True,
            ingests=False,
            reaches_hook=True,
            evidence="hermes tools/kanban_tools.py::_handle_create",
        ),
    ),
    (
        "kanban_comment",
        ToolAxes(
            acts=True,
            ingests=False,
            reaches_hook=True,
            evidence="hermes tools/kanban_tools.py::_handle_comment",
        ),
    ),
    (
        "patch",
        ToolAxes(
            acts=True,
            ingests=False,
            reaches_hook=True,
            evidence="hermes tools/file_tools.py::_handle_patch",
        ),
    ),
)

_TOOL_AXES: MappingProxyType[str, ToolAxes] = _build_axes(_TOOL_AXES_ROWS)
_TOOL_AXES_VERIFIED_AGAINST = "hermes-agent b415029b6 (2026-08-06)"

# Argument-axis exemption set (published name; membership means the tool cannot
# act, so its arguments skip content blocking). Unknown names are gated.
READ_ONLY_TOOLS: frozenset[str] = _derive(_TOOL_AXES, acts=False)
# Named hook-reaching ingesting subset. The seam gates on NON_INGESTING_TOOLS;
# this set cannot name tools that are not in the table, which is the point of
# invert, so it is no longer the membership test.
INGESTION_TOOLS: frozenset[str] = _derive(_TOOL_AXES, ingests=True, reaches_hook=True)
NON_INGESTING_TOOLS: frozenset[str] = _derive(_TOOL_AXES, ingests=False)

_READ_ONLY_CANON: frozenset[str] = frozenset(
    c for c in (canonicalize_tool_name(t) for t in READ_ONLY_TOOLS) if c
)


DEFAULT_TOOL_ALIASES: MappingProxyType[str, str] = MappingProxyType(
    {
        "bash": "exec",
        "shell": "exec",
        "terminal": "exec",
        "file_read": "read",
        "read_file": "read",
        "file_write": "write",
        "write_file": "write",
        "web_fetch": "browser",
        "web_search": "browser",
        "http_request": "browser",
    }
)
