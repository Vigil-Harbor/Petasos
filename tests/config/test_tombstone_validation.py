"""Pin positive, bounded termination-tombstone configuration."""

from __future__ import annotations

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig


class TestConfigMaxTerminatedTombstonesValidation:
    def test_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="sessions.max_tombstones"):
            from_mapping(
                PetasosConfig,
                {
                    "sessions": {
                        "max_tombstones": 0,
                    },
                },
            )

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="sessions.max_tombstones"):
            from_mapping(
                PetasosConfig,
                {
                    "sessions": {
                        "max_tombstones": -1,
                    },
                },
            )

    def test_bool_raises(self) -> None:
        with pytest.raises(ValueError, match="sessions.max_tombstones"):
            from_mapping(
                PetasosConfig,
                {
                    "sessions": {
                        "max_tombstones": True,
                    },
                },
            )

    def test_string_raises(self) -> None:
        with pytest.raises(
            (ValueError, TypeError),
        ):
            from_mapping(
                PetasosConfig,
                {
                    "sessions": {
                        "max_tombstones": "foo",
                    },
                },
            )

    def test_valid_positive_integer(self) -> None:
        cfg = from_mapping(
            PetasosConfig,
            {
                "sessions": {
                    "max_tombstones": 500,
                },
            },
        )
        assert cfg.sessions.max_tombstones == 500
