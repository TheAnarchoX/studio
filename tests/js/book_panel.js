/* Runs the format panel's pure parts (studio/static/book-panel.js) in node: the rows and buttons the panel shows for a
   state and which of them are pressed, the palette's Format group where the cursor is, how a key is written on Windows
   and on macOS, where the panel goes, and how the arrow keys and Tab move in it. Used by tests/test_book_panel.py.

     node book_panel.js <prosemirror.js> <book-schema.js> <book-format.js> <book-panel.js> <book-table.js>
     output: {"failures": [{"name", "got", "want"}], "checked": n}   */
"use strict";
const fs = require("fs"), vm = require("vm");
const [pm, schema, format, panel, table] = process.argv.slice(2);
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(pm, "utf8"));
if (typeof PM !== "undefined") globalThis.PM = PM;
vm.runInThisContext(fs.readFileSync(schema, "utf8"));
vm.runInThisContext(fs.readFileSync(format, "utf8"));
vm.runInThisContext(fs.readFileSync(panel, "utf8"));
vm.runInThisContext(fs.readFileSync(table, "utf8"));       // as index.html: after the panel, which reads it when used
const F = globalThis.BookFormat, B = globalThis.BookPanel, S = globalThis.BookSchema, P = globalThis.PM;
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };

/* ——— documents and states ——— */
const txt = (s, marks) => (marks ? {type: "text", text: s, marks} : {type: "text", text: s});
const para = s => (s ? {type: "paragraph", content: [txt(s)]} : {type: "paragraph"});
const item = (list, s, level = 0) => ({type: "list_item", attrs: {list, level, start: null}, content: [txt(s)]});
const hd = (s, level = 2) => ({type: "heading", attrs: {level}, content: [txt(s)]});
const al = (align, s) => ({type: "aligned", attrs: {align}, content: [para(s)]});
const titled = s => ({type: "title", content: [txt(s)]});
const docOf = (blocks, form = "prose") => P.Node.fromJSON(S, {type: "doc", attrs: {form}, content: blocks});
/* the position of the first text `s` in `doc`, plus `offset` */
function textAt(doc, s, offset = 0) {
  let at = null;
  doc.descendants((n, pos) => { if (at == null && n.isText && n.text.includes(s)) at = pos + n.text.indexOf(s) + offset; return at == null; });
  if (at == null) throw new Error(`no text ${s}`);
  return at;
}
/* the cursor at the start of the text `s`; the text from `a` to the end of `b` selected */
const on = (blocks, s, form) => { const doc = docOf(blocks, form), at = textAt(doc, s); return P.EditorState.create({doc, selection: P.TextSelection.create(doc, at)}); };
const over = (blocks, a, b = a, form) => { const doc = docOf(blocks, form); return P.EditorState.create({doc, selection: P.TextSelection.create(doc, textAt(doc, a), textAt(doc, b, b.length))}); };
const noteState = P.EditorState.create({doc: S.nodes.note.create(null, S.text("Noot"))});
const imageSel = (() => {
  const doc = docOf([para("Een"), {type: "image", attrs: {src: "../images/a.png"}}]);
  return P.EditorState.create({doc, selection: P.NodeSelection.create(doc, doc.child(0).nodeSize)});
})();
const list = [item("decimal", "Een"), item("decimal", "Twee")];

/* ——— the panel's rows: [row, its buttons pressed, its buttons that can't be pressed] ——— */
const shape = state => B.rows(state, false).map(r => [r.id, r.buttons.filter(b => b.pressed).map(b => b.id), r.buttons.filter(b => b.disabled).map(b => b.id)]);
eq("rows:paragraph every row, the paragraph's state pressed, Outdent and Indent not here", shape(on([para("Een")], "Een")),
  [["text", ["paragraph"], []], ["list", [], ["outdent", "indent"]], ["align", ["align-book"], []], ["size", ["size-normal"], []], ["style", [], []]]);
eq("rows:list item no Align; its list style pressed; Indent from the second item", [shape(on(list, "Twee")), shape(on(list, "Een"))],
  [[["text", ["paragraph"], []], ["list", ["decimal"], ["outdent"]], ["size", ["size-normal"], []], ["style", [], []]],
   [["text", ["paragraph"], []], ["list", ["decimal"], ["outdent", "indent"]], ["size", ["size-normal"], []], ["style", [], []]]]);
