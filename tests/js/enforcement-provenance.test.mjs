// PET-139: the drill-down "is this legit?" provenance line renders the three
// integrity states (genuine / unverifiable / unattested) on an enforcement row.
//
// The badge reads summary.provenance. Only the exact strings "genuine" and
// "unverifiable" map through; anything else (absent, null, non-string, unknown)
// renders as "unattested" — never a crash, never a false "genuine". An
// unverifiable row stays visible (surface-and-flag, not hide).
//
// Zero npm deps: Node's built-in test runner + node:vm over the real shipped
// petasos.js. Run with: node --test tests/js/enforcement-provenance.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// Minimal DOM shim — scanDetailPanel only builds elements + text nodes via Pet.h.
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

// Recursively concatenate all text-node content under a rendered node.
function textOf(node) {
  if (!node) return "";
  if (node.nodeType === 3) return node.nodeValue || "";
  let s = "";
  for (const c of (node.childNodes || [])) s += textOf(c);
  return s;
}
// Collect every className present in the subtree.
function classesOf(node, acc) {
  acc = acc || [];
  if (!node) return acc;
  if (node.className) acc.push(node.className);
  for (const c of (node.childNodes || [])) classesOf(c, acc);
  return acc;
}

const enfBlock = (provenance) => ({
  source: "enforcement",
  event_type: "block",
  tool: "send_email",
  tier: "tier2",
  reason: "blocked by escalation",
  session_id: "sess-1",
  armed: true,
  provenance,
});

test("loader: petasos.js exposes scanDetailPanel", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.scanDetailPanel, "function");
});

test("genuine renders the verified marker", () => {
  const el = Pet.scanDetailPanel(enfBlock("genuine"));
  const txt = textOf(el);
  assert.match(txt, /Verified Petasos event/);
  assert.ok(classesOf(el).some((c) => c.includes("sd-prov-genuine")));
  assert.doesNotMatch(txt, /Unverified/);
});

test("unverifiable renders the warn copy and stays visible", () => {
  const el = Pet.scanDetailPanel(enfBlock("unverifiable"));
  const txt = textOf(el);
  assert.match(txt, /Unverified: signature missing or invalid/);
  assert.ok(classesOf(el).some((c) => c.includes("sd-prov-unverifiable")));
  // surface-and-flag, not hide: the decision body still renders (tool value present).
  assert.match(txt, /send_email/);
});

test("unattested renders the neutral copy", () => {
  const el = Pet.scanDetailPanel(enfBlock("unattested"));
  const txt = textOf(el);
  assert.match(txt, /Integrity not configured/);
  assert.ok(classesOf(el).some((c) => c.includes("sd-prov-unattested")));
});

test("absent provenance renders as unattested, not a crash and not a false genuine", () => {
  const ev = enfBlock(undefined);
  delete ev.provenance;
  const el = Pet.scanDetailPanel(ev);
  const txt = textOf(el);
  assert.match(txt, /Integrity not configured/);
  assert.ok(classesOf(el).some((c) => c.includes("sd-prov-unattested")));
  assert.doesNotMatch(txt, /Verified Petasos event/);
});

test("non-string and unknown provenance both fall back to unattested", () => {
  for (const bad of [123, null, true, "bogus", ""]) {
    const el = Pet.scanDetailPanel(enfBlock(bad));
    const txt = textOf(el);
    assert.match(txt, /Integrity not configured/, `provenance=${JSON.stringify(bad)}`);
    assert.doesNotMatch(txt, /Verified Petasos event/, `provenance=${JSON.stringify(bad)}`);
  }
});

test("playground rows carry no attestation badge", () => {
  const el = Pet.scanDetailPanel({ source: "playground", safe: true });
  const cls = classesOf(el);
  assert.ok(!cls.some((c) => c.includes("sd-prov-att")));
});
