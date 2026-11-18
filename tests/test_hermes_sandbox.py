"""Sandbox preparation safety and relocation, without importing Hermes."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pwd = pytest.importorskip("pwd", reason="Hermes sandbox wrapper requires POSIX")

from tests.hermes_host import prepare_sandbox as prep  # noqa: E402
from tests.hermes_host import sandbox_guard as guard  # noqa: E402


def test_account_destinations_are_refused_even_with_a_replaced_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = tmp_path / "account"
    monkeypatch.setattr(pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(account)))
    for name in guard._BANNED:
        dest = account / name / "nested" / "sandbox"
        with pytest.raises(SystemExit, match="refusing"):
            prep.prepare(dest, prep.DEFAULT_TAG)
        assert not dest.exists()
        monkeypatch.setenv("PETASOS_SANDBOX_ROOT", str(dest))
        with pytest.raises(SystemExit, match="refusing"):
            guard.sandbox_root()


def test_guard_resolves_an_alias_into_an_account_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = tmp_path / "account"
    account.mkdir()
    monkeypatch.setattr(pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(account)))
    alias = tmp_path / "alias"
    alias.symlink_to(account / ".hermes")
    with pytest.raises(SystemExit, match="refusing"):
        prep.prepare(alias / "sandbox", prep.DEFAULT_TAG)
    assert not (account / ".hermes").exists()


def test_wrapper_cleans_the_environment_and_refuses_escaping_homes(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    wrapper = prep._wrapper(root, sys.executable)
    env = os.environ | {"HERMES_UNSAFE": "inherited", "PYTHONPATH": "/outside"}
    selected = root / "homes" / "chosen"
    env["PETASOS_HERMES_HOME"] = str(selected)
    run = subprocess.run(
        [
            str(wrapper),
            sys.executable,
            "-c",
            "import os,json; print(json.dumps(dict(os.environ)))",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    actual = json.loads(run.stdout)
    assert actual["HOME"] == str(root / "home")
    assert actual["HERMES_HOME"] == str(selected)
    assert "HERMES_UNSAFE" not in actual
    assert "PYTHONPATH" not in actual
    escape = root / "escape"
    escape.symlink_to(tmp_path)
    for home in (root, tmp_path / "outside", escape / "outside"):
        env["PETASOS_HERMES_HOME"] = str(home)
        run = subprocess.run(
            [str(wrapper), "/usr/bin/true"], env=env, capture_output=True, text=True, check=False
        )
        assert run.returncode == 2
        assert "refusing" in run.stderr
    assert not (tmp_path / "outside").exists()


def test_download_checks_the_content_and_repairs_a_bad_cached_archive(tmp_path: Path) -> None:
    source = tmp_path / "upstream"
    source.write_bytes(b"verified archive")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    cached = tmp_path / "cached"
    cached.write_bytes(b"truncated archive")
    prep._download(source.as_uri(), cached, expected)
    assert cached.read_bytes() == source.read_bytes()
    source.write_bytes(b"tampered")
    cached.unlink()
    with pytest.raises(SystemExit, match="checksum mismatch"):
        prep._download(source.as_uri(), cached, expected)
    assert not cached.exists()


def test_copy_launchers_and_editable_imports_survive_original_renamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, dest = tmp_path / "original", tmp_path / "parallel lane"
    (source / "venv" / "bin").mkdir(parents=True)
    checkout = source / "src" / "hermes-agent"
    checkout.mkdir(parents=True)
    (checkout / "example_editable.py").write_text("VALUE = 42\n")
    prep._write_manifest(source, {"tag": prep.DEFAULT_TAG})
    prep._wrapper(source, sys.executable)
    # Model an editable .pth and a generated launcher with an absolute shebang.
    site = source / "site"
    site.mkdir()
    (site / "editable.pth").write_text(str(checkout) + "\n")
    (site / "editable.pth").chmod(0o444)
    (source / "venv" / "bin" / "python").symlink_to(sys.executable)
    launcher = source / "venv" / "bin" / "probe"
    launcher.write_text(
        f"#!{source / 'venv' / 'bin' / 'python'}\n"
        f"import site\nsite.addsitedir({str(site)!r})\n"
        "import example_editable\nprint(example_editable.VALUE)\n"
    )
    launcher.chmod(0o755)
    node = source / "opt" / "node"
    node.mkdir(parents=True)
    (node / "node").write_text("#!/bin/sh\necho sandbox-node\n")
    (node / "node").chmod(0o755)
    for name in ("node", "npm", "npx", "pnpm"):
        (source / "venv" / "bin" / name).symlink_to(node / "node")
    monkeypatch.setattr(prep, "_confirm", lambda _dest: None)
    monkeypatch.setattr(prep, "shutil_which", lambda _name: sys.executable)
    prep.copy_sandbox(source, dest)
    source.rename(tmp_path / "original-unavailable")
    result = subprocess.check_output([str(dest / "bin" / "with-sandbox"), "probe"], text=True)
    assert result.strip() == "42"
    for name in ("node", "npm", "npx", "pnpm"):
        result = subprocess.check_output([str(dest / "bin" / "with-sandbox"), name], text=True)
        assert result.strip() == "sandbox-node"
        assert (dest / "venv" / "bin" / name).resolve().is_relative_to(dest)


def test_prepare_can_resume_a_manifest_only_sandbox_and_rejects_a_different_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "sandbox"
    dest.mkdir()
    prep._write_manifest(dest, {"tag": prep.DEFAULT_TAG})
    commands: list[list[str]] = []

    def run(cmd: list[str], **_kwargs: object) -> None:
        commands.append(cmd)
        if cmd[1:2] == ["clone"]:
            checkout = Path(cmd[-1])
            checkout.mkdir()
            for name in ("uv.lock", "pnpm-lock.yaml", "pm/lock.json"):
                (checkout / name).parent.mkdir(parents=True, exist_ok=True)
                (checkout / name).write_text("lockfile")
        if "venv" in cmd:
            python = Path(cmd[-1]) / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_bytes(b"fake interpreter")

    monkeypatch.setattr(prep, "_run", run)
    monkeypatch.setattr(prep, "_output", lambda _cmd: "recorded-commit")
    monkeypatch.setattr(prep, "_toolchain", lambda _dest, _data: None)
    monkeypatch.setattr(prep, "_confirm", lambda _dest: None)
    monkeypatch.setattr(prep, "shutil_which", lambda _name: sys.executable)
    prep.prepare(dest, prep.DEFAULT_TAG)
    assert any(cmd[1:2] == ["clone"] for cmd in commands)
    assert any("build" in cmd for cmd in commands)
    assert (dest / "bin" / "with-sandbox").is_file()
    with pytest.raises(SystemExit, match="sandbox tag"):
        prep.prepare(dest, "other-tag")


def test_copy_refuses_overwrite_and_nested_destinations(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    prep._write_manifest(source, {"tag": prep.DEFAULT_TAG})
    prep._wrapper(source, sys.executable)
    for dest in (source, source / "nested", tmp_path):
        with pytest.raises(SystemExit, match="destination"):
            prep.copy_sandbox(source, dest)
