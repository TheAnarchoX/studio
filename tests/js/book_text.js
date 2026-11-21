/* Runs the writing window's pure helpers (studio/static/book-text.js) in node. Used by tests/test_book_text.py.

     node book_text.js <prosemirror.js> <book-schema.js> <book-text.js> <input.json> <book-format.js>
     input: [{"doc": document, "words": manuscript.counts words}, ...]
     output: {"failures": [{"name", "got", "want"}], "checked": n}
   book-format.js loads before book-text.js, as in the app (index.html).   */
"use strict";
const fs = require("fs"), vm = require("vm");
const [pm, schema, text, input, format] = process.argv.slice(2);
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(pm, "utf8"));
if (typeof PM !== "undefined") globalThis.PM = PM;
vm.runInThisContext(fs.readFileSync(schema, "utf8"));
vm.runInThisContext(fs.readFileSync(format, "utf8"));
vm.runInThisContext(fs.readFileSync(text, "utf8"));
const T = globalThis.BookText, S = globalThis.BookSchema, node = json => globalThis.PM.Node.fromJSON(S, json);
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };

// word counts: the same as the server's (manuscript.counts) for every sample document
JSON.parse(fs.readFileSync(input, "utf8")).forEach((d, i) => eq(`words of sample ${i}`, T.docWords(node(d.doc)), d.words));
eq("a lone clitic is part of the next word", T.countWords("en ’s avonds liepen we"), 4);
eq("a dash alone is no word", T.countWords("zei ze – en"), 3);

// straight quotes in each style
const q = (before, ch, style) => T.quoteFor(before, ch, style);
eq("“…” opens", q("", "\"", "“…”"), "“");
eq("“…” opens after a space", q("Ze zei ", "\"", "“…”"), "“");
eq("“…” closes after a word", q("Ze zei “Kom,", "\"", "“…”"), "”");
eq("„…” opens low", q("Ze zei ", "\"", "„…”"), "„");
eq("„…” closes high", q("Ze zei „Kom", "\"", "„…”"), "”");
eq("«…» opens", q("", "\"", "«…»"), "«");
eq("«…» closes", q("«Viens", "\"", "«…»"), "»");
eq("‘…’ opens with \"", q("He said ", "\"", "‘…’"), "‘");
eq("‘…’ closes with \"", q("He said ‘Come", "\"", "‘…’"), "’");
eq("an apostrophe after a letter", q("don", "'", "“…”"), "’");
eq("an apostrophe after a letter in „…”", q("zo", "'", "„…”"), "’");
eq("a single quote opens at a word start", q("Hij zei ", "'", "“…”"), "‘");
eq("a single quote opens low in „…”", q("Hij zei ", "'", "„…”"), "‚");
eq("‹ closes after a word inside ‹…›", q("«Il dit ‹non", "'", "«…»"), "›");
eq("an apostrophe in «…» with nothing open", q("aujourd", "'", "«…»"), "’");
eq("an unknown style is “…”", q("", "\"", "??"), "“");
const cl = s => { const m = T.CLITIC.exec(s); return m && [m[2], m[3], m[4]]; };
eq("‘s avonds is a clitic", cl("en ‘s "), ["‘", "s", " "]);
eq("‚t is a clitic", cl("‚t,"), ["‚", "t", ","]);
eq("’90 is a clitic", cl("in ‘90 "), ["‘", "90", " "]);
eq("‘so is no clitic", cl("‘so "), null);
eq("‘s-Hertogenbosch: a clitic before a hyphen", cl("in ‘s-"), ["‘", "s", "-"]);

// note numbers through the book, or per piece
const contents = [{auto: "toc"}, {file: "a.md", notes: 3}, {file: "b.md", notes: 2}, {auto: "notes"}, {file: "c.md", notes: 4}];
eq("per chapter starts at 0", T.noteStart(contents, "c.md", "chapter"), 0);
eq("through the book counts the pieces before", T.noteStart(contents, "c.md", "book"), 5);
eq("the first piece starts at 0", T.noteStart(contents, "a.md", "book"), 0);

