// Unit tests for PET-127 — skeleton loading primitive.
//
// Covers the two new pure builders in petasos/console/static/petasos.js plus the
// Pet.h aria passthrough that the loading wrappers depend on:
//   1. Pet.skel(w, h) — number->px / string-passthrough / default / finite-zero,
//      never-throws, aria-hidden (decorative).
//   2. Pet.skelRows(n, opts) — n bars in a column; n<1 / non-number -> 1 bar.
//   3. Pet.h ariaBusy / ariaHidden passthrough (Decision 3 regression guard) —
//      the loading semantic rides on role=status + aria-busy; this pins that the
//      two additive attrs reach the DOM and that a node setting neither stays clean.
//
// Mirrors the config-sections.test.mjs harness: zero npm deps, Node's built-in
// test runner + assert + node:vm evaluating the REAL shipped petasos.js, with a
// small DOM shim recording style/className/dataset and setAttribute into a
// readable `attributes` map. Run with:
//   node --test tests/js/skeleton.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── DOM shim (style / className / dataset / attributes) ─────────────────────
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

// ── Load the real petasos.js under a sandbox ────────────────────────────────
const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
const src = readFileSync(petasosJsPath, "utf8");

const sandbox = { window: {}, document };
vm.runInNewContext(src, sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

// element children of a node (skip text nodes)
const elementChildren = (node) => (node.childNodes || []).filter((c) => c.nodeType === 1);

// ── Loader guard ─────────────────────────────────────────────────────────────
test("loader: petasos.js exports the PET-127 surfaces", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.skel, "function");
  assert.equal(typeof Pet.skelRows, "function");
});

// ── Pet.skel ───────────────────────────────────────────────────────────────
test("Pet.skel(120, 16): numbers coerce to px; className is skel", () => {
  const n = Pet.skel(120, 16);
  assert.equal(n.nodeType, 1);
  assert.equal(n.className, "skel");
  assert.equal(n.style.width, "120px");
  assert.equal(n.style.height, "16px");
});

test("Pet.skel('80%', '1em'): string dims pass through unchanged", () => {
  const n = Pet.skel("80%", "1em");
  assert.equal(n.style.width, "80%");
  assert.equal(n.style.height, "1em");
});

test("Pet.skel(): bare call defaults to 100% x 12px, never throws", () => {
  let n;
  assert.doesNotThrow(() => { n = Pet.skel(); });
  assert.equal(n.style.width, "100%");
  assert.equal(n.style.height, "12px");
});

test("Pet.skel(NaN, {}) / (null, undefined): garbage args fall back to defaults, no throw", () => {
  for (const args of [[NaN, {}], [null, undefined], ["   ", "\t"]]) {
    let n;
    assert.doesNotThrow(() => { n = Pet.skel(args[0], args[1]); });
    assert.equal(n.style.width, "100%", `width default for ${JSON.stringify(args)}`);
    assert.equal(n.style.height, "12px", `height default for ${JSON.stringify(args)}`);
  }
});

test("Pet.skel(0, 0): finite zero is honored (pins the isFinite branch)", () => {
  const n = Pet.skel(0, 0);
  assert.equal(n.style.width, "0px");
  assert.equal(n.style.height, "0px");
});

test("Pet.skel(...): decorative -> aria-hidden='true'", () => {
  const n = Pet.skel(40, 10);
  assert.equal(n.getAttribute("aria-hidden"), "true");
});

// ── Pet.skelRows ─────────────────────────────────────────────────────────────
test("Pet.skelRows(3): returns a column of 3 skeleton bars", () => {
  const rows = Pet.skelRows(3);
  const bars = elementChildren(rows);
  assert.equal(bars.length, 3);
  assert.ok(bars.every((b) => b.className === "skel"), "every child is a .skel bar");
});

test("Pet.skelRows(0) / ('x') / (0.5): degrade to 1 bar, never throw (divergent from skel(0))", () => {
  // 0.5 is the regression guard: a positive fraction must NOT Math.floor to 0 bars.
  for (const bad of [0, "x", null, undefined, NaN, -4, 0.5]) {
    let rows;
    assert.doesNotThrow(() => { rows = Pet.skelRows(bad); });
    assert.equal(elementChildren(rows).length, 1, `skelRows(${JSON.stringify(bad)}) -> 1 bar`);
  }
});

test("Pet.skelRows(2, {h, gap}): opts.h sizes bars, opts.gap sets column gap", () => {
  const rows = Pet.skelRows(2, { h: "20px", gap: "10px" });
  assert.equal(rows.style.gap, "10px");
  const bars = elementChildren(rows);
  assert.equal(bars.length, 2);
  assert.ok(bars.every((b) => b.style.height === "20px"), "each bar honors opts.h");
});

// ── Pet.h aria passthrough (Decision 3 regression guard) ─────────────────────
test("Pet.h ariaBusy: maps to aria-busy attribute", () => {
  assert.equal(Pet.h("div", { ariaBusy: true }).getAttribute("aria-busy"), "true");
  assert.equal(Pet.h("div", { ariaBusy: false }).getAttribute("aria-busy"), "false");
});

test("Pet.h ariaHidden: maps to aria-hidden attribute", () => {
  assert.equal(Pet.h("div", { ariaHidden: true }).getAttribute("aria-hidden"), "true");
});

test("Pet.h: a node setting neither aria attr stays clean (behavior-preserving)", () => {
  const n = Pet.h("div", { className: "x" });
  assert.equal(n.getAttribute("aria-busy"), null);
  assert.equal(n.getAttribute("aria-hidden"), null);
});
