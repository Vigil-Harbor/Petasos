// Unit tests for PET-124 — the strength-preset "tuning dial".
//
// Covers the two new JS surfaces in petasos/console/static/petasos.js:
//   1. Pet.resolveActivePreset(configValues, presets) — pure JS mirror of the
//      Python comparator (exact match, owned-field edit → Custom, non-owned edit
//      ignored, numeric value-normalizing equality).
//   2. Pet.renderStrengthDial(presets, activeKey, onSelect) — segmented control:
//      one segment per preset + a Custom tail, active marking, never-throw
//      degradation on malformed shapes, and metal-click → apply path.
//
// Zero npm dependencies: Node's built-in test runner + assert + node:vm,
// evaluating the real shipped petasos.js. Run with:
//   node --test tests/js/preset-dial.test.mjs
//
// The DOM shim mirrors tests/js/config-sections.test.mjs (addEventListener /
// setAttribute / dataset support), since the dial renders interactive buttons
// and HelpTip tooltips.

import { test } from "node:test";
import assert from "node:assert/strict";
import assertLoose from "node:assert";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── Interactive DOM shim ────────────────────────────────────────────────────
function makeNode(nodeType) {
  return {
    nodeType,
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

// ── Load the real petasos.js under a sandbox ───────────────────────────────
const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
const src = readFileSync(petasosJsPath, "utf8");

const sandbox = { window: {}, document };
vm.runInNewContext(src, sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

// ── Helpers ──────────────────────────────────────────────────────────────────
function fire(node, type, evt) {
  const hs = (node.handlers && node.handlers[type]) || [];
  hs.forEach((fn) => fn(evt || { preventDefault() {} }));
}

const hasClass = (el, c) => (el.className || "").split(/\s+/).includes(c);

// Collect every element carrying a data-preset (the dial segments), depth-first.
function segments(node, acc) {
  acc = acc || [];
  for (const child of node.childNodes || []) {
    if (child.nodeType === 1) {
      if (child.dataset && child.dataset.preset != null) acc.push(child);
      segments(child, acc);
    }
  }
  return acc;
}

function segByKey(node, key) {
  return segments(node).find((s) => s.dataset.preset === key) || null;
}

// Preset fixtures. Deliberately NOT in `order` sequence — the dial must sort.
const IRON = {
  fail_mode: "degraded", tier1_threshold: 15, tier2_threshold: 30, tier3_threshold: 50,
  presidio_score_threshold: 0.35, anonymize: false, tool_guard_enabled: true,
  normalize_nfkc: true, strip_zero_width: true, map_homoglyphs: true,
  detect_rtl_override: true, fold_leet: true, decode_encoded_payloads: true,
};
const BRONZE = {
  fail_mode: "degraded", tier1_threshold: 25, tier2_threshold: 45, tier3_threshold: 65,
  presidio_score_threshold: 0.5, anonymize: false, tool_guard_enabled: true,
  normalize_nfkc: true, strip_zero_width: true, map_homoglyphs: true,
  detect_rtl_override: true, fold_leet: true, decode_encoded_payloads: true,
};
const TIN = {
  fail_mode: "open", tier1_threshold: 40, tier2_threshold: 60, tier3_threshold: 80,
  presidio_score_threshold: 0.6, anonymize: false, tool_guard_enabled: false,
  normalize_nfkc: true, strip_zero_width: true, map_homoglyphs: true,
  detect_rtl_override: false, fold_leet: false, decode_encoded_payloads: false,
};
function presets() {
  return [
    { key: "tin", label: "Tin", order: 0, description: "Loosest temper.", overrides: { ...TIN } },
    { key: "iron", label: "Iron", order: 2, description: "Default temper.", overrides: { ...IRON } },
    { key: "bronze", label: "Bronze", order: 1, description: "Relaxed temper.", overrides: { ...BRONZE } },
  ];
}

// ── Loader guard ─────────────────────────────────────────────────────────────
test("loader: petasos.js exports the PET-124 surfaces", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.resolveActivePreset, "function");
  assert.equal(typeof Pet.renderStrengthDial, "function");
});

// ── resolveActivePreset ──────────────────────────────────────────────────────
test("resolveActivePreset: exact match returns the preset key", () => {
  assert.equal(Pet.resolveActivePreset({ ...IRON }, presets()), "iron");
  assert.equal(Pet.resolveActivePreset({ ...BRONZE }, presets()), "bronze");
});

test("resolveActivePreset: an edited owned field flips to Custom (null)", () => {
  assert.equal(Pet.resolveActivePreset({ ...IRON, fail_mode: "open" }, presets()), null);
  assert.equal(Pet.resolveActivePreset({ ...IRON, tier1_threshold: 14 }, presets()), null);
});

test("resolveActivePreset: a non-owned field change does not flip the dial", () => {
  // The resolver only inspects each preset's override keys; extra keys are ignored.
  assert.equal(Pet.resolveActivePreset({ ...IRON, alert_per_minute_cap: 7 }, presets()), "iron");
});

test("resolveActivePreset: value-normalizing numeric equality (30 vs 30.0/'30')", () => {
  // Numeric owned fields compare as Number(a) === Number(b), so a JSON-sourced
  // integer or string still resolves to the float-literal preset.
  const asStrings = { ...IRON, tier1_threshold: "15", tier2_threshold: "30", tier3_threshold: "50" };
  assert.equal(Pet.resolveActivePreset(asStrings, presets()), "iron");
});

test("resolveActivePreset: degrades to null on malformed inputs", () => {
  assert.equal(Pet.resolveActivePreset({ ...IRON }, null), null);
  assert.equal(Pet.resolveActivePreset({ ...IRON }, []), null);
  assert.equal(Pet.resolveActivePreset(null, presets()), null);
  assert.equal(Pet.resolveActivePreset({}, presets()), null);
});

// ── renderStrengthDial ───────────────────────────────────────────────────────
test("renderStrengthDial: one segment per preset plus a Custom tail", () => {
  const dial = Pet.renderStrengthDial(presets(), "iron", function () {});
  const segs = segments(dial);
  // 3 metals + Custom.
  assert.equal(segs.length, 4);
  // Metals sorted by `order`: tin, bronze, iron — then custom last.
  assertLoose.deepEqual(
    segs.map((s) => s.dataset.preset),
    ["tin", "bronze", "iron", "custom"]
  );
});

test("renderStrengthDial: marks the active metal, Custom off", () => {
  const dial = Pet.renderStrengthDial(presets(), "iron", function () {});
  assert.ok(hasClass(segByKey(dial, "iron"), "on"), "iron is active");
  assert.ok(!hasClass(segByKey(dial, "bronze"), "on"), "bronze not active");
  assert.ok(!hasClass(segByKey(dial, "custom"), "on"), "custom not active");
});

test("renderStrengthDial: null/unknown active highlights Custom", () => {
  for (const key of [null, undefined, "nonexistent"]) {
    const dial = Pet.renderStrengthDial(presets(), key, function () {});
    assert.ok(hasClass(segByKey(dial, "custom"), "on"), "custom active when no metal matches");
    assert.ok(!hasClass(segByKey(dial, "iron"), "on"), "no metal active");
  }
});

test("renderStrengthDial: recommendation line names Iron + code_generation", () => {
  const dial = Pet.renderStrengthDial(presets(), "iron", function () {});
  const text = dial.textContent;
  assert.ok(text.includes("Iron"), "names Iron");
  assert.ok(text.includes("code_generation"), "names the code_generation profile");
});

test("renderStrengthDial: degrades without throwing on malformed shapes", () => {
  // Absent presets → renders nothing (no segments), no throw.
  assert.doesNotThrow(() => Pet.renderStrengthDial(undefined, "iron", function () {}));
  assert.equal(segments(Pet.renderStrengthDial(undefined, "iron", function () {})).length, 0);
  // Empty presets → nothing.
  assert.equal(segments(Pet.renderStrengthDial([], "iron", function () {})).length, 0);
  // active_preset null/absent with presets present → dial renders, no throw.
  assert.doesNotThrow(() => Pet.renderStrengthDial(presets(), null, function () {}));
  // A preset entry lacking `overrides` is skipped; valid ones still render.
  const withBad = presets().concat([{ key: "broken", label: "Broken", order: 9 }]);
  const dial = Pet.renderStrengthDial(withBad, "iron", function () {});
  assert.equal(segByKey(dial, "broken"), null, "malformed preset is skipped");
  // tin/bronze/iron + custom survive.
  assert.equal(segments(dial).length, 4);
});

test("renderStrengthDial: a metal click invokes the apply path with that preset's overrides", () => {
  let putBody = null;
  const originalPutConfig = Pet.api.putConfig;
  // Stub the apply path; record the PUT body the dial sends. Restored in finally
  // so the global mutation cannot leak into later tests.
  try {
    Pet.api.putConfig = function (body) {
      putBody = body;
      return { then: function () { return { then: function () {} }; } };
    };
    const onSelect = function (p) { Pet.api.putConfig(p.overrides); };
    const dial = Pet.renderStrengthDial(presets(), "iron", onSelect);

    fire(segByKey(dial, "bronze"), "click");
    assertLoose.deepEqual(putBody, BRONZE);
  } finally {
    Pet.api.putConfig = originalPutConfig;
  }
});

test("renderStrengthDial: the in-segment HelpTip swallows clicks (no preset apply)", () => {
  // Regression for PET-124 review (Major): the HelpTip lives inside the clickable
  // segment, so reading the tooltip must not bubble to onSelect. The fix registers
  // a click handler on the tip that stops propagation; assert it is present.
  const dial = Pet.renderStrengthDial(presets(), "iron", function () {});
  const ironSeg = segByKey(dial, "iron");
  const help = (function find(node) {
    for (const c of node.childNodes || []) {
      if (c.nodeType === 1) {
        if (hasClass(c, "help")) return c;
        const f = find(c);
        if (f) return f;
      }
    }
    return null;
  })(ironSeg);
  assert.ok(help, "metal segment carries a HelpTip");
  assert.ok(help.handlers.click && help.handlers.click.length > 0, "HelpTip has a click handler");
  // Firing the tip's click invokes its stopPropagation guard without throwing.
  let propagationStopped = false;
  assert.doesNotThrow(() =>
    fire(help, "click", { stopPropagation() { propagationStopped = true; } })
  );
  assert.ok(propagationStopped, "tip click calls stopPropagation");
});

test("renderStrengthDial: the Custom segment is not clickable (no onSelect)", () => {
  let called = false;
  const dial = Pet.renderStrengthDial(presets(), null, function () { called = true; });
  // Custom carries no click handler.
  const custom = segByKey(dial, "custom");
  assert.ok(!custom.handlers.click, "custom has no click handler");
  fire(custom, "click"); // no-op
  assert.equal(called, false);
});
