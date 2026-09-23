/* Result cards: draws a square image of the podium (and your weekend) to share or download. */
(function () {
  "use strict";
  var btn = document.getElementById("share-card");
  if (!btn) return;
  var dialog = document.getElementById("share-dialog");
  var canvas = document.getElementById("share-canvas");
  var ctx = canvas.getContext("2d");
  var data = JSON.parse(btn.dataset.card);
  var W = 1080, H = 1080;
  var FONT = '"Titillium Web", "Segoe UI", system-ui, sans-serif';

  function text(str, x, y, size, color, weight, align) {
    ctx.font = (weight || "700") + " " + size + "px " + FONT;
    ctx.fillStyle = color || "#fff";
    ctx.textAlign = align || "left";
    ctx.fillText(str, x, y);
  }
  function fit(str, max, size, weight) {
    ctx.font = (weight || "700") + " " + size + "px " + FONT;
    while (ctx.measureText(str).width > max && str.length > 3) str = str.slice(0, -2);
    return str === "" ? "" : str;
  }
  function round(x, y, w, h, r, fill) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
    ctx.fillStyle = fill; ctx.fill();
  }

  function draw() {
    var bg = ctx.createLinearGradient(0, 0, W, H);
    bg.addColorStop(0, "#0c1019"); bg.addColorStop(1, "#1a0a0c");
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "#e10600"; ctx.fillRect(0, 0, W, 14);
    // diagonal stripes
    ctx.save(); ctx.globalAlpha = 0.06; ctx.fillStyle = "#fff";
    for (var i = -H; i < W; i += 60) { ctx.beginPath(); ctx.moveTo(i, H); ctx.lineTo(i + 30, H); ctx.lineTo(i + 30 + H, 0); ctx.lineTo(i + H, 0); ctx.fill(); }
    ctx.restore();

    text((data.league || "").toUpperCase(), 70, 100, 30, "#e10600", "800");
    text("ROUND " + data.round + " · " + data.season, 70, 145, 28, "#8d97a8", "700");
    text(fit(data.event, W - 140, 84, "900"), 70, 240, 84, "#fff", "900");
    if (data.location) text(data.location, 70, 290, 32, "#8d97a8", "600");

    // podium
    var steps = [{ i: 1, x: 70, h: 250 }, { i: 0, x: 390, h: 310 }, { i: 2, x: 710, h: 210 }];
    var base = data.me ? 760 : 900;
    steps.forEach(function (s) {
      var p = data.podium[s.i];
      if (!p) return;
      var y = base - s.h;
      round(s.x, y, 300, s.h, 18, "rgba(255,255,255,0.06)");
      ctx.fillStyle = p.color || "#e10600"; ctx.fillRect(s.x, y, 300, 10);
      text("P" + (s.i + 1), s.x + 150, y + 90, 72, s.i === 0 ? "#ffd54a" : "#fff", "900", "center");
      var parts = p.name.split(" ");
      var last = parts.pop();
      text(fit(parts.join(" "), 270, 30, "600"), s.x + 150, y + 145, 30, "#c5ccd8", "600", "center");
      text(fit(last.toUpperCase(), 270, 40, "800"), s.x + 150, y + 190, 40, "#fff", "800", "center");
      text(fit(p.team, 270, 26, "600"), s.x + 150, y + 228, 26, "#8d97a8", "600", "center");
    });

    if (data.me) {
      var m = data.me;
      round(70, 800, W - 140, 200, 22, "rgba(225,6,0,0.14)");
      ctx.fillStyle = m.color || "#e10600"; ctx.fillRect(70, 800, 12, 200);
      text("MY WEEKEND", 110, 850, 26, "#e10600", "800");
      text(fit(m.name, 560, 46, "800"), 110, 905, 46, "#fff", "800");
      text(m.team, 110, 950, 28, "#8d97a8", "600");
      text(m.result, W - 110, 905, 90, "#fff", "900", "right");
      var line = "from " + m.grid + " · " + m.points + " pts";
      if (m.gained !== null && m.gained !== undefined && m.gained !== 0) line += " · " + (m.gained > 0 ? "▲" + m.gained : "▼" + (-m.gained));
      text(line, W - 110, 955, 28, "#c5ccd8", "600", "right");
    }
    text("PADDOCK LEGACY", W - 70, H - 30, 22, "rgba(255,255,255,0.35)", "800", "right");
  }

  function blob() {
    return new Promise(function (resolve) { canvas.toBlob(resolve, "image/png"); });
  }

  btn.addEventListener("click", function () {
    draw();
    document.getElementById("share-download").href = canvas.toDataURL("image/png");
    document.getElementById("share-download").download = ("R" + data.round + "-" + data.event).replace(/\W+/g, "-") + ".png";
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", "");
  });
  document.getElementById("share-go").addEventListener("click", function () {
    blob().then(function (b) {
      var file = new File([b], "result.png", { type: "image/png" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        navigator.share({ files: [file], title: data.event, text: data.league + " · R" + data.round + " " + data.event })
          .catch(function () {});
      } else {
        document.getElementById("share-download").click();
      }
    });
  });
})();
