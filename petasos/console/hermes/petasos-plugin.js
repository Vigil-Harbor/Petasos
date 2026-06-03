/* petasos-plugin.js — Hermes Dashboard plugin bridge (IIFE, no build step).
   Loads the core petasos.js dynamically and mounts it into the React tree. */
(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function (ev) {
        reject(new Error("Failed to load script " + src + (ev && ev.message ? ": " + ev.message : "")));
      };
      document.head.appendChild(s);
    });
  }

  function PetasosTab() {
    var ref = SDK.hooks.useRef(null);
    var errorState = SDK.hooks.useState(null);
    SDK.hooks.useEffect(function () {
      var cancelled = false;
      (window.__PETASOS_CONSOLE__
        ? Promise.resolve()
        : loadScript("/dashboard-plugins/petasos/dist/petasos.js")
      ).then(function () {
        if (!cancelled && ref.current && window.__PETASOS_CONSOLE__) {
          window.__PETASOS_CONSOLE__.api.baseUrl = "/api/plugins/petasos";
          window.__PETASOS_CONSOLE__.mount(ref.current);
        }
      }).catch(function (err) {
        if (!cancelled) errorState[1](err.message || "Failed to load Petasos console");
      });
      return function () {
        cancelled = true;
        if (window.__PETASOS_CONSOLE__) window.__PETASOS_CONSOLE__.unmount();
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
