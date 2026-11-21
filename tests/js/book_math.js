/* Runs LaTeX math of the writing window (studio/static/book-math.js) in node: typing `$tex$` as the dialect reads it,
   one Backspace giving the dollars back, `$$` + Enter and / Math putting in display math, prices and escaped dollars
   staying text, math typed in every kind of text, Enter on a selected math, KaTeX's check; and the writing window's
   own typing rules and / menu with math in them (book-text.js). Used by tests/test_book_math.py.

     node book_math.js <prosemirror.js> <book-schema.js> <book-math.js> <katex.min.js> <input.json> <book-format.js> <book-text.js>
     input: {"parity": [{"line": a line of Markdown, "content": the paragraph manuscript.parse reads from it}],
             "reload": {scenario: document parsed from the scenario's Markdown}}
     output: {"failures": [{"name", "got", "want"}], "checked": n, "reload": {scenario: document after its edit}}
   KaTeX and book-math.js load before book-format.js and book-text.js, as in the app (index.html). */
"use strict";
const fs = require("fs"), vm = require("vm");
const [pm, schema, math, katex, input, format, text] = process.argv.slice(2);
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(pm, "utf8"));
if (typeof PM !== "undefined") globalThis.PM = PM;
vm.runInThisContext(fs.readFileSync(schema, "utf8"));
vm.runInThisContext(fs.readFileSync(katex, "utf8"));
vm.runInThisContext(fs.readFileSync(math, "utf8"));
vm.runInThisContext(fs.readFileSync(format, "utf8"));
vm.runInThisContext(fs.readFileSync(text, "utf8"));
const B = globalThis.BookMath, S = globalThis.BookSchema, P = globalThis.PM, BT = globalThis.BookText;
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };
const IN = JSON.parse(fs.readFileSync(input, "utf8"));

/* ——— documents and states ——— */
const txt = (s, marks) => (marks ? {type: "text", marks, text: s} : {type: "text", text: s});
const mth = (tex, marks) => (marks ? {type: "math", attrs: {tex}, marks} : {type: "math", attrs: {tex}});
const para = (...c) => (c.length ? {type: "paragraph", content: c} : {type: "paragraph"});
const heading = (...c) => Object.assign({type: "heading", attrs: {level: 2}}, c.length ? {content: c} : {});
const item = (...c) => Object.assign({type: "list_item", attrs: {list: "bullet", level: 0, start: null}}, c.length ? {content: c} : {});
const cell = (...c) => Object.assign({type: "table_cell"}, c.length ? {content: c} : {});
const table = (...rows) => ({type: "table", attrs: {header: true, align: rows[0].map(() => null)},
  content: rows.map(r => ({type: "table_row", content: r}))});
const quote = (...ps) => ({type: "blockquote", content: ps});
const display = tex => ({type: "math_display", attrs: {tex}});
const cite = {type: "cite", attrs: {items: [{key: "smith2020", prefix: null, locator: null}]}};
const STRONG = [{type: "strong"}];
const docOf = (blocks, form = "prose") => P.Node.fromJSON(S, {type: "doc", attrs: {form}, content: blocks});
/* the ends of the document's text blocks, in order */
const ends = doc => { const out = []; doc.descendants((n, pos) => { if (n.isTextblock) out.push(pos + 1 + n.content.size); }); return out; };
const textblocks = doc => { const out = []; doc.descendants(n => { if (n.isTextblock) out.push(n); }); return out; };
const plugins = () => [P.inputRules({rules: B.inputRules()}), P.history()];
const at = (doc, pos) => P.EditorState.create({doc, plugins: plugins(), selection: P.TextSelection.create(doc, pos)});
/* types `text` as the editor does: the input rules first (handleTextInput, as prosemirror-inputrules' own tests), else
   the text goes in as typed */
