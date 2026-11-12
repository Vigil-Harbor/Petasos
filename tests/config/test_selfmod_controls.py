"""The public configuration catalogue exposes no self-modification disable knob."""

from __future__ import annotations

from petasos.config.schema import describe
from petasos.config.sections import PetasosConfig


def test_schema_exposes_no_selfmod_disable_control() -> None:
    rows = describe(PetasosConfig)
    assert rows
    assert all("selfmod" not in row.path.lower() for row in rows)
