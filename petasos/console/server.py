"""FastAPI app factory and route handlers for the Petasos Console.

No ``from __future__ import annotations`` here: build_app's nested route
signatures (``request: Request``) must evaluate eagerly in build_app's local
scope, where the function-local fastapi imports live. With string annotations
FastAPI resolves against module globals, misses ``Request``, and silently
treats the parameter as a required query param — every standalone POST/PUT
422s (pre-existing defect surfaced by the PET-85 route-parity tests).
TYPE_CHECKING-only names in module-level signatures are quoted instead.
"""

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from petasos.console._config_meta import generate_config_metadata, generate_section_metadata
from petasos.console._paths import resolve_hermes_config_path
from petasos.console._presets import generate_preset_metadata, resolve_active_preset
from petasos.console._ring_buffer import RingBuffer
from petasos.console._sse import SSEBroadcaster
from petasos.console._validation import SessionIdError, sanitize_session_id
from petasos.normalize import normalize

if TYPE_CHECKING:
    from fastapi import FastAPI

    from petasos.pipeline import Pipeline

_logger = logging.getLogger(__name__)

_MAX_SCAN_TEXT_LEN = 100_000
_VALID_DIRECTIONS = frozenset({"inbound", "outbound"})

# PET-131: enforcement event_types that count as a block for the *blocked* tile and
# the per-session reconciliation tally. `bypassed_disarmed` is a visible-but-not-
# blocked heartbeat and is deliberately excluded.
_BLOCK_EVENT_TYPES = frozenset({"block", "quarantine", "tier3"})
# Bound on the per-session block tally (drop-oldest by session), mirroring the
# config.max_terminated_tombstones discipline. Independent of the 500-entry ring.
_MAX_TALLY_SESSIONS = 10_000
# Poll cadence of the dashboard's background enforcement-spool tailer (standalone).
_ENFORCEMENT_TAIL_INTERVAL_S = 1.0
# PET-139: rate-limit window for the integrity-failure tripwire (D9), mirroring the
# reference plugin's `_DISARM_LOG_EVERY_S` cadence so a forging loop cannot spam the log.
_INTEGRITY_LOG_EVERY_S = 30.0
# Cap on the surfaced enforcement `reason` length. The raw matched value lives in a
# finding's `matched_text` (never surfaced); `reason` is the structured scanner/guard
# message (e.g. "PII detected: PERSON"), already returned to the agent. We cap it so a
# long decoded-payload message cannot bloat the ring buffer / SSE frame — matching the
# 200-char block-message truncation in petasos/session/formatting.py.
_MAX_REASON_LEN = 200

# PET-137: bounds on the per-row playground "detail" blob persisted alongside the
# scan-history summary so a playground row can drill down to its findings (enforcement
# rows already carry their decision fields). Hard caps, not config fields — a cap is not
# a tuning dial; mirrors `_MAX_REASON_LEN` / `_MAX_TALLY_SESSIONS` / `SPOOL_CAP_BYTES`.
_MAX_DETAIL_FINDINGS = 50
_MAX_DETAIL_NORMALIZED_CHARS = 2_000
_MAX_DETAIL_BYTES = 8_000
# Severity ordering for detail-blob shedding. A 6th local copy (the cross-module rank is
# private; the reference plugin documents preferring a local copy over a cross-boundary
# import). Keyed by the Severity `.value` string; an unknown severity ranks highest so it
# is kept (shed last), never silently dropped first.
_SEVERITY_RANK: dict[str, int] = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_SEVERITY_RANK_MAX = max(_SEVERITY_RANK.values()) + 1


def _detail_bytes(blob: dict[str, Any]) -> int:
    """Serialized UTF-8 size of a detail blob, measured the way it is broadcast/stored."""
    return len(json.dumps(blob, default=str).encode("utf-8"))


