// Unit tests for the PET-138 disarmed-bypass counter surface (petasos.js).
//
// The "bypassed (disarmed)" tile must reflect an authoritative per-session count
// that survives buffer eviction. The count rides a single rate-limited
// bypassed_disarmed heartbeat row, so it is held in dedicated state
// (Pet.state.bypassBySession) via Pet.accrueBypass — NOT recomputed from the
// ≤500-entry scan-history buffer — and summed for the tile by Pet.bypassTotal.
// accrueBypass integer-gates the carried count (a non-integer / bool / null / zero
// contributes nothing) and keeps a monotonic max per session, bounded drop-oldest.
//
// Zero npm deps: Node's built-in test runner + node:vm over the real shipped
// petasos.js. Run with: node --test tests/js/disarm-bypass-counter.test.mjs

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// Minimal DOM shim — these tests exercise pure data seams (accrueBypass /
// bypassTotal), so document is only needed for petasos.js to evaluate.
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

const bypass = (session_id, bypassed_count) => ({
  source: "enforcement",
  event_type: "bypassed_disarmed",
  session_id,
  bypassed_count,
  scan_id: "e-" + session_id + "-" + String(bypassed_count),
});

beforeEach(() => {
  Pet.state.bypassBySession = {}; // isolate: Pet is shared across tests in this vm context
});

test("loader: petasos.js exposes accrueBypass + bypassTotal + bypassBySession state", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.accrueBypass, "function");
  assert.equal(typeof Pet.bypassTotal, "function");
  assert.equal(typeof Pet.state.bypassBySession, "object");
});

test("live frame with an integer count updates state and the tile total", () => {
  Pet.accrueBypass([bypass("s1", 3)]);
  assert.equal(Pet.state.bypassBySession.s1, 3);
  assert.equal(Pet.bypassTotal(), 3);
});

test("monotonic max: a later higher count raises it; a lower count does not lower it", () => {
  Pet.accrueBypass([bypass("s1", 3)]);
  Pet.accrueBypass([bypass("s1", 7)]); // higher -> adopt
  assert.equal(Pet.state.bypassBySession.s1, 7);
  Pet.accrueBypass([bypass("s1", 5)]); // re-surfaced lower -> ignored
  assert.equal(Pet.state.bypassBySession.s1, 7);
  assert.equal(Pet.bypassTotal(), 7);
});

test("seed path: an array of pre-existing rows populates state (mount seed, not a live frame)", () => {
  // Mirrors Pet.accrueBypass(d.entries) on the one-shot history seed.
  Pet.accrueBypass([bypass("s1", 2), bypass("s2", 5), { event_type: "block", session_id: "s3" }]);
  assert.equal(Pet.state.bypassBySession.s1, 2);
  assert.equal(Pet.state.bypassBySession.s2, 5);
  assert.equal("s3" in Pet.state.bypassBySession, false); // non-bypass row ignored
  assert.equal(Pet.bypassTotal(), 7); // summed across sessions
});

test("coercion: non-integer float / null / 'undefined' / missing / bool / zero / negative contribute 0", () => {
  Pet.accrueBypass([
    bypass("a", 3.7),
    bypass("b", null),
    bypass("c", "undefined"),
    bypass("d", undefined),
    bypass("e", true),
    bypass("f", 0),
    bypass("g", -4),
    { event_type: "bypassed_disarmed", session_id: "h" }, // no bypassed_count
  ]);
  assert.deepEqual(Pet.state.bypassBySession, {}); // nothing admitted
  assert.equal(Pet.bypassTotal(), 0);
  // The tile renders the integer 0 honestly (never the string "undefined").
  assert.equal(String(Pet.bypassTotal()), "0");
});

test("eviction-proof: the count persists in state independent of the scan-history buffer", () => {
  Pet.accrueBypass([bypass("s1", 4)]);
  // Simulate the source row aging out of the buffer (buffer cleared); state is not
  // recomputed from the buffer, so the tile total is unchanged.
  Pet.state.scanHistory = [];
  assert.equal(Pet.bypassTotal(), 4);
});

test("malformed input never throws and is skipped", () => {
  assert.doesNotThrow(() => Pet.accrueBypass(null));
  assert.doesNotThrow(() => Pet.accrueBypass(undefined));
  assert.doesNotThrow(() => Pet.accrueBypass([null, 42, "x", {}]));
  assert.equal(Pet.bypassTotal(), 0);
});

test("bounded drop-oldest: more than the cap distinct sessions stays bounded, oldest dropped", () => {
  const CAP = 10000; // mirrors _MAX_BYPASS_SESSIONS / server._MAX_TALLY_SESSIONS
  for (let i = 0; i <= CAP; i++) Pet.accrueBypass([bypass("s" + i, 1)]); // CAP+1 sessions
  const keys = Object.keys(Pet.state.bypassBySession);
  assert.equal(keys.length, CAP); // bounded
  assert.equal("s0" in Pet.state.bypassBySession, false); // genuine oldest evicted
  assert.equal(Pet.state.bypassBySession["s" + CAP], 1); // newest retained
});
