"""Replay Hermes v0.23.1 messages offline, without importing or running Hermes.

Read every stored row (including archived/rewound rows), in insertion order.
This measures stored records, not a deduplicated reconstruction of live hooks.
Only built-in scanners are enabled; no host settings or secrets are loaded.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
from collections import Counter
from contextlib import closing, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from petasos.config import Secrets, Settings, resolve
from petasos.config.layers import LEVELS, ROLES
from petasos.enforce import Approve, Block, Enforcer, HostInfo, SettingsSnapshot, ToolCall
from petasos.model import AuditEvent, severity_rank
from petasos.pipeline.ingest import scan_ingestion_result

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from petasos.pipeline.ingest import IngestionScanResult


def open_store(path: str, *, mode: str = "ro") -> sqlite3.Connection:
    """Open a filesystem path using only SQLite's read-only URI mode.

    URI inputs are deliberately refused: their query parameters cannot change
    the mode, VFS or cache settings of the URI constructed here.
    """
    if mode != "ro" or path.startswith("file:"):
        raise ValueError("only a filesystem path and mode=ro are accepted")
    connection = sqlite3.connect(Path(path).expanduser().resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


class ReplayClock:
    """Stored epoch time, with regressions clamped to the previous reading."""

    def __init__(self) -> None:
        self.now = 0.0
        self.regressions = 0

    def set(self, timestamp: object) -> None:
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError("invalid message timestamp")
        if timestamp < self.now:
            self.regressions += 1
        self.now = max(self.now, timestamp)

    def monotonic(self) -> float:
        return self.now


@contextmanager
def quiet_library() -> Iterator[None]:
    """Library diagnostics can contain excerpts; expose only our safe report."""
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def _json(raw: str, row_id: int, field: str) -> Any:
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise ValueError(f"message {row_id}: invalid {field}") from None


def _calls(row: sqlite3.Row) -> Iterator[ToolCall]:
    if not row["tool_calls"]:
        return
    calls = _json(row["tool_calls"], row["id"], "tool_calls")
    if not isinstance(calls, list):
        raise ValueError(f"message {row['id']}: tool_calls must be a list")
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise ValueError(f"message {row['id']}: invalid tool function")
        args = function.get("arguments", {})
        if isinstance(args, str):
            args = _json(args, row["id"], "arguments")
        if not isinstance(args, dict) or not isinstance(call.get("id"), str):
            raise ValueError(f"message {row['id']}: invalid tool call")
        yield ToolCall(function["name"], args, session=row["session_id"], tool_call_id=call["id"])


def _metadata(call: ToolCall, row_id: int, phase: str, size: int) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "message_id": row_id,
        "session_id": call.session,
        "tool": call.tool,
        "phase": phase,
        "chars": size,
    }
    for key in ("path", "file_path", "filename", "target_path"):
        value = call.args.get(key)
        if isinstance(value, str) and value:
            metadata["file"] = value.replace("\\", "/").rsplit("/", 1)[-1]
            break
    return metadata


class Report:
    """Keep metadata only; never retain an excerpt, result, reason or argument."""

    def __init__(self, *, all_findings: bool) -> None:
        self.all_findings = all_findings
        self.counts: Counter[str] = Counter()
        self.flags: Counter[tuple[str, str]] = Counter()
        self.decisions: list[dict[str, Any]] = []
        self.findings: list[dict[str, Any]] = []
        self.tiers: dict[str, str] = {}
        self.current: dict[str, Any] = {}
        self.events: list[dict[str, str]] = []
        self.failed: set[tuple[int, str]] = set()

    def scan_failed(self) -> None:
        key = (self.current["message_id"], self.current["phase"])
        if key not in self.failed:
            self.failed.add(key)
            self.counts["scan_failures"] += 1

    def emit(self, event: Mapping[str, object]) -> bool:
        safe = {
            key: value
            for key in ("event_type", "rule_id")
            if isinstance((value := event.get(key)), str)
        }
        self.events.append(safe)
        if safe.get("event_type") == "ingest_flagged":
            self.counts["flags"] += 1
            self.flags[(safe["rule_id"], self.current["tool"])] += 1
        if safe.get("event_type") == "ingest_unscanned" or event.get("param_scan_degraded"):
            self.scan_failed()
        return True

    def finding(self, rule: str, severity: str) -> None:
        if self.all_findings or severity_rank(severity) >= severity_rank("high"):
            self.findings.append({**self.current, "rule": rule, "severity": severity})

    def audit(self, event: AuditEvent) -> None:
        if self.current["phase"] == "call":
            for finding in event.payload.get("findings", ()):
                self.finding(finding["rule_id"], finding["severity"])
        tier = event.payload.get("escalation_tier")
        if tier in ("tier1", "tier2", "tier3"):
            session = self.current["session_id"]
            self.tiers[session] = max(self.tiers.get(session, "none"), tier)

    async def ingestion(self, *args: Any, **kwargs: Any) -> IngestionScanResult:
        # Observe the real merged head+sweep result; do not scan a second time.
        try:
            result = await scan_ingestion_result(*args, **kwargs)
        except Exception:
            self.scan_failed()
            raise
        if result.errors or result.inspect_failed or result.head is None:
            self.scan_failed()
        self.counts["results_scanned"] += 1
        # The head and sweep can report the same rule at different positions.
        # List each rule/severity once per stored message, without positions.
        for rule, severity in sorted({(f.rule_id, f.severity.value) for f in result.findings}):
            self.finding(rule, severity)
        return result

    def decision(self, decision: object) -> None:
        if not isinstance(decision, (Approve, Block)):
            return
        kind = "ask" if isinstance(decision, Approve) else "block"
        self.counts[kind + "s"] += 1
        rule = (
            decision.rule_key
            if isinstance(decision, Approve)
            else next(
                (event["rule_id"] for event in reversed(self.events) if event.get("rule_id")),
                "petasos.policy."
                + next((event["event_type"] for event in reversed(self.events)), "block"),
            )
        )
        self.decisions.append({**self.current, "decision": kind, "rule": rule})

    def output(self, job: str, strictness: str, regressions: int) -> dict[str, Any]:
        return {
            "job": job,
            "strictness": strictness,
            "counts": {
                key: self.counts[key]
                for key in (
                    "messages",
                    "conversations",
                    "calls",
                    "results",
                    "results_scanned",
                    "results_skipped",
                    "unmatched_results",
                    "flags",
                    "blocks",
                    "asks",
                    "scan_failures",
                )
            },
            "timestamp_regressions": regressions,
            "flags_by_rule_and_tool": [
                {"rule": rule, "tool": tool, "count": count}
                for (rule, tool), count in sorted(self.flags.items())
            ],
            "decisions": self.decisions,
            "tier_rises": [
                {"session_id": session, "tier": tier}
                for session, tier in sorted(self.tiers.items())
            ],
            "findings": self.findings,
        }


def replay(
    path: str, *, job: str = "research", strictness: str = "relaxed", all_findings: bool = False
) -> dict[str, Any]:
    """Analyze a store with the normal config resolver and host-neutral enforcer."""
    config = resolve(
        Settings(
            role=job,
            level=strictness,
            overrides={
                "scanners": {
                    name: {"enabled": "off"} for name in ("prompt_guard", "presidio", "semgrep")
                }
            },
        )
    ).config
    snapshot = SettingsSnapshot(True, config, Secrets(), "replay")
    report = Report(all_findings=all_findings)
    clock = ReplayClock()
    pending: dict[tuple[str, str | None], ToolCall] = {}
    sessions: set[str] = set()
    with (
        closing(open_store(path)) as store,
        quiet_library(),
        patch("petasos.session.frequency.time", clock),
        patch("petasos.enforce.results.scan_ingestion_result", report.ingestion),
    ):
        enforcer = Enforcer(
            lambda: snapshot,
            events=report,
            host=HostInfo(host_id="hermes", approve_directive=True, subagent_hooks=False),
        )
        try:
            enforcer.start()
            if not enforcer.settle() or enforcer.status().state != "ready":
                raise ValueError("enforcer failed to initialize")
            # Enforcer has no public pipeline accessor. Use the existing audit
            # listener internally in this measurement script, without a new API.
            engine = enforcer._core.engine
            if engine is None:
                raise ValueError("enforcer has no pipeline")
            engine.pipeline.add_audit_listener(report.audit)
            rows = store.execute(
                "SELECT id, session_id, role, content, tool_call_id, tool_calls, "
                "tool_name, timestamp FROM messages ORDER BY id"
            )
            for row in rows:
                report.counts["messages"] += 1
                clock.set(row["timestamp"])
                session = row["session_id"]
                sessions.add(session)
                if row["role"] == "assistant":
                    for call in _calls(row):
                        pending[(session, call.tool_call_id)] = call
                        report.current = _metadata(
                            call, row["id"], "call", len(json.dumps(call.args))
                        )
                        report.events.clear()
                        report.counts["calls"] += 1
                        report.decision(enforcer.tool_call(call))
                elif row["role"] == "tool":
                    report.counts["results"] += 1
                    matched = pending.pop((session, row["tool_call_id"]), None)
                    if matched is None:
                        report.counts["unmatched_results"] += 1
                    call = (
                        matched
                        if matched is not None
                        else ToolCall(
                            row["tool_name"] or "",
                            session=session,
                            tool_call_id=row["tool_call_id"],
                        )
                    )
                    result = row["content"]
                    if isinstance(result, str) and result.startswith("\x00json:"):
                        result = _json(result[6:], row["id"], "content")
                    report.current = _metadata(
                        call, row["id"], "result", len(row["content"] or "")
                    )
                    report.events.clear()
                    before = report.counts["results_scanned"]
                    enforcer.tool_result(call, result)
                    if report.counts["results_scanned"] == before:
                        report.counts["results_skipped"] += 1
                    enforcer.tool_finished(call, result if isinstance(result, str) else "")
                tier = enforcer.session_tier(session)
                if tier in ("tier1", "tier2", "tier3"):
                    report.tiers[session] = max(report.tiers.get(session, "none"), tier)
        finally:
            enforcer.close()
    report.counts["conversations"] = len(sessions)
    return report.output(job, strictness, clock.regressions)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay stored Hermes tool calls offline; execute nothing. "
            "Point at a copy of state.db or a store you own. Opened only with mode=ro."
        )
    )
    parser.add_argument("store", help="filesystem path to Hermes state.db (messages table)")
    parser.add_argument("--job", choices=tuple(ROLES), default="research")
    parser.add_argument("--strictness", choices=tuple(LEVELS), default="relaxed")
    parser.add_argument("--all", action="store_true", help="list findings of every severity")
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    args = parser.parse_args(argv)
    try:
        report = replay(
            args.store, job=args.job, strictness=args.strictness, all_findings=args.all
        )
    except (ValueError, sqlite3.Error, OSError):
        # Never echo exception messages: malformed input may contain private text.
        parser.exit(
            2, "Replay failed: check the store path, messages schema and stored records.\n"
        )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"Replay: job={args.job} strictness={args.strictness}")
        print("Counts: " + json.dumps(report["counts"], sort_keys=True))
        print(f"Timestamp regressions clamped: {report['timestamp_regressions']}")
        for section in ("flags_by_rule_and_tool", "decisions", "tier_rises", "findings"):
            print(section + ":")
            for item in report[section]:
                print("  " + json.dumps(item, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
