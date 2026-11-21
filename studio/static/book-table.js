"use strict";
/* Tables in the writing window (book-text.js uses it): / Table; rows and columns added and deleted, the header row, a
   column's alignment, the table deleted; Tab, Shift+Tab, Enter and Backspace in a cell; a selection across cells or the
   table's edge deleted, typed or pasted over; a table pasted from outside, each cell made one line; what is on where
   the cursor is (the format panel's Table row); KEYS, one row per command for the panel and the palette, and the keys
   Ctrl+Alt+arrows; the decorations that align a column's cells and mark the table the cursor is in; and the node view: the table in a
   wrapper that scrolls sideways, with the quiet Table button that opens the commands as a menu. There is no
   prosemirror-tables: each command changes the table's rows, cells and attributes in one transaction (one undo) and puts
   the cursor in the cell it means. A classic script after vendor/prosemirror.js and book-schema.js (and menu.js, for the
   button); sets window.BookTable. Only TableView and pasteCells touch the DOM (flatCell only the cell it is given), so
   tests/js/book_table.js runs the rest in node. Spec:
   docs/superpowers/specs/2026-11-13-book-editor-power-design.md ("Tables in detail", "Tables in the writing window"). */
(function (root) {
  const S = root.BookSchema, N = S.nodes;
  const {Plugin, PluginKey, Selection, TextSelection, NodeSelection, Decoration, DecorationSet} = root.PM;
  const COLUMN_ALIGNS = [null, "left", "center", "right"];       // as the book, then manuscript.COLUMN_ALIGNS

  /* ——— where the selection is ——— */
  /* The table the whole selection is in, and the cursor's cell: {table, pos, row, col}; null outside a table, for a
     selection that leaves it, and for the table itself selected. */
  function locate(state) {
    const {$from, $to} = state.selection;
    for (let d = $from.depth; d > 0; d--) {
      if ($from.node(d).type !== N.table) continue;
      if ($from.depth < d + 1 || $to.depth < d || $to.before(d) !== $from.before(d)) return null;
      return {table: $from.node(d), pos: $from.before(d), row: $from.index(d), col: $from.index(d + 1)};
    }
    return null;
  }
  const inTable = state => !!locate(state);
  /* the table Delete table and Backspace remove: the one the cursor is in, or the table selected */
  function tableAt(state) {
    const sel = state.selection;
    if (sel instanceof NodeSelection && sel.node.type === N.table) return {table: sel.node, pos: sel.from};
    return locate(state);
  }
  /* a table's columns: its longest row (a pasted table may have short ones) */
  const width = table => { let n = 1; table.forEach(r => { n = Math.max(n, r.childCount); }); return n; };
  /* `align` with one alignment per column: cut, or filled with "as the book" */
  const fit = (align, n) => Array.from({length: n}, (_, k) => (COLUMN_ALIGNS.includes((align || [])[k]) ? align[k] : null));
  const emptyRow = n => N.table_row.create(null, Array.from({length: n}, () => N.table_cell.create()));
  const isEmpty = table => { let empty = true; table.forEach(r => r.forEach(c => { if (c.content.size) empty = false; })); return empty; };

  /* positions in the table at `pos`: before row r (after the last row when r is the number of rows), and before cell c of
     row r (the row's end when c is past its cells) */
  function rowStart(table, pos, r) { let p = pos + 1; for (let k = 0; k < r; k++) p += table.child(k).nodeSize; return p; }
  function cellStart(table, pos, r, c) {
    const row = table.child(r);
    let p = rowStart(table, pos, r) + 1;
    for (let k = 0; k < Math.min(c, row.childCount); k++) p += row.child(k).nodeSize;
    return p;
  }
  /* the cursor in cell (r, c) of the table at `pos` in tr.doc (the nearest there is): at the end of its text, or its start */
  function into(tr, pos, r, c, atEnd = true) {
    const table = tr.doc.nodeAt(pos), rr = Math.max(0, Math.min(r, table.childCount - 1)), row = table.child(rr);
    const cc = Math.max(0, Math.min(c, row.childCount - 1)), p = cellStart(table, pos, rr, cc) + 1;
    return tr.setSelection(TextSelection.create(tr.doc, atEnd ? p + row.child(cc).content.size : p));
  }
  /* the table at `pos` in tr.doc with every row as long as the longest, as a reload makes it (short rows filled) */
  function filled(tr, pos) {
    const table = tr.doc.nodeAt(pos), n = width(table);
    for (let r = table.childCount - 1; r >= 0; r--) {
      const row = table.child(r);
      if (row.childCount < n) tr.insert(rowStart(table, pos, r) + row.nodeSize - 1, emptyRow(n - row.childCount).content);
    }
    return tr.doc.nodeAt(pos);
  }

  /* ——— the commands: (state, dispatch) → whether they apply; false outside a table ——— */
  /* / Table: `cols` columns, a header row and `rows` rows, the cursor in the first cell. It goes where a block goes
     (book-text.js's insertBlock): in place of an empty line, before or after a line at its edges, between the halves of a
     line, or after the block the cursor is in; never in a poem piece (its table lines would be lines) or a note. */
  function insertTable(cols = 3, rows = 2) {
    return (state, dispatch) => {
      if (state.doc.type !== N.doc || state.doc.attrs.form === "poem") return false;
      if (!dispatch) return true;
      const table = N.table.create({header: true, align: Array(cols).fill(null)}, Array.from({length: rows + 1}, () => emptyRow(cols)));
      const {$from} = state.selection, tr = state.tr;
      let pos;
      if ($from.depth === 1 && $from.parent.type === N.paragraph) {
        const p = $from.parent;
        if (!p.content.size) { pos = $from.before(1); tr.replaceWith(pos, pos + p.nodeSize, table); }
        else if ($from.parentOffset === 0) { pos = $from.before(1); tr.insert(pos, table); }
        else if ($from.parentOffset === p.content.size) { pos = $from.after(1); tr.insert(pos, table); }
        else { tr.split($from.pos); pos = $from.pos + 1; tr.insert(pos, table); }
      } else if ($from.depth >= 1) { pos = $from.after(1); tr.insert(pos, table); }
      else {                                                   // a block selected, or the gap cursor: there; never before the title
        pos = $from.pos + ($from.nodeAfter && $from.nodeAfter.type === N.title ? $from.nodeAfter.nodeSize : 0);
        tr.insert(pos, table);
      }
      dispatch(into(tr, pos, 0, 0, false).scrollIntoView());
      return true;
    };
  }
  /* a row above (-1) or below (1) the cursor's, the cursor in it, in the same column. A row added above the header is the
     header; left empty above rows with text it reads back as no header and is gone (spec ruling, "Tables in detail"). */
  function addRow(dir) {
    return (state, dispatch) => {
      const at = locate(state);
      if (!at) return false;
      if (dispatch) {
        const r = dir < 0 ? at.row : at.row + 1, tr = state.tr.insert(rowStart(at.table, at.pos, r), emptyRow(width(at.table)));
        dispatch(into(tr, at.pos, r, at.col, false).scrollIntoView());
      }
      return true;
    };
  }
  /* a column left (-1) or right (1) of the cursor's, as the book; the cursor in it, in the same row */
  function addColumn(dir) {
    return (state, dispatch) => {
      const at = locate(state);
      if (!at) return false;
      if (dispatch) {
        const tr = state.tr, table = filled(tr, at.pos), c = dir < 0 ? at.col : at.col + 1, align = fit(table.attrs.align, width(table));
        for (let r = table.childCount - 1; r >= 0; r--) tr.insert(cellStart(table, at.pos, r, c), N.table_cell.create());
        align.splice(c, 0, null);
        tr.setNodeMarkup(at.pos, null, {...table.attrs, align});
        dispatch(into(tr, at.pos, at.row, c, false).scrollIntoView());
      }
      return true;
    };
  }
  /* the cursor's row; the cursor in the row that takes its place (the row above when it was the last). The only row: the
     table. Deleting the header row makes the next row the header. */
  function deleteRow(state, dispatch) {
    const at = locate(state);
    if (!at) return false;
    if (at.table.childCount === 1) return deleteTable(state, dispatch);
    if (dispatch) {
      const from = rowStart(at.table, at.pos, at.row), tr = state.tr.delete(from, from + at.table.child(at.row).nodeSize);
      dispatch(into(tr, at.pos, at.row, at.col).scrollIntoView());
    }
    return true;
  }
  /* the cursor's column and its alignment; the cursor in the column that takes its place (the one before when it was the
     last). The only column: the table. */
  function deleteColumn(state, dispatch) {
    const at = locate(state);
    if (!at) return false;
    if (width(at.table) === 1) return deleteTable(state, dispatch);
    if (dispatch) {
      const tr = state.tr, table = filled(tr, at.pos), align = fit(table.attrs.align, width(table));
      for (let r = table.childCount - 1; r >= 0; r--) {
        const from = cellStart(table, at.pos, r, at.col);
        tr.delete(from, from + table.child(r).child(at.col).nodeSize);
      }
      align.splice(at.col, 1);
      tr.setNodeMarkup(at.pos, null, {...table.attrs, align});
      dispatch(into(tr, at.pos, at.row, at.col).scrollIntoView());
    }
    return true;
  }
  /* Header row on and off: the first row is the header or a row like the others; the cursor stays */
  function toggleHeader(state, dispatch) {
    const at = locate(state);
    if (!at) return false;
    if (dispatch) {
      const attrs = at.table.attrs;
      dispatch(state.tr.setNodeMarkup(at.pos, null, {...attrs, header: !attrs.header, align: fit(attrs.align, width(at.table))}));
    }
    return true;
  }
  /* the cursor's column as the book (null), left, centred or right; the cursor stays */
  function setColumnAlign(align) {
    return (state, dispatch) => {
      const at = locate(state);
      if (!at || !COLUMN_ALIGNS.includes(align)) return false;
      const old = at.table.attrs.align, next = fit(old, width(at.table));
      next[at.col] = align;
      if (dispatch && JSON.stringify(next) !== JSON.stringify(old)) dispatch(state.tr.setNodeMarkup(at.pos, null, {...at.table.attrs, align: next}));
      return true;
    };
  }
  /* the table the cursor is in, or the one selected; the cursor at the end of the text before it (not the title's), else
     at the start of the text after it, else in an empty line in its place (the piece keeps a line to type on) */
  function deleteTable(state, dispatch) {
    const at = tableAt(state);
    if (!at) return false;
    if (dispatch) {
      const tr = state.tr.delete(at.pos, at.pos + at.table.nodeSize), $p = tr.doc.resolve(at.pos);
      const blocks = tr.doc.childCount - (tr.doc.firstChild && tr.doc.firstChild.type === N.title ? 1 : 0);
      const before = blocks ? Selection.findFrom($p, -1, true) : null, after = blocks ? Selection.findFrom($p, 1, true) : null;
      let sel = before && before.$from.parent.type === N.title ? after || before : before || after;
      if (!sel) { tr.insert(at.pos, N.paragraph.create()); sel = TextSelection.create(tr.doc, at.pos + 1); }
      dispatch(tr.setSelection(sel).scrollIntoView());
    }
    return true;
  }
  /* Tab (1) and Shift+Tab (-1): the next or the previous cell, the cursor at the end of its text. Tab in the last cell
     adds a row; Shift+Tab in the first cell stays (and keeps the key, as Tab does at the top of a list). */
  function nextCell(dir) {
    return (state, dispatch) => {
      const at = locate(state);
      if (!at) return false;
      const {table, row, col} = at, rows = table.childCount;
      let r = row, c = col + dir;
      if (c >= table.child(r).childCount) { r++; c = 0; }
      else if (c < 0) { r--; c = r >= 0 ? table.child(r).childCount - 1 : 0; }
      if (r < 0 || !dispatch) return true;
      const tr = state.tr;
      if (r >= rows) tr.insert(rowStart(table, at.pos, rows), emptyRow(width(table)));
      dispatch(into(tr, at.pos, r, c, r < rows).scrollIntoView());
      return true;
    };
  }
  /* Enter: the cell below, the cursor at the end of its text; in the last row out of the table, into the paragraph after
     it (at its start), made when the table isn't followed by one. On a selected note or math in a cell false: Enter
     opens it (book-text.js, book-math.js). */
  function cellEnter(state, dispatch) {
    const at = locate(state);
    if (!at || (state.selection instanceof NodeSelection && state.selection.node.isInline)) return false;
    if (!dispatch) return true;
    const {table, pos, row, col} = at;
    if (row < table.childCount - 1) { dispatch(into(state.tr, pos, row + 1, col).scrollIntoView()); return true; }
    const end = pos + table.nodeSize, next = state.doc.resolve(end).nodeAfter, tr = state.tr;
    if (!next || next.type !== N.paragraph) tr.insert(end, N.paragraph.create());
    dispatch(tr.setSelection(TextSelection.create(tr.doc, end + 1)).scrollIntoView());
    return true;
  }
  /* Backspace: over a selection across cells their text cleared (cellDelete); in a table with nothing in it the first
     selects the table; on a selected table it removes it. Anywhere else false, so Backspace does what it does in text
     (at a cell's start nothing: a cell is isolating). */
  function cellBackspace(state, dispatch) {
    if (cellDelete(state, dispatch)) return true;
    const sel = state.selection;
    if (sel instanceof NodeSelection && sel.node.type === N.table) return deleteTable(state, dispatch);
    const at = locate(state);
    if (!at || !isEmpty(at.table)) return false;
    if (dispatch) dispatch(state.tr.setSelection(NodeSelection.create(state.doc, at.pos)).scrollIntoView());
    return true;
  }

  /* ——— a selection across cells, or across a table's edge: a cell holds one line, so deleting, typing, pasting or
     cutting over cells clears the text selected in each and keeps the rows and columns, and the text selected outside
     the table is deleted on its own (ProseMirror's own deletion would join the cells, or a cell with a paragraph) ——— */
  /* the position of the table whose cell holds $pos, else null */
  const cellTable = $pos => ($pos.parent.type === N.table_cell ? $pos.before($pos.depth - 2) : null);
  /* {from, ranges: [[a, b], …] in document order} when the selection is text with an end in a table's cell and isn't in
     one cell, else null: the selected text of each cell of the table (or two tables) its ends are in, and between them
     what lies outside those tables (whole blocks, tables too, and the ends of the lines it starts or ends in) */
  function across(state) {
    const sel = state.selection;
    if (!(sel instanceof TextSelection) || sel.empty || sel.$from.sameParent(sel.$to)) return null;
    const first = cellTable(sel.$from), last = cellTable(sel.$to);
    if (first == null && last == null) return null;
    const ranges = [];
    state.doc.nodesBetween(sel.from, sel.to, (node, pos) => {
      if (node.type === N.table) return pos === first || pos === last;
      if (node.type !== N.table_cell) return node.type === N.table_row;
      const a = Math.max(sel.from, pos + 1), b = Math.min(sel.to, pos + 1 + node.content.size);
      if (b > a) ranges.push([a, b]);
      return false;
    });
    if (first !== last) {
      // outside the tables: from the first table's end (or the selection's start) to the last's start (or its end),
      // without a line's mere edge (nothing of it selected)
      let $a = state.doc.resolve(first == null ? sel.from : first + state.doc.nodeAt(first).nodeSize);
      let $b = state.doc.resolve(last == null ? sel.to : last);
      while ($a.depth && $a.pos === $a.end()) $a = state.doc.resolve($a.after());
      while ($b.depth && $b.pos === $b.start()) $b = state.doc.resolve($b.before());
      if ($b.pos > $a.pos) ranges.push([$a.pos, $b.pos]);
      ranges.sort((x, y) => x[0] - y[0]);
    }
    return {from: sel.from, ranges};
  }
  /* the transaction that deletes what across(state) gives, `text` typed where the selection starts (the first cell, or
     the line before the table), the cursor after it; null when the selection isn't across cells or a table's edge */
  function clearAcross(state, text = "") {
    const a = across(state);
    if (!a) return null;
    const tr = state.tr;
    for (const [x, y] of a.ranges.reverse()) tr.delete(x, y);
    if (text) tr.insertText(text, a.from);
    return tr.setSelection(TextSelection.create(tr.doc, a.from + text.length)).scrollIntoView();
  }
  /* Delete (and Backspace, the word keys, a cut) over a selection across cells: their text cleared */
  function cellDelete(state, dispatch) {
    const tr = clearAcross(state);
    if (!tr) return false;
    if (dispatch) dispatch(tr);
    return true;
  }

  /* ——— a table pasted from Word, Docs or the web: each cell one line before the schema reads it. Word and Docs put
     paragraphs in cells and the web line breaks and lists, and the schema's cell holds one line: each would end the cell,
     and the table, where it stands ——— */
  // what ends a line in a pasted cell: a block (a paragraph, a heading, a quotation, a list and its items, a table in the
  // cell and its cells) or a line break
  const LINE_ENDS = /^(ADDRESS|ARTICLE|ASIDE|BLOCKQUOTE|BR|CAPTION|CENTER|DD|DIV|DL|DT|FIGCAPTION|FIGURE|FOOTER|H[1-6]|HEADER|HR|LI|OL|P|PRE|SECTION|TABLE|TBODY|TD|TFOOT|TH|THEAD|TR|UL)$/;
  // the editor's own notes, citations and math stay whole (a note's line breaks are its own)
  const own = n => /(^|\s)bk-(note|cite|math)(\s|$)/.test((n.nodeType === 1 && n.getAttribute("class")) || "");
  const endsLines = e => [...e.childNodes].some(k => k.nodeType === 1 && !own(k) && (LINE_ENDS.test(k.nodeName) || endsLines(k)));
  /* The lines of `parent`'s content added to `lines`, whose last line is open: inline nodes as they are; a block or a line
     break ends a line; an inline element that holds one is split around it, each piece in a copy of the element (its
     formatting stays). Images are left out (a cell holds none). */
  function cellLines(parent, lines) {
    for (const c of [...parent.childNodes]) {
      if (c.nodeType === 3) lines[lines.length - 1].push(c);
      else if (c.nodeType !== 1 || c.nodeName === "IMG") continue;
      else if (own(c) || !(LINE_ENDS.test(c.nodeName) || endsLines(c))) lines[lines.length - 1].push(c);
      else if (LINE_ENDS.test(c.nodeName)) { lines.push([]); cellLines(c, lines); lines.push([]); }
      else {
        cellLines(c, [[]]).forEach((line, i) => {
          if (i) lines.push([]);
          if (!line.length) return;
          const copy = c.cloneNode(false);
          copy.append(...line);
          lines[lines.length - 1].push(copy);
        });
      }
    }
    return lines;
  }
  /* A pasted table's cell (an element) as one line, in place: its lines joined by a space, the empty ones left out. */
  function flatCell(cell) {
    const lines = cellLines(cell, [[]]).filter(l => l.some(n => own(n) || /\S/.test(n.textContent)));
    cell.replaceChildren(...lines.flatMap((l, i) => (i ? [cell.ownerDocument.createTextNode(" "), ...l] : l)));
  }
  /* HTML pasted or dropped from outside, before the schema reads it (book-text.js's cleanPaste): each cell of a table in
     it one line (flatCell, a table in a cell taken in by it). Without the browser's DOMParser, or without a cell in
     what it reads (cells with no table around them), the HTML is left as it is. */
  function pasteCells(html) {
    if (typeof root.DOMParser !== "function") return html;
    const d = new root.DOMParser().parseFromString(html, "text/html"), cells = [...d.body.querySelectorAll("td, th")];
    if (!cells.length) return html;
    for (const cell of cells) if (cell.isConnected && !cell.parentElement.closest("td, th")) flatCell(cell);
    return d.body.innerHTML;
  }

  /* ——— what is on where the cursor is (the format panel's Table row) ——— */
  /* {header, align: the cursor's column's (null: as the book), row, col, rows, cols}; null outside a table */
  function current(state) {
    const at = locate(state);
    if (!at) return null;
    const {table, row, col} = at, cols = width(table);
    return {header: !!table.attrs.header, align: fit(table.attrs.align, cols)[col], row, col, rows: table.childCount, cols};
  }

  /* ——— keys ——— */
  /* a command on the view the author is writing in; nothing while the piece is locked */
  const onView = cmd => T => {
    if (T.locked) return;
    const view = (T.activeView && T.activeView()) || T.view;
    cmd(view.state, tr => view.dispatch(tr), view);
  };
  const keyRow = (id, label, key, cmd, short) => Object.assign({id, label, key, group: "Table", run: onView(cmd), cmd}, short ? {short} : {});
  /* One row per command, in the palette's order, as book-format.js's KEYS: its key as the spec writes it (null: none), the
     group "Table" (the format panel's Table row); `cmd` the command itself, and `short` what the panel's Table row and
     the button's menu call an alignment. */
  const KEYS = [
    keyRow("table-row-above", "Row above", "Ctrl+Alt+↑", addRow(-1)),
    keyRow("table-row-below", "Row below", "Ctrl+Alt+↓", addRow(1)),
    keyRow("table-column-left", "Column left", "Ctrl+Alt+←", addColumn(-1)),
    keyRow("table-column-right", "Column right", "Ctrl+Alt+→", addColumn(1)),
    keyRow("table-delete-row", "Delete row", null, deleteRow),
    keyRow("table-delete-column", "Delete column", null, deleteColumn),
    keyRow("table-header", "Header row", null, toggleHeader),
    keyRow("table-align-book", "Align column as the book", null, setColumnAlign(null), "As the book"),
    keyRow("table-align-left", "Align column left", null, setColumnAlign("left"), "Left"),
    keyRow("table-align-center", "Centre column", null, setColumnAlign("center"), "Centre"),
    keyRow("table-align-right", "Align column right", null, setColumnAlign("right"), "Right"),
    keyRow("table-delete", "Delete table", null, deleteTable),
  ];
  const ALIGN_IDS = ["table-align-book", "table-align-left", "table-align-center", "table-align-right"];     // COLUMN_ALIGNS' order
  const rowOf = id => KEYS.find(k => k.id === id);
  const MAC = typeof navigator !== "undefined" && /Mac|iP(hone|[oa]d)/.test(navigator.platform || "");
  /* the keys of ProseMirror's base keymap that delete a selection, besides Backspace and Delete */
  const DELETING = ["Mod-Backspace", "Mod-Delete", "Shift-Backspace",
    ...(MAC ? ["Ctrl-h", "Alt-Backspace", "Ctrl-d", "Ctrl-Alt-Backspace", "Alt-Delete", "Alt-d"] : [])];
  /* The keys for book-text.js's keymap: Ctrl+Alt+↑ / ↓ a row above / below, Ctrl+Alt+← / → a column left / right. In a
     table they keep the key (nothing changes while the piece is locked); elsewhere they pass. The keys that delete a
     word clear the text of the cells a selection runs across (else they pass). Tab, Enter, Backspace and Delete are
     book-text's chains, which try nextCell, cellEnter, cellBackspace and cellDelete first. */
  function keymap(T) {
    const key = cmd => (state, dispatch, view) => { if (!inTable(state)) return false; if (!T.locked) cmd(state, dispatch, view); return true; };
    const clear = (state, dispatch) => { if (!across(state)) return false; if (!T.locked) cellDelete(state, dispatch); return true; };
    return {"Mod-Alt-ArrowUp": key(addRow(-1)), "Mod-Alt-ArrowDown": key(addRow(1)),
            "Mod-Alt-ArrowLeft": key(addColumn(-1)), "Mod-Alt-ArrowRight": key(addColumn(1)),
            ...Object.fromEntries(DELETING.map(k => [k, clear]))};
  }
  /* a key as the keyboard shows it (book-panel.js, once loaded: ⌘⌥↑ on macOS) */
  const keyText = key => (root.BookPanel && root.BookPanel.keyText ? root.BookPanel.keyText(key) : key);

  /* ——— the Table button's menu ——— */
  /* The items for StudioMenu.open where the cursor is in a table (none elsewhere): the commands, Header row and the
     column's alignment checked as they are. `run(cmd)` gives what an item does. */
  function menu(state, run) {
    const cur = current(state);
    if (!cur) return [];
    const item = id => { const k = rowOf(id); return Object.assign({label: k.label, act: run(k.cmd)}, k.key ? {kbd: keyText(k.key)} : {}); };
    return [
      item("table-row-above"), item("table-row-below"), item("table-column-left"), item("table-column-right"), "-",
      item("table-delete-row"), item("table-delete-column"), "-",
      Object.assign(item("table-header"), {checked: cur.header}),
      {label: "Align column", items: ALIGN_IDS.map((id, i) => ({label: rowOf(id).short, checked: cur.align === COLUMN_ALIGNS[i], act: run(rowOf(id).cmd)}))},
      "-",
      Object.assign(item("table-delete"), {danger: true}),
    ];
  }

  /* ——— decorations: each cell of an aligned column says so (data-align, book-table.css aligns it); the table the cursor
     is in is marked (bk-table-on: its Table button shows) ——— */
  const tableKey = new PluginKey("bk-table");
  function alignments(doc) {
    const decos = [];
    doc.forEach((node, pos) => {                    // tables stand at the top level
      if (node.type !== N.table) return;
      const align = fit(node.attrs.align, width(node));
      if (!align.some(Boolean)) return;
      let p = pos + 1;
      node.forEach(row => {
        let q = p + 1;
        row.forEach((cell, _, c) => { if (align[c]) decos.push(Decoration.node(q, q + cell.nodeSize, {"data-align": align[c]})); q += cell.nodeSize; });
        p += row.nodeSize;
      });
    });
    return DecorationSet.create(doc, decos);
  }
  /* the transaction that makes every table of `state` rectangular (short rows filled with empty cells, as a reload does)
     with one alignment per column; null when they all are */
  function rectangular(state) {
    let tr = null;
    state.doc.forEach((node, pos) => {
      if (node.type !== N.table) return;
      const n = width(node), align = fit(node.attrs.align, n);
      node.forEach((row, offset) => {
        if (row.childCount < n) (tr = tr || state.tr).insert(tr.mapping.map(pos + 1 + offset + row.nodeSize - 1), emptyRow(n - row.childCount).content);
      });
      if (JSON.stringify(align) !== JSON.stringify(node.attrs.align)) (tr = tr || state.tr).setNodeMarkup(tr.mapping.map(pos), null, {...node.attrs, align});
    });
    return tr;
  }
  /* The plugin for book-text.js's view: the decorations; text typed or pasted over a selection across cells into the
     first of them, the others cleared; a cut across cells clears them after ProseMirror has copied the selection (its own
     deletion, and a drag's, is refused: it would join the cells); and every table kept rectangular. Book-text puts it
     first, before the / menu's and the typing rules' handleTextInput. */
  function plugins() {
    return [new Plugin({
      key: tableKey,
      state: {init: (config, state) => alignments(state.doc), apply: (tr, set) => (tr.docChanged ? alignments(tr.doc) : set)},
      props: {
        decorations(state) {
          const set = tableKey.getState(state), at = locate(state);
          return at ? set.add(state.doc, [Decoration.node(at.pos, at.pos + at.table.nodeSize, {class: "bk-table-on"})]) : set;
        },
        handleTextInput(view, from, to, text) {
          const sel = view.state.selection;
          if (from !== sel.from || to !== sel.to) return false;
          const tr = clearAcross(view.state, text);
          if (!tr) return false;
          view.dispatch(tr);
          return true;
        },
        // in a cell the slice is one line already (book-text.js's transformPasted); it goes where the selection starts,
        // as ProseMirror's own paste puts it there (replaceSelection), the cursor after it
        handlePaste(view, event, slice) {
          const tr = clearAcross(view.state);
          if (!tr) return false;
          view.dispatch(tr.replaceSelection(slice).scrollIntoView());
          return true;
        },
        handleDOMEvents: {
          cut(view) {             // nothing while the piece is locked (the view isn't editable): a cut is then a copy
            if (view.editable && across(view.state)) queueMicrotask(() => { const tr = clearAcross(view.state); if (tr) view.dispatch(tr); });
            return false;
          },
        },
      },
      filterTransaction: (tr, state) => !(["cut", "drop"].includes(tr.getMeta("uiEvent")) && tr.docChanged && across(state)),
      appendTransaction: (trs, old, state) => (trs.some(tr => tr.docChanged) ? rectangular(state) : null),
    })];
  }

  /* ——— the node view ——— */
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  /* The table inside a wrapper that scrolls sideways when the table is wider than the text column (never widening it),
     and the quiet Table button at its top right, shown while the cursor is in the table (bk-table-on, book-table.css),
     which opens the commands as a menu. The table element says whether its first row is the header (data-header). */
  class TableView {
    constructor(node, view, getPos, T) {
      Object.assign(this, {node, view, getPos, T});
      this.dom = el("div", "bk-tablew");
      this.button = el("button", "btn small quiet bk-table-b", "Table");
      Object.assign(this.button, {type: "button", tabIndex: -1, contentEditable: "false"});
      this.button.setAttribute("aria-haspopup", "menu");
      this.button.addEventListener("mousedown", e => e.preventDefault());       // the selection stays in the table
      this.button.addEventListener("click", e => this.open(e));
      const scroll = el("div", "bk-table-s");
      this.table = el("table", "bk-table");
      this.contentDOM = el("tbody");
      this.table.append(this.contentDOM);
      scroll.append(this.table);
      this.dom.append(this.button, scroll);
      this.sync();
    }
    sync() { this.table.setAttribute("data-header", String(!!this.node.attrs.header)); }
    update(node) {
      if (node.type !== N.table) return false;
      this.node = node;
      this.sync();
      return true;
    }
    open(e) {
      e.preventDefault(); e.stopPropagation();
      const T = this.T, v = this.view;
      if (T.locked || typeof StudioMenu === "undefined") return;
      const r = this.button.getBoundingClientRect();
      StudioMenu.open({preventDefault() {}, stopPropagation() {}, clientX: r.left, clientY: r.bottom + 4},
        menu(v.state, cmd => () => { if (T.locked) return; cmd(v.state, tr => v.dispatch(tr), v); v.focus(); }));
      // Escape closes the menu (menu.js, which listens first) and leaves the focus nowhere: back to the text, its caret
      // where it was. Any other key once the menu has gone, or a pointer down, ends this.
      const done = () => { removeEventListener("keydown", key, true); removeEventListener("pointerdown", done, true); };
      const key = e => {
        if (e.key === "Escape") { done(); if (!document.activeElement || document.activeElement === document.body) v.focus(); }
        else if (!document.querySelector(".ctx")) done();
      };
      addEventListener("keydown", key, true);
      addEventListener("pointerdown", done, true);
    }
    stopEvent(e) { return this.button.contains(e.target); }
    /* the wrapper, the button and the table element are this view's own; the rows are ProseMirror's */
    ignoreMutation(m) { return !this.contentDOM.contains(m.target) || (m.target === this.contentDOM && m.type === "attributes"); }
  }
  /* the node views for book-text.js's view */
  const nodeViews = T => ({table: (n, v, g) => new TableView(n, v, g, T)});

  root.BookTable = {
    commands: {insertTable, addRow, addColumn, deleteRow, deleteColumn, toggleHeader, setColumnAlign, deleteTable, nextCell, cellEnter, cellBackspace,
      cellDelete},
    inTable, current, across, clearAcross, KEYS, keymap, menu, plugins, TableView, nodeViews, flatCell, pasteCells,
  };
})(typeof window !== "undefined" ? window : globalThis);
