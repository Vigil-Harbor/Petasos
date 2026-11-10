// ---------------------------------------------------------------------------
// Activity: what Petasos did and why, newest first, from the event record.
// ---------------------------------------------------------------------------

var RANGES = [
  { value: "1h", label: "1 hour", seconds: 3600 },
  { value: "24h", label: "24 hours", seconds: 86400 },
  { value: "7d", label: "7 days", seconds: 7 * 86400 },
  { value: "all", label: "All", seconds: null },
  { value: "custom", label: "Custom", seconds: null },
];

// An outcome count on the overview opens the list filtered to it. These
// are the API's outcome codes; the reader filters on them, so paging and
// counts agree with the list.
var OUTCOME_CODES = {
  blocked: ["blocked", "stopped", "attempt_blocked"],
  asked: ["asked", "attempt_asked"],
  flagged: ["flagged"],
  allowed: ["allowed"],
  not_stopped: ["not_stopped"],
};

var OUTCOME_FILTER_WORDS = {
  blocked: "blocked",
  asked: "asked a person",
  flagged: "flagged to the agent",
  allowed: "let through while paused",
  not_stopped: "setting changes not stopped",
};

// A custom range is kept as YYYY-MM-DDTHH:MM in the browser's time zone and
// shown as YYYY-MM-DD HH:MM, which no reader can take for another date.
function parseLocal(value) {
  var match = String(value || "").trim().match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})$/);
  if (!match) return null;
  var date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]));
  if (date.getMonth() !== Number(match[2]) - 1 || date.getDate() !== Number(match[3])) return null;
  return date;
}

function localSeconds(value) {
  var date = parseLocal(value);
  return date ? Math.floor(date.getTime() / 1000) : null;
}

function localStamp(date) {
  function pad(n) {
    return String(n).padStart(2, "0");
  }
  return (
    date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) + "T" + pad(date.getHours()) + ":" + pad(date.getMinutes())
  );
}

// One end of a custom range: a text field in an unambiguous form, and a
// calendar button that opens the browser's own picker.
function DateTimeField(props) {
  var pickerRef = useRef(null);
  var textState = useState(String(props.value || "").replace("T", " "));
  useEffect(
    function () {
      textState[1](String(props.value || "").replace("T", " "));
    },
    [props.value]
  );
  var invalid = textState[0].trim() !== "" && !parseLocal(textState[0]);
  function commit(text) {
    var date = parseLocal(text);
    if (date) props.onChange(localStamp(date));
    else if (!text.trim()) props.onChange("");
  }
  return h(
    "div",
    { className: "petasos-choice petasos-datetime" },
    h(C.Label, { className: "petasos-label", htmlFor: props.id }, props.label),
    h(
      "div",
      { className: "petasos-datetime-box" },
      h(C.Input, {
        id: props.id,
        value: textState[0],
        placeholder: "YYYY-MM-DD HH:MM",
        inputMode: "numeric",
        "aria-invalid": invalid ? "true" : undefined,
        "aria-describedby": props.id + "-format",
        onChange: function (event) {
          textState[1](event.target.value);
        },
        onBlur: function () {
          commit(textState[0]);
        },
        onKeyDown: function (event) {
          if (event.key === "Enter") commit(textState[0]);
        },
      }),
      h(
        "button",
        {
          type: "button",
          className: "petasos-datetime-pick",
          "aria-label": "Choose " + props.label.toLowerCase() + " on a calendar",
          onClick: function () {
            var picker = pickerRef.current;
            if (!picker) return;
            picker.value = props.value || "";
            if (picker.showPicker) picker.showPicker();
            else picker.focus();
          },
        },
        h(Icon, { name: "calendar", size: 16 })
      ),
      h("input", {
        ref: pickerRef,
        type: "datetime-local",
        className: "petasos-datetime-native",
        tabIndex: -1,
        "aria-hidden": true,
        onChange: function (event) {
          if (event.target.value) props.onChange(event.target.value.slice(0, 16));
        },
      })
    ),
    h(
      "p",
      { className: cn("petasos-tertiary", invalid && "petasos-field-error"), id: props.id + "-format" },
      invalid ? "Write it as YYYY-MM-DD HH:MM." : "Year-month-day, 24-hour clock"
    )
  );
}

