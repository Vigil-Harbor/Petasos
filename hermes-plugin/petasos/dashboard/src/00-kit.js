// ---------------------------------------------------------------------------
// Kit: the Hermes SDK, the API client, and small shared pieces.
//
// Everything visual comes from Hermes: its React, its components (Card,
// Button, Badge, Select, Input, Tabs, ConfirmDialog, Toast), its fonts and
// its colour variables. Petasos adds layout rules in style.css and nothing
// else. Everything Petasos knows (roles, levels, fields, rules, sentences)
// comes from the plugin's API at /api/plugins/petasos/.
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
// Words. The two choices a casual user makes get plain copy here, keyed by
// the API's names. An unknown name falls back to the API's own sentence, so
// a new role or level still shows correctly.
// ---------------------------------------------------------------------------

var JOB_COPY = {
  general: {
    label: "General",
    plain: "A bit of everything. Every check runs at its usual sensitivity.",
  },
  coding: {
    label: "Coding",
    plain:
      "Writes and runs code on your machine. Checks that trip on ordinary code are quieter, " +
      "and risky commands wait for you to approve them.",
  },
  research: {
    label: "Research",
    plain:
      "Reads a lot of web pages. Ignores the odd characters pages are full of, " +
      "and only reports what it is fairly sure of.",
  },
  support: {
    label: "Customer support",
    plain:
      "Talks to people outside your team. Treats attempts to take over the agent as " +
      "serious, and watches for names, emails and phone numbers.",
  },
  admin: {
    label: "Admin",
    plain:
      "Has powerful access. Watches for personal and financial details such as names, " +
      "card numbers and bank accounts.",
  },
};

var LEVEL_COPY = {
  relaxed: {
    label: "Relaxed",
    plain:
      "Fewer interruptions. A conversation has to look clearly risky before Petasos " +
      "stops it.",
  },
  balanced: {
    label: "Balanced",
    plain:
      "Stops clear attacks, and steps in sooner when a conversation keeps looking risky.",
  },
  strict: {
    label: "Strict",
    plain:
      "Steps in earliest. Hides personal details before text moves on, and blocks " +
      "whenever a check cannot run.",
  },
};

function titleCase(word) {
  var text = String(word || "").replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

function jobLabel(name) {
  return (JOB_COPY[name] && JOB_COPY[name].label) || titleCase(name);
}

function levelLabel(name) {
  return (LEVEL_COPY[name] && LEVEL_COPY[name].label) || titleCase(name);
}

// A setting's label is its last path part in words: tools.dangerous_posture
// reads "Dangerous posture". The API's help sentence carries the meaning.
function fieldLabel(path) {
  var last = String(path).split(".").pop().replace(/([a-z])(\d)/gi, "$1 $2");
  return titleCase(last);
}

function sectionLabel(path) {
  if (!path) return "General";
  return String(path).split(".").map(titleCase).join(" · ");
}

function originLabel(origin, stored) {
  if (origin === "role") return "From the job: " + jobLabel(stored && stored.role);
  if (origin === "level") return "From strictness: " + levelLabel(stored && stored.level);
  if (origin === "override") return "Your change";
  if (origin === "default") return "Default";
  return "Unknown";
}

function showValue(value) {
  if (value === null || value === undefined) return "not set";
  if (value === true) return "on";
  if (value === false) return "off";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
  if (typeof value === "object") {
    var keys = Object.keys(value);
    if (!keys.length) return "none";
    return keys
      .map(function (key) {
        return key + " → " + showValue(value[key]);
      })
      .join(", ");
  }
  return String(value);
}

var SEVERITY_TONE = {
  critical: "destructive",
  high: "destructive",
  medium: "warning",
  low: "secondary",
  info: "secondary",
};

function severityWord(severity) {
  return severity ? titleCase(String(severity).toLowerCase()) : "";
}

// Hermes's timeAgo takes unix seconds (its type comment says milliseconds).
function whenText(seconds) {
  if (typeof seconds !== "number") return "";
  return SDK.utils.timeAgo(seconds);
}

function clockTime(seconds) {
  if (typeof seconds !== "number") return "";
  return new Date(seconds * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function exactTime(seconds) {
  if (typeof seconds !== "number") return "";
  return new Date(seconds * 1000).toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
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
              props.title ? h(C.CardTitle, { className: "text-sm" }, props.title) : null,
              props.description
                ? h("p", { className: "petasos-panel-desc" }, props.description)
                : null
            ),
            props.actions ? h("div", { className: "petasos-panel-actions" }, props.actions) : null
          )
        )
      : null,
    h(C.CardContent, { className: cn("petasos-panel-body", props.bodyClassName) }, props.children)
  );
}

