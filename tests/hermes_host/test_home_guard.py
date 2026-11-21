"""The wrapper keeps a Hermes home inside the sandbox."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.hermes_host.client import fresh_home, sandbox_env
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox


def test_wrapper_refuses_a_home_outside_the_sandbox(hermes_sandbox: Path) -> None:
    """A home that does not resolve under the sandbox never reaches a command."""
    outside = Path("/tmp/petasos-p1a-not-a-home")
    outside.mkdir(exist_ok=True)
    env = sandbox_env(None)
    env["PETASOS_HERMES_HOME"] = str(outside)
    completed = subprocess.run(
        [str(hermes_sandbox / "bin" / "with-sandbox"), "/usr/bin/true"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert completed.returncode != 0
    assert "refusing" in completed.stderr


def test_a_chosen_home_is_the_one_hermes_resolves(hermes_sandbox: Path) -> None:
    """``get_hermes_home`` follows the home the wrapper accepted."""
    home = fresh_home(hermes_sandbox, "guard")
    python = hermes_sandbox / "venv" / "bin" / "python"
    completed = subprocess.run(
        [
            str(hermes_sandbox / "bin" / "with-sandbox"),
            str(python),
            "-c",
            "from hermes_constants import get_hermes_home; print(get_hermes_home())",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=sandbox_env(home),
    )
    assert completed.returncode == 0, completed.stderr
    assert Path(completed.stdout.strip()).resolve() == home.resolve()
