"""Commands write to the named profile while another home is active."""

from __future__ import annotations

import json
import sys
import types
from contextvars import ContextVar
from typing import TYPE_CHECKING

import pytest

from petasos.cli import main
from tests.hermes.conftest import enabled_config, write_config, write_plugin

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


@pytest.mark.parametrize("command", ["set", "migrate", "released"])
@pytest.mark.parametrize("selector", ["home", "profile"])
def test_commands_write_only_the_named_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, selector: str
) -> None:
    active = tmp_path / "active"
    named = active / "profiles" / "named"
    for home in (active, named):
        write_plugin(home)
        write_config(home, enabled_config())
    config = named / "config.yaml"
    config.write_text(config.read_text() + "\npetasos:\n  profile_name: research\n")
    before = (active / "config.yaml").read_bytes()
    current: ContextVar[Path] = ContextVar("test_home", default=active)
    constants = types.ModuleType("hermes_constants")
    constants.set_hermes_home_override = current.set  # type: ignore[attr-defined]
    constants.reset_hermes_home_override = current.reset  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
    monkeypatch.setenv("HERMES_HOME", str(active))

    def save(values: Mapping[str, object], *, plugin_dir: Path) -> None:
        write_config(current.get(), json.dumps({"saved": dict(values)}))

    def released() -> tuple[bool, str]:
        write_config(current.get(), json.dumps({"installed": True}))
        return True, "Installed."

    monkeypatch.setattr("petasos.hermes.config_set.write_settings", save)
    monkeypatch.setattr("petasos.hermes.migrate_cmd.write_settings", save)
    monkeypatch.setattr("petasos.hermes.install.run_released_install", released)
    args = {
        "set": ["config", "set", "role", "research"],
        "migrate": ["config", "migrate", "--write"],
        "released": ["hermes", "install", "--released", "--run"],
    }[command]
    args += ["--home", str(named)] if selector == "home" else ["--profile", "named"]
    main(args)
    assert (active / "config.yaml").read_bytes() == before
    written = json.loads(config.read_text())
    if command == "released":
        assert written["installed"] is True
    else:
        assert written["saved"]["role"] == "research"
    assert current.get() == active
