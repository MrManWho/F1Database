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
  window.F1TelemetryHooks = {
    applied: function (info) {
      fetch(appliedUrl, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ event_id: eventId, upload_id: info.upload_id, session: info.session, names: info.names }) })
        .catch(function () { /* only a convenience for next time */ });
    }
  };
})();
