#!/usr/bin/env python3
"""PET-135 offline replay harness.

Recovers real tool-call arguments (and, secondarily, message content) from
Hermes ``request_dump_*.json`` session transcripts and re-runs them through the
Petasos ``Pipeline`` offline, under a chosen profile, to regenerate the
per-finding ``rule_id`` / ``severity`` / ``confidence`` ground truth that the
disarmed live deployment never recorded (its enforcement spool logs
``rule_id=null`` while ``armed:false``).

Fidelity model (matches the live Hermes integration, profiles/<p>/plugins/petasos):
  * The enforced path is ``pre_tool_call`` -> ``ToolCallGuard.evaluate`` ->
    ``_scan_params`` -> ``pipeline.inspect(param_text, direction="outbound")``.
    So tool-call args are scanned OUTBOUND. ``param_text`` is built exactly as
    ``guard._scan_params``: each param value, raw if ``str`` else
    ``safe_json_dumps(value)``, joined by ``"\n"``.
  * There is NO inbound-message hook in the live plugin; user/assistant message
    content is scanned here only as a SECONDARY view (``--include-messages``) and
    is clearly labelled non-enforced.
  * "Would block" mirrors the plugin: a non-PII finding at HIGH or CRITICAL
    (the ordinal ``_blocks`` gate) on a dangerous (non-read-only) tool.

Determinism: only ``MinimalScanner`` is wired (zero-dep, always-on, the layer
the regression corpus pins). ML backends (LLM Guard / LlamaFirewall / Presidio)
are intentionally excluded — they are nondeterministic across model/version and
their findings are the ``confidence_floor`` lever, analysed separately.

Usage:
  python scripts/pet135_replay.py --sessions <dir> --out <dir> [--include-messages]

Outputs (under --out):
  records.jsonl     one row per (scope, tool/role, profile) with findings
  per_rule.json     aggregate per-rule_id table (counts/sessions/sev/conf), per profile
  summary.json      headline counts + would-block deltas
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Repo-relative import (run from the repo root or with it on sys.path).
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from petasos import PetasosConfig, Pipeline  # noqa: E402
from petasos.scanners import MinimalScanner  # noqa: E402
from petasos.session._safe_json import safe_json_dumps  # noqa: E402

if TYPE_CHECKING:
    from petasos._types import Direction

_BLOCKING_SEVERITIES = {"critical", "high"}


# --------------------------------------------------------------------------
# Redaction — request_dumps are RAW (unredacted) request bodies. Every snippet
# that leaves this harness (examples, fixtures) must be scrubbed. We keep the
# structural trigger (what made the rule fire) and mask only secrets/PII.
# --------------------------------------------------------------------------

_REDACTORS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<EMAIL>"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE), "Bearer <TOKEN>"),
    (re.compile(r"\b(sk|pk|ghp|gho|xoxb|xoxp)-[A-Za-z0-9_\-]{8,}"), r"\1-<REDACTED>"),
    (re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"']+"), r"C:\\Users\\<USER>"),
    (re.compile(r"/(?:home|Users)/[^/\s\"']+"), "/home/<USER>"),
    (re.compile(r"\b(\d{1,3}\.){3}\d{1,3}\b"), "<IP>"),
]


def redact(text: str, cap: int = 200) -> str:
    out = text
    for pat, repl in _REDACTORS:
        out = pat.sub(repl, out)
    # Collapse very long base64/hex blobs so an example stays legible + safe.
    out = re.sub(
        r"([A-Za-z0-9+/]{12})[A-Za-z0-9+/]{12,}(={0,2})",
        r"\1...\2",
        out,
    )
    if len(out) > cap:
        out = out[:cap] + "...[snip]"
    return out


# --------------------------------------------------------------------------
# Extraction from request_dump_*.json (Codex /responses API shape)
# --------------------------------------------------------------------------


@dataclass
class ToolCall:
    session_id: str
    tool: str
    params: dict[str, Any]
    source_file: str


@dataclass
class Message:
    session_id: str
    role: str
    text: str
    source_file: str


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            if isinstance(c, dict):
                t = c.get("text") or c.get("content") or ""
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(c, str):
                parts.append(c)
        return "\n".join(parts)
    return ""


def extract_from_dump(path: Path) -> tuple[list[ToolCall], list[Message]]:
    tool_calls: list[ToolCall] = []
    messages: list[Message] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  ! skip {path.name}: {exc}", file=sys.stderr)
        return tool_calls, messages

    session_id = data.get("session_id") or path.stem
    body = (data.get("request") or {}).get("body") or {}
    items = body.get("input")
    if not isinstance(items, list):
        return tool_calls, messages

    for item in items:
        if not isinstance(item, dict):
            continue
        itype = item.get("type", "")
        if itype == "function_call" or ("name" in item and "arguments" in item):
            name = item.get("name", "")
            raw_args = item.get("arguments", "")
            try:
                params = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:  # noqa: BLE001
                params = {"_raw_arguments": raw_args}
            if not isinstance(params, dict):
                params = {"_value": params}
            tool_calls.append(ToolCall(session_id, name, params, path.name))
        elif itype == "message" or "role" in item:
            role = item.get("role", "unknown")
            text = _content_to_text(item.get("content"))
            if text:
                messages.append(Message(session_id, role, text, path.name))
        # function_call_output / reasoning / other -> ignored for the primary view
    return tool_calls, messages


def extract_from_statedb(db_path: Path) -> tuple[list[ToolCall], list[Message]]:
    """Pull the full tool-call + message corpus from a Hermes ``state.db``.

    Outbound tool calls come from assistant rows' ``tool_calls`` (a JSON list of
    ``{function:{name, arguments}}``). Inbound content = user ``content`` and
    tool-result ``content`` rows.
    """
    tool_calls: list[ToolCall] = []
    messages: list[Message] = []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.execute("select session_id, role, content, tool_calls, tool_name from messages")
        for session_id, role, content, raw_tc, tool_name in cur:
            session_id = session_id or "unknown"
            if role == "assistant" and raw_tc and raw_tc not in ("None", ""):
                try:
                    calls = json.loads(raw_tc)
                except Exception:  # noqa: BLE001
                    calls = []
                if isinstance(calls, dict):
                    calls = [calls]
                for call in calls if isinstance(calls, list) else []:
                    if not isinstance(call, dict):
                        continue
                    fn = call.get("function") or call
                    name = fn.get("name", "") if isinstance(fn, dict) else ""
                    raw_args = fn.get("arguments", "") if isinstance(fn, dict) else ""
                    try:
                        params = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:  # noqa: BLE001
                        params = {"_raw_arguments": raw_args}
                    if not isinstance(params, dict):
                        params = {"_value": params}
                    tool_calls.append(ToolCall(session_id, name, params, db_path.name))
            elif role in ("user", "tool"):
                text = content if isinstance(content, str) and content not in ("None", "") else ""
                if text:
                    label = "user" if role == "user" else f"tool_result:{tool_name or '?'}"
                    messages.append(Message(session_id, label, text, db_path.name))
    finally:
        con.close()
    return tool_calls, messages


def build_param_text(params: dict[str, Any]) -> str:
    """Mirror ToolCallGuard._scan_params param-text construction exactly."""
    parts: list[str] = []
    for value in params.values():
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(value)
        else:
            parts.append(safe_json_dumps(value))
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------


def make_pipeline(ml: bool = False) -> Pipeline:
    """MinimalScanner pipeline. decode_encoded_payloads=True matches the live
    gibson config (PET-98 on); normalize() defaults match fold_leet/homoglyph/
    rtl/zero-width/nfkc all-on in the live config.

    ml=True additionally wires the ML backends that verify available, mirroring
    the live armed deployment (MinimalScanner + LLM Guard + LlamaFirewall +
    Presidio). NONDETERMINISTIC — use only for the ML FP census, never for the
    regression corpus.
    """
    cfg = PetasosConfig(profile_name=None)
    scanners: list[Any] = [MinimalScanner(decode_encoded_payloads=True)]
    if ml:
        from petasos.scanners import (  # noqa: PLC0415
            LlamaFirewallScanner,
            LlmGuardScanner,
            PresidioScanner,
        )

        for cls in (LlmGuardScanner, LlamaFirewallScanner, PresidioScanner):
            try:
                inst = cls()
                ok, _reason, _ = inst.availability()
                if ok:
                    scanners.append(inst)
                    print(f"  ML scanner active: {inst.name}")
            except Exception as exc:  # noqa: BLE001
                print(f"  ML scanner {cls.__name__} unavailable: {exc}")
    return Pipeline(config=cfg, scanners=scanners)


@dataclass
class Finding:
    rule_id: str
    severity: str
    confidence: float
    finding_type: str
    message: str
    matched_text: str


async def scan_one(
    pipe: Pipeline, text: str, direction: Direction, profile: str | None
) -> list[Finding]:
    res = await pipe.inspect(text, direction=direction, profile=profile)
    out: list[Finding] = []
    for f in res.findings:
        out.append(
            Finding(
                rule_id=f.rule_id,
                severity=f.severity.value,
                confidence=f.confidence,
                finding_type=f.finding_type,
                message=f.message,
                matched_text=redact(f.matched_text or ""),
            )
        )
    return out


def would_block(findings: list[Finding]) -> bool:
    return any(f.severity in _BLOCKING_SEVERITIES and f.finding_type != "pii" for f in findings)


@dataclass
class RuleAgg:
    count: int = 0
    sessions: set[str] = field(default_factory=set)
    severities: set[str] = field(default_factory=set)
    confidences: list[float] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", help="dir containing request_dump_*.json")
    ap.add_argument("--statedb", help="Hermes state.db (full transcript store)")
    ap.add_argument("--out", required=True, help="output dir")
    ap.add_argument(
        "--include-messages",
        action="store_true",
        help="also scan message content inbound (NON-enforced view)",
    )
    ap.add_argument(
        "--profiles", default="none,code_generation", help="comma list; 'none' == no profile"
    )
    ap.add_argument(
        "--ml",
        action="store_true",
        help="wire ML backends (LLM Guard/LlamaFirewall/Presidio) — NONDETERMINISTIC",
    )
    ap.add_argument(
        "--sample",
        type=int,
        default=0,
        help="deterministic stride-sample of N unique tool calls (0=all)",
    )
    args = ap.parse_args()

    if not args.sessions and not args.statedb:
        ap.error("provide at least one of --sessions or --statedb")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    profiles = [None if p == "none" else p for p in args.profiles.split(",")]

    all_calls: list[ToolCall] = []
    all_msgs: list[Message] = []
    dumps: list[Path] = []
    if args.sessions:
        dumps = sorted(Path(args.sessions).glob("request_dump_*.json"))
        print(f"Found {len(dumps)} request dumps in {args.sessions}")
        for d in dumps:
            tc, ms = extract_from_dump(d)
            all_calls.extend(tc)
            all_msgs.extend(ms)
    if args.statedb:
        tc, ms = extract_from_statedb(Path(args.statedb))
        print(f"state.db: {len(tc)} tool calls, {len(ms)} messages from {args.statedb}")
        all_calls.extend(tc)
        all_msgs.extend(ms)

    # Dedup identical (session, tool, param_text) tool calls — a later request's
    # history repeats earlier calls; counting duplicates would inflate fire rates.
    seen: set[tuple[str, str, str]] = set()
    uniq_calls: list[tuple[ToolCall, str]] = []
    for c in all_calls:
        pt = build_param_text(c.params)
        key = (c.session_id, c.tool, pt)
        if key in seen:
            continue
        seen.add(key)
        uniq_calls.append((c, pt))

    seen_m: set[tuple[str, str]] = set()
    uniq_msgs: list[Message] = []
    for m in all_msgs:
        key_m = (m.session_id, m.text)
        if key_m in seen_m:
            continue
        seen_m.add(key_m)
        uniq_msgs.append(m)

    print(f"  tool calls: {len(all_calls)} total, {len(uniq_calls)} unique")
    print(f"  messages:   {len(all_msgs)} total, {len(uniq_msgs)} unique")
    print(f"  sessions:   {len({c.session_id for c in all_calls})}")

    if args.sample and len(uniq_calls) > args.sample:
        stride = len(uniq_calls) / args.sample
        uniq_calls = [uniq_calls[int(i * stride)] for i in range(args.sample)]
        if uniq_msgs:
            mstride = max(1, len(uniq_msgs) // args.sample)
            uniq_msgs = uniq_msgs[::mstride]
        print(f"  sampled to {len(uniq_calls)} tool calls, {len(uniq_msgs)} messages")

    pipe = make_pipeline(ml=args.ml)

    records: list[dict[str, Any]] = []
    # per_rule[profile_label][rule_id] = RuleAgg  (outbound tool-call scope only)
    per_rule: dict[str, dict[str, RuleAgg]] = {}
    block_counts: dict[str, int] = defaultdict(int)
    tool_block: dict[str, dict[str, int]] = {}  # profile -> tool -> blocked count

    for prof in profiles:
        label = prof or "none"
        per_rule[label] = defaultdict(RuleAgg)
        tool_block[label] = defaultdict(int)

    # ---- Tool calls (OUTBOUND, enforced path) ----
    for call, pt in uniq_calls:
        rec: dict[str, Any] = {
            "scope": "tool_call",
            "direction": "outbound",
            "session_id": call.session_id,
            "tool": call.tool,
            "source_file": call.source_file,
            "param_len": len(pt),
            "by_profile": {},
        }
        for prof in profiles:
            label = prof or "none"
            findings = await scan_one(pipe, pt, "outbound", prof)
            blk = would_block(findings)
            if blk:
                block_counts[label] += 1
                tool_block[label][call.tool] += 1
            rec["by_profile"][label] = {
                "findings": [vars(f) for f in findings],
                "would_block": blk,
            }
            for f in findings:
                agg = per_rule[label][f.rule_id]
                agg.count += 1
                agg.sessions.add(call.session_id)
                agg.severities.add(f.severity)
                agg.confidences.append(f.confidence)
                if len(agg.examples) < 5:
                    agg.examples.append(
                        {
                            "tool": call.tool,
                            "session": call.session_id,
                            "matched": f.matched_text,
                            "message": redact(f.message, cap=160),
                        }
                    )
        records.append(rec)

    # ---- Messages (INBOUND, secondary/non-enforced) ----
    msg_rule: dict[str, dict[str, RuleAgg]] = {}
    for prof in profiles:
        msg_rule[prof or "none"] = defaultdict(RuleAgg)
    if args.include_messages:
        for m in uniq_msgs:
            rec = {
                "scope": "message",
                "direction": "inbound",
                "session_id": m.session_id,
                "role": m.role,
                "source_file": m.source_file,
                "text_len": len(m.text),
                "by_profile": {},
            }
            for prof in profiles:
                label = prof or "none"
                findings = await scan_one(pipe, m.text, "inbound", prof)
                rec["by_profile"][label] = {
                    "findings": [vars(f) for f in findings],
                    "would_block": would_block(findings),
                }
                for f in findings:
                    agg = msg_rule[label][f.rule_id]
                    agg.count += 1
                    agg.sessions.add(m.session_id)
                    agg.severities.add(f.severity)
                    agg.confidences.append(f.confidence)
                    if len(agg.examples) < 5:
                        agg.examples.append(
                            {
                                "role": m.role,
                                "session": m.session_id,
                                "matched": f.matched_text,
                                "message": redact(f.message, cap=160),
                            }
                        )
            records.append(rec)

    # ---- Serialize ----
    def agg_to_dict(d: dict[str, RuleAgg]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for rid, a in sorted(d.items(), key=lambda kv: -kv[1].count):
            confs = sorted(a.confidences)
            out[rid] = {
                "count": a.count,
                "distinct_sessions": len(a.sessions),
                "severities": sorted(a.severities),
                "confidence_min": confs[0] if confs else None,
                "confidence_max": confs[-1] if confs else None,
                "examples": a.examples,
            }
        return out

    (out_dir / "records.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    per_rule_out = {
        "tool_call_outbound": {lbl: agg_to_dict(d) for lbl, d in per_rule.items()},
        "message_inbound": {lbl: agg_to_dict(d) for lbl, d in msg_rule.items()},
    }
    (out_dir / "per_rule.json").write_text(json.dumps(per_rule_out, indent=2), encoding="utf-8")

    summary = {
        "dumps": len(dumps),
        "tool_calls_total": len(all_calls),
        "tool_calls_unique": len(uniq_calls),
        "messages_total": len(all_msgs),
        "messages_unique": len(uniq_msgs),
        "sessions": len({c.session_id for c in all_calls}),
        "tool_calls_would_block_by_profile": dict(block_counts),
        "blocking_tools_by_profile": {p: dict(t) for p, t in tool_block.items()},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
