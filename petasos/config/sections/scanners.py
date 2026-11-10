"""Per-scanner settings.

The three scanner sections need a restart, except the extra Presidio types.
A scan reads that list itself, so a change applies without a restart.
"""

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
        label="Use PromptGuard",
        help=(
            "PromptGuard is an optional model that catches reworded hidden "
            "instructions the basic checks miss."
        ),
        choice_labels={
            "auto": "Use it when it is installed",
            "on": "Always (report a problem if it is missing)",
            "off": "Never",
        },
    )
    threshold: float = setting(
        default=PROMPT_GUARD_THRESHOLD,
        ge=0,
        le=1,
        restart=True,
        label="PromptGuard sensitivity",
        help=(
            "How sure PromptGuard must be, from 0 to 1, before it reports hidden "
            "instructions. Lower catches more and interrupts more."
        ),
    )


@section
class PresidioConfig:
    """Whether Presidio runs, which types it looks for, and how sure it must be."""

    enabled: _ENABLED = setting(
        default="auto",
        restart=True,
        label="Use Presidio",
        help=(
            "Presidio is an optional check that finds personal details such as names, "
            "emails, phone numbers and card numbers."
        ),
        choice_labels={
            "auto": "Use it when it is installed",
            "on": "Always (report a problem if it is missing)",
            "off": "Never",
        },
    )
    entities: tuple[str, ...] | None = setting(
        default=None,
        normalize=str.upper,
        restart=True,
        label="Kinds of personal detail (replace)",
        help=(
            "Replace the kinds Presidio looks for, one per line, such as CREDIT_CARD. "
            "Leave empty to keep the usual set: cards, ids, emails and phone numbers."
        ),
    )
    entities_extra: tuple[str, ...] = setting(
        default=(),
        normalize=str.upper,
        label="Extra kinds of personal detail",
        help="More kinds to look for on top of the usual set, one per line, such as PERSON.",
    )
    score_threshold: float = setting(
        default=PRESIDIO_SCORE_THRESHOLD,
        ge=0,
        le=1,
        restart=True,
        label="Presidio sensitivity",
        help=(
            "How sure Presidio must be, from 0 to 1, before it reports a detail. "
            "Lower finds more and is wrong more often."
        ),
    )
    language: str = setting(
        default=PRESIDIO_LANGUAGE,
        restart=True,
        label="Language",
        help="The language of the text Presidio reads, as a short code such as en.",
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
        label="Use Semgrep",
        help=(
            "Semgrep is an optional code checker that looks for risky code the agent "
            "writes. It needs a separately installed engine, set below."
        ),
        choice_labels={
            "auto": "Use it when it is installed",
            "on": "Always (report a problem if it is missing)",
            "off": "Never",
        },
    )
    engine_path: str | None = setting(
        default=None,
        restart=True,
        label="Engine location",
        help="The full path to the semgrep-core program Petasos is allowed to run.",
    )
    engine_sha256: str | None = setting(
        default=None,
        restart=True,
        label="Engine fingerprint",
        help=(
            "The SHA-256 fingerprint of that program, so a replaced program is refused. "
            "64 hexadecimal characters."
        ),
    )
    request_timeout_seconds: float = setting(
        default=8.0,
        ge=1,
        le=8,
        restart=True,
        label="Time limit per check (seconds)",
        help="How long one Semgrep check may take, including time spent waiting its turn.",
    )
    max_source_bytes: int = setting(
        default=65536,
        ge=4096,
        le=65536,
        restart=True,
        label="Largest code checked (bytes)",
        help="The most code, in bytes, one Semgrep check will read.",
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
        label="Time limit per check (seconds)",
        help="How long to wait for a slow optional check before giving up on it for that text.",
    )
    breaker_threshold: int = setting(
        default=3,
        gt=0,
        audience="expert",
        label="Timeouts before a check is paused",
        help=(
            "After this many timeouts in a row, a slow check sits out for a while so "
            "it does not slow everything down."
        ),
    )
    breaker_cooldown_seconds: float = setting(
        default=30.0,
        gt=0,
        audience="expert",
        label="Pause length (seconds)",
        help="How long a paused check sits out before it is tried again.",
    )
    prompt_guard: PromptGuardConfig = setting(
        default=PromptGuardConfig(),
        label="PromptGuard",
        help="An optional model that catches reworded hidden instructions.",
    )
    presidio: PresidioConfig = setting(
        default=PresidioConfig(),
        label="Presidio",
        help="An optional check that finds personal details.",
    )
    semgrep: SemgrepConfig = setting(
        default=SemgrepConfig(),
        label="Semgrep",
        help="An optional checker for risky code, with an engine you install.",
    )
