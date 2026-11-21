/* Runs the writing log's pure helpers (studio/static/writing.js) in node. Used by tests/test_writing_js.py.

     node writing.js <writing.js>
     output: {"failures": [{"name", "got", "want"}], "checked": n}   */
"use strict";
const fs = require("fs"), vm = require("vm");
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"));
const W = globalThis.WritingLog;
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };

eq("week starts on Monday", [W.weekStart("2026-11-13"), W.weekStart("2026-11-09"), W.weekStart("2026-11-15")], ["2026-11-09", "2026-11-09", "2026-11-09"]);
eq("week across a month and a year", [W.weekStart("2026-12-01"), W.weekStart("2027-01-01")], ["2026-11-30", "2026-12-28"]);
eq("addDays across the DST change", W.addDays("2026-03-28", 2), "2026-03-30");
eq("addDays backwards across a year", W.addDays("2026-01-01", -1), "2025-12-31");

const data = {today: "2026-11-13", days: {"2026-11-13": {poems: {"Sea/Harbour": 120}, books: {"Field Notes": 540}},
  "2026-11-09": {poems: {}, books: {"Field Notes": 610}}, "2026-10-31": {poems: {}, books: {"Field Notes": 100}}}};
eq("weeks", W.periods(data, "weeks", 3).map(p => p.total), [1270, 0, 100]);
eq("weeks: labels", W.periods(data, "weeks", 3).map(p => p.label), ["9–15 Nov", "2–8 Nov", "26 Oct–1 Nov"]);
eq("months", W.periods(data, "months", 2).map(p => [p.label, p.total]), [["Nov 2026", 1270], ["Oct 2026", 100]]);
eq("days: newest first with a label", W.periods(data, "days", 3).map(p => [p.label, p.start, p.end, p.total]),
  [["Fri 13 Nov", "2026-11-13", "2026-11-13", 660], ["Thu 12 Nov", "2026-11-12", "2026-11-12", 0], ["Wed 11 Nov", "2026-11-11", "2026-11-11", 0]]);
eq("period split into poems and books", W.periods(data, "days", 1)[0], {label: "Fri 13 Nov", start: "2026-11-13", end: "2026-11-13", poems: 120, books: {"Field Notes": 540}, total: 660});
eq("a month across a year", W.periods({today: "2026-01-10", days: {}}, "months", 2).map(p => p.label), ["Jan 2026", "Dec 2025"]);
eq("totals", W.totals(data, "2026-11-13"), {poems: 120, books: {"Field Notes": 540}, total: 660});
eq("totals of nothing", W.totals(data, "2026-11-12"), {poems: 0, books: {}, total: 0});
eq("summary", W.summary(data), {today: 660, week: 1270, month: 1270, year: 1370});
eq("goalStats since the first day", W.goalStats({"2026-11-09": 610, "2026-11-13": 540}, 500, "2026-11-13"), {met: 2, of: 5, since: "2026-11-09"});
eq("goalStats with a long history", W.goalStats({"2026-09-01": 900, "2026-11-13": 540}, 500, "2026-11-13"), {met: 1, of: 30, since: null});
eq("goalStats without days", W.goalStats({}, 500, "2026-11-13"), {met: 0, of: 0, since: null});

process.stdout.write(JSON.stringify({failures, checked}));