function type(state, text) {
  for (const ch of text) {
    const view = {composing: false, state, dispatch(tr) { this.state = this.state.apply(tr); }};
    const {from, to} = state.selection;
    if (!state.plugins.some(p => p.props.handleTextInput && p.props.handleTextInput(view, from, to, ch))) view.dispatch(state.tr.insertText(ch, from, to));
    state = view.state;
  }
  return state;
}
/* `text` typed at the end of text block `k` (in document order) of a document of `blocks` */
const typed = (text, blocks = [para()], k = 0, form = "prose") => { const doc = docOf(blocks, form); return type(at(doc, ends(doc)[k]), text); };
/* the inline content of text block `k` */
const inl = (state, k = 0) => textblocks(state.doc)[k].toJSON().content || [];
const tops = state => state.doc.toJSON().content;
/* a command on a state: [what it returned, the state after it] */
function run(state, cmd) { let next = state; const ok = cmd(state, tr => { next = next.apply(tr); }); return [ok, next]; }
const selected = state => (state.selection instanceof P.NodeSelection ? [state.selection.node.type.name, state.selection.from] : null);
const T = {locked: false}, LOCKED = {locked: true};

/* ——— math:typing ——— */
eq("math:typing $x^2$ is math", inl(typed("$x^2$")), [mth("x^2")]);
eq("math:typing in a line", inl(typed("Een $x^2$ twee")), [txt("Een "), mth("x^2"), txt(" twee")]);
eq("math:typing the cursor goes after it", typed("$x^2$").selection.from, 2);
eq("math:typing fires on the closing dollar", inl(typed("Een $x^2")), [txt("Een $x^2")]);
eq("math:typing $20 en $ stays text", inl(typed("$20 en $")), [txt("$20 en $")]);
eq("math:typing \\$x$ stays text", inl(typed("\\$x$")), [txt("\\$x$")]);
eq("math:typing no space after the opening dollar", inl(typed("$ x$")), [txt("$ x$")]);
eq("math:typing no space before the closing dollar", inl(typed("$x $")), [txt("$x $")]);
eq("math:typing $$ stays text", inl(typed("$$")), [txt("$$")]);
eq("math:typing two in a row", inl(typed("$a$ en $b$")), [mth("a"), txt(" en "), mth("b")]);
eq("math:typing TeX with spaces inside", inl(typed("$E = mc^2$")), [mth("E = mc^2")]);
eq("math:typing the text's marks go on the math", inl(typed("$x$", [para(txt("Vet ", STRONG))])), [txt("Vet ", STRONG), mth("x", STRONG)]);
// the writing window's typing rules turn ' " -- ... into typography as they are typed; in TeX they are what was typed
eq("math:typing the text's typography is TeX again", inl(typed("$f’(x) – g’’ … h — “q” ‘r’$")), [mth("f'(x) -- g'' ... h --- \"q\" 'r'")]);
eq("math:typing a closing dollar before a digit stays text", inl(type(at(docOf([para(txt("$x5"))]), 3), "$")), [txt("$x$5")]);
eq("math:typing a selection typed over", (() => {
  const doc = docOf([para(txt("$x weg"))]);
  return inl(type(P.EditorState.create({doc, plugins: plugins(), selection: P.TextSelection.create(doc, 3, 7)}), "$"));
})(), [mth("x")]);
eq("math:typing mathStart", ["$x$", "a $x$", "$20 en $", "\\$x$", "$x\\$", "\\\\$x$", "$$", "$a$b$", "$$x$", "x$", "$", "", "$a￼b$"].map(B.mathStart),
  [0, 2, -1, -1, -1, 2, -1, -1, 1, -1, -1, -1, -1]);
// a \text{…} group is TeX, dollars and all (manuscript._text_group_end): the math closes after it, not inside it
eq("math:typing a \\text{…} group with math in it", inl(typed("$x = 1 \\text{ als $y > 0$}$")), [mth("x = 1 \\text{ als $y > 0$}")]);
eq("math:typing not inside a \\text{…} group still open", [inl(typed("$x \\text{ als $y$")), inl(typed("$x \\text{ als {$y$"))],
  [[txt("$x \\text{ als $y$")], [txt("$x \\text{ als {$y$")]]);
