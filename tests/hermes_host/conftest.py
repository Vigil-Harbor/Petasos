"""Session fixture: install the stand-in plugin into the prepared sandbox."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.hermes_host.client import invoke, sandbox_path

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="session")
def hermes_sandbox() -> Path:
    path = sandbox_path()
    if not (path / "bin" / "with-sandbox").is_file():
        pytest.fail(f"PETASOS_HERMES_SANDBOX={path} has no bin/with-sandbox")
    if not (path / "venv" / "bin" / "python").is_file():
        pytest.fail(f"PETASOS_HERMES_SANDBOX={path} has no venv")
    result = invoke(path, {"action": "ensure_plugin"}, timeout=240)
    if not result.get("ok"):
        pytest.fail(f"ensure_plugin failed: {result}")
    return path
