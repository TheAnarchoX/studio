/* Runs the tables of the writing window (studio/static/book-table.js) in node: / Table, Tab and Shift+Tab, Enter, rows
   and columns, the column's alignment, the header row, Backspace in an empty table, poem pieces, one undo per command,
   what is on where the cursor is, the keys and KEYS, the Table button's menu, the decorations; and documents after an
   edit for the reload check. Used by tests/test_book_table.py.

     node book_table.js <prosemirror.js> <book-schema.js> <book-table.js> <input.json>
     input: {"reload": {scenario: document parsed from the scenario's Markdown}}
     output: {"failures": [{"name", "got", "want"}], "checked": n, "reload": {scenario: document after its edit}}   */
"use strict";
const fs = require("fs"), vm = require("vm");
const [pm, schema, table, input] = process.argv.slice(2);
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(pm, "utf8"));
if (typeof PM !== "undefined") globalThis.PM = PM;
vm.runInThisContext(fs.readFileSync(schema, "utf8"));
vm.runInThisContext(fs.readFileSync(table, "utf8"));
const B = globalThis.BookTable, S = globalThis.BookSchema, P = globalThis.PM, C = B.commands;
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };
const IN = JSON.parse(fs.readFileSync(input, "utf8"));

/* ——— documents and states ——— */
const txt = s => ({type: "text", text: s});
const para = s => (s ? {type: "paragraph", content: [txt(s)]} : {type: "paragraph"});
const heading = s => ({type: "heading", attrs: {level: 2}, content: [txt(s)]});
const cell = s => (s ? {type: "table_cell", content: [txt(s)]} : {type: "table_cell"});
/* a table of rows of cell texts; header and align as given (align: one null per column by default) */
const tbl = (rows, {header = true, align = null} = {}) => ({type: "table", attrs: {header, align: align || rows[0].map(() => null)},
  content: rows.map(r => ({type: "table_row", content: r.map(cell)}))});
const docOf = (blocks, form = "prose") => P.Node.fromJSON(S, {type: "doc", attrs: {form}, content: blocks});
const posOf = (doc, i) => { let p = 0; for (let k = 0; k < i; k++) p += doc.child(k).nodeSize; return p; };
/* the position in cell (r, c) of the table that is top-level block i, at `offset` (the cell's end when null) */
function cellPos(doc, i, r, c, offset = null) {
  const t = doc.child(i);
  let p = posOf(doc, i) + 1;
  for (let k = 0; k < r; k++) p += t.child(k).nodeSize;
  const row = t.child(r);
  p += 1;
  for (let k = 0; k < c; k++) p += row.child(k).nodeSize;
  return p + 1 + (offset == null ? row.child(c).content.size : offset);
}
/* the position in top-level text block i at `offset` (its end when null) */
const textPos = (doc, i, offset = null) => posOf(doc, i) + 1 + (offset == null ? doc.child(i).content.size : offset);
const plugins = () => [P.history(), ...B.plugins()];
/* a state on `blocks`, the cursor at `at`: [i, r, c, offset?] in a cell, [i, offset?] in a text block, {pos} */
function make(blocks, at, form = "prose") {
  const doc = docOf(blocks, form);
  const pos = at.pos != null ? at.pos : at.length >= 3 ? cellPos(doc, ...at) : textPos(doc, ...at);
  return P.EditorState.create({doc, plugins: plugins(), selection: P.TextSelection.create(doc, pos)});
}
/* a command on a state: [what it returned, the state after it] */
function run(state, cmd) { let next = state; const ok = cmd(state, tr => { next = next.apply(tr); }); return [ok, next]; }
const after = (state, cmd) => run(state, cmd)[1];
const typeIn = (state, s) => state.apply(state.tr.insertText(s));
/* commands and typed text, one after the other */
const steps = (state, ...todo) => todo.reduce((st, t) => (typeof t === "string" ? typeIn(st, t) : after(st, t)), state);
const json = state => JSON.stringify(state.doc.toJSON());
/* the blocks: a table as ["table", header, align, [[cell texts]]], anything else as [type, text] */
const shape = state => state.doc.content.content.map(n => (n.type === S.nodes.table
  ? ["table", n.attrs.header, n.attrs.align, n.content.content.map(r => r.content.content.map(c => c.textContent))]
  : [n.type.name, n.textContent]));
const cells = state => shape(state).find(b => b[0] === "table")[3];
const aligns = state => shape(state).find(b => b[0] === "table")[2];
/* where the cursor is: [row, col, offset in the cell] in a table, else [top-level index, the block's type, offset] */
function where(state) {
  const cur = B.current(state), $f = state.selection.$from;
  return cur ? [cur.row, cur.col, $f.parentOffset] : [$f.index(0), $f.parent.type.name, $f.parentOffset];
}
/* the decorations of the state's plugins */
const decos = state => state.plugins.flatMap(p => (p.props.decorations ? p.props.decorations.call(p, state).find() : []));
/* the cells the decorations align: [row, col, align] */
const alignedCells = state => decos(state).filter(d => d.type.attrs && d.type.attrs["data-align"])
  .map(d => { const $p = state.doc.resolve(d.from + 1); return [$p.index(1), $p.index(2), d.type.attrs["data-align"]]; })
  .sort((a, b) => JSON.stringify(a) < JSON.stringify(b) ? -1 : 1);
/* the tables marked as holding the cursor (their Table button shows) */
const lit = state => decos(state).filter(d => d.type.attrs && d.type.attrs.class === "bk-table-on").map(d => d.from);

const ABC = [tbl([["A", "B", "C"], ["a", "b", "c"], ["d", "e", "f"]], {align: [null, "center", "right"]})];
const GRID = [tbl([["a", "b"], ["c", "d"]])];
const THREE = [tbl([["Kop", "Kop"], ["a", "b"], ["c", "d"]])];
const plain = make([para("Een")], [0]);

/* ——— / Table ——— */
const fresh = after(make([para()], [0, 0]), C.insertTable());
eq("table:insert three columns, a header row and two rows, the cursor in the first cell", [shape(fresh), where(fresh), B.current(fresh)],
  [[["table", true, [null, null, null], [["", "", ""], ["", "", ""], ["", "", ""]]]], [0, 0, 0],
   {header: true, align: null, row: 0, col: 0, rows: 3, cols: 3}]);
const placed = at => shape(after(make([para("Een twee")], at), C.insertTable(2, 1))).map(b => (b[0] === "table" ? "T" : b[1]));
eq("table:insert where a block goes: after the line, before it, between its halves", [placed([0]), placed([0, 0]), placed([0, 4])],
  [["Een twee", "T"], ["T", "Een twee"], ["Een ", "T", "twee"]]);
eq("table:insert insertTable(2, 1): two columns, a header row and one row", shape(after(make([para()], [0, 0]), C.insertTable(2, 1))),
  [["table", true, [null, null], [["", ""], ["", ""]]]]);