eq("math:typing mathStart and \\text{…}", ["$a \\text{b} c$", "$a \\text{ als $b$ } c$", "$a \\text{ als $b$", "$a \\text{ $ ￼ } c$", "$a \\textbf{$"].map(B.mathStart),
  [0, 0, -1, -1, 0]);           // only \text{…} is read whole, as the dialect reads it
eq("math:typing asTyped", [B.asTyped("f’(x)"), B.asTyped("a – b — c…"), B.asTyped("„x” «y» ‹z› ‚w’"), B.asTyped("x^2")],
  ["f'(x)", "a -- b --- c...", "\"x\" \"y\" 'z' 'w'", "x^2"]);

/* ——— math:undo: one Backspace (undoInputRule) right after gives back the dollars ——— */
const undone = state => run(state, P.undoInputRule);
eq("math:undo the dollars back", (([ok, st]) => [ok, inl(st), st.selection.from])(undone(typed("$x^2$"))), [true, [txt("$x^2$")], 6]);
eq("math:undo in a line", inl(undone(typed("Een $x^2$"))[1]), [txt("Een $x^2$")]);
eq("math:undo only right after", undone(type(typed("$x$"), " "))[0], false);
eq("math:undo the dollars given back stay text as typing goes on", inl(type(undone(typed("$x^2$"))[1], " en $y$")), [txt("$x^2$ en "), mth("y")]);

/* ——— math:display: `$$` + Enter in an empty top-level paragraph; / Math; Enter on a selected math ——— */
const dollars = (blocks, k = 0, form = "prose") => run(typed("$$", blocks, k, form), B.enter(T));
eq("math:display $$ + Enter", (([ok, st]) => [ok, tops(st), selected(st)])(dollars([para()])), [true, [display(""), para()], ["math_display", 0]]);
eq("math:display after the title", (([ok, st]) => [ok, tops(st), selected(st)])(dollars([{type: "title", content: [txt("T")]}, para()], 1)),
  [true, [{type: "title", content: [txt("T")]}, display(""), para()], ["math_display", 3]]);
eq("math:display between paragraphs", tops(dollars([para(txt("Een")), para(), para(txt("Twee"))], 1)[1]),
  [para(txt("Een")), display(""), para(), para(txt("Twee"))]);
eq("math:display in a poem piece too (the dialect reads it there)", tops(dollars([para()], 0, "poem")[1]), [display(""), para()]);
eq("math:display not with other text, nor in a list item, heading, quotation or ::: poem", [
  dollars([para(txt("a "))])[0], dollars([item()])[0], dollars([heading()])[0], dollars([quote(para())])[0],
  dollars([{type: "poem", attrs: {src: null}, content: [para()]}])[0]], [false, false, false, false, false]);
eq("math:display not with the cursor before the dollars", run(at(docOf([para(txt("$$"))]), 1), B.enter(T))[0], false);
eq("math:display not while the piece is locked", run(typed("$$"), B.enter(LOCKED))[0], false);
const inlineSel = P.EditorState.create({doc: docOf([para(txt("a "), mth("x"))]), plugins: plugins()});
const selInline = inlineSel.apply(inlineSel.tr.setSelection(P.NodeSelection.create(inlineSel.doc, 3)));
const blockSel = P.EditorState.create({doc: docOf([display("x"), para()]), plugins: plugins()});
const selBlock = blockSel.apply(blockSel.tr.setSelection(P.NodeSelection.create(blockSel.doc, 0)));
eq("math:display Enter on a selected math is math's (it opens the source) and changes nothing",
  [run(selInline, B.enter(T)), run(selBlock, B.enter(T))].map(([ok, st]) => [ok, tops(st)]),
  [[true, [para(txt("a "), mth("x"))]], [true, [display("x"), para()]]]);
eq("math:display Enter elsewhere passes on", run(at(docOf([para(txt("Tekst"))]), 6), B.enter(T))[0], false);
/* / Math: display math at the cursor, as the / menu puts in a block, selected (its source opens) */
const slash = (blocks, pos) => run(at(docOf(blocks), pos), B.commands.insertDisplay);
eq("math:display / Math in an empty paragraph", (([ok, st]) => [ok, tops(st), selected(st)])(slash([para()], 1)), [true, [display(""), para()], ["math_display", 0]]);
eq("math:display / Math at a paragraph's end", (([ok, st]) => [tops(st), selected(st)])(slash([para(txt("Tekst"))], 6)),
  [[para(txt("Tekst")), display(""), para()], ["math_display", 7]]);
