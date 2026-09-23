/* Screenshot import: turn OCR text lines into proposed results, matched only against the active grid.
   Pure functions, no network and no DOM: used by importer.js in the browser and by the test suite in Node.
   Nothing here ever invents a driver; anything uncertain is marked for review instead of guessed. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.OcrMatch = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const STATUS_WORDS = { DNF: "DNF", RET: "DNF", RETIRED: "DNF", DNS: "DNS", DSQ: "DSQ", DQ: "DSQ", DISQ: "DSQ", DISQUALIFIED: "DSQ" };
  const SESSIONS = ["qualifying", "sprint", "race"];

  // ---- text normalisation -------------------------------------------------------------------------
  function stripAccents(s) { return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, ""); }
  /** Lower-case letters and single spaces only; common OCR look-alikes folded to letters. */
  function normName(s) {
    return stripAccents(s).toLowerCase()
      .replace(/0/g, "o").replace(/1/g, "l").replace(/5/g, "s").replace(/8/g, "b").replace(/\|/g, "l")
      .replace(/[^a-z\s'-]/g, " ").replace(/['-]/g, "").replace(/\s+/g, " ").trim();
  }
  /** Variants that undo the classic "rn" <-> "m" and "vv" <-> "w" confusions. */
  function variants(s) {
    const out = new Set([s]);
    out.add(s.replace(/rn/g, "m")); out.add(s.replace(/m/g, "rn"));
    out.add(s.replace(/vv/g, "w")); out.add(s.replace(/cl/g, "d"));
    return Array.from(out);
  }

  // ---- similarity ----------------------------------------------------------------------------------
  function levenshtein(a, b) {
    if (a === b) return 0;
    if (!a.length) return b.length;
    if (!b.length) return a.length;
    let prev = Array.from({ length: b.length + 1 }, function (_, i) { return i; });
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      for (let j = 1; j <= b.length; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
      prev = cur;
    }
    return prev[b.length];
  }
  function ratio(a, b) {
    if (!a || !b) return 0;
    return 1 - levenshtein(a, b) / Math.max(a.length, b.length);
  }

  /** Forms a driver's name can appear in on a results screen. */
  function nameForms(name) {
    const n = normName(name);
    const parts = n.split(" ").filter(Boolean);
    const first = parts[0] || "", last = parts[parts.length - 1] || "";
    const forms = { full: n, surname: last, initial: first ? first[0] + " " + last : last, first: first };
    if (parts.length > 2) forms.surname2 = parts.slice(1).join(" ");  // e.g. "De Vries" style surnames
    return forms;
  }

  /**
   * Match OCR'd text to one driver on the active grid.
   * grid: [{id, name, team?, is_player?}]
   * Returns {state: "matched" | "review" | "ambiguous" | "unmatched", driver_id, score, candidates}
   */
  function matchDriver(text, grid, opts) {
    opts = opts || {};
    const raw = normName(text);
    if (!raw || raw.replace(/\s/g, "").length < 2) return { state: "unmatched", driver_id: null, score: 0, candidates: [] };
    const tokens = raw.split(" ");
    // The name is at the start of what's left; trailing words are usually a mangled team name or noise.
    const pieces = new Set();
    for (let k = 1; k <= Math.min(4, tokens.length); k++) {
      const head = tokens.slice(0, k);
      pieces.add(head.join(" "));
      if (k > 1 && head[0].length === 1) pieces.add(head[0] + " " + head.slice(1).join(""));  // "f coi apinto"
      if (k > 1) pieces.add(head.join(""));
    }
    const scored = grid.map(function (d) {
      const f = nameForms(d.name);
      let best = 0;
      const tried = [];
      pieces.forEach(function (p) { variants(p).forEach(function (v) { tried.push(v); }); });
      tried.forEach(function (v) {
        const vt = v.split(" ");
        const vlast = vt[vt.length - 1];
        best = Math.max(best,
          ratio(v, f.full),
          ratio(v, f.initial),
          f.surname2 ? ratio(v, f.surname2) : 0,
          // Surname only (e.g. "VERSTAPPEN"): trust it slightly less than a full match.
          ratio(v, f.surname) * 0.97,
          // "M VERSTAPPEN", "MAX VERSTAPPEN": surname plus matching initial.
          (vt.length > 1 && vt[0][0] === f.first[0]) ? ratio(vlast, f.surname) * 0.99 : 0,
          // Extra words (team names, times) around the name: look for the surname as a whole token.
          (vt.length > 1 && vt.indexOf(f.surname) >= 0 && f.surname.length >= 4) ? 0.9 : 0);
      });
      return { id: d.id, name: d.name, score: Math.round(best * 1000) / 1000 };
    }).sort(function (a, b) { return b.score - a.score; });
    const top = scored[0] || { score: 0 }, second = scored[1] || { score: 0 };
    const high = opts.high || 0.86, low = opts.low || 0.72;
    const candidates = scored.filter(function (c) { return c.score >= low; }).slice(0, 4);
    if (top.score < low) return { state: "unmatched", driver_id: null, score: top.score, candidates: candidates, tokens: tokens };
    if (second.score >= low && top.score - second.score < 0.05) {
      return { state: "ambiguous", driver_id: null, score: top.score, candidates: candidates };
    }
    return { state: top.score >= high ? "matched" : "review", driver_id: top.id, score: top.score, candidates: candidates };
  }

  // ---- line parsing --------------------------------------------------------------------------------
  const TIME_RE = /\b\d{1,2}:\d{2}[.:]\d{1,3}\b|\+\s?\d+[.:]\d+|\b\d+\s?laps?\b|\+\s?\d+\s?laps?/gi;

  /** Remove known team names so they can't be mistaken for part of the driver's name. */
  function stripTeams(text, teams) {
    let out = " " + text + " ";
    (teams || []).slice().sort(function (a, b) { return b.length - a.length; }).forEach(function (t) {
      const esc = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      out = out.replace(new RegExp("\\s" + esc + "(?=\\s)", "gi"), " ");
    });
    return out.trim();
  }

  /** One OCR line -> {position, status, nameText, raw}. Position may be null (read from row order later). */
  function parseLine(line, teams) {
    const raw = String(line || "").trim();
    let text = " " + raw.replace(TIME_RE, " ") + " ";
    let status = null;
    text = text.replace(/\b(DNF|RET|RETIRED|DNS|DSQ|DQ|DISQ|DISQUALIFIED)\b/gi, function (m) {
      status = STATUS_WORDS[m.toUpperCase()];
      return " ";
    });
    if (!status) {
      // Common OCR misreads of the status column, only accepted as a separate word near the end of the line.
      const tail = text.trim().split(/\s+/).slice(-2).join(" ");
      const fuzzy = { DNF: /^(DNE|ONF|0NF|DNP|DN[FE]\.?|D\s?N\s?F)$/i, DNS: /^(DN5|0NS|ONS|D\s?N\s?S)$/i, DSQ: /^(D5Q|DSO|DS0|D5O|D\s?S\s?Q)$/i };
      tail.split(" ").forEach(function (w) {
        Object.keys(fuzzy).forEach(function (k) { if (!status && fuzzy[k].test(w)) { status = k; text = text.replace(new RegExp("\\b" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b"), " "); } });
      });
    }
    let position = null;
    const lead = text.match(/^\s*(?:P\s?)?(\d{1,2})(?:st|nd|rd|th)?[\s.):-]+/i);
    if (lead) {
      position = parseInt(lead[1], 10);
      text = text.slice(lead[0].length);
    }
    text = stripTeams(text, teams)
      .replace(/\b\d+\b/g, " ")                   // points, lap counts, car numbers
      .replace(/[^A-Za-zÀ-ÖØ-öø-ÿ.'\s-]/g, " ")
      .replace(/(^|\s)[.'-]+(?=\s|$)/g, " ")
      .replace(/\s+/g, " ").trim();
    return { raw: raw, position: position, status: status, nameText: text };
  }

  // ---- session detection ---------------------------------------------------------------------------
  function detectSession(fullText) {
    const t = stripAccents(fullText || "").toUpperCase();
    const hits = {
      qualifying: (t.match(/QUALIFYING|QUALI\b|\bQ3\b|\bQ2\b|\bQ1\b|STARTING GRID|POLE/g) || []).length,
      sprint: (t.match(/SPRINT/g) || []).length,
      race: (t.match(/\bRACE\b|GRAND PRIX|FINAL CLASSIFICATION|RACE RESULT/g) || []).length
    };
    if (/SHOOTOUT/.test(t)) return { session: null, confidence: "none", hits: hits, note: "Sprint Shootout screens aren't imported" };
    if (hits.sprint && hits.qualifying) return { session: null, confidence: "none", hits: hits };
    if (hits.sprint) return { session: "sprint", confidence: "high", hits: hits };
    if (hits.qualifying && !hits.race) return { session: "qualifying", confidence: hits.qualifying > 1 ? "high" : "medium", hits: hits };
    if (hits.race && !hits.qualifying) return { session: "race", confidence: hits.race > 1 ? "high" : "medium", hits: hits };
    return { session: null, confidence: "none", hits: hits };
  }

  // ---- building the preview ------------------------------------------------------------------------
  /**
   * shots: [{index, lines: [{text, confidence}]}]; grid: active drivers; teams: team names.
   * Returns rows for the preview: {key, source, raw, driver_id, position, status, confidence, state, notes, candidates}
   */
  function buildRows(shots, grid, teams, maxPos) {
    const rows = [];
    shots.forEach(function (shot) {
      let order = 0;
      shot.lines.forEach(function (ln) {
        const p = parseLine(ln.text, teams);
        if (!p.nameText || p.nameText.replace(/[^a-z]/gi, "").length < 3) return;   // headers, times, noise
        const m = matchDriver(p.nameText, grid);
        if (m.state === "unmatched" && p.position === null && !p.status) return;    // stray words
        order++;
        const notes = [];
        let position = p.position;
        if (position !== null && (position < 1 || position > maxPos)) {
          notes.push("Position P" + position + " is outside the grid (1–" + maxPos + ")");
        }
        const lineConf = typeof ln.confidence === "number" ? ln.confidence : 100;
        let state = m.state === "matched" ? "high" : m.state === "unmatched" ? "unmatched" : "review";
        if (m.state === "ambiguous") notes.push("Could be " + m.candidates.map(function (c) { return c.name; }).join(" or "));
        if (position === null && !p.status) { state = state === "high" ? "review" : state; notes.push("No position read"); }
        if (lineConf < 60 && state === "high") { state = "review"; notes.push("Blurry text"); }
        rows.push({ key: shot.index + ":" + order, source: shot.index, raw: p.raw, nameText: p.nameText,
          driver_id: m.driver_id, position: position, status: p.status || (position ? "Finished" : null),
          confidence: Math.round(Math.min(m.score * 100, lineConf)), state: state, notes: notes,
          candidates: m.candidates, include: true });
      });
    });
    return mergeRows(rows);
  }

  /** Combine rows from several screenshots: drop exact repeats, flag disagreements. */
  function mergeRows(rows) {
    const byDriver = {};
    const out = [];
    rows.forEach(function (r) {
      if (r.driver_id === null) { out.push(r); return; }
      const prev = byDriver[r.driver_id];
      if (!prev) { byDriver[r.driver_id] = r; out.push(r); return; }
      if (prev.position === r.position && prev.status === r.status) {
        // Overlap between screenshots: keep the clearer reading.
        if (r.confidence > prev.confidence) { Object.assign(prev, { raw: r.raw, confidence: r.confidence, source: r.source }); }
        prev.duplicates = (prev.duplicates || 0) + 1;
        return;
      }
      prev.state = "conflict"; r.state = "conflict";
      const msg = "Screenshots disagree: " + fmt(prev) + " (screenshot " + (prev.source + 1) + ") vs " + fmt(r) + " (screenshot " + (r.source + 1) + ")";
      prev.notes.push(msg); r.notes.push(msg);
      r.include = false;   // only one reading of a driver can be applied; the person chooses
      out.push(r);
    });
    // An unreadable row in the overlap between screenshots: if another screenshot has a clear reading at the
    // same position, it's almost certainly the same row. Leave it out (the person can include it again).
    out.forEach(function (r) {
      if (r.driver_id !== null || r.position === null) return;
      const twin = out.find(function (o) { return o !== r && o.driver_id !== null && o.position === r.position && o.source !== r.source; });
      if (twin) { r.include = false; r.notes.push("Probably the same row as P" + twin.position + " in screenshot " + (twin.source + 1) + ", so it's left out"); }
    });
    return out;
  }
  function fmt(r) { return r.status && r.status !== "Finished" ? r.status : r.position ? "P" + r.position : "no position"; }

  /**
   * Check the preview before anything is applied.
   * existing: {driver_id: {position, status}} for the chosen session (only rows that already have data).
   * Returns {blocking, warnings, info, changes}
   */
  function validate(rows, grid, opts) {
    opts = opts || {};
    const maxPos = opts.maxPos || grid.length;
    const session = opts.session, detected = opts.detected;
    const blocking = [], warnings = [], info = [];
    const nameOf = {}; grid.forEach(function (d) { nameOf[d.id] = d.name; });
    if (SESSIONS.indexOf(session) < 0) blocking.push("Choose which session these results are for: Qualifying, Sprint or Race.");
    if (session === "sprint" && !opts.isSprint) blocking.push("This isn't a Sprint weekend, so Sprint results can't be imported.");
    if (detected && detected.session && detected.confidence !== "none" && session && detected.session !== session) {
      blocking.push("The screenshot looks like " + label(detected.session) + " results, but " + label(session) +
        " is selected. Pick the right session before applying.");
    }
    const inc = rows.filter(function (r) { return r.include; });
    const seenDriver = {}, seenPos = {};
    inc.forEach(function (r) {
      const where = r.raw ? "“" + r.raw.slice(0, 40) + "”" : "a row";
      if (r.driver_id === null || r.driver_id === undefined || r.driver_id === "") {
        blocking.push("No driver chosen for " + where + ". Pick one or exclude the row.");
        return;
      }
      if (!nameOf[r.driver_id]) { blocking.push(where + " is matched to a driver who isn't on this season's grid."); return; }
      if (seenDriver[r.driver_id]) blocking.push(nameOf[r.driver_id] + " appears more than once.");
      seenDriver[r.driver_id] = true;
      if (r.status && ["Finished", "DNF", "DNS", "DSQ"].indexOf(r.status) < 0) blocking.push(nameOf[r.driver_id] + " has an unknown status.");
      if (r.position !== null && r.position !== undefined && r.position !== "") {
        const p = Number(r.position);
        if (!Number.isInteger(p) || p < 1 || p > maxPos) blocking.push(nameOf[r.driver_id] + ": P" + r.position + " isn't a possible position (1–" + maxPos + ").");
        else if (r.status === "DNS") blocking.push(nameOf[r.driver_id] + " is DNS but has a position.");
        else if (seenPos[p]) blocking.push("P" + p + " is given to both " + nameOf[seenPos[p]] + " and " + nameOf[r.driver_id] + ".");
        else seenPos[p] = r.driver_id;
      } else if (!r.status || r.status === "Finished") {
        blocking.push(nameOf[r.driver_id] + " has no position or status.");
      }
      if (r.state === "conflict") blocking.push(nameOf[r.driver_id] + ": the screenshots disagree. Choose one reading and exclude the other.");
      else if (r.state === "review" || r.state === "unmatched") warnings.push(nameOf[r.driver_id] + ": low-confidence reading, please check it.");
    });
    // Positions already held by drivers who aren't in this import would end up shared.
    const existing = opts.existing || {};
    Object.keys(existing).forEach(function (id) {
      const cur = existing[id];
      if (seenDriver[id] || !cur || !cur.position || !nameOf[id]) return;
      if (seenPos[cur.position]) blocking.push("P" + cur.position + " already belongs to " + nameOf[id] +
        " (not in this import), so it can't also go to " + nameOf[seenPos[cur.position]] + ".");
    });
    const missing = grid.filter(function (d) { return !seenDriver[d.id]; });
    if (missing.length) warnings.push(missing.length + " driver" + (missing.length === 1 ? "" : "s") + " on the grid " +
      (missing.length === 1 ? "isn't" : "aren't") + " in the import and will be left as they are: " +
      missing.slice(0, 8).map(function (d) { return d.name; }).join(", ") + (missing.length > 8 ? "…" : ""));
    const excluded = rows.length - inc.length;
    if (excluded) info.push(excluded + " row" + (excluded === 1 ? " is" : "s are") + " excluded and won't be applied.");
    const dups = rows.reduce(function (n, r) { return n + (r.duplicates || 0); }, 0);
    if (dups) info.push(dups + " overlapping row" + (dups === 1 ? "" : "s") + " between screenshots merged.");
    const changes = compare(inc.filter(function (r) { return nameOf[r.driver_id]; }), opts.existing || {}, nameOf);
    const replacing = changes.filter(function (c) { return c.action === "replace"; }).length;
    if (replacing) warnings.push(replacing + " existing result" + (replacing === 1 ? "" : "s") + " would be replaced. Review the comparison and confirm.");
    return { blocking: unique(blocking), warnings: unique(warnings), info: info, changes: changes, replacing: replacing };
  }

  /** What applying would do to each driver's existing value. */
  function compare(rows, existing, nameOf) {
    return rows.map(function (r) {
      const cur = existing[r.driver_id] || null;
      const next = { position: r.position === "" || r.position === undefined ? null : r.position === null ? null : Number(r.position),
                     status: r.status || "Finished" };
      const had = cur && (cur.position || (cur.status && cur.status !== "Not Run"));
      const same = had && (cur.position || null) === next.position && (cur.status || "Finished") === next.status;
      return { driver_id: r.driver_id, name: nameOf[r.driver_id], existing: cur, imported: next,
               action: !had ? "add" : same ? "unchanged" : "replace" };
    });
  }
  function label(s) { return { qualifying: "Qualifying", sprint: "Sprint", race: "Race" }[s] || s; }
  function unique(list) { return list.filter(function (v, i) { return list.indexOf(v) === i; }); }

  return { normName: normName, matchDriver: matchDriver, parseLine: parseLine, detectSession: detectSession,
           buildRows: buildRows, mergeRows: mergeRows, validate: validate, compare: compare, ratio: ratio };
});
