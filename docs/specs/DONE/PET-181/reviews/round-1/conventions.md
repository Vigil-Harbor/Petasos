# Conventions Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: Decision 1 claims to honor PET-179 sequencing it actually ships past
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:51 | spec § Decision 1
**Convention violated:** wiki `decisions/2026-09-15-pet-179-two-axis-tool-classification.md` Decision 2 (invert sequenced after PET-178); prior-decision axis — contradict without proposing supersession
**Evidence:** Wiki Decision 2: “Closing that fail-open is PET-181, sequenced after PET-178.” Spec Decision 1: “**Honors.** Brief Decision 1; wiki … Decision 2 (invert sequenced after PET-178)”. The brief’s Q1 C *does* authorize invert-only now, with PET-178 as residual, and the spec’s design matches the brief. The defect is the Honors line: it names the sequencing constraint as honored while this ticket ships invert with PET-178 still Backlog. That is inadvertent drift in the decision record, not in the code plan. Plane still lists PET-178 as blocker; the spec already says the brief wins on ticket wording, but it never says the wiki sequencing is superseded.
**Suggested fix:** In Decision 1, replace the Honors clause with an explicit supersession of *sequencing only*: PET-179 sequenced invert after PET-178 because invert-with-pool died in review; this ticket ships invert-only (brief Q1 C), leaves cheaper scans / P=80 as a PET-178 residual, and does **not** reopen wiki Decision 1 (one table, derived sets) or Decision 3 (no pool in PET-179). Keep the two-axis table; supersede only “PET-181 waits for PET-178”.

### F-2: CHANGELOG plan does not record the published-name semantic change
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:29 | spec § Scope (CHANGELOG.md row); also spec.md:285 (Done when — ML posture / CHANGELOG)
**Convention violated:** CLAUDE.md Implementation Discipline — public API surface gets a CHANGELOG entry, not a silent meaning change; PET-179 Unreleased Added bullet
**Evidence:** `CHANGELOG.md:31-36` still-Unreleased Added: “`petasos.session.guard.INGESTION_TOOLS` (PET-179). The result-axis selection set… The reference plugin requires a `petasos` release exporting `petasos.session.guard.INGESTION_TOOLS`.” Spec CHANGELOG instruction: own Changed/Fixed line for unknown-tools-scanned + ML posture, own Added line for `NON_INGESTING_TOOLS`, “not a bullet inside the PET-179 entry”. It never requires stating that `INGESTION_TOOLS` is **no longer** the seam’s membership test. Both bullets will ship in the same release (`v0.3.0` is still the latest tag; PET-179 is Unreleased). CLAUDE.md: “public breakage gets a deprecation cycle and a CHANGELOG entry, not a silent removal.” Membership of the 17-name frozenset is unchanged; the documented role (“the set the seam *selects*”) is not. `hermes-desktop.md` is told to document the gate change; CHANGELOG is not.
**Suggested fix:** The PET-181 Changed line must say `INGESTION_TOOLS` remains the named hook-reaching subset and is no longer the seam’s gate; `NON_INGESTING_TOOLS` is. Amend the still-Unreleased PET-179 Added bullet (same release) so it does not publish “selection set” as current meaning — e.g. add “PET-181: no longer the seam’s membership test.” Pin the re-export posture on the new Added line: not re-exported from `petasos`, matching `READ_ONLY_TOOLS` / `INGESTION_TOOLS` (`CHANGELOG.md:33`).

### F-3: Cotenant “can never contend” comment and files-to-change pin left stale vs D11
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:23 (Files to change — `_INGESTION_CANON` parenthetical); spec.md:158-162 | spec § Decision 11; live `docs/deployment/reference_plugin/__init__.py:2546-2548` and `tests/test_reference_plugin_tool_result.py:1279-1286`
**Convention violated:** CLAUDE.md comments must stay factual; filemap standing hazard on this file — load-bearing comments that lie get re-copied into the hand-synced plugin
**Evidence:** Plugin comment today: “its target set is disjoint from `_INGESTION_CANON`, so it can never contend.” Test name/docstring: `test_bundled_security_guidance_target_set_can_never_contend` / “It can never discard a Petasos annotation because its target set is disjoint from the ingestion set.” D11 correctly accepts `skill_manage` overlap on the *scanned* set and asks to update that test. Files-to-change still says keep `_INGESTION_CANON` as “the named-subset cache (**cotenant disjoint pin**, `test_no_row_canonicalizes_away`)”. After invert, `_INGESTION_CANON` is unchanged (still the 17-name named subset, still disjoint from `{write_file, patch, skill_manage}`), so the old assertion keeps passing while proving the wrong claim. D11 says the INFO log stays; it does not say to rewrite the comment above it that asserts disjointness.
**Suggested fix:** (1) Files-to-change: `_INGESTION_CANON` is the named-subset cache and `test_no_row_canonicalizes_away` pin only — cotenant is D11. (2) Plugin comment at the `PETASOS_INGESTION_SCAN_COTENANT` site: `write_file`/`patch` stay excluded; `skill_manage` inherits ingest and can contend under host first-string-wins (PET-170). (3) Rename or retitle the test so it does not still claim “can never contend”; D11’s pins (`write_file`/`patch` excluded, `skill_manage not in NON_INGESTING_TOOLS`) stay.

