# The interface loop

The Petasos tab is built in a judged loop (section 8.4 of `redesign.md`). A
generator revises the tab. Four independent judges each score one criterion
out of ten from a fixed set of screenshots, beside reference screenshots of
Hermes's own dashboard and of a well-regarded secrets manager. The loop ends
when every score reaches the bar.

- Generator: Opus. Judges: Codex, one per criterion.
- The judges are not told the bar, that there is one, who built the tab, or
  that it will be revised. Each must first report details from a named
  screenshot to show it can see the images.
- The scale is the same for all four and carries written anchors: 6 to 7 is
  competent with notable weaknesses, 8 is good with only minor issues, 9 is
  excellent, 10 is exemplary.
- The screenshot set is fixed so rounds compare: ten states in each of
  Hermes's two themes, and one narrow layout. Round 2 added five states,
  kept since. Screenshots and references live
  in `.ux-reference/`, which is not committed.
- Bar: 8 on every criterion.

## Scores

| Round | Visual design | Usability | Conventions | Fit with Hermes |
|---|---|---|---|---|
| 1 | 6 | 6 | 7 | 7 |
| 2 | 7 | 7 | 7 | 8 |
| 3 | 7 | 7 | 7 | 8 |
| 4 | 7 | 7 | 7 | 8 |

## Round 1

Built from the brief alone. Four views (Overview, Activity, Try it,
Settings), all on real data in a sandboxed Hermes dashboard.

What the judges agreed on:

- **Status badges are hard to read** (design, conventions, usability): tiny
  condensed lettering, and dim red, green and amber on dark fills.
- **Rule identifiers wrap mid-word** in the preview and the event detail
  (design, conventions).
- **"Put back" does not say where the value goes back to** (conventions,
  usability).
- **The light theme is one saturated blue** (design, conventions), though
  the fit judge counts that as faithful to Hermes.

Visual design, 6. Disciplined alignment and grouping; the smallest and most
consequential text is the hardest to read. Also: the change preview gives its
evidence too little width; too many nested outlines; the two choices take
more room than the evidence that protection is working; the Try it layout is
unbalanced with settings expanded; tabs and small headings are too delicate.

Usability, 6. Both users can get through their tasks, with clear paused and
unsaved states. Held back by two things. The casual user's preview before
committing is an expert diff (`rules.suppress`, rule ids, a confidence
floor), and a first-install warning sends them to an env file. And several
statements invite stronger conclusions than the evidence supports:
"Protected… every tool call is checked" beside three skipped scanners; a
trial result headlined "Allowed" when the saved settings would ask a person;
"How sure: 100%" for a pattern match; a critical self-change event marked
"Recorded" without saying whether the change went through; "the signature
checks out" without saying what that proves. For the technical user: no
search by event id or text, no custom range, no matched text in the event
detail, no entry format for tool-name fields, no statement of when a save
takes effect.

Conventions, 7. Controls match their meaning, the preview precedes an
explicit apply, defaults and overrides are distinguishable, validation sits
at the field. Held back by badge legibility, audit timestamps without year
or timezone, no visible cue that an activity row opens, vague reset wording,
action labels that hide the action ("Only this conversation", "Review"), and
example buttons that read like commands.

Fit with Hermes, 7. Frame, palette, panels, inputs and badge lettering
belong. Held back by habits from another product: settings laid out as label
left and control right with a checkbox, where Hermes's Config page runs the
control beneath the label and uses a switch; the Overview's stacks of
explanatory radio cards, which Hermes has no pattern for; a conversational,
instructional voice in headings where Hermes uses terse labels; underlined
text tabs where Hermes uses enclosed adjoining tabs; a bottom save bar where
Hermes saves from a top toolbar; an empty state borrowed from the kanban
columns; coloured edge bars repeated on unrelated elements.

### Where the judges pull against each other, and the ruling

- **Badge lettering.** Three judges want larger, normal-width status text;
  the fit judge credits the condensed face as Hermes's own. Ruling:
  legibility wins where the badge carries a safety meaning (severity,
  outcome, verdict). Keep Hermes's badge for incidental labels; make
  operational status readable within Hermes's kit, by size and contrast
  first, and by a different Hermes text style if that is not enough.
