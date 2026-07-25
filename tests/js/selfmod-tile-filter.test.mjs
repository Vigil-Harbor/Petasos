// Unit tests for the PET-165 self-tamper tile count and scan-history filter
// (petasos.js).
//
// The tile reads a SERVER-AUTHORITATIVE lifetime count (`/health`
// `pipeline.selfmod_total`), adopted through one seam and live-incremented over
// SSE, rather than being derived from the <=500-entry scanHistory ring. That is
// the whole point: a buffer-scoped tamper count decays to 0 once 500 ordinary
// scans evict the tamper rows, and the highest-stakes signal is precisely the
// one that must not decay silently.
//
// The filter is a pure client-side seam over the same buffer: it narrows
// RENDERED rows only, never the buffer and never a tile value, and it applies to
// the live head only (a filtered slice of one older page would read as the whole
// truth).
//
// Zero npm deps: Node's built-in test runner + a DOM shim + node:vm over the
// real shipped petasos.js. Run with: node --test tests/js/selfmod-tile-filter.test.mjs
//
// Harness pin (cross-realm trap): objects built inside the node:vm realm do NOT
// share this realm's Object.prototype, so assert.deepEqual(x, {}) fails on a
// Pet.state object even when it is empty. Assert emptiness via
// Object.keys(x).length instead.

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

// ── fixtures ────────────────────────────────────────────────────────────────
const selfmodRow = (scan_id, severity = "critical") => ({
  source: "enforcement",
  safe: true,
  event_type: "selfmod_attempt",
  tool: "write_file",
  rule_id: "petasos.selfmod.config_write",
  severity,
  session_id: "sess-sm",
  scan_id,
});
const scanRow = (scan_id) => ({ source: "playground", safe: true, direction: "inbound", scan_id });
const blockRow = (scan_id) => ({ source: "enforcement", safe: false, event_type: "block", scan_id });

function resetState() {
  Pet.state.selfmodTotal = 0;
  Pet.state.historyFilter = "all";
  Pet.state.historyAtHead = true;
  Pet.state.historyStack = [];
  Pet.state.scanHistory = [];
  Pet.state.bypassBySession = {};
}

// ── tile: adoption from /health ─────────────────────────────────────────────

test("adoptSelfmodTotal: adopts a valid non-negative count", () => {
  resetState();
  Pet.adoptSelfmodTotal({ scans_total: 12, selfmod_total: 4 });
  assert.equal(Pet.state.selfmodTotal, 4);
  Pet.adoptSelfmodTotal({ selfmod_total: 0 });
  assert.equal(Pet.state.selfmodTotal, 0, "an honest zero is adoptable, not treated as absent");
});

test("adoptSelfmodTotal: ignores missing / negative / non-numeric, never writes NaN", () => {
  // Leaving the current value is the honest failure mode: a health payload from an
  // older server (no such key) or a malformed one must not blank or NaN the tile.
  for (const pipeline of [
    undefined, null, {}, "nope", 7,
    { selfmod_total: undefined },
    { selfmod_total: null },
    { selfmod_total: -1 },
    { selfmod_total: NaN },
    { selfmod_total: Infinity },
    { selfmod_total: "5" },
    { selfmod_total: true },
    { selfmod_total: [5] },
  ]) {
    resetState();
    Pet.state.selfmodTotal = 3;
    assert.doesNotThrow(() => Pet.adoptSelfmodTotal(pipeline), `threw on ${JSON.stringify(pipeline)}`);
    assert.equal(Pet.state.selfmodTotal, 3, `${JSON.stringify(pipeline)} must leave the count alone`);
  }
});

test("adoptSelfmodTotal: a LOWER server value overwrites (console-restart semantics)", () => {
  // Deliberately overwrite, never monotonic-max. The counter is lifetime-since-console-
  // start, so a restarted console honestly resets its tile instead of showing a total
  // the running process cannot account for. The cost (a <=10s downward flicker when a
  // pre-event health snapshot lands after a client increment) self-heals on the next poll.
  resetState();
  Pet.state.selfmodTotal = 9;
  Pet.adoptSelfmodTotal({ selfmod_total: 1 });
  assert.equal(Pet.state.selfmodTotal, 1);
});