// citation labels
const sources = [
  {id: "one", type: "book", title: "Een boek", author: [{family: "Jansen", given: "M."}], issued: {"date-parts": [[2019]]}},
  {id: "dijk", type: "book", author: [{family: "Dijk", "non-dropping-particle": "van", given: "A."}], issued: {"date-parts": [[2010]]}},
  {id: "wit", type: "book", author: [{family: "Wit", "dropping-particle": "de", given: "K."}, {family: "Berg", "non-dropping-particle": "van den"}], issued: {"date-parts": [[2015]]}},
  {id: "two", type: "book", author: [{family: "Bakker"}, {family: "Smit"}], issued: {"date-parts": [[2001, 5]]}},
  {id: "three", type: "book", author: [{family: "A"}, {family: "B"}, {family: "C"}], issued: {literal: "z.j."}},
  {id: "nobody", type: "webpage", title: "Een heel lange titel van een webpagina zonder auteur"},
];
eq("one author, year and locator", T.citeLabel([{key: "one", prefix: "", locator: "p. 12"}], sources), "Jansen 2019, p. 12");
eq("a name particle comes with the family name", T.citeLabel([{key: "dijk", prefix: "", locator: "p. 3"}], sources), "van Dijk 2010, p. 3");
eq("dropping and non-dropping particles", T.citeLabel([{key: "wit", prefix: "", locator: ""}], sources), "de Wit & van den Berg 2015");
eq("two authors and a prefix", T.citeLabel([{key: "two", prefix: "zie", locator: ""}], sources), "zie Bakker & Smit 2001");
eq("three authors", T.citeLabel([{key: "three", prefix: "", locator: ""}], sources), "A et al. z.j.");
eq("no author: the title, short", T.citeLabel([{key: "nobody", prefix: "", locator: ""}], sources), "Een heel lange titel van een we…");
eq("an unknown key shows as itself", T.citeLabel([{key: "elders", prefix: "", locator: "pp. 3–5"}], sources), "elders, pp. 3–5");
eq("two items", T.citeLabel([{key: "one", prefix: "", locator: ""}, {key: "two", prefix: "", locator: ""}], sources), "Jansen 2019; Bakker & Smit 2001");
eq("keys as manuscript.CITE_KEY", ["smith2020", "a:b.c", "x-", "-x", "één"].map(k => T.CITE_KEY.test(k)), [true, true, false, false, true]);

// the / menu and the bar follow the features
const memoir = {notes: "endnotes", sources: false, index: false}, all = {notes: "footnotes", sources: true, index: true};
eq("/ for a memoir", T.slashItems("", memoir, "prose").map(i => i.label),
  ["Note", "Scene break", "Epigraph", "Poem", "Image", "Math", "Table", "Page break", "Linked poem", "Bulleted list", "Numbered list"]);
eq("/ with everything on", T.slashItems("", all, "prose").map(i => i.id),
  ["note", "cite", "scene", "epigraph", "poem", "image", "math", "table", "page", "linked", "bullets", "numbers"]);
eq("/ for fiction", T.slashItems("", {notes: "off"}, "prose").map(i => i.id), ["scene", "epigraph", "poem", "image", "math", "table", "page", "linked", "bullets", "numbers"]);
eq("/ lists and tables only in prose pieces", T.slashItems("", all, "poem").map(i => i.id), ["note", "cite", "scene", "epigraph", "poem", "image", "math", "page", "linked"]);
eq("/ filtered: table", [T.slashItems("tab", all, "prose").map(i => i.id), T.slashItems("tab", all, "poem")], [["table"], []]);
eq("/ filtered: starts first, then a word", T.slashItems("p", all, "prose").map(i => i.label), ["Poem", "Page break", "Linked poem"]);
eq("/ filtered: inside a word from two letters", T.slashItems("gra", all, "prose").map(i => i.label), ["Epigraph"]);
eq("/ filtered: a word", T.slashItems("break", all, "prose").map(i => i.label), ["Scene break", "Page break"]);
eq("/ filtered: lists", [T.slashItems("list", all, "prose").map(i => i.id), T.slashItems("num", all, "prose").map(i => i.id), T.slashItems("list", all, "poem")],
  [["bullets", "numbers"], ["numbers"], []]);
