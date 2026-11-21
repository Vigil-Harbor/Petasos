"""Hermes's own admission check accepts the plugin directory as shipped.

``hermes plugins validate`` runs static manifest checks and a security scan
over every file in the plugin directory. A dangerous verdict means Hermes
will not install or load the plugin. Skipped unless ``PETASOS_HERMES_SANDBOX``
names a prepared sandbox.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from tests.hermes_host.client import PETASOS_HARNESS, Sandbox, call
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox

_ROOT = Path(__file__).resolve().parents[2]
_SOURCES = _ROOT / "hermes-plugin" / "dashboard-src"


def _validate(box: Sandbox) -> dict[str, Any]:
    return call(box, {"action": "validate"}, harness=PETASOS_HARNESS, timeout=180)


def _failed(report: dict[str, Any]) -> list[Any]:
    return [check for check in report["report"]["checks"] if not check.get("ok")]


def test_every_admission_check_passes_on_the_shipped_directory(installed: Sandbox) -> None:
    """The repository's plugin directory, dashboard folder included, passes every check."""
    plugin = installed.home / "plugins" / "petasos"
    assert (plugin / "dashboard" / "index.js").is_file()
    report = _validate(installed)
    assert _failed(report) == [], report
    assert report["ok"] is True, report
    names = " ".join(str(check.get("name", "")) for check in report["report"]["checks"])
    assert "security" in names.lower(), report


def test_the_tab_sources_also_pass_the_security_scan(installed: Sandbox) -> None:
    """Even with the tab's sources copied in beside the joined script, nothing is flagged."""
    target = installed.home / "plugins" / "petasos" / "dashboard" / "src"
    shutil.copytree(_SOURCES, target)
    report = _validate(installed)
    assert _failed(report) == [], report
    assert report["ok"] is True, report