eq("math:display / Math at a paragraph's start", tops(slash([para(txt("Tekst"))], 1)[1]), [display(""), para(txt("Tekst"))]);
eq("math:display / Math in the middle splits it", tops(slash([para(txt("Tekst"))], 4)[1]), [para(txt("Tek")), display(""), para(txt("st"))]);
eq("math:display / Math in a list item: after it", tops(slash([item(txt("Punt")), para(txt("Na"))], 3)[1]), [item(txt("Punt")), display(""), para(txt("Na"))]);
eq("math:display / Math in a table: after it", tops(slash([table([cell(txt("A"))], [cell(txt("b"))])], 4)[1]),
  [table([cell(txt("A"))], [cell(txt("b"))]), display(""), para()]);

/* ——— math:after: text typed on selected display math goes into the line after it (made when there is none), as typing
   on a selected note or citation goes after it (book-text.js) ——— */
const blockAt = (blocks, pos) => { const st = P.EditorState.create({doc: docOf(blocks), plugins: plugins()}); return st.apply(st.tr.setSelection(P.NodeSelection.create(st.doc, pos))); };
const typedOn = (st, text) => { const tr = typeof B.typedAfter === "function" ? B.typedAfter(st, text) : "no typedAfter"; return tr && tr.doc ? st.apply(tr) : tr; };
const onMath = typedOn(blockAt([para(txt("Voor")), display("E=mc^2"), para(txt("Na"))], 6), "x");
const mathLast = typedOn(blockAt([para(txt("Voor")), display("x")], 6), "y"), beforeTable = typedOn(blockAt([display("x"), table([cell(txt("a"))])], 0), "z");
eq("math:after typed on selected display math: into the line after it, the cursor after the text",
  [onMath.doc && tops(onMath), onMath.selection && onMath.selection.from, mathLast.doc && tops(mathLast), beforeTable.doc && tops(beforeTable).map(n => n.type)],
  [[para(txt("Voor")), display("E=mc^2"), para(txt("xNa"))], 9, [para(txt("Voor")), display("x"), para(txt("y"))], ["math_display", "paragraph", "table"]]);
eq("math:after not on inline math, nor with the cursor in text", [typeof B.typedAfter === "function" && B.typedAfter(selInline, "x"),
  typeof B.typedAfter === "function" && B.typedAfter(at(docOf([para(txt("Tekst"))]), 3), "x")], [null, null]);

/* ——— math:no-dollars-price: prices stay text ——— */
for (const line of ["Het kost $20 en $30.", "Van $5 tot $10", "20$ of 30$", "kost $ 20 of $", "Prijs: $1.000, korting $50 $", "$20, $30 en $40"]) {
  eq(`math:no-dollars-price ${line}`, inl(typed(line)), [txt(line)]);
}
eq("math:no-dollars-price a price, then math", inl(typed("Prijs $5 of meer, en $y$.")), [txt("Prijs $5 of meer, en "), mth("y"), txt(".")]);

/* ——— math:escaped: a backslash escapes the dollar after it, in the text and in the TeX ——— */
eq("math:escaped \\$x$ stays text", inl(typed("\\$x$")), [txt("\\$x$")]);
eq("math:escaped a dollar after a backslash doesn't close", inl(typed("$x\\$")), [txt("$x\\$")]);
eq("math:escaped \\$ in TeX is TeX's dollar", inl(typed("$x\\$y$")), [mth("x\\$y")]);
eq("math:escaped an escaped backslash doesn't escape the dollar", inl(typed("\\\\$x$")), [txt("\\\\"), mth("x")]);
eq("math:escaped TeX ending in \\\\ closes", inl(typed("$x\\\\$")), [mth("x\\\\")]);
eq("math:escaped in a line", inl(typed("Prijs \\$5 en $y$")), [txt("Prijs \\$5 en "), mth("y")]);

