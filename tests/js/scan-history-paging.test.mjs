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

// ── PET-152 handler-integration helpers ──────────────────────────────────────
// Pet.pageHistoryOlder is the async two-fetch re-mint handler; these drive it over the real
// shipped petasos.js. The handler's in-flight guard (_historyPaging) and paging generation
// (_historyPagingGen) are module-private, so each handler test calls resetPagingState() first
// to clear the guard via the real exposed teardown (Pet.auth._enterAuthRequired) and
// re-establish a clean live-head context — making every test independent of what a prior test
// left in flight (e.g. the never-resolving fetch in the cross-guard test).
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
function makeRows(n, prefix) {
  const rows = [];
  for (let i = 0; i < n; i++) rows.push({ scan_id: (prefix || "s") + "-" + i });
  return rows;
}
function resetPagingState() {
  // The real, already-exposed teardown bumps _historyPagingGen and resets _historyPaging without
  // needing DOM (renderDashboard is gated on the null _container in this headless harness).
  Pet.renderDashboard = function () {};
  Pet.auth._enterAuthRequired();
  Pet.state.authRequired = false;
  Pet.state.armed = true;
  Pet.state.historyAtHead = true;
  Pet.state.historyStack = [];
  Pet.state.scanHistory = [];
  Pet.state.pipelineHealth = null;
  Pet.state.tab = "obs";
}

test("loader: petasos.js exposes the paging seams", () => {
  assert.equal(typeof Pet, "object");
  assert.equal(typeof Pet.historyPagingView, "function");
  assert.equal(typeof Pet.historyPageLabel, "function");
  // PET-152: the new seams + extracted handlers are on the namespace.
  assert.equal(typeof Pet.scanHistoryHasOlder, "function");
  assert.equal(typeof Pet.pageHistoryOlder, "function");
  assert.equal(typeof Pet.pageHistoryNewer, "function");
});

test("Older off the live head signals a re-mint, never a cached cursor (PET-152)", () => {
  // PET-152: off the head the reducer signals needsRemint instead of returning a (now-removed)
  // cached seed cursor — that cursor went stale after ring eviction and skipped a band of rows.
  const next = Pet.historyPagingView({ atHead: true, stack: [], bufferLength: 437 }, "older");
  assert.equal(next.needsRemint, true);
  assert.equal(next.cursor, null);      // no cursor is derivable; the reducer cannot hand back a stale one
  assert.equal(next.remintLimit, 437);  // the handler re-mints sized to the runtime buffer length
  assert.equal(next.needsFetch, false); // the re-mint is the handler's own fetch, not this plan's cursor fetch
  assert.equal(next.atHead, false);     // a re-mint leaves the live head
});

test("Older from a paged view advances to that page's next_before cursor", () => {
  const state = { atHead: false, stack: [{ entries: [{}], nextBefore: "1600.0~s-def" }] };
  const next = Pet.historyPagingView(state, "older");
  assert.equal(next.needsFetch, true);
  assert.equal(next.cursor, "1600.0~s-def"); // advances past the current page
});

