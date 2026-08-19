// PET-185: Pet.armScopeView — the ONE derivation of the arm control's scope state
// and the caption naming which binding the banner describes.
//
// Pure seam only (readScope in, plain object out); renderDashboard is never driven,
// per the harness rule in profile-scoped-reads.test.mjs. Assert via field-by-field
// comparison, never deepEqual on cross-realm objects.
//
// Zero npm deps: Node's built-in test runner + node:vm over the real shipped petasos.js.
// Run with: node --test tests/js/arm-scope-view.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

function makeNode(nodeType) {
  return {
    nodeType,
    childNodes: [],
    style: {},
    className: "",
    attrs: {},
    appendChild(child) { this.childNodes.push(child); return child; },
    setAttribute(k, v) { this.attrs[k] = v; },
    removeAttribute(k) { delete this.attrs[k]; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
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
const sandbox = {
  window: {}, document, console,
  setTimeout, clearTimeout, setInterval, clearInterval,
  AbortController, TextDecoder,
  fetch: function () { return new Promise(function () {}); },
};
vm.runInNewContext(readFileSync(petasosJsPath, "utf8"), sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

function view(rs) { return Pet.armScopeView(rs); }

test("null readScope: standalone path, all defaults", () => {
  for (const rs of [null, undefined]) {
    const v = view(rs);
    assert.equal(v.disabled, false);
    assert.equal(v.unscoped, false);
    assert.equal(v.notice, null);
  }
});

test("empty object: unscoped (the old equipped == null disjunct)", () => {
  const v = view({});
  assert.equal(v.disabled, false);
  assert.equal(v.unscoped, true);
  assert.notEqual(v.notice, null);
});

test("equipped with a named member: fully quiet", () => {
  // Full fixture on purpose: a bare {state:"equipped"} has equipped === undefined,
  // and undefined == null is true, so unscoped would fire. That combination is
  // server-unreachable (state "equipped" forces a non-null is_active member).
  const v = view({ state: "equipped", equipped: "alpha", selected: "alpha", equipped_tier: "profile" });
  assert.equal(v.disabled, false);
  assert.equal(v.unscoped, false);
  assert.equal(v.notice, null);
});

test("equipped with equipped:null stays unscoped BY DESIGN (D16 disjunct)", () => {
  // Pinned so nobody "repairs" a red bare-fixture test by short-circuiting on
  // st === "equipped", which would silently drop the equipped == null disjunct.
  const v = view({ state: "equipped", equipped: null });
  assert.equal(v.unscoped, true);
});

test("not_equipped with a named equipped profile: disabled, names whose state shows", () => {
  const v = view({ state: "not_equipped", equipped: "gibson", selected: "work" });
  assert.equal(v.disabled, true);
  assert.equal(v.unscoped, false);
  assert.ok(v.notice.includes("gibson"));
  assert.ok(v.notice.includes("work"));
  assert.ok(v.notice.includes("The banner above shows gibson's state, not work's."));
});

test("the live-box row: HERMES_HOME binding, named selection", () => {
  const v = view({ state: "not_equipped", equipped: null, equipped_tier: "hermes_home", selected: "gibson" });
  assert.equal(v.disabled, false);
  assert.equal(v.unscoped, true);
  assert.ok(v.notice.includes("HERMES_HOME"));
  assert.ok(v.notice.includes("gibson"));
  assert.ok(v.notice.includes("does not change gibson's enforcement"));
});

test("root tier gets the root label", () => {
  const v = view({ state: "not_equipped", equipped: null, equipped_tier: "root", selected: "gibson" });
  assert.ok(v.notice.includes("the root Hermes home"));
});

test("profile tier with equipped:null: no parenthetical, no self-reference", () => {
  // Reachable: an active_profile pointing at a directory with no config.yaml.
  const v = view({ state: "not_equipped", equipped: null, equipped_tier: "profile", selected: "gibson" });
  assert.equal(v.unscoped, true);
  assert.ok(!v.notice.includes("("));
  assert.ok(!v.notice.includes("this profile"));
});

test("equipped_tier absent entirely (stale or skewed backend): same shape", () => {
  const v = view({ state: "not_equipped", equipped: null, selected: "gibson" });
  assert.equal(v.unscoped, true);
  assert.ok(!v.notice.includes("("));
  assert.ok(!v.notice.includes("this profile"));
});

test("unknown wins over a non-null equipped name and refuses to vouch", () => {
  const v = view({ state: "unknown", equipped: "gibson", selected: "work", equipped_tier: "profile" });
  assert.equal(v.disabled, false);
  assert.equal(v.unscoped, true);
  assert.ok(v.notice.includes("fail-secure"));
  assert.ok(v.notice.includes("arming may not persist"));
  assert.ok(!v.notice.includes("both describe this dashboard's binding"));
  assert.ok(!v.notice.includes("(")); // no binding parenthetical in the unknown row
});

test("selected:null falls back to the generic phrase, never the string 'null'", () => {
  const v = view({ state: "not_equipped", equipped: null, equipped_tier: "hermes_home", selected: null });
  assert.ok(v.notice.includes("the selected profile"));
  assert.ok(!v.notice.includes("null"));
});

test("house style: no em dash in any caption string", () => {
  const fixtures = [
    { state: "not_equipped", equipped: "gibson", selected: "work" },
    { state: "not_equipped", equipped: null, equipped_tier: "hermes_home", selected: "gibson" },
    { state: "not_equipped", equipped: null, equipped_tier: "root", selected: "gibson" },
    { state: "unknown", equipped: "gibson", selected: "work" },
    {},
  ];
  for (const rs of fixtures) {
    const v = view(rs);
    if (v.notice != null) assert.ok(!v.notice.includes("—"), "em dash in: " + v.notice);
  }
});

test("term-by-term equivalence to the old inline booleans", () => {
  // Old: _armDisabled = st === "not_equipped" && equipped != null (over readScope || {});
  //      _armUnscoped = (readScope != null) && (st === "unknown" || equipped == null).
  const cases = [
    [null, false, false],
    [{}, false, true],
    [{ state: "equipped", equipped: "a", selected: "a", equipped_tier: "profile" }, false, false],
    [{ state: "equipped", equipped: null }, false, true],
    [{ state: "not_equipped", equipped: "a" }, true, false],
    [{ state: "not_equipped", equipped: null }, false, true],
    [{ state: "unknown", equipped: "a" }, false, true],
    [{ state: "unknown", equipped: null }, false, true],
  ];
  for (const [rs, disabled, unscoped] of cases) {
    const v = view(rs);
    assert.equal(v.disabled, disabled, "disabled for " + JSON.stringify(rs));
    assert.equal(v.unscoped, unscoped, "unscoped for " + JSON.stringify(rs));
  }
});
