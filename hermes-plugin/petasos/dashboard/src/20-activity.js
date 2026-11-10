// ---------------------------------------------------------------------------
// Activity: what Petasos did and why, newest first, from the event record.
// ---------------------------------------------------------------------------

var RANGES = [
  { value: "1h", label: "1 hour", seconds: 3600 },
  { value: "24h", label: "24 hours", seconds: 86400 },
  { value: "7d", label: "7 days", seconds: 7 * 86400 },
  { value: "all", label: "All", seconds: null },
];

var OUTCOME_KIND = {
  // An outcome tile on the overview opens the list filtered to the kinds
  // that produce it. Kinds are the API's ids; this is a filter, not a label.
  blocked: ["quarantine", "block", "tier3"],
  asked: ["approval"],
  flagged: ["ingest_flagged"],
  allowed: ["bypassed_disarmed"],
};

function rangeSince(range) {
  var found = RANGES.filter(function (item) {
    return item.value === range;
  })[0];
  if (!found || !found.seconds) return null;
  return Math.floor(Date.now() / 1000) - found.seconds;
}

function IntegrityPill(props) {
  var integrity = props.integrity;
  if (!integrity) return null;
  if (integrity.mode === "verified") {
    return h(
      Pill,
      { tone: "success", title: "Each event carries a signature, and every one shown checks out." },
      "Signed · " + integrity.checked + " checked"
    );
  }
  if (integrity.mode === "mixed") {
    return h(Pill, { tone: "destructive" }, integrity.failed + " of " + integrity.checked + " failed checks");
  }
  if (integrity.mode === "failed") {
    return h(Pill, { tone: "destructive" }, "Signatures do not match");
  }
  return h(Pill, { tone: "warning", title: integrity.reason }, "Not signed");
}

function IntegrityNotice(props) {
  var integrity = props.integrity;
  if (!integrity) return null;
  if (integrity.mode === "off") {
    return h(
      Notice,
      { tone: "warning", title: "This record is not signed" },
      "Anything that can write to the profile could change or remove an entry without it " +
        "showing here. " +
        (integrity.reason || "") +
        " Set PETASOS_SESSION_SECRET in the profile's env file to sign new events."
    );
  }
  if (integrity.mode === "failed" || integrity.mode === "mixed") {
    return h(
      Notice,
      { tone: "destructive", title: "Some entries do not match their signatures" },
      "An entry marked below was changed after Petasos wrote it, or written by something " +
        "else. Treat those entries as untrustworthy."
    );
  }
  return null;
}

function ActivityFilters(props) {
  var filters = props.filters;
  var options = props.options || {};
  function set(key, value) {
    var next = Object.assign({}, filters);
    next[key] = value === "any" ? "" : value;
    if (key !== "outcome") next.outcome = "";
    props.onChange(next);
  }
  function listed(counts, labeller) {
    return [{ value: "any", label: "Any" }].concat(
      Object.keys(counts || {})
        .sort()
        .map(function (key) {
          return { value: key, label: (labeller ? labeller(key) : key) + " (" + counts[key] + ")" };
        })
    );
  }
  var active = ["kind", "tool", "session", "severity", "outcome"].some(function (key) {
    return filters[key];
  });
  return h(
    "div",
    { className: "petasos-filters", role: "group", "aria-label": "Filter activity" },
    h(Segmented, {
      label: "Time",
      value: filters.range,
      options: RANGES,
      onChange: function (value) {
        set("range", value);
      },
    }),
    h(
      "div",
      { className: "petasos-filter-selects" },
      h(Choice, {
        id: "petasos-filter-kind",
        label: "What happened",
        value: filters.kind || "any",
        options: listed(options.by_kind, function (kind) {
          return (options.kind_labels && options.kind_labels[kind]) || kind;
        }),
        onChange: function (value) {
          set("kind", value);
        },
      }),
      h(Choice, {
        id: "petasos-filter-tool",
        label: "Tool",
        value: filters.tool || "any",
        options: listed(options.by_tool),
        onChange: function (value) {
          set("tool", value);
        },
      }),
      h(Choice, {
        id: "petasos-filter-session",
        label: "Conversation",
        value: filters.session || "any",
        options: listed(options.by_session),
        onChange: function (value) {
          set("session", value);
        },
      }),
      h(Choice, {
        id: "petasos-filter-severity",
        label: "How serious",
        value: filters.severity || "any",
        options: listed(options.by_severity, severityWord),
        onChange: function (value) {
          set("severity", value);
        },
      })
    ),
    active
      ? h(
          Btn,
          {
            ghost: true,
            onClick: function () {
              props.onChange({ range: filters.range });
            },
          },
          "Clear filters"
        )
      : null
  );
}

