/* Runs the research board canvas's helpers (studio/static/board-canvas.js, the part above create()) in node: the view
   (points, zoom around a point, the zoom steps, fitting, the view kept in the browser), the selection box, where
   dragged and nudged cards land and in which frame, a frame moved with its cards, resizing, what a drop holds, a
   card's HTML (escaped, the style's quote marks) and the undo stack. Used by tests/test_board_js.py.

     node board_canvas.js <prosemirror.js> <book-schema.js> <book-text.js> <board-core.js> <board-canvas.js>
     output: {"failures": [{"name", "got", "want"}], "checked": n}   */
"use strict";
const fs = require("fs"), vm = require("vm");
const files = process.argv.slice(2);
globalThis.window = globalThis;
for (const f of files) {
  vm.runInThisContext(fs.readFileSync(f, "utf8"));
  if (f === files[0] && typeof PM !== "undefined") globalThis.PM = PM;
}
const V = globalThis.BoardCanvas;
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };
const near = (name, got, want, e = 1e-9) => { checked++; if (!(Math.abs(got - want) <= e)) failures.push({name, got, want}); };

(async () => {
  eq("the module loads without a page", typeof V.create, "function");
  eq("nothing ran at load", typeof globalThis.document, "undefined");

  // the view: screen = board * zoom + {x, y}
  const view = {x: 100, y: 50, zoom: 2};
  eq("boardPoint", V.boardPoint(view, 300, 250), {x: 100, y: 100});
  eq("screenPoint", V.screenPoint(view, 100, 100), {x: 300, y: 250});
  eq("boardPoint and screenPoint undo each other", V.screenPoint(view, ...Object.values(V.boardPoint(view, 37, 81))), {x: 37, y: 81});
  const z = V.zoomAround(view, 1, 300, 250);
  eq("zoomAround keeps the point under the pointer", V.boardPoint(z, 300, 250), {x: 100, y: 100});
  eq("zoomAround zooms", z.zoom, 1);
  eq("zoomAround stops at 200%", V.zoomAround(view, 9, 0, 0).zoom, 2);
  eq("zoomAround stops at 25%", V.zoomAround(view, 0.01, 0, 0).zoom, 0.25);
  eq("zoomAround at the limit keeps the point", V.boardPoint(V.zoomAround({x: 0, y: 0, zoom: 1}, 9, 400, 300), 400, 300), {x: 400, y: 300});
  eq("zoom step up from 100%", V.zoomStep(1, 1), 1.25);
  eq("zoom step down from 100%", V.zoomStep(1, -1), 0.75);
  eq("zoom step up from between steps", V.zoomStep(0.9, 1), 1);
  eq("zoom step down from between steps", V.zoomStep(0.9, -1), 0.75);
  eq("zoom step up at the top", V.zoomStep(2, 1), 2);
  eq("zoom step down at the bottom", V.zoomStep(0.25, -1), 0.25);
  eq("a wheel notch down zooms out", V.wheelZoom(100) < 1, true);
  eq("a wheel notch up zooms in", V.wheelZoom(-100) > 1, true);
  near("a notch in and a notch out come back", V.wheelZoom(100) * V.wheelZoom(-100), 1);
  near("a large delta is one notch", V.wheelZoom(1000), V.wheelZoom(50));
  eq("a pinch's small delta is a small step", V.wheelZoom(4) > 0.98 && V.wheelZoom(4) < 1, true);

  // fitting
  const box = (x, y, w, h) => ({x, y, w, h});
  eq("fit: nothing on the board", V.fitBoxes([], 1000, 800), {x: 48, y: 48, zoom: 1});
  eq("fit: a small board is shown at 100%, centred", V.fitBoxes([box(0, 0, 200, 100)], 1000, 800), {x: 400, y: 350, zoom: 1});
  eq("fit: never closer than asked", V.fitBoxes([box(10, 10, 100, 100)], 1000, 800, 1.5).zoom, 1.5);
  eq("fit: a large board as BoardCore fits it", V.fitBoxes([box(0, 0, 4000, 100)], 1000, 800), globalThis.BoardCore.fitView([box(0, 0, 4000, 100)], 1000, 800));

  // the view kept in the browser
  eq("readView of JSON", V.readView('{"x":10,"y":-20,"zoom":0.5}'), {x: 10, y: -20, zoom: 0.5});
  eq("readView of an object", V.readView({x: 1, y: 2, zoom: 1, extra: 3}), {x: 1, y: 2, zoom: 1});
  eq("readView of garbage", V.readView("{nope"), null);
  eq("readView of nothing", V.readView(null), null);
  eq("readView of a zoom out of range", V.readView({x: 0, y: 0, zoom: 5}), null);
  eq("readView of a missing number", V.readView({x: 0, zoom: 1}), null);
  eq("readView of text numbers", V.readView({x: "1", y: 0, zoom: 1}), null);
  eq("the view's key for a book", V.viewKey("b1"), "board.view.b1");
  eq("the view's key for the shared board", V.viewKey("_shared"), "board.view._shared");
  eq("the view's key for null", V.viewKey(null), "board.view._shared");

  // the selection box
  eq("rectOf from any two corners", V.rectOf({x: 50, y: 10}, {x: 10, y: 40}), {x: 10, y: 10, w: 40, h: 30});
  const cards = [{id: "a", x: 0, y: 0, w: 100, h: 100}, {id: "b", x: 200, y: 0, w: 100, h: 100}, {id: "c", x: 0, y: 300, w: 100, h: 50}];
  eq("a box touching one card", V.within(cards, {x: 50, y: 50, w: 20, h: 20}), ["a"]);
  eq("a box across two cards", V.within(cards, {x: 90, y: 90, w: 120, h: 10}), ["a", "b"]);
  eq("a box in the gap", V.within(cards, {x: 120, y: 0, w: 50, h: 300}), []);
  eq("a box only touching an edge doesn't take it", V.within(cards, {x: 100, y: 0, w: 50, h: 50}), []);
  eq("a box around everything", V.within(cards, {x: -10, y: -10, w: 400, h: 400}), ["a", "b", "c"]);

  // dropping dragged cards
  const frames = [{id: "f-big", x: 0, y: 0, w: 1000, h: 1000, z: 0}, {id: "f-small", x: 500, y: 500, w: 300, h: 300, z: 1}];
  const moving = [{id: "n1", x: 10, y: 10, w: 240, h: 100, z: 5}, {id: "n2", x: 20, y: 400, w: 240, h: 100, z: 2}];
  eq("dropped: moved, rounded, in the frame at the centre", V.dropped(moving, 0.4, -0.6, frames),
    {n1: {x: 10, y: 9, frame: "f-big"}, n2: {x: 20, y: 399, frame: "f-big"}});
  eq("dropped: into the smaller frame", V.dropped([moving[0]], 520, 540, frames).n1.frame, "f-small");
  eq("dropped: out of every frame", V.dropped([moving[0]], 2000, 0, frames).n1.frame, null);
  eq("dropped: the centre decides, not the corner", V.dropped([{id: "x", x: 900, y: 10, w: 240, h: 100}], 0, 0, frames).x.frame, null);
  eq("dropped: raised above the top in their own order", V.dropped(moving, 0, 0, frames, 9), {n2: {x: 20, y: 400, frame: "f-big", z: 10}, n1: {x: 10, y: 10, frame: "f-big", z: 11}});
  eq("dropped: without a top, no z", "z" in V.dropped(moving, 1, 1, frames).n1, false);
  eq("dropped: no frames", V.dropped(moving, 0, 0, []).n1.frame, null);
  eq("dropped: the input is left alone", moving[0], {id: "n1", x: 10, y: 10, w: 240, h: 100, z: 5});

  // a frame moved with its cards
  eq("frameMoved: the frame and its cards by the same whole units",
    V.frameMoved({id: "f-a", x: 100, y: 100, w: 400, h: 300}, [{id: "q", x: 124, y: 156}, {id: "r", x: 124.5, y: 300}], 10.4, -20.6),
    {items: {q: {x: 134, y: 135, frame: "f-a"}, r: {x: 135, y: 279, frame: "f-a"}}, frames: [{id: "f-a", x: 110, y: 79}]});
  eq("frameMoved: an empty frame", V.frameMoved({id: "f-a", x: 0, y: 0}, [], 5, 5), {items: {}, frames: [{id: "f-a", x: 5, y: 5}]});

  // resizing
  const min = {w: 160, h: 80}, max = {w: 1200, h: 2000};
  eq("resized: grows by the drag", V.resized(240, 160, 60.4, 39.6, min, max), {w: 300, h: 200});
  eq("resized: not below the minimum", V.resized(240, 160, -500, -500, min, max), {w: 160, h: 80});
  eq("resized: not above the maximum", V.resized(240, 160, 5000, 5000, min, max), {w: 1200, h: 2000});
  eq("resized: a frame keeps 160 × 160", V.resized(480, 320, -1000, -1000, {w: 160, h: 160}, {w: 1e6, h: 1e6}), {w: 160, h: 160});

  // drops
  const file = {name: "a.png"};
  eq("drop: files first", V.readDrop({files: [file], uris: "https://x.org", text: "hi"}), {files: [file]});
  eq("drop: a link from another tab", V.readDrop({uris: "# comment\r\nhttps://example.org/a?b=1\r\nhttps://other.org", text: "Example"}), {url: "https://example.org/a?b=1"});
  eq("drop: a uri-list without a web address falls to the text", V.readDrop({uris: "file:///C:/x.txt", text: "some words"}), {text: "some words"});
  eq("drop: text that is one address", V.readDrop({text: "  http://example.org/page  "}), {url: "http://example.org/page"});
  eq("drop: text with an address in it is text", V.readDrop({text: "see https://example.org"}), {text: "see https://example.org"});
  eq("drop: text", V.readDrop({text: "Het was een koude winter.\n\nTwee."}), {text: "Het was een koude winter.\n\nTwee."});
  eq("drop: blank", V.readDrop({text: "   "}), null);
  eq("drop: nothing", V.readDrop({}), null);
  eq("drop: not a web address", V.readDrop({text: "javascript:alert(1)"}), {text: "javascript:alert(1)"});
  const own = "http://127.0.0.1:4747/researchfiles/_shared/pier.png?w=960";
  eq("drop: a picture of Studio's own (the item panel's) is nothing", V.readDrop({uris: own, text: own, origin: "http://127.0.0.1:4747"}), null);
  eq("drop: its address as text is nothing too", V.readDrop({text: own, origin: "http://127.0.0.1:4747"}), null);
  eq("drop: another port is another site", V.readDrop({uris: own, origin: "http://127.0.0.1:4748"}), {url: own});

  // what a press or a double-click is on: elements as closest() sees them
  const node = (cls, parent = null, data = {}) => ({cls, parent, dataset: data,
    closest(sel) { for (let n = this; n; n = n.parent) if (n.cls.includes(sel.slice(1))) return n; return null; }});
  const stage = node(["bc"]);
  const cardEl = node(["bc-card"], node(["bc-cards"], stage), {id: "ask-about-the-boat"});
  const words = node(["bc-x"], node(["bc-in"], cardEl));
  const frameEl = node(["bc-frame"], node(["bc-frames"], stage), {id: "f-house"});
  const bar = node(["bc-fbar"], frameEl), title = node(["bc-ft"], bar);
  eq("target: the words on a card are the card", V.targetOf(words), {what: "card", id: "ask-about-the-boat"});
  eq("target: the card itself", V.targetOf(cardEl), {what: "card", id: "ask-about-the-boat"});
  eq("target: a card's corner", V.targetOf(node(["bc-grip"], cardEl)), {what: "grip", id: "ask-about-the-boat"});
  eq("target: a frame's title", V.targetOf(title), {what: "fbar", id: "f-house"});
  eq("target: a frame's corner", V.targetOf(node(["bc-fgrip"], frameEl)), {what: "fgrip", id: "f-house"});
  eq("target: the title being typed", V.targetOf(node(["bc-fin"], bar)), {what: "field", id: null});
  eq("target: the stage", V.targetOf(stage), {what: "empty", id: null});
  eq("target: inside a frame, off its title", V.targetOf(frameEl), {what: "empty", id: null});
  eq("target: nothing", V.targetOf(null), {what: "empty", id: null});

  // quote marks
  eq("marks: “…”", V.marks("“…”"), ["“", "”"]);
  eq("marks: „…”", V.marks("„…”"), ["„", "”"]);
  eq("marks: «…»", V.marks("«…»"), ["«", "»"]);
  eq("marks: none given", V.marks(null), ["“", "”"]);

  // a card's HTML
  const item = (type, o = {}) => ({id: "it", type, title: "", excerpt: "", tags: [], ...o});
  const opts = (o = {}) => ({title: {text: "", own: false}, source: "", kind: "Note", quotes: ["“", "”"], ...o});
  const html = V.cardHtml(item("note", {excerpt: "<b>bold</b> & 'so' \"on\"", tags: ["zee", "<i>"]}), opts());
  eq("card: the kind first", html.startsWith(`<p class="bc-k">Note</p>`), true);
  eq("card: words escaped", html.includes("&lt;b&gt;bold&lt;/b&gt; &amp; &#39;so&#39; &quot;on&quot;"), true);
  eq("card: tags escaped, a quiet line", html.includes(`<p class="bc-tags">zee, &lt;i&gt;</p>`), true);
  eq("card: no raw markup from the item", /<b>|<i>/.test(html), false);
  eq("card: a title of its own", V.cardHtml(item("note", {excerpt: "x"}), opts({title: {text: "A <title>", own: true}})).includes(`<p class="bc-t">A &lt;title&gt;</p>`), true);
  eq("card: first words aren't shown as a title", V.cardHtml(item("note", {excerpt: "first words"}), opts({title: {text: "first words", own: false}})).includes("bc-t"), false);
  eq("card: an empty note says so", V.cardHtml(item("note"), opts()).includes("Empty note"), true);
  const long = "w".repeat(280);
  eq("card: a cut text ends in …", V.cardHtml(item("note", {excerpt: long}), opts()).includes(long + "…"), true);
  eq("card: a short text doesn't", V.cardHtml(item("note", {excerpt: "short"}), opts()).includes("short…"), false);
  const q = V.cardHtml(item("quote", {excerpt: "Het water kwam"}), opts({kind: "Quote", quotes: ["„", "”"], source: "van Dijk 1998, p. 12"}));
  eq("card: a quote between the style's marks, in the serif", q.includes(`<p class="bc-q">„Het water kwam”</p>`), true);
  eq("card: a quote's source line (board.js's HTML, as it is)", q.includes(`<p class="bc-s">van Dijk 1998, p. 12</p>`), true);
  eq("card: a quote's marks escaped with its words", V.cardHtml(item("quote", {excerpt: "a<b"}), opts({quotes: ["“", "”"]})).includes("“a&lt;b”"), true);
  eq("card: a quote without words", V.cardHtml(item("quote"), opts()).includes("No words yet"), true);
  const clip = V.cardHtml(item("clip", {excerpt: "page text", thumb: "/researchfiles/_shared/a%20b.jpg?w=640&v=1"}), opts({kind: "Web clip", title: {text: "Flood", own: true}, source: "example.org"}));
  eq("card: a clip's picture, lazy, escaped", clip.includes(`<img class="bc-img bc-shot" src="/researchfiles/_shared/a%20b.jpg?w=640&amp;v=1" alt="Flood" loading="lazy"`), true);
  eq("card: a clip with a picture shows no text", clip.includes("page text"), false);
  eq("card: the picture comes before the title", clip.indexOf("bc-img") < clip.indexOf("bc-t"), true);
  eq("card: a clip without a picture shows its first lines", V.cardHtml(item("clip", {excerpt: "page text"}), opts()).includes("page text"), true);
  const img = V.cardHtml(item("image", {excerpt: "a caption", thumb: "/researchfiles/b1/x.png?w=640&v=2"}), opts({kind: "Image"}));
  eq("card: an image's picture at its own shape", img.includes(`class="bc-img" src=`), true);
  eq("card: an image's caption, held to three lines", img.includes(`<p class="bc-x bc-small bc-clamp bc-c3">a caption</p>`), true);
  eq("card: an image's title, source and tags come after its picture and caption",
    (h => ["bc-img", "bc-t", "bc-x", "bc-s", "bc-tags"].map(c => h.indexOf(`class="${c}`)).every((n, i, a) => n > 0 && (!i || n > a[i - 1])))(
      V.cardHtml(item("image", {excerpt: "cap", tags: ["t"], thumb: "/x.png"}), opts({title: {text: "The house, front", own: true}, source: "Jansen 1998"}))), true);
  eq("card: a source's notes aren't held short", V.cardHtml(item("source", {excerpt: "notes"}), opts()).includes(`<p class="bc-x bc-small">notes</p>`), true);
  eq("card: no picture for a note with a thumb", V.cardHtml(item("note", {thumb: "/x.png"}), opts()).includes("<img"), false);
  eq("card: a picture's address with a quote in it is escaped", V.cardHtml(item("image", {thumb: '/x.png?"onerror="x'}), opts()).includes('src="/x.png?&quot;onerror=&quot;x"'), true);
  eq("card: a link's original board", V.cardHtml(item("note", {excerpt: "x", link: {board: null, board_title: "Shared board", missing: false}}), opts()).includes("From the shared board"), true);
  eq("card: a link on a book's board", V.cardHtml(item("note", {excerpt: "x", link: {board: "b1", board_title: "A <Year>", missing: false}}), opts()).includes("From A &lt;Year&gt;"), true);
  eq("card: a link whose original is gone", V.cardHtml(item("link", {link: {board: "b1", missing: true}}), opts({kind: "Link"})),
    `<p class="bc-k">Link</p><p class="bc-x bc-none">The original of this link is gone.</p>`);
  eq("card: a file that can't be read", V.cardHtml(item("note", {id: "x<y", error: "bad"}), opts()), `<p class="bc-k">Note</p><p class="bc-t">x&lt;y.md</p><p class="bc-s bc-bad">Can't be read</p>`);
  eq("card: the kind escaped", V.cardHtml(item("note"), opts({kind: "<k>"})).startsWith(`<p class="bc-k">&lt;k&gt;</p>`), true);
  eq("card: tags that aren't text are left out", V.cardHtml(item("note", {excerpt: "x", tags: [3, null, "ok"]}), opts()).includes(`<p class="bc-tags">ok</p>`), true);

  // the undo stack
  const log = [];
  const entry = (name, ok = true) => ({label: name, undo: async () => { log.push("undo " + name); return ok ? `Undid ${name}` : null; },
    redo: async () => { log.push("redo " + name); return `Redid ${name}`; }});
  const U = new V.Undo(3);
  eq("undo: nothing at first", await U.undo(), null);
  eq("redo: nothing at first", await U.redo(), null);
  U.push(entry("a")); U.push(entry("b"));
  let r = await U.undo();
  eq("undo: the last action", [r.entry.label, r.said], ["b", "Undid b"]);
  eq("undo: then the one before", (await U.undo()).said, "Undid a");
  eq("undo: then nothing", await U.undo(), null);
  eq("redo: in the order they were done", [(await U.redo()).said, (await U.redo()).said], ["Redid a", "Redid b"]);
  eq("redo: then nothing", await U.redo(), null);
  await U.undo();
  U.push(entry("c"));
  eq("a new action ends what could be redone", [U.canRedo, await U.redo()], [false, null]);
  U.push(entry("d")); U.push(entry("e"));
  eq("only the last few are kept", U.done.map(e => e.label), ["c", "d", "e"]);
  U.push(entry("bad", false));
  r = await U.undo();
  eq("a failed undo says nothing", r.said, null);
  eq("a failed undo is dropped", [U.done.map(e => e.label), U.undone.length], [["d", "e"], 0]);
  const T = new V.Undo();
  T.push({label: "x", undo: async () => { throw new Error("boom"); }, redo: async () => "r"});
  const realError = console.error;
  console.error = () => {};
  r = await T.undo();
  console.error = realError;
  eq("an undo that throws is a failed one", [r.said, T.canUndo, T.canRedo, T.busy], [null, false, false, false]);
  let release;
  const W = new V.Undo();
  W.push(entry("quick"));
  W.push({label: "slow", undo: () => new Promise(res => { release = res; }), redo: async () => "r"});
  const first = W.undo();
  eq("one at a time: a second undo while one runs does nothing", [W.busy, await W.undo()], [true, null]);
  release("Undid slow");
  eq("one at a time: the running one finishes", [(await first).said, W.busy, W.undone.map(e => e.label)], ["Undid slow", false, ["slow"]]);
  eq("one at a time: the next one then runs", (await W.undo()).said, "Undid quick");
  W.clear();
  eq("clear: empty", [W.canUndo, W.canRedo], [false, false]);
  // an action recorded while an undo is under way ends what could be redone, that undo's entry too
  const X = new V.Undo();
  let go;
  X.push(entry("older"));
  X.push({label: "slow", undo: () => new Promise(res => { go = res; }), redo: async () => "r"});
  const running = X.undo();
  X.push(entry("new"));
  go("Undid slow");
  eq("recorded during an undo: the undo still says what it did", (await running).said, "Undid slow");
  eq("recorded during an undo: nothing to redo", [X.canRedo, await X.redo()], [false, null]);
  eq("recorded during an undo: the new action is the next to undo", X.done.map(e => e.label), ["older", "new"]);
  // a redo under way when an action is recorded stays done
  const Y = new V.Undo();
  Y.push({label: "r1", undo: async () => "u", redo: () => new Promise(res => { go = res; })});
  await Y.undo();
  const redoing = Y.redo();
  Y.push(entry("n"));
  go("Redid r1");
  await redoing;
  eq("recorded during a redo: both are done", Y.done.map(e => e.label), ["n", "r1"]);
  eq("the default keeps 50", new V.Undo().max, 50);

  console.log(JSON.stringify({failures, checked}));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
