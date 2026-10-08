/* Telemetry import (League settings → Telemetry import): loads a session the game's telemetry sent to this league, or
   a recorder's .json file opened from this computer, into the Import dialog's preview (static/js/importer.js).
   After "Apply" it tells the league which game name was which driver, so the next import matches straight away.
   Screenshots never pass through here. */
(function () {
  "use strict";
  const dlg = document.getElementById("import-dialog");
  if (!dlg || !dlg.dataset.teleGet || !window.F1Import) return;
  const getUrl = dlg.dataset.teleGet.replace(/0$/, ""), namesUrl = dlg.dataset.teleNames, appliedUrl = dlg.dataset.teleApplied;
  const eventId = parseInt(dlg.dataset.eventId, 10);
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  function toast(msg, kind) { if (window.F1 && window.F1.toast) window.F1.toast(msg, kind); }
  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok || !j.ok) throw new Error(j.error || "Couldn't load that (" + r.status + ")");
        return j;
      });
    });
  }
  dlg.querySelectorAll("[data-tele-id]").forEach(function (b) {
    b.addEventListener("click", function () {
      const id = parseInt(b.dataset.teleId, 10);
      b.disabled = true;
      getJSON(getUrl + id).then(function (j) { window.F1Import.loadTelemetry(j.upload, id, j.names || {}); })
        .catch(function (err) { toast(err.message, "error"); })
        .then(function () { b.disabled = false; });
    });
  });
  const file = document.getElementById("imp-tele-file");
  if (file) file.addEventListener("change", function (e) {
    const f = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!f) return;
    f.text().then(function (text) {
      let data;
      try { data = JSON.parse(text); } catch (err) { throw new Error(f.name + " isn't a telemetry results file"); }
      return getJSON(namesUrl).then(function (j) { window.F1Import.loadTelemetry(data, null, j.names || {}); },
        function () { window.F1Import.loadTelemetry(data, null, {}); });
    }).catch(function (err) { toast(err.message, "error"); });
  });
  // "Fill the whole weekend": every session of this round from the game, then weather and race times, then a reload
  // so everything shows. Results go into the results table as a draft; nothing is submitted.
  const roundUrl = dlg.dataset.teleRound, extrasUrl = dlg.dataset.teleExtras, DONE_KEY = "f1-tele-filled:" + eventId;
  function postJSON(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, Accept: "application/json" },
      body: JSON.stringify(body) }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok || !j.ok) throw new Error(j.error || "Couldn't save that (" + r.status + ")");
        return j;
      });
    });
  }
  function summary(rep, server) {
    const bits = [];
    if (rep.filled.length) bits.push("Results: " + rep.filled.join(", ") + ".");
    (rep.extra_notes || []).forEach(function (n) { bits.push(n); });
    if (server.done && server.done.length) bits.push("Saved " + server.done.join("; ") + ".");
    (server.notes || []).forEach(function (n) { bits.push(n); });
    if (rep.missing.length) bits.push("Not matched, so left for you: " + rep.missing.slice(0, 6).join(", ") + (rep.missing.length > 6 ? " and " + (rep.missing.length - 6) + " more" : "") + ".");
    if (rep.review) bits.push(rep.review + " driver match" + (rep.review === 1 ? " is a best guess" : "es are best guesses") + ": check the names.");
    bits.push("Review everything, then submit as usual.");
    return bits.join(" ");
  }
  document.querySelectorAll("[data-tele-fill]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (!window.F1Entry || !window.F1Import.fillWeekend) return;
      document.querySelectorAll("[data-tele-fill]").forEach(function (x) { x.disabled = true; });
      let rep = null;
      getJSON(roundUrl).then(function (j) {
        rep = window.F1Import.fillWeekend(j.sessions, j.names || {});
        if (dlg.open) dlg.close();
        return postJSON(extrasUrl, { sessions: rep.sessions, pace: j.pace ? rep.pace : [], names: rep.names, upload_ids: rep.upload_ids });
      }).then(function (server) {
        const text = summary(rep, server);
        return window.F1Entry.flush().then(function (saved) {
          if (saved) {
            try { sessionStorage.setItem(DONE_KEY, text); } catch (e) { /* private mode: no message after reload */ }
            location.reload();
          } else {
            toast(text + " The results table couldn't save yet: fix the highlighted boxes. Reload to see the weather and times.", "error");
          }
        });
      }).catch(function (err) { toast(err.message, "error"); })
        .then(function () { document.querySelectorAll("[data-tele-fill]").forEach(function (x) { x.disabled = false; }); });
    });
  });
  try {
    const done = sessionStorage.getItem(DONE_KEY);
    if (done) { sessionStorage.removeItem(DONE_KEY); setTimeout(function () { toast("Filled from the game. " + done, "success"); }, 300); }
  } catch (e) { /* private mode */ }
  window.F1TelemetryHooks = {
    applied: function (info) {
      fetch(appliedUrl, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ event_id: eventId, upload_id: info.upload_id, session: info.session, names: info.names }) })
        .catch(function () { /* only a convenience for next time */ });
    }
  };
})();
