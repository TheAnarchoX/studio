/* Runs the suggestions' pure helpers (studio/static/book-suggest.js) in node. Used by tests/test_book_suggest.py.

     node book_suggest.js <prosemirror.js> <book-schema.js> <book-text.js> <book-tools.js> <book-suggest.js> <fixture.json>
     output: {"failures": [{"name", "got", "want"}], "checked": n}

   The fixture is tests/fixtures/suggest-locate.json with a "doc" (the document as manuscript.parse gives it) added to
   each case by the Python test: nothing here parses Markdown. */
"use strict";
const fs = require("fs"), vm = require("vm");
const [pm, schema, text, tools, suggest, fixture] = process.argv.slice(2);
globalThis.window = globalThis;
// the page's own (studio/static/app.js)
globalThis.esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
vm.runInThisContext(fs.readFileSync(pm, "utf8"));
if (typeof PM !== "undefined") globalThis.PM = PM;
for (const f of [schema, text, tools, suggest]) vm.runInThisContext(fs.readFileSync(f, "utf8"));
const T = globalThis.BookTools, S = globalThis.BookSchema, B = globalThis.BookSuggest;
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };

// the same cases as the server's locate
for (const c of JSON.parse(fs.readFileSync(fixture, "utf8"))) {
  const boxes = T.containersOf(globalThis.PM.Node.fromJSON(S, c.doc), "en");
  const got = B.locate(boxes, {in: "text", ...c.s});
  eq("locate: " + c.name, got && {index: got.index, start: got.from, end: got.to, kind: got.box.kind}, c.want);
}

eq("kind names", B.KIND_NAME, {edit: "Edit", note: "Note", index: "Index", cite: "Citation", comment: "Comment"});
eq("shown: a note number and a line break are spaces", B.shown("a￼b\nc"), "a b c");

// rows
const x = (html, tag) => (new RegExp(`<span class="${tag}">(.*?)</span>`, "s").exec(html) || [])[1];
const sources = [{id: "dijk2020", title: "Tides", author: [{family: "Dijk", "non-dropping-particle": "van"}], issued: {"date-parts": [[2020]]}}];
const edit = {kind: "edit", piece: "Harbour", quote: "gull", text: "heron", before: "A large ", after: " circled twice", why: "Be exact"};
eq("edit row", B.rowHtml(edit, {sources}),
  '<span class="bs-k">Edit</span><span class="bs-x">A large <del>gull</del><ins>heron</ins> circled twice</span><span class="bs-w">Be exact</span>');
eq("edit row: the piece when the list is the whole book", x(B.rowHtml(edit, {sources, showPiece: true}), "bs-k"), "Edit · Harbour");
eq("edit row: no context, no why", B.rowHtml({kind: "edit", quote: "gull", text: "heron"}, {sources}),
  '<span class="bs-k">Edit</span><span class="bs-x"><del>gull</del><ins>heron</ins></span>');
const walking = "Walking through the fog, slowly, toward the ", circled = " circled the mast and came on and on";
eq("edit row: the context is cut to whole words", x(B.rowHtml({...edit, before: walking.slice(-32), after: circled.slice(0, 32)}, {sources}), "bs-x"),
  "…the fog, slowly, toward the <del>gull</del><ins>heron</ins> circled the mast and came on…");
eq("edit row: a context that reached the end of its line has no ellipsis, a cut one has", [
  x(B.rowHtml({...edit, before: walking.slice(-32), after: " ok"}, {sources}), "bs-x").startsWith("…"),
  x(B.rowHtml({...edit, before: "ok ", after: circled.slice(0, 32)}, {sources}), "bs-x").endsWith("…")], [true, true]);
eq("edit row: 32 code points count, not 32 UTF-16 units", x(B.rowHtml({...edit, before: "😀".repeat(16) + " ", after: ""}, {sources}), "bs-x").startsWith("😀"), true);
eq("note row: the tail keeps its first word when the cut falls between words",
  x(B.rowHtml({kind: "note", quote: "one two three four five six seven eight nine ten", text: "n"}, {sources}), "bs-x"), "After ‘…three four five six seven eight nine ten’: n");
