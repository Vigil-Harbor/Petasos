# Hermes native fit

Checked against upstream Hermes Agent tag `v0.23.1`, commit
`3b421578588243f920886e6fe79a6faa87ea026e`. This is what "native" means for a
plugin like Petasos, and where today's Petasos duplicates or cuts across
Hermes. It is written for the person designing the user-facing surface and
deciding what Petasos should stop doing itself.

`docs/architecture/redesign.md` was not edited. Loader, settings, and hook
facts already recorded in `docs/architecture/hermes-host-facts.md` are used,
not re-run. New runs are marked **Ran**. Everything else is **Read** from
the tag, and the text says when the documentation and the source disagree.

Sandbox: `/tmp/petasos-h1-native-fit`. `HOME` is `<sandbox>/home`.
`HERMES_HOME` is `<sandbox>/hermes_home`. Every Hermes command went through
`<sandbox>/bin/with-sandbox`. Screenshots are outside the repository, in
`/tmp/petasos-h1-screenshots/` (see `INDEX.md` there). The dashboard process
was stopped. Nothing under a live Hermes home was opened.

## Conclusions

### What native requires

Do:

- Ship one directory plugin: `plugin.yaml` with `provides_hooks` and a
  `config_schema`, plus a one-line `__init__.py`. That is the shape Hermes
  documents and the shape the host-facts run already loaded.
- Put the two-choice setup (`enabled`, `role`, `level`) and the overrides
  JSON in that `config_schema`, so Hermes Desktop draws the form and
  `hermes config` / `ctx.get_config` are the same store. Defaults in the
  schema are what the form displays. Policy defaults stay in Petasos.
- Draw any dashboard tab with `window.__HERMES_PLUGIN_SDK__`: its React,
  its Card/Button/Badge, `fetchJSON`, and the `--color-*` tokens. Draw any
  Desktop page with `@hermes/plugin-sdk` and `var(--ui-*)`. One family of
  components per surface. Hermes does not share one kit across them.
- Let Hermes ask the human. An approve directive is a request into Hermes's
  approval gate, not a second dialog. Let Hermes redact. Call
  `agent.redact.redact_sensitive_text` (already what the reference plugin
  imports) and, when a pattern must be added, `ctx.register_redaction_patterns`.
- Let Hermes decide whether a terminal command is dangerous, whether a URL
  is private, and whether a file write is denied. Petasos scans what those
  gates do not see: tool arguments that are not a shell command, tool
  results, session risk, and egress of tainted content.
- Put health that is about the install on `hermes petasos doctor`
  (`ctx.register_cli_command`). Hermes `doctor` has no plugin row to join.
- Treat a block without a message as a bug. Hermes ignores it. Keep Petasos
  deadlines under `plugins.hook_callback_timeout`.

Do not:

- Do not run a second local web server, a second token, or a second visual
  language (the Arcade face, the private dark shell) as the way a Hermes
  user meets Petasos.
- Do not write `config.yaml` yourself, and do not keep a top-level `petasos:`
  section. Settings live at `plugins.entries.petasos.settings`.
- Do not install with `pip` into `~/.hermes/hermes-agent/venv`. That tree is
  not the one Hermes generations run. The documented route is `hermes plugins
  install` of an index requirement.
- Do not put plugin tabs in the main sidebar. At this tag they render in a
  separate Plugins group under Documentation. `tab.position: after:skills`
  only orders that group.
- Do not assume a `transform_tool_result` string is shown. The first string
  in registration order wins, and the bundled `security-guidance` plugin
  sorts before `petasos`.
- Do not re-prompt, or silently allow, a command Hermes has already decided.
  A second allow-list next to `command_allowlist` will confuse the user who
  pressed Always.
- Do not add a plugin password. The machine-managed config
  (`/etc/hermes/config.yaml`, or `HERMES_MANAGED_DIR`) already pins exact
  keys so the agent cannot change them.

### Where each user-facing piece lives

| Piece | Home | Mechanism | Not possible today |
|---|---|---|---|
| Two-choice setup (`enabled`, `role`, `level`) | Hermes Desktop, Settings → Plugins, for the profile the user is looking at | `config_schema` on `plugin.yaml`. `bool` is a switch, `str` plus `choices` is a dropdown. No Desktop code. | The web dashboard does not render `config_schema` at all. There is no `hermes setup` step a plugin can join. |
| Full settings (`overrides` and the rest) | Same Desktop form, the `overrides` key as a JSON field (`type: dict`) | Same writer as `ctx.set_config` (`save_plugin_setting`) | A nested form. The schema is flat. A richer editor is a Desktop `registerSettingsPage` sub-page or a dashboard tab, fed by `describe()`, and it must write through that same writer. |
| Scanner playground | A Petasos dashboard tab, and optionally a Desktop page | Dashboard: `dashboard/manifest.json` plus an IIFE that calls `SDK.fetchJSON('/api/plugins/petasos/...')`. Desktop: `desktop/plugin.js` and `ctx.rest` to the same namespace. | No built-in playground, slot, or CLI pane. The tab will sit in the dashboard's Plugins group, not in the main rail. |
| Activity log ("what was blocked and why") | That same Petasos tab. A one-line count can also sit on the Desktop status bar (`statusBar.right`). | Plugin API reads the event spool and returns rows. The dashboard Logs page is `agent.log` and is the wrong pile. | No shared security-event log, no plugin hook on `hermes doctor`, no slot aimed at a decision list. `logs:top` only pins a widget onto the agent log. |
| Health and diagnostics | `hermes petasos doctor` for the install, the System page's footer for "is the gateway up", and a short status line on the Petasos tab for scanner state | `ctx.register_cli_command`. Scanner state is Petasos's. | `hermes doctor`'s check list is fixed in `hermes_cli/doctor.py`. A plugin cannot add a row. |