def _build_playground_detail(result: Any, normalized: Any) -> dict[str, Any]:
    """Bounded ``detail`` blob for a playground scan-history row (PET-137 D2/D-CAP/D5/D7).

    Structured decision only: ``matched_text`` is stripped (D5); the normalized-text view
    is a bounded preview (D7); findings are capped and severity-shed so the serialized blob
    is ``<= _MAX_DETAIL_BYTES`` unconditionally (D-CAP). Pure; never raises.
    """
    try:
        findings: list[Any] = [
            {
                "rule_id": f.rule_id,
                "finding_type": f.finding_type,
                "severity": f.severity.value,  # `.value` string, matching ScanFinding.to_dict()
                "scanner_name": f.scanner_name,
                "message": (f.message or "")[:_MAX_REASON_LEN],
            }
            for f in result.findings
        ]
        total = len(findings)
        findings_omitted = 0
        detail_truncated = False

        # Cap finding count: keep the most severe (stable rank-desc, index-asc).
        if total > _MAX_DETAIL_FINDINGS:
            keep_set = set(
                sorted(
                    range(total),
                    key=lambda i: (
                        -_SEVERITY_RANK.get(findings[i]["severity"], _SEVERITY_RANK_MAX),
                        i,
                    ),
                )[:_MAX_DETAIL_FINDINGS]
            )
            findings = [findings[i] for i in range(total) if i in keep_set]
            findings_omitted = total - _MAX_DETAIL_FINDINGS
            detail_truncated = True

        scanner_results: Any = [
            {
                "scanner_name": sr.scanner_name,
                "duration_ms": sr.duration_ms,
                "finding_count": len(sr.findings),
                "error": sr.error,
            }
            for sr in result.scanner_results
        ]
        norm_full = normalized.normalized or ""
        norm_truncated = len(norm_full) > _MAX_DETAIL_NORMALIZED_CHARS

        blob: dict[str, Any] = {
            "findings": findings,
            "findings_omitted": findings_omitted,
            "scanner_results": scanner_results,
            "normalized_text": norm_full[:_MAX_DETAIL_NORMALIZED_CHARS],
            "normalized_text_truncated": norm_truncated,
            "transformations_applied": list(normalized.transformations_applied),
            "detail_truncated": detail_truncated,
        }

        # D-CAP hard byte cap. Findings are the payload that answers "what happened", so
        # shed the cheap/low-value parts FIRST and findings LAST: normalized preview
        # (the operator's own, already-bounded input) -> scanner_results (count-only) ->
        # findings (lowest severity first, may reach zero). This keeps the most-severe
        # findings (e.g. a critical) as long as anything at all fits; a huge multibyte
        # preview can no longer evict the critical. The irreducible floor (structural keys
        # + small transformations list) is far below the cap, so this terminates with the
        # blob `<= _MAX_DETAIL_BYTES` unconditionally.
        if _detail_bytes(blob) > _MAX_DETAIL_BYTES and blob["normalized_text"]:
            # Largest char-prefix of the preview whose whole-blob serialization fits.
            # str slicing is codepoint-safe (never splits a multibyte sequence).
            blob["normalized_text_truncated"] = True
            full_preview = blob["normalized_text"]
            lo, hi, best = 0, len(full_preview), 0
            while lo <= hi:
                mid = (lo + hi) // 2
                blob["normalized_text"] = full_preview[:mid]
                if _detail_bytes(blob) <= _MAX_DETAIL_BYTES:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            blob["normalized_text"] = full_preview[:best]

        if _detail_bytes(blob) > _MAX_DETAIL_BYTES:
            blob["scanner_results"] = {"count": len(scanner_results)}

        if _detail_bytes(blob) > _MAX_DETAIL_BYTES and blob["findings"]:
            shed = sorted(
                range(len(blob["findings"])),
                key=lambda i: (
                    _SEVERITY_RANK.get(blob["findings"][i]["severity"], _SEVERITY_RANK_MAX),
                    -i,
                ),
            )
            kept: list[Any] = list(blob["findings"])
            for idx in shed:
                if _detail_bytes(blob) <= _MAX_DETAIL_BYTES:
                    break
                kept[idx] = None
                blob["findings"] = [x for x in kept if x is not None]
                blob["detail_truncated"] = True
                # total = the original finding count, so this stays correct across both
                # the count-cap and this byte-shed pass.
                blob["findings_omitted"] = total - len(blob["findings"])

        return blob
    except Exception:  # never-throw: a malformed result must not break run_scan
        return {"findings": [], "detail_truncated": True, "detail_error": True}


def _enforcement_summary(ev: dict[str, Any], *, provenance: str = "unattested") -> dict[str, Any]:
    """Build the unified `scan_history` summary for a drained enforcement event (D6).

    One schema, two producers: `run_scan` writes playground summaries (no `source`,
    read as "playground"); enforcement entries carry `source="enforcement"` plus
    tool/event_type/tier/rule_id/severity/reason. A block-class event sets
    `safe=False` so the existing `safe === false` tile loop counts it with no
    tile-math change; a `bypassed_disarmed` event sets `safe=True` (visible row,
    never counted as blocked).

    PET-139: `provenance` (one of "genuine"/"unverifiable"/"unattested", D4) carries the
    spool-integrity verdict to the drill-down "is this legit?" line. Keyword-only and
    DEFAULTED so existing callers (playground summaries, the PET-131/137/138 enforcement
    tests) stay green untouched — the default reflects "no key configured".
    """
    event_type = ev.get("event_type")
    is_block = event_type in _BLOCK_EVENT_TYPES
    reason = ev.get("reason")
    if isinstance(reason, str) and len(reason) > _MAX_REASON_LEN:
        reason = reason[:_MAX_REASON_LEN]
    # PET-138: only a bypassed_disarmed heartbeat carries a count; gate on the event
    # type so a malformed/legacy non-bypass event that stamps a stray bypassed_count
    # can never feed the tile. Then normalize to a positive int (or None): a float or
    # a bool is dropped (bool via `type(...) is int` — isinstance(True, int) is True).
    # The frontend integer-gates again before summing.
    raw_count = ev.get("bypassed_count")
    bypassed_count = (
        raw_count
        if event_type == "bypassed_disarmed" and type(raw_count) is int and raw_count > 0
        else None
    )
    return {
        "scan_id": ev.get("scan_id"),
        "source": "enforcement",
        "safe": not is_block,
        "finding_count": 1 if is_block else 0,
        "duration_ms": 0.0,
        "direction": "tool_call",
        "session_id": ev.get("session_id"),
        "timestamp": ev.get("timestamp"),
        "tool": ev.get("tool"),
        "event_type": event_type,
        "tier": ev.get("tier"),
        "rule_id": ev.get("rule_id"),
        "severity": ev.get("severity"),
        "reason": reason,
        # PET-137: authoritative armed-at-decision for the drill-down provenance line
        # (D6). The plugin stamps `armed` on every event (reference_plugin emits
        # armed=True on the armed branch, armed=False on the disarmed bypass).
        "armed": ev.get("armed"),
        # PET-138: cumulative per-session disarmed-bypass count (bypassed_disarmed
        # heartbeats only; None elsewhere). Drives the "bypassed (disarmed)" tile.
        "bypassed_count": bypassed_count,
        # PET-139: spool-integrity verdict for the drill-down "is this legit?" line (D4).
        "provenance": provenance,
    }


