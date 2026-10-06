/* Paddock Legacy 2.0 application shell: navigation drawer, league/mode switchers, command palette, tabs,
   table filters and the unsaved-work guard. No external libraries; everything works with the keyboard. */
(function () {
  "use strict";
  var F1 = window.F1 = window.F1 || {};

  /* ---------------------------------------------------------------- unsaved work
     Pages register a function that says whether they have unsaved edits (results entry does). Ordinary forms
     are tracked automatically once someone types in them. */
  var checks = [];
  F1.registerUnsaved = function (fn) { checks.push(fn); };
  var touched = new Set();
  document.addEventListener("input", function (e) {
    var form = e.target.closest && e.target.closest("form");
    if (!form || form.method.toLowerCase() !== "post" || e.target.type === "search" || form.hasAttribute("data-mode-form")) return;
    if (e.target.closest("[data-no-dirty]")) return;
    touched.add(form);
  });
  document.addEventListener("submit", function (e) { touched.delete(e.target); }, true);
  F1.hasUnsaved = function () {
    return touched.size > 0 || checks.some(function (fn) { try { return !!fn(); } catch (err) { return false; } });
  };
  function guard(message, go) {
    if (!F1.hasUnsaved()) { go(); return; }
    if (F1.confirmAction) {
      F1.confirmAction({ title: "Leave with unsaved changes?", what: message,
        history: "Anything you haven't saved on this page will be lost (results entry keeps a copy on this device).",
        ok: "Leave anyway", safe: true }).then(function (ok) { if (ok) { touched.clear(); go(); } });
    } else if (window.confirm(message + " Unsaved changes on this page will be lost.")) { go(); }
  }
  // Switching league or view mode with unsaved work asks first.
  document.addEventListener("click", function (e) {
    var link = e.target.closest("a[data-league-link]");
    if (link && F1.hasUnsaved()) {
      e.preventDefault();
      guard("You're switching to another league.", function () { window.location.href = link.href; });
    }
  });
  document.querySelectorAll("form[data-mode-form]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (form.dataset.confirmed === "1" || !F1.hasUnsaved()) return;
      e.preventDefault();
      var btn = e.submitter;
      guard("You're changing how this league is shown.", function () {
        form.dataset.confirmed = "1";
        if (btn) { var h = document.createElement("input"); h.type = "hidden"; h.name = btn.name; h.value = btn.value; form.appendChild(h); }
        form.submit();
      });
    });
  });

  /* ---------------------------------------------------------------- dropdowns (league & mode switchers) */
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.dropdown[open]").forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    document.querySelectorAll("details.dropdown[open]").forEach(function (d) {
      d.removeAttribute("open");
      var s = d.querySelector("summary"); if (s) s.focus();
    });
  });

  /* ---------------------------------------------------------------- navigation drawer (phones and tablets) */
  var sidebar = document.getElementById("sidebar");
  var scrim = document.getElementById("sidebar-scrim");
  var menuBtn = document.getElementById("menu-btn");
  var lastFocus = null;
  function openMenu() {
    if (!sidebar) return;
    lastFocus = document.activeElement;
    sidebar.classList.add("open");
    if (scrim) scrim.hidden = false;
    if (menuBtn) menuBtn.setAttribute("aria-expanded", "true");
    var first = sidebar.querySelector("a, button"); if (first) first.focus();
  }
  function closeMenu() {
    if (!sidebar || !sidebar.classList.contains("open")) return;
    sidebar.classList.remove("open");
    if (scrim) scrim.hidden = true;
    if (menuBtn) menuBtn.setAttribute("aria-expanded", "false");
    if (lastFocus) lastFocus.focus();
  }
  if (menuBtn) menuBtn.addEventListener("click", function () { sidebar.classList.contains("open") ? closeMenu() : openMenu(); });
  document.querySelectorAll("[data-open-menu]").forEach(function (b) { b.addEventListener("click", openMenu); });
  if (scrim) scrim.addEventListener("click", closeMenu);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeMenu();
    if (e.key === "Tab" && sidebar && sidebar.classList.contains("open") && window.matchMedia("(max-width: 900px)").matches) {
      var items = Array.prototype.filter.call(sidebar.querySelectorAll("a, button"), function (el) { return el.offsetParent !== null; });
      if (!items.length) return;
      if (e.shiftKey && document.activeElement === items[0]) { e.preventDefault(); items[items.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === items[items.length - 1]) { e.preventDefault(); items[0].focus(); }
    }
  });

  /* ---------------------------------------------------------------- tabs */
  document.querySelectorAll("[role=tablist]").forEach(function (list) {
    var tabs = Array.prototype.slice.call(list.querySelectorAll("[role=tab]"));
    function select(tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.classList.toggle("is-on", on);
        t.tabIndex = on ? 0 : -1;
        var panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
      try { history.replaceState(null, "", "#" + tab.dataset.tab); } catch (e) { /* ignore */ }
    }
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { select(t); });
      t.addEventListener("keydown", function (e) {
        var j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null;
        if (j === null) return;
        e.preventDefault();
        select(tabs[(j + tabs.length) % tabs.length], true);
      });
    });
    var wanted = tabs.find(function (t) { return "#" + t.dataset.tab === location.hash; });
    if (wanted) select(wanted);
  });

  /* ---------------------------------------------------------------- table search and "player drivers only" */
  function filterTable(id) {
    var table = document.getElementById(id);
    if (!table) return;
    var q = ((document.querySelector('[data-filter-table="' + id + '"]') || {}).value || "").trim().toLowerCase();
    var only = (document.querySelector('[data-players-only="' + id + '"]') || {}).checked;
    var shown = 0;
    table.querySelectorAll("tbody tr").forEach(function (tr) {
      var ok = (!q || (tr.dataset.search || tr.textContent.toLowerCase()).indexOf(q) !== -1) && (!only || tr.dataset.player === "1");
      tr.hidden = !ok;
      if (ok) shown++;
    });
    var empty = table.closest(".card") && table.closest(".card").querySelector(".filter-empty");
    if (empty) empty.hidden = shown > 0;
  }
  document.querySelectorAll("[data-filter-table]").forEach(function (el) {
    el.addEventListener("input", function () { filterTable(el.dataset.filterTable); });
  });
  document.querySelectorAll("[data-players-only]").forEach(function (el) {
    el.addEventListener("change", function () { filterTable(el.dataset.playersOnly); });
  });

  /* ---------------------------------------------------------------- command palette (Ctrl/⌘ K) */
  var palette = document.getElementById("palette");
  var searchBtn = document.getElementById("search-btn");
  if (palette && searchBtn) {
    var input = document.getElementById("palette-q");
    var list = document.getElementById("palette-list");
    var url = searchBtn.dataset.searchUrl;
    var items = [], active = 0, timer = null, ctrl = null, loading = false, goWhenLoaded = false, loadedFor = null;
    function render() {
      list.innerHTML = "";
      if (!items.length) {
        var li = document.createElement("li");
        li.className = "palette-empty";
        li.textContent = input.value ? "Nothing matches “" + input.value + "” in this league." : "Start typing to search.";
        list.appendChild(li);
        input.removeAttribute("aria-activedescendant");
        return;
      }
      items.forEach(function (it, i) {
        var li = document.createElement("li");
        li.id = "pal-" + i;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", i === active ? "true" : "false");
        li.className = i === active ? "is-active" : "";
        var kind = document.createElement("span"); kind.className = "pal-kind"; kind.textContent = it.kind;
        var label = document.createElement("b"); label.textContent = it.label;
        var sub = document.createElement("small"); sub.className = "muted"; sub.textContent = it.sub || "";
        li.append(kind, label, sub);
        li.addEventListener("click", function () { go(i); });
        list.appendChild(li);
      });
      input.setAttribute("aria-activedescendant", "pal-" + active);
      var el = document.getElementById("pal-" + active); if (el) el.scrollIntoView({ block: "nearest" });
    }
    function load() {
      clearTimeout(timer); timer = null;
      if (ctrl) ctrl.abort();
      ctrl = window.AbortController ? new AbortController() : null;
      var q = input.value;
      loading = true;
      fetch(url + "?q=" + encodeURIComponent(q), { credentials: "same-origin", signal: ctrl ? ctrl.signal : undefined })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          items = (data && data.items) || []; active = 0; loading = false; loadedFor = q; render();
          if (goWhenLoaded) { goWhenLoaded = false; go(active); }   // Enter pressed while these were on their way
        })
        .catch(function (err) { if (err.name !== "AbortError") { loading = false; items = []; render(); } });
    }
    function go(i) {
      var it = items[i]; if (!it) return;
      guard("You're leaving this page.", function () { window.location.href = it.url; });
    }
    function open() {
      input.value = "";
      palette.showModal();
      input.focus();
      load();
    }
    searchBtn.addEventListener("click", open);
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); palette.open ? palette.close() : open(); }
      else if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !palette.open) { e.preventDefault(); open(); }
    });
    input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(load, 120); });
    input.addEventListener("keydown", function (e) {
      // v3.0: one Escape closes the palette (a search box would otherwise use the first one to clear itself)
      if (e.key === "Escape") { e.preventDefault(); palette.close(); searchBtn.focus(); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(items.length - 1, active + 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); render(); }
      else if (e.key === "Enter") {
        e.preventDefault();
        // Never open a stale result: if the list doesn't match what's typed yet, open the first fresh one.
        if (timer || loading || loadedFor !== input.value) { goWhenLoaded = true; if (timer) load(); }
        else go(active);
      }
    });
  }

  /* ---------------------------------------------------------------- offline banner */
  function offline() {
    var bar = document.getElementById("offline-bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "offline-bar"; bar.className = "offline-bar"; bar.setAttribute("role", "status");
      bar.textContent = "You're offline. Pages you open may be out of date; unsaved result changes stay on this device.";
      document.body.appendChild(bar);
    }
    bar.hidden = navigator.onLine !== false;
  }
  window.addEventListener("online", offline);
  window.addEventListener("offline", offline);
  if (navigator.onLine === false) offline();

  /* v3.0: a table or code block that scrolls sideways (common on phones) can be reached and scrolled by keyboard. */
  function focusableScrollers() {
    document.querySelectorAll(".table-wrap, .scroll-x, pre, main table").forEach(function (el) {
      var scrolls = el.scrollWidth > el.clientWidth + 1;
      if (scrolls && !el.hasAttribute("tabindex")) {
        el.setAttribute("tabindex", "0");
        el.setAttribute("data-scroll-focus", "1");
        if (!el.getAttribute("aria-label") && !el.getAttribute("role") && el.tagName !== "TABLE") {
          var cap = el.querySelector("caption");
          el.setAttribute("role", "region");
          el.setAttribute("aria-label", (cap && cap.textContent.trim()) || "Scrollable table");
        }
      } else if (!scrolls && el.getAttribute("data-scroll-focus")) {
        el.removeAttribute("tabindex");
        el.removeAttribute("data-scroll-focus");
      }
    });
  }
  focusableScrollers();
  window.addEventListener("resize", function () { clearTimeout(focusableScrollers.t); focusableScrollers.t = setTimeout(focusableScrollers, 200); });
})();

