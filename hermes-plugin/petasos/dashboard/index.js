(function () {
  var plugins = window.__HERMES_PLUGINS__;
  var SDK = window.__HERMES_PLUGIN_SDK__;
  if (!plugins || !SDK || !SDK.React) {
    return;
  }
  var React = SDK.React;
  function PetasosStatus() {
    var state = React.useState(null);
    var status = state[0];
    var setStatus = state[1];
    var errorState = React.useState("");
    var error = errorState[0];
    var setError = errorState[1];
    React.useEffect(function () {
      SDK.fetchJSON("/api/plugins/petasos/status").then(setStatus).catch(function (err) {
        setError(err && err.message ? err.message : "Petasos status is unavailable.");
      });
    }, []);
    var body;
    if (error) {
      body = React.createElement("p", null, error);
    } else if (!status) {
      body = React.createElement("p", null, "Loading Petasos status.");
    } else {
      body = React.createElement(
        "pre",
        { style: { fontFamily: "var(--font-mono, monospace)", whiteSpace: "pre-wrap" } },
        JSON.stringify(status, null, 2)
      );
    }
    return React.createElement(
      "section",
      { style: { color: "var(--color-text)" } },
      React.createElement("h1", null, "Petasos"),
      body
    );
  }
  plugins.register("petasos", PetasosStatus);
})();