const afterHeading = after(make([heading("Kop"), para("Tekst")], [0, 1]), C.insertTable(1, 1));
eq("table:insert after a heading, the cursor in its first cell", [shape(afterHeading).map(b => b[0]), where(afterHeading)],
  [["heading", "table", "paragraph"], [0, 0, 0]]);
const twoTables = after(make([tbl([["a"]])], [0, 0, 0, 0]), C.insertTable(1, 1));
eq("table:insert in a table: after it", [shape(twoTables), twoTables.selection.from], [[["table", true, [null], [["a"]]], ["table", true, [null], [[""], [""]]]], 10]);
const noteDoc = P.Node.fromJSON(S, {type: "note", content: [txt("noot")]});
eq("table:insert answers without dispatch; not in a note's text",
  [C.insertTable()(make([para()], [0, 0])), C.insertTable()(P.EditorState.create({doc: noteDoc, selection: P.TextSelection.create(noteDoc, 2)}), () => {})],
  [true, false]);

/* ——— poems: no table in a poem piece ——— */
const poemPiece = make([para("Regel")], [0], "poem"), poemRun = run(poemPiece, C.insertTable());
eq("table:no-poem refused in a poem piece", [C.insertTable()(poemPiece), poemRun[0], json(poemRun[1]) === json(poemPiece)], [false, false, true]);
const poemBlockDoc = docOf([para("Proza."), {type: "poem", attrs: {src: null}, content: [para("regel")]}]);
const inPoemBlock = after(P.EditorState.create({doc: poemBlockDoc, plugins: plugins(), selection: P.TextSelection.create(poemBlockDoc, 15)}), C.insertTable(1, 1));
eq("table:no-poem a ::: poem block in a prose piece: the table after it, at the top level", shape(inPoemBlock).map(b => b[0]),
  ["paragraph", "poem", "table"]);

/* ——— outside a table every command passes ——— */
eq("table:outside the commands return false", [C.nextCell(1)(plain), C.nextCell(-1)(plain), C.cellEnter(plain), C.cellBackspace(plain),
  C.addRow(-1)(plain), C.addRow(1)(plain), C.addColumn(-1)(plain), C.addColumn(1)(plain), C.deleteRow(plain), C.deleteColumn(plain),
  C.toggleHeader(plain), C.setColumnAlign("center")(plain), C.deleteTable(plain), B.inTable(plain), B.current(plain)],
  [false, false, false, false, false, false, false, false, false, false, false, false, false, false, null]);
const leaving = (() => { const st = make([...ABC, para("Na")], [0, 1, 1]); return st.apply(st.tr.setSelection(P.TextSelection.create(st.doc, st.selection.from, st.doc.content.size - 1))); })();
const across = (() => { const st = make(ABC, [0, 1, 0, 0]); return st.apply(st.tr.setSelection(P.TextSelection.create(st.doc, st.selection.from, cellPos(st.doc, 0, 2, 2)))); })();
eq("table:outside a selection that leaves the table is not in it; one across cells is", [B.inTable(leaving), C.nextCell(1)(leaving),
  B.inTable(across), B.current(across)], [false, false, true, {header: true, align: null, row: 1, col: 0, rows: 3, cols: 3}]);

/* ——— Tab and Shift+Tab ——— */
const tabs = [make(GRID, [0, 0, 0, 0])];
for (let k = 0; k < 4; k++) tabs.push(after(tabs[k], C.nextCell(1)));
eq("table:tab Tab walks the cells, the cursor at the end of each", tabs.slice(1, 4).map(where), [[0, 1, 1], [1, 0, 1], [1, 1, 1]]);
eq("table:tab Tab in the last cell adds a row", [shape(tabs[4]), where(tabs[4])],
  [[["table", true, [null, null], [["a", "b"], ["c", "d"], ["", ""]]]], [2, 0, 0]]);
const backs = [tabs[3]];
for (let k = 0; k < 3; k++) backs.push(after(backs[k], C.nextCell(-1)));
eq("table:tab Shift+Tab goes back", backs.slice(1).map(where), [[1, 0, 1], [0, 1, 1], [0, 0, 1]]);
const firstCell = run(backs[3], C.nextCell(-1));
eq("table:tab Shift+Tab in the first cell stays, and keeps the key", [firstCell[0], firstCell[1] === backs[3]], [true, true]);
eq("table:tab Tab, typed: the text in the new row", cells(steps(tabs[3], C.nextCell(1), "e")), [["a", "b"], ["c", "d"], ["e", ""]]);

/* ——— Enter ——— */
eq("table:enter goes to the cell below", where(after(make(THREE, [0, 0, 1, 1]), C.cellEnter)), [1, 1, 1]);
const out1 = after(make(THREE, [0, 2, 0]), C.cellEnter);
eq("table:enter in the last row: a paragraph made after the table", [shape(out1).slice(1), where(out1)], [[["paragraph", ""]], [1, "paragraph", 0]]);
const out2 = after(make([...THREE, para("Na")], [0, 2, 1]), C.cellEnter);
eq("table:enter in the last row: into the paragraph after it", [shape(out2).length, where(out2)], [2, [1, "paragraph", 0]]);
const out3 = after(make([...THREE, {type: "scene_break"}], [0, 2, 1]), C.cellEnter);
const out4 = after(make([...THREE, heading("Kop")], [0, 2, 1]), C.cellEnter);
eq("table:enter in the last row: a paragraph made before a block that is no paragraph",
  [shape(out3).map(b => b[0]), where(out3), shape(out4).map(b => b[0]), where(out4)],
  [["table", "paragraph", "scene_break"], [1, "paragraph", 0], ["table", "paragraph", "heading"], [1, "paragraph", 0]]);

/* ——— rows and columns ——— */
const rowAbove = after(make(ABC, [0, 1, 1]), C.addRow(-1));
eq("table:rows-columns a row above, the cursor in it", [cells(rowAbove), where(rowAbove)],
  [[["A", "B", "C"], ["", "", ""], ["a", "b", "c"], ["d", "e", "f"]], [1, 1, 0]]);
const rowBelow = after(make(ABC, [0, 1, 1]), C.addRow(1));
eq("table:rows-columns a row below, the cursor in it", [cells(rowBelow), where(rowBelow)],
  [[["A", "B", "C"], ["a", "b", "c"], ["", "", ""], ["d", "e", "f"]], [2, 1, 0]]);
const colLeft = after(make(ABC, [0, 1, 1]), C.addColumn(-1));
eq("table:rows-columns a column left: align keeps one per column", [aligns(colLeft), cells(colLeft), where(colLeft)],
  [[null, null, "center", "right"], [["A", "", "B", "C"], ["a", "", "b", "c"], ["d", "", "e", "f"]], [1, 1, 0]]);
const colRight = after(make(ABC, [0, 1, 2]), C.addColumn(1));
eq("table:rows-columns a column right: align keeps one per column", [aligns(colRight), cells(colRight), where(colRight)],
  [[null, "center", "right", null], [["A", "B", "C", ""], ["a", "b", "c", ""], ["d", "e", "f", ""]], [1, 3, 0]]);
