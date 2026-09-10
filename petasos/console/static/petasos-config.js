/* Owns: configuration grouping/rendering, profile controls, and host binding. Depends on: core, transport, and Pet shell unmount callback. */
(function () {
  "use strict";
  var Pet = window.__PETASOS_CONSOLE__;
  var actual = Pet && Pet._moduleState ? Pet._moduleState.last : "missing";
  if (actual !== "playground") throw new Error("petasos-config expected module playground, got " + actual);

  // PET-114: pure builder — turns the flat field list + registry section metadata
  // into an ordered array of groups, each carrying a real boolean default_collapsed:
  //   [ { key, label, default_collapsed, fields: [field, …] }, … ]
  // Testable without the network (mirrors Pet.scannerHealthRows / mergeScanHistory).
  // Degrades gracefully (D6): a stale backend with no `sections` falls back to
  // field-appearance order, all expanded; a field whose section is absent from the
  // registry (forward-compat new field) lands in a trailing expanded group keyed by
  // its raw section — never silently dropped.
  Pet.groupConfigSections = function (fields, sections) {
    if (!Array.isArray(fields) || fields.length === 0) return [];

    // Group fields by section, preserving field order and first-appearance order.
    var bySection = {};
    var appearance = [];
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i];
      if (!f || typeof f !== "object") continue;
      var key = (f.section == null) ? "unknown" : f.section;
      if (!Object.prototype.hasOwnProperty.call(bySection, key)) {
        bySection[key] = [];
        appearance.push(key);
      }
      bySection[key].push(f);
    }

    var groups = [];
    var used = {};
    if (Array.isArray(sections) && sections.length > 0) {
      // Registry path: emit one group per registry entry in `order` (sort on the
      // explicit value rather than trusting array order across the wire); skip
      // registry entries with zero matching fields.
      var ordered = sections.slice().sort(function (a, b) {
        return ((a && a.order) || 0) - ((b && b.order) || 0);
      });
      ordered.forEach(function (s) {
        if (!s || s.key == null) return;
        var gk = s.key;
        if (!Object.prototype.hasOwnProperty.call(bySection, gk)) return;
        groups.push({
          key: gk,
          label: (s.label != null) ? s.label : gk,
          // PET-123: carry the registry copy the last hop (builder -> render) so
          // the section body can show a plain-language intro. Never-undefined (D4).
          description: (s.description != null) ? s.description : "",
          default_collapsed: Boolean(s.default_collapsed),
          fields: bySection[gk],
        });
        used[gk] = true;
      });
    }
    // Trailing groups: any section not emitted above (unknown registry, or stale
    // backend with no/empty sections), in field first-appearance order, expanded.
    appearance.forEach(function (gk) {
      if (used[gk]) return;
      // PET-123: a stale backend / unknown section has no registry copy; "" is the
      // never-undefined sentinel the intro builder degrades on (D4).
      groups.push({ key: gk, label: gk, description: "", default_collapsed: false, fields: bySection[gk] });
    });
    return groups;
  };

  // PET-114 §3f: for each errored field, expand its owning section panel so the
  // inline error is visible, and persist the expansion as a user-visible choice.
  // Pure w.r.t. the DOM handles passed in; returns the set of section keys
  // revealed. A field with no panel / unknown section is a safe no-op.
  Pet.revealFieldSections = function (errorFields, fieldSection, panelsBySection) {
    var revealed = {};
    (errorFields || []).forEach(function (name) {
      var sec = fieldSection[name];
      var panel = sec && panelsBySection[sec];
      if (panel && typeof panel.petSetCollapsed === "function") {
        panel.petSetCollapsed(false);             // imperative expand (no onToggle)
        Pet.state.sectionCollapsed[sec] = false;  // next re-render keeps it open
        revealed[sec] = true;
      }
    });
    return revealed;
  };

  // Humanize a config key for display: "tier3_threshold" -> "Tier 3 Threshold".
  Pet.CONFIG_ACRONYMS = { pii: "PII", iban: "IBAN", ssn: "SSN", ttl: "TTL", id: "ID", ip: "IP", rtl: "RTL", nfkc: "NFKC", hmac: "HMAC", url: "URL", ml: "ML", jwt: "JWT", api: "API", json: "JSON", llm: "LLM" };
  Pet.humanizeKey = function (key) {
    if (typeof key !== "string" || !key) return "";
    var s = key.replace(/^petasos\./, "").replace(/[._]+/g, " ").replace(/([a-zA-Z])([0-9])/g, "$1 $2").trim();
    return s.split(/\s+/).filter(Boolean).map(function (w) {
      var lw = w.toLowerCase();
      return Pet.CONFIG_ACRONYMS[lw] || (w.charAt(0).toUpperCase() + w.slice(1));
    }).join(" ");
  };

  // PET-123: intro node for a section body, or null when there is no copy to show
  // (stale backend / unknown section). Never throws on a missing / blank /
  // non-string description — degrades to null (PET-99 / D4 never-throw posture).
  Pet.sectionIntro = function (description) {
    if (typeof description !== "string") return null;
    var text = description.trim();
    if (!text) return null;
    return Pet.h("div", {
      style: { fontSize: "12px", color: "var(--tx-faint)", margin: "2px 0 10px",
               lineHeight: "1.45" }
    }, text);
  };

  // ── PET-124: strength-preset "tuning dial" ──
  // Pure JS mirror of petasos.console._presets.resolve_active_preset. Projects
  // `configValues` to each preset's override keys and returns the matching
  // preset key, or null (the derived "Custom" state) when none match. Used for
  // live (pre-apply) flips while editing. Value-normalizing equality: booleans
  // and the fail_mode string compare strictly; numeric owned fields compare as
  // Number(a) === Number(b), so a JSON-sourced `30` and a literal `30.0` are
  // equal and a freshly-applied preset never spuriously reads as Custom.
  Pet.resolveActivePreset = function (configValues, presets) {
    if (!configValues || typeof configValues !== "object") return null;
    if (!Array.isArray(presets) || presets.length === 0) return null;
    var valEq = function (a, b) {
      if (typeof a === "boolean" || typeof b === "boolean") return a === b;
      if (typeof a === "number" || typeof b === "number") return Number(a) === Number(b);
      return a === b;
    };
    for (var i = 0; i < presets.length; i++) {
      var p = presets[i];
      if (!p || typeof p !== "object" || !p.overrides || typeof p.overrides !== "object") continue;
      var keys = Object.keys(p.overrides);
      if (keys.length === 0) continue;
      var match = true;
      for (var j = 0; j < keys.length; j++) {
        var k = keys[j];
        if (!Object.prototype.hasOwnProperty.call(configValues, k) || !valEq(configValues[k], p.overrides[k])) {
          match = false;
          break;
        }
      }
      if (match) return p.key != null ? p.key : null;
    }
    return null;
  };

  // Renders the segmented strength dial: one button per preset (in `order`) plus
  // a trailing non-selectable Custom segment, the active one highlighted from
  // `activeKey` (Custom when null/absent/unknown). Each metal carries a HelpTip
  // from its description. Clicking a metal calls onSelect(preset). Never throws
  // (PET-99) / no innerHTML (PET-82): degrades on every malformed shape — a stale
  // backend missing `presets` (renders nothing), an empty list (nothing), a
  // preset entry lacking `overrides` (skipped).
  Pet.renderStrengthDial = function (presets, activeKey, onSelect) {
    var wrap = Pet.h("div", { className: "pet-dial-wrap" });
    if (!Array.isArray(presets) || presets.length === 0) return wrap;
    var ordered = presets
      .filter(function (p) {
        return p && typeof p === "object" && p.overrides && typeof p.overrides === "object";
      })
      .sort(function (a, b) { return ((a && a.order) || 0) - ((b && b.order) || 0); });
    if (ordered.length === 0) return wrap;

    var row = Pet.h("div", { className: "pet-dial-row" });
    row.appendChild(Pet.h("span", { className: "pet-dial-title eyebrow" }, "Strength"));
    var seg = Pet.h("div", { className: "seg pet-dial" });

    var activeIsKnown = false;
    ordered.forEach(function (p) {
      var isOn = p.key === activeKey;
      if (isOn) activeIsKnown = true;
      var btn = Pet.h("button", {
        className: "pet-dial-seg" + (isOn ? " on" : ""),
        type: "button",
        dataset: { preset: String(p.key) },
        onClick: function () { if (typeof onSelect === "function") onSelect(p); },
      }, p.label != null ? p.label : String(p.key));
      if (p.description) {
        // The HelpTip lives inside the clickable segment; swallow its click so
        // reading the tooltip never bubbles to onSelect and applies the preset.
        var tip = Pet.HelpTip(p.description);
        tip.addEventListener("click", function (e) { if (e && e.stopPropagation) e.stopPropagation(); });
        btn.appendChild(tip);
      }
      seg.appendChild(btn);
    });

    // Derived Custom segment — presentational, not clickable. Highlighted when no
    // built-in level matches the live config.
    var custom = Pet.h("span", {
      className: "pet-dial-seg pet-dial-custom" + (activeIsKnown ? "" : " on"),
      dataset: { preset: "custom" },
      title: "Custom: the live config does not match any built-in level.",
    }, "Custom");
    seg.appendChild(custom);

    row.appendChild(seg);
    wrap.appendChild(row);

    // D6: presentational recommendation pairing Iron (strength) with the
    // code_generation profile (scenario, selected separately). Changes no default.
    wrap.appendChild(Pet.h("div", { className: "pet-dial-rec" },
      "Recommended for coding agents: ",
      Pet.h("b", {}, "Iron"),
      " strength with the ",
      Pet.h("b", {}, "code_generation"),
      " profile."
    ));
    return wrap;
  };

  // ── Profile-picker pure builders (PET-122) ──
  // Two single-purpose, never-throw builders in the Pet.groupConfigSections /
  // Pet.scannerHealthRows idiom (no DOM, no network). profileNames is the option
  // source (every valid name); profileDescriptions is the tip source (names that
  // carry a usable description). Both first-wins dedup so they agree on a
  // duplicate-name payload.

  // Map a profile name -> its trimmed description. Tolerant of a missing/partial/
  // failed /api/profiles payload. Never throws (PET-99 never-throw posture).
  // Profiles with a blank/missing/non-string description are intentionally absent
  // (caller falls back to neutral tip copy). First occurrence of a name wins, so a
  // duplicate-name payload agrees with profileNames. Values are never undefined/empty.
  Pet.profileDescriptions = function (profiles) {
    var out = Object.create(null);
    if (!Array.isArray(profiles)) return out;
    for (var i = 0; i < profiles.length; i++) {
      var p = profiles[i];
      // Gate on p.name.trim() so a whitespace-only name (e.g. "   ") is rejected
      // rather than rendered as a blank button; the original p.name is kept as the
      // key/value so a padded-but-real name still matches the resolver exactly.
      if (p && typeof p.name === "string" && p.name.trim() &&
          !Object.prototype.hasOwnProperty.call(out, p.name) &&
          typeof p.description === "string" && p.description.trim()) {
        out[p.name] = p.description.trim();
      }
    }
    return out;
  };

  // Ordered list of valid profile names (ALL of them, regardless of description),
  // deduped first-wins, malformed entries skipped. Never throws. This is the option
  // source; profileDescriptions is the tip source.
  Pet.profileNames = function (profiles) {
    // Object.create(null): a profile literally named "__proto__" must not bypass the
    // first-wins dedup. With a plain {}, `seen["__proto__"] = true` hits the prototype
    // setter (a no-op for a non-object) so hasOwnProperty stays false and the dupe slips
    // through; a null-prototype map stores every string key as a plain own property.
    var out = [], seen = Object.create(null);
    if (!Array.isArray(profiles)) return out;
    for (var i = 0; i < profiles.length; i++) {
      var p = profiles[i];
      // Whitespace-only names are rejected (see profileDescriptions); the original
      // name is the option value so it round-trips to the resolver unchanged.
      if (p && typeof p.name === "string" && p.name.trim() &&
          !Object.prototype.hasOwnProperty.call(seen, p.name)) {
        seen[p.name] = true;
        out.push(p.name);
      }
    }
    return out;
  };

  // ── Profile-picker render seam (PET-122, D1/D3) ──
  // Bespoke, fetch-sourced control for the nullable `profile_name` field. Render-
  // then-enrich: paints a minimal seg ("(none)" + current value) synchronously,
  // then swaps in the full option set + per-option HelpTips when profilesP resolves.
  // Never blocks the form on /api/profiles and never throws. Exposed on Pet (like
  // groupConfigSections / revealFieldSections) so the render-seam unit tests can
  // drive it; the returned node carries a `_petRebuild(names, descMap)` handle for
  // the dirty-selection and collision-guard tests.
  //
  // NONE_LABEL doubles as the structural unset button's label AND the reserved
  // literal guarded against name collision (D6): a payload/stored value equal to
  // "(none)" is treated as unset, never rendered as a second truthy-string button.
  var PROFILE_NONE_LABEL = "(none)";
  var PROFILE_FALLBACK_TIP = "Custom profile: no description provided.";   // D5, sole authored string
  Pet.buildProfileControl = function (f, val, profilesP) {
    var seg = Pet.h("div", { className: "seg", role: "radiogroup", ariaLabel: Pet.humanizeKey(f.name) });
    var btns = [];   // explicit node array; selection clearing avoids querySelectorAll (F-1)

    // Recompute selection from configDirty on EVERY call (F-4): dirty wins (may be
    // null); else the config value captured once in this function's `val` param
    // (F-3); null => unset. A click before getProfiles resolves wrote configDirty,
    // so the enrich rebuild re-reads it and keeps the highlight.
    function currentSelection() {
      return Object.prototype.hasOwnProperty.call(Pet.state.configDirty, "profile_name")
        ? Pet.state.configDirty.profile_name
        : (typeof val === "string" && val ? val : null);
    }
    // null OR the literal "(none)" both resolve to the structural unset button.
    function isNoneSel(sel) { return sel == null || sel === PROFILE_NONE_LABEL; }

    function highlight() {
      var sel = currentSelection();
      var noneOn = isNoneSel(sel);
      for (var i = 0; i < btns.length; i++) {
        var b = btns[i];
        var on = b._petNone ? noneOn : (!noneOn && b._petVal === sel);
        b.className = on ? "on" : "";
        b.setAttribute("aria-checked", on ? "true" : "false");
      }
    }

    function addButton(label, value, tipText) {
      var btn = Pet.h("button", {
        className: "", type: "button", role: "radio", ariaChecked: "false",
        onClick: function () { Pet.state.configDirty.profile_name = value; highlight(); },
      }, label);
      btn._petVal = value;          // null for the structural "(none)" button
      btn._petNone = (value == null);
      seg.appendChild(btn);
      btns.push(btn);
      if (tipText) seg.appendChild(Pet.HelpTip(tipText));   // sibling .help node, focus-revealable (D4)
    }

    // Clear via shim-observable node removal, never innerHTML="" (F-1): the test
    // shim has no innerHTML setter, so an innerHTML write would leave childNodes
    // intact and the enrich rebuild would stack on the stale minimal seg.
    function clearSeg() {
      while (seg.childNodes.length) seg.removeChild(seg.childNodes[seg.childNodes.length - 1]);
      btns = [];
    }

    function rebuild(names, descMap) {
      clearSeg();
      var list = Array.isArray(names) ? names : [];
      var map = (descMap && typeof descMap === "object") ? descMap : {};
      // A non-empty profile list means we have enriched data and attach a HelpTip
      // per name/union button. An empty list is the minimal/degrade seg (initial
      // paint, or getProfiles rejected/empty): "(none)" + current value, selectable,
      // NO tips, no console error (D3). tipFor() encodes that split.
      var enriched = list.length > 0;
      function tipFor(name) {
        return enriched && Object.prototype.hasOwnProperty.call(map, name) ? map[name] : (enriched ? PROFILE_FALLBACK_TIP : null);
      }

      addButton(PROFILE_NONE_LABEL, null, null);   // structural unset, writes null, never a tip
      var sel = currentSelection();
      var present = {};
      for (var i = 0; i < list.length; i++) {
        var nm = list[i];
        if (nm === PROFILE_NONE_LABEL) continue;   // D6: never a second "(none)" button
        present[nm] = true;
        addButton(nm, nm, tipFor(nm));
      }
      // Union the current/dirty value if it is a real custom/unknown name not
      // already listed (and not the reserved "(none)" literal — F-2).
      if (typeof sel === "string" && sel && sel !== PROFILE_NONE_LABEL &&
          !Object.prototype.hasOwnProperty.call(present, sel)) {
        addButton(sel, sel, tipFor(sel));
      }
      highlight();
    }

    rebuild([], {});   // minimal initial seg: "(none)" + current value
    if (profilesP && typeof profilesP.then === "function") {
      profilesP.then(
        function (profiles) { rebuild(Pet.profileNames(profiles), Pet.profileDescriptions(profiles)); },
        function () { rebuild([], {}); }   // defensive: a non-normalized rejecting promise still degrades to the minimal seg
      );
    }
    seg._petRebuild = rebuild;   // test seam: drive the enrich rebuild synchronously
    return seg;
  };

  // PET-146: pure ordered option list for the Hermes-agent-profile selector,
  // derived from a /config payload's `hermes_profiles`. First-wins dedup by name;
  // blank / non-string names skipped; options keyed by `name` (not the display
  // label) so a profile dir literally named "root"/"HERMES_HOME" is harmless to
  // selection (edge F-10). Fail-soft to [] on any malformed payload; never throws.
  Pet.hermesProfileOptions = function (d) {
    var list = (d && Array.isArray(d.hermes_profiles)) ? d.hermes_profiles : [];
    var out = [];
    // Object.create(null) so a profile named "__proto__" can't bypass first-wins dedup
    // (a plain {} routes that key through the prototype setter, leaving hasOwnProperty
    // false on the repeat). Sibling of Pet.profileNames; same null-prototype rationale.
    var seen = Object.create(null);
    list.forEach(function (p) {
      if (!p || typeof p !== "object") return;
      var name = p.name;
      if (typeof name !== "string" || !name.trim()) return;
      if (Object.prototype.hasOwnProperty.call(seen, name)) return;
      seen[name] = true;
      out.push({
        name: name,
        path: typeof p.path === "string" ? p.path : "",
        is_active: p.is_active === true,
        tier: typeof p.tier === "string" ? p.tier : "profile",
      });
    });
    return out;
  };

  // PET-146 D5: pinned non-equipped restart-banner copy (no em dash, house style).
  // Exported so the JS test and the impl can't drift.
  Pet.HERMES_RESTART_BANNER =
    "This isn't the equipped profile; changes take effect when it's equipped (restart).";

  // PET-146: build the PUT /config payload for a save. Copies the source map (the
  // dirty-field subset, or a preset's overrides) and tags it with `profile` ONLY
  // when a non-equipped profile is in view, so update_config persists-only to that
  // profile (D4); the equipped view omits `profile` and hot-applies (D3,
  // byte-identical to pre-PET-146). Pure; never mutates the source.
  Pet.buildSavePatch = function (source, viewingActive, selectedProfile) {
    var patch = {};
    var src = (source && typeof source === "object") ? source : {};
    Object.keys(src).forEach(function (k) { patch[k] = src[k]; });
    if (!viewingActive && selectedProfile) patch.profile = selectedProfile;
    return patch;
  };

  // PET-146: the Hermes-agent-profile selector. Mounts a <select> over the payload's
  // profiles (defaulting to the equipped/active entry, or `opts.selected` when a
  // non-equipped profile is being viewed), the binding read-out, the dangling-pointer
  // warning strip (labeled as the ACTIVE binding so it is not misread as a property
  // of a browsed non-active profile, edge round-2 F-7), the "scoped to the selected
  // Hermes profile" note (no per-field "global" badge — D2), an effective
  // (what's-enforced) read-out, and the non-equipped restart banner (D5).
  //
  // `opts.selected` is the name of the non-equipped profile currently viewed (or
  // null/absent when viewing the equipped one). `opts.onSwitch(target)` is invoked
  // with the chosen target — null for the equipped entry, else the profile name —
  // AFTER the selector clears Pet.state.configDirty, so a subsequent save sends only
  // the freshly-loaded profile's values (edge round-2 F-4). A switch away from a
  // dirty form is gated behind a two-step confirm (the preset-apply idiom) so pending
  // edits are not silently discarded (edge round-3 F-1). Never throws.
  Pet.renderHermesProfileSelector = function (host, d, opts) {
    opts = opts || {};
    // PET-155: diegetic (host-bound) mode. When embedded in Hermes and a host
    // profile signal is present (opts.hostBinding.source !== "none"), surrender the
    // dial to the host switcher and render read-only (D1/D8). With no host binding the
    // editable in-house selector below is byte-equivalent to PET-146 (standalone).
    var hb = opts.hostBinding;
    if (hb && hb.source !== "none") return Pet.renderDiegeticProfile(host, d, hb);
    var onSwitch = typeof opts.onSwitch === "function" ? opts.onSwitch : function () {};
    var options = Pet.hermesProfileOptions(d);
    var isActiveView = !d || d.is_active !== false;

    var optionByName = function (nm) {
      for (var i = 0; i < options.length; i++) if (options[i].name === nm) return options[i];
      return null;
    };
    var activeName = null;
    options.forEach(function (o) { if (o.is_active) activeName = o.name; });
    // The currently-selected option name: the viewed non-equipped profile when
    // given, else the equipped entry.
    var currentName = (!isActiveView && opts.selected) ? opts.selected : activeName;

    // ── selector row ──
    var select = Pet.h("select", { className: "pet-hermes-select input mono", ariaLabel: "Hermes agent profile" });
    options.forEach(function (o) {
      var label = o.name + (o.is_active ? " (equipped)" : "");
      select.appendChild(Pet.h("option", { value: o.name }, label));
    });
    if (currentName != null) select.value = currentName;

    var pendingTarget;   // a target awaiting a confirming second change (dirty form)
    var removeStrip = function () {
      var n = host.querySelector ? host.querySelector(".pet-hermes-switch-confirm") : null;
      if (n && n.remove) n.remove();
    };
    var proceed = function (target) {
      pendingTarget = undefined;
      removeStrip();
      // Clear pending edits + any weaken-confirm intent so the previously-viewed
      // profile's edits neither leak into the next save (F-4) nor linger.
      Pet.state.configDirty = {};
      onSwitch(target);
    };
    select.addEventListener("change", function () {
      var name = select.value;
      if (name === currentName) { pendingTarget = undefined; removeStrip(); return; }   // no real change
      var opt = optionByName(name);
      var target = (opt && opt.is_active) ? null : name;      // equipped -> null
      var dirtyCount = Object.keys(Pet.state.configDirty || {}).length;
      if (dirtyCount > 0 && pendingTarget !== name) {
        // Gate the switch: stash the intent, revert the visible value, and show the
        // confirm strip. A second change to the same option confirms. (removeStrip
        // only drops the DOM node — it must NOT reset pendingTarget, or the confirm
        // could never latch.)
        pendingTarget = name;
        select.value = currentName != null ? currentName : "";
        removeStrip();   // drop any stale strip before re-adding (idempotent)
        host.appendChild(Pet.h("div", { role: "alert", className: "notice pet-hermes-switch-confirm", style: { marginTop: "8px" } },
          Pet.Icon("warn"),
          Pet.h("span", {}, "Switching profiles discards your " + dirtyCount + " unsaved edit" + (dirtyCount === 1 ? "" : "s") + ". Choose ", Pet.h("b", {}, name), " again to confirm.")
        ));
        return;
      }
      proceed(target);
    });

    var row = Pet.h("div", { className: "pet-hermes-row" },
      Pet.h("label", { className: "pet-hermes-label" }, "Hermes agent profile"),
      select
    );
    host.appendChild(row);

    // ── resolution read-out: HOW the path was resolved (PET-166 D16: relabelled from
    // "binding:" so it reads as a resolution-mechanism line and no longer competes
    // with the scope panel's identity claim on the HERMES_HOME-aliasing config) ──
    var tier = d && d.config_tier ? String(d.config_tier) : "root";
    var home = d && d.profile_home ? String(d.profile_home) : "";
    host.appendChild(Pet.h("div", { className: "pet-hermes-binding mono" },
      "resolved via: " + (d && d.hermes_profile ? String(d.hermes_profile) : "root") + " · tier " + tier + (home ? (" · " + home) : "")));

    // ── dangling-pointer warning, labeled as the ACTIVE binding (edge round-2 F-7) ──
    if (d && d.config_warning) {
      host.appendChild(Pet.h("div", { role: "alert", className: "notice pet-hermes-warn", style: { marginTop: "8px" } },
        Pet.Icon("warn"),
        Pet.h("span", {}, "Active binding: ", Pet.h("b", {}, d.hermes_profile ? String(d.hermes_profile) : "root"),
          " has a dangling pointer. " + String(d.config_warning))));
    }

    // ── selected-profile parse warning (its config.yaml holds invalid values) ──
    // Labeled as the SELECTED profile, distinct from the active-binding warning above.
    if (d && d.profile_warning) {
      host.appendChild(Pet.h("div", { role: "alert", className: "notice pet-hermes-profile-warn", style: { marginTop: "8px" } },
        Pet.Icon("warn"),
        Pet.h("span", {}, "Selected profile: " + String(d.profile_warning))));
    }

    // ── "scoped to the selected Hermes profile" note (replaces any global marker) ──
    host.appendChild(Pet.h("div", { className: "pet-hermes-note" },
      "Settings here are scoped to the selected Hermes profile. No machine-wide tier exists."));

    // ── non-equipped restart banner (D5, pinned copy) ──
    if (!isActiveView) {
      host.appendChild(Pet.h("div", { role: "status", className: "notice pet-hermes-banner", style: { marginTop: "8px" } },
        Pet.Icon("warn"), Pet.h("span", {}, Pet.HERMES_RESTART_BANNER)));
    }

    // ── effective (what's enforced) read-out ──
    host.appendChild(Pet.hermesEffectiveReadout(d));
    return host;
  };

  // PET-155: own-profile (host's own / dashboard) read-out placeholder + display cap
  // for the diegetic name (D7/§F). The host name is untrusted data: trimmed, capped,
  // and rendered through a text node (escaped), never innerHTML.
  Pet.HOST_OWN_PROFILE_LABEL = "default (dashboard profile)";
  Pet.HOST_NAME_DISPLAY_CAP = 64;

  // PET-155: diegetic render mode for the Hermes-agent-profile selector. Read-only:
  // shows the host-bound profile name, the binding-tier read-out, the read-only
  // safety warnings, the "follows the sidebar" note, the equipped-vs-management
  // banner (D5: shown iff profile/current are both known and differ), and the
  // effective read-out. No editable <select>, no change listener (D8). The host name
  // is escaped via a text node (D7). Never throws.
  Pet.renderDiegeticProfile = function (host, d, hb) {
    hb = hb || {};
    var canon = function (x) { return String(x == null ? "" : x).trim(); };
    var profile = canon(hb.profile);   // management/write target; "" = host's own
    var current = canon(hb.current);   // equipped profile (process); "" = unknown
    // own-profile placeholder when empty-after-trim; length-cap an over-long name so a
    // multi-KB host string cannot blow out the layout (§F).
    var display = profile === "" ? Pet.HOST_OWN_PROFILE_LABEL : profile;
    if (display.length > Pet.HOST_NAME_DISPLAY_CAP) {
      display = display.slice(0, Pet.HOST_NAME_DISPLAY_CAP) + "…";
    }

    // ── read-only profile row (name as an escaped text node, D7) ──
    host.appendChild(Pet.h("div", { className: "pet-hermes-row pet-hermes-diegetic" },
      Pet.h("label", { className: "pet-hermes-label" }, "Hermes agent profile"),
      Pet.h("span", { className: "pet-hermes-bound mono" }, display)));

    // ── resolution read-out (reused from PET-146; PET-166 D16 relabel, see the
    // twin site in renderHermesProfileSelector) ──
    var tier = d && d.config_tier ? String(d.config_tier) : "root";
    var home = d && d.profile_home ? String(d.profile_home) : "";
    host.appendChild(Pet.h("div", { className: "pet-hermes-binding mono" },
      "resolved via: " + (d && d.hermes_profile ? String(d.hermes_profile) : "root") + " · tier " + tier + (home ? (" · " + home) : "")));

    // ── read-only safety warnings (dangling active-binding pointer / selected-profile parse) ──
    if (d && d.config_warning) {
      host.appendChild(Pet.h("div", { role: "alert", className: "notice pet-hermes-warn", style: { marginTop: "8px" } },
        Pet.Icon("warn"),
        Pet.h("span", {}, "Active binding: ", Pet.h("b", {}, d.hermes_profile ? String(d.hermes_profile) : "root"),
          " has a dangling pointer. " + String(d.config_warning))));
    }
    if (d && d.profile_warning) {
      host.appendChild(Pet.h("div", { role: "alert", className: "notice pet-hermes-profile-warn", style: { marginTop: "8px" } },
        Pet.Icon("warn"),
        Pet.h("span", {}, "Selected profile: " + String(d.profile_warning))));
    }

    // ── diegetic note: the dial follows the host sidebar (no per-tab dial) ──
    host.appendChild(Pet.h("div", { className: "pet-hermes-note pet-hermes-diegetic-note" },
      "This profile follows the Hermes sidebar selection. Switch profiles from the sidebar."));

    // ── equipped-vs-management banner (D5): only when both known and they differ ──
    if (profile !== "" && current !== "" && profile !== current) {
      host.appendChild(Pet.h("div", { role: "status", className: "notice pet-hermes-banner", style: { marginTop: "8px" } },
        Pet.Icon("warn"), Pet.h("span", {}, Pet.HERMES_RESTART_BANNER)));
    } else if (current === "") {
      // current unknown -> banner suppressed (fail-safe); a muted note keeps some
      // equipped-state signal rather than a silent gap (round-2 edge/F-4).
      host.appendChild(Pet.h("div", { className: "pet-hermes-note pet-hermes-effective-faint", style: { marginTop: "8px" } },
        "Equipped-profile status unavailable."));
    }

    // ── effective (what's enforced) read-out ──
    host.appendChild(Pet.hermesEffectiveReadout(d));
    return host;
  };

  // PET-155: host-profile capability layer. A self-contained resolver that decides
  // whether the console is embedded (a Hermes SDK with fetchJSON is present) and, if
  // so, binds the Config Editor to the HOST-selected profile instead of an
  // independent dial. Resolution order (D1/D2): SDK `profileScope` (reactive,
  // companion D3) -> `?profile=` query + `/api/profiles/active` fallback (works
  // against today's host) -> standalone ("none", editable dial). Canonicalization
  // invariant: `profile`/`current` are always strings; absent/null/unknown all
  // normalize to "" (own/unknown). Never throws.
  var _NAV_UNSET = {};   // sentinel: "no original history fn captured" (teardown guard)

  Pet.hostProfile = {
    source: "none",      // "sdk" | "query" | "none"
    profile: "",         // canonical management/write target ("" = host's own)
    current: "",         // canonical equipped profile ("" = unknown)
    profiles: [],        // coerced array (companion-supplied; [] on the fallback)
    _teardown: null,     // subscribe() teardown, invoked + nulled by Pet.unmount
    _unsub: null,        // profileScope unsubscribe (SDK path), or null
    _navPatch: null,     // fallback history-patch state object, or null
    _gen: 0,             // bind generation; supersedes a stale /api/profiles/active resolve

    _canon: function (x) { return String(x == null ? "" : x).trim(); },

    // The embedded SDK iff it can actually fetch (the existing standalone/embedded
    // predicate, petasos.js:521-522/618-619). A partial SDK without fetchJSON is
    // treated as standalone.
    _sdk: function () {
      var sdk = window.__HERMES_PLUGIN_SDK__;
      // Require fetchJSON to be CALLABLE (not merely truthy): a half-built companion
      // with a non-function fetchJSON must fall through to standalone rather than route
      // here and throw on the first sdk.fetchJSON(...) call. Mirrors _scope()'s subscribe check.
      return (sdk && typeof sdk.fetchJSON === "function") ? sdk : null;
    },

    // A *usable* profileScope: an object whose subscribe is callable. A truthy-but-
    // half-built companion (missing/non-function subscribe) is rejected here and falls
    // through to the fallback (defends D3 against a malformed companion, not just absence).
    _scope: function () {
      var sdk = this._sdk();
      if (!sdk) return null;
      var ps = sdk.profileScope;
      if (typeof ps === "object" && ps && typeof ps.subscribe === "function") return ps;
      return null;
    },

    // Parse ?profile= from the live location.search; canonicalized to "" when absent/blank.
    _readQueryProfile: function () {
      try {
        var search = (window.location && window.location.search) || "";
        var m = /[?&]profile=([^&]*)/.exec(search);
        if (!m) return "";
        return this._canon(decodeURIComponent(m[1].replace(/\+/g, " ")));
      } catch (_) { return ""; }
    },

    snapshot: function () {
      return { source: this.source, profile: this.profile, current: this.current, profiles: this.profiles };
    },

    // Synchronous detect + read of profile/profiles (+ current for the SDK path).
    // Fallback `current` is asynchronous (see refreshCurrent), so it is not read here.
    resolve: function () {
      var sdk = this._sdk();
      if (!sdk) {
        this.source = "none"; this.profile = ""; this.current = ""; this.profiles = [];
        return this.snapshot();
      }
      var scope = this._scope();
      if (scope) {
        this.source = "sdk";
        this.profile = this._canon(scope.profile);
        this.current = this._canon(scope.currentProfile);
        this.profiles = Array.isArray(scope.profiles) ? scope.profiles.slice() : [];
        return this.snapshot();
      }
      this.source = "query";
      this.profile = this._readQueryProfile();
      this.current = "";          // unknown until refreshCurrent resolves (fail-safe)
      this.profiles = [];
      return this.snapshot();
    },

    // Fallback only: read the equipped profile from the HOST endpoint
    // GET /api/profiles/active via the raw SDK fetch (NOT Pet.api, whose embedded
    // baseUrl is /api/plugins/petasos). Success shape only (!error && !_status);
    // 404 / network / malformed / missing field leave current "" (unknown). The
    // generation guard drops a resolve superseded by a newer bind.
    refreshCurrent: function () {
      var self = this;
      var sdk = self._sdk();
      if (!sdk) return Promise.resolve("");
      var gen = self._gen;
      return Promise.resolve()
        .then(function () { return sdk.fetchJSON("/api/profiles/active"); })
        .then(function (resp) {
          if (gen !== self._gen) return self.current;   // superseded
          if (resp && typeof resp === "object" && !resp.error && !resp._status) {
            self.current = self._canon(resp.current);
          }
          return self.current;
        }, function () { return self.current; });
    },

    // Observe host selection changes. SDK: profileScope.subscribe (reactive). Fallback:
    // a history.pushState/replaceState patch (+ popstate) — replaceState fires no
    // popstate, so a popstate-only listener would miss every sidebar flip (D4). Returns
    // a teardown function.
    subscribe: function (onChange) {
      var self = this;
      var cb = typeof onChange === "function" ? onChange : function () {};
      if (self.source === "sdk") {
        var scope = self._scope();
        self._unsub = null;
        if (scope) {
          try {
            var u = scope.subscribe(function () { cb(); });
            if (typeof u === "function") self._unsub = u;
          } catch (_) {}
        }
        return function () {
          if (typeof self._unsub === "function") { try { self._unsub(); } catch (_) {} }
          self._unsub = null;
        };
      }
      if (self.source === "query") return self._installNavPatch(cb);
      return function () {};   // source none — nothing to observe
    },

    // Install the history patch once (re-armable). Wrappers call the original FIRST,
    // capture its return, then fire cb inside try/catch and return the captured result
    // (a throwing/slow rebind can never make the host's pushState throw or change its
    // return, test #16). Foreign-patcher-safe and idempotent across remounts (D4/§E).
    _installNavPatch: function (cb) {
      var self = this;
      var hist = window.history;
      var patch = self._navPatch;
      if (patch && patch.installed) { patch.cb = cb; return patch.teardown; }   // re-arm, don't re-wrap
      patch = self._navPatch = {
        installed: true, cb: cb, popHandler: null,
        ourPush: null, ourReplace: null, origPush: _NAV_UNSET, origReplace: _NAV_UNSET, teardown: null,
      };
      var fire = function () {
        try { patch.cb(); } catch (e) {
          try { if (window.console && console.warn) console.warn("petasos: host-profile rebind failed", e); } catch (_) {}
        }
      };
      if (hist && typeof hist.pushState === "function" && typeof hist.replaceState === "function") {
        patch.origPush = hist.pushState;
        patch.origReplace = hist.replaceState;
        patch.ourPush = function () { var r = patch.origPush.apply(hist, arguments); fire(); return r; };
        patch.ourReplace = function () { var r = patch.origReplace.apply(hist, arguments); fire(); return r; };
        hist.pushState = patch.ourPush;
        hist.replaceState = patch.ourReplace;
      }
      patch.popHandler = function () { fire(); };
      try { window.addEventListener("popstate", patch.popHandler); } catch (_) {}
      patch.teardown = function () {
        // order: remove popstate -> un-patch history. Each step isolated.
        try { if (patch.popHandler) window.removeEventListener("popstate", patch.popHandler); } catch (_) {}
        patch.popHandler = null;
        // restore only if (a) an original was captured and (b) OUR wrapper is still the
        // top one (never clobber a foreign patcher / the host's wrapper).
        try { if (patch.origPush !== _NAV_UNSET && hist && hist.pushState === patch.ourPush) hist.pushState = patch.origPush; } catch (_) {}
        try { if (patch.origReplace !== _NAV_UNSET && hist && hist.replaceState === patch.ourReplace) hist.replaceState = patch.origReplace; } catch (_) {}
        patch.cb = function () {};   // if a foreign wrapper sits on top, our link becomes inert
        patch.installed = false;
        self._navPatch = null;
      };
      return patch.teardown;
    },

    // Re-bind to the current host selection and re-render the cfg tab if visible.
    // No-op guard: skip when the canonical bound profile is unchanged (SDK also re-binds
    // on a current-only change — it is exact; the fallback is profile-keyed, round-2
    // edge/F-5). Re-render is guarded on tab==="cfg" && Pet._runtime.container so a flip while on
    // another tab (or after unmount nulled Pet._runtime.container) only updates state.
    _rebind: function () {
      var self = this;
      if (self.source === "sdk") {
        var scope = self._scope();
        if (!scope) return;
        var np = self._canon(scope.profile);
        var nc = self._canon(scope.currentProfile);
        var bound = self._canon(Pet.state.selectedHermesProfile);
        if (np === bound && nc === self.current) return;   // true no-op
        // PET-146 F-4 isolation on the host-driven path: when the bound MANAGEMENT
        // profile actually changes, drop the prior profile's unsaved edits so they
        // cannot leak into the next Apply against the new target (the standalone
        // selector clears configDirty on switch; this rebind is host-driven and is
        // never mediated by that selector). A currentProfile-only update keeps the
        // selection (np === bound), so the operator's in-progress edits are preserved.
        if (np !== bound) Pet.state.configDirty = {};
        self.profile = np; self.current = nc;
        self.profiles = Array.isArray(scope.profiles) ? scope.profiles.slice() : self.profiles;
        Pet.state.selectedHermesProfile = np;
        self._gen++;
        // PET-166 (D17): a change on EITHER axis (management selection or equipped
        // flip) invalidates every scoped read surface and re-subscribes SSE.
        Pet._scope.invalidate();
        if (Pet.state.tab === "cfg" && Pet._runtime.container) Pet.renderConfig(Pet._runtime.container);
        return;
      }
      if (self.source !== "query") return;
      var newProfile = self._readQueryProfile();
      if (newProfile === self._canon(Pet.state.selectedHermesProfile)) return;   // profile-keyed no-op
      // PET-146 F-4 isolation (see SDK path): past the no-op guard the management
      // profile has changed, so drop the prior profile's unsaved edits.
      Pet.state.configDirty = {};
      self.profile = newProfile;
      Pet.state.selectedHermesProfile = newProfile;
      self._gen++;
      Pet._scope.invalidate(); // PET-166 (D17)
      // refresh equipped/current for the new selection, then settle the banner.
      self.refreshCurrent().then(function () {
        if (Pet.state.tab === "cfg" && Pet._runtime.container) Pet.renderConfig(Pet._runtime.container);
      });
      if (Pet.state.tab === "cfg" && Pet._runtime.container) Pet.renderConfig(Pet._runtime.container);
    },

    // Wire into the mount lifecycle (§E): resolve once, pin the initial host profile,
    // install the observer, store teardown. Idempotent — detach() first clears a stale
    // patch left by a remount that skipped unmount.
    attach: function () {
      var self = this;
      self.detach();
      var desc = self.resolve();
      if (desc.source !== "none") Pet.state.selectedHermesProfile = desc.profile;
      if (desc.source === "query") {
        self.refreshCurrent().then(function () {
          if (Pet.state.tab === "cfg" && Pet._runtime.container) Pet.renderConfig(Pet._runtime.container);
        });
      }
      self._teardown = self.subscribe(function () { self._rebind(); });
    },

    // Invoked by Pet.unmount: run the stored teardown (un-patch history / unsubscribe)
    // and null it. Guarded so the bridge's cancelled-before-mount path is a no-op.
    detach: function () {
      if (typeof this._teardown === "function") { try { this._teardown(); } catch (_) {} }
      this._teardown = null;
      // PET-155: invalidate any refreshCurrent in flight. Its generation guard drops a
      // resolve when _gen has moved on; bumping here (attach() calls detach() first, so
      // this covers remount too) stops a slow /api/profiles/active reply from a torn-down
      // lifecycle mutating `current` or triggering a render after detach/remount.
      this._gen++;
    },
  };

  // PET-155: monotonic Config-render generation. A getConfig resolve whose render has
  // been superseded by a newer renderConfig (e.g. a rapid host re-bind X->Y->X) is
  // dropped, so an out-of-order in-flight fetch cannot paint a stale profile under a
  // newer binding (last-write-wins; mirrors the SSE _gen guard at petasos.js:609/633).

  // PET-146: compact, read-only "effective (what's enforced)" block — the resolved
  // tier thresholds (config ⊕ the internal profile's tier_thresholds) plus the
  // internal profile's added suppressions / severity / pii / confidence floor, so
  // the operator sees what the active internal profile adds without it masquerading
  // as a config field. Pure builder; never throws.
  Pet.hermesEffectiveReadout = function (d) {
    var eff = (d && d.effective_config && typeof d.effective_config === "object") ? d.effective_config : {};
    var ov = (d && d.active_profile_overrides && typeof d.active_profile_overrides === "object") ? d.active_profile_overrides : null;
    // Collapsed by default (house style): the resolved tier thresholds are honest
    // but crowd the simplified Strength view, so they live behind a disclosure and
    // stay one click away rather than always-on.
    var box = Pet.h("details", { className: "pet-hermes-effective" });
    box.appendChild(Pet.h("summary", { className: "pet-hermes-effective-head" }, "effective (what's enforced)"));
    var t1 = eff.tier1_threshold, t2 = eff.tier2_threshold, t3 = eff.tier3_threshold;
    box.appendChild(Pet.h("div", { className: "mono pet-hermes-effective-row" },
      "tier thresholds: " + (t1 != null ? t1 : "?") + " / " + (t2 != null ? t2 : "?") + " / " + (t3 != null ? t3 : "?")));
    if (ov) {
      box.appendChild(Pet.h("div", { className: "mono pet-hermes-effective-row" },
        "internal profile: " + (ov.name != null ? String(ov.name) : "(unnamed)")));
      if (ov.confidence_floor != null) {
        box.appendChild(Pet.h("div", { className: "mono pet-hermes-effective-row" }, "confidence floor: " + ov.confidence_floor));
      }
      var sr = Array.isArray(ov.suppress_rules) ? ov.suppress_rules : [];
      if (sr.length) box.appendChild(Pet.h("div", { className: "mono pet-hermes-effective-row" }, "suppressed rules: " + sr.join(", ")));
      var so = (ov.severity_overrides && typeof ov.severity_overrides === "object") ? Object.keys(ov.severity_overrides) : [];
      if (so.length) box.appendChild(Pet.h("div", { className: "mono pet-hermes-effective-row" }, "severity overrides: " + so.length));
      var pe = Array.isArray(ov.pii_entities_extra) ? ov.pii_entities_extra : [];
      if (pe.length) box.appendChild(Pet.h("div", { className: "mono pet-hermes-effective-row" }, "extra PII entities: " + pe.join(", ")));
    } else {
      box.appendChild(Pet.h("div", { className: "mono pet-hermes-effective-row pet-hermes-effective-faint" }, "no internal profile active"));
    }
    return box;
  };

  Pet.renderConfig = function (container) {
    var _renderGen = (Pet._runtime.configRenderGen += 1);   // PET-155: this render's generation
    container.innerHTML = "";
    // PET-129: in the authenticate state render the token panel instead of issuing
    // config reads that would only 401 (the obs dashboard does the same). The auth
    // flow takes precedence when the config tab is opened while authRequired, so no
    // redundant getProfiles/getConfig calls and no skeleton flash before on401 swaps in.
    if (Pet.state.authRequired) {
      container.appendChild(Pet.renderAuthPanel());
      return;
    }
    var wrapper = Pet.h("div", { style: { display: "flex", flexDirection: "column", gap: "16px", height: "100%" } });

    // PET-13: the "how saving works" disclosure moved to the sticky save bar at the
    // bottom (subtle faint text, always visible) and replaces the top warning
    // banner. With every section collapsed by default, the save bar is the page's
    // visible anchor, so the disclosure belongs there, not up top.
    // PET-127: skeleton field-rows while /config resolves. role=status carries the
    // loading semantic for AT; the resolve arm (formArea.innerHTML = "") and error
    // arm both wipe this wrapper before appending real content, so no arm change.
    var formArea = Pet.h("div", { style: { flex: "1", overflowY: "auto" } },
      Pet.h("div", { role: "status", ariaBusy: true, ariaLabel: "Loading configuration", style: { padding: "20px" } },
        Pet.skelRows(5, { h: "20px" }))
    );
    wrapper.appendChild(formArea);
    container.appendChild(wrapper);

    // PET-122: kick off the profiles fetch concurrently with getConfig so it is
    // already in flight when the form paints. Normalize to a never-throwing promise
    // of a raw profile array: a rejected or malformed getProfiles resolves to [].
    // (_get/_req return a fetch-based promise that resolves to {error} on failure
    // rather than rejecting, so the onRejected arm is belt-and-suspenders.)
    var profilesP = Pet.api.getProfiles().then(
      function (resp) {
        if (Pet.auth.on401(resp)) return []; // PET-129: a profiles 401 enters the auth state (chokepoint completeness)
        return (resp && Array.isArray(resp.profiles)) ? resp.profiles : [];
      },
      function () { return []; }
    );

    Pet.api.getConfig(Pet.state.selectedHermesProfile).then(function (d) {
      if (_renderGen !== Pet._runtime.configRenderGen) return; // PET-155: a newer renderConfig superseded this fetch (out-of-order re-bind); drop it
      if (Pet.auth.on401(d)) return; // PET-129 D3: a 401 on the config read enters the authenticate state, not "Config unavailable"
      // PET-146 (CodeRabbit PR #135): a selected profile that no longer resolves
      // (deleted out-of-band) is rejected by the backend with a 422 naming the
      // `profile` field. Reset to the equipped view and reload, rather than bricking
      // the editor on a stale selection (getConfig(null) won't 422, so no loop).
      if (d && d._status === 422 && Array.isArray(d.detail) &&
          d.detail.some(function (e) { return e && e.field === "profile"; }) &&
          Pet.state.selectedHermesProfile) {
        // PET-155 (D7/§C): in diegetic mode the host pin must NOT revert to own — that
        // would silently re-introduce the two-dial drift this ticket fixes. Surface the
        // readable {detail[0]} error and keep selectedHermesProfile; the §D no-op guard
        // stops the next render from re-fetching the same rejected profile (no loop).
        if (Pet.hostProfile.source !== "none") {
          // The guard above only requires SOME profile detail; pick that entry for the
          // message (not detail[0]) so a non-first profile error shows the right reason.
          var first = d.detail.filter(function (e) { return e && e.field === "profile"; })[0] || d.detail[0];
          var emsg = (first && typeof first === "object")
            ? (first.field || "profile") + ": " + (first.message || first.msg || "unresolved profile")
            : "unresolved profile";
          formArea.innerHTML = "";
          formArea.appendChild(Pet.h("div", { role: "alert", style: { padding: "20px", color: "var(--err)", fontSize: "12px", fontFamily: "var(--font-mono)" } },
            "Host profile not resolved: " + emsg + ". Select a valid profile from the Hermes sidebar."));
          return;
        }
        Pet.state.selectedHermesProfile = null;
        Pet.state.configDirty = {};
        Pet.renderConfig(container);
        return;
      }
      if (d.error || !d.config || !d.fields) {
        formArea.innerHTML = "";
        formArea.appendChild(Pet.h("div", { style: { padding: "20px", color: "var(--err)", fontSize: "12px", fontFamily: "var(--font-mono)" } },
          d.error ? "Config unavailable: " + d.error : "Unexpected response from API"));
        return;
      }
      Pet.state.config = d.config;
      Pet.state.configFields = d.fields;
      Pet.state.configPresets = d.presets;
      Pet.state.configActivePreset = d.active_preset;
      formArea.innerHTML = "";

      // PET-124: strength dial at the top of the editor. The owned-field set is
      // derived from the presets payload so the live (pre-apply) recompute and the
      // apply wiring stay in lockstep with the backend registry. If `presets` is
      // absent (stale backend), OWNED is empty and the dial renders nothing.
      var OWNED = {};
      (Array.isArray(d.presets) ? d.presets : []).forEach(function (p) {
        if (p && p.overrides && typeof p.overrides === "object") {
          Object.keys(p.overrides).forEach(function (k) { OWNED[k] = true; });
        }
      });
      var dialHost = Pet.h("div", { className: "pet-dial-host" });
      formArea.appendChild(dialHost);

      // PET-146: the Hermes-agent-profile selector sits at the very TOP of the
      // editor (above the Strength dial). dialHost is already appended, so
      // insertBefore positions the selector host visually above it. `viewingActive`
      // gates the save routing: a non-equipped view tags the PUT with the selected
      // profile so update_config persists-only (D4) instead of hot-applying.
      var viewingActive = d.is_active !== false;
      var hermesHost = Pet.h("div", { className: "pet-hermes-profile-host" });
      formArea.insertBefore(hermesHost, dialHost);
      Pet.renderHermesProfileSelector(hermesHost, d, {
        selected: Pet.state.selectedHermesProfile,
        hostBinding: Pet.hostProfile.snapshot(),   // PET-155: diegetic when source !== "none"
        onSwitch: function (target) {
          // target: null for the equipped entry, else the chosen profile name.
          // configDirty was already cleared by the selector before this fires.
          Pet.state.selectedHermesProfile = target;
          Pet.renderConfig(container);
        },
      });

      var dialApplyInFlight = false;
      var currentConfigValues = function () {
        // Persisted config overlaid with in-memory edits, restricted to owned fields.
        var vals = {};
        Object.keys(OWNED).forEach(function (k) {
          if (d.config && Object.prototype.hasOwnProperty.call(d.config, k)) vals[k] = d.config[k];
        });
        Object.keys(Pet.state.configDirty).forEach(function (k) { vals[k] = Pet.state.configDirty[k]; });
        return vals;
      };
      // PET-13: render-scoped so renderDial can surface the confirm hint.
      var _presetConfirmKey = null;
      var _presetConfirmTimer = null;
      var clearPresetConfirm = function () {
        _presetConfirmKey = null;
        if (_presetConfirmTimer) { clearTimeout(_presetConfirmTimer); _presetConfirmTimer = null; }
      };
      var onSelectPreset = function (preset) {
        if (!preset || !preset.overrides || dialApplyInFlight) return;
        // PET-13: a preset apply re-renders from server truth, discarding unsaved
        // edits. With pending edits, require a confirming second click on the same
        // level before throwing them away. No dirty edits -> applies on one click.
        var dirtyCount = Object.keys(Pet.state.configDirty).length;
        if (dirtyCount > 0 && _presetConfirmKey !== preset.key) {
          _presetConfirmKey = preset.key;
          renderDial();
          _presetConfirmTimer = setTimeout(function () { clearPresetConfirm(); renderDial(); }, 4000);
          return;
        }
        clearPresetConfirm();
        dialApplyInFlight = true;  // in-flight guard, mirrors the Apply button
        // PET-146: tag the PUT with the selected profile when a non-equipped profile
        // is being viewed, so a preset apply persists to THAT profile (D4) rather
        // than hot-applying to the equipped pipeline behind the operator's back.
        var presetPatch = Pet.buildSavePatch(preset.overrides, viewingActive, Pet.state.selectedHermesProfile);
        Pet.api.putConfig(presetPatch).then(function (resp) {
          if (_renderGen !== Pet._runtime.configRenderGen) return; // PET-155: a host rebind/unmount superseded this render — drop the stale preset save so it can't clear the new profile's dirty edits or clobber its config
          if (Pet.auth.on401(resp)) return; // PET-129: a config-save 401 enters the auth state, not a validation error
          var failMsg = null;
          if (resp && resp._status && resp.detail) {
            var raw = Array.isArray(resp.detail) ? resp.detail : [resp.detail];
            failMsg = raw.map(function (e) {
              if (!e || typeof e !== "object") return String(e);
              return (e.field || "?") + ": " + (e.message || e.msg || e.detail || String(e));
            }).join("; ");
          } else if (resp && resp.error) {
            failMsg = String(resp.error);
          }
          if (failMsg !== null) {
            // PET-13: inline error in the dial host, consistent with the Apply
            // path's .pet-field-err strip (replaces the native alert()).
            renderDial();
            dialHost.appendChild(Pet.h("div", {
              role: "alert",
              className: "pet-field-err",
              style: { color: "var(--err)", fontSize: "12px", padding: "8px 12px", background: "var(--bg-raised)", borderRadius: "var(--r-card)", marginTop: "8px" }
            }, "Preset apply failed: " + failMsg));
            return;
          }
          // Re-render from persisted truth: the merge base is the server-side
          // config, so a preset apply intentionally discards unsaved non-owned
          // edits and resets the dirty map, consistent with the Apply path.
          Pet.state.config = resp.config || Pet.state.config;
          Pet.state.configDirty = {};
          Pet.renderConfig(container);
        }).then(function () { dialApplyInFlight = false; }, function () { dialApplyInFlight = false; });
      };
      var renderDial = function () {
        dialHost.innerHTML = "";
        var activeKey = Pet.resolveActivePreset(currentConfigValues(), d.presets);
        var dial = Pet.renderStrengthDial(d.presets, activeKey, onSelectPreset);
        dialHost.appendChild(dial);
        // PET-13: frame the dial as a shortcut, not the headline. Only when the
        // dial actually rendered (presets present) — keep a stale backend clean.
        if (dial && dial.firstChild) {
          dialHost.appendChild(Pet.h("div", { className: "pet-dial-rec", style: { marginTop: "2px" } },
            "Quick preset: sets the strength fields below. Or expand a section to tune individual fields."));
        }
        // PET-13: confirm strip when applying a preset would discard unsaved edits.
        if (_presetConfirmKey) {
          var n = Object.keys(Pet.state.configDirty).length;
          dialHost.appendChild(Pet.h("div", { className: "notice", style: { marginTop: "8px" } },
            Pet.Icon("warn"),
            Pet.h("span", {}, "Applying ", Pet.h("b", {}, String(_presetConfirmKey)),
              " discards your " + n + " unsaved edit" + (n === 1 ? "" : "s") + ". Click that level again to confirm.")
          ));
        }
      };
      // Recompute the highlight only when an owned field changes; a non-owned edit
      // never flips the dial.
      var maybeUpdateDial = function (name) { if (OWNED[name]) renderDial(); };
      renderDial();

      var groups = Pet.groupConfigSections(d.fields, d.sections);
      // Declared up front (not inside the loop) so the empty path leaves them
      // safe-to-index {} objects for revealFieldSections (§3e).
      var fieldSection = {};
      var panelsBySection = {};
      // never-throw (PET-99): skip a malformed entry rather than throwing on
      // f.name before the empty-guard / recovery panel can render — mirrors the
      // guard groupConfigSections already applies to the same d.fields.
      d.fields.forEach(function (f) {
        if (!f || typeof f !== "object" || f.name == null) return;
        fieldSection[f.name] = f.section;
      });

      if (groups.length === 0) {
        // Expected-degraded, never-throw (PET-99): no fields, or a registry/field
        // mismatch. Render a neutral panel rather than a blank area.
        formArea.appendChild(Pet.Panel({
          icon: "sliders", title: "Configuration",
          content: Pet.h("div", { className: "mono", style: { fontSize: "12px", color: "var(--tx-faint)", padding: "8px" } }, "No configurable fields."),
        }));
      }

      groups.forEach(function (group) {
        var fields = group.fields;
        var fieldEls = fields.map(function (f) {
          var val = d.config[f.name];
          var control;
          if (f.name === "profile_name") {
            // PET-122: dedicated fetch-sourced control, placed first so no other
            // field matches it and the generic enum/text branches stay unreachable
            // for profile_name (D-OPT1).
            control = Pet.buildProfileControl(f, val, profilesP);
          } else if (f.type === "boolean") {
            var toggleFn = function () {
              val = !val;
              sw.className = "switch" + (val ? " on" : "");
              sw.setAttribute("aria-checked", val ? "true" : "false");
              Pet.state.configDirty[f.name] = val;
              maybeUpdateDial(f.name);
            };
            var sw = Pet.h("button", {
              className: "switch" + (val ? " on" : ""),
              type: "button",
              role: "switch", ariaChecked: val ? "true" : "false", ariaLabel: Pet.humanizeKey(f.name),
              onClick: toggleFn,
            });
            sw.addEventListener("keydown", function (e) {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleFn(); }
            });
            control = sw;
          } else if (f.type === "enum" && f.constraints && f.constraints.values) {
            var seg = Pet.h("div", { className: "seg", role: "radiogroup", ariaLabel: Pet.humanizeKey(f.name) });
            f.constraints.values.forEach(function (opt) {
              var btn = Pet.h("button", {
                className: opt === val ? "on" : "", role: "radio", ariaChecked: opt === val ? "true" : "false",
                onClick: function () {
                  seg.querySelectorAll("button").forEach(function (b) { b.className = ""; b.setAttribute("aria-checked", "false"); });
                  btn.className = "on"; btn.setAttribute("aria-checked", "true");
                  Pet.state.configDirty[f.name] = opt;
                  maybeUpdateDial(f.name);
                }
              }, opt);
              seg.appendChild(btn);
            });
            control = seg;
          } else if (f.type === "number") {
            var inp = Pet.h("input", {
              className: "input mono", type: "number",
              style: { width: "110px", height: "32px" },
              value: val != null ? String(val) : "",
            });
            var c = f.constraints || {};
            if (c.min != null) inp.setAttribute("min", String(c.min));
            if (c.max != null) inp.setAttribute("max", String(c.max));
            var frac = (c.min != null && !Number.isInteger(c.min)) || (c.max != null && c.max <= 1);
            inp.setAttribute("step", frac ? "any" : "1");
            inp.addEventListener("change", function () {
              // PET-13: a cleared field is parseFloat("") -> NaN, which JSON-serializes
              // to null and silently sends null. Drop it from the diff instead.
              var n = parseFloat(inp.value);
              if (Number.isNaN(n)) { delete Pet.state.configDirty[f.name]; }
              else { Pet.state.configDirty[f.name] = n; }
              maybeUpdateDial(f.name);
            });
            control = inp;
          } else if (f.redacted) {
            control = Pet.h("span", { className: "mono", style: { fontSize: "12px", color: "var(--tx-faint)", overflowWrap: "anywhere", wordBreak: "break-all" } }, val || "(not set)");
          } else {
            var inp2 = Pet.h("input", {
              className: "input mono", style: { width: "200px", height: "32px" },
              value: val != null ? String(val) : "",
            });
            inp2.addEventListener("change", function () { Pet.state.configDirty[f.name] = inp2.value; maybeUpdateDial(f.name); });
            control = inp2;
          }

          return Pet.h("div", { dataset: { field: f.name }, style: { display: "flex", alignItems: "flex-start", gap: "14px", padding: "12px 0", borderBottom: "1px solid var(--border-soft)" } },
            Pet.h("div", { style: { flex: "1" } },
              Pet.h("div", { style: { fontSize: "13px", fontWeight: "600", color: "var(--tx-bright)" } }, Pet.humanizeKey(f.name)),
              Pet.h("div", { style: { fontSize: "11.5px", color: "var(--tx-mut)", marginTop: "2px" } }, f.help_plain || f.description),
              Pet.h("div", { className: "mono", style: { fontSize: "10px", color: "var(--tx-mut)", marginTop: "2px" } }, f.name)
            ),
            Pet.h("div", { className: "pet-ctrl-wrap", style: { flex: "0 0 auto", display: "flex", flexDirection: "column" } }, control)
          );
        });

        // Seed rule (§3b): read the user-choice map only if the key is present;
        // otherwise the registry/builder default. Never write the map here.
        var collapsed = Object.prototype.hasOwnProperty.call(Pet.state.sectionCollapsed, group.key)
          ? Pet.state.sectionCollapsed[group.key]   // user chose
          : group.default_collapsed;                 // registry/builder default
        // PET-123: prepend the plain-language intro (when present) above the field
        // rows. fieldEls is passed as a direct array child in both branches, so the
        // rows stay at today's DOM depth (Pet.h flattens an array child); the only
        // tree change is the single intro node when copy exists. intro === null is
        // byte-for-byte today's render (D4 / Design Change 3).
        var intro = Pet.sectionIntro(group.description);
        var body = intro
          ? Pet.h("div", {}, intro, fieldEls)
          : Pet.h("div", {}, fieldEls);
        var sectionPanel = Pet.Panel({
          icon: "sliders", title: group.label,
          collapsible: true, collapsed: collapsed,
          onToggle: function (c) { Pet.state.sectionCollapsed[group.key] = c; },
          content: body,
        });
        sectionPanel.dataset.section = group.key;
        panelsBySection[group.key] = sectionPanel;
        formArea.appendChild(sectionPanel);
      });

      // ── Save bar (PET-13: sticky so Apply stays visible below collapsed sections) ──
      // PET-13: flag pending edits that LOWER protection (a scanner/feature toggled
      // off, or fail_mode -> open) so Apply gates them with a confirming second
      // click, the same care the disarm switch gets. base = persisted config.
      var diffWeakensProtection = function () {
        var base = Pet.state.config || {};
        var dirty = Pet.state.configDirty || {};
        return Object.keys(dirty).some(function (k) {
          if (base[k] === true && dirty[k] === false) return true;    // a protection toggled off
          if (k === "fail_mode" && dirty[k] === "open") return true;  // weakest fail mode
          return false;
        });
      };
      var _weakenConfirmPending = false;
      var _weakenConfirmTimer = null;
      var applyLabel = Pet.h("span", {}, " Apply");
      var applyBtn;
      var setWeakenConfirm = function (on) {
        _weakenConfirmPending = on;
        if (applyBtn) applyBtn.className = "btn btn-primary" + (on ? " confirm-weaken" : "");
        applyLabel.textContent = on ? " Confirm: this lowers protection" : " Apply";
        var note = formArea.querySelector(".pet-weaken-note");
        if (on && !note) {
          formArea.insertBefore(Pet.h("div", { role: "alert", className: "notice pet-weaken-note", style: { marginBottom: "8px" } },
            Pet.Icon("warn"), Pet.h("span", {}, Pet.h("b", {}, "These changes lower protection."), " Click Apply again to confirm.")
          ), formArea.firstChild);
        } else if (!on && note) {
          note.remove();
        }
      };
      var clearWeakenConfirm = function () {
        if (_weakenConfirmTimer) { clearTimeout(_weakenConfirmTimer); _weakenConfirmTimer = null; }
        setWeakenConfirm(false);
      };
      var saveBar = Pet.h("div", { className: "pet-save-bar", style: { position: "sticky", bottom: "0", background: "var(--bg-app)", borderTop: "1px solid var(--border-soft)", marginTop: "6px", padding: "8px 0", display: "flex", flexDirection: "column", gap: "8px" } },
        // PET-13: subtle hot-swap disclosure (PET-126), bottom-anchored, not a top warning.
        // PET-146: honest per-view copy — the equipped profile hot-applies; a
        // non-equipped profile persists to its config.yaml and waits for equip/restart.
        Pet.h("div", { style: { fontSize: "11px", color: "var(--tx-faint)", fontFamily: "var(--font-mono)", lineHeight: "1.5" } },
          viewingActive
            ? "Saved to config.yaml and applied to the running pipeline immediately. No restart needed; frequency counters and escalation state are preserved."
            : "Saved to the selected profile's config.yaml. Takes effect when that profile is equipped (restart); the running pipeline is not changed."),
        Pet.h("div", { style: { display: "flex", gap: "10px", justifyContent: "flex-end", alignItems: "center" } },
        Pet.h("button", { className: "btn btn-ghost", onClick: function () {
          if (applyBtn && applyBtn.disabled) return;  // PET-13: Apply in flight; don't tear down formArea mid-PUT
          clearWeakenConfirm();
          Pet.state.configDirty = {};
          Pet.renderConfig(container);
        } }, "Discard"),
        (function () {
          applyBtn = Pet.h("button", { className: "btn btn-primary", onClick: function () {
            if (Object.keys(Pet.state.configDirty).length === 0) return;
            // PET-13: protection-weakening edits require a confirming second click.
            if (diffWeakensProtection() && !_weakenConfirmPending) {
              setWeakenConfirm(true);
              _weakenConfirmTimer = setTimeout(function () { clearWeakenConfirm(); }, 4000);
              return;
            }
            clearWeakenConfirm();
            formArea.querySelectorAll(".pet-field-err").forEach(function (el) { el.remove(); });
            applyBtn.disabled = true;
            // PET-146: send the dirty-field subset (never the full form — a full-form
            // save against an empty on-disk section would reset a profile's posture,
            // edge round-2 F-6) and, when a non-equipped profile is in view, tag it
            // with `profile` so update_config persists-only (D4).
            var savePatch = Pet.buildSavePatch(Pet.state.configDirty, viewingActive, Pet.state.selectedHermesProfile);
            Pet.api.putConfig(savePatch).then(function (d) {
              if (_renderGen !== Pet._runtime.configRenderGen) return; // PET-155: a host rebind/unmount superseded this render — drop the stale save so it can't wipe the new profile's dirty edits or clobber its config
              if (Pet.auth.on401(d)) return; // PET-129: a config-save 401 enters the auth state, not a validation error
              if (d._status && d.detail) {
                var raw = Array.isArray(d.detail) ? d.detail : [d.detail];
                var details = raw.map(function (el) {
                  if (typeof el === "string") return { field: "?", message: el };
                  if (!el || typeof el !== "object") return { field: "?", message: String(el) };
                  return { field: el.field || el.name || el.path || "?", message: el.message || el.msg || el.detail || String(el) };
                });
                // §3f: expand any default-collapsed section that owns an errored
                // field BEFORE the .pet-field-err nodes are appended, so the
                // inline error lands in a visible (un-hidden) body. Synchronous
                // class removal in petSetCollapsed un-hides it this same tick.
                Pet.revealFieldSections(
                  details.map(function (e) { return e.field; }), fieldSection, panelsBySection
                );
                details.forEach(function (err) {
                  if (err.field === "?") return;
                  var fieldEl = null;
                  formArea.querySelectorAll("[data-field]").forEach(function (el) {
                    if (el.dataset.field === err.field) fieldEl = el;
                  });
                  if (fieldEl) {
                    var wrapper = fieldEl.querySelector(".pet-ctrl-wrap");
                    (wrapper || fieldEl).appendChild(Pet.h("div", {
                      className: "pet-field-err",
                      style: { color: "var(--err)", fontSize: "11px", marginTop: "4px" }
                    }, err.message));
                  }
                });
                if (!formArea.querySelector(".pet-field-err")) {
                  var msg = details.map(function (e) { return e.field + ": " + e.message; }).join("; ");
                  formArea.insertBefore(Pet.h("div", {
                    role: "alert",
                    className: "pet-field-err",
                    style: { color: "var(--err)", fontSize: "12px", padding: "8px 12px", background: "var(--bg-raised)", borderRadius: "var(--r-card)", marginBottom: "8px" }
                  }, msg), formArea.firstChild);
                }
                return;
              }
              if (d.error) {
                formArea.insertBefore(Pet.h("div", {
                  role: "alert",
                  className: "pet-field-err",
                  style: { color: "var(--err)", fontSize: "12px", padding: "8px 12px", background: "var(--bg-raised)", borderRadius: "var(--r-card)", marginBottom: "8px" }
                }, "Couldn't save: " + d.error + ". Your changes are kept; try Apply again."), formArea.firstChild);
                return;
              }
              Pet.state.config = d.config || Pet.state.config;
              Pet.state.configDirty = {};
              // PET-146 D5: a non-equipped save persisted-only (applied === false) —
              // say so honestly (takes effect on equip/restart) rather than claiming
              // it hit the running pipeline. The re-render below re-shows the banner.
              var savedTail = (d.applied === false)
                ? " Saved to the selected profile; takes effect when it's equipped (restart)."
                : " Applied to the running pipeline.";
              formArea.insertBefore(Pet.h("div", {
                role: "status",
                className: "notice",
                style: { background: "var(--ok-soft)", borderColor: "rgba(63,185,80,.3)", color: "var(--ok)", marginBottom: "8px" }
              }, Pet.Icon("check"), Pet.h("span", {}, Pet.h("b", {}, "Configuration saved."), savedTail)), formArea.firstChild);
              var savedRenderGen = _renderGen;
              setTimeout(function () {
                if (Pet.state.tab === "cfg" && savedRenderGen === Pet._runtime.configRenderGen) Pet.renderConfig(container);
              }, 1500);
            }).then(function () { applyBtn.disabled = false; }, function () { applyBtn.disabled = false; });
          } }, Pet.Icon("check"), applyLabel);
          return applyBtn;
        })()
        )
      );
      formArea.appendChild(saveBar);
    });
  };


  Pet._moduleState.last = "config";
})();