eq("/ in a list: not the style it already is", [T.slashItems("list", all, "prose", "bullet").map(i => i.id), T.slashItems("list", all, "prose", "decimal").map(i => i.id),
  T.slashItems("list", all, "prose", "lower-alpha").map(i => i.id)], [["numbers"], ["bullets"], ["bullets", "numbers"]]);
eq("/ filtered: nothing", T.slashItems("xyz", all, "prose"), []);
eq("bar with everything on", T.barButtons(all).map(b => b[1]), ["Bold", "Italic", "Note", "Source", "Index", "Comment", "Format"]);
eq("bar for fiction", T.barButtons({notes: "off", sources: false, index: false}).map(b => b[0]), ["bold", "italic", "comment", "format"]);
eq("no Index for an index of first lines", T.barButtons({index: "first-lines"}).map(b => b[0]), ["bold", "italic", "comment", "format"]);
eq("bar across blocks", [T.barButtons(all, {multi: true}).map(b => b[0]), T.barButtons(memoir, {multi: true}).map(b => b[0])],
  [["bold", "italic", "format"], ["bold", "italic", "format"]]);
eq("bar in a note's text", [T.barButtons(all, {inNote: true}).map(b => b[0]), T.barButtons(memoir, {inNote: true}).map(b => b[0]),
  T.barButtons(all, {inNote: true, multi: true}).map(b => b[0])], [["bold", "italic", "source", "format"], ["bold", "italic", "format"], ["bold", "italic", "source", "format"]]);

// the bar's pressed buttons: Bold and Italic as the format panel shows them and as they toggle (BookFormat.current: a
// note's own text keeps its formatting, so its bold doesn't press Bold); Index and Comment when some of the text has them
const barDoc = node({type: "doc", attrs: {form: "prose"}, content: [{type: "paragraph", content: [{type: "text", text: "Een "},
  {type: "note", content: [{type: "text", text: "noot", marks: [{type: "strong"}, {type: "em"}]}]}, {type: "text", text: " twee", marks: [{type: "comment", attrs: {note: "n"}}]}]},
  {type: "paragraph", content: [{type: "text", text: "Vet", marks: [{type: "strong"}]}, {type: "text", text: " niet"}]}]});
const barOn = (from, to) => { const P0 = globalThis.PM, st = P0.EditorState.create({doc: barDoc, selection: P0.TextSelection.create(barDoc, from, to)});
  return typeof T.barPressed === "function" ? T.barPressed(st) : "no barPressed"; };
eq("bar pressed: a note's own bold and italic press nothing; some bold presses Bold; a comment presses Comment",
  [barOn(1, 11), barOn(1, 16), barOn(18, 23)],
  [{bold: false, italic: false, index: false, comment: false}, {bold: false, italic: false, index: false, comment: true},
   {bold: true, italic: false, index: false, comment: false}]);

// comments as ranges
const c = (note, text) => ({type: "text", text, marks: [{type: "comment", attrs: {note}}]});
const cdoc = node({type: "doc", attrs: {form: "prose"}, content: [{type: "paragraph", content: [
  {type: "text", text: "a "}, c("x", "bc"), {type: "text", text: "d", marks: [{type: "em"}, {type: "comment", attrs: {note: "x"}}]},
  {type: "text", text: " e "}, c("y", "f"), c("z", "g")]}]});
eq("comments: neighbouring text with the same comment is one", T.commentRanges(cdoc).map(r => [r.from, r.to, r.mark.attrs.note]), [[3, 6, "x"], [9, 10, "y"], [10, 11, "z"]]);

