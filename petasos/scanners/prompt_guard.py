"""Direct PromptGuard 2 scanner on torch and transformers (PET-242).

Module-level imports are stdlib plus ``petasos._types``. torch and transformers
import locally inside ``_load`` and ``_score``, so ``import petasos.scanners``
stays ML-free. ``_score`` holds every torch use in the inference path, which lets
the default test lane replace it and test the rest of the scanner without torch.

The loaded model is module state, not instance state. One multiplexed Hermes
gateway builds a scanner list per guarded profile home, and every copy imports
this one module, so N copies share one model in memory.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import math
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

from petasos._types import (
    AVAILABILITY_CAUSE_ABSENT,
    AVAILABILITY_CAUSE_LOAD_FAILED,
    AvailabilityCause,
    Direction,
    ScanFinding,
    ScanResult,
    Severity,
)

_logger = logging.getLogger(__name__)

_REQUIRED_PACKAGES: tuple[str, ...] = ("torch", "transformers")
_INSTALL_HINT = "torch or transformers not installed. pip install petasos[prompt-guard]"

_MODEL_ID = "meta-llama/Llama-Prompt-Guard-2-86M"
_MODEL_REVISION = "a8ded8e697ce7c355e395a0df51f94adb4a2fd27"
_RULE_ID = "petasos.promptguard.injection"
_BLOCK_THRESHOLD = 0.9
_MAX_TOKENS = 512
_WINDOW_CHARS = 8192

_INFER_WAIT_SECONDS = 8.0
_LOAD_RETRY_SECONDS = 30.0

_SNAPSHOT_FILES: tuple[str, ...] = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "model.safetensors",
)
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_WHITESPACE_RUN = re.compile(r"\s+")


@dataclass(frozen=True)
class _LoadFailure:
    message: str
    retry_at: float | None
    """Monotonic time a retry is allowed. ``None`` means latched for the process."""


class _ScanRefused(Exception):
    """A scan that cannot run. Its message becomes ``ScanResult.error``."""


_MODEL: tuple[Any, Any] | None = None
_LOAD_ERROR: _LoadFailure | None = None
_LOAD_STARTED: float | None = None
_FALLBACK_WARNED = False
_LOAD_LOCK = threading.Lock()
_INFER_LOCK = threading.Lock()


def _reset_for_tests() -> None:
    global _MODEL, _LOAD_ERROR, _LOAD_STARTED, _FALLBACK_WARNED
    _MODEL = None
    _LOAD_ERROR = None
    _LOAD_STARTED = None
    _FALLBACK_WARNED = False


def _hf_home() -> str:
    # expanduser: llamafirewall sets HF_HOME to a literal "~/.cache/huggingface"
    # and the two backends can share a process during migration.
    home = os.environ.get("HF_HOME", "")
    return os.path.expanduser(home) if home else os.path.expanduser("~/.cache/huggingface")


def _cache_dir() -> str:
    """The hub cache the probe and the load both use.

    A documented subset of the hub's settings. ``cache_dir`` is passed explicitly
    because the hub fixes its cache constant at import, while this reads the
    environment on each call.
    """
    explicit = os.environ.get("HF_HUB_CACHE", "")
    if explicit:
        return os.path.expanduser(explicit)
    return os.path.join(_hf_home(), "hub")


def _snapshot_complete() -> bool:
    # A killed download leaves a directory that looks cached, because the hub
    # writes small files first. Keying on the files lets a partial snapshot resume.
    snapshot = os.path.join(
        _cache_dir(),
        f"models--{_MODEL_ID.replace('/', '--')}",
        "snapshots",
        _MODEL_REVISION,
    )
    return all(os.path.isfile(os.path.join(snapshot, name)) for name in _SNAPSHOT_FILES)


def _has_token() -> bool:
    if os.environ.get("HF_TOKEN", "").strip():
        return True
    if os.environ.get("HUGGING_FACE_HUB_TOKEN", "").strip():
        return True
    token_path = os.environ.get("HF_TOKEN_PATH", "") or os.path.join(_hf_home(), "token")
    try:
        if os.path.isfile(token_path):
            with open(token_path, encoding="utf-8") as f:
                return bool(f.read().strip())
    except Exception:
        return False
    return False


def _offline() -> bool:
    return any(
        os.environ.get(flag, "").strip().lower() in _TRUTHY
        for flag in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    )


def _prerequisite_message() -> str:
    return (
        f"PromptGuard model unavailable: revision {_MODEL_REVISION} of {_MODEL_ID} is not "
        "fully cached and cannot be downloaded (no Hugging Face token, or offline). Accept "
        f"the model license, then run: hf download {_MODEL_ID} --revision {_MODEL_REVISION}. "
        "On a multiplexed gateway a token in profiles/<name>/.env is not seen; see "
        'docs/deployment/hermes-desktop.md ("PromptGuard model prerequisites")'
    )


def _window(text: str) -> str:
    """The text the model is offered: normalized, whitespace-collapsed, head only.

    Whitespace padding cannot push content out of the window, though ordinary
    words can, and the per-character
    preprocessing loop never sees more than ``_WINDOW_CHARS``.
    """
    # A lone surrogate would raise in the tokenizer and become a no-ML verdict.
    text = text.encode("utf-8", "replace").decode("utf-8")
    return _WHITESPACE_RUN.sub(" ", text).strip()[:_WINDOW_CHARS]


# _preprocess is ported from llamafirewall 1.0.3,
# llamafirewall/scanners/promptguard_utils.py (_preprocess_text_for_promptguard).
#
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
def _preprocess(text: str, tokenizer: Any) -> str:
    """Re-tokenize with whitespace removed, to resist whitespace-splitting evasion."""
    global _FALLBACK_WARNED
    try:
        cleaned_text = ""
        index_map = []
        for i, char in enumerate(text):
            if not char.isspace():
                cleaned_text += char
                index_map.append(i)
        tokens = tokenizer.tokenize(cleaned_text)
        result = []
        last_end = 0
        for token in tokens:
            token_str = tokenizer.convert_tokens_to_string([token])
            start = cleaned_text.index(token_str, last_end)
            end = start + len(token_str)
            original_start = index_map[start]
            if original_start > 0 and text[original_start - 1].isspace():
                result.append(" ")
            result.append(token_str)
            last_end = end
        return "".join(result)
    except Exception as exc:
        # A silent fallback removes the defense with no visible change. The
        # exception type only: the message can carry the scanned text.
        if not _FALLBACK_WARNED:
            _FALLBACK_WARNED = True
            _logger.warning(
                "PromptGuard preprocessing fell back to raw text (%s)", type(exc).__name__
            )
        return text


def _score(text: str) -> float:
    """The injection probability for ``text``. Caller holds ``_INFER_LOCK``."""
    import torch

    holder = _MODEL
    if holder is None:
        raise RuntimeError("PromptGuard model is not loaded")
    model, tokenizer = holder
    inputs = tokenizer(
        _preprocess(text, tokenizer),
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=_MAX_TOKENS,
    )
    with torch.inference_mode():
        logits = model(**inputs).logits
    return float(torch.softmax(logits, dim=-1)[0, -1].item())


def _load(*, local_files_only: bool) -> tuple[Any, Any]:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    cache_dir = _cache_dir()
    # use_safetensors: no pickle file is ever loaded.
    model = AutoModelForSequenceClassification.from_pretrained(
        _MODEL_ID,
        revision=_MODEL_REVISION,
        cache_dir=cache_dir,
        local_files_only=local_files_only,
        use_safetensors=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        _MODEL_ID,
        revision=_MODEL_REVISION,
        cache_dir=cache_dir,
        local_files_only=local_files_only,
    )
    model.eval()
    return model, tokenizer


def _availability() -> tuple[bool, str | None, AvailabilityCause | None]:
    if _MODEL is not None:
        return (True, None, None)
    for pkg in _REQUIRED_PACKAGES:
        if pkg in sys.modules and sys.modules[pkg] is not None:
            continue
        try:
            spec = importlib.util.find_spec(pkg)
        except Exception:
            return (False, _INSTALL_HINT, AVAILABILITY_CAUSE_ABSENT)
        if spec is None or spec.origin is None:
            return (False, _INSTALL_HINT, AVAILABILITY_CAUSE_ABSENT)
    failure = _LOAD_ERROR
    if failure is not None and (failure.retry_at is None or time.monotonic() < failure.retry_at):
        return (False, failure.message, AVAILABILITY_CAUSE_LOAD_FAILED)
    if not _snapshot_complete() and (_offline() or not _has_token()):
        return (False, _prerequisite_message(), AVAILABILITY_CAUSE_ABSENT)
    return (True, None, None)


def _ensure_model() -> None:
    """Load the shared model once. Raises ``_ScanRefused`` when a scan cannot run."""
    global _MODEL, _LOAD_ERROR, _LOAD_STARTED
    if _MODEL is not None:
        return
    if not _LOAD_LOCK.acquire(blocking=False):
        started = _LOAD_STARTED
        elapsed = 0.0 if started is None else time.monotonic() - started
        raise _ScanRefused(
            f"prompt_guard warming up: first model load in progress ({elapsed:.0f}s elapsed)"
        )
    try:
        if _MODEL is not None:
            return
        # Re-checked under the lock: another copy's load can have failed since
        # this scan's own check, and the cooldown has to hold across copies.
        ok, reason, _cause = _availability()
        if not ok:
            raise _ScanRefused(reason or "prompt_guard unavailable")
        _LOAD_STARTED = time.monotonic()
        complete = _snapshot_complete()
        try:
            loaded = _load(local_files_only=complete)
        except Exception as exc:
            # huggingface_hub raises httpx errors that are not OSError when a
            # connection drops, so anything from a network-capable load retries.
            retryable = not complete or isinstance(exc, (OSError, MemoryError))
            message = f"prompt_guard load failed: {exc}"
            _LOAD_ERROR = _LoadFailure(
                message, time.monotonic() + _LOAD_RETRY_SECONDS if retryable else None
            )
            raise _ScanRefused(message) from exc
        _MODEL = loaded
        _LOAD_ERROR = None
    finally:
        _LOAD_STARTED = None
        _LOAD_LOCK.release()


def _map_score(score: float, duration_ms: float) -> ScanResult:
    """Score to verdict. Pure, so the default test lane exercises it without torch."""
    if not math.isfinite(score):
        # upstream's `score >= threshold` is false for NaN, so a broken model
        # would pass as clean.
        return ScanResult(
            scanner_name="prompt_guard",
            findings=(),
            duration_ms=duration_ms,
            error=f"prompt_guard produced a non-finite score ({score})",
        )
    findings: tuple[ScanFinding, ...] = ()
    if score >= _BLOCK_THRESHOLD:
        findings = (
            ScanFinding(
                rule_id=_RULE_ID,
                finding_type="injection",
                severity=Severity.HIGH,
                confidence=max(0.0, min(1.0, score)),
                # Never the scanned text: findings reach audit.
                message=f"PromptGuard 2 injection score {score:.3f}",
                scanner_name="prompt_guard",
                position=None,
                matched_text=None,
            ),
        )
    return ScanResult(scanner_name="prompt_guard", findings=findings, duration_ms=duration_ms)


def _scan_sync(text: str) -> float | None:
    """Load and infer off the event loop. ``None`` means nothing to score.

    Blank input is clean before availability is consulted, so an absent backend
    reports an error only for text it would have scored.
    """
    window = _window(text)
    if not window:
        return None
    ok, reason, _cause = _availability()
    if not ok:
        raise _ScanRefused(reason or "prompt_guard unavailable")
    _ensure_model()
    if not _INFER_LOCK.acquire(timeout=_INFER_WAIT_SECONDS):
        # pipeline.py imports petasos.scanners, so this import stays local. The
        # prefix makes a miss count toward the breaker; a plain error would clear
        # the streak and a wedged forward would cost every call this wait forever.
        from petasos.pipeline import _TIMEOUT_ERROR_PREFIX

        raise _ScanRefused(
            f"{_TIMEOUT_ERROR_PREFIX}: prompt_guard inference lock not acquired "
            f"within {_INFER_WAIT_SECONDS}s"
        )
    try:
        return _score(window)
    finally:
        _INFER_LOCK.release()


class PromptGuardScanner:
    @property
    def name(self) -> str:
        return "prompt_guard"

    def availability(self) -> tuple[bool, str | None, AvailabilityCause | None]:
        """Cheap backend-presence probe. Never imports the backend."""
        return _availability()

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        """Scan ``text`` and return a ScanResult (never raises).

        Both directions score identically, as the LlamaFirewall wrapper does.

        Load and inference run in a worker thread, so ``asyncio.wait_for`` in the
        pipeline can return during a slow load. A cancelled scan's thread runs to
        completion: a load finishes for the next scan, and a queued inference
        gives up at ``_INFER_WAIT_SECONDS``.
        """
        start = time.perf_counter()

        def elapsed() -> float:
            return (time.perf_counter() - start) * 1000

        try:
            score = await asyncio.to_thread(_scan_sync, text)
            if score is None:
                return ScanResult(scanner_name=self.name, findings=(), duration_ms=elapsed())
            return _map_score(score, elapsed())
        except Exception as exc:
            return ScanResult(
                scanner_name=self.name,
                findings=(),
                duration_ms=elapsed(),
                error=str(exc),
            )