eq("rows:sub-item Outdent", shape(on([item("decimal", "Een"), item("lower-alpha", "Twee", 1)], "Twee"))[1], ["list", ["lower-alpha"], ["indent"]]);
eq("rows:note only Size and Style", shape(noteState), [["size", ["size-normal"], []], ["style", [], []]]);
eq("rows:title only Size and Style", shape(on([titled("Titel"), para("x")], "Titel")).map(r => r[0]), ["size", "style"]);
eq("rows:poem piece no List or Align", shape(on([para("Regel")], "Regel", "poem")).map(r => r[0]), ["text", "size", "style"]);
eq("rows:heading no Align", shape(on([hd("Kop")], "Kop")).map(r => r.slice(0, 2)), [["text", ["heading"]], ["list", []], ["size", ["size-normal"]], ["style", []]]);
eq("rows:a selected image nothing", B.rows(imageSel, false), []);
/* the buttons pressed in row `id` */
const pressedIn = (state, id) => (shape(state).find(r => r[0] === id) || [id, null])[1];
const rich = {type: "paragraph", content: [txt("Een", [{type: "size", attrs: {size: "large"}}, {type: "strong"}, {type: "em"}, {type: "smallcaps"}])]};
eq("rows:state centred, right, large, bold and italic, small caps", [shape(on([al("center", "Een")], "Een")).map(r => r[0]), pressedIn(on([al("center", "Een")], "Een"), "align"),
  pressedIn(on([al("right", "Een")], "Een"), "align"), pressedIn(over([rich], "Een"), "size"), pressedIn(over([rich], "Een"), "style")],
  [["text", "align", "size", "style"], ["align-center"], ["align-right"], ["size-large"], ["strong", "em", "smallcaps"]]);
eq("rows:mixed nothing pressed", [pressedIn(over([para("Een"), hd("Twee")], "Een", "Twee"), "text"), pressedIn(over([al("center", "Een"), al("right", "Twee")], "Een", "Twee"), "align")],
  [[], []]);
eq("rows:what is typed next", pressedIn((st => st.apply(st.tr.addStoredMark(S.marks.underline.create())))(on([para("Een")], "Een")), "style"), ["underline"]);

/* the buttons: what they show, their names and keys, as the spec draws the panel */
const all = B.rows(on([para("Een")], "Een"), false);
eq("buttons:text", all.map(r => [r.label, r.buttons.map(b => b.text)]), [
  ["Text", ["Paragraph", "Heading", "Subheading", "Quotation"]],
  ["List", ["•", "1.", "a.", "A.", "i.", "I.", "Outdent", "Indent"]],
  ["Align", ["As the book", "Centre", "Right"]],
  ["Size", ["A", "A", "A", "A", "A"]],
  ["Style", ["B", "I", "U", "S", "Small caps", "Clear"]]]);
const btn = id => all.flatMap(r => r.buttons).find(b => b.id === id);
eq("buttons:names and keys", ["paragraph", "quotation", "bullet", "lower-roman", "upper-roman", "indent", "align-book", "align-center", "strike", "clear"]
  .map(id => [btn(id).name, btn(id).key]),
  [["Paragraph", "Ctrl+Alt+0"], ["Quotation", ""], ["Bulleted list", "Ctrl+Shift+8"], ["Roman list (small)", ""], ["Roman list", ""], ["Indent", "Ctrl+]"],
   ["Align as the book", "Ctrl+Shift+L"], ["Centre", "Ctrl+Shift+E"], ["Strikethrough", "Alt+Shift+5"], ["Clear formatting", "Ctrl+Space"]]);
eq("buttons:the size ladder, Normal in the middle, each at its own size, with the step keys",
  all[3].buttons.map(b => [b.name, b.scale, b.key]),
  [["Extra small", .75, "Smaller Ctrl+Shift+, · Larger Ctrl+Shift+."], ["Small", .875, "Smaller Ctrl+Shift+, · Larger Ctrl+Shift+."],
   ["Normal size", 1, "Smaller Ctrl+Shift+, · Larger Ctrl+Shift+."], ["Large", 1.2, "Smaller Ctrl+Shift+, · Larger Ctrl+Shift+."],
   ["Extra large", 1.44, "Smaller Ctrl+Shift+, · Larger Ctrl+Shift+."]]);