Enablement is still `hermes plugins enable petasos` or the Plugins page.
`plugins.enabled` is Hermes's switch. `settings.enabled` is Petasos's arm
switch. Both have to be on, and the doctor command should say which one is
off.

### Overlap

| Petasos capability | Hermes at this tag | Recommendation |
|---|---|---|
| Syntactic injection rules | Partial. `tools/threat_patterns.py` scans context files, memory, and some tool results for "ignore previous instructions", hidden HTML, and role hijacks. A hit blocks `AGENTS.md` / `.cursorrules` from the prompt and warns on the user's own `SOUL.md`. | Keep. Different surface: tool arguments and inbound content, not the prompt files. Do not scan a file Hermes already refused to load and report it as a new block. |
| Command rules (pipe-to-shell, decode-exec, fetch-exec, destructive verbs) | Equivalent for the `terminal` tool. `tools/approval_detection.py` `DANGEROUS_PATTERNS` plus a hardline blocklist, `approvals.deny`, and the approval gate. Container backends skip the pattern list because the container is the boundary. | Defer when the tool is `terminal` or `execute_code`. Keep only for command-shaped text that never reaches those tools. |
| Encoding rules (invisible characters, base64, homoglyphs, RTL) | Partial. Invisible and bidi characters in a shell command are a dangerous-pattern hit. Homoglyphs and base64-in-prose are not. | Defer the shell-command case. Keep the content scan. |
| Structural rules (size, depth, binary) | Nothing. | Keep. |
| PromptGuard | Nothing. Tirith left the core; the catalog plugin runs a local binary on terminal commands only. | Keep. |
| Presidio PII detection and anonymization | Narrow partial. `privacy.redact_pii` (default off) hashes user ids and strips phone numbers from the session context prompt. Secret redaction is a different pass. | Keep. Do not treat `privacy.redact_pii` as a substitute. |
| Semgrep | Partial and weak. Bundled `security-guidance` appends a warning to `write_file` / `patch` / `skill_manage` for 25 dangerous-code patterns. It does not block unless `SECURITY_GUIDANCE_BLOCK=1`. | Keep Semgrep. Do not copy those 25 patterns. If both plugins are enabled, see the transform note below. |
| Tool-call guard (classification, exemptions, aliases) | Partial. Hermes gates `terminal`, file writes, `execute_code` scripts, and skill/memory writes. It does not classify the rest of the tool list as acting or ingesting. | Keep the classification. Defer the terminal and file-write decisions to Hermes. |
| Session score and three tiers | Nothing. Delegation has iteration and concurrency caps, not a risk score. | Keep. |
| Sub-agent lineage and fan-out budget | Partial. `delegation.max_spawn_depth` (default 1), `max_concurrent_children` (default 10), `oneshot_max_children` (default 2), `subagent_auto_approve` (default false, auto-deny). | Keep lineage and the score-tied budget. Do not add a second depth cap. Read Hermes's depth and the auto-approve flag in `doctor` so the user sees one story. |
| Egress fence and source taint | Partial around the edges only: `security.website_blocklist`, SSRF in `tools/url_safety.py`, credential-upload patterns on curl/wget, and the Docker egress proxy. No memory of "this span came from a tool result". | Keep taint. Defer URL policy and sandbox credential isolation. |
| Tool-result annotation | Partial. `security-guidance` annotates writes. Hermes does not annotate reads or web pages. | Keep for ingested content. A string return can be dropped: first `transform_tool_result` string wins (`model_tools.py` lines 873–887), and plugins with no dependency edge load alphabetically (`plugins_manifest.py` lines 280–283). `security-guidance` is before `petasos`. |
| Approval observation | Hermes owns the prompt, the choices (once / session / always), the timeout, and `command_allowlist`. Hooks `pre_approval_request` and `post_approval_response` are observers. They do not run when nobody is attached. | Keep the record. Do not draw a second approval UI. Do not honour a standing "always" for a guardrail change; Hermes will store one if the user presses Always, and Petasos has to make that key unable to match another session. |
| Audit events and alerting | `agent.log` in the dashboard Logs page, `hermes doctor`, supply-chain advisories, approval history (`hermes approvals suggest`). No decision spool. | Keep the spool and the Petasos tab. Do not copy events into `agent.log` as the user-facing log. |
| Self-modification detection | Partial. File tools hard-deny credentials and some Hermes state, and approval-gate `config.yaml` rather than deny it (`agent/file_safety.py` lines 243–250). Nothing stops `hermes plugins disable`, safe mode, or a hook-timeout edit. | Keep, aimed at the switches in host-facts section 7. For `never`, pin the keys in the managed config instead of a Petasos password. |
| Credential redaction in what it displays | Equivalent. `agent.redact.redact_sensitive_text` is on the public plugin API. `ctx.register_redaction_patterns` adds patterns and cannot weaken the built-ins. `security.redact_secrets` (default true) governs it. | Defer. Keep only the withheld notice for when the host redactor is missing. |

### Interfaces to depend on

Stable, in the plugin contract or the public import list
(`website/docs/developer-guide/plugins/public-api.md`, generated from
`hermes_cli/data/plugin_api.json`):