// index terms, titles, editable documents
eq("index term spacing", [T.indexTerm(" trauma>childhood "), T.indexTerm("a  >  b > c"), T.indexTerm("  ")], ["trauma > childhood", "a > b > c", null]);
const titled = {type: "doc", attrs: {form: "prose"}, content: [{type: "title", content: [{type: "text", text: "Oud"}, {type: "note", content: [{type: "text", text: "n"}]}]}, {type: "paragraph"}]};
eq("titleOf", T.titleOf(titled), "Oud");
eq("withTitle keeps a note in the title", T.withTitle(titled, "Nieuw").content[0], {type: "title", content: [{type: "text", text: "Nieuw"}, {type: "note", content: [{type: "text", text: "n"}]}]});
eq("withTitle adds a title", T.withTitle({type: "doc", content: [{type: "paragraph"}]}, "Eerste").content.map(n => n.type), ["title", "paragraph"]);
eq("withTitle with no title removes it", T.withTitle({type: "doc", content: [{type: "title", content: [{type: "text", text: "x"}]}]}, "").content, []);
eq("editable: an empty piece gets a line", T.editableDoc({type: "doc", attrs: {form: "prose"}}).content, [{type: "paragraph"}]);
eq("editable: a title alone gets a line after it", T.editableDoc({type: "doc", content: [{type: "title"}]}).content.map(n => n.type), ["title", "paragraph"]);
eq("editable: an empty poem and epigraph get a line", T.editableDoc({type: "doc", content: [{type: "poem", attrs: {src: null}}, {type: "epigraph", content: [{type: "attribution"}]}]}).content.map(n => (n.content || []).map(c => c.type)),
  [["paragraph"], ["paragraph", "attribution"]]);
eq("editable: a linked poem stays empty", T.editableDoc({type: "doc", content: [{type: "poem", attrs: {src: "S/P"}}]}).content[0].content, undefined);
eq("editable documents are valid", (() => { try { node(T.editableDoc({type: "doc", attrs: {form: "prose"}, content: [{type: "poem", attrs: {src: null}}]})).check(); return true; } catch (e) { return e.message; } })(), true);

// ## and ### make headings of paragraphs only: at the start of the title they do nothing
const P = globalThis.PM, rules = T.blockRules(() => "“…”"), heading = rules.find(r => r.match.source.includes("#{2,3}"));
const typed = (doc, pos, text) => {        // what the rule does when `text` is typed at pos (as the input rules plugin calls it)
  const state = P.EditorState.create({doc: node(doc)}), $p = state.doc.resolve(pos);
  const before = $p.parent.textBetween(0, $p.parentOffset, null, "\ufffc") + text, m = heading.match.exec(before);
  if (!m) return "no match";
  const tr = heading.handler(state, m, pos - (m[0].length - text.length), pos);
  return tr ? tr.doc.toJSON().content.map(n => n.type + (n.attrs && n.attrs.level ? n.attrs.level : "")) : null;
};
eq("## at the start of the title is left alone", typed({type: "doc", content: [{type: "title", content: [{type: "text", text: "##"}]}]}, 3, " "), null);
eq("## at the start of a paragraph is a heading", typed({type: "doc", content: [{type: "title", content: [{type: "text", text: "T"}]}, {type: "paragraph", content: [{type: "text", text: "##"}]}]}, 6, " "), ["title", "heading2"]);
eq("### in a quotation does nothing", typed({type: "doc", content: [{type: "blockquote", content: [{type: "paragraph", content: [{type: "text", text: "###"}]}]}]}, 5, " "), null);