eq("buttons:toggles say pressed or not, actions neither", ["paragraph", "bullet", "indent", "outdent", "align-right", "size-large", "em", "clear"].map(id => btn(id).pressed),
  [true, false, null, null, false, false, false, null]);
eq("buttons:set apart at the row's end", all.flatMap(r => r.buttons).filter(b => b.apart).map(b => b.id), ["outdent", "clear"]);
eq("buttons:on macOS", ["paragraph", "indent", "strike", "strong"].map(id => B.rows(on([para("Een")], "Een"), true).flatMap(r => r.buttons).find(b => b.id === id).key)
  .concat([B.rows(on([para("Een")], "Een"), true)[3].buttons[0].key]),
  ["⌥⌘0", "⌘]", "⌥⇧5", "⌘B", "Smaller ⇧⌘, · Larger ⇧⌘."]);
eq("buttons:every button's command is a command", all.flatMap(r => r.buttons).filter(b => typeof B.COMMANDS[b.id] !== "function").map(b => b.id), []);
eq("buttons:the five rows are KEYS' groups", all.map(r => r.label), [...new Set(F.KEYS.map(k => k.group))].filter(g => g !== "Format"));

/* ——— keys as written ——— */
eq("keyText", [B.keyText("Ctrl+Shift+E", false), B.keyText("Ctrl+Shift+E", true), B.keyText("Alt+O", true), B.keyText("Alt+O", false),
  B.keyText("Alt+Shift+5", true), B.keyText("Ctrl+Space", true), B.keyText(null, true), B.keyText("", false)],
  ["Ctrl+Shift+E", "⇧⌘E", "⌃⌥O", "Alt+O", "⌥⇧5", "⌘Space", "", ""]);

/* ——— the palette's Format group ——— */
const labels = state => B.paletteRows(state).map(r => r.label);
const LIST = ["Bulleted list", "Numbered list", "Lettered list", "Lettered list (capitals)", "Roman list", "Roman list (small)", "Indent", "Outdent", "Make a list of these lines"];
eq("palette:applies in a list item Indent, not Centre", [labels(on(list, "Twee")).includes("Indent"), labels(on(list, "Twee")).includes("Centre"),
  labels(on(list, "Een")).includes("Indent"), labels(on(list, "Twee")).includes("Outdent")], [true, false, false, false]);
eq("palette:poem piece no list commands, no alignment", labels(on([para("Regel")], "Regel", "poem")).filter(l => LIST.includes(l) || /^(Align|Centre|Right)/.test(l)), []);
eq("palette:note only sizes and styles", labels(noteState),
  ["Larger", "Smaller", "Normal size", "Bold", "Italic", "Underline", "Strikethrough", "Small caps", "Clear formatting", "Format…"]);
eq("palette:paragraph every command but Indent, Outdent and Make a list", labels(on([para("Een")], "Een")),
  ["Paragraph", "Heading", "Subheading", "Quotation", "Bulleted list", "Numbered list", "Lettered list", "Lettered list (capitals)", "Roman list",
   "Roman list (small)", "Align as the book", "Centre", "Right", "Larger", "Smaller", "Normal size", "Bold", "Italic", "Underline", "Strikethrough",
   "Small caps", "Clear formatting", "Format…"]);
eq("palette:typed markers Make a list of these lines", labels(on([para("1. Een")], "1. Een")).includes("Make a list of these lines"), true);
eq("palette:a selected image nothing, not even Format…", labels(imageSel), []);
eq("palette:every KEYS row has a command", F.KEYS.filter(k => k.id !== "format" && typeof B.commandOf(k) !== "function").map(k => k.id), []);