// ── tile: SSE increment + eviction independence ─────────────────────────────

const frame = (obj) => Pet.sse._dispatch("scan_result", JSON.stringify(obj));

test("SSE: a selfmod frame increments the tile; other frames do not", () => {
  resetState();
  frame(scanRow("p1"));
  frame(blockRow("b1"));
  assert.equal(Pet.state.selfmodTotal, 0, "ordinary and block frames leave the tile at zero");

  frame(selfmodRow("sm1"));
  assert.equal(Pet.state.selfmodTotal, 1);
  frame(selfmodRow("sm2", "high"));
  assert.equal(Pet.state.selfmodTotal, 2);
});

test("SSE: malformed frames never increment and never throw", () => {
  resetState();
  for (const raw of ["null", "3", '"selfmod_attempt"', "[]", "{oops", ""]) {
    assert.doesNotThrow(() => Pet.sse._dispatch("scan_result", raw), `threw on ${raw}`);
  }
  assert.equal(Pet.state.selfmodTotal, 0);
});

test("tile count survives ring eviction (the load-bearing PET-165 guarantee)", () => {
  // One tamper attempt, then enough ordinary scans to push it out of the 500-entry
  // buffer. The row is gone from the window; the count must not be.
  resetState();
  frame(selfmodRow("sm-evict"));
  for (let i = 0; i < 600; i++) frame(scanRow("p" + i));

  assert.equal(Pet.state.scanHistory.length, 500, "ring stays hard-capped");
  assert.equal(
    Pet.state.scanHistory.filter((e) => e.scan_id === "sm-evict").length,
    0,
    "precondition: the tamper row has been evicted from the live window"
  );
  assert.equal(Pet.state.selfmodTotal, 1, "the tile count must not decay with the buffer");
});

// ── filter seam ─────────────────────────────────────────────────────────────

test("filterHistoryRows: the selfmod filter keeps only selfmod rows", () => {
  const rows = [scanRow("p1"), selfmodRow("sm1"), blockRow("b1"), selfmodRow("sm2", "high")];
  const out = Pet.filterHistoryRows(rows, "selfmod");
  assert.equal(out.length, 2);
  // Cross-realm pin (same trap as deepEqual({}) on Pet.state): the array comes back with
  // the vm realm's Array.prototype, so deepStrictEqual against a host array fails on
  // reference-equal prototypes. Compare a primitive projection instead.
  assert.equal(out.map((e) => e.scan_id).join(","), "sm1,sm2");
  assert.equal(rows.length, 4, "the input buffer is never mutated");
});

test("filterHistoryRows: any non-selfmod filter returns the input unchanged", () => {
  // Same array reference, so the default path is byte-identical to pre-PET-165 rendering.
  const rows = [scanRow("p1"), selfmodRow("sm1")];
  for (const f of ["all", undefined, null, "", "SELFMOD", "bogus"]) {
    assert.equal(Pet.filterHistoryRows(rows, f), rows, `filter ${JSON.stringify(f)} must pass through`);
  }
});

test("filterHistoryRows: malformed entries are dropped, never thrown on", () => {
  const rows = [null, undefined, 3, "selfmod_attempt", [], selfmodRow("sm1")];
  let out;
  assert.doesNotThrow(() => { out = Pet.filterHistoryRows(rows, "selfmod"); });
  assert.equal(out.length, 1);
  assert.equal(out[0].scan_id, "sm1");

  for (const bad of [null, undefined, 42, "rows", {}]) {
    let r;
    assert.doesNotThrow(() => { r = Pet.filterHistoryRows(bad, "selfmod"); }, `threw on ${JSON.stringify(bad)}`);
    assert.equal(r.length, 0);
  }
});