/* types `text` at the end of a one-paragraph document with these input rules, as the editor does (handleTextInput) */
const typeRules = (rules, text, form = "prose") => {
  const doc = node({type: "doc", attrs: {form}, content: [{type: "paragraph"}]});
  let state = P.EditorState.create({doc, plugins: [P.inputRules({rules})], selection: P.TextSelection.create(doc, 1)});
  for (const ch of text) {
    const view = {composing: false, state, dispatch(tr) { this.state = this.state.apply(tr); }}, {from, to} = state.selection;
    if (!state.plugins.some(p => p.props.handleTextInput && p.props.handleTextInput(view, from, to, ch))) view.dispatch(state.tr.insertText(ch, from, to));
    state = view.state;
  }
  return state.doc.toJSON().content;
};
eq("strike:typing ~~weg~~ is struck through", typeRules(T.inlineRules(() => "“…”"), "nu ~~weg~~ en"),
  [{type: "paragraph", content: [{type: "text", text: "nu "}, {type: "text", marks: [{type: "strike"}], text: "weg"}, {type: "text", text: " en"}]}]);
eq("strike:typing not with a space inside the edge, nor ~ alone", [typeRules(T.inlineRules(() => "“…”"), "~~ weg~~")[0].content, typeRules(T.inlineRules(() => "“…”"), "~weg~")[0].content],
  [[{type: "text", text: "~~ weg~~"}], [{type: "text", text: "~weg~"}]]);
eq("strike:typing at a line's start, one letter", typeRules(T.inlineRules(() => "“…”"), "~~x~~")[0].content, [{type: "text", marks: [{type: "strike"}], text: "x"}]);
eq("lists:typing the triggers are among the text's rules", [typeRules(T.blockRules(() => "“…”"), "- Een")[0], typeRules(T.blockRules(() => "“…”"), "- Een", "poem")[0].type],
  [{type: "list_item", attrs: {list: "bullet", level: 0, start: null}, content: [{type: "text", text: "Een"}]}, "paragraph"]);

// the margin does nothing once its text is gone (an image loading late, fonts arriving)
const fake = () => ({className: "", style: {setProperty() {}}, children: [], append(...c) { this.children.push(...c); }, setAttribute() {},
  getBoundingClientRect: () => ({top: 0, bottom: 0, left: 0}), remove() {}, isConnected: true, offsetHeight: 0});
globalThis.document = {createElement: fake, activeElement: null};
let frames = 0;
globalThis.requestAnimationFrame = () => { frames++; return frames; };
globalThis.cancelAnimationFrame = () => {};
const gone = () => { throw new Error("used a destroyed view"); };
const owner = {destroyed: false, lang: "nl", view: {get state() { return gone(); }, coordsAtPos: gone}, ctx: {features: () => ({}), noteStart: () => 0}};
const margin = new T.Margin(owner, fake());
owner.destroyed = true;
margin.schedule();
eq("no layout is scheduled after destroy", frames, 0);
eq("a layout after destroy does nothing", (() => { try { margin.layout(); margin.sync(node({type: "doc", content: [{type: "paragraph"}]})); return "fine"; } catch (e) { return e.message; } })(), "fine");

// a comment is one line
eq("line breaks in a comment become spaces", T.oneLine("eerst\ndan\r\nlater\rnu"), "eerst dan later nu");

