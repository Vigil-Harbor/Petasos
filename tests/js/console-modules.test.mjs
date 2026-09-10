// PET-183 regression coverage for ordered classic-script console modules.
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";

import {
  consoleScriptFiles,
  consoleSources,
  createDOM,
  loadConsole,
} from "./harness.mjs";

const indexSource = readFileSync(
  new URL("../../petasos/console/static/index.html", import.meta.url),
  "utf8",
);
const pluginSource = readFileSync(
  new URL("../../petasos/console/hermes/petasos-plugin.js", import.meta.url),
  "utf8",
);
const embeddedBase = "/dashboard-plugins/petasos/dist/";

function pluginFiles() {
  const block = /var CONSOLE_SCRIPT_FILES = \[([\s\S]*?)\];/.exec(pluginSource);
  assert.ok(block, "Hermes loader declares CONSOLE_SCRIPT_FILES");
  return [...block[1].matchAll(/"([^"]+\.js)"/g)].map((match) => match[1]);
}

function standaloneFiles() {
  return [...indexSource.matchAll(/<script src="\/static\/([^"]+\.js)"><\/script>/g)]
    .map((match) => match[1]);
}

function makeEvalContext(src = "https://example.test/static/petasos-core.js") {
  const sandbox = { window: {}, document: { currentScript: { src } } };
  return { sandbox, context: vm.createContext(sandbox) };
}

function runEntry(context, entry) {
  vm.runInContext(entry.source, context, { filename: entry.filename });
}

function executableText(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/\/\/[^\r\n]*/g, " ")
    .replace(/"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g, " ");
}

test("runtime loaders and harness share the exact seven-file order", () => {
  assert.deepEqual(standaloneFiles(), consoleScriptFiles);
  assert.deepEqual(pluginFiles(), consoleScriptFiles);
  assert.doesNotMatch(indexSource, /\/static\/petasos\.js/);
  assert.doesNotMatch(pluginSource, /\/dist\/petasos\.js/);
});

test("every module declares ownership, dependencies, isolation, and stays bounded", () => {
  for (const { filename, source } of consoleSources) {
    assert.match(source, /^\/\*[^\n]*Owns:[^\n]*Depends on:[^\n]*\*\/\r?\n\(function \(\) \{\r?\n  "use strict";/, filename);
    assert.match(source, /\}\)\(\);\s*$/, filename);
    assert.ok(source.split(/\r?\n/).length <= 1400, `${filename} exceeds 1,400 lines`);
  }
});

test("readiness advances only through the ordered module chain", () => {
  const first = makeEvalContext();
  runEntry(first.context, consoleSources[0]);
  assert.deepEqual(
    { ...first.sandbox.window.__PETASOS_CONSOLE__._moduleState },
    { last: "core", ready: false },
  );
  assert.throws(
    () => runEntry(first.context, consoleSources[2]),
    /petasos-observability expected module transport, got core/,
  );

  const reordered = makeEvalContext();
  runEntry(reordered.context, consoleSources[0]);
  runEntry(reordered.context, consoleSources[1]);
  assert.throws(
    () => runEntry(reordered.context, consoleSources[3]),
    /petasos-dashboard expected module observability, got transport/,
  );

  const sandbox = { window: {}, document: { currentScript: null } };
  const Pet = loadConsole(sandbox);
  assert.equal(Pet._moduleState.last, "shell");
  assert.equal(Pet._moduleState.ready, true);
});

test("core captures standalone and embedded asset bases from its own script URL", () => {
  for (const [src, expected] of [
    ["https://host/static/petasos-core.js", "https://host/static/img/petasos-helmet.png"],
    ["https://host/dashboard-plugins/petasos/dist/petasos-core.js", "https://host/dashboard-plugins/petasos/dist/img/petasos-helmet.png"],
  ]) {
    const loaded = makeEvalContext(src);
    runEntry(loaded.context, consoleSources[0]);
    assert.equal(loaded.sandbox.window.__PETASOS_CONSOLE__.asset("img/petasos-helmet.png"), expected);
  }
});