const delRow = after(make(ABC, [0, 1, 1]), C.deleteRow);
eq("table:rows-columns Delete row: the cursor in the row that takes its place", [cells(delRow), where(delRow)],
  [[["A", "B", "C"], ["d", "e", "f"]], [1, 1, 1]]);
eq("table:rows-columns Delete row in the last row: the row above", where(after(make(ABC, [0, 2, 1]), C.deleteRow)), [1, 1, 1]);
const delHeader = after(make(ABC, [0, 0, 0]), C.deleteRow);
eq("table:rows-columns Delete row on the header row: the next row is the header", [shape(delHeader)[0][1], cells(delHeader)[0]], [true, ["a", "b", "c"]]);
const delCol = after(make(ABC, [0, 1, 1]), C.deleteColumn);
eq("table:rows-columns Delete column: align keeps one per column", [aligns(delCol), cells(delCol), where(delCol)],
  [[null, "right"], [["A", "C"], ["a", "c"], ["d", "f"]], [1, 1, 1]]);
const delLastCol = after(make(ABC, [0, 1, 2]), C.deleteColumn);
eq("table:rows-columns Delete column, the last: the column before it", [aligns(delLastCol), where(delLastCol)], [[null, "center"], [1, 1, 1]]);
eq("table:rows-columns deleting the only column or the only row removes the table",
  [shape(after(make([para("Voor"), tbl([["A"], ["a"]]), para("Na")], [1, 1, 0]), C.deleteColumn)),
   shape(after(make([para("Voor"), tbl([["A", "B"]]), para("Na")], [1, 0, 1]), C.deleteRow))],
  [[["paragraph", "Voor"], ["paragraph", "Na"]], [["paragraph", "Voor"], ["paragraph", "Na"]]]);
const mixed = steps(make(ABC, [0, 0, 0]), C.addColumn(1), C.addColumn(-1), C.deleteColumn, C.addRow(1), C.addColumn(1), C.deleteColumn, C.deleteColumn);
eq("table:rows-columns after any of them: a cell per column in every row, align one per column", [aligns(mixed), cells(mixed), where(mixed)],
  [[null, null, "right"], [["A", "", "C"], ["", "", ""], ["a", "", "c"], ["d", "", "f"]], [1, 2, 0]]);
// a table pasted with rows of different lengths: a column added or deleted fills the short rows first (as a reload
// does), align as long as the longest row
const RAGGED = [tbl([["A", "B", "C"], ["a"]], {align: [null, "right"]})];
const ragged = after(make(RAGGED, [0, 1, 0]), C.addColumn(1)), raggedDel = after(make(RAGGED, [0, 1, 0]), C.deleteColumn);
eq("table:rows-columns a ragged table: short rows filled, align fits the longest",
  [aligns(ragged), cells(ragged), where(ragged), aligns(raggedDel), cells(raggedDel), where(raggedDel)],
  [[null, null, "right", null], [["A", "", "B", "C"], ["a", "", "", ""]], [1, 1, 0], ["right", null], [["B", "C"], ["", ""]], [1, 0, 0]]);

/* ——— the column's alignment ——— */
const leftStart = make(ABC, [0, 2, 0, 1]), left = after(leftStart, C.setColumnAlign("left"));
eq("table:align the cursor's column, the cursor stays", [aligns(left), where(left), left.selection.from === leftStart.selection.from],
  [["left", "center", "right"], [2, 0, 1], true]);
eq("table:align as the book", aligns(after(make(ABC, [0, 0, 2]), C.setColumnAlign(null))), [null, "center", null]);
const sameStart = make(ABC, [0, 0, 1]), same = run(sameStart, C.setColumnAlign("center"));
eq("table:align the column's own alignment again: true, no step to undo", [same[0], same[1] === sameStart], [true, true]);
eq("table:align only as the book, left, centre and right", [C.setColumnAlign("justify")(make(ABC, [0, 0, 0])),
  C.setColumnAlign("center")(make(ABC, [0, 0, 0]))], [false, true]);
eq("table:align current: the cursor's column", [B.current(make(ABC, [0, 1, 1])).align, B.current(make(ABC, [0, 1, 0])).align], ["center", null]);
eq("table:align the cells of an aligned column carry it (data-align)", alignedCells(make(ABC, [0, 0, 0])),
  [[0, 1, "center"], [0, 2, "right"], [1, 1, "center"], [1, 2, "right"], [2, 1, "center"], [2, 2, "right"]]);
eq("table:align the decorations follow an edit", alignedCells(after(make(ABC, [0, 0, 0]), C.setColumnAlign("left"))).filter(c => c[1] === 0),
  [[0, 0, "left"], [1, 0, "left"], [2, 0, "left"]]);

/* ——— the header row ——— */
const headerOff = run(make(ABC, [0, 1, 1, 0]), C.toggleHeader);
eq("table:header off, the cursor stays", [headerOff[0], shape(headerOff[1])[0][1], where(headerOff[1]), B.current(headerOff[1]).header],
  [true, false, [1, 1, 0], false]);
eq("table:header on again", shape(after(headerOff[1], C.toggleHeader))[0][1], true);

/* ——— Backspace in an empty table ——— */
const EMPTY = [para("Voor"), tbl([["", ""], ["", ""]]), para("Na")];
const emptyStart = make(EMPTY, [1, 1, 1]), b1 = run(emptyStart, C.cellBackspace);
eq("table:backspace-empty the first Backspace selects the table", [b1[0], b1[1].selection.node && b1[1].selection.node.type.name,
  b1[1].selection.from, json(b1[1]) === json(emptyStart)], [true, "table", 6, true]);
const b2 = run(b1[1], C.cellBackspace);
eq("table:backspace-empty the second removes it, the cursor at the end of the line before", [b2[0], shape(b2[1]), where(b2[1])],
  [true, [["paragraph", "Voor"], ["paragraph", "Na"]], [0, "paragraph", 4]]);
eq("table:backspace-empty a table with text: Backspace is the text's", [C.cellBackspace(make(ABC, [0, 1, 1, 0])),
  C.cellBackspace(make([tbl([["", "x"]])], [0, 0, 0]))], [false, false]);
const twice = blocks => steps(make(blocks, [blocks.findIndex(b => b.type === "table"), 0, 0]), C.cellBackspace, C.cellBackspace);
const alone = twice([tbl([["", ""]])]), titled = twice([{type: "title", content: [txt("Titel")]}, tbl([[""]])]), leading = twice([tbl([[""]]), para("Na")]);
eq("table:backspace-empty the only block: an empty line in its place; after the title too; first: the line after",
  [shape(alone), where(alone), shape(titled), where(titled), shape(leading), where(leading)],
  [[["paragraph", ""]], [0, "paragraph", 0], [["title", "Titel"], ["paragraph", ""]], [1, "paragraph", 0], [["paragraph", "Na"]], [0, "paragraph", 0]]);