- `plugin.yaml` and `register(ctx)`. There is no single `PLUGIN_API_VERSION`.
  Documented `PluginContext` methods are not removed or renamed; new hook
  fields arrive as keywords. `manifest_version` is the file format (absent
  means 1, current max 2). `api_version` is a separate generation number the
  manifest may declare. Both are in the plugin guide, lines 607–618.
- `ctx.get_config` / `ctx.set_config`, `ctx.register_hook`,
  `ctx.register_tool`, `ctx.register_command`, `ctx.register_cli_command`,
  `ctx.register_redaction_patterns` (the method exists on `PluginContext` at
  `hermes_cli/plugins_context.py` lines 684–696; the plugin guide does not
  mention it, so call it but do not build a feature that has no other path).
- `agent.redact.redact_sensitive_text` only. The rest of `agent.redact` is
  not on the list.
- `hermes_constants.get_hermes_home` and `hermes_cli.config` as a module
  (the env-file reader the redesign already uses).
- Dashboard manifest keys in `website/docs/user-guide/features/extending-the-dashboard.md`:
  `tab`, `slots`, `entry`, `css`, `api`. Routes mount at `/api/plugins/<name>/`.
- Desktop `HermesPlugin` and the contribution areas in
  `website/docs/developer-guide/desktop-plugin-sdk.md`. The guide says the
  three plugin systems do not share code. Only the `/api/plugins/<id>`
  namespace is shared.

Internal, and the place for one isolating seam:

- `tools.approval`, `tools.approval_detection`, `agent.file_safety`,
  `tools.threat_patterns`, `tools.skills_guard`. Read their results through
  the approval hooks and the public redactor. Do not import the pattern
  tables. `hermes plugins validate` warns on private imports
  (`hermes_cli/plugin_validate_private_imports.py` names `tools.tirith_security`
  as the example of a removed module).
- `hermes_cli.kanban_db` and the rest of the kanban split. The bundled
  kanban API imports them (`plugins/kanban/dashboard/plugin_api.py` lines
  31–39). A third-party plugin that does the same will break when those
  modules move. They moved once already: the plugin guide, lines 303–313,
  says the September 2026 split deleted the old import paths.
- Dashboard plugin discovery and mount
  (`hermes_cli/web_server_dashboard.py`). The SDK file
  `web/src/plugins/sdk.d.ts` lines 1–36 calls itself a spike. Depend on the
  documented globals (`__HERMES_PLUGIN_SDK__`, `__HERMES_PLUGINS__`), not on
  React component prop types.
- `hermes doctor`'s check list. Fixed tuples in `hermes_cli/doctor.py` lines
  114–133.
- The clone is depth-1, so this pass has no file history beyond the tag
  commit. The churn evidence is the guide's own removal notice and the
  private-import warning, not a git log.

The seam is the Hermes adapter in the redesign: it translates hooks and
`HostInfo`, and it is the only module allowed to import a Hermes name that
is not on the public list. When a name leaves the list, one file changes.

### What in today's console and install flow should go

- The supervised process on `127.0.0.1:8384`, its own bearer token, and the
  instruction to keep it alive across Hermes updates. The dashboard plugin
  API is the durable mount. At this tag a user plugin's `plugin_api.py`
  mounts when the plugin is in `plugins.enabled` (`web_server_dashboard.py`
  lines 846–859 and 1179–1239). `docs/deployment/hermes-desktop.md` says the
  in-tab backend mounts only for a bundled copy. That was true of an older
  host. It is not true here.
- The Arcade font, the private dark palette, and the four-pane shell
  (Observability, Scan Playground, Config Editor, About) as the Hermes
  face. Those pages can remain the contents of one plugin tab, restyled
  with the SDK.
- Hand-written `plugin.yaml` using `hooks:` and a top-level `petasos:`
  block in `config.yaml`. `hooks:` loads and fails `hermes plugins validate`.
  The profile's `plugins.entries.petasos.settings` is the store.
- `pip install` into `~/.hermes/hermes-agent/venv`, and the copy that has
  to be re-dropped after every Hermes update. Publish the wheel on an index
  and install with `hermes plugins install`.
- `verify.py` as a second doctor. One command, `petasos doctor`, using
  Hermes's own discovery to say enabled, loaded, or not.
- Two writers. The console's `PUT /api/config` against the raw file fights
  the Desktop form. The tab should call the plugin API, and the API should
  call `save_plugin_setting`.

## Evidence

### A. What a native plugin looks like

#### 1. Kanban, the model of "always been there"

Kanban is not one plugin. It is core code plus two UI packages that happen
to use the plugin doors.

**Read.** The board, the dispatcher, the CLI, and the `kanban_*` tools live
in `hermes_cli/kanban_db.py` and its siblings. `website/docs/user-guide/features/kanban.md`
lines 29–36: the model uses tools, the human uses `hermes kanban`, `/kanban`,
or the dashboard, and both go through `kanban_db`. The CLI is registered as
a built-in surface in `hermes_cli/console_engine.py` line 314. The slash
command is documented at kanban.md line 1072. Gateway notifications are a
config block under `kanban:` (`hermes_cli/config_defaults.py` lines 1862–1875),
on by default.

