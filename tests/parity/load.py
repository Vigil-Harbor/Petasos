"""Load the parity corpus and serialise verdict documents.

The corpus is plain JSON. A text case is either a ``text`` string or a
``repeat`` pair ``[fragment, count]`` used for the one oversized payload,
which is expanded at load time and is not stored expanded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
CORPUS_PATH = HERE / "corpus.json"
VERDICTS_PATH = HERE / "verdicts.json"

# ``none`` is the unbound profile. The other five are the built-in names.
PROFILES: tuple[str, ...] = (
    "none",
    "general",
    "code_generation",
    "research",
    "customer_service",
    "admin",
)


def load_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from ``path``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path.name} must be a JSON object")
    return cast("dict[str, Any]", data)


def text_of(case: dict[str, Any]) -> str:
    """Return the text a corpus case scans."""
    repeat = case.get("repeat")
    if repeat is not None:
        if (
            not isinstance(repeat, list)
            or len(repeat) != 2
            or not isinstance(repeat[0], str)
            or not isinstance(repeat[1], int)
        ):
            raise TypeError("repeat must be a [string, int] pair")
        return repeat[0] * repeat[1]
    text = case.get("text")
    if not isinstance(text, str):
        raise TypeError("text case needs a string 'text' or a 'repeat' pair")
    return text


def dump(payload: object) -> str:
    """Serialise ``payload`` so two calls return the same bytes."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