/* ——— math:places: inline math is typed wherever the schema has it ——— */
eq("math:places in a heading", inl(typed("Over $x$", [heading()])), [txt("Over "), mth("x")]);
eq("math:places in a list item", inl(typed("$a_1$", [item()])), [mth("a_1")]);
eq("math:places in a table cell", inl(typed("$x$", [table([cell(txt("A"))], [cell()])], 1), 1), [mth("x")]);
eq("math:places in the title", inl(typed(" $\\pi$", [{type: "title", content: [txt("Over")]}, para()])), [txt("Over "), mth("\\pi")]);
eq("math:places in a quotation", inl(typed("$x$", [quote(para())])), [mth("x")]);
eq("math:places in a poem line and a poem piece", [inl(typed("$x$", [{type: "poem", attrs: {src: null}, content: [para()]}])),
  inl(typed("$x$", [para()], 0, "poem"))], [[mth("x")], [mth("x")]]);
const note = P.Node.fromJSON(S, {type: "note", content: [txt("Zie ")]});
eq("math:places in a note's own text", type(at(note, note.content.size), "$x$").doc.toJSON().content, [txt("Zie "), mth("x")]);
eq("math:places never across a citation or other math", [inl(typed("$", [para(txt("$a "), cite, txt(" b"))])),
  inl(typed("$", [para(txt("$a"), mth("y"), txt("b"))]))],
  [[txt("$a "), cite, txt(" b$")], [txt("$a"), mth("y"), txt("b$")]]);
// a backslash escapes the character after it, but a note or a citation is no character: it never goes into the TeX
const noteN = {type: "note", content: [txt("N")]};
eq("math:places a backslash before a citation or a note doesn't take it into math", [inl(typed("$", [para(txt("$x\\"), cite, txt("y"))])),
  inl(typed("$", [para(txt("$x\\"), noteN, txt("y"))])), inl(typed("$", [para(txt("$x \\text{a\\"), cite, txt("} y"))]))],
  [[txt("$x\\"), cite, txt("y$")], [txt("$x\\"), noteN, txt("y$")], [txt("$x \\text{a\\"), cite, txt("} y$")]]);
eq("math:typing mathStart: a backslash before U+FFFC", ["$x\\￼y$", "$x \\text{a\\￼} y$", "\\￼$x$"].map(B.mathStart), [-1, -1, 2]);

/* ——— math:parity: typed, a line is what the dialect reads from it ——— */
IN.parity.forEach(({line, content}) => eq(`math:parity ${line}`, inl(typed(line)), content));

/* ——— texError: KaTeX's message when it can't render the TeX, else null ——— */
eq("math:check KaTeX renders these", [B.texError("x^2"), B.texError("\\frac{a}{b}", true), B.texError("E = mc^2")], [null, null, null]);
eq("math:check what KaTeX can't render", [B.texError("\\foo"), B.texError("x^")].map(m => typeof m === "string" && m.length > 0), [true, true]);
eq("math:check the message names the trouble", /\\foo/.test(B.texError("\\foo")), true);
eq("math:check node views for both", Object.keys(B.nodeViews(T)).sort(), ["math", "math_display"]);

/* ——— math:katex: nothing is trusted; strict "ignore" ——— */
const has = name => typeof B[name] === "function";
eq("math:katex the options: never trusted, strict ignore", has("katexOptions") ? (() => {
  const o = B.katexOptions(true, []);
  return [o.trust({command: "\\href", url: "https://example.com", protocol: "https"}), o.trust({command: "\\includegraphics", url: "a.png"}), o.strict, o.displayMode, o.throwOnError];
})() : "missing", [false, false, "ignore", true, true]);
eq("math:katex links, pictures and HTML are refused, by name", ["\\href{https://example.com}{x}", "\\url{https://example.com}", "\\includegraphics{a.png}",
  "\\htmlClass{a}{x}", "\\htmlStyle{color:red}{x}"].map(t => { const m = B.texError(t); return typeof m === "string" && m.includes(t.slice(0, t.indexOf("{"))); }),
  [true, true, true, true, true]);
{
  const warned = [], warn0 = console.warn;
  console.warn = (...a) => warned.push(a.join(" "));
  const got = [B.texError("x = é + ü"), B.texError("\\text{één} + ∑")];
  console.warn = warn0;
  eq("math:katex Unicode in math renders without a word to the console", [got, warned.length], [[null, null], 0]);
}

