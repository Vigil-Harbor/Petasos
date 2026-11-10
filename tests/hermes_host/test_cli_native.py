"""``hermes petasos`` through Hermes's own command dispatch.

The sandbox variable gates the module. This file is run on its own, against
a fresh sandbox. It does not start a gateway.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from petasos.hermes.dashboard.manifest import render_dashboard_manifest
from tests.hermes_host.client import invoke
from tests.hermes_host.marks import requires_hermes_sandbox

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = requires_hermes_sandbox

_ROOT = Path(__file__).resolve().parents[2]


def _run(
    sandbox: Path, args: list[str], *, timeout: float = 180
) -> subprocess.CompletedProcess[str]:
    """Run one command inside the sandbox wrapper."""
    wrapper = sandbox / "bin" / "with-sandbox"
    return subprocess.run(
        [str(wrapper), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _petasos(sandbox: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    python = sandbox / "venv" / "bin" / "python"
    return _run(sandbox, [str(python), "-m", "petasos", *args])


def _hermes(sandbox: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(sandbox, ["hermes", *args])


@pytest.fixture(scope="module")
def native_sandbox(hermes_sandbox: Path) -> Path:
    """Install this worktree into the sandbox interpreter."""
    completed = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(hermes_sandbox / "venv" / "bin" / "python"),
            "-e",
            str(_ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr[-2000:])
    return hermes_sandbox


@pytest.fixture
def profile(native_sandbox: Path, tmp_path: Path) -> Iterator[Path]:
    """The sandbox home, restored after the test."""
    home = native_sandbox / "hermes_home"
    plugin = home / "plugins" / "petasos"
    saved_plugin = tmp_path / "plugin"
    if plugin.exists():
        shutil.copytree(plugin, saved_plugin)
    config = home / "config.yaml"
    env = home / ".env"
    saved_config = config.read_text(encoding="utf-8") if config.is_file() else None
    saved_env = env.read_text(encoding="utf-8") if env.is_file() else None
    yield home
    if plugin.exists():
        shutil.rmtree(plugin)
    if saved_plugin.exists():
        shutil.copytree(saved_plugin, plugin)
    if saved_config is None:
        config.unlink(missing_ok=True)
    else:
        config.write_text(saved_config, encoding="utf-8")
    if saved_env is None:
        env.unlink(missing_ok=True)
    else:
        env.write_text(saved_env, encoding="utf-8")


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
    native_sandbox: Path, profile: Path
) -> None:
    """``hermes petasos doctor`` and ``petasos doctor`` agree for one home."""
    installed = _petasos(native_sandbox, ["hermes", "install", "--home", str(profile)])
    assert installed.returncode in (0, 1), installed.stdout[-2000:] + installed.stderr[-2000:]

    help_text = _hermes(native_sandbox, ["petasos", "--help"])
    assert help_text.returncode == 0, help_text.stderr[-2000:]
    assert "doctor" in help_text.stdout
    assert "migrate" in help_text.stdout or "config" in help_text.stdout

    standalone = _petasos(native_sandbox, ["doctor", "--json", "--home", str(profile)])
    native = _hermes(native_sandbox, ["petasos", "doctor", "--json", "--home", str(profile)])
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


def test_install_writes_a_dashboard_hermes_accepts(native_sandbox: Path, profile: Path) -> None:
    """The installed plugin and its dashboard files are the ones this version ships."""
    if (profile / "plugins" / "petasos").exists():
        shutil.rmtree(profile / "plugins" / "petasos")
    installed = _petasos(native_sandbox, ["hermes", "install", "--home", str(profile)])
    assert installed.returncode in (0, 1), installed.stdout[-2000:] + installed.stderr[-2000:]

    plugin = profile / "plugins" / "petasos"
    report = invoke(native_sandbox, {"action": "validate", "path": str(plugin)})
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
    python = native_sandbox / "venv" / "bin" / "python"
    checked = _run(native_sandbox, [str(python), "-c", snippet])
    assert checked.returncode == 0, checked.stderr[-2000:]
    body = json.loads(checked.stdout)
    assert body["has_api"] is True
    assert body["path"] == "/petasos"
    assert body["hidden"] is False
