// ---------------------------------------------------------------------------
// Kit: the Hermes SDK, the API client, and small shared pieces.
//
// Everything visual comes from Hermes: its React, its components (Card,
// Button, Badge, Select, Input, Label, ConfirmDialog, Toast), its fonts and
// its colour variables. Where the SDK does not export a Hermes control
// (Segmented, Switch), the tab draws the same markup with the same tokens.
// Everything Petasos knows (roles, levels, settings, labels, rules,
// sentences) comes from the plugin's API at /api/plugins/petasos/. This file
// holds interface wording only.
// ---------------------------------------------------------------------------

var SDK = window.__HERMES_PLUGIN_SDK__;
var PLUGINS = window.__HERMES_PLUGINS__;
if (!SDK || !PLUGINS || !SDK.React) {
  return;
}

var React = SDK.React;
var h = React.createElement;
var Fragment = React.Fragment;
var useState = SDK.hooks.useState;
var useEffect = SDK.hooks.useEffect;
var useCallback = SDK.hooks.useCallback;
var useMemo = SDK.hooks.useMemo;
var useRef = SDK.hooks.useRef;
var C = SDK.components;
var cn = SDK.utils.cn;

var API = "/api/plugins/petasos";

// One request to the plugin API. A failure is thrown as an ApiFailure with
// the HTTP status and the API's own code and sentence when it sent one.
function ApiFailure(status, code, message, path) {
  this.status = status;
  this.code = code;
  this.message = message;
  this.path = path || null;
}

// Hermes's fetchJSON throws an error carrying ``status`` and the raw
// ``body``. Older hosts threw Error("<status>: <body>"); both are read.
function parseFailure(err) {
  var raw = err && err.message ? String(err.message) : String(err || "");
  var status = 0;
  var body = "";
  if (err && typeof err.status === "number") {
    status = err.status;
    body = typeof err.body === "string" ? err.body : "";
  } else {
    var match = raw.match(/^(\d{3}):\s*([\s\S]*)$/);
    status = match ? Number(match[1]) : 0;
    body = match ? match[2] : "";
  }
  try {
    var parsed = JSON.parse(body);
    if (parsed && parsed.error) {
      return new ApiFailure(status, parsed.error.code, parsed.error.message, parsed.error.path);
    }
    if (parsed && typeof parsed.detail === "string") {
      return new ApiFailure(status, "http", parsed.detail, null);
    }
  } catch (_e) {
    // Not JSON. Fall through.
  }
  if (status === 0) {
    return new ApiFailure(0, "unreachable", "The dashboard could not reach Petasos.", null);
  }
  return new ApiFailure(status, "http", "Petasos answered with an error (" + status + ").", null);
}

function call(path, options) {
  var init = { method: (options && options.method) || "GET" };
  if (options && options.body !== undefined) {
    init.body = JSON.stringify(options.body);
    init.headers = { "Content-Type": "application/json" };
  }
  return SDK.fetchJSON(API + path, init).catch(function (err) {
    throw parseFailure(err);
  });
}

function query(params) {
  var parts = [];
  Object.keys(params).forEach(function (key) {
    var value = params[key];
    if (value === undefined || value === null || value === "") return;
    parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(String(value)));
  });
  return parts.length ? "?" + parts.join("&") : "";
}

// ---------------------------------------------------------------------------
// The tab's own address: #overview, #activity?event=…, #settings?rule=…
// The view lives in the hash so a link (and the browser's back button) can
// open a view, an event, or the settings for one rule.
// ---------------------------------------------------------------------------

var VIEWS = ["overview", "activity", "tryit", "settings"];

// Hermes adds ?profile=… to the address on arrival and drops the fragment.
// Put back the fragment the page was opened with, once, so a pasted link
// still opens the view it names.
(function restoreArrivalHash() {
  if (window.location.hash) return;
  var entries = window.performance && window.performance.getEntriesByType
    ? window.performance.getEntriesByType("navigation")
    : [];
  var first = entries && entries[0] && entries[0].name;
  var at = first ? first.indexOf("#") : -1;
  if (at < 0) return;
  var fragment = first.slice(at);
  if (VIEWS.indexOf(fragment.slice(1).split("?")[0]) < 0) return;
  window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search + fragment);
})();

