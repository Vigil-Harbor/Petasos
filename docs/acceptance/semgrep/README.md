# Semgrep component evidence

## Counting-run rule from November 9, 2026 (PET-257)

The `extras-semgrep` workflow no longer runs the latency benchmark on
`pull_request` events. Its pytest step still runs on every pull request that
touches the lane's paths (the PET-106 pairing). The benchmark step and its
`semgrep-component` artifact run only on `workflow_dispatch`, against the ref the
operator chooses, on both Python 3.14 jobs.

The rule for a counting run is otherwise unchanged:

1. The counting run for a piece is the first manual dispatch at that piece's
   final head. Earlier dispatches against other heads do not count as its
   measurement. A failed dispatch under a supported hosted label still blocks
   the evaluated product, workload and criteria combination, as protocol v3
   requires, until a reviewed relevant repair or a verified infrastructure
   cause is followed by a corrected measurement. A documentation-only change
   does not make a new final head for this purpose.
2. Every row must pass on both platforms in that one run. Rows from other runs
   are not combined with it.
3. Any failure stands. There is no retry. The result goes back to the operator.
4. A pull-request run measures nothing and never counts.

Limits and `criteria_version` `S7-2026-11-08-v3` are unchanged. The sections
below record runs made under the earlier first-push rule and stand as written.

## Protocol v4 counting run at 167efa8 passed

