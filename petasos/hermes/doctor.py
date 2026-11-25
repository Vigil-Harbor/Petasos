"""Say whether Petasos is protecting one Hermes profile.

The report is read-only. A missing Hermes install, or a missing YAML reader,
is a line in the report. The checks that do not need them still run.

Checks live in the sibling modules and return a :class:`Report`.
:func:`render_text` and :func:`render_json` are two views of that report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.hermes.doctor_install import hermes_view, plugin_load_view
from petasos.hermes.doctor_model import Check, HermesView, Report
from petasos.hermes.doctor_render import render_json, render_text, report_payload
from petasos.hermes.doctor_report import build_report

if TYPE_CHECKING:
    from pathlib import Path

    from petasos.scanners.registry import ScannerSpec

__all__ = [
    "Check",
    "HermesView",
    "Report",
    "examine",
    "hermes_view",
    "plugin_load_view",
    "render_json",
    "render_text",
    "report_payload",
]


def examine(
    home: Path,
    *,
    home_reason: str,
    probe_plugin: bool = True,
    registry: tuple[ScannerSpec, ...] | None = None,
) -> Report:
    """Read ``home`` and return the doctor report. Nothing is written.

    ``probe_plugin`` asks Hermes to validate the plugin. Set it false when
    the caller must not start the plugin, which is what the dashboard does.
    ``registry`` replaces the scanner registry. The default is the real one.
    """
    return build_report(
        home,
        home_reason=home_reason,
        hermes_view_fn=hermes_view,
        plugin_load_fn=plugin_load_view,
        probe_plugin=probe_plugin,
        registry=registry,
    )
