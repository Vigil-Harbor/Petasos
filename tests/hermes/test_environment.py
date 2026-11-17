"""The doctor asks the environment Hermes would run, not this interpreter."""

from __future__ import annotations

import hashlib
import json
import shlex
import stat
from typing import TYPE_CHECKING

import pytest

from petasos.hermes.dashboard.scope import load_home
from petasos.hermes.dashboard.status import status
from petasos.hermes.doctor import examine
from petasos.hermes.environment import Probe
from petasos.hermes.install import render_project
from tests.hermes.conftest import healthy_home

if TYPE_CHECKING:
    from pathlib import Path


def _facts(home: Path, python: Path) -> None:
    environment = python.parent.parent
    key = home / "installs" / "abc"
    key.mkdir(parents=True)
    environment.mkdir(parents=True, exist_ok=True)
    recorded = key / "environments" / "one" / "venv"
    recorded.mkdir(parents=True)
    (recorded / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    payload = {"schema": 1, "packages": {"venv": {"environment": str(recorded)}}}
    (key / "facts.json").write_text(json.dumps(payload), encoding="utf-8")
    bindir = recorded / "bin"
    bindir.mkdir()
    script = bindir / "python"
    script.write_text(python.read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _python(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _enabled(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "plugins" / "petasos").mkdir(parents=True)
    (home / "plugins" / "petasos" / "pyproject.toml").write_text(
        'dependencies = ["petasos==0.4.0"]\n',
        encoding="utf-8",
    )
    (home / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - petasos\n",
        encoding="utf-8",
    )


def test_no_committed_environment_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A home with no environment record says so, and does not claim a failure."""
    _enabled(tmp_path)
    report = examine(tmp_path, home_reason="test")
    check = next(item for item in report.checks if item.id == "hermes_environment")
    assert check.status == "info"
    assert "has not committed an environment" in check.summary


def test_a_profile_reads_the_environment_its_root_recorded(tmp_path: Path) -> None:
    """Profiles under one root share the root's environment record."""
    home = tmp_path / "profiles" / "ops"
    _enabled(home)
    script = _python(
        tmp_path / "answer.sh",
        'printf \'{"ok": false, "error": "No module named petasos"}\\n\'\n',
    )
    _facts(tmp_path, script)
    report = examine(home, home_reason="test")
    check = next(item for item in report.checks if item.id == "hermes_environment")
    assert check.status == "fail"
    assert "not in the environment" in check.summary


def test_a_missing_import_is_not_protected(tmp_path: Path) -> None:
    """A committed environment that cannot import Petasos is not protection."""
    _enabled(tmp_path)
    script = _python(
        tmp_path / "answer.sh",
        'printf \'{"ok": false, "error": "No module named petasos"}\\n\'\n',
    )
    _facts(tmp_path, script)
    report = examine(tmp_path, home_reason="test")
    check = next(item for item in report.checks if item.id == "hermes_environment")
    assert check.status == "fail"
    assert report.verdict == "not_protected"
    assert "not in the environment" in check.summary
    assert f"petasos hermes install --home {tmp_path}" in check.next_step


def test_dashboard_status_follows_the_environment_check(tmp_path: Path) -> None:
    """The tab's protection flag uses the same check as doctor."""
    _enabled(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "plugins:\n"
        "  enabled:\n"
        "    - petasos\n"
        "  entries:\n"
        "    petasos:\n"
        "      settings:\n"
        "        enabled: true\n"
        "        role: research\n"
        "        level: strict\n",
        encoding="utf-8",
    )
    script = _python(
        tmp_path / "answer.sh",
        'printf \'{"ok": false, "error": "No module named petasos"}\\n\'\n',
    )
    _facts(tmp_path, script)
    body = status(load_home(tmp_path))
    assert body["protection"] == "off"
    row = next(item for item in body["doctor"]["checks"] if item["id"] == "hermes_environment")
    assert row["status"] == "fail"
    assert "petasos hermes install" in row["next_step"]


def test_a_compatible_version_is_ok(tmp_path: Path) -> None:
    """Version 0.4.0 satisfies the plugin's pin, so the check passes."""
    _enabled(tmp_path)
    script = _python(
        tmp_path / "answer.sh",
        'printf \'{"ok": true, "version": "0.4.0"}\\n\'\n',
    )
    _facts(tmp_path, script)
    report = examine(tmp_path, home_reason="test")
    check = next(item for item in report.checks if item.id == "hermes_environment")
    assert check.status == "ok"
    assert "0.4.0" in check.summary


def test_an_incompatible_version_is_not_protected(tmp_path: Path) -> None:
    """A newer major version in that environment is not this plugin."""
    _enabled(tmp_path)
    script = _python(
        tmp_path / "answer.sh",
        'printf \'{"ok": true, "version": "0.5.0"}\\n\'\n',
    )
    _facts(tmp_path, script)
    report = examine(tmp_path, home_reason="test")
    check = next(item for item in report.checks if item.id == "hermes_environment")
    assert check.status == "fail"
    assert report.verdict == "not_protected"
    assert "0.5.0" in check.summary
    assert "petasos hermes install" in check.next_step


@pytest.mark.parametrize("use_hash", [False, True])
@pytest.mark.parametrize("stale", [False, True])
def test_doctor_compares_the_committed_build_to_the_plugin_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_hash: bool, stale: bool
) -> None:
    home = healthy_home(tmp_path, monkeypatch)
    target = home / "plugins" / "petasos"
    source = target / "wheels" / "new" / "petasos-0.4.0-py3-none-any.whl"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new")
    (target / "pyproject.toml").write_text(
        render_project(source.relative_to(target / "wheels").as_posix()), encoding="utf-8"
    )
    older = source.with_name("old.whl")
    older.write_bytes(b"old")
    direct: dict[str, object] = {"url": (older if stale else source).as_uri()}
    if use_hash:
        # Hermes's generation URL differs even when the installed bytes match.
        direct = {
            "url": (home / "generation" / source.name).as_uri(),
            "archive_info": {
                "hashes": {"sha256": hashlib.sha256(b"old" if stale else b"new").hexdigest()}
            },
        }
    payload = {"ok": True, "version": "0.4.0", "direct_url": json.dumps(direct)}
    script = _python(
        tmp_path / "answer.sh", "printf '%s\\n' " + shlex.quote(json.dumps(payload)) + "\n"
    )
    _facts(home, script)
    report = examine(home, home_reason="test")
    check = next(item for item in report.checks if item.id == "hermes_environment")
    assert check.status == ("warn" if stale else "ok")
    assert report.verdict != "not_protected"
    if stale:
        assert str(home) in check.next_step and "petasos hermes install" in check.next_step


@pytest.mark.parametrize("direct", ["", "null", "[]", "invalid", '{"archive_info": null}'])
def test_unavailable_build_provenance_is_unknown(tmp_path: Path, direct: str) -> None:
    assert Probe(ok=True, direct_url=direct).matches_wheel(tmp_path / "missing.whl") is None


@pytest.mark.parametrize("stale", [False, True])
def test_snapshot_wheel_without_archive_hash(tmp_path: Path, stale: bool) -> None:
    source = tmp_path / "source.whl"
    source.write_bytes(b"new")
    snapshot = tmp_path / "snapshot.whl"
    snapshot.write_bytes(b"old" if stale else b"new")
    direct = json.dumps({"url": snapshot.as_uri(), "archive_info": {}})
    assert Probe(ok=True, direct_url=direct).matches_wheel(source) is not stale


def test_a_recorded_wheel_that_is_gone_is_unknown(tmp_path: Path) -> None:
    source = tmp_path / "source.whl"
    source.write_bytes(b"new")
    gone = tmp_path / "generation" / "petasos.whl"
    direct = json.dumps({"url": gone.as_uri(), "archive_info": {}})
    assert Probe(ok=True, direct_url=direct).matches_wheel(source) is None
