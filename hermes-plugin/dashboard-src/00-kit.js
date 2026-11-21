// See docs/architecture/rationale.md, "Dashboard source packaging".

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

function ApiFailure(status, code, message, path) {
  this.status = status;
  this.code = code;
  this.message = message;
  this.path = path || null;
}

// Hosts report status/body properties or a status-prefixed response body.
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


var VIEWS = ["overview", "activity", "tryit", "settings"];

// Hermes profile navigation drops fragments; restore the initial fragment once.
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

// The API has no event stream; only visible tabs poll.
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

function originText(origin, stored, catalog) {
  if (origin === "role") return "From the job (" + roleLabel(catalog, stored && stored.role) + ")";
  if (origin === "level") return "From strictness (" + levelLabel(catalog, stored && stored.level) + ")";
  if (origin === "override") return "Your setting";
  if (origin === "default") return "Default";
  return "Unknown";
}

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


function whenText(seconds) {
  if (typeof seconds !== "number") return "";
  // Hermes timeAgo accepts Unix seconds despite its milliseconds type annotation.
  return SDK.utils.timeAgo(seconds);
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function clock24(date, seconds) {
  var options = { hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
  if (seconds) options.second = "2-digit";
  return date.toLocaleTimeString(undefined, options);
}

function listTime(seconds) {
  if (typeof seconds !== "number") return "";
  var date = new Date(seconds * 1000);
  var now = new Date();
  if (sameDay(date, now)) return "Today " + clock24(date);
  var options = { day: "numeric", month: "short" };
  if (date.getFullYear() !== now.getFullYear()) options.year = "numeric";
  return date.toLocaleDateString(undefined, options) + " " + clock24(date);
}

function fullTime(seconds) {
  if (typeof seconds !== "number") return "";
  var date = new Date(seconds * 1000);
  var zone = "";
  try {
    var parts = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" }).formatToParts(date);
    zone = (parts.filter(function (part) {
      return part.type === "timeZoneName";
    })[0] || {}).value || "";
  } catch (_e) {
    zone = "";
  }
  return (
    date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }) +
    " " +
    clock24(date, true) +
    (zone ? " " + zone : "")
  );
}

function clockTime(ms) {
  return clock24(new Date(ms), true);
}

function timeZoneName() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "your time zone";
  } catch (_e) {
    return "your time zone";
  }
}


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
                ? h(
                    "div",
                    { className: "petasos-panel-titlerow" },
                    h(C.CardTitle, { className: "text-sm petasos-panel-title", id: props.titleId }, props.title),
                    props.badge || null
                  )
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

var TONES = ["success", "warning", "destructive", "neutral"];
var BADGE_TONE = { success: "success", warning: "warning", destructive: "destructive", neutral: "secondary" };

function Status(props) {
  var tone = TONES.indexOf(props.tone) >= 0 ? props.tone : "neutral";
  return h(
    C.Badge,
    {
      tone: BADGE_TONE[tone],
      className: cn("petasos-status", "petasos-status-" + tone, props.large && "petasos-status-large", props.className),
      title: props.title,
      "data-petasos-state": props.state,
    },
    props.children
  );
}

function Tag(props) {
  return h(C.Badge, { tone: props.tone || "secondary", className: cn("petasos-tag", props.className), title: props.title }, props.children);
}

function Severity(props) {
  var severity = String(props.value || "").toLowerCase();
  var known = { critical: 1, high: 1, medium: 1, low: 1, info: 1 };
  var label = props.label || (known[severity] ? capital(severity) : "");
  if (!label) return null;
  return h(
    "span",
    { className: cn("petasos-sev", known[severity] && "petasos-sev-" + severity) },
    h("span", { className: "sr-only" }, "Severity: "),
    label
  );
}

function outcomeTone(code) {
  var destructive = ["blocked", "stopped", "declined", "not_stopped", "attempt_blocked", "block"];
  var warning = ["asked", "attempt_asked", "flagged", "allowed", "degraded", "unchecked", "approve", "flag", "none"];
  if (destructive.indexOf(code) >= 0) return "destructive";
  if (warning.indexOf(code) >= 0) return "warning";
  if (code === "approved" || code === "allow") return "success";
  return "neutral";
}

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
            tone === "success"
              ? h(Icon, { name: "check", size: 15, className: "petasos-notice-check" })
              : h("span", { className: "petasos-notice-dot", "aria-hidden": true }),
            props.title
          )
        : null,
      props.children ? h("div", { className: "petasos-notice-body" }, props.children) : null
    ),
    props.action ? h("div", { className: "petasos-notice-action" }, props.action) : null
  );
}

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

var ICONS = {
  clock: ["M12 6v6l4 2", "M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20"],
  chevron: ["M9 6l6 6l-6 6"],
  copy: ["M9 9h11v11H9z", "M5 15H4V4h11v1"],
  search: ["M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14", "M20 20l-4-4"],
  shield: ["M12 3l8 3v6c0 5-3.5 8-8 9c-4.5-1-8-4-8-9V6z"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  calendar: ["M4 6h16v14H4z", "M4 10h16", "M8 3v4", "M16 3v4"],
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
  delete rest.compact;
  rest.type = rest.type || "button";
  rest.size = rest.size || "sm";
  rest.className = cn(!props.ghost && "petasos-btn-caps", props.compact && "petasos-btn-compact", props.className);
  return h(C.Button, rest, props.children);
}

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

function readRemembered(key) {
  try {
    return window.localStorage.getItem("petasos." + key) === "open";
  } catch (_e) {
    return false;
  }
}

function writeRemembered(key, open) {
  try {
    if (open) window.localStorage.setItem("petasos." + key, "open");
    else window.localStorage.removeItem("petasos." + key);
  } catch (_e) {
    // Storage may be refused; disclosure state must still work for this visit.
  }
}

function Disclosure(props) {
  var openState = useState(function () {
    return props.remember ? readRemembered(props.remember) : Boolean(props.defaultOpen);
  });
  var open = openState[0];
  var id = props.id || "petasos-disclosure-" + String(props.remember || props.label).replace(/[^a-z0-9]+/gi, "-").toLowerCase();
  return h(
    "div",
    { className: cn("petasos-disclosure", open && "petasos-disclosure-open", props.className) },
    h(
      "button",
      {
        type: "button",
        className: "petasos-disclosure-toggle",
        "aria-expanded": open,
        "aria-controls": id,
        onClick: function () {
          var next = !open;
          openState[1](next);
          if (props.remember) writeRemembered(props.remember, next);
        },
      },
      h(Icon, { name: "chevron", size: 14, className: "petasos-disclosure-chevron" }),
      h("span", null, open && props.openLabel ? props.openLabel : props.label)
    ),
    open ? h("div", { className: "petasos-disclosure-body", id: id }, props.children) : null
  );
}

function Command(props) {
  return h(
    "div",
    { className: "petasos-command" },
    h("code", { className: "petasos-command-text" }, props.value),
    h(CopyButton, { value: props.value, label: props.label || "Copy the command" })
  );
}

function Mono(props) {
  return h("code", { className: cn("petasos-mono", props.className), title: props.title }, props.children);
}

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
      "aria-describedby": props.describedBy,
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

// Scrolling the inner container keeps the Hermes page frame stationary.
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
