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
hashes, the Hermes commit, and the copied configuration whose digest its
evidence file names. A commit that changes one of those files, a different
wheel, a different Hermes commit, or a different copied `petasos:` section
(a different `section_sha256`) needs a new run. A commit that only adds the evidence file and its verdict
entry does not.

## What the gate shows

- The wheel that Hermes installed is 0.5.0, the installed files match the
  wheel, and Presidio, PromptGuard, and the spaCy model import.
- The Python that Hermes resolved for the run sits in the isolated root's own
  tool store (`stage1.store_isolated`). No probe runs on any other interpreter.
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

The gate gives the isolated root a tool store of its own by setting
`HERMES_RUNTIME_DIR` to `<isolated root>/tools`. Left alone, Hermes points a
root that borrows the live checkout at the live root's `tools` directory, and
the dependency sync locks that store, re-hashes each tool, and repairs any
that fail. That behaviour is read from the Hermes 0.22.5 source. The first
gating run is the first time the override is exercised.

One live read belongs to the operator, not to the gate. Run-procedure step 3
reads the store-Python path from `installs/<key>/facts.json` under the live
root. The gate never opens that file.

## Secret-free rule

The evidence file is built to carry no host name and no user name. Paths are
rewritten to
`<root>`, `<live>`, `<tree>`, `<workdir>`, `<hf_cache>`, and `<home>`.
There is no environment dump. `PETASOS_SESSION_SECRET` is recorded only as
the harness's fixed throwaway constant. Spool rows omit `sig`.

The evidence does not carry a profile's settings. A copied section keeps
`PetasosConfig` fields and `enabled`, and drops `hash_key`,
`session_secret`, and every other key. The evidence records only that
section's SHA-256, the names of the two keys the gate forces, and how many
keys were dropped. The settings a verdict depends on are the ones the corpus
assumes for each profile, and a check fails when the copied section differs
from them. Profiles left out of the matrix are counted by reason and not
named. The matrix profiles are named, because the corpus names them.

`hermes.tracked_clean` says whether the live checkout has no modified tracked
file, so that the recorded commit is the code that ran. Hermes's own version
string says `dirty` for an untracked file as well.

Before the file is written, a sweep looks for the home directory, the live
root, the workdir, the release tree, the host name, and the OS user name as
a path segment. On a hit the driver prints `evidence NOT written: contains
<which>` and exits 5. No file is written.

The sweep matches the user name only as a whole path segment. A user name
inside a longer word, such as a profile called `<user>-dev`, is not caught.
Read the evidence file before committing it.

## Reproduce

1. `git fetch origin` in the Petasos repo. In `../PET-release-0.5.0`, merge
   `origin/master` and push `release/0.5.0`. If the merge conflicts, stop.
2. Build the wheel from that worktree, for example `python -m build --wheel`.
3. Read the store-Python path from the live `installs/<key>/facts.json`.
   Do not hardcode it. Do not use anything else in that file.
4. Run the gate with a throwaway `--workdir` whose path has no space and no
   comma. The `python` that runs the driver needs PyJWT and PyYAML, for
   example a venv with `pip install "pyjwt[crypto]" pyyaml` or this
   repo's dev environment. The driver imports `petasos` from its own
   checkout and uses that `PetasosConfig` to decide which live settings
   to copy. Preflight stops when its `petasos/config.py` differs from the
   release tree's, so bring the driver checkout up to the same
   `origin/master` first. `--hermes-python` is a different interpreter and
   only starts the Hermes bootstrap:

```
python scripts/hermes_composition_gate.py <label> <release_tree> ^
  --wheel <path> --hermes-python <store-or-hermes-python> ^
  --workdir <empty-dir>
```

   The first run downloads the ML dependencies into the isolated root's own
   cache. It also downloads Hermes's pinned toolchain (Python, uv, and the
   other tools a source install needs) into `<isolated root>/tools`. Both
   survive the wipe, so a later run on the same `--workdir` reuses them.
   PromptGuard weights are read from the existing hub cache
   (`--hf-cache` overrides the default). The run does not send a Hugging
   Face token.
