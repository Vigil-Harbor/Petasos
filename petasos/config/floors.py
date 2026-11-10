"""Floors and vocabularies the config tree enforces on its own.

The scanners and the guard own the live copies of these facts. The values
here are the config layer's statement of them; tests tie the two together.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from petasos._types import Severity

# Hard minimum for the tier that terminates a session.
TIER3_FLOOR: Final[float] = 30.0

# PromptGuard 2 blocks at this score. The scanner reads the same cut.
PROMPT_GUARD_THRESHOLD: Final[float] = 0.9

# Presidio's constructor defaults. ``None`` entities means the curated set.
PRESIDIO_SCORE_THRESHOLD: Final[float] = 0.35
PRESIDIO_LANGUAGE: Final[str] = "en"

# Rule-id prefixes. A test shows each one selects exactly the scanner's set.
STRUCTURAL_PREFIX: Final[str] = "petasos.syntactic.structural."
INJECTION_PREFIX: Final[str] = "petasos.syntactic.injection."
SELFMOD_PREFIX: Final[str] = "petasos.selfmod."

# Base severity of each self-modification rule the guard or the console emits.
# An override below this rank is a downgrade and is rejected. An id that is
# not listed has no recorded base, so it cannot be retargeted at all.
SELFMOD_BASE_SEVERITY: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        "petasos.selfmod.config_write": "critical",
        "petasos.selfmod.config_ref": "high",
        "petasos.selfmod.console_probe": "critical",
    }
)

# Presidio recognizer names this package will accept. URL is opt-in only.
KNOWN_PII_ENTITIES: Final[frozenset[str]] = frozenset(
    {
        "CREDIT_CARD",
        "IBAN_CODE",
        "US_SSN",
        "US_BANK_NUMBER",
        "CRYPTO",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_DRIVER_LICENSE",
        "US_PASSPORT",
        "IP_ADDRESS",
        "PERSON",
        "LOCATION",
        "DATE_TIME",
        "NRP",
        "URL",
    }
)

SEVERITY_NAMES: Final[tuple[str, ...]] = tuple(member.value for member in Severity)
