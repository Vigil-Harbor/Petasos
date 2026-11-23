
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
        ? "Turn Petasos on in Plugins, then restart the dashboard. Until this page loads, it cannot confirm whether tool calls are being checked."
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

// Hermes rewrites root colour variables when the theme changes.
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

// What the page says about protection while a change is unconfirmed: the last
// state it read is history, not the present.
function unconfirmed(verdict, pending) {
  return {
    code: "unconfirmed",
    tone: "warning",
    word: "Unconfirmed",
    title: "Petasos did not confirm the last change",
    reason:
      "This page cannot tell whether “" +
      pending.what +
      "” took effect. The last state it read was “" +
      verdict.word +
      "”, which may no longer be true.",
  };
}

// A change was saved, but the status could not be read afterwards. What the
// save itself settled (paused or not) is stated; nothing from the earlier
// reading is repeated as current.
function sinceSaved(status, catalog) {
  var enabled = !catalog || !catalog.stored || catalog.stored.enabled !== false;
  var wasPaused = Boolean(status.paused || (status.switches && status.switches.petasos && status.switches.petasos.on === false));
  if (!enabled) {
    return {
      code: "paused",
      tone: "warning",
      word: "Paused",
      title: "Pause is saved",
      reason: "Actions run unchecked. This page has not been able to read what Hermes is running or recording since the change.",
    };
  }
  return {
    code: "saved",
    tone: "warning",
    word: "Saved, not re-read",
    title: wasPaused ? "Resume is saved; the running state is unconfirmed" : "Settings saved; the running state is unconfirmed",
    reason: "This page has not been able to read what Hermes is running since the change.",
  };
}

// Any other write in flight: the reading on screen is from before it, and says so.
function savingOver(verdict, readAt) {
  return {
    code: "saving",
    was: verdict.code,
    tone: "warning",
    word: "Saving…",
    title: "Saving a change…",
    reason: "Before it, this page read “" + verdict.title + "”" + (readAt ? " at " + clockTime(readAt) : "") + ".",
  };
}

// Pause or Resume has been sent and not yet answered: neither the old state nor the new one is claimed.
function changing(what) {
  var pausing = what === "Pause protection";
  return {
    code: "changing",
    tone: "warning",
    word: pausing ? "Pausing…" : "Resuming…",
    title: pausing ? "Pausing protection…" : "Turning protection back on…",
    reason: "Waiting for Petasos to confirm.",
  };
}

// Pause or Resume, whichever control sent it, is read from the value being written.
function changeOf(payload, catalog) {
  if (!payload || typeof payload.enabled !== "boolean") return null;
  var enabled = !catalog || !catalog.stored || catalog.stored.enabled !== false;
  if (payload.enabled === enabled) return null;
  return payload.enabled ? "Resume protection" : "Pause protection";
}

// The status could not be re-read on the last attempt: what is shown is the
// reading before it, named as such.
function lastKnown(verdict, readAt) {
  return {
    code: "lastknown",
    tone: "warning",
    word: verdict.word + (readAt ? ", as of " + clock24(new Date(readAt)) : ", earlier"),
    title: "The last check failed",
    reason:
      "“" + verdict.title + "” is what this page read" + (readAt ? " at " + clockTime(readAt) : " earlier") + ". It has not been able to read the state since.",
  };
}

// The one rule for every view: the status is shown as current only when it was
// read after the last write settled and the last attempt to read it succeeded.
// `flags`: changing (a Pause or Resume in flight), saving (any write in flight),
// pending (a write with an unknown outcome), stale (saved, status not re-read),
// failed (the last status read failed), readAt.
function protectionView(status, catalog, flags) {
  var verdict = verdictOf(status);
  var shown = verdict;
  if (flags.changing) shown = changing(flags.changing);
  else if (flags.saving) shown = savingOver(verdict, flags.readAt);
  else if (flags.pending) shown = unconfirmed(verdict, flags.pending);
  else if (flags.stale) shown = sinceSaved(status, catalog);
  else if (flags.failed) shown = lastKnown(verdict, flags.readAt);
  return {
    verdict: shown,
    // Coverage, per-check states and anything else derived from the status reading.
    current: !flags.changing && !flags.saving && !flags.pending && !flags.stale && !flags.failed,
    waiting: Boolean(flags.saving || flags.changing),
  };
}

