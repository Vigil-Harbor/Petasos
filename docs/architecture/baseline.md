# Baseline at `dfb24a68840b353f70feb201a442442acb9ff425`

Measurements of the tree this redesign starts from (`dfb24a6`,
"docs(architecture): add redesign contracts"), taken before the parity
oracle was added. Commands ran in this worktree with a uv-managed
CPython 3.11.15 at `.venv` (`uv 0.11.23`). The system `python3` is 3.9
and was not used. The install was `uv pip install -e ".[dev,console]"`.
Tool versions from that install: ruff 0.17.4, mypy 2.4.1, pytest 9.1.1.
Node is v22.23.0.

## Lint and types

| Command | Result |
|---|---|
| `ruff check .` | fail, 1 error |
| `ruff format --check .` | pass, 228 files already formatted |
| `mypy --strict .` | pass, no issues in 228 source files |

The ruff error is `SIM102` in `petasos/scanners/minimal.py:856` (nested
`if` inside the JSON-depth walk). Ruff marks the suggested fix unsafe.

## Tests

`pytest -q`: **3692 passed, 276 skipped, 1 xfailed, 0 failed**, 688
warnings, 104.86s. No failing test ids.

`node --test tests/js` does not run the suite. Node v22 treats the
directory as a module and exits 1:

```
Error: Cannot find module '.../tests/js'
code: MODULE_NOT_FOUND
# tests 1
# pass 0
# fail 1
```

`node --test tests/js/*.test.mjs` runs the suite: **388 tests, 388
passed, 0 failed, 0 skipped**, 2552 ms.

## Coverage

`pytest -q --cov=petasos` on the same tree (3692 passed, 276 skipped,
1 xfailed, 133.76s). Coverage.py reports statement coverage. A bare
`pytest --cov` with no source also counts imported test modules, so the
package total below is from `--cov=petasos`.

| Module | Statements | Missed | Cover |
|---|---:|---:|---:|
| `petasos/pipeline/pipeline.py` | 574 | 38 | 93% |
| `petasos/session/frequency.py` | 311 | 10 | 97% |
| `petasos/guard/guard.py` | 430 | 27 | 94% |
| `petasos/session/audit.py` | 56 | 0 | 100% |
| `petasos/session/alerting.py` | 259 | 12 | 95% |
| `petasos` total | 9693 | 1525 | 84% |

## Benchmarks

Means are the pytest-benchmark Mean column from the `pytest -q` run
above. The table is in nanoseconds; the ms column is that number
divided by 1e6. Eighteen benchmarks ran. These five did not, because
their extras are not installed: `test_benchmark_single_ml_llm_guard`,
`test_benchmark_single_ml_llama_firewall`,
`test_benchmark_single_ml_prompt_guard`,
`test_benchmark_prompt_guard_8wide`,
`test_benchmark_full_pipeline_migrated`.

| Test | Mean (ns) | Mean (ms) |
|---|---:|---:|
| `test_benchmark_ingestion_disarmed_no_op` | 285.3980 | 0.0003 |
| `test_benchmark_ingestion_non_ingestion_tool_large_result` | 2349.9102 | 0.0023 |
| `test_benchmark_syntactic_only` | 62153.3417 | 0.0622 |
| `test_benchmark_full_pipeline` | 102320.8373 | 0.1023 |
| `test_benchmark_ingestion_result_1kb` | 1493406.2492 | 1.4934 |
| `test_benchmark_syntactic_outbound` | 3590268.2960 | 3.5903 |
| `test_benchmark_syntactic_anchor_dense` | 4888983.2804 | 4.8890 |
| `test_benchmark_syntactic_leet_worst_case` | 5734391.7259 | 5.7344 |
| `test_benchmark_ingestion_result_8kb` | 6240268.8607 | 6.2403 |
| `test_benchmark_ingestion_unknown_tool_8kb` | 6260068.7030 | 6.2601 |
| `test_benchmark_ingestion_result_8kb_armed_correlator` | 6244323.0534 | 6.2443 |
| `test_benchmark_syntactic_separator_leet_worst_case` | 10093159.1191 | 10.0932 |
| `test_benchmark_ingestion_result_8wide_concurrent` | 10417942.0043 | 10.4179 |
| `test_benchmark_ingestion_result_100kb` | 40553262.5009 | 40.5533 |
| `test_benchmark_ingestion_helper_8wide_serial` | 49131763.9826 | 49.1318 |
| `test_benchmark_syntactic_decode_load` | 74345067.3635 | 74.3451 |
| `test_benchmark_fallback_param_scan_1mb` | 312339291.3258 | 312.3393 |
| `test_benchmark_ingestion_result_1e6` | 349501933.4514 | 349.5019 |

## Line counts

`wc -l` on the starting tree. `tests/js` includes its harness notes.
`petasos/console/static/` text is `.js`, `.css` and `.html`; `wc -l` on
the whole static tree is 7750 because image and font files contain
newline bytes. The reference plugin count excludes `__pycache__`.

| Tree | Lines |
|---|---:|
| `petasos/` Python | 21911 |
| `petasos/console/static/` text (js, css, html) | 6089 |
| `tests/` Python | 61759 |
| `tests/js` | 8992 |
| `docs/deployment/reference_plugin/` (py, yaml, toml) | 4770 |

## Presidio

`uv pip install -e ".[presidio,dev]"` into a separate venv
(`/tmp/wave0-presidio`, Python 3.11.15) succeeded: presidio-analyzer
2.2.366, presidio-anonymizer 2.2.366, spacy 3.8.18. The live tests also
need spaCy `en_core_web_lg`. `python -m spacy download en_core_web_lg`
reported success but installed the wheel into this worktree's `.venv`
(which has no spaCy), so `spacy.load("en_core_web_lg")` still failed in
the presidio venv and 22 tests skipped with "presidio + spaCy model
required". Installing that same wheel with
`uv pip install --python /tmp/wave0-presidio/bin/python` fixed the load.
The accidental copy was uninstalled from `.venv`.

After that, `pytest -q` on `tests/test_presidio_scanner.py`,
`tests/test_presidio_entity_scoping.py` and
`tests/test_pipeline_suppression.py`: **86 passed, 0 skipped, 0 failed**,
14.16s.

The prompt-guard extra was not attempted. Its model weights are gated.