- **Plain words against terse labels.** The owner's requirement that a casual
  user never feel stupid outranks fit. The two reconcile in Hermes's own
  pattern: a terse label as the heading, and the plain sentence beneath it as
  the description.
- **The two choices.** Stacked explanatory cards read as a setup wizard and
  crowd out the evidence. Ruling: a compact, native single-choice control for
  each, with every option's plain description still visible without clicking
  through them, and the recent-activity evidence moved up.
- **The light theme's blue.** Fidelity to Hermes stands. Improve hierarchy
  with weight and size, not new colours, and make links distinguishable by
  underline.
- **Staged saving.** Hermes saves from a toolbar and has no review step. The
  review and try-first steps stay, because proving a change before it takes
  effect is a stated requirement; the controls move to where Hermes puts
  Save.

## Round 2

Revised against every numbered problem from round 1, under the rulings
above. Screenshots: the same fixed set, plus five states round 1 could not
show (the review before saving, the confirmation after it, the status with
a recommended check missing, a search with a custom range, keyboard focus).

Words moved to their source. Every section and setting declares a plain
`label` (and, for a choice, a label per choice) with `setting()`; roles and
levels carry a label and a description that states the consequence; the
four stored settings have labels. The API serves them, and the tab holds
no copy of Petasos's settings, roles, levels or rules.

Honesty, in substance:

- The status says protection is on and, separately, what is running and
  what is not, from `coverage`. Only the basic checks running reads as
  that, not as complete coverage.
- A trial is headed as the trial and sits beside the live result.
- Match strength is labelled and says it is not the chance of an attack.
- An attempt to change the guardrails says, per event, whether the call
  was blocked or not stopped. The demonstration now includes one that is
  not stopped, because that is how the product behaves today.
- A signature says it covers the entry and cannot show a deletion.
- A save says when it takes effect, and names what waits for a restart
  before and after the person commits.
- Plain text coming in is reported as flagged, not blocked: a tool result
  is never withheld, and the old "tool was not executed" message for text
  was wrong.

Found while running the real-Hermes tests: round 1's script carried the
sample attacks for Try it, and Hermes's plugin guard reads those as an
attack. It gave the plugin directory a `dangerous` verdict, so Hermes
refused to load Petasos and nothing was checked. The samples are now
served by the API from the wheel, and a test keeps attack strings out of
the plugin directory.

Decisions where the reviews pulled apart beyond the rulings:

- Coloured edge bars (design credited the banner; fit counted the repeats
  as a Petasos signature): removed everywhere except a notice that a
  record failed its signature or the settings are broken. Tone is carried
  by the status badge and a small dot.
- Example inputs (conventions: read like commands; fit: lost Hermes's
  button type): replaced by one Hermes select labelled Example, with a
  line saying that choosing one fills the input and runs nothing.
- Custom range and search (usability) against Hermes's plain segmented
  filters (fit): Custom is one more segment, and search is a field like
  the Sessions page's.
- Tool-name fields (usability asked for selectors): left as text with the
  format stated, because the API has no list of the agent's tools to
  offer. A selector would need Hermes's tool registry served first.
- View tabs use Hermes's enclosed segmented tabs in mixed case, as the
  Sessions page does, rather than the upper case of the Logs filters: the
  design review asked for less delicate navigation.

### Round 2 scores

Visual design 7 (from 6), usability 7 (from 6), conventions 7 (unchanged),
fit with Hermes 8 (from 7). Fresh judges, same briefs, the screenshots in a
neutrally named folder so nothing showed it was a second round. Before
judging, one wording fault was fixed at source and the whole set was
re-captured from the merged tree: a check that was switched on but not
installed was described as "installed but cannot be used", with a pip
instruction.

Every problem the round 1 judges numbered was either fixed or credited as a
strength this time. The scores held below the bar on a new set of findings.

What more than one judge found:

- **The paused view contradicts itself** (conventions, usability):
  "without being checked" above a row reading "Running: Basic checks". The
  row shows what is configured, not what is operating.
- **The open event is not marked in the list** (design, conventions,
  usability).
- **A row truncates in the narrow layout** (design, conventions,
  usability).

