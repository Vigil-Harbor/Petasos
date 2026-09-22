# Conventions Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: Unreleased Fixed bullet omits the changelog lead
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:21, spec.md:140
**Convention violated:** `CHANGELOG.md` house style under Keep a Changelog. Every current `## [Unreleased]` / `### Fixed` entry is a prepended bold lead ending in the ticket id.
**Evidence:** At `723cdc5`, `CHANGELOG.md:3` says the file follows Keep a Changelog, and `### Fixed` starts at line 110. The newest bullets are `**Named families no longer read composed views, and role-switch pairs on one view (PET-211, PET-212).**` (`:112-113`), `**Guard and reconfigure waits no longer leak the shared inspect mutex (PET-208).**` (`:124-125`), and `**Failed ingestion windows no longer claim complete coverage (PET-209).**` (`:134-135`). The spec only says "one bullet" plus the four sentences, and "No em dash." A literal bullet is a bare sentence with no `(PET-205)` lead, and it does not say to prepend it.
**Suggested fix:** Specify a prepended `### Fixed` bullet whose first sentence is a bold lead ending in `(PET-205)`, followed by the four claims already listed, with no em dash.

### F-2: Decision 3 chooses two outcomes the brief does not name
**Severity:** P3
**Where:** spec.md:54 | spec § Decision 3
**Convention violated:** None. These are spec-level additions with rationale (class (c)), not silent drift and not a break of PET-209 or PET-170.
**Evidence:** Brief contract items 1–5 never mention lock acquisition or a floor-error copy that raises. At `723cdc5`, `petasos/session/ingest.py:150-162` uses one `try` for acquire, `inspect`, and the `errors.extend` copy, and the shared `except` always sets `head = None`. Decision 3 keeps a lock `Exception` as `cause=boundary` and, if the copy raises, keeps `head` and leaves `inspect_failed` false, so that path is no longer `boundary`. Both choices are written down, and "a new cause for lock-acquire failure" is out of scope. That matches the brief's smallest-change rule. It is still behavior the brief did not decide: today's lock failure and today's copy failure are the same `head is None` result.
**Suggested fix:** Leave the choices. In Decision 3, state the operator delta in one sentence: a lock-acquire failure stays today's `boundary`; a floor-copy exception stops clearing `head`, so the plugin classifies the returned head (`floor_error` or `sweep_error`) instead of `boundary`.

### F-3: "Wins over sweep_error" names the wrong rival label
**Severity:** P3
**Where:** spec.md:71 | spec § Decision 4; spec.md:190
**Convention violated:** Cause-token naming. Decision 1 defines `boundary` as the missing-head label. `sweep_error` is only the later branch, after a present head and a clean floor.
**Evidence:** The plugin chain at `723cdc5` `docs/deployment/reference_plugin/__init__.py:2427-2433` assigns `boundary` when `head is None` and reaches `sweep_error` only in the last `elif scan.errors`. Decision 2 sets the flag only in the handler that also sets `head = None`. With that shape, a raising `inspect()` never reaches the `sweep_error` arm; the label it replaces is `boundary`. Chunk errors can still sit on `errors`, but they do not become the cause. Decision 4's "wins over a sweep error" and the Done-when line "Floor and sweep errors are not reported as `inspect_error`" are both true only for different cases, and the spec does not say so. PET-209 is otherwise respected: unavailability still wins, and the HIGH+ versus `sweep_error` rule is not retuned. `inspect_error` does not collide with `no_pipeline`, `raised`, `timeout`, `boundary`, `floor_error`, or `sweep_error`.
**Suggested fix:** Say that a raising `inspect()` clears `head`, so the cause it replaces is `boundary`. A later chunk error remains on `errors` and does not change that cause. `sweep_error` stays the head-present, flag-false, nonempty-`errors` case. Keep the pure floor and sweep pins labeled as they are now.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 2 | P4: 0

STATUS: GREEN
