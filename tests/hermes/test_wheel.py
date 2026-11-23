"""Development wheels have immutable paths, including same-version builds."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from petasos.hermes import wheel


def test_content_addressed_wheels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / wheel.wheel_filename()
    source.write_bytes(b"first build")
    monkeypatch.setattr(wheel, "_existing_wheel", lambda: source)
    directory = tmp_path / "wheels"
    first, problem = wheel.place_wheel(directory)
    assert not problem
    assert first == directory / hashlib.sha256(b"first build").hexdigest()[:16] / source.name
    stamp = first.stat().st_mtime_ns
    again, problem = wheel.place_wheel(directory)
    assert again == first and not problem
    assert first.stat().st_mtime_ns == stamp
    source.write_bytes(b"second build")
    second, problem = wheel.place_wheel(directory)
    assert second is not None and second != first and not problem
    assert first.read_bytes() == b"first build"
    assert second.read_bytes() == b"second build"


def test_repacked_wheel_is_repeatable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The installed-files fallback also produces stable bytes and paths."""
    monkeypatch.setattr(wheel, "_existing_wheel", lambda: None)
    monkeypatch.setattr(wheel, "_source_root", lambda: None)
    first, problem = wheel.place_wheel(tmp_path)
    assert first is not None and not problem
    stamp = first.stat().st_mtime_ns
    again, problem = wheel.place_wheel(tmp_path)
    assert again == first and not problem
    assert first.stat().st_mtime_ns == stamp


def test_pruning_skips_a_wheel_it_cannot_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = tmp_path / "wheels" / "aaaa" / "petasos-0.4.0-py3-none-any.whl"
    old = tmp_path / "wheels" / "bbbb" / "petasos-0.4.0-py3-none-any.whl"
    for path in (current, old):
        path.parent.mkdir(parents=True)
        path.write_bytes(path.parent.name.encode())
    real_unlink = Path.unlink

    def refuse(self: Path, missing_ok: bool = False) -> None:
        if self == old:
            raise PermissionError(self)
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", refuse)
    wheel.prune_wheels(current, plugin_dir=tmp_path)
    assert current.is_file()
    assert old.is_file()


def test_pruning_keeps_the_declared_flat_wheel(tmp_path: Path) -> None:
    directory = tmp_path / "wheels"
    directory.mkdir()
    current = directory / wheel.wheel_filename()
    current.write_bytes(b"current")
    old = directory / "old" / wheel.wheel_filename()
    old.parent.mkdir()
    old.write_bytes(b"old")
    wheel.prune_wheels(current, plugin_dir=tmp_path)
    assert current.read_bytes() == b"current"
    assert not old.exists()


def test_pruning_does_not_follow_symlinks_outside_the_plugin(tmp_path: Path) -> None:
    directory = tmp_path / "plugin" / "wheels"
    current = directory / "current" / wheel.wheel_filename()
    current.parent.mkdir(parents=True)
    current.write_bytes(b"current")
    shared = tmp_path / "shared"
    shared.mkdir()
    other = shared / wheel.wheel_filename()
    other.write_bytes(b"other")
    try:
        (directory / "linked").symlink_to(shared, target_is_directory=True)
    except OSError:
        pytest.skip("symlink not permitted")
    wheel.prune_wheels(current, plugin_dir=directory.parent)
    assert other.read_bytes() == b"other"
    assert current.read_bytes() == b"current"
    # The wheel directory itself may also have been redirected.
    external_plugin = tmp_path / "external-plugin"
    external_plugin.mkdir()
    (external_plugin / "wheels").symlink_to(directory, target_is_directory=True)
    wheel.prune_wheels(current, plugin_dir=external_plugin)
    assert other.read_bytes() == b"other"
