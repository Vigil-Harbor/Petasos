"""The doctor asks the environment Hermes would run, not this interpreter."""

from __future__ import annotations

import hashlib
import json
import os
import sysconfig
import venv
from pathlib import Path

import pytest

from petasos.hermes.dashboard.scope import load_home
from petasos.hermes.dashboard.status import status
from petasos.hermes.doctor import examine
from petasos.hermes.environment import Probe, file_url_path
from petasos.hermes.install import render_project
from tests.hermes.conftest import healthy_home

_NOT_INSTALLED = '{"ok": false, "error": "No module named petasos"}'


def _facts(home: Path, answer: str) -> None:
    """Record a committed environment whose Python prints ``answer`` to any question.

    The stand-in is a real interpreter, so it runs on every system. Its
    ``sitecustomize`` answers and exits before the doctor's question is read.
    """
    key = home / "installs" / "abc"
    recorded = key / "environments" / "one" / "venv"
    venv.create(recorded, with_pip=False, symlinks=os.name != "nt")
    where = {"base": str(recorded), "platbase": str(recorded)}
    packages = Path(sysconfig.get_path("purelib", "venv", vars=where))
    (packages / "sitecustomize.py").write_text(
        "import os, sys\n"
        f"sys.stdout.write({answer + chr(10)!r})\n"
        "sys.stdout.flush()\n"
        "os._exit(0)\n",
        encoding="utf-8",
    )
    payload = {"schema": 1, "packages": {"venv": {"environment": str(recorded)}}}
    (key / "facts.json").write_text(json.dumps(payload), encoding="utf-8")


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
    _facts(tmp_path, _NOT_INSTALLED)
    report = examine(home, home_reason="test")
    check = next(item for item in report.checks if item.id == "hermes_environment")
    assert check.status == "fail"
    assert "not in the environment" in check.summary


def test_a_missing_import_is_not_protected(tmp_path: Path) -> None:
    """A committed environment that cannot import Petasos is not protection."""
    _enabled(tmp_path)
    _facts(tmp_path, _NOT_INSTALLED)
    report = examine(tmp_path, home_reason="test")
    check = next(item for item in report.checks if item.id == "hermes_environment")
    assert check.status == "fail"
    assert report.verdict == "not_protected"
    assert "not in the environment" in check.summary
    # The stand-in really answered: the reason shown is its own, not a failure to run it.
    assert "No module named petasos" in check.meaning
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
    _facts(tmp_path, _NOT_INSTALLED)
    body = status(load_home(tmp_path))
    assert body["protection"] == "off"
    row = next(item for item in body["doctor"]["checks"] if item["id"] == "hermes_environment")
    assert row["status"] == "fail"
    assert "petasos hermes install" in row["next_step"]


def test_a_compatible_version_is_ok(tmp_path: Path) -> None:
    """Version 0.4.0 satisfies the plugin's pin, so the check passes."""
    _enabled(tmp_path)
    _facts(tmp_path, '{"ok": true, "version": "0.4.0"}')
    report = examine(tmp_path, home_reason="test")
    check = next(item for item in report.checks if item.id == "hermes_environment")
    assert check.status == "ok"
    assert "0.4.0" in check.summary


def test_an_incompatible_version_is_not_protected(tmp_path: Path) -> None:
    """A newer major version in that environment is not this plugin."""
    _enabled(tmp_path)
    _facts(tmp_path, '{"ok": true, "version": "0.5.0"}')
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
    _facts(home, json.dumps(payload))
    report = examine(home, home_reason="test")
    check = next(item for item in report.checks if item.id == "hermes_environment")
    assert check.status == ("warn" if stale else "ok")
    assert report.verdict != "not_protected"
    if stale:
        assert str(home) in check.next_step and "hermes petasos refresh" in check.next_step


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
    # A definite answer either way: "unknown" (None) is not one.
    assert Probe(ok=True, direct_url=direct).matches_wheel(source) is (not stale)


def test_a_file_address_names_the_same_path_on_this_system(tmp_path: Path) -> None:
    """A path survives the trip through a ``file:`` address, drive letter and space included."""
    wheel = tmp_path / "dir with space" / "petasos-0.4.0-py3-none-any.whl"
    assert file_url_path(wheel.as_uri()) == wheel
    assert file_url_path("https://example.invalid/petasos.whl") is None


def test_a_recorded_wheel_that_is_gone_is_unknown(tmp_path: Path) -> None:
    source = tmp_path / "source.whl"
    source.write_bytes(b"new")
    gone = tmp_path / "generation" / "petasos.whl"
    direct = json.dumps({"url": gone.as_uri(), "archive_info": {}})
    assert Probe(ok=True, direct_url=direct).matches_wheel(source) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows file addresses")
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("file:///C:/Users/x/petasos.whl", "C:/Users/x/petasos.whl"),
        ("file://localhost/C:/Users/x/petasos.whl", "C:/Users/x/petasos.whl"),
        ("file://LOCALHOST/C:/Users/x/petasos.whl", "C:/Users/x/petasos.whl"),
        ("file:///C:/dir%20with%20space/p.whl", "C:/dir with space/p.whl"),
        ("file://server/share/p.whl", "//server/share/p.whl"),
    ],
)
def test_a_windows_file_address(url: str, expected: str) -> None:
    assert file_url_path(url) == Path(expected)


@pytest.mark.skipif(os.name == "nt", reason="off Windows the path part is the path")
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("file:///tmp/p.whl", "/tmp/p.whl"),
        ("file://localhost/tmp/p.whl", "/tmp/p.whl"),
        ("file://server/share/p.whl", "/share/p.whl"),
        ("file:////localhost/tmp/x", "//localhost/tmp/x"),
        ("file:///tmp/dir%20x/p.whl", "/tmp/dir x/p.whl"),
    ],
)
def test_a_file_address_off_windows_is_its_path_part(url: str, expected: str) -> None:
    """What the code returned before it learned Windows addresses, on every Python version."""
    assert str(file_url_path(url)) == expected


def test_a_malformed_file_address_is_not_a_match(tmp_path: Path) -> None:
    source = tmp_path / "build.whl"
    source.write_bytes(b"new")
    tail = source.as_posix().split(":", 1)[-1]
    direct = json.dumps({"url": "file:abc:" + tail})
    assert Probe(ok=True, direct_url=direct).matches_wheel(source) is None
