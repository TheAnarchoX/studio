/* Runs the research board's text side (studio/static/board-rail.js) in node: what a prepared item becomes in the text,
   where it goes for a drop position, the one transaction that inserts it, and the drop position kept through changes.
   Used by tests/test_board_js.py.

     node board_rail.js <prosemirror.js> <book-schema.js> <book-text.js> <board-core.js> <board-rail.js>
     output: {"failures": [{"name", "got", "want"}], "checked": n}   */
"use strict";
const fs = require("fs"), vm = require("vm");
const files = process.argv.slice(2);
globalThis.window = globalThis;
for (const f of files) {
  vm.runInThisContext(fs.readFileSync(f, "utf8"));
  if (f === files[0] && typeof PM !== "undefined") globalThis.PM = PM;
}
const D = globalThis.BoardDrop, S = globalThis.BookSchema, {EditorState, TextSelection, history, undo} = globalThis.PM;
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };

const t = (text, ...marks) => marks.length ? {type: "text", marks: marks.map(m => ({type: m})), text} : {type: "text", text};      // toJSON's key order
const para = (...c) => c.length ? {type: "paragraph", content: c} : {type: "paragraph"};
const title = text => ({type: "title", content: [t(text)]});
const docOf = (...c) => ({type: "doc", attrs: {form: "prose"}, content: c});
const node = json => globalThis.PM.Node.fromJSON(S, json);
const json = list => list.map(n => n.toJSON());
const KEY = "van-dijk-1998";
const citeJ = (key = KEY, locator = "p. 12") => ({type: "cite", attrs: {items: [{key, prefix: "", locator}]}});
const quote = (paragraphs, o = {}) => ({kind: "quote", paragraphs, words: 3, key: KEY, locator: "p. 12", added: false, ...o});
const words = n => Array.from({length: n}, (_, i) => "w" + i).join(" ");
/* the document position `offset` characters into the first text node holding `text` */
function at(doc, text, offset = 0) {
  let found = null;
  doc.descendants((n, pos) => {
    if (found != null) return false;
    if (n.isText && n.text.includes(text)) found = pos + n.text.indexOf(text) + offset;
    return true;
  });
  return found;
}
const stateOf = (d, extra = []) => EditorState.create({doc: node(d), plugins: [...extra, ...D.plugins({})]});
/* the document after putting `prep` at `pos` */
function put(d, pos, prep, style = "„…”", opts) {
  const s = stateOf(d), c = D.content(prep, style);
  return D.insert(s, typeof pos === "function" ? pos(s.doc) : pos, false, c, opts).tr.doc.toJSON().content;
}

// ——— what an item becomes ———
eq("a short quote with an em mark: marks, its text, the marks, a space, the citation",
  json(D.content(quote([[t("koud", "em")]]), "„…”").inline),
  [t("„"), t("koud", "em"), t("”"), t(" "), citeJ()]);
eq("its block (where no line can take it) is a paragraph of the same",
  D.content(quote([[t("koud", "em")]]), "„…”").block.toJSON(), para(t("„"), t("koud", "em"), t("” "), citeJ()));
eq("a quote inside the quote takes the single marks",
  json(D.content(quote([[t("Ze zei \"nee\".")]]), "„…”").inline), [t("„"), t("Ze zei ‚nee’."), t("”"), t(" "), citeJ()]);
eq("the single marks are decided on the paragraph, across marks",
  json(D.content(quote([[t("zei \"ja"), t("\" toen", "em")]]), "“…”").inline), [t("“"), t("zei ‘ja"), t("’ toen", "em"), t("”"), t(" "), citeJ()]);
eq("an apostrophe typed straight on the board", json(D.content(quote([[t("don't")]]), "“…”").inline)[1], t("don’t"));
eq("«…» marks", json(D.content(quote([[t("non")]]), "«…»").inline).slice(0, 3), [t("«"), t("non"), t("»")]);
eq("an unknown style is “…”", json(D.content(quote([[t("x")]]), undefined).inline).slice(0, 3), [t("“"), t("x"), t("”")]);
eq("no source: no space and no citation", json(D.content(quote([[t("koud")]], {key: null}), "„…”").inline), [t("„"), t("koud"), t("”")]);
eq("a locator-less citation", json(D.content(quote([[t("koud")]], {locator: ""}), "„…”").inline)[4], citeJ(KEY, ""));
const two = D.content(quote([[t("Een.")], [t("Twee.", "em")]], {words: 2}), "„…”");
eq("two paragraphs: no inline form", two.inline, null);
eq("two paragraphs: a block quotation with the citation at the end of its last paragraph",
  two.block.toJSON(), {type: "blockquote", content: [para(t("Een.")), para(t("Twee.", "em"), t(" "), citeJ())]});
