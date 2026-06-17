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