const abcDoc = docOf(ABC), selected = P.EditorState.create({doc: abcDoc, plugins: plugins(), selection: P.NodeSelection.create(abcDoc, 0)});
eq("table:backspace-empty a selected table: Backspace removes it", shape(after(selected, C.cellBackspace)), [["paragraph", ""]]);
eq("table:delete Delete table from a cell, and on a selected table", [shape(after(make(EMPTY, [1, 0, 0]), C.deleteTable)),
  shape(after(b1[1], C.deleteTable))], [[["paragraph", "Voor"], ["paragraph", "Na"]], [["paragraph", "Voor"], ["paragraph", "Na"]]]);

/* ——— one undo per command ——— */
const undo = state => after(state, P.undo), redo = state => after(state, P.redo);
/* [it changed the document, one undo gives it back with the selection, one redo does it again] */
function exact(state, cmd) {
  const done = after(state, cmd), back = undo(done);
  return [json(done) !== json(state), json(back) === json(state) && back.selection.eq(state.selection), json(redo(back)) === json(done)];
}
const undone = [
  ["insert", exact(make([para()], [0, 0]), C.insertTable())],
  ["row above", exact(make(ABC, [0, 1, 1]), C.addRow(-1))], ["row below", exact(make(ABC, [0, 1, 1]), C.addRow(1))],
  ["column left", exact(make(ABC, [0, 1, 1]), C.addColumn(-1))], ["column right", exact(make(ABC, [0, 1, 1]), C.addColumn(1))],
  ["delete row", exact(make(ABC, [0, 1, 1]), C.deleteRow)], ["delete column", exact(make(ABC, [0, 1, 1]), C.deleteColumn)],
  ["header", exact(make(ABC, [0, 1, 1]), C.toggleHeader)], ["align", exact(make(ABC, [0, 1, 1]), C.setColumnAlign("left"))],
  ["delete table", exact(make(ABC, [0, 1, 1]), C.deleteTable)], ["tab adds a row", exact(make(GRID, [0, 1, 1]), C.nextCell(1))],
  ["enter makes a paragraph", exact(make(THREE, [0, 2, 0]), C.cellEnter)], ["backspace removes", exact(b1[1], C.cellBackspace)],
];
eq("undo:table one undo per command", undone.filter(([, r]) => r.some(x => !x)).map(([name, r]) => [name, r]), []);

/* ——— what is on where the cursor is ——— */
eq("current:in a cell", B.current(make(ABC, [0, 2, 1])), {header: true, align: "center", row: 2, col: 1, rows: 3, cols: 3});
eq("current:inTable", [B.inTable(make(ABC, [0, 2, 1])), B.inTable(selected), B.current(selected)], [true, false, null]);

/* ——— the rows for the panel and the palette, the keys ——— */
const row = id => B.KEYS.find(k => k.id === id);
eq("keys:rows", [B.KEYS.map(k => k.label), B.KEYS.filter(k => k.key).map(k => [k.label, k.key]), [...new Set(B.KEYS.map(k => k.group))],
  new Set(B.KEYS.map(k => k.id)).size === B.KEYS.length, B.KEYS.every(k => typeof k.run === "function" && typeof k.cmd === "function"),
  B.KEYS.filter(k => k.short).map(k => k.short)],
  [["Row above", "Row below", "Column left", "Column right", "Delete row", "Delete column", "Header row", "Align column as the book",
    "Align column left", "Centre column", "Align column right", "Delete table"],
   [["Row above", "Ctrl+Alt+↑"], ["Row below", "Ctrl+Alt+↓"], ["Column left", "Ctrl+Alt+←"], ["Column right", "Ctrl+Alt+→"]], ["Table"], true, true,
   ["As the book", "Left", "Centre", "Right"]]);
eq("keys:every row's command applies in a table and nowhere else", [B.KEYS.filter(k => !k.cmd(make(ABC, [0, 1, 1]))).map(k => k.id),
  B.KEYS.filter(k => k.cmd(plain)).map(k => k.id)], [[], []]);
const km = B.keymap({locked: false});
const press = (name, st, keys = km) => { let next = st; const ok = keys[name](st, tr => { next = next.apply(tr); }, null); return [ok, next]; };
const ARROWS = ["Mod-Alt-ArrowUp", "Mod-Alt-ArrowDown", "Mod-Alt-ArrowLeft", "Mod-Alt-ArrowRight"];
// the arrows, and the word-deleting keys of ProseMirror's base keymap (Backspace and Delete are book-text's chains)
eq("keys:the bindings", Object.keys(km).sort(), [...ARROWS, "Mod-Backspace", "Mod-Delete", "Shift-Backspace"].sort());
eq("keys:Ctrl+Alt+arrows add a row above and below, a column left and right", ARROWS.map(k => { const [ok, st] = press(k, make(ABC, [0, 1, 1]));
  return [ok, cells(st).length, cells(st)[0].length, where(st)]; }),
  [[true, 4, 3, [1, 1, 0]], [true, 4, 3, [2, 1, 0]], [true, 3, 4, [1, 1, 0]], [true, 3, 4, [1, 2, 0]]]);
eq("keys:outside a table the keys pass", ARROWS.map(k => press(k, plain)[0]), [false, false, false, false]);
const lockedKeys = B.keymap({locked: true}), lockedStart = make(ABC, [0, 1, 1]);
eq("keys:while the piece is locked: the key is kept, nothing changes", ARROWS.map(k => { const [ok, st] = press(k, lockedStart, lockedKeys);
  return [ok, st === lockedStart]; }), ARROWS.map(() => [true, true]));
const fakeView = state => ({state, dispatch(tr) { this.state = this.state.apply(tr); }});
const T1 = {locked: false, view: fakeView(make(ABC, [0, 1, 1]))}, T2 = {locked: true, view: fakeView(make(ABC, [0, 1, 1]))};
const note = fakeView(plain), T3 = {locked: false, view: fakeView(make(ABC, [0, 1, 1])), activeView: () => note};
row("table-row-below").run(T1); row("table-row-below").run(T2); row("table-row-below").run(T3);
eq("keys:a row's run: on the view written in, nothing while locked", [cells(T1.view.state).length, cells(T2.view.state).length,
  cells(T3.view.state).length, note.state === plain], [4, 3, 3, true]);

/* ——— the Table button: its menu, and the table it shows on ——— */
const menuOf = state => B.menu(state, cmd => cmd);
const labels = items => items.map(i => (i === "-" ? "-" : i.items ? [i.label, labels(i.items)] : (i.checked ? "✓ " : "") + i.label));
const m = menuOf(make(ABC, [0, 1, 1]));
eq("table:menu the commands", labels(m), ["Row above", "Row below", "Column left", "Column right", "-", "Delete row", "Delete column", "-",
  "✓ Header row", ["Align column", ["As the book", "Left", "✓ Centre", "Right"]], "-", "Delete table"]);
