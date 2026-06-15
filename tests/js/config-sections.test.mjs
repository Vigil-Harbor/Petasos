// Unit tests for PET-114 — collapsible, grouped config sections.
//
// Covers the three new JS surfaces in petasos/console/static/petasos.js:
//   1. Pet.groupConfigSections(fields, sections) — pure registry-driven grouper
//      (order, labels, skip-empty, unknown-section trailing group, stale-backend
//      fallback, empty input).
//   2. Pet.Panel collapsible support — chevron + role/tabIndex/aria-expanded,
//      click/Enter/Space toggle (live-DOM mutation), petSetCollapsed handle.
//   3. Pet.revealFieldSections — expands the owning section of an errored field.
//
// Collapse is the project's first *interactive* JS unit under test, so this file
// ships its OWN extended DOM shim: the scanner-health `makeNode` has no
// addEventListener/setAttribute/dataset/createElementNS. Here addEventListener
// records handlers into a per-node map that a `fire()` helper invokes, and
// setAttribute writes into a `node.attributes` object the assertions read.
//
// Zero npm dependencies: Node's built-in test runner + assert + node:vm,
// evaluating the real shipped petasos.js. Run with:
//   node --test tests/js/config-sections.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
// Legacy (non-strict) assert: its deepEqual ignores object prototypes. Values
// returned from the node:vm sandbox carry the sandbox realm's Object/Array
// prototypes, so assert/strict's prototype-checking deepStrictEqual rejects them
// even when structurally identical. Structural comparisons use this; primitive
// comparisons keep the strict `assert`.
import assertLoose from "node:assert";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── Extended interactive DOM shim ──────────────────────────────────────────
function makeNode(nodeType) {
  return {
    nodeType, // 1 = element, 3 = text, 11 = fragment
    childNodes: [],
    style: {},
    dataset: {},
    attributes: {},
    handlers: {},
    className: "",
    title: "",
    tabIndex: undefined,
    appendChild(child) {
      this.childNodes.push(child);
      return child;
    },
    setAttribute(k, v) {
      this.attributes[k] = String(v);
    },
    getAttribute(k) {
      return Object.prototype.hasOwnProperty.call(this.attributes, k) ? this.attributes[k] : null;
    },
    addEventListener(type, fn) {
      (this.handlers[type] = this.handlers[type] || []).push(fn);
    },
    get textContent() {
      if (this.nodeType === 3) return this.nodeValue;
      return this.childNodes.map((c) => c.textContent).join("");
    },
    set textContent(v) {
      // Permissive (unlike scanner-health's throwing setter): replace children
      // with a single text node so the getter stays consistent.
      const t = makeNode(3);
      t.nodeValue = String(v);
      this.childNodes = [t];
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
  createElementNS(ns, tag) {
    const el = makeNode(1);
    el.tagName = tag.toUpperCase();
    el.localName = tag;
    el.namespaceURI = ns;
    return el;
  },
  createTextNode(t) {
    const node = makeNode(3);
    node.nodeValue = String(t);
    return node;
  },
};

// ── Load the real petasos.js under a sandbox ───────────────────────────────
const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
const src = readFileSync(petasosJsPath, "utf8");

const sandbox = { window: {}, document };
vm.runInNewContext(src, sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

// ── Helpers ────────────────────────────────────────────────────────────────
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

const hasClass = (el, c) => (el.className || "").split(/\s+/).includes(c);

function fire(node, type, evt) {
  const hs = (node.handlers && node.handlers[type]) || [];
  hs.forEach((fn) => fn(evt || { preventDefault() {} }));
}

// Build a collapsible panel and surface its head + an onToggle spy.
function collapsiblePanel(collapsed) {
  const calls = [];
  const panel = Pet.Panel({
    icon: "sliders",
    title: "T",
    collapsible: true,
    collapsed: collapsed,
    onToggle: function (c) {
      calls.push(c);
    },
    content: Pet.h("div", {}, "body"),
  });
  const head = panel.childNodes[0];
  return { panel, head, calls };
}

// Registry + fields fixtures for the grouper.
function registry() {
  // Deliberately NOT in array order — the grouper must sort on `order`.
  return [
    { key: "alerting", label: "Alerting", default_collapsed: true, order: 9 },
    { key: "profiles", label: "Profiles", default_collapsed: false, order: 0 },
    { key: "scanning", label: "Scanning", default_collapsed: false, order: 4 },
  ];
}
function scrambledFields() {
  return [
    { name: "a1", section: "alerting" },
    { name: "p1", section: "profiles" },
    { name: "a2", section: "alerting" },
    { name: "s1", section: "scanning" },
  ];
}

// ── Loader guard ─────────────────────────────────────────────────────────────
test("loader: petasos.js exports the PET-114 surfaces", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.groupConfigSections, "function");
  assert.equal(typeof Pet.revealFieldSections, "function");
  assert.equal(typeof Pet.Panel, "function");
});

// ── groupConfigSections ──────────────────────────────────────────────────────
test("groupConfigSections: registry order + labels + booleans", () => {
  const groups = Pet.groupConfigSections(scrambledFields(), registry());
  assertLoose.deepEqual(
    groups.map((g) => g.key),
    ["profiles", "scanning", "alerting"]
  );
  assertLoose.deepEqual(
    groups.map((g) => g.label),
    ["Profiles", "Scanning", "Alerting"]
  );
  assertLoose.deepEqual(
    groups.map((g) => g.default_collapsed),
    [false, false, true]
  );
  // Field order preserved within a group.
  assertLoose.deepEqual(
    groups.find((g) => g.key === "alerting").fields.map((f) => f.name),
    ["a1", "a2"]
  );
});

test("groupConfigSections: default_collapsed is coerced to a real boolean", () => {
  const groups = Pet.groupConfigSections(
    [{ name: "p1", section: "profiles" }],
    [{ key: "profiles", label: "Profiles", default_collapsed: 1, order: 0 }]
  );
  assert.equal(groups[0].default_collapsed, true);
  assert.equal(typeof groups[0].default_collapsed, "boolean");
});

test("groupConfigSections: skips registry sections with no fields", () => {
  const reg = registry().concat([
    { key: "session", label: "Session", default_collapsed: true, order: 10 },
  ]);
  const groups = Pet.groupConfigSections(scrambledFields(), reg);
  assert.ok(!groups.some((g) => g.key === "session"), "empty registry section must be skipped");
});

test("groupConfigSections: unknown-section field is a trailing expanded group", () => {
  const fields = scrambledFields().concat([{ name: "x1", section: "future_thing" }]);
  const groups = Pet.groupConfigSections(fields, registry());
  const last = groups[groups.length - 1];
  assert.equal(last.key, "future_thing");
  assert.equal(last.label, "future_thing"); // label === key
  assert.equal(last.default_collapsed, false); // expanded — never dropped
  assertLoose.deepEqual(last.fields.map((f) => f.name), ["x1"]);
});

test("groupConfigSections: stale-backend fallback (no sections)", () => {
  for (const stale of [null, undefined, [], "nope", 7]) {
    const groups = Pet.groupConfigSections(scrambledFields(), stale);
    // Field first-appearance order: alerting (a1), profiles (p1), scanning (s1).
    assertLoose.deepEqual(
      groups.map((g) => g.key),
      ["alerting", "profiles", "scanning"]
    );
    assert.ok(groups.every((g) => g.label === g.key && g.default_collapsed === false));
  }
});

test("groupConfigSections: empty/non-array fields return []", () => {
  assertLoose.deepEqual(Pet.groupConfigSections([], registry()), []);
  assertLoose.deepEqual(Pet.groupConfigSections(null, registry()), []);
  assertLoose.deepEqual(Pet.groupConfigSections(undefined, registry()), []);
  // Empty fields + a registry that matches nothing still collapses to [] —
  // drives the renderConfig empty-guard.
  assertLoose.deepEqual(
    Pet.groupConfigSections([], [{ key: "nomatch", label: "x", default_collapsed: false, order: 0 }]),
    []
  );
});

// ── Pet.Panel collapsible ────────────────────────────────────────────────────
test("Pet.Panel collapsible: structure (collapsed)", () => {
  const { panel, head } = collapsiblePanel(true);
  assert.ok(findEl(head, (el) => hasClass(el, "chevron")), "chevron rendered");
  assert.ok(hasClass(head, "collapsible"), "head has collapsible class");
  assert.equal(head.getAttribute("role"), "button");
  assert.equal(head.tabIndex, 0);
  assert.equal(head.getAttribute("aria-expanded"), "false");
  // The panel `collapsed` class is the body-hidden observable (no CSS engine).
  assert.ok(hasClass(panel, "collapsed"), "panel carries collapsed class");
});

test("Pet.Panel collapsible: structure (expanded)", () => {
  const { panel, head } = collapsiblePanel(false);
  assert.equal(head.getAttribute("aria-expanded"), "true");
  assert.ok(!hasClass(panel, "collapsed"), "expanded panel lacks collapsed class");
});

test("Pet.Panel collapsible: click toggles live state + aria + onToggle", () => {
  const { panel, head, calls } = collapsiblePanel(false);
  fire(head, "click");
  assert.ok(hasClass(panel, "collapsed"));
  assert.equal(head.getAttribute("aria-expanded"), "false");
  assertLoose.deepEqual(calls, [true]);
  fire(head, "click");
  assert.ok(!hasClass(panel, "collapsed"));
  assert.equal(head.getAttribute("aria-expanded"), "true");
  assertLoose.deepEqual(calls, [true, false]);
});

test("Pet.Panel collapsible: Enter key toggles", () => {
  const { panel, head, calls } = collapsiblePanel(false);
  let prevented = false;
  fire(head, "keydown", { key: "Enter", preventDefault() { prevented = true; } });
  assert.ok(prevented, "Enter calls preventDefault");
  assert.ok(hasClass(panel, "collapsed"));
  assert.equal(head.getAttribute("aria-expanded"), "false");
  assertLoose.deepEqual(calls, [true]);
});

test("Pet.Panel collapsible: Space key toggles", () => {
  const { panel, head, calls } = collapsiblePanel(false);
  let prevented = false;
  fire(head, "keydown", { key: " ", preventDefault() { prevented = true; } });
  assert.ok(prevented, "Space calls preventDefault");
  assert.ok(hasClass(panel, "collapsed"));
  assertLoose.deepEqual(calls, [true]);
});

test("Pet.Panel collapsible: other keys do not toggle", () => {
  const { panel, head, calls } = collapsiblePanel(false);
  fire(head, "keydown", { key: "Tab", preventDefault() {} });
  assert.ok(!hasClass(panel, "collapsed"));
  assertLoose.deepEqual(calls, []);
});

test("Pet.Panel collapsible: petSetCollapsed expands without firing onToggle", () => {
  const { panel, head, calls } = collapsiblePanel(true);
  assert.equal(typeof panel.petSetCollapsed, "function");
  panel.petSetCollapsed(false);
  assert.ok(!hasClass(panel, "collapsed"), "collapsed class removed");
  assert.equal(head.getAttribute("aria-expanded"), "true");
  assertLoose.deepEqual(calls, [], "programmatic expand must NOT fire onToggle");
});

test("Pet.Panel non-collapsible: unchanged (regression guard)", () => {
  const panel = Pet.Panel({ icon: "sliders", title: "x", content: Pet.h("div", {}, "y") });
  const head = panel.childNodes[0];
  assert.equal(head.className, "panel-head");
  assert.ok(!findEl(head, (el) => hasClass(el, "chevron")), "no chevron");
  assert.equal(head.getAttribute("role"), null);
  assert.equal(head.getAttribute("aria-expanded"), null);
  assert.ok(!head.handlers.click, "no click handler");
  assert.ok(!head.handlers.keydown, "no keydown handler");
  assert.equal(typeof panel.petSetCollapsed, "undefined");
});

// ── revealFieldSections ──────────────────────────────────────────────────────
test("revealFieldSections: expands the owning section of an errored field", () => {
  let calledWith = "UNSET";
  const panelsBySection = {
    escalation: { petSetCollapsed(c) { calledWith = c; } },
  };
  const fieldSection = { tier2_threshold: "escalation" };
  Pet.state.sectionCollapsed = {};
  const revealed = Pet.revealFieldSections(["tier2_threshold"], fieldSection, panelsBySection);
  assert.equal(calledWith, false, "petSetCollapsed(false) called");
  assert.equal(Pet.state.sectionCollapsed.escalation, false, "choice persisted");
  assertLoose.deepEqual(revealed, { escalation: true });
});

test("revealFieldSections: unknown / missing-panel field is a safe no-op", () => {
  Pet.state.sectionCollapsed = {};
  assert.doesNotThrow(() => Pet.revealFieldSections(["nope"], {}, {}));
  assertLoose.deepEqual(Pet.revealFieldSections(["nope"], {}, {}), {});
  // Null error list is also safe.
  assertLoose.deepEqual(Pet.revealFieldSections(null, {}, {}), {});
  // A field whose section has no panel entry: no throw, nothing revealed.
  assertLoose.deepEqual(
    Pet.revealFieldSections(["f"], { f: "missing_section" }, {}),
    {}
  );
});

// ── PET-123: section intro copy carried builder -> render ────────────────────
// The bug class is "registry copy that exists end-to-end but is dropped at the
// last frontend hop". These pin the carry (builder), the graceful-degradation
// sentinel, and the Pet.sectionIntro builder (trim + never-throw).

// Dedicated loader sibling (keeps the PET-114 loader test name accurate).
test("loader: petasos.js exports the PET-123 surface (sectionIntro)", () => {
  assert.equal(typeof Pet.sectionIntro, "function");
});

// A registry carrying distinct, non-empty descriptions, in scrambled `order`.
function registryWithDescriptions() {
  return [
    { key: "alerting", label: "Alerting", description: "alerting intro copy", default_collapsed: true, order: 9 },
    { key: "profiles", label: "Profiles", description: "profiles intro copy", default_collapsed: false, order: 0 },
    { key: "scanning", label: "Scanning", description: "scanning intro copy", default_collapsed: false, order: 4 },
  ];
}

test("groupConfigSections: carries each registry description onto its group (PET-123)", () => {
  const groups = Pet.groupConfigSections(scrambledFields(), registryWithDescriptions());
  // Order still by `order` — the carry is additive, ordering untouched.
  assertLoose.deepEqual(
    groups.map((g) => g.key),
    ["profiles", "scanning", "alerting"]
  );
  // Every emitted group's description equals its registry entry's description.
  assertLoose.deepEqual(
    groups.map((g) => g.description),
    ["profiles intro copy", "scanning intro copy", "alerting intro copy"]
  );
});

test("groupConfigSections: fallback groups carry description === \"\" (PET-123)", () => {
  // Stale backend (null / []) — every trailing group gets the never-undefined "".
  // strict assert.equal rejects undefined, so this pins strictly "".
  for (const stale of [null, []]) {
    const groups = Pet.groupConfigSections(scrambledFields(), stale);
    assert.ok(groups.length > 0);
    for (const g of groups) {
      assert.equal(g.description, "", "stale-backend group description is strictly \"\"");
    }
  }
  // Unknown-section field (no registry entry) — trailing group also gets "".
  const fields = scrambledFields().concat([{ name: "x1", section: "future_thing" }]);
  const groups = Pet.groupConfigSections(fields, registryWithDescriptions());
  const last = groups[groups.length - 1];
  assert.equal(last.key, "future_thing");
  assert.equal(last.description, "", "unknown-section group description is strictly \"\"");
});

test("sectionIntro: renders a node whose textContent is the trimmed copy (PET-123)", () => {
  // Deliberate leading/trailing whitespace — pins that the builder trims, not
  // just that it renders clean input.
  const node = Pet.sectionIntro("  Clean up disguised text before scanning.  ");
  assert.ok(node, "intro node is truthy");
  assert.equal(node.nodeType, 1, "intro is an element node");
  assert.equal(node.textContent, "Clean up disguised text before scanning.");
});

test("sectionIntro: blank / non-string copy degrades to null, never throws (PET-123)", () => {
  // Empty, whitespace-only, null, undefined, plus non-strings (number + the two
  // collection types) so the test reads as obviously type-class-total.
  for (const bad of ["", "   ", null, undefined, 42, [], {}]) {
    let out = "UNSET";
    assert.doesNotThrow(() => {
      out = Pet.sectionIntro(bad);
    });
    assert.equal(out, null, `sectionIntro(${JSON.stringify(bad)}) returns null`);
  }
});
