"""Refuse to run Hermes against a home outside the sandbox.

The wrappers and the in-process harnesses both call this. A test may choose
a Hermes home, and that home has to resolve underneath the sandbox root.
"""

from __future__ import annotations

import os
import pwd
from pathlib import Path

_BANNED = (
    ".hermes",
    ".hermes-second",
    "hermes-services",
    "model-lab",
    "work",
    "notes",
)


def _account_home() -> Path:
    """The account's home directory, not ``HOME``, which the wrapper replaces."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def require_inside_sandbox(path: Path, *, label: str) -> Path:
    """Return ``path`` resolved, or exit when it is not inside the sandbox."""
    root = sandbox_root()
    resolved = path.resolve()
    if not _inside(resolved, root) or resolved == root:
        raise SystemExit(f"refusing {label} outside the sandbox: {resolved}")
    account = _account_home()
    for name in _BANNED:
        banned = (account / name).resolve()
        if _inside(resolved, banned):
            raise SystemExit(f"refusing {label} under {banned}")
    return resolved


def sandbox_root() -> Path:
    """The sandbox directory the wrapper exported, or exit."""
    raw = os.environ.get("PETASOS_SANDBOX_ROOT", "")
    if not raw:
        raise SystemExit("PETASOS_SANDBOX_ROOT is not set; run through bin/with-sandbox")
    root = Path(raw).resolve()
    account = _account_home()
    for name in _BANNED:
        banned = (account / name).resolve()
        if _inside(root, banned):
            raise SystemExit(f"refusing to run a sandbox under {banned}")
    if not (root / "bin" / "with-sandbox").is_file():
        raise SystemExit(f"PETASOS_SANDBOX_ROOT is not a sandbox: {root}")
    user_home = Path.home().resolve()
    if "HERMES_HOME" not in os.environ:
        raise SystemExit("HERMES_HOME is not set; run through bin/with-sandbox")
    hermes_home = Path(os.environ["HERMES_HOME"]).resolve()
    if not _inside(user_home, root) or user_home == root:
        raise SystemExit(f"refusing HOME outside the sandbox: {user_home}")
    if not _inside(hermes_home, root) or hermes_home == root:
        raise SystemExit(f"refusing HERMES_HOME outside the sandbox: {hermes_home}")
    return root


def hermes_home() -> Path:
    """The Hermes home for this process. It is inside the sandbox."""
    sandbox_root()
    return Path(os.environ["HERMES_HOME"]).resolve()