Hosted run
[42464906511](https://github.com/Vigil-Harbor/Petasos/actions/runs/42464906511)
is the one counting run fixed by the rule below. It measured merge revision
`679f1631ac273c99798575bff748e20bd6cb911d` (branch head `167efa8` onto
`2222a8b`), with workload `eight_outstanding_three_profiles_16k_64k_v3`,
manifest `62d44848...945e` and criteria `S7-2026-11-08-v3`. It includes the
code-review fixes from pieces 1-5. Summaries are retained in
`hosted-mac-167efa8.json` and `hosted-win-167efa8.json`.

**Every v4 component gate passed on both platforms in this run: 17 of 17 rows,
1,752 of 1,752 planned requests completed per platform, zero errors, nothing unrun or
unfinished, empty `gate_failures`.** Recomputing the gates from the artifacts
gives the same result. `qualified` stays `false` because the qualification
manifest is still empty. That is a separate release gate. All four test jobs
(Python 3.11 and 3.14 on both platforms) passed 350 tests with no failures.

| Row (limit) | macOS 15 | Windows Server 2025 |
|---|---|---|
| Single 16 KiB mean / p95 / p99 (macOS 1.0 / 1.2 / 1.4 s; Windows 1.2 / 1.4 / 1.6 s) | 0.649 / 0.780 / 0.878 | 0.773 / 0.822 / 0.965 |
| 64 KiB repeated mean / p95 / p99 (1.8 / 2.0 / 2.3 s) | 1.047 / 1.247 / 1.319 | 1.197 / 1.251 / 1.395 |
| 64 KiB distinct mean / p95 / p99 (1.8 / 2.0 / 2.3 s) | 1.045 / 1.300 / 1.470 | 1.207 / 1.361 / 1.411 |
| Eight-wide 16 KiB, worst p95 of six (6.5 × single mean) | 3.327 (limit 4.216) | 4.705 (limit 5.024) |
| Replacements p95 (6.5 × single mean) | 3.186 (limit 4.216) | 3.566 (limit 5.024) |
| Eight-wide 64 KiB, worst p95 of six (6.5 × distinct mean) | 5.817 (limit 6.790) | 5.865 (limit 7.847) |
| Worst max of the twelve loaded rows and replacements (8.0 s) | 6.370 | 6.134 |
| Preflight 1M p95 (0.050 s) | 0.022 | 0.012 |

Hosts: macOS Apple M1 (Virtual), 3 cores, image `20261104.0514.1`; Windows AMD
Family 25 Model 17, 2 physical / 4 logical cores, image `20261103.298.1`;
Python 3.14.10 on both.

What this run does not show:

- The Windows host was a fast draw. The single 16 KiB mean was 0.773 s and the
  cold probe 0.550 s, close to the `5221a7c` reference (0.544 s). Every row also
  passes the superseded v2 criteria. The run does not exercise the v4 limits on
  a slow host.
- Closest margins: Windows eight-wide 16 KiB three-owner 4/2/2 had a ratio of
  6.09 against 6.5, about 6% headroom, with p99 4.843 s and max 5.117 s. macOS
  64 KiB shared-owner 3/3/2 had p95 5.817 s against 6.790 s.
- The known cleanup deadline edge, Windows root-removal intermittency and the
  local `semgrep.cleanup_failed` sighting below remain open. A pass does not
  resolve them.

Runs that do not count: the run started by the push that records this section.

## Host-relative load gates (protocol v4, November 8, 2026)

### What changed

After the package was split into stacked PRs #215-#220, the top PR's own run
[42458942519](https://github.com/Vigil-Harbor/Petasos/actions/runs/42458942519)
at `24d9cb0` FAILED on Windows. Its code is identical to `027f371`, which
contains the `fb65503` counting run below. Eight-wide 16 KiB shared-owner 4/2/2
had p95 6.015 s against 5.0 s. Every other row, and every macOS row, passed.
That run does not count. It ran before the code-review fixes and before this
decision. Summaries for it are not retained in this directory. The full
artifact is kept locally.

Three hosted Windows runs of essentially the same code:

| Run | Windows host | Single 16 KiB mean | Eight-wide 16 KiB worst p95 | Eight-wide 64 KiB worst max | Worst p95 / serial mean | Under v2 criteria |
|---|---|---:|---:|---:|---:|---|
| 42439292090 @ `fb65503` | AMD Fam 25 Model 17 | 0.778 | 4.705 | 6.111 | 6.05 | pass |
| 42436053501 @ `51acf8e` | AMD Fam 25 Model 17 | 1.022 | 5.561 | 7.377 | 5.44 | fail |
| 42458942519 @ `24d9cb0` | AMD Fam 25 Model 1 | 0.985 | 6.015 | 7.822 | 6.11 | fail |

Same CPU model, 31% apart on the serial mean, so host load matters as well as the
CPU generation. macOS passed every row in all three runs. Across every loaded and
replacement row on both platforms, p95 over the same run's serial mean was
3.6-6.1x. The serial single 16 KiB mean also failed one host (`51acf8e`), so a
host-relative load gate alone would not have been enough.

The operator chose:

1. Loaded and replacement p95 at most **6.5 ×** the same run's serial mean for
   the same fixture. Every loaded and replacement sample within the **8.0 s**
   runtime deadline. Zero errors. The 16 KiB and replacement rows gain that
   maximum.
2. Windows serial single 16 KiB at **1.2 / 1.4 / 1.6 s** (mean / p95 / p99).
   Other platforms stay at 1.0 / 1.2 / 1.4 s.
3. All other limits unchanged.

Rejected: loosening only the fixed Windows limits, a pinned or self-hosted
runner (not for now), and keeping the limits as they were. That last option
would likely fail about 2 runs in 3 on host draw alone.
Details are in [protocol v4](protocol-v4.md), criteria `S7-2026-11-08-v3`,
implemented in `scripts/semgrep_benchmark_protocol.py`. Records now carry
`hardware.system`.

For interpretation only: replaying the v4 gates over the full artifacts of the
three runs above passes all six platform-runs. That replay is not a
measurement. The `51acf8e` and `24d9cb0` failures stand under their criteria.

### Rule for the counting run

Fixed before the push:

1. The next push of `feat/pet-254-s6-measurement` (#220) carries the code-review
   fixes from pieces 1-5 and these criteria. Its run is the one counting run. No
   hosted runner has measured those fixes yet.
2. Every row must pass on both Python 3.14 platforms in that one run. Rows from
   other runs are not combined with it.
3. Any failure stands. There is no retry. The result goes back to the operator.
4. Later documentation pushes start the lane again. Those runs do not count.

### Open observation carried forward

In code review of piece 6, one local focused test invocation, outside the
benchmark, recorded a terminal `semgrep.cleanup_failed` sample at 10.006 s. It
was in a real-engine replacement case (`test_real_loaded_case_records_telemetry_and_closes`,
plan index 8) after both cancellation cycles reached two active jobs. The
harness rejected it correctly, and a later combined lane run passed. The cause
was not established. It belongs with the known cleanup deadline edge and the
intermittent Windows root-removal failures, which stay unresolved.

## Piece 7 cleanup evidence (PET-255)

### Working directory does not block removal (D6)

Probed on 2026-11-08 on this Windows host. The real `_WindowsChild` used the
root as its working directory and as `TEMP`. A helper wrote a file into `TEMP`
and slept. The probe force-terminated the child, polled `cleaned()`, then
unlinked the content and called `os.rmdir(root)` immediately. The helper was a
Python sleep process started 0.4 s before termination, so these times are not
a `semgrep-core` measurement.

| Run | Runs | Removal failures | Terminate to `cleaned()` |
|---|---|---|---|
| 1 | 80 (40 single-child, 40 with a grandchild in the same job) | 0 | max 2.45 s |
| 2, single-child | 30 | 0 | median 1.31 s, p90 2.305 s, max 2.36 s, 13 of 30 above 2 s |
| 2, grandchild | 30 | 0 | median 0.122 s, max 4.091 s |

Run 2 overall: 60 runs, 0 removal failures. A child's working directory does
not block root removal once `cleaned()` has passed. The working directory is
unchanged. The same times are evidence that a Windows exit can outlast the 2 s
native bound. Recovery handles that case.

The probe script:

```python
"""D6 probe: does a Windows child's cwd on the root block os.rmdir(root) once cleaned() passes?

Runs the real _WindowsChild (cwd = root, TEMP = root) with a helper that writes a file
into TEMP and then sleeps; also a variant whose helper spawns a grandchild in the same
job. Force-terminates, waits for cleaned(), then removes the root immediately.
"""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from petasos.scanners._semgrep_process import _WindowsChild  # noqa: E402

PY = sys.executable
SLEEP = "import os,time;open(os.path.join(os.environ['TEMP'],'t.txt'),'w').write('x');time.sleep(30)"
SPAWN = (
    "import os,subprocess,sys,time;open(os.path.join(os.environ['TEMP'],'t.txt'),'w').write('x');"
    "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);time.sleep(30)"
)
results = {"rmdir_fail": 0, "rmtree_fail": 0, "runs": 0, "max_cleaned_s": 0.0, "errors": []}
for i in range(int(sys.argv[2])):
    for code in (SLEEP, SPAWN):
        root = Path(tempfile.mkdtemp(prefix="pcwd-"))
        child = _WindowsChild([PY, "-c", code], root)
        time.sleep(0.4)
        start = time.monotonic()
        child.terminate(force=True)
        while not child.cleaned():
            if time.monotonic() - start > 5:
                break
            time.sleep(0.005)
        took = time.monotonic() - start
        results["max_cleaned_s"] = max(results["max_cleaned_s"], took)
        results["runs"] += 1
        try:
            for entry in root.iterdir():
                entry.unlink()
            os.rmdir(root)
        except OSError as exc:
            results["rmdir_fail"] += 1
            results["errors"].append([type(exc).__name__, exc.errno, getattr(exc, "winerror", None)])
            try:
                shutil.rmtree(root)
            except OSError:
                results["rmtree_fail"] += 1
print(json.dumps(results))
```

### Loaded real-engine attempt (D9)

`scripts/semgrep_cleanup_stress.py` is not part of CI and gates nothing. Each
iteration runs one replacement cycle on the real pinned `semgrep-core` with the
`single_16k` fixture: two active scans are cancelled, then one scan runs. The
load is `--load 16`: sixteen busy-loop processes on this host's 16 logical CPUs,
so the CPU is saturated for the whole run. Run it with the checkout on
`PYTHONPATH`: run as a file, `import petasos` otherwise resolves to whatever
copy the interpreter has installed. The first record of this attempt
(`clean=60`) imported an older installed copy and is withdrawn.

Nine runs of 60 iterations on the final piece 7 code, 2026-11-08, in order:

| Run | Result | Close |
|---|---|---|
| 1 | aborted: the owner's close raised `SemgrepCleanupError` (the script then had no close handling, so counts and diagnostics were lost) | failed |
| 2, 3, 4, 5 | `clean=60` | closed |
| 6 | first failure at iteration 5; the runtime then stayed failed, so the script labels the remaining iterations `cleanup_failed` too (`clean=4 cleanup_failed=56 recovered=0 expired=0`) | failed |
| 7 | `clean=60` | closed |
| 8 | `clean=56 cleanup_failed=4 recovered=1` | closed |
| 9 | `clean=60` | closed |

Run 6's close diagnostics were `kind=native outcome=unfinished` (a native
worker still running at the interrupt + 4 s ceiling) and
`kind=root_removal type=none errno=none winerror=none outcome=unfinished` (a
removal attempt still running at its budget). There was no `outcome=expired`
line: the failed runtime failed every later request at once, so the run ended
inside the 30 s recovery window and close reported `failed` as D4 specifies.
Whether that worker would have finished and recovered is not established.

Reading: under full CPU saturation a Windows cleanup can still overrun the
approved 4 s ceiling, the item-3 behaviour. With piece 7 the runtime recovered
once (run 8) instead of retiring for the life of the process, and otherwise
failed closed. These are not hosted-runner conditions: the protocol v4 counting
run at `167efa8` completed 1,752 of 1,752 requests per platform with no cleanup
failure.

### Counting run for piece 7 (D10)

The first push of `feat/pet-254-s7-cleanup` is the counting run under the
protocol v4 rule:

1. Every row runs on both platforms in that one run.
2. Any failure stands. There is no retry. The result goes back to the operator.
3. The result of that run is recorded in a later push. That later push does not count.

The rule above was recorded before the first push.

### Piece 7 counting run at 52c93e0 passed

The first push, `9b64c57`, started run
[42531161785](https://github.com/Vigil-Harbor/Petasos/actions/runs/42531161785).
It failed in the test step on all four jobs. The benchmark step was skipped, so
no protocol v4 row was measured. Both failures were test defects:

- `test_marker_guards_refuse_without_reading_or_unlinking` installed its
  `Path.open` spy before the test wrote and read back `secret.txt`, so it
  recorded the test's own reads. The guard refused the linked marker as
  intended. Local Windows skips this test because symlinks are not permitted,
  which is why the local gate passed.
- `test_finished_removal_error_recovers_without_a_child_check` expected
  `winerror=32`. Python sets `winerror` only on Windows, so macOS correctly
  reported `winerror=none`.

`52c93e0` fixes both tests and changes nothing else. The operator decided that
its run is the counting run for piece 7, under the same rule.

Hosted run
[42537024961](https://github.com/Vigil-Harbor/Petasos/actions/runs/42537024961)
measured merge revision `01c8cb256b1da7eae212025b7d821574f5885b53` (branch
head `52c93e0`), with workload `eight_outstanding_three_profiles_16k_64k_v3`,
manifest `62d44848...945e` and criteria `S7-2026-11-08-v3`. Summaries are
retained in `hosted-mac-52c93e0.json` and `hosted-win-52c93e0.json`.

**Every v4 component gate passed on both platforms in this run: 17 of 17 rows,
1,752 of 1,752 planned requests completed per platform, zero errors, nothing
unrun or unfinished, empty `gate_failures`.** Recomputing the gates from the
artifacts gives the same result. `qualified` stays `false` because the
qualification manifest is still empty. All four test jobs (Python 3.11 and 3.14
on both platforms) ran 388 tests with no failures. Both repaired tests ran and
passed on every job.

| Row (limit) | macOS 15 | Windows Server 2025 |
|---|---|---|
| Single 16 KiB mean / p95 / p99 (macOS 1.0 / 1.2 / 1.4 s; Windows 1.2 / 1.4 / 1.6 s) | 0.684 / 0.833 / 1.025 | 1.059 / 1.300 / 1.447 |
| 64 KiB repeated mean / p95 / p99 (1.8 / 2.0 / 2.3 s) | 1.209 / 1.602 / 1.933 | 1.535 / 1.833 / 2.025 |
| 64 KiB distinct mean / p95 / p99 (1.8 / 2.0 / 2.3 s) | 1.123 / 1.624 / 1.897 | 1.507 / 1.568 / 1.818 |
| Eight-wide 16 KiB, worst p95 of six (6.5 × single mean) | 3.134 (limit 4.445) | 4.595 (limit 6.883) |
| Replacements p95 (6.5 × single mean) | 3.035 (limit 4.445) | 4.489 (limit 6.883) |
| Eight-wide 64 KiB, worst p95 of six (6.5 × distinct mean) | 6.078 (limit 7.300) | 7.112 (limit 9.796) |
| Worst max of the twelve loaded rows and replacements (8.0 s) | 7.150 | 7.449 |
| Preflight 1M p95 (0.050 s) | 0.023 | 0.014 |

Hosts: macOS Apple M1 (Virtual), 3 cores, image `20261104.0514.1`; Windows
Intel Family 6 Model 207, 2 physical / 4 logical cores, image
`20261103.298.1`; Python 3.14.10 on both.

Cleanup evidence: `cleanup_diagnostics` is empty on both platforms. Every root
removal took one attempt: `root_remove_attempt` and `root_cleanup` each ran
1,776 times on macOS and 1,789 times on Windows. The slowest attempt was
0.032 s on macOS and 0.090 s on Windows. No owned root or live owned process
remained after any loaded row.

What this run does not show:

- No hosted cleanup failure occurred, so the recovery path (D4) did not run
  here. Its evidence is the unit tests and the loaded stress record above.
- Whether piece 7 changes hosted latency. The Windows host was a different
  CPU from the `167efa8` run (Intel rather than AMD) and slower on every
  serial and loaded row: single 16 KiB mean 1.059 s against 0.773 s,
  cold probe 0.747 s against 0.550 s. macOS ran on the same host type, with
  serial means 5% to 15% above `167efa8`. One pair of runs cannot separate
  that from run-to-run variation.
- This run is the slow Windows draw that `167efa8` lacked. The host-relative
  loaded gates held on it. The fixed limits were closest: Windows single
  16 KiB mean 1.059 s against 1.2 s and p95 1.300 s against 1.4 s; 64 KiB
  repeated p95 1.833 s against 2.0 s; worst loaded max 7.449 s against 8.0 s.
  On Windows 64 KiB loaded rows the 8.0 s max is the binding limit, because
  6.5 times the distinct mean is 9.796 s.

Runs that do not count: the run started by the push that records this section.

## 64 KiB maximum (protocol v3): counting run at fb65503 passed

Hosted run
[42439292090](https://github.com/Vigil-Harbor/Petasos/actions/runs/42439292090)
is the single corrected measurement fixed by the rerun rule below. It measured
merge revision `f833b5e99de6eb0dee2bdedc201ff639900df7b2` for branch head
`fb65503`, with workload `eight_outstanding_three_profiles_16k_64k_v3`, manifest
`62d44848...945e` and criteria `S7-2026-11-07-v2`. Summaries are retained in
`hosted-mac-fb65503.json` and `hosted-win-fb65503.json`.

**Every v3 component gate passed on both platforms in this run: 17 of 17 rows,
zero errors, empty `gate_failures`.** `qualified` stays `false` because the
qualification manifest is still empty; that is a separate release gate.

| Row (limit) | macOS 15 | Windows Server 2025 |
|---|---|---|
| Single 16 KiB mean / p95 / p99 (1.0 / 1.2 / 1.4 s) | 0.575 / 0.693 / 0.748 | 0.778 / 0.812 / 0.966 |
| 64 KiB repeated mean / p95 / p99 (1.8 / 2.0 / 2.3 s) | 0.924 / 1.165 / 1.248 | 1.264 / 1.410 / 1.740 |
| 64 KiB distinct mean / p95 / p99 (1.8 / 2.0 / 2.3 s) | 0.866 / 1.074 / 1.269 | 1.218 / 1.378 / 1.397 |
| Eight-wide 16 KiB, worst p95 of six (5.0 s) | 3.085 | 4.705 |
| Eight-wide 64 KiB, worst p95 of six (7.5 s) | 3.954 | 5.931 |
| Eight-wide 64 KiB, worst max of six (8.0 s) | 4.218 | 6.111 |
| Replacements p95 (7.5 s) | 2.842 | 3.595 |
| Preflight 1M p95 (0.050 s) | 0.022 | 0.012 |

Hosts: macOS Apple M1 (Virtual), 3 cores, image `20261104.0514.1`; Windows AMD
Family 25 Model 17, 2 physical cores, image `20261103.298.1`; Python 3.14.10 on
both. The Windows host looked like the `5221a7c` reference, not the slow
`51acf8e` host: native suite 86.72 s, preflight mean 0.011 s, single 16 KiB cold
probe 0.545 s.

Margins worth watching. These are observations, not failures:

- Windows eight-wide 16 KiB shared-owner 8/0/0 had p95 4.705 s against 5.0 s,
  p99 5.976 s and max 6.993 s. That is about 6% headroom on the binding 16 KiB
  row. The 16 KiB eight-wide gate has no per-request maximum.
- Windows 64 KiB repeated had one 4.343 s serial outlier. Its p99 of 1.740 s is
  within 2.3 s.

Other jobs in the same run: `scanner-tests (windows-2025, 3.11)` failed one
functional test, `test_sibling_errors_and_discard_time_preserved`. It measured a
20 ms sleep as 0.015 s because Python 3.11 on Windows backs `time.monotonic()`
with a 15.625 ms tick (3.13+ use a fine-grained clock). That lane runs no
benchmark. Commit `7ce5525` allows for the clock's reported resolution. macOS 3.11
passed.

Runs that do not count: 42438233233 (`e86b922`) and 42439132916 (`ba84582`) were
started by documentation pushes. Pull-request path filters evaluate the whole PR
diff, so every push starts this lane. Both were cancelled without reading their
results. The run started by the push that records this section also does not
count.

## 64 KiB maximum (protocol v3): first hosted attempt at 51acf8e

On November 7, 2026 the operator lowered the supported maximum source to 64 KiB
([protocol v3](protocol-v3.md)); latency limits are unchanged. Hosted run
[42436053501](https://github.com/Vigil-Harbor/Petasos/actions/runs/42436053501)
measured merge revision `7a447f21be58b9cee15832a4564887d14a928740` for branch head
`51acf8e`. Summaries (per-sample data omitted for size) are retained in
`hosted-mac-51acf8e.json` and `hosted-win-51acf8e.json`.

- **macOS 15 / Python 3.14 (Apple M1 virtual, 3 cores): every component gate
  passed.** 64 KiB serial repeated/distinct mean 1.128/1.044 s. The six 64 KiB
  eight-wide cases had p95 4.77-5.09 s, max 5.77 s and zero errors.
- **Windows Server 2025 / Python 3.14 (AMD Family 25 Model 17, 2 physical cores):
  FAILED.** All seven 64 KiB rows passed: serial repeated/distinct mean
  1.510/1.478 s, and the six eight-wide cases had p95 6.89-7.05 s, max 7.38 s and
  zero errors. Two unchanged 16 KiB rows failed: serial single mean 1.022 s
  (limit 1.0 s) and eight-wide 16 KiB shared-owner 4/2/2 p95 5.561 s (limit 5.0 s).

An independent review (`.claude/reviews/PET-254-S7-v3-review-1.md`, local)
judged a slower Windows host **plausible and strongly supported, but not
verified**. `51acf8e` changes only the source-byte cap, which neither a single
16 KiB target nor preflight reaches. Against run 42404464485 (`5221a7c`, same base
`39b4cb1`, same hardware label, image `20261103.298.1`, Python and engine), the
native test suite on the same VM before the benchmark slowed from 81.66 s to
109.37 s (median 1.33x across 278 common tests). Comparable benchmark cases
slowed by a similar factor: single 16 KiB mean 0.785 to 1.022 s, cold probe 0.544
to 0.697 s, engine-free preflight mean 0.0112 to 0.0145 s with non-overlapping
distributions. The macOS control was flat (suite 62.15 to 60.83 s). The 4/2/2
p95 failure also needed a short extra episode: burst maxima stepped up at burst 7,
and control-loop lag reached 0.427 s against at most 0.114 s in most cases. Not
every summary stage duration slowed; those pool different workload mixes.

The 64 KiB passes above were measured on the same slower host. They support the
64 KiB capacity estimate but are not a qualifying result by themselves.
Qualification needs one complete v3 run in which every row passes. The Windows
failure stands until the operator accepts a verified infrastructure cause or a
reviewed repair, and a rerun alone does not erase it. The qualification manifest
remains empty.

### Operator decision and rerun rule (November 7, 2026)

Fixed before the rerun:

1. The operator accepts the slower Windows host as the cause of the `51acf8e`
   Windows failure, on the evidence above. The failed attempt stays on record.
2. Exactly one corrected measurement: the next push that changes the native lane
   (the source-limit boundary tests from the review) runs the complete v3
   benchmark on both Python 3.14 platforms.
3. Only that run counts. Qualification of the v3 component gates needs every row
   to pass on both platforms in that same run. Rows from `51acf8e` are not combined
   with it.
4. If any row fails on either platform, that failure stands. There is no further
   retry. The result goes back to the operator as a gate-margin decision (the
   single 16 KiB mean has about 21% baseline headroom on this label).
5. For interpretation only, not as a filter: the `5221a7c` Windows reference is a
   native suite of 81.66 s, preflight mean 0.0112 s and single 16 KiB cold probe
   0.544 s. The run records its own figures.

## Approved S7 v2 amendment (superseded by v3 for new measurements)

On November 7, 2026 the operator approved the reviewed
[v2 measurement protocol](protocol-v2.md): maximum-source serial limits are
1.8 s mean / 2.0 s p95 / 2.3 s p99, plus an independent eight-wide maximum-source
gate at 7.5 s p95, every request ≤8 s, zero errors. Other latency limits,
coverage and cleanup bounds remain unchanged. Loaded samples increase to 104
per case, with pinned fixtures, exact findings/coverage checks, resource
telemetry and preserved partial failures. Historical measurements below retain
their original criteria and failure status. They do not qualify the new workload.

## Completed hosted measurements at 5a13965

The November 7, 2026 hosted run
[42369954500](https://github.com/Vigil-Harbor/Petasos/actions/runs/42369954500)
measured the PR merge revision `e59f4d14b30a32f84e445c9b635943579c3ff042`
for branch head `5a13965`. The unchanged artifact data is retained in
`hosted-mac-5a13965.json` and `hosted-win-5a13965.json`.

Both Python 3.14 native suites passed: Mac 242 passed with two Windows-only
skips; Windows 243 passed with one POSIX-only skip. The Mac run executed the
native zombie-group cleanup test and all four additional signal transitions.
Both benchmarks completed, closed their owners, and recorded no stage errors.
Single 16 KiB scans, all six eight-wide scheduling distributions and cancellation
replacements passed their gates. The 16-candidate/128 KiB workload failed all
three serial latency limits on both platforms. Windows also failed the
million-character preflight gate; Mac passed it.

These are **failed component qualifications**. Package S permits declared hosted
measurement hardware, so the Mac runner's three cores and 7 GiB RAM do not waive
its failed gates. Q's real-host hardware requirements and eight-hour soaks are
separate. The successful Windows cleanup in this run does not resolve the
earlier intermittent root-removal failure. At that run's revision no thresholds
or cleanup budgets had changed. The later amendment above changes only the
specified acceptance protocol; the qualification manifest remains empty.

## Earlier local evidence

These are exploratory Windows x64 / Python 3.14 measurements of the PET-254
package-S implementation candidate before its first commit. They are not a
qualification certificate or evidence of a Hermes gateway run. The engine and
rules digests, hardware and workload sizes are recorded in the JSON files.

- `windows-exploratory.json`: initial run, overlapping other regression tests.
  Single-request p95/p99 and maximum-source p99 missed the reviewed limits.
- `windows-isolated.json`: repeated without concurrent test suites. Single 16 KiB
  p99 was 3.162 seconds against a 1.4-second limit. Its mean and p95 passed;
  the 16-target / 128 KiB case passed all three thresholds. All three eight-wide
  distributions and cancellation replacements passed their p95 limits. Close
  completed successfully. This run predates the final prepared-input fingerprint
  check and is diagnostic evidence, not an exact committed-revision performance proof.

This earlier failed latency gate was not waived. The later approved amendment
requires new measurements; it does not reclassify these results. The packaged
qualification manifest remains empty. Native Apple Silicon, Python 3.11, and
hosted CI evidence was still outstanding at this historical revision.
The benchmark script exits nonzero on a missed gate and saves its measurements;
the native workflow runs it on both Python 3.14 platform cells.

Functional evidence collected during implementation: 3,495 base-suite passes
(172 optional skips and one expected failure), 165 final required-engine Windows
passes with no skips, and 388 JavaScript passes. The final focused base run passed
249 tests with three real-engine tests skipped; strict typing passed 218 source
files, Ruff passed, and the built wheel contains all rule assets. Synthetic process helpers establish lifecycle
behavior only. Detector evidence uses the pinned real engine and a separate
72-case held-out corpus (12 positive and 12 negative cases per language).

Remaining release work includes native resource/performance gates, the supported
Hermes cleanup callback, durable reporting, host warning delivery and both
8-hour real-host soaks. Package S does not enable the backend in Hermes.

## First code-review repairs (not qualification)

The repair candidate forces real parsing in every selected grammar, retains
findings across partial parses, projects indented fragments and earlier JSON
leaves, and admits work before allocating projection maps. It also consumes the
qualification manifest and pins both downloaded engine wheels and engine bytes.
The measurement script now records revision/environment identity, uses dense code,
exercises three owners, and saves stage timings and partial failed measurements.

Windows Python 3.14 verification during this repair pass:

- The broad regression run passed 3,514 tests, with 186 optional skips and one
  expected failure. This preceded the final additional regression fixtures.
- The subsequent required-engine run passed 198 tests and failed the native
  long-running-child cancellation test: cleanup exceeded its two-second budget.
  Five isolated repeats passed, but a separate 60-cancellation diagnostic
  reproduced one cleanup failure. Its original owned process handle signaled
  before the deadline; complete cleanup confirmation arrived later. The cause
  remains unresolved. This is a failed stability gate, not an accepted flake.
- Indented patch fragments across all four affected Python rule families, deep
  JSON with earlier code, Python line-boundary postfilter regressions, and the
  qualification fallback are covered by the passing required-engine cases.

The two-second cleanup budget and all latency limits remain unchanged. These
results do not qualify S, and the runtime continues to retain ownership/capacity
when cleanup cannot be confirmed. Native Apple Silicon, Python 3.11, hosted CI,
and real Presidio/PromptGuard/Semgrep composition remain unverified. The latter
now has an opt-in test requiring the actual backends and cached model assets.

## Second code-review repairs

Code-free JSON now bypasses engine queue admission after a bounded escaped-content
preflight. Native lifecycle work uses the existing two owned workers so a slow
CreateProcess call does not block the shared control loop. Windows launches use
detached processes with explicit pipes; the Job Object still owns each process
before it resumes. Native tests prove the simple child has no console-host member.
A worker timeout retains capacity and cleanup failures survive cancellation.

These changes do not yet establish stability: an intermediate required-engine run
passed 203 tests and failed the descendant-holding-pipes cleanup gate. Earlier
runs also recorded a probe prerequisite failure and an output-limit helper timeout.
Twenty subsequent descendant diagnostics completed, but do not erase that failure.
The runtime now retains bounded, source-free handle/accounting snapshots on failed
cleanup. The two-second bound and all latency thresholds remain unchanged.

## Third code-review repairs

Streaming preflight now carries whitespace and incomplete escapes across chunk
boundaries; the padded-call bypass has raw, JSON, mixed-leaf and double-escaped
regressions through the real engine. Native worker and supervisor share the
reported cleanup deadline, and findings survive a later language's native failure.
Constructor-watchdog and native-cleanup phases are documented separately; owner
and process-close absolute deadlines remain unchanged. No qualification is implied.

The pre-commit Windows/Python 3.14 native gate passed 224 tests, including the pinned
engine's Job-membership check (no descendants observed). Lifecycle helpers now
explicitly keep any intentionally-created console descendant hidden; stream tests
use the base interpreter rather than an unrelated virtual-environment launcher.
Historical cleanup and latency failures above remain evidence until the revised
commit completes its required gates.
