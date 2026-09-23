/* Small dependency-free line charts: legend, direct end labels, crosshair tooltip, data table. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const SLOTS = 8;

  function el(tag, attrs, parent) {
    const node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  function niceMax(v) {
    if (v <= 0) return 1;
    const exp = Math.pow(10, Math.floor(Math.log10(v)));
    const f = v / exp;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp;
  }

  function ticks(min, max, count) {
    const step = niceMax((max - min) / count);
    const out = [];
    for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Math.round(v * 100) / 100);
    return out;
  }

  function assignSlots(series) {
    let next = 1;
    const used = {};
    series.forEach(function (s) { if (s.slot) used[s.slot] = true; });
    series.forEach(function (s) {
      if (!s.slot) {
        while (used[next] && next < SLOTS) next++;
        s.slot = next;
        used[next] = true;
      }
    });
  }

  function render(host) {
    const data = JSON.parse(host.dataset.chart);
    const labels = data.labels || [];
    const series = (data.series || []).filter(function (s) { return s.values && s.values.length; });
    host.innerHTML = "";
    if (!labels.length || !series.length) {
      host.innerHTML = '<p class="muted small chart-empty">No results to chart yet.</p>';
      return;
    }
    assignSlots(series);
    const multi = series.length > 1;

    if (multi) {
      const legend = document.createElement("div");
      legend.className = "chart-legend";
      series.forEach(function (s) {
        const item = document.createElement("span");
        item.innerHTML = '<i style="background: var(--series-' + s.slot + ')"></i>';
        item.appendChild(document.createTextNode(s.name));
        legend.appendChild(item);
      });
      host.appendChild(legend);
    }

    const width = Math.max(280, host.clientWidth);
    const height = parseInt(host.dataset.height || "240", 10);
    const directLabels = multi && series.length <= 4 && width > 520;
    const pad = { top: 12, right: directLabels ? 118 : 16, bottom: 26, left: 40 };
    const w = width - pad.left - pad.right;
    const h = height - pad.top - pad.bottom;

    let lo = Infinity, hi = -Infinity;
    series.forEach(function (s) { s.values.forEach(function (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); }); });
    if (data.zero || lo > 0) lo = Math.min(0, lo);
    if (lo < 0) { const m = niceMax(Math.max(Math.abs(lo), Math.abs(hi))); lo = -m; hi = m; }
    else hi = niceMax(hi);
    if (hi === lo) hi = lo + 1;

    const x = function (i) { return pad.left + (labels.length === 1 ? w / 2 : (i / (labels.length - 1)) * w); };
    const y = function (v) { return pad.top + h - ((v - lo) / (hi - lo)) * h; };

    const svg = el("svg", { width: width, height: height, class: "chart-svg", role: "img",
      "aria-label": (data.yLabel || "Chart") + " by round" }, host);

    ticks(lo, hi, 4).forEach(function (t) {
      el("line", { x1: pad.left, x2: pad.left + w, y1: y(t), y2: y(t), class: t === 0 && lo < 0 ? "chart-zero" : "chart-grid" }, svg);
      const lab = el("text", { x: pad.left - 6, y: y(t) + 4, class: "chart-tick", "text-anchor": "end" }, svg);
      lab.textContent = t;
    });
    const every = Math.max(1, Math.ceil(labels.length / Math.max(2, Math.floor(w / 48))));
    labels.forEach(function (l, i) {
      if (i % every && i !== labels.length - 1) return;
      const lab = el("text", { x: x(i), y: height - 6, class: "chart-tick", "text-anchor": "middle" }, svg);
      lab.textContent = l;
    });
    el("line", { x1: pad.left, x2: pad.left + w, y1: pad.top + h, y2: pad.top + h, class: "chart-axis" }, svg);

    series.forEach(function (s) {
      const d = s.values.map(function (v, i) { return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); }).join(" ");
      el("path", { d: d, class: "chart-line" + (s.player ? " is-player" : ""), style: "stroke: var(--series-" + s.slot + ")" }, svg);
      if (s.values.length === 1) el("circle", { cx: x(0), cy: y(s.values[0]), r: 4, style: "fill: var(--series-" + s.slot + ")" }, svg);
    });

    if (directLabels) {
      const placed = series.map(function (s) {
        return { s: s, y: y(s.values[s.values.length - 1]) };
      }).sort(function (a, b) { return a.y - b.y; });
      for (let i = 1; i < placed.length; i++) {
        if (placed[i].y - placed[i - 1].y < 13) placed[i].y = placed[i - 1].y + 13;
      }
      placed.forEach(function (p) {
        const t = el("text", { x: pad.left + w + 8, y: p.y + 4, class: "chart-direct" }, svg);
        t.textContent = shortName(p.s.name) + " " + p.s.values[p.s.values.length - 1];
      });
    }

    // Crosshair + tooltip
    const cross = el("line", { y1: pad.top, y2: pad.top + h, class: "chart-cross", visibility: "hidden" }, svg);
    const dots = series.map(function (s) {
      return el("circle", { r: 4.5, class: "chart-dot", style: "fill: var(--series-" + s.slot + ")", visibility: "hidden" }, svg);
    });
    const tip = document.createElement("div");
    tip.className = "chart-tip";
    tip.hidden = true;
    host.appendChild(tip);
    const hit = el("rect", { x: pad.left - 10, y: 0, width: w + 20, height: height, fill: "transparent" }, svg);

    function show(clientX) {
      const box = svg.getBoundingClientRect();
      const px = clientX - box.left;
      const i = labels.length === 1 ? 0 : Math.max(0, Math.min(labels.length - 1, Math.round(((px - pad.left) / w) * (labels.length - 1))));
      cross.setAttribute("x1", x(i));
      cross.setAttribute("x2", x(i));
      cross.setAttribute("visibility", "visible");
      const rows = series.map(function (s, k) {
        dots[k].setAttribute("cx", x(i));
        dots[k].setAttribute("cy", y(s.values[i]));
        dots[k].setAttribute("visibility", "visible");
        return { s: s, v: s.values[i] };
      }).sort(function (a, b) { return b.v - a.v; });
      tip.innerHTML = "<strong>" + labels[i] + "</strong>" + rows.map(function (r) {
        return '<div><i style="background: var(--series-' + r.s.slot + ')"></i><span>' + escapeHtml(r.s.name) + "</span><b>" + r.v + "</b></div>";
      }).join("");
      tip.hidden = false;
      const left = x(i) + 14 + tip.offsetWidth > width ? x(i) - tip.offsetWidth - 14 : x(i) + 14;
      tip.style.left = Math.max(0, left) + "px";
      tip.style.top = (multi ? 34 : 4) + "px";
    }
    function hide() {
      cross.setAttribute("visibility", "hidden");
      dots.forEach(function (d) { d.setAttribute("visibility", "hidden"); });
      tip.hidden = true;
    }
    hit.addEventListener("mousemove", function (e) { show(e.clientX); });
    hit.addEventListener("mouseleave", hide);
    hit.addEventListener("touchstart", function (e) { show(e.touches[0].clientX); }, { passive: true });
    hit.addEventListener("touchmove", function (e) { show(e.touches[0].clientX); }, { passive: true });

    // Table view (accessible alternative to the picture)
    const details = document.createElement("details");
    details.className = "chart-table";
    details.innerHTML = "<summary>Show data</summary>";
    const table = document.createElement("table");
    table.className = "data-table compact";
    table.innerHTML = "<thead><tr><th></th>" + series.map(function (s) { return "<th>" + escapeHtml(s.name) + "</th>"; }).join("") +
      "</tr></thead><tbody>" + labels.map(function (l, i) {
        return "<tr><td>" + l + "</td>" + series.map(function (s) { return '<td class="num">' + s.values[i] + "</td>"; }).join("") + "</tr>";
      }).join("") + "</tbody>";
    details.appendChild(table);
    host.appendChild(details);
  }

  function shortName(name) {
    const parts = name.split(" ");
    return parts.length > 1 && name.length > 14 ? parts[parts.length - 1] : name;
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderAll() { document.querySelectorAll("[data-chart]").forEach(render); }
  renderAll();
  let timer;
  window.addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(renderAll, 150); });
})();