The web board is a bundled dashboard plugin. `plugins/kanban/dashboard/manifest.json`
lines 1–14 name the tab `/kanban`, position `after:skills`, icon `Package`,
entry `dist/index.js`, and `api: plugin_api.py`. kanban.md lines 767–776
tell the user to run `hermes kanban init` and `hermes dashboard`, and say
the tab is not a core feature and not a separate service. There is no
`plugin.yaml` in `plugins/kanban/`, so the agent loader has nothing to
enable. The dashboard finds the manifest on its own.

The Desktop board is a bundled SDK plugin at
`apps/desktop/src/plugins/kanban/plugin.tsx` lines 1–9. It contributes a
page, a sidebar row, and a status-bar count, and it calls the same
`/api/plugins/kanban` router through `ctx.rest`. It ships off by default:
Capabilities → Plugins, until the user flips it. That is a second switch
the web tab does not have.

**Ran.** The sandboxed dashboard, with no `plugins.enabled` entry, served
`/kanban`. The page showed an empty board: Triage, Todo, Scheduled, Ready,
an Orchestration: Auto pill, and "— no tasks —" in each column
(`teal-kanban.png`). The live sidebar text put KANBAN and ACHIEVEMENTS
under a Plugins heading after Documentation, not after Skills. The agent
log line was `Mounted plugin API routes: /api/plugins/kanban/`.

What a third-party directory plugin can use:

- Dashboard tab, slots, CSS, and (when enabled) a FastAPI router.
- Desktop panes, pages, sidebar rows, status bar, settings pages, themes,
  palette commands. Drop `desktop/plugin.js` in the plugin directory or
  `$HERMES_HOME/desktop-plugins/<id>/plugin.js`.
- Tools, hooks, slash commands (`/name` in CLI and gateway), and
  `hermes <name>` subcommands.

What it cannot use, because those are core or bundled-only doors:

- A `kanban_*`-style toolset that is on without `plugins.enabled`.
- A slash command implemented in the CLI rather than `ctx.register_command`.
- A TUI panel. Slash commands reach the TUI because the TUI talks to the
  gateway. There is no TUI component SDK in the plugin guide.
- A row inside `hermes doctor`.
- The Desktop kanban card-badge area is a real contribution
  (`KANBAN_CARD_AREAS.badges`, named in kanban.md line 929), so a plugin
  can decorate cards. It cannot replace the board's data model.

#### 2. What a directory plugin can add to the dashboard and to Desktop

Dashboard, **read** from `website/docs/user-guide/features/extending-the-dashboard.md`
and the source.

| Contribution | Mechanism | What the plugin is given |
|---|---|---|
| Tab | `dashboard/manifest.json` `tab.path`, `tab.position`, `tab.hidden`, `tab.override`. JS calls `window.__HERMES_PLUGINS__.register(name, Component)`. | `SDK.React` and `SDK.hooks`. Do not bundle React. |
| Slot on an existing page or the shell | `registerSlot(plugin, slot, Component)`. Manifest `slots` is documentation only. Names are in `web/src/plugins/slots.ts` lines 18–94: header, footer, sidebar, and `<page>:top` / `<page>:bottom` for sessions, analytics, logs, cron, skills, plugins, config, env, docs, chat. | The same SDK. The shell renders only the known names. |
| Backend routes | Manifest `api` points at a file inside `dashboard/` that exports `router`. Mounted at `/api/plugins/<name>/`. | FastAPI. Auth is the dashboard's session token. Importing Hermes from the route is possible and is how kanban is written; it is not a stable promise. |
| CSS | Manifest `css`. | Prefer `var(--color-*)`, `--radius`, `--font-mono`. The guide, lines 799–814, lists those tokens. |
| Status | No status API. A slot or the tab itself. | — |
| Notifications | No dashboard toast contract beyond `SDK.hooks.useToast` (`sdk.d.ts` lines 109–117). | A toast component the plugin mounts itself. |
| Commands | None on this surface. Commands are the Python plugin. | — |

Discovery order is user, then bundled, then project
(`web_server_dashboard.py` lines 529–569). User wins on a name clash.
Project plugins may ship JS. Their Python `api` is never imported (lines
1200–1207). User Python runs only when the name is in `plugins.enabled`
and not in `plugins.disabled` (lines 846–859). Bundled Python runs unless
the name is disabled.

**Read, and it disagrees with an older Petasos note.** Mounting does not
require the plugin to be bundled. **Read, and the kanban page disagrees
with the extending-the-dashboard page.** kanban.md lines 913–919 say the
auth middleware skips `/api/plugins/`. `hermes_cli/dashboard_auth/public_paths.py`
lines 9–27 list the public paths. `/api/plugins/` is not among them.
`web_server.py` lines 458–477 require the session token on every other
`/api/` path. The extending-the-dashboard page (lines 750–751) matches the
source. On loopback the token is injected into the page, which is why the
screenshots loaded. A plugin that calls `fetch` itself instead of
`SDK.fetchJSON` will 401.

The sidebar split is source, not the guide. `partitionSidebarNav` in
`web/src/App.tsx` lines 293–307 pulls plugin paths back out of the merged
list. Lines 673–691 render them under `t.app.pluginNavSection`. The guide's
"after Skills" sentence describes `buildNavItems` (lines 274–284) before
that split. What the user sees is the Plugins group. **Ran**, sidebar text
quoted above.

Desktop, **read** from `website/docs/developer-guide/desktop-plugin-sdk.md`.

The guide's first warning (lines 22–32) is the useful one: web dashboard
plugins, Desktop plugins, and Python plugins are three systems. They share
the backend namespace and nothing else.