function EventRow(props) {
  var event = props.event;
  var severity = event.severity ? String(event.severity).toLowerCase() : "";
  var outcomeInfo = event.outcome || {};
  var failed = event.integrity && event.integrity.status === "failed";
  return h(
    "li",
    { className: "petasos-event-item" },
    h(
      "button",
      {
        type: "button",
        className: cn("petasos-event", props.selected && "petasos-event-selected"),
        "aria-current": props.selected ? "true" : undefined,
        onClick: props.onOpen,
      },
      h(
        "span",
        { className: "petasos-event-when", title: exactTime(event.timestamp) },
        h("span", { className: "petasos-block" }, whenText(event.timestamp)),
        h("span", { className: "petasos-block petasos-event-clock" }, clockTime(event.timestamp))
      ),
      h(
        "span",
        { className: "petasos-event-what" },
        h("span", { className: "petasos-event-summary" }, event.summary),
        h(
          "span",
          { className: "petasos-event-meta" },
          event.tool ? h(Mono, null, event.tool) : null,
          event.session_id ? h("span", null, "in " + event.session_id) : null,
          failed ? h(Pill, { tone: "destructive" }, "Signature does not match") : null
        )
      ),
      h(
        "span",
        { className: "petasos-event-tags" },
        severity
          ? h(Pill, { tone: SEVERITY_TONE[severity] || "secondary" }, severityWord(severity))
          : h("span", { className: "petasos-event-noseverity" }, "—"),
        h(Pill, { tone: outcomeTone(outcomeInfo.code) }, outcomeInfo.label || "Recorded")
      )
    )
  );
}

// Everything recorded about one event, with the ways to act on it.
function EventDetail(props) {
  var event = props.event;
  var known = {
    scan_id: 1, timestamp: 1, event_type: 1, tool: 1, session_id: 1, severity: 1,
    rule_id: 1, reason: 1, summary: 1, outcome: 1, kind_label: 1, rule_sentence: 1,
    integrity: 1, sig: 1,
  };
  var others = Object.keys(event)
    .filter(function (key) {
      return !known[key] && event[key] !== null && event[key] !== "" && event[key] !== undefined;
    })
    .sort();
  var rule = event.rule_id ? String(event.rule_id).replace(/^plugin_rule:/, "") : "";
  var integrity = event.integrity || {};
  var integrityText =
    integrity.status === "verified"
      ? "Signed, and the signature checks out."
      : integrity.status === "failed"
        ? integrity.reason || "The signature does not match."
        : "Not signed, so it cannot be checked.";
  return h(
    "aside",
    { className: "petasos-detail", "aria-label": "Event detail" },
    h(
      "div",
      { className: "petasos-detail-head" },
      h(Pill, { tone: outcomeTone(event.outcome && event.outcome.code) }, (event.outcome && event.outcome.label) || "Recorded"),
      h(Btn, { ghost: true, onClick: props.onClose, "aria-label": "Close event detail" }, "Close")
    ),
    h("h3", { className: "petasos-detail-title" }, event.summary),
    h(KeyValues, {
      rows: [
        ["When", exactTime(event.timestamp) + " (" + whenText(event.timestamp) + ")"],
        ["Kind", event.kind_label ? h(Fragment, null, event.kind_label, " ", h(Mono, null, event.event_type)) : event.event_type],
        ["Tool", event.tool ? h(Mono, null, event.tool) : null],
        ["Conversation", event.session_id ? h(Mono, null, event.session_id) : null],
        ["How serious", event.severity ? severityWord(String(event.severity).toLowerCase()) : null],
        ["Rule", rule ? h(Fragment, null, event.rule_sentence ? h("span", { className: "petasos-block" }, event.rule_sentence) : null, h(Mono, null, rule)) : null],
        ["Why", event.reason],
        ["Record", integrityText],
      ],
    }),
    h(
      "div",
      { className: "petasos-row-actions" },
      rule && rule.indexOf("petasos.syntactic.") === 0
        ? h(
            Btn,
            {
              outlined: true,
              onClick: function () {
                go("settings", { rule: rule });
              },
            },
            "Settings for this rule"
          )
        : null,
      event.session_id
        ? h(
            Btn,
            {
              ghost: true,
              onClick: function () {
                props.onFilter({ session: event.session_id });
              },
            },
            "Only this conversation"
          )
        : null
    ),
    others.length
      ? h(
          "details",
          { className: "petasos-raw" },
          h("summary", null, "Everything else recorded (" + others.length + ")"),
          h(KeyValues, {
            rows: others.map(function (key) {
              var value = event[key];
              return [key, h(Mono, null, typeof value === "object" ? JSON.stringify(value) : String(value))];
            }),
          })
        )
      : null,
    h("p", { className: "petasos-help" }, "Event id ", h(Mono, null, event.scan_id))
  );
}

