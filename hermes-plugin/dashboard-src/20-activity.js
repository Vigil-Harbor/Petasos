
var RANGES = [
  { value: "1h", label: "1 hour", seconds: 3600 },
  { value: "24h", label: "24 hours", seconds: 86400 },
  { value: "7d", label: "7 days", seconds: 7 * 86400 },
  { value: "all", label: "All", seconds: null },
  { value: "custom", label: "Custom", seconds: null },
];

// An outcome filter is the list of outcome codes one of the API's figures covers.
function figureCodes(figure) {
  return (figure.outcomes || [figure.code]).slice().sort().join(",");
}

function figureFor(figures, value) {
  var wanted = String(value || "").split(",").filter(Boolean).sort().join(",");
  return (figures || []).filter(function (figure) {
    return figureCodes(figure) === wanted;
  })[0];
}

// Custom date ranges use browser-local time with an unambiguous year-month-day form.
function parseLocal(value) {
  var match = String(value || "").trim().match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})$/);
  if (!match) return null;
  var date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]));
  if (date.getMonth() !== Number(match[2]) - 1 || date.getDate() !== Number(match[3])) return null;
  if (Number(match[4]) > 23 || Number(match[5]) > 59) return null;
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
  useEffect(
    function () {
      if (props.onInvalid) props.onInvalid(invalid);
    },
    [invalid]
  );
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
  var tone =
    integrity.mode === "verified"
      ? integrity.unsigned
        ? "warning"
        : "success"
      : integrity.mode === "off" || integrity.mode === "unsigned"
        ? "warning"
        : "destructive";
  var badge = h(
    Status,
    { tone: tone, title: integrity.mode === "off" ? integrity.reason : undefined },
    integrity.label
  );
  if (!integrity.limit) return badge;
  return h(
    "div",
    { className: "petasos-integrity" },
    badge,
    h(
      LinkButton,
      { expanded: props.open, onClick: props.onToggle },
      props.open ? "Hide what a signature shows" : integrity.limit_label
    )
  );
}

function IntegrityNotice(props) {
  var integrity = props.integrity;
  var signing = props.signing || {};
  var openState = useState(false);
  if (!integrity) return null;
  if (integrity.mode === "off" && props.secretSet) {
    return h(
      Notice,
      { tone: "warning", title: "Signatures cannot be checked" },
      h(
        "p",
        null,
        "A session secret is set, but Petasos cannot make a signing key from it, so this page cannot tell which records are genuine." +
          (integrity.reason ? " " + sentenceCase(integrity.reason).replace(/\.?$/, ".") : "")
      ),
      h("p", null, "Running hermes petasos doctor names what is wrong with the secret.")
    );
  }
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
              openState[0] ? "Hide the steps" : "Set up record signing"
            )
          : null,
      },
      h("p", null, "Without a signature, a changed record could go unnoticed."),
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
  var unsigned = integrity.unsigned
    ? h(
        Notice,
        { tone: "info", title: plural(integrity.unsigned, "record has", "records have") + " no signature" },
        "A record without a signature may have been written before signing was set up, or by something other than Petasos. This page cannot tell which, and cannot say whether it changed."
      )
    : null;
  if (integrity.mode === "failed" || integrity.mode === "mixed") {
    return h(
      Fragment,
      null,
      h(
        Notice,
        { tone: "destructive", strong: true, title: "Some records do not match their signatures" },
        "A marked record could not be verified with this profile's current key. It may have been changed, written by something else, or signed with an earlier key. Treat its contents as unverified."
      ),
      unsigned
    );
  }
  return unsigned;
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
  var chosen = ["outcome", "kind", "tool", "session", "severity"].filter(function (key) {
    return filters[key];
  });
  var active = chosen.length > 0 || Boolean(filters.q);
  var openState = useState(chosen.length > 0);
  var open = openState[0];
  var figures = options.figures || [];
  var shownFigure = figureFor(figures, filters.outcome);
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
          "aria-label": "Search activity",
          placeholder: "Search activity",
          value: searchState[0],
          onChange: function (event) {
            searchState[1](event.target.value);
          },
          onBlur: function () {
            if (searchState[0].trim() !== (filters.q || "")) set("q", searchState[0].trim());
          },
        })
      ),
      h(
        Btn,
        {
          outlined: true,
          className: "petasos-filter-toggle",
          "aria-expanded": open,
          "aria-controls": "petasos-filter-selects",
          onClick: function () {
            openState[1](!open);
          },
        },
        (open ? "Hide filters" : "Filters") + (chosen.length ? " (" + chosen.length + " on)" : "")
      ),
      active
        ? h(
            Btn,
            {
              ghost: true,
              onClick: function () {
                openState[1](false);
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
            onInvalid: function (bad) {
              props.onRangeInvalid("from", bad);
            },
            value: filters.from || "",
            onChange: function (value) {
              set("from", value);
            },
          }),
          h(DateTimeField, {
            id: "petasos-to",
            label: "To",
            onInvalid: function (bad) {
              props.onRangeInvalid("to", bad);
            },
            value: filters.to || "",
            onChange: function (value) {
              set("to", value);
            },
          })
        )
      : null,
    open
      ? h(
      "div",
      { className: "petasos-filter-selects", id: "petasos-filter-selects" },
      h(Choice, {
        id: "petasos-filter-outcome",
        label: "Outcome",
        value: shownFigure ? shownFigure.code : filters.outcome ? "__current" : "any",
        options: [{ value: "any", label: "Any" }]
          .concat(
            figures.map(function (figure) {
              return { value: figure.code, label: figure.label + " (" + figure.count + ")" };
            })
          )
          .concat(filters.outcome && !shownFigure ? [{ value: "__current", label: props.word || filters.outcome }] : []),
        onChange: function (value) {
          if (value === "__current") return;
          var figure = figures.filter(function (item) {
            return item.code === value;
          })[0];
          set("outcome", figure ? figureCodes(figure) : value);
        },
      }),
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
      : null
  );
}