A Desktop plugin default-exports a `HermesPlugin` and registers
contributions. The areas in lines 239–250 cover panes, full pages, sidebar
nav, status bar, title bar, command palette, keybinds, themes, and composer
slots. Settings are `ctx.registerSettingsPage` (lines 994–1033), and a
`config_schema` renders with no JS. The UI kit (lines 2097–2122) is the
app's own Button, Input, Switch, Dialog, EmptyState, StatusDot, LogView,
and Codicon. Colors are `var(--ui-text-secondary)`, `--ui-stroke-secondary`,
`--ui-accent`. Hardcoded colors are called out as wrong.

`defaultEnabled: false` inventories the plugin off. Kanban's Desktop half
uses that. A security plugin should too, unless the product decision is
that installing it is the consent.

#### 3. UI conventions, from the source and from the running dashboard

**Ran** at 1440×900, Hermes Teal and Nous Blue. The built-in theme list is
`hermes_cli/web_server_dashboard.py` lines 306–315: Teal, Teal Large,
Nous Blue (the light one: cream `#E8F2FD` and blue `#0053FD`,
`web/src/themes/presets.ts` lines 202–223), Midnight, Ember, Mono,
Cyberpunk, Rosé. The config schema's `dashboard.theme` dropdown
(`web_server_config.py` lines 139–141) omits Nous Blue and Teal Large.
The switcher in the running page does not. It offered Nous Blue and
applied it. The footer then read NOUS BLUE.

Layout. A left rail, about a fifth of the width, lists the product in
tracked small caps: Chat, Sessions, Files, Models, Logs, Cron, Skills,
Plugins, MCP, Channels, Webhooks, Pairing, Profiles, Config, Keys,
System, Documentation. Plugin tabs sit in a second group under a
Plugins label, below a hairline. The content column has a title, then
one toolbar, then the body. There is no top tab bar.

The rail footer is the status block: System, Gateway Status, Active
Sessions, Restart Gateway, Update Hermes, the theme name, the language.
On this run the gateway was Off and sessions were 0, in the same quiet
type as the nav. That is how Hermes shows health: one word, no chart.

Typography. System UI sans for body, a display face for the wordmark and
section labels, mono for keys, counts, and log lines. Section titles on
the Plugins page are wide-tracked caps (RUNTIME PROVIDER PLUGINS). Body
copy is one short sentence under the title.

Colour. Teal is near-black green with a warm off-white accent. Nous Blue
is a light blue field with a saturated blue for the selected control.
Status uses a small pill: green `active` and `latest`, grey
`not logged in`. Destructive actions stay buttons, not red text, until
a confirm dialog. The config page imports `ConfirmDialog` from
`@nous-research/ui` (`ConfigPage.tsx` line 48) for reset.

Settings. The Config page is a section list with a count, a search box,
the path of `config.yaml`, and YAML / Save. Each field is a human label,
the dotted key in faint type, a one-line description, and a control.
Security → Approvals → Mode is the label "Dangerous command approval
mode", the key `approvals.mode`, a dropdown sitting on `smart`. Timeout
is a number. Cron mode, single-query mode, and unattended mode are
text fields showing `deny`. That is the pattern a Petasos form should
copy: one decision, the key visible, the sentence plain.

Empty states. Sessions: a clock, "No sessions yet", "Start a conversation
to see it here". Kanban: "— no tasks —" inside a dashed box, and a
sentence on the column ("Raw ideas — a specifier will flesh out the spec").
No illustration, no apology.

Wording. Short, second person, names the next action. The telemetry bar
at the top says what is shared and what is not, then Share with Nous and
No thanks. Errors in the log are the logger name plus one sentence, not
a stack in the page.

A plugin tab that brings its own font and its own dark shell will look
like a different application inside this rail. The kanban board does not.
It uses the page title, the same buttons, and the same empty sentence.

#### 4. Onboarding

**Read.** `website/docs/getting-started/quickstart.md` lines 100–109.
`hermes setup` on a fresh install offers Quick Setup (Nous Portal), Full
Setup, and Blank Slate. Blank Slate turns plugins off along with
everything else. None of the three modes is a hook a plugin can register.

The shortest path Hermes offers a third-party plugin, from the plugins
page lines 209–222 and 424–440:

1. `hermes plugins install <catalog name>` or a git URL. The enable
   question defaults to no.
2. `hermes plugins enable <name>`, or the Plugins page switch.
3. The `config_schema` defaults are what the Desktop form shows before
   the user types anything. `ctx.get_config` still returns the caller's
   default until a value is saved (host-facts section 3). Sensible
   behaviour has to be the code default, not a saved document.

There is no first-run card, no plugin wizard API, and no doctor
registration. `hermes plugins` is the interactive list. `hermes doctor`
(`doctor.py` lines 176–199) prints a fixed sequence: advisories, MCP,
Python, config, auth, gateway supervision, tools, skills, memory,
plugins that an update disabled, plugins on both lists. A plugin-specific
check is a subcommand the plugin registers.

Petasos rides that path by being installable as a catalog or git plugin,
enabled with one command, and correct at the schema defaults (`general` /
`balanced`, or whatever the redesign ships). The role suggestion must
stay a recommendation, as redesign section 4.2 already says, because
Hermes will not apply it. A plugin that needs a model download
(PromptGuard) has to say so in `doctor` output and degrade until then.
Hermes will not prompt for a Hugging Face token on the plugin's behalf.

