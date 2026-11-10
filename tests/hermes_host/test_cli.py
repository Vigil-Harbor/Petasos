"""The petasos command against a real Hermes, inside the sandbox.

The sandbox variable gates the whole module. Each test uses a fresh Hermes
home and installs into that home. Hermes is only started through the sandbox
wrapper.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from tests.hermes_host.client import PETASOS_HARNESS, fresh_home, invoke, sandbox_env
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox


def _run(
    sandbox: Path, home: Path, args: list[str], *, timeout: float = 180
) -> subprocess.CompletedProcess[str]:
    """Run the petasos command inside the sandbox wrapper."""
    wrapper = sandbox / "bin" / "with-sandbox"
    python = sandbox / "venv" / "bin" / "python"
    return subprocess.run(
        [str(wrapper), str(python), "-m", "petasos", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=sandbox_env(home),
    )


def _hermes(
    sandbox: Path, home: Path, args: list[str], *, timeout: float = 180
) -> subprocess.CompletedProcess[str]:
    # ``hermes`` activates this home's package-manager environment. Put the
    # test wheel there first, or the command imports a Python without Petasos.
    invoke(sandbox, {"action": "ensure_wheel"}, home=home, harness=PETASOS_HARNESS)
    wrapper = sandbox / "bin" / "with-sandbox"
    return subprocess.run(
        [str(wrapper), "hermes", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=sandbox_env(home),
    )


def _python(sandbox: Path, home: Path, code: str, *, timeout: float = 120) -> dict[str, Any]:
    wrapper = sandbox / "bin" / "with-sandbox"
    python = sandbox / "venv" / "bin" / "python"
    completed = subprocess.run(
        [str(wrapper), str(python), "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=sandbox_env(home),
    )
    if completed.returncode != 0:
        raise AssertionError(f"snippet exited {completed.returncode}\n{completed.stderr[-2000:]}")
    parsed = json.loads(completed.stdout)
    if not isinstance(parsed, dict):
        raise AssertionError("snippet did not return an object")
    return parsed


@pytest.fixture
def cli_sandbox(petasos_wheel: Path) -> Path:
    """The sandbox whose interpreter has this worktree's wheel."""
    return petasos_wheel


@pytest.fixture
def profile(petasos_wheel: Path, request: pytest.FixtureRequest) -> Path:
    """A fresh Hermes home. The test installs Petasos into it."""
    return fresh_home(petasos_wheel, request.node.name)


def _clear_petasos(home: Path) -> None:
    plugin = home / "plugins" / "petasos"
    if plugin.exists():
        shutil.rmtree(plugin)


def test_install_then_doctor_reports_protected(cli_sandbox: Path, profile: Path) -> None:
    """From a profile with no Petasos plugin, install then doctor says protected."""
    _clear_petasos(profile)
    installed = _run(cli_sandbox, profile, ["hermes", "install"])
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert "Protected." in installed.stdout
    checked = _run(cli_sandbox, profile, ["doctor"])
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "Protected. Petasos is checking tool calls" in checked.stdout
    plugin = str(profile / "plugins" / "petasos")
    report = invoke(cli_sandbox, {"action": "validate", "path": plugin}, home=profile)
    assert report["ok"] is True


def test_doctor_names_each_break(cli_sandbox: Path, profile: Path) -> None:
    """Disabling, a damaged description, a bad job, and a missing hash key are each named."""
    _clear_petasos(profile)
    installed = _run(cli_sandbox, profile, ["hermes", "install"])
    assert installed.returncode == 0, installed.stdout[-2000:]

    disabled = _hermes(cli_sandbox, profile, ["plugins", "disable", "petasos"])
    assert disabled.returncode == 0, disabled.stdout + disabled.stderr
    after_disable = _run(cli_sandbox, profile, ["doctor"])
    assert "switched-off" in after_disable.stdout
    again = _hermes(cli_sandbox, profile, ["plugins", "enable", "petasos"])
    assert again.returncode == 0, again.stdout + again.stderr

    manifest = profile / "plugins" / "petasos" / "plugin.yaml"
    original = manifest.read_text(encoding="utf-8")
    manifest.write_text("not a plugin description\n", encoding="utf-8")
    damaged = _run(cli_sandbox, profile, ["doctor"])
    assert "damaged" in damaged.stdout
    manifest.write_text(original, encoding="utf-8")

    written = _python(
        cli_sandbox,
        profile,
        "import json\n"
        "from hermes_cli.plugins_state import save_plugin_setting\n"
        "save_plugin_setting('petasos', ('role',), 'nope')\n"
        "print(json.dumps({'ok': True}))\n",
    )
    assert written["ok"] is True
    bad_role = _run(cli_sandbox, profile, ["doctor"])
    assert "nope" in bad_role.stdout

    hashed = _python(
        cli_sandbox,
        profile,
        "import json\n"
        "from hermes_cli.plugins_settings import save_plugin_settings\n"
        "from hermes_cli.config import save_env_value\n"
        "from pathlib import Path\n"
        "import os\n"
        "home = Path(os.environ['HERMES_HOME'])\n"
        "save_plugin_settings('petasos', home / 'plugins' / 'petasos', {\n"
        "    'enabled': True, 'role': 'general', 'level': 'balanced',\n"
        "    'overrides': {'anonymization': {'mode': 'hash'}},\n"
        "})\n"
        "save_env_value('PETASOS_HASH_KEY', 'sandbox-hash')\n"
        "print(json.dumps({'ok': True}))\n",
    )
    assert hashed["ok"] is True
    env = profile / ".env"
    text = env.read_text(encoding="utf-8")
    kept = "\n".join(
        line for line in text.splitlines() if not line.startswith("PETASOS_HASH_KEY=")
    )
    env.write_text(kept + "\n", encoding="utf-8")
    missing = _run(cli_sandbox, profile, ["doctor"])
    assert "PETASOS_HASH_KEY" in missing.stdout
    assert "sandbox-hash" not in missing.stdout


def test_migrate_write_is_what_hermes_reads(cli_sandbox: Path, profile: Path) -> None:
    """An old section stored with --write is what Hermes's reader returns. The section stays."""
    _clear_petasos(profile)
    installed = _run(cli_sandbox, profile, ["hermes", "install"])
    assert installed.returncode == 0, installed.stdout[-2000:]
    config = profile / "config.yaml"
    existing = config.read_text(encoding="utf-8") if config.is_file() else ""
    config.write_text(
        existing
        + "\npetasos:\n  enabled: true\n  profile_name: code_generation\n"
        + "  session_secret: hidden-secret\n",
        encoding="utf-8",
    )
    migrated = _run(cli_sandbox, profile, ["config", "migrate", "--write"])
    assert migrated.returncode == 0, migrated.stdout + migrated.stderr
    assert "hidden-secret" not in migrated.stdout
    assert "delete the petasos: block" in migrated.stdout
    read = _python(
        cli_sandbox,
        profile,
        "import json\n"
        "from hermes_cli.plugins import get_plugin_manager\n"
        "manager = get_plugin_manager()\n"
        "manager.discover_and_load()\n"
        "loaded = manager._plugins['petasos']\n"
        "from hermes_cli.plugins import PluginContext\n"
        "ctx = PluginContext(loaded.manifest, manager)\n"
        "print(json.dumps({'role': ctx.get_config('role'), 'level': ctx.get_config('level'), "
        "'enabled': ctx.get_config('enabled')}))\n",
    )
    assert read["role"] == "coding"
    assert read["enabled"] is True
    assert "session_secret: hidden-secret" in config.read_text(encoding="utf-8")
