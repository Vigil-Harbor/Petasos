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
| 2 | pending | pending | pending | pending |

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
