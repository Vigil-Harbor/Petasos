// Unit tests for PET-122 — the self-describing profile_name picker.
//
// Covers the three JS surfaces added to petasos/console/static/petasos.js:
//   1. Pet.profileDescriptions(profiles) — pure name->trimmed-description map
//      (the tip source); first-wins dedup, blank/missing/non-string skipped,
//      never-throw on any malformed /api/profiles payload.
//   2. Pet.profileNames(profiles) — pure ordered valid-name list (the option
//      source); first-wins dedup, blank-description names kept, never-throw.
//   3. Pet.buildProfileControl(f, val, profilesP) — the render seam: a .seg of
//      hoverable radio buttons with an explicit "(none)" unset option, per-option
//      HelpTip enrich, dirty-selection recompute, and the "(none)" collision guard.
//
// Like config-sections.test.mjs this file ships its OWN extended DOM shim. It adds
// `removeChild` (the only capability beyond that file's shim) because the picker's
// enrich rebuild clears the seg via shim-observable node removal, never
// innerHTML="" (which the shim does not service — see the spec's F-1 note).
//
// Zero npm dependencies: Node's built-in test runner + assert + node:vm, evaluating
// the real shipped petasos.js. Run with:
//   node --test tests/js/profile-picker.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
// Legacy (non-strict) assert: its deepEqual ignores object prototypes. Values
// returned from the node:vm sandbox carry the sandbox realm's Object/Array
// prototypes, so assert/strict's deepStrictEqual rejects them even when
// structurally identical (config-sections.test.mjs:22-28). Structural comparisons
// use this; primitive comparisons keep the strict `assert`.
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
    removeChild(child) {
      const i = this.childNodes.indexOf(child);
      if (i !== -1) this.childNodes.splice(i, 1);
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

const FALLBACK_TIP = "Custom profile: no description provided.";

// ── Helpers ────────────────────────────────────────────────────────────────
const hasClass = (el, c) => (el.className || "").split(/\s+/).includes(c);

// Option buttons of a built control, in DOM order.
function buttons(seg) {
  return (seg.childNodes || []).filter((n) => n.nodeType === 1 && n.tagName === "BUTTON");
}
// The .help (HelpTip) node, if any, that immediately follows `btn` in the seg.
function tipAfter(seg, btn) {
  const cn = seg.childNodes || [];
  const next = cn[cn.indexOf(btn) + 1];
  return next && next.nodeType === 1 && hasClass(next, "help") ? next : null;
}
// Read a HelpTip node's rendered tip text (through the richText fragment).
function tipText(helpNode) {
  const tip = (helpNode.childNodes || []).find((c) => c.nodeType === 1 && hasClass(c, "tip"));
  return tip ? tip.textContent : null;
}
const btnByVal = (seg, v) => buttons(seg).find((b) => b._petVal === v);
const isOn = (b) => hasClass(b, "on") && b.getAttribute("aria-checked") === "true";

const PROFILE_FIELD = { name: "profile_name" };
function build(val, profilesP) {
  Pet.state.configDirty = {}; // module-global; reset per build so tests don't bleed
  return Pet.buildProfileControl(PROFILE_FIELD, val, profilesP);
}

// Five built-ins with non-empty descriptions (fixtures; values are arbitrary copy,
// no em dashes per house style — the test pins structure, not the shipped strings).
function builtins() {
  return [
    { name: "general", description: "Balanced defaults for everyday agent traffic." },
    { name: "customer_service", description: "Support chat: stricter PII handling." },
    { name: "code_generation", description: "Lets code through; still blocks injection." },
    { name: "research", description: "Permissive for analysis and long-context reading." },
    { name: "admin", description: "Maximum strictness for privileged operations." },
  ];
}

// Malformed payloads shared by the never-throw matrices (3) and (5).
const BAD_PAYLOADS = [
  null,
  undefined,
  [],
  "nope",
  7,
  [{ name: "x" }], // no description
  [{ description: "y" }], // no name
  [{ name: "z", description: "  " }], // blank description
  [{ name: "   ", description: "x" }], // whitespace-only NAME -> rejected (no blank button)
  [{ name: "a", description: null }], // null description
  [{ name: "b", description: 7 }], // number description
  [{ name: "c", description: {} }], // object description
  [null, undefined, {}], // garbage entries
];

// ── 1. Loader guard ──────────────────────────────────────────────────────────
test("loader: petasos.js exports the PET-122 surfaces", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.profileDescriptions, "function");
  assert.equal(typeof Pet.profileNames, "function");
  assert.equal(typeof Pet.buildProfileControl, "function");
});

