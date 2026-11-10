// ---------------------------------------------------------------------------
// The tab: four views under one row of Hermes's enclosed tabs, and the
// states that come before any view (loading, Petasos not answering).
// ---------------------------------------------------------------------------

var VIEW_TABS = [
  { value: "overview", label: "Overview" },
  { value: "activity", label: "Activity" },
  { value: "tryit", label: "Try it" },
  { value: "settings", label: "Settings" },
];

function Unreachable(props) {
  var failure = props.failure;
  var notMounted = failure.status === 404;
  return h(
    Panel,
    { title: notMounted ? "Petasos's part of the dashboard is not loaded" : "Petasos is not answering" },
    h(
      "p",
      null,
      notMounted
        ? "Hermes loads this tab's data only for a plugin it is running. Petasos is switched off in Hermes's plugin list, or was switched on after the dashboard started."
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
      notMounted ? h("a", { className: "petasos-link", href: "/plugins" }, "Open Plugins") : null
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
  // Staged settings live here, so moving between views keeps them.
  var draftState = useState(EMPTY_DRAFT);
  var draft = draftState[0];
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

  // Leaving the page with staged settings asks first.
  var dirty = !draftIsEmpty(draft);
  useEffect(
    function () {
      if (!dirty) return;
      function warn(event) {
        event.preventDefault();
        event.returnValue = "";
        return "";
      }
      window.addEventListener("beforeunload", warn);
      return function () {
        window.removeEventListener("beforeunload", warn);
      };
    },
    [dirty]
  );

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
        toast.showToast(saved.restart_message || "Saved", "success");
        onSaved(saved);
        return saved;
      })
      .catch(function (failure) {
        if (failure.code === "managed") lockedState[1](failure.message);
        toast.showToast(failure.message, "error");
        throw failure;
      });
  }

  function stage(candidate) {
    var next = { overrides: {} };
    if (candidate.enabled !== undefined) next.enabled = candidate.enabled;
    if (candidate.role) next.role = candidate.role;
    if (candidate.level) next.level = candidate.level;
    if (candidate.overrides) next.overrides = clone(candidate.overrides);
    draftState[1](next);
  }

  var view = route.view;
  var locked = Boolean(lockedState[0]);
  var body;
  if (!status && failureState[0]) {
    body = h(Unreachable, { failure: failureState[0], onRetry: refreshAll });
  } else if (!status) {
    body = h("p", { className: "petasos-help", role: "status" }, "Loading Petasos…");
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
      body = h(
        TryIt,
        Object.assign({ key: (route.params.example || "") + "|" + (route.params.settings || "") + "|" + (route.params.rule || ""), onStage: stage }, shared)
      );
    else if (view === "settings")
      body = h(
        Settings,
        Object.assign(
          { key: (route.params.rule || "") + "|" + (route.params.review || "") + "|" + (route.params.changed || ""), draft: draft, setDraft: draftState[1] },
          shared
        )
      );
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

  var paused = Boolean(status && (status.paused || (status.switches && status.switches.petasos && status.switches.petasos.on === false)));
  var viewLabel = (VIEW_TABS.filter(function (tab) {
    return tab.value === view;
  })[0] || VIEW_TABS[0]).label;

  return h(
    "div",
    { className: cn("petasos", light && "petasos-light") },
    h(C.Toast, { toast: toast.toast }),
    h(
      "div",
      { className: "petasos-topbar" },
      h(
        "div",
        { className: "petasos-topbar-main" },
        h(ViewTabs, {
          label: "Petasos views",
          views: VIEW_TABS,
          value: view,
          onChange: function (value) {
            go(value);
          },
        }),
        paused ? h(Status, { tone: "warning", state: "paused" }, "Paused") : null,
        dirty && view !== "settings"
          ? h(
              "button",
              { type: "button", className: "petasos-unsaved", onClick: function () { go("settings"); } },
              "Unsaved settings changes"
            )
          : null
      ),
      h(
        "div",
        { className: "petasos-topbar-side" },
        failureState[0] && status ? h(Status, { tone: "warning", title: failureState[0].message }, "Last check failed") : null,
        checkedState[0] ? h("span", { className: "petasos-help" }, "Checked " + whenText(checkedState[0] / 1000)) : null,
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
          "Actions run unchecked. Each one is recorded."
        )
      : null,
    h(
      "div",
      { className: "petasos-view", id: "petasos-panel", role: "tabpanel", "aria-labelledby": "petasos-tab-" + view, "aria-label": viewLabel },
      body
    ),
    h(C.ConfirmDialog, {
      open: pauseState[0],
      title: "Pause protection?",
      description:
        "Until you resume, the agent's actions run unchecked. Each one is still recorded in Activity. Applies from the agent's next action.",
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
