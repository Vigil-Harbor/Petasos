"""Layered ingestion-result scan: one short ``inspect()`` head plus a syntactic sweep.

Closes the PET-170 mid-window hole below ``_MAX_PARAM_TEXT_LEN``. ``Pipeline.inspect``
stays one-shot; callers that want full-coverage result scanning go through this helper.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from petasos._types import Direction, PipelineResult, Position, ScanFinding, ScanResult
from petasos.scanners.minimal import _DECODE_MAX_BYTES, MinimalScanner

if TYPE_CHECKING:
    import threading

    from petasos.pipeline import Pipeline
from petasos.session.guard import _MAX_PARAM_TEXT_LEN

HEAD_CHARS = 2_048
CHUNK_CHARS = 65_536
CHUNK_OVERLAP_CHARS = _DECODE_MAX_BYTES  # 8_192
_STRIDE = CHUNK_CHARS - CHUNK_OVERLAP_CHARS

IngestionRegime = Literal["full", "ceiling"]


@dataclass(frozen=True)
class IngestionCoverage:
    regime: IngestionRegime
    scanned_chars: int
    total_chars: int
    head_chars: int
    chunk_count: int


@dataclass(frozen=True)
class IngestionScanResult:
    findings: tuple[ScanFinding, ...]
    coverage: IngestionCoverage
    head: PipelineResult | None
    errors: tuple[str, ...]


def _chunk_origins(length: int) -> tuple[int, ...]:
    """Inclusive-origin list for a covered prefix of ``length`` characters.

    First origin is always 0. Consecutive origins differ by ``_STRIDE`` until the
    last window, which may be short. ``length <= 0`` still yields ``(0,)`` so the
    origin arithmetic is defined for the empty-string pin.
    """
    covered = min(max(length, 0), _MAX_PARAM_TEXT_LEN)
    if covered <= 0:
        return (0,)
    origins: list[int] = []
    origin = 0
    while origin < covered:
        origins.append(origin)
        nxt = origin + _STRIDE
        if nxt >= covered:
            break
        origin = nxt
    return tuple(origins)


def _map_finding(finding: ScanFinding, origin: int) -> ScanFinding:
    if finding.position is None or origin == 0:
        return finding
    return replace(
        finding,
        position=Position(finding.position.start + origin, finding.position.end + origin),
    )


def _coverage_for(text: str, chunk_count: int) -> IngestionCoverage:
    total = len(text)
    scanned = min(total, _MAX_PARAM_TEXT_LEN)
    regime: IngestionRegime = "full" if total <= _MAX_PARAM_TEXT_LEN else "ceiling"
    return IngestionCoverage(
        regime=regime,
        scanned_chars=scanned,
        total_chars=total,
        head_chars=min(HEAD_CHARS, scanned),
        chunk_count=chunk_count,
    )


async def _acquire_inspect_lock(lock: threading.Lock) -> None:
    """Poll a non-blocking acquire so the ingest loop can honour ``wait_for``.

    A blocking ``Lock.acquire()`` freezes this event loop, so the scan budget
    cannot fire while another holder (guard evaluate / reconfigure) has the
    mutex. ``asyncio.to_thread(Lock.acquire)`` is cancel-unsafe (PET-208): the
    worker can still acquire after this coroutine is cancelled and leak the
    lock. Yielding between non-blocking attempts keeps cancellation at an
    ``await`` that has not yet acquired.
    """
    while not lock.acquire(blocking=False):
        await asyncio.sleep(0.01)


async def scan_ingestion_result(
    pipeline: Pipeline,
    text: str,
    *,
    direction: Direction = "inbound",
    session_id: str | None = None,
    weight_cap: float | None = None,
    inspect_lock: threading.Lock | None = None,
) -> IngestionScanResult:
    """Scan an ingesting tool result with no unscanned gap below the 1e6 ceiling.

    Never throws. One ``pipeline.inspect`` on the ML-sized head, then overlapping
    ``MinimalScanner.scan`` chunks over the covered prefix. Finding positions are
    original-result coordinates. The inspect mutex, when provided, is held only
    around the head ``inspect()``.
    """
    from petasos.pipeline import merge_findings

    errors: list[str] = []
    head: PipelineResult | None = None
    origins = _chunk_origins(len(text))
    try:
        covered = text[:_MAX_PARAM_TEXT_LEN]
        try:
            decode_flag = bool(pipeline.config.decode_encoded_payloads)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            decode_flag = True

        async def _inspect_head() -> PipelineResult:
            return await pipeline.inspect(
                covered[:HEAD_CHARS],
                direction=direction,
                session_id=session_id,
                weight_cap=weight_cap,
            )

        acquired = False
        try:
            if inspect_lock is not None:
                await _acquire_inspect_lock(inspect_lock)
                acquired = True
            head = await _inspect_head()
        except Exception as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            errors.append(f"{type(exc).__name__}: {exc}")
            head = None
        finally:
            if acquired and inspect_lock is not None:
                inspect_lock.release()

        scanner = MinimalScanner(decode_encoded_payloads=decode_flag)
        mapped: list[ScanFinding] = []
        for origin in origins:
            chunk = covered[origin : origin + CHUNK_CHARS]
            try:
                result = await scanner.scan(chunk, direction=direction)
            except Exception as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                errors.append(f"{type(exc).__name__}: {exc}")
                continue
            if result.error is not None:
                errors.append(result.error)
            mapped.extend(_map_finding(f, origin) for f in result.findings)

        head_findings: tuple[ScanFinding, ...] = () if head is None else head.findings
        merged = merge_findings(
            (
                ScanResult(scanner_name="ingest-head", findings=head_findings),
                ScanResult(scanner_name="ingest-sweep", findings=tuple(mapped)),
            )
        )
        return IngestionScanResult(
            findings=merged,
            coverage=_coverage_for(text, len(origins)),
            head=head,
            errors=tuple(errors),
        )
    except Exception as exc:
        if isinstance(exc, asyncio.CancelledError):
            raise
        errors.append(f"{type(exc).__name__}: {exc}")
        return IngestionScanResult(
            findings=(),
            coverage=_coverage_for(text, 0),
            head=head,
            errors=tuple(errors),
        )