eq("more than 40 words: a block quotation", D.content(quote([[t(words(41))]], {words: 41}), "„…”").block.type.name, "blockquote");
eq("40 words: inline", D.content(quote([[t(words(40))]], {words: 40}), "„…”").inline.length, 5);
eq("a block quotation: straight quotes become the style's",
  D.content(quote([[t("Hij zei \"ja\".")], [t("Toen 'niets'.")]], {words: 4, key: null}), "„…”").block.toJSON(),
  {type: "blockquote", content: [para(t("Hij zei „ja”.")), para(t("Toen ‚niets’."))]});
eq("a line break in a quote stays", json(D.content(quote([[t("a"), {type: "hard_break"}, t("b")]]), "“…”").inline).map(n => n.type),
  ["text", "text", "hard_break", "text", "text", "text", "cite"]);
eq("a mark this schema doesn't know: the text alone",
  json(D.content(quote([[{type: "text", text: "x", marks: [{type: "nope"}]}]]), "“…”").inline)[1], t("x"));
eq("a quote without text: nothing", D.content(quote([]), "„…”"), null);
eq("a quote of empty paragraphs: nothing", D.content(quote([[], []]), "„…”"), null);
const cite = D.content({kind: "cite", key: "smith2020", added: true}, "„…”");
eq("a source: the citation alone", json(cite.inline), [citeJ("smith2020", "")]);
eq("a source where no line can take it: a paragraph with it", cite.block.toJSON(), para(citeJ("smith2020", "")));
const img = D.content({kind: "image", src: "../images/kaart.png", alt: "De kaart"}, "„…”");
eq("an image: an image block with its caption", [img.inline, img.block.toJSON()],
  [null, {type: "image", attrs: {src: "../images/kaart.png", alt: "De kaart", width: null}}]);
eq("mapText keeps each node's share", D.mapText([t("ab"), {type: "cite"}, t("cd")], s => s.toUpperCase()), [t("AB"), {type: "cite"}, t("CD")]);

// ——— where it goes ———
const short = quote([[t("koud", "em")]]), long = quote([[t("Een.")], [t("Twee.")]], {words: 2});
const prose = docOf(title("Titel"), para(t("Ze zei toen.")));
eq("a short quote dropped after a word: a space before it, none after (one is there)",
  put(prose, d => at(d, "Ze zei", 6), short),
  [title("Titel"), para(t("Ze zei „"), t("koud", "em"), t("” "), citeJ(), t(" toen."))]);
eq("dropped before a word: a space after it",
  put(prose, d => at(d, "zei", 0), short),
  [title("Titel"), para(t("Ze „"), t("koud", "em"), t("” "), citeJ(), t(" zei toen."))]);
eq("dropped before punctuation: no space after",
  put(prose, d => at(d, "toen.", 4), short),
  [title("Titel"), para(t("Ze zei toen „"), t("koud", "em"), t("” "), citeJ(), t("."))]);
eq("dropped in an empty paragraph: in it, no spaces",
  put(docOf(para()), 1, short), [para(t("„"), t("koud", "em"), t("” "), citeJ())]);
eq("a source dropped after a word: [@key] with a space",
  put(prose, d => at(d, "toen", 4), {kind: "cite", key: "smith2020"}),
  [title("Titel"), para(t("Ze zei toen "), citeJ("smith2020", ""), t("."))]);
const between = docOf(title("T"), para(t("A")), para(t("B")));
eq("between blocks: a paragraph there", put(between, 6, short),
  [title("T"), para(t("A")), para(t("„"), t("koud", "em"), t("” "), citeJ()), para(t("B"))]);
eq("before the title: after it", put(between, 0, {kind: "image", src: "../images/x.png", alt: ""}),
  [title("T"), {type: "image", attrs: {src: "../images/x.png", alt: "", width: null}}, para(t("A")), para(t("B"))]);
eq("a long quote dropped in a paragraph: after the paragraph",
  put(prose, d => at(d, "zei", 1), long),
  [title("Titel"), para(t("Ze zei toen.")), {type: "blockquote", content: [para(t("Een.")), para(t("Twee. "), citeJ())]}]);
eq("a long quote dropped in an empty paragraph: in its place",
  put(docOf(para(t("A")), para(), para(t("B"))), 4, long),
  [para(t("A")), {type: "blockquote", content: [para(t("Een.")), para(t("Twee. "), citeJ())]}, para(t("B"))]);
const heading = {type: "heading", attrs: {level: 2}, content: [t("Hoofdstuk")]};
eq("a long quote dropped in another top-level line (a heading, a list item): after it",
  put(docOf(heading, para(t("A"))), 3, long),
  [heading, {type: "blockquote", content: [para(t("Een.")), para(t("Twee. "), citeJ())]}, para(t("A"))]);