// poem lines keep their indentation: typed, tabbed and pasted spaces at a line start become no-break spaces
const NB = "\u00A0", P2 = globalThis.PM;
const para = (...c) => ({type: "paragraph", content: c.length ? c : undefined});
const txt = s => ({type: "text", text: s}), br = {type: "hard_break"};
const poemDoc = node({type: "doc", attrs: {form: "poem"}, content: [{type: "title", content: [txt("Lijnen")]}, para(txt("Een regel"), br)]});
const proseDoc = node({type: "doc", attrs: {form: "prose"}, content: [para(txt("Proza.")), {type: "poem", attrs: {src: null}, content: [para()]}, para()]});
/* types `text` at `pos` as the editor does: the poem rule first, else as typed */
const typeAt = (doc, pos, text) => {
  let state = P2.EditorState.create({doc, selection: P2.TextSelection.create(doc, pos)});
  for (const ch of text) {
    const at = state.selection.from, spaces = T.poemTyped(state, at, ch);
    state = state.apply(state.tr.insertText(spaces == null ? ch : spaces, at, at));
  }
  return state;
};
const lineText = (state, i) => state.doc.child(i).textContent;
const typedPoem = typeAt(poemDoc, poemDoc.content.size - 1, "  ingesprongen  regel");
eq("spaces at a poem line's start are no-break spaces", lineText(typedPoem, 1), `Een regel${NB}${NB}ingesprongen  regel`);
const midLine = typeAt(poemDoc, 18, " ");
eq("a space within a poem line stays a space", lineText(midLine, 1), "Een regel ");
const firstLine = typeAt(node({type: "doc", attrs: {form: "poem"}, content: [para()]}), 1, " \tweg");
eq("a tab typed at the start is two no-break spaces", lineText(firstLine, 0), `${NB}${NB}${NB}weg`);
const inBlock = typeAt(proseDoc, 10, "  lijn");
eq("in a ::: poem block too", inBlock.doc.child(1).textContent, `${NB}${NB}lijn`);
const prose = typeAt(proseDoc, proseDoc.content.size - 1, "  tekst");
eq("prose is unchanged", lineText(prose, 2), "  tekst");
const proseStart = typeAt(proseDoc, 1, "  ");
eq("prose: spaces at a paragraph's start stay spaces", lineText(proseStart, 0), "  Proza.");
const tabbed = (doc, pos) => { let st = P2.EditorState.create({doc, selection: P2.TextSelection.create(doc, pos)}); const ok = T.poemTab(st, tr => { st = st.apply(tr); }); return [ok, st]; };
eq("Tab in a poem line: two no-break spaces", (([ok, st]) => [ok, lineText(st, 1)])(tabbed(poemDoc, poemDoc.content.size - 1)), [true, `Een regel${NB}${NB}`]);
eq("Tab in prose is left to the browser", tabbed(proseDoc, 2)[0], false);
const sliceOf = (content, open) => new P2.Slice(P2.Fragment.fromJSON(S, content), open, open);
const pasted = T.poemPasted(sliceOf([para(txt("  eerste"), br, txt("\ttweede"), br, txt("derde"))], 1), true);
eq("pasted at a line start: each line keeps its indentation", pasted.content.toJSON()[0].content.map(n => n.text || "|"),
  [`${NB}${NB}eerste`, "|", `${NB}${NB}tweede`, "|", "derde"]);
const pastedMid = T.poemPasted(sliceOf([para(txt(" na"), br, txt("  volgende"))], 1), false);
eq("pasted within a line: its first line continues it", pastedMid.content.toJSON()[0].content.map(n => n.text || "|"), [" na", "|", `${NB}${NB}volgende`]);
const li = (list, level, ...c) => ({type: "list_item", attrs: {list, level, start: null}, content: c});
const pastedList = T.poemPasted(sliceOf([li("decimal", 0, txt("Een")), li("lower-alpha", 1, txt("Sub")), li("bullet", 0, txt("  Punt"))], 0), true);
eq("list items pasted into a poem line: lines led by their marker", pastedList.content.toJSON().map(n => [n.type, n.content.map(c => c.text).join("")]),
  [["paragraph", "1. Een"], ["paragraph", `${NB}${NB}a. Sub`], ["paragraph", "•   Punt"]]);
// what a paste or a drop brings in (the view's transformPasted): in a poem piece no list item, wherever the cursor is
const listSlice = sliceOf([li("decimal", 0, txt("Een")), li("decimal", 0, txt("Twee"))], 0);
const pastedTypes = (doc, pos) => T.pasted(listSlice, doc.resolve(pos)).content.toJSON().map(n => n.type + ":" + (n.content || []).map(c => c.text).join(""));
eq("pasted into a poem piece outside a poem line: lines, not items", [pastedTypes(poemDoc, 3), pastedTypes(proseDoc, 2)],
  [["paragraph:1. Een", "paragraph:2. Twee"], ["list_item:Een", "list_item:Twee"]]);
