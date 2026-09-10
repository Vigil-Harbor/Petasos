"""Assert PET-183's exact console JavaScript set in a wheel and source archive."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

EXPECTED = {
    "petasos-core.js",
    "petasos-transport.js",
    "petasos-observability.js",
    "petasos-dashboard.js",
    "petasos-playground.js",
    "petasos-config.js",
    "petasos-shell.js",
}


def _static_scripts(names: list[str], *, strip_top: bool) -> set[str]:
    scripts: set[str] = set()
    for raw_name in names:
        name = raw_name.replace("\\", "/")
        if strip_top and "/" in name:
            name = name.split("/", 1)[1]
        path = PurePosixPath(name)
        if path.parent == PurePosixPath("petasos/console/static") and path.suffix == ".js":
            scripts.add(path.name)
    return scripts


def _check(label: str, actual: set[str]) -> None:
    if actual != EXPECTED:
        missing = sorted(EXPECTED - actual)
        extra = sorted(actual - EXPECTED)
        raise SystemExit(f"{label}: console scripts differ; missing={missing}, extra={extra}")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit("usage: assert_console_artifacts.py WHEEL SDIST")
    wheel = Path(argv[1])
    sdist = Path(argv[2])
    with zipfile.ZipFile(wheel) as archive:
        _check("wheel", _static_scripts(archive.namelist(), strip_top=False))
    with tarfile.open(sdist, "r:gz") as archive:
        _check("sdist", _static_scripts(archive.getnames(), strip_top=True))
    print("console artifacts: exact seven-script set present in wheel and sdist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
