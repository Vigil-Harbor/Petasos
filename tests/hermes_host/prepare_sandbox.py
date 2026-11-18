"""Prepare or copy a dedicated, resumable real-Hermes test sandbox.

Run with Python 3.11+ and uv on PATH. No Hermes code runs outside the wrapper.
The default destination is ~/.cache/petasos/hermes-sandbox/<name>.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import pwd
import shlex
import shutil
import stat
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

HERMES_REPO = "https://github.com/NousResearch/hermes-agent.git"
DEFAULT_TAG = "v0.23.1"
NODE_VERSION = "26.13.1"
PNPM_VERSION = "12.15.0"
PLAYWRIGHT_VERSION = "1.56.0"
MANIFEST = "sandbox-manifest.json"

WRAPPER = """#!/bin/bash
# Every command that runs Hermes code goes through this wrapper.
# HOME is this sandbox's home. HERMES_HOME is the sandbox default, or
# PETASOS_HERMES_HOME when that path resolves strictly inside the sandbox.
# Anything else is refused before the command starts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
REQUESTED="${PETASOS_HERMES_HOME:-$ROOT/hermes_home}"
RESOLVED="$(
  /usr/bin/python3 -c '
import os, pwd, sys
root = os.path.realpath(sys.argv[1])
home = os.path.realpath(sys.argv[2])
account = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
banned_names = (
    ".hermes", ".hermes-second", "hermes-services", "model-lab", "work", "notes",
)
def under(path, parent):
    return path == parent or path.startswith(parent + os.sep)
if home == root or not under(home, root):
    sys.stderr.write("refusing Hermes home outside the sandbox: %s\\n" % home)
    raise SystemExit(2)
for name in banned_names:
    banned = os.path.realpath(os.path.join(account, name))
    if under(home, banned) or under(root, banned):
        sys.stderr.write("refusing Hermes home under %s\\n" % banned)
        raise SystemExit(2)
print(home)
' "$ROOT" "$REQUESTED"
)"
while IFS='=' read -r name _; do
  case "$name" in
    HERMES_*) unset "$name" ;;
  esac