// ── 2. profileDescriptions happy path ────────────────────────────────────────
test("profileDescriptions: five built-ins map to their exact trimmed descriptions", () => {
  const map = Pet.profileDescriptions(builtins());
  assertLoose.deepEqual(map, {
    general: "Balanced defaults for everyday agent traffic.",
    customer_service: "Support chat: stricter PII handling.",
    code_generation: "Lets code through; still blocks injection.",
    research: "Permissive for analysis and long-context reading.",
    admin: "Maximum strictness for privileged operations.",
  });
  // Whitespace is trimmed off the stored value.
  assertLoose.deepEqual(Pet.profileDescriptions([{ name: "g", description: "  hi  " }]), { g: "hi" });
});

// ── 3. profileDescriptions never-throw / degrade matrix ──────────────────────
test("profileDescriptions: degrade matrix returns {} and never throws", () => {
  for (const bad of BAD_PAYLOADS) {
    let out;
    assert.doesNotThrow(() => { out = Pet.profileDescriptions(bad); });
    assertLoose.deepEqual(out, {}, `bad payload ${JSON.stringify(bad)} -> {}`);
    // No undefined / empty values ever leak in (vacuously true for {}).
    for (const k of Object.keys(out)) {
      assert.equal(typeof out[k], "string");
      assert.ok(out[k].length > 0);
    }
  }
});

// ── 4. profileNames happy path: order, dedup, blank-description kept ──────────
test("profileNames: ordered, first-wins deduped, blank-description kept, no-name skipped", () => {
  const payload = [
    { name: "general", description: "g" },
    { name: "research", description: "" }, // blank description is STILL a valid option
    { name: "general", description: "dup" }, // dedup, first wins
    { description: "noname" }, // missing name -> skipped
    { name: "admin", description: "a" },
  ];
  assertLoose.deepEqual(Pet.profileNames(payload), ["general", "research", "admin"]);
});

// ── 5. profileNames never-throw / degrade matrix ─────────────────────────────
test("profileNames: degrade matrix returns an array, never throws, skips bad entries", () => {
  const expected = new Map([
    [JSON.stringify(null), []],
    [JSON.stringify([]), []],
    [JSON.stringify("nope"), []],
    [JSON.stringify(7), []],
    [JSON.stringify([{ name: "x" }]), ["x"]], // name present, description irrelevant
    [JSON.stringify([{ description: "y" }]), []], // no name
    [JSON.stringify([{ name: "z", description: "  " }]), ["z"]], // blank desc, name kept
    [JSON.stringify([{ name: "   ", description: "x" }]), []], // whitespace-only name dropped
    [JSON.stringify([{ name: "a", description: null }]), ["a"]],
    [JSON.stringify([{ name: "b", description: 7 }]), ["b"]],
    [JSON.stringify([{ name: "c", description: {} }]), ["c"]],
    [JSON.stringify([null, undefined, {}]), []],
  ]);
  for (const bad of BAD_PAYLOADS) {
    let out;
    assert.doesNotThrow(() => { out = Pet.profileNames(bad); });
    assert.ok(Array.isArray(out), "always an array");
    const key = JSON.stringify(bad);
    if (expected.has(key)) assertLoose.deepEqual(out, expected.get(key), `names(${key})`);
  }
  assertLoose.deepEqual(Pet.profileNames(undefined), []);
});

// ── 6. Duplicate-name payload: the two builders agree (first-wins) ────────────
test("duplicate-name payload: profileNames and profileDescriptions both first-wins", () => {
  const dup = [
    { name: "x", description: "A" },
    { name: "x", description: "B" },
  ];
  assertLoose.deepEqual(Pet.profileNames(dup), ["x"]);
  assertLoose.deepEqual(Pet.profileDescriptions(dup), { x: "A" });
});

// ── 7. Unknown/custom profile fallback (render seam) ─────────────────────────
test("render seam: a custom/unknown value renders as a selectable option with the fallback tip", () => {
  let seg;
  assert.doesNotThrow(() => { seg = build("my_custom", null); });
  // Enrich with a payload that does NOT contain the custom value.
  seg._petRebuild(["general"], { general: "g desc" });

  const custom = btnByVal(seg, "my_custom");
  assert.ok(custom, "custom value rendered as an option");
  const help = tipAfter(seg, custom);
  assert.ok(help, "custom option carries a HelpTip");
  assert.equal(tipText(help), FALLBACK_TIP);

  // A custom profile that IS in the payload but lacks a description: same fallback.
  const seg2 = build(null, null);
  seg2._petRebuild(["weird_one"], {});
  const weird = btnByVal(seg2, "weird_one");
  assert.ok(weird);
  assert.equal(tipText(tipAfter(seg2, weird)), FALLBACK_TIP);
});

