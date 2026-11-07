# Isolated Semgrep code scanner

Semgrep is opt-in and uses existing severity, frequency and failure policies.
It detects code patterns without running the submitted code. Python, JavaScript
and TypeScript are the first language targets. Windows x64 and Apple Silicon
macOS are the native validation targets; neither this document nor a unit-test
pass establishes production qualification. The eight-hour Hermes gates belong
to the later host integration and qualification packages.

The library requires explicit lifecycle ownership. Bundled dashboards do not
start Semgrep. Current Hermes integration refuses it until the supported cleanup
callback and host delivery work land. Do not bypass that prerequisite by creating
a standalone owner inside a Hermes plugin.

## Installation

Install the adapter extra in the application environment:

```console
python -m pip install "petasos[semgrep]"
```

Install Semgrep CE **1.183.0** in a separate virtual environment. Keep its adjacent
libraries and upstream license notices; copying just the executable is unsupported.
The Petasos extra installs `psutil>=7,<8`, not Semgrep or its Python dependencies.
Semgrep is absent from the base install and `[all]`.

```console
python -m venv /operator-owned/path/semgrep-env
/operator-owned/path/semgrep-env/bin/python -m pip install semgrep==1.183.0
```

On Windows, use the environment's `Scripts/python.exe`. Locate the engine with
that isolated interpreter:

```python
import pathlib
import semgrep

print(pathlib.Path(semgrep.__file__).parent / "bin")
```

The executable is `semgrep-core.exe` on Windows and `semgrep-core` on macOS.
Configure its absolute path and SHA-256 digest from the trusted installation.
Protect both configuration and engine files with operator-owned permissions.
The digest detects replacement relative to configuration; it does not authenticate
an executable when an agent can rewrite both the path and the digest.

Petasos does not download, update or discover an executable through PATH. It uses
owned source files and an allowlisted child environment. Windows additionally
requires a short private temporary directory: the pinned engine's OCaml
`socketpair` startup fails when that path is too long. An unsuitable temp path
reports `semgrep.temp_path_limit`; choose a short operator-controlled OS temp
location and restart.

## Library ownership

```python
import asyncio

from petasos import Pipeline, SemgrepLifecycleOwner, SemgrepScanner


async def inspect_code(engine_path: str, trusted_digest: str) -> None:
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(
            owner=owner,
            engine_path=engine_path,
            engine_sha256=trusted_digest,
        )
        # Startup probes are asynchronous. Code scans report probe_pending until
        # a successful identity/version/protocol probe; health reads start no work.
        while scanner.availability()[1] == "semgrep.probe_pending":
            await asyncio.sleep(0.05)
        result = await Pipeline([scanner]).inspect("eval(user_input)")
        print(result.to_dict())
```

Use `build_scanners(config, semgrep_lifecycle=owner)` for config-driven construction.
An optional opaque `semgrep_scheduling_key` identifies a profile's queue across
scanner replacements; the owner and scheduling identity are separate. The owner
may span caller threads and event loops. Close one scanner with `await
scanner.aclose()`; leaving the owner closes all its remaining leases. A failed
context close raises `SemgrepCleanupError`, or preserves an existing body
exception and records the failure in `owner.close_result`.

`close_semgrep_runtime(deadline=time.monotonic() + remaining_seconds)` is a
synchronous operation for a shutdown worker, not an event-loop thread. It seals
future admissions. A timed-out observation retains ownership and reports residual
counts; it does not certify successful cleanup. Native Windows containment uses
Job Objects assigned before resume and retained process handles. macOS uses a
process group and observed descendant identities; this is not an OS security
sandbox against a deliberately escaping, unobserved descendant.

## Coverage and policy

No supported targets returns non-error coverage without launching an engine.
Tentative prose, shell, search excerpts and unsupported-language fragments that
no grammar accepts remain explicitly unsupported. Supported asserted code with
incomplete coverage follows `fail_mode`: errors make `degraded` and `closed`
unsafe. Findings survive incomplete scans and remain action-independent.

Lossless host pagination is annotated. A true line clamp or Petasos-side source
loss is distinguished from paging. The scanner inspects at most one million
original characters, selects at most sixteen targets, and retains up to 128 KiB
of decoded code in document order. It launches at most three grammar batches.
Coverage never substitutes the MinimalScanner sweep for Semgrep coverage.

Findings use original end-exclusive character coordinates, a fixed message
catalog and no matched source excerpt. A span across JSON escapes or line gutters
locates a finding; it is not an edit or redaction range. Python's bounded syntax
postfilter rejects empty suites that the raw engine accepts and conservatively
excludes proven local `eval`/`exec` definitions. Assigned aliases, indirect lookup
and computed properties remain detection limitations.

The process-wide pool permits two active requests and ten queued jobs, with
round-robin dequeue across scheduling keys. Two adversarial active requests can
delay siblings until their deadlines and cleanup finish; fairness is not
preemption. Per-lease preparation capacity is ten, including completed results
not yet consumed. Retired or replayed prepared tokens never run policy twice;
the guard treats this ownership error as unsafe even under open mode.

All five `semgrep_*` configuration controls require restart. The default deadline
is eight seconds, including queueing. Lower values remain unqualified at eight
outstanding requests until matching native measurements exist. Packaged reference
measurements are not a benchmark of the operator's machine.

## Validation status

The native workflow installs the engine separately and checks architecture,
integrity, version and protocol before collecting its required real-engine
classes. The held-out corpus includes twelve positives and twelve negatives per
language, including safe alternatives and `nosemgrep` comments. The runtime never
executes those submitted fixtures.

Production release still requires both native platform gates, the reviewed
latency/resource measurements, supported Hermes cleanup, durable reporting,
real-host model-warning proofs, and the eight-hour soak on each supported host.