function rangeWindow(filters) {
  if (filters.range === "custom") {
    return { since: localSeconds(filters.from), until: localSeconds(filters.to) };
  }
  var found = RANGES.filter(function (item) {
    return item.value === filters.range;
  })[0];
  if (!found || !found.seconds) return { since: null, until: null };
  return { since: Math.floor(Date.now() / 1000) - found.seconds, until: null };
}

function IntegrityStatus(props) {
  var integrity = props.integrity;
  if (!integrity) return null;
  if (integrity.mode === "verified") {
    return h(Status, { tone: "success", title: "Each record shown carries a signature that matches." }, "Signed · " + integrity.checked + " checked");
  }
  if (integrity.mode === "mixed") {
    return h(Status, { tone: "destructive" }, integrity.failed + " of " + integrity.checked + " do not match");
  }
  if (integrity.mode === "failed") {
    return h(Status, { tone: "destructive" }, "Signatures do not match");
  }
  return h(Status, { tone: "warning", title: integrity.reason }, "Not signed");
}

function IntegrityNotice(props) {
  var integrity = props.integrity;
  var signing = props.signing || {};
  var openState = useState(false);
  if (!integrity) return null;
  if (integrity.mode === "off") {
    return h(
      Notice,
      {
        tone: "warning",
        title: "Records are not signed yet",
        action: (signing.steps || []).length
          ? h(
              Btn,
              {
                outlined: true,
                "aria-expanded": openState[0],
                onClick: function () {
                  openState[1](!openState[0]);
                },
              },
              openState[0] ? "Hide the steps" : "Set up record checking"
            )
          : null,
      },
      h("p", null, "Protection runs and every record is written. Without a signature, a changed record could go unnoticed."),
      openState[0]
        ? h(
            "ol",
            { className: "petasos-steps" },
            (signing.steps || []).map(function (step) {
              return h("li", { key: step }, step);
            })
          )
        : null
    );
  }
  if (integrity.mode === "failed" || integrity.mode === "mixed") {
    return h(
      Notice,
      { tone: "destructive", strong: true, title: "Some records do not match their signatures" },
      "A marked record was changed after Petasos wrote it, or written by something else. Do not trust it."
    );
  }
  return null;
}