test("retired shared identifiers have no bare executable reads", () => {
  const retired = [
    "_container", "_scopeGen", "_scopePollTimer", "_cfgRenderGen",
    "_historySeeded", "_historyPaging", "_historyPagingGen", "_healthLoaded",
    "_armedSeeded", "_armedBusy", "_armedConfirmPending", "_armedConfirmTimer",
    "_adoptHistoryScope", "_adoptReadScope", "_scopeGuardHistory",
    "_invalidateScopeState", "clearArmedConfirm",
  ];
  for (const { filename, source } of consoleSources) {
    const code = executableText(source);
    for (const identifier of retired) {
      assert.doesNotMatch(code, new RegExp(`(^|[^.$\\w])${identifier}\\b`), `${identifier} is bare in ${filename}`);
    }
  }
  assert.equal(consoleSources.filter(({ source }) => /var SEV\s*=/.test(source)).length, 1);
  assert.match(consoleSources[2].source, /var SEV\s*=/);
  assert.match(consoleSources[2].source, /Pet\.SevBadge\s*=/);
  assert.equal(consoleSources.filter(({ source }) => /Pet\._runtime\s*=/.test(source)).length, 1);
});

function selectorMatches(node, selector) {
  if (node.nodeType !== 1) return false;
  if (selector.startsWith(".")) {
    return (node.className || "").split(/\s+/).includes(selector.slice(1));
  }
  if (selector.startsWith("[")) {
    const match = /^\[([^=\]]+)(?:=["']([^"']*)["'])?\]$/.exec(selector);
    if (!match) return false;
    const attr = match[1];
    const key = attr.startsWith("data-")
      ? attr.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())
      : attr;
    const value = node.dataset?.[key] ?? node.attributes?.[attr];
    return match[2] === undefined ? value !== undefined : String(value) === match[2];
  }
  return node.tagName === selector.toUpperCase();
}

function matchingDescendants(root, selector) {
  const found = [];
  const walk = (node) => {
    for (const child of node.childNodes || []) {
      if (selectorMatches(child, selector)) found.push(child);
      walk(child);
    }
  };
  walk(root);
  return found;
}

function renderDOM() {
  return createDOM({
    title: true,
    dataset: true,
    tabIndex: true,
    attributes: "record",
    events: "record",
    textContent: "replace",
    innerHTML: "readWrite",
    svg: "namespace",
    head: true,
    tree: { parents: true, remove: true, detach: true, insert: true, first: true },
    extendNode(node) {
      Object.assign(node, {
        value: undefined,
        disabled: false,
        removeAttribute(name) { delete this.attributes?.[name]; },
        querySelector(selector) { return matchingDescendants(this, selector)[0] || null; },
        querySelectorAll(selector) { return matchingDescendants(this, selector); },
      });
    },
  });
}

test("standalone order executes and all four tabs render in one audited realm", async () => {
  const { makeDocument } = renderDOM();
  const document = makeDocument();
  document.currentScript = { src: `https://host/static/${standaloneFiles()[0]}` };
  const location = { search: "", href: "https://host/", pathname: "/", hash: "" };
  const window = {
    location,
    history: { pushState() {}, replaceState() {} },
    console: { warn() {}, error() {}, log() {} },
    innerHeight: 900,
    innerWidth: 1400,
    addEventListener() {},
    removeEventListener() {},
  };
  const sandbox = {
    window,
    document,
    console: window.console,
    URLSearchParams,
    AbortController,
    TextDecoder,
    setTimeout: () => 1,
    clearTimeout() {},
    setInterval: () => 1,
    clearInterval() {},
    fetch: () => Promise.resolve({
      ok: true,
      status: 200,
      statusText: "OK",
      body: null,
      json: () => Promise.resolve({}),
    }),
  };
  const Pet = loadConsole(sandbox);
  Pet.sse.connect = function () {};
  Pet.hostProfile.attach = function () {};
  Pet.hostProfile.detach = function () {};
  Pet._poll.startHealth = function () {};
  Pet._poll.stopHealth = function () {};
  const root = document.createElement("div");
  Pet.mount(root);
  for (const tab of ["obs", "play", "cfg", "about"]) {
    Pet.switchTab(tab);
    assert.ok(Pet._runtime.container.childNodes.length > 0, `${tab} rendered no children`);
  }
  await flush();
  const images = matchingDescendants(root, "img").map((node) => node.src);
  assert.ok(images.some((src) => String(src).startsWith("https://host/static/")));
  Pet.unmount();
  await flush();
});