test("Older at the retained bottom does not fetch (empty head; paged-view null cursor)", () => {
  // PET-152: empty live head (no buffered rows) — re-mint refused, no fetch (edges E-2/E-4).
  const atHead = Pet.historyPagingView({ atHead: true, stack: [], bufferLength: 0 }, "older");
  assert.equal(atHead.needsRemint, false);
  assert.equal(atHead.needsFetch, false);
  assert.equal(atHead.cursor, null);
  // paged view whose next_before is null (true bottom) — unchanged:
  const paged = Pet.historyPagingView({ atHead: false, stack: [{ nextBefore: null }] }, "older");
  assert.equal(paged.needsFetch, false);
  assert.equal(paged.needsRemint, false);
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

// ── PET-152: re-mint reducer, gate predicate, and two-fetch handler ───────────

test("older off the live head re-mints, never reuses a stale seed cursor (PET-152 gap closure)", () => {
  // Even handed a (now-removed) cached cursor field, the reducer ignores it: off the head it
  // returns NO cursor and signals a re-mint, so no stale seed cursor can ever be handed back.
  const next = Pet.historyPagingView(
    { atHead: true, stack: [], bufferLength: 200, headCursor: "1700.5~stale" },
    "older"
  );
  assert.equal(next.needsRemint, true);
  assert.equal(next.cursor, null);
  assert.equal(next.remintLimit, 200);
});

test("re-mint sizes the head fetch from runtime buffer length, not the literal 500 (D-DRIFT)", () => {
  assert.equal(
    Pet.historyPagingView({ atHead: true, stack: [], bufferLength: 312 }, "older").remintLimit,
    312
  );
});

test("scanHistoryHasOlder truth table (PET-152 gate)", () => {
  assert.equal(Pet.scanHistoryHasOlder(500, 1200), true);   // evicting: older rows exist
  assert.equal(Pet.scanHistoryHasOlder(500, 501), true);    // one evicted row (E-7 boundary)
  assert.equal(Pet.scanHistoryHasOlder(300, 300), false);   // the window holds everything
  assert.equal(Pet.scanHistoryHasOlder(500, 3), false);     // restart stale-low total (E-7)
  assert.equal(Pet.scanHistoryHasOlder(0, 5), false);       // empty live buffer (E-2)
  assert.equal(Pet.scanHistoryHasOlder(500, null), false);  // /health not loaded yet (E-5)
  assert.equal(Pet.scanHistoryHasOlder(500, undefined), false);
  assert.equal(Pet.scanHistoryHasOlder(500, NaN), false);
});

test("pageHistoryOlder re-mints then pages from the fresh boundary (post-eviction, seed -> evict -> older)", async () => {
  resetPagingState();
  const L = 500;
  Pet.state.scanHistory = makeRows(L, "live");          // a full, post-eviction live window
  Pet.state.pipelineHealth = { scans_total: 1200 };
  const calls = [];
  Pet.api.getScanHistory = function (limit, before) {
    calls.push({ limit: limit, before: before });
    if (before === undefined) {
      // fetch-1: the head re-mint off the in-memory ring. Entries are discarded; only next_before read.
      return Promise.resolve({ entries: makeRows(limit, "head"), next_before: "FRESH" });
    }
    // fetch-2: the older page from the on-disk sink, keyed on the RE-MINTED cursor.
    return Promise.resolve({ entries: makeRows(100, "older"), next_before: "OLDER" });
  };
  Pet.pageHistoryOlder();
  await flush();
  assert.equal(calls.length, 2);
  assert.equal(calls[0].limit, L);            // fetch-1 sized to the runtime buffer length
  assert.equal(calls[0].before, undefined);   // fetch-1 is `before`-absent (reads the ring)
  assert.equal(calls[1].before, "FRESH");     // fetch-2 pages from the re-minted boundary, not a seed value
  const top = Pet.state.historyStack[Pet.state.historyStack.length - 1];
  assert.equal(top.cursor, "FRESH");
  assert.equal(top.nextBefore, "OLDER");
  assert.equal(top.entries.length, 100);
  assert.equal(Pet.state.historyAtHead, false);
});

test("pageHistoryOlder clears the in-flight guard on a rejected re-mint fetch (E-3)", async () => {
  resetPagingState();
  Pet.state.scanHistory = makeRows(500, "live");
  Pet.state.pipelineHealth = { scans_total: 1200 };
  let calls = 0;
  let mode = "reject";
  Pet.api.getScanHistory = function (limit, before) {
    calls++;
    if (mode === "reject") return Promise.reject(new Error("transport down"));
    if (before === undefined) return Promise.resolve({ entries: [], next_before: "FRESH" });
    return Promise.resolve({ entries: makeRows(100, "older"), next_before: null });
  };
  Pet.pageHistoryOlder();
  await flush();
  assert.equal(calls, 1); // the rejected re-mint
  // The .catch must have cleared the guard — a subsequent click must be able to fetch again.
  mode = "ok";
  Pet.pageHistoryOlder();
  await flush();
  assert.ok(calls >= 3, "in-flight guard wedged after a rejected re-mint (calls=" + calls + ")");
});

test("pageHistoryOlder shows the honest empty state when the re-mint yields no cursor (E-6)", async () => {
  resetPagingState();
  Pet.state.scanHistory = makeRows(500, "live");
  Pet.state.pipelineHealth = { scans_total: 1200 };          // gate-true: older rows "exist"
  const calls = [];
  Pet.api.getScanHistory = function (limit, before) {
    calls.push({ limit: limit, before: before });
    return Promise.resolve({ entries: makeRows(limit, "head"), next_before: null }); // ring points nowhere
  };
  Pet.pageHistoryOlder();
  await flush();
  assert.equal(calls.length, 1); // no fetch-2 (no cursor to page with)
  const top = Pet.state.historyStack[Pet.state.historyStack.length - 1];
  assert.equal(Pet.historyPageLabel(top), "no older retained history");
  assert.equal(Pet.state.historyAtHead, false);
  assert.equal(top.nextBefore, null); // self-disables further "Older" (no re-click loop, bounded stack)
  // _historyPaging must be cleared: re-establish a live head and confirm a fresh re-mint fetches.
  Pet.state.historyAtHead = true;
  Pet.state.historyStack = [];
  Pet.pageHistoryOlder();
  await flush();
  assert.ok(calls.length >= 2, "in-flight guard not cleared after the E-6 empty push");
});

test("a sink rotation between the two fetches lands on the honest empty state (E-8)", async () => {
  resetPagingState();
  Pet.state.scanHistory = makeRows(500, "live");
  Pet.state.pipelineHealth = { scans_total: 1200 };
  const calls = [];
  Pet.api.getScanHistory = function (limit, before) {
    calls.push({ limit: limit, before: before });
    if (before === undefined) return Promise.resolve({ entries: makeRows(limit, "head"), next_before: "FRESH" });
    // fetch-2: the segment just older than FRESH was unlinked by a rotation between the fetches.
    return Promise.resolve({ entries: [], older_truncated: true });
  };
  Pet.pageHistoryOlder();
  await flush();
  assert.equal(calls.length, 2);
  assert.equal(calls[1].before, "FRESH");
  const top = Pet.state.historyStack[Pet.state.historyStack.length - 1];
  assert.equal(top.entries.length, 0);
  assert.equal(top.olderTruncated, true);
  assert.equal(Pet.historyPageLabel(top), "no older retained history"); // never a contiguous-looking page
  assert.equal(Pet.state.historyAtHead, false);
});

test("an in-flight Older blocks a Newer click (E-9 cross-guard, shared _historyPaging)", () => {
  resetPagingState();
  Pet.state.scanHistory = makeRows(500, "live");
  Pet.state.pipelineHealth = { scans_total: 1200 };
  // A paged-back context with one page, so a (wrongly) allowed Newer would pop back toward the head.
  Pet.state.historyAtHead = false;
  Pet.state.historyStack = [{ entries: makeRows(3, "p"), cursor: "C", nextBefore: "N" }];
  const pending = deferred(); // fetch never resolves -> _historyPaging stays set
  let calls = 0;
  Pet.api.getScanHistory = function () { calls++; return pending.promise; };
  Pet.pageHistoryOlder(); // advances the paged view; sets the shared in-flight guard
  assert.equal(calls, 1);
  Pet.pageHistoryNewer(); // must be ignored while the Older fetch is pending
  assert.equal(Pet.state.historyStack.length, 1); // NOT popped
  assert.equal(Pet.state.historyAtHead, false);   // still paged back
});

test("a re-mint that resolves after teardown does not push onto the reset stack (E-9 generation)", async () => {
  resetPagingState();
  Pet.state.scanHistory = makeRows(500, "live");
  Pet.state.pipelineHealth = { scans_total: 1200 };
  const d1 = deferred();
  let calls = 0;
  Pet.api.getScanHistory = function (limit, before) {
    calls++;
    if (before === undefined) return d1.promise; // fetch-1: controllable
    return Promise.resolve({ entries: makeRows(100, "older"), next_before: "OLDER" });
  };
  Pet.pageHistoryOlder(); // captures gen; fetch-1 pending
  assert.equal(calls, 1);
  // The real, already-exposed teardown (the :449 site) bumps the generation and resets the guard.
  Pet.auth._enterAuthRequired();
  Pet.state.authRequired = false;
  // Simulate the re-seed straight back to the live head that follows teardown.
  Pet.state.historyStack = [];
  Pet.state.historyAtHead = true;
  // Now let the stale fetch-1 resolve; its .then must see gen !== _historyPagingGen and bail.
  d1.resolve({ entries: makeRows(500, "head"), next_before: "FRESH" });
  await flush();
  assert.equal(Pet.state.historyStack.length, 0); // stale continuation dropped, nothing pushed
  assert.equal(Pet.state.historyAtHead, true);    // not flipped back to a paged view
  assert.equal(calls, 1);                          // fetch-2 never issued under the dead generation
});

test("_pushOlderPage tolerates a malformed older-page body (F-5)", async () => {
  for (const bad of [{}, { entries: null }]) {
    resetPagingState();
    Pet.state.scanHistory = makeRows(500, "live");
    Pet.state.pipelineHealth = { scans_total: 1200 };
    Pet.api.getScanHistory = function (limit, before) {
      if (before === undefined) return Promise.resolve({ entries: [], next_before: "FRESH" });
      return Promise.resolve(bad); // fetch-2: malformed
    };
    Pet.pageHistoryOlder();
    await flush();
    const top = Pet.state.historyStack[Pet.state.historyStack.length - 1];
    assert.equal(top.entries.length, 0);
    assert.equal(top.nextBefore, null);
    assert.match(Pet.historyPageLabel(top), /no older/); // honest empty state, no throw
  }
});

test("a non-OK sink fetch is a failed read, never an empty older page (F-6, _status gate)", async () => {
  // _req stamps `_status` on a parsed non-OK body; a 403/500 like {} carries NO `error`. The push
  // must NOT treat it as an empty older page (that would render a silent "no older history" on an
  // auth/server failure). Nothing is pushed and the in-flight guard clears so a retry can fetch.
  resetPagingState();
  Pet.state.scanHistory = makeRows(500, "live");
  Pet.state.pipelineHealth = { scans_total: 1200 };
  let calls = 0;
  Pet.api.getScanHistory = function (limit, before) {
    calls++;
    if (before === undefined) return Promise.resolve({ entries: makeRows(limit, "head"), next_before: "FRESH" });
    return Promise.resolve({ _status: 500 }); // fetch-2: server error, no `error` field, no entries
  };
  Pet.pageHistoryOlder();
  await flush();
  assert.equal(calls, 2);
  assert.equal(Pet.state.historyStack.length, 0); // failed read NOT pushed as an empty page
  assert.equal(Pet.state.historyAtHead, true);    // never left the live head (only _pushOlderPage flips it)
  // guard cleared: a fresh re-mint must be able to fetch again
  Pet.api.getScanHistory = function (limit, before) {
    calls++;
    if (before === undefined) return Promise.resolve({ entries: makeRows(limit, "head"), next_before: "FRESH" });
    return Promise.resolve({ entries: makeRows(100, "older"), next_before: "OLDER" });
  };
  Pet.pageHistoryOlder();
  await flush();
  assert.ok(calls >= 4, "in-flight guard wedged after a non-OK sink fetch (calls=" + calls + ")");
  assert.equal(Pet.state.historyStack.length, 1); // the retry pages cleanly
});

test("a non-OK paged-view fetch is a failed read, never an empty older page (F-6, _status gate)", async () => {
  resetPagingState();
  // Paged-back one level so the reducer takes the needsFetch (non-remint) branch.
  Pet.state.scanHistory = makeRows(500, "live");
  Pet.state.pipelineHealth = { scans_total: 1200 };
  Pet.state.historyAtHead = false;
  Pet.state.historyStack = [{ entries: makeRows(3, "p"), cursor: "C0", nextBefore: "C1" }];
  let calls = 0;
  Pet.api.getScanHistory = function () { calls++; return Promise.resolve({ _status: 403 }); };
  Pet.pageHistoryOlder();
  await flush();
  assert.equal(calls, 1);
  assert.equal(Pet.state.historyStack.length, 1); // unchanged: the 403 is not pushed as a new page
  // guard cleared: a subsequent click fetches again
  Pet.api.getScanHistory = function () { calls++; return Promise.resolve({ entries: makeRows(2, "q"), next_before: null }); };
  Pet.pageHistoryOlder();
  await flush();
  assert.equal(calls, 2);
  assert.equal(Pet.state.historyStack.length, 2);
});