function filtersFromRoute(params) {
  return {
    range: params.range || "24h",
    kind: params.kind || "",
    tool: params.tool || "",
    session: params.session || "",
    severity: params.severity || "",
    outcome: params.outcome || "",
  };
}

function Activity(props) {
  var params = props.route.params;
  var filters = filtersFromRoute(params);
  var selectedId = params.event || "";
  var pageState = useState(null);
  var page = pageState[0];
  var setPage = pageState[1];
  var olderState = useState([]);
  var older = olderState[0];
  var setOlder = olderState[1];
  var optionsState = useState(null);
  var failureState = useState(null);
  var loadingMore = useState(false);
  var extraEvent = useState(null);

  function setFilters(next) {
    var route = Object.assign({}, next);
    Object.keys(route).forEach(function (key) {
      if (!route[key]) delete route[key];
    });
    go("activity", route);
  }

  var kinds = filters.outcome ? OUTCOME_KIND[filters.outcome] || [] : [];
  var request = {
    limit: 50,
    since: rangeSince(filters.range),
    kind: filters.kind,
    tool: filters.tool,
    session: filters.session,
    severity: filters.severity,
  };
  var key = JSON.stringify([request, filters.outcome]);

  usePoll(
    function () {
      call("/activity" + query(request))
        .then(function (body) {
          setPage(body);
          failureState[1](null);
        })
        .catch(function (failure) {
          failureState[1](failure);
        });
      call("/activity/summary" + query({ since: request.since }))
        .then(optionsState[1])
        .catch(function () {});
    },
    15000,
    [key, props.refreshKey]
  );
  useEffect(
    function () {
      setOlder([]);
    },
    [key]
  );

  function loadOlder() {
    var last = older.length ? older[older.length - 1] : page;
    if (!last || !last.next_cursor) return;
    loadingMore[1](true);
    call("/activity" + query(Object.assign({}, request, { cursor: last.next_cursor })))
      .then(function (body) {
        setOlder(older.concat([body]));
      })
      .catch(function (failure) {
        failureState[1](failure);
      })
      .finally(function () {
        loadingMore[1](false);
      });
  }

  var events = [];
  if (page) {
    events = (page.events || []).slice();
    older.forEach(function (chunk) {
      events = events.concat(chunk.events || []);
    });
  }
  if (kinds.length) {
    events = events.filter(function (event) {
      return kinds.indexOf(event.event_type) >= 0;
    });
  }
  var selected = events.filter(function (event) {
    return event.scan_id === selectedId;
  })[0];

  // An event linked from elsewhere may sit outside the current page.
  useEffect(
    function () {
      if (!selectedId || selected) return;
      call("/activity/" + encodeURIComponent(selectedId))
        .then(function (body) {
          extraEvent[1](body.event);
        })
        .catch(function () {
          extraEvent[1](null);
        });
    },
    [selectedId, Boolean(selected)]
  );
  if (!selected && extraEvent[0] && extraEvent[0].scan_id === selectedId) selected = extraEvent[0];

  var tail = older.length ? older[older.length - 1] : page;
  var options = optionsState[0];
  var everEmpty = options && options.total === 0 && !filters.kind && !filters.tool && !filters.session && !filters.severity;

  function open(event) {
    var route = Object.assign({}, params, { event: event.scan_id });
    go("activity", route);
  }
  function close() {
    var route = Object.assign({}, params);
    delete route.event;
    go("activity", route);
  }

  var list;
  if (failureState[0] && !page) {
    list = h(Notice, { tone: "destructive", title: "The activity record could not be read" }, failureState[0].message);
  } else if (!page) {
    list = h("p", { className: "petasos-muted" }, "Loading activity…");
  } else if (!events.length && everEmpty && filters.range === "all") {
    list = h(
      Empty,
      {
        title: "Nothing recorded yet",
        action: h(Btn, { onClick: function () { go("tryit", { example: "hidden" }); } }, "See it work in Try it"),
      },
      h(
        "p",
        null,
        "When Petasos blocks a tool call, asks a person about one, or warns the agent about a " +
          "tool result, it appears here with the reason. Calls that pass cleanly are not listed."
      ),
      h(
        "p",
        null,
        "To see what it would do without waiting for a real attack, paste some text into Try it."
      )
    );
  } else if (!events.length) {
    list = h(
      Empty,
      {
        title: everEmpty ? "Nothing in this time range" : "Nothing matches these filters",
        action: everEmpty
          ? h(Btn, { outlined: true, onClick: function () { setFilters({ range: "all" }); } }, "Show all time")
          : h(Btn, { outlined: true, onClick: function () { setFilters({ range: filters.range }); } }, "Clear filters"),
      },
      everEmpty
        ? "Petasos has not stepped in during this time. Clean tool calls are not listed."
        : "Try a longer time range, or clear the filters."
    );
  } else {
    list = h(
      Fragment,
      null,
      h(
        "div",
        { className: "petasos-event-header", "aria-hidden": true },
        h("span", null, "When"),
        h("span", null, "What happened"),
        h("span", null, "Seriousness · Outcome")
      ),
      h(
        "ul",
        { className: "petasos-events", "aria-label": "Events, newest first" },
        events.map(function (event) {
          return h(EventRow, {
            key: event.scan_id,
            event: event,
            selected: event.scan_id === selectedId,
            onOpen: function () {
              open(event);
            },
          });
        })
      ),
      tail && tail.next_cursor
        ? h(
            "div",
            { className: "petasos-more" },
            h(Btn, { outlined: true, onClick: loadOlder, disabled: loadingMore[0] }, loadingMore[0] ? "Loading…" : "Show older events")
          )
        : h("p", { className: "petasos-help petasos-end" }, page.complete === false ? "Older events were not read." : "That is everything in this range.")
    );
  }

  var shownSummary = options
    ? plural(options.total, "event") +
      " in this range · " +
      (options.blocked || 0) +
      " blocked"
    : "";

  return h(
    "div",
    { className: "petasos-stack" },
    h(
      Panel,
      {
        title: "Activity",
        description:
          "What Petasos blocked, flagged or asked about, and why. Newest first; refreshed every 15 seconds.",
        actions: h(
          Fragment,
          null,
          shownSummary ? h("span", { className: "petasos-count" }, shownSummary) : null,
          page ? h(IntegrityPill, { integrity: page.integrity }) : null
        ),
      },
      h(ActivityFilters, { filters: filters, options: options, onChange: setFilters }),
      filters.outcome
        ? h(
            "p",
            { className: "petasos-help" },
            "Showing: ",
            h("strong", null, filters.outcome === "allowed" ? "let through while paused" : filters.outcome === "asked" ? "asked a person" : filters.outcome),
            ". ",
            h(LinkButton, { onClick: function () { setFilters({ range: filters.range }); } }, "Show everything")
          )
        : null
    ),
    page ? h(IntegrityNotice, { integrity: page.integrity }) : null,
    h(
      "div",
      { className: cn("petasos-split", selected && "petasos-split-open") },
      h("div", { className: "petasos-split-main" }, h(C.Card, { className: "petasos-panel petasos-list-card" }, list)),
      selected
        ? h(EventDetail, {
            event: selected,
            onClose: close,
            onFilter: function (patch) {
              setFilters(Object.assign({}, filters, patch));
            },
          })
        : null
    )
  );
}
