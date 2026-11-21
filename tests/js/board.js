/* Runs the board's pure helpers and save queue (studio/static/board-core.js) in node. Used by tests/test_board_js.py.

     node board.js <prosemirror.js> <book-schema.js> <book-text.js> <board-core.js>
     output: {"failures": [{"name", "got", "want"}], "checked": n}   */
"use strict";
const fs = require("fs"), vm = require("vm");
const [pm, schema, text, core] = process.argv.slice(2);
globalThis.window = globalThis;
for (const f of [pm, schema, text, core]) {
  vm.runInThisContext(fs.readFileSync(f, "utf8"));
  if (f === pm && typeof PM !== "undefined") globalThis.PM = PM;
}
const B = globalThis.BoardCore;
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };
const tick = () => new Promise(r => setImmediate(r));

(async () => {
  // names and constants
  eq("kind names", B.KIND_NAME, {note: "Note", quote: "Quote", source: "Source", clip: "Web clip", image: "Image", piece: "Piece", link: "Link"});
  eq("mime", B.MIME, "application/x-studio-research");
  eq("inline words", B.INLINE_WORDS, 40);
  eq("zoom", B.ZOOM, {min: 0.25, max: 2});

  // addresses
  eq("shared board hash", B.boardHash(null), "#/research");
  eq("a book's board hash", B.boardHash("b1"), "#/book/b1/board");
  eq("a book id is encoded in the hash", B.boardHash("a b/c"), "#/book/a%20b%2Fc/board");
  eq("shared board param", B.boardParam(null), "");
  eq("book param", B.boardParam("b 1"), "b=b%201");
  eq("shared file", B.fileUrl(null, "x.png"), "/researchfiles/_shared/x.png");
  eq("book file with width", B.fileUrl("b1", "x y.png", 320), "/researchfiles/b1/x%20y.png?w=320");

  // frames
  const outer = {id: "f-out", x: 0, y: 0, w: 1000, h: 800, z: 0, title: "Outer"};
  const inner = {id: "f-in", x: 100, y: 100, w: 300, h: 200, z: 1, title: "Inner"};
  eq("frameAt picks the inner frame", B.frameAt([outer, inner], 150, 150), "f-in");
  eq("frameAt picks the outer outside the inner", B.frameAt([outer, inner], 600, 600), "f-out");
  eq("frameAt outside every frame", B.frameAt([outer, inner], 1500, 10), null);
  eq("frameAt without frames", B.frameAt([], 1, 1), null);
  eq("frameAt on the edge", B.frameAt([inner], 100, 100), "f-in");

  // cards
  const item = (id, type, o = {}) => ({id, type, title: id, created: 0, tags: [], pos: {x: 10, y: 20, w: null, h: null, z: 0, frame: null, placed: true}, ...o});
  eq("cardBox of a note: width and height by kind", B.cardBox(item("a", "note")), {x: 10, y: 20, w: 240, h: 160});
  eq("cardBox of a clip", B.cardBox(item("a", "clip")), {x: 10, y: 20, w: 300, h: 280});
  eq("cardBox of an image", B.cardBox(item("a", "image")), {x: 10, y: 20, w: 240, h: 200});
  eq("cardBox of a quote", B.cardBox(item("a", "quote")), {x: 10, y: 20, w: 280, h: 170});
  eq("cardBox of a source", B.cardBox(item("a", "source")), {x: 10, y: 20, w: 260, h: 120});
  eq("cardBox of a piece", B.cardBox(item("a", "piece")), {x: 10, y: 20, w: 260, h: 150});
  eq("cardBox of a link", B.cardBox(item("a", "link")), {x: 10, y: 20, w: 260, h: 160});
  eq("cardBox uses a measured height", B.cardBox(item("a", "note", {_h: 99})).h, 99);
  eq("cardBox prefers the set size", B.cardBox(item("a", "note", {_h: 99, pos: {x: 0, y: 0, w: 400, h: 300}})), {x: 0, y: 0, w: 400, h: 300});

  // reading order
  const fr = (id, x, y) => ({id, x, y, w: 100, h: 100, z: 0, title: id});
  eq("reading order: rows then left", B.readingOrder([fr("c", 500, 10), fr("a", 600, 0), fr("b", 0, 300)]).map(f => f.id), ["c", "a", "b"]);
  eq("reading order: a row within 40 units", B.readingOrder([fr("r", 300, 39), fr("l", 0, 0)]).map(f => f.id), ["l", "r"]);
  eq("reading order: beyond 40 units is the next row", B.readingOrder([fr("r", 0, 41), fr("l", 300, 0)]).map(f => f.id), ["l", "r"]);
  eq("reading order: the next row even when further left", B.readingOrder([fr("low", 0, 41), fr("high", 300, 0)]).map(f => f.id), ["high", "low"]);
  eq("reading order leaves the input alone", (() => { const a = [fr("b", 5, 5), fr("a", 0, 0)]; B.readingOrder(a); return a.map(f => f.id); })(), ["b", "a"]);

  // groups
  const frames = [fr("f2", 0, 300), fr("f1", 0, 0)];
  const items = [item("zeta", "note", {pos: {frame: "f1"}, created: 3}), item("alpha", "quote", {pos: {frame: "f2"}, created: 2}),
    item("loose", "image", {pos: {frame: null}, created: 1}), item("beta", "note", {pos: {frame: "f1"}, created: 5}),
    item("ghost", "note", {pos: {frame: "f-gone"}, created: 4})];
  const g = B.groups(items, frames, "title");
  eq("groups: frames in reading order, then none", g.map(x => x.frame && x.frame.id), ["f1", "f2", null]);
  eq("groups: sorted by title", g[0].items.map(i => i.id), ["beta", "zeta"]);
  eq("groups: items without a frame (or an unknown one) last", g[2].items.map(i => i.id), ["ghost", "loose"]);
  eq("groups by added: newest first", B.groups(items, frames, "added")[0].items.map(i => i.id), ["beta", "zeta"]);
  eq("groups by added: loose newest first", B.groups(items, frames, "added")[2].items.map(i => i.id), ["ghost", "loose"]);
  eq("groups by kind", B.groups(items, frames, "kind")[0].items.map(i => i.type), ["note", "note"]);
  eq("groups by kind: notes before quotes (the kind order), then title", B.groups(items, [], "kind")[0].items.map(i => i.id), ["beta", "ghost", "zeta", "alpha", "loose"]);
  eq("groups: an empty frame is kept", B.groups([], frames, "title").length, 3);
  eq("groups: nothing at all", B.groups([], [], "title"), [{frame: null, items: []}]);

  // fit
  const box = (x, y, w, h) => ({x, y, w, h});
  eq("fitView of two boxes", B.fitView([box(0, 0, 100, 100), box(300, 100, 100, 100)], 1000, 800), {x: 100, y: 200, zoom: 2});
  eq("fitView of a wide spread", B.fitView([box(0, 0, 100, 100), box(3000, 0, 100, 100)], 1000, 800).zoom, (1000 - 96) / 3100);
  eq("fitView clamps to the minimum zoom", B.fitView([box(0, 0, 100, 100), box(100000, 0, 100, 100)], 1000, 800).zoom, 0.25);
  eq("fitView of nothing", B.fitView([], 1000, 800), {x: 0, y: 0, zoom: 1});
  eq("fitView with another pad", B.fitView([box(0, 0, 400, 400)], 500, 500, 50).zoom, 1);

  // quotes
  const words = n => Array.from({length: n}, () => "w").join(" ");
  const prep = (paragraphs, n) => ({kind: "quote", paragraphs, words: n});
  eq("40 words: inline", B.quoteParts(prep([[{type: "text", text: words(40)}]], 40), "“…”").block, false);
  eq("41 words: block", B.quoteParts(prep([[{type: "text", text: words(41)}]], 41), "“…”").block, true);
  eq("two paragraphs: block", B.quoteParts(prep([[], []], 2), "“…”").block, true);
  eq("“…” marks", B.quoteParts(prep([[]], 1), "“…”"), {block: false, open: "“", close: "”"});
  eq("„…” marks", B.quoteParts(prep([[]], 1), "„…”"), {block: false, open: "„", close: "”"});
  eq("«…» marks", B.quoteParts(prep([[]], 1), "«…»"), {block: false, open: "«", close: "»"});
  eq("‘…’ marks", B.quoteParts(prep([[]], 1), "‘…’"), {block: false, open: "‘", close: "’"});
  eq("innerQuotes: straight, „…”", B.innerQuotes('zei "ja"', "„…”"), "zei ‚ja’");
  eq("innerQuotes: straight, “…”", B.innerQuotes('zei "ja" en "nee".', "“…”"), "zei ‘ja’ en ‘nee’.");
  eq("innerQuotes: same-style marks, “…”", B.innerQuotes("zei “ja”", "“…”"), "zei ‘ja’");
  eq("innerQuotes: same-style marks, „…”", B.innerQuotes("zei „ja”", "„…”"), "zei ‚ja’");
  eq("innerQuotes: «…»", B.innerQuotes("zei «ja»", "«…»"), "zei ‹ja›");

  // plain words (Copy text of a clip, the panel's open row)
  eq("plainText: escapes become their characters, markup goes",
    B.plainText("# Kop\r\n\r\nHet *was* \\[1\\] een \\*koude\\* [winter](https://example.org)  \nin het noorden.\n\n\n> Een citaat\\\nover twee regels.\n\n- een\n- twee"),
    "Kop\n\nHet was [1] een *koude* winter\nin het noorden.\n\nEen citaat\nover twee regels.\n\neen\ntwee");
  eq("plainText: a picture is its words, an underscore escaped stays", B.plainText("![De kaart](x.png) snake\\_case"), "De kaart snake_case");
  eq("plainText: nothing", B.plainText(""), "");
  eq("innerQuotes: straight, «…»", B.innerQuotes('zei "ja"', "«…»"), "zei ‹ja›");
  eq("innerQuotes: at the start", B.innerQuotes('"ja" zei ze', "“…”"), "‘ja’ zei ze");
  eq("innerQuotes: no quotes, untouched", B.innerQuotes("niets", "“…”"), "niets");
  eq("innerQuotes: an apostrophe stays", B.innerQuotes("’s avonds", "“…”"), "’s avonds");

  // drag payload
  eq("payload round trip, book", B.readPayload(B.payload("b1", {id: "n-1"})), {board: "b1", id: "n-1"});
  eq("payload round trip, shared", B.readPayload(B.payload(null, {id: "n-1"})), {board: null, id: "n-1"});
  eq("payload is a string", typeof B.payload("b1", {id: "n-1"}), "string");
  eq("garbage payload", B.readPayload("not json"), null);
  eq("empty payload", B.readPayload(""), null);
  eq("payload of the wrong shape", B.readPayload('{"a":1}'), null);
  eq("payload with a non-text id", B.readPayload('{"board":null,"id":5}'), null);
  eq("payload of an array", B.readPayload("[1]"), null);
  eq("payload of null", B.readPayload(null), null);

  // filter
  const t = item("t", "quote", {tags: ["dood", "zee"]});
  eq("no filter matches", B.matches(t, {}), true);
  eq("null filter matches", B.matches(t, null), true);
  eq("kind matches", B.matches(t, {kind: "quote"}), true);
  eq("kind mismatch", B.matches(t, {kind: "note"}), false);
  eq("tag matches", B.matches(t, {tag: "zee"}), true);
  eq("tag mismatch", B.matches(t, {tag: "wind"}), false);
  eq("ids contain", B.matches(t, {ids: new Set(["t"])}), true);
  eq("ids missing", B.matches(t, {ids: new Set(["x"])}), false);
  eq("ids null is no filter", B.matches(t, {ids: null}), true);
  eq("all together", B.matches(t, {kind: "quote", tag: "dood", ids: new Set(["t"])}), true);
  eq("an item without tags", B.matches({id: "u", type: "note"}, {tag: "x"}), false);

  // the save queue, on a fake clock
  function rig(opts = {}) {
    const r = {now: 0, timers: [], saves: [], kept: [], drops: 0, fail: null};
    r.setTimeout = (fn, ms) => { const t = {fn, at: r.now + ms, id: r.timers.length + 1}; r.timers.push(t); return t.id; };
    r.clearTimeout = id => { r.timers = r.timers.filter(t => t.id !== id); };
    r.advance = async ms => {
      const end = r.now + ms;
      for (;;) {
        const due = r.timers.filter(t => t.at <= end).sort((a, b) => a.at - b.at)[0];
        if (!due) break;
        r.timers = r.timers.filter(t => t !== due); r.now = due.at; due.fn(); await tick(); await tick();
      }
      r.now = end; await tick();
    };
    r.saver = new B.Saver({
      base: opts.base || "t0",
      save: async (fields, base, force) => {
        r.saves.push({fields, base, force: !!force});
        if (r.fail) throw r.fail;
        return {id: "n", updated: "t" + r.saves.length};
      },
      keep: f => r.kept.push(f), drop: () => { r.drops++; },
      setTimeout: r.setTimeout, clearTimeout: r.clearTimeout,
    });
    return r;
  }
  const err = (status, data) => Object.assign(new Error("fail"), {status, data});

  let r = rig();
  r.saver.change({title: "a"}); await r.advance(500); r.saver.change({excerpt: "b"}); await r.advance(900);
  eq("save: nothing before the debounce ends", r.saves.length, 0);
  eq("save: pending while waiting", r.saver.pending(), true);
  eq("save: text kept at once", r.kept[r.kept.length - 1], {title: "a", excerpt: "b"});
  await r.advance(200);
  eq("save: two changes within 1 s are one save", r.saves, [{fields: {title: "a", excerpt: "b"}, base: "t0", force: false}]);
  eq("save: kept text dropped after success", r.drops, 1);
  eq("save: nothing pending after", r.saver.pending(), false);
  r.saver.change({title: "c"}); await r.advance(1000);
  eq("save: the next save builds on the server's stamp", r.saves[1], {fields: {title: "c"}, base: "t1", force: false});

  r = rig();
  r.saver.change({title: "x"}); await r.saver.flush();
  eq("flush: saves at once", r.saves.length, 1);
  eq("flush with nothing pending resolves", await rig().saver.flush(), undefined);

  r = rig();
  r.saver.change({title: "x"}); r.saver.flush({leaving: true}); await tick();
  eq("flush leaving: saves and keeps the text", [r.saves.length, r.kept.length > 0], [1, true]);

  r = rig(); r.fail = err(409, {error: "stale", current: {id: "n", title: "theirs", updated: "t9"}});
  r.saver.change({title: "mine"}); await r.advance(1000);
  eq("conflict: set from the server's current", r.saver.conflict, {id: "n", title: "theirs", updated: "t9"});
  eq("conflict: one try", r.saves.length, 1);
  r.fail = null; await r.advance(60000);
  eq("conflict: nothing saved until chosen", r.saves.length, 1);
  r.saver.change({title: "mine 2"}); await r.advance(5000);
  eq("conflict: more typing doesn't save either", r.saves.length, 1);
  eq("conflict: the text stays kept", r.kept[r.kept.length - 1], {title: "mine 2"});
  eq("conflict: still pending", r.saver.pending(), true);
  await r.saver.keepMine();
  eq("keepMine: saves with force on their stamp", r.saves[1], {fields: {title: "mine 2"}, base: "t9", force: true});
  eq("keepMine: conflict cleared", r.saver.conflict, null);
  eq("keepMine: kept text dropped", [r.drops, r.saver.pending()], [1, false]);

  r = rig(); r.fail = err(409, {current: {id: "n", title: "theirs", updated: "t9"}});
  r.saver.change({title: "mine"}); await r.advance(1000);
  const theirs = r.saver.reload();
  eq("reload: returns theirs", theirs, {id: "n", title: "theirs", updated: "t9"});
  eq("reload: forgets mine", [r.saver.conflict, r.saver.pending(), r.drops], [null, false, 1]);
  r.fail = null; r.saver.change({title: "again"}); await r.advance(1000);
  eq("reload: later saves build on theirs", r.saves[1].base, "t9");

  r = rig(); r.fail = err(409, {error: "The board is busy; try again."});
  r.saver.change({title: "x"}); await r.advance(1000);
  eq("busy 409: no conflict", r.saver.conflict, null);
  eq("busy 409: text kept and still pending", [r.saver.pending(), r.kept.length > 0, r.drops], [true, true, 0]);
  r.fail = null; await r.advance(30000);
  eq("busy 409: retried later and saved", [r.saves.length > 1, r.saver.pending(), r.drops], [true, false, 1]);

  r = rig(); r.fail = err(500, {error: "boom"});
  r.saver.change({title: "x"}); await r.advance(1000);
  eq("failure: kept, no conflict, pending", [r.saver.conflict, r.saver.pending(), r.drops], [null, true, 0]);
  eq("failure: the error is shown", !!r.saver.error, true);
  r.fail = new TypeError("network"); await r.advance(30000);
  r.fail = null; await r.advance(30000);
  eq("failure without status: retried and saved", [r.saver.pending(), r.drops, r.saver.error], [false, 1, null]);

  r = rig();
  r.saver.change({title: "a"}); await r.advance(1000);
  r.saver.change({title: "b"});
  eq("pending again after a save", r.saver.pending(), true);
  await r.advance(1000);
  eq("two saves in a row", r.saves.map(s => s.fields.title), ["a", "b"]);

  console.log(JSON.stringify({failures, checked}));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
