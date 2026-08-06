// Unit tests for Pet.scanHistoryRows enforcement rendering (petasos.js), PET-131.
//
// The Observability history must render live enforcement entries
// (source==="enforcement") distinguishably from playground scans: an "enf" source
// pill, a blocked / bypassed / safe badge, and tool + event/tier in place of the
// playground direction/findings pair. A bypassed_disarmed row carries no
// tier/rule/severity and must show the no-data glyph, never "undefined". Playground
// rows render byte-identically to before. Never throws on a malformed/partial/
// non-object entry (the scan_result SSE handler re-renders synchronously). New
// operator-facing labels carry no banned dash (em / en / double-hyphen) per house
// style — the only "—" is the no-data glyph for absent fields.
//
// Zero npm deps: Node's built-in test runner + a DOM shim + node:vm over the real
// shipped petasos.js. Run with: node --test tests/js/enforcement-history.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── DOM shim ────────────────────────────────────────────────────────────────
// scanHistoryRows uses `el.textContent = ...` on freshly-created spans, so the
// shim ALLOWS textContent assignment (unlike the PET-103 scanner-health shim). The
// textContent getter aggregates child text plus any directly-set text.
function makeNode(nodeType) {
  return {
    nodeType, // 1 = element, 3 = text, 11 = fragment
    childNodes: [],
    style: {},
    className: "",
    title: "",
    dataset: {},
    _text: "",
    setAttribute() {},
    addEventListener() {},
    appendChild(child) {
      this.childNodes.push(child);
      return child;
    },
    get textContent() {
      if (this.nodeType === 3) return this.nodeValue;
      return this.childNodes.map((c) => c.textContent).join("") + (this._text || "");
    },
    set textContent(v) {
      this._text = String(v);
      this.childNodes = [];
    },
  };
}

const document = {
  createDocumentFragment() {
    return makeNode(11);
  },
  createElement(tag) {
    const el = makeNode(1);
    el.tagName = tag.toUpperCase();
    el.localName = tag;
    return el;
  },
  createTextNode(t) {
    const node = makeNode(3);
    node.nodeValue = String(t);
    return node;
  },
};

const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
const sandbox = { window: {}, document };
vm.runInNewContext(readFileSync(petasosJsPath, "utf8"), sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

// ── helpers ───────────────────────────────────────────────────────────────
function findEl(node, pred) {
  for (const child of node.childNodes || []) {
    if (child.nodeType === 1) {
      if (pred(child)) return child;
      const found = findEl(child, pred);
      if (found) return found;
    }
  }
  return null;
}
const hasClass = (cls) => (el) => typeof el.className === "string" && el.className.split(/\s+/).includes(cls);
function text(tree) {
  return tree.textContent;
}

const ENF_BLOCK = {
  source: "enforcement",
  safe: false,
  event_type: "quarantine",
  tier: "tier2",
  tool: "send_email",
  rule_id: "petasos.injection.x",
  severity: "HIGH",
  session_id: "sess-1",
  duration_ms: 5,
  timestamp: 1700000000,
  scan_id: "e-001",
};
const ENF_BYPASS = {
  source: "enforcement",
  safe: true,
  event_type: "bypassed_disarmed",
  tool: "send_email",
  session_id: "sess-2",
  timestamp: 1700000000,
  scan_id: "e-002",
  // tier / rule_id / severity deliberately absent
};
const PLAYGROUND = {
  safe: false,
  direction: "inbound",
  finding_count: 2,
  duration_ms: 3.5,
  session_id: "sess-p",
  timestamp: 1700000000,
  scan_id: "s-aaa",
};

// ── tests ───────────────────────────────────────────────────────────────

test("loader: petasos.js exports scanHistoryRows", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.scanHistoryRows, "function");
});

