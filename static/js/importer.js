/* Screenshot import, entirely in the browser: canvas clean-up -> Tesseract.js (self-hosted, free) -> preview.
   Screenshots never leave this page: nothing is uploaded, stored or logged. Applying only fills the normal
   results form; saving, submitting and locking still happen through the usual steps. */
(function () {
  "use strict";
  const dlg = document.getElementById("import-dialog");
  if (!dlg || !window.OcrMatch) return;
  const M = window.OcrMatch;
  const VENDOR = dlg.dataset.vendor;
  const grid = JSON.parse(dlg.dataset.entrants || "[]");
  const teams = Array.from(new Set(grid.map(function (d) { return d.team; }).filter(Boolean)));
  const isSprintWeekend = dlg.dataset.sprint === "1";
  const maxPos = Math.max(grid.length, 1);
  const byId = {}; grid.forEach(function (d) { byId[d.id] = d; });
  const $ = function (sel) { return dlg.querySelector(sel); };

  let shots = [];          // {id, name, img, url, rotate, fine, crop, contrast, autoTrim, lines, text}
  let rows = [];           // preview rows (see OcrMatch.buildRows)
  let detected = null;     // session detection
  let worker = null, cancelled = false, busy = false, nextId = 1;

  // ---------------------------------------------------------------- loading the OCR engine (on demand only)
  let loading = null;
  function loadEngine() {
    if (window.Tesseract) return Promise.resolve(window.Tesseract);
    if (loading) return loading;
    loading = new Promise(function (resolve, reject) {
      const s = document.createElement("script");
      s.src = VENDOR + "tesseract.min.js";
      s.onload = function () { window.Tesseract ? resolve(window.Tesseract) : reject(new Error("OCR engine didn't start")); };
      s.onerror = function () { loading = null; reject(new Error("The OCR engine couldn't be loaded")); };
      document.head.appendChild(s);
    });
    return loading;
  }
  function getWorker() {
    if (worker) return Promise.resolve(worker);
    return loadEngine().then(function (T) {
      return T.createWorker("eng", 1, {
        workerPath: VENDOR + "worker.min.js", corePath: VENDOR, langPath: VENDOR + "lang",
        cacheMethod: "write",   // language data is kept in this browser's storage after the first download
        logger: function (m) { progress(m.status, m.progress); }
      });
    }).then(function (w) {
      return w.setParameters({ tessedit_pageseg_mode: "6", preserve_interword_spaces: "1" }).then(function () { worker = w; return w; });
    });
  }
  function release() {
    if (worker) { try { worker.terminate(); } catch (e) { /* already gone */ } }
    worker = null;
  }

  // ---------------------------------------------------------------- image clean-up (canvas)
  function loadImage(file) {
    return new Promise(function (resolve, reject) {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = function () { resolve({ img: img, url: url }); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error(file.name + " isn't an image this browser can read")); };
      img.src = url;
    });
  }
  /** Rotate (quarter turns + fine angle) into a new canvas. */
  function rotated(shot) {
    const img = shot.img, turns = ((shot.rotate / 90) % 4 + 4) % 4, rad = (shot.rotate + shot.fine) * Math.PI / 180;
    const w = img.naturalWidth, h = img.naturalHeight;
    const sw = turns % 2 ? h : w, sh = turns % 2 ? w : h;
    const c = document.createElement("canvas");
    c.width = sw; c.height = sh;
    const g = c.getContext("2d");
    g.fillStyle = "#000"; g.fillRect(0, 0, sw, sh);
    g.translate(sw / 2, sh / 2); g.rotate(rad); g.drawImage(img, -w / 2, -h / 2);
    return c;
  }
  /** Trim flat borders (letterboxing, blank margins) when they're clearly uniform. */
  function autoTrimRect(c) {
    const g = c.getContext("2d"), w = c.width, h = c.height;
    const data = g.getImageData(0, 0, w, h).data;
    const lum = function (x, y) { const i = (y * w + x) * 4; return 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]; };
    const flat = function (vals) { let lo = 255, hi = 0; vals.forEach(function (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); }); return hi - lo < 18; };
    const row = function (y) { const v = []; for (let x = 0; x < w; x += Math.max(1, w >> 7)) v.push(lum(x, y)); return v; };
    const col = function (x) { const v = []; for (let y = 0; y < h; y += Math.max(1, h >> 7)) v.push(lum(x, y)); return v; };
    let top = 0, bottom = h - 1, left = 0, right = w - 1;
    while (top < h / 3 && flat(row(top))) top++;
    while (bottom > h * 2 / 3 && flat(row(bottom))) bottom--;
    while (left < w / 3 && flat(col(left))) left++;
    while (right > w * 2 / 3 && flat(col(right))) right--;
    return { x: left, y: top, w: right - left + 1, h: bottom - top + 1 };
  }
  /** Crop, scale, greyscale, invert dark themes, stretch contrast and sharpen: what Tesseract reads best. */
  function prepare(shot) {
    let src = rotated(shot);
    let r = { x: 0, y: 0, w: src.width, h: src.height };
    if (shot.crop) r = { x: shot.crop.x * src.width, y: shot.crop.y * src.height, w: shot.crop.w * src.width, h: shot.crop.h * src.height };
    else if (shot.autoTrim) r = autoTrimRect(src);
    const scale = Math.min(3, Math.max(1, 2000 / Math.max(r.w, 1)));
    const out = document.createElement("canvas");
    out.width = Math.round(r.w * scale); out.height = Math.round(r.h * scale);
    const g = out.getContext("2d", { willReadFrequently: true });
    g.imageSmoothingQuality = "high";
    g.drawImage(src, r.x, r.y, r.w, r.h, 0, 0, out.width, out.height);
    src.width = src.height = 0;
    const im = g.getImageData(0, 0, out.width, out.height), d = im.data;
    const hist = new Array(256).fill(0);
    let sum = 0;
    for (let i = 0; i < d.length; i += 4) {
      const v = Math.round(0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]);
      d[i] = v; hist[v]++; sum += v;
    }
    const n = d.length / 4, mean = sum / n;
    const invert = mean < 110;   // light text on a dark game screen -> dark text on white
    let acc = 0, lo = 0, hi = 255;
    for (let v = 0; v < 256; v++) { acc += hist[v]; if (acc < n * 0.02) lo = v; if (acc < n * 0.98) hi = v; }
    const span = Math.max(1, hi - lo), k = shot.contrast;
    for (let i = 0; i < d.length; i += 4) {
      let v = (d[i] - lo) / span * 255;
      if (invert) v = 255 - v;
      v = (v - 128) * k + 128 + shot.brightness;
      v = v < 0 ? 0 : v > 255 ? 255 : v;
      d[i] = d[i + 1] = d[i + 2] = v; d[i + 3] = 255;
    }
    // Light 3x3 sharpen.
    const copy = new Uint8ClampedArray(d), W = out.width, H = out.height;
    for (let y = 1; y < H - 1; y++) {
      for (let x = 1; x < W - 1; x++) {
        const i = (y * W + x) * 4;
        const v = 5 * copy[i] - copy[i - 4] - copy[i + 4] - copy[i - W * 4] - copy[i + W * 4];
        d[i] = d[i + 1] = d[i + 2] = v < 0 ? 0 : v > 255 ? 255 : v;
      }
    }
    g.putImageData(im, 0, 0);
    return out;
  }

  // ---------------------------------------------------------------- screenshot list with simple tools
  function renderShots() {
    const list = $("#imp-shots");
    list.innerHTML = "";
    shots.forEach(function (shot, i) {
      const card = document.createElement("div");
      card.className = "imp-shot";
      card.innerHTML =
        '<div class="imp-shot-head"><b>Screenshot ' + (i + 1) + '</b> <span class="muted small"></span>' +
        '<button type="button" class="btn btn-sm btn-ghost" data-act="remove" aria-label="Remove screenshot ' + (i + 1) + '">Remove</button></div>' +
        '<canvas class="imp-thumb" aria-label="Preview of screenshot ' + (i + 1) + '. Drag to crop."></canvas>' +
        '<div class="imp-tools">' +
        '<button type="button" class="btn btn-sm btn-ghost" data-act="left" aria-label="Rotate left">⟲</button>' +
        '<button type="button" class="btn btn-sm btn-ghost" data-act="right" aria-label="Rotate right">⟳</button>' +
        '<label class="small">Straighten <input type="range" min="-5" max="5" step="0.5" data-act="fine" value="' + shot.fine + '"></label>' +
        '<label class="small">Contrast <input type="range" min="0.8" max="2.2" step="0.1" data-act="contrast" value="' + shot.contrast + '"></label>' +
        '<label class="small">Brightness <input type="range" min="-60" max="60" step="5" data-act="brightness" value="' + shot.brightness + '"></label>' +
        '<label class="check small"><input type="checkbox" data-act="trim" ' + (shot.autoTrim ? "checked" : "") + '> Trim borders</label>' +
        '<button type="button" class="btn btn-sm btn-ghost" data-act="uncrop" ' + (shot.crop ? "" : "hidden") + '>Clear crop</button>' +
        '</div>';
      card.querySelector(".imp-shot-head .muted").textContent = shot.name;
      list.appendChild(card);
      drawThumb(card.querySelector("canvas"), shot);
      bindCrop(card.querySelector("canvas"), shot);
      card.addEventListener("click", function (e) {
        const act = e.target.dataset && e.target.dataset.act;
        if (act === "remove") { URL.revokeObjectURL(shot.url); shots.splice(shots.indexOf(shot), 1); renderShots(); invalidate(); }
        if (act === "left" || act === "right") { shot.rotate += act === "left" ? -90 : 90; shot.crop = null; renderShots(); invalidate(); }
        if (act === "uncrop") { shot.crop = null; renderShots(); invalidate(); }
      });
      card.addEventListener("change", function (e) {
        const act = e.target.dataset && e.target.dataset.act;
        if (act === "fine") shot.fine = parseFloat(e.target.value);
        if (act === "contrast") shot.contrast = parseFloat(e.target.value);
        if (act === "brightness") shot.brightness = parseFloat(e.target.value);
        if (act === "trim") shot.autoTrim = e.target.checked;
        if (act) { drawThumb(card.querySelector("canvas"), shot); invalidate(); }
      });
    });
    $("#imp-read").disabled = !shots.length;
    $("#imp-empty").hidden = !!shots.length;
  }
  function drawThumb(canvas, shot) {
    const src = rotated(shot);
    const w = Math.min(520, src.width), h = Math.round(src.height * w / src.width);
    canvas.width = w; canvas.height = h;
    const g = canvas.getContext("2d");
    g.drawImage(src, 0, 0, w, h);
    src.width = src.height = 0;
    if (shot.crop) {
      g.fillStyle = "rgba(0,0,0,.55)";
      const c = shot.crop;
      g.fillRect(0, 0, w, c.y * h); g.fillRect(0, (c.y + c.h) * h, w, h);
      g.fillRect(0, c.y * h, c.x * w, c.h * h); g.fillRect((c.x + c.w) * w, c.y * h, w, c.h * h);
      g.strokeStyle = "#4aa3ff"; g.lineWidth = 2; g.strokeRect(c.x * w, c.y * h, c.w * w, c.h * h);
    }
  }
  function bindCrop(canvas, shot) {
    let start = null;
    const pt = function (e) {
      const r = canvas.getBoundingClientRect(), p = e.touches ? e.touches[0] : e;
      return { x: Math.min(1, Math.max(0, (p.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (p.clientY - r.top) / r.height)) };
    };
    const down = function (e) { start = pt(e); };
    const move = function (e) {
      if (!start) return;
      const p = pt(e);
      shot.crop = { x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y) };
      drawThumb(canvas, shot);
      if (e.cancelable) e.preventDefault();
    };
    const up = function () {
      if (start && shot.crop && (shot.crop.w < 0.05 || shot.crop.h < 0.05)) shot.crop = null;
      start = null; renderShots(); invalidate();
    };
    canvas.addEventListener("mousedown", down); canvas.addEventListener("mousemove", move); canvas.addEventListener("mouseup", up);
    canvas.addEventListener("touchstart", down, { passive: true }); canvas.addEventListener("touchmove", move); canvas.addEventListener("touchend", up);
  }
  function invalidate() { shots.forEach(function (s) { s.lines = null; }); showStep("files"); }

  // ---------------------------------------------------------------- reading
  function progress(status, value) {
    const bar = $("#imp-progress-bar"), text = $("#imp-progress-text");
    const labels = { "loading tesseract core": "Loading the OCR engine", "initializing tesseract": "Starting the OCR engine",
      "loading language traineddata": "Loading English text data (first time only)", "initializing api": "Getting ready",
      "recognizing text": "Reading text" };
    if (status) text.textContent = (labels[status] || status) + (current ? " · screenshot " + current + " of " + shots.length : "") + "…";
    if (typeof value === "number") { bar.value = value; bar.textContent = Math.round(value * 100) + "%"; }
  }
  let current = 0;
  function read() {
    if (busy || !shots.length) return;
    busy = true; cancelled = false; current = 0;
    showStep("progress");
    progress("Preparing images", 0);
    getWorker().then(function (w) {
      let chain = Promise.resolve();
      shots.forEach(function (shot, i) {
        chain = chain.then(function () {
          if (cancelled) throw new Error("cancelled");
          current = i + 1;
          const canvas = prepare(shot);
          return w.recognize(canvas).then(function (res) {
            canvas.width = canvas.height = 0;   // free the pixels straight away
            shot.text = res.data.text || "";
            shot.lines = (res.data.lines || []).map(function (l) { return { text: l.text.trim(), confidence: l.confidence }; })
              .filter(function (l) { return l.text; });
          });
        });
      });
      return chain;
    }).then(function () {
      busy = false;
      buildPreview();
    }).catch(function (err) {
      busy = false;
      if (cancelled || (err && err.message === "cancelled")) { release(); showStep("files"); toast("Reading cancelled. Nothing was changed.", "success"); return; }
      release();
      showStep("failed");
      $("#imp-fail-msg").textContent = (err && err.message ? err.message + ". " : "") +
        "Nothing was changed. You can try again, or close this and enter the results in the table as usual.";
    });
  }
  function cancelRead() {
    cancelled = true;
    release();   // terminating the worker stops recognition straight away
  }

  // ---------------------------------------------------------------- preview
  function buildPreview() {
    tele = null;
    $("#imp-raw-head").textContent = "Recognised text";
    const all = shots.map(function (s) { return s.text || ""; }).join("\n");
    detected = M.detectSession(all);
    const chosen = $("#imp-session").value;
    if (chosen === "auto") $("#imp-session2").value = detected.session && (detected.session !== "sprint" || isSprintWeekend) ? detected.session : "";
    else $("#imp-session2").value = chosen;
    rows = M.buildRows(shots.map(function (s, i) { return { index: i, lines: s.lines || [] }; }), grid, teams, maxPos);
    $("#imp-detected").textContent = detected.session
      ? "These look like " + { qualifying: "Qualifying", sprint: "Sprint", race: "Race" }[detected.session] + " results" +
        (detected.confidence === "high" ? "." : " (not certain).")
      : "Couldn't tell which session this is" + (detected.note ? " (" + detected.note + ")" : "") + ". Choose it below.";
    $("#imp-raw").textContent = shots.map(function (s, i) { return "— Screenshot " + (i + 1) + " —\n" + (s.text || "(no text found)"); }).join("\n\n");
    const usable = rows.filter(function (r) { return r.driver_id !== null; }).length;
    $("#imp-lowconf").hidden = usable >= Math.min(3, grid.length);
    renderRows();
    showStep("review");
  }
  function driverOptions(selected) {
    let html = '<option value="">— choose a driver —</option>';
    grid.forEach(function (d) {
      html += '<option value="' + d.id + '"' + (String(d.id) === String(selected) ? " selected" : "") + ">" + esc(d.name) +
        (d.is_player ? " ★" : "") + (d.team ? " · " + esc(d.team) : "") + "</option>";
    });
    return html;
  }
  const STATE_LABEL = { high: "High confidence", review: "Needs review", unmatched: "Unmatched", conflict: "Conflict", manual: "Added by you" };
  function renderRows() {
    const body = $("#imp-rows");
    body.innerHTML = "";
    rows.forEach(function (r, i) {
      const d = byId[r.driver_id];
      const tr = document.createElement("tr");
      tr.className = "imp-row state-" + r.state + (d && d.is_player ? " player-row" : "") + (r.include ? "" : " is-excluded");
      if (d && d.is_player && d.color) tr.style.setProperty("--player", d.color);
      tr.innerHTML =
        '<td><input type="checkbox" data-f="include" aria-label="Include this row"' + (r.include ? " checked" : "") + "></td>" +
        '<td class="small">' + (r.source === null || r.source === undefined ? "—" : "#" + (r.source + 1)) + "</td>" +
        '<td class="imp-raw-cell small"></td>' +
        '<td><select data-f="driver_id" aria-label="Driver">' + driverOptions(r.driver_id) + "</select></td>" +
        '<td><input type="number" min="1" max="' + maxPos + '" data-f="position" class="narrow" aria-label="Position" value="' + (r.position || "") + '"></td>' +
        '<td><select data-f="status" aria-label="Status">' + ["Finished", "DNF", "DNS", "DSQ"].map(function (s) {
          return '<option value="' + s + '"' + ((r.status || "Finished") === s ? " selected" : "") + ">" + s + "</option>"; }).join("") + "</select></td>" +
        '<td><span class="imp-state">' + (r.state === "high" ? "✓ " : r.state === "conflict" ? "⚠ " : r.state === "unmatched" ? "✕ " : "? ") +
        STATE_LABEL[r.state] + "</span> <small class=\"muted\">" + (r.confidence ? r.confidence + "%" : "") + "</small></td>" +
        '<td class="small imp-notes"></td>';
      tr.querySelector(".imp-raw-cell").textContent = r.raw || "";
      tr.querySelector(".imp-notes").textContent = (r.notes || []).join(" · ");
      tr.addEventListener("change", function (e) {
        const f = e.target.dataset.f;
        if (!f) return;
        if (f === "include") r.include = e.target.checked;
        else if (f === "driver_id") { r.driver_id = e.target.value ? parseInt(e.target.value, 10) : null; if (r.state === "unmatched" || r.state === "review") r.state = r.driver_id ? "manual" : r.state; }
        else if (f === "position") r.position = e.target.value === "" ? null : parseInt(e.target.value, 10);
        else if (f === "status") r.status = e.target.value;
        if (f === "status" && r.status === "DNS") r.position = null;
        renderRows();
      });
      body.appendChild(tr);
    });
    check();
  }
  function existingValues(session) { return window.F1Entry ? window.F1Entry.existing(session) : {}; }
  function check() {
    const session = $("#imp-session2").value;
    const res = M.validate(rows, grid, { session: session, detected: $("#imp-ignore-detect").checked ? null : detected,
      existing: session ? existingValues(session) : {}, maxPos: maxPos, isSprint: isSprintWeekend });
    const list = function (sel, items) { const el = $(sel); el.innerHTML = items.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join(""); el.closest(".imp-findings").hidden = !items.length; };
    list("#imp-blocking", res.blocking); list("#imp-warnings", res.warnings); list("#imp-info", res.info);
    const cmp = $("#imp-compare");
    const touched = res.changes.filter(function (c) { return c.action !== "add"; });
    cmp.closest(".imp-compare-wrap").hidden = !touched.length;
    cmp.innerHTML = res.changes.map(function (c) {
      const show = function (v) { return !v ? "—" : (v.status && v.status !== "Finished" && v.status !== "Not Run" ? v.status + (v.position ? " (P" + v.position + ")" : "") : v.position ? "P" + v.position : "—"); };
      return "<tr class=\"cmp-" + c.action + "\"><td>" + esc(c.name) + "</td><td>" + show(c.existing) + "</td><td>" + show(c.imported) + "</td><td>" +
        { add: "Will be added", unchanged: "Unchanged", replace: "⚠ Will be replaced" }[c.action] + "</td></tr>";
    }).join("");
    const confirmRow = $("#imp-confirm-row");
    confirmRow.hidden = !res.replacing;
    if (!res.replacing) $("#imp-confirm").checked = false;
    $("#imp-apply").disabled = res.blocking.length > 0 || (res.replacing > 0 && !$("#imp-confirm").checked) ||
      !rows.some(function (r) { return r.include && r.driver_id; });
    return res;
  }
  function addManualRow() {
    rows.push({ key: "manual:" + (nextId++), source: null, raw: "", driver_id: null, position: null, status: "Finished",
      confidence: 0, state: "manual", notes: ["Added by you"], include: true, candidates: [] });
    renderRows();
  }
  function apply() {
    const res = check();
    if (res.blocking.length) return;
    const session = $("#imp-session2").value;
    const chosen = rows.filter(function (r) { return r.include && r.driver_id; })
      .map(function (r) { return { driver_id: r.driver_id, position: r.status === "DNS" ? null : r.position, status: r.status || "Finished" }; });
    if (!window.F1Entry) return;
    const n = window.F1Entry.applyImport(session, chosen);
    let extra = "";
    if (tele) {
      const fastest = session === "race" ? rows.find(function (r) { return r.fastest && r.include && r.driver_id; }) : null;
      const ai = tele.data.session && tele.data.session.ai_difficulty;
      const notes = window.F1Entry.applyExtras ? window.F1Entry.applyExtras({
        fastest_lap: fastest ? fastest.driver_id : null, ai_difficulty: typeof ai === "number" ? ai : null }) : [];
      if (notes.length) extra = " " + notes.join(" ");
      rememberTelemetry(session);
    }
    close();
    toast("Filled " + n + " " + { qualifying: "qualifying", sprint: "Sprint", race: "race" }[session] +
      " result" + (n === 1 ? "" : "s") + " into the table." + extra + " Check the highlighted boxes; nothing is submitted until you review and complete the weekend.", "success");
  }

  // ---------------------------------------------------------------- telemetry: results sent from the game
  // The same preview and checks as a screenshot, but the rows come from the game's own final classification.
  let tele = null;   // {upload_id, data}
  const TELE_STATUS = { Finished: "Finished", Active: "Finished", DSQ: "DSQ", DNF: "DNF", Retired: "DNF",
    "Not Classified": "DNF", Inactive: "DNS", Invalid: "DNS" };
  function teleSession(sess) {
    const id = sess.session_type_id;
    if (id >= 5 && id <= 9) return "qualifying";
    if (id === 16 || id === 17) return "race";
    if (id === 15) return isSprintWeekend ? "sprint" : "race";   // on a Sprint weekend the Sprint is "Race", the GP "Race 2"
    return null;
  }
  function teleKey(r) { return (r.name || "") + "|" + (r.team || ""); }
  function sameTeam(a, b) {
    const w = function (t) { return M.normName(t || "").split(" ").filter(function (x) { return x.length >= 3 && ["racing", "team", "f1"].indexOf(x) < 0; }); };
    const x = w(a), y = w(b);
    return x.some(function (t) { return y.indexOf(t) >= 0; });
  }
  function teleRow(r, i, known) {
    const notes = [];
    let driverId = null, state = "unmatched", score = 0;
    const remembered = known[teleKey(r)];
    if (remembered && byId[remembered]) {
      driverId = remembered; state = "high"; score = 1; notes.push("Matched as in an earlier import");
    } else if (r.name) {
      const m = M.matchDriver(r.name, grid);
      const sameTeamCands = (m.candidates || []).filter(function (c) { return byId[c.id] && sameTeam(byId[c.id].team, r.team); });
      if (m.driver_id && (!r.team || sameTeam(byId[m.driver_id].team, r.team))) {
        driverId = m.driver_id; state = m.state === "matched" ? "high" : "review"; score = m.score;
      } else if (sameTeamCands.length === 1) {
        driverId = sameTeamCands[0].id; state = "review"; score = sameTeamCands[0].score;
      } else if (m.driver_id) {
        driverId = m.driver_id; state = "review"; score = m.score;
        notes.push("The game has them at " + r.team + "; check this is the right driver");
      } else if (m.state === "ambiguous") {
        notes.push("Could be " + m.candidates.map(function (c) { return c.name; }).join(" or "));
      }
    }
    const status = TELE_STATUS[r.status] || "Finished";
    if (r.reason && status !== "Finished") notes.push(r.reason);
    if (r.penalty_s) notes.push("+" + r.penalty_s + "s in penalties (already in the position)");
    if (r.fastest_lap && r.best_lap) notes.push("Fastest lap " + r.best_lap);
    return { key: "t:" + i, source: null, raw: (r.position ? "P" + r.position + " " : "") + (r.name || "?") + (r.team ? " · " + r.team : ""),
      teleKey: teleKey(r), driver_id: driverId, position: status === "DNS" ? null : (r.position || null), status: status,
      confidence: Math.round(score * 100), state: state, notes: notes, candidates: [], include: true, fastest: !!r.fastest_lap };
  }
  function loadTelemetry(data, uploadId, known) {
    if (!data || !Array.isArray(data.results) || !data.results.length) {
      toast("That file has no results in it. Use the .json file the recorder saves for a session.", "error");
      return;
    }
    tele = { upload_id: uploadId || null, data: data };
    const sess = data.session || {};
    const session = teleSession(sess);
    detected = { session: session, confidence: session ? "high" : "none" };
    $("#imp-session2").value = session && (session !== "sprint" || isSprintWeekend) ? session : "";
    rows = data.results.map(function (r, i) { return teleRow(r, i, known || {}); });
    const what = (sess.session_type || "Session") + (sess.track ? " at " + sess.track : "");
    $("#imp-detected").textContent = session
      ? what + ", from the game's telemetry" + (typeof sess.ai_difficulty === "number" ? " (AI " + sess.ai_difficulty + ")" : "") + "."
      : what + ": only qualifying, Sprint and race sessions can be imported. Choose a session below to use it anyway.";
    $("#imp-raw").textContent = data.results.map(function (r) {
      return [r.position ? "P" + r.position : "–", r.name, r.team, r.status, r.best_lap, r.penalty_s ? "+" + r.penalty_s + "s" : ""].filter(Boolean).join("  ");
    }).join("\n");
    $("#imp-lowconf").hidden = true;
    $("#imp-raw-head").textContent = "From the game";
    renderRows();
    showStep("review");
  }
  function rememberTelemetry(session) {
    // Only names and driver ids, handed to static/js/telemetry_import.js; this file never sends anything.
    const names = {};
    rows.forEach(function (r) { if (r.include && r.driver_id && r.teleKey) names[r.teleKey] = r.driver_id; });
    if (window.F1TelemetryHooks) window.F1TelemetryHooks.applied({ upload_id: tele.upload_id, session: session, names: names });
  }
  // ---------------------------------------------------------------- telemetry: a whole weekend at once
  // bundle: this round's game sessions ({qualifying: [Q1, Q2, Q3...], sprint, race}, from the league). Every session
  // is matched like a single import, then filled into the results table (a draft); drivers that don't match
  // confidently are left out and listed. Weather and race times are worked out here and saved by the caller.
  function ident(r) { return teleKey(r) + "|" + (r.race_number || ""); }
  function byPos(a, b) { return (a.position || 99) - (b.position || 99); }
  function combineQuali(list) {
    // Q1, Q2 and Q3 come as separate sessions: the final order is Q3, then those out in Q2, then those out in Q1.
    const seen = {}, out = [];
    list.slice().reverse().forEach(function (q) {
      (q.results || []).filter(function (r) { return r.position; }).sort(byPos).forEach(function (r) {
        if (seen[ident(r)]) return;
        seen[ident(r)] = true;
        out.push(Object.assign({}, r, { position: out.length + 1 }));
      });
    });
    return out;
  }
  function fillWeekend(bundle, known) {
    const report = { filled: [], missing: [], review: 0, names: {}, pace: [], upload_ids: [], sessions: {} };
    if (!window.F1Entry) return report;
    const label = { qualifying: "qualifying", sprint: "Sprint", race: "race" };
    const plans = [];
    if (bundle.qualifying && bundle.qualifying.length) plans.push({ key: "qualifying", results: combineQuali(bundle.qualifying), uploads: bundle.qualifying });
    if (bundle.sprint && isSprintWeekend) plans.push({ key: "sprint", results: bundle.sprint.results || [], uploads: [bundle.sprint] });
    if (bundle.race) plans.push({ key: "race", results: bundle.race.results || [], uploads: [bundle.race] });
    const driverOf = {};
    plans.forEach(function (p) {
      const matched = p.results.map(function (r, i) { return teleRow(r, i, known || {}); });
      const count = {};
      matched.forEach(function (m) { if (m.driver_id) count[m.driver_id] = (count[m.driver_id] || 0) + 1; });
      const use = [];
      matched.forEach(function (m, i) {
        if (m.driver_id && count[m.driver_id] === 1) {
          use.push(m); driverOf[ident(p.results[i])] = m.driver_id;
          if (m.teleKey) report.names[m.teleKey] = m.driver_id;
          if (m.state === "review") report.review++;
        } else if (report.missing.indexOf(m.raw) < 0) report.missing.push(label[p.key] + ": " + m.raw);
      });
      const n = window.F1Entry.applyImport(p.key, use.map(function (m) {
        return { driver_id: m.driver_id, position: m.status === "DNS" ? null : m.position, status: m.status || "Finished" };
      }));
      if (n) report.filled.push(n + " " + label[p.key]);
      p.uploads.forEach(function (u) { if (u.id) report.upload_ids.push(u.id); });
      report.sessions[{ qualifying: "quali", sprint: "sprint", race: "race" }[p.key]] = p.uploads.map(function (u) { return u.id; }).filter(Boolean);
    });
    // Fastest lap (Grand Prix) and the AI level, as a single race import would.
    const race = bundle.race;
    const fastest = race && (race.results || []).find(function (r) { return r.fastest_lap; });
    const anySession = race || bundle.sprint || (bundle.qualifying || [])[0];
    const ai = anySession && anySession.session && anySession.session.ai_difficulty;
    const extras = window.F1Entry.applyExtras ? window.F1Entry.applyExtras({
      fastest_lap: fastest ? driverOf[ident(fastest)] || null : null, ai_difficulty: typeof ai === "number" && ai > 0 ? ai : null }) : [];
    report.extra_notes = extras;
    // Race times for each player against their AI teammate (same team in the game), and qualifying laps.
    const isPlayer = function (id) { return id && byId[id] && byId[id].is_player; };
    const bestQ = {};
    (bundle.qualifying || []).forEach(function (q) {
      (q.results || []).forEach(function (r) {
        if (r.best_lap_ms && (!bestQ[ident(r)] || r.best_lap_ms < bestQ[ident(r)])) bestQ[ident(r)] = r.best_lap_ms;
      });
    });
    grid.filter(function (d) { return d.is_player; }).forEach(function (d) {
      [["gp", race], ["sprint", isSprintWeekend ? bundle.sprint : null]].forEach(function (pair) {
        const sess = pair[1], entry = { driver_id: d.id, session: pair[0] };
        const all = sess ? sess.results || [] : [];
        let me = all.find(function (r) { return driverOf[ident(r)] === d.id; });
        if (!me && pair[0] === "gp") {   // no race: qualifying still gives lap times
          Object.keys(bestQ).some(function (k) { return driverOf[k] === d.id && (me = { _ident: k }); });
        }
        if (!me) return;
        const myIdent = me._ident || ident(me);
        const myTeam = myIdent.split("|")[1];
        const mate = all.find(function (r) { return ident(r) !== myIdent && r.team === myTeam && !isPlayer(driverOf[ident(r)]); });
        if (pair[0] === "gp") {
          let mateIdent = mate ? ident(mate) : null;
          if (!mateIdent) Object.keys(bestQ).some(function (k) {
            return k !== myIdent && k.split("|")[1] === myTeam && !isPlayer(driverOf[k]) && (mateIdent = k);
          });
          if (bestQ[myIdent] && mateIdent && bestQ[mateIdent]) {
            entry.quali_time = bestQ[myIdent] / 1000; entry.mate_quali_time = bestQ[mateIdent] / 1000;
          }
        }
        if (!me._ident) {
          if (me.laps) entry.laps = me.laps;
          const done = function (r) { return r && r.status === "Finished" && r.race_time_s > 0; };
          if (done(me) && done(mate) && me.laps === mate.laps) {
            entry.race_time = me.race_time_s + (me.penalty_s || 0);
            entry.bench_race_time = mate.race_time_s + (mate.penalty_s || 0);
          } else {      // a retirement shows as DNF in the race time boxes (no race gap)
            const out = function (r) { return r && ["DNF", "Retired", "DSQ", "Not Classified"].indexOf(r.status) >= 0; };
            if (out(me)) entry.race_dnf = true;
            if (out(mate)) entry.bench_dnf = true;
            if (entry.race_dnf && !entry.bench_dnf && done(mate)) entry.bench_race_time = mate.race_time_s + (mate.penalty_s || 0);
            if (entry.bench_dnf && !entry.race_dnf && done(me)) entry.race_time = me.race_time_s + (me.penalty_s || 0);
          }
        }
        if (Object.keys(entry).length > 2) report.pace.push(entry);
      });
    });
    return report;
  }
  window.F1Import = { loadTelemetry: loadTelemetry, fillWeekend: fillWeekend };

  // ---------------------------------------------------------------- steps, open/close
  function showStep(step) {
    ["files", "progress", "review", "failed"].forEach(function (s) { $("#imp-step-" + s).hidden = s !== step; });
  }
  function addFiles(files) {
    const list = Array.from(files || []).filter(function (f) { return /^image\//.test(f.type); });
    if (!list.length) return;
    Promise.all(list.map(loadImage)).then(function (loaded) {
      loaded.forEach(function (l, i) {
        shots.push({ id: nextId++, name: list[i].name || "pasted image", img: l.img, url: l.url, rotate: 0, fine: 0, crop: null,
          contrast: 1.3, brightness: 0, autoTrim: true, lines: null, text: "" });
      });
      renderShots();
    }).catch(function (err) { toast(err.message, "error"); });
  }
  function reset() {
    shots.forEach(function (s) { URL.revokeObjectURL(s.url); s.img = null; });
    shots = []; rows = []; detected = null; tele = null;
    $("#imp-file").value = ""; $("#imp-raw").textContent = ""; $("#imp-rows").innerHTML = "";
    $("#imp-session").value = "auto"; $("#imp-ignore-detect").checked = false;
    renderShots(); showStep("files");
  }
  function close() { if (dlg.open) dlg.close(); }
  dlg.addEventListener("close", function () { cancelled = true; release(); reset(); });   // nothing is kept after closing
  $("#imp-file").addEventListener("change", function (e) { addFiles(e.target.files); });
  $("#imp-drop").addEventListener("dragover", function (e) { e.preventDefault(); });
  $("#imp-drop").addEventListener("drop", function (e) { e.preventDefault(); addFiles(e.dataTransfer.files); });
  dlg.addEventListener("paste", function (e) { if (e.clipboardData) addFiles(e.clipboardData.files); });
  $("#imp-read").addEventListener("click", read);
  $("#imp-cancel-read").addEventListener("click", cancelRead);
  $("#imp-retry").addEventListener("click", function () { showStep("files"); });
  $("#imp-back").addEventListener("click", function () { showStep("files"); });
  $("#imp-add").addEventListener("click", addManualRow);
  $("#imp-apply").addEventListener("click", apply);
  ["#imp-session2", "#imp-confirm", "#imp-ignore-detect"].forEach(function (sel) { $(sel).addEventListener("change", check); });
  dlg.querySelectorAll("[data-imp-cancel]").forEach(function (b) { b.addEventListener("click", close); });
  // Opening the dialog starts fetching the small OCR script in the background; the big files load on "Read".
  document.querySelectorAll('[data-dialog="import-dialog"]').forEach(function (b) {
    b.addEventListener("click", function () { loadEngine().catch(function () { /* reported when reading */ }); });
  });

  function esc(t) { const d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }
  function toast(msg, kind) { if (window.F1 && window.F1.toast) window.F1.toast(msg, kind); }
  showStep("files");
})();