const bq = {type: "blockquote", content: [para(t("Al geciteerd."))]};
eq("a long quote dropped in a block quotation: after it, never inside",
  put(docOf(bq, para(t("A"))), d => at(d, "geciteerd", 2), long),
  [bq, {type: "blockquote", content: [para(t("Een.")), para(t("Twee. "), citeJ())]}, para(t("A"))]);
eq("a short quote dropped in a block quotation's line: in it",
  put(docOf(bq), d => at(d, "geciteerd.", 10), short),
  [{type: "blockquote", content: [para(t("Al geciteerd. „"), t("koud", "em"), t("” "), citeJ())]}]);
eq("an image dropped in a line: after its block",
  put(prose, d => at(d, "zei", 1), {kind: "image", src: "../images/x.png", alt: "X"}),
  [title("Titel"), para(t("Ze zei toen.")), {type: "image", attrs: {src: "../images/x.png", alt: "X", width: null}}]);
const linked = {type: "poem", attrs: {src: "Gedichten/Zee"}};
eq("a source dropped on a linked poem: a paragraph after it",
  put(docOf(para(t("A")), linked), 4, {kind: "cite", key: "k"}), [para(t("A")), linked, para(citeJ("k", ""))]);
eq("a short quote with a line break dropped in the title: the break a space",
  put(docOf(title("Titel")), 6, quote([[t("a"), {type: "hard_break"}, t("b")]])),
  [{type: "title", content: [t("Titel „a b” "), citeJ()]}]);
const noted = docOf(para(t("Een"), {type: "note", content: [t("noot")]}, t(" twee")));
eq("a quote with a note dropped in a note's own text: in it, without the note",
  put(noted, 7, quote([[t("x"), {type: "note", content: [t("n")]}]])),
  [para(t("Een"), {type: "note", content: [t("no „x” "), citeJ(), t(" ot")]}, t(" twee"))]);
eq("a block quote dropped in a note's own text: inline in it, its paragraphs joined, with the citation",
  put(noted, 7, long),
  [para(t("Een"), {type: "note", content: [t("no „Een. Twee.” "), citeJ(), t(" ot")]}, t(" twee"))]);
eq("a quote of over 40 words dropped in a note: inline in it too",
  put(noted, 5, quote([[t(words(41))]], {words: 41, key: null}))[0].content[1].content,
  [t("„" + words(41) + "” noot")]);
{
  // a note's own editor takes a board drag itself (book-text.js notePlugins): never ProseMirror's text/plain drop
  const [p] = D.notePlugins({destroyed: true}, null);
  const ev = types => ({clientX: 0, clientY: 0, prevented: false, preventDefault() { this.prevented = true; },
    dataTransfer: {types, getData: k => k === globalThis.BoardCore.MIME ? JSON.stringify({board: null, id: "q"}) : "the excerpt"}});
  const view = {posAtCoords: () => ({pos: 2}), state: {selection: {to: 1}}};
  const board = ev(["text/plain", globalThis.BoardCore.MIME]), other = ev(["text/plain"]);
  eq("a board drag dropped in a note: taken by the board's drop", [p.props.handleDrop(view, board), board.prevented], [true, true]);
  eq("any other drop in a note: ProseMirror's", [p.props.handleDrop(view, other), other.prevented], [false, false]);
}
eq("the place of an inline insert", (() => { const s = stateOf(prose), p = D.place(s.doc, at(s.doc, "toen", 0), D.content(short, "„…”")); return [p.from, p.to, p.inline]; })(),
  [15, 15, true]);
eq("the place of a block insert", (() => { const s = stateOf(prose), p = D.place(s.doc, 10, D.content(long, "„…”")); return [p.from, p.to, p.inline]; })(),
  [21, 21, false]);
eq("a position past the end is the end", put(docOf(para(t("A"))), 99, {kind: "image", src: "../images/x.png", alt: ""}),
  [para(t("A")), {type: "image", attrs: {src: "../images/x.png", alt: "", width: null}}]);

// ——— gone: the end of the block ———
{
  const s = stateOf(docOf(para(t("Een twee drie."))));
  eq("what was at the place is gone: the end of the block there",
    D.insert(s, 4, true, D.content({kind: "cite", key: "k"}, "„…”")).tr.doc.toJSON().content, [para(t("Een twee drie. "), citeJ("k", ""))]);
}

