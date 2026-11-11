"""Every block a person or an agent can see goes through the formatters.

PET-77 counted call sites so a new hand-written block string could not land
beside them. The count is the ``petasos.enforce`` package. The reference
plugin called the same functions and added no extra ``Name`` calls.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TARGETS = {"format_block_message", "format_content_block", "format_result_notice"}
_ROOT = Path("petasos/enforce")


def test_every_block_site_calls_a_formatter() -> None:
    call_sites = 0
    for path in sorted(_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        call_sites += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _TARGETS
        )
    assert call_sites == 14, f"expected 14 formatter call sites, found {call_sites}"
