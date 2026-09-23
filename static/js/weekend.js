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

  const ICONS = { saved: "✓ ", saving: "", dirty: "● ", error: "⚠ " };
  function setState(state, text) {
    if (!stateEl) return;
    stateEl.dataset.state = state;
    stateEl.textContent = (ICONS[state] || "") + text;
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

  let timer = null, saving = false, queued = false, dirty = false;

  function schedule() {
    if (readOnly) return;
    dirty = true;
    setState("dirty", "Unsaved changes");
    clearTimeout(timer);
    timer = setTimeout(function () { save(false); }, 850);
  }

  function save(markComplete) {
    clearTimeout(timer);
    if (recalc() > 0) {
      setState("error", "Fix highlighted positions to save");
      if (markComplete) window.F1.toast("Fix duplicate or invalid positions first.", "error");
      return Promise.resolve(false);
    }
    if (saving) { queued = true; return Promise.resolve(false); }
    saving = true;
    dirty = false;
    setState("saving", "Saving…");
    return window.F1.postJSON(table.dataset.url, payload(markComplete)).then(function (res) {
      saving = false;
      if (!res.ok) {
        dirty = true;
        setState("error", "Save failed");
        window.F1.toast(res.error || "Save failed", "error");
        return false;
      }
      statusEl.textContent = res.status;
      statusEl.className = "status-badge status-" + res.status.toLowerCase().replace(/ /g, "-");
      setState("saved", "Saved");
      if (res.market_opened) window.F1.toast("Silly season! The transfer market just opened for next year.", "success");
      if (queued) { queued = false; return save(false); }
      return true;
    }).catch(function () {
      saving = false;
      dirty = true;
      setState("error", "Save failed");
      return false;
    });
  }

  applyFilter();
  if (readOnly) return;  // read-only views are plain text: nothing to edit or save
  recalc();

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
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(false); return; }
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
  document.getElementById("no-track").addEventListener("click", function () { diffInput.value = ""; schedule(); });
  document.getElementById("clear-awards").addEventListener("click", function () {
    table.querySelectorAll('input[type=radio]').forEach(function (r) { r.checked = false; });
    schedule();
  });
  document.getElementById("mark-complete").addEventListener("click", function () {
    let gpLeft = 0, spLeft = 0;
    rows.forEach(function (tr) {
      const race = parsePos(tr.querySelector('[data-field="race_position"]').value);
      if (resolve(tr.querySelector('[data-field="status_override"]').value, race) === "Not Run") gpLeft++;
      if (isSprint) {
        const sp = parsePos(tr.querySelector('[data-field="sprint_position"]').value);
        if (resolve(tr.querySelector('[data-field="sprint_status_override"]').value, sp) === "Not Run") spLeft++;
      }
    });
    if (gpLeft || spLeft) {
      const parts = [];
      if (spLeft) parts.push(spLeft + " Sprint");
      if (gpLeft) parts.push(gpLeft + " GP");
      window.F1.toast(parts.join(" and ") + " result(s) still incomplete.", "error");
      return;
    }
    const master = table.dataset.master === "1";
    if (!master && !confirm("Submit these results? After submitting, only the Race Master can change them.")) return;
    save(true).then(function (ok) {
      if (!ok) return;
      window.F1.toast(master ? "Weekend complete." : "Results submitted.", "success");
      if (!master) { dirty = false; setTimeout(function () { window.location.reload(); }, 900); }
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

  // ---- Screenshot import: fill a column from the game's classification screen.
  const importForm = document.getElementById("import-form");
  if (importForm) {
    importForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const go = document.getElementById("import-go");
      go.disabled = true;
      go.textContent = "Reading screenshots…";
      const csrf = document.querySelector('meta[name="csrf-token"]').content;
      fetch(importForm.dataset.url, { method: "POST", body: new FormData(importForm), credentials: "same-origin",
        headers: { "X-CSRF-Token": csrf } })
        .then(function (r) { return r.json().catch(function () { return { ok: false, error: "Server error (" + r.status + ")" }; }); })
        .then(function (res) {
          go.disabled = false;
          go.textContent = "Read screenshots";
          if (!res.ok) { window.F1.toast(res.error || "Import failed", "error"); return; }
          applyImport(res);
          importForm.closest("dialog").close();
        })
        .catch(function () {
          go.disabled = false; go.textContent = "Read screenshots";
          window.F1.toast("Couldn't reach the server.", "error");
        });
    });
  }
  function applyImport(res) {
    const field = { qualifying: "qualifying_position", sprint: "sprint_position", race: "race_position" }[res.kind];
    const statusField = { sprint: "sprint_status_override", race: "status_override" }[res.kind];
    const byDriver = {};
    rows.forEach(function (tr) { byDriver[tr.dataset.driverId] = tr; });
    table.querySelectorAll('input[data-field="' + field + '"]').forEach(function (i) { i.value = ""; i.classList.remove("imported"); });
    res.rows.forEach(function (r) {
      const tr = byDriver[r.driver_id];
      if (!tr) return;
      const inp = tr.querySelector('[data-field="' + field + '"]');
      inp.value = r.position;
      inp.classList.add("imported");
      if (statusField) tr.querySelector('[data-field="' + statusField + '"]').value = r.status === "Finished" ? "Auto" : r.status;
    });
    if (res.kind === "race" && res.fastest_lap_driver_id && byDriver[res.fastest_lap_driver_id]) {
      byDriver[res.fastest_lap_driver_id].querySelector('[data-field="fastest_lap"]').checked = true;
    }
    recalc(); schedule();
    let msg = "Filled " + res.rows.length + " " + res.kind + " positions. Check the highlighted boxes.";
    if (rows.length - res.rows.length > 0) msg += " " + (rows.length - res.rows.length) + " driver(s) weren't found.";
    if (res.notes) msg += " Note: " + res.notes;
    window.F1.toast(msg, res.rows.length ? "success" : "error");
  }

  window.addEventListener("beforeunload", function (e) {
    if (dirty || saving) { e.preventDefault(); e.returnValue = ""; }
  });
})();
