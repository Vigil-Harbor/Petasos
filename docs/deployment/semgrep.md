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
