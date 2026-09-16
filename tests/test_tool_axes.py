"""PET-179: two-axis tool classification. Both published sets are derived from
``_TOOL_AXES``; a like-for-like swap that preserves counts still fails the
membership pin.
"""

from __future__ import annotations

import re
from types import MappingProxyType

import pytest

from petasos.session.guard import (
    _TOOL_AXES,
    _TOOL_AXES_ROWS,
    INGESTION_TOOLS,
    READ_ONLY_TOOLS,
    ToolAxes,
    _build_axes,
    _derive,
)

_EVIDENCE_RE = re.compile(r"^(hermes \S+::\S+|live-registry \d{4}-\d{2}-\d{2}: (present|absent))$")

_HOOK_BYPASSING = frozenset(
    {"todo", "session_search", "memory", "clarify", "read_terminal", "delegate_task"}
)

_EXPECTED_READ_ONLY = (
    "mcp_plane_list_projects",
    "mcp_plane_list_work_items",
    "mcp_plane_retrieve_work_item",
    "mcp_plane_retrieve_work_item_by_identifier",
    "mcp_vigil_harbor_memory_fetch",
    "mcp_vigil_harbor_memory_list",
    "mcp_vigil_harbor_memory_query",
    "mcp_vigil_harbor_memory_search",
    "mcp_vigil_harbor_memory_sources",
    "mcp_vigil_harbor_memory_status",
    "read_file",
    "search_files",
    "session_search",
    "vision_analyze",
    "web_extract",
    "web_search",
)

_EXPECTED_INGESTION = (
    "browser_back",
    "browser_cdp",
    "browser_click",
    "browser_console",
    "browser_dialog",
    "browser_get_images",
    "browser_navigate",
    "browser_press",
    "browser_scroll",
    "browser_snapshot",
    "browser_type",
    "browser_vision",
    "read_file",
    "search_files",
    "vision_analyze",
    "web_extract",
    "web_search",
)


def test_browser_navigate_is_scanned_and_still_argument_gated() -> None:
    """Regression for PET-179: both halves for one tool, which one frozenset cannot satisfy."""
    assert "browser_navigate" in INGESTION_TOOLS
    assert "browser_navigate" not in READ_ONLY_TOOLS
    assert "browser_type" not in READ_ONLY_TOOLS
    assert "browser_click" not in READ_ONLY_TOOLS
    assert "browser_type" in INGESTION_TOOLS
    assert "browser_click" in INGESTION_TOOLS


def test_derive_is_the_only_source() -> None:
    assert _derive(_TOOL_AXES, acts=False) == READ_ONLY_TOOLS
    assert _derive(_TOOL_AXES, ingests=True, reaches_hook=True) == INGESTION_TOOLS

    synthetic = _build_axes(
        (
            ("a", ToolAxes(acts=False, ingests=True, reaches_hook=True, evidence="hermes x::y")),
            ("b", ToolAxes(acts=True, ingests=True, reaches_hook=False, evidence="hermes x::y")),
            ("c", ToolAxes(acts=True, ingests=False, reaches_hook=True, evidence="hermes x::y")),
        )
    )
    assert _derive(synthetic, acts=False) == frozenset({"a"})
    assert _derive(synthetic, ingests=True) == frozenset({"a", "b"})
    assert _derive(synthetic, ingests=True, reaches_hook=True) == frozenset({"a"})
    with pytest.raises(ValueError, match="at least one filter"):
        _derive(synthetic)


def test_unknown_tool_defaults_stated_per_axis() -> None:
    """Unknown names are gated on arguments and unscanned on results. PET-181 owns the latter."""
    unknown = "definitely_not_a_registered_tool"
    assert unknown not in READ_ONLY_TOOLS
    assert unknown not in INGESTION_TOOLS
    assert unknown not in _TOOL_AXES


def test_every_row_carries_a_structured_evidence_anchor() -> None:
    for name, axes in _TOOL_AXES.items():
        assert _EVIDENCE_RE.match(axes.evidence), f"{name}: {axes.evidence!r}"


def test_hook_bypassing_tools_are_marked() -> None:
    for name in _HOOK_BYPASSING:
        assert name in _TOOL_AXES, name
        assert _TOOL_AXES[name].reaches_hook is False, name
    assert _TOOL_AXES["session_search"].ingests is True
    assert _TOOL_AXES["session_search"].reaches_hook is False


def test_argument_axis_does_not_widen() -> None:
    assert READ_ONLY_TOOLS.isdisjoint(
        {"todo", "memory", "clarify", "delegate_task", "read_terminal"}
    )


def test_phantom_names_are_gone() -> None:
    assert "search" not in READ_ONLY_TOOLS
    assert "list_directory" not in READ_ONLY_TOOLS
    assert "search_files" in READ_ONLY_TOOLS
    assert "search_files" in INGESTION_TOOLS


def test_published_counts() -> None:
    mcp_rows = {n for n in _TOOL_AXES if n.startswith("mcp_")}
    browser_rows = {n for n in _TOOL_AXES if n.startswith("browser_")}
    assert len(_TOOL_AXES) == 33
    assert len(READ_ONLY_TOOLS) == 16
    assert len(INGESTION_TOOLS) == 17
    assert sum(1 for a in _TOOL_AXES.values() if a.ingests) == 29
    assert INGESTION_TOOLS - mcp_rows - browser_rows - {"search_files"} == {
        "read_file",
        "vision_analyze",
        "web_extract",
        "web_search",
    }


def test_table_is_immutable_and_has_no_duplicate_keys() -> None:
    assert isinstance(_TOOL_AXES, MappingProxyType)
    with pytest.raises((TypeError, AttributeError)):
        _TOOL_AXES["x"] = ToolAxes(True, True, True, "hermes a::b")  # type: ignore[index]
    with pytest.raises(ValueError, match="duplicate"):
        _build_axes(
            (
                ("a", ToolAxes(True, False, True, "hermes x::y")),
                ("a", ToolAxes(False, True, True, "hermes x::y")),
            )
        )
    assert len(_TOOL_AXES_ROWS) == len(_TOOL_AXES) == 33


def test_full_membership_is_pinned() -> None:
    assert tuple(sorted(READ_ONLY_TOOLS)) == _EXPECTED_READ_ONLY
    assert tuple(sorted(INGESTION_TOOLS)) == _EXPECTED_INGESTION
