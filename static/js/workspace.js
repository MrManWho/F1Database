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
  const INCIDENT_ANCHOR = { q: "incidents-q", s: "incidents-s", r: "incidents" };
  const back = document.querySelector("[data-ws-back]"), next = document.querySelector("[data-ws-next]");
  const nextLabel = next && next.querySelector("[data-ws-next-label]"), nextLine = document.querySelector("[data-ws-next-line]");
  const layout = document.querySelector(".ws-layout");
  const classSec = document.getElementById("sec-classification");
  const table = document.getElementById("entry-table");
  let current = (stages.find(function (s) { return !s.hidden; }) || stages[0]).dataset.stage;
  let session = table ? (table.dataset.sessionDefault || "r") : "r";
  // 4.0.0-beta.13: a fix opened from Review & submit leads back to Review (kept in the address, so it survives a
  // form that reloads the page) instead of on through the remaining sessions.
  let fromReview = false;
  try { fromReview = new URL(location.href).searchParams.get("from") === "review"; } catch (e) { /* old browser */ }

  function flush() {
    return window.F1Weekend && window.F1Weekend.flush ? window.F1Weekend.flush() : Promise.resolve(true);
  }
  function setUrl() {
    try {
      const u = new URL(location.href);
      u.searchParams.set("stage", current);
      if (current === "sessions" && session) u.searchParams.set("session", session); else u.searchParams.delete("session");
      if (current === "sessions" && fromReview) u.searchParams.set("from", "review"); else u.searchParams.delete("from");
      u.searchParams.delete("submitted");
      history.replaceState(null, "", u.pathname + u.search + u.hash);
    } catch (e) { /* old browser: the stage just isn't kept in the address */ }
  }
  // The bottom bar: one way on. "Save & continue" saves pending edits and moves to the next session or step; it
  // never submits. On Review & submit the step's own Submit button is the action, so the bar only goes back.
  function updateBar() {
    const i = ORDER.indexOf(current);
    const ro = next && next.dataset.readonly === "1";
    if (back) back.hidden = i <= 0 && !(current === "sessions" && SESSION_ORDER.indexOf(session) > 0);
    if (!next) return;
    if (fromReview && current === "sessions") {
      next.hidden = false;
      setNext(ro ? "Back to Review" : "Save & return to Review", "");
      return;
    }
    const si = SESSION_ORDER.indexOf(session);
    const inSessions = current === "sessions" && si > -1 && si < SESSION_ORDER.length - 1;
    const atSubmit = current === "review" && next.dataset.complete !== "1";
    next.hidden = i >= ORDER.length - 1 || (atSubmit && !ro);
    const label = inSessions ? LABELS[SESSION_ORDER[si + 1]] : (ORDER[i + 1] ? stageName(ORDER[i + 1]) : "");
    setNext(ro ? "Next" : "Save & continue", label ? "Next: " + label : "");
  }
  function stageName(key) {
    const b = document.querySelector('.ws-step[data-stage-link="' + key + '"] b');
    return b ? b.textContent : key;
  }
  function setNext(text, line) {
    if (nextLabel) nextLabel.textContent = text; else next.textContent = text;
    if (nextLine) nextLine.textContent = line;
    next.setAttribute("aria-label", text + (line ? " (" + line + ")" : ""));
  }
  function show(stage, opts) {
    opts = opts || {};
    if (ORDER.indexOf(stage) < 0) return;
    current = stage;
    if (stage !== "sessions") fromReview = false;
    stages.forEach(function (s) { s.hidden = s.dataset.stage !== stage; });
    document.querySelectorAll(".ws-step").forEach(function (a) {
      const on = a.dataset.stageLink === stage;
      a.classList.toggle("is-on", on);
      if (on) a.setAttribute("aria-current", "step"); else a.removeAttribute("aria-current");
    });
    if (layout) layout.dataset.stageNow = stage;
    if (stage === "review") refreshChecklist();
    setUrl(); updateBar();
    if (!opts.keepScroll && layout) {
      const top = layout.getBoundingClientRect().top + window.scrollY - 76;
      if (window.scrollY > top) window.scrollTo({ top: Math.max(0, top) });
    }
  }
  function showSessionExtras(key) {
    const changed = key !== session;
    session = key;
    // data-session-strict: shown for exactly the sessions listed ("all" is the whole-grid view); otherwise every
    // per-session part also shows in the whole-grid view.
    document.querySelectorAll("[data-session-only]").forEach(function (el) {
      const keys = el.dataset.sessionOnly.split(" ");
      el.hidden = el.hasAttribute("data-session-strict") ? keys.indexOf(key) < 0 : (key !== "all" && keys.indexOf(key) < 0);
    });
    document.querySelectorAll("[data-session-title]").forEach(function (el) { el.textContent = LABELS[key] || key; });
    const sel = document.getElementById("incident-session");
    if (sel && key !== "all") sel.value = ({ q: "qualifying", s: "sprint", r: "race" })[key];
    const nx = document.querySelector("[data-incident-next]");
    if (nx && key !== "all") nx.value = location.pathname + "?stage=sessions&session=" + key + "#" + INCIDENT_ANCHOR[key];
    // a saved session's classification folds away while the round is still being entered (Edit opens it)
    if (classSec && (changed || !classSec.dataset.seen)) {
      classSec.dataset.seen = "1";
      const done = (classSec.dataset.doneSessions || "").split(" ");
      classSec.open = key === "all" || done.indexOf(key) < 0;
    }
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
          // the first field the user can actually see (a single-session table hides the other sessions' columns)
          const field = el.matches("input, select, textarea") ? el : Array.prototype.find.call(
            el.querySelectorAll("input:not([type=hidden]):not([disabled]), select, textarea"), function (f) { return f.offsetParent !== null; });
          if (field) setTimeout(function () { field.focus(); }, 150);
        }
      }
    });
  }

  document.addEventListener("click", function (e) {
    const railSession = e.target.closest(".ws-rail [data-session]");
    if (railSession) { e.preventDefault(); fromReview = false; goTo("sessions", railSession.dataset.session); return; }
    const report = e.target.closest("[data-incident-session]");
    if (report && report.dataset.incidentSession) {
      const sel = document.getElementById("incident-session");
      if (sel) sel.value = report.dataset.incidentSession;
    }
    const link = e.target.closest("[data-stage-link]");
    if (link) { e.preventDefault(); goTo(link.dataset.stageLink); return; }
    const fix = e.target.closest("[data-fix-session]");
    if (fix) {
      e.preventDefault();
      const dlg = fix.closest("dialog"); if (dlg && dlg.open) dlg.close();
      fromReview = true;
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
    next.addEventListener("click", function (e) {
      e.preventDefault();
      if (fromReview && current === "sessions") { goTo("review"); return; }
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
    if (m.indexOf("race times") > -1) return m.indexOf("(sprint)") > -1 && m.indexOf("(grand prix)") < 0 ? ["s", "pace-sprint"] : ["r", "pace"];
    if (m.indexOf("ai difficulty") > -1) return ["r", "ai-difficulty"];
    if (m.indexOf("weekend notes") > -1) return ["r", "event-notes"];
    if (m.indexOf("sprint") > -1) return ["s", "entry-table"];
    if (m.indexOf("qualifying") > -1) return ["q", "entry-table"];
    return ["r", "entry-table"];
  }
  function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function fixButton(text, cls) {
    const w = where(text);
    return ' <a class="' + (cls || "btn btn-sm btn-ghost") + '" href="?stage=sessions&session=' + w[0] + "&from=review#" + w[1] + '" data-fix-session="' + w[0] + '" data-fix-anchor="' + w[1] + '">Fix<span class="sr-only">: ' + esc(text) + "</span></a>";
  }
  const CHECK = '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
  function head(n, kind, title) {
    const cls = n ? (kind === "block" ? "is-attention" : "is-warn") : "is-done";
    return '<h3 class="mini-head check-head is-' + kind + '"><span class="st-ico ' + cls + '" aria-hidden="true">' + (n ? "!" : CHECK) + "</span> " + title + " (" + n + ")</h3>";
  }
  // The Review checklist, in the same shape the server renders it. Fix opens the exact place and comes back here.
  function renderChecks(body, count, b, w) {
    const list = function (items, cls, btn) {
      return items.length ? '<ul class="check-list ' + cls + '">' + items.map(function (t) { return "<li><span>" + esc(t) + "</span>" + fixButton(t, btn) + "</li>"; }).join("") + "</ul>" : "";
    };
    body.innerHTML = head(b.length, "block", "Must fix") + (list(b, "is-block", "btn btn-sm") || '<p class="small check-none">Nothing blocking.</p>') +
      head(w.length, "warn", "Warnings") + (list(w, "is-warn") || '<p class="small check-none">None.</p>');
    if (count) {
      count.textContent = b.length + " to fix · " + w.length + " warning" + (w.length !== 1 ? "s" : "");
      count.classList.toggle("pill-hot", b.length > 0); count.classList.toggle("pill-ok", b.length === 0);
    }
    const submit = document.getElementById("mark-complete"); if (submit) submit.dataset.blocked = b.length ? "1" : "0";
    const note = document.getElementById("submit-warn-note"); if (note) note.hidden = !w.length || b.length > 0;
  }
  window.F1Workspace = { fixButton: fixButton, show: show, renderChecks: function (b, w) {
    if (box) renderChecks(box.querySelector("[data-check-body]"), box.querySelector("[data-check-count]"), b, w);
  } };
  const box = document.querySelector("[data-checklist]");
  function refreshChecklist() {
    if (!box || !table || !table.dataset.checklistUrl) return;
    flush().then(function () { return fetch(table.dataset.checklistUrl, { credentials: "same-origin" }); })
      .then(function (r) { return r.json(); })
      .then(function (check) {
        if (!check || !check.ok) return;
        const body = box.querySelector("[data-check-body]"), count = box.querySelector("[data-check-count]");
        const b = check.blocking || [], w = check.warnings || [];
        renderChecks(body, count, b, w);
      }).catch(function () { /* offline: the last checklist stays on screen */ });
  }

  // Live counts for the Classification heading, the rail and the overview as results are typed (the server's own
  // count replaces them on the next load).
  function recount() {
    if (!table || table.dataset.readonly === "1") return;
    const trs = table.querySelectorAll("tbody tr"), total = trs.length, n = { q: 0, s: 0, r: 0 };
    trs.forEach(function (tr) {
      const v = function (f) { const el = tr.querySelector('[data-field="' + f + '"]'); return el ? el.value.trim() : ""; };
      if (v("qualifying_position")) n.q++;
      if (v("sprint_position") || (v("sprint_status_override") && v("sprint_status_override") !== "Auto")) n.s++;
      if (v("race_position") || (v("status_override") && v("status_override") !== "Auto")) n.r++;
    });
    Object.keys(n).forEach(function (k) {
      const sum = document.querySelector('[data-class-sum="' + k + '"]');
      if (!sum) return;
      sum.textContent = n[k] >= total ? total + " of " + total + " entered" : n[k] ? n[k] + " of " + total + " entered" : "Not started";
      const rail = document.querySelector('.ws-rail .session-card[data-session="' + k + '"] .sc-state');
      if (rail) rail.textContent = n[k] >= total ? "Entered" : n[k] ? n[k] + "/" + total : "Not started";
      const ov = document.querySelector('[data-ov-session="' + k + '"]');
      if (ov) ov.textContent = n[k] >= total ? "All entered" : n[k] ? n[k] + "/" + total + " entered" : "Not started";
    });
  }
  if (table) { table.addEventListener("change", recount); table.addEventListener("input", function (e) { if (e.target.matches(".pos-input")) recount(); }); }

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
