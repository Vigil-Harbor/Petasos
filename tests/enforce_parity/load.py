"""Load enforcement scenarios and serialise outcome documents.

A scenario is host-neutral JSON. String nodes may contain ``$config`` and
``$home``; the adapter substitutes the temporary paths for one run and
scrubs them back out of the outcome. Compact nodes keep large payloads out
of the file:

* ``{"$repeat": [text, count]}`` repeats ``text``. Optional ``$prefix`` and
  ``$suffix`` are strings.
* ``{"$nest": depth}`` builds that many one-key objects around ``$leaf``.
* A step ``repeat`` count unrolls into ``id-1`` .. ``id-N`` before replay.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
SCENARIOS_PATH = HERE / "scenarios.json"
OUTCOMES_PATH = HERE / "outcomes.json"

OUTCOME_VERSION = 1

# Stamped by the spool writer from the clock, a random id, or the per-run key.
_VOLATILE_EVENT_FIELDS = frozenset({"scan_id", "timestamp", "sig"})

_ANON_RE = re.compile(r"anon-[0-9a-f]{8}")
_DESKTOP_RE = re.compile(r"desktop-[0-9a-f]{12}")
_SHA_RE = re.compile(r"\b[0-9a-f]{64}\b")
_PID_RE = re.compile(r"\bpid=\d+")


def load_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from ``path``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path.name} must be a JSON object")
    return cast("dict[str, Any]", data)


def expand_value(value: Any) -> Any:
    """Expand compact corpus nodes. Ordinary JSON values pass through."""
    if isinstance(value, dict):
        keys = set(value)
        if "$repeat" in keys and keys <= {"$repeat", "$prefix", "$suffix"}:
            return _expand_repeat(value)
        if "$nest" in keys and keys <= {"$nest", "$leaf"}:
            return _expand_nest(value.get("$nest"), value.get("$leaf", "x"))
        return {key: expand_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_value(item) for item in value]
    return value


def expand_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with compact nodes and step repeats expanded.

    Does not substitute ``$config`` or ``$home``. Those stay tokens until
    the adapter knows this run's temporary home.
    """
    expanded = expand_value(scenario)
    if not isinstance(expanded, dict):
        raise TypeError("scenario must expand to an object")
    steps = expanded.get("steps")
    if not isinstance(steps, list):
        raise TypeError("scenario steps must be a list")
    flat: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            raise TypeError("step must be an object")
        count = step.get("repeat", 1)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise TypeError("step repeat must be a positive int")
        body = {key: value for key, value in step.items() if key != "repeat"}
        step_id = body.get("id")
        if not isinstance(step_id, str) or not step_id:
            raise TypeError("step id must be a non-empty string")
        if count == 1:
            flat.append(body)
            continue
        for index in range(1, count + 1):
            copy = dict(body)
            copy["id"] = f"{step_id}-{index}"
            flat.append(copy)
    expanded["steps"] = flat
    return expanded


def bind_paths(value: Any, *, home: str, config: str) -> Any:
    """Substitute ``$home`` and ``$config`` in strings. Does not mutate ``value``."""
    if isinstance(value, str):
        return value.replace("$config", config).replace("$home", home)
    if isinstance(value, dict):
        return {key: bind_paths(item, home=home, config=config) for key, item in value.items()}
    if isinstance(value, list):
        return [bind_paths(item, home=home, config=config) for item in value]
    return value


def scrub_known(text: str, *, homes: list[str], configs: list[str]) -> str:
    """Replace concrete home and config paths, then the other volatile tokens.

    Longer paths win, so the config file (which lives under the home) is
    replaced before the home directory.
    """
    rewritten = text
    ordered = [(path, "<config>") for path in configs] + [(path, "<home>") for path in homes]
    ordered.sort(key=lambda item: len(item[0]), reverse=True)
    for path, token in ordered:
        if path:
            rewritten = rewritten.replace(path, token)
    rewritten = _ANON_RE.sub("<anon>", rewritten)
    rewritten = _DESKTOP_RE.sub("<desktop>", rewritten)
    rewritten = _PID_RE.sub("pid=0", rewritten)
    rewritten = _SHA_RE.sub("<sha256>", rewritten)
    return rewritten


def scrub_event(event: dict[str, Any], *, homes: list[str], configs: list[str]) -> dict[str, Any]:
    """Drop volatile spool fields and scrub paths inside the rest."""
    kept: dict[str, Any] = {}
    for key in sorted(event):
        if key in _VOLATILE_EVENT_FIELDS:
            continue
        kept[key] = _scrub_node(event[key], homes=homes, configs=configs)
    return kept


def _scrub_node(value: Any, *, homes: list[str], configs: list[str]) -> Any:
    if isinstance(value, str):
        return scrub_known(value, homes=homes, configs=configs)
    if isinstance(value, dict):
        return {
            key: _scrub_node(item, homes=homes, configs=configs)
            for key, item in value.items()
            if key not in _VOLATILE_EVENT_FIELDS
        }
    if isinstance(value, list):
        return [_scrub_node(item, homes=homes, configs=configs) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def dump(payload: object) -> str:
    """Serialise ``payload`` so two calls return the same bytes."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def dump_outcomes(document: dict[str, Any]) -> str:
    """Serialise outcomes with one step on each line.

    A diff of the file is then one step. Key order inside a step follows
    ``sort_keys``. Scenario ids stay in the order they were recorded.
    """
    scenarios = document.get("scenarios")
    if not isinstance(scenarios, dict):
        raise TypeError("outcomes scenarios must be an object")
    lines = [
        "{",
        f'  "version": {OUTCOME_VERSION},',
        '  "scenarios": {',
    ]
    items = list(scenarios.items())
    for index, (scenario_id, steps) in enumerate(items):
        if not isinstance(steps, list):
            raise TypeError(f"{scenario_id} outcomes must be a list")
        comma = "," if index < len(items) - 1 else ""
        lines.append(f"    {json.dumps(scenario_id, ensure_ascii=False)}: [")
        for step_index, step in enumerate(steps):
            step_comma = "," if step_index < len(steps) - 1 else ""
            encoded = json.dumps(step, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            lines.append(f"      {encoded}{step_comma}")
        lines.append(f"    ]{comma}")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _expand_repeat(value: dict[str, Any]) -> str:
    pair = value["$repeat"]
    prefix = value.get("$prefix", "")
    suffix = value.get("$suffix", "")
    if (
        not isinstance(pair, list)
        or len(pair) != 2
        or not isinstance(pair[0], str)
        or isinstance(pair[1], bool)
        or not isinstance(pair[1], int)
        or not isinstance(prefix, str)
        or not isinstance(suffix, str)
    ):
        raise TypeError("$repeat must be a [string, int] pair with string prefix and suffix")
    return f"{prefix}{pair[0] * pair[1]}{suffix}"


def _expand_nest(depth: object, leaf: object) -> Any:
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
        raise TypeError("$nest depth must be a non-negative int")
    node: Any = leaf
    for _ in range(depth):
        node = {"k": node}
    return node
