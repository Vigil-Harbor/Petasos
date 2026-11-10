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
  Hermes's two themes, and one narrow layout. Screenshots and references live
  in `.ux-reference/`, which is not committed.
- Bar: 8 on every criterion.

## Scores

| Round | Visual design | Usability | Conventions | Fit with Hermes |
|---|---|---|---|---|
| 1 | 6 | 6 | 7 | 7 |
| 2 | 7 | 7 | 7 | 8 |

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