// ——— the cursor, and one undo step ———
{
  const s = stateOf(prose, [history()]), r = D.insert(s, at(s.doc, "toen", 0), false, D.content(short, "„…”"), {caret: true});
  const after = s.apply(r.tr);
  eq("the cursor after the inline insert", [after.selection.from, after.selection.empty], [r.end, true]);
  eq("the end is after the citation", after.doc.nodeAt(r.end - 1).type.name, "text");
  let back = after;
  undo(after, tr => { back = after.apply(tr); });
  eq("one undo takes the insert back", back.doc.toJSON(), s.doc.toJSON());
  eq("an insert is one transaction", r.tr.docChanged, true);
}
{
  const s = stateOf(docOf(para(t("A"))), [history()]), r = D.insert(s, 1, false, D.content(long, "„…”"), {caret: true});
  const after = s.apply(r.tr);
  eq("a block at the end: a line after it for the cursor", after.doc.toJSON().content.map(n => n.type), ["paragraph", "blockquote", "paragraph"]);
  eq("the cursor in that line", after.selection.$from.parent.type.name + ":" + after.selection.$from.index(0), "paragraph:2");
  let back = after;
  undo(after, tr => { back = after.apply(tr); });
  eq("one undo takes the block and its line back", back.doc.toJSON(), s.doc.toJSON());
}
{
  const s = stateOf(docOf(para(t("A")), para(t("B")))), r = D.insert(s, 1, false, D.content({kind: "image", src: "../images/x.png", alt: ""}, ""), {caret: true});
  const after = s.apply(r.tr);
  eq("a block before a line: no new line, the cursor in the next one", [after.doc.childCount, after.selection.$from.parent.textContent], [3, "B"]);
}
{
  const s = stateOf(prose), r = D.insert(s, 7, false, D.content({kind: "cite", key: "k"}, ""), {caret: true});
  eq("without caret the selection stays", s.apply(D.insert(s, 10, false, D.content({kind: "cite", key: "k"}, "")).tr).selection.from, s.selection.from);
  const $c = s.apply(r.tr).selection.$from;
  eq("a citation between blocks: in a line of its own, the cursor at its end", [$c.parent.type.name, $c.parent.firstChild.type.name, $c.parentOffset], ["paragraph", "cite", 1]);
}

// ——— the place kept through changes ———
{
  const add = (s, id, pos) => s.apply(s.tr.setMeta(D.KEY, {add: {id, pos}}));
  let s = stateOf(prose);
  const p0 = at(s.doc, "toen", 0);
  s = add(s, 1, p0);
  eq("a pending insert", D.pending(s), [{gone: false, touched: false, id: 1, pos: p0}]);
  s = s.apply(s.tr.setMeta("other", true));
  eq("a transaction that changes nothing leaves it untouched", D.pending(s)[0].touched, false);
  s = s.apply(s.tr.insertText("Nou, ", at(s.doc, "Ze", 0)));
  eq("text typed before it moves it", [D.pending(s)[0].pos, D.pending(s)[0].touched], [p0 + 5, true]);
  s = s.apply(s.tr.insertText("en ", D.pending(s)[0].pos));
  eq("text typed at that very place goes after it", D.pending(s)[0].pos, p0 + 5);
  s = s.apply(s.tr.insertText("!", s.doc.content.size - 1));
  eq("text typed after it doesn't move it", D.pending(s)[0].pos, p0 + 5);
  s = add(s, 2, D.pending(s)[0].pos);
  s = s.apply(s.tr.setSelection(TextSelection.create(s.doc, 1)));
  eq("a moved cursor touches it", D.pending(s).find(e => e.id === 2).touched, true);
  const a = at(s.doc, "zei", 0), b = at(s.doc, "toen", 2);
  s = s.apply(s.tr.delete(a, b));
  eq("deleted around: gone, at the place of the deletion", D.pending(s).map(e => [e.id, e.pos, e.gone]), [[1, a, true], [2, a, true]]);
  s = s.apply(s.tr.setMeta(D.KEY, {done: 1}));
  eq("done: forgotten", D.pending(s).map(e => e.id), [2]);
  const r = D.insert(s, D.pending(s)[0].pos, D.pending(s)[0].gone, D.content({kind: "cite", key: "k"}, ""));
  eq("inserted after its place was deleted: at the end of that line", r.tr.doc.lastChild.lastChild.type.name, "cite");
}
{
  let s = stateOf(prose);
  s = s.apply(s.tr.setMeta(D.KEY, {add: {id: 7, pos: at(s.doc, "zei", 1)}}));
  s = s.apply(s.tr.delete(at(s.doc, "zei", 0), at(s.doc, "zei", 1)));
  eq("a deletion that ends at the place: not gone", D.pending(s)[0].gone, false);
}

console.log(JSON.stringify({failures, checked}));
