// PET-148: unit tests for the scan-history back-page paging seams (petasos.js).
//
// The server cursor walks only OLDER (D-PAGING); "Newer" replays the client-buffered page
// stack back toward the live head. Pet.historyPagingView is a pure reducer (no DOM, no
// network — like Pet.scanHistorySubtitle / Pet.mergeScanHistory) so the harness can assert
// cursor advance/retreat without the network, and Pet.historyPageLabel is the positional
// (NO numeric total — D-RESTART) label whose empty state is retention-honest (D-ROTATION /
// edge F-2: "no older retained history" when the cursor's segment aged out).
//
// Zero npm deps: Node's built-in test runner + node:vm over the real shipped petasos.js.
// Run with: node --test tests/js/scan-history-paging.test.mjs

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

test("loader: petasos.js exposes the paging seams", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.historyPagingView, "function");
  assert.equal(typeof Pet.historyPageLabel, "function");
});

test("Older off the live head fetches with the head's server cursor", () => {
  const next = Pet.historyPagingView({ atHead: true, stack: [], headCursor: "1700.5~s-abc" }, "older");
  assert.equal(next.needsFetch, true);
  assert.equal(next.cursor, "1700.5~s-abc");
  assert.equal(next.atHead, false); // a successful older fetch leaves the live head
});

test("Older from a paged view advances to that page's next_before cursor", () => {
  const state = { atHead: false, stack: [{ entries: [{}], nextBefore: "1600.0~s-def" }] };
  const next = Pet.historyPagingView(state, "older");
  assert.equal(next.needsFetch, true);
  assert.equal(next.cursor, "1600.0~s-def"); // advances past the current page
});

test("Older at the retained bottom (null cursor) does not fetch", () => {
  // head with no server cursor (empty sink / seed not done):
  const atHead = Pet.historyPagingView({ atHead: true, stack: [], headCursor: null }, "older");
  assert.equal(atHead.needsFetch, false);
  assert.equal(atHead.cursor, null);
  // paged view whose next_before is null (true bottom):
  const paged = Pet.historyPagingView({ atHead: false, stack: [{ nextBefore: null }] }, "older");
  assert.equal(paged.needsFetch, false);
});

test("Newer at the boundary restores the live head", () => {
  // one page deep -> Newer pops it and returns to the head (client-buffered, no fetch).
  const next = Pet.historyPagingView({ atHead: false, stack: [{ entries: [{}] }] }, "newer");
  assert.equal(next.atHead, true);
  assert.equal(next.stack.length, 0); // .length, not deepEqual: stack is a cross-realm (vm) array
  assert.equal(next.needsFetch, false);
});

test("Newer mid-stack drops the current page but stays paged", () => {
  const stack = [{ id: "p1" }, { id: "p2" }];
  const next = Pet.historyPagingView({ atHead: false, stack }, "newer");
  assert.equal(next.atHead, false);
  assert.equal(next.stack.length, 1);
  assert.equal(next.stack[0].id, "p1");
  assert.equal(next.needsFetch, false);
  // pure: the input stack is not mutated.
  assert.equal(stack.length, 2);
});

test("head action resets straight to the live head", () => {
  const next = Pet.historyPagingView({ atHead: false, stack: [{}, {}] }, "head");
  assert.equal(next.atHead, true);
  assert.equal(next.stack.length, 0); // .length, not deepEqual: stack is a cross-realm (vm) array
});

test("paged-back label is positional and asserts NO numeric total (D-RESTART)", () => {
  const label = Pet.historyPageLabel({ entries: [{ scan_id: "s-1" }], olderTruncated: false });
  assert.equal(label, "older history");
  assert.equal(/\d/.test(label), false); // never an "of N" total
});

test("empty paged response is retention-honest (D-ROTATION / edge F-2)", () => {
  // reclaimed cursor (segment aged out) -> "no older retained history", never a flat absolute.
  assert.equal(
    Pet.historyPageLabel({ entries: [], olderTruncated: true }),
    "no older retained history"
  );
  // true bottom -> "no older history".
  assert.equal(
    Pet.historyPageLabel({ entries: [], olderTruncated: false }),
    "no older history"
  );
});

test("the head subtitle stays scanHistorySubtitle (the only 'of N' total)", () => {
  // The live head keeps the PET-144 honest subtitle; paged views never compute a total.
  assert.equal(Pet.scanHistorySubtitle(500, 1200), "showing last 500 of 1200");
});