/* paletteActions: {label, hint, run} on the view the author writes in */
const fakeView = state => ({state, dispatch(tr) { this.state = this.state.apply(tr); }, focus() { this.focused = true; }});
const fakeT = (state, extra = {}) => { const T = {locked: false, view: fakeView(state), ...extra}; T.activeView = () => T.view; return T; };
const T1 = fakeT(on([para("Een")], "Een")), acts = F.paletteActions(T1);
eq("paletteActions:labels and hints", acts.filter(a => ["Heading", "Quotation", "Centre", "Format…"].includes(a.label)).map(a => [a.label, a.hint]),
  [["Heading", B.keyText("Ctrl+Alt+2")], ["Quotation", ""], ["Centre", B.keyText("Ctrl+Shift+E")], ["Format…", B.keyText("Alt+O")]]);
acts.find(a => a.label === "Centre").run();
eq("paletteActions:run applies to the view and gives it the focus", [T1.view.state.doc.child(0).type.name, T1.view.state.doc.child(0).attrs.align, T1.view.focused],
  ["aligned", "center", true]);
let opened = null;
const realOpen = F.openPanel;
F.openPanel = (T, view) => { opened = [T, view]; };
F.paletteActions(T1).find(a => a.label === "Format…").run();
F.openPanel = realOpen;
eq("paletteActions:Format… opens the panel on that view", [opened[0] === T1, opened[1] === T1.view], [true, true]);
eq("paletteActions:locked or no text nothing", [F.paletteActions(fakeT(on([para("Een")], "Een"), {locked: true})), F.paletteActions(null), F.paletteActions(undefined)], [[], [], []]);
const T2 = fakeT(on([para("Een")], "Een")), bold = F.paletteActions(T2).find(a => a.label === "Bold");
T2.locked = true;
bold.run();
eq("paletteActions:a run while locked does nothing", [T2.view.state.storedMarks, !!T2.view.focused], [null, false]);
/* a note the author was writing in, the palette having the focus now (book-tools.js keeps T.lastView) */
const noteView = fakeView(noteState), T3 = fakeT(on([para("Een")], "Een"), {lastView: noteView, margin: {notes: new Set([{inner: noteView}])}});
T3.view.hasFocus = () => false;
eq("paletteActions:in the note last written in", F.paletteActions(T3).map(a => a.label), labels(noteState));
T3.view.hasFocus = () => true;
eq("paletteActions:in the text when it has the focus", F.paletteActions(T3).length, labels(on([para("Een")], "Een")).length);

/* ——— in a table: the table's rows instead of Text, List and Align; its commands in the palette ——— */
const cell = s => (s ? {type: "table_cell", content: [txt(s)]} : {type: "table_cell"});
const tbl = (rows, align, header = true) => ({type: "table", attrs: {header, align}, content: rows.map(r => ({type: "table_row", content: r.map(cell)}))});
const inTable = [para("Voor"), tbl([["Naam", "Jaar"], ["Een", "1990"]], [null, "right"])];
eq("table:applies size, style and the table", [F.applies(on(inTable, "1990")), F.applies(on(inTable, "Voor")).table, F.current(on(inTable, "1990")).table],
  [{text: false, list: false, align: false, size: true, style: true, table: true}, false, {header: true, align: "right", row: 1, col: 1, rows: 2, cols: 2}]);
eq("table:rows instead of Text, List and Align; the column's alignment and the header pressed", shape(on(inTable, "1990")),
  [["table-row", [], []], ["table-column", [], []], ["table-align", ["table-align-right"], []], ["table", ["table-header"], []],
   ["size", ["size-normal"], []], ["style", [], []]]);
const tableRows = B.rows(on(inTable, "Naam"), false);
eq("table:the buttons: what they show, their names and keys", tableRows.slice(0, 4).map(r => [r.label, r.buttons.map(b => [b.text, b.name, b.key])]), [
  ["Row", [["Above", "Row above", "Ctrl+Alt+↑"], ["Below", "Row below", "Ctrl+Alt+↓"], ["Delete", "Delete row", ""]]],
  ["Column", [["Left", "Column left", "Ctrl+Alt+←"], ["Right", "Column right", "Ctrl+Alt+→"], ["Delete", "Delete column", ""]]],
  ["Align", [["As the book", "Align column as the book", ""], ["Left", "Align column left", ""], ["Centre", "Centre column", ""], ["Right", "Align column right", ""]]],
  ["Table", [["Header row", "Header row", ""], ["Delete table", "Delete table", ""]]]]);