**Ran.** The Plugins page in the sandbox showed the memory provider and
the context engine at the top, then Install from GitHub, then the
catalog. It did not show a per-plugin settings form. That matches the
web source: `web/src` has no `config_schema` renderer. The form is
Desktop-only, and this pass did not start Desktop.

#### 5. Health and activity

**Ran.** The System page showed host facts, Hermes `v0.23.1` with a
`latest` pill, Nous Portal "not logged in", and the skill curator
"active · every 168h · never run". The rail footer showed Gateway Status:
Off. The Logs page was `agent.log` with filters for file, level, and
component. The lines were plugin registration, then
`Mounted plugin API routes: /api/plugins/kanban/`, then a warning that
`state.db` is not initialized because this profile's gateway was not
started. That warning is expected. No gateway was started.

Kanban's own health is the board: column counts, the orchestration pill,
and the dispatcher nudge. It does not post into System or Logs as a
status object. A failure of a worker shows up as a card state and, if
the gateway is running, as a notification. Those notifications are
kanban core, not a plugin facility.

There is no shared plugin event log. A "what did I block and why" view
cannot live inside Logs without pretending agent log lines are decisions.
It can sit beside Logs as its own tab, with a slot on `logs:top` only as
a pointer ("3 blocks this session" linking to the tab).

### B. Overlap

#### 6. Hermes security features at this tag

All of these are **read** unless marked **ran**.

Approvals. `hermes_cli/config_defaults.py` lines 1637–1682. `approvals.mode`
is `manual`, `smart` (default), or `off`. `smart` asks an auxiliary model
and escalates the uncertain cases. `cron_mode`, `single_query_mode`, and
`unattended_mode` default to `deny`. Timeout defaults to 300 seconds and
fails closed. `approvals.deny` is a list of fnmatch globs that block even
under yolo. `command_allowlist` is the permanent list, filled by the
Always choice. A plugin approve uses the key `plugin_rule:<rule_key>`
(host-facts section 5, which was run). `security.approval.transport`
defaults to `builtin` (config_defaults.py lines 1758–1762). A plugin
transport only presents the prompt. It does not decide.

Hardline blocklist. `website/docs/user-guide/security.md` lines 141–163.
`rm -rf /`, fork bombs, `mkfs` on the live disk, `dd` onto a disk, and a
pipe of an untrusted URL to a shell at the root. Yolo does not pass
these. The same page's "what triggers approval" table (lines 207–244) is
a short subset. The source list in `tools/approval_detection.py` lines
416–695 is much longer: Windows deletion, PowerShell encoded commands,
cloud metadata IPs, decode-and-execute, credential upload by curl, git
force push, package uninstall, docker daemon redirect, Hermes
self-termination. The documentation is behind the source. Depend on the
module's behaviour, and do not copy either list into Petasos.

Dangerous-command detection used to call out to tirith. The catalog file
`plugin-catalog/tirith.yaml` lines 29–30 say Hermes 0.21.6 and later do
not have the built-in check. Content rules that used to be tirith findings
are now `_CONTENT_RULE_DESCRIPTIONS` in `approval_detection.py` lines
721–728 (credential upload, invisible Unicode). **Read.**

Secret redaction. `agent/redact.py` lines 1–7 and 1491. Regex plus an
exact vault-value registry. `security.redact_secrets` defaults true
(config_defaults.py line 1754). Plugins add patterns. They cannot remove
built-ins (`plugins_context.py` lines 684–688).

File and terminal sandboxing. `agent/file_safety.py` lines 243–305.
Credential paths and a fixed set of Hermes subpaths (`state.db`,
`sessions`, `mcp-tokens`, `pairing`, `vault`, `browser-profile`,
`webapp`) are hard-denied. `config.yaml` and `auth.json` are
deliberately not in that set: reads are denied, writes go through
approval. `HERMES_WRITE_SAFE_ROOT` hard-blocks writes outside a prefix
(security.md lines 426–428). Terminal backends include docker, modal,
daytona, vercel, and SSH. Dangerous-pattern checks are skipped inside a
container (security.md lines 246–248). The egress proxy
(`website/docs/user-guide/egress/iron-proxy.md`) keeps real provider keys
out of a Docker sandbox. It does not see host-process tool calls.

Shell hooks. `hooks:` in config, documented at
`website/docs/user-guide/features/hooks.md` lines 1944–2218. A script
receives JSON on stdin and may block, modify, or request approval.
Default is fail-open. `fail_closed: true` blocks on a crash, and only
for `pre_tool_call`. First use of a `(event, command)` pair asks, then
stores the answer in `shell-hooks-allowlist.json`. The allowlist keys the
command string, not a hash, so an edited script stays trusted. `hermes
hooks doctor` reports mtime drift. Safe mode skips unapproved hooks
rather than approving them. These are a user-owned policy hook, not a
plugin. A Petasos user who also has a fail-closed shell hook will see
two blockers. Doctor should mention that, not try to disable the hook.

Safe mode. `HERMES_SAFE_MODE=1` skips user plugins (host-facts section 7,
which was run). `--safe-mode` sets that and `HERMES_IGNORE_USER_CONFIG`.
The ignore flag alone did not stop discovery.

Sub-agents. `delegation` in config_defaults.py lines 1311–1374. Depth,
concurrency, a one-shot child cap, and non-interactive auto-deny. A child
does not inherit kanban's iteration checkpoint (kanban.md lines 26–27).

