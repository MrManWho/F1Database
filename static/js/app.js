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

  // The phone/tablet menu drawer lives in shell.js.

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
    const markBtn = document.getElementById("notif-mark");
    const clearBtn = document.getElementById("notif-clear");
    function render(items) {
      list.innerHTML = "";
      if (!items.length) {
        list.innerHTML = '<li class="notif-empty"><span aria-hidden="true">🔕</span> You\'re all caught up. Results, offers and comments will show up here.</li>';
        return;
      }
      items.forEach(function (n) {
        const li = document.createElement("li");
        li.className = n.unread ? "unread" : "read";
        const ico = document.createElement("span");
        ico.className = "notif-ico"; ico.title = n.category || ""; ico.textContent = n.icon || "🔔";
        const wrap = document.createElement("div");
        wrap.className = "notif-body";
        const body = n.link ? document.createElement("a") : document.createElement("span");
        if (n.link) body.href = n.link;
        body.textContent = n.text;
        const when = document.createElement("small");
        when.title = n.when || "";
        when.textContent = (n.unread ? "New · " : "") + (n.category ? n.category + " · " : "") + n.created_at;
        wrap.append(body, when);
        li.append(ico, wrap);
        list.appendChild(li);
      });
    }
    function poll() {
      return fetch(bell.dataset.url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (res) {
        if (!res.ok) return;
        if (res.unread > last && soundOn) chime();
        if (res.unread > last) toast(res.items[0] ? res.items[0].text : "New notification", "success");
        last = res.unread;
        setCount(res.unread);
        if (markBtn) markBtn.disabled = !res.unread;
        render(res.items);
      }).catch(function () { /* offline: try again next minute */ });
    }
    setCount(last);
    setInterval(poll, 60000);
    // Opening the panel only shows notifications; reading them is the person's choice.
    if (markBtn) markBtn.addEventListener("click", function () {
      postJSON(bell.dataset.read, {}).then(function () { last = 0; setCount(0); markBtn.disabled = true; poll(); });
    });
    if (clearBtn) clearBtn.addEventListener("click", function () {
      postJSON(clearBtn.dataset.url, {}).then(poll);
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
  // Same states as timefmt.race_status: countdown, race window open, awaiting results, completed.
  var ICONS = { unscheduled: "📅", postponed: "⏸", scheduled: "📅", upcoming: "⏱", soon: "🔔", live: "🟢", pending: "⏳", complete: "🏁", paddock: "🏁" };
  function state(el, now) {
    if (el.dataset.eventStatus === "Complete") return ["complete", "Completed"];
    if (el.dataset.postponed === "1") return ["postponed", "Postponed"];
    if (el.dataset.phase === "live") return ["live", "Lights out · Live"];     // v2.3: started by the Scorekeeper
    var d = parse(el.dataset.countdown);
    if (el.dataset.phase === "paddock" && (!d || d <= now)) return ["paddock", "Paddock open"];
    if (!d || !el.dataset.countdown) return ["unscheduled", "Not scheduled"];
    var left = Math.floor((d - now) / 1000), mins = left / 60;
    if (mins > 7 * 24 * 60) return ["scheduled", "Scheduled"];
    if (mins > 30) {
      var days = Math.floor(left / 86400), h = Math.floor(left % 86400 / 3600), m = Math.floor(left % 3600 / 60);
      return ["upcoming", "Starts in " + (days ? days + "d " + h + "h" : h ? h + "h " + m + "m" : Math.max(1, m) + "m")];
    }
    if (mins > 0) return ["soon", "Starting soon"];
    if (-mins <= (parseInt(el.dataset.window, 10) || 180)) return ["live", "In progress"];
    return ["pending", "Results pending"];
  }
  function tick() {
    var now = Date.now();
    counters.forEach(function (el) {
      var s = state(el, now);
      if (!s) return;
      el.className = el.className.replace(/\bstate-\w+/g, "").trim() + " state-" + s[0];
      var text = el.querySelector(".state-text"), ico = el.querySelector(".state-ico");
      if (text) { if (text.textContent !== s[1]) text.textContent = s[1]; } else el.textContent = s[1];
      if (ico) ico.textContent = ICONS[s[0]] || "";
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

  // Density
  var dens = document.getElementById("density-pick");
  if (dens) {
    try { dens.value = localStorage.getItem("f1-density") || "comfortable"; } catch (e) {}
    dens.addEventListener("change", function () {
      try { localStorage.setItem("f1-density", dens.value); } catch (e) {}
      document.body.classList.toggle("compact", dens.value === "compact");
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

/* Wide tables: let headers stick to the page when the table fits; scroll sideways (frozen first column) when it doesn't. */
(function () {
  function fit() {
    document.querySelectorAll(".table-wrap").forEach(function (w) {
      var t = w.querySelector("table");
      if (!t) return;
      w.classList.remove("scroll-x");
      if (t.scrollWidth > w.clientWidth + 1) w.classList.add("scroll-x");
    });
  }
  fit();
  var timer;
  window.addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(fit, 120); });
})();

/* Password forms: show/hide, Caps Lock warning, matching and length checks, and no double submission. */
(function () {
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-pw-toggle]");
    if (!btn) return;
    var input = document.getElementById(btn.dataset.pwToggle);
    if (!input) return;
    var show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.textContent = show ? "Hide" : "Show";
    btn.setAttribute("aria-pressed", show ? "true" : "false");
    btn.setAttribute("aria-label", btn.getAttribute("aria-label").replace(show ? "Show" : "Hide", show ? "Hide" : "Show"));
  });
  document.querySelectorAll("form[data-password-form]").forEach(function (form) {
    var caps = form.querySelector(".pw-caps"), err = form.querySelector(".pw-error");
    var cur = form.querySelector('[data-pw="current"]'), pw = form.querySelector('[data-pw="new"]'), again = form.querySelector('[data-pw="confirm"]');
    form.querySelectorAll("[data-pw]").forEach(function (input) {
      ["keydown", "keyup"].forEach(function (ev) {
        input.addEventListener(ev, function (e) { if (caps && e.getModifierState) caps.hidden = !e.getModifierState("CapsLock"); });
      });
      input.addEventListener("blur", function () { if (caps) caps.hidden = true; });
    });
    form.addEventListener("submit", function (e) {
      if (form.dataset.sending === "1") { e.preventDefault(); return; }   // already on its way
      var min = pw ? parseInt(pw.getAttribute("minlength") || "6", 10) : 0;
      var msg = cur && !cur.value ? "Enter your current password."
        : pw && pw.value.length < min ? "The new password needs at least " + min + " characters."
        : again && pw && pw.value !== again.value ? "The two passwords don't match."
        : cur && pw && pw.value === cur.value ? "Choose a password that's different from the current one." : "";
      if (err) { err.textContent = msg; err.hidden = !msg; }
      if (msg) {
        e.preventDefault();
        (cur && !cur.value ? cur : pw && pw.value.length < min ? pw : again || pw).focus();
        return;
      }
      form.dataset.sending = "1";
      form.querySelectorAll("button:not([type=button])").forEach(function (b) { b.disabled = true; b.textContent = "Saving…"; });
    });
  });
})();

/* Email form: race-result emails need a valid address. */
(function () {
  var ef = document.querySelector("[data-email-form]");
  if (ef) {
    var email = ef.elements.email, box = ef.elements.email_results, hint = document.getElementById("email-results-hint");
    var sync = function () {
      var ok = email.value.trim() !== "" && email.checkValidity();
      box.disabled = !ok;
      if (!ok) box.checked = false;
      box.closest("label").classList.toggle("is-disabled", !ok);
      hint.hidden = ok;
      hint.textContent = email.value.trim() && !ok ? "Enter a valid email address to enable race-result emails." : "Add an email address to enable race-result emails.";
    };
    email.addEventListener("input", sync);
  }
})();

/* v1.18 Help: search, topic dropdown, and highlighting the section being read. Anchors stay shareable. */
(function () {
  var content = document.getElementById("help-content");
  if (!content) return;
  var sections = Array.prototype.slice.call(content.querySelectorAll("section.help"));
  var links = {};
  document.querySelectorAll(".help-group a[data-topic]").forEach(function (a) { links[a.dataset.topic] = a; });
  function mark(id) {
    Object.keys(links).forEach(function (k) {
      links[k].classList.toggle("current", k === id);
      if (k === id) links[k].setAttribute("aria-current", "true"); else links[k].removeAttribute("aria-current");
    });
  }
  if ("IntersectionObserver" in window) {
    var visible = {};
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { visible[e.target.id] = e.isIntersecting ? e.intersectionRatio : 0; });
      var best = sections.filter(function (s) { return visible[s.id] > 0 && !s.hidden; })[0];
      if (best) mark(best.id);
    }, { rootMargin: "0px 0px -60% 0px", threshold: [0, 0.01, 0.5] });
    sections.forEach(function (s) { io.observe(s); });
  }
  if (location.hash) mark(location.hash.slice(1));
  var jump = document.getElementById("help-jump");
  if (jump) jump.addEventListener("change", function () {
    if (!jump.value) return;
    location.hash = jump.value;
    var target = document.getElementById(jump.value);
    if (target) { target.setAttribute("tabindex", "-1"); target.focus({ preventScroll: true }); }
  });
  var search = document.getElementById("help-search"), status = document.getElementById("help-search-status");
  var empty = document.getElementById("help-empty");
  var titles = content.querySelectorAll(".help-group-title");
  if (search) {
    search.addEventListener("input", function () {
      var q = search.value.trim().toLowerCase(), shown = 0;
      sections.forEach(function (s) {
        var hit = !q || s.textContent.toLowerCase().indexOf(q) !== -1;
        s.hidden = !hit;
        if (links[s.id]) links[s.id].hidden = !hit;
        if (hit) shown++;
      });
      titles.forEach(function (t) {
        var n = t.nextElementSibling, any = false;
        while (n && n.tagName === "SECTION") { if (!n.hidden) any = true; n = n.nextElementSibling; }
        t.hidden = !any;
      });
      empty.hidden = shown > 0;
      status.textContent = q ? shown + " topic" + (shown === 1 ? "" : "s") + " match" + (shown === 1 ? "es" : "") : "";
    });
    search.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      var first = sections.filter(function (s) { return !s.hidden; })[0];
      if (first) { e.preventDefault(); location.hash = first.id; }
    });
  }
})();

