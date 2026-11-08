# S7 component measurement protocol v3

[Protocol v4](protocol-v4.md) replaces this protocol's latency limits for new
measurements (criteria `S7-2026-11-08-v3`). Everything else below still applies.

On November 7, 2026 the operator lowered the supported Semgrep maximum source from
128 KiB to 64 KiB after the v2 workload failed its maximum-source gates on both
hosted platforms (capacity, not correctness: local profiling measured about
0.22-0.26 s of fixed engine start per launch, so three launches cost about 0.75 s
per request regardless of size, and four rounds over two slots overran the
8 s deadline). `semgrep_max_source_bytes` now defaults to and is bounded at
65,536. Supported code beyond the limit is reported as incomplete coverage and
follows `fail_mode`. The latency limits are the v2 criteria
(`S7-2026-11-07-v2`) unchanged; only the maximum workload changes. This
supersedes [protocol v2](protocol-v2.md) for new measurements. This is a
requirements amendment, not a qualification result. S remains unqualified until new measurements pass; historical failures remain evidence.
H/L/I/Q, real three-scanner composition, the qualification manifest and both
eight-hour real-host soaks remain separate requirements. The known cleanup
deadline edge and intermittent Windows root-removal failures remain unresolved.

## Limits

| Named fixture/case | Mean | p95 | p99 | Hard condition |
| --- | ---: | ---: | ---: | --- |
| Serial single 16 KiB | 1.0 s | 1.2 s | 1.4 s | Existing limits |
| Serial 16 targets / 64 KiB, repeated | 1.8 s | 2.0 s | 2.3 s | Independent pass |
| Serial 16 targets / 64 KiB, distinct | 1.8 s | 2.0 s | 2.3 s | Independent pass |
| Eight-wide 16 KiB | — | 5.0 s | — | Unchanged; zero errors |
| Eight-wide distinct maximum | — | 7.5 s | — | Zero errors, every request ≤8 s |
| Eight replacements behind two canceled active scans | — | 7.5 s | — | Existing cancellation/cleanup contract unchanged |
| Preflight at examination ceiling | — | 50 ms | — | Existing yielding/ceiling |

All table values are ceilings. Coverage, all three grammar attempts in separate
serial invocations, engine `-j 1`, two active jobs, capacity/lease bounds, failure
policies and cleanup deadlines are unchanged. The approved constructor allowance
is at most 2 s followed by at most 2 s native cleanup; no owner-close allowance
changes. Submitted fixture code is scanned, never executed.

Four service waves at 1.8 s would leave little room inside the 7.5/8 s loaded
bounds. Before this protocol was adopted, local diagnostics measured the 64 KiB
maximum at about 1.21-1.23 s serial against 1.62 s for 128 KiB.
This is a capacity budget, not proof that serial quantiles predict load. Both
the distinct serial and maximum loaded gates may still fail on hosted hardware.
The named dense ASCII Python fixtures do not qualify all accepted source shapes
or maximum JS/TS/non-ASCII inputs; their ordinary deadlines/failure policies apply.

## Fixed fixtures and measurements

`scripts/semgrep_workloads.py` generates the pinned
`scripts/semgrep_workloads_v3.json`. Its exact UTF-8/LF bytes, including one final
LF and no BOM, hash to
`62d448486c7d7b257750782278e03d62da68bfc85556184bb1dc870d5b14945e`.
Git attributes preserve LF. Each payload's digest, original segments and derived
expected findings are pinned too. A maximum request has sixteen 4 KiB fragments
(the worst case at the sixteen-target cap), 65,536 selected bytes and 65,551
envelope bytes, including 15 newline separators. Distinct fragments
use seeds `i * 1000`, i=0..15; repeated fragments use seed 0. Fixture generation
or expected-finding changes need a reviewed new workload identity, never an
edit to match observed results. A first-run mismatch fails.

The workload identity is `eight_outstanding_three_profiles_16k_64k_v3`. Record
revision, dirty state, Python, hardware, OS, runner label/image, engine/rule hashes,
fixture hashes and criteria version. Each request is timed from before prepare
through consumption and completed discard. Require exact finding IDs and original
spans, original-position basis and complete selected-target coverage. Do not
silently omit error samples or substitute faster samples.

Normal loaded cases run both shared-owner/three-key and three-owner/three-key
topologies, each with 3/3/2, 4/2/2 and 8/0/0 distributions. They are twelve
separate cases across the two sizes. Replacements use the first owner/key in a
three-owner/three-key setup, other keys idle: cancel two active jobs and immediately
submit eight replacements on that same key.

Use at least 100 serial samples and `ceil(runs / 8)` complete loaded/replacement
bursts: 13 bursts/104 requests at `--runs 100`. This strengthens the former 80
loaded samples. Warm up with one unmeasured scan or complete burst/cancellation
cycle; a warmup error fails. Requests within a burst are correlated. Record burst
IDs/maxima; no independent-trial or endurance claim follows. Quantiles use sorted
index `floor((n-1)*q)`; never pool cases or platforms.

Order: serial single, serial repeated maximum, six single loaded cases (shared
then three owners, distributions in order above), replacements, preflight,
serial distinct maximum, six maximum loaded cases. Each scan case gets fresh
owners/scanners and its warmup. Cold probes are timed separately. Any retained
failed runtime, cleanup failure or unsuccessful close stops the run; remaining
mandatory cases fail as not run. Do not reset global ownership to continue.

Preserve planned/started/completed/errored/unfinished/not-run counts, every started
sample, its terminal error, expected/observed findings and coverage. Failed elapsed
times are time-to-error, separate from successful latencies, and fail the case
regardless of quantiles. Persist partial evidence after each burst/case and at
least every 30 s via atomic checkpoints. A single request error must not erase
sibling results.

## Resources, CI and interpretation

Measure maps/buffers/control-loop responsiveness at width eight for both sizes.
The off-loop bounded monitor samples at no more than 10 Hz; record actual sample
counts, parent/owned-descendant RSS peaks, parent handles/FDs and threads before
and after, source/map/buffer high-water observations, control-loop lag, limit
errors and exact owned-root/runtime residue after close. Missing observations
are incomplete evidence, never zero. These are sampled observations, not proof
of instantaneous peaks; map budget charges are cumulative per selection, not
simultaneous allocations. No new numerical resource cap is introduced.

Monitoring is inside the measured run, with no overhead subtraction. Ownership
and cleanup still determine pass/fail. The script never scans unrelated temp
directories or signals a process for telemetry. Native CI has a 45-minute job
allocation and the benchmark a 35-minute measurement budget. On expiry, cancel
through owned APIs, close, retain partial evidence and fail. Never abandon a
worker or call `os._exit` to meet the script budget. CI always uploads the last
available checkpoint.

Keep every qualifying attempt and hardware identity. A failure under a supported
hosted label blocks that evaluated product/workload/criteria combination even
if a later attempt lands on a faster CPU. A retry or documentation-only commit
cannot erase it; require a reviewed relevant repair or verified infrastructure
cause and corrected measurement. New approved criteria must be named explicitly,
not retroactively applied to old artifacts. No SKU-specific qualification is
introduced here.

Only when legitimately qualified may packaged `loaded_p95_seconds` become the
worst normal-loaded p95 across all twelve cases. Old workload rows do not match
v3; the manifest stays empty and uses the existing unqualified 8 s fallback.
This script never populates that manifest. A component pass does not approve
merging the draft PR or enabling Semgrep in Hermes.
