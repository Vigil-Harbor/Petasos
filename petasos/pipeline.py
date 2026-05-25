from __future__ import annotations

import asyncio
import copy
import time
from typing import TYPE_CHECKING

from petasos._types import (
    PipelineResult,
    ScanFinding,
    ScanResult,
    Severity,
)
from petasos.config import PetasosConfig
from petasos.normalize import normalize
from petasos.scanners.minimal import MinimalScanner

if TYPE_CHECKING:
    from collections.abc import Sequence

    from petasos._types import Direction, Scanner

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}

_SCANNER_TIMEOUT = 30.0


def merge_findings(results: Sequence[ScanResult]) -> tuple[ScanFinding, ...]:
    all_findings: list[ScanFinding] = []
    for r in results:
        all_findings.extend(r.findings)

    if not all_findings:
        return ()

    positioned: list[ScanFinding] = []
    unpositioned: list[ScanFinding] = []
    for f in all_findings:
        if f.position is not None:
            positioned.append(f)
        else:
            unpositioned.append(f)

    if not positioned:
        return tuple(unpositioned)

    positioned.sort(key=lambda f: f.position.start)  # type: ignore[union-attr]

    surviving: list[ScanFinding] = []
    current = positioned[0]

    for nxt in positioned[1:]:
        assert current.position is not None
        assert nxt.position is not None
        if nxt.position.start < current.position.end:
            if nxt.confidence > current.confidence:
                current = nxt
            elif nxt.confidence == current.confidence:
                nxt_rank = _SEVERITY_RANK.get(nxt.severity, 999)
                cur_rank = _SEVERITY_RANK.get(current.severity, 999)
                if nxt_rank < cur_rank:
                    current = nxt
                elif nxt_rank == cur_rank:
                    surviving.append(current)
                    current = nxt
        else:
            surviving.append(current)
            current = nxt

    surviving.append(current)
    return tuple(surviving) + tuple(unpositioned)


def _compute_safe(
    findings: tuple[ScanFinding, ...],
    scanner_results: Sequence[ScanResult],
    fail_mode: str,
) -> bool:
    safe = True
    for f in findings:
        if f.severity in (Severity.CRITICAL, Severity.HIGH):
            safe = False
            break

    ml_total = 0
    ml_errored = 0
    for r in scanner_results:
        if r.scanner_name == "minimal":
            continue
        ml_total += 1
        if r.error is not None:
            ml_errored += 1

    if ml_total == 0:
        return safe

    partial_failure = 0 < ml_errored < ml_total
    all_ml_failure = ml_errored == ml_total

    if fail_mode == "degraded":
        if all_ml_failure:
            safe = False
    elif fail_mode == "open":
        pass
    elif fail_mode == "closed" and (partial_failure or all_ml_failure):
        safe = False

    return safe