/* ——— math:source: what the source field writes is the TeX the dialect writes (manuscript._inline_tex; _display_lines,
   then _display_dollars), so the editor's document is what a reload gives ——— */
IN.source.forEach(({tex, display, want}) => eq(`math:source ${display ? "display" : "inline"} ${JSON.stringify(tex)}`,
  has("sourceTex") ? B.sourceTex(tex, display) : "missing", want));

/* ——— math:wired: the writing window's own typing rules and / menu (book-text.js) ——— */
const QUOTES = () => "“…”", ALL = {notes: "footnotes", sources: true, index: true};
const withRules = (rules, text, doc = docOf([para()])) => {
  const at = doc.type === S.nodes.doc ? ends(doc)[0] : doc.content.size;
  return type(P.EditorState.create({doc, plugins: [P.inputRules({rules}), P.history()], selection: P.TextSelection.create(doc, at)}), text);
};
eq("math:wired the text's typing rules make math", inl(withRules(BT.blockRules(QUOTES), "Dus $x^2$ en")), [txt("Dus "), mth("x^2"), txt(" en")]);
eq("math:wired one Backspace gives the dollars back", inl(run(withRules(BT.blockRules(QUOTES), "Dus $x^2$"), P.undoInputRule)[1]), [txt("Dus $x^2$")]);
// the text's rules make ’ – … of ' -- ... as they are typed; in the TeX they are what was typed
eq("math:wired typography typed in TeX is TeX again", inl(withRules(BT.blockRules(QUOTES), "$f'(x) -- g...$")), [mth("f'(x) -- g...")]);
eq("math:wired a note's typing rules make math too", withRules(BT.inlineRules(QUOTES), " $x$", P.Node.fromJSON(S, {type: "note", content: [txt("Zie")]})).doc.toJSON().content,
  [txt("Zie "), mth("x")]);
eq("math:wired prices stay text, and lists are still typed", [inl(withRules(BT.blockRules(QUOTES), "Het kost $20 en $30.")), tops(withRules(BT.blockRules(QUOTES), "- Een"))[0].type],
  [[txt("Het kost $20 en $30.")], "list_item"]);
eq("math:wired / Math in prose and poem pieces", [BT.slashItems("", ALL, "prose").map(i => i.id).includes("math"), BT.slashItems("", ALL, "poem").map(i => i.id).includes("math"),
  BT.slashItems("math", ALL, "prose").map(i => i.label)], [true, true, ["Math"]]);