5. Only after exit 0 or 1: copy `<workdir>/composition-<label>.json` to
   `docs/acceptance/composition/windows-<release-short-sha>-<label>.json`.
   Add a verdict entry below. Commit those with the gate. Any other exit
   wrote no evidence, so never copy after one. A run removes the previous
   file for its label once its label and workdir pass preflight.
6. Post the Plane comment. File a Plane item for each defect. Fill in
   `smoke-checklist.md` before the ticket closes. The checklist does not
   change the verdict.

Exit 0 is go. Exit 1 is no-go with evidence written. Exit 2 is a preflight
stop with no verdict. Exit 4 means a probe found its dependencies on the
live root, and no evidence is written. Exit 5 means the secret-free sweep
refused the file. Exit 6 is an unexpected error.

## Verdict log

Each recorded run adds one entry: date, evidence file and its SHA-256,
verdict, failed checks, Plane items, and the written go or no-go for
unholding #209.

### 2026-11-10, run1 and run2: no-go

Both runs used release tree `5549d62` and stopped at stage 1, so `hooks`,
`cold`, `negative`, and `dash` were skipped and no corpus case ran.

- Evidence: not in this repository. Both files were written before the
  evidence stopped carrying profile settings and the names of excluded
  profiles, so they stay on the host. SHA-256 of `composition-run1.json`:
  `09606e18e1912112cbc458aeaa4dfd2026f8e37fb20e96f95b51d927d4d880f9`. SHA-256
  of `composition-run2.json`:
  `2b8028b4a0ff8ee0da13bfb9c8d8c2f98c213544fe73bcbe1d4a09863ac51c46`.
- Failed checks, both runs: `stage1.bootstrap`, `stage1.plugin_kept`,
  `stage1.completed`. `stage1.store_isolated` passed: Hermes resolved its
  Python from the isolated root's own tool store.
- Cause of run1: a defect in the gate's harness, not in the wheel or the
  plugin. Hermes disabled the plugin on all three matrix profiles because its
  dependency resolve needs git, and the resolver could not find `git.exe`. The
  harness kept `PATH` for its children and dropped `PATHEXT`. A real Hermes
  session inherits `PATHEXT`. The harness now keeps it.
- Cause of run2: the fix was not loaded. The driver's Python had an editable
  install of another checkout, and the gate took that checkout's harness. Its
  evidence names the old harness hash. The gate now takes the harness beside
  its own file when it is started as a file.
- Plane: PET-262.
- Unholding #209: no-go. Neither run says anything about the wheel. The gate
  and the harness changed, so a new run is needed.

### 2026-11-10, run3: no-go

- Evidence: `windows-5549d62-run3.json`, SHA-256
  `05f54d8d0472d8be9899b69760e82ab98e31eb8f4d7c0cfe5521cd56f2ed08bb`.
- Verdict: no-go. The run stopped at stage 1, so `hooks`, `cold`, `negative`,
  and `dash` were skipped and no corpus case ran.
- Failed checks: `stage1.bootstrap`, `stage1.plugin_kept`, `stage1.completed`.
  `stage1.store_isolated` passed.
- Cause: a defect in the reference plugin manifest, found with the fixed
  harness loaded. Hermes locks one workspace for every platform, Android
  included. The manifest required `petasos[presidio,prompt-guard]` on every
  platform, and torch has no Android wheel, so the lock had no solution.
  Hermes then disabled the plugin on all three matrix profiles. A real
  Hermes 0.22.5 host would have installed the 0.5.0 plugin with no hooks. The
  manifest's requirement now excludes Android.
- Plane: PET-263.
- Unholding #209: no-go. The manifest changed, so a new run is needed.
