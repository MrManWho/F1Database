(function () {
  "use strict";
  const table = document.getElementById("entry-table");
  if (!table) return;
  const readOnly = table.dataset.readonly === "1";
  const isSprint = table.dataset.sprint === "1";
  const GP = JSON.parse(table.dataset.gp);
  const SP = JSON.parse(table.dataset.sprintPoints);
  const stateEl = document.getElementById("save-state");
  const statusEl = document.getElementById("event-status");
  const diffInput = document.getElementById("ai-difficulty");
  const notesEl = document.getElementById("event-notes");
  const rows = Array.from(table.querySelectorAll("tbody tr"));
  const MAX = parseInt(table.dataset.max || "22", 10);
  let untracked = table.dataset.untracked === "1";  // "Don't track this round" pressed

  function parsePos(v) {
    v = (v || "").trim();
    if (!v) return null;
    if (!/^\d+$/.test(v)) return NaN;
    const n = parseInt(v, 10);
    return n >= 1 && n <= MAX ? n : NaN;
  }
  function resolve(override, pos) {
    if (override && override !== "Auto") return override;
    return pos ? "Finished" : "Not Run";
  }

  function recalc() {
    let problems = 0;
    ["qualifying_position", "sprint_position", "race_position"].forEach(function (field) {
      const seen = {};
      table.querySelectorAll('input[data-field="' + field + '"]').forEach(function (inp) {
        const p = parsePos(inp.value);
        inp.classList.remove("dup", "bad");
        if (Number.isNaN(p)) { inp.classList.add("bad"); problems++; return; }
        if (p) (seen[p] = seen[p] || []).push(inp);
      });
      Object.values(seen).forEach(function (list) {
        if (list.length > 1) { list.forEach(function (i) { i.classList.add("dup"); }); problems++; }
      });
    });
    rows.forEach(function (tr) {
      const race = parsePos(tr.querySelector('[data-field="race_position"]').value);
      const status = resolve(tr.querySelector('[data-field="status_override"]').value, race);
      const gp = status === "Finished" && race ? (GP[race] || 0) : 0;
      let sp = 0;
      if (isSprint) {
        const spos = parsePos(tr.querySelector('[data-field="sprint_position"]').value);
        const sstatus = resolve(tr.querySelector('[data-field="sprint_status_override"]').value, spos);
        sp = sstatus === "Finished" && spos ? (SP[spos] || 0) : 0;
        tr.querySelector(".sp-pts").textContent = sp;
      }
      tr.querySelector(".gp-pts").textContent = gp;
      tr.querySelector(".tot-pts").innerHTML = "<strong>" + (gp + sp) + "</strong>";
      const out = ["DNF", "DNS", "DSQ"].indexOf(status) >= 0;
      tr.classList.toggle("row-out", out);
      tr.dataset.points = gp + sp;
      tr.dataset.out = out ? "1" : "0";
      tr.dataset.complete = status !== "Not Run" ? "1" : "0";
    });
    applyFilter();
    return problems;
  }

  function payload(markComplete) {
    return {
      mark_complete: !!markComplete,
      ai_difficulty: diffInput.value === "" ? null : diffInput.value,
      ai_untracked: diffInput.value === "" && untracked,
      event_notes: notesEl.value,
      results: rows.map(function (tr) {
        const get = function (f) { const el = tr.querySelector('[data-field="' + f + '"]'); return el ? el : null; };
        return {
          driver_id: parseInt(tr.dataset.driverId, 10),
          qualifying_position: get("qualifying_position").value.trim(),
          sprint_position: isSprint ? get("sprint_position").value.trim() : null,
          sprint_status_override: isSprint ? get("sprint_status_override").value : "Auto",
          race_position: get("race_position").value.trim(),
          status_override: get("status_override").value,
          fastest_lap: get("fastest_lap").checked,
          driver_of_day: get("driver_of_day").checked,
          notes: get("notes").value
        };
      })
    };
  }

  const ICONS = { saved: "✓ ", saving: "", dirty: "● ", error: "⚠ ", offline: "⟳ " };
  function setState(state, text, retry) {
    if (!stateEl) return;
    stateEl.dataset.state = state;
    stateEl.textContent = (ICONS[state] || "") + text;
    if (retry) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "btn btn-sm btn-ghost save-retry"; b.textContent = "Retry";
      b.addEventListener("click", function () { save(false); });
      stateEl.appendChild(document.createTextNode(" "));
      stateEl.appendChild(b);
    }
  }

  // ---- Filters (everyone): all, player drivers, incomplete, points scorers, DNF/DNS/DSQ.
  let filter = "all";
  const emptyNote = document.querySelector(".filter-empty");
  function applyFilter() {
    let shown = 0;
    rows.forEach(function (tr) {
      const d = tr.dataset;
      const keep = filter === "all" || (filter === "player" && d.player === "1") ||
        (filter === "incomplete" && d.complete === "0") || (filter === "points" && parseInt(d.points || "0", 10) > 0) ||
        (filter === "out" && d.out === "1");
      tr.hidden = !keep;
      if (keep) shown++;
    });
    if (emptyNote) emptyNote.hidden = shown > 0;
  }
  document.querySelectorAll("[data-filter]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      filter = chip.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach(function (c) {
        c.classList.toggle("is-on", c === chip); c.setAttribute("aria-pressed", c === chip ? "true" : "false");
      });
      applyFilter();
    });
  });

  // ---- Saving, offline queue and recovery ------------------------------------------------------------
  // Every edit is kept in this browser (scoped to account, league, season and round) until the server has it.
  // Each save carries the round's revision; if someone else saved in between, the server refuses and we merge.
  let timer = null, saving = false, queued = false, dirty = false, retryTimer = null, locked = false;
  let revision = parseInt(table.dataset.revision || "0", 10);
  let lastError = null;
  const RKEY = "f1-recovery:" + (table.dataset.scope || location.pathname);
  function store(key, value) { try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ } }
  function load(key) { try { return JSON.parse(localStorage.getItem(key) || "null"); } catch (e) { return null; } }

  // A completed round (Race Master only reaches this) isn't autosaved: corrections wait for "Save corrections".
  const correcting = table.dataset.complete === "1" && table.dataset.master === "1";
  function schedule() {
    if (readOnly || locked) return;
    dirty = true;
    remember();
    if (correcting) {
      setState("dirty", "Unsaved corrections");
      const b = document.getElementById("save-corrections");
      if (b) { b.disabled = false; b.textContent = "Save corrections"; }
      return;
    }
    setState("dirty", "Unsaved changes");
    clearTimeout(timer);
    timer = setTimeout(function () { save(false); }, 850);
  }
  function remember() {
    // What the server last confirmed (base) stays fixed until a save succeeds, so conflicts can be detected later.
    const rec = load(RKEY) || { base: baseline, revision: revision };
    rec.payload = payload(false);
    rec.savedAt = new Date().toISOString();
    store(RKEY, rec);
  }
  function forget() { store(RKEY, null); }

  function waitForConnection() {
    setState("offline", "Offline — changes stored on this device");
    clearTimeout(retryTimer);
    retryTimer = setTimeout(function () { if (dirty && !correcting) save(false); }, 15000);
  }
  window.addEventListener("online", function () { if (dirty && !locked && !correcting) save(false); });
  window.addEventListener("offline", function () { if (dirty) waitForConnection(); });

  function send(body) {
    return fetch(table.dataset.url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": (document.querySelector('meta[name="csrf-token"]') || {}).content || "" },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: "Server error (" + r.status + ")" }; })
        .then(function (res) { res.httpStatus = r.status; return res; });
    });
  }

  function lockOut(message) {
    locked = true; dirty = false;
    clearTimeout(timer); clearTimeout(retryTimer);
    setState("error", "Locked");
    table.querySelectorAll("input, select, textarea, button").forEach(function (el) { el.disabled = true; });
    showBanner("🔒 " + (message || "This round has been submitted.") + " Your unsent changes weren't applied. " +
      "Contact the Race Master if something needs fixing.", true);
  }

  function save(markComplete) {
    clearTimeout(timer);
    if (locked) return Promise.resolve(false);
    if (recalc() > 0) {
      setState("error", "Fix highlighted positions to save");
      lastError = "Some positions are invalid or duplicated.";
      return Promise.resolve(false);
    }
    if (saving) { queued = true; return Promise.resolve(false); }
    if (navigator.onLine === false) { dirty = true; waitForConnection(); return Promise.resolve(false); }
    saving = true;
    const sent = payload(markComplete);
    sent.base_revision = revision;
    const editsAtSend = JSON.stringify(payload(false));
    setState("saving", "Saving…");
    return send(sent).then(function (res) {
      saving = false;
      if (res.httpStatus === 409 && res.conflict) { resolveConflict(res.server); return false; }
      if (res.httpStatus === 403 && res.locked) { lockOut(res.error); return false; }
      if (res.httpStatus === 422 && res.blocked) { revision = res.revision || revision; renderChecklist(res.checklist); return false; }
      if (!res.ok) {
        dirty = true;
        lastError = res.error || "Save failed";
        setState("error", "Couldn't save — " + lastError, true);
        window.F1.toast(lastError, "error");
        return false;
      }
      lastError = null;
      revision = res.revision;
      baseline = JSON.parse(editsAtSend);
      if (JSON.stringify(payload(false)) === editsAtSend) { dirty = false; forget(); }
      else { const rec = load(RKEY) || {}; rec.base = baseline; rec.revision = revision; store(RKEY, rec); }
      statusEl.textContent = res.status;
      statusEl.className = "status-badge status-" + res.status.toLowerCase().replace(/ /g, "-");
      setState("saved", "Saved");
      if (res.market_opened) window.F1.toast("Silly season! The transfer market just opened for next year.", "success");
      if (queued || dirty) { queued = false; return save(false).then(function () { return true; }); }
      return res;
    }).catch(function () {
      saving = false;
      dirty = true;
      remember();
      waitForConnection();
      return false;
    });
  }

  // ---- Conflicts: compare what we started from (base), what's on screen (mine) and what's saved (server).
  const FIELDS = ["qualifying_position", "sprint_position", "sprint_status_override", "race_position", "status_override", "notes"];
  const LABELS = { qualifying_position: "Qualifying", sprint_position: "Sprint position", sprint_status_override: "Sprint status",
    race_position: "Race position", status_override: "Race status", notes: "Notes", fastest_lap: "Fastest Lap",
    driver_of_day: "Driver of the Day", ai_difficulty: "AI difficulty", event_notes: "Weekend notes" };
  function norm(v) { return v === null || v === undefined || v === false ? "" : v === true ? "1" : String(v); }
  function flat(p) {
    // One flat map of every value, with Fastest Lap / Driver of the Day as a single driver id each.
    const out = { ai_difficulty: norm(p.ai_difficulty), event_notes: norm(p.event_notes), fastest_lap: "", driver_of_day: "" };
    const results = Array.isArray(p.results) ? p.results : Object.keys(p.results || {}).map(function (id) {
      return Object.assign({ driver_id: id }, p.results[id]);
    });
    results.forEach(function (r) {
      FIELDS.forEach(function (f) {
        let v = norm(r[f]);
        if ((f === "status_override" || f === "sprint_status_override") && v === "") v = "Auto";
        out[r.driver_id + ":" + f] = v;
      });
      if (r.fastest_lap) out.fastest_lap = String(r.driver_id);
      if (r.driver_of_day) out.driver_of_day = String(r.driver_id);
    });
    return out;
  }
  function driverName(id) {
    const tr = table.querySelector('tbody tr[data-driver-id="' + id + '"]');
    return tr ? tr.querySelector(".driver-cell strong").textContent : "Driver " + id;
  }
  function describe(key, value) {
    if (key === "fastest_lap" || key === "driver_of_day") return value ? driverName(value) : "nobody";
    if (/_position$/.test(key)) return value ? "P" + value : "blank";
    return value === "" ? "blank" : value;
  }
  function writeValues(values) {
    Object.keys(values).forEach(function (key) {
      const v = values[key];
      if (key === "ai_difficulty") { diffInput.value = v; return; }
      if (key === "event_notes") { notesEl.value = v; return; }
      if (key === "fastest_lap" || key === "driver_of_day") {
        table.querySelectorAll('input[data-field="' + key + '"]').forEach(function (r) { r.checked = r.closest("tr").dataset.driverId === v; });
        return;
      }
      const parts = key.split(":");
      const tr = table.querySelector('tbody tr[data-driver-id="' + parts[0] + '"]');
      const el = tr && tr.querySelector('[data-field="' + parts[1] + '"]');
      if (el) el.value = v;
    });
  }
  function resolveConflict(server) {
    const b = flat(baseline), mine = flat(payload(false)), theirs = flat(server);
    const merged = {}, conflicts = [];
    Object.keys(theirs).forEach(function (key) {
      if (!(key in mine)) return;
      const bv = key in b ? b[key] : "", mv = mine[key], sv = theirs[key];
      if (mv === bv) merged[key] = sv;                // I didn't touch it: take the server's value
      else if (sv === bv || sv === mv) merged[key] = mv;  // only I changed it (or we agree)
      else conflicts.push({ key: key, mine: mv, server: sv });
    });
    revision = server.revision;
    baseline = serverPayload(server);
    if (server.status === "Complete" && table.dataset.master !== "1") { lockOut("This round was submitted while your edits were waiting."); return; }
    writeValues(merged);
    recalc();
    if (!conflicts.length) {
      window.F1.toast("Merged with newer changes from the server.", "success");
      dirty = true; remember(); save(false);
      return;
    }
    setState("error", "Conflict detected — choose which values to keep");
    const list = document.getElementById("conflict-list");
    list.innerHTML = "";
    conflicts.forEach(function (c, i) {
      const parts = c.key.split(":");
      const what = parts.length > 1 ? driverName(parts[0]) + " · " + LABELS[parts[1]] : LABELS[c.key];
      const row = document.createElement("fieldset");
      row.className = "conflict-row";
      row.innerHTML = "<legend></legend>" +
        '<label class="check"><input type="radio" name="c' + i + '" value="mine"> <span>Mine: <b></b></span></label>' +
        '<label class="check"><input type="radio" name="c' + i + '" value="server"> <span>Server: <b></b></span></label>';
      row.querySelector("legend").textContent = what;
      const bs = row.querySelectorAll("b");
      bs[0].textContent = describe(parts[1] || c.key, c.mine);
      bs[1].textContent = describe(parts[1] || c.key, c.server);
      row.dataset.key = c.key; row.dataset.mine = c.mine; row.dataset.server = c.server;
      list.appendChild(row);
    });
    const dlg = document.getElementById("conflict-dialog");
    const apply = document.getElementById("conflict-apply");
    const check = function () { apply.disabled = list.querySelectorAll("input:checked").length < conflicts.length; };
    list.onchange = check;
    document.getElementById("conflict-all-mine").onclick = function () { list.querySelectorAll('input[value="mine"]').forEach(function (r) { r.checked = true; }); check(); };
    document.getElementById("conflict-all-server").onclick = function () { list.querySelectorAll('input[value="server"]').forEach(function (r) { r.checked = true; }); check(); };
    apply.onclick = function () {
      const chosen = {};
      list.querySelectorAll(".conflict-row").forEach(function (row) {
        const pick = row.querySelector("input:checked").value;
        chosen[row.dataset.key] = pick === "mine" ? row.dataset.mine : row.dataset.server;
      });
      writeValues(chosen);
      recalc();
      dlg.close();
      dirty = true; remember(); save(false);
    };
    check();
    if (dlg.showModal) dlg.showModal();
  }
  function serverPayload(server) {
    return { ai_difficulty: server.ai_difficulty, event_notes: server.event_notes,
      results: Object.keys(server.results).map(function (id) { return Object.assign({ driver_id: parseInt(id, 10) }, server.results[id]); }) };
  }

  function showBanner(html, isError) {
    const bn = document.getElementById("recovery-banner");
    if (!bn) return;
    bn.hidden = false;
    bn.classList.toggle("banner-warn", !!isError);
    bn.setAttribute("role", isError ? "alert" : "status");
    bn.textContent = "";
    const span = document.createElement("span");
    span.textContent = html;
    bn.appendChild(span);
    if (isError && load(RKEY)) {
      const discard = document.createElement("button");
      discard.type = "button"; discard.className = "btn btn-sm btn-ghost"; discard.textContent = "Discard my unsent changes";
      discard.addEventListener("click", function () { forget(); location.reload(); });
      bn.appendChild(document.createTextNode(" "));
      bn.appendChild(discard);
    }
  }

  applyFilter();
  if (readOnly) return;  // read-only views are plain text: nothing to edit or save
  recalc();
  let baseline = payload(false);  // what the server had when this page loaded
  restore();

  // ---- Coming back to an interrupted entry: put the unsent edits back, then sync (or explain why not).
  function restore() {
    const rec = load(RKEY);
    if (!rec || !rec.payload) return;
    if (JSON.stringify(rec.payload) === JSON.stringify(baseline)) { forget(); return; }
    fetch(table.dataset.stateUrl, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (state) {
      if (!state.ok) return;
      if (state.locked) { lockOut("This round was submitted after you last edited it."); return; }
      writeValues(flat(rec.payload));
      recalc();
      baseline = rec.base || baseline;
      revision = typeof rec.revision === "number" ? rec.revision : revision;
      const when = rec.savedAt ? new Date(rec.savedAt).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "earlier";
      showBanner("↺ Restored unsaved changes from " + when + "." + (correcting ? " Review them, then press Save corrections." : " Saving them now."), false);
      dirty = true;
      if (correcting) schedule(); else save(false);
    }).catch(function () {
      writeValues(flat(rec.payload)); recalc();
      baseline = rec.base || baseline;
      revision = typeof rec.revision === "number" ? rec.revision : revision;
      dirty = true;
      showBanner("↺ Restored unsaved changes. You're offline; they're stored on this device and will save when the connection returns.", false);
      waitForConnection();
    });
  }

  function markEdited(el) {
    const tr = el.closest("tbody tr");
    if (!tr) return;
    rows.forEach(function (r) { r.classList.remove("last-edited"); });
    tr.classList.add("last-edited");
  }
  table.addEventListener("input", function (e) {
    if (e.target.matches("input")) { markEdited(e.target); recalc(); schedule(); }
  });
  table.addEventListener("change", function (e) {
    if (e.target.matches("select, input[type=radio]")) { markEdited(e.target); recalc(); schedule(); }
  });

  // ---- Clear one driver, or a whole session, after confirming.
  table.addEventListener("click", function (e) {
    const btn = e.target.closest(".clear-row");
    if (!btn) return;
    const tr = btn.closest("tr");
    const name = tr.querySelector(".driver-cell strong").textContent;
    if (!confirm("Clear every result for " + name + " this weekend?")) return;
    tr.querySelectorAll(".pos-input, .note-input").forEach(function (i) { i.value = ""; });
    tr.querySelectorAll("select").forEach(function (sel) { sel.value = "Auto"; });
    tr.querySelectorAll("input[type=radio]").forEach(function (r) { r.checked = false; });
    markEdited(tr); recalc(); schedule();
  });
  const clearSession = document.getElementById("clear-session");
  if (clearSession) clearSession.addEventListener("change", function () {
    const field = clearSession.value;
    clearSession.value = "";
    if (!field) return;
    const label = { qualifying_position: "qualifying", sprint_position: "Sprint", race_position: "Grand Prix" }[field];
    if (!confirm("Clear every " + label + " position and status this weekend?")) return;
    table.querySelectorAll('input[data-field="' + field + '"]').forEach(function (i) { i.value = ""; });
    const statusField = { sprint_position: "sprint_status_override", race_position: "status_override" }[field];
    if (statusField) table.querySelectorAll('select[data-field="' + statusField + '"]').forEach(function (s) { s.value = "Auto"; });
    recalc(); schedule();
  });

  // ---- Keyboard: Ctrl/Cmd+S saves now, Esc leaves quick order, ? shows the shortcuts.
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      if (correcting) { if (dirty && corrDlg && corrDlg.showModal) corrDlg.showModal(); } else save(false);
      return;
    }
    if (e.key === "Escape" && typeof stopTap === "function") { stopTap(); return; }
    const typing = e.target.matches && e.target.matches("input, textarea, select");
    if (e.key === "?" && !typing) {
      const dlg = document.getElementById("keys-dialog");
      if (dlg && dlg.showModal) dlg.showModal();
    }
  });
  [diffInput, notesEl].forEach(function (el) { el.addEventListener("input", schedule); });

  table.addEventListener("keydown", function (e) {
    const inp = e.target;
    if (!inp.classList.contains("pos-input")) return;
    if (["ArrowDown", "Enter", "ArrowUp"].indexOf(e.key) < 0) return;
    e.preventDefault();
    const field = inp.dataset.field;
    const i = rows.indexOf(inp.closest("tr"));
    const j = e.key === "ArrowUp" ? i - 1 : i + 1;
    if (j < 0 || j >= rows.length) return;
    const next = rows[j].querySelector('[data-field="' + field + '"]');
    next.focus();
    next.select();
  });

  const useRec = document.getElementById("use-rec");
  if (useRec) useRec.addEventListener("click", function () { diffInput.value = useRec.dataset.value; schedule(); });
  function showUntracked() {
    const note = document.getElementById("untracked-note");
    if (note) note.hidden = !untracked;
    document.getElementById("no-track").setAttribute("aria-pressed", untracked ? "true" : "false");
  }
  document.getElementById("no-track").addEventListener("click", function () { diffInput.value = ""; untracked = true; showUntracked(); schedule(); });
  diffInput.addEventListener("input", function () { if (diffInput.value !== "") { untracked = false; showUntracked(); } });
  document.getElementById("clear-awards").addEventListener("click", function () {
    table.querySelectorAll('input[type=radio]').forEach(function (r) { r.checked = false; });
    schedule();
  });
  // ---- Review and submit: the server checks the saved results; nothing is submitted with a blocking error.
  const submitBtn = document.getElementById("mark-complete");
  const submitDlg = document.getElementById("submit-dialog");
  const submitBody = document.getElementById("submit-body");
  const submitGo = document.getElementById("submit-go");
  const confirmBox = document.getElementById("confirm-submit");
  const acceptBox = document.getElementById("accept-warnings");
  const acceptRow = document.getElementById("accept-warnings-row");
  let lastCheck = null;
  function esc(t) { const d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }
  function renderChecklist(check, clientBlocking) {
    lastCheck = check;
    const blocking = (clientBlocking || []).concat(check.blocking || []);
    const warnings = check.warnings || [];
    const s = check.summary || {};
    const out = s.out || {};
    const list = function (items) { return items && items.length ? items.map(esc).join(", ") : "—"; };
    let html = '<dl class="submit-summary">' +
      "<div><dt>Round</dt><dd>R" + esc(s.round) + " " + esc(s.event) + " · " + (s.sprint ? "Sprint weekend" : "Standard weekend") + "</dd></div>" +
      "<div><dt>Pole</dt><dd>" + esc(s.pole || "—") + "</dd></div>" +
      (s.sprint ? "<div><dt>Sprint winner</dt><dd>" + esc(s.sprint_winner || "—") + "</dd></div>" : "") +
      "<div><dt>Grand Prix winner</dt><dd>" + esc(s.winner || "—") + "</dd></div>" +
      "<div><dt>Podium</dt><dd>" + list(s.podium) + "</dd></div>" +
      "<div><dt>DNF / DNS / DSQ</dt><dd>" + list(out.DNF) + " / " + list(out.DNS) + " / " + list(out.DSQ) + "</dd></div>" +
      "<div><dt>Fastest Lap</dt><dd>" + esc(s.fastest_lap || "—") + "</dd></div>" +
      "<div><dt>Driver of the Day</dt><dd>" + esc(s.dotd || "—") + "</dd></div>" +
      "<div><dt>AI difficulty</dt><dd>" + (s.ai_difficulty == null ? "Not tracked" : esc(s.ai_difficulty)) + "</dd></div></dl>";
    if (s.players && s.players.length) {
      html += '<h3 class="mini-head">Player results</h3><ul class="plain-list small">' + s.players.map(function (p) {
        return "<li><b>" + esc(p.name) + "</b>: Q " + (p.quali ? "P" + esc(p.quali) : "—") + (p.sprint ? " · Sprint " + esc(p.sprint) : "") +
          " · Race " + esc(p.race) + " · " + esc(p.points) + " pts</li>";
      }).join("") + "</ul>";
    }
    if (check.player_issues && check.player_issues.length) {
      html += '<div class="check-players" role="alert"><h3 class="mini-head">👤 Player drivers with missing results</h3><ul>' +
        check.player_issues.map(function (p) {
          return '<li><span class="p-dot" style="background:' + esc(p.color || "#4aa3ff") + '"></span><b>' + esc(p.name) + "</b>: " + p.missing.map(esc).join(", ") + "</li>";
        }).join("") + "</ul></div>";
    }
    html += '<div class="check-block" role="alert"><h3 class="mini-head">⛔ Blocking errors (' + blocking.length + ")</h3>" +
      (blocking.length ? "<ul>" + blocking.map(function (b) { return "<li>" + esc(b) + "</li>"; }).join("") + "</ul>" : '<p class="small">None. ✓</p>') + "</div>";
    html += '<div class="check-warn"><h3 class="mini-head">⚠️ Warnings (' + warnings.length + ")</h3>" +
      (warnings.length ? "<ul>" + warnings.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("") + "</ul>" : '<p class="small">None. ✓</p>') + "</div>";
    if (check.lock_notice) html += '<p class="lock-notice small"><span aria-hidden="true">🔒</span> ' + esc(check.lock_notice) + "</p>";
    submitBody.innerHTML = html;
    acceptRow.hidden = !warnings.length;
    acceptBox.checked = false; confirmBox.checked = false;
    submitGo.dataset.blocked = blocking.length ? "1" : "0";
    updateGo();
    if (submitDlg && !submitDlg.open && submitDlg.showModal) submitDlg.showModal();
  }
  function updateGo() {
    submitGo.disabled = submitGo.dataset.blocked === "1" || !confirmBox.checked || (!acceptRow.hidden && !acceptBox.checked);
  }
  if (confirmBox) { confirmBox.addEventListener("change", updateGo); acceptBox.addEventListener("change", updateGo); }
  if (submitBtn) submitBtn.addEventListener("click", function () {
    submitBody.innerHTML = '<p class="muted">Saving and checking the results…</p>';
    if (submitDlg.showModal && !submitDlg.open) submitDlg.showModal();
    // Wait for any save in flight, then push the latest edits, so the check runs on what's really on the server.
    const idle = function () { return new Promise(function (done) {
      let n = 0; (function wait() { if (!saving || n++ > 40) done(); else setTimeout(wait, 250); })();
    }); };
    const flush = idle().then(function () { return dirty ? save(false).then(idle) : true; });
    flush.then(function () {
      const pending = [];
      if (locked) pending.push("This round is locked. Only the Race Master can change it.");
      if (dirty || saving) pending.push(navigator.onLine === false ? "You're offline: some edits haven't reached the server yet." : "Some edits haven't saved yet.");
      if (lastError) pending.push("Last save failed: " + lastError);
      if (recalc() > 0) pending.push("Some positions are invalid or duplicated (highlighted in the table).");
      return fetch(table.dataset.checklistUrl, { credentials: "same-origin" }).then(function (r) { return r.json(); })
        .then(function (check) {
          if (!check.ok) { submitBody.innerHTML = '<p class="form-error" role="alert">' + esc(check.error || "Couldn't check the results.") + "</p>"; return; }
          renderChecklist(check, pending);
        });
    }).catch(function () {
      submitBody.innerHTML = '<p class="form-error" role="alert">You appear to be offline. Results can be submitted once your edits have reached the server.</p>';
    });
  });
  const corrBtn = document.getElementById("save-corrections");
  const corrDlg = document.getElementById("corrections-dialog");
  if (corrBtn) corrBtn.addEventListener("click", function () { if (corrDlg.showModal) corrDlg.showModal(); });
  const corrGo = document.getElementById("corrections-go");
  if (corrGo) corrGo.addEventListener("click", function () {
    corrGo.disabled = true;
    save(false).then(function (res) {
      corrGo.disabled = false;
      corrDlg.close();
      if (!res) return;
      corrBtn.disabled = true; corrBtn.textContent = "✓ Weekend complete";
      window.F1.toast("Corrections saved. Standings and ratings have been recalculated.", "success");
    });
  });
  if (submitGo) submitGo.addEventListener("click", function () {
    submitGo.disabled = true;
    save(true).then(function (res) {
      if (!res) { updateGo(); return; }
      forget();
      submitDlg.close();
      window.F1.toast("Results submitted. Standings and records have been recalculated.", "success");
      setTimeout(function () { window.location.href = (res.summary_url || table.dataset.summaryUrl) + "?submitted=1"; }, 700);
    });
  });

  // ---- Quick order (tap mode): tap drivers in finishing order to number a column.
  const banner = document.getElementById("tap-banner");
  const labels = { qualifying_position: "qualifying", sprint_position: "Sprint", race_position: "race" };
  let tapField = null, tapStack = [];
  function nextFree(field) {
    const used = {};
    table.querySelectorAll('input[data-field="' + field + '"]').forEach(function (i) {
      const p = parsePos(i.value); if (p) used[p] = true;
    });
    for (let n = 1; n <= MAX; n++) if (!used[n]) return n;
    return null;
  }
  function refreshTap() {
    if (!tapField) return;
    const n = nextFree(tapField);
    document.getElementById("tap-next").textContent = n ? "P" + n : "all placed";
    rows.forEach(function (tr) {
      const inp = tr.querySelector('[data-field="' + tapField + '"]');
      tr.classList.toggle("tap-placed", !!inp.value);
    });
  }
  function stopTap() {
    tapField = null; tapStack = [];
    banner.hidden = true;
    table.classList.remove("tap-mode");
    rows.forEach(function (tr) { tr.classList.remove("tap-placed"); });
    document.querySelectorAll("[data-tap]").forEach(function (b) { b.classList.remove("btn-primary"); });
  }
  document.querySelectorAll("[data-tap]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (tapField === btn.dataset.tap) { stopTap(); return; }
      stopTap();
      tapField = btn.dataset.tap;
      btn.classList.add("btn-primary");
      document.getElementById("tap-field").textContent = labels[tapField];
      banner.hidden = false;
      table.classList.add("tap-mode");
      refreshTap();
    });
  });
  table.addEventListener("click", function (e) {
    if (!tapField || e.target.closest("input, select, button")) return;
    const tr = e.target.closest("tbody tr");
    if (!tr) return;
    const inp = tr.querySelector('[data-field="' + tapField + '"]');
    if (inp.value) return;
    const n = nextFree(tapField);
    if (!n) return;
    inp.value = n;
    tapStack.push(inp);
    recalc(); schedule(); refreshTap();
  });
  if (banner) {
    document.getElementById("tap-undo").addEventListener("click", function () {
      const inp = tapStack.pop();
      if (inp) { inp.value = ""; recalc(); schedule(); refreshTap(); }
    });
    document.getElementById("tap-clear").addEventListener("click", function () {
      if (!confirm("Clear every " + labels[tapField] + " position?")) return;
      table.querySelectorAll('input[data-field="' + tapField + '"]').forEach(function (i) { i.value = ""; });
      tapStack = []; recalc(); schedule(); refreshTap();
    });
    document.getElementById("tap-done").addEventListener("click", stopTap);
  }

  // ---- Screenshot import (static/js/importer.js) hands its reviewed rows to the form here. Nothing is saved
  //      until the normal save happens, and a completed round still needs "Save corrections".
  const SESSION_FIELDS = { qualifying: ["qualifying_position", null], sprint: ["sprint_position", "sprint_status_override"],
                           race: ["race_position", "status_override"] };
  window.F1Entry = {
    existing: function (session) {
      const f = SESSION_FIELDS[session];
      const out = {};
      if (!f) return out;
      rows.forEach(function (tr) {
        const pos = parsePos(tr.querySelector('[data-field="' + f[0] + '"]').value);
        const sel = f[1] ? tr.querySelector('[data-field="' + f[1] + '"]') : null;
        const status = sel ? resolve(sel.value, pos) : (pos ? "Finished" : "Not Run");
        if (pos || status !== "Not Run") out[tr.dataset.driverId] = { position: pos || null, status: status };
      });
      return out;
    },
    applyImport: function (session, imported) {
      const f = SESSION_FIELDS[session];
      if (!f || readOnly || locked) return 0;
      const byDriver = {};
      rows.forEach(function (tr) { byDriver[tr.dataset.driverId] = tr; });
      let n = 0;
      imported.forEach(function (r) {
        const tr = byDriver[r.driver_id];
        if (!tr) return;
        const inp = tr.querySelector('[data-field="' + f[0] + '"]');
        inp.value = r.position ? r.position : "";
        inp.classList.add("imported");
        if (f[1]) tr.querySelector('[data-field="' + f[1] + '"]').value = r.status && r.status !== "Finished" ? r.status : "Auto";
        markEdited(inp);
        n++;
      });
      recalc(); schedule();
      return n;
    }
  };

  window.addEventListener("beforeunload", function (e) {
    if ((dirty || saving) && !locked) { remember(); e.preventDefault(); e.returnValue = ""; }
  });
})();