MCP. Servers live under `mcp_servers`. Install can write
`tools.include` or `tools.exclude` (mcp.md lines 167–184). Stdio servers
receive a stripped environment (security.md lines 741–764). Tool errors
are redacted. `/reload-mcp` confirms (approvals.mcp_reload_confirm,
default true). Plugins call MCP only through `ctx.call_mcp`, default off,
per server (plugins.md line 1180, "Security: default-off, per-server
allowlist").

Inbound and outbound messages. Gateway allowlists and DM pairing
(security.md lines 450–549) decide who may talk to the bot. Slack,
Discord, and Matrix can require a mention. That is admission, not content
filtering. Outbound content has the redactor and, if a plugin returns a
string from `transform_llm_output`, a rewrite. Context files are scanned
before they enter the prompt (`agent/prompt_builder.py` lines 84–110
calls `tools/threat_patterns.py` `scan_for_threats`). Cron prompts and
skills have their own copies of that idea (`tools/cronjob_prompt_scan.py`,
`tools/skills_guard.py`). None of these is a general egress fence.

Bundled security plugin. `plugins/security-guidance/` is opt-in
(`provides_hooks: transform_tool_result, pre_tool_call`). It warns on
dangerous code in writes. It does not scan reads, and it does not score
a session. README lines 60–72 say the LLM review layers were not ported.

Managed config, because the guardrail design depends on it. **Read**
`hermes_cli/managed_scope.py`. The directory is `$HERMES_MANAGED_DIR` if
that directory exists, otherwise `/etc/hermes` if it exists (lines 45–59).
There is no Windows default. The comment on line 30 says other platforms
belong only inside `get_managed_dir`, and the function does not grow one.
A `config.yaml` there deep-merges on top of the user file (lines 129–151).
Any leaf can be pinned, including `plugins.enabled` and a single plugin
setting. Lists count as one leaf.

**Ran**, inside the sandbox, `HERMES_MANAGED_DIR` pointed at
`<sandbox>/managed`, not at `/etc/hermes`. A file pinning
`plugins.enabled: [petasos]`, `settings.enabled: true`, and
`settings.level: strict` produced:

- `hermes config get plugins.entries.petasos.settings.level` printed
  `strict`.
- `hermes config set` of that key exited 1: "Cannot set
  'plugins.entries.petasos.settings.level': it is managed by your
  administrator".
- `save_plugin_setting("petasos", ("level",), "relaxed")` raised
  `PermissionError`. That is the writer `ctx.set_config` and the Desktop
  form use (`plugins_state.py` lines 66–82).
- An unpinned sibling, `settings.role`, was written to the profile
  `config.yaml`.
- `hermes config set plugins.enabled` was refused the same way.

So `never` can be made real for the exact keys an admin lists. Pinning
`plugins.entries.petasos.settings` as a dict does not pin future keys.
Each leaf is its own pin. `plugins.disabled` was not in the file and was
not pinned. An agent that can write `/etc/hermes` is outside this
mechanism, which is the same limit the guardrail note already states.

#### 7 and 8. Capability by capability, and which side gives way

The table in the conclusions is the recommendation. The specific
re-implementations, with the file that owns the Hermes behaviour:

- Terminal command patterns. Petasos `petasos/scanners/minimal/command.py` (pipe-to-shell, decode-exec, fetch-exec) match a subset of
  `DANGEROUS_PATTERNS` (approval_detection.py lines 520–550). Hermes also
  covers Windows, git, docker, and the hardline. For a `terminal` call,
  Hermes has already decided before a plugin needs a second opinion.
  Petasos still has to look at command text that arrives as a message or
  as another tool's argument. That is the part Hermes does not see.
- Display redaction. `petasos/enforce/approvals.py` lines 37–63 takes a
  host redactor and withholds the text if it is missing. The reference
  plugin imports `redact_sensitive_text` (`docs/deployment/reference_plugin/__init__.py`
  around lines 1428 and 2192). Keep that call. Do not grow a second
  pattern list in the console.
- Path handling. Petasos `ToolCallGuard._classify_selfmod`
  (`petasos/guard/selfmod.py`) normalises strings and checks
  them against an owned set. Hermes `file_safety` resolves real paths,
  refuses NT namespaces, and treats `config.yaml` as approval-gated rather
  than denied. Use Hermes for "may this write proceed" on file tools.
  Keep Petasos for the commands and paths that turn the plugin off, which
  Hermes does not classify as dangerous: `hermes plugins disable`,
  `plugins.hook_callback_timeout`, `HERMES_SAFE_MODE`, `active_profile`.
  Those are listed in host-facts section 7.
- Approval. Petasos must not collect once/session/always itself. It
  returns `approve` and records the outcome. The fail-closed no-human
  path never fires the observer hooks (host-facts section 5). A log that
  only listens to those hooks will miss the blocks that matter most.
  `doctor` should say when `dangerous_posture: approve` currently means
  allow, which the redesign already requires.
- PII. `privacy.redact_pii` is not Presidio. The label on the Config page
  is "Redact PII" and the description under it is the session-prompt
  behaviour. A user who turns that on has not turned Petasos anonymization
  on. The doctor text has to say so in one sentence.
- Code warnings. `security-guidance` and a Petasos result annotation can
  both return a string. Only one is kept. Prefer Petasos to annotate by
  prefixing only when it is first, or to put the finding in the event
  spool even when the string is discarded. Do not document the banner as
  guaranteed.
- Egress. Re-implementing the website blocklist or the SSRF ranges would
  drift from `tools/url_safety.py` and would surprise a user who already
  set `security.allow_private_urls`. Taint is the gap. Keep it.

What works against the way Hermes expects a plugin to behave:

- A private UI embedded in the dashboard tab. The tab loader
  (`petasos/console/hermes/petasos-plugin.js`) pulls seven scripts from
  `/dashboard-plugins/petasos/dist/` and mounts them into a div. It uses
  `SDK.React` and then ignores `SDK.components`. The CSS
  (`petasos/console/static/petasos.css` lines 12–48) falls back to Hermes
  variables and then paints its own shell, including an Arcade font.
- A second HTTP server and a second token (`docs/deployment/hermes-desktop.md`
  lines 726–768). Hermes already authenticated the dashboard page.
- Writing the profile `config.yaml` from that server (the same doc, lines
  791–797, describes last-writer-wins against the agent). Hermes's writer
  is `save_plugin_setting`, and it is the writer that honours the managed
  pin.
- The install document's `hooks:` list and top-level `petasos:` key
  (hermes-desktop.md lines 186–213 and 328–351). Current Hermes stores
  `hooks:` as `provides_hooks` when the key is absent, and validate still
  wants `provides_hooks` (host-facts section 1). The settings form will
  not edit a top-level `petasos:` key. It edits `plugins.entries`.
- Assuming the plugin API mounts only for a bundled copy. At this tag the
  gate is `plugins.enabled`.

#### 9. Stable or internal

Covered in the conclusions. Two extra notes from this tag.

The compatibility section of the plugin guide (lines 235–301) is the
contract to cite in the adapter: additive context methods, keyword hook
payloads, unknown manifest fields ignored, two minor releases of
deprecation. It also says, in the same breath, that monkeypatching core
is refused by the catalog. Petasos should not wrap `AIAgent` or
`tools.approval` at runtime. The approve directive is the supported way
to enter that gate.

`api_version` does not gate loading. A manifest without it is fine. The
number is advisory. The enforcing checks are `requires_hermes`,
`provides_hooks` matching `register()`, and the public-import warning.
Pin `requires_hermes` to a floor once the adapter is written, and re-read
the public list when that floor moves. The September 2026 split is the
reason the import seam must be one module: plugins that imported the old
paths failed at load with no other warning than `hermes plugins list`.

### C. Reference screenshots

#### 10. Hermes

Fourteen images in `/tmp/petasos-h1-screenshots/hermes/`, seven per theme.
Desktop width 1440×900. **Ran** against the sandbox dashboard on
`127.0.0.1:18791`. No gateway, no model provider, no model call. The web
UI was built inside the sandbox with Node 26 because the checkout had no
`web_dist` and the repo refuses Node 22 (`package.json` engines, pnpm
12.15.0 from `pm/lock.json`). Playwright Chromium was installed into
`<sandbox>/shot` and its browser cache landed under `<sandbox>/home`.

The pages are Sessions (the rail and an empty state), Kanban, Plugins,
Config, Config → Security, Logs, and System. Nous Blue is the light
theme. There is no separate light/dark toggle. The other built-ins are
alternate dark skins plus Teal Large.

Index: `/tmp/petasos-h1-screenshots/INDEX.md`.

#### 11. Infisical

Ten public images in `/tmp/petasos-h1-screenshots/infisical/`, downloaded
from Infisical's documentation CDN. No account, no login. Each row in the
index has the docs page and the image URL.

They are the organization overview, the secrets dashboard, the secrets
overview, organization settings, project roles, the custom-role form, a
change-approval policy, the audit-log table, the insights overview, and
the new-project step. The useful habits, compared with the Hermes
screenshots: a list that shows state per row, a policy page that is a
checklist rather than a YAML box, and an audit table with actor, action,
and time. The new-project image is the onboarding empty state.

#### 12. Three other screens worth looking at

No images collected.

- Firefox Enhanced Tracking Protection, the Standard / Strict / Custom
  choice. One named level, and Custom is where the individual switches
  live. <https://support.mozilla.org/en-US/kb/enhanced-tracking-protection-firefox-desktop>
- uBlock Origin's logger, the page that lists what was blocked and the
  rule that did it. <https://github.com/gorhill/uBlock/wiki/The-logger>
- GitHub secret-scanning alerts, one row per finding with the secret type
  and where it was. <https://docs.github.com/en/code-security/secret-scanning/managing-alerts-from-secret-scanning>

### What was not run

- No Hermes gateway, no messaging platform, no model provider, and no
  model API call. The System page therefore shows Gateway Status Off, and
  the log warns that `state.db` is uninitialized.
- No Desktop app. The settings form is described from
  `plugin-settings-form.tsx` and the plugin guide, not from a window.
  `config_schema` was exercised through the API in the earlier host-facts
  run, not again here.
- No `hermes dashboard --stop` and no `hermes dashboard --status`. Both
  scan the process table and signal every dashboard on the machine. The
  sandbox server was stopped by its own process group. Port 18791 was
  free afterwards, and the listener PID was gone.
- No kanban worker and no check of whether a worker freezes plugin
  settings at session start. Host-facts left that open. It is still open.
- No write to `/etc/hermes`. The pin experiment used a directory inside
  the sandbox.
- The Hermes checkout is a depth-1 clone, so plugin-file history before
  `3b421578` was not available. The September 2026 import-path removal is
  taken from the plugin guide at this tag, not from a log.
- Infisical screenshots are the vendor's documentation images, not a
  session in their product.
