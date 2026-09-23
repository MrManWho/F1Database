// Screenshot-import matching tests. Run by tests/test_v119.py (or directly: node tests/js/ocr_match.test.js).
"use strict";
const assert = require("assert");
const M = require("../../static/js/ocr_match.js");

const grid = [
  { id: 1, name: "Max Verstappen", team: "Red Bull Racing" }, { id: 2, name: "Lando Norris", team: "McLaren" },
  { id: 3, name: "Oscar Piastri", team: "McLaren" }, { id: 4, name: "Charles Leclerc", team: "Ferrari" },
  { id: 5, name: "Lewis Hamilton", team: "Ferrari" }, { id: 6, name: "Nico Hulkenberg", team: "Audi" },
  { id: 7, name: "Mick Schumacher", team: "Haas" }, { id: 8, name: "Ralf Schumacher", team: "Haas" },
  // Human drivers (more than two), matched only by being on the grid:
  { id: 20, name: "David Conley", team: "Cadillac", is_player: true }, { id: 21, name: "Carson Hayes", team: "Cadillac", is_player: true },
  { id: 22, name: "Ana Silva", team: "Williams", is_player: true },
];
const teams = Array.from(new Set(grid.map(d => d.team)));
let passed = 0;
function test(name, fn) { fn(); passed++; }

