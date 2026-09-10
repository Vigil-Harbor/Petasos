// Shared console test harness (PET-182). Node built-ins only.
// Owns source loading and the base DOM; suites opt into their audited surfaces.
// Fetch, timers, storage, SDKs and lifecycle fixtures remain caller-owned.
import { readFileSync } from "node:fs";
import vm from "node:vm";

export const consoleSource = readFileSync(new URL("../../petasos/console/static/petasos.js", import.meta.url), "utf8");

// Suites supply fresh sandboxes when they need fresh realms; no globals are added.
// Compare realm objects by keys/values, not host-realm prototype identity.
export function loadConsole(sandbox) {
  vm.runInNewContext(consoleSource, sandbox);
  return sandbox.window.__PETASOS_CONSOLE__;
}

// This is deliberately a small test DOM, not a browser implementation. Appends
// do not reparent or flatten fragments. Options preserve existing shim behavior,
// including absent APIs and the different empty/null text assignment semantics.
export function createDOM(options = {}) {
  const tree = options.tree || {};
  function makeNode(nodeType) {
    const node = {
      nodeType,
      childNodes: [],
      appendChild(child) {
        if (tree.parents) child.parentNode = this;
        this.childNodes.push(child);
        return child;
      },
    };
    if (options.styled !== false) Object.assign(node, { style: {}, className: "" });
    if (options.title) node.title = "";
    if (options.dataset) node.dataset = {};
    if (options.tabIndex) node.tabIndex = undefined;
    if (tree.parents) node.parentNode = null;
    if (tree.remove) node.removeChild = function (child) {
      const i = this.childNodes.indexOf(child);
      if (i !== -1) this.childNodes.splice(i, 1);
      if (tree.parents) child.parentNode = null;
      return child;
    };
    if (tree.detach) node.remove = function () {
      if (this.parentNode) this.parentNode.removeChild(this);
    };
    if (tree.insert) node.insertBefore = function (child, ref) {
      if (tree.parents) child.parentNode = this;
      const i = ref ? this.childNodes.indexOf(ref) : -1;
      if (i < 0) this.childNodes.push(child);
      else this.childNodes.splice(i, 0, child);
      return child;
    };
    if (tree.first) Object.defineProperty(node, "firstChild", {
      enumerable: true, configurable: true,
      get() { return this.childNodes[0] || null; },
    });

    const attrs = options.attributes;
    if (attrs === "noop") node.setAttribute = function () {};
    else if (attrs) {
      const key = attrs === "record" ? "attributes" : "attrs";
      node[key] = {};
      node.setAttribute = function (k, v) { this[key][k] = attrs === "raw" ? v : String(v); };
      if (attrs !== "raw") node.getAttribute = function (k) {
        return attrs === "record" && !Object.prototype.hasOwnProperty.call(this[key], k)
          ? null : this[key][k];
      };
      if (attrs !== "record") node.removeAttribute = function (k) { delete this[key][k]; };
    }
    if (options.events === "noop") node.addEventListener = function () {};
    if (options.events === "record") {
      node.handlers = {};
      node.addEventListener = function (type, fn) {
        (this.handlers[type] = this.handlers[type] || []).push(fn);
      };
    }
    if (options.selectors) node.querySelector = function () { return null; };
    if (options.selectors === "empty") node.querySelectorAll = function () { return []; };

    const text = options.textContent;
    if (text === "stored") node._text = "";
    if (text) {
      const descriptor = {
        enumerable: true, configurable: true,
        get() {
          if (this.nodeType === 3) return this.nodeValue;
          return this.childNodes.map((c) => c.textContent).join("") +
            (text === "stored" ? (this._text || "") : "");
        },
      };
      if (text !== "readonly") descriptor.set = function (v) {
        if (text === "strict") throw new Error(
          "PET-103 D10: textContent assignment is banned in this shim — pass the " +
          "message as a Pet.h text child, not `errEl.textContent = ...`."
        );
        if (text === "stored") {
          this._text = String(v);
          this.childNodes = [];
          return;
        }
        this.childNodes = [];
        const s = text === "clear" && v == null ? "" : String(v);
        if (text === "clear" && s === "") return;
        const child = makeNode(3);
        child.nodeValue = s;
        if (tree.parents) child.parentNode = this;
        this.childNodes.push(child);
      };
      Object.defineProperty(node, "textContent", descriptor);
    }
    if (options.innerHTML) {
      const descriptor = {
        enumerable: true, configurable: true,
        set(_v) { this.childNodes = []; },
      };
      if (options.innerHTML === "readWrite") descriptor.get = function () { return ""; };
      Object.defineProperty(node, "innerHTML", descriptor);
    }
    if (options.extendNode) options.extendNode(node);
    return node;
  }

  function makeDocument() {
    const document = {
      createDocumentFragment() { return makeNode(11); },
      createElement(tag) {
        const el = makeNode(1);
        el.tagName = tag.toUpperCase();
        if (options.localName !== false) el.localName = tag;
        return el;
      },
      createTextNode(t) {
        const node = makeNode(3);
        node.nodeValue = String(t);
        return node;
      },
    };
    if (options.svg) document.createElementNS = function (ns, tag) {
      if (options.svg === "alias") return this.createElement(tag);
      const el = makeNode(1);
      el.tagName = tag.toUpperCase();
      el.localName = tag;
      el.namespaceURI = ns;
      return el;
    };
    if (options.head) document.head = makeNode(1);
    if (options.currentScript === null) document.currentScript = null;
    return document;
  }
  return { makeNode, makeDocument };
}
