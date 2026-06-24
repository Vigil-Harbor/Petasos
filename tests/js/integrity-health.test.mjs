// PET-157: Pet.integrityRows renders the self-diagnosing integrity state on the Observability
// tab — integrity ON/OFF, the dominant verdict pill, the failure class, and the remediation
// line — from the additive get_health `integrity` payload. It must NEVER throw (the SSE
// _dispatch re-render path calls the obs render synchronously), so a missing/partial payload
// renders an "unavailable" fallback rather than crashing, and the OFF / unattested paths carry
// no alarm styling (bare `pill`, never `pill err`).
//
// Zero npm deps: Node's built-in test runner + node:vm over the real shipped petasos.js.
// Run with: node --test tests/js/integrity-health.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// Minimal DOM shim — Pet.integrityRows only builds elements + text nodes via Pet.h.
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

function textOf(node) {
  if (!node) return "";
  if (node.nodeType === 3) return node.nodeValue || "";
  let s = "";
  for (const c of (node.childNodes || [])) s += textOf(c);
  return s;
}
function classesOf(node, acc) {
  acc = acc || [];
  if (!node) return acc;
  if (node.className) acc.push(node.className);
  for (const c of (node.childNodes || [])) classesOf(c, acc);
  return acc;
}

test("loader: petasos.js exposes integrityRows", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.integrityRows, "function");
});

test("key_off renders the off/no-alarm copy with no err pill", () => {
  const el = Pet.integrityRows({
    key_on: false,
    dominant_verdict: "unattested",
    failure_class: null,
    counts: { genuine: 0, unattested: 3, unverifiable: 0 },
    window_size: 3,
    remediation: "Integrity is off because no valid PETASOS_SESSION_SECRET is configured for this process.",
  });
  const txt = textOf(el);
  assert.match(txt, /OFF/);
  assert.match(txt, /no valid PETASOS_SESSION_SECRET/);
  const cls = classesOf(el);
  assert.ok(!cls.some((c) => c.split(" ").includes("err")), "OFF must carry no alarm (err) pill");
});

test("genuine renders the ok pill and no remediation line", () => {
  const el = Pet.integrityRows({
    key_on: true,
    dominant_verdict: "genuine",
    failure_class: null,
    counts: { genuine: 5, unattested: 0, unverifiable: 0 },
    window_size: 5,
    remediation: null,
  });
  const txt = textOf(el);
  assert.match(txt, /ON/);
  assert.match(txt, /genuine/);
  const cls = classesOf(el);
  assert.ok(cls.some((c) => c.split(" ").includes("ok")), "genuine verdict should use the ok pill");
  assert.ok(!cls.some((c) => c.split(" ").includes("err")), "genuine must carry no err pill");
});

test("unverifiable / sig-mismatch renders the err pill + remediation line", () => {
  const remediation =
    "the gateway and dashboard most likely hold different PETASOS_SESSION_SECRET values; " +
    "set the same secret on both processes and restart them.";
  const el = Pet.integrityRows({
    key_on: true,
    dominant_verdict: "unverifiable",
    failure_class: "sig-mismatch",
    counts: { genuine: 2, unattested: 0, unverifiable: 4 },
    window_size: 6,
    remediation,
  });
  const txt = textOf(el);
  assert.match(txt, /unverifiable/);
  assert.match(txt, /sig-mismatch/);
  assert.match(txt, /restart them/);
  const cls = classesOf(el);
  assert.ok(cls.some((c) => c.split(" ").includes("err")), "unverifiable verdict should use the err pill");
});

test("missing/partial integrity object renders the unavailable fallback and never throws", () => {
  for (const bad of [undefined, null, {}, { key_on: "yes" }, 123, "nope"]) {
    let el;
    assert.doesNotThrow(() => { el = Pet.integrityRows(bad); }, `input=${JSON.stringify(bad)}`);
    const txt = textOf(el);
    assert.match(txt, /integrity status unavailable/, `input=${JSON.stringify(bad)}`);
  }
});