function EventRow(props) {
  var event = props.event;
  var outcome = event.outcome || {};
  var failed = event.integrity && event.integrity.status === "failed";
  var headline = event.headline || event.summary;
  var severityWord = event.severity_label || capital(event.severity);
  return h(
    "button",
    {
      type: "button",
      id: "petasos-event-" + event.scan_id,
      className: cn("petasos-event", props.selected && "petasos-event-selected", props.nested && "petasos-event-nested"),
      "aria-current": props.selected ? "true" : undefined,
      "aria-label":
        (props.selected ? "Open now: " : "Open details: ") +
        [
          headline,
          event.headline && event.explanation ? event.explanation : "",
          outcome.label || "Recorded",
          severityWord ? "severity " + severityWord : "",
          failed ? "signature does not match" : "",
          event.integrity && event.integrity.status === "unsigned" ? "no signature" : "",
          event.tool ? "tool " + event.tool : "",
          event.session_id ? "conversation " + event.session_id : "",
          listTime(event.timestamp),
        ]
          .filter(Boolean)
          .join(", "),
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
      h("span", { className: "petasos-event-summary" }, headline),
      event.headline && event.explanation ? h("span", { className: "petasos-event-explain" }, event.explanation) : null,
      h(
        "span",
        { className: "petasos-event-meta" },
        event.tool ? h(Mono, null, event.tool) : null,
        event.tool && event.session_id ? h("span", { "aria-hidden": true }, "·") : null,
        event.session_id ? h("span", null, event.session_id) : null,
        failed ? h(Status, { tone: "destructive" }, "Signature does not match") : null,
        event.integrity && event.integrity.status === "unsigned" ? h(Status, { tone: "neutral" }, "No signature") : null
      )
    ),
    h("span", { className: "petasos-event-severity" }, h(Severity, { value: event.severity, label: event.severity_label })),
    h("span", { className: "petasos-event-outcome" }, h(Status, { tone: outcomeTone(outcome.code), state: outcome.code }, outcome.label || "Recorded")),
    h(Icon, { name: "chevron", className: "petasos-chevron" })
  );
}

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
        "button",
        {
          type: "button",
          className: "petasos-disclosure-toggle",
          "aria-expanded": open,
          onClick: function () {
            openState[1](!open);
          },
        },
        h(Icon, { name: "chevron", size: 14, className: cn("petasos-disclosure-chevron", open && "petasos-chevron-open") }),
        h("span", null, open ? "Hide the " + count : "Show all " + count)
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