Visual design, 7. Clean alignment and clear status treatments across many
states. Held back by the light theme's single blue, small text in several
competing type styles, settings metadata carrying as much weight as the
value, severity and outcome badges that are all the same red rectangle, an
uneven metrics strip, date-picker icons invisible in the dark theme, and a
saved confirmation that looks like a warning.

Usability, 7. All ten tasks succeed or mostly succeed; the saved, trial and
live distinction and the bounded signature statement are credited. Held back
by contradictory safety feedback (the paused view; an activity summary that
says "0 blocked" above a blocked row; a settings-change event with no route
to check the current settings) and by how much a casual user still reads:
the two choices sit below the event history; coverage is named by product
(Presidio, PromptGuard, Semgrep) and not by what each adds; Try it leads
with tool names and JSON; the fix for a missing check is a command with no
word on where to run it; raw keys show under Job and Strictness; "Use
Relaxed too" recommends weaker protection without its cost.

Conventions, 7. Staged changes, validation, audit-log filters, focus and
grouped repeats are credited. Held back by the paused contradiction, the
missing selection in the event detail, a failed required check shown in
warning amber, faint input values and borders in the light theme, small
switches without state text, an ambiguous numeric date format, and labels
that name a destination ("Trial settings").

Fit with Hermes, 8. Frame, panels, settings structure, segmented controls
and both themes are credited as Hermes's own. The remaining tells: an
explanatory voice where Hermes is terse; field and filter labels heavier
than Hermes's; a review ritual around saving; settings rows taller and
busier than Config's; status badges in a different lettering from Hermes's;
an enclosing panel around the activity filters; heavier sub-navigation; an
empty state more emphatic than Sessions'; a statistics strip Hermes has no
equivalent for.

### Rulings for round 3

- **The light theme's blue stands** (fit credits it; design marks it down).
  Hierarchy comes from weight, size and Hermes's own muted text treatment
  for secondary content. Entered values use full-strength text.
- **Less prose, both for fit and for the casual user.** One short sentence
  per thing; anything longer sits behind a disclosure. Statements that keep
  someone from believing more than is true stay, shortened.
- **The two choices move into the status panel**, as compact controls, with
  the history below. This answers usability (choices first) and round 1's
  design finding (evidence not crowded out). Raw keys do not show on
  Overview.
- **One badge family.** Outcome keeps a legible badge built like Hermes's.
  Severity becomes a quiet text indicator beside it, not a second coloured
  rectangle.
- **Saving is direct, and the change list is one click away.** Save sits in
  the toolbar as in Hermes's Config; the list of staged changes opens from
  the change count beside it; "Try it first" stays as a quiet action.
- **Try it leads with the plain path**: pick an example, run it, read the
  outcome in a sentence. The input editor, the model-facing message and rule
  identifiers are technical detail, one click away.
- **Hermes's switch stays as it is**, without added state text.

## Round 3

Revised under the rulings above. Seven named defects were fixed, among them
the activity summary that miscounted blocked events (the count now comes
from the same rows it sits above, with a test) and a failed required check
shown in warning amber. The light theme's flat text had a cause: a text
variable the tab used was not defined in that theme, so everything fell
back to one colour. It now uses Hermes's own primary and secondary text
tokens. The API gained an outcome filter, a count of calls blocked by
accumulated risk, and plain words for what each optional check covers.

### Round 3 scores

Visual design 7, usability 7, conventions 7, fit with Hermes 8: unchanged.
Fresh judges, same briefs. Again nearly everything numbered in the previous
round was fixed or credited (the selected event row, the settings review,
validation, the trial beside the live result, the signature statement), and
again the scores held on a new, finer set.

What more than one judge found:

- **The paused view still contradicts itself** (design, usability,
  conventions; the first thing each would change). Round 3 fixed the status
  panel, which now reads "Suspended". The Checks panel lower on the same
  page still says "Basic checks always run" beside a green "Running". This
  was a named defect and it was half fixed.
- **Status badges in condensed lettering** (design, conventions), for the
  third round.
- **The light theme's blue** (design, conventions): ordinary text, links
  and values in closely related blues. Fit credits it again, in so many
  words: "faithful to Hermes, even where that host convention is visually
  aggressive".