## Parser and resource contract

The raw engine runs with irrelevant-rule and irrelevant-pattern filtering disabled.
A skipped parse is never evidence of complete coverage. Matches from every grammar
are retained before family/span deduplication; another grammar cannot erase a
finding. Common indentation is projected for all candidate fragments, including
comments and decorators. JSON keys containing code are examined too. A projection
limit retains already-selected targets and reports the unexamined tail.

Engine jobs acquire a bounded slot before projection. At most two active engine
jobs hold decoded source/maps; ten pending jobs retain only references to the
caller's original input. Error adapters without a runtime use two separate bounded
applicability slots and never start an engine. Transient file locks are retried off
the manager loop within the remaining two-second child/file cleanup budget.

An escaped-content preflight keeps code-free JSON out of engine admission, even
when the engine queue is saturated. Proven non-candidate JSON leaves need no
offset maps. Preflight carries incomplete escapes and compacted whitespace across
chunks, so arbitrarily padded calls cannot disappear at chunk boundaries. The
engine and finding coordinates still use the original, unmodified source.
Native child creation, polling and termination run on the same two
owned workers as other bounded work, so a slow native call cannot block the
manager loop. A worker exceeding cleanup time retains its job and root. Windows
children are detached from consoles with explicit stdio pipes and remain assigned
to their Job Object before resuming; no console host is needed for scanner output.

Once native termination starts, the worker immediately reports its absolute
two-second cleanup deadline to the supervisor; both observe that same deadline.
Before a constructor reports one, the supervisor retains a separate two-second
watchdog for a stalled constructor. The operator approved these separate phases
in PET-254 S5/S6 on 2026-11-07: cancellation during creation can include at most
two seconds of constructor wait followed by at most two seconds of native cleanup.
Control caps the combined allowance at four seconds after observed cancellation
or the absolute request deadline, even if a worker reports a later deadline.
This is not a promise that every cancelled scan returns within two seconds.
Owner and process-close calls
keep their original absolute caller deadlines and report outstanding ownership
on expiry. Findings from earlier language batches survive native cleanup failure.

Scheduling keys are opaque identities: reuse the same object across rebuilds of a
profile. Equality of distinct strings is insufficient. Each live lease retains its
key object, preventing object-ID reuse while queued or active work still owns it.

`semgrep_qualification.json` schema 1 contains a `measurements` list. A usable row
must have matching `platform` (`windows_x64` or `macos_arm64`), `engine_version`,
`engine_sha256`, `rules_sha256`, `workload` (`eight_outstanding_three_profiles`),
nonempty `hardware`, `qualified: true`, and positive `loaded_p95_seconds` at most 8.
Malformed, missing or mismatched evidence falls back to an unqualified eight-second
reference. A lower configured deadline reports the workload, reference value and
whether it came from packaged evidence or the fallback. No measured rows ship yet.

Ingestion's per-backend coverage is read-only. Its additive field supports
`dataclasses.asdict`; the pre-existing `head` still has its own `PipelineResult.to_dict`
serializer (its existing mapping proxies cannot be generically deep-copied).

CI verifies the downloaded wheel and extracted engine against the committed
per-platform hashes in `scripts/semgrep_engine_pins.json`.
The isolated wheel install uses `--no-deps`; the Python wrapper's dependency tree
is not used to run the pinned engine. The benchmark records
commit/dirty state, Python/Petasos versions, runner image, hardware and engine/rule
identities. It exercises dense code, both shared-owner and three-owner topologies,
and cancellation replacements, with source-free stage timing summaries.

For the additional real PII/injection composition gate, install the existing
Presidio/PromptGuard prerequisites and cached weights, set both
`PETASOS_TEST_SCANNER_COMPOSITION=1` and `PETASOS_TEST_SEMGREP_COMPOSITION=1`, provide
the isolated engine path, and run `tests/test_scanner_composition.py`. That gate
fails on missing prerequisites when requested and does not enable the backend in
Hermes. Native tests alone do not satisfy this combined gate.

Candidate admission recognizes sensitive callees separated from arguments by
newlines or Unicode whitespace only when followed by an opening parenthesis.
Domains, filenames and isolated words followed by whitespace do not qualify.
Candidate matching consumes maximal identifier runs once, using Python 3.11+
possessive matching rather than retrying at each dot. The same predicate serves
streaming preflight and whole-region selection. Source tests run million-character
dotted inputs behind a separate process watchdog, including JSON and early-code
wrappers; an asyncio timeout alone cannot interrupt a synchronous regex.
Declaration and dense-search headers use bounded linear scans, and fence matching
uses possessive quantifiers. The watchdog also covers long repeated return
annotations, dotted search headers and fence markers with embedded carriage
returns, both raw and JSON-wrapped.
A JavaScript comment opener after a
sensitive callee is enough for conservative admission, even across long comments;
the engine receives the original bytes and determines whether there is a finding.
Ordinary prose with a spaced word and parenthesis retains its existing treatment.
When a later language batch or the Python postfilter fails, completed engine
parse spans and deduplicated findings remain available alongside the overall
error. A postfilter failure retains conservative pre-exclusion findings.

Windows cleanup failures include bounded process-handle wait states, the Job's
total process count and best-effort executable basenames. These diagnostics do
not include source text, command lines or executable paths. They are evidence
for investigation, not a waiver of the cleanup deadline.

On macOS, signalling a group containing only zombies can return a permission
error because the kernel excludes zombies from group signalling. Cleanup may
reap a confirmed exited leader after that response, but succeeds only after a
separate check proves the group no longer exists. A surviving or inaccessible
group remains a cleanup failure. No termination signal is sent after the leader
is reaped, preserving the protection against signalling a reused process-group
ID. See [Apple's group-signal implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_sig.c).