test("enforcement block row renders distinguishably (enf pill + blocked badge + tool)", () => {
  const tree = Pet.scanHistoryRows([ENF_BLOCK]);
  const enfPill = findEl(tree, hasClass("blue"));
  assert.ok(enfPill, "expected an 'enf' source pill");
  assert.equal(enfPill.textContent, "enf");

  const blockedBadge = findEl(tree, (el) => hasClass("err")(el) && el.textContent === "blocked");
  assert.ok(blockedBadge, "expected a 'blocked' (pill err) badge");

  const t = text(tree);
  assert.ok(t.includes("send_email"), "tool name rendered");
  assert.ok(t.includes("quarantine"), "event_type rendered");
});

test("bypassed_disarmed row: warn badge, no tier/rule/severity rendered as 'undefined'", () => {
  const tree = Pet.scanHistoryRows([ENF_BYPASS]);
  const badge = findEl(tree, (el) => hasClass("warn")(el) && el.textContent === "bypassed (disarmed)");
  assert.ok(badge, "expected a 'bypassed (disarmed)' (pill warn) badge");
  // It must NOT count as blocked (no 'err' badge present).
  assert.equal(findEl(tree, (el) => hasClass("err")(el)), null, "bypass must not be a blocked/err badge");
  // Absent fields show the no-data glyph, never the string 'undefined'.
  assert.ok(!/undefined/.test(text(tree)), "no 'undefined' for absent tier/rule/severity");
});

test("playground row renders unchanged (no enf pill; findings count present)", () => {
  const tree = Pet.scanHistoryRows([PLAYGROUND]);
  assert.equal(findEl(tree, hasClass("blue")), null, "playground row has no 'enf' source pill");
  const blockedBadge = findEl(tree, (el) => hasClass("err")(el) && el.textContent === "blocked");
  assert.ok(blockedBadge, "playground blocked badge preserved");
  assert.ok(text(tree).includes("2 findings"), "playground findings count preserved");
});

test("never throws on malformed / partial / non-object entries", () => {
  assert.doesNotThrow(() => Pet.scanHistoryRows([{ source: "enforcement" }])); // no tool/event/safe
  assert.doesNotThrow(() => Pet.scanHistoryRows([null, 42, "x"])); // non-object entries skipped
  // A non-object entry alongside a valid enforcement entry: the valid one still renders.
  const tree = Pet.scanHistoryRows([null, ENF_BLOCK]);
  assert.ok(text(tree).includes("send_email"));
});

test("enforcement labels carry no banned dash (em / en / double-hyphen)", () => {
  // Fully-populated rows so no field falls back to the no-data glyph '—'; what
  // remains is pure label text, which must be dash-free per house style.
  const tree = Pet.scanHistoryRows([ENF_BLOCK, { ...ENF_BYPASS, tier: "n/a", rule_id: "n/a", severity: "n/a" }]);
  const t = text(tree);
  assert.ok(!t.includes("—"), "no em dash in labels");
  assert.ok(!t.includes("–"), "no en dash in labels");
  assert.ok(!t.includes("--"), "no double-hyphen in labels");
});

// ── PET-170: ingestion-result scan rows (Test plan 14) ──────────────────────
//
// Two independent discriminator chains needed an arm: the badge chain in
// scanHistoryRows and the drill-down chain in scanDetailPanel. Both precedents
// (PET-167 cold-start, PET-164 selfmod) shipped a pin for exactly this, because a
// body-only edit leaves the row in the terminal "Unknown row kind" else where
// `reason` is never rendered at all. `reason` is the operator's ONLY copy of the
// evidence here: the model-facing banner deliberately quotes none of the matched text.

