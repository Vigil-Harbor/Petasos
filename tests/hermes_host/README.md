# Hermes host harness

Optional tests that load a real Hermes checkout and drive its plugin manager.
The default `pytest` run skips them. They do not use the network.

The facts these tests pin are written up in
`docs/architecture/hermes-host-facts.md`.

## Safety

There are live Hermes installations on this machine. Do not read, write,
start, stop, or signal any of them.

- Do not touch `~/.hermes`, `~/.hermes-second`, `~/hermes-services`,
  `~/model-lab`, `~/work`, or `~/notes`.
- Do not reuse an existing Hermes checkout or virtualenv. Clone upstream
  into the sandbox.
- Put the sandbox in a new directory under the system temp area. One
  directory holds the clone, the virtualenv, `HOME`, and `HERMES_HOME`.
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
python tests/hermes_host/prepare_sandbox.py --dest /tmp/petasos-hermes-sandbox --tag v0.23.1
```

The script clones `https://github.com/NousResearch/hermes-agent.git` at
that tag, creates `<dest>/venv` with `uv`, syncs the frozen lock with
`--no-dev`, and writes `<dest>/bin/with-sandbox`. It then asks Hermes for
its home and refuses to finish if that path is outside `<dest>`.

The dashboard tests also need Hermes's web bundle at
`<dest>/src/hermes-agent/hermes_cli/web_dist/index.html`. This tag has no
bundle in the checkout and refuses Node 22 (`package.json` engines,
`pnpm` 12.15.0 from `pm/lock.json`). Install Node 26 under the sandbox
(the prepare script does not download it), put `node` and that `pnpm` on
the wrapper's `PATH` (the sandbox `venv/bin` is on that path), and build
through the wrapper:

```bash
<path-to-node-26>/bin/npm install -g pnpm@12.15.0 --prefix <dest>/opt/pnpm
ln -sfn <path-to-node-26>/bin/node <dest>/venv/bin/node
ln -sfn <dest>/opt/pnpm/bin/pnpm <dest>/venv/bin/pnpm
<dest>/bin/with-sandbox bash -lc 'cd <dest>/src/hermes-agent && pnpm install --frozen-lockfile && pnpm --dir web run build'
```

## Homes

The sandbox checkout and its virtualenv are shared. Each test gets a new
Hermes home under `<sandbox>/homes/<label>-<id>`. Hermes stores a home's
package-manager environments in `<home>/installs/`, so a new home is a new
set of those environments too. Nothing in one home is visible to another.

`bin/with-sandbox` is what selects the home. It reads
`PETASOS_HERMES_HOME`, resolves it, and refuses to run when that path is
not strictly inside the sandbox or when it sits under an account Hermes
directory (`~/.hermes`, `~/.hermes-second`, `~/hermes-services`,
`~/model-lab`, `~/work`, `~/notes`). Inherited `HERMES_*`
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
into the home's committed environment when one exists, so a later `hermes`
process imports the test wheel rather than whatever that environment
resolved on its own. The stand-in plugins follow the same split:
`install_standin_wheel` once, `prepare_standin_home` per home.

## Run

```bash
PETASOS_HERMES_SANDBOX=/tmp/petasos-hermes-sandbox pytest tests/hermes_host -q
```

Use the repo's Python 3.11 environment (`uv pip install -e ".[dev,console]"`).
The tests stay on that interpreter. Each one calls the sandbox's Python
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
  itself is what installs the plugin. Before any `hermes` command, call
  the harness action `ensure_wheel` so the committed environment, if the
  test just created one, has the wheel.
- A module fixture that calls `fresh_home` once — only when several tests
  share one process, as the dashboard tests share one server. Stop that
  process in the fixture's `finally`, and `remember_pid` so the session
  reap stops it if the run is interrupted. The reap refuses to signal a
  process whose environment does not mention the sandbox.

A test that needs a prepared profile prepares it inside its own home.
Assert what that home does on its own. A second profile belongs under
`<home>/profiles/<name>`, which is still inside the sandbox.