eq("table:menu keys, the danger, the header and alignment as they are", [m.slice(0, 4).map(i => i.kbd), m[m.length - 1].danger,
  labels(menuOf(headerOff[1]))[8], labels(menuOf(make(ABC, [0, 1, 0])))[9][1][0]],
  [["Ctrl+Alt+↑", "Ctrl+Alt+↓", "Ctrl+Alt+←", "Ctrl+Alt+→"], true, "Header row", "✓ As the book"]);
eq("table:menu an item does its command; nothing outside a table", [cells(after(make(ABC, [0, 1, 1]), m[1].act)).length,
  aligns(after(make(ABC, [0, 1, 1]), m[9].items[3].act)), menuOf(plain)], [4, [null, "right", "right"], []]);
eq("table:button shows on the table that holds the cursor", [lit(make([para("Voor"), ...ABC], [1, 1, 1])), lit(make([para("Voor"), ...ABC], [0])),
  lit(selected)], [[6], [], []]);
eq("table:view the node views", [typeof B.TableView, Object.keys(B.nodeViews({})), typeof B.nodeViews({}).table], ["function", ["table"], "function"]);

/* ——— a cell holds one line: deleting across cells clears their text, the rows and columns stay ——— */
const NJ = [para("Voor"), tbl([["Naam", "Jaar"], ["Een", "1990"]]), para("Na")];
/* the text from cell (r1, c1) at o1 to cell (r2, c2) at o2 of the table that is block 1 selected */
function span(blocks, [r1, c1, o1], [r2, c2, o2]) {
  const st = make(blocks, [1, r1, c1, o1]);
  return st.apply(st.tr.setSelection(P.TextSelection.create(st.doc, cellPos(st.doc, 1, r1, c1, o1), cellPos(st.doc, 1, r2, c2, o2))));
}
const twoRows = span(NJ, [0, 0, 2], [1, 1, 2]), oneRow = span(NJ, [0, 0, 2], [0, 1, 2]), inOne = span(NJ, [0, 0, 1], [0, 0, 3]);
const del2 = run(twoRows, C.cellDelete), bs2 = run(twoRows, C.cellBackspace), del1 = run(oneRow, C.cellDelete);
eq("table:across Delete and Backspace over cells of two rows clear their text, the cursor where it began",
  [del2[0], cells(del2[1]), where(del2[1]), bs2[0], json(bs2[1]) === json(del2[1])], [true, [["Na", ""], ["", "90"]], [0, 0, 2], true, true]);
eq("table:across within one row", [cells(del1[1]), where(del1[1])], [[["Na", "ar"], ["Een", "1990"]], [0, 0, 2]]);
eq("table:across in one cell: the text's own keys", [C.cellDelete(inOne), C.cellBackspace(inOne), C.cellDelete(plain)], [false, false, false]);
/* text typed as the editor does: the plugins' handleTextInput first */
function typeOver(state, text) {
  const view = {state, composing: false, dispatch(tr) { this.state = this.state.apply(tr); }}, {from, to} = state.selection;
  return [state.plugins.some(p => p.props.handleTextInput && p.props.handleTextInput(view, from, to, text)), view.state];
}
const typed2 = typeOver(twoRows, "X");
eq("table:across text typed over cells goes into the first, the others cleared", [typed2[0], cells(typed2[1]), where(typed2[1])],
  [true, [["NaX", ""], ["", "90"]], [0, 0, 3]]);
eq("table:across typed in one cell: the text's own", typeOver(inOne, "X")[0], false);
const pasteView = fakeView(twoRows), line = new P.Slice(P.Fragment.from(S.nodes.paragraph.create(null, S.text("P"))), 1, 1);
const pastedOver = twoRows.plugins.some(p => p.props.handlePaste && p.props.handlePaste(pasteView, null, line));
eq("table:across pasted over cells: into the first, the others cleared", [pastedOver, cells(pasteView.state), where(pasteView.state)],
  [true, [["NaP", ""], ["", "90"]], [0, 0, 3]]);
// a cut copies the selection first (ProseMirror), then the cells are cleared (the cut's own deletion is refused); a drag
// of a selection across cells moves nothing
const cutTr = twoRows.applyTransaction(twoRows.tr.deleteSelection().setMeta("uiEvent", "cut"));
const dropTr = twoRows.applyTransaction(twoRows.tr.deleteSelection().setMeta("uiEvent", "drop"));
const cutOne = inOne.applyTransaction(inOne.tr.deleteSelection().setMeta("uiEvent", "cut"));
eq("table:across a cut or a drop doesn't delete across cells; a cut in one cell does", [cutTr.state === twoRows, dropTr.state === twoRows,
  cells(cutOne.state)[0]], [true, true, ["Nm", "Jaar"]]);
eq("table:across the word keys clear across cells and pass elsewhere", [cells(press("Mod-Backspace", twoRows)[1]), press("Mod-Delete", inOne)[0],
  press("Shift-Backspace", plain)[0]], [[["Na", ""], ["", "90"]], false, false]);
eq("undo:across one undo", [exact(twoRows, C.cellDelete), exact(twoRows, C.cellBackspace)], [[true, true, true], [true, true, true]]);

/* ——— a selection across a table's edge (Shift+Down from the line above, a drag out of a cell): the selected text of each
   cell cleared, the text outside the table deleted, a cell never joined with a paragraph ——— */
const EDGE = [para("Voor"), tbl([["a1", "b1", "c1"], ["a2", "b2", "c2"]]), para("Na")];
/* `blocks` with the selection from `a` to `b`: [i, offset] in text block i, [i, r, c, offset] in a cell of the table that is block i */
function spanOf(blocks, a, b) {
  const st = make(blocks, a), pos = p => (p.length >= 3 ? cellPos(st.doc, ...p) : textPos(st.doc, ...p));
  return st.apply(st.tr.setSelection(P.TextSelection.create(st.doc, pos(a), pos(b))));
}
const intoTable = spanOf(EDGE, [0, 2], [1, 0, 1, 0]), intoB1 = spanOf(EDGE, [0, 2], [1, 0, 1, 1]), outOfTable = spanOf(EDGE, [1, 1, 1, 1], [2, 1]);
const bsInto = run(intoTable, C.cellBackspace), delInto = run(intoB1, C.cellDelete), bsOut = run(outOfTable, C.cellBackspace);
eq("table:edge from the line above into the table: the line's end deleted, the cells' text cleared, the columns stay",
  [bsInto[0], shape(bsInto[1]), where(bsInto[1]), delInto[0], shape(delInto[1]), where(delInto[1])],
  [true, [["paragraph", "Vo"], ["table", true, [null, null, null], [["", "b1", "c1"], ["a2", "b2", "c2"]]], ["paragraph", "Na"]], [0, "paragraph", 2],
   true, [["paragraph", "Vo"], ["table", true, [null, null, null], [["", "1", "c1"], ["a2", "b2", "c2"]]], ["paragraph", "Na"]], [0, "paragraph", 2]]);
eq("table:edge from a cell out of the table: the cells' text cleared, the line's start deleted, the cursor in the cell",
  [bsOut[0], shape(bsOut[1]), where(bsOut[1])],
  [true, [["paragraph", "Voor"], ["table", true, [null, null, null], [["a1", "b1", "c1"], ["a2", "b", ""]]], ["paragraph", "a"]], [1, 1, 1]]);
