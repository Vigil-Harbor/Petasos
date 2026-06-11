// Unit tests for Pet.richText (petasos/console/static/petasos.js).
//
// Regression for PET-82: HelpTip used `tip.innerHTML = html`, a variable-fed
// innerHTML sink. richText replaces it with a restricted-markup builder that
// only ever creates <b>/<code>/<em> elements and escapes everything else to
// text — so a future dynamic tooltip cannot smuggle an XSS payload.
//
// Zero npm dependencies: Node's built-in test runner + assert, a minimal DOM
// shim, and node:vm to evaluate the real shipped petasos.js. Run with:
//   node --test tests/js/richtext.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

// ── Minimal DOM shim ──────────────────────────────────────────────────────
// Models exactly the surface richText touches. richText only ever appends
// freshly-created nodes (never re-parents, never appends a fragment into a
// node), so the shim does not model real-DOM appendChild re-parenting or
// DocumentFragment flattening — see spec D3 "Fidelity boundary".
function makeNode(nodeType) {
  return {
    nodeType, // 1 = element, 3 = text, 11 = fragment
    childNodes: [],
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
    el.tagName = tag.toUpperCase(); // mirrors real DOM (uppercase for HTML)
    el.localName = tag;
    return el;
  },
  createTextNode(t) {
    const node = makeNode(3);
    node.nodeValue = String(t);
    return node;
  },
};

// ── Load the real petasos.js under a sandbox ──────────────────────────────
const here = dirname(fileURLToPath(import.meta.url));
const petasosJsPath = join(here, "..", "..", "petasos", "console", "static", "petasos.js");
const src = readFileSync(petasosJsPath, "utf8");

const sandbox = { window: {}, document };
vm.runInNewContext(src, sandbox);
const Pet = sandbox.window.__PETASOS_CONSOLE__;

// Guards spec D5: the export ran and richText is present.
test("loader: petasos.js exports Pet.richText", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.richText, "function");
});

// ── Helpers ───────────────────────────────────────────────────────────────
// Depth-first list of every element node's tagName in the subtree.
function tagNames(node) {
  const out = [];
  for (const child of node.childNodes) {
    if (child.nodeType === 1) {
      out.push(child.tagName);
      out.push(...tagNames(child));
    }
  }
  return out;
}

// ── Test matrix ─────────────────────────────────────────────────────────

// #1 allowed <b>
test("#1 <b> renders a B element", () => {
  const f = Pet.richText("<b>hi</b>");
  assert.equal(f.childNodes.length, 1);
  assert.equal(f.childNodes[0].tagName, "B");
  assert.equal(f.childNodes[0].textContent, "hi");
});

// #2 allowed <code>
test("#2 <code> renders a CODE element", () => {
  const f = Pet.richText("<code>x</code>");
  assert.deepEqual(tagNames(f), ["CODE"]);
  assert.equal(f.textContent, "x");
});

// #3 allowed <em>
test("#3 <em> is allow-listed", () => {
  const f = Pet.richText("<em>y</em>");
  assert.deepEqual(tagNames(f), ["EM"]);
  assert.equal(f.textContent, "y");
});

// #4 nesting
test("#4 nested tags build a nested tree", () => {
  const f = Pet.richText("a <b>b <code>c</code></b> d");
  assert.equal(f.textContent, "a b c d");
  assert.deepEqual(tagNames(f), ["B", "CODE"]);
  // structure: text, B(text, CODE(text)), text
  assert.equal(f.childNodes[1].tagName, "B");
  assert.equal(f.childNodes[1].childNodes[1].tagName, "CODE");
});

// #5 case-insensitive (pins D2)
test("#5 uppercase tags are honored (case-insensitive)", () => {
  assert.deepEqual(tagNames(Pet.richText("<B>X</B>")), ["B"]);
  assert.deepEqual(tagNames(Pet.richText("<CODE>x</CODE>")), ["CODE"]);
});

// #6 disallowed <script> escaped
test("#6 <script> is escaped to text, no element", () => {
  const f = Pet.richText("<script>alert(1)</script>");
  assert.deepEqual(tagNames(f), []);
  assert.equal(f.textContent, "<script>alert(1)</script>");
});

// #7 disallowed <img onerror> escaped
test("#7 <img onerror> is escaped to text, no element", () => {
  const input = "<img src=x onerror=alert(1)>";
  const f = Pet.richText(input);
  assert.deepEqual(tagNames(f), []);
  assert.equal(f.textContent, input);
});

// #8 attribute-bearing allowed tag is NOT honored
test("#8 <b class=...> degrades to literal text", () => {
  const f = Pet.richText('<b class="x">y</b>');
  assert.deepEqual(tagNames(f), []);
  // The open-tag-with-attributes never opens a B, so the trailing </b> has no
  // matching element and is also literal: the whole input round-trips to text.
  assert.equal(f.textContent, '<b class="x">y</b>');
});

// #9 mismatched closer is treated as literal text (structural rule not suppressed)
test("#9 mismatched </b> does not close the wrong element", () => {
  const f = Pet.richText("<b><em>x</b>");
  // </b> does not match the open <em>, so it is literal text, not a close.
  assert.deepEqual(tagNames(f), ["B", "EM"]);
  assert.equal(f.textContent, "x</b>");
  assert.equal(f.childNodes[0].tagName, "B");
  assert.equal(f.childNodes[0].childNodes[0].tagName, "EM");
  assert.equal(f.childNodes[0].childNodes[0].textContent, "x</b>");
});

