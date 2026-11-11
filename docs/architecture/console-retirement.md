# Console retirement

Record of what a person could do in the standalone console and in the copy of
it mounted inside Hermes, written before either is deleted. Both surfaces
called the same handlers in `petasos/console/server.py`. The standalone server
(`petasos-console`, `python -m petasos.console`) bound `127.0.0.1:8384` and
served `petasos/console/static/`. The embedded copy mounted the same routes
from `petasos/console/hermes/plugin_api.py`.

"Lives now" names code that does the thing. The tab script is
`hermes-plugin/petasos/dashboard/index.js`. Its views are `overview`,
`activity`, `tryit` and `settings`. Its API is mounted at
`/api/plugins/petasos/` by `petasos/hermes/dashboard/router.py`.

| Feature | Where it lives now |
|---|---|
| Observability page (scanner health, integrity, history, the protection banner) | Overview and Activity. Overview draws the verdict, the last 24 hours, Checks and Who can change these settings. Activity draws the event list. |
| Scan Playground page | Try it (`tryit`). It posts to `POST /playground`. |
| Config Editor page | Settings, plus the job and strictness controls on Overview. Settings reads `GET /settings` and writes `PUT /settings`. |
| Armed / unequipped banner and its toggle (`GET /api/armed`, `POST /api/armed`) | Overview's Pause protection and Resume protection, and the Protection switch on Settings. Both write `enabled` with `PUT /settings`. `GET /status` returns `protection` and `switches` (`petasos/hermes/dashboard/status.py`). |
| Scanner health panel (`GET /api/health`, the `scanners` list) | Overview's Checks panel, from `scanners` and `doctor` on `GET /status`. The same report is `petasos doctor` (`petasos/hermes/commands.py`). |
| Integrity panel (whether the spool's signatures check out) | Activity, from `integrity` on `GET /activity` and `GET /activity/summary` (`petasos/hermes/dashboard/activity.py`). How to start signing is `record_signing` on `GET /status`. |
| Scan history of enforcement events, newest first (`GET /api/scan-history`) | Activity. `GET /activity` pages newest first; `GET /activity/{scan_id}` is one event. Overview's Last 24 hours panel reads `GET /activity` and `GET /activity/summary`. |
| History filter "all" or "self-tamper" | Activity's outcome and kind filters. A setting change that was not stopped is the outcome `not_stopped` (`OUTCOME_CODES` in the tab script; `outcome` in `activity.py`). |
| Older / Newer paging through retained history | Activity's Show older events button, which sends the `cursor` from `next_cursor` (`activity.read_page`). |
| Text scan, inbound or outbound (`POST /api/scan`) | Try it, text mode. `POST /playground` takes `text` and `direction` (`playground.try_input`). The trial is not written to the spool. |
| Findings list with severity and the matched span | Try it, from `findings` on `POST /playground` (`FindingList` and `Marked` in the tab script). |
| Normalization, the text before and after disguise-folding | Try it, the "How Petasos read it" block, from `normalized` when `normalized_changed` is set (`playground._body`). |
| Strength dial (balanced and the other presets) | Job and strictness. Overview's setup controls and Settings write `role` and `level`. The choices come from `roles` and `levels` on `GET /settings` (`catalog.read_settings`). The manifest's `config_schema` offers the same two choices to Hermes Desktop (`petasos/hermes/manifest.py`). `redesign.md` section 11 replaces the preset registry with `layers.py`. |
| Read and save settings (`GET /api/config`, `PUT /api/config`), including where a value came from | Settings. `GET /settings` is built from `describe()` and `resolve()` (`catalog.read_settings`). `POST /settings/preview` shows the change before it is saved. `PUT /settings` writes through Hermes's settings writer (`changes.save_settings`). `DELETE /overrides` and `DELETE /overrides/{path}` put a setting back. A restart-required field is named in `restart`. The old equipped save hot-applied the console's own pipeline; the tab writes the settings the gateway reads (section 8.2, one writer). |
| Secrets redacted on read, and not accepted back on write | `GET /settings` returns `session_secret` and `hash_key` as `set` or `unset` only (`catalog.read_settings`). `PUT /settings` and `POST /settings/preview` reject both keys (`changes._reject_secrets`). The manifest declares them as environment secrets (`manifest.render_manifest`). |
| List of old named profiles (`GET /api/profiles`) | The job list on `GET /settings` (`roles`), drawn by Overview and Settings. |
| Live enforcement events (`GET /api/events`, the server-sent stream) | Activity and Overview poll `GET /activity`. The tab reads the spool (`redesign.md` section 8.1) and is a different process from the one that enforces (section 8.2), so there is no push socket. |
| Version string (`GET /api/about`) | `petasos_version` on `GET /status` (`status.py`). The tab script does not draw it. |
| Standalone process on `127.0.0.1:8384`, `petasos-console`, and `GET /` | Dropped. `redesign.md` section 8 retires the console's own local web server. |
| Console token (`PETASOS_CONSOLE_TOKEN`), the unlock panel, and the bearer check on `/api/*` | Dropped. Section 8 retires the console's own token. Section 8.6: Hermes's dashboard session returns 401 without `X-Hermes-Session-Token`, and Petasos adds no second token. |
| Rate-limited `petasos.selfmod.console_probe` finding on a 401 | Dropped with the token. The probe ran only inside the console's bearer check (`server._maybe_fire_console_probe`). Section 8.6 leaves no console 401 to record. |
| Arcade font, private palette, and the four-pane shell | Dropped. Section 8.2: the tab uses Hermes's components and tokens, and Petasos ships no font, palette or layout shell of its own. |
| A playground scan kept in the on-screen history ring | Dropped. Section 8.2: the playground shows what would happen and the activity panel shows what did. `playground.try_input` does not write the spool. |
| Refused-approvals queue (`GET /api/approvals/refused`): choice filter, rule-origin filter, show reviewed, refresh | No equivalent. Section 8.2 says an approval ask appears in Hermes's own prompt. Nothing in the tab or in `router.py` lists past refusals or filters them. |
| Mark one refusal reviewed (`POST /api/approvals/reviewed`), including the rule that the standalone server refused the mark unless the console token was set | No equivalent. No route writes a reviewed set. |
| Open a Hermes profile that is not the one this process is running, read its history or settings, save it without touching the live pipeline, or be refused when arming it | No equivalent. Every dashboard route calls `active_home()` (`router.py`). |
| Anonymized output panel (the scan text with personal information hidden) | No equivalent. `POST /playground` returns the decision, the findings and the normalized text (`playground._body`). It does not return an anonymized document. |
| Session overlay on a trial (the running risk score and escalation tier for a chosen session) | No equivalent. A trial builds a pipeline and throws it away (`playground.py`). The response has no score and no tier, and the request has no session id. The old `POST /api/scan` took `session_id`. |
| Trap burst (a rapid series of attacks against one session, watched as the tier climbs) | No equivalent. Try it checks one input per request. |
| Process counters on the health payload: uptime, config hash, lifetime scan count, lifetime self-tamper count, history-ring capacity | No equivalent. `GET /status` reports protection, the two switches, scanners and the doctor report. It does not report those process counters. Self-tamper events themselves are in Activity. |
| About page: welcome text, repository link, issue tracker, scanner reference, configuration guide | No equivalent. |
| About page: the donation panel and the credits | No equivalent. |
| `GET /diag` on the embedded plugin API | No equivalent. It returned whether the console handlers had finished starting. |
| LIVE / POLLING blip, and the spoken announcement of the newest scan verdict | No equivalent. Overview and Activity poll, and a paused or alarming state is marked in the page, but nothing draws a connection blip or announces each new verdict. |

## No equivalent

These are for the project's owner to rule on. The console is still deleted.

- Refused-approvals queue (`GET /api/approvals/refused`): choice filter, rule-origin filter, show reviewed, refresh. Section 8.2 moves the live approval ask to Hermes's own prompt. Nothing lists past refusals.
- Mark one refusal reviewed (`POST /api/approvals/reviewed`), and the standalone rule that refused the mark unless `PETASOS_CONSOLE_TOKEN` was set.
- Open a Hermes profile that is not the running one: read its history or settings, save it without hot-applying, or be refused when arming it. The new routes use `active_home()` only.
- Anonymized output panel on a trial scan.
- Session overlay on a trial (risk score, escalation tier, and a chosen session id).
- Trap burst.
- Process counters: uptime, config hash, lifetime scan count, lifetime self-tamper count, history-ring capacity.
- About page welcome text and the links to the repository, the issue tracker, the scanner reference and the configuration guide.
- About page donation panel and credits.
- `GET /diag`.
- LIVE / POLLING blip, and the spoken announcement of the newest scan verdict.

The version string is not in that list. `GET /status` returns it as `petasos_version`. The tab does not draw it.
