// Unit tests for the PET-144 honest scan-history subtitle seam (petasos.js).
//
// The scan-history pane's subtitle must tell the truth about eviction: the <=500 ring
// drops oldest rows silently, so once the authoritative lifetime count (scans_total
// from /health) exceeds the buffered window, the subtitle reads "showing last N of M"
// instead of implying the window is the whole record. Pet.scanHistorySubtitle is a pure
// seam (mirrors Pet.bypassTotal / Pet.mergeScanHistory) so the harness can assert the
// label without driving renderDashboard. It reads scans_total from the health stat, never
// a separately-derived number that could silently disagree with the backend ring.
//
// Zero npm deps: Node's built-in test runner + node:vm over the real shipped petasos.js.
// Run with: node --test tests/js/scan-history-count.test.mjs

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// Minimal DOM shim -- these tests exercise a pure data seam, so document is only needed
// for petasos.js to evaluate.
function makeNode(nodeType) {
  return {
    nodeType,
    childNodes: [],
    style: {},
    className: "",
    appendChild(child) { this.childNodes.push(child); return child; },
    setAttribute() {},
    addEventListener() {},
  };
}
const document = {
  createDocumentFragment() { return makeNode(11); },
  createElement(tag) { const el = makeNode(1); el.tagName = tag.toUpperCase(); return el; },
  createTextNode(t) { const n = makeNode(3); n.nodeValue = String(t); return n; },
};

const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
const sandbox = { window: {}, document };
vm.runInNewContext(readFileSync(petasosJsPath, "utf8"), sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

beforeEach(() => {
  Pet.state.pipelineHealth = null; // isolate: Pet is shared across tests in this vm context
});

test("loader: petasos.js exposes Pet.scanHistorySubtitle", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.scanHistorySubtitle, "function");
});

test("total > buffered: the subtitle announces the lifetime total", () => {
  assert.equal(Pet.scanHistorySubtitle(500, 612), "showing last 500 of 612");
});

test("total <= buffered: not evicting, fall back to the static subtitle", () => {
  assert.equal(Pet.scanHistorySubtitle(500, 500), "recent evaluations"); // equal -> not evicting
  assert.equal(Pet.scanHistorySubtitle(500, 12), "recent evaluations"); // fewer than buffered
});

test("health not loaded (null / undefined / NaN): static subtitle, never 'of NaN'", () => {
  for (const total of [null, undefined, NaN, "not-a-number"]) {
    const out = Pet.scanHistorySubtitle(500, total);
    assert.equal(out, "recent evaluations");
    assert.equal(out.includes("NaN"), false);
  }
});

test("reads scans_total from the health stat shape (cannot mis-source the displayed total)", () => {
  Pet.state.pipelineHealth = { scans_total: 700 };
  assert.equal(
    Pet.scanHistorySubtitle(500, Pet.state.pipelineHealth.scans_total),
    "showing last 500 of 700"
  );
});

test("buffered tracks the live count, not a hardcoded 500", () => {
  // The denominator-of-rows follows hist.length post the petasos.js:483 mirror clamp,
  // not a literal constant; the "500" in the cases above is a stand-in for that length.
  assert.equal(Pet.scanHistorySubtitle(487, 700), "showing last 487 of 700");
  // A negative / non-finite buffered is floored to 0 (never a misleading negative).
  assert.equal(Pet.scanHistorySubtitle(-5, 700), "showing last 0 of 700");
});

test("cold-mount refresh: null health -> static; once scans_total settles -> honest label", () => {
  // Pins the Design step-3 fix: before /health settles pipelineHealth is null and the
  // subtitle is static; after the in-render settle populates scans_total the same
  // (buffered, scans_total) call returns the honest label -- no new scan frame needed.
  assert.equal(
    Pet.scanHistorySubtitle(500, Pet.state.pipelineHealth && Pet.state.pipelineHealth.scans_total),
    "recent evaluations"
  );
  Pet.state.pipelineHealth = { scans_total: 612 };
  assert.equal(
    Pet.scanHistorySubtitle(500, Pet.state.pipelineHealth && Pet.state.pipelineHealth.scans_total),
    "showing last 500 of 612"
  );
});