// a table pasted into a poem piece or a poem line: a line per row, its cells joined by " | "; in prose it stays a table
const tcell = (...c) => (c.length ? {type: "table_cell", content: c} : {type: "table_cell"});
const trow = (...c) => ({type: "table_row", content: c});
const tableSlice = sliceOf([para(txt("Voor")), {type: "table", attrs: {header: true, align: [null, "right"]},
  content: [trow(tcell(txt("Naam")), tcell(txt("Jaar"))), trow(tcell({type: "text", text: "Een", marks: [{type: "em"}]}), tcell())]}], 0);
const tableIn = (doc, pos) => T.pasted(tableSlice, doc.resolve(pos)).content.toJSON().map(n => [n.type, (n.content || []).map(c => c.text + (c.marks ? "*" : "")).join("")]);
eq("pasted table into a poem piece, a poem line, prose", [tableIn(poemDoc, 3), tableIn(proseDoc, 10), tableIn(proseDoc, 2).map(b => b[0])],
  [[["paragraph", "Voor"], ["paragraph", "Naam | Jaar"], ["paragraph", "Een* | "]], [["paragraph", "Voor"], ["paragraph", "Naam | Jaar"], ["paragraph", "Een* | "]],
   ["paragraph", "table"]]);
const openCell = T.pasted(sliceOf([{type: "table", attrs: {header: true, align: [null]}, content: [trow(tcell(txt("woord")))]}], 3), poemDoc.resolve(3));
eq("pasted from inside a cell into a poem piece: the words, open into the line", [openCell.openStart, openCell.openEnd, openCell.content.toJSON()],
  [1, 1, [{type: "paragraph", content: [{type: "text", text: "woord"}]}]]);
// pasted or dropped into a table's cell: one line of it, whatever comes in; the table keeps its rows and columns
const host = node({type: "doc", attrs: {form: "prose"}, content: [para(txt("Voor")), {type: "table", attrs: {header: true, align: [null, null]},
  content: [trow(tcell(txt("Naam")), tcell(txt("Jaar"))), trow(tcell(txt("Een")), tcell(txt("1990")))]}, para(txt("Na"))]});
let inEen = null;
host.descendants((n, p) => { if (inEen == null && n.type.name === "table_cell" && n.textContent === "Een") inEen = p + 2; });   // after "E"
const grid = d => d.content.content.map(n => (n.type.name === "table" ? n.content.content.map(r => r.content.content.map(c => c.textContent))
  : n.type.name + ":" + n.textContent));
const docSlice = (blocks, open) => { const d = node({type: "doc", attrs: {form: "prose"}, content: blocks}); return d.slice(open, d.content.size - open); };
function intoCell(slice) {
  const st = P2.EditorState.create({doc: host, selection: P2.TextSelection.create(host, inEen)});
  const tr = st.tr.replaceSelection(T.pasted(slice, st.selection.$from));
  tr.doc.check();
  return tr.doc;
}
const cellOf = d => grid(d)[1][1][0];
const otherTable = node({type: "doc", attrs: {form: "prose"}, content: [{type: "table", attrs: {header: true, align: [null, null]},
  content: [trow(tcell(txt("a")), tcell(txt("b"))), trow(tcell(txt("c")), tcell(txt("d")))]}]});
