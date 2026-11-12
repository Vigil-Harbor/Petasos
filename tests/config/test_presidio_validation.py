"""Pin nonempty curated entity selections and valid Presidio thresholds.

See docs/architecture/rationale.md, "Test timing and backend qualification"."""

from __future__ import annotations

import math

import pytest

from petasos.config.schema import from_mapping, to_mapping
from petasos.config.sections import PetasosConfig


def test_config_round_trips_presidio_fields() -> None:
    """Pin config round trips presidio fields."""
    cfg = from_mapping(
        PetasosConfig,
        {
            "scanners": {
                "presidio": {
                    "entities": ("EMAIL_ADDRESS", "US_SSN"),
                    "entities_extra": ("URL",),
                    "score_threshold": 0.5,
                },
            },
        },
    )
    rt = from_mapping(PetasosConfig, to_mapping(cfg))
    assert rt.scanners.presidio.entities == ("EMAIL_ADDRESS", "US_SSN")
    assert rt.scanners.presidio.entities_extra == ("URL",)
    assert rt.scanners.presidio.score_threshold == 0.5

    base = PetasosConfig()
    assert base.scanners.presidio.entities is None
    rt_none = from_mapping(PetasosConfig, to_mapping(base))
    assert rt_none.scanners.presidio.entities is None

    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "scanners": {
                    "presidio": {
                        "score_threshold": 1.5,
                    },
                },
            },
        )
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "scanners": {
                    "presidio": {
                        "score_threshold": math.nan,
                    },
                },
            },
        )
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "scanners": {
                    "presidio": {
                        "entities": (),
                    },
                },
            },
        )
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "scanners": {
                    "presidio": {
                        "entities": "EMAIL_ADDRESS",
                    },
                },
            },
        )
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "scanners": {
                    "presidio": {
                        "entities": ("",),
                    },
                },
            },
        )
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "scanners": {
                    "presidio": {
                        "entities_extra": "URL",
                    },
                },
            },
        )


def test_presidio_entities_casing_normalized() -> None:
    # Recognizer names are trimmed and case-normalized to prevent silent scope mismatches.
    """Pin presidio entities casing normalized."""
    cfg = from_mapping(
        PetasosConfig,
        {
            "scanners": {
                "presidio": {
                    "entities": (" person ", "url"),
                    "entities_extra": ("ip_address ",),
                },
            },
            "anonymization": {
                "entities": (" EMAIL_ADDRESS ",),
            },
        },
    )
    assert cfg.scanners.presidio.entities == ("PERSON", "URL")
    assert cfg.scanners.presidio.entities_extra == ("IP_ADDRESS",)
    assert cfg.anonymization.entities == ("EMAIL_ADDRESS",)


def test_whitespace_only_entity_entries_rejected() -> None:
    # Whitespace-only entity names would silently disable detection without validation.
    """Pin whitespace only entity entries rejected."""
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "scanners": {
                    "presidio": {
                        "entities": ("   ",),
                    },
                },
            },
        )
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "scanners": {
                    "presidio": {
                        "entities_extra": ("\t",),
                    },
                },
            },
        )
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "anonymization": {
                    "entities": ("  ",),
                },
            },
        )
