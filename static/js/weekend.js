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
  const MAX = 22;

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
      tr.classList.toggle("row-out", ["DNF", "DNS", "DSQ"].indexOf(status) >= 0);
    });
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

  function setState(state, text) {
    stateEl.dataset.state = state;
    stateEl.textContent = text;
  }

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
    setState("saving", "Saving changes…");
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
      setState("saved", "All changes saved");
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

  recalc();
  if (readOnly) return;

  table.addEventListener("input", function (e) {
    if (e.target.matches("input")) { recalc(); schedule(); }
  });
  table.addEventListener("change", function (e) {
    if (e.target.matches("select, input[type=radio]")) { recalc(); schedule(); }
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
    save(true).then(function (ok) { if (ok) window.F1.toast("Weekend complete.", "success"); });
  });

  window.addEventListener("beforeunload", function (e) {
    if (dirty || saving) { e.preventDefault(); e.returnValue = ""; }
  });
})();