// A status pill. The tone colours it; the words always say the same thing,
// so nothing is carried by colour alone.
function Pill(props) {
  return h(
    C.Badge,
    {
      tone: props.tone || "secondary",
      className: cn("petasos-pill", "petasos-tone-" + (props.tone || "secondary"), props.className),
      title: props.title,
    },
    props.children
  );
}

// A notice with a marked edge: used for paused, locked, restart, invalid.
function Notice(props) {
  return h(
    "div",
    {
      className: cn("petasos-notice", "petasos-notice-" + (props.tone || "info"), props.className),
      role: props.tone === "destructive" ? "alert" : "status",
    },
    h(
      "div",
      { className: "petasos-notice-text" },
      props.title ? h("p", { className: "petasos-notice-title" }, props.title) : null,
      props.children ? h("div", { className: "petasos-notice-body" }, props.children) : null
    ),
    props.action ? h("div", { className: "petasos-notice-action" }, props.action) : null
  );
}

// The dashed empty box kanban uses, with a sentence and an optional action.
function Empty(props) {
  return h(
    "div",
    { className: "petasos-empty" },
    h("p", { className: "petasos-empty-title" }, props.title),
    props.children ? h("div", { className: "petasos-empty-body" }, props.children) : null,
    props.action ? h("div", { className: "petasos-empty-action" }, props.action) : null
  );
}

function Btn(props) {
  var rest = Object.assign({}, props);
  delete rest.children;
  rest.type = rest.type || "button";
  rest.size = rest.size || "sm";
  return h(C.Button, rest, props.children);
}

// A text link that moves within the tab (or to a Hermes page by href).
function LinkButton(props) {
  return h(
    "button",
    {
      type: "button",
      className: cn("petasos-link", props.className),
      onClick: props.onClick,
      "aria-label": props.label,
    },
    props.children
  );
}

function Mono(props) {
  return h("code", { className: cn("petasos-mono", props.className), title: props.title }, props.children);
}

function Choice(props) {
  // A labelled native select drawn with Hermes's Select.
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
      },
      props.options.map(function (option) {
        return h(C.SelectOption, { key: option.value, value: option.value }, option.label);
      })
    )
  );
}

// A row of buttons where exactly one is chosen, like the Logs page filters.
function Segmented(props) {
  return h(
    "div",
    { className: "petasos-segmented", role: "radiogroup", "aria-label": props.label },
    props.label ? h("span", { className: "petasos-segmented-label", "aria-hidden": true }, props.label) : null,
    props.options.map(function (option) {
      var active = option.value === props.value;
      return h(
        "button",
        {
          key: option.value,
          type: "button",
          role: "radio",
          "aria-checked": active,
          className: cn("petasos-segment", active && "petasos-segment-on"),
          onClick: function () {
            props.onChange(option.value);
          },
        },
        option.label
      );
    })
  );
}

function KeyValues(props) {
  return h(
    "dl",
    { className: "petasos-kv" },
    props.rows
      .filter(function (row) {
        return row && row[1] !== undefined && row[1] !== null && row[1] !== "";
      })
      .map(function (row) {
        return h(
          Fragment,
          { key: row[0] },
          h("dt", null, row[0]),
          h("dd", null, row[1])
        );
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

function plural(count, one, many) {
  return count + " " + (count === 1 ? one : many || one + "s");
}
