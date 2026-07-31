// Unit tests for selfmod_attempt rendering (petasos.js), PET-164 + PET-165.
//
// A self-tamper classification row (event_type === "selfmod_attempt") is
// detection-only: the summary carries safe=true, but the row must never wear
// the green "safe" badge. The drill-down must render rule/severity/reason and
// the detection-only explainer, never the "Unknown row kind" fallback, and the
// provenance line must not claim a content scan ran. Labels carry no banned
// dash (em / en / double-hyphen) per house style.
//
// PET-165 differentiates the badge by severity: config_write (critical) takes
// the red `err` class, config_ref (high) stays amber `warn`, and the severity
// rides the badge TEXT as well as the class so the distinction never depends on
// color alone. Anything else falls back to the pre-PET-165 plain amber badge.
//
// Zero npm deps: Node's built-in test runner + a DOM shim + node:vm over the
// real shipped petasos.js. Run with: node --test tests/js/selfmod-row.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── DOM shim (same as enforcement-history.test.mjs) ─────────────────────────
function makeNode(nodeType) {
  return {
    nodeType,
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

// ── helpers ─────────────────────────────────────────────────────────────────
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

const ENF_SELFMOD = {
  source: "enforcement",
  safe: true, // detection only: not counted as a block
  event_type: "selfmod_attempt",
  tool: "write_file",
  rule_id: "petasos.selfmod.config_write",
  severity: "critical",
  reason: "selfmod target: ~/.hermes/profiles/gibson/config.yaml",
  armed: true,
  session_id: "sess-sm",
  duration_ms: 0,
  timestamp: 1700000000,
  scan_id: "e-sm1",
};

// ── row tests ───────────────────────────────────────────────────────────────

test("selfmod row: self-tamper badge, never the green safe badge", () => {
  const tree = Pet.scanHistoryRows([ENF_SELFMOD]);
  assert.equal(
    findEl(tree, (el) => hasClass("ok")(el) && el.textContent === "safe"),
    null,
    "selfmod row must not wear the green 'safe' badge"
  );
  assert.ok(findEl(tree, (el) => /^self-tamper/.test(el.textContent)), "self-tamper badge present");
  assert.equal(findEl(tree, (el) => el.textContent === "blocked"), null, "selfmod is detection only, never 'blocked'");
  const enfPill = findEl(tree, hasClass("blue"));
  assert.ok(enfPill && enfPill.textContent === "enf", "enf source pill present");
  assert.ok(text(tree).includes("selfmod_attempt"), "event_type rendered");
  assert.ok(text(tree).includes("write_file"), "tool rendered");
});

// ── PET-165: severity-differentiated badges ─────────────────────────────────

const badgeOf = (row) =>
  findEl(Pet.scanHistoryRows([row]), (el) => /^self-tamper/.test(el.textContent));

test("PET-165 badge: critical severity takes the err class and says so in text", () => {
  const badge = badgeOf(ENF_SELFMOD); // severity: "critical"
  assert.ok(badge, "badge rendered");
  assert.equal(badge.textContent, "self-tamper (critical)");
  assert.ok(hasClass("err")(badge), "critical rides the red err class, not amber");
});

test("PET-165 badge: high severity stays amber and says so in text", () => {
  const badge = badgeOf({
    ...ENF_SELFMOD,
    rule_id: "petasos.selfmod.config_ref",
    severity: "high",
  });
  assert.ok(badge, "badge rendered");
  assert.equal(badge.textContent, "self-tamper (high)");
  assert.ok(hasClass("warn")(badge), "high stays on the amber warn class");
});

test("PET-165 badge: missing / nonsense severity falls back to the plain amber badge", () => {
  // The exact pre-PET-165 rendering, so an unrecognized severity can never produce a
  // half-formed label like "self-tamper (undefined)" or throw mid-render.
  for (const severity of [undefined, null, "", "SEVERE", "Critical", 3, {}, ["high"], true]) {
    const row = { ...ENF_SELFMOD, severity };
    let badge;
    assert.doesNotThrow(() => { badge = badgeOf(row); }, `severity ${JSON.stringify(severity)} threw`);
    assert.equal(badge.textContent, "self-tamper", `severity ${JSON.stringify(severity)} must fall back`);
    assert.ok(hasClass("warn")(badge), "fallback stays amber");
  }
});

test("PET-165 badge: severity does not leak onto non-selfmod rows", () => {
  // The mapping keys on the row's severity only WITHIN a selfmod row; an ordinary
  // enforcement block row carrying a severity keeps its own badge text.
  const block = { source: "enforcement", event_type: "block", safe: false, severity: "critical", scan_id: "e-b1" };
  const badge = findEl(Pet.scanHistoryRows([block]), (el) => el.textContent === "blocked");
  assert.ok(badge, "block row still reads 'blocked', not a severity-suffixed label");
});

// ── drill-down tests ────────────────────────────────────────────────────────

test("selfmod detail: renders rule/severity/reason, not the unknown-row fallback", () => {
  const panel = Pet.scanDetailPanel(ENF_SELFMOD);
  const t = text(panel);
  assert.ok(!t.includes("Unknown row kind"), "must not fall into the unknown-row branch");
  assert.ok(t.includes("petasos.selfmod.config_write"), "rule_id rendered");
  assert.ok(t.includes("critical"), "severity rendered");
  assert.ok(t.includes("selfmod target: ~/.hermes/profiles/gibson/config.yaml"), "reason rendered");
  assert.ok(t.includes("Self-tamper attempt"), "explainer headline rendered");
  assert.ok(t.includes("Detection only"), "detection-only copy rendered");
});

test("selfmod detail provenance: no content-scan claim, armed passthrough honored", () => {
  const panel = Pet.scanDetailPanel(ENF_SELFMOD);
  const t = text(panel);
  assert.ok(t.includes("scan ran: n/a (tool argument classification, not a content scan)"));
  assert.ok(t.includes("armed: armed (Equipped)"));
});

// ── robustness + house style ────────────────────────────────────────────────

test("selfmod row/detail never throw on missing fields; no 'undefined' text", () => {
  const bare = { source: "enforcement", event_type: "selfmod_attempt", scan_id: "e-sm2" };
  assert.doesNotThrow(() => Pet.scanHistoryRows([bare]));
  assert.doesNotThrow(() => Pet.scanDetailPanel(bare));
  const t = text(Pet.scanDetailPanel(bare)) + text(Pet.scanHistoryRows([bare]));
  assert.ok(!/undefined/.test(t), "absent fields show the no-data glyph, never 'undefined'");
});

test("selfmod labels carry no banned dash (em / en / double-hyphen)", () => {
  const t = text(Pet.scanHistoryRows([ENF_SELFMOD])) + text(Pet.scanDetailPanel(ENF_SELFMOD));
  assert.ok(!t.includes("—"), "no em dash in labels");
  assert.ok(!t.includes("–"), "no en dash in labels");
  assert.ok(!t.includes("--"), "no double-hyphen in labels");
});