async def _scan_one(
    scanner: Scanner,
    normalized_text: str,
    *,
    direction: Direction,
    session_id: str | None,
) -> ScanResult:
    sname = getattr(scanner, "name", "unknown")
    t0 = time.perf_counter()
    try:
        return await asyncio.wait_for(
            scanner.scan(normalized_text, direction=direction, session_id=session_id),
            timeout=_SCANNER_TIMEOUT,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ScanResult(
            scanner_name=sname,
            findings=(),
            duration_ms=elapsed,
            error=str(exc),
        )


class Pipeline:
    def __init__(
        self,
        scanners: Sequence[Scanner] = (),
        *,
        config: PetasosConfig | None = None,
    ) -> None:
        self._config = copy.deepcopy(config) if config is not None else PetasosConfig()
        self._premium_active = False

        scanner_list = list(scanners)
        self._minimal_scanner: MinimalScanner | None = None
        self._ml_scanners: list[Scanner] = []

        for s in scanner_list:
            if self._minimal_scanner is None and getattr(s, "name", None) == "minimal":
                if isinstance(s, MinimalScanner):
                    self._minimal_scanner = s
                else:
                    self._ml_scanners.append(s)
            else:
                self._ml_scanners.append(s)

        if self._minimal_scanner is None:
            self._minimal_scanner = MinimalScanner()

    async def inspect(
        self,
        text: str,
        *,
        direction: Direction | None = None,
        session_id: str | None = None,
    ) -> PipelineResult:
        resolved_direction: Direction = (
            direction if direction is not None else self._config.direction
        )

        try:
            return await self._inspect_inner(
                text, direction=resolved_direction, session_id=session_id
            )
        except Exception as exc:
            return PipelineResult(
                safe=False,
                findings=(),
                errors=(str(exc),),
            )

    async def _inspect_inner(
        self,
        text: str,
        *,
        direction: Direction,
        session_id: str | None,
    ) -> PipelineResult:
        errors: list[str] = []

        # Stage 1: Normalize
        any_toggle_off = not (
            self._config.normalize_nfkc
            and self._config.strip_zero_width
            and self._config.map_homoglyphs
            and self._config.detect_rtl_override
        )
        if any_toggle_off:
            normalized_text = text
        else:
            norm_result = normalize(text)
            normalized_text = norm_result.normalized

        # Stage 2: Syntactic pre-filter (raw text)
        assert self._minimal_scanner is not None
        minimal_result = await self._minimal_scanner.scan(
            text, direction=direction, session_id=session_id
        )

        # Stage 3: Early exit (closed mode) — skip ML fan-out but still
        # run premium hooks so audit/alerting sees critical findings.
        early_exit = False
        if self._config.fail_mode == "closed":
            has_critical = any(f.severity == Severity.CRITICAL for f in minimal_result.findings)
            if has_critical:
                early_exit = True

        # Stage 4: Fan-out scan
        if early_exit:
            ml_results: list[ScanResult] = []
        elif self._ml_scanners:
            tasks = [
                _scan_one(s, normalized_text, direction=direction, session_id=session_id)
                for s in self._ml_scanners
            ]
            ml_results = list(await asyncio.gather(*tasks))
        else:
            ml_results = []

        all_results = [minimal_result] + ml_results

        # Stage 5: Merge findings
        merged = merge_findings(all_results)

        # Stage 6: Premium frequency hook
        await self._premium_frequency_hook(merged, session_id)

        # Stage 7: Premium escalation hook
        await self._premium_escalation_hook(merged, session_id)

        # Stage 8: Fail-mode enforcement
        safe = False if early_exit else _compute_safe(merged, all_results, self._config.fail_mode)

        # Stage 9: Anonymize
        sanitized_content: str | None = None
        if self._config.anonymize:
            pii_findings = [f for f in merged if f.finding_type == "pii"]
            if pii_findings:
                try:
                    from petasos.scanners.presidio import anonymize as _anonymize

                    sanitized_content = _anonymize(
                        normalized_text,
                        pii_findings,
                        mode=self._config.redaction_mode,
                        hash_key=self._config.hash_key,
                    )
                except ImportError:
                    errors.append("presidio not installed: anonymization skipped")
                except Exception as exc:
                    errors.append(str(exc))

        scanner_results = tuple(all_results)

        result = PipelineResult(
            safe=safe,
            findings=merged,
            sanitized_content=sanitized_content,
            scanner_results=scanner_results,
            errors=tuple(errors),
        )

        # Stage 10: Premium audit hook
        await self._premium_audit_hook(result, session_id)

        # Stage 11: Premium alert hook
        await self._premium_alert_hook(result, session_id)

        # Stage 12: Return
        return result

    async def _premium_frequency_hook(
        self, findings: tuple[ScanFinding, ...], session_id: str | None
    ) -> None:
        pass

    async def _premium_escalation_hook(
        self, findings: tuple[ScanFinding, ...], session_id: str | None
    ) -> None:
        pass

    async def _premium_audit_hook(self, result: PipelineResult, session_id: str | None) -> None:
        pass

    async def _premium_alert_hook(self, result: PipelineResult, session_id: str | None) -> None:
        pass