- **Switches without state text** (design, usability).
- **The floating change review** (design: weak separation in the dark
  theme; fit: Hermes has no floating surface).

Visual design, 7. Orderly alignment, the selected row, the Try it match
highlight and the invalid field are credited. Held back by the light theme,
badge and small-label lettering, a statistics strip whose counts are
smaller than their labels and lose their baseline when labels wrap, an
uneven wrap of rule actions in the trial column, and an unbalanced Try it
layout.

Usability, 7. All ten tasks succeed or mostly succeed. Held back by the
paused contradiction and by three statements that leave someone unsure of
their protection: the choice that requires a check reads "report a problem
if it is missing" when the effect is that tool calls are held; "Protection
on" sits in a frame whose sidebar reads "Gateway Status: Off"; a settings
change that was not stopped still has no route to the current settings.
Also: tool and product names where a casual user reads; vague option
descriptions ("runs as standard", "steps in"); no handoff from an event to
a test of its rule; no route from a risk-score block to the events that
caused it; an empty state that says "every record is written"; "blocked for
good" with no word on how work resumes.

Conventions, 7. Staged changes, validation, list-to-detail behaviour, the
trial and live split and focus are credited. Held back by the paused
contradiction, badge lettering, the light theme, state-changing actions
drawn as links, list timestamps without year or timezone, and a mapping
setting edited as raw JSON.

Fit with Hermes, 8. Frame, panels, settings foundations, the empty state
and both themes are credited. Remaining tells: the explanatory voice;
settings rows taller and more annotated than Config's; the floating review;
severity drawn as signal bars; activity rows that read as cards; button
case that does not follow Config's; a status panel composed unlike
Hermes's.

### What three rounds show

The first round bought a point on three criteria; the second and third
bought none on three of four. Each round's named problems are fixed, and
fresh judges find a finer set, so a flat score is not a flat interface:
what holds a 7 in round 3 (an action drawn as a link) is smaller than what
held a 7 in round 1 (a status that claimed more protection than there
was). The scale's step from 7 to 8 is "only minor issues remain", and two
things have kept three judges from taking it. One is a defect that has
survived two rounds, the paused contradiction. The other is a ruling: the
light theme and the condensed badge are Hermes's own, and judges who do not
score fit count them against the tab.

The loop has also been the best source of honesty defects in the product:
overstated coverage, a wrong "tool was not executed" message, the miscount,
and the plugin's own admission failure were all found by it.

### Rulings for round 4

- **The light theme's blue stands**, a third time. It is Hermes's theme,
  and the tab is a page in it. Within it: every state-changing action is a
  button, so that underlined text only ever navigates; nothing else is
  underlined.
- **Operational badges leave the condensed face.** Outcome and check-state
  badges keep Hermes's badge container and take the body face at the size
  of the text around them. The condensed face stays where Hermes uses it,
  on counts. This reverses round 1's "within Hermes's kit first": three
  rounds of the same finding from two criteria outweigh a credit from one.
- **Severity is a word**, set beside the outcome, with Critical heavier
  than High. No bars, no second rectangle.
- **State text without touching the switch.** Each setting gets one
  secondary line that carries its state and its source ("On · Default"),
  which also answers fit's request for a single annotation line.
- **The change list is inline**, a panel under the toolbar, not a floating
  surface.
- **One rule for button case**: filled and outlined form buttons follow
  Config's upper case; quiet utilities stay as they are.
- **A consequence is computed, not written.** Any sentence that says what
  happens to tool calls (a required check that cannot run, a failed check)
  is derived from the resolved fail mode, so it is true under each.
- **Stopping rule.** If round 4 moves no score, the loop stops and the
  remaining conflict between fidelity and the design score goes to the
  owner as a choice.

## Round 4

Revised under the round 4 rulings. Every view now draws a check's state
from one `operating` value the API serves, so a paused status cannot show
a running check; two tests fail if it does. The option that requires a
check reads "Required", and Settings says before Save what that does to
tool calls, computed from the fail mode and the dangerous-action setting;
`tests/hermes/test_consequence_is_true.py` runs the enforcer in that state
under each combination and holds the sentence to what it does. The status
panel says what "on" covers (every agent Hermes starts from this profile,
except in safe mode) and makes no claim about Hermes's gateway, whose
sidebar status only reports whether a gateway process is alive. Every
action is a button; operational badges use the body face; severity is a
word; the change list is inline; a mapping is edited as rows, from a new
`entry_labels` declaration in the schema.

