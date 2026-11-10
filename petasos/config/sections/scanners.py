"""Per-scanner settings. Everything in the three scanner sections needs a restart."""

from __future__ import annotations

import os
import re
from typing import Literal

from petasos.config.floors import (
    KNOWN_PII_ENTITIES,
    PRESIDIO_LANGUAGE,
    PRESIDIO_SCORE_THRESHOLD,
    PROMPT_GUARD_THRESHOLD,
)
from petasos.config.schema import ConfigError, section, setting

_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_ENABLED = Literal["auto", "on", "off"]
_KNOWN_PII = ", ".join(sorted(KNOWN_PII_ENTITIES))


def _unknown_entity(name: str) -> str:
    return f'"{name}" is not a known personal-information type. Known names: {_KNOWN_PII}.'


@section
class PromptGuardConfig:
    """Whether PromptGuard runs, and the score at which it reports injection."""

    enabled: _ENABLED = setting(
        default="auto",
        restart=True,
        help="Use PromptGuard when it is installed, always, or never.",
    )
    threshold: float = setting(
        default=PROMPT_GUARD_THRESHOLD,
        ge=0,
        le=1,
        restart=True,
        help="How high PromptGuard's injection score must be before it reports a finding.",
    )


@section
class PresidioConfig:
    """Whether Presidio runs, which types it looks for, and how sure it must be."""

    enabled: _ENABLED = setting(
        default="auto",
        restart=True,
        help="Use Presidio when it is installed, always, or never.",
    )
    entities: tuple[str, ...] | None = setting(
        default=None,
        normalize=str.upper,
        restart=True,
        help=(
            "Replace Presidio's detected types wholesale, or leave unset to keep "
            "the curated set of cards, ids, emails, and phone numbers."
        ),
    )
    entities_extra: tuple[str, ...] = setting(
        default=(),
        normalize=str.upper,
        restart=True,
        help="Add personal-information types, such as URL or PERSON, on top of the detected set.",
    )
    score_threshold: float = setting(
        default=PRESIDIO_SCORE_THRESHOLD,
        ge=0,
        le=1,
        restart=True,
        help="How sure Presidio must be, from 0 to 1, before it reports a match.",
    )
    language: str = setting(
        default=PRESIDIO_LANGUAGE,
        restart=True,
        help="The language Presidio uses when it looks for personal information, usually en.",
    )

    def check(self) -> None:
        problems: list[tuple[str, str]] = []
        if self.language.strip() == "":
            problems.append(("language", "must name a language, such as en"))
        if self.entities is not None:
            if len(self.entities) == 0:
                problems.append(
                    (
                        "entities",
                        "must list at least one type; leave it unset to use the curated default",
                    )
                )
            for index, name in enumerate(self.entities):
                if name not in KNOWN_PII_ENTITIES:
                    problems.append((f"entities[{index}]", _unknown_entity(name)))
        for index, name in enumerate(self.entities_extra):
            if name not in KNOWN_PII_ENTITIES:
                problems.append((f"entities_extra[{index}]", _unknown_entity(name)))
        if problems:
            raise ConfigError(problems)


@section
class SemgrepConfig:
    """Whether the isolated Semgrep engine runs, and where that engine lives."""

    enabled: _ENABLED = setting(
        default="off",
        restart=True,
        help="Run the isolated Semgrep engine, or leave it off until an engine is configured.",
    )
    engine_path: str | None = setting(
        default=None,
        restart=True,
        help="Absolute path to the pinned semgrep-core executable this process owns.",
    )
    engine_sha256: str | None = setting(
        default=None,
        restart=True,
        help="SHA-256 digest of that executable, so a swapped binary is refused.",
    )
    request_timeout_seconds: float = setting(
        default=8.0,
        ge=1,
        le=8,
        restart=True,
        help="How many seconds one Semgrep scan may wait, including time spent queued.",
    )
    max_source_bytes: int = setting(
        default=65536,
        ge=4096,
        le=65536,
        restart=True,
        help="The most decoded source bytes one Semgrep scan will accept.",
    )

    def check(self) -> None:
        problems: list[tuple[str, str]] = []
        if self.engine_path is not None and not os.path.isabs(self.engine_path):
            problems.append(("engine_path", "must be an absolute path"))
        if self.engine_sha256 is not None and _SHA256.fullmatch(self.engine_sha256) is None:
            problems.append(
                ("engine_sha256", "must be a SHA-256 digest, 64 hexadecimal characters")
            )
        if problems:
            raise ConfigError(problems)


@section
class ScannersConfig:
    """How long a scanner may run, plus the settings for each optional scanner."""

    timeout_seconds: float = setting(
        default=10.0,
        gt=0,
        le=60,
        help="How many seconds to wait for a slow scanner before giving up on that scan.",
    )
    breaker_threshold: int = setting(
        default=3,
        gt=0,
        audience="expert",
        help="How many timeouts in a row bench a scanner so it stops slowing every scan.",
    )
    breaker_cooldown_seconds: float = setting(
        default=30.0,
        gt=0,
        audience="expert",
        help="How many seconds a benched scanner sits out before it is tried again.",
    )
    prompt_guard: PromptGuardConfig = setting(
        default=PromptGuardConfig(),
        help="PromptGuard arming and the score that counts as injection.",
    )
    presidio: PresidioConfig = setting(
        default=PresidioConfig(),
        help="Presidio arming, the types it detects, and how sure a match must be.",
    )
    semgrep: SemgrepConfig = setting(
        default=SemgrepConfig(),
        help="Semgrep arming and the pinned engine it is allowed to run.",
    )
