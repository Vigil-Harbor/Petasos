/* petasos-plugin.js - Hermes Dashboard plugin bridge (IIFE, no build step).
   Loads the ordered console scripts and mounts only a complete namespace. */
(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;

  var CONSOLE_SCRIPT_FILES = [
    "petasos-core.js",
    "petasos-transport.js",
    "petasos-observability.js",
    "petasos-dashboard.js",
    "petasos-playground.js",
    "petasos-config.js",
    "petasos-shell.js",
  ];
  var CONSOLE_BASE = "/dashboard-plugins/petasos/dist/";

  function isReady(Pet) {
    return !!(Pet && Pet._moduleState && Pet._moduleState.ready === true);
  }

  function moduleName(filename) {
    return filename.slice("petasos-".length, -".js".length);
  }

  function loadScript(src, expected) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = function () {
        var Pet = window.__PETASOS_CONSOLE__;
        var actual = Pet && Pet._moduleState ? Pet._moduleState.last : "missing";
        if (actual !== expected) {
          reject(new Error("Failed to initialize script " + src + ": expected module " + expected + ", got " + actual));
          return;
        }
        resolve();
      };
      s.onerror = function (ev) {
        reject(new Error("Failed to load script " + src + (ev && ev.message ? ": " + ev.message : "")));
      };
      document.head.appendChild(s);
    });
  }

  function loadConsoleScripts() {
    var cached = window.__PETASOS_CONSOLE__;
    if (isReady(cached)) return Promise.resolve(cached);
    if (window.__PETASOS_CONSOLE_LOADING__) return window.__PETASOS_CONSOLE_LOADING__;

    // A failed attempt may leave a partial namespace. Core always starts a retry
    // from a clean object; inert script elements from the old attempt are harmless.
    if (cached) window.__PETASOS_CONSOLE__ = undefined;

    var sequence = CONSOLE_SCRIPT_FILES.reduce(function (chain, filename) {
      return chain.then(function () {
        var src = CONSOLE_BASE + filename;
        return loadScript(src, moduleName(filename));
      });
    }, Promise.resolve()).then(function () {
      var Pet = window.__PETASOS_CONSOLE__;
      if (!isReady(Pet)) {
        throw new Error("Petasos console did not become ready after " + CONSOLE_BASE + CONSOLE_SCRIPT_FILES[CONSOLE_SCRIPT_FILES.length - 1]);
      }
      return Pet;
    });

    var attempt = sequence.then(function (Pet) {
      if (window.__PETASOS_CONSOLE_LOADING__ === attempt) window.__PETASOS_CONSOLE_LOADING__ = null;
      return Pet;
    }, function (err) {
      if (window.__PETASOS_CONSOLE_LOADING__ === attempt) window.__PETASOS_CONSOLE_LOADING__ = null;
      throw err;
    });
    window.__PETASOS_CONSOLE_LOADING__ = attempt;
    return attempt;
  }

  function PetasosTab() {
    var ref = SDK.hooks.useRef(null);
    var errorState = SDK.hooks.useState(null);
    SDK.hooks.useEffect(function () {
      var cancelled = false;
      var mountAttempted = false;
      var owner = {};

      function teardown(Pet) {
        if (!mountAttempted || !isReady(Pet)) return;
        if (window.__PETASOS_CONSOLE_MOUNT_OWNER__ !== owner) return;
        try {
          if (typeof Pet.unmount === "function") Pet.unmount();
        } catch (_) {
          // React cleanup must remain non-throwing even if a host-provided seam fails.
        } finally {
          if (window.__PETASOS_CONSOLE_MOUNT_OWNER__ === owner) {
            window.__PETASOS_CONSOLE_MOUNT_OWNER__ = null;
          }
        }
      }

      loadConsoleScripts().then(function (Pet) {
        if (cancelled || !ref.current) return;
        if (!isReady(Pet)) throw new Error("Petasos console is incomplete and cannot mount");
        Pet.api.baseUrl = "/api/plugins/petasos";
        mountAttempted = true;
        window.__PETASOS_CONSOLE_MOUNT_OWNER__ = owner;
        try {
          Pet.mount(ref.current);
        } catch (err) {
          teardown(Pet);
          throw err;
        }
      }).catch(function (err) {
        if (!cancelled) errorState[1](err.message || "Failed to load Petasos console");
      });

      return function () {
        cancelled = true;
        teardown(window.__PETASOS_CONSOLE__);
      };
    }, []);

    if (errorState[0]) {
      return h("div", { style: { padding: "2rem", textAlign: "center", color: "#ed4245" } },
        h("p", { style: { fontWeight: 600 } }, "Petasos console failed to load"),
        h("p", { style: { fontSize: "0.85rem", color: "#6b7178" } }, errorState[0]),
        h("button", {
          onClick: function () { errorState[1](null); location.reload(); },
          style: { marginTop: "1rem", padding: "0.4rem 1rem", cursor: "pointer" },
        }, "Retry")
      );
    }
    return h("div", { ref: ref, className: "pet", style: { height: "100%" } });
  }

  window.__HERMES_PLUGINS__.register("petasos", PetasosTab);
})();