/* 4.0.0-beta.13: every form that saves something.
   - It says where it was sent from (return_to: this page, its stage and section), so the site can bring you back
     to the same place. The site checks that address itself and ignores anything that isn't one of its own pages.
   - A second press while the first is still on its way is ignored here; the site also refuses duplicates itself.
   - What was typed is kept in this tab until the site answers. If it says the form wasn't saved, the page you come
     back to puts the values back; once something saves, the copy is thrown away. Passwords are never kept. */
(function () {
  "use strict";
  var KEY = "f1-last-form";
  function actionPath(form, submitter) {
    var raw = (submitter && submitter.getAttribute("formaction")) || form.getAttribute("action") || location.pathname;
    try { return new URL(raw, location.href).pathname; } catch (e) { return raw; }
  }
  function remember(form, path) {
    var fields = [];
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || el.disabled) return;
      var type = (el.type || "").toLowerCase();
      if (["hidden", "password", "file", "submit", "button", "reset", "image"].indexOf(type) > -1) return;
      if (el.name === "csrf_token" || el.name === "return_to") return;
      if (type === "checkbox" || type === "radio") fields.push([el.name, el.value, el.checked]);
      else if (el.tagName === "SELECT" && el.multiple) fields.push([el.name, Array.prototype.filter.call(el.options, function (o) { return o.selected; }).map(function (o) { return o.value; })]);
      else fields.push([el.name, el.value]);
    });
    try { sessionStorage.setItem(KEY, JSON.stringify({ action: path, at: Date.now(), fields: fields })); } catch (e) { /* private mode */ }
  }
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (e.defaultPrevented || !form || !form.getAttribute || (form.getAttribute("method") || "").toLowerCase() !== "post") return;
    if (form.target && form.target !== "_self") return;
    if (form.dataset.f1Sending === "1") { e.preventDefault(); return; }
    if (navigator.onLine === false) {
      // Sending now would only show the browser's offline page and lose what was typed.
      e.preventDefault();
      if (window.F1 && window.F1.toast) window.F1.toast("You're offline, so that wasn't sent. What you entered is still here; send it again once you're back online.", "error");
      return;
    }
    form.dataset.f1Sending = "1";
    var btn = e.submitter;
    if (btn) { btn.classList.add("is-sending"); btn.setAttribute("aria-busy", "true"); }
    // a download or a page that doesn't change: allow sending again after a while
    setTimeout(function () { delete form.dataset.f1Sending; if (btn) { btn.classList.remove("is-sending"); btn.removeAttribute("aria-busy"); } }, 8000);
    if (!form.querySelector('input[name="return_to"]')) {
      var back = document.createElement("input");
      back.type = "hidden"; back.name = "return_to";
      back.value = location.pathname + location.search + location.hash;
      form.appendChild(back);
    }
    remember(form, actionPath(form, btn));
  });
  // Coming back to this page with the browser's Back button: its forms can be sent again.
  window.addEventListener("pageshow", function (e) {
    if (!e.persisted) return;
    document.querySelectorAll("form[data-f1-sending]").forEach(function (f) { delete f.dataset.f1Sending; });
    document.querySelectorAll(".is-sending").forEach(function (b) { b.classList.remove("is-sending"); b.removeAttribute("aria-busy"); });
  });
  // The page after a form: put back what was typed when the site said it wasn't saved.
  var failed = document.querySelector('meta[name="form-failed"]');
  var saved = null;
  try { saved = JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch (e) { saved = null; }
  if (/^\/login/.test(location.pathname)) return;    // the sign-in page: keep it for the page after signing in
  try { sessionStorage.removeItem(KEY); } catch (e) { /* private mode */ }
  if (!failed || !saved || saved.action !== failed.content || Date.now() - saved.at > 30 * 60 * 1000) return;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", restore); else restore();
  function restore() {
  var forms = Array.prototype.filter.call(document.querySelectorAll("form"), function (f) {
    return (f.getAttribute("method") || "").toLowerCase() === "post" && actionPath(f) === saved.action;
  });
  if (!forms.length) return;
  forms.forEach(function (form) {
    var seen = {};
    saved.fields.forEach(function (f) {
      var name = f[0], value = f[1];
      var els = Array.prototype.filter.call(form.elements, function (el) { return el.name === name; });
      if (!els.length) return;
      var t = (els[0].type || "").toLowerCase();
      if (t === "checkbox" || t === "radio") {
        els.forEach(function (el) { if (el.value === value) el.checked = !!f[2]; });
      } else if (els[0].tagName === "SELECT" && els[0].multiple && Array.isArray(value)) {
        Array.prototype.forEach.call(els[0].options, function (o) { o.selected = value.indexOf(o.value) > -1; });
      } else {
        var i = seen[name] || 0; seen[name] = i + 1;
        var el = els[Math.min(i, els.length - 1)];
        if (el.type !== "hidden" && el.type !== "password" && el.type !== "file") el.value = value;
      }
    });
    form.classList.add("form-restored");
    var det = form.closest("details"); if (det) det.open = true;
  });
  var first = forms[0];
  var stage = first.closest(".ws-stage");
  if (stage && window.F1Workspace && window.F1Workspace.show) window.F1Workspace.show(stage.dataset.stage, { keepScroll: true });
  // A form that lives in a pop-up (e.g. Report an incident) opens again, so what was typed is actually seen.
  var dlg = first.closest("dialog");
  if (dlg && !dlg.open && dlg.showModal) {
    // The pop-up covers the page's message, so the reason is repeated inside it.
    var why = document.querySelector("#toasts .toast-error span");
    if (why && !first.querySelector(".form-error")) {
      var p = document.createElement("p");
      p.className = "form-error"; p.setAttribute("role", "alert"); p.textContent = why.textContent;
      first.insertBefore(p, first.firstChild);
    }
    try { dlg.showModal(); } catch (e) { /* already open elsewhere */ }
    return;
  }
  setTimeout(function () { first.scrollIntoView({ block: "center" }); }, 60);
  }
})();
