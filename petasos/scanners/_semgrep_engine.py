"""Pinned raw-core protocol; source text is data in owned files only."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from petasos._coverage import CoverageSpan, CoverageStatus, ScanCoverage
from petasos._types import Position, ScanFinding, ScanResult, Severity
from petasos.scanners._semgrep_process import run_process
from petasos.scanners._semgrep_source import LANGUAGES, Selection, Target

if TYPE_CHECKING:
    import threading
    from concurrent.futures import Future, ThreadPoolExecutor

ENGINE_VERSION = "1.183.0"
_RULE_ROOT = Path(__file__).with_name("semgrep_rules")
_MESSAGES = {
    "python.dynamic_code": "Dynamic code evaluation call.",
    "python.shell": "Shell invocation.",
    "python.deserialization": "Object deserialization.",
    "python.unsafe_yaml": "Unsafe YAML loader.",
    "javascript.dynamic_code": "Dynamic code evaluation call.",
    "javascript.shell": "Shell invocation.",
}
RULE_MESSAGES = {"petasos.semgrep." + key: message for key, message in _MESSAGES.items()}


class ProtocolError(ValueError):
    pass


class CpuCleanupFailure(RuntimeError):
    """Retain the occupied worker and its immutable partial outcome."""

    def __init__(self, future: Any, outcome: ScanResult) -> None:
        super().__init__("semgrep.cleanup_failed")
        self.future = future
        self.outcome = outcome


_T = TypeVar("_T")


@dataclass(frozen=True)
class CpuResult(Generic[_T]):
    value: _T | None
    error: str | None


async def await_cpu(
    worker: Future[_T], deadline: float, cancelled: threading.Event, outcome: ScanResult
) -> CpuResult[_T]:
    """Observe cancellation promptly without detaching an unkillable CPU worker."""
    waiting = asyncio.wrap_future(worker)
    while not waiting.done() and not cancelled.is_set() and time.monotonic() < deadline:
        await asyncio.wait({waiting}, timeout=min(0.01, max(0, deadline - time.monotonic())))
    code = (
        "semgrep.cancelled"
        if cancelled.is_set()
        else "ScannerTimeout: semgrep.deadline"
        if time.monotonic() >= deadline
        else None
    )
    if code is None:
        return CpuResult(waiting.result(), None)
    end = time.monotonic() + 2
    while not waiting.done() and time.monotonic() < end:
        await asyncio.wait({waiting}, timeout=min(0.01, max(0, end - time.monotonic())))
    if not waiting.done():
        # Retrieve a later exception without losing ownership of the worker.
        waiting.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        raise CpuCleanupFailure(worker, outcome)
    with contextlib.suppress(Exception):
        waiting.result()
    return CpuResult(None, code)


def strict_output(raw: bytes) -> dict[str, Any]:
    """Bound depth/nodes before the JSON decoder creates object containers."""
    if len(raw) > 2 * 1024 * 1024:
        raise ProtocolError("output_limit")
    start = raw.find(b"{")
    if not 0 <= start <= 256 or raw[:start].strip(b". \r\n\t"):
        raise ProtocolError("protocol_error")
    quoted = escaped = False
    depth = nodes = 0
    for char in raw[start:]:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
            nodes += 1
        elif char in (123, 91):
            depth += 1
            nodes += 1
        elif char in (125, 93):
            depth -= 1
        elif char == 44:
            nodes += 1
        if depth > 32 or nodes > 32768:
            raise ProtocolError("output_limit")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in items:
            if key in obj:
                raise ProtocolError("protocol_error")
            obj[key] = value
        return obj

    def constant(value: str) -> Any:
        raise ProtocolError("protocol_error")

    try:
        result = json.loads(
            raw[start:].decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=constant,
        )
    except (ValueError, UnicodeError) as exc:
        raise ProtocolError("protocol_error") from exc
    if not isinstance(result, dict) or result.get("version") != ENGINE_VERSION:
        raise ProtocolError("protocol_error")
    if not isinstance(result.get("results"), list) or len(result["results"]) > 256:
        raise ProtocolError("output_limit")
    return result


def _path(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 32768:
        raise ProtocolError("protocol_error")
    return os.path.normcase(os.path.abspath(value))


def _local_functions(text: str) -> set[tuple[int, int]]:
    """Conservative exclusion for an explicit preceding same-scope def eval/exec.

    Parameters, imported/assigned aliases, globals and computed bindings are not
    proofs of a harmless local function. Retain matches for those cases.
    """
    tree = ast.parse(text)
    if sum(1 for _ in ast.walk(tree)) > 20000:
        raise ProtocolError("postfilter_limit")
    excluded: set[tuple[int, int]] = set()

    def visit_body(body: list[ast.stmt]) -> None:
        local: set[str] = set()
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Decorators/defaults execute at definition time and can replace
                # bindings. A definition without them is the only local proof.
                if (
                    statement.decorator_list
                    or statement.args.defaults
                    or any(statement.args.kw_defaults)
                ):
                    local.clear()
                elif statement.name in ("eval", "exec"):
                    local.add(statement.name)
                if not any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(statement)):
                    visit_body(statement.body)
                continue
            if isinstance(statement, ast.ClassDef):
                local.clear()
                for member in statement.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        visit_body(member.body)
                continue
            # Narrow straight-line proof only. Imports, control flow, lambdas,
            # comprehensions, assignment and unknown calls invalidate it.
            expression = statement.value if isinstance(statement, (ast.Expr, ast.Return)) else None
            if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name):
                arguments = [*expression.args, *(kw.value for kw in expression.keywords)]
                simple = all(isinstance(arg, (ast.Name, ast.Constant)) for arg in arguments)
                if expression.func.id in local and simple:
                    excluded.add((expression.lineno, expression.col_offset))
                # Even the local function can mutate its module's bindings.
                local.clear()
            else:
                local.clear()

    visit_body(tree.body)
    return excluded


def _findings(
    data: dict[str, Any], expected: dict[str, tuple[int, Target]]
) -> tuple[dict[int, list[ScanFinding]], set[int], str | None]:
    scanned = data.get("paths", {}).get("scanned")
    if not isinstance(scanned, list) or {_path(p) for p in scanned} != set(expected):
        raise ProtocolError("target_mismatch")
    parsed = {i for i, _ in expected.values()}
    error: str | None = None
    errors = data.get("errors")
    if not isinstance(errors, list):
        raise ProtocolError("protocol_error")
    for item in errors:
        kind = item.get("error_type", item.get("type"))
        kind = kind[0] if isinstance(kind, list) and kind else kind
        path = item.get("location", {}).get("path", item.get("path"))
        if kind in ("PartialParsing", "ParseError", "Syntax error") and path is not None:
            owned = expected.get(_path(path))
            if owned is None:
                raise ProtocolError("target_mismatch")
            parsed.discard(owned[0])
        else:
            error = "semgrep.engine_error"
    found: dict[int, list[ScanFinding]] = {}
    for row in data["results"]:
        rule = row.get("check_id")
        if rule not in RULE_MESSAGES:
            raise ProtocolError("unknown_rule")
        owned = expected.get(_path(row.get("path")))
        if owned is None:
            raise ProtocolError("target_mismatch")
        i, target = owned
        a, b = row.get("start", {}).get("offset"), row.get("end", {}).get("offset")
        source = target.region.text.encode("utf-8")
        if type(a) is not int or type(b) is not int or not 0 <= a <= b <= len(source):
            error = "semgrep.offset_invalid"
            continue
        try:
            start = len(source[:a].decode("utf-8"))
            end = start + len(source[a:b].decode("utf-8"))
            start, end = target.region.interval(start, end)
        except (ValueError, UnicodeError):
            error = "semgrep.offset_invalid"
            continue
        found.setdefault(i, []).append(
            ScanFinding(
                rule,
                "unsafe_code",
                Severity.MEDIUM,
                1.0,
                RULE_MESSAGES[rule],
                "semgrep",
                Position(start, end),
                position_basis="original",
            )
        )
    return found, parsed, error


def result_for(
    selection: Selection,
    findings: tuple[ScanFinding, ...] = (),
    completed: set[int] | None = None,
    error: str | None = None,
    duration_ms: float = 0,
) -> ScanResult:
    completed = completed or set()
    error = error or selection.error
    spans = []
    reasons = set(selection.reasons)
    any_partial = selection.tail is not None or selection.unsupported
    for i, target in enumerate(selection.targets):
        status: CoverageStatus = "complete" if i in completed else "unsupported"
        if (
            target.incomplete
            or (
                (target.region.clipped or target.region.clamped)
                and (target.asserted or i in completed)
            )
            or (target.asserted and i not in completed)
        ):
            status = "partial"
            error = error or "semgrep.incomplete"
        elif i not in completed:
            reasons.add("no_grammar_accepted")
        elif target.region.clipped:
            status = "partial"
        if target.region.clipped and i not in completed and not target.asserted:
            status = "partial"
            reasons.add("source_limit_tentative")
        any_partial |= status != "complete"
        spans.append(
            CoverageSpan(
                target.region.start,
                target.region.end,
                target.language,
                status,
                target.region.projection,
            )
        )
    if selection.tail is not None:
        spans.append(CoverageSpan(selection.tail, selection.total, None, "partial"))
    status = "complete"
    if error:
        status = "partial" if error == "semgrep.incomplete" else "error"
    elif not selection.targets:
        status = "unsupported" if selection.unsupported else "no_targets"
    elif not completed:
        status = (
            "partial"
            if selection.tail is not None or any(t.region.clipped for t in selection.targets)
            else "unsupported"
        )
    elif any_partial:
        status = "partial"
    coverage = ScanCoverage(
        status,
        selection.total,
        selection.examined,
        len(selection.targets),
        len(completed),
        tuple(spans),
        tuple(sorted(reasons)),
    )
    return ScanResult("semgrep", findings, duration_ms, error, coverage)


async def scan_selected(
    selection: Selection,
    engine: str,
    root: Path,
    deadline: float,
    cancelled: threading.Event,
    executor: ThreadPoolExecutor,
) -> ScanResult:
    start = time.monotonic()
    all_findings: dict[int, list[tuple[bool, ScanFinding]]] = {}
    completed: set[int] = set()
    error = selection.error
    try:
        raw_rules = (_RULE_ROOT / "rules.json").read_bytes()
        manifest = json.loads((_RULE_ROOT / "manifest.json").read_bytes())
        if hashlib.sha256(raw_rules).hexdigest() != manifest["rules_sha256"]:
            raise ProtocolError("rules_integrity")
        rules = root / "rules.json"
        rules.write_bytes(raw_rules)
        paths: dict[int, Path] = {}
        for i, target in enumerate(selection.targets):
            paths[i] = root / f"candidate-{i}.source"
            paths[i].write_bytes(target.region.text.encode("utf-8"))
        for language in LANGUAGES:
            batch = {
                i: t for i, t in enumerate(selection.targets) if t.language in (None, language)
            }
            if not batch:
                continue
            if cancelled.is_set():
                error = "semgrep.cancelled"
                break
            if time.monotonic() >= deadline:
                error = "ScannerTimeout: semgrep.deadline"
                break
            targets = root / "targets.json"
            targets.write_text(
                json.dumps(
                    [
                        "Targets",
                        [
                            [
                                "CodeTarget",
                                {
                                    "path": {
                                        "fpath": str(paths[i]),
                                        "ppath": f"/candidate-{i}.source",
                                    },
                                    "analyzer": language,
                                    "products": ["sast"],
                                },
                            ]
                            for i in batch
                        ],
                    ]
                ),
                encoding="utf-8",
            )
            process = await run_process(
                [
                    engine,
                    "-rules",
                    str(rules),
                    "-targets",
                    str(targets),
                    "-json",
                    "-j",
                    "1",
                    "-timeout",
                    "2",
                    "-max_memory",
                    "512",
                ],
                root,
                deadline,
                cancelled,
            )
            if process.error is not None:
                error = process.error
                break
            if process.returncode != 0 and not process.stdout.strip():
                error = "semgrep.engine_error"
                break
            data = strict_output(process.stdout)
            found, parsed, batch_error = _findings(
                data, {_path(str(paths[i])): (i, t) for i, t in batch.items()}
            )
            if process.returncode != 0 and not data.get("errors"):
                batch_error = "semgrep.engine_error"
            error = error or batch_error
            if language == "python":
                # Raw-core accepts an empty Python suite without a parse error.
                # CPython's bounded syntax check closes that specific false-clear
                # class and supplies the lexical local-binding exclusion.
                for i in tuple(parsed):
                    items = found.get(i, [])
                    dynamic = [f for f in items if f.rule_id.endswith("python.dynamic_code")]
                    try:
                        worker = executor.submit(_local_functions, batch[i].region.text)
                        retained = tuple(f for values in found.values() for f in values)
                        cpu_result = await await_cpu(
                            worker,
                            deadline,
                            cancelled,
                            result_for(selection, retained, error="semgrep.cleanup_failed"),
                        )
                        excluded, cpu_error = cpu_result.value, cpu_result.error
                        error = error or cpu_error
                        if cpu_error:
                            break
                        if excluded and dynamic:
                            offsets = [0]
                            for line in batch[i].region.text.splitlines(keepends=True):
                                offsets.append(offsets[-1] + len(line.encode("utf-8")))
                            raw = batch[i].region.text.encode("utf-8")
                            locations = set()
                            for line_number, col in excluded:
                                pos = len(raw[: offsets[line_number - 1] + col].decode("utf-8"))
                                locations.add(batch[i].region.interval(pos, pos)[0])
                            found[i] = [
                                f
                                for f in items
                                if f not in dynamic
                                or f.position is None
                                or f.position.start not in locations
                            ]
                    except SyntaxError:
                        parsed.discard(i)
                    except CpuCleanupFailure:
                        raise
                    except Exception:
                        error = error or "semgrep.postfilter_error"
            if time.monotonic() >= deadline:
                error = error or "ScannerTimeout: semgrep.deadline"
            completed.update(parsed)
            for i, items in found.items():
                all_findings.setdefault(i, []).extend((i in parsed, f) for f in items)
            await asyncio.sleep(0)
    except ProtocolError as exc:
        error = "semgrep." + str(exc)
    findings: dict[tuple[str, int, int], ScanFinding] = {}
    for i, candidates in all_findings.items():
        for full, finding in candidates:
            if i in completed and not full:
                continue
            assert finding.position is not None
            key = (
                finding.rule_id.rsplit(".", 1)[-1],
                finding.position.start,
                finding.position.end,
            )
            findings.setdefault(key, finding)
    if len(findings) > 256:
        error = "semgrep.output_limit"
    return result_for(
        selection,
        tuple(list(findings.values())[:256]),
        completed,
        error,
        (time.monotonic() - start) * 1000,
    )