/* Race Master tools in the sidebar: collapsible, remembered per browser. */
(function () {
  var btn = document.getElementById("nav-admin-toggle");
  if (!btn) return;
  var root = document.documentElement;
  function set(open) {
    root.classList.toggle("admin-nav-closed", !open);
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    try { localStorage.setItem("f1-admin-nav", open ? "1" : "0"); } catch (e) { /* private mode */ }
  }
  set(!root.classList.contains("admin-nav-closed"));
  btn.addEventListener("click", function () { set(root.classList.contains("admin-nav-closed")); });
})();

/* Confirmations for high-impact actions. A form opts in with data-confirm='{"title", "what", "history", "backup",
   "undo", "target", "strong", "ok"}'. "strong" asks the person to type a word (e.g. the driver's name) first.
   Cancel is the default button. window.F1.confirmAction(opts) returns a Promise<boolean> for scripts. */
(function () {
  var dlg = document.getElementById("confirm-dialog");
  if (!dlg) return;
  var body = document.getElementById("confirm-body"), ok = document.getElementById("confirm-ok");
  var typeRow = document.getElementById("confirm-type-row"), typeIn = document.getElementById("confirm-type");
  function esc(t) { var d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }
  function ask(o) {
    return new Promise(function (resolve) {
      document.getElementById("confirm-title").textContent = o.title || "Are you sure?";
      var rows = [["Affects", o.target], ["What changes", o.what], ["Historical results", o.history],
                  ["Backup", o.backup], ["Undo", o.undo]].filter(function (r) { return r[1]; });
      body.innerHTML = '<dl class="confirm-facts">' + rows.map(function (r) {
        return "<div><dt>" + esc(r[0]) + "</dt><dd>" + esc(r[1]) + "</dd></div>"; }).join("") + "</dl>";
      ok.textContent = o.ok || "Confirm";
      ok.className = "btn " + (o.safe ? "btn-primary" : "btn-danger");
      typeRow.hidden = !o.strong;
      typeIn.value = "";
      if (o.strong) document.getElementById("confirm-type-label").textContent = "Type " + o.strong + " to confirm";
      ok.disabled = !!o.strong;
      typeIn.oninput = function () { ok.disabled = typeIn.value.trim() !== o.strong; };
      var done = false;
      function finish(v) { if (done) return; done = true; if (dlg.open) dlg.close(); resolve(v); }
      ok.onclick = function () { finish(true); };
      document.getElementById("confirm-cancel").onclick = function () { finish(false); };
      dlg.addEventListener("close", function onClose() { dlg.removeEventListener("close", onClose); finish(false); });
      if (dlg.showModal) dlg.showModal(); else finish(window.confirm((o.title || "") + "\n" + (o.what || "")));
      (o.strong ? typeIn : document.getElementById("confirm-cancel")).focus();
    });
  }
  window.F1 = window.F1 || {};
  window.F1.confirmAction = ask;
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.dataset || !form.dataset.confirm || form.dataset.confirmed === "1") return;
    e.preventDefault();
    var opts; try { opts = JSON.parse(form.dataset.confirm); } catch (err) { opts = { what: form.dataset.confirm }; }
    var submitter = e.submitter;
    ask(opts).then(function (yes) {
      if (!yes) return;
      form.dataset.confirmed = "1";
      if (opts.strong) {
        var h = form.querySelector('input[name="confirm_text"]') || form.appendChild(Object.assign(document.createElement("input"), { type: "hidden", name: "confirm_text" }));
        h.value = opts.strong;
      }
      if (form.requestSubmit) form.requestSubmit(submitter || undefined); else form.submit();
    });
  }, true);
})();

