"""Build a Hermes sandbox for the host-fact harness.

Run with Python 3.11 or newer. The sandbox interpreter is CPython 3.14 because
Hermes v0.23.1 installs its dependencies only on 3.14.

    python tests/hermes_host/prepare_sandbox.py --dest /tmp/petasos-hermes-sandbox

The script clones upstream Hermes, creates a uv virtualenv inside ``--dest``,
and writes ``bin/with-sandbox``. It does not start a gateway, write a model
provider, or touch a Hermes home outside ``--dest``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
from pathlib import Path

HERMES_REPO = "https://github.com/NousResearch/hermes-agent.git"
DEFAULT_TAG = "v0.23.1"

WRAPPER = """#!/bin/bash
# Every command that runs Hermes code goes through this wrapper.
# HOME and HERMES_HOME are inside this sandbox and replace anything inherited.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
while IFS='=' read -r name _; do
  case "$name" in
    HERMES_*) unset "$name" ;;
  esac
done < <(env)
export HOME="$ROOT/home"
export HERMES_HOME="$ROOT/hermes_home"
export VIRTUAL_ENV="$ROOT/venv"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH || true
unset XDG_RUNTIME_DIR || true
export XDG_CONFIG_HOME="$ROOT/home/.config"
export XDG_DATA_HOME="$ROOT/home/.local/share"
export XDG_CACHE_HOME="$ROOT/home/.cache"
export XDG_STATE_HOME="$ROOT/home/.local/state"
mkdir -p "$ROOT/tmp" "$HOME" "$HERMES_HOME" "$ROOT/home/.config"
export TMPDIR="$ROOT/tmp"
export TMP="$ROOT/tmp"
export TEMP="$ROOT/tmp"
export PATH="$ROOT/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# uv is last so this venv's hermes wins over a launcher beside uv.
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:${UV_BIN_DIR}"
exec "$@"
"""


def _forbidden(dest: Path) -> str:
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
    names = (
        ".hermes",
        ".hermes-second",
        "hermes-services",
        "model-lab",
        "work",
        "notes",
    )
    resolved = dest.resolve()
    for name in names:
        banned = (home / name).resolve()
        if resolved == banned or banned in resolved.parents:
            return str(banned)
    return ""


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def prepare(dest: Path, tag: str) -> None:
    banned = _forbidden(dest)
    if banned:
        raise SystemExit(f"refusing to build a sandbox under {banned}")
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "home").mkdir()
    (dest / "hermes_home").mkdir()
    (dest / "src").mkdir()
    (dest / "bin").mkdir()
    (dest / "tmp").mkdir()
    uv = shutil_which("uv")
    uv_dir = str(Path(uv).parent)
    wrapper = dest / "bin" / "with-sandbox"
    wrapper.write_text(WRAPPER.replace("${UV_BIN_DIR}", uv_dir), encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    checkout = dest / "src" / "hermes-agent"
    _run(["git", "clone", "--depth", "1", "--branch", tag, HERMES_REPO, str(checkout)])
    _run([uv, "venv", "--python", "3.14", str(dest / "venv")])
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(dest / "venv")
    _run([uv, "sync", "--frozen", "--no-dev"], cwd=checkout, env=env)
    confirm = (
        "import os; from pathlib import Path; "
        "from hermes_constants import get_hermes_home; "
        "root = Path(os.environ['HERMES_HOME']).resolve().parent; "
        "home = get_hermes_home().resolve(); "
        "assert str(home).startswith(str(root)), home; "
        "assert Path.home().resolve().parent == root; "
        "print(home)"
    )
    _run([str(wrapper), str(dest / "venv" / "bin" / "python"), "-c", confirm])


def shutil_which(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} is not on PATH")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Hermes sandbox for tests/hermes_host")
    parser.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="Empty directory that will hold the sandbox",
    )
    parser.add_argument(
        "--tag",
        default=DEFAULT_TAG,
        help="Hermes git tag to clone (default v0.23.1)",
    )
    args = parser.parse_args()
    prepare(args.dest, args.tag)
    print(args.dest.resolve())


if __name__ == "__main__":
    main()