eq("note row: the tail counts code points", x(B.rowHtml({kind: "note", quote: "ab " + "😀".repeat(40), text: "n"}, {sources}), "bs-x"), "After ‘…" + "😀".repeat(40) + "’: n");
eq("index row: a term equal to the words adds nothing", x(B.rowHtml({kind: "index", quote: "the pier", term: "the pier"}, {sources}), "bs-x"), "the pier");
eq("score counts code points", B.score("c-door😀 d.", 2, 6, "z ", "😀"), 1);
eq("score: a shared low surrogate is not a match", B.score("🨀door one.", 2, 6, "😀", "Q"), 0);
eq("note row", B.rowHtml({kind: "note", quote: "a lamp, not a torch", text: "Bring two", why: ""}, {sources}),
  '<span class="bs-k">Note</span><span class="bs-x">After ‘…a lamp, not a torch’: Bring two</span>');
eq("note row: a long quote keeps its last words", x(B.rowHtml({kind: "note", quote: "The harbour was quiet, the gulls circled twice over the pier", text: "n"}, {sources}), "bs-x"),
  "After ‘…the gulls circled twice over the pier’: n");
eq("index row", x(B.rowHtml({kind: "index", quote: "the pier", term: "Pier"}, {sources}), "bs-x"), "the pier → Pier");
eq("index row: without a term, the words themselves", x(B.rowHtml({kind: "index", quote: "the pier"}, {sources}), "bs-x"), "the pier");
eq("cite row", B.rowHtml({kind: "cite", quote: "as the survey showed", source: "dijk2020", locator: "p. 12", why: "Source"}, {sources}),
  '<span class="bs-k">Citation</span><span class="bs-x">After ‘…as the survey showed’: van Dijk 2020, p. 12</span><span class="bs-w">Source</span>');
eq("cite row: a source the book doesn't have shows its id", x(B.rowHtml({kind: "cite", quote: "q", source: "gone2001"}, {sources}), "bs-x"), "After ‘…q’: gone2001");
eq("comment row", x(B.rowHtml({kind: "comment", quote: "slowly", text: "Too slow?"}, {sources}), "bs-x"), "‘slowly’: Too slow?");
eq("a note number in the quote shows as a space", x(B.rowHtml({kind: "index", quote: "a￼b"}, {sources}), "bs-x"), "a b");

// the preview in the text: every one underlined, the current one showing its change; widgets carry text, never HTML
eq("preview: not the current one, only its words", B.previewOf(edit, false, {sources}), {cls: "bs-u"});
eq("preview: an edit struck through, the new words after", B.previewOf(edit, true, {sources}),
  {cls: "bs-u on bs-del", widget: {tag: "ins", cls: "bs-ins", text: "heron"}});
eq("preview: an edit that removes its words has nothing after them", B.previewOf({...edit, text: ""}, true, {sources}), {cls: "bs-u on bs-del"});
eq("preview: an edit's line break shows as a space", B.previewOf({...edit, text: "a\nb"}, true, {sources}).widget.text, "a b");
eq("preview: a note as a faint mark, titled with the note", B.previewOf({kind: "note", quote: "q", text: "Bring two"}, true, {sources}),
  {cls: "bs-u on", widget: {tag: "sup", cls: "bs-ghost bs-gn", text: "+", title: "Bring two"}});
eq("preview: a citation as its label", B.previewOf({kind: "cite", quote: "q", source: "dijk2020", locator: "p. 12"}, true, {sources}),
  {cls: "bs-u on", widget: {tag: "span", cls: "bs-ghost bs-gc", text: "van Dijk 2020, p. 12"}});
eq("preview: an index term in the tooltip", B.previewOf({kind: "index", quote: "the pier", term: "Pier"}, true, {sources}), {cls: "bs-u on", title: "Index: Pier"});
eq("preview: an index term without a term is the words", B.previewOf({kind: "index", quote: "the pier"}, true, {sources}).title, "Index: the pier");
eq("preview: a comment highlighted as comments are, its remark in the tooltip", B.previewOf({kind: "comment", quote: "slowly", text: "Too slow?"}, true, {sources}),
  {cls: "bs-u on bk-com-on", title: "Too slow?"});
eq("preview: markup in a suggestion stays text", B.previewOf({...edit, text: "<b>heron</b>"}, true, {sources}).widget.text, "<b>heron</b>");

const nasty = B.rowHtml({kind: "edit", quote: "<b>gull</b>", text: "d’r ’t „ja”…", before: "<i>", after: "&", why: "<b>why</b>"}, {sources});
eq("row escapes and keeps typography", [nasty.includes("&lt;b&gt;gull&lt;/b&gt;"), nasty.includes("&lt;b&gt;why&lt;/b&gt;"), nasty.includes("&lt;i&gt;"),
  nasty.includes("&amp;"), nasty.includes("<b>"), nasty.includes("d’r ’t „ja”…")], [true, true, true, true, false, true]);

console.log(JSON.stringify({failures, checked}));
