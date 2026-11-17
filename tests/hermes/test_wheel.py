"""Development wheels have immutable paths, including same-version builds."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from petasos.hermes import wheel

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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
