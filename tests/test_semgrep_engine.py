"""Real raw-core compatibility; synthetic fixtures are scanned, never executed."""

import json
import os
import tempfile
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from petasos.scanners._semgrep_engine import scan_selected
from petasos.scanners._semgrep_source import select_sources
from tests._semgrep_helpers import require


@pytest.fixture
def engine_root() -> Iterator[Path]:
    # OCaml socketpair uses the private temp path: keep it under Windows' limit.
    with tempfile.TemporaryDirectory(prefix="psg-") as directory:
        yield Path(directory)


@pytest.mark.skipif(not os.environ.get("SEMGREP_ENGINE_PATH"), reason="isolated engine required")
class TestSemgrepRealEngine:
    @pytest.mark.parametrize(
        "source,family",
        [
            ("        import os\n        os.system(cmd)\n", "shell"),
            ("\n    # comment\n    import pickle\n    pickle.loads(data)\n", "deserialization"),
            ("    import yaml\n    yaml.unsafe_load(data)\n", "unsafe_yaml"),
            ("    @decorator\n    def method(self):\n        return eval(data)\n", "dynamic_code"),
            ("eval (payload)", "dynamic_code"),
            (
                '{"a":"import os\\nos.system(cmd)","b":' + "[" * 140 + "0" + "]" * 140 + "}",
                "shell",
            ),
        ],
    )
    async def test_review_false_clear_regressions(
        self,
        source: str,
        family: str,
        engine_root: Path,
    ) -> None:
        selection = await select_sources(source)
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await scan_selected(
                selection,
                os.environ["SEMGREP_ENGINE_PATH"],
                engine_root,
                time.monotonic() + 8,
                threading.Event(),
                executor,
            )
        assert any(f.rule_id.endswith("." + family) for f in result.findings), result
        if '"b":' in source:
            assert result.error == "semgrep.projection_limit_code"
        else:
            assert result.error is None, result

    @pytest.mark.parametrize(
        "source",
        [
            "The scanner (see below) reports results (if any).",
            "Please call me (maybe) tomorrow, thanks.",
            "calls(x) and then some ordinary prose without valid syntax",
        ],
    )
    async def test_prose_never_claims_completed_grammar(
        self, source: str, engine_root: Path
    ) -> None:
        selection = await select_sources(source)
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await scan_selected(
                selection,
                os.environ["SEMGREP_ENGINE_PATH"],
                engine_root,
                time.monotonic() + 8,
                threading.Event(),
                executor,
            )
        assert require(result.coverage).status != "complete", result
        assert result.error is None, result

    @pytest.mark.parametrize("separator", ["\x0c", "\u2028", "\r\n", "\r"])
    async def test_local_exclusion_preserves_real_builtin_offset(
        self,
        separator: str,
        engine_root: Path,
    ) -> None:
        source = (
            "# a"
            + separator
            + "# b"
            + separator
            + "# c\neval(payload)\ndef eval(a): pass\neval(b)\n"
        )
        selection = await select_sources("```python\n" + source + "```")
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await scan_selected(
                selection,
                os.environ["SEMGREP_ENGINE_PATH"],
                engine_root,
                time.monotonic() + 8,
                threading.Event(),
                executor,
            )
        starts = {require(f.position).start for f in result.findings}
        assert source.index("eval(payload)") + len("```python\n") in starts, result
        assert source.index("eval(b)") + len("```python\n") not in starts, result

    async def test_dense_python_within_source_limit_is_not_postfilter_error(
        self, engine_root: Path
    ) -> None:
        source = "```python\nDATA = [" + "0," * 55000 + "]\n```"
        selection = await select_sources(source)
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await scan_selected(
                selection,
                os.environ["SEMGREP_ENGINE_PATH"],
                engine_root,
                time.monotonic() + 8,
                threading.Event(),
                executor,
            )
        assert result.error is None, result
        assert require(result.coverage).status == "complete", result

    @pytest.mark.parametrize(
        "source,family",
        [
            ("eval(user_input)", "dynamic_code"),
            ("import os\nos.system(command)", "shell"),
            ("import pickle\npickle.loads(data)", "deserialization"),
            ("import yaml\nyaml.unsafe_load(data)", "unsafe_yaml"),
            ("```javascript\nnew Function(code);\n```", "dynamic_code"),
            ("```typescript\nconst cmd: string = input;\neval(cmd);\n```", "dynamic_code"),
            ("    def run(self):\n        return eval(data)\n", "dynamic_code"),
            (json.dumps({"content": '5|# 😀\n6|eval("é")\n'}), "dynamic_code"),
        ],
    )
    async def test_detects_real_rules_and_original_offsets(
        self, source: str, family: str, engine_root: Path
    ) -> None:
        selection = await select_sources(source)
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await scan_selected(
                selection,
                os.environ["SEMGREP_ENGINE_PATH"],
                engine_root,
                time.monotonic() + 8,
                threading.Event(),
                executor,
            )
        assert result.error is None, result
        assert any(f.rule_id.endswith("." + family) for f in result.findings), result
        assert all(
            f.position_basis == "original" and f.matched_text is None for f in result.findings
        )
        assert all(
            0 <= require(f.position).start < require(f.position).end <= len(source)
            for f in result.findings
        )

    @pytest.mark.parametrize(
        "source,error",
        [
            ("def handler(value):\n", "semgrep.incomplete"),
            ("```python\ndef handler(value):\n```", "semgrep.incomplete"),
            ("```bash\nif [ -f x ]; then echo hi; fi\n```", None),
            ("```python\ndef eval(value):\n    return value\neval(data)\n```", None),
        ],
    )
    async def test_parse_classification_and_local_function(
        self, source: str, error: str | None, engine_root: Path
    ) -> None:
        selection = await select_sources(source)
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await scan_selected(
                selection,
                os.environ["SEMGREP_ENGINE_PATH"],
                engine_root,
                time.monotonic() + 8,
                threading.Event(),
                executor,
            )
        assert result.error == error, result
        assert not result.findings


@pytest.mark.skipif(not os.environ.get("SEMGREP_ENGINE_PATH"), reason="isolated engine required")
class TestSemgrepHeldOut:
    @pytest.mark.parametrize(
        "case",
        json.loads((Path(__file__).parent / "fixtures/semgrep/held_out.json").read_text()),
        ids=lambda case: case["id"],
    )
    async def test_corpus(self, case: dict[str, Any], engine_root: Path) -> None:
        source = "```" + case["language"] + "\n" + case["source"] + "\n```"
        selection = await select_sources(source)
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await scan_selected(
                selection,
                os.environ["SEMGREP_ENGINE_PATH"],
                engine_root,
                time.monotonic() + 8,
                threading.Event(),
                executor,
            )
        assert result.error is None, result
        assert bool(result.findings) is case["finding"], result
