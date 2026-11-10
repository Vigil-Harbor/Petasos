"""Regenerate ``verdicts.json`` from ``corpus.json``.

Run from the repository root::

    .venv/bin/python -m tests.parity.record

Re-running this is only legitimate for a deliberate behaviour change.
Two runs against an unchanged tree write byte-identical output.
"""

from __future__ import annotations

from typing import Any

from tests.parity.adapter import replay_corpus
from tests.parity.load import (
    CORPUS_PATH,
    VERDICTS_PATH,
    compact_verdicts,
    dump_verdicts,
    load_json,
)


def replay(corpus: dict[str, Any]) -> dict[str, Any]:
    """Replay every corpus case under every profile label.

    The result is keyed by kind, then profile, then case id. ``plugin:<name>``
    is the reference-plugin guard arrangement for that pipeline profile.
    """
    return replay_corpus(corpus)


def main() -> None:
    """Write the compact ``verdicts.json`` next to this file."""
    corpus = load_json(CORPUS_PATH)
    VERDICTS_PATH.write_text(dump_verdicts(compact_verdicts(replay(corpus))), encoding="utf-8")


if __name__ == "__main__":
    main()
