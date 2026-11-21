"use strict";
/* The format panel (Alt+O, Format in the selection bar, Format… in the palette) and the palette's Format group, for the
   writing window's text and a note's text. Built on book-format.js: its commands, KEYS, current() and applies(); in a
   table, on book-table.js's KEYS too (read when used, so it may load later). A
   classic script after book-format.js; sets BookFormat.openPanel and BookFormat.paletteActions, and window.BookPanel
   (the pure parts, for tests/js/book_panel.js). Everything before "the panel" touches no DOM, so node runs it: the rows
   and buttons the panel shows for a state, the palette's commands, how a key is written, where the panel goes and how
   the keys move in it. Spec: docs/superpowers/specs/2026-11-13-book-editor-power-design.md ("The format panel", "The
   palette", "Keys"). */
(function (root) {
  const F = root.BookFormat, C = F.commands;
  const MAC = typeof navigator !== "undefined" && /Mac|iP(hone|[oa]d)/.test(navigator.platform || "");

  /* ——— the commands: KEYS' rows carry only `run`, so here is each row's command (a row's own `cmd` comes first), and
     the panel's five sizes ——— */
  const COMMANDS = {
    paragraph: C.setTextStyle("paragraph"), heading: C.setTextStyle("heading"), subheading: C.setTextStyle("subheading"),
    quotation: C.setTextStyle("quotation"),
    ...Object.fromEntries(F.STYLES.map(s => [s, C.setList(s)])),
    indent: C.indent(1), outdent: C.indent(-1), "from-markers": C.listFromMarkers,
    "align-book": C.setAlign(null), "align-center": C.setAlign("center"), "align-right": C.setAlign("right"),
    larger: C.stepSize(1), smaller: C.stepSize(-1), "size-normal": C.setSize(null),
    "size-x-small": C.setSize("x-small"), "size-small": C.setSize("small"), "size-large": C.setSize("large"), "size-x-large": C.setSize("x-large"),
    strong: C.toggle("strong"), em: C.toggle("em"), underline: C.toggle("underline"), strike: C.toggle("strike"), smallcaps: C.toggle("smallcaps"),
    clear: C.clearFormatting,
  };
  const commandOf = row => row.cmd || COMMANDS[row.id] || null;
  /* the rows of the table's commands (book-table.js: each carries its `cmd`), none without it */
  const tableKeys = () => (root.BookTable ? root.BookTable.KEYS : []);
  const keyRow = id => F.KEYS.find(k => k.id === id) || tableKeys().find(k => k.id === id) || null;

  /* A key as KEYS writes it ("Ctrl+Shift+E") as the keyboard shows it: on macOS ⇧⌘E (BookFormat.keymap binds Mod), the
     modifiers in Apple's order ⌃⌥⇧⌘, and the panel's own Alt+O is ⌃⌥O there, where ⌥O types ø. */
  const GLYPHS = {Ctrl: "⌘", Alt: "⌥", Shift: "⇧"}, APPLE = "⌃⌥⇧⌘";
  function keyText(key, mac = MAC) {
    if (!key) return "";
    if (!mac) return key;
    if (key === "Alt+O") return "⌃⌥O";
    const parts = key.split("+"), last = parts.pop();
    return parts.map(p => GLYPHS[p] || p).sort((a, b) => APPLE.indexOf(a) - APPLE.indexOf(b)).join("") + last;
  }

  /* ——— the panel's rows, as the spec draws them: the rows are KEYS' groups Text, List, Align, Size and Style; a button
     is a row of KEYS (its label is the button's name) or one of the five sizes. `text`: what the button shows when not
     its name; `glyph`: it shows a mark or a letter, set in the serif; `apart`: it and what follows stand at the row's
     end. In a table the table's commands (book-table.js's KEYS) stand instead of Text, List and Align, in four short
     rows (`on`: what applies() says of them): its rows, its columns, the column's alignment, and the table itself. ——— */
  const SIZES = [["size-x-small", "Extra small", .75], ["size-small", "Small", .875], ["size-normal", "Normal size", 1],
    ["size-large", "Large", 1.2], ["size-x-large", "Extra large", 1.44]];
  const ROWS = [
    {id: "table-row", on: "table", label: "Row", buttons: [{id: "table-row-above", text: "Above"}, {id: "table-row-below", text: "Below"},
      {id: "table-delete-row", text: "Delete", apart: true}]},
    {id: "table-column", on: "table", label: "Column", buttons: [{id: "table-column-left", text: "Left"}, {id: "table-column-right", text: "Right"},
      {id: "table-delete-column", text: "Delete", apart: true}]},
    {id: "table-align", on: "table", label: "Align", buttons: [{id: "table-align-book", text: "As the book"}, {id: "table-align-left", text: "Left"},
      {id: "table-align-center", text: "Centre"}, {id: "table-align-right", text: "Right"}]},
    {id: "table", label: "Table", buttons: [{id: "table-header"}, {id: "table-delete", apart: true}]},
    {id: "text", label: "Text", buttons: [{id: "paragraph"}, {id: "heading"}, {id: "subheading"}, {id: "quotation"}]},
    {id: "list", label: "List", buttons: [["bullet", "•"], ["decimal", "1."], ["lower-alpha", "a."], ["upper-alpha", "A."], ["lower-roman", "i."],
      ["upper-roman", "I."]].map(([id, text]) => ({id, text, glyph: true})).concat([{id: "outdent", apart: true}, {id: "indent"}])},
    {id: "align", label: "Align", buttons: [{id: "align-book", text: "As the book"}, {id: "align-center"}, {id: "align-right"}]},
    {id: "size", label: "Size", buttons: SIZES.map(([id, name, scale]) => ({id, name, text: "A", glyph: true, scale}))},
    {id: "style", label: "Style", buttons: [["strong", "B"], ["em", "I"], ["underline", "U"], ["strike", "S"], ["smallcaps", "Small caps"]]
      .map(([id, text]) => ({id, text, glyph: true})).concat([{id: "clear", text: "Clear", apart: true}])},
  ];
  const TEXT_IDS = ["paragraph", "heading", "subheading", "quotation"], MARK_IDS = ["strong", "em", "underline", "strike", "smallcaps"];
  const ALIGN_OF = {"align-book": null, "align-center": "center", "align-right": "right"};
  const SIZE_OF = {"size-x-small": "x-small", "size-small": "small", "size-normal": null, "size-large": "large", "size-x-large": "x-large"};
  const COLUMN_OF = {"table-align-book": null, "table-align-left": "left", "table-align-center": "center", "table-align-right": "right"};
  /* whether button `id` shows pressed in the state `cur` (current()): true or false for a choice or a mark, null for an
     action (Outdent, Indent, Clear, a row added); nothing is pressed where the selection holds more than one ("mixed") */
  function pressedOf(id, cur) {
    if (id in COLUMN_OF) return !!cur.table && cur.table.align === COLUMN_OF[id];
    if (id === "table-header") return !!cur.table && cur.table.header;
    if (TEXT_IDS.includes(id)) return cur.text === id;
    if (F.STYLES.includes(id)) return cur.list === id;
    if (id in ALIGN_OF) return cur.align === ALIGN_OF[id];
    if (id in SIZE_OF) return cur.size === SIZE_OF[id];
    if (MARK_IDS.includes(id)) return !!cur.marks[id];
    return null;
  }
  /* The rows the panel shows for `state`: [{id, label, buttons: [{id, text, name, key, pressed, disabled, glyph, apart,
     scale}]}]. Only rows that apply (applies()); a button whose command doesn't apply here (Indent on a list's first item)
     stays, not to be pressed, so the rows keep their shape. `key` as the keyboard shows it; the sizes show the keys that
     step through them. */
  function rows(state, mac = MAC) {
    const on = F.applies(state), cur = F.current(state);
    const steps = `${keyRow("smaller").label} ${keyText(keyRow("smaller").key, mac)} · ${keyRow("larger").label} ${keyText(keyRow("larger").key, mac)}`;
    return ROWS.filter(r => on[r.on || r.id]).map(r => ({id: r.id, label: r.label, buttons: r.buttons.map(b => {
      const row = keyRow(b.id), name = b.name || row.label, cmd = commandOf(row || b);
      return {id: b.id, text: b.text || name, name, key: r.id === "size" ? steps : keyText(row && row.key, mac), pressed: pressedOf(b.id, cur),
        disabled: !cmd(state), glyph: !!b.glyph, apart: !!b.apart, scale: b.scale || null};
    })})).filter(r => r.buttons.some(b => !b.disabled));
  }

  /* ——— the palette ——— */
  /* The rows of KEYS whose command applies in `state`, in KEYS' order (the palette's), then the table's (in a table),
     and Format… last when the panel has something to show. */
  function paletteRows(state) {
    const keys = [...F.KEYS.filter(k => k.id !== "format"), ...tableKeys(), ...F.KEYS.filter(k => k.id === "format")];
    return keys.filter(k => (k.id === "format" ? rows(state).length > 0 : !!commandOf(k)?.(state)));
  }
  /* The view the author writes in: a note's editor or the text. While the palette has the focus, the one last written in
     (book-tools.js keeps T.lastView, as the rail's Cite uses it). */
  function writingView(T) {
    const v = T.activeView ? T.activeView() : T.view;
    if (v !== T.view) return v;
    const last = T.lastView, notes = T.margin ? [...T.margin.notes] : [];
    return last && last !== T.view && notes.some(nv => nv.inner === last) && !T.view.hasFocus() ? last : T.view;
  }
  /* a command on `view`, the focus back in it first (what is typed next keeps the marks a command gives it); nothing
     while the piece is locked */
  function runOn(T, view, cmd) {
    if (T.locked || T.destroyed) return;
    view.focus?.();
    cmd(view.state, tr => view.dispatch(tr), view);
  }
  /* The palette's Format group (book-tools.js): [{label, hint, run}] for the text `T`, every command that applies where
     the author writes, its key as the hint; none while the piece is locked. */
  function paletteActions(T) {
    if (!T || T.locked || T.destroyed) return [];
    const view = writingView(T);
    return paletteRows(view.state).map(k => ({label: k.label, hint: keyText(k.key),
      run: k.id === "format" ? () => { if (!T.locked) root.BookFormat.openPanel(T, view); } : () => runOn(T, view, commandOf(k))}));
  }

  /* ——— where the panel goes, and how the keys move in it ——— */
  /* The panel's {left, top} in the page's coordinates. Under `rect` (the cursor or selection: {left, top, bottom}), or
     above it when there's no room below in `seen` (the text's visible part, {top, bottom}) and there is above (with room
     on neither side, on the side with more). Its left edge 16px before the cursor, kept in the text column `col` when it
     fits there, as the citation form is, and always inside `page` with 16px to spare. `w`, `h`: the panel's size; all in
     the window's coordinates. */
  function place(rect, w, h, page, col, seen) {
    let left = Math.max(Math.min(col.left, page.right - w - 16), Math.min(rect.left - 16, col.right - w));
    left = Math.max(page.left + 16, Math.min(left, page.right - w - 16));
    const below = rect.bottom + 10, above = rect.top - 10 - h;
    const down = below + h <= seen.bottom || (above < seen.top && seen.bottom - rect.bottom >= rect.top - seen.top);
    return {left: Math.round(left - page.left), top: Math.round((down ? below : above) - page.top)};
  }
  /* The button to go to from [r, c] in `grid` (rows of {x, enabled}: a button's centre and whether it can be pressed)
     for `key`, as [r, c]: ←/→ along the row and round, Home/End to its ends, ↑/↓ to the row above or below (round) at the
     button nearest in x, Tab and Shift+Tab through every button and round; buttons that can't be pressed are passed.
     null for any other key. */
  function move(grid, [r, c], key) {
    const ok = row => row.map((b, j) => (b.enabled ? j : -1)).filter(j => j >= 0);
    const here = ok(grid[r]);
    if (key === "ArrowLeft" || key === "ArrowRight") {
      const i = here.indexOf(c), n = here.length;
      return [r, here[(i + (key === "ArrowRight" ? 1 : -1) + n) % n]];
    }
    if (key === "Home") return [r, here[0]];
    if (key === "End") return [r, here[here.length - 1]];
    if (key === "ArrowUp" || key === "ArrowDown") {
      const d = key === "ArrowDown" ? 1 : -1, x = grid[r][c].x;
      for (let k = 1; k <= grid.length; k++) {
        const to = (r + d * k + grid.length * k) % grid.length, cols = ok(grid[to]);
        if (!cols.length) continue;
        let best = cols[0];
        for (const j of cols) if (Math.abs(grid[to][j].x - x) < Math.abs(grid[to][best].x - x)) best = j;
        return [to, best];
      }
      return [r, c];
    }
    if (key === "Tab" || key === "Shift+Tab") {
      const all = grid.flatMap((row, i) => ok(row).map(j => [i, j])), i = all.findIndex(([a, b]) => a === r && b === c);
      return all[(i + (key === "Tab" ? 1 : -1) + all.length) % all.length];
    }
    return null;
  }

  /* ——— the panel ——— */
  const esc = s => String(s).replace(/[&<>"]/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;"})[ch]);
  const buttonHTML = b => `<button type="button" class="bk-fmt-b${b.glyph ? " g" : ""}${b.apart ? " apart" : ""}" data-id="${esc(b.id)}" tabindex="-1"`
    + `${b.text !== b.name ? ` aria-label="${esc(b.name)}"` : ""}${b.pressed == null ? "" : ` aria-pressed="${b.pressed}"`}`
    + `${b.scale ? ` style="--bk-fs:${b.scale}"` : ""}${b.disabled ? " disabled" : ""}>${esc(b.text)}</button>`;
  const panelHTML = shown => `<div class="bk-fmt-rows">${shown.map(r => `<div class="bk-fmt-row" role="toolbar" aria-labelledby="bk-fmt-${r.id}">`
    + `<span class="label" id="bk-fmt-${r.id}">${esc(r.label)}</span><div class="bk-fmt-bs">${r.buttons.map(buttonHTML).join("")}</div></div>`).join("")}</div>`
    + `<div class="bk-fmt-foot"><span class="n"></span><span class="k"></span></div>`;
  /* the key that opens the panel (BookFormat.keymap): in the panel it closes it. By the key's letter (or its key code,
     for ⌥O typing ø), as ProseMirror's keymap reads it, not by where the key sits on the keyboard. */
  const panelKey = e => (String(e.key || "").toLowerCase() === "o" || e.keyCode === 79) && e.altKey && !e.shiftKey && !e.metaKey && e.ctrlKey === MAC;

  /* The format panel for the text `T` at the cursor of `view` (the view the author writes in): the rows that apply,
     each choice pressed as it stands, the focus on the first row's current choice. A choice applies and closes it, as a
     menu does; Escape, the same key again or a click outside closes it; the focus goes back to the text, or the note. It
     is one of the text's small forms (T.openPop), so it closes when another opens and when the piece is locked. */
  function openPanel(T, view = T && writingView(T)) {
    if (!T || T.locked || T.destroyed || !view) return;
    const shown = rows(view.state);
    if (!shown.length) return;             // nothing to format here (an image is selected)
    const sel = view.state.selection, a = view.coordsAtPos(sel.from), z = sel.empty ? a : view.coordsAtPos(sel.to, -1);
    const rect = {left: Math.abs(a.top - z.top) < 4 ? a.left : z.left, top: a.top, bottom: z.bottom};
    const f = T.openPop("bk-fmt", panelHTML(shown), rect, {view, pos: sel.head});
    f.setAttribute("role", "dialog");
    f.setAttribute("aria-label", "Format");
    const page = T.page.getBoundingClientRect(), col = (view === T.view ? T.textHost : view.dom).getBoundingClientRect();
    const box = (T.page.closest(".bw-scroll") || T.page).getBoundingClientRect();
    const seen = {top: Math.max(box.top, 0), bottom: Math.min(box.bottom, innerHeight)};
    const at = place(rect, f.offsetWidth, f.offsetHeight, page, col, seen);
    f.style.left = at.left + "px";
    f.style.top = at.top + "px";

    const byId = new Map(shown.flatMap(r => r.buttons).map(b => [b.id, b]));
    const lines = [...f.querySelectorAll(".bk-fmt-bs")].map(bs => [...bs.children]);
    const foot = {n: f.querySelector(".bk-fmt-foot .n"), k: f.querySelector(".bk-fmt-foot .k")};
    const focused = () => document.activeElement?.closest?.(".bk-fmt-b") || null;
    /* the footer: the button under the pointer, else the one with the focus, and its key */
    const say = el => { const b = el && byId.get(el.dataset.id); foot.n.textContent = b ? b.name : ""; foot.k.textContent = b ? b.key : ""; };
    const apply = el => {
      const b = el && byId.get(el.dataset.id);
      if (!b || b.disabled) return;
      T.closePop(true);
      runOn(T, view, commandOf(keyRow(b.id) || b));
    };
    f.addEventListener("submit", e => e.preventDefault());
    f.addEventListener("mousedown", e => e.preventDefault());      // the focus stays where the keys left it
    // the focus gone somewhere else in the window closes it; the window itself losing the focus (no relatedTarget) not
    f.addEventListener("focusout", e => { if (e.relatedTarget && !f.contains(e.relatedTarget) && T.pop === f) T.closePop(); });
    f.addEventListener("click", e => apply(e.target.closest(".bk-fmt-b")));
    f.addEventListener("mouseover", e => say(e.target.closest(".bk-fmt-b") || focused()));
    f.addEventListener("mouseleave", () => say(focused()));
    f.addEventListener("focusin", e => say(e.target.closest(".bk-fmt-b")));
    f.addEventListener("keydown", e => {
      if (e.key === "Escape") return;              // openPop's: closes, the focus back in the text
      if (panelKey(e)) { e.preventDefault(); T.closePop(true); return; }
      const el = focused();
      if (!el || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); apply(el); return; }
      const r = lines.findIndex(line => line.includes(el)), grid = lines.map(line => line.map(b => {
        const box = b.getBoundingClientRect();
        return {x: box.left + box.width / 2, enabled: !b.disabled};
      }));
      const to = r < 0 ? null : move(grid, [r, lines[r].indexOf(el)], e.key === "Tab" && e.shiftKey ? "Shift+Tab" : e.key);
      if (!to) return;
      e.preventDefault();
      lines[to[0]][to[1]].focus();
    });
    // the focus on the first row's current choice, else its first button that can be pressed
    const first = lines[0], choice = shown[0].buttons.findIndex(b => b.pressed && !b.disabled);
    (first[choice >= 0 ? choice : shown[0].buttons.findIndex(b => !b.disabled)]).focus();
    return f;
  }

  Object.assign(root.BookFormat, {openPanel, paletteActions});
  root.BookPanel = {rows, paletteRows, keyText, place, move, commandOf, COMMANDS, writingView};
})(typeof window !== "undefined" ? window : globalThis);