done < <(env)
export HOME="$ROOT/home"
export HERMES_HOME="$RESOLVED"
export PETASOS_SANDBOX_ROOT="$ROOT"
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
    # HOME may already be a throwaway home. Always check the password entry too.
    homes = {Path.home().resolve(), Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()}
    resolved = dest.resolve()
    for home in homes:
        for name in (
            ".hermes",
            ".hermes-second",
            "hermes-services",
            "model-lab",
            "work",
            "notes",
        ):
            banned = (home / name).resolve()
            if resolved == banned or banned in resolved.parents:
                return str(banned)
    return ""


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def _output(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_manifest(dest: Path, data: dict[str, Any]) -> None:
    temporary = dest / (MANIFEST + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(dest / MANIFEST)


def _download(url: str, path: Path, expected: str, algorithm: str = "sha256") -> None:
    def matches(candidate: Path) -> bool:
        with candidate.open("rb") as stream:
            return hashlib.file_digest(stream, algorithm).hexdigest() == expected

    if path.is_file() and matches(path):
        return
    temporary = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    if not matches(temporary):
        temporary.unlink()
        raise SystemExit(f"checksum mismatch: {url}")
    temporary.replace(path)


def _extract(archive: Path, target: Path) -> None:
    # data_filter also works on Python 3.11.8+, including our development Python.
    staging = target.with_name(target.name + ".extracting")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with tarfile.open(archive) as bundle:
        bundle.extractall(staging, filter="data")
    children = list(staging.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        raise SystemExit(f"expected one archive directory: {archive}")
    if target.exists():
        shutil.rmtree(target)
    children[0].rename(target)
    staging.rmdir()


def _toolchain(dest: Path, data: dict[str, Any]) -> None:
    system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64"}.get(platform.machine())
    if not system or not arch:
        raise SystemExit("Node sandbox supports macOS/Linux on arm64/x64")
    archive_name = f"node-v{NODE_VERSION}-{system}-{arch}.tar.gz"
    base = f"https://nodejs.org/dist/v{NODE_VERSION}"
    with urllib.request.urlopen(base + "/SHASUMS256.txt", timeout=120) as response:
        checksums = response.read()
    (dest / "downloads" / "SHASUMS256.txt").write_bytes(checksums)
    expected = next(
        line.split()[0]
        for line in checksums.decode().splitlines()
        if line.split()[1] == archive_name
    )
    archive = dest / "downloads" / archive_name
    _download(f"{base}/{archive_name}", archive, expected)
    _extract(archive, dest / "opt" / "node")
    data["node"] = {"version": NODE_VERSION, "url": f"{base}/{archive_name}", "sha256": expected}
    pin = json.loads((dest / "src" / "hermes-agent" / "pm" / "lock.json").read_text())["packages"][
        "pnpm"
    ]
    if pin["version"] != PNPM_VERSION:
        raise SystemExit("Hermes pm/lock.json does not pin the required pnpm version")
    artifacts = pin["artifacts"][f"{system}-{arch}"]
    for index, artifact in enumerate(artifacts):
        archive = dest / "downloads" / f"pnpm-{PNPM_VERSION}-{index}.tgz"
        _download(artifact["url"], archive, artifact["sha256"])
        _extract(archive, dest / "opt" / ("pnpm-native" if index == 0 else "pnpm"))
    shutil.copy2(dest / "opt" / "pnpm-native" / "pnpm", dest / "opt" / "pnpm" / "pnpm")
    (dest / "opt" / "pnpm" / "pnpm").chmod(0o755)
    data["pnpm"] = {"version": PNPM_VERSION, "artifacts": artifacts}
    for name, target in (
        ("node", "../../opt/node/bin/node"),
        ("npm", "../../opt/node/bin/npm"),
        ("npx", "../../opt/node/bin/npx"),
        ("pnpm", "../../opt/pnpm/pnpm"),
    ):
        link = dest / "venv" / "bin" / name
        link.unlink(missing_ok=True)
        link.symlink_to(target)
    _write_manifest(dest, data)


def _wrapper(dest: Path, uv: str) -> Path:
    wrapper = dest / "bin" / "with-sandbox"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(WRAPPER.replace("${UV_BIN_DIR}", str(Path(uv).parent)), encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    return wrapper


def _uv_env(dest: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        UV_PROJECT_ENVIRONMENT=str(dest / "venv"),
        UV_PYTHON_INSTALL_DIR=str(dest / "opt" / "python"),
        UV_CACHE_DIR=str(dest / "cache" / "uv"),
        UV_LINK_MODE="copy",
    )
    return env


def _confirm(dest: Path) -> None:
    confirm = (
        "import os, hermes_cli; from pathlib import Path; "
        "from hermes_constants import get_hermes_home; "
        "root = Path(os.environ['PETASOS_SANDBOX_ROOT']); "
        "assert get_hermes_home().resolve().is_relative_to(root); "
        "assert Path.home().resolve() == root / 'home'; "
        "assert Path(hermes_cli.__file__).resolve().is_relative_to(root); "
        "print(get_hermes_home())"
    )
    _run([str(dest / "bin" / "with-sandbox"), "python", "-c", confirm])
    for tool in ("node", "npm", "npx", "pnpm"):
        _run([str(dest / "bin" / "with-sandbox"), tool, "--version"])


def prepare(dest: Path, tag: str) -> None:
    dest = dest.expanduser().resolve()
    if banned := _forbidden(dest):
        raise SystemExit(f"refusing to build a sandbox under {banned}")
    manifest = dest / MANIFEST
    data: dict[str, Any] = {"tag": tag}
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data["tag"] != tag:
            raise SystemExit(f"sandbox tag is {data['tag']}, not {tag}; use a new destination")
    elif dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty and has no {MANIFEST}")
    for directory in ("home", "hermes_home", "src", "bin", "tmp", "opt", "downloads"):
        (dest / directory).mkdir(parents=True, exist_ok=True)
    _write_manifest(dest, data)
    uv = shutil_which("uv")
    wrapper = _wrapper(dest, uv)
    checkout = dest / "src" / "hermes-agent"
    if not (checkout / ".git").is_dir():
        if checkout.exists():
            # Only the manifest-owned upstream clone is rebuilt; homes are kept.
            shutil.rmtree(checkout)
        _run(["git", "clone", "--depth", "1", "--branch", tag, HERMES_REPO, str(checkout)])
    head = _output(["git", "-C", str(checkout), "rev-parse", "HEAD"])
    pinned = _output(["git", "-C", str(checkout), "rev-parse", f"{tag}^{{commit}}"])
    if head != pinned or data.get("hermes_commit", head) != head:
        raise SystemExit("Hermes checkout does not match the recorded pinned tag")
    data["hermes_commit"] = head
    _write_manifest(dest, data)
    _run(["git", "-C", str(checkout), "restore", "--source", head, "--worktree", "--", "."])
    env = _uv_env(dest)
    # Both the managed interpreter and the venv live in this directory.
    if (
        not (dest / "venv" / "bin" / "python").is_file()
        or not (dest / "venv" / "pyvenv.cfg").is_file()
    ):
        _run(
            [uv, "venv", "--clear", "--managed-python", "--python", "3.14", str(dest / "venv")],
            env=env,
        )
    _run([str(wrapper), uv, "sync", "--frozen", "--no-dev", "--reinstall"], cwd=checkout, env=env)
    _toolchain(dest, data)
    _run([str(wrapper), "pnpm", "install", "--frozen-lockfile", "--force"], cwd=checkout)
    _run([str(wrapper), "pnpm", "--dir", "web", "run", "build"], cwd=checkout)
    # The tab tests need a browser too; keep its environment and binary here.
    if (
        not (dest / "shot" / "bin" / "python").is_file()
        or not (dest / "shot" / "pyvenv.cfg").is_file()
    ):
        _run(
            [uv, "venv", "--clear", "--managed-python", "--python", "3.11", str(dest / "shot")],
            env=env,
        )
    _run(
        [
            str(wrapper),
            uv,
            "pip",
            "install",
            "--python",
            str(dest / "shot" / "bin" / "python"),
            f"playwright=={PLAYWRIGHT_VERSION}",
        ],
        env=env,
    )
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(dest / "opt" / "ms-playwright")
    _run(
        [
            str(wrapper),
            str(dest / "shot" / "bin" / "python"),
            "-m",
            "playwright",
            "install",
            "chromium-headless-shell",
        ],
        env=env,
    )
    browser_root = dest / "opt" / "ms-playwright"
    browser_hashes = {
        str(path.relative_to(browser_root)): _sha256(path)
        for path in sorted(browser_root.rglob("*"))
        if path.is_file() and os.access(path, os.X_OK)
    }
    data["playwright"] = {"version": PLAYWRIGHT_VERSION, "executables_sha256": browser_hashes}
    data["python"] = {
        "version": _output([str(wrapper), "python", "--version"]),
        "executable_sha256": _sha256(dest / "venv" / "bin" / "python"),
    }
    data["uv"] = _output([uv, "--version"])
    data["locks"] = {
        name: _sha256(checkout / name) for name in ("uv.lock", "pnpm-lock.yaml", "pm/lock.json")
    }
    _write_manifest(dest, data)
    _confirm(dest)


def copy_sandbox(source: Path, dest: Path) -> None:
    """Copy and relocate launchers, editable metadata, and internal absolute links."""
    source, dest = source.expanduser().resolve(), dest.expanduser().resolve()
    for path in (source, dest):
        if banned := _forbidden(path):
            raise SystemExit(f"refusing sandbox under {banned}")
    if not (source / MANIFEST).is_file() or not (source / "bin" / "with-sandbox").is_file():
        raise SystemExit(f"not a prepared sandbox: {source}")
    if dest.exists() or source in dest.parents or dest in source.parents:
        raise SystemExit("copy destination must be new and outside the source")
    # No shared hardlinks; never follow links back into the original.
    shutil.copytree(
        source, dest, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    old, new = os.fsencode(source), os.fsencode(dest)
    for base, directories, files in os.walk(dest, followlinks=False):
        for name in directories + files:
            path = Path(base) / name
            if path.is_symlink():
                target = os.readlink(path)
                if target == str(source) or target.startswith(str(source) + os.sep):
                    path.unlink()
                    path.symlink_to(str(dest) + target[len(str(source)) :])
            elif path.is_file():
                content = path.read_bytes()
                if old in content and b"\0" not in content:
                    relocated = content.replace(old, new)
                    first, _separator, body = relocated.partition(b"\n")
                    if first.startswith(b"#!" + new + b"/") and b"python" in first:
                        # Direct shebangs break for spaces or long destination paths.
                        interpreter = shlex.quote(os.fsdecode(first[2:]))
                        header = f"#!/bin/sh\n'''exec' {interpreter} \"$0\" \"$@\"\n' '''\n"
                        relocated = header.encode() + body
                    mode = path.stat().st_mode
                    path.chmod(mode | stat.S_IWUSR)
                    path.write_bytes(relocated)
                    path.chmod(mode)
    _wrapper(dest, shutil_which("uv"))
    _confirm(dest)


def shutil_which(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} is not on PATH")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--name", default="default", help="Name under ~/.cache/petasos/hermes-sandbox"
    )
    parser.add_argument("--dest", type=Path, help="Override the default durable sandbox directory")
    parser.add_argument("--tag", default=DEFAULT_TAG, help="Pinned Hermes tag (default v0.23.1)")
    parser.add_argument(
        "--copy-from", type=Path, help="Copy a prepared sandbox into a new destination"
    )
    args = parser.parse_args()
    if Path(args.name).name != args.name or args.name in {".", ".."}:
        parser.error("--name must be one directory name")
    dest = args.dest or Path.home() / ".cache" / "petasos" / "hermes-sandbox" / args.name
    if args.copy_from:
        copy_sandbox(args.copy_from, dest)
    else:
        prepare(dest, args.tag)
    print(dest.expanduser().resolve())


if __name__ == "__main__":
    main()