/* ——— math:reload — tests/test_book_math.py checks each document equals what a reload gives ——— */
const R = IN.reload, reload = {};
const typedIn = (name, k, text) => { const doc = P.Node.fromJSON(S, R[name]); reload[name] = type(at(doc, ends(doc)[k]), text).doc.toJSON(); };
typedIn("inline", 0, " $x^2$ twee");
typedIn("heading", 0, " $E = mc^2$");
typedIn("item", 0, " $a_1$");
typedIn("cell", 1, " $x$");
typedIn("title", 0, " $\\pi$");
typedIn("escaped", 0, " \\$5 en $y\\$z$");
typedIn("text-group", 0, " $x = 1 \\text{ als $y > 0$}$");
try {
  // `$$` + Enter on a new line after "Tekst", the source filled in (as the source field does), "Na" typed after it
  const doc = P.Node.fromJSON(S, R.display);
  let st = at(doc, ends(doc)[0]);
  st = st.apply(st.tr.insert(doc.content.size, S.nodes.paragraph.create()));
  st = st.apply(st.tr.setSelection(P.TextSelection.create(st.doc, st.doc.content.size - 1)));
  st = run(type(st, "$$"), B.enter(T))[1];
  const pos = st.selection.from;
  st = st.apply(st.tr.setNodeMarkup(pos, null, {tex: "E = mc^2"}));
  st = st.apply(st.tr.setSelection(P.TextSelection.create(st.doc, pos + 2)));
  reload.display = type(st, "Na").doc.toJSON();
  eq("math:display the source filled in", tops(type(st, "Na")).map(n => n.type), ["paragraph", "math_display", "paragraph"]);
} catch (e) { eq("math:display the source filled in", e.message, null); }
/* the source field given untidy source: it sets the math's TeX to B.sourceTex of what is in it (MathView.typed) */
const field = (state, pos, raw, display) => state.apply(state.tr.setNodeMarkup(pos, null, {tex: has("sourceTex") ? B.sourceTex(raw, display) : raw}));
try {
  const doc = P.Node.fromJSON(S, R["source-inline"]);
  const st = type(at(doc, ends(doc)[0]), " $x$");
  reload["source-inline"] = field(st, st.selection.from - 1, IN.sourceInline, false).doc.toJSON();
} catch (e) { eq("math:source inline in the document", e.message, null); }
try {
  const doc = P.Node.fromJSON(S, R["source-display"]);
  let st = at(doc, ends(doc)[0]);
  st = st.apply(st.tr.insert(doc.content.size, S.nodes.paragraph.create()));
  st = st.apply(st.tr.setSelection(P.TextSelection.create(st.doc, st.doc.content.size - 1)));
  st = run(type(st, "$$"), B.enter(T))[1];
  const pos = st.selection.from;
  st = field(st, pos, IN.sourceDisplay, true);
  st = st.apply(st.tr.setSelection(P.TextSelection.create(st.doc, pos + 2)));
  reload["source-display"] = type(st, "Na").doc.toJSON();
} catch (e) { eq("math:source display in the document", e.message, null); }

/* ——— math:escape: Escape in the source field closes it and goes back to the text: after inline math, into the line after
   display math (made when there is none), so a letter typed next never replaces the math. The field (MathView.key, then
   close) on stand-ins for its elements and the view; last, as it puts what the field's code needs in place. ——— */
globalThis.removeEventListener = () => {};
globalThis.document = {removeEventListener() {}};
function escaped(blocks, pos, key = {key: "Escape"}) {
  const doc = docOf(blocks), view = {state: P.EditorState.create({doc, plugins: plugins(), selection: P.NodeSelection.create(doc, pos)}),
    dispatch(tr) { this.state = this.state.apply(tr); }, focus() {}};
  const mv = Object.assign(Object.create(B.MathView.prototype), {node: doc.nodeAt(pos), view, getPos: () => pos, T: {locked: false},
    display: doc.nodeAt(pos).type === S.nodes.math_display, box: {remove() {}}, dom: {classList: {remove() {}}}});
  mv.key(Object.assign({isComposing: false, preventDefault() {}, stopPropagation() {}}, key));
  return view.state;
}
const escDisplay = escaped([para(txt("Voor")), display("E=mc^2"), para(txt("Na"))], 6), escLast = escaped([para(txt("Voor")), display("x")], 6);
const escInline = escaped([para(txt("a "), mth("x"), txt(" b"))], 3), ctrlEnter = escaped([para(txt("Voor")), display("x")], 6, {key: "Enter", ctrlKey: true});
eq("math:escape from display math: into the line after it, made when there is none; a letter typed then goes there",
  [escDisplay.selection instanceof P.TextSelection, escDisplay.selection.from, tops(type(escDisplay, "x")), tops(escLast), escLast.selection.from],
  [true, 8, [para(txt("Voor")), display("E=mc^2"), para(txt("xNa"))], [para(txt("Voor")), display("x"), para()], 8]);
eq("math:escape from inline math: the cursor right after it; Ctrl+Enter as before", [escInline.selection instanceof P.TextSelection, escInline.selection.from,
  tops(ctrlEnter), ctrlEnter.selection.from], [true, 4, [para(txt("Voor")), display("x"), para()], 8]);

process.stdout.write(JSON.stringify({failures, checked, reload}));
