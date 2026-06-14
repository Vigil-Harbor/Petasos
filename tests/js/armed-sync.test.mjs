// Unit tests for the `armed` arm of Pet.sse._dispatch (petasos/console/static/petasos.js).
//
// Regression for PET-116: live cross-tab sync of the Equipped/Unequipped bit.
// When one `obs` tab flips the master switch (POST /api/armed succeeds), the
// backend broadcasts an `armed` SSE frame; every other open tab's _dispatch
// adopts the authoritative pushed value into Pet.state.armed. This file pins:
//   1. State adoption — a valid boolean frame mutates Pet.state.armed.
//   2. Never-throw — a malformed frame (null / number / array / non-bool /
//      invalid JSON) is ignored, does not enter Pet.state.armed, and does not
//      throw (the cross-tab _dispatch runs renderDashboard synchronously, so a
//      throw would abort a live re-render in another tab — PET-99 posture).
//
// The re-render half is `_container`-guarded; `_container` is null in a headless
// load, so no real DOM is exercised here (the visual repaint and the in-flight
// `_armedBusy` guard stay in the spec's manual verification — `_armedBusy` is
// module-private and only set by a real in-flight doToggle).
//
// Zero npm dependencies: Node's built-in test runner + assert, a minimal DOM
// shim (same shape as scanner-health.test.mjs), and node:vm to evaluate the real
// shipped petasos.js. Run with:
//   node --test tests/js/armed-sync.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── Minimal DOM shim ────────────────────────────────────────────────────────
// The armed arm needs no real DOM (its re-render is _container-guarded and
// _container is null headlessly), but loading petasos.js under vm requires
// `document` to exist. Mirror the scanner-health shim shape.
function makeNode(nodeType) {
  return {
    nodeType,
    childNodes: [],
    style: {},
    className: "",
    title: "",
    appendChild(child) {
      this.childNodes.push(child);
      return child;
    },
    get textContent() {
      if (this.nodeType === 3) return this.nodeValue;
      return this.childNodes.map((c) => c.textContent).join("");
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

// ── Load the real petasos.js under a sandbox ────────────────────────────────
const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
const src = readFileSync(petasosJsPath, "utf8");

const sandbox = { window: {}, document };
vm.runInNewContext(src, sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

// ── Tests ───────────────────────────────────────────────────────────────────

// Guards that the export ran and the _dispatch seam is present.
test("loader: petasos.js exports Pet.sse._dispatch", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.sse, "object");
  assert.equal(typeof Pet.sse._dispatch, "function");
});

// Done-when 1 (state-adoption half): a valid boolean frame is adopted into
// Pet.state.armed, in both directions.
test("test_armed_adopts_valid_boolean", () => {
  Pet.state.armed = true;
  Pet.sse._dispatch("armed", JSON.stringify({ armed: false }));
  assert.equal(Pet.state.armed, false, "armed:false frame should set state to false");

  Pet.state.armed = false;
  Pet.sse._dispatch("armed", JSON.stringify({ armed: true }));
  assert.equal(Pet.state.armed, true, "armed:true frame should set state to true");
});

// Done-when 4: malformed frames never enter Pet.state.armed and never throw.
// Vectors: JSON null, a number, an array, an empty object (missing `armed`), a
// string-valued `armed`, a null-valued `armed` (the NaN-ish case — NaN cannot
// survive a JSON round-trip, it serializes to null), and a non-JSON string.
test("test_armed_ignores_malformed_frames_and_never_throws", () => {
  const badFrames = [
    "null",
    "5",
    "[]",
    "{}",
    JSON.stringify({ armed: "no" }),
    JSON.stringify({ armed: null }),
    "not json",
  ];
  for (const bad of badFrames) {
    Pet.state.armed = true;
    assert.doesNotThrow(
      () => Pet.sse._dispatch("armed", bad),
      `_dispatch threw on malformed frame: ${bad}`
    );
    assert.equal(
      Pet.state.armed,
      true,
      `malformed frame must not mutate Pet.state.armed: ${bad}`
    );
  }
});