const typedInto = typeOver(intoB1, "X"), typedOut = typeOver(outOfTable, "X");
eq("table:edge text typed over the edge goes where the selection starts", [typedInto[0], shape(typedInto[1]), where(typedInto[1]),
  typedOut[0], cells(typedOut[1]), shape(typedOut[1])[2], where(typedOut[1])],
  [true, [["paragraph", "VoX"], ["table", true, [null, null, null], [["", "1", "c1"], ["a2", "b2", "c2"]]], ["paragraph", "Na"]], [0, "paragraph", 3],
   true, [["a1", "b1", "c1"], ["a2", "bX", ""]], ["paragraph", "a"], [1, 1, 2]]);
const pasteOut = fakeView(outOfTable), pastedOut = outOfTable.plugins.some(p => p.props.handlePaste && p.props.handlePaste(pasteOut, null, line));
const pasteInto = fakeView(intoB1), pastedInto = intoB1.plugins.some(p => p.props.handlePaste && p.props.handlePaste(pasteInto, null, line));
eq("table:edge pasted over the edge: where the selection starts", [pastedOut, cells(pasteOut.state), where(pasteOut.state), pastedInto,
  shape(pasteInto.state)[0], cells(pasteInto.state)[0], where(pasteInto.state)],
  [true, [["a1", "b1", "c1"], ["a2", "bP", ""]], [1, 1, 2], true, ["paragraph", "VoP"], ["", "1", "c1"], [0, "paragraph", 3]]);
const cutOut = outOfTable.applyTransaction(outOfTable.tr.deleteSelection().setMeta("uiEvent", "cut"));
const dropInto = intoB1.applyTransaction(intoB1.tr.deleteSelection().setMeta("uiEvent", "drop"));
eq("table:edge a cut or a drop doesn't delete over the edge; the word keys clear it", [cutOut.state === outOfTable, dropInto.state === intoB1,
  cells(press("Mod-Backspace", outOfTable)[1]), shape(press("Shift-Backspace", intoB1)[1])[0]],
  [true, true, [["a1", "b1", "c1"], ["a2", "b", ""]], ["paragraph", "Vo"]]);
// from a cell of one table, over a line, into a cell of the next: both tables keep their rows and columns, the line goes
const TWO = [tbl([["a", "b"]]), para("Tussen"), tbl([["c", "d"]]), para("Na")];
const acrossTwo = (st => run(st, C.cellDelete))(spanOf(TWO, [0, 0, 0, 1], [2, 0, 1, 0]));
eq("table:edge from one table into the next: the line between deleted, both tables kept", [acrossTwo[0], shape(acrossTwo[1]), where(acrossTwo[1])],
  [true, [["table", true, [null, null], [["a", ""]]], ["table", true, [null, null], [["", "d"]]], ["paragraph", "Na"]], [0, 0, 1]]);
// a whole line selected: above the table it stays empty, the cursor in it; after the table it goes, the cursor in the cell
const wholeAbove = run(spanOf(EDGE, [0, 0], [1, 0, 0, 1]), C.cellDelete), wholeAfter = run(spanOf(EDGE, [1, 1, 2, 0], [2]), C.cellDelete);
eq("table:edge a whole line selected: above the table an empty line stays, after it the line goes",
  [shape(wholeAbove[1]).map(b => b[0] + ":" + (b[0] === "table" ? "" : b[1])), where(wholeAbove[1]), shape(wholeAfter[1]).map(b => b[0]), cells(wholeAfter[1]), where(wholeAfter[1])],
  [["paragraph:", "table:", "paragraph:Na"], [0, "paragraph", 0], ["paragraph", "table"], [["a1", "b1", "c1"], ["a2", "b2", ""]], [1, 2, 0]]);
// a selection that holds a whole table, from the text before it to the text after it, is the text's own (the table goes)
const overTable = spanOf(EDGE, [0, 2], [2, 1]);
eq("table:edge a whole table selected from outside: the text's own keys", [C.cellDelete(overTable), C.cellBackspace(overTable), typeOver(overTable, "X")[0]],
  [false, false, false]);
eq("undo:edge one undo", [exact(intoTable, C.cellBackspace), exact(outOfTable, C.cellDelete), exact(spanOf(TWO, [0, 0, 0, 1], [2, 0, 1, 0]), C.cellDelete)],
  [[true, true, true], [true, true, true], [true, true, true]]);

/* ——— every table stays rectangular, with one alignment per column ——— */
const njStart = make(NJ, [1, 1, 0]);
const cellGone = (() => { const from = cellPos(njStart.doc, 1, 1, 1, 0) - 1; return njStart.apply(njStart.tr.delete(from, from + 6)); })();
const badAlign = njStart.apply(njStart.tr.setNodeMarkup(posOf(njStart.doc, 1), null, {header: true, align: ["right"]}));
const raggedIn = njStart.apply(njStart.tr.insert(njStart.doc.content.size, P.Node.fromJSON(S, tbl([["a", "b", "c"], ["d"]], {align: ["left"]}))));
const collapsed = twoRows.apply(twoRows.tr.deleteSelection());
eq("table:rectangular a row that loses a cell gets an empty one; align fitted; a ragged table put in filled",
  [cells(cellGone), aligns(badAlign), shape(raggedIn)[3]],
  [[["Naam", "Jaar"], ["Een", ""]], ["right", null], ["table", true, ["left", null, null], [["a", "b", "c"], ["d", "", ""]]]]);
eq("table:rectangular whatever is left of a table: rows as long as its longest, align as long", (t => [t[2].length,
  t[3].every(r => r.length === t[2].length)])(shape(collapsed).find(b => b[0] === "table")), [1, true]);
eq("undo:rectangular the filling goes with the edit", json(undo(cellGone)) === json(njStart), true);

/* ——— Enter on a selected note or math in a cell is theirs; Delete table after the title ——— */
const noted = docOf([{type: "table", attrs: {header: true, align: [null]}, content: [{type: "table_row", content: [cell("Naam")]},
  {type: "table_row", content: [{type: "table_cell", content: [txt("Een"), {type: "note", content: [txt("noot")]}, {type: "math", attrs: {tex: "x"}}]}]}]}]);
const notePos = cellPos(noted, 0, 1, 0, 3), noteSel = P.EditorState.create({doc: noted, selection: P.NodeSelection.create(noted, notePos)});
const mathSel = P.EditorState.create({doc: noted, selection: P.NodeSelection.create(noted, notePos + noted.nodeAt(notePos).nodeSize)});
eq("table:enter on a selected note or math: not the table's", [noteSel.selection.node.type.name, C.cellEnter(noteSel), mathSel.selection.node.type.name,
  C.cellEnter(mathSel)], ["note", false, "math", false]);
