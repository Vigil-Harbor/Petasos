"""Opt-in local code scanner with explicit, loop-independent ownership."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib.util
import logging
import math
import os
import platform
import re
import sys
import threading
import time
from typing import TYPE_CHECKING, Any

from petasos._limits import MAX_PARAM_TEXT_LEN
from petasos.scanners._semgrep_engine import result_for
from petasos.scanners._semgrep_runtime import (
    Job,
    Lease,
    SemgrepCleanupError,
    SemgrepCloseResult,
    Settings,
    acquire,
    await_job,
    close_leases,
    close_semgrep_runtime,
    error_result,
)
from petasos.scanners._semgrep_source import ProjectionError, select_sources, validate_envelope

if TYPE_CHECKING:
    from collections.abc import Callable

    from petasos._types import Direction, ScanResult

__all__ = [
    "SemgrepCleanupError",
    "SemgrepCloseResult",
    "SemgrepLifecycleOwner",
    "SemgrepScanner",
    "close_semgrep_runtime",
]


def supported_platform() -> bool:
    machine = platform.machine().lower()
    return (sys.platform == "win32" and machine in ("amd64", "x86_64")) or (
        sys.platform == "darwin" and machine == "arm64"
    )


def monitor_available() -> bool:
    return importlib.util.find_spec("psutil") is not None


class SemgrepLifecycleOwner:
    """Standalone embedder ownership; Hermes must supply its supported callback.

    Construction/entry creates no thread, probe or source file. The owner may be
    shared across threads and loops. Closing it never closes a sibling owner.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = "new"
        self._leases: set[Lease] = set()
        self.close_result: SemgrepCloseResult | None = None

    def __reduce__(self) -> Any:
        raise TypeError("Semgrep lifecycle ownership is process-local")

    async def __aenter__(self) -> SemgrepLifecycleOwner:
        with self._lock:
            if self._state != "new":
                raise RuntimeError("semgrep.owner_not_new")
            self._state = "live"
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        result = await self.aclose()
        if result.status != "closed":
            if exc is None:
                raise SemgrepCleanupError(result)
            logging.getLogger(__name__).error("semgrep.cleanup_failed during context exit")
            if hasattr(exc, "add_note"):
                exc.add_note("Semgrep cleanup incomplete; see owner.close_result")

    async def aclose(self, *, deadline: float | None = None) -> SemgrepCloseResult:
        with self._lock:
            self._state = "closed"
            leases = set(self._leases)
        result = await close_leases(leases, time.monotonic() + 3 if deadline is None else deadline)
        self.close_result = result
        return result


class PreparedSemgrepScan:
    """Private one-shot result, bound to one Pipeline and lease generation."""

    def __init__(
        self,
        scanner: SemgrepScanner,
        binding: object,
        text: str | None,
        *,
        registered: bool = False,
        outcome: ScanResult | None = None,
    ) -> None:
        self._scanner = scanner
        self._binding: object | None = binding
        from petasos.session.ingest import HEAD_CHARS

        self._text = text
        self._input_evidence = self._evidence(text) if text is not None else None
        self._head_evidence = self._evidence(text[:HEAD_CHARS]) if text is not None else None
        self._registered = registered
        self._state = "prepared"
        self._result = outcome or error_result("semgrep.cancelled")
        self._job: Job | None = None
        lease = scanner._lease
        self._lock = lease.runtime.lock if lease is not None else threading.RLock()

    def __reduce__(self) -> Any:
        raise TypeError("Prepared scans cannot be serialized")

    @staticmethod
    def _evidence(text: str) -> tuple[int, bytes]:
        # The tail beyond the examination ceiling is explicitly unexamined.
        return len(text), hashlib.sha256(
            text[:MAX_PARAM_TEXT_LEN].encode("utf-8", errors="surrogatepass")
        ).digest()

    def matches_input(self, binding: object, text: str) -> bool:
        with self._lock:
            return binding is self._binding and (
                self._input_evidence is None or self._evidence(text) == self._input_evidence
            )

    @property
    def outcome(self) -> ScanResult:
        with self._lock:
            return self._result

    def _set_result(self, result: ScanResult) -> None:
        with self._lock:
            self._result = result
            if self._state != "prepared":
                self._release()

    def _release(self) -> None:
        self._text = None
        self._binding = None
        self._input_evidence = self._head_evidence = None
        if self._job is not None and not self._job.future.done():
            return  # Active cleanup still owns one preparation slot.
        lease = self._scanner._lease
        if self._registered and lease is not None:
            lease.tokens.discard(self)
            self._registered = False
        self._job = None

    def _retire(self) -> None:
        with self._lock:
            if self._state != "prepared":
                return
            self._state = "discarded"
            if self._job is not None:
                lease = self._scanner._lease
                if lease is not None:
                    lease.runtime.cancel(self._job)
            self._release()

    async def discard(self) -> ScanResult:
        self._retire()
        # Terminal access after runtime join requires no new loop work.
        if self._job is not None and not self._job.future.done():
            with contextlib.suppress(asyncio.CancelledError):
                await await_job(self._job)
        return self.outcome

    def consume(self, binding: object, text: str) -> ScanResult | None:
        with self._lock:
            valid = self._state == "prepared" and binding is self._binding
            valid &= not self._scanner._is_closed()
            # Zero-resource refusal tokens intentionally retain no source.
            valid &= self._input_evidence is None or self._evidence(text) in (
                self._input_evidence,
                self._head_evidence,
            )
            if not valid:
                return None
            self._state = "consumed"
            self._release()
            return self._result