async function flush(count = 30) {
  for (let i = 0; i < count; i += 1) await Promise.resolve();
}

function hermesHarness(options = {}) {
  const requests = [];
  const errors = [];
  const effects = [];
  const mounts = [];
  let unmounts = 0;
  let component;
  let currentHost;
  let paused;
  let context;
  const failure = { current: options.failure || null };

  const document = {
    currentScript: null,
    createElement() { return {}; },
    head: {
      appendChild(script) {
        requests.push(script.src);
        const filename = script.src.slice(script.src.lastIndexOf("/") + 1);
        const configured = failure.current;
        if (configured && configured.filename === filename && configured.kind === "network") {
          queueMicrotask(() => script.onerror({ message: "network" }));
          return script;
        }
        document.currentScript = script;
        if (!(configured && configured.filename === filename && configured.kind === "evaluation")) {
          const entry = consoleSources.find((candidate) => candidate.filename === filename);
          assert.ok(entry, filename);
          runEntry(context, entry);
        }
        if (options.pauseAt === filename && !paused) {
          paused = script.onload;
        } else {
          queueMicrotask(script.onload);
        }
        return script;
      },
    },
  };
  const hooks = {
    useRef() { return { current: currentHost }; },
    useState() { return [null, (value) => errors.push(value)]; },
    useEffect(effect) { effects.push(effect()); },
  };
  const window = {
    __HERMES_PLUGIN_SDK__: {
      React: { createElement: (type, props, ...children) => ({ type, props, children }) },
      hooks,
    },
    __HERMES_PLUGINS__: { register(_name, registered) { component = registered; } },
  };
  context = vm.createContext({ window, document, console, Promise, setTimeout, clearTimeout });
  vm.runInContext(pluginSource, context, { filename: "petasos-plugin.js" });

  function installMountSpy() {
    const Pet = window.__PETASOS_CONSOLE__;
    if (!Pet || !Pet._moduleState?.ready || Pet.__mountSpyInstalled) return;
    Pet.__mountSpyInstalled = true;
    Pet.mount = function (host) {
      mounts.push(host);
      if (options.mountThrows) throw new Error("mount exploded");
    };
    Pet.unmount = function () { unmounts += 1; };
  }

  // Wrap script completion so the ready namespace receives lifecycle spies before
  // the loader's final continuation can mount it.
  const originalAppend = document.head.appendChild;
  document.head.appendChild = function (script) {
    const originalLoad = script.onload;
    script.onload = function () {
      installMountSpy();
      originalLoad();
    };
    return originalAppend.call(this, script);
  };

  return {
    window,
    requests,
    errors,
    mounts,
    failure,
    render(host = {}) {
      currentHost = host;
      component();
      return effects[effects.length - 1];
    },
    release() {
      assert.ok(paused, "no paused script load");
      const resume = paused;
      paused = null;
      queueMicrotask(resume);
    },
    unmountCount() { return unmounts; },
  };
}