function PetasosTab() {
  var route = useRoute();
  var light = useLightTheme();
  var statusState = useState(null);
  var status = statusState[0];
  var failureState = useState(null);
  var catalogState = useState(null);
  var catalog = catalogState[0];
  var catalogFailureState = useState(null);
  var checkedState = useState(null);
  var refreshState = useState(0);
  var lockedState = useState(null);
  var pauseState = useState(false);
  // Staged settings outlive view changes.
  var draftState = useState(EMPTY_DRAFT);
  var draft = draftState[0];
  // The profile whose draft is loaded; null until the first status read names it.
  var draftHome = useRef(null);
  var catalogReadState = useState(null);
  // The name of the write in flight, or null.
  var savingState = useState(null);
  var problemState = useState(null);
  // Set when a write was saved but the status read that follows it failed; cleared by the next status read.
  var staleState = useState(null);
  // "Pause protection" or "Resume protection" while a write that changes it is in flight, whichever view sent it.
  var changingState = useState(null);
  // A write whose outcome is unknown, until both reads succeed again.
  var pendingState = useState(null);
  var pendingRef = useRef(null);
  var checkingState = useState(false);
  var toast = SDK.hooks.useToast();
  var rememberPauseOpener = useReturnFocus(pauseState[0], "petasos-protection-action");
  var beginStatus = useLatest();
  var beginCatalog = useLatest();

  function readStatus() {
    var latest = beginStatus();
    return call("/status").then(
      function (body) {
        if (!latest()) return false;
        statusState[1](body);
        failureState[1](null);
        checkedState[1](Date.now());
        staleState[1](null);
        return true;
      },
      function (failure) {
        if (latest()) failureState[1](failure);
        return false;
      }
    );
  }
  function readCatalog() {
    var latest = beginCatalog();
    return call("/settings").then(
      function (body) {
        if (!latest()) return false;
        catalogState[1](body);
        catalogFailureState[1](null);
        catalogReadState[1](Date.now());
        return true;
      },
      function (failure) {
        if (latest()) catalogFailureState[1](failure);
        return false;
      }
    );
  }
  // Both reads, started now. Only this clears an unconfirmed change.
  function reconcile() {
    checkingState[1](true);
    refreshState[1](function (n) {
      return n + 1;
    });
    return Promise.all([readStatus(), readCatalog()]).then(function (read) {
      checkingState[1](false);
      if (!read[0] || !read[1]) return false;
      pendingRef.current = null;
      pendingState[1](null);
      problemState[1](function (problem) {
        return problem && problem.outcome === "unknown" ? null : problem;
      });
      return true;
    });
  }

  usePoll(
    function () {
      return pendingRef.current ? reconcile() : readStatus();
    },
    20000,
    []
  );
  useEffect(function () {
    readCatalog();
  }, []);

  var dirty = !draftIsEmpty(draft);
  var home = status ? status.home || "" : null;
  useEffect(
    function () {
      if (home === null || draftHome.current === home) return;
      draftHome.current = home;
      draftState[1](readDraft(home));
    },
    [home]
  );
  useEffect(
    function () {
      if (draftHome.current !== null) writeDraft(draft, draftHome.current);
    },
    [draft]
  );
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

  // Settings a write returned replace the catalog; the status is then read
  // again, and the promise says whether that read succeeded.
  function onSaved(body) {
    if (body && body.settings) {
      beginCatalog();
      catalogState[1](body);
      catalogFailureState[1](null);
      catalogReadState[1](Date.now());
    } else {
      readCatalog();
    }
    refreshState[1](function (n) {
      return n + 1;
    });
    return readStatus();
  }

  // Every write goes through here, one at a time. `run` performs it; `what`
  // names it for the person. A refusal tied to one field is left to the caller.
  // `sent`, when given, is the draft body this write carries: once saved, those
  // values leave the draft, and anything staged since stays.
  function write(run, what, notes, sent, payload) {
    if (savingState[0]) return Promise.reject(new ApiFailure(0, "busy", "The last change is still being saved.", null));
    savingState[1](what || "Save");
    changingState[1](changeOf(sent || payload, catalog));
    return run()
      .then(function (result) {
        problemState[1](null);
        if (sent) {
          var known = knownPaths(result.settings && result.settings.settings);
          draftState[1](function (held) {
            return draftAfterSave(held, sent, known);
          });
        }
        // The write stays in flight until the status has been read again, so
        // the reading from before it is never shown as current.
        var readAt = checkedState[0];
        return onSaved(result.settings).then(function (read) {
          if (!read) staleState[1]({ readAt: readAt });
          return result;
        });
      })
      .catch(function (failure) {
        failure.what = what;
        failure.note = notes ? (failure.outcome === "unknown" ? notes.unknown : notes.other) || "" : "";
        if (failure.code === "managed") lockedState[1](failure.message);
        if (failure.outcome === "unknown") {
          pendingRef.current = { what: what };
          pendingState[1](pendingRef.current);
        }
        // The reason stays on the page until dismissed; a toast would vanish with it.
        if (!failure.path) problemState[1](failure);
        if (failure.settings) onSaved(failure.settings);
        throw failure;
      })
      .finally(function () {
        savingState[1](null);
        changingState[1](null);
      });
  }

  function save(body, what, applies) {
    return write(
      function () {
        return writeSettings(body, applies);
      },
      what,
      null,
      null,
      body
    ).then(function (result) {
      toast.showToast(result.message, "success");
      return result;
    });
  }

  function stage(candidate) {
    var known = knownPaths(catalog && catalog.settings);
    draftState[1](function (held) {
      return mergeDraft(held, candidate, known);
    });
  }

  if (status) startProfile = status.home || "";
  var view = route.view;
  var locked = Boolean(lockedState[0]);
  var pending = pendingState[0];
  var stale = !pending && staleState[0] && status ? staleState[0] : null;
  var view_ = status
    ? protectionView(status, catalog, {
        changing: changingState[0],
        saving: Boolean(savingState[0]),
        pending: pending,
        stale: stale,
        failed: Boolean(failureState[0]),
        readAt: checkedState[0],
      })
    : null;
  var body;
  if (!status && failureState[0]) {
    body = h(Unreachable, { failure: failureState[0], onRetry: reconcile });
  } else if (!status) {
    body = h("p", { className: "petasos-help", role: "status" }, "Loading Petasos…");
  } else {
    var shared = {
      route: route,
      status: status,
      catalog: catalog,
      catalogFailure: catalogFailureState[0],
      catalogReadAt: catalogReadState[0],
      onRetryCatalog: readCatalog,
      refreshKey: refreshState[0],
      locked: locked,
      lockedMessage: lockedState[0],
      onSave: save,
      onWrite: write,
      saving: Boolean(savingState[0]),
      savingWhat: savingState[0],
      pending: pending,
      stale: stale,
      verdict: view_.verdict,
      detailsCurrent: view_.current,
      waiting: view_.waiting,
      checking: checkingState[0],
      onCheck: reconcile,
    };
    if (view === "activity") body = h(Activity, shared);
    // Each linked candidate or example requires fresh Try it and Settings state.
    else if (view === "tryit")
      body = h(
        TryIt,
        Object.assign(
          { key: (route.params.example || "") + "|" + (route.params.settings || "") + "|" + (route.params.rule || ""), draft: draft, onStage: stage },
          shared
        )
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
            rememberPauseOpener();
            pauseState[1](true);
          },
          onResume: function () {
            save({ enabled: true }, "Resume protection").catch(function () {});
          },
        })
      );
  }

  var verdict = view_ ? view_.verdict : null;
  var paused = Boolean(verdict && verdict.code === "paused");
  // An unconfirmed change is explained once, by the notice or panel that offers Check again.
  var problem = problemState[0] && !(pending && problemState[0].outcome === "unknown") ? problemState[0] : null;
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
        verdict && view !== "overview"
          ? h(
              "button",
              {
                type: "button",
                className: "petasos-statechip",
                "aria-label": "Protection: " + verdict.word + ". Open Overview.",
                onClick: function () {
                  go("overview");
                },
              },
              h("span", { className: "petasos-statechip-label", "aria-hidden": true }, "Protection"),
              h(Status, { tone: verdict.tone, state: verdict.code }, verdict.word)
            )
          : null,
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
        status && status.petasos_version ? h("span", { className: "petasos-help petasos-version" }, "Petasos " + status.petasos_version) : null,
        checkedState[0] ? h("span", { className: "petasos-help" }, "Checked " + whenText(checkedState[0] / 1000)) : null,
        h(Btn, { ghost: true, onClick: reconcile, "aria-label": "Refresh now" }, "Refresh")
      )
    ),
    problem
      ? h(
          Notice,
          {
            tone: problem.outcome === "unknown" ? "warning" : "destructive",
            title:
              (problem.what ? problem.what + ": " : "") +
              (problem.outcome === "unknown" ? "not confirmed" : problem.outcome === "not_saved" ? "not there when read back" : "not saved"),
            action: h(Btn, { ghost: true, onClick: function () { problemState[1](null); } }, "Dismiss"),
          },
          h("p", null, problem.message),
          problem.note ? h("p", null, problem.note) : null
        )
      : null,
    pending && view !== "overview"
      ? h(
          Notice,
          {
            tone: "warning",
            title: "Protection state not confirmed",
            action: h(Btn, { onClick: reconcile, disabled: checkingState[0] }, checkingState[0] ? "Checking…" : "Check again"),
          },
          verdict.reason
        )
      : paused && view !== "overview"
        ? h(
            Notice,
            {
              tone: "warning",
              title: "Protection is paused",
              action: h(
                Btn,
                {
                  onClick: function () {
                    save({ enabled: true }, "Resume protection").catch(function () {});
                  },
                  disabled: locked || Boolean(savingState[0]),
                },
                savingState[0] === "Resume protection" ? "Resuming…" : "Resume"
              ),
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
        save({ enabled: false }, "Pause protection").catch(function () {});
      },
    })
  );
}

PLUGINS.register("petasos", PetasosTab);