/* Grid editor: replacing a driver or vacating a seat asks first, listing exactly which seats change. */
(function () {
  ["grid-form", "player-form"].forEach(function (id) {
    var form = document.getElementById(id);
    if (!form || !(window.F1 && window.F1.confirmAction)) return;
    form.addEventListener("submit", function (e) {
      if (form.dataset.confirmed === "1") return;
      var changes = [];
      form.querySelectorAll("select").forEach(function (sel) {
        var before = Array.prototype.find.call(sel.options, function (o) { return o.defaultSelected; });
        var after = sel.selectedOptions[0];
        if (!before || before === after) return;
        var where = sel.closest(".grid-team") ? sel.closest(".grid-team").querySelector("strong").textContent + " seat " + sel.name.split("_").pop()
          : (sel.closest("label").querySelector("strong") || {}).textContent;
        if (id === "grid-form") {
          if (before.value && !after.value) changes.push(where + ": " + before.textContent.trim() + " → vacant");
          else if (before.value) changes.push(where + ": " + before.textContent.trim() + " → " + after.textContent.trim());
        } else if (after.dataset.occupant) {
          changes.push(where + " takes " + after.textContent.trim() + ", replacing " + after.dataset.occupant);
        }
      });
      if (!changes.length) return;
      e.preventDefault();
      window.F1.confirmAction({
        title: changes.length === 1 ? "Change this seat?" : "Change " + changes.length + " seats?",
        target: changes.join("; "),
        what: "The drivers move for rounds that haven't been run yet. Anyone left without a seat becomes a free agent (AI drivers can fill empty seats).",
        history: "Not affected: completed and in-progress rounds keep their original lineups, and every driver keeps their results and career history.",
        backup: "An automatic backup already runs daily and after each round.",
        undo: "Yes: put the drivers back the same way.", ok: "Save grid", safe: true
      }).then(function (yes) {
        if (!yes) return;
        form.dataset.confirmed = "1";
        if (form.requestSubmit) form.requestSubmit(); else form.submit();
      });
    }, true);
  });
})();
