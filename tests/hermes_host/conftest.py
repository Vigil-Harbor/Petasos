"""Per-test Hermes homes inside one prepared sandbox."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.hermes_host.client import (
    PETASOS_HARNESS,
    Sandbox,
    call,
    fresh_home,
    invoke,
    reap,
    sandbox_path,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def hermes_sandbox() -> Path:
    """Provide hermes sandbox for the test fixture."""
    path = sandbox_path()
    if not (path / "bin" / "with-sandbox").is_file():
        pytest.fail(f"PETASOS_HERMES_SANDBOX={path} has no bin/with-sandbox")
    if not (path / "venv" / "bin" / "python").is_file():
        pytest.fail(f"PETASOS_HERMES_SANDBOX={path} has no venv")
    return path


@pytest.fixture(scope="session", autouse=True)
def _stop_sandbox_processes() -> Iterator[None]:
    """Stop any Hermes process a test started, including after a failed run."""
    yield
    raw = os.environ.get("PETASOS_HERMES_SANDBOX", "")
    if not raw:
        return
    still = reap(Path(raw))
    if still:
        pytest.fail(f"Hermes processes still running: {still}")


@pytest.fixture(scope="session")
def standin_wheel(hermes_sandbox: Path) -> Path:
    """The stand-in wheel, installed once into the sandbox interpreter."""
    result = invoke(hermes_sandbox, {"action": "install_standin_wheel"}, timeout=240)
    if not result.get("ok"):
        pytest.fail(f"install_standin_wheel failed: {result}")
    return hermes_sandbox


@pytest.fixture
def standin(standin_wheel: Path, request: pytest.FixtureRequest) -> Sandbox:
    """A fresh home with both stand-in plugins enabled."""
    home = fresh_home(standin_wheel, request.node.name)
    result = invoke(standin_wheel, {"action": "prepare_standin_home"}, home=home)
    if not result.get("ok"):
        pytest.fail(f"prepare_standin_home failed: {result}")
    return Sandbox(standin_wheel, home)


@pytest.fixture(scope="session")
def petasos_wheel(hermes_sandbox: Path) -> Path:
    """This worktree's wheel, installed once into the sandbox interpreter."""
    result = invoke(
        hermes_sandbox,
        {"action": "install_wheel", "worktree": str(_ROOT)},
        harness=PETASOS_HARNESS,
        timeout=240,
    )
    if not result.get("ok"):
        pytest.fail(f"install_wheel failed: {result}")
    return hermes_sandbox


@pytest.fixture
def installed(petasos_wheel: Path, request: pytest.FixtureRequest) -> Sandbox:
    """A fresh home with the Petasos plugin directory enabled and the wheel in place."""
    home = fresh_home(petasos_wheel, request.node.name)
    box = Sandbox(petasos_wheel, home)
    result = call(
        box,
        {"action": "install_home", "worktree": str(_ROOT)},
        harness=PETASOS_HARNESS,
        timeout=180,
    )
    if not result.get("ok"):
        pytest.fail(f"install_home failed: {result}")
    return box
