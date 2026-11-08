"""Conservative recovery of private source roots after abrupt parent death."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

_NAME = re.compile(r"psg-[a-z0-9_]{8}\Z")


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
                marker = root / "petasos-owner.json"
                if marker.is_symlink() or marker.stat().st_size > 16384:
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
                    shutil.rmtree(root)
                    removed += 1
            # OverflowError: a recorded PID too large for the OS process APIs.
            except (OSError, ValueError, TypeError, AttributeError, OverflowError):
                continue
    return removed
