"""CI-only isolated installation; never imported by the shipped adapter."""

import hashlib
import json
import os
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path


def main() -> None:
    expected = sys.argv[1]
    actual = platform.machine().lower()
    if actual not in ({"amd64", "x86_64"} if expected == "x64" else {"arm64"}):
        raise SystemExit("Native runner architecture does not match the qualification lane")
    root = Path(os.environ["RUNNER_TEMP"]) / "petasos-semgrep-engine"
    subprocess.run([sys.executable, "-m", "venv", str(root)], check=True)
    executable = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    pins = json.loads(Path(__file__).with_name("semgrep_engine_pins.json").read_text())
    identity = pins["platforms"]["windows_x64" if os.name == "nt" else "macos_arm64"]
    artifact = root / identity["filename"]
    urllib.request.urlretrieve(identity["url"], artifact)
    with artifact.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != identity["wheel_sha256"]:
            raise SystemExit("Pinned Semgrep wheel integrity mismatch")
    subprocess.run(
        [str(executable), "-m", "pip", "install", "--no-deps", str(artifact)], check=True
    )
    # Ask the isolated interpreter for its own package location, not Petasos'.
    location = subprocess.check_output(
        [
            str(executable),
            "-c",
            "import pathlib,semgrep;print(pathlib.Path(semgrep.__file__).parent/'bin')",
        ],
        text=True,
    ).strip()
    engine = Path(location) / ("semgrep-core.exe" if os.name == "nt" else "semgrep-core")
    with engine.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != identity["engine_sha256"]:
        raise SystemExit("Pinned Semgrep engine integrity mismatch")
    home = Path(os.environ["RUNNER_TEMP"]) / "petasos-semgrep-hermes-home"
    home.mkdir(exist_ok=True)
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
        output.write(
            f"SEMGREP_ENGINE_PATH={engine}\nSEMGREP_ENGINE_SHA256={digest}\nHERMES_HOME={home}\n"
        )


if __name__ == "__main__":
    main()