### F-4: ToolAxes “row exists only on deviation” invariant rewritten only in Decision 2
**Severity:** P3
**Where:** spec.md:69-70 | spec § Decision 2 Row hygiene; spec.md:168 | spec § Design / Table item 1
**Convention violated:** wiki PET-179 Decision 1 — “A row exists only where a tool deviates from the defaults (`acts=True`, `ingests=False`, `reaches_hook=True`)”; `guard.py:63-64` restates that on `ToolAxes`
**Evidence:** Decision 2: a row still exists where a tool **deviates** from the *new* defaults **or** already carries a per-row evidence pin; do not drop the twelve `browser_*` rows. Design item 1 only says “`ToolAxes` docstring defaults become `acts=True`, `ingests=True`, `reaches_hook=True`.” An implementer who updates only the three default tokens leaves “A row exists only where a tool deviates…” as a lie about the twelve browser rows, which now *match* the default. Keeping those rows is the right call (wiki Decision 4: no silent drop of a published set; dropping them would shrink `INGESTION_TOOLS` 17→5). The exception needs to live on the docstring the implementer is told to edit.
**Suggested fix:** Design item 1: rewrite the whole `ToolAxes` docstring sentence to Decision 2’s rule (defaults plus evidence-pin rows that now match), and name the browser family as the kept pins.

### F-5: Spec-level additions the brief authorized as pins, plus D11
**Severity:** P3
**Where:** spec.md:93-97 (D4), 99-115 (D5), 129-139 (D8), 152-156 (D10), 158-162 (D11), 217-219 (alias layer)
**Convention violated:** silent-additions axis (c) — spec-level additions with rationale; brief Risks 1–4 said “spec author pins this”
**Evidence:** Brief does not choose the 30s window, the 10_000 map bound, census 81 vs ~68/72, or `verify.py` requiring both exports. It also does not name `skill_manage` or the `write`/`write_file` alias split. The spec flags each as Chosen with reasoning. None of these change brief scope; they are the drift-check list.
**Suggested fix:** None required for gate. Human drift-check: D4 exclude `write_file` despite lint/LSP JSON; D5 sibling 30s clock, own map, drop-oldest at `_MAX_DISARM_SESSIONS`, `"uncorrelated"` bucket (not `anon-{uuid8}`); D8 census 81 production names, 73/81 conceptual ingesting, P=8 measured / P=80 residual; D10 `verify.py` keeps `INGESTION_TOOLS` and requires `NON_INGESTING_TOOLS`; D11 accept `skill_manage` overlap rather than exclude without evidence; Design “Alias layer is not the exclusion layer” (PET-118 alias-free classification — do not auto-exclude `write`).

### F-6: Cadence lookup of `_session_ids` does not name the existing lock
**Severity:** P3
**Where:** spec.md:108 | spec § Decision 5 key step 3
**Convention violated:** plugin convention at `_derive_session_id` / PET-138 — `_session_ids` is mutated under `_bypass_lock`; filemap: concurrent dict resize is the reason the lock exists
**Evidence:** `reference_plugin/__init__.py:942-950` inserts under `_bypass_lock` “so two threads racing a fresh `_agent` cannot mint two ids … or trigger an unsafe concurrent dict resize.” Spec: “the stable `desktop-{uuid12}` from the existing `_session_ids` map (same lookup `_derive_session_id` uses; do not mint a second id).” It does not say the read takes `_bypass_lock`, nor what to do on a miss (`_agent` present, id not yet in the map). A lockless get plus a fall-through mint would reintroduce the race the lock exists to close; a lockless get plus fall-through to `"uncorrelated"` is the intended “do not mint” policy but is unstated.
**Suggested fix:** Cadence helper: lookup `_session_ids` under `_bypass_lock`; on miss do not insert — fall through to `"uncorrelated"`. Do not call `_derive_session_id` (that would mint `anon-{uuid8}` on the no-agent path and break the cap).

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 3 | P4: 0

STATUS: GREEN
