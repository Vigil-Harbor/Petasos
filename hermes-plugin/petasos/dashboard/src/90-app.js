// ---------------------------------------------------------------------------
// The tab: four views under one row of Hermes tabs, and the states that
// come before any view (loading, Petasos not answering).
// ---------------------------------------------------------------------------

var VIEW_LABELS = {
  overview: "Overview",
  activity: "Activity",
  tryit: "Try it",
  settings: "Settings",
};

function Unreachable(props) {
  var failure = props.failure;
  var notMounted = failure.status === 404;
  return h(
    Panel,
    { title: notMounted ? "Petasos's part of the dashboard is not loaded" : "Petasos is not answering" },
    h(
      "p",
      { className: "petasos-verdict-reason" },
      notMounted
        ? "Hermes loads this tab's data only for a plugin it is running. Petasos is either " +
            "switched off in Hermes's plugin list, or was switched on after the dashboard started."
        : "The dashboard could not get Petasos's status. " + (failure.message || "")
    ),
    h(
      "p",
      { className: "petasos-help" },
      notMounted
        ? "Turn Petasos on in Plugins, then restart the dashboard. Until then, tool calls are not being checked."
        : "This page tries again every 20 seconds. If it keeps failing, the dashboard's log has the detail."
    ),
    h(
      "div",
      { className: "petasos-row-actions" },
      h(Btn, { onClick: props.onRetry }, "Try again"),
      notMounted ? h("a", { className: "petasos-link", href: "/plugins" }, "Open Plugins →") : null
    )
  );
}

// True when the active Hermes theme has a light background. Hermes rewrites
// its colour variables on the root element when the theme changes.
function useLightTheme() {
  function measure() {
    var raw = window.getComputedStyle(document.documentElement).getPropertyValue("--background-base").trim();
    var match = raw.match(/^#([0-9a-f]{6})$/i);
    if (!match) return false;
    var n = parseInt(match[1], 16);
    var r = (n >> 16) & 255;
    var g = (n >> 8) & 255;
    var b = n & 255;
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140;
  }
  var state = useState(measure);
  useEffect(function () {
    var observer = new MutationObserver(function () {
      state[1](measure());
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["style", "class"] });
    return function () {
      observer.disconnect();
    };
  }, []);
  return state[0];
}

function PetasosTab() {
  var route = useRoute();
  var light = useLightTheme();
  var statusState = useState(null);
  var status = statusState[0];
  var failureState = useState(null);
  var catalogState = useState(null);
  var catalog = catalogState[0];
  var checkedState = useState(null);
  var refreshState = useState(0);
  var lockedState = useState(null);
  var pauseState = useState(false);
  var toast = SDK.hooks.useToast();

  var loadStatus = useCallback(function () {
    return call("/status")
      .then(function (body) {
        statusState[1](body);
        failureState[1](null);
        checkedState[1](Date.now());
      })
      .catch(function (failure) {
        failureState[1](failure);
      });
  }, []);
  var loadCatalog = useCallback(function () {
    return call("/settings")
      .then(catalogState[1])
      .catch(function () {});
  }, []);

  usePoll(loadStatus, 20000, []);
  useEffect(function () {
    loadCatalog();
  }, []);

  function refreshAll() {
    loadStatus();
    loadCatalog();
    refreshState[1](refreshState[0] + 1);
  }

  function onSaved(body) {
    if (body && body.settings) catalogState[1](body);
    loadCatalog();
    loadStatus();
    refreshState[1](refreshState[0] + 1);
  }

  function save(body) {
    return call("/settings", { method: "PUT", body: body })
      .then(function (saved) {
        toast.showToast("Saved", "success");
        onSaved(saved);
        return saved;
      })
      .catch(function (failure) {
        if (failure.code === "managed") lockedState[1](failure.message);
        toast.showToast(failure.message, "error");
        throw failure;
      });
  }

  var view = route.view;
  var locked = Boolean(lockedState[0]);
  var body;
  if (!status && failureState[0]) {
    body = h(Unreachable, { failure: failureState[0], onRetry: refreshAll });
  } else if (!status) {
    body = h("p", { className: "petasos-loading", role: "status" }, "Loading Petasos…");
  } else {
    var shared = {
      route: route,
      status: status,
      catalog: catalog,
      refreshKey: refreshState[0],
      locked: locked,
      lockedMessage: lockedState[0],
      onLocked: lockedState[1],
      onSaved: onSaved,
      onSave: save,
    };
    if (view === "activity") body = h(Activity, shared);
    // Try it and Settings start from what the link carried (an example, a
    // candidate, a rule), so a new link starts them afresh.
    else if (view === "tryit")
      body = h(TryIt, Object.assign({ key: (route.params.example || "") + "|" + (route.params.settings || "") }, shared));
    else if (view === "settings")
      body = h(Settings, Object.assign({ key: (route.params.stage || "") + "|" + (route.params.rule || "") }, shared));
    else
      body = h(
        Overview,
        Object.assign({}, shared, {
          onPause: function () {
            pauseState[1](true);
          },
          onResume: function () {
            save({ enabled: true }).catch(function () {});
          },
        })
      );
  }

  var paused = status && status.switches && status.switches.petasos && status.switches.petasos.on === false;

  return h(
    "div",
    { className: cn("petasos", light && "petasos-light") },
    h(C.Toast, { toast: toast.toast }),
    h(
      "div",
      { className: "petasos-topbar" },
      h(
        C.TabsList,
        { role: "tablist", "aria-label": "Petasos views", className: "petasos-tabs" },
        VIEWS.map(function (name) {
          return h(
            C.TabsTrigger,
            {
              key: name,
              value: name,
              active: view === name,
              role: "tab",
              "aria-selected": view === name,
              onClick: function () {
                go(name);
              },
            },
            VIEW_LABELS[name],
            name === "overview" && paused ? h("span", { className: "petasos-tab-flag" }, "\u00a0· Paused") : null
          );
        })
      ),
      h(
        "div",
        { className: "petasos-topbar-side" },
        failureState[0] && status
          ? h(Pill, { tone: "warning", title: failureState[0].message }, "Last check failed")
          : null,
        checkedState[0]
          ? h("span", { className: "petasos-help" }, "Checked " + whenText(checkedState[0] / 1000))
          : null,
        h(Btn, { ghost: true, onClick: refreshAll, "aria-label": "Refresh now" }, "Refresh")
      )
    ),
    paused && view !== "overview"
      ? h(
          Notice,
          {
            tone: "warning",
            title: "Protection is paused",
            action: h(Btn, { onClick: function () { save({ enabled: true }).catch(function () {}); }, disabled: locked }, "Resume"),
          },
          "Tool calls are going through unchecked and being recorded."
        )
      : null,
    h("div", { className: "petasos-view", role: "tabpanel", "aria-label": VIEW_LABELS[view] }, body),
    h(C.ConfirmDialog, {
      open: pauseState[0],
      title: "Pause protection?",
      description:
        "Until you resume, Petasos lets every tool call through without checking it. Each " +
        "one is still recorded in Activity. Hermes keeps running the plugin.",
      confirmLabel: "Pause",
      cancelLabel: "Keep protecting",
      destructive: true,
      onCancel: function () {
        pauseState[1](false);
      },
      onConfirm: function () {
        pauseState[1](false);
        save({ enabled: false }).catch(function () {});
      },
    })
  );
}

PLUGINS.register("petasos", PetasosTab);
