"""Regenerate the checked-in reference and compare every output byte."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_reference_regenerates_without_a_diff(tmp_path: Path) -> None:
    output = tmp_path / "reference"
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.generate_reference", "--output", str(output)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    committed = ROOT / "docs" / "reference"
    assert sorted(p.name for p in output.iterdir()) == sorted(p.name for p in committed.iterdir())
    for generated in output.iterdir():
        assert generated.read_bytes() == (committed / generated.name).read_bytes(), (
            f"Regenerate {generated.name}: python -m scripts.generate_reference"
        )
