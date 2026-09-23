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

  const rail = document.getElementById("rail-toggle");
  if (rail) rail.addEventListener("click", function () {
    const on = document.body.classList.toggle("rail");
    try { localStorage.setItem("f1-rail", on ? "1" : "0"); } catch (e) { /* private mode */ }
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

/* Join-role pickers: the driver name only matters for roles that drive. */
(function () {
  document.querySelectorAll("select[data-join-role]").forEach(function (sel) {
    var scope = sel.closest("form") || sel.closest("tr");
    var field = scope && scope.querySelector("[data-driver-field]");
    if (!field) return;
    var input = field.querySelector("input");
    function sync() {
      var drives = sel.value === "driver" || sel.value === "driver_scorekeeper";
      field.style.opacity = drives ? "" : "0.4";
      if (input) { input.required = drives; input.disabled = !drives; }
    }
    sel.addEventListener("change", sync);
    sync();
  });
})();

/* v1.13: local times, countdowns, reactions, theme, install and phone alerts. */
(function () {
  "use strict";
  var F1 = window.F1 || {};
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  // Race times are formatted by the server in the league's time zone; only the countdown ticks here.
  function parse(iso) { var d = new Date(iso); return isNaN(d) ? null : d; }
  var counters = document.querySelectorAll("[data-countdown]");
  function tick() {
    var now = Date.now();
    counters.forEach(function (el) {
      var d = parse(el.dataset.countdown);
      if (!d) return;
      var left = Math.floor((d - now) / 1000);
      if (left <= 0) { el.textContent = "Race time"; el.classList.add("live"); return; }
      var days = Math.floor(left / 86400), h = Math.floor(left % 86400 / 3600), m = Math.max(1, Math.floor(left % 3600 / 60));
      el.textContent = "Starts in " + (days ? days + "d " + h + "h" : h ? h + "h " + Math.floor(left % 3600 / 60) + "m" : m + "m");
    });
  }
  if (counters.length) { tick(); setInterval(tick, 30000); }

  // First visit by the Race Master: remember the league's time zone from their browser.
  var tzUrl = document.body.dataset.tzDetect;
  if (tzUrl && window.Intl) {
    try {
      var zoneName = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (zoneName) {
        fetch(tzUrl, { method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ timezone: zoneName }) })
          .then(function (r) { return r.json(); })
          .then(function (res) { if (res.ok) location.reload(); }).catch(function () {});
      }
    } catch (e) { /* no Intl time zone support */ }
  }

  // Reactions toggle in place.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".react-bar .react");
    if (!btn) return;
    var bar = btn.closest(".react-bar");
    var body = new FormData();
    body.append("target", bar.dataset.target);
    body.append("emoji", btn.dataset.emoji);
    body.append("csrf_token", csrf);
    fetch(bar.dataset.url, { method: "POST", body: body, credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res.ok) { if (F1.toast) F1.toast(res.error || "Couldn't react", "error"); return; }
        res.reactions.forEach(function (r) {
          var b = bar.querySelector('[data-emoji="' + r.emoji + '"]');
          if (!b) return;
          b.classList.toggle("mine", r.mine);
          b.querySelector("span").textContent = r.count || "";
          b.title = r.who.length ? r.who.join(", ") : "React";
        });
      }).catch(function () { if (F1.toast) F1.toast("Couldn't react. Check your connection.", "error"); });
  });

  // Copy buttons
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-copy]");
    if (!btn) return;
    var input = document.querySelector(btn.dataset.copy);
    if (!input) return;
    input.select();
    (navigator.clipboard ? navigator.clipboard.writeText(input.value) : Promise.reject()).then(
      function () { if (F1.toast) F1.toast("Link copied", "success"); },
      function () { document.execCommand && document.execCommand("copy"); });
  });

  // Theme
  var pick = document.getElementById("theme-pick");
  if (pick) {
    try { pick.value = localStorage.getItem("f1-theme") || "dark"; } catch (e) {}
    pick.addEventListener("change", function () {
      try { localStorage.setItem("f1-theme", pick.value); } catch (e) {}
      var t = pick.value;
      if (t === "auto") t = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", t);
    });
  }

  // Service worker (installable app + alerts). Needs HTTPS or localhost.
  var swReady = null;
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
    swReady = navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(function () { return navigator.serviceWorker.ready; })
      .catch(function () { return null; });
  }

  // Install prompt
  var installBox = document.getElementById("install-box"), installBtn = document.getElementById("install-btn"), deferred = null;
  var standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  var ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  if (installBox && !standalone) {
    if (ios) {
      installBox.hidden = false;
      document.getElementById("install-help").textContent = "On iPhone: tap the Share button in Safari, then “Add to Home Screen”. Alerts on iPhone only work from the installed app.";
    }
    window.addEventListener("beforeinstallprompt", function (e) {
      e.preventDefault(); deferred = e; installBox.hidden = false; installBtn.hidden = false;
    });
    installBtn.addEventListener("click", function () {
      if (!deferred) return;
      deferred.prompt();
      deferred.userChoice.finally(function () { deferred = null; installBox.hidden = true; });
    });
  }

  // Phone & desktop alerts
  var keyMeta = document.querySelector('meta[name="push-key"]');
  var on = document.getElementById("push-on"), off = document.getElementById("push-off"), test = document.getElementById("push-test");
  var status = document.getElementById("push-status");
  function b64ToBytes(b64) {
    var pad = "=".repeat((4 - b64.length % 4) % 4);
    var raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); });
  }
  function post(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json(); });
  }
  function show(sub) { on.hidden = !!sub; off.hidden = !sub; test.hidden = !sub; }
  if (on && status) {
    if (!keyMeta || !swReady || !("PushManager" in window)) {
      status.textContent = ios && !standalone ? "Install the app to your home screen first, then turn alerts on from there."
        : "Alerts aren't available here (they need the website's https address and a modern browser).";
    } else {
      swReady.then(function (reg) {
        if (!reg) return;
        reg.pushManager.getSubscription().then(show);
        on.addEventListener("click", function () {
          Notification.requestPermission().then(function (perm) {
            if (perm !== "granted") { status.textContent = "Notifications are blocked for this site in your browser settings."; return; }
            reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(keyMeta.content) })
              .then(function (sub) { return post("/push/subscribe", sub.toJSON()).then(function (res) {
                if (!res.ok) throw new Error(res.error);
                show(sub); status.textContent = "Alerts are on for this device.";
              }); })
              .catch(function (err) { status.textContent = "Couldn't turn alerts on: " + (err.message || err); });
          });
        });
        off.addEventListener("click", function () {
          reg.pushManager.getSubscription().then(function (sub) {
            if (!sub) return show(null);
            return post("/push/unsubscribe", { endpoint: sub.endpoint }).then(function () { return sub.unsubscribe(); })
              .then(function () { show(null); status.textContent = "Alerts are off for this device."; });
          });
        });
        test.addEventListener("click", function () {
          post("/push/test").then(function (res) { status.textContent = res.ok ? "Test sent. It should pop up in a few seconds." : res.error; });
        });
      });
    }
  }
})();

/* v1.16: whole table rows open their driver/race page; clicks on links and controls inside still work. */
(function () {
  document.addEventListener("click", function (e) {
    var tr = e.target.closest("tr[data-href]");
    if (!tr || e.target.closest("a, button, input, select, textarea, label, summary")) return;
    if (window.getSelection && String(window.getSelection())) return;  // let people select text
    window.location.href = tr.dataset.href;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    var tr = e.target.closest && e.target.closest("tr[data-href]");
    if (tr && e.target === tr) window.location.href = tr.dataset.href;
  });
})();