const afterTitle = after(make([{type: "title", content: [txt("Titel")]}, tbl([["a"]]), para("Na")], [1, 0, 0]), C.deleteTable);
const afterText = after(make([para("Voor"), tbl([["a"]]), para("Na")], [1, 0, 0]), C.deleteTable);
eq("table:delete with only the title before it: the cursor at the start of the text after it; else at the end of the text before",
  [shape(afterTitle), where(afterTitle), where(afterText)], [[["title", "Titel"], ["paragraph", "Na"]], [1, "paragraph", 0], [0, "paragraph", 4]]);

/* ——— after an edit the document is what a reload gives (the runner checks parse(serialize(doc)) == doc) ——— */
const reload = {};
const scenario = (name, at, edit) => {
  const doc = IN.reload[name];
  if (!doc) { eq(`table:reload ${name}`, "missing", "given"); return null; }
  const d = P.Node.fromJSON(S, doc);
  const st = edit(P.EditorState.create({doc: d, plugins: plugins(), selection: P.TextSelection.create(d, at(d))}));
  reload[name] = st.doc.toJSON();
  return st;
};
const inserted = scenario("insert", d => textPos(d, 0), st => steps(st, C.insertTable(), "Naam", C.nextCell(1), "Jaar", C.nextCell(1), "Plaats",
  C.nextCell(1), "Een"));
eq("table:reload insert", inserted && shape(inserted),
  [["paragraph", "Tekst"], ["table", true, [null, null, null], [["Naam", "Jaar", "Plaats"], ["Een", "", ""], ["", "", ""]]]]);
const insertedEmpty = scenario("insert-empty", d => textPos(d, 0), st => after(st, C.insertTable()));
eq("table:reload insert-empty", insertedEmpty && shape(insertedEmpty),
  [["paragraph", "Tekst"], ["table", true, [null, null, null], [["", "", ""], ["", "", ""], ["", "", ""]]]]);
const edited = scenario("edited", d => cellPos(d, 0, 0, 0), st => steps(st, C.addColumn(1), "Plaats", C.setColumnAlign("center"), C.nextCell(1),
  C.nextCell(1), C.addRow(1), "Anderhalf", C.nextCell(1), "Utrecht", C.nextCell(1), "1995", C.cellEnter, C.deleteRow, C.nextCell(1), "Drie"));
eq("table:reload edited", edited && shape(edited), [["table", true, [null, "center", "right"],
  [["Naam", "Plaats", "Jaar"], ["Een", "", "1990"], ["Anderhalf", "Utrecht", "1995"], ["Drie", "", ""]]]]);
const headerless = scenario("header-off", d => cellPos(d, 0, 1, 0), st => after(st, C.toggleHeader));
eq("table:reload header-off", headerless && shape(headerless)[0].slice(0, 2), ["table", false]);
const piped = scenario("pipes", d => cellPos(d, 0, 1, 0), st => typeIn(st, " | twee"));
eq("table:reload pipes", piped && cells(piped)[1], ["Een | twee", "1990"]);
const deleted = scenario("deleted", d => cellPos(d, 1, 1, 1), st => after(st, C.deleteTable));
eq("table:reload deleted", deleted && shape(deleted), [["paragraph", "Voor"], ["paragraph", "Na"]]);
const outOf = scenario("last-row-out", d => cellPos(d, 0, 2, 1), st => steps(st, C.cellEnter, "Na de tabel"));
eq("table:reload last-row-out", outOf && shape(outOf).slice(1), [["paragraph", "Na de tabel"]]);
/* the text of the first table from cell (r1, c1) at o1 to cell (r2, c2) at o2 selected */
const across0 = (st, [r1, c1, o1], [r2, c2, o2]) => st.apply(st.tr.setSelection(P.TextSelection.create(st.doc, cellPos(st.doc, 0, r1, c1, o1),
  cellPos(st.doc, 0, r2, c2, o2))));
const cleared = scenario("cells-cleared", d => cellPos(d, 0, 0, 0), st => after(across0(st, [0, 0, 2], [2, 1, 2]), C.cellDelete));
eq("table:reload cells-cleared", cleared && cells(cleared), [["Na", ""], ["", ""], ["", "01"]]);
const typedCells = scenario("cells-typed", d => cellPos(d, 0, 0, 0), st => typeOver(across0(st, [1, 0, 1], [1, 1, 2]), "X")[1]);
eq("table:reload cells-typed", typedCells && cells(typedCells), [["Naam", "Jaar"], ["EX", "90"], ["Twee", "2001"]]);
const filledIn = scenario("rectangular", d => cellPos(d, 0, 0, 0), st => { const from = cellPos(st.doc, 0, 2, 1, 0) - 1;
  return st.apply(st.tr.delete(from, from + st.doc.child(0).child(2).child(1).nodeSize)); });
eq("table:reload rectangular", filledIn && cells(filledIn), [["Naam", "Jaar"], ["Een", "1990"], ["Twee", ""]]);
/* the selection in the document "Voor", the table, "Na" from `a` to `b` ([i, offset] in a line, [i, r, c, offset] in a cell) */
const edge = (st, a, b) => { const pos = p => (p.length >= 3 ? cellPos(st.doc, ...p) : textPos(st.doc, ...p));
  return st.apply(st.tr.setSelection(P.TextSelection.create(st.doc, pos(a), pos(b)))); };
const edgeAbove = scenario("edge-above", d => textPos(d, 0), st => after(edge(st, [0, 2], [1, 0, 1, 2]), C.cellBackspace));
eq("table:reload edge-above", edgeAbove && shape(edgeAbove).map(b => (b[0] === "table" ? b[3] : b[1])),
  ["Vo", [["", "ar"], ["Een", "1990"], ["Twee", "2001"]], "Na"]);
const edgeBelow = scenario("edge-below", d => textPos(d, 0), st => after(edge(st, [1, 1, 1, 2], [2, 1]), C.cellDelete));
eq("table:reload edge-below", edgeBelow && shape(edgeBelow).map(b => (b[0] === "table" ? b[3] : b[1])),
  ["Voor", [["Naam", "Jaar"], ["Een", "19"], ["", ""]], "a"]);
const edgeTyped = scenario("edge-typed", d => textPos(d, 0), st => typeOver(edge(st, [1, 2, 0, 2], [2, 1]), "X")[1]);
eq("table:reload edge-typed", edgeTyped && shape(edgeTyped).map(b => (b[0] === "table" ? b[3] : b[1])),
  ["Voor", [["Naam", "Jaar"], ["Een", "1990"], ["TwX", ""]], "a"]);

/* ——— pinned, by the spec's ruling: a header row left empty above rows with text reads back as no header, the empty row
   gone (the runner checks what a reload gives) ——— */
