"""``hermes petasos`` through Hermes's own command dispatch.

The sandbox variable gates the module. This file is run on its own, against
a fresh sandbox. It does not start a gateway.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from petasos.hermes.dashboard.manifest import render_dashboard_manifest
from tests.hermes_host.client import fresh_home, invoke, sandbox_env
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox


def _run(
    sandbox: Path,
    home: Path,
    args: list[str],
    *,
    timeout: float = 180,
) -> subprocess.CompletedProcess[str]:
    """Run one command inside the sandbox wrapper, against ``home``."""
    wrapper = sandbox / "bin" / "with-sandbox"
    return subprocess.run(
        [str(wrapper), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=sandbox_env(home),
        # Not the checkout: the installed wheel must be the copy that runs.
        cwd=str(home),
    )


def _petasos(sandbox: Path, home: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    python = sandbox / "venv" / "bin" / "python"
    return _run(sandbox, home, [str(python), "-m", "petasos", *args])


def _hermes(sandbox: Path, home: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(sandbox, home, ["hermes", *args])


@pytest.fixture
def profile(petasos_wheel: Path, request: pytest.FixtureRequest) -> Path:
    """A fresh Hermes home. Nothing is shared with another test."""
    return fresh_home(petasos_wheel, request.node.name)


def _json_report(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    if completed.returncode not in (0, 1, 2):
        raise AssertionError(
            f"exit {completed.returncode}\n{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"not JSON\n{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
        ) from exc
    if not isinstance(payload, dict):
        raise AssertionError("report was not an object")
    return payload


def test_hermes_petasos_doctor_matches_the_standalone_command(
    petasos_wheel: Path, profile: Path
) -> None:
    """``hermes petasos doctor`` and ``petasos doctor`` agree for one home."""
    installed = _petasos(petasos_wheel, profile, ["hermes", "install"])
    assert installed.returncode in (0, 1), installed.stdout[-2000:] + installed.stderr[-2000:]

    help_text = _hermes(petasos_wheel, profile, ["petasos", "--help"])
    assert help_text.returncode == 0, help_text.stderr[-2000:]
    assert "doctor" in help_text.stdout
    assert "migrate" in help_text.stdout or "config" in help_text.stdout

    standalone = _petasos(petasos_wheel, profile, ["doctor", "--json"])
    native = _hermes(petasos_wheel, profile, ["petasos", "doctor", "--json"])
    left = _json_report(standalone)
    right = _json_report(native)
    assert right["verdict"] == left["verdict"]
    assert right["exit_code"] == left["exit_code"]
    assert native.returncode == standalone.returncode
    left_checks = left["checks"]
    right_checks = right["checks"]
    assert isinstance(left_checks, list) and isinstance(right_checks, list)
    assert [row["id"] for row in left_checks] == [row["id"] for row in right_checks]
    assert [row["status"] for row in left_checks] == [row["status"] for row in right_checks]


def test_install_writes_a_dashboard_hermes_accepts(petasos_wheel: Path, profile: Path) -> None:
    """The installed plugin and its dashboard files are the ones this version ships."""
    installed = _petasos(petasos_wheel, profile, ["hermes", "install"])
    assert installed.returncode in (0, 1), installed.stdout[-2000:] + installed.stderr[-2000:]

    plugin = profile / "plugins" / "petasos"
    report = invoke(petasos_wheel, {"action": "validate", "path": str(plugin)}, home=profile)
    assert report["ok"] is True, report

    dashboard = plugin / "dashboard"
    manifest = (dashboard / "manifest.json").read_text(encoding="utf-8")
    assert manifest == render_dashboard_manifest()
    api = (dashboard / "plugin_api.py").read_text(encoding="utf-8")
    assert "build_router" in api
    assert (dashboard / "index.js").read_text(encoding="utf-8").strip()

    snippet = (
        "import json; from pathlib import Path; "
        "from hermes_cli.web_server_dashboard import _dashboard_plugin_entry; "
        f"folder = Path({str(dashboard)!r}); "
        "data = json.loads((folder / 'manifest.json').read_text()); "
        "entry = _dashboard_plugin_entry(data, 'petasos', folder, 'user'); "
        "print(json.dumps({'has_api': entry['has_api'], 'path': entry['tab']['path'], "
        "'hidden': bool(entry['tab'].get('hidden'))}))"
    )
    python = petasos_wheel / "venv" / "bin" / "python"
    checked = _run(petasos_wheel, profile, [str(python), "-c", snippet])
    assert checked.returncode == 0, checked.stderr[-2000:]
    body = json.loads(checked.stdout)
    assert body["has_api"] is True
    assert body["path"] == "/petasos"
    assert body["hidden"] is False