// ── 8. a11y focus-reveal structure (render seam) ─────────────────────────────
test("render seam: each enriched option tip is a focusable HelpTip (.help, tabIndex 0, focus handler)", () => {
  const seg = build(null, null);
  seg._petRebuild(["research"], { research: "Permissive." });
  const help = tipAfter(seg, btnByVal(seg, "research"));
  assert.ok(help, "research option has a HelpTip sibling");
  assert.ok(hasClass(help, "help"), "tip node is a .help span");
  assert.equal(help.tabIndex, "0", "HelpTip is keyboard-focusable");
  // Focus-reveal parity with hover: HelpTip registers a focus handler. Structure
  // only; we do NOT fire it (reveal is pure CSS, and position() needs a real
  // getBoundingClientRect the shim has no business providing).
  assert.ok(Array.isArray(help.handlers.focus) && help.handlers.focus.length >= 1, "focus handler registered");
  assert.equal(tipText(help), "Permissive.");
});

// ── 9. "(none)" + degrade render (render seam) ───────────────────────────────
test("render seam: empty profiles -> (none) + current value, selectable, no tips", () => {
  const seg = build("general", Promise.resolve([])); // /profiles down -> resolves []
  seg._petRebuild([], {}); // the degrade repaint the empty promise drives

  const none = btnByVal(seg, null);
  const cur = btnByVal(seg, "general");
  assert.ok(none, "(none) option present");
  assert.ok(cur, "current configured value present");
  // No tips on the minimal/degrade seg.
  assert.equal(tipAfter(seg, none), null, "(none) has no tip");
  assert.equal(tipAfter(seg, cur), null, "current value has no tip in degrade render");
  assert.ok(!(seg.childNodes || []).some((n) => n.nodeType === 1 && hasClass(n, "help")), "no HelpTip nodes at all");

  // Clicking "(none)" writes null and never throws.
  assert.doesNotThrow(() => none.handlers.click[0]({ preventDefault() {} }));
  assert.equal(Pet.state.configDirty.profile_name, null);
  assert.ok(isOn(none), "(none) is highlighted after click");
});

// ── 10. Dirty selection survives the enrich rebuild (round-1 F-4) ─────────────
test("render seam: a selection made before enrich survives the rebuild", () => {
  const seg = build("general", null); // config value is "general"
  // Operator clicks "research" before getProfiles resolves: writes configDirty.
  Pet.state.configDirty.profile_name = "research";
  // Enrich arrives.
  seg._petRebuild(["general", "research", "admin"], { general: "g", research: "r", admin: "a" });

  const research = btnByVal(seg, "research");
  assert.ok(research);
  assert.ok(isOn(research), "research (the dirty value) is highlighted, not the config value");
  assert.ok(!isOn(btnByVal(seg, "general")), "config value is NOT highlighted");
});

// ── 11. "(none)" label collision guard (round-1 F-3, round-2 F-2) ─────────────
test("render seam: a profile named (none) never duplicates the structural unset button", () => {
  // (a) payload contains a profile literally named "(none)".
  const seg = build(null, null);
  seg._petRebuild(["(none)", "general"], { "(none)": "should be ignored", general: "g" });
  const noneButtons = buttons(seg).filter((b) => b._petNone);
  assert.equal(noneButtons.length, 1, "exactly one structural (none) button");
  assert.equal(noneButtons[0]._petVal, null, "the (none) button writes null, not the string");
  assert.ok(!buttons(seg).some((b) => b._petVal === "(none)"), "no button writes the literal '(none)' string");

  // (b) a current/dirty value equal to the literal "(none)" is treated as unset:
  // still exactly one structural button, and it is highlighted.
  const seg2 = build(null, null);
  Pet.state.configDirty.profile_name = "(none)";
  seg2._petRebuild(["general"], { general: "g" });
  const none2 = buttons(seg2).filter((b) => b._petNone);
  assert.equal(none2.length, 1, "literal '(none)' dirty value adds no second button");
  assert.ok(isOn(none2[0]), "structural (none) is highlighted for a '(none)' dirty value");
  assert.ok(!buttons(seg2).some((b) => b._petVal === "(none)"), "no truthy '(none)' string button");
});