var SHOWN_FIELDS = {
  scan_id: 1, timestamp: 1, event_type: 1, tool: 1, session_id: 1, severity: 1, rule_id: 1, reason: 1,
  summary: 1, outcome: 1, kind_label: 1, rule_sentence: 1, integrity: 1, sig: 1, matched_note: 1,
  deferred_to: 1, score: 1, tier: 1, target: 1, outcome_note: 1, risk_block: 1, review_action: 1, risk_sentence: 1,
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
  var review = event.review_action;
  var risky = Boolean(event.session_id && event.risk_block);
  useEffect(
    function () {
      if (!ref.current) return;
      ref.current.focus({ preventScroll: true });
      // In one column the details sit above the list, possibly out of view.
      var box = ref.current.getBoundingClientRect();
      if (box.top < 0 || box.top > window.innerHeight - 160) revealInView(ref.current, "start");
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
      h(Status, { tone: outcomeTone(outcome.code), large: true, state: outcome.code }, outcome.label || "Recorded"),
      h(Severity, { value: event.severity, label: event.severity_label })
    ),
    h("h3", { className: "petasos-detail-title", id: "petasos-detail-title" }, event.headline || event.summary),
    event.headline && event.explanation ? h("p", { className: "petasos-detail-note" }, event.explanation) : null,
    event.outcome_note ? h("p", { className: "petasos-detail-note" }, event.outcome_note) : null,
    event.risk_sentence ? h("p", { className: "petasos-detail-note" }, event.risk_sentence) : null,
    review || risky
      ? h(
          "div",
          { className: "petasos-row-actions" },
          review
            ? h(Btn, { outlined: true, onClick: function () { go("settings", { changed: "1" }); } }, review)
            : null,
          risky
            ? h(
                Btn,
                {
                  outlined: true,
                  onClick: function () {
                    props.onFilter({ range: "all", session: event.session_id, event: event.scan_id });
                  },
                },
                "Show earlier warnings"
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
        ["Left for", event.deferred_to || null],
        ["Conversation risk", typeof event.score === "number" ? String(event.score) + " points" : null],
        ["Risk tier", event.tier || null],
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
      rule && rule.indexOf("petasos.selfmod.") !== 0
        ? h(
            Btn,
            {
              outlined: true,
              onClick: function () {
                go("tryit", {
                  rule: rule,
                  sentence: event.rule_sentence || "",
                  direction: event.event_type === "ingest_flagged" ? "inbound" : "outbound",
                });
              },
            },
            "Try this rule"
          )
        : null,
      rule && rule.indexOf("petasos.syntactic.") === 0
        ? h(LinkButton, { onClick: function () { go("settings", { rule: rule }); } }, "Rule settings")
        : null,
      event.session_id && !risky
        ? h(
            LinkButton,
            {
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

function sideBySide() {
  return window.innerWidth > 1100;
}

function inView(element) {
  var box = element.getBoundingClientRect();
  return box.top >= 80 && box.bottom <= window.innerHeight - 40;
}

function Activity(props) {
  var params = props.route.params;
  var filters = filtersFromRoute(params);
  var selectedId = params.event || "";
  // Rows, counts and signature status are read together and kept with the
  // filters that produced them, so one selection is never shown under another.
  var filterKey = JSON.stringify(filters);
  var dataState = useState(null);
  var failureState = useState(null);
  var olderState = useState({ key: filterKey, chunks: [] });
  var loadingMore = useState(false);
  var extraEvent = useState(null);
  var limitState = useState(false);
  var retryState = useState(0);
  var returnTo = useRef("");
  var anchored = useRef(false);
  var noteState = useState("");
  var lookupState = useState(0);
  var olderFailureState = useState(null);
  var badDateState = useState({});
  var begin = useLatest();

  function setFilters(next) {
    var route = Object.assign({}, next);
    Object.keys(route).forEach(function (key) {
      if (!route[key]) delete route[key];
    });
    go("activity", route);
  }

  function requestNow() {
    var span = rangeWindow(filters);
    return {
      limit: 100,
      since: span.since,
      until: span.until,
      q: filters.q,
      kind: filters.kind,
      tool: filters.tool,
      session: filters.session,
      severity: filters.severity,
      outcome: filters.outcome,
    };
  }

  var unreadableDate = filters.range === "custom" && (badDateState[0].from || badDateState[0].to);
  var customSpan = filters.range === "custom" ? rangeWindow(filters) : null;
  var backwards = Boolean(customSpan && customSpan.since && customSpan.until && customSpan.since > customSpan.until);
  usePoll(
    function () {
      // With older pages open the list is one fixed reading: a refreshed first
      // page under them could drop or repeat events at the seam.
      if (anchored.current || backwards) return null;
      var latest = begin();
      var live = requestNow();
      if (!live.until) live.until = Math.floor(Date.now() / 1000);
      var counted = Object.assign({}, live);
      delete counted.limit;
      return Promise.all([
        call("/activity" + query(live)),
        call("/activity/summary" + query({ since: live.since, until: live.until, q: filters.q })),
        call("/activity/summary" + query(counted)),
      ]).then(
        function (answers) {
          if (!latest()) return;
          dataState[1]({ key: filterKey, page: answers[0], options: answers[1], counts: answers[2], request: live, readAt: Date.now() });
          failureState[1](null);
        },
        function (failure) {
          if (latest()) failureState[1]({ key: filterKey, failure: failure });
        }
      );
    },
    15000,
    [filterKey, props.refreshKey, retryState[0]]
  );

  var data = dataState[0] && dataState[0].key === filterKey ? dataState[0] : null;
  var failure = failureState[0] && failureState[0].key === filterKey ? failureState[0].failure : null;
  var page = data && data.page;
  var older = olderState[0].key === filterKey ? olderState[0].chunks : [];
  var olderFailure = olderFailureState[0] && olderFailureState[0].key === filterKey ? olderFailureState[0].failure : null;
  if (!older.length && !loadingMore[0] && !olderFailure) anchored.current = false;

  function loadOlder() {
    var last = older.length ? older[older.length - 1] : page;
    if (!last || !last.next_cursor) return;
    var key = filterKey;
    // From here the list is one reading: a refresh already under way must not
    // replace the first page, and older pages use the same time bounds as it.
    anchored.current = true;
    begin();
    loadingMore[1](true);
    olderFailureState[1](null);
    call("/activity" + query(Object.assign({}, data.request, { cursor: last.next_cursor })))
      .then(
        function (body) {
          if (body.cursor_reset) {
            // The record was rotated under the cursor: rows, counts and signatures are all read again.
            reload("The record was rotated while you were reading, so the list was reloaded from the newest event.");
            return;
          }
          olderState[1](function (held) {
            return { key: key, chunks: (held.key === key ? held.chunks : []).concat([body]) };
          });
        },
        function (problem) {
          olderFailureState[1]({ key: key, failure: problem });
        }
      )
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

  useEffect(
    function () {
      if (!selectedId || selected || !page) return;
      var live = true;
      extraEvent[1]({ id: selectedId, state: "loading" });
      call("/activity/" + encodeURIComponent(selectedId)).then(
        function (body) {
          if (live) extraEvent[1](body.event ? { id: selectedId, state: "found", event: body.event } : { id: selectedId, state: "missing" });
        },
        function (problem) {
          if (live) extraEvent[1]({ id: selectedId, state: problem.status === 404 ? "missing" : "failed", failure: problem });
        }
      );
      return function () {
        live = false;
      };
    },
    [selectedId, Boolean(selected), Boolean(page), lookupState[0]]
  );
  var lookup = !selected && extraEvent[0] && extraEvent[0].id === selectedId ? extraEvent[0] : null;
  if (lookup && lookup.state === "found") selected = lookup.event;

  // Beside the details, keep the open row in sight. In one column the details
  // own the scroll position; the row is shown again when they close.
  useEffect(
    function () {
      if (selectedId) {
        if (!selectedInList || !sideBySide()) return;
        var row = document.getElementById("petasos-event-" + selectedId);
        if (row && !inView(row)) revealInView(row, "center");
        return;
      }
      var id = returnTo.current;
      returnTo.current = "";
      if (!id) return;
      var closed = document.getElementById("petasos-event-" + id);
      if (!closed) return;
      closed.focus({ preventScroll: true });
      if (!inView(closed)) revealInView(closed, "center");
    },
    [selectedId, selectedInList]
  );

  var tail = older.length ? older[older.length - 1] : page;
  var skipped = older.reduce(function (most, chunk) {
    return Math.max(most, chunk.skipped_lines || 0);
  }, page ? page.skipped_lines || 0 : 0);
  var skippedWords = (older.length ? "at least " : "") + plural(skipped, "line");
  var options = data && data.options;
  var counts = data && data.counts;
  var filtered = filters.kind || filters.tool || filters.session || filters.severity || filters.q || filters.outcome;
  var neverRecorded = options && options.total === 0 && options.complete !== false && !filtered && filters.range === "all";

  function open(event) {
    go("activity", Object.assign({}, params, { event: event.scan_id }));
  }
  function close() {
    returnTo.current = selectedId;
    var route = Object.assign({}, params);
    delete route.event;
    go("activity", route);
  }
  function reload(note) {
    olderState[1]({ key: filterKey, chunks: [] });
    olderFailureState[1](null);
    anchored.current = false;
    noteState[1](note || "");
    retryState[1](function (n) {
      return n + 1;
    });
  }
  function retry() {
    reload("");
  }

  var list;
  if ((!page && failure) || backwards || unreadableDate) {
    list = null;
  } else if (!page) {
    list = h("p", { className: "petasos-secondary", role: "status" }, "Loading activity…");
  } else if (!events.length && skipped) {
    list = h(
      Empty,
      { title: "No readable events" },
      plural(skipped, "line") + " of the record could not be read as events, so this page cannot say what " + (skipped === 1 ? "it holds" : "they hold") + "."
    );
  } else if (!events.length && neverRecorded) {
    list = h(
      Empty,
      {
        title: "Nothing recorded yet",
        action: h(Btn, { outlined: true, onClick: function () { go("tryit", { example: "notes" }); } }, "Try it"),
      },
      "Blocks, approval requests and warnings are recorded here. Clean actions are not."
    );
  } else if (!events.length && page.complete === false) {
    list = h(
      Empty,
      { title: "Nothing found in the part of the record that was read" },
      "The record is too large to read in full here, so older events were not searched."
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
      filtered ? "Try a longer time range or fewer filters." : "No blocks, approval requests or warnings in this time."
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
            olderFailure
              ? h("p", { className: "petasos-field-error", role: "alert" }, "Older events could not be loaded. " + olderFailure.message + " The events above are unchanged.")
              : null,
            h(
              Btn,
              { outlined: true, onClick: loadOlder, disabled: loadingMore[0] },
              loadingMore[0] ? "Loading…" : olderFailure ? "Try loading older events again" : "Show older events"
            )
          )
        : tail && tail.complete === false
          ? h("p", { className: "petasos-secondary petasos-end" }, "Older events were not read.")
          : null
    );
  }

  // The badge speaks for every counted event, not only the page on screen.
  var listIntegrity = (counts && counts.integrity) || (page && page.integrity);
  var count = counts
    ? plural(counts.total, "event") +
      " · " +
      plural(counts.blocked || 0, "tool call") +
      " blocked" +
      (counts.complete === false ? " · counted in the part of the record that was read" : "")
    : "";

  return h(
    "div",
    { className: "petasos-stack petasos-activity" },
    h(ActivityFilters, {
      filters: filters,
      options: options,
      word: params.word,
      onChange: setFilters,
      onRangeInvalid: function (which, bad) {
        badDateState[1](function (held) {
          var next = Object.assign({}, held);
          next[which] = bad;
          return next;
        });
      },
    }),
    unreadableDate
      ? h(
          Notice,
          { tone: "warning", title: "A date in the time range cannot be read" },
          "Nothing is shown until it is fixed, because the list would be for a different range than the one typed."
        )
      : null,
    backwards
      ? h(Notice, { tone: "warning", title: "The time range ends before it starts" }, "Nothing was searched. Set From earlier than To.")
      : null,
    !page && failure
      ? h(
          Notice,
          {
            tone: "destructive",
            title: "The activity record could not be read",
            action: h(Btn, { onClick: retry }, "Try again"),
          },
          h("p", null, "Nothing is listed because the read failed, not because nothing happened."),
          h("p", { className: "petasos-tertiary" }, failure.message)
        )
      : null,
    page && failure
      ? h(
          Notice,
          {
            tone: "warning",
            title: "Could not refresh",
            action: h(Btn, { ghost: true, onClick: retry }, "Try again"),
          },
          "These events, counts and signatures were read at " + clockTime(data.readAt) + ". " + failure.message
        )
      : null,
    page && !unreadableDate
      ? h(
          "div",
          { className: "petasos-listbar" },
          h(
            "p",
            { className: "petasos-listbar-count", role: "status" },
            count && (!neverRecorded || skipped) ? h("span", { className: "petasos-count" }, count) : null,
            events.length ? h("span", { className: "petasos-secondary" }, " · Newest first · Times in " + timeZoneName()) : null,
            skipped
              ? h(
                  "span",
                  { className: "petasos-strong" },
                  " · " + skippedWords + " of the record could not be read and " + (skipped === 1 ? "is" : "are") + " not counted or verified"
                )
              : null
          ),
          h(IntegrityStatus, {
            integrity: listIntegrity,
            open: limitState[0],
            onToggle: function () {
              limitState[1](!limitState[0]);
            },
          })
        )
      : null,
    listIntegrity && listIntegrity.limit && limitState[0]
      ? h("p", { className: "petasos-integrity-note", role: "status" }, listIntegrity.limit)
      : null,
    noteState[0] ? h(Notice, { tone: "info", title: "List reloaded" }, noteState[0]) : null,
    anchored.current && data
      ? h(
          "p",
          { className: "petasos-secondary", role: "status" },
          "Showing one reading from " + clockTime(data.readAt) + " so older pages stay in order. New events are not added. ",
          h(Btn, { ghost: true, compact: true, onClick: retry }, "Reload from the newest")
        )
      : null,
    page
      ? h(IntegrityNotice, {
          integrity: listIntegrity,
          signing: props.status.record_signing,
          secretSet: Boolean(props.status.secrets && props.status.secrets.session_secret === "set"),
        })
      : null,
    !list
      ? null
      : neverRecorded && !events.length && !skipped
        ? list
        : h(
            "div",
            { className: cn("petasos-split", (selected || lookup) && "petasos-split-open") },
            h("div", { className: "petasos-split-main" }, h(C.Card, { className: "petasos-panel petasos-list-card" }, list)),
            selected
              ? h(EventDetail, {
                  event: selected,
                  onClose: close,
                  onFilter: function (patch) {
                    setFilters(Object.assign({}, filters, patch));
                  },
                })
              : lookup
                ? h(
                    "aside",
                    { className: "petasos-detail", "aria-label": "Event details", role: "status" },
                    h(
                      "div",
                      { className: "petasos-detail-head" },
                      h("p", { className: "petasos-detail-which" }, "Event ", h(Ident, null, selectedId)),
                      h(Btn, { ghost: true, onClick: close, "aria-label": "Close event details" }, "Close")
                    ),
                    lookup.state === "loading"
                      ? h("p", { className: "petasos-secondary" }, "Loading this event…")
                      : lookup.state === "missing"
                        ? h("p", null, (lookup.failure && lookup.failure.message) || "That event was not found.")
                        : h(
                            Fragment,
                            null,
                            h("p", null, "This event could not be read. " + ((lookup.failure && lookup.failure.message) || "")),
                            h("div", { className: "petasos-row-actions" }, h(Btn, { onClick: function () { lookupState[1](lookupState[0] + 1); } }, "Try again"))
                          )
                  )
                : null
          )
  );
}
