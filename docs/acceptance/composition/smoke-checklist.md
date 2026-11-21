# Composition smoke checklist

The hand-run gate this checklist followed is retired. A real Hermes check
is the sandbox in `tests/hermes_host/README.md`. `petasos doctor` reports
whether that home is protected. Do not point either at a live Hermes home.

The model turn below is not part of the automated suite, and it does not
change a test result. It needs a provider the operator supplies. The
sandbox must not be given a provider key.

## Session environment

Use a home prepared by `tests/hermes_host/README.md`. Put
`PETASOS_SESSION_SECRET` in that home's `.env`. `petasos doctor` names a
secret it cannot read, and it does not print the value.

`PYTHONDONTWRITEBYTECODE=1`.

## Turns

Pick one profile whose protection is on. A paused profile lets an
injection command through, so the second turn would read as a failure.

Before the turns, note the line count of that profile's
`petasos-enforcement.jsonl` (in the home for the default profile,
otherwise in `profiles/<name>`). Only lines after that count belong to
this session.

Record pass or fail:

| Turn | Pass condition | Result |
|---|---|---|
| A benign tool turn runs | The tool executes and Petasos does not block it | |
| A terminal command carrying injection text | Refused with the `[BLOCKED by Petasos]` message | |
| A read of a file holding injection text | The result comes back with the `[Petasos]` notice | |
| The profile's own spool | Rows after the noted line count match the blocked command and the flagged read, and are signed | |

Date:

Profile:

Spool line count before the turns:

Notes:
