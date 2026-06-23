// Unit tests for PET-146 — the Config Editor Hermes-agent-profile selector.
//
// Covers the JS surfaces added to petasos/console/static/petasos.js:
//   1. Pet.hermesProfileOptions(d) — pure ordered/deduped option list from a
//      /config payload; fail-soft to [] on any malformed payload; never-throw.
//   2. Pet.renderHermesProfileSelector(host, d, opts) — the render seam: a <select>
//      over the profiles, the "scoped to the selected Hermes profile" note (no
//      "global" badge), the binding read-out, the non-equipped restart banner, the
//      effective read-out, and the dirty-form switch confirm gating that clears
//      Pet.state.configDirty before invoking opts.onSwitch (edge round-2 F-4 /
//      round-3 F-1).
//   3. Pet.hermesEffectiveReadout(d) — the read-only effective (what's enforced)
//      block (tier thresholds + active_profile_overrides).
//
// Like profile-picker.test.mjs this ships its OWN DOM shim, extended with
// parentNode tracking, node.remove(), and a minimal class-based querySelector —
// the only capabilities the selector needs beyond that file's shim.
//
// Zero npm dependencies: Node's built-in test runner + assert + node:vm, evaluating
// the real shipped petasos.js. Run with:
//   node --test tests/js/hermes-profile-selector.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
// Legacy (non-strict) assert: its deepEqual ignores object prototypes. Values
// returned from the node:vm sandbox carry the sandbox realm's Object/Array
// prototypes, so assert/strict's deepStrictEqual rejects them even when
// structurally identical (profile-picker.test.mjs:24-29). Structural comparisons
// of sandbox-origin values use this; primitive comparisons keep strict `assert`.
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
    value: undefined,
    parentNode: null,
    tabIndex: undefined,
    appendChild(child) {
      child.parentNode = this;
      this.childNodes.push(child);
      return child;
    },
    removeChild(child) {
      const i = this.childNodes.indexOf(child);
      if (i !== -1) this.childNodes.splice(i, 1);
      child.parentNode = null;
      return child;
    },
    remove() {
      if (this.parentNode) this.parentNode.removeChild(this);
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
    // Minimal descendant ".class" matcher (the only selector the seam uses).
    querySelector(sel) {
      const cls = sel.startsWith(".") ? sel.slice(1) : sel;
      const hit = (node) => {
        for (const c of node.childNodes) {
          if (c.nodeType === 1) {
            if ((c.className || "").split(/\s+/).includes(cls)) return c;
            const deep = hit(c);
            if (deep) return deep;
          }
        }
        return null;
      };
      return hit(this);
    },
    get textContent() {
      if (this.nodeType === 3) return this.nodeValue;
      return this.childNodes.map((c) => c.textContent).join("");
    },
    set textContent(v) {
      const t = makeNode(3);
      t.nodeValue = String(v);
      t.parentNode = this;
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
const hasClass = (el, c) => (el.className || "").split(/\s+/).includes(c);
function findByClass(root, cls) {
  for (const c of root.childNodes) {
    if (c.nodeType === 1) {
      if (hasClass(c, cls)) return c;
      const deep = findByClass(c, cls);
      if (deep) return deep;
    }
  }
  return null;
}
function findByTag(root, tag) {
  for (const c of root.childNodes) {
    if (c.nodeType === 1) {
      if (c.tagName === tag) return c;
      const deep = findByTag(c, tag);
      if (deep) return deep;
    }
  }
  return null;
}
function optionLabels(select) {
  return (select.childNodes || []).filter((n) => n.tagName === "OPTION").map((o) => o.textContent);
}

function payload(over) {
  over = over || {};
  return Object.assign(
    {
      is_active: true,
      hermes_profile: "alpha",
      config_tier: "profile",
      profile_home: "/root/profiles/alpha",
      config_warning: null,
      effective_config: { tier1_threshold: 15, tier2_threshold: 30, tier3_threshold: 50 },
      active_profile_overrides: null,
      hermes_profiles: [
        { name: "alpha", path: "/r/alpha", is_active: true, tier: "profile" },
        { name: "beta", path: "/r/beta", is_active: false, tier: "profile" },
      ],
    },
    over,
  );
}

function host() {
  return makeNode(1);
}

// ── 1. Loader guard ──────────────────────────────────────────────────────────
test("loader: petasos.js exports the PET-146 surfaces", () => {
  assert.equal(typeof Pet.hermesProfileOptions, "function");
  assert.equal(typeof Pet.renderHermesProfileSelector, "function");
  assert.equal(typeof Pet.hermesEffectiveReadout, "function");
  assert.equal(typeof Pet.HERMES_RESTART_BANNER, "string");
});

// ── 2. hermesProfileOptions: order, dedup, skip-blank, degrade ──────────────
test("hermesProfileOptions: ordered, first-wins deduped, blank/garbage skipped", () => {
  const d = payload({
    hermes_profiles: [
      { name: "alpha", path: "/r/alpha", is_active: true, tier: "profile" },
      { name: "beta", path: "/r/beta", is_active: false, tier: "profile" },
      { name: "alpha", path: "/dup", is_active: false }, // dedup, first wins
      { name: "  ", path: "/blank" }, // blank name -> skipped
      { description: "noname" }, // no name -> skipped
    ],
  });
  const opts = Pet.hermesProfileOptions(d);
  assertLoose.deepEqual(opts.map((o) => o.name), ["alpha", "beta"]);
  assert.equal(opts[0].is_active, true);
  assert.equal(opts[1].is_active, false);

  for (const bad of [null, undefined, {}, { hermes_profiles: "nope" }, { hermes_profiles: 7 }]) {
    let out;
    assert.doesNotThrow(() => { out = Pet.hermesProfileOptions(bad); });
    assert.ok(Array.isArray(out));
    assert.equal(out.length, 0);
  }
});

// ── 3. selector renders: <select>, options, scoped note, no "global" badge ──
test("renderHermesProfileSelector: select + options + scoped note, no global marker", () => {
  Pet.state.configDirty = {};
  const h = host();
  Pet.renderHermesProfileSelector(h, payload(), { selected: null, onSwitch() {} });

  const select = findByTag(h, "SELECT");
  assert.ok(select, "a <select> is rendered");
  const labels = optionLabels(select);
  assert.equal(labels.length, 2);
  assert.ok(labels.some((l) => l.includes("alpha") && l.includes("(equipped)")), "equipped option labeled");
  assert.ok(labels.some((l) => l.includes("beta")), "non-equipped option present");

  const note = findByClass(h, "pet-hermes-note");
  assert.ok(note, "scoped note present");
  assert.ok(note.textContent.includes("scoped to the selected Hermes profile"));
  // No per-field "global" badge anywhere in the selector subtree.
  assert.ok(!h.textContent.toLowerCase().includes("global"), "no 'global' marker rendered");

  // Default selection is the equipped entry when viewing active.
  assert.equal(select.value, "alpha");
});

// ── 4. non-equipped view shows the pinned restart banner ────────────────────
test("renderHermesProfileSelector: is_active false renders the pinned restart banner", () => {
  Pet.state.configDirty = {};
  const h = host();
  Pet.renderHermesProfileSelector(h, payload({ is_active: false }), { selected: "beta", onSwitch() {} });

  const banner = findByClass(h, "pet-hermes-banner");
  assert.ok(banner, "restart banner present when non-equipped");
  assert.ok(banner.textContent.includes(Pet.HERMES_RESTART_BANNER));
  // The pinned copy is exact (JS test and impl cannot drift) and em-dash-free.
  assert.equal(
    Pet.HERMES_RESTART_BANNER,
    "This isn't the equipped profile; changes take effect when it's equipped (restart).",
  );
  assert.ok(!Pet.HERMES_RESTART_BANNER.includes("—"), "no em dash (house style)");
});

test("renderHermesProfileSelector: equipped view renders NO restart banner", () => {
  Pet.state.configDirty = {};
  const h = host();
  Pet.renderHermesProfileSelector(h, payload({ is_active: true }), { selected: null, onSwitch() {} });
  assert.equal(findByClass(h, "pet-hermes-banner"), null);
});

// ── 5. effective read-out reflects tier thresholds + overrides ──────────────
test("hermesEffectiveReadout: renders tier thresholds and active_profile_overrides", () => {
  const d = payload({
    effective_config: { tier1_threshold: 25, tier2_threshold: 45, tier3_threshold: 70 },
    active_profile_overrides: {
      name: "research",
      confidence_floor: 0.7,
      suppress_rules: ["petasos.syntactic.encoding.base64-in-text"],
      severity_overrides: {},
      pii_entities_extra: [],
    },
  });
  const box = Pet.hermesEffectiveReadout(d);
  const txt = box.textContent;
  assert.ok(txt.includes("effective (what's enforced)"));
  assert.ok(txt.includes("25") && txt.includes("45") && txt.includes("70"), "profile tier thresholds shown");
  assert.ok(txt.includes("research"), "internal profile named");
  assert.ok(txt.includes("0.7"), "confidence floor surfaced (it is NOT a config field)");
});

// ── 6. clean-form switch invokes onSwitch immediately ───────────────────────
test("switch on a clean form: change invokes onSwitch with the target name", () => {
  Pet.state.configDirty = {};
  const h = host();
  let got = "UNSET";
  Pet.renderHermesProfileSelector(h, payload(), { selected: null, onSwitch(t) { got = t; } });
  const select = findByTag(h, "SELECT");

  select.value = "beta";
  select.handlers.change[0]();
  assert.equal(got, "beta", "non-equipped target passed through");
});

test("switch to the equipped entry passes null (loads the live config)", () => {
  Pet.state.configDirty = {};
  const h = host();
  let got = "UNSET";
  Pet.renderHermesProfileSelector(h, payload({ is_active: false }), { selected: "beta", onSwitch(t) { got = t; } });
  const select = findByTag(h, "SELECT");

  select.value = "alpha"; // alpha is the equipped option
  select.handlers.change[0]();
  assert.equal(got, null, "equipped entry -> null target");
});

// ── 7. dirty-form switch is gated, then confirmed (round-2 F-4 / round-3 F-1) ─
test("dirty-form switch: first change prompts confirm + keeps configDirty; second confirms + clears it", () => {
  Pet.state.configDirty = { fail_mode: "open" }; // an unsaved edit under profile A
  const h = host();
  const calls = [];
  Pet.renderHermesProfileSelector(h, payload(), { selected: null, onSwitch(t) { calls.push(t); } });
  const select = findByTag(h, "SELECT");

  // First change toward beta: gated. onSwitch NOT called; configDirty intact;
  // a confirm strip appears; the visible value reverts to the current (alpha).
  select.value = "beta";
  select.handlers.change[0]();
  assert.equal(calls.length, 0, "switch not committed on first change");
  assertLoose.deepEqual(Pet.state.configDirty, { fail_mode: "open" }, "edits preserved, not discarded");
  assert.ok(findByClass(h, "pet-hermes-switch-confirm"), "confirm strip shown");
  assert.equal(select.value, "alpha", "visible selection reverted pending confirm");

  // Second change to the SAME target confirms: onSwitch fires with beta and
  // configDirty is cleared so a subsequent save sends only B's values.
  select.value = "beta";
  select.handlers.change[0]();
  assertLoose.deepEqual(calls, ["beta"], "switch committed on confirm");
  assertLoose.deepEqual(Pet.state.configDirty, {}, "configDirty cleared before onSwitch");
});

// ── 8. dangling-pointer warning labeled as the ACTIVE binding (round-2 F-7) ──
test("renderHermesProfileSelector: config_warning renders labeled as the active binding", () => {
  Pet.state.configDirty = {};
  const h = host();
  Pet.renderHermesProfileSelector(
    h,
    payload({ is_active: false, selected: "beta", config_warning: "active_profile points to a missing dir" }),
    { selected: "beta", onSwitch() {} },
  );
  const warn = findByClass(h, "pet-hermes-warn");
  assert.ok(warn, "warning strip present");
  assert.ok(warn.textContent.includes("Active binding"), "labeled as the ACTIVE binding, not the browsed profile");
});
