# PET-182 harness audit

Baseline: `ad8d33a`. There are 24 suites, 313 tests and 7,858 JavaScript lines.
The ticket's 22 suites / 6,925 lines describe an older tree. The audit examined
node factories, document factories, source reads, VM globals and throwing fixtures
before extraction. No console behavior or existing assertion is changed.

A = duplicate within the named family (ignoring comments/formatting).
B = deliberately stricter surface. C = distinct surface or lifecycle fixture.
Categories can overlap; a shared DOM does not imply interchangeable runtimes.

| Suite (`.test.mjs`) | Class | DOM and retained differences | Runtime fixtures retained in suite |
| --- | --- | --- | --- |
| arm-scope-view | A/C | Scope family: raw `attrs`, empty selectors, no text accessor/localName | Real timers and stream APIs; parked fetch |
| armed-sync | B | Styled nodes; getter-only textContent | Bare sandbox |
| cold-start-row | A | Row family: dataset, stored text, no-op attributes/events | Bare sandbox |
| config-sections | A | Form family: recorded attributes/events, replacement text, SVG namespace | Bare sandbox |
| console-token | C | Clearing text/HTML, insertion, form values, `attrs`, empty selectors | Fresh realm/document, storage failure fixtures, fetch, recording timers, abort/decoder overrides |
| disarm-bypass-counter | A | Minimal family: no text accessor/localName, no-op attributes/events | Bare sandbox |
| enforcement-history | A | Row family | Bare sandbox |
| enforcement-provenance | A | Minimal family | Bare sandbox |
| hermes-diegetic-profile | C | Form family plus parent links, insertion/removal, selectors, head, HTML getter/clear | Fresh realm/document, host history/events, SDK, fetch, inert timers, throwing subscriber |
| hermes-profile-selector | C | Form family plus parent links, removal and class-only selector | Suite-local API/host fixtures |
| integrity-health | A | Minimal family | Bare sandbox |
| playground | C | Clearing text/HTML; SVG aliases createElement; no-op attributes/events | Suite-local scan fixtures |
| preset-dial | A | Form family | Bare sandbox |
| profile-picker | C | Form family plus removal without parent links | Bare sandbox |
| profile-scoped-reads | A/C | Scope family | Real timers and stream APIs; parked fetch, per-case state reset |
| richtext | B | Getter-only text; deliberately no style, className or extra DOM APIs | Bare sandbox |
| scan-history-count | A | Minimal family | Bare sandbox |
| scan-history-paging | A/C | Minimal family | Per-case fetch overrides and deferred requests |
| scanner-health | B | Styled nodes; PET-103 D10 throwing setter **and** aggregating getter | Existing guard-of-the-guard test |
| selfmod-row | A | Row family | Bare sandbox |
| selfmod-tile-filter | A/C | Row family | Source-copy assertion now uses the shared source read |
| skeleton | A | Form family | Bare sandbox |
| sse-reconnect | B/C | Getter-only text, no-op attributes, null querySelector, currentScript:null | Fresh realm/document, controlled streams/timers/randomness, capturing console, invalid-outcome guard |
| trap-burst | C | Playground family plus insertion/firstChild | Immediate short timers; long timers suppressed |

## Strictness and failure fixtures

The four-file `throw` count in the original brief is not a count of strict DOMs.
Only scanner-health has the explicit PET-103 D10 setter; its existing test checks
that the setter throws, and its renderer tests check that the getter still works.
Getter-only textContent in armed-sync, richtext and sse-reconnect also rejects
assignment by the strict-mode console. Those accessors remain getter-only.

Console-token's three throws simulate denied storage and failed set/remove writes.
Hermes-diegetic-profile's throw tests subscriber exception isolation.
SSE-reconnect's `bad /events outcome` throw rejects an invalid test fixture; it is
not a production DOM regression guard. These fixtures stay local, unchanged.

## Shared seam and fidelity boundary

`harness.mjs` is the only place that reads/evaluates the shipped console source.
`loadConsole(sandbox)` evaluates in the supplied sandbox and injects no additional
globals; suites retain their fresh-sandbox boundaries. `consoleSource` exposes that same read for the existing copy
assertion. PET-183 can change the source-loading implementation here.

`createDOM(options)` returns node/document factories. Each suite names its existing
capabilities explicitly; it does not receive a union of all suites' APIs. Text modes
preserve the old distinction between getter-only, throwing, stored text, replacing
with one text node, and clearing empty/null text. Attribute modes preserve raw vs
string values and missing-value null vs undefined. Optional tree operations,
selectors, SVG namespaces, event recording and innerHTML clearing are enabled only
where previously present. Specialized selector matching remains suite-local.

This remains a test DOM: appends do not flatten fragments or reparent children,
and HTML setters model clearing, not parsing. Cross-realm assertions still compare
keys and values rather than host-realm prototypes. No dependency or build step is
introduced; no additional frontend coverage is added.