function ActivityFilters(props) {
  var filters = props.filters;
  var options = props.options || {};
  var searchState = useState(filters.q || "");
  useEffect(
    function () {
      searchState[1](filters.q || "");
    },
    [filters.q]
  );
  function set(key, value) {
    var next = Object.assign({}, filters);
    next[key] = value === "any" ? "" : value;
    if (key === "range" && value === "custom" && !next.from && !next.to) {
      var now = new Date();
      next.from = localStamp(new Date(now.getTime() - 86400000));
      next.to = localStamp(now);
    }
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
  var active = ["kind", "tool", "session", "severity", "outcome", "q"].some(function (key) {
    return filters[key];
  });
  return h(
    "div",
    { className: "petasos-filters", role: "group", "aria-label": "Filter activity" },
    h(
      "div",
      { className: "petasos-filter-row" },
      h(
        "div",
        { className: "petasos-filter-group" },
        h("span", { className: "petasos-filter-label", id: "petasos-range-label" }, "Time"),
        h(Segmented, {
          id: "petasos-range",
          labelledBy: "petasos-range-label",
          value: filters.range,
          options: RANGES,
          onChange: function (value) {
            set("range", value);
          },
        })
      ),
      h(
        "form",
        {
          className: "petasos-search",
          role: "search",
          onSubmit: function (event) {
            event.preventDefault();
            set("q", searchState[0].trim());
          },
        },
        h(Icon, { name: "search", className: "petasos-search-icon" }),
        h(C.Input, {
          id: "petasos-activity-search",
          type: "search",
          "aria-label": "Search activity by event id or words",
          placeholder: "Search by event id or words…",
          value: searchState[0],
          onChange: function (event) {
            searchState[1](event.target.value);
          },
          onBlur: function () {
            if (searchState[0].trim() !== (filters.q || "")) set("q", searchState[0].trim());
          },
        })
      ),
      active
        ? h(
            Btn,
            {
              ghost: true,
              onClick: function () {
                props.onChange({ range: filters.range, from: filters.from, to: filters.to });
              },
            },
            "Clear filters"
          )
        : null
    ),
    filters.range === "custom"
      ? h(
          "div",
          { className: "petasos-filter-row petasos-range-row" },
          h(DateTimeField, {
            id: "petasos-from",
            label: "From",
            value: filters.from || "",
            onChange: function (value) {
              set("from", value);
            },
          }),
          h(DateTimeField, {
            id: "petasos-to",
            label: "To",
            value: filters.to || "",
            onChange: function (value) {
              set("to", value);
            },
          }),
          h("p", { className: "petasos-secondary petasos-tz" }, "Your time zone: " + Intl.DateTimeFormat().resolvedOptions().timeZone)
        )
      : null,
    h(
      "div",
      { className: "petasos-filter-selects" },
      h(Choice, {
        id: "petasos-filter-kind",
        label: "Kind",
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
        label: "Severity",
        value: filters.severity || "any",
        options: listed(options.by_severity, capital),
        onChange: function (value) {
          set("severity", value);
        },
      })
    )
  );
}

function EventRow(props) {
  var event = props.event;
  var outcome = event.outcome || {};
  var failed = event.integrity && event.integrity.status === "failed";
  return h(
    "button",
    {
      type: "button",
      id: "petasos-event-" + event.scan_id,
      className: cn("petasos-event", props.selected && "petasos-event-selected", props.nested && "petasos-event-nested"),
      "aria-current": props.selected ? "true" : undefined,
      "aria-label": (props.selected ? "Open now: " : "Open details: ") + event.summary + ", " + listTime(event.timestamp),
      onClick: props.onOpen,
    },
    h(
      "span",
      { className: "petasos-event-when" },
      h("span", { className: "petasos-block" }, listTime(event.timestamp)),
      h("span", { className: "petasos-block petasos-tertiary" }, whenText(event.timestamp))
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
        failed ? h(Status, { tone: "destructive" }, "Signature does not match") : null
      )
    ),
    h("span", { className: "petasos-event-severity" }, h(Severity, { value: event.severity })),
    h("span", { className: "petasos-event-outcome" }, h(Status, { tone: outcomeTone(outcome.code) }, outcome.label || "Recorded")),
    h(Icon, { name: "chevron", className: "petasos-chevron" })
  );
}

// Repeats are one row with a count; opening the group lists each event.
function EventGroup(props) {
  var group = props.group;
  var openState = useState(false);
  var first = group.events[0];
  var last = group.events[group.events.length - 1];
  var count = group.events.length;
  var inside = group.events.some(function (event) {
    return event.scan_id === props.selectedId;
  });
  var open = openState[0] || (inside && first.scan_id !== props.selectedId);
  if (count === 1) {
    return h(
      "li",
      { className: "petasos-event-item" },
      h(EventRow, { event: first, selected: first.scan_id === props.selectedId, onOpen: function () { props.onOpen(first); } })
    );
  }
  return h(
    "li",
    { className: "petasos-event-item petasos-event-group" },
    h(EventRow, {
      event: first,
      selected: first.scan_id === props.selectedId,
      onOpen: function () {
        props.onOpen(first);
      },
    }),
    h(
      "div",
      { className: "petasos-group-bar" },
      h(
        "span",
        { className: "petasos-repeat" },
        "Repeated " + count + " times, " + listTime(last.timestamp) + " to " + listTime(first.timestamp)
      ),
      h(
        LinkButton,
        {
          expanded: open,
          onClick: function () {
            openState[1](!open);
          },
        },
        open ? "Hide the " + count : "Show all " + count
      )
    ),
    open
      ? h(
          "ul",
          { className: "petasos-events petasos-events-nested", "aria-label": "The " + count + " repeated events" },
          group.events.slice(1).map(function (event) {
            return h(
              "li",
              { key: event.scan_id, className: "petasos-event-item" },
              h(EventRow, {
                event: event,
                nested: true,
                selected: event.scan_id === props.selectedId,
                onOpen: function () {
                  props.onOpen(event);
                },
              })
            );
          })
        )
      : null
  );
}

