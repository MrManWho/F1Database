/* 4.0 Race Weekend workspace: moves between the four stages (Prepare, Sessions, Review & submit, Debrief) and the
   sessions inside Sessions without reloading. Where the page opens is decided on the server from the saved round;
   this only switches what's shown. "Save & continue" saves any pending edit first and never submits anything.
   Without JavaScript every stage simply shows, one after the other. */
(function () {
  "use strict";
  const stages = Array.prototype.slice.call(document.querySelectorAll(".ws-stage"));
  if (!stages.length) return;
  const ORDER = stages.map(function (s) { return s.dataset.stage; });
  const SESSION_ORDER = Array.prototype.slice.call(document.querySelectorAll(".session-cards [data-session]"))
    .map(function (b) { return b.dataset.session; }).filter(function (k) { return k !== "all"; });
  const LABELS = { q: "Qualifying", s: "Sprint", r: "Race", all: "All sessions" };
  const back = document.querySelector("[data-ws-back]"), next = document.querySelector("[data-ws-next]");
  const table = document.getElementById("entry-table");
  let current = (stages.find(function (s) { return !s.hidden; }) || stages[0]).dataset.stage;
  let session = table ? (table.dataset.sessionDefault || "r") : "r";

  function flush() {
    return window.F1Weekend && window.F1Weekend.flush ? window.F1Weekend.flush() : Promise.resolve(true);
  }
  function setUrl() {
    try {
      const u = new URL(location.href);
      u.searchParams.set("stage", current);
      if (current === "sessions" && session) u.searchParams.set("session", session); else u.searchParams.delete("session");
      u.searchParams.delete("submitted");
      history.replaceState(null, "", u.pathname + u.search + u.hash);
    } catch (e) { /* old browser: the stage just isn't kept in the address */ }
  }
  function updateBar() {
    const i = ORDER.indexOf(current);
    if (back) back.hidden = i <= 0 && !(current === "sessions" && SESSION_ORDER.indexOf(session) > 0);
    if (next) {
      const inSessions = current === "sessions" && SESSION_ORDER.indexOf(session) > -1 && SESSION_ORDER.indexOf(session) < SESSION_ORDER.length - 1;
      next.hidden = i >= ORDER.length - 1;
      const label = inSessions ? LABELS[SESSION_ORDER[SESSION_ORDER.indexOf(session) + 1]] : (ORDER[i + 1] ? document.querySelector('[data-stage-link="' + ORDER[i + 1] + '"] b').textContent : "");
      next.textContent = (next.dataset.readonly === "1" ? "Next: " : "Save & continue: ") + label + " →";
    }
  }
  function show(stage, opts) {
    opts = opts || {};
    if (ORDER.indexOf(stage) < 0) return;
    current = stage;
    stages.forEach(function (s) { s.hidden = s.dataset.stage !== stage; });
    document.querySelectorAll(".ws-step").forEach(function (a) {
      const on = a.dataset.stageLink === stage;
      a.classList.toggle("is-on", on);
      if (on) a.setAttribute("aria-current", "step"); else a.removeAttribute("aria-current");
    });
    if (stage === "review") refreshChecklist();
    setUrl(); updateBar();
    if (!opts.keepScroll) {
      const head = document.querySelector(".ws-stepper");
      if (head) window.scrollTo({ top: Math.max(0, head.getBoundingClientRect().top + window.scrollY - 70) });
    }
  }
  function showSessionExtras(key) {
    session = key;
    document.querySelectorAll("[data-session-only]").forEach(function (el) {
      const keys = el.dataset.sessionOnly.split(" ");
      el.hidden = key !== "all" && keys.indexOf(key) < 0;
    });
    document.querySelectorAll("[data-session-title]").forEach(function (el) { el.textContent = key === "all" ? "Results · all sessions" : LABELS[key] + " results"; });
    const sel = document.getElementById("incident-session");
    if (sel && key !== "all") sel.value = ({ q: "qualifying", s: "sprint", r: "race" })[key];
    const nx = document.querySelector("[data-incident-next]");
    if (nx) nx.value = location.pathname + "?stage=sessions&session=" + key + "#incidents";
    if (current === "sessions") setUrl();
    updateBar();
  }
  document.addEventListener("f1:session", function (e) { showSessionExtras(e.detail); });
  showSessionExtras(session);

  function goSession(key) {
    if (window.F1Weekend && window.F1Weekend.showSession) window.F1Weekend.showSession(key); else showSessionExtras(key);
  }
  function goTo(stage, key, anchor) {
    return flush().then(function (ok) {
      if (ok === false) return;
      show(stage, { keepScroll: !!anchor });
      if (key) goSession(key);
      if (anchor) {
        const el = document.getElementById(anchor);
        if (el) {
          const det = el.closest("details"); if (det) det.open = true;
          el.scrollIntoView({ block: "center" });
          const field = el.matches("input, select, textarea") ? el : el.querySelector("input:not([type=hidden]):not([disabled]), select, textarea");
          if (field) setTimeout(function () { field.focus(); }, 150);
        }
      }
    });
  }

  document.addEventListener("click", function (e) {
    const link = e.target.closest("[data-stage-link]");
    if (link) { e.preventDefault(); goTo(link.dataset.stageLink); return; }
    const fix = e.target.closest("[data-fix-session]");
    if (fix) {
      e.preventDefault();
      const dlg = fix.closest("dialog"); if (dlg && dlg.open) dlg.close();
      goTo("sessions", fix.dataset.fixSession, fix.dataset.fixAnchor);
      return;
    }
    const opener = e.target.closest("[data-open-details]");
    if (opener) {
      const id = (opener.getAttribute("href") || "").replace("#", "");
      const el = id && document.getElementById(id);
      if (el) { e.preventDefault(); const st = el.closest(".ws-stage"); if (st) show(st.dataset.stage, { keepScroll: true });
        const det = el.closest("details"); if (det) det.open = true; el.scrollIntoView({ block: "start" }); }
    }
  });
  if (back) back.addEventListener("click", function (e) {
    e.preventDefault();
    const si = SESSION_ORDER.indexOf(session);
    if (current === "sessions" && si > 0) { flush().then(function () { goSession(SESSION_ORDER[si - 1]); }); return; }
    const i = ORDER.indexOf(current);
    if (i > 0) goTo(ORDER[i - 1]);
  });
  if (next) {
    next.dataset.readonly = /Next/.test(next.textContent) ? "1" : "0";
    next.addEventListener("click", function (e) {
      e.preventDefault();
      const si = SESSION_ORDER.indexOf(session);
      if (current === "sessions" && si > -1 && si < SESSION_ORDER.length - 1) {
        flush().then(function () { goSession(SESSION_ORDER[si + 1]); window.scrollTo({ top: 0 }); });
        return;
      }
      const i = ORDER.indexOf(current);
      if (i < ORDER.length - 1) goTo(ORDER[i + 1]);
    });
  }

  // Review: the checklist is the server's own, fetched again each time the stage opens (after saving).
  function where(text) {
    const m = text.toLowerCase();
    if (m.indexOf("race times") > -1) return ["r", "pace"];
    if (m.indexOf("ai difficulty") > -1) return ["r", "ai-difficulty"];
    if (m.indexOf("weekend notes") > -1) return ["r", "event-notes"];
    if (m.indexOf("sprint") > -1) return ["s", "entry-table"];
    if (m.indexOf("qualifying") > -1) return ["q", "entry-table"];
    return ["r", "entry-table"];
  }
  function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function fixButton(text) {
    const w = where(text);
    return ' <a class="btn btn-sm btn-ghost" href="?stage=sessions&session=' + w[0] + "#" + w[1] + '" data-fix-session="' + w[0] + '" data-fix-anchor="' + w[1] + '">Fix</a>';
  }
  window.F1Workspace = { fixButton: fixButton, show: show };
  const box = document.querySelector("[data-checklist]");
  function refreshChecklist() {
    if (!box || !table || !table.dataset.checklistUrl) return;
    flush().then(function () { return fetch(table.dataset.checklistUrl, { credentials: "same-origin" }); })
      .then(function (r) { return r.json(); })
      .then(function (check) {
        if (!check || !check.ok) return;
        const body = box.querySelector("[data-check-body]"), count = box.querySelector("[data-check-count]");
        const b = check.blocking || [], w = check.warnings || [];
        const list = function (items, cls) {
          return items.length ? '<ul class="check-list ' + cls + '">' + items.map(function (t) { return "<li><span>" + esc(t) + "</span>" + fixButton(t) + "</li>"; }).join("") + "</ul>" : '<p class="small">None. ✓</p>';
        };
        body.innerHTML = '<h3 class="mini-head">⛔ Must fix (' + b.length + ")</h3>" + list(b, "is-block") +
          '<h3 class="mini-head">⚠️ Warnings (' + w.length + ")</h3>" + list(w, "is-warn");
        if (count) { count.textContent = b.length + " to fix · " + w.length + " warning" + (w.length !== 1 ? "s" : ""); count.classList.toggle("pill-hot", b.length > 0); }
      }).catch(function () { /* offline: the last checklist stays on screen */ });
  }

  // Deep link to an element inside a stage (e.g. #press, #target): open that stage.
  if (location.hash) {
    const el = document.getElementById(location.hash.slice(1));
    const st = el && el.closest(".ws-stage");
    if (st && st.dataset.stage !== current) show(st.dataset.stage, { keepScroll: true });
    const only = el && el.closest("[data-session-only]");
    if (only && only.hidden) goSession(only.dataset.sessionOnly.split(" ")[0]);
    if (el) { const det = el.closest("details"); if (det) det.open = true; setTimeout(function () { el.scrollIntoView({ block: "start" }); }, 50); }
  }
  updateBar();
})();
