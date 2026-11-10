# Composition gate

Hand-run check that the 0.5.0 wheel, installed by Hermes itself from the
reference plugin's unmodified manifest, composes MinimalScanner, Presidio,
PromptGuard 2, and a refused Semgrep on an isolated Hermes 0.22.5 root.
The script is `scripts/hermes_composition_gate.py`. It does not arm the live
gateway and it does not hold a provider key.

A verdict is go only when every gating check passed. Any other completed run
is no-go. A first-run mismatch is a defect, or an expectation change that
carries a written reason in the corpus and in the verdict log below. It is
not fixed by editing an expectation to fit what was observed.

## What a verdict counts for

A verdict counts only for the script, harness, corpus, wheel, and plugin-file
hashes and the copied configuration named in its evidence file. A later
commit, a different wheel, or a different copied `petasos:` section needs a
new run.

## What the gate shows

- The wheel that Hermes installed is 0.5.0, the installed files match the
  wheel, and Presidio, PromptGuard, and the spaCy model import.
- Each matrix profile's copied arming configuration is what the corpus
  assumes, and each case matches its expected directive or return class and
  its expected spool row.
- Health on the gateway copy and on the console matches the ground truth for
  every backend. Semgrep is enabled with no lifecycle owner, so its build
  outcome is `failed` / `semgrep.host_lifecycle_unavailable`, it is not a
  registered scanner, and no spool row carries a Semgrep rule.
- Eight requests are in flight at once. Each call stays under Hermes's 30
  second hook bound. The recorded timings are measurements, not a latency budget.
- Cold start delivers a 0.05 second timeout during load, the following scan
  completes, and seven of eight queued PromptGuard scans cancel.
- With PromptGuard's cache pointed at an empty directory, a `closed` or
  `degraded` profile blocks and an `open` profile passes. At least one
  profile must show that block, and only after the same run's benign case
  C01 and PromptGuard case C04 matched.
- Signed spool rows verify under the harness throwaway secret and fail under
  a different constant. The evidence stores `sig_verified` and drops `sig`.
- When a matrix profile uses the approve posture, one fetch-exec call is
  answered inside Hermes's notify callback. Today's matrix does not use that
  posture, so the evidence says the path was not exercised.

Nothing is anonymized. No copied section sets `anonymize`.

`ops` has the tool guard off, so the corpus expects it to pass the pre-call
cases. That is the configuration under test, not a miss, and a verdict entry
should say so when the run confirms it.

The numbers at 8 outstanding are call wall time. Each plugin copy holds its
own inspect lock across a scan, and PromptGuard runs one inference at a time
for the process. Waiting inside a copy counts against Hermes's 30 second
bound. It does not count against PromptGuard's 8 second lock deadline.

## What it does not show

- A first-time gated weight download. The run is offline and requires a
  snapshot that is already complete. The gate checks that the snapshot
  directory's file list and sizes do not change. It does not prove a download.
- That an abandoned scan's text is never scored or analysed. That stays with
  the PromptGuard and Presidio unit tests named in the spec.
- Whether a live profile's plugin is enabled. The gate reads only the
  `petasos:` section, plus two existence checks.
- macOS, or any second host.
- Latency budgets. Timings are recorded and do not gate.
- Session escalation. Every case uses its own session.
- The approval path, whenever no matrix profile uses the approve posture.
- A real model turn. That is the smoke checklist, and it does not change the
  verdict.
- Memory use. The gate does not record it.
- That the live Hermes checkout is left untouched by Hermes itself. Hermes
  claims its update marker while it syncs a throwaway root that borrows the
  live checkout. That marker lands in the isolated root (`HERMES_HOME`), not
  in the shared checkout.

One live read belongs to the operator, not to the gate. Run-procedure step 3
reads the store-Python path from `installs/<key>/facts.json` under the live
root. The gate never opens that file.

## Secret-free rule

The evidence file has no host name and no user name. Paths are rewritten to
`<root>`, `<live>`, `<tree>`, `<workdir>`, `<hf_cache>`, and `<home>`.
There is no environment dump. `PETASOS_SESSION_SECRET` is recorded only as
the harness's fixed throwaway constant. Spool rows omit `sig`. A copied
section keeps `PetasosConfig` fields and `enabled`, and drops `hash_key`,
`session_secret`, and every other key (their names are listed under
`withheld_keys`).

Before the file is written, a sweep looks for the home directory, the live
root, the workdir, the release tree, the host name, and the OS user name as
a path segment. On a hit the driver prints `evidence NOT written: contains
<which>` and exits 5. No file is written.

## Reproduce

1. `git fetch origin` in the Petasos repo. In `../PET-release-0.5.0`, merge
   `origin/master` and push `release/0.5.0`. If the merge conflicts, stop.
2. Build the wheel from that worktree, for example `python -m build --wheel`.
3. Read the store-Python path from the live `installs/<key>/facts.json`.
   Do not hardcode it. Do not use anything else in that file.
4. Run the gate with a throwaway `--workdir` whose path has no space and no
   comma:

```
python scripts/hermes_composition_gate.py <label> <release_tree> ^
  --wheel <path> --hermes-python <store-or-hermes-python> ^
  --workdir <empty-dir>
```

   The first run downloads the ML dependencies into the isolated root's own
   cache. PromptGuard weights are read from the existing hub cache
   (`--hf-cache` overrides the default). The run does not send a Hugging
   Face token.
5. Copy `<workdir>/composition-<label>.json` to
   `docs/acceptance/composition/windows-<release-short-sha>-<label>.json`.
   Add a verdict entry below. Commit those with the gate.
6. Post the Plane comment. File a Plane item for each defect. Fill in
   `smoke-checklist.md` before the ticket closes. The checklist does not
   change the verdict.

Exit 0 is go. Exit 1 is no-go with evidence written. Exit 2 is a preflight
stop with no verdict. Exit 4 means a probe found its dependencies on the
live root, and no evidence is written. Exit 5 means the secret-free sweep
refused the file. Exit 6 is an unexpected error.

## Verdict log

No run has been recorded. The evidence file is produced only by a real
gating run, and this repository does not contain one yet. There is therefore
no written go or no-go for unholding draft PR #209.

Each recorded run adds one entry: date, evidence file and its SHA-256,
verdict, failed checks, Plane items, and the written go or no-go for
unholding #209.
