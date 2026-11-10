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

## Run

```bash
PETASOS_HERMES_SANDBOX=/tmp/petasos-hermes-sandbox pytest tests/hermes_host -q
```

Use the repo's Python 3.11 environment (`uv pip install -e ".[dev,console]"`).
The tests stay on that interpreter. Each one calls the sandbox's Python
through the wrapper, so Hermes is imported only inside the sandbox.

`tests/hermes_host/harness.py` is the in-process helper. It installs the
stand-in wheel and directory plugin, reads and writes plugin settings, and
dispatches a named hook through Hermes's own functions. The pytest files
cover discovery, settings, and the hook decisions recorded in the facts
document.
