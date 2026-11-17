"""Produce the Petasos wheel Hermes's package manager can install.

The public package index may already have this version number for a different
build. A development install therefore hands Hermes a file, not a name to
look up.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import petasos

_WHEEL_NAME = f"petasos-{petasos.__version__}-py3-none-any.whl"


def wheel_filename() -> str:
    """The file name of a wheel built from this version."""
    return _WHEEL_NAME


def place_wheel(directory: Path) -> tuple[Path | None, str]:
    """Put this Petasos's wheel in ``directory`` and return its path.

    The second value is a sentence when no wheel could be produced. ``directory``
    is created when a wheel is written. An existing file with the same bytes is
    left in place.
    """
    source = _existing_wheel()
    if source is not None:
        return _copy(source, directory), ""
    root = _source_root()
    if root is not None:
        built, problem = _build(root)
        if built is not None:
            placed = _copy(built, directory)
            shutil.rmtree(built.parent, ignore_errors=True)
            return placed, ""
        return None, problem
    with tempfile.TemporaryDirectory(prefix="petasos-wheel-") as staging:
        packed = Path(staging) / wheel_filename()
        if _pack_installed(packed):
            return _copy(packed, directory), ""
    return None, (
        "This command could not find a wheel of this Petasos to give to Hermes. "
        "Install Petasos from a checkout, then run it again."
    )


def _copy(source: Path, directory: Path) -> Path:
    data = source.read_bytes()
    target = directory / hashlib.sha256(data).hexdigest()[:16] / wheel_filename()
    if target.is_file():
        try:
            if target.read_bytes() == data:
                return target
        except OSError:
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def wheel_source(project: Path) -> Path | None:
    """The local Petasos wheel named by a plugin's uv source, when present."""
    try:
        document = tomllib.loads(project.read_text(encoding="utf-8"))
        source = document["tool"]["uv"]["sources"]["petasos"]["path"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(source, str) or not source.endswith(".whl"):
        return None
    return project.parent / source


def prune_wheels(current: Path) -> None:
    """Remove older Petasos wheels only after Hermes accepted the current build."""
    directory = current.parent.parent
    for old in directory.glob("*/petasos-*.whl"):
        if old != current:
            old.unlink()
            if not any(old.parent.iterdir()):
                old.parent.rmdir()
    for old in directory.glob("petasos-*.whl"):
        old.unlink()


def _existing_wheel() -> Path | None:
    """A wheel file this install was taken from, when that file is still there."""
    try:
        raw = importlib.metadata.distribution("petasos").read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    url = payload.get("url") if isinstance(payload, dict) else None
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    path = Path(unquote(parsed.path))
    if path.is_file() and path.suffix == ".whl":
        return path
    return None


def _source_root() -> Path | None:
    """The checkout this process was installed from, when it is an editable install."""
    try:
        raw = importlib.metadata.distribution("petasos").read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        raw = None
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            info = payload.get("dir_info")
            url = payload.get("url")
            editable = isinstance(info, dict) and info.get("editable") is True
            if editable and isinstance(url, str):
                parsed = urlparse(url)
                if parsed.scheme == "file":
                    root = Path(unquote(parsed.path))
                    if (root / "pyproject.toml").is_file():
                        return root
    here = Path(petasos.__file__).resolve().parent
    for parent in (here.parent, *here.parents):
        project = parent / "pyproject.toml"
        if not project.is_file():
            continue
        try:
            document = tomllib.loads(project.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        project_table = document.get("project")
        name = project_table.get("name") if isinstance(project_table, dict) else None
        if name == "petasos":
            return parent
    return None


def _build(root: Path) -> tuple[Path | None, str]:
    uv = shutil.which("uv")
    if uv is None:
        return None, (
            "The uv build tool is not on PATH, so this command could not build a wheel. "
            "Install uv, then run petasos hermes install again."
        )
    staging = Path(tempfile.mkdtemp(prefix="petasos-wheel-"))
    try:
        completed = subprocess.run(
            [uv, "build", "--wheel", "--out-dir", str(staging), str(root)],
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return None, f"The wheel build did not finish: {exc}"
    if completed.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        tail = detail[-1] if detail else "uv build failed"
        return None, f"The wheel build failed: {tail}"
    wheels = sorted(staging.glob("petasos-*.whl"))
    if not wheels:
        shutil.rmtree(staging, ignore_errors=True)
        return None, "The wheel build finished without producing a wheel."
    return wheels[-1], ""


def _pack_installed(target: Path) -> bool:
    """Zip the installed files when no checkout and no original wheel remain."""
    try:
        dist = importlib.metadata.distribution("petasos")
    except importlib.metadata.PackageNotFoundError:
        return False
    files = dist.files
    if not files:
        return False
    rows: list[str] = []
    payload: list[tuple[str, bytes]] = []
    for entry in files:
        name = entry.as_posix()
        if name.endswith(".dist-info/RECORD"):
            continue
        source = Path(str(dist.locate_file(entry)))
        if not source.is_file():
            continue
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        payload.append((name, data))
        rows.append(f"{name},sha256={digest},{len(data)}")
    if not payload:
        return False
    info = next((name.split("/", 1)[0] for name, _ in payload if ".dist-info/" in name), "")
    if info == "":
        return False
    record_name = f"{info}/RECORD"
    record = "".join(row + "\n" for row in rows) + f"{record_name},,\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as archive:
        for name, data in payload:
            archive.writestr(zipfile.ZipInfo(name), data)
        archive.writestr(zipfile.ZipInfo(record_name), record)
    return True