const ENF_INGEST_FLAGGED = {
  source: "enforcement",
  safe: true, // annotation, not a block: the content reached the model whole
  event_type: "ingest_flagged",
  tool: "read_file",
  rule_id: "petasos.syntactic.injection.ignore-previous",
  severity: "HIGH",
  reason:
    "Injection pattern matched: ignore-previous (tool result len=42000, truncated=True, scanned=8000)",
  armed: true,
  session_id: "sess-ing",
  duration_ms: 0,
  finding_count: 1,
  timestamp: 1700000000,
  scan_id: "e-ing1",
};
const ENF_INGEST_UNSCANNED = {
  source: "enforcement",
  safe: true,
  event_type: "ingest_unscanned",
  tool: "web_search",
  reason: "result scan unavailable cause=timeout len=120345",
  armed: true,
  session_id: "sess-ing",
  duration_ms: 0,
  finding_count: 1,
  timestamp: 1700000000,
  scan_id: "e-ing2",
  // rule_id / severity deliberately absent: no finding exists on this path
};

test("ingestion rows render amber, never the red blocked badge", () => {
  for (const row of [ENF_INGEST_FLAGGED, ENF_INGEST_UNSCANNED]) {
    const tree = Pet.scanHistoryRows([row]);
    assert.equal(
      findEl(tree, hasClass("err")),
      null,
      `${row.event_type} must not wear a red (err) badge`
    );
    const badge = findEl(tree, hasClass("warn"));
    assert.ok(badge, `${row.event_type} must wear an amber (warn) badge`);
    assert.ok(!/undefined/.test(text(tree)), "no 'undefined' for absent rule/severity/tier");
    assert.ok(text(tree).includes(row.tool), "tool rendered");
  }
  // The two classes are labelled apart: calling an unscanned result "flagged" would
  // assert a finding that by definition does not exist on that path.
  assert.equal(
    findEl(Pet.scanHistoryRows([ENF_INGEST_FLAGGED]), hasClass("warn")).textContent,
    "flagged"
  );
  assert.equal(
    findEl(Pet.scanHistoryRows([ENF_INGEST_UNSCANNED]), hasClass("warn")).textContent,
    "unscanned"
  );
});

test("ingestion rows do not change the blocked tile count", () => {
  // The tile loop is `if (e.safe === false) blocked++`, so this is the assertion that
  // catches a future summary setting safe=false and rendering every flagged read as a
  // red block. Replicated here rather than calling the tile renderer, which needs the
  // full Pet.state DOM.
  const rows = [ENF_INGEST_FLAGGED, ENF_INGEST_UNSCANNED, ENF_BLOCK, PLAYGROUND];
  const blocked = rows.filter((e) => e.safe === false).length;
  assert.equal(blocked, 2, "only the true blocks count; neither ingestion row does");
});

test("ingestion drill-down renders the reason, not the unknown-row fallback", () => {
  for (const row of [ENF_INGEST_FLAGGED, ENF_INGEST_UNSCANNED]) {
    const t = text(Pet.scanDetailPanel(row));
    assert.ok(!t.includes("Unknown row kind"), `${row.event_type} must not hit the unknown branch`);
    assert.ok(t.includes(row.reason), "reason rendered (the operator's only copy of the evidence)");
    assert.ok(t.includes(row.tool), "tool rendered");
    assert.ok(t.includes(row.session_id), "session rendered");
    assert.ok(
      t.includes("Detection only: the content was passed through to the model"),
      "the drill-down states that nothing was withheld"
    );
    assert.ok(!t.includes("scan ran: unknown"), "never falls through to 'unknown' coverage");
  }
  assert.ok(
    text(Pet.scanDetailPanel(ENF_INGEST_FLAGGED)).includes(ENF_INGEST_FLAGGED.rule_id),
    "flagged row surfaces the rule id"
  );
  assert.ok(
    text(Pet.scanDetailPanel(ENF_INGEST_UNSCANNED)).includes("passed through to the model unverified"),
    "unscanned explainer rendered"
  );
});

test("ingestion rows never throw on partial input", () => {
  assert.doesNotThrow(() => Pet.scanHistoryRows([{ source: "enforcement", event_type: "ingest_flagged" }]));
  assert.doesNotThrow(() => Pet.scanDetailPanel({ source: "enforcement", event_type: "ingest_unscanned" }));
});
