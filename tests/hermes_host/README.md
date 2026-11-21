# Hermes host harness

Optional tests that load a real Hermes checkout and drive its plugin manager.
The default `pytest` run skips them. `tests/hermes_host/test_environment.py`
binds a package index on `127.0.0.1` and resolves Hermes's other dependencies
from PyPI. The other files do not use the network.

The facts these tests pin are written up in
`docs/architecture/hermes-host-facts.md`.

## Safety

There are live Hermes installations on this machine. Do not read, write,
start, stop, or signal any of them.

- Do not touch `~/.hermes`, any `~/.hermes-*` directory, or any directory
  this machine lists in `~/.config/petasos/protected-dirs` (one directory per
  line, absolute or relative to the home directory, `#` for comments). Put
  every other place a live installation keeps code or data in that list. The
  file is local to the machine and is not part of the repository.
- Do not reuse an existing Hermes checkout or virtualenv. Clone upstream
  into the sandbox.
- Put the sandbox in a new dedicated directory, by default
  `~/.cache/petasos/hermes-sandbox/<name>`. One directory holds the clone,
  the virtualenv, `HOME`, and `HERMES_HOME`. A sandbox under any account
  Hermes directory listed above is refused, including the real account's
  `.hermes` even when `HOME` has been overridden.
- Run every Hermes command through `<sandbox>/bin/with-sandbox`. That
  wrapper sets `HOME` and `HERMES_HOME` to directories inside the sandbox
  and drops inherited `HERMES_*` variables. Hermes's account-default home
  still names the real `~/.hermes` if something calls it; the wrapper is
  what keeps `get_hermes_home()` inside the sandbox.
- Do not start a gateway or any other long-running Hermes process. Do not
  configure a messaging platform or a model provider, and do not call a
  model API.
- Install Hermes only into the sandbox virtualenv, with `uv`. Do not
  install it into the system Python or this repo's `.venv`.

## Prepare

Python 3.11 or newer runs the script. Hermes itself is installed on
CPython 3.14, which is the version its dependency pins target. `uv` must
be on `PATH`. The tag defaults to `v0.23.1`.

```bash
.venv/bin/python tests/hermes_host/prepare_sandbox.py --name lane-1
```

This prepares `~/.cache/petasos/hermes-sandbox/lane-1` (`--name` defaults to
`default`). Use `--dest <path>` to override the location. `/tmp` still works,
but macOS can clean its contents after about three days, including Node and
the web bundle. Use the durable default for work spanning multiple days.

One command clones `https://github.com/NousResearch/hermes-agent.git` at the
pinned tag, installs a sandbox-local managed CPython 3.14 and virtualenv with
`uv sync --frozen --no-dev`, installs Node 26.13.1 and pnpm 12.15.0 under
`<sandbox>/opt`, and builds the web bundle through `bin/with-sandbox`.
No system Node, sudo or Homebrew installation is needed. The sandbox's
`venv/bin/{node,npm,npx,pnpm}` links point inside it. The command also installs
a local Python 3.11 browser environment in `shot` with Playwright 1.56.0 and
Chromium headless shell under `opt/ms-playwright`, for the dashboard tab tests.
All Hermes imports and build commands run through the wrapper.

Rerun the same prepare command to resume or rebuild a partly cleaned sandbox.
It restores the pinned tracked checkout, syncs missing Python packages,
reinstalls Node and pnpm and rebuilds the bundle. Homes are preserved.
A nonempty unrecognized destination or a changed Hermes tag/commit is refused;
use a new directory for a different tag. Do not prepare while tests use that
sandbox. Preparation needs network access.

`<sandbox>/sandbox-manifest.json` records the Hermes commit, tool versions,
Node download URL and verified SHA-256, pnpm artifact URLs and verified
SHA-256s from Hermes's pinned `pm/lock.json`, and hashes of the frozen Python
and JavaScript dependency locks (which contain package download checksums). It
also records SHA-256s of the installed Python and browser executables.
Downloaded tool archives are retained in `<sandbox>/downloads`.

## Copy for a parallel lane

Stop processes in the source sandbox before copying it:

```bash
.venv/bin/python tests/hermes_host/prepare_sandbox.py \
  --copy-from ~/.cache/petasos/hermes-sandbox/lane-1 --name lane-2
```

The destination must be new and outside the source. The copy has independent
files and homes. The command rewrites editable-install metadata, environment
launchers and internal absolute links, including the Python interpreter and
Node/npm/npx/pnpm links. It confirms that Hermes imports from the copy and
that the toolchain runs. The original can then be renamed or removed without
breaking the copy. A raw filesystem copy does not perform these repairs.

## Homes

The sandbox checkout and its virtualenv are shared. Each test gets a new
Hermes home under `<sandbox>/homes/<label>-<id>`. Hermes stores a home's
package-manager environments in `<home>/installs/`, so a new home is a new
set of those environments too. Nothing in one home is visible to another.

`bin/with-sandbox` is what selects the home. It reads
`PETASOS_HERMES_HOME`, resolves it, and refuses to run when that path is
not strictly inside the sandbox or when it sits under an account Hermes
directory (`~/.hermes`, any `~/.hermes-*`, or a directory in
`~/.config/petasos/protected-dirs`). Inherited `HERMES_*`
variables are dropped. The default, when the variable is unset, is
`<sandbox>/hermes_home`. The in-process harnesses check the same boundary
before they import Hermes (`sandbox_guard.py`).

`HOME` stays `<sandbox>/home` for every test. Do not point it at a
per-test directory. Hermes account-default code still computes the real
`~/.hermes` from the password entry; the wrapper is what keeps
`get_hermes_home()` on the chosen home.

## What runs where

Two Pythons can import plugin code:

- The sandbox virtualenv (`<sandbox>/venv`). Harness actions and
  `python -m petasos` use it. `hermes` uses it only when the home has no
  committed package-manager environment.
- The home's committed environment
  (`<home>/installs/<key>/environments/<id>/venv`), once `hermes plugins
  enable` or `petasos hermes install` has run. `hermes`, including
  `hermes dashboard`, activates that environment at startup and removes
  the sandbox virtualenv's `site-packages` from `sys.path`.

`install_wheel` builds this worktree's wheel once per session and installs
it into the sandbox virtualenv. `install_home` copies
`hermes-plugin/petasos` into the home and enables it by writing that
home's `config.yaml` (it does not call `hermes plugins enable`, which
would commit a new environment). `ensure_wheel` installs the same wheel
into the home's committed environment when one exists. Tests that install
through `petasos hermes install` do not call it: that command declares the
wheel in the plugin's `pyproject.toml` and Hermes installs it.
`ensure_wheel` remains for tests that copy the plugin directory themselves
(`install_home`, and the in-process harness). The stand-in plugins follow
the same split: `install_standin_wheel` once, `prepare_standin_home` per home.
The environment tests that add a scanner, or that install by
`hermes plugins install`, serve wheels from `127.0.0.1` and set
`UV_EXTRA_INDEX_URL` to that index. An extra index is searched before PyPI,
so the test wheel wins for a name it publishes and Hermes's own packages
still come from PyPI.

## Run

```bash
export PETASOS_HERMES_SANDBOX="$HOME/.cache/petasos/hermes-sandbox/lane-1"
.venv/bin/python -m pytest tests/hermes_host -q \
  --ignore=tests/hermes_host/test_environment.py \
  --ignore=tests/hermes_host/test_dashboard.py \
  --ignore=tests/hermes_host/test_dashboard_tab.py
.venv/bin/python -m pytest tests/hermes_host/test_environment.py -q
.venv/bin/python -m pytest tests/hermes_host/test_dashboard.py \
  tests/hermes_host/test_dashboard_tab.py -q
```

Use the repo's Python 3.11 environment (`uv pip install -e ".[dev]"`).
Run these groups separately: the full real-Hermes suite takes over ten
minutes. The tests stay on that interpreter. Each one calls the sandbox's Python
through the wrapper, so Hermes is imported only inside the sandbox.

## A new test

Request one of the fixtures. Do not reuse `<sandbox>/hermes_home`, and do
not write a home outside `<sandbox>/homes`.

- `standin` — a fresh home with the stand-in directory plugins enabled.
  Use it for discovery, settings, and hook tests. Call
  `tests.hermes_host.client.call`.
- `installed` — a fresh home with the Petasos plugin directory and the
  test wheel. Use it when the test drives the real plugin through the
  harness (`petasos_harness.py`).
- `petasos_wheel` plus `fresh_home` — a fresh empty home whose sandbox
  interpreter can already run `python -m petasos`. Use it when the test
  itself is what installs the plugin. `petasos hermes install` puts the
  wheel where a later `hermes` process imports it. A test that enables the
  plugin some other way calls `ensure_wheel` before that `hermes` command.
- A module fixture that calls `fresh_home` once — only when several tests
  share one process, as the dashboard tests share one server. Stop that
  process in the fixture's `finally`, and `remember_pid` so the session
  reap stops it if the run is interrupted. The reap refuses to signal a
  process whose environment does not mention the sandbox.

A test that needs a prepared profile prepares it inside its own home.
Assert what that home does on its own. A second profile belongs under
`<home>/profiles/<name>`, which is still inside the sandbox.

## Try it follow-ups

`test_dashboard_tab.py` also exercises hidden personal information, input-only
risk and the version, in both themes at 1440 and 700 pixels. Its isolated
home copies `trial_fixture.py` beside the API loader. The fixture replaces
only the trial's optional personal-information detector, on the calling
`playground` module; the dashboard, API, pipeline anonymization (replace mode)
and risk calculation all run normally. No optional model or API is needed.

Capture the same states with the existing capture driver:

```bash
python tests/hermes_host/capture_round.py --sandbox ~/.cache/petasos/hermes-sandbox/lane-1 \
  --out .ux-reference/t1 --tryit-followups
```

The driver stops its dashboard, and reports script/API failures and horizontal
overflow. Inspect the four images before using them as evidence.

## README animation

The loop action uses the unmodified tab in the default Hermes Teal theme at
900 by 720. It checks a clean tool result, pastes a harmless instruction override,
shows its highlighted match and higher input risk, then visits recorded Activity.
Try it adds no events; Activity comes from `demo_harness.py`'s real hooks.
Each input starts a fresh risk calculation, so the preview does not simulate a
cumulative conversation score or a climb through tiers.

Install Pillow only in the sandbox's browser environment, then regenerate from
the worktree (choose a scratch output directory outside the repository):

```bash
uv pip install --python ~/.cache/petasos/hermes-sandbox/pet-277-278-impl/shot/bin/python Pillow==12.2.0
.venv/bin/python tests/hermes_host/capture_round.py \
  --sandbox ~/.cache/petasos/hermes-sandbox/pet-277-278-impl \
  --out ~/.cache/petasos/hermes-sandbox/pet-277-278-impl/tmp/readme-loop \
  --readme-loop assets/petasos-demo-loop.webp
```

The driver builds this checkout's wheel, creates a throwaway populated home,
starts its dashboard through `bin/with-sandbox` on `127.0.0.1`, and stops it in
`finally`. `--out` receives the PNG sequence, six named review frames, and
`frames.json` with millisecond durations. The JSON report includes the actual
encoded dimensions, frame count, duration, size, risk and browser errors.
The dashboard test group also exercises recording and encoding when Pillow is
installed in `shot`.
