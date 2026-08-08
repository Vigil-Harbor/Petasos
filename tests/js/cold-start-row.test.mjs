// Unit tests for cold-start marker rendering (petasos.js), PET-167.
//
// `cold_start_degraded` and `init_failed` are per-session, non-blocking markers: the
// summary carries safe=true and finding_count=0, and they stay out of the block-class
// set so they never inflate the blocked tile. But a row whose entire meaning is "we did
// not scan" must not render as if everything was fine. Three surfaces are pinned:
//
//   - the row badge, which fell through to the green "safe" pill;
//   - the provenance line's `scan ran:` value, computed in a chain SEPARATE from the
//     body branches, which read "unknown";
//   - the drill-down body, which fell to the terminal "Unknown row kind" branch and so
//     never rendered `reason` at all.
//
// Modelled case-for-case on selfmod-row.test.mjs. Zero npm deps: Node's built-in test
// runner + a DOM shim + node:vm over the real shipped petasos.js.
// Run with: node --test tests/js/cold-start-row.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── DOM shim (same as selfmod-row.test.mjs) ─────────────────────────────────
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

const ENF_DEGRADED = {
  source: "enforcement",
  safe: true, // non-blocking marker: not counted as a block
  event_type: "cold_start_degraded",
  tool: "write_file",
  // PET-170: refreshed in lockstep with the shim's _COLD_START_REASON, which dropped the
  // "(warm path too)" parenthetical this ticket made false.
  reason:
    "scanners not up; tool results unscanned; syntactic only, dangerous tools only, params only (100k cap)",
  armed: true,
  session_id: "sess-cold",
  duration_ms: 0,
  finding_count: 0,
  timestamp: 1700000000,
  scan_id: "e-cs1",
};

const ENF_INIT_FAILED = {
  ...ENF_DEGRADED,
  event_type: "init_failed",
  // PET-171: refreshed in lockstep with the shim's _INIT_FAILED_REASON_PREFIX. The branch
  // now runs the syntactic fallback, so "enforcement disabled ... allowed unscanned" is
  // false. Test INPUT carrying the Python-side prefix, not a fourth JS string.
  reason:
    "scanner init failed; syntactic fallback only (dangerous tools, params, 100k cap); tool results unscanned; no ML scanners: No module named 'x'",
  scan_id: "e-cs2",
};

// ── a. badge ────────────────────────────────────────────────────────────────

test("cold-start badges are amber and never the green safe pill", () => {
  for (const [row, label] of [
    [ENF_DEGRADED, "degraded"],
    // PET-171: was "unenforced". Not folded into "degraded" either: that would erase the
    // transient-versus-permanent distinction an operator scanning history most needs.
    [ENF_INIT_FAILED, "syntactic only"],
  ]) {
    const tree = Pet.scanHistoryRows([row]);
    assert.equal(
      findEl(tree, (el) => hasClass("ok")(el) && el.textContent === "safe"),
      null,
      `${row.event_type} must not wear the green 'safe' badge`
    );
    const badge = findEl(tree, (el) => el.textContent === label);
    assert.ok(badge, `${label} badge present`);
    assert.ok(hasClass("warn")(badge), `${label} rides the amber warn class`);
    assert.ok(!hasClass("err")(badge), `${label} is not red: it blocks nothing`);
    assert.equal(
      findEl(tree, (el) => el.textContent === "blocked"),
      null,
      "a marker is never rendered as a block"
    );
    const enfPill = findEl(tree, hasClass("blue"));
    assert.ok(enfPill && enfPill.textContent === "enf", "enf source pill present");
  }
});

// ── b. provenance ───────────────────────────────────────────────────────────

test("cold-start provenance states coverage, never 'unknown'", () => {
  const degraded = text(Pet.scanDetailPanel(ENF_DEGRADED));
  assert.ok(
    degraded.includes("scan ran: partial (syntactic scan only; ML scanners still starting)"),
    "cold_start_degraded states partial coverage"
  );
  assert.ok(!degraded.includes("scan ran: unknown"), "never falls through to 'unknown'");

  const failed = text(Pet.scanDetailPanel(ENF_INIT_FAILED));
  assert.ok(
    failed.includes("scan ran: partial (syntactic scan only; ML scanners unavailable)"),
    "init_failed states the partial coverage the session actually got"
  );
  assert.ok(!failed.includes("scan ran: unknown"), "never falls through to 'unknown'");
});

// ── c. drill-down body ──────────────────────────────────────────────────────

test("cold-start detail renders the reason, not the unknown-row fallback", () => {
  for (const row of [ENF_DEGRADED, ENF_INIT_FAILED]) {
    const t = text(Pet.scanDetailPanel(row));
    assert.ok(!t.includes("Unknown row kind"), `${row.event_type} must not hit the unknown branch`);
    assert.ok(t.includes(row.reason), "reason rendered (it carries the whole payload)");
    assert.ok(t.includes(row.tool), "tool rendered");
    assert.ok(t.includes(row.session_id), "session rendered");
  }
  assert.ok(
    text(Pet.scanDetailPanel(ENF_DEGRADED)).includes("fast pattern scan only"),
    "degraded explainer rendered"
  );
  assert.ok(
    text(Pet.scanDetailPanel(ENF_INIT_FAILED)).includes(
      "Scanner startup failed permanently: this session runs on the fast pattern scan only."
    ),
    "init_failed explainer rendered"
  );
});

// ── d. robustness ───────────────────────────────────────────────────────────

test("cold-start row/detail never throw on missing fields; no 'undefined' text", () => {
  const bare = { source: "enforcement", event_type: "init_failed", scan_id: "e-cs3" };
  assert.doesNotThrow(() => Pet.scanHistoryRows([bare]));
  assert.doesNotThrow(() => Pet.scanDetailPanel(bare));
  const t = text(Pet.scanDetailPanel(bare)) + text(Pet.scanHistoryRows([bare]));
  assert.ok(!/undefined/.test(t), "absent fields show the no-data glyph, never 'undefined'");
  assert.ok(t.includes("—"), "absent fields render the no-data glyph");
});

// ── e. house style ──────────────────────────────────────────────────────────

test("cold-start labels carry no banned dash (em / en / double-hyphen)", () => {
  // Fully-populated rows only: the no-data glyph is a legitimate "—" and is exercised
  // by the bare-row case above.
  const t =
    text(Pet.scanHistoryRows([ENF_DEGRADED, ENF_INIT_FAILED])) +
    text(Pet.scanDetailPanel(ENF_DEGRADED)) +
    text(Pet.scanDetailPanel(ENF_INIT_FAILED));
  assert.ok(!t.includes("—"), "no em dash in labels");
  assert.ok(!t.includes("–"), "no en dash in labels");
  assert.ok(!t.includes("--"), "no double-hyphen in labels");
});
