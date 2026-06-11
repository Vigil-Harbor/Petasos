from __future__ import annotations

import asyncio
import importlib.util
import logging
import math
import os
import sys
import threading
import time
from contextlib import contextmanager
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

from petasos._types import Direction, ScanFinding, ScanResult, Severity

_logger = logging.getLogger(__name__)

_REQUIRED_PACKAGES: tuple[str, ...] = ("llamafirewall",)

_INSTALL_HINT = "llamafirewall not installed. pip install petasos[llamafirewall]"

_WARMING_UP_MSG = "llama_firewall warming up — first model load in progress"

_STDIN_GUARD = threading.Lock()

_COMPONENT_TAXONOMY: MappingProxyType[str, tuple[str, str, Severity]] = MappingProxyType(
    {
        "prompt_guard": (
            "petasos.llamafirewall.prompt-guard",
            "injection",
            Severity.HIGH,
        ),
        "alignment_check": (
            "petasos.llamafirewall.alignment-check",
            "alignment",
            Severity.HIGH,
        ),
        "code_shield": (
            "petasos.llamafirewall.code-shield",
            "unsafe_code",
            Severity.MEDIUM,
        ),
    }
)

_TRIPWIRE_FALLBACK_MSG = (
    "interactive stdin prompt intercepted — check HF token/model "
    "prerequisites; see docs/deployment/hermes-desktop.md"
)


@contextmanager
def _stdin_swap() -> Iterator[bool]:
    """Swap sys.stdin with devnull under _STDIN_GUARD (non-blocking).

    Yields True if the lock was acquired and stdin is swapped, False on
    contention (caller must produce the warming-up error without entering
    the guarded body).
    """
    if not _STDIN_GUARD.acquire(blocking=False):
        yield False
        return
    devnull = open(os.devnull, encoding="utf-8")  # noqa: SIM115
    saved = sys.stdin
    sys.stdin = devnull
    try:
        yield True
    finally:
        sys.stdin = saved
        devnull.close()
        _STDIN_GUARD.release()


def _prompt_guard_prereq_error(enable_prompt_guard: bool) -> str | None:
    """Return an actionable error if upstream would interactively prompt, else None."""
    if not enable_prompt_guard:
        return None

    try:
        hf_home = os.environ.get("HF_HOME", "")
        if not hf_home:
            hf_home = os.path.join(os.path.expanduser("~"), ".cache", "huggingface")

        model_id = "meta-llama/Llama-Prompt-Guard-2-86M"
        model_dir_name = model_id.replace("/", "--")
        model_path = os.path.join(hf_home, "hub", f"models--{model_dir_name}")

        if os.path.isdir(model_path):
            return None

        token = os.environ.get("HF_TOKEN", "").strip()
        if not token:
            token = os.environ.get("HUGGING_FACE_HUB_TOKEN", "").strip()
        if not token:
            token_path = os.environ.get("HF_TOKEN_PATH", "")
            if not token_path:
                token_path = os.path.join(hf_home, "token")
            try:
                if os.path.isfile(token_path):
                    with open(token_path, encoding="utf-8") as f:
                        token = f.read().strip()
            except Exception:
                token = ""

        if token:
            return None

        return (
            "PromptGuard model unavailable — set HF_TOKEN from a Hugging Face "
            "account that has accepted the meta-llama/Llama-Prompt-Guard-2-86M "
            "license, or pre-download the model; see "
            'docs/deployment/hermes-desktop.md ("PromptGuard model prerequisites")'
        )
    except Exception:
        return (
            "PromptGuard model unavailable — set HF_TOKEN from a Hugging Face "
            "account that has accepted the meta-llama/Llama-Prompt-Guard-2-86M "
            "license, or pre-download the model; see "
            'docs/deployment/hermes-desktop.md ("PromptGuard model prerequisites")'
        )


