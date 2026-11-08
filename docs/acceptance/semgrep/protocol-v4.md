# S7 component measurement protocol v4

On November 8, 2026 the operator replaced the fixed eight-wide latency limits
with host-relative ones and raised the Windows serial single 16 KiB limits. The
criteria are named `S7-2026-11-08-v3`. The workload
(`eight_outstanding_three_profiles_16k_64k_v3`), fixtures, manifest digest,
case plan, sample counts, coverage and finding checks, resource telemetry, CI
budgets and interpretation rules are those of [protocol v3](protocol-v3.md),
unchanged. This supersedes v3 for new measurements only. Results measured under
`S7-2026-11-07-v2` keep that criteria name and their pass or fail status.

## Why

Three hosted Windows runs of essentially the same code passed once and failed
twice. The `windows-2025` label hands out at least three AMD CPU generations,
and the same CPU model varied 31% between runs. Single 16 KiB serial means
ranged from 0.778 to 1.022 s, a 1.3x spread on Windows and 1.8x across both
platforms. The eight-wide p95 divided by the same run's serial mean stayed
between 3.6x and 6.1x on every host and both platforms. Eight requests over two
slots is four rounds, so 4.0x is the ideal. That ratio is what the runtime's
scheduling controls. The absolute numbers move with host speed. The full
analysis is in the README section for this decision.

## Limits

| Case | Mean | p95 | p99 | Max | Other |
| --- | ---: | ---: | ---: | ---: | --- |
| Serial single 16 KiB, Windows | 1.2 s | 1.4 s | 1.6 s | none | |
| Serial single 16 KiB, other platforms | 1.0 s | 1.2 s | 1.4 s | none | |
| Serial 16 targets / 64 KiB, repeated and distinct | 1.8 s | 2.0 s | 2.3 s | none | |
| Eight-wide 16 KiB, six cases | none | 6.5 × serial single 16 KiB mean | none | 8.0 s | zero errors |
| Eight replacements | none | 6.5 × serial single 16 KiB mean | none | 8.0 s | zero errors |
| Eight-wide 64 KiB distinct, six cases | none | 6.5 × serial 64 KiB distinct mean | none | 8.0 s | zero errors |
| Preflight at examination ceiling | none | 50 ms | none | none | |

- The serial mean is the one measured in the same run, on the same host, for the
  same fixture. Loaded cases are never compared against another run or platform.
- The platform is the recorded `hardware.system` (`platform.system()`). A record
  without it gets the stricter non-Windows limits.
- A missing, non-finite or zero reference mean fails every loaded row that
  depends on it. A reference case with no successful samples has no mean.
- 8.0 s is the runtime's default per-request deadline. Every loaded and
  replacement sample must finish within it. Under v3, the 16 KiB and
  replacement rows had no maximum. They have one now.

## What this does and does not promise

Eight-wide latency is no longer a fixed figure on slow hardware. The bounds that
remain are the serial limits, the 6.5x ratio and the 8 s deadline. Together they
cap eight-wide 16 KiB p95 at 7.8 s on Windows (6.5 × 1.2) and 6.5 s elsewhere.
The 64 KiB rows are capped by the 8 s deadline. A host slower than the serial
limits fails on its serial rows.

The ratio gate catches a scheduling or contention regression that raises loaded
latency relative to serial latency. It does not catch a regression that slows
serial and loaded latency by the same factor. The serial limits still catch
that, with less margin on Windows than before.

Packaged `loaded_p95_seconds` stays the worst normal-loaded p95 across all
twelve cases, measured on a legitimately qualified run. The qualification
manifest stays empty. A component pass does not approve merging or enabling
Semgrep in Hermes.
