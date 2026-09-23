(function () {
  "use strict";
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  function toast(message, kind) {
    const stack = document.getElementById("toasts");
    const el = document.createElement("div");
    el.className = "toast toast-" + (kind || "success");
    const span = document.createElement("span");
    span.textContent = message;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "✕";
    btn.setAttribute("data-dismiss", "");
    el.append(span, btn);
    stack.appendChild(el);
    autoDismiss(el);
  }
  function autoDismiss(el) { setTimeout(function () { el.remove(); }, 7000); }

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body),
      credentials: "same-origin"
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: "Server error (" + r.status + ")" }; });
    });
  }

  window.F1 = { toast: toast, postJSON: postJSON };

  document.querySelectorAll("#toasts .toast").forEach(autoDismiss);
  document.addEventListener("click", function (e) {
    const dismiss = e.target.closest("[data-dismiss]");
    if (dismiss) dismiss.closest(".toast").remove();
    const opener = e.target.closest("[data-dialog]");
    if (opener) {
      const dlg = document.getElementById(opener.dataset.dialog);
      if (dlg) dlg.showModal();
    }
    const closer = e.target.closest("[data-close]");
    if (closer) closer.closest("dialog").close();
    if (e.target.tagName === "DIALOG") e.target.close();  // backdrop click
  });

  const menu = document.getElementById("menu-btn");
  if (menu) menu.addEventListener("click", function () { document.getElementById("sidebar").classList.toggle("open"); });

  // Client-side sortable tables
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th[data-sort]").forEach(function (th, idx) {
      th.addEventListener("click", function () {
        const col = Array.prototype.indexOf.call(th.parentNode.children, th);
        const body = table.tBodies[0];
        const rows = Array.from(body.rows);
        const asc = th.dataset.dir !== "asc";
        table.querySelectorAll("th").forEach(function (h) { delete h.dataset.dir; });
        th.dataset.dir = asc ? "asc" : "desc";
        const val = function (row) {
          const cell = row.cells[col];
          const raw = (cell.dataset.value !== undefined ? cell.dataset.value : cell.textContent).trim();
          const num = parseFloat(raw.replace(/[^\d.\-]/g, ""));
          return raw === "" || raw === "—" ? null : (isNaN(num) || /[a-z]/i.test(raw.replace(/^P/, "")) ? raw.toLowerCase() : num);
        };
        rows.sort(function (a, b) {
          const x = val(a), y = val(b);
          if (x === null) return 1;
          if (y === null) return -1;
          if (x < y) return asc ? -1 : 1;
          if (x > y) return asc ? 1 : -1;
          return 0;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });

  // Driver search / team filter
  const search = document.getElementById("driver-search");
  const teamFilter = document.getElementById("team-filter");
  function filterDrivers() {
    const q = (search.value || "").toLowerCase();
    const t = teamFilter.value;
    document.querySelectorAll("#driver-table tbody tr").forEach(function (tr) {
      const ok = tr.dataset.name.indexOf(q) >= 0 && (!t || tr.dataset.team === t);
      tr.hidden = !ok;
    });
  }
  if (search && teamFilter) {
    search.addEventListener("input", filterDrivers);
    teamFilter.addEventListener("change", filterDrivers);
  }

  // Full grid editor health
  const gridForm = document.getElementById("grid-form");
  function gridHealth() {
    const selects = Array.from(gridForm.querySelectorAll("select"));
    const counts = {};
    let filled = 0;
    selects.forEach(function (s) { if (s.value) { filled++; counts[s.value] = (counts[s.value] || 0) + 1; } });
    let dups = 0;
    selects.forEach(function (s) {
      const dup = s.value && counts[s.value] > 1;
      s.classList.toggle("dup", !!dup);
      if (dup) dups++;
      const opt = s.options[s.selectedIndex];
      s.closest(".seat").classList.toggle("player-seat", !!(opt && opt.dataset.player));
    });
    const out = document.getElementById("grid-health");
    const vac = selects.length - filled;
    out.innerHTML = "<span><b>" + filled + "</b>/" + selects.length + " seats filled</span>" +
      "<span><b>" + vac + "</b> vacancies</span><span><b>" + dups + "</b> duplicate seats</span>" +
      '<span class="health ' + (vac || dups ? "bad" : "good") + '">' + (vac || dups ? "Grid needs attention" : "Grid healthy") + "</span>";
    gridForm.querySelector("button[type=submit]").disabled = !!(vac || dups);
  }
  if (gridForm) { gridForm.addEventListener("change", gridHealth); gridHealth(); }

  // Quick player placement preview
  const playerForm = document.getElementById("player-form");
  function playerPreview() {
    const selects = Array.from(playerForm.querySelectorAll("select"));
    const values = selects.map(function (s) { return s.value; }).filter(Boolean);
    const clash = values.length !== new Set(values).size;
    selects.forEach(function (s) {
      const opt = s.options[s.selectedIndex];
      const out = document.getElementById("preview-" + s.dataset.player);
      out.textContent = s.value ? (opt.dataset.occupant ? "Replaces " + opt.dataset.occupant : "Takes this seat") : "No race seat";
      s.classList.toggle("dup", clash && !!s.value && values.filter(function (v) { return v === s.value; }).length > 1);
    });
    playerForm.querySelector("button[type=submit]").disabled = clash;
    document.getElementById("player-clash").hidden = !clash;
  }
  if (playerForm) { playerForm.addEventListener("change", playerPreview); playerPreview(); }

  // Notifications bell: poll once a minute, optional chime, mark read when opened.
  const bell = document.getElementById("bell");
  if (bell) {
    const countEl = document.getElementById("bell-count");
    const list = document.getElementById("notif-list");
    const sound = document.getElementById("notif-sound");
    const baseTitle = document.title;
    let last = parseInt(countEl.textContent || "0", 10) || 0;
    let soundOn = false;
    try { soundOn = localStorage.getItem("f1-notif-sound") === "1"; } catch (e) { soundOn = false; }
    sound.checked = soundOn;
    sound.addEventListener("change", function () {
      soundOn = sound.checked;
      try { localStorage.setItem("f1-notif-sound", soundOn ? "1" : "0"); } catch (e) { /* private mode */ }
      if (soundOn) chime();
    });
    function chime() {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        [880, 1320].forEach(function (f, i) {
          const o = ctx.createOscillator(), g = ctx.createGain();
          o.frequency.value = f; o.type = "sine";
          g.gain.setValueAtTime(0.0001, ctx.currentTime + i * 0.15);
          g.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + i * 0.15 + 0.02);
          g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i * 0.15 + 0.3);
          o.connect(g); g.connect(ctx.destination);
          o.start(ctx.currentTime + i * 0.15); o.stop(ctx.currentTime + i * 0.15 + 0.32);
        });
      } catch (e) { /* audio blocked */ }
    }
    function setCount(n) {
      countEl.textContent = n;
      countEl.hidden = !n;
      document.title = (n ? "(" + n + ") " : "") + baseTitle;
    }
    function render(items) {
      list.innerHTML = "";
      if (!items.length) { list.innerHTML = '<li class="muted">Nothing yet.</li>'; return; }
      items.forEach(function (n) {
        const li = document.createElement("li");
        if (n.unread) li.className = "unread";
        const body = n.link ? document.createElement("a") : document.createElement("span");
        if (n.link) body.href = n.link;
        body.textContent = n.text;
        const when = document.createElement("small");
        when.textContent = n.created_at;
        li.append(body, when);
        list.appendChild(li);
      });
    }
    function poll() {
      fetch(bell.dataset.url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (res) {
        if (!res.ok) return;
        if (res.unread > last && soundOn) chime();
        if (res.unread > last) toast(res.items[0] ? res.items[0].text : "New notification", "success");
        last = res.unread;
        setCount(res.unread);
        render(res.items);
      }).catch(function () { /* offline: try again next minute */ });
    }
    setCount(last);
    setInterval(poll, 60000);
    bell.addEventListener("click", function () {
      if (!last) return;
      postJSON(bell.dataset.read, {}).then(function () { last = 0; setCount(0); });
    });
  }
})();
