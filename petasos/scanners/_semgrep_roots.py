"""Conservative recovery of private source roots after abrupt parent death."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import time
from pathlib import Path

_NAME = re.compile(r"psg-[a-z0-9_]{8}\Z")
_MARKER = "petasos-owner.json"
_MARKER_LIMIT = 16384
_REPARSE = 0x400
# Empty marker-less roots younger than this stay for a paused creator.
MARKERLESS_MIN_AGE = 600.0


def _real_directory(metadata: os.stat_result, entry: os.DirEntry[str]) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not entry.is_symlink()
        and not (getattr(metadata, "st_file_attributes", 0) & _REPARSE)
    )


def _restore_marker(root: Path, raw: bytes) -> None:
    try:
        fd, name = tempfile.mkstemp(prefix="petasos-owner-", dir=root)
        try:
            view = raw
            while view:
                written = os.write(fd, view)
                view = view[written:]
        finally:
            os.close(fd)
        os.replace(name, root / _MARKER)
    except OSError:
        return


def _take_marker(root: Path) -> bytes | None:
    """Unlink a guarded marker and return its bytes. None when it is already gone."""
    marker = root / _MARKER
    try:
        metadata = os.stat(marker, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_file_attributes", 0) & _REPARSE
        or metadata.st_size > _MARKER_LIMIT
    ):
        raise OSError("semgrep.marker_refused")
    with marker.open("rb") as stream:
        raw = stream.read(_MARKER_LIMIT + 1)
    if len(raw) > _MARKER_LIMIT:
        raise OSError("semgrep.marker_refused")
    os.unlink(marker)
    return raw


def remove_owned_root(root: Path) -> None:
    """Remove a private root, unlinking its owner marker only after the entries.

    A failure before the marker unlink leaves the marker in place. A failure of
    the final rmdir restores the original marker bytes. A missing marker does
    not block rmdir, so a crash between unlink and rmdir can still be retried.
    """
    marker_bytes: bytes | None = None
    try:
        # scandir follows a root replaced by a symlink or junction; refuse it so
        # removal never traverses or deletes anything outside the owned root.
        metadata = os.stat(root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & _REPARSE
        ):
            raise OSError("semgrep.root_not_owned")
        pending: list[tuple[str, bool]] = []
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.name == _MARKER:
                    continue
                metadata = entry.stat(follow_symlinks=False)
                pending.append((entry.path, _real_directory(metadata, entry)))
        for path, real_dir in pending:
            if real_dir:
                shutil.rmtree(path)
            else:
                os.unlink(path)
        marker_bytes = _take_marker(root)
        os.rmdir(root)
    except OSError:
        if marker_bytes is not None and root.exists():
            _restore_marker(root, marker_bytes)
        raise


def recover_roots() -> int:
    """Remove only marked roots whose recorded owner and children are gone.

    Never signal a PID. A live reused PID is also left alone. Unknown, malformed,
    inaccessible and reparse-point roots are left for operator inspection.
    The walk and metadata reads are bounded and never inspect submitted source.
    """
    import psutil

    removed = 0
    checked = 0
    parent = Path(tempfile.gettempdir()).resolve()
    with os.scandir(parent) as entries:
        for entry in entries:
            if not _NAME.fullmatch(entry.name):
                continue
            checked += 1
            if checked > 64:
                break
            try:
                metadata = entry.stat(follow_symlinks=False)
                if not stat.S_ISDIR(metadata.st_mode) or entry.is_symlink():
                    continue
                if getattr(metadata, "st_file_attributes", 0) & 0x400:
                    continue
                root = parent / entry.name
                marker = root / _MARKER
                try:
                    if marker.is_symlink() or marker.stat().st_size > _MARKER_LIMIT:
                        continue
                except FileNotFoundError:
                    age = time.time() - entry.stat().st_mtime
                    if age >= MARKERLESS_MIN_AGE and not any(root.iterdir()):
                        os.rmdir(root)
                        removed += 1
                    continue
                with marker.open("rb") as stream:
                    raw = stream.read(16385)
                if len(raw) > 16384:
                    continue
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get("schema") != 1:
                    continue
                children = data.get("children")
                if not isinstance(children, list) or len(children) > 4:
                    continue
                identities = [data, *children]
                verified = True
                for identity in identities:
                    pid, born = identity.get("pid"), identity.get("born")
                    if (
                        type(pid) is not int
                        or pid <= 0
                        or type(born) not in (int, float)
                        or born <= 0
                    ):
                        verified = False
                        break
                    # No process is stronger evidence than a creation-time
                    # mismatch. Leave even a reused live PID's root untouched.
                    if psutil.pid_exists(pid):
                        verified = False
                        break
                if verified:
                    remove_owned_root(root)
                    removed += 1
            # OverflowError: a recorded PID too large for the OS process APIs.
            except (OSError, ValueError, TypeError, AttributeError, OverflowError):
                continue
    return removed
