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
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function PetasosTab() {
    var ref = SDK.hooks.useRef(null);
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
      });
      return function () {
        cancelled = true;
        if (window.__PETASOS_CONSOLE__) window.__PETASOS_CONSOLE__.unmount();
      };
    }, []);
    return h("div", { ref: ref, className: "pet", style: { height: "100%" } });
  }

  window.__HERMES_PLUGINS__.register("petasos", PetasosTab);
})();