test("exact names", () => {
  assert.strictEqual(M.matchDriver("Max Verstappen", grid).driver_id, 1);
  assert.strictEqual(M.matchDriver("Max Verstappen", grid).state, "matched");
  assert.strictEqual(M.matchDriver("Ana Silva", grid).driver_id, 22);
});
test("fuzzy names and OCR look-alikes", () => {
  assert.strictEqual(M.matchDriver("L. Hami1ton", grid).driver_id, 5);
  assert.strictEqual(M.matchDriver("N0RRIS", grid).driver_id, 2);
  assert.strictEqual(M.matchDriver("Hülkenberg", grid).driver_id, 6);       // accents
  assert.strictEqual(M.matchDriver("HULKENBERG", grid).driver_id, 6);       // missing accents
  assert.strictEqual(M.matchDriver("C.  LECLERC.", grid).driver_id, 4);     // punctuation and spaces
  assert.strictEqual(M.matchDriver("D. CONLEY CADIL I AC", grid).driver_id, 20);  // trailing noise
});
test("initials and surnames only", () => {
  assert.strictEqual(M.matchDriver("M. VERSTAPPEN", grid).driver_id, 1);
  assert.strictEqual(M.matchDriver("PIASTRI", grid).driver_id, 3);
  assert.strictEqual(M.matchDriver("C HAYES", grid).driver_id, 21);
});
test("ambiguous names are never guessed", () => {
  const m = M.matchDriver("SCHUMACHER", grid);
  assert.strictEqual(m.state, "ambiguous"); assert.strictEqual(m.driver_id, null);
  assert.strictEqual(M.matchDriver("M. SCHUMACHER", grid).driver_id, 7);
});
test("unknown drivers are not invented", () => {
  const m = M.matchDriver("Zhou Guanyu", grid);
  assert.strictEqual(m.state, "unmatched"); assert.strictEqual(m.driver_id, null);
});
test("statuses, including common misreads", () => {
  assert.strictEqual(M.parseLine("18 C. LECLERC FERRARI DNF", teams).status, "DNF");
  assert.strictEqual(M.parseLine("22 C HAYES CADILLAC DNE", teams).status, "DNF");
  assert.strictEqual(M.parseLine("L. NORRIS MCLAREN DNS", teams).status, "DNS");
  assert.strictEqual(M.parseLine("5 O. PIASTRI MCLAREN DSQ", teams).status, "DSQ");
  assert.strictEqual(M.parseLine("5 O. PIASTRI MCLAREN D5Q", teams).status, "DSQ");
  assert.strictEqual(M.parseLine("12 L. HAMILTON FERRARI +12.345", teams).position, 12);
});
test("session detection", () => {
  assert.strictEqual(M.detectSession("SPRINT CLASSIFICATION").session, "sprint");
  assert.strictEqual(M.detectSession("QUALIFYING Q3").session, "qualifying");
  assert.strictEqual(M.detectSession("RACE RESULT - GRAND PRIX").session, "race");
  assert.strictEqual(M.detectSession("RESULTS").session, null);
  assert.strictEqual(M.detectSession("SPRINT SHOOTOUT").session, null);
});
const shot = (index, lines) => ({ index, lines: lines.map(t => ({ text: t, confidence: 90 })) });
test("overlapping screenshots merge exact repeats", () => {
  const rows = M.buildRows([shot(0, ["1 M. VERSTAPPEN RED BULL RACING", "2 L. NORRIS MCLAREN"]),
                            shot(1, ["2 L. NORRIS MCLAREN", "3 O. PIASTRI MCLAREN"])], grid, teams, 22);
  assert.deepStrictEqual(rows.map(r => [r.driver_id, r.position]), [[1, 1], [2, 2], [3, 3]]);
  assert.strictEqual(rows[1].duplicates, 1);
});
test("conflicting screenshots are flagged, one reading excluded", () => {
  const rows = M.buildRows([shot(0, ["2 L. NORRIS MCLAREN"]), shot(1, ["4 L. NORRIS MCLAREN"])], grid, teams, 22);
  assert.strictEqual(rows.length, 2);
  assert.ok(rows.every(r => r.state === "conflict"));
  assert.strictEqual(rows.filter(r => r.include).length, 1);
  const v = M.validate(rows, grid, { session: "race" });
  assert.ok(v.blocking.some(b => /disagree/.test(b)));
});
test("duplicate drivers and positions block applying", () => {
  const base = { include: true, state: "high", status: "Finished" };
  let v = M.validate([{ ...base, driver_id: 1, position: 1 }, { ...base, driver_id: 1, position: 2 }], grid, { session: "race" });
  assert.ok(v.blocking.some(b => /more than once/.test(b)));
  v = M.validate([{ ...base, driver_id: 1, position: 1 }, { ...base, driver_id: 2, position: 1 }], grid, { session: "race" });
  assert.ok(v.blocking.some(b => /P1 is given to both/.test(b)));
  v = M.validate([{ ...base, driver_id: 1, position: 40 }], grid, { session: "race", maxPos: 22 });
  assert.ok(v.blocking.some(b => /isn't a possible position/.test(b)));
  v = M.validate([{ ...base, driver_id: 1, position: 3, status: "DNS" }], grid, { session: "race" });
  assert.ok(v.blocking.some(b => /DNS but has a position/.test(b)));
  v = M.validate([{ ...base, driver_id: null, position: 3, raw: "3 ???" }], grid, { session: "race" });
  assert.ok(v.blocking.some(b => /No driver chosen/.test(b)));
});
test("Sprint and Race are never mixed up", () => {
  const rows = [{ include: true, state: "high", status: "Finished", driver_id: 1, position: 1 }];
  let v = M.validate(rows, grid, { session: "race", detected: { session: "sprint", confidence: "high" }, isSprint: true });
  assert.ok(v.blocking.some(b => /looks like Sprint/.test(b)));
  v = M.validate(rows, grid, { session: "sprint", isSprint: false });
  assert.ok(v.blocking.some(b => /isn't a Sprint weekend/.test(b)));
  v = M.validate(rows, grid, { session: "" });
  assert.ok(v.blocking.some(b => /Choose which session/.test(b)));
  v = M.validate(rows, grid, { session: "sprint", detected: { session: "sprint", confidence: "high" }, isSprint: true });
  assert.deepStrictEqual(v.blocking, []);
});
test("existing results are compared and protected", () => {
  const rows = [{ include: true, state: "high", status: "Finished", driver_id: 1, position: 1 },
                { include: true, state: "high", status: "Finished", driver_id: 2, position: 2 },
                { include: true, state: "high", status: "DNF", driver_id: 3, position: null }];
  const existing = { 1: { position: 1, status: "Finished" }, 2: { position: 5, status: "Finished" }, 4: { position: 2, status: "Finished" } };
  const v = M.validate(rows, grid, { session: "race", existing });
  const act = Object.fromEntries(v.changes.map(c => [c.driver_id, c.action]));
  assert.deepStrictEqual(act, { 1: "unchanged", 2: "replace", 3: "add" });
  assert.strictEqual(v.replacing, 1);
  assert.ok(v.blocking.some(b => /P2 already belongs to Charles Leclerc/.test(b)));   // not in import, keeps P2
});
test("human drivers are matched by grid id, however many there are", () => {
  const rows = M.buildRows([shot(0, ["1 D. CONLEY CADILLAC", "2 C. HAYES CADILLAC", "3 A. SILVA WILLIAMS"])], grid, teams, 22);
  assert.deepStrictEqual(rows.map(r => r.driver_id), [20, 21, 22]);
});
test("noise lines are ignored and nothing outside the grid appears", () => {
  const rows = M.buildRows([shot(0, ["RACE RESULT", "POS DRIVER TEAM TIME", "1:32:45.123", "1 M. VERSTAPPEN RED BULL RACING"])], grid, teams, 22);
  assert.strictEqual(rows.length, 1);
  rows.forEach(r => assert.ok(r.driver_id === null || grid.some(d => d.id === r.driver_id)));
});
console.log("ok " + passed + " tests");