// Everything recorded about one event, with the ways to act on it.
var SHOWN_FIELDS = {
  scan_id: 1, timestamp: 1, event_type: 1, tool: 1, session_id: 1, severity: 1, rule_id: 1, reason: 1,
  summary: 1, outcome: 1, kind_label: 1, rule_sentence: 1, integrity: 1, sig: 1, matched_note: 1,
  target: 1, outcome_note: 1, risk_block: 1,
};

function EventDetail(props) {
  var event = props.event;
  var ref = useRef(null);
  var others = Object.keys(event)
    .filter(function (key) {
      return !SHOWN_FIELDS[key] && event[key] !== null && event[key] !== "" && event[key] !== undefined;
    })
    .sort();
  var rule = event.rule_id ? String(event.rule_id).replace(/^plugin_rule:/, "") : "";
  var integrity = event.integrity || {};
  var outcome = event.outcome || {};
  var notStopped = outcome.code === "not_stopped";
  // Stopped by the conversation's risk score, which earlier warnings built up.
  var risky = Boolean(event.session_id && event.risk_block);
  useEffect(
    function () {
      if (ref.current) ref.current.focus({ preventScroll: true });
    },
    [event.scan_id]
  );
  return h(
    "aside",
    {
      className: "petasos-detail",
      "aria-labelledby": "petasos-detail-title",
      tabIndex: -1,
      ref: ref,
      onKeyDown: function (keyEvent) {
        if (keyEvent.key === "Escape") props.onClose();
      },
    },
    h(
      "div",
      { className: "petasos-detail-head" },
      h(
        "p",
        { className: "petasos-detail-which" },
        listTime(event.timestamp),
        event.session_id ? " · " + event.session_id : ""
      ),
      h(Btn, { ghost: true, onClick: props.onClose, "aria-label": "Close event details" }, "Close")
    ),
    h(
      "div",
      { className: "petasos-detail-status" },
      h(Status, { tone: outcomeTone(outcome.code), large: true }, outcome.label || "Recorded"),
      event.severity ? h(Severity, { value: event.severity }) : null
    ),
    h("h3", { className: "petasos-detail-title", id: "petasos-detail-title" }, event.summary),
    event.outcome_note ? h("p", { className: "petasos-detail-note" }, event.outcome_note) : null,
    notStopped || risky
      ? h(
          "div",
          { className: "petasos-row-actions" },
          notStopped ? h(Btn, { outlined: true, onClick: function () { go("settings"); } }, "Review current protection settings") : null,
          risky
            ? h(
                LinkButton,
                {
                  onClick: function () {
                    props.onFilter({ range: "all", session: event.session_id, event: event.scan_id });
                  },
                },
                "See the earlier warnings that caused this block"
              )
            : null
        )
      : null,
    h(KeyValues, {
      rows: [
        ["When", h(Fragment, null, fullTime(event.timestamp), h("span", { className: "petasos-tertiary" }, " · " + whenText(event.timestamp)))],
        ["Kind", event.kind_label || event.event_type],
        ["Tool", event.tool ? h(Mono, null, event.tool) : null],
        ["Conversation", event.session_id ? h(Mono, null, event.session_id) : null],
      ],
    }),
    h(KeyValues, {
      stacked: true,
      rows: [
        ["Target", event.target ? h(Ident, null, event.target) : null],
        [
          "Rule",
          rule
            ? h(
                Fragment,
                null,
                event.rule_sentence ? h("span", { className: "petasos-block" }, event.rule_sentence) : null,
                h("span", { className: "petasos-idrow petasos-tertiary" }, h(Ident, null, rule), h(CopyButton, { value: rule, label: "Copy rule id" }))
              )
            : null,
        ],
        ["Matched text", event.matched_note || null],
        ["Signature", integrity.meaning || null],
      ],
    }),
    h(
      "div",
      { className: "petasos-row-actions" },
      rule && rule.indexOf("petasos.syntactic.") === 0
        ? h(Btn, { outlined: true, onClick: function () { go("settings", { rule: rule }); } }, "Rule settings")
        : null,
      event.session_id && !risky
        ? h(
            Btn,
            {
              ghost: true,
              onClick: function () {
                props.onFilter({ session: event.session_id, event: event.scan_id });
              },
            },
            "Show this conversation"
          )
        : null
    ),
    h(
      Disclosure,
      { label: "Technical detail", openLabel: "Hide technical detail", remember: "activity-technical" },
      h(KeyValues, {
        stacked: true,
        rows: [
          ["Event id", h("span", { className: "petasos-idrow" }, h(Ident, null, event.scan_id), h(CopyButton, { value: event.scan_id, label: "Copy event id" }))],
          ["Event type", h(Mono, null, event.event_type)],
          ["Rule's note", event.reason && !event.target ? event.reason : null],
        ].concat(
          others.map(function (key) {
            var value = event[key];
            return [key, h(Mono, null, typeof value === "object" ? JSON.stringify(value) : String(value))];
          })
        ),
      })
    )
  );
}

