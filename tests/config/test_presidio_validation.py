"""PET-109: Presidio entity scoping — default-set, config round-trip/apply, and
real-backend regression (benign technical corpus + real-PII preservation).

The backend-free rows are module-level functions. The two `@requires_presidio`
rows live in class ``TestPresidioTightenedDefault`` — the ``target_class`` the
conftest non-skipping-lane guard pins for ``extras-presidio`` (D4).
"""

from __future__ import annotations

import math

import pytest

from petasos.config.schema import from_mapping, to_mapping
from petasos.config.sections import PetasosConfig


def test_config_round_trips_presidio_fields() -> None:
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

    # None -> to_dict -> from_dict -> None (no existing precedent; assert explicitly)
    base = PetasosConfig()
    assert base.scanners.presidio.entities is None
    rt_none = from_mapping(PetasosConfig, to_mapping(base))
    assert rt_none.scanners.presidio.entities is None

    # invalid threshold
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
    # empty explicit presidio_entities is meaningless
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
    # bare-string / empty-string entries
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
    # case-folded AND surrounding whitespace trimmed (a " URL " entry would otherwise
    # be a silent no-op — it matches no recognizer in analyzer.analyze).
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
    assert cfg.anonymization.entities == (
        "EMAIL_ADDRESS",
    )  # trimmed (D7 filter uppercases at read)


def test_whitespace_only_entity_entries_rejected() -> None:
    # whitespace-only entries are non-empty but normalize to nothing — reject them
    # rather than let them silently disable a security-sensitive detector/filter.
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