const pinned = {};
if (IN.pinned) {
  const d = P.Node.fromJSON(S, IN.pinned["row-above-header"]);
  const st = after(P.EditorState.create({doc: d, plugins: plugins(), selection: P.TextSelection.create(d, cellPos(d, 0, 0, 0))}), C.addRow(-1));
  eq("table:pinned a row above the header, left empty: the new header", [shape(st)[0][1], cells(st)[0], cells(st).length], [true, ["", ""], 4]);
  pinned["row-above-header"] = st.doc.toJSON();
}
// and a table with no text at all keeps its rows: / Table, Header row off, nothing typed (the runner: it reads back with
// the header on and the same rows)
if (IN.pinned && IN.pinned["empty-header-off"]) {
  const d = P.Node.fromJSON(S, IN.pinned["empty-header-off"]);
  const st = steps(P.EditorState.create({doc: d, plugins: plugins(), selection: P.TextSelection.create(d, textPos(d, 0))}), C.insertTable(), C.toggleHeader);
  eq("table:pinned an empty table, Header row off", [shape(st)[1][1], cells(st)], [false, [["", "", ""], ["", "", ""], ["", "", ""]]]);
  pinned["empty-header-off"] = st.doc.toJSON();
}

/* ——— a table pasted from Word, Docs or the web: each cell one line before the schema reads it (flatCell; pasteCells runs
   it on what the browser's DOMParser reads, which node has not: a small DOM of what flatCell uses stands in) ——— */
class FakeNode {
  constructor(type, name, value) { Object.assign(this, {nodeType: type, nodeName: name, parentNode: null, childNodes: [], ownerDocument: fakeDoc});
    if (type === 3) this.data = value; else this.attrs = value || {}; }
  get textContent() { return this.nodeType === 3 ? this.data : this.childNodes.map(c => c.textContent).join(""); }
  getAttribute(name) { return this.nodeType === 1 && name in this.attrs ? this.attrs[name] : null; }
  remove() { if (this.parentNode) { const s = this.parentNode.childNodes; s.splice(s.indexOf(this), 1); this.parentNode = null; } }
  append(...nodes) { for (const n of nodes) { n.remove(); n.parentNode = this; this.childNodes.push(n); } }
  replaceChildren(...nodes) { for (const c of [...this.childNodes]) c.remove(); this.append(...nodes); }
  cloneNode() { return this.nodeType === 3 ? fakeDoc.createTextNode(this.data) : fakeDoc.createElement(this.nodeName, this.attrs); }
}
const fakeDoc = {createTextNode: s => new FakeNode(3, "#text", s), createElement: (name, attrs) => new FakeNode(1, name.toUpperCase(), {...attrs})};
/* an element: h("p", {class: "x"}, "text", h(…), …) */
const h = (name, attrs, ...kids) => { const e = fakeDoc.createElement(name, attrs); e.append(...kids.map(k => (typeof k === "string" ? fakeDoc.createTextNode(k) : k))); return e; };
const htmlOf = n => (n.nodeType === 3 ? n.data : `<${n.nodeName.toLowerCase()}${Object.entries(n.attrs).map(([k, v]) => ` ${k}="${v}"`).join("")}>` +
  n.childNodes.map(htmlOf).join("") + `</${n.nodeName.toLowerCase()}>`);
/* the cell flattened, as HTML */
const flat = cell => { if (typeof B.flatCell !== "function") return "no flatCell"; B.flatCell(cell); return htmlOf(cell); };
eq("table:paste-cells Word: a paragraph in a cell, its runs kept", flat(h("td", {width: "301"}, "\n", h("p", {class: "MsoNormal"},
  h("span", {lang: "NL"}, "Naam", h("o:p", {})), "\n"), "\n")),
  '<td width="301"><span lang="NL">Naam<o:p></o:p></span>\n</td>');
eq("table:paste-cells Docs: paragraphs joined by a space, their formatting kept", flat(h("td", {}, h("p", {dir: "ltr"}, h("span", {style: "font-weight:700"}, "Utrecht")),
  h("p", {dir: "ltr"}, h("span", {style: "font-style:italic"}, "en Gent")))),
  '<td><span style="font-weight:700">Utrecht</span> <span style="font-style:italic">en Gent</span></td>');
eq("table:paste-cells a line break is a space", [flat(h("td", {}, "Utrecht", h("br", {}), "en Gent")), flat(h("td", {}, h("p", {}, "a", h("br", {}), "b")))],
  ["<td>Utrecht en Gent</td>", "<td>a b</td>"]);
eq("table:paste-cells a list: its items' text joined by a space", flat(h("td", {}, h("ul", {}, h("li", {}, "een"), h("li", {}, h("b", {}, "twee"))))),
  "<td>een <b>twee</b></td>");
eq("table:paste-cells a table in a cell: its cells' text", flat(h("td", {}, "Buiten", h("table", {}, h("tbody", {}, h("tr", {}, h("td", {}, "a"), h("td", {}, h("p", {}, "b"))))))),
  "<td>Buiten a b</td>");
eq("table:paste-cells formatting around paragraphs or a line break: on each piece", [flat(h("th", {}, h("em", {}, h("p", {}, "a"), h("p", {}, "b")))),
  flat(h("td", {}, h("u", {}, "a", h("br", {}), h("s", {}, "b"))))], ["<th><em>a</em> <em>b</em></th>", "<td><u>a</u> <u><s>b</s></u></td>"]);
eq("table:paste-cells empty lines left out: white space, a no-break space, an image", flat(h("td", {}, "\n  ", h("p", {}, "a"), "\n  ", h("p", {}, " "),
  h("div", {}, h("img", {src: "x.png"})), h("h2", {}, "b"), "\n")), "<td>a b</td>");
eq("table:paste-cells one line as it was; the editor's own note keeps its line break", [flat(h("td", {}, "Een ", h("em", {}, "twee"))),
  flat(h("td", {}, "Een", h("sup", {class: "bk-note"}, "a", h("br", {}), "b"), h("span", {class: "bk-math", "data-tex": "x"}, "x")))],
  ["<td>Een <em>twee</em></td>", '<td>Een<sup class="bk-note">a<br></br>b</sup><span class="bk-math" data-tex="x">x</span></td>']);
eq("table:paste-cells without the browser's DOMParser the HTML stays as it is", typeof B.pasteCells === "function" ? B.pasteCells("<td><p>a</p></td>") : "no pasteCells",
  "<td><p>a</p></td>");

/* ——— a cut across cells: ProseMirror copies the selection, then the cells are cleared; nothing while the piece is locked
   (the view isn't editable) ——— */
const cutHandler = twoRows.plugins.map(p => p.props.handleDOMEvents && p.props.handleDOMEvents.cut).find(Boolean);
const cutView = editable => ({state: twoRows, editable, dispatched: 0, dispatch(tr) { this.dispatched++; this.state = this.state.apply(tr); }});
const cutOpen = cutView(true), cutLocked = cutView(false), cutReturned = [cutHandler(cutOpen), cutHandler(cutLocked)];

queueMicrotask(() => {          // after the cut's own microtask
  eq("table:cut clears the cells after the copy; nothing while locked", [cutReturned, cells(cutOpen.state), cutLocked.dispatched, cutLocked.state === twoRows],
    [[false, false], [["Na", ""], ["", "90"]], 0, true]);
  console.log(JSON.stringify({failures, checked, reload, pinned}));
});