function filtersFromRoute(params) {
  return {
    range: params.range || "24h",
    from: params.from || "",
    to: params.to || "",
    q: params.q || "",
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
  var olderState = useState([]);
  var older = olderState[0];
  var optionsState = useState(null);
  var countState = useState(null);
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

  var codes = filters.outcome ? OUTCOME_CODES[filters.outcome] || [filters.outcome] : [];
  var span = rangeWindow(filters);
  var request = {
    limit: 100,
    since: span.since,
    until: span.until,
    q: filters.q,
    kind: filters.kind,
    tool: filters.tool,
    session: filters.session,
    severity: filters.severity,
    outcome: codes.join(","),
  };
  var key = JSON.stringify([request, filters.range === "custom" ? 0 : Math.floor(Date.now() / 600000)]);

  usePoll(
    function () {
      var now = rangeWindow(filters);
      var live = Object.assign({}, request, { since: now.since, until: now.until });
      call("/activity" + query(live))
        .then(function (body) {
          pageState[1](body);
          failureState[1](null);
        })
        .catch(function (failure) {
          failureState[1](failure);
        });
      // The choices in each filter list come from the time range and search
      // alone; the count above the list uses every filter, as the list does.
      call("/activity/summary" + query({ since: now.since, until: now.until, q: filters.q }))
        .then(optionsState[1])
        .catch(function () {});
      var counted = Object.assign({}, live);
      delete counted.limit;
      call("/activity/summary" + query(counted))
        .then(countState[1])
        .catch(function () {});
    },
    15000,
    [key, props.refreshKey]
  );
  useEffect(
    function () {
      olderState[1]([]);
    },
    [key]
  );

  function loadOlder() {
    var last = older.length ? older[older.length - 1] : page;
    if (!last || !last.next_cursor) return;
    loadingMore[1](true);
    call("/activity" + query(Object.assign({}, request, { cursor: last.next_cursor })))
      .then(function (body) {
        olderState[1](older.concat([body]));
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
  var selected = events.filter(function (event) {
    return event.scan_id === selectedId;
  })[0];
  var selectedInList = Boolean(selected);

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

  // Keep the open event's row in view beside its detail.
  useEffect(
    function () {
      if (!selectedId || !selectedInList) return;
      var timer = window.setTimeout(function () {
        var row = document.getElementById("petasos-event-" + selectedId);
        if (!row) return;
        var box = row.getBoundingClientRect();
        if (box.top < 80 || box.bottom > window.innerHeight - 40) revealInView(row, "center");
      }, 60);
      return function () {
        window.clearTimeout(timer);
      };
    },
    [selectedId, selectedInList]
  );

  var tail = older.length ? older[older.length - 1] : page;
  var options = optionsState[0];
  var counts = countState[0];
  var filtered = filters.kind || filters.tool || filters.session || filters.severity || filters.q || filters.outcome;
  var neverRecorded = options && options.total === 0 && !filtered && filters.range === "all";

  function open(event) {
    var route = Object.assign({}, params, { event: event.scan_id });
    go("activity", route);
  }
  function close() {
    var id = selectedId;
    var route = Object.assign({}, params);
    delete route.event;
    go("activity", route);
    window.setTimeout(function () {
      var row = document.getElementById("petasos-event-" + id);
      if (row) row.focus({ preventScroll: true });
    }, 50);
  }

  var list;
  if (failureState[0] && !page) {
    list = h(Notice, { tone: "destructive", title: "The activity record could not be read" }, failureState[0].message);
  } else if (!page) {
    list = h("p", { className: "petasos-secondary", role: "status" }, "Loading activity…");
  } else if (!events.length && neverRecorded) {
    list = h(
      Empty,
      {
        title: "Nothing recorded yet",
        action: h(Btn, { outlined: true, onClick: function () { go("tryit", { example: "notes" }); } }, "Try it"),
      },
      "Blocks, approvals and warnings appear here. Clean tool calls are not listed."
    );
  } else if (!events.length) {
    list = h(
      Empty,
      {
        title: filtered ? "Nothing matches" : "Nothing in this time range",
        action: filtered
          ? h(Btn, { outlined: true, onClick: function () { setFilters({ range: filters.range, from: filters.from, to: filters.to }); } }, "Clear filters")
          : h(Btn, { outlined: true, onClick: function () { setFilters({ range: "all" }); } }, "Show all time"),
      },
      filtered ? "Try a longer time range or fewer filters." : "Petasos did not step in during this time."
    );
  } else {
    var groups = groupEvents(events);
    list = h(
      Fragment,
      null,
      h(
        "div",
        { className: "petasos-event-header", "aria-hidden": true },
        h("span", null, "When"),
        h("span", null, "What happened"),
        h("span", null, "Severity"),
        h("span", null, "Outcome"),
        h("span", null, "")
      ),
      h(
        "ul",
        { className: "petasos-events", "aria-label": "Events, newest first. Select one to see its details." },
        groups.map(function (group) {
          return h(EventGroup, { key: group.events[0].scan_id, group: group, selectedId: selectedId, onOpen: open });
        })
      ),
      tail && tail.next_cursor
        ? h(
            "div",
            { className: "petasos-more" },
            h(Btn, { outlined: true, onClick: loadOlder, disabled: loadingMore[0] }, loadingMore[0] ? "Loading…" : "Show older events")
          )
        : h("p", { className: "petasos-secondary petasos-end" }, page.complete === false ? "Older events were not read." : "That is everything in this range.")
    );
  }

  var count = counts
    ? plural(counts.total, "event") + " · " + plural(counts.blocked || 0, "tool call") + " blocked"
    : "";

  return h(
    "div",
    { className: "petasos-stack petasos-activity" },
    h(ActivityFilters, { filters: filters, options: options, onChange: setFilters }),
    h(
      "div",
      { className: "petasos-listbar" },
      h(
        "p",
        { className: "petasos-listbar-count", role: "status" },
        count && !neverRecorded ? h("span", { className: "petasos-count" }, count) : null,
        filters.outcome
          ? h(
              "span",
              { className: "petasos-secondary" },
              " · Only " + (OUTCOME_FILTER_WORDS[filters.outcome] || filters.outcome) + ". ",
              h(LinkButton, { onClick: function () { setFilters(Object.assign({}, filters, { outcome: "" })); } }, "Show every outcome")
            )
          : null,
        events.length ? h("span", { className: "petasos-tertiary" }, " · Newest first") : null
      ),
      page ? h(IntegrityStatus, { integrity: page.integrity }) : null
    ),
    page ? h(IntegrityNotice, { integrity: page.integrity, signing: props.status.record_signing }) : null,
    neverRecorded && !events.length
      ? list
      : h(
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