class LlamaFirewallScanner:
    def __init__(
        self,
        *,
        enable_prompt_guard: bool = True,
        enable_alignment_check: bool = False,
        enable_code_shield: bool = False,
    ) -> None:
        self._enable_prompt_guard = enable_prompt_guard
        self._enable_alignment_check = enable_alignment_check
        self._enable_code_shield = enable_code_shield
        self._loaded = False
        self._load_error: str | None = None
        self._load_error_retryable: bool = False
        self._lock = threading.Lock()
        self._components: dict[str, Any] = {}
        self._user_message_cls: type[Any] | None = None
        self._assistant_message_cls: type[Any] | None = None
        self._allow_decision: Any = None
        self._warmed = False

    @property
    def name(self) -> str:
        return "llama_firewall"

    def availability(self) -> tuple[bool, str | None]:
        """Cheap backend-presence probe. Never imports the backend."""
        if self._load_error is not None and not self._load_error_retryable:
            return (False, self._load_error)
        for pkg in _REQUIRED_PACKAGES:
            if pkg in sys.modules and sys.modules[pkg] is not None:
                continue
            try:
                spec = importlib.util.find_spec(pkg)
            except Exception:
                return (False, _INSTALL_HINT)
            if spec is None or spec.origin is None:
                return (False, _INSTALL_HINT)
        if self._enable_prompt_guard and not self._components:
            prereq = _prompt_guard_prereq_error(self._enable_prompt_guard)
            if prereq is not None:
                return (False, prereq)
        return (True, None)

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            if self._load_error is not None and self._load_error_retryable:
                pass
            else:
                return self._load_error is None
        if self._load_error is not None and not self._load_error_retryable:
            return False
        with self._lock:
            if self._loaded and self._load_error is None:
                return True
            if self._load_error is not None and not self._load_error_retryable:
                return False
            if self._load_error is not None and self._load_error_retryable:
                if self._load_error == _WARMING_UP_MSG:
                    self._load_error = None
                    self._load_error_retryable = False
                    self._loaded = False
                else:
                    avail, _reason = self.availability()
                    if not avail:
                        if _reason is not None:
                            self._load_error = _reason
                        return False
                    self._load_error = None
                    self._load_error_retryable = False
                    self._loaded = False
                    self._components.clear()
            return self._do_load()

    def _do_load(self) -> bool:
        try:
            from llamafirewall import (
                AssistantMessage,
                LlamaFirewall,
                Role,
                ScanDecision,
                ScannerType,
                UserMessage,
            )

            self._user_message_cls = UserMessage
            self._assistant_message_cls = AssistantMessage
            self._allow_decision = ScanDecision.ALLOW

            prereq = _prompt_guard_prereq_error(self._enable_prompt_guard)
            if prereq is not None:
                self._components.clear()
                self._load_error = prereq
                self._load_error_retryable = True
                return False

            _COMPONENT_MAP: dict[str, Any] = {
                "prompt_guard": ScannerType.PROMPT_GUARD,
                "alignment_check": ScannerType.AGENT_ALIGNMENT,
                "code_shield": ScannerType.CODE_SHIELD,
            }
            _ENABLED: dict[str, bool] = {
                "prompt_guard": self._enable_prompt_guard,
                "alignment_check": self._enable_alignment_check,
                "code_shield": self._enable_code_shield,
            }

            with _stdin_swap() as acquired:
                if not acquired:
                    self._load_error = _WARMING_UP_MSG
                    self._load_error_retryable = True
                    return False
                for comp_name, scanner_type in _COMPONENT_MAP.items():
                    if _ENABLED[comp_name]:
                        self._components[comp_name] = LlamaFirewall(
                            scanners={
                                Role.USER: [scanner_type],
                                Role.ASSISTANT: [scanner_type],
                            }
                        )

            if not self._components:
                _logger.warning(
                    "LlamaFirewallScanner: all components disabled — "
                    "scan() will return error, not clean"
                )
            self._loaded = True
            return True
        except ImportError:
            self._components.clear()
            from petasos.scanners import _is_missing_package

            exc = sys.exc_info()[1]
            if isinstance(exc, ImportError) and _is_missing_package(exc, set(_REQUIRED_PACKAGES)):
                self._load_error = _INSTALL_HINT
                self._load_error_retryable = True
            else:
                avail_ok, avail_reason = self.availability()
                if avail_ok:
                    self._loaded = True
                    self._load_error = str(exc)
                    self._load_error_retryable = False
                else:
                    self._load_error = avail_reason or _INSTALL_HINT
                    self._load_error_retryable = True
            return False
        except Exception as exc:
            self._components.clear()
            if isinstance(exc, EOFError):
                prereq = _prompt_guard_prereq_error(self._enable_prompt_guard)
                self._load_error = prereq or _TRIPWIRE_FALLBACK_MSG
            else:
                self._load_error = f"llamafirewall init failed: {exc}"
            avail_ok, _ = self.availability()
            if avail_ok:
                self._loaded = True
                self._load_error_retryable = False
            else:
                self._load_error_retryable = True
            return False

    def _scan_sync(self, text: str, direction: Direction) -> tuple[list[ScanFinding], list[str]]:
        if self._user_message_cls is None or self._assistant_message_cls is None:
            return [], ["internal error: message type classes not initialized"]

        if direction == "inbound":
            message = self._user_message_cls(content=text)
        else:
            message = self._assistant_message_cls(content=text)

        findings: list[ScanFinding] = []
        errors: list[str] = []

        eof_tripped = False
        prompt_guard_ok = False

        if not self._warmed:
            with _stdin_swap() as acquired:
                if not acquired:
                    return [], [_WARMING_UP_MSG]
                for comp_name, fw_instance in self._components.items():
                    try:
                        result = fw_instance.scan(message)
                        if comp_name == "prompt_guard":
                            prompt_guard_ok = True
                        if result.decision != self._allow_decision:
                            rule_id, finding_type, severity = _COMPONENT_TAXONOMY[comp_name]
                            raw_score = result.score if result.score is not None else 1.0
                            confidence = (
                                0.0
                                if not math.isfinite(raw_score)
                                else max(0.0, min(1.0, raw_score))
                            )
                            findings.append(
                                ScanFinding(
                                    rule_id=rule_id,
                                    finding_type=finding_type,
                                    severity=severity,
                                    confidence=confidence,
                                    message=result.reason
                                    or (f"{comp_name} flagged content ({result.decision.name})"),
                                    scanner_name=self.name,
                                    position=None,
                                    matched_text=None,
                                )
                            )
                    except Exception as exc:
                        if isinstance(exc, EOFError):
                            eof_tripped = True
                            prereq = _prompt_guard_prereq_error(self._enable_prompt_guard)
                            errors.append(f"{comp_name}: {prereq or _TRIPWIRE_FALLBACK_MSG}")
                        else:
                            errors.append(f"{comp_name}: {exc}")

            pg_enabled = self._enable_prompt_guard and "prompt_guard" in self._components
            if not eof_tripped and (not pg_enabled or prompt_guard_ok):
                self._warmed = True
        else:
            for comp_name, fw_instance in self._components.items():
                try:
                    result = fw_instance.scan(message)
                    if result.decision != self._allow_decision:
                        rule_id, finding_type, severity = _COMPONENT_TAXONOMY[comp_name]
                        raw_score = result.score if result.score is not None else 1.0
                        confidence = (
                            0.0 if not math.isfinite(raw_score) else max(0.0, min(1.0, raw_score))
                        )
                        findings.append(
                            ScanFinding(
                                rule_id=rule_id,
                                finding_type=finding_type,
                                severity=severity,
                                confidence=confidence,
                                message=result.reason
                                or (f"{comp_name} flagged content ({result.decision.name})"),
                                scanner_name=self.name,
                                position=None,
                                matched_text=None,
                            )
                        )
                except Exception as exc:
                    errors.append(f"{comp_name}: {exc}")

        return findings, errors

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        """Scan ``text`` and return a ScanResult (never raises).

        Cancellation residual (SCAN-03): inference runs in a worker thread via
        ``asyncio.to_thread``. Cancelling the awaiting task frees the event loop
        promptly, but the worker thread runs to completion on the default
        executor — cancellation does not interrupt in-flight ML inference. A
        cancellable-executor path is future work.
        """
        start = time.perf_counter()
        try:
            if not self._ensure_loaded():
                elapsed = (time.perf_counter() - start) * 1000
                return ScanResult(
                    scanner_name=self.name,
                    findings=(),
                    duration_ms=elapsed,
                    error=self._load_error,
                )

            if not self._components:
                elapsed = (time.perf_counter() - start) * 1000
                return ScanResult(
                    scanner_name=self.name,
                    findings=(),
                    duration_ms=elapsed,
                    error="all components disabled — no ML inspection performed",
                )

            findings, errors = await asyncio.to_thread(self._scan_sync, text, direction)
            elapsed = (time.perf_counter() - start) * 1000
            error_str = "; ".join(errors) if errors else None
            return ScanResult(
                scanner_name=self.name,
                findings=tuple(findings),
                duration_ms=elapsed,
                error=error_str,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return ScanResult(
                scanner_name=self.name,
                findings=(),
                duration_ms=elapsed,
                error=str(exc),
            )