class SemgrepScanner:
    name = "semgrep"

    def __init__(
        self,
        *,
        owner: SemgrepLifecycleOwner,
        engine_path: str | None = None,
        engine_sha256: str | None = None,
        request_timeout_seconds: float = 8,
        max_source_bytes: int = 131072,
        semgrep_scheduling_key: object | None = None,
    ) -> None:
        if not isinstance(owner, SemgrepLifecycleOwner):
            raise ValueError("semgrep.host_lifecycle_unavailable")
        if not supported_platform():
            raise ValueError("semgrep.unsupported_platform")
        if (
            type(request_timeout_seconds) not in (int, float)
            or not math.isfinite(request_timeout_seconds)
            or not 1 <= request_timeout_seconds <= 8
        ):
            raise ValueError("semgrep.invalid_timeout")
        if type(max_source_bytes) is not int or not 4096 <= max_source_bytes <= 131072:
            raise ValueError("semgrep.invalid_source_limit")
        self.qualification_warning = (
            "deadline_below_qualified_load" if request_timeout_seconds < 8 else None
        )
        if self.qualification_warning:
            logging.getLogger(__name__).warning(
                "Semgrep deadline is below the unqualified eight-request load budget"
            )
        self._owner = owner
        self._closed = False
        self._lease: Lease | None = None
        self._error: str | None = None
        self.settings = Settings(
            engine_path or "", engine_sha256 or "", request_timeout_seconds, max_source_bytes
        )
        with owner._lock:
            if owner._state != "live":
                raise ValueError("semgrep.host_lifecycle_unavailable")
            if (
                not engine_path
                or not os.path.isabs(engine_path)
                or not engine_sha256
                or not re.fullmatch(r"[0-9a-fA-F]{64}", engine_sha256)
            ):
                self._error = "semgrep.engine_unavailable"
            elif not monitor_available():
                self._error = "semgrep.monitor_unavailable"
            else:
                key = object() if semgrep_scheduling_key is None else semgrep_scheduling_key
                # Identity is opaque; user-defined equality/hash is never called.
                acquired = acquire(self.settings, (id(owner), id(key)))
                self._key = key
                if isinstance(acquired, str):
                    self._error = acquired
                else:
                    self._lease = acquired
                    owner._leases.add(acquired)

    def _is_closed(self) -> bool:
        # Owner state is written once under its lock. Do not acquire that lock
        # while holding the runtime lock (constructor uses the opposite order).
        return (
            self._closed
            or self._owner._state != "live"
            or bool(self._lease and self._lease.closed)
        )

    def availability(self) -> tuple[bool, str | None]:
        if self._is_closed():
            return False, "semgrep.lease_closed"
        if self._error:
            return False, self._error
        assert self._lease is not None
        with self._lease.runtime.lock:
            error = self._lease.runtime.availability_error
            return error is None, error

    async def aclose(self, *, deadline: float | None = None) -> SemgrepCloseResult:
        self._closed = True
        result = await close_leases(
            {self._lease} if self._lease else set(),
            time.monotonic() + 3 if deadline is None else deadline,
        )
        if result.status == "closed" and self._lease is not None:
            with self._owner._lock:
                self._owner._leases.discard(self._lease)
        return result

    async def prepare(
        self,
        text: str,
        *,
        binding: object,
        segments: tuple[tuple[int, int], ...] | None = None,
        upstream_total_chars: int | None = None,
        _refusal: str | None = None,
        _on_complete: Callable[[ScanResult], None] | None = None,
    ) -> PreparedSemgrepScan:
        start = time.monotonic()

        def refused(code: str) -> PreparedSemgrepScan:
            return PreparedSemgrepScan(self, binding, None, outcome=error_result(code))

        if self._is_closed():
            return refused("semgrep.lease_closed")
        try:
            validate_envelope(text, segments, upstream_total_chars)
        except (ProjectionError, TypeError, ValueError):
            return refused("semgrep.invalid_envelope")
        token = PreparedSemgrepScan(self, binding, text)
        lease = self._lease
        if lease is not None:
            with lease.runtime.lock:
                if lease.closed:
                    return refused("semgrep.lease_closed")
                if len(lease.tokens) >= 10:
                    return refused("semgrep.prepared_capacity")
                lease.tokens.add(token)
                token._registered = True
        try:
            selected = await select_sources(
                text,
                segments=segments,
                total=upstream_total_chars,
                max_bytes=self.settings.max_bytes,
            )
            if self._is_closed():
                token._set_result(error_result("semgrep.lease_closed"))
            elif not selected.targets:
                token._set_result(result_for(selected))
            elif self._error or _refusal:
                token._set_result(result_for(selected, error=self._error or _refusal))
            else:
                assert lease is not None
                job = lease.runtime.submit(lease, selected, start + self.settings.timeout)
                token._job = job

                def completed(future: Any) -> None:
                    token._set_result(future.result())
                    if _on_complete is not None:
                        _on_complete(future.result())

                job.future.add_done_callback(completed)
                await await_job(job)
            if lease is None:
                token._text = None
            if token._job is None and _on_complete is not None:
                _on_complete(token.outcome)
            return token
        except asyncio.CancelledError:
            token._retire()
            raise
        except Exception:
            token._set_result(error_result("semgrep.engine_error"))
            return token

    async def scan(
        self, text: str, *, direction: Direction = "inbound", session_id: str | None = None
    ) -> ScanResult:
        token = await self.prepare(text, binding=self)
        try:
            return token.consume(self, text) or token.outcome
        finally:
            await token.discard()
