# Composition gate

The hand-run scripts that drove this check are retired. What they verified,
and which of it the current tests already pin, is recorded in
`docs/architecture/retired-gate-scripts.md`.

A real Hermes is exercised only in the sandbox described in
`tests/hermes_host/README.md`. `petasos doctor` reports whether the home
you point it at is protected. Do not point either at a live Hermes home.

The verdict log below records the runs of those scripts for the 0.5.0
release. Its evidence files sit beside this README.

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

### 2026-11-23, run4: no-go

- Evidence: `windows-5acfbb9-run4.json`, SHA-256
  `9f668579621d1228bd112e857fd2cbab6fd3327d3e559e3665cb72a65b28da3a`.
- Verdict: no-go. Every stage ran.
- Failed checks: `warmup.*`, `health.presidio.*`, `corpus.margin.C06.*`,
  `corpus.default.C01`, `C03`, `C06`, `C07`, `C08` and the same five for
  `gibson`, every `load.pre.*`, `cold.presidio_follow`, `negative.block_shown`.
  `console.semgrep_refusal` passed on every matrix profile.
- Cause: the run's environment, not the wheel or the plugin. The workdir sat
  under `%TEMP%`, so the isolated root's deepest spaCy module
  (`transition_system.cp314-win_amd64.pyd`) had a 256-character path. Windows
  refused to load it ("The filename or extension is too long"), so Presidio
  could not import and every Presidio scan errored. The same module sits at
  201 characters under the live root. Step 4 now asks for a short workdir.
- Plane: none.
- Unholding #209: no-go for this run. Nothing in the release changed, so the
  next run uses the same wheel.

### 2026-11-23, run5: go

- Evidence: `windows-5acfbb9-run5.json`, SHA-256
  `762a19480e903f5c00f79e73edc4c2ac40fba1ec6bca4ce3e1c63057d0a6a9c9`.
- Release tree `5acfbb9`, `origin/master` `91428bc`, wheel SHA-256
  `98cd3c2898d13bbcb1f3326eb9b8914ab4e85f4d035c74e51c332ef6dd086148`, Hermes
  0.22.5 at `5019bf7`, workdir `C:\pg-gate`.
- Verdict: go. 477 checks passed, none failed, and every stage (`stage1`,
  `hooks`, `cold`, `negative`, `dash`) passed. `console.semgrep_refusal`
  passed on every matrix profile (PET-264).
- Plane: PET-261, PET-264.
- Unholding #209: go.