const li2 = s => li("bullet", 0, txt(s));
const intoCellDocs = [
  intoCell(docSlice([para(txt("Alpha")), para(txt("Beta"))], 0)), intoCell(docSlice([para(txt("Alpha")), para(txt("Beta"))], 1)),
  intoCell(docSlice([li2("Een"), li2("Twee")], 1)), intoCell(docSlice([{type: "heading", attrs: {level: 2}, content: [txt("Kop")]}], 0)),
  intoCell(docSlice([{type: "image", attrs: {src: "../images/a.png", alt: "", width: null}}], 0)), intoCell(tableSlice),
  intoCell(otherTable.slice(3, otherTable.content.size - 3)), intoCell(otherTable.slice(1, otherTable.content.size - 1)),
  intoCell(docSlice([para(txt("a"), br, txt("b")), {type: "scene_break"}, {type: "blockquote", content: [para(txt("c"))]}], 0)),
];
eq("pasted into a cell: one line, the table as it was around it", [intoCellDocs.map(cellOf), intoCellDocs.map(d => grid(d).length),
  intoCellDocs.map(d => grid(d)[1].map(r => r.length))],
  [["EAlpha Betaen", "EAlpha Betaen", "EEen Tweeen", "EKopen", "Een", "EVoor Naam | Jaar Een | en", "Ea | b c | den", "Ea | b c | den", "Ea b cen"],
   intoCellDocs.map(() => 3), intoCellDocs.map(() => [2, 2])]);
const mathIn = intoCell(docSlice([{type: "math_display", attrs: {tex: "x^2"}}], 0));
let mathInCell = null;
mathIn.descendants(n => { if (n.type.name === "math") mathInCell = n.attrs.tex; });
eq("pasted into a cell: display math as inline math, marks kept", [mathInCell, JSON.stringify(intoCellDocs[5].toJSON()).includes('"marks":[{"type":"em"}],"text":"Een"')],
  ["x^2", true]);
/* a drop (the view's handleDrop): at the cell under the pointer; a move takes the dragged text away; nothing that holds no text */
function dropAt(pos, slice, moved, sel = null) {
  const st0 = P2.EditorState.create({doc: host, selection: sel ? P2.TextSelection.create(host, sel[0], sel[1]) : undefined});
  const view = {state: st0, dispatch(tr) { this.state = this.state.apply(tr); }, focus() {}, posAtCoords: () => ({pos, inside: -1})};
  return [T.cellDrop(view, {clientX: 0, clientY: 0}, slice, moved), view.state];
}
const dropped = dropAt(inEen, docSlice([para(txt("Alpha")), para(txt("Beta"))], 0), false);
const movedIn = dropAt(inEen, host.slice(1, 5), true, [1, 5]);
const imageDrop = dropAt(inEen, docSlice([{type: "image", attrs: {src: "../images/a.png", alt: "", width: null}}], 0), true);
eq("dropped into a cell: one line; a move; an image not", [dropped[0], cellOf(dropped[1].doc), movedIn[0], grid(movedIn[1].doc)[0], cellOf(movedIn[1].doc),
  imageDrop[0], imageDrop[1].doc.eq(host), dropAt(2, docSlice([para(txt("x"))], 0), false)[0]],
  [true, "EAlpha Betaen", true, "paragraph:", "EVooren", true, true, false]);
const plain = T.poemText("  een\n    twee\n\n\tdrie\nvier\n", [], true);
eq("plain text pasted: lines and stanzas stay, indented", plain.content.toJSON().map(p => (p.content || []).map(n => n.text || "|")),
  [[`${NB}${NB}een`, "|", `${NB}${NB}${NB}${NB}twee`], [`${NB}${NB}drie`, "|", "vier"]]);
eq("plain text pasted within a line: its first line as it is", T.poemText(" x\ny", [], false).content.toJSON()[0].content[0].text, " x");
// for test_book_text.py: these documents go through the server's Markdown and come back the same
const pastedInto = (() => { const st = P2.EditorState.create({doc: poemDoc}); return st.apply(st.tr.replace(poemDoc.content.size - 1, poemDoc.content.size - 1, pasted)).doc; })();
const indentedDocs = [typedPoem.doc.toJSON(), firstLine.doc.toJSON(), inBlock.doc.toJSON(), pastedInto.toJSON()];

console.log(JSON.stringify({failures, checked, typed: indentedDocs, cells: [...intoCellDocs, mathIn, dropped[1].doc, movedIn[1].doc].map(d => d.toJSON())}));
