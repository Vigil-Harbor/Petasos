# Parity oracle

This directory is a replayable record of today's syntactic verdicts. The
redesign replaces `PetasosConfig`, the five built-in profiles and the
scanner bootstrap. Those replacements are checked by replaying this corpus
through `adapter.py` and diffing the result against `verdicts.json`.

`adapter.py` is the only file here that imports Petasos. A cutover
re-points that file at the new interfaces and leaves the corpus, the
recorded verdicts and `test_parity.py` untouched.

The record is syntactic only. Every case runs on the zero-dependency
`MinimalScanner` under default config, once for each built-in profile
(`general`, `code_generation`, `research`, `customer_service`, `admin`)
and once with no profile. `plugin:admin` and `plugin:research` bind that
profile to the pipeline and construct the guard without one, which is what
the reference plugin does. The other built-ins leave the guard's profile
inputs empty, so a separate plugin label would repeat the bare profile.
Single-shot cases use a fresh session. Session cases pin escalation by the
tier after each step, not by the score, because the score decays with
wall-clock time. The sequences are sized so a gap of a few seconds between
steps stays in the same tier.

`verdicts.json` stores each case on one line. The stored verdict is the one
shared by the most profiles. `base` names a profile that has it. `differs`
holds only the profiles that do not. A diff of the file is one case, and the
profile names in that line are the ones whose verdict changed.

## Platforms

The record was made on macOS, where `/tmp` is a link to `/private/tmp`.
Thirteen tool cases name the parity config file in free text as
`/tmp/petasos-parity-home/config.yaml`. On macOS the guard owns the resolved
path, so that text is not recognised and the record says nothing was
reported. Where `/tmp` is a real directory, as on Linux, the same text is the
owned path and a `petasos.selfmod.config_ref` finding is reported.
`test_parity.py` names those thirteen cases and expects that finding on such
a platform. Every other verdict is compared as recorded on every platform.
`verdicts.json` is not changed for this.

## Re-record

From the repository root, with the dev environment:

```bash
.venv/bin/python -m tests.parity.record
```

That rewrites `verdicts.json` from `corpus.json`. Run it twice and the
file must be byte-identical.

Re-recording is only legitimate for a deliberate, listed behaviour change.
A diff in `verdicts.json` is a behaviour change, and it has to be named in
the change that produces it. Do not refresh the file to make a failing
replay pass.

`harvest.py` rebuilds `corpus.json` from the test suites and the checked-in
corpora. It is not part of a normal test run. Changing the corpus is a
separate decision from re-recording verdicts.