eq("table:pressed: as the book, the header off; actions neither", [pressedIn(on(inTable, "Naam"), "table-align"),
  pressedIn(on([tbl([["a", "b"]], [null, null], false)], "a"), "table"), tableRows[0].buttons.map(b => b.pressed)],
  [["table-align-book"], [], [null, null, null]]);
eq("table:on macOS", B.rows(on(inTable, "Naam"), true)[0].buttons.map(b => b.key), ["⌥⌘↑", "⌥⌘↓", ""]);
const tableLabels = labels(on(inTable, "Naam"));
eq("table:palette the table's commands, Format… last; none outside a table", [tableLabels.slice(-13), labels(on(inTable, "Voor")).some(l => /column|Row above|table/i.test(l))],
  [["Row above", "Row below", "Column left", "Column right", "Delete row", "Delete column", "Header row", "Align column as the book",
    "Align column left", "Centre column", "Align column right", "Delete table", "Format…"], false]);
eq("table:palette no text styles, lists or alignment of paragraphs in a cell", tableLabels.filter(l => ["Paragraph", "Heading", "Bulleted list", "Centre", "Indent"].includes(l)), []);
const T4 = fakeT(on(inTable, "Naam"));
F.paletteActions(T4).find(a => a.label === "Column right").run();
eq("table:paletteActions run a table's command", [T4.view.state.doc.child(1).child(0).childCount, T4.view.state.doc.child(1).attrs.align, T4.view.focused],
  [3, [null, null, "right"], true]);

/* ——— where the panel goes: in the page's coordinates ——— */
const page = {left: 0, right: 1000, top: -200}, col = {left: 200, right: 700}, seen = {top: 0, bottom: 800};
const at = (left, top, bottom = top + 24) => ({left, top, bottom});
eq("place:under the cursor, 16px before it", B.place(at(300, 100), 400, 200, page, col, seen), {left: 284, top: 334});
eq("place:above it when there's no room below", B.place(at(300, 700), 400, 200, page, col, seen), {left: 284, top: 690});
eq("place:below when there's no room either side and more below", B.place(at(300, 150), 400, 700, page, col, seen), {left: 284, top: 384});
eq("place:kept in the text column when it fits", B.place(at(650, 100), 400, 200, page, col, seen).left, 300);
eq("place:kept inside the page", [B.place(at(990, 100), 900, 200, page, {left: 900, right: 990}, seen).left, B.place(at(5, 100), 300, 200, {left: 0, right: 360, top: 0}, {left: 0, right: 120}, seen).left],
  [84, 16]);

/* ——— the keys in the panel: [row, column] to go to ——— */
const g = (...rows) => rows.map(r => r.map(([x, enabled = true]) => ({x, enabled})));
const grid = g([[10], [50], [90], [130]], [[10], [50, false], [90], [200]], [[60], [140]]);
eq("move:left and right along the row, round, past what can't be pressed",
  [B.move(grid, [0, 0], "ArrowRight"), B.move(grid, [0, 3], "ArrowRight"), B.move(grid, [0, 0], "ArrowLeft"), B.move(grid, [1, 0], "ArrowRight"), B.move(grid, [1, 2], "ArrowLeft")],
  [[0, 1], [0, 0], [0, 3], [1, 2], [1, 0]]);
eq("move:Home and End", [B.move(grid, [0, 2], "Home"), B.move(grid, [0, 1], "End")], [[0, 0], [0, 3]]);
eq("move:up and down to the nearest button, round",
  [B.move(grid, [0, 1], "ArrowDown"), B.move(grid, [0, 3], "ArrowDown"), B.move(grid, [1, 3], "ArrowDown"), B.move(grid, [2, 0], "ArrowDown"), B.move(grid, [0, 0], "ArrowUp")],
  [[1, 0], [1, 2], [2, 1], [0, 1], [2, 0]]);
eq("move:Tab and Shift+Tab through every button, round", [B.move(grid, [0, 3], "Tab"), B.move(grid, [1, 0], "Tab"), B.move(grid, [2, 1], "Tab"), B.move(grid, [0, 0], "Shift+Tab")],
  [[1, 0], [1, 2], [0, 0], [2, 1]]);
eq("move:other keys", B.move(grid, [0, 0], "a"), null);

console.log(JSON.stringify({failures, checked}));
