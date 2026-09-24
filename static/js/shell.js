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
    var items = [], active = 0, timer = null, ctrl = null;
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
      if (ctrl) ctrl.abort();
      ctrl = window.AbortController ? new AbortController() : null;
      fetch(url + "?q=" + encodeURIComponent(input.value), { credentials: "same-origin", signal: ctrl ? ctrl.signal : undefined })
        .then(function (r) { return r.json(); })
        .then(function (data) { items = (data && data.items) || []; active = 0; render(); })
        .catch(function (err) { if (err.name !== "AbortError") { items = []; render(); } });
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
      if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(items.length - 1, active + 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); render(); }
      else if (e.key === "Enter") { e.preventDefault(); go(active); }
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
})();