test("Hermes cancellation and concurrent effects share one ordered load", async () => {
  const harness = hermesHarness({ pauseAt: "petasos-core.js" });
  const cancelledCleanup = harness.render({ id: "cancelled" });
  await flush();
  const attempt = harness.window.__PETASOS_CONSOLE_LOADING__;
  assert.ok(attempt);
  const survivorCleanup = harness.render({ id: "survivor" });
  assert.equal(harness.window.__PETASOS_CONSOLE_LOADING__, attempt);
  cancelledCleanup();
  harness.release();
  await flush();
  assert.deepEqual(harness.requests, consoleScriptFiles.map((name) => embeddedBase + name));
  assert.equal(harness.mounts.length, 1);
  assert.equal(harness.mounts[0].id, "survivor");
  assert.equal(harness.window.__PETASOS_CONSOLE__.api.baseUrl, "/api/plugins/petasos");
  assert.equal(harness.window.__PETASOS_CONSOLE__.asset("img/x.png"), embeddedBase + "img/x.png");
  survivorCleanup();
  assert.equal(harness.unmountCount(), 1);
});

test("Hermes cleanup during module loading is inert", async () => {
  const harness = hermesHarness({ pauseAt: "petasos-core.js" });
  const cleanup = harness.render();
  await flush();
  assert.doesNotThrow(cleanup);
  harness.release();
  await flush();
  assert.equal(harness.mounts.length, 0);
  assert.equal(harness.unmountCount(), 0);
});

test("Hermes failures stop at the exact URL and retry from core", async (t) => {
  for (const failure of [
    { filename: "petasos-core.js", kind: "network" },
    { filename: "petasos-dashboard.js", kind: "evaluation" },
  ]) {
    await t.test(`${failure.kind} failure at ${failure.filename}`, async () => {
      const harness = hermesHarness({ failure });
      harness.render();
      await flush();
      const failedUrl = embeddedBase + failure.filename;
      assert.equal(harness.requests.at(-1), failedUrl);
      assert.equal(harness.requests.length, consoleScriptFiles.indexOf(failure.filename) + 1);
      assert.equal(harness.mounts.length, 0);
      assert.match(harness.errors.at(-1), new RegExp(failedUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
      assert.equal(harness.window.__PETASOS_CONSOLE_LOADING__, null);

      harness.failure.current = null;
      const beforeRetry = harness.requests.length;
      const cleanup = harness.render({ id: "retry" });
      await flush();
      assert.deepEqual(
        harness.requests.slice(beforeRetry),
        consoleScriptFiles.map((name) => embeddedBase + name),
      );
      assert.equal(harness.mounts.length, 1);
      assert.equal(harness.window.__PETASOS_CONSOLE__._moduleState.ready, true);
      assert.equal(harness.window.__PETASOS_CONSOLE_LOADING__, null);
      cleanup();
      assert.equal(harness.unmountCount(), 1);
    });
  }
});

test("Hermes mount rollback tears down exactly once and preserves later owners", async () => {
  const harness = hermesHarness({ mountThrows: true });
  const failedCleanup = harness.render({ id: "failed" });
  await flush();
  assert.equal(harness.mounts.length, 1);
  assert.equal(harness.unmountCount(), 1);
  assert.match(harness.errors.at(-1), /mount exploded/);
  failedCleanup();
  assert.equal(harness.unmountCount(), 1);

  // A new component owns the cached ready namespace. The failed effect's cleanup
  // cannot tear down this later mount.
  harness.window.__PETASOS_CONSOLE__.mount = function (host) { harness.mounts.push(host); };
  const laterCleanup = harness.render({ id: "later" });
  await flush();
  assert.equal(harness.mounts.length, 2);
  failedCleanup();
  assert.equal(harness.unmountCount(), 1);
  laterCleanup();
  assert.equal(harness.unmountCount(), 2);
});

test("Hermes cleanup requires a callable unmount", async () => {
  const harness = hermesHarness();
  const cleanup = harness.render();
  await flush();
  assert.equal(harness.mounts.length, 1);
  harness.window.__PETASOS_CONSOLE__.unmount = null;
  assert.doesNotThrow(cleanup);
  assert.equal(harness.unmountCount(), 0);
});