test("filterHistoryRows: an empty buffer under the filter yields an empty result", () => {
  // Feeds the filtered-empty state ("No self-tamper events in the buffered window.")
  // rather than the "no scans yet" live-head copy.
  assert.equal(Pet.filterHistoryRows([], "selfmod").length, 0);
  assert.equal(Pet.filterHistoryRows([scanRow("p1")], "selfmod").length, 0);
});

// ── filter control ──────────────────────────────────────────────────────────

test("setHistoryFilter: toggles state and never touches tile values or the buffer", () => {
  resetState();
  Pet.state.selfmodTotal = 5;
  Pet.state.bypassBySession = { s: 2 };
  Pet.state.scanHistory = [scanRow("p1"), selfmodRow("sm1")];

  Pet.setHistoryFilter("selfmod");
  assert.equal(Pet.state.historyFilter, "selfmod");
  Pet.setHistoryFilter("all");
  assert.equal(Pet.state.historyFilter, "all");
  Pet.setHistoryFilter("nonsense");
  assert.equal(Pet.state.historyFilter, "all", "an unknown filter value normalizes to 'all'");

  assert.equal(Pet.state.selfmodTotal, 5, "filtering never changes a tile value");
  assert.equal(Pet.bypassTotal(), 2, "filtering never changes a tile value");
  assert.equal(Pet.state.scanHistory.length, 2, "filtering never changes the buffer");
});

test("setHistoryFilter: activating the filter from a paged view snaps back to the head", () => {
  // The filter is a live-head view. Filtering a single older page would present "the
  // self-tamper events in this page" as "the self-tamper events"; paged views therefore
  // always render unfiltered, and activating the filter returns to the head first.
  resetState();
  Pet.state.historyAtHead = false;
  Pet.state.historyStack = [{ entries: [scanRow("old1")], nextBefore: "cur-1" }];

  Pet.setHistoryFilter("selfmod");
  assert.equal(Pet.state.historyFilter, "selfmod");
  assert.equal(Pet.state.historyAtHead, true, "snapped back to the live head");
  assert.equal(Pet.state.historyStack.length, 0, "paged stack cleared by the head transition");
  // Harness pin: cross-realm prototypes break deepEqual({}) on vm-realm objects.
  assert.equal(Object.keys(Pet.state.bypassBySession).length, 0);
});

test("setHistoryFilter: re-selecting an already-active filter still snaps to head", () => {
  // Reachable state: filter, then page back (paged views render unfiltered). Clicking the
  // already-lit chip must do the honest thing rather than no-op into a lying control.
  resetState();
  Pet.state.historyFilter = "selfmod";
  Pet.state.historyAtHead = false;
  Pet.state.historyStack = [{ entries: [], nextBefore: null }];

  Pet.setHistoryFilter("selfmod");
  assert.equal(Pet.state.historyAtHead, true);
  assert.equal(Pet.state.historyStack.length, 0);
});

test("setHistoryFilter: selecting 'all' from a paged view leaves the page alone", () => {
  resetState();
  Pet.state.historyFilter = "selfmod";
  Pet.state.historyAtHead = false;
  Pet.state.historyStack = [{ entries: [scanRow("old1")], nextBefore: "cur-1" }];

  Pet.setHistoryFilter("all");
  assert.equal(Pet.state.historyFilter, "all");
  assert.equal(Pet.state.historyAtHead, false, "clearing the filter is not a navigation");
  assert.equal(Pet.state.historyStack.length, 1);
});

// ── house style ─────────────────────────────────────────────────────────────

test("PET-165 copy carries no em dash", () => {
  const src = readFileSync(petasosJsPath, "utf8");
  const selfmodCopy = src.match(/"[^"\n]*self-tamper[^"\n]*"/g) || [];
  assert.ok(selfmodCopy.length > 0, "expected self-tamper copy in the shipped console");
  for (const s of selfmodCopy) assert.ok(!s.includes("—"), `em dash in shipped copy: ${s}`);
});
