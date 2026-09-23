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
    close();
    toast("Filled " + n + " " + { qualifying: "qualifying", sprint: "Sprint", race: "race" }[session] +
      " result" + (n === 1 ? "" : "s") + " into the table. Check the highlighted boxes; nothing is submitted until you review and complete the weekend.", "success");
  }

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
    shots = []; rows = []; detected = null;
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