function readRoute() {
  var raw = (window.location.hash || "").replace(/^#/, "");
  var parts = raw.split("?");
  var view = VIEWS.indexOf(parts[0]) >= 0 ? parts[0] : "overview";
  var params = {};
  if (parts[1]) {
    parts[1].split("&").forEach(function (pair) {
      var kv = pair.split("=");
      if (kv[0]) params[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || "");
    });
  }
  return { view: view, params: params };
}

function go(view, params) {
  var next = "#" + view + query(params || {});
  if (window.location.hash !== next) {
    window.location.hash = next;
  }
}

function useRoute() {
  var state = useState(readRoute);
  useEffect(function () {
    function onChange() {
      state[1](readRoute());
    }
    window.addEventListener("hashchange", onChange);
    return function () {
      window.removeEventListener("hashchange", onChange);
    };
  }, []);
  return state[0];
}

// Run ``load`` now and every ``ms`` while the page is visible. Polling is
// the only refresh: the API has no stream. A hidden tab does not poll.
function usePoll(load, ms, deps) {
  useEffect(function () {
    var stopped = false;
    function tick() {
      if (!stopped && document.visibilityState !== "hidden") load();
    }
    load();
    var timer = window.setInterval(tick, ms);
    document.addEventListener("visibilitychange", tick);
    return function () {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, deps);
}

// ---------------------------------------------------------------------------
// Names. Every name a person reads comes from the API's labels. These look
// them up; a name the API did not label is shown as it was sent.
// ---------------------------------------------------------------------------

function roleOf(catalog, name) {
  return ((catalog && catalog.roles) || []).filter(function (role) {
    return role.name === name;
  })[0];
}

function levelOf(catalog, name) {
  return ((catalog && catalog.levels) || []).filter(function (level) {
    return level.name === name;
  })[0];
}

function roleLabel(catalog, name) {
  var role = roleOf(catalog, name);
  return (role && role.label) || name || "";
}

function levelLabel(catalog, name) {
  var level = levelOf(catalog, name);
  return (level && level.label) || name || "";
}

function rowsByPath(rows) {
  var found = {};
  (rows || []).forEach(function (row) {
    found[row.path] = row;
  });
  return found;
}

function sectionsByPath(catalog) {
  var found = {};
  ((catalog && catalog.sections) || []).forEach(function (item) {
    found[item.path] = item;
  });
  return found;
}

function rowLabel(row) {
  return (row && row.label) || (row && row.path) || "";
}

// Where a value comes from, in words. The job and strictness are named by
// their labels.
function originText(origin, stored, catalog) {
  if (origin === "role") return "From the job (" + roleLabel(catalog, stored && stored.role) + ")";
  if (origin === "level") return "From strictness (" + levelLabel(catalog, stored && stored.level) + ")";
  if (origin === "override") return "Your setting";
  if (origin === "default") return "Default";
  return "Unknown";
}

// One value as a person reads it. A choice uses the API's label for it.
function showValue(value, row) {
  if (value === null || value === undefined) return "not set";
  if (row && row.choice_labels && Object.prototype.hasOwnProperty.call(row.choice_labels, String(value))) {
    return row.choice_labels[String(value)];
  }
  if (value === true) return "On";
  if (value === false) return "Off";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
  if (typeof value === "object") {
    var keys = Object.keys(value);
    if (!keys.length) return "none";
    return keys
      .map(function (key) {
        return key + ": " + showValue(value[key]);
      })
      .join(", ");
  }
  return String(value);
}

function plural(count, one, many) {
  return count + " " + (count === 1 ? one : many || one + "s");
}

function capital(word) {
  var text = String(word || "");
  return text ? text.charAt(0).toUpperCase() + text.slice(1).toLowerCase() : "";
}

// ---------------------------------------------------------------------------
// Time. Lists show a full date when the record spans days; details show the
// year and the time zone. Relative age is secondary.
// ---------------------------------------------------------------------------

function whenText(seconds) {
  if (typeof seconds !== "number") return "";
  // Hermes's timeAgo takes unix seconds (its type comment says milliseconds).
  return SDK.utils.timeAgo(seconds);
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function listTime(seconds) {
  if (typeof seconds !== "number") return "";
  var date = new Date(seconds * 1000);
  var now = new Date();
  var clock = date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (sameDay(date, now)) return "Today " + clock;
  var options = { day: "numeric", month: "short" };
  if (date.getFullYear() !== now.getFullYear()) options.year = "numeric";
  return date.toLocaleDateString(undefined, options) + " " + clock;
}

function fullTime(seconds) {
  if (typeof seconds !== "number") return "";
  return new Date(seconds * 1000).toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
}

function clockTime(ms) {
  return new Date(ms).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// ---------------------------------------------------------------------------
// Small pieces built from Hermes components.
// ---------------------------------------------------------------------------

// A Hermes Card with the title row Hermes uses on its own pages.
function Panel(props) {
  return h(
    C.Card,
    { className: cn("petasos-panel", props.className), id: props.id },
    props.title || props.actions
      ? h(
          C.CardHeader,
          { className: "petasos-panel-head" },
          h(
            "div",
            { className: "petasos-panel-headrow" },
            h(
              "div",
              { className: "petasos-panel-titles" },
              props.title
                ? h(C.CardTitle, { className: "text-sm petasos-panel-title", id: props.titleId }, props.title)
                : null,
              props.description ? h("p", { className: "petasos-panel-desc" }, props.description) : null
            ),
            props.actions ? h("div", { className: "petasos-panel-actions" }, props.actions) : null
          )
        )
      : null,
    h(C.CardContent, { className: cn("petasos-panel-body", props.bodyClassName) }, props.children)
  );
}

// A status that carries a safety meaning (outcome, severity, verdict, check
// state): Hermes's sans at a readable size, with stronger contrast. Words
// always say the same thing as the colour.
var TONES = ["success", "warning", "destructive", "neutral"];

function Status(props) {
  var tone = TONES.indexOf(props.tone) >= 0 ? props.tone : "neutral";
  return h(
    "span",
    {
      className: cn("petasos-status", "petasos-status-" + tone, props.large && "petasos-status-large", props.className),
      title: props.title,
    },
    h("span", { className: "petasos-status-dot", "aria-hidden": true }),
    props.children
  );
}

// An incidental label: Hermes's own badge, as Hermes draws it.
function Tag(props) {
  return h(C.Badge, { tone: props.tone || "secondary", className: cn("petasos-tag", props.className), title: props.title }, props.children);
}

var SEVERITY_TONE = {
  critical: "destructive",
  high: "destructive",
  medium: "warning",
  low: "neutral",
  info: "neutral",
};

function Severity(props) {
  var severity = String(props.value || "").toLowerCase();
  if (!severity) return h("span", { className: "petasos-none", "aria-label": "No severity" }, "—");
  return h(Status, { tone: SEVERITY_TONE[severity] || "neutral" }, capital(severity));
}

function outcomeTone(code) {
  var destructive = ["blocked", "stopped", "declined", "not_stopped", "attempt_blocked", "block"];
  var warning = ["asked", "attempt_asked", "flagged", "allowed", "degraded", "unchecked", "approve", "flag", "none"];
  if (destructive.indexOf(code) >= 0) return "destructive";
  if (warning.indexOf(code) >= 0) return "warning";
  if (code === "approved" || code === "allow") return "success";
  return "neutral";
}

// A notice. The tone is a dot and a word, not a thick edge; only an
// exceptional warning (``strong``) keeps the marked edge.
function Notice(props) {
  var tone = props.tone || "info";
  return h(
    "div",
    {
      className: cn("petasos-notice", "petasos-notice-" + tone, props.strong && "petasos-notice-strong", props.className),
      role: tone === "destructive" ? "alert" : "status",
    },
    h(
      "div",
      { className: "petasos-notice-text" },
      props.title
        ? h(
            "p",
            { className: "petasos-notice-title" },
            h("span", { className: "petasos-notice-dot", "aria-hidden": true }),
            props.title
          )
        : null,
      props.children ? h("div", { className: "petasos-notice-body" }, props.children) : null
    ),
    props.action ? h("div", { className: "petasos-notice-action" }, props.action) : null
  );
}

// The empty list, as Hermes's Sessions page draws it: a small icon, a short
// title, one line, on the page background.
function Empty(props) {
  return h(
    "div",
    { className: "petasos-empty", role: "status" },
    h(Icon, { name: props.icon || "clock", className: "petasos-empty-icon" }),
    h("p", { className: "petasos-empty-title" }, props.title),
    props.children ? h("p", { className: "petasos-empty-body" }, props.children) : null,
    props.action ? h("div", { className: "petasos-empty-action" }, props.action) : null
  );
}

// Outline icons drawn inline in the current colour, the style Hermes's
// pages use. No image files.
var ICONS = {
  clock: ["M12 6v6l4 2", "M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20"],
  chevron: ["M9 6l6 6l-6 6"],
  copy: ["M9 9h11v11H9z", "M5 15H4V4h11v1"],
  search: ["M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14", "M20 20l-4-4"],
  shield: ["M12 3l8 3v6c0 5-3.5 8-8 9c-4.5-1-8-4-8-9V6z"],
};

function Icon(props) {
  return h(
    "svg",
    {
      className: cn("petasos-icon", props.className),
      viewBox: "0 0 24 24",
      width: props.size || 16,
      height: props.size || 16,
      fill: "none",
      stroke: "currentColor",
      strokeWidth: 1.75,
      strokeLinecap: "round",
      strokeLinejoin: "round",
      "aria-hidden": true,
      focusable: "false",
    },
    (ICONS[props.name] || []).map(function (d, i) {
      return h("path", { key: i, d: d });
    })
  );
}

function Btn(props) {
  var rest = Object.assign({}, props);
  delete rest.children;
  rest.type = rest.type || "button";
  rest.size = rest.size || "sm";
  return h(C.Button, rest, props.children);
}

// A text action: underlined, so it reads as a link in every theme.
function LinkButton(props) {
  return h(
    "button",
    {
      type: "button",
      className: cn("petasos-link", props.className),
      onClick: props.onClick,
      "aria-label": props.label,
      "aria-expanded": props.expanded,
      disabled: props.disabled,
    },
    props.children
  );
}

function Mono(props) {
  return h("code", { className: cn("petasos-mono", props.className), title: props.title }, props.children);
}

// A technical identifier that may wrap only after its separators, never
// in the middle of a word.
function Ident(props) {
  var text = String(props.children || "");
  var parts = [];
  var buffer = "";
  for (var i = 0; i < text.length; i += 1) {
    buffer += text[i];
    if (/[./_:-]/.test(text[i]) && i < text.length - 1) {
      parts.push(buffer);
      parts.push(h("wbr", { key: "w" + i }));
      buffer = "";
    }
  }
  parts.push(buffer);
  return h("code", { className: cn("petasos-mono petasos-ident", props.className) }, parts);
}

function CopyButton(props) {
  var doneState = useState(false);
  return h(
    "button",
    {
      type: "button",
      className: "petasos-copy",
      "aria-label": props.label || "Copy",
      title: props.label || "Copy",
      onClick: function () {
        var text = String(props.value || "");
        var write = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(text) : Promise.reject();
        write
          .then(function () {
            doneState[1](true);
            window.setTimeout(function () {
              doneState[1](false);
            }, 1500);
          })
          .catch(function () {});
      },
    },
    h(Icon, { name: "copy", size: 14 }),
    h("span", { className: "petasos-copy-text" }, doneState[0] ? "Copied" : "Copy")
  );
}

// Hermes's Select with a label above it.
function Choice(props) {
  return h(
    "div",
    { className: cn("petasos-choice", props.className) },
    props.label ? h(C.Label, { className: "petasos-label", htmlFor: props.id }, props.label) : null,
    h(
      C.Select,
      {
        id: props.id,
        value: props.value,
        onValueChange: props.onChange,
        disabled: props.disabled,
        placeholder: props.placeholder,
        "aria-describedby": props.describedBy,
      },
      props.options.map(function (option) {
        return h(C.SelectOption, { key: option.value, value: option.value }, option.label);
      })
    )
  );
}

// Arrow keys move along a row of options, as a native radio group does.
function arrowKeys(event, values, current, onChange, focusPrefix) {
  var keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1, Home: "first", End: "last" };
  var step = keys[event.key];
  if (step === undefined) return;
  event.preventDefault();
  var index = values.indexOf(current);
  var next;
  if (step === "first") next = 0;
  else if (step === "last") next = values.length - 1;
  else next = (index + step + values.length) % values.length;
  onChange(values[next]);
  var target = document.getElementById(focusPrefix + values[next]);
  if (target) target.focus();
}

// Hermes's Segmented control (Logs, Sessions): joined rectangular buttons,
// the chosen one filled. One choice of several, with arrow keys.
function Segmented(props) {
  var values = props.options.map(function (option) {
    return option.value;
  });
  var prefix = (props.id || "petasos-seg") + "-";
  return h(
    "div",
    {
      className: cn("petasos-segmented", props.className),
      role: "radiogroup",
      "aria-label": props.label,
      "aria-labelledby": props.labelledBy,
    },
    props.options.map(function (option) {
      var active = option.value === props.value;
      return h(
        "button",
        {
          key: option.value,
          id: prefix + option.value,
          type: "button",
          role: "radio",
          "aria-checked": active,
          tabIndex: active || (props.value === undefined && option === props.options[0]) ? 0 : -1,
          disabled: props.disabled,
          className: cn("petasos-segment", active && "petasos-segment-on"),
          onClick: function () {
            props.onChange(option.value);
          },
          onKeyDown: function (event) {
            arrowKeys(event, values, props.value, props.onChange, prefix);
          },
        },
        option.label,
        option.mark ? h("span", { className: "petasos-segment-mark" }, option.mark) : null
      );
    })
  );
}

// Hermes's Switch: a rectangular track and square thumb at the end of a row.
function Switch(props) {
  return h(
    "button",
    {
      id: props.id,
      type: "button",
      role: "switch",
      "aria-checked": Boolean(props.checked),
      "aria-labelledby": props.labelledBy,
      "aria-label": props.label,
      "aria-describedby": props.describedBy,
      disabled: props.disabled,
      className: cn("petasos-switch", props.checked && "petasos-switch-on"),
      onClick: function () {
        props.onChange(!props.checked);
      },
    },
    h("span", { className: "petasos-switch-thumb", "aria-hidden": true })
  );
}

// The view tabs, drawn as Hermes's enclosed segmented tabs (Sessions, Logs).
function ViewTabs(props) {
  var values = props.views.map(function (view) {
    return view.value;
  });
  return h(
    "div",
    { className: "petasos-segmented petasos-viewtabs", role: "tablist", "aria-label": props.label },
    props.views.map(function (view) {
      var active = view.value === props.value;
      return h(
        "button",
        {
          key: view.value,
          id: "petasos-tab-" + view.value,
          type: "button",
          role: "tab",
          "aria-selected": active,
          "aria-controls": "petasos-panel",
          tabIndex: active ? 0 : -1,
          className: cn("petasos-segment", active && "petasos-segment-on"),
          onClick: function () {
            props.onChange(view.value);
          },
          onKeyDown: function (event) {
            arrowKeys(event, values, props.value, props.onChange, "petasos-tab-");
          },
        },
        view.label
      );
    })
  );
}

// Config's field layout: the label, the setting's key in faint mono, one
// plain sentence, then the control across the panel. A switch sits at the
// end of the label row instead.
function Field(props) {
  var labelId = props.id + "-label";
  var helpId = props.id + "-help";
  return h(
    "div",
    {
      className: cn("petasos-field", props.inline && "petasos-field-inline", props.className),
      id: props.rowId,
    },
    h(
      "div",
      { className: "petasos-field-head" },
      h(
        "div",
        { className: "petasos-field-text" },
        h(C.Label, { className: "petasos-field-label", htmlFor: props.inline ? undefined : props.id, id: labelId }, props.label),
        props.path ? h("span", { className: "petasos-field-key" }, props.path) : null,
        props.help ? h("p", { className: "petasos-field-help", id: helpId }, props.help) : null
      ),
      props.inline ? h("div", { className: "petasos-field-switch" }, props.control) : null
    ),
    props.inline ? null : h("div", { className: "petasos-field-control" }, props.control),
    props.children
  );
}

function KeyValues(props) {
  return h(
    "dl",
    { className: cn("petasos-kv", props.stacked && "petasos-kv-stacked", props.className) },
    props.rows
      .filter(function (row) {
        return row && row[1] !== undefined && row[1] !== null && row[1] !== "";
      })
      .map(function (row) {
        return h(Fragment, { key: row[0] }, h("dt", null, row[0]), h("dd", null, row[1]));
      })
  );
}

// Scroll the nearest scrolling container so ``element`` is in view. Unlike
// scrollIntoView, this never moves Hermes's own page frame.
function revealInView(element, where) {
  if (!element) return;
  var node = element.parentElement;
  while (node && node !== document.body) {
    var style = window.getComputedStyle(node);
    if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) break;
    node = node.parentElement;
  }
  if (!node || node === document.body) return;
  var box = element.getBoundingClientRect();
  var frame = node.getBoundingClientRect();
  var offset = box.top - frame.top;
  if (where === "center") offset -= (frame.height - box.height) / 2;
  else offset -= 16;
  node.scrollTop += offset;
}