// #10 truncated "<"
test("#10 truncated < is literal text", () => {
  const f = Pet.richText("<b");
  assert.deepEqual(tagNames(f), []);
  assert.equal(f.textContent, "<b");
});

// #11 lone close tag has no matching element → literal text
test("#11 lone </b> is literal text, no throw", () => {
  const f = Pet.richText("</b>");
  assert.deepEqual(tagNames(f), []);
  assert.equal(f.textContent, "</b>");
});

// #12 unclosed open tag
test("#12 unclosed <b> still wraps trailing text", () => {
  const f = Pet.richText("<b>hi");
  assert.deepEqual(tagNames(f), ["B"]);
  assert.equal(f.childNodes[0].textContent, "hi");
});

// #13 null / undefined / empty (D7 contract)
test("#13 null/undefined/empty return an empty fragment", () => {
  assert.equal(Pet.richText("").childNodes.length, 0);
  assert.equal(Pet.richText(null).childNodes.length, 0);
  assert.equal(Pet.richText(undefined).childNodes.length, 0);
});

// #14 number coercion (D7 contract)
test("#14 number input coerces to text", () => {
  const f = Pet.richText(123);
  assert.equal(f.childNodes.length, 1);
  assert.equal(f.childNodes[0].nodeType, 3);
  assert.equal(f.textContent, "123");
});

// #15 plain text
test("#15 plain text becomes a single text node", () => {
  const f = Pet.richText("plain text");
  assert.equal(f.childNodes.length, 1);
  assert.equal(f.childNodes[0].nodeType, 3);
  assert.equal(f.textContent, "plain text");
});

// #16 whitespace / stray angle brackets
test("#16 whitespace and stray angle brackets", () => {
  // trailing-space tag → escaped
  let f = Pet.richText("<b >text");
  assert.deepEqual(tagNames(f), []);
  assert.equal(f.textContent, "<b >text");

  // bare > with no < → plain text
  f = Pet.richText("a > b");
  assert.equal(f.childNodes.length, 1);
  assert.equal(f.childNodes[0].nodeType, 3);
  assert.equal(f.textContent, "a > b");

  // "<<b>>" → text "<", then unclosed B holding trailing ">"
  f = Pet.richText("<<b>>");
  assert.deepEqual(tagNames(f), ["B"]);
  assert.equal(f.textContent, "<>");
  assert.equal(f.childNodes.length, 2);
  assert.equal(f.childNodes[0].nodeType, 3);
  assert.equal(f.childNodes[0].nodeValue, "<");
  assert.equal(f.childNodes[1].tagName, "B");
  assert.equal(f.childNodes[1].textContent, ">");
});

// #17 astral / surrogate pair preserved
test("#17 astral characters survive intact", () => {
  const f = Pet.richText("<b>\u{1F600}</b>");
  assert.deepEqual(tagNames(f), ["B"]);
  assert.equal(f.textContent, "\u{1F600}");
});

// #18 security sweep — no element may ever be smuggled
test("#18 security sweep: only b/code/em can become elements", () => {
  const attacks = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<svg/onload=1>",
    "<iframe>",
    "<a href=javascript:1>z</a>",
    '<b title=">">x',
    "<b/>",
    "<b\nclass=x>",
  ];
  for (const input of attacks) {
    const f = Pet.richText(input);
    assert.deepEqual(
      tagNames(f),
      [],
      `expected no elements for: ${JSON.stringify(input)}`
    );
  }
});

// #19 regression: the 6 current HelpTip caller strings render with only
// B/CODE elements and text identical to the tags-stripped string.
test("#19 current caller strings render identically (structural)", () => {
  const callers = [
    "<b>Scanner Health</b> — per-scanner backend status. <code>healthy</code>: last scan succeeded. <code>degraded</code>: last scan errored or timeout streak. <code>circuit_open</code>: consecutive timeout breaker tripped. <code>unavailable</code>: backend not installed or prerequisites missing.",
    "<b>Scan History</b> — recent pipeline scans with severity, direction, and timing. Each row is one <code>Pipeline.evaluate()</code> call.",
    "<b>Findings</b> — individual detections from each scanner. Severity ranges from <code>INFO</code> to <code>CRITICAL</code>. High+ on dangerous tools triggers a block.",
    "<b>Session Overlay</b> — cumulative session risk score and escalation tier. Score rises with repeated violations; tier thresholds trigger progressively stricter enforcement.",
    "<b>Scan Playground</b> — paste text and run it through the full pipeline. Choose <code>inbound</code> (user→agent) or <code>outbound</code> (agent→user) direction. Optionally bind to a session ID for frequency tracking.",
    "<b>Support</b> — Petasos is free and open source (MIT). Sponsorship helps fund continued development but unlocks nothing — every feature is available to everyone.",
  ];
  for (const s of callers) {
    const f = Pet.richText(s);
    // only B/CODE elements
    for (const t of tagNames(f)) {
      assert.ok(t === "B" || t === "CODE", `unexpected element ${t} in: ${s}`);
    }
    const stripped = s.replace(/<\/?(?:b|code)>/g, "");
    // tripwire: equivalence holds only because these strings contain no
    // entities and no stray angle brackets outside the b/code tags.
    assert.ok(!s.includes("&"), `caller string contains '&': ${s}`);
    assert.ok(
      !stripped.includes("<") && !stripped.includes(">"),
      `caller string has stray angle brackets: ${s}`
    );
    assert.equal(f.textContent, stripped);
  }
});