def _persist_config(validated_config: Any) -> bool:
    """Write the petasos: section back to Hermes config.yaml.

    Returns True on success, False on failure.
    """
    import os
    import tempfile

    import yaml

    res = resolve_hermes_config_path()
    if res.warning is not None:
        _logger.warning("Hermes profile resolution: %s", res.warning)
    config_path = res.path
    if not config_path.exists():
        _logger.warning("Cannot persist config — %s not found", config_path)
        return False

    try:
        with open(config_path, encoding="utf-8") as f:
            raw = f.read()

        full = yaml.safe_load(raw)
        if not isinstance(full, dict):
            full = {}
        export = validated_config.to_dict(redact_secrets=False)
        export.pop("session_secret", None)
        export.pop("hash_key", None)
        # PET-111 BUG-A: `enabled`/`host_id` are not PetasosConfig fields (they are
        # popped before building the config), so a bare `full["petasos"] = export`
        # drops them on every Config Editor save. Merge-preserve them.
        existing = full.get("petasos")
        preserved = {}
        if isinstance(existing, dict):
            for k in ("enabled", "host_id"):
                if k in existing:
                    preserved[k] = existing[k]
        full["petasos"] = {**preserved, **export}

        fd, tmp_path = tempfile.mkstemp(
            dir=str(config_path.parent),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(full, f, default_flow_style=False, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(config_path))
        except BaseException:
            import contextlib

            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

        _logger.info("Petasos config persisted to %s", config_path)
        return True
    except Exception as exc:
        _logger.error("Failed to persist config: %s", exc)
        return False


class ConsoleHandlers:
    """Shared route handlers used by both standalone and Hermes plugin modes."""

    def __init__(self, pipeline: "Pipeline") -> None:
        self.pipeline = pipeline
        # PET-139: derive the reader-side spool-integrity key from the pipeline's config
        # (D5). This is the single construction chokepoint for BOTH standalone (`build_app`)
        # and embedded (`plugin_api.init_handlers`) modes, so `self._spool_key` is always
        # bound (no AttributeError on any drain path) and both modes obtain the key from the
        # `session_secret` the pipeline already carries. `None` => integrity off ("unattested").
        from petasos.console import _events

        self._spool_key: bytes | None = (
            _events._derive_spool_key(s) if (s := pipeline.config.session_secret) else None
        )
        # PET-139: monotonic clock for the rate-limited integrity-failure tripwire (D9). A
        # plain instance attribute is safe — every `_surface_enforcement_event` runs inside
        # `_enforcement_lock`, which already serializes the read path (no `threading.Lock`
        # needed, unlike the reference plugin's writer-thread module clocks).
        self._integrity_log_last = 0.0
        self.scan_history = RingBuffer[dict[str, Any]](maxlen=500)
        self.sse = SSEBroadcaster()
        self._start_time = time.monotonic()

        # PET-131: cross-process enforcement-event drain state. Byte offsets into the
        # spool / its rotated segment (restart-independent; not a producer seq). One
        # asyncio.Lock serializes the whole peek->push->advance->broadcast(+rotate)
        # unit so the background tailer and a concurrent get_scan_history are
        # exactly-once. The per-session block tally is the reconciliation source of
        # truth (D4) — independent of the 500-entry ring's eviction.
        self._enforcement_offset = 0
        self._rot_offset = 0
        self._enforcement_spool_path: str | None = None
        self._enforcement_lock = asyncio.Lock()
        self._block_tally: dict[str, int] = {}
        # PET-138: per-session cumulative count of disarmed bypasses, a
        # reconciliation/test source-of-truth mirroring _block_tally's role (NOT a
        # UI feed — the tile reads dedicated frontend state). Monotonic-max of the
        # cumulative count carried on bypassed_disarmed heartbeats; bounded
        # drop-oldest; resets on a dashboard restart (in-memory by design).
        self._bypass_tally: dict[str, int] = {}
        # PET-144: eviction-proof lifetime scan count. Decoupled from the 500-entry ring
        # (mirrors the PET-131/138 tally pattern): monotonic, in-memory, resets on a
        # dashboard restart by design. A single scalar, so no per-session bound.
        self._scans_total = 0
        # One-shot guard so the first ring overflow logs exactly once per run, not per scan.
        self._ring_overflow_warned = False

        pipeline.add_audit_listener(self._on_audit)
        pipeline.add_alert_listener(self._on_alert)

    def block_tally_for(self, session_id: str) -> int:
        """PET-131: per-session count of surfaced block-class enforcement events.

        The D4 reconciliation source of truth; survives ring-buffer eviction within a
        session. Resets on a dashboard restart (in-memory by design).
        """
        return self._block_tally.get(session_id, 0)

    def _bump_block_tally(self, session_id: str) -> None:
        tally = self._block_tally
        if session_id in tally:
            tally[session_id] += 1
            return
        tally[session_id] = 1
        if len(tally) > _MAX_TALLY_SESSIONS:
            # Drop-oldest by insertion order (dict is insertion-ordered).
            del tally[next(iter(tally))]

    def bypass_tally_for(self, session_id: str) -> int:
        """PET-138: per-session cumulative count of disarmed bypasses. Reconciliation
        source of truth (mirrors block_tally_for); resets on a dashboard restart."""
        return self._bypass_tally.get(session_id, 0)

    def _set_bypass_tally(self, session_id: str, count: int) -> None:
        """PET-138: set-or-refresh (NOT increment) — the carried count is an absolute
        cumulative, so the caller passes a monotonic max. An existing key is assigned
        in place (preserves insertion order, so drop-oldest still evicts the genuine
        oldest); a new key triggers the _MAX_TALLY_SESSIONS drop-oldest bound."""
        tally = self._bypass_tally
        if session_id in tally:
            tally[session_id] = count
            return
        tally[session_id] = count
        if len(tally) > _MAX_TALLY_SESSIONS:
            del tally[next(iter(tally))]

    def _log_integrity_failure(self, ev: dict[str, Any]) -> None:
        """PET-139: rate-limited WARNING tripwire for a spool-integrity failure (D9). Never raises.

        Greppable token `PETASOS_INTEGRITY_UNVERIFIABLE` plus a failure class so an operator can
        tell a forging process (`sig-mismatch`) from a key-config mistake or a legacy unsigned
        event on upgrade (`sig-missing`). Mirrors the codebase's greppable-attribution convention
        (`PETASOS_DISARMED` / `PETASOS_ARMED_RESOLUTION`). The clock is a plain instance attribute
        serialized by `_enforcement_lock` (the caller always holds it). Fail-safe and observable
        are not in tension: this never raises and never gates the drain.
        """
        try:
            now = time.monotonic()
            if now - self._integrity_log_last < _INTEGRITY_LOG_EVERY_S:
                return
            self._integrity_log_last = now
            failure_class = "sig-missing" if not isinstance(ev.get("sig"), str) else "sig-mismatch"
            _logger.warning(
                "PETASOS_INTEGRITY_UNVERIFIABLE class=%s scan_id=%s session_id=%s — spool row "
                "failed HMAC verification (forged, misconfigured, or legacy unsigned)",
                failure_class,
                ev.get("scan_id"),
                ev.get("session_id"),
            )
        except Exception:
            pass

    def _record_scan(self, summary: dict[str, Any]) -> None:
        """Single record chokepoint: append to the ring AND bump the eviction-proof
        total. Both the playground run_scan push and the drained-enforcement fold route
        here so scans_total can never diverge from what was recorded (PET-144)."""
        self.scan_history.push(summary)
        self._scans_total += 1
        if not self._ring_overflow_warned and self._scans_total > len(self.scan_history):
            self._ring_overflow_warned = True
            _logger.warning(
                "console scan-history ring at capacity (%d entries); oldest rows now "
                "evict silently. scans_total is authoritative; the history pane shows "
                "the last %d.",
                len(self.scan_history),
                len(self.scan_history),
            )

    async def _surface_enforcement_event(self, ev: dict[str, Any]) -> None:
        """Fold one drained enforcement event into scan_history + the tally + SSE.

        PET-139: classify provenance (D4) before folding. With NO key configured the event is
        "unattested" and behaves exactly as pre-PET-139 — surfaced, and a block-class event
        still bumps the tally (the no-regression path). With a key configured, a verified event
        is "genuine"; a missing or invalid `sig` is "unverifiable" — surfaced and flagged,
        logged (D9), and EXCLUDED from the authoritative block tally so a forged row can never
        be counted as a trusted block.
        """
        from petasos.console import _events

        verified = _events.verify_event(ev, self._spool_key)
        key_on = self._spool_key is not None
        provenance = "unattested" if not key_on else ("genuine" if verified else "unverifiable")
        if key_on and not verified:
            self._log_integrity_failure(ev)
        summary = _enforcement_summary(ev, provenance=provenance)
        self._record_scan(summary)
        if ev.get("event_type") in _BLOCK_EVENT_TYPES:
            # unattested + genuine count; unverifiable does NOT (D4) — a forged/legacy-unsigned
            # block is surfaced-but-flagged, never tallied as a trusted block.
            if provenance != "unverifiable":
                sid = ev.get("session_id")
                if isinstance(sid, str) and sid:
                    self._bump_block_tally(sid)
        elif ev.get("event_type") == "bypassed_disarmed":
            # PET-138: monotonic-max of the cumulative count (restart re-seed belt;
            # exactly-once delivery already comes from the forward offset / .rot
            # discipline). type(cnt) is int excludes bool; cnt > 0 skips no-ops.
            # Intentionally NOT integrity-gated: a disarmed-bypass heartbeat is safe=True,
            # never a trusted-block claim, so gating it would be scope creep (the v1 residual
            # — a forged heartbeat can inflate _bypass_tally — is named in the spec threat model).
            sid = ev.get("session_id")
            cnt = ev.get("bypassed_count")
            if isinstance(sid, str) and sid and type(cnt) is int and cnt > 0:
                self._set_bypass_tally(sid, max(self.bypass_tally_for(sid), cnt))
        await self.sse.broadcast("scan_result", summary)

    async def _drain_and_clear_rot(self, rot_path: str) -> None:
        """Drain a rotated `.rot` segment forward from `self._rot_offset`, then unlink.

        `_rot_offset` advances per recovered record and resets to 0 only after a
        successful unlink — so if the unlink fails (a Windows handle held on `.rot`)
        the next cycle does NOT re-push or re-tally the already-recovered records
        (spec round-4 edge F-1). Never raises.
        """
        import os

        from petasos.console import _events

        try:
            events, new_off = _events.drain_enforcement_events(rot_path, self._rot_offset)
        except Exception:
            events, new_off = [], self._rot_offset
        for ev in events:
            await self._surface_enforcement_event(ev)
        self._rot_offset = new_off
        try:
            os.remove(rot_path)
            self._rot_offset = 0
        except OSError:
            _logger.warning(
                "PETASOS_ENFORCEMENT could not unlink %s; will retry next cycle", rot_path
            )

    async def _drain_enforcement_into_history(self) -> None:
        """Drain the cross-process enforcement spool into scan_history + SSE (PET-131).

        Exactly-once under one asyncio.Lock: the byte offset advances inside the same
        critical section that pushes the ring and broadcasts, and any rotation runs
        inside it too, so the background tailer and a concurrent get_scan_history can
        never double-deliver or interleave a rotation. Forward-only reader -> no
        scan_id seen-set. Read-side; never raises.
        """
        import os

        from petasos.console import _events

        async with self._enforcement_lock:
            path = _events._spool_path()
            # The resolved spool can move mid-session (a Hermes profile/config path
            # switch). Stale byte offsets index a different (possibly smaller) file and
            # would skip its events, so reset to 0 and read the new spool from the start.
            if path != self._enforcement_spool_path:
                self._enforcement_offset = 0
                self._rot_offset = 0
                self._enforcement_spool_path = path
            rot = path + _events._ROT_SUFFIX
            # (1) Recover an orphan .rot from a reader that crashed mid-rotation BEFORE
            # touching the live spool, so its undrained events are never overwritten.
            if os.path.exists(rot):
                await self._drain_and_clear_rot(rot)
            # Normal forward drain of the live spool.
            try:
                events, new_offset = _events.drain_enforcement_events(
                    path, self._enforcement_offset
                )
            except Exception:
                events, new_offset = [], self._enforcement_offset
            for ev in events:
                await self._surface_enforcement_event(ev)
            self._enforcement_offset = new_offset
            # (2/3) Bounding via reader-owned rotation, off the gateway hot path.
            try:
                if _events.spool_size(path) > _events.SPOOL_CAP_BYTES:
                    if _events.rotate_spool(path):
                        # The just-renamed .rot IS the former live spool; continue
                        # from the committed live offset to capture in-flight appends,
                        # then reset the live offset to 0 for the fresh spool.
                        self._rot_offset = self._enforcement_offset
                        await self._drain_and_clear_rot(rot)
                        self._enforcement_offset = 0
                    else:
                        # Windows handle held, or a leftover .rot we could not clear:
                        # soft cap. The spool grows on disk (no telemetry loss, no
                        # double-count); the WARNING makes it observable; retry next cycle.
                        _logger.warning(
                            "PETASOS_ENFORCEMENT spool over cap; rotation skipped (will retry)"
                        )
            except Exception:
                _logger.debug("enforcement spool bounding failed", exc_info=True)

    def _on_audit(self, event: Any) -> None:
        import asyncio

        try:
            data = event.to_dict() if hasattr(event, "to_dict") else {"raw": str(event)}
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.sse.broadcast("audit", data))
        except Exception:
            _logger.debug("Console audit broadcast failed", exc_info=True)

    def _on_alert(self, alert: Any) -> None:
        import asyncio

        try:
            data = alert.to_dict() if hasattr(alert, "to_dict") else {"raw": str(alert)}
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.sse.broadcast("alert", data))
        except Exception:
            _logger.debug("Console alert broadcast failed", exc_info=True)

    async def get_config(self) -> dict[str, Any]:
        config_dict = self.pipeline.config.to_dict(redact_secrets=True)
        fields = generate_config_metadata()
        sections = generate_section_metadata()
        # PET-124: the strength-preset registry and the derived active level. The
        # comparator is passed the PetasosConfig object (not the redacted payload
        # dict) — no preset-owned field is a secret, so redaction cannot perturb it.
        return {
            "config": config_dict,
            "fields": fields,
            "sections": sections,
            "presets": generate_preset_metadata(),
            "active_preset": resolve_active_preset(self.pipeline.config),
        }

    async def update_config(
        self, body: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]] | None]:
        current = self.pipeline.config.to_dict()
        current.pop("session_secret", None)
        merged = {**current, **body}
        try:
            from petasos.config import PetasosConfig

            validated = PetasosConfig.from_dict(merged)
        except (ValueError, TypeError) as exc:
            msg = str(exc)
            field = _extract_field_from_error(msg, body)
            return None, [{"field": field, "message": msg}]
        # PET-126: route through reconfigure so the change takes effect on the
        # running pipeline (frequency, escalation, audit verbosity, alerting, and
        # decode_encoded_payloads all live-update), not just on a new session. A
        # bare ``self.pipeline._config = validated`` only updated the fields read
        # directly off _config at scan time.
        try:
            self.pipeline.reconfigure(validated)
        except (ValueError, TypeError) as exc:
            # from_dict validates structure, but frequency_weights content (glob
            # position, non-negative/finite values) is validated inside
            # FrequencyTracker.apply_config during reconfigure. Surface that as a
            # structured field error (422), not an unhandled 500. reconfigure is
            # atomic (Decision 5), so the live config is unchanged on failure and
            # we do not persist a config that could not be applied.
            msg = str(exc)
            field = _extract_field_from_error(msg, body)
            return None, [{"field": field, "message": msg}]
        persisted = _persist_config(validated)
        result = {
            "config": validated.to_dict(redact_secrets=True),
            "fields": generate_config_metadata(),
            "sections": generate_section_metadata(),
            # PET-124: recompute the dial level from the freshly validated config so
            # the editor re-render reflects the just-applied preset (or Custom).
            "presets": generate_preset_metadata(),
            "active_preset": resolve_active_preset(validated),
        }
        if not persisted:
            result["warning"] = "Config applied in memory but failed to persist to disk"
        return result, None

    async def run_scan(
        self,
        text: str,
        direction: str = "inbound",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        result = await self.pipeline.inspect(
            text,
            direction=direction,  # type: ignore[arg-type]  # validated upstream
            session_id=session_id,
        )

        cfg = self.pipeline.config
        # PET-137: keep the full NormalizedText (not just `.normalized`) so the detail
        # blob can carry `transformations_applied`; the bare string still feeds the
        # HTTP response below.
        norm = normalize(
            text,
            nfkc=cfg.normalize_nfkc,
            strip_zero_width=cfg.strip_zero_width,
            map_homoglyphs=cfg.map_homoglyphs,
            detect_rtl=cfg.detect_rtl_override,
            fold_leet=cfg.fold_leet,
        )
        normalized_text = norm.normalized

        scan_id = f"s-{uuid.uuid4().hex[:6]}"
        summary: dict[str, Any] = {
            "scan_id": scan_id,
            "safe": result.safe,
            "finding_count": len(result.findings),
            "duration_ms": sum((sr.duration_ms or 0.0) for sr in result.scanner_results),
            "direction": direction,
            "session_id": session_id,  # PET-102: required by the Observability *sessions* tile
            "timestamp": time.time(),
            # PET-137: bounded detail blob so a playground row can drill down (D2/D-CAP).
            "detail": _build_playground_detail(result, norm),
        }
        self._record_scan(summary)
        await self.sse.broadcast("scan_result", summary)

        return {
            "result": result.to_dict(),
            "normalized_text": normalized_text,
            "scan_id": scan_id,
            "session_id": session_id,
        }

    async def get_health(self) -> dict[str, Any]:
        cfg = self.pipeline.config
        config_hash = hashlib.sha256(
            json.dumps(cfg.to_dict(redact_secrets=True), sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        return {
            "pipeline": {
                "fail_mode": cfg.fail_mode,
                "scanner_count": len(self.pipeline.scanner_health()),
                "config_hash": config_hash,
                "uptime_seconds": round(time.monotonic() - self._start_time, 1),
                "scans_total": self._scans_total,  # PET-144: eviction-proof lifetime count
            },
            "scanners": self.pipeline.scanner_health(),
            "feature_status": dict(self.pipeline._build_feature_status()),
        }

    async def get_scan_history(self, limit: int = 100) -> dict[str, Any]:
        # PET-131: drain-on-read is the floor that surfaces live enforcement on the
        # gated-mode polling fallback (PET-83) and in the embedded Hermes plugin path
        # (no FastAPI startup tailer there). The background tailer is the live-SSE
        # latency optimization on top; both share the exactly-once drain.
        await self._drain_enforcement_into_history()
        clamped = min(max(1, limit), 1000)
        return {"entries": list(reversed(self.scan_history.to_list(clamped)))}

    async def get_profiles(self) -> dict[str, Any]:
        return {"profiles": self.pipeline.list_profiles()}

    async def get_about(self) -> dict[str, Any]:
        import petasos

        return {
            # PET-141: source the version from the package single-source; no
            # hardcoded fallback (a literal can only mask a real packaging defect).
            "version": petasos.__version__,
            "repo_url": "https://github.com/Vigil-Harbor/Petasos",
            "license": "MIT",
            "description": (
                "Pluggable, session-aware content security pipeline for Python AI agents"
            ),
            "donation": {
                "message": (
                    "Did Petasos prevent a disaster? Every feature is"
                    " free, forever. If this saved your team from a"
                    " bad day, a coffee keeps the lights on."
                ),
                "url": "https://github.com/sponsors/Vigil-Harbor",
            },
            "credits": [
                "Vigil Harbor — maintainer",
                "Built with FastAPI, Python, vanilla JS",
            ],
        }

    async def get_armed(self) -> dict[str, Any]:
        # PET-111: the Equipped/Unequipped master bit. File-backed (petasos.enabled)
        # via the shared _paths resolver — the dashboard reads what the gateway reads.
        from petasos.console._armed import read_armed

        return {"armed": read_armed()}

    async def set_armed(self, armed: bool) -> tuple[dict[str, Any], bool]:
        from petasos.console._armed import write_armed

        ok = write_armed(armed)
        if ok:
            # PET-116: live cross-tab sync. Broadcast the authoritative value only
            # on a persisted flip, so every other open `obs` tab adopts file-truth
            # within one SSE frame. A failed write (503) emits nothing — other tabs
            # must not be told the file changed when it did not. Awaited directly
            # (not loop.create_task'd like _on_audit/_on_alert) because set_armed
            # already runs in the route's event loop; no try/except is needed — the
            # payload is trivially serializable and broadcast suppresses QueueFull
            # internally over a list() snapshot, so it cannot raise here.
            await self.sse.broadcast("armed", {"armed": armed})
        return {"armed": armed, "persisted": ok}, ok


def _extract_field_from_error(msg: str, body: dict[str, Any]) -> str:
    # Return the MOST SPECIFIC (longest) body key named in the error message.
    # A first-match scan mis-attributes when one field name is a substring of
    # another the body also carries (e.g. ``presidio_entities`` vs
    # ``presidio_entities_extra``): the error names the longer field but the
    # shorter one matched first. Longest-match makes the 422 point at the field
    # the validator actually rejected.
    best = ""
    for key in body:
        if key in msg and len(key) > len(best):
            best = key
    return best or "unknown"


def build_app(pipeline: "Pipeline", *, auth_token: str | None = None) -> "FastAPI":
    """Build the complete FastAPI application.

    PET-125: when *auth_token* is a non-blank string, every ``/api/*`` route
    requires an ``Authorization: Bearer <token>`` credential. ``auth_token=None``
    (the default) means no auth — byte-for-byte the prior zero-config behavior.
    A set-but-blank token (``""`` / whitespace, from any caller including the
    ``serve()`` env path) logs one WARNING and is treated as no auth. A non-blank
    token is stored and compared verbatim; ``.strip()`` decides on/off only and
    never alters the token.
    """
    import importlib.resources

    from fastapi import Depends, Header, HTTPException, Request
    from fastapi import FastAPI as _FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles

    import petasos

    # PET-141: bind the package version once so both FastAPI constructions (and the
    # package) can never drift — D3 single source for the OpenAPI version field.
    _version = petasos.__version__

    # PET-125: normalize the token once, centrally, so the env path (serve) and a
    # programmatic auth_token= argument agree. Single WARNING site for set-but-blank.
    resolved_token: str | None
    if auth_token is None:
        resolved_token = None
    elif auth_token.strip() == "":
        _logger.warning("PETASOS console auth token is set but blank; console auth disabled")
        resolved_token = None
    else:
        resolved_token = auth_token

    if resolved_token is None:
        app = _FastAPI(title="Petasos Console", version=_version)
    else:
        token: str = resolved_token  # non-Optional capture for the closure below

        def _require_console_token(
            request: Request,
            authorization: str | None = Header(default=None),
        ) -> None:
            # PET-125: deny-by-prefix. Only /api/* is gated; GET / (the HTML shell)
            # and the /static mount stay ungated so the page and assets still load
            # with the token on. INVARIANT: every sensitive route MUST live under
            # /api/ — a future non-asset route added outside /api/ would be served
            # unauthenticated (see hardening.md section 6). Relies on Starlette's
            # already-normalized request.url.path.
            if not request.url.path.startswith("/api/"):
                return
            # Parse defensively: never index/split before the prefix check, so a
            # malformed header is a clean 401, never a 500. Scheme match is
            # case-sensitive ("bearer " does not match).
            if authorization is None or not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
            credential = authorization[len("Bearer ") :]
            if not hmac.compare_digest(credential.encode("utf-8"), token.encode("utf-8")):
                raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})

        app = _FastAPI(
            title="Petasos Console",
            version=_version,
            dependencies=[Depends(_require_console_token)],
        )

    handlers = ConsoleHandlers(pipeline)

    static_dir = importlib.resources.files("petasos.console") / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # PET-131: background enforcement-spool tailer (standalone live-SSE latency).
    # Embedded Hermes-plugin mode mounts the bare router and never runs this
    # lifecycle; there the drain-on-read in get_scan_history is the floor.
    _enforcement_tailer: dict[str, Any] = {"task": None}

    @app.on_event("startup")
    async def _startup() -> None:
        async def _tail() -> None:
            while True:
                try:
                    await handlers._drain_enforcement_into_history()
                except Exception:
                    _logger.debug("enforcement tailer drain failed", exc_info=True)
                await asyncio.sleep(_ENFORCEMENT_TAIL_INTERVAL_S)

        _enforcement_tailer["task"] = asyncio.create_task(_tail())

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        task = _enforcement_tailer.get("task")
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await handlers.sse.shutdown()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html_path = static_dir / "index.html"
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/config")
    async def api_get_config() -> dict[str, Any]:
        return await handlers.get_config()

    @app.put("/api/config")
    async def api_update_config(request: Request) -> Any:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                status_code=422,
                content={"detail": [{"field": "body", "message": "Invalid JSON"}]},
            )
        if not isinstance(body, dict):
            return JSONResponse(
                status_code=422,
                content={"detail": [{"field": "body", "message": "Expected JSON object"}]},
            )
        result, errors = await handlers.update_config(body)
        if errors is not None:
            return JSONResponse(status_code=422, content={"detail": errors})
        return result

    @app.post("/api/scan")
    async def api_run_scan(request: Request) -> Any:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                status_code=422,
                content={"detail": [{"field": "body", "message": "Invalid JSON"}]},
            )
        if not isinstance(body, dict):
            return JSONResponse(
                status_code=422,
                content={"detail": [{"field": "body", "message": "Expected JSON object"}]},
            )
        text = body.get("text", "")
        if not isinstance(text, str) or not text.strip():
            err = {"field": "text", "message": "Text must be a non-empty string"}
            return JSONResponse(status_code=422, content={"detail": [err]})
        if len(text) > _MAX_SCAN_TEXT_LEN:
            msg = f"Text exceeds {_MAX_SCAN_TEXT_LEN} character limit"
            err = {"field": "text", "message": msg}
            return JSONResponse(status_code=422, content={"detail": [err]})
        direction = body.get("direction", "inbound")
        if not isinstance(direction, str) or direction not in _VALID_DIRECTIONS:
            err = {"field": "direction", "message": "Must be 'inbound' or 'outbound'"}
            return JSONResponse(status_code=422, content={"detail": [err]})
        try:
            session_id = sanitize_session_id(body.get("session_id"))
        except SessionIdError as exc:
            err = {"field": "session_id", "message": str(exc)}
            return JSONResponse(status_code=422, content={"detail": [err]})
        try:
            return await handlers.run_scan(text, direction=direction, session_id=session_id)
        except Exception as exc:  # PET-99 D8: defense-in-depth; pipeline.inspect never throws
            _logger.exception("console scan failed")
            return JSONResponse(
                status_code=500,
                content={"detail": [{"field": "scan", "message": str(exc)}]},
            )

    @app.get("/api/health")
    async def api_get_health() -> dict[str, Any]:
        return await handlers.get_health()

    @app.get("/api/scan-history")
    async def api_get_scan_history(limit: int = 100) -> dict[str, Any]:
        return await handlers.get_scan_history(limit)

    @app.get("/api/profiles")
    async def api_get_profiles() -> dict[str, Any]:
        return await handlers.get_profiles()

    @app.get("/api/events")
    async def api_events() -> StreamingResponse:
        q = handlers.sse.subscribe()
        return StreamingResponse(
            handlers.sse.stream(q),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/about")
    async def api_get_about() -> dict[str, Any]:
        return await handlers.get_about()

    @app.get("/api/armed")
    async def api_get_armed() -> dict[str, Any]:
        return await handlers.get_armed()

    @app.post("/api/armed")
    async def api_set_armed(request: Request) -> Any:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                status_code=422,
                content={"detail": [{"field": "body", "message": "Invalid JSON"}]},
            )
        # bool-strict: isinstance(True, int) is True, but isinstance(1, bool) is False,
        # so 1 / "true" / null / missing all reject. Non-dict body rejects first.
        if not isinstance(body, dict) or not isinstance(body.get("armed"), bool):
            return JSONResponse(
                status_code=422,
                content={"detail": [{"field": "armed", "message": "Must be a boolean"}]},
            )
        result, ok = await handlers.set_armed(body["armed"])
        if not ok:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": [
                        {"field": "armed", "message": "Failed to persist armed state to disk"}
                    ]
                },
            )
        return result

    return app