### Round 4 scores

Visual design 7, usability 7, conventions 7, fit with Hermes 8: unchanged
for the second round running. The paused contradiction, badge lettering,
floating review, link-styled actions, timestamps and the JSON mapping are
gone from every list.

What the judges found this time:

- **Hermes's own look** (design, conventions): the light theme's blue
  again, first on the design list, with the remark that "inheriting
  Hermes's visual treatment does not remove those weaknesses"; Hermes's
  serif labels, full-width fields, small switches and quiet text actions.
- **The reverse, from fit**: the operational badges should go back to
  Hermes's condensed lettering, which two criteria marked down for three
  rounds; outcome words should be terser ("Approval requested", not
  "Asked a person"), which usability marks down.
- **Saved against in effect** (usability, conventions; first for
  conventions): after a check is saved as Required, "waits for a Hermes
  restart" sits above a present-tense statement about tool calls.
- **A description read as a state** (usability, first): the General job
  reads "Every rule is on, and a risky tool call is blocked" while
  protection is paused. Round 4 introduced this wording.
- **Two commit buttons in the job preview** (usability, conventions):
  "Apply" beside "Apply Research with Relaxed" while Balanced is selected.
- **Figures that do not reconcile** (conventions): "18 events" above five
  numbers that sum to 16, one of them a finding and not an outcome.
- Smaller: a dash for a severity that does not apply; "Signed · 18
  checked" without its limit; "Show changed settings" implying the event's
  change is known; no direct route from a skipped check to its setting; a
  trial result narrower than the live one.

### The loop stops here

The stopping rule set before this round was: no score moves, the loop
stops. None did.

What four rounds show about the method:

- **As a defect finder it earned its cost.** Each round's judges found
  things that were wrong and that tests did not: overstated coverage, a
  miscount, a status contradiction, a consequence that was false under one
  setting, the plugin's own admission failure. Usability, the criterion
  told to weigh anything misleading about protection most heavily, was the
  most productive.
- **As a gauge it stopped registering after round 2.** Three criteria
  returned 7 in rounds 2, 3 and 4 with almost wholly different problem
  lists each time. A fresh judge asked for every problem it can
  substantiate finds some, and "notable weaknesses" then describes any
  interface. An absolute score from a new judge each round cannot show
  improvement between rounds; a judge shown two rounds side by side
  could.
- **The criteria now pull directly against each other.** What design and
  conventions mark down first is what fit credits, and round 4's fit
  judge asked for the reversal of round 4's badge ruling. With Hermes's
  theme fixed by ruling, 8 on visual design is probably not reachable by
  revising the tab.

The round 4 defects that are faults and not taste are being fixed in an
ordinary lane, outside the loop. The rulings stand as the tab's design
record.

### Owner's decision, 2026-11-10

Stop here, keep Hermes's look, fix what the judges found. A later loop
should grade from a firmer rubric. What this one suggests that rubric
needs:

- **Items, not an impression.** A fixed list of checks per criterion, each
  passed or failed with the screenshot that shows it, and the score derived
  from the list. Two judges then differ on named items, and a round's gain
  is the items that changed.
- **The host's constraints stated as given.** The theme's palette,
  typefaces and stock controls belong to Hermes. A judge scores how well the
  tab uses them, and reports a complaint about the host separately.
- **A side-by-side for improvement.** One judge sees the previous round and
  the current one, unlabelled and in random order, and says which is better
  on each item. Absolute scores from fresh judges did not register change.
- **Precedence between criteria written down first**: honesty about
  protection, then the casual user's understanding, then fit with Hermes,
  then general convention and polish. The rulings above arrived at this
  order one conflict at a time.
- **Honesty as its own criterion.** The most valuable findings were
  statements that let someone believe more than was true. They were found
  under usability; they deserve a judge whose only question is whether each
  sentence on screen is true in the state shown.
