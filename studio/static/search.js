"use strict";
/* One search across the library (spec S3, S5-S8): the panel that Ctrl+K opens anywhere outside a book's writing
   window (and the top bar's Search button, and the book palette's first action), its keys, and the jumps to the match.
   The index and GET /api/search are studio/search.py; every range in a reply counts UTF-16 code units, as JS strings
   do, so marks and selections slice the text directly. A classic script after book-tools.js, whose Ctrl+K listener (the
   book's palette) runs first; sets window.LibrarySearch. The helpers at the top touch no DOM, so
   tests/test_library_static.py runs them in node. */
(function (root) {
  /* ——— helpers (no DOM) ——— */
  const GAP = "\ufffc";                 // an inline node that isn't text (a note, a citation), as book-tools.js writes it
  const MORE = 200;                     // what Show all asks for (the server's most)
  const NOUNS = {poem: "poems", piece: "pieces", book: "books", series: "series", design: "designs", research: "research items"};
  const num = n => Number(n || 0).toLocaleString("en-GB");
  const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  /* text with the server's marks ([from, to] in UTF-16 units) as <mark>: cut by index first, then each piece escaped */
  function marked(text, marks) {
    const s = String(text ?? ""), out = [];
    let at = 0;
    for (const [from, to] of [...(marks || [])].sort((x, y) => x[0] - y[0])) {
      const a = Math.max(at, Math.min(from, s.length)), b = Math.min(to, s.length);
      if (b <= a) continue;
      out.push(esc(s.slice(at, a)), `<mark>${esc(s.slice(a, b))}</mark>`);
      at = b;
    }
    out.push(esc(s.slice(at)));
    return out.join("");
  }
  /* "Poems · 23" */
  const groupHead = g => `${g.label} · ${num(g.total)}`;
  /* "Show all 23 poems"; past what one answer holds, "Show the first 200 of 1,234 poems" */
  const moreLabel = g => {
    const noun = NOUNS[g.kind] || String(g.label || "").toLowerCase();
    return g.total > MORE ? `Show the first ${MORE} of ${num(g.total)} ${noun}` : `Show all ${num(g.total)} ${noun}`;
  };
  /* "312 poems · 2 books · 41 designs" (what isn't there is left out) */
  const countsLine = c => [["poems", "poem"], ["books", "book"], ["designs", "design"]].filter(([k]) => c?.[k])
    .map(([k, one]) => `${num(c[k])} ${c[k] === 1 ? one : k}`).join(" · ");
  /* how fresh the answer is: the first read, a check, or when the files were last checked (`checked`: the server's local
     time, without a zone, which Date reads as local time) */
  function freshness(st, now = Date.now()) {
    if (!st) return "";
    const b = st.building;
    if (b) return b.total ? `Reading the library… ${num(b.done)} of ${num(b.total)}` : "Reading the library…";
    if (st.checking) return "Checking for changes…";
    const t = st.checked ? new Date(st.checked).getTime() : NaN;
    if (isNaN(t)) return "";
    const s = (now - t) / 1000;
    return s < 10 ? "Checked just now" : `Checked ${Math.max(1, Math.floor(s / 60))} min ago`;
  }
  /* [from, to] of the match in a field's text: at `start` when the text there is still the match, else its first
     occurrence in any case; null when it isn't there any more */
  function findRange(value, match, start) {
    const v = String(value ?? ""), m = String(match ?? "");
    if (!m) return null;
    if (Number.isInteger(start) && v.slice(start, start + m.length) === m) return [start, start + m.length];
    const r = new RegExp(escRe(m), "iu").exec(v);
    return r ? [r.index, r.index + r[0].length] : null;
  }
  /* [from, to] (document positions) of the first occurrence of `match` in any case in a ProseMirror document's text
     blocks, across marks; never across a note, a citation or a line break; null when it isn't there */
  function docRange(doc, match) {
    const m = String(match ?? "");
    if (!m || !doc) return null;
    const re = new RegExp(escRe(m), "giu");
    let found = null;
    doc.descendants((node, pos) => {
      if (found) return false;
      if (!node.isTextblock) return true;
      let text = "";
      const at = [];
      node.forEach((c, off) => {
        const p = pos + 1 + off;
        if (c.isText) { for (let i = 0; i < c.text.length; i++) at.push(p + i); text += c.text; }
        else { at.push(p); text += c.type.name === "hard_break" ? "\n" : GAP; }
      });
      at.push(pos + 1 + node.content.size);
      for (const r of text.matchAll(re)) {
        if (r[0].includes(GAP) || r[0].includes("\n")) continue;
        found = [at[r.index], at[r.index + r[0].length]];
        break;
      }
      return false;
    });
    return found;
  }
  /* a result's row: the title with its marks, where it is and the field (muted, on the right), the snippet below */
  function resultHtml(r, i, on) {
    const meta = [r.where, r.field_label].filter(Boolean).join(" · ");
    return `<div class="ls-i" role="option" id="ls-${i}" data-i="${i}" aria-selected="${!!on}"><div class="ls-top">`
      + `<span class="ls-t">${marked(r.title, r.title_marks)}</span>${meta ? `<span class="ls-h">${esc(meta)}</span>` : ""}</div>`
      + `${r.snippet?.text ? `<div class="ls-s">${marked(r.snippet.text, r.snippet.marks)}</div>` : ""}</div>`;
  }
  const nothingHtml = q => `<p class="ls-none">Nothing in the library matches “${esc(q)}”.</p>`;
  /* Call step() soon, then every `every` ms, until it returns true (or throws: the page changed under it), alive()
     turns false or `within` ms have passed. Timers, not requestAnimationFrame, which doesn't run while the window
     isn't drawing (minimised, or behind another): a jump would give up unseen. */
  function poll(step, alive = () => true, within = 3000, every = 50) {
    const until = Date.now() + within;
    const tick = () => {
      if (!alive() || Date.now() > until) return;
      let done = true;
      try { done = step(); } catch { /* it simply opens */ }
      if (!done) setTimeout(tick, every);
    };
    setTimeout(tick, 0);
  }
  /* The search panel's question as a call: the /api/search reply for q (the first 8 of each group) */
  const search = q => api("/api/search?q=" + encodeURIComponent(String(q ?? "")));

  const helpers = {marked, groupHead, moreLabel, countsLine, freshness, findRange, docRange, resultHtml, nothingHtml, poll, search};
  if (typeof document === "undefined") { root.LibrarySearch = helpers; return; }          // node: the helpers only

  /* ——— the panel ——— */
  const KEYS = "↑↓ to move · Enter to open · Esc to close";
  const S = {
    wrap: null, input: null, list: null, foot: null, back: null, tick: 0,          // while it is open
    q: "", reply: null, full: {}, expanded: new Set(), active: 0, rows: [],        // kept while Studio runs
    state: null, error: "", seq: 0, timer: 0, retryTimer: 0, retries: 0, enterWhen: null,
    navigating: false, jump: 0,
  };

  function open(q = "") {
    q = String(q ?? "").trim();
    if (S.wrap) {
      if (q && q !== S.input.value.trim()) { S.input.value = q; changed(true); }
      S.input.focus(); S.input.select();
      return;
    }
    S.back = document.activeElement;
    // Opened from the book's palette: closing, it focused the text again, which scrolls the browser to the text's top;
    // the caret's line comes back into view before the panel takes the focus (and stays there behind it)
    const v = root.BookTools?.activePiece?.()?.text?.view;
    if (v && S.back === v.dom && v.hasFocus()) v.dispatch(v.state.tr.scrollIntoView());
    const wrap = document.createElement("div");
    wrap.className = "ls-wrap";
    wrap.innerHTML = `<div class="ls" role="dialog" aria-modal="true" aria-label="Search the library">
      <input class="ls-q" type="text" role="combobox" aria-expanded="true" aria-controls="ls-list" aria-autocomplete="list"
        aria-label="Search the library" spellcheck="false" autocomplete="off" placeholder="Search poems, books and designs">
      <div class="ls-list" id="ls-list" role="listbox" aria-label="Results"></div>
      <div class="ls-f"><span class="ls-st"></span><span class="ls-keys">${KEYS}</span></div></div>`;
    document.body.append(wrap);
    Object.assign(S, {wrap, input: $(".ls-q", wrap), list: $(".ls-list", wrap), foot: $(".ls-f", wrap)});
    wrap.addEventListener("keydown", key);
    wrap.addEventListener("mousedown", e => {
      if (!e.target.closest(".ls")) { e.preventDefault(); close(); }
      else if (e.target !== S.input) e.preventDefault();                 // the field keeps the focus
    });
    S.input.addEventListener("input", () => changed());
    S.list.addEventListener("mousemove", e => {
      const row = e.target.closest("[data-i]");
      if (row && +row.dataset.i !== S.active) { S.active = +row.dataset.i; mark(false); }
    });
    S.list.addEventListener("click", e => {
      const row = e.target.closest("[data-i]");
      if (row) { S.active = +row.dataset.i; choose(); }
    });
    if (q) S.q = q;
    S.input.value = S.q;
    render(true);                // the last results, as they were left, while they are asked again
    paintFoot();
    S.input.focus(); S.input.select();
    S.tick = setInterval(paintFoot, 5000);
    api("/api/search/warm", {}).catch(() => {});        // the first read of the library, or a check, starts now
    ask(S.q);                    // the kept query too: the library may have changed since
  }

  function close(refocus = true) {
    if (!S.wrap) return;
    const {wrap, back} = S;
    clearTimeout(S.timer); clearTimeout(S.retryTimer); clearInterval(S.tick);
    if (S.input.value.trim() !== S.q) { S.q = S.input.value.trim(); S.seq++; }        // asked again when it opens
    Object.assign(S, {wrap: null, input: null, list: null, foot: null, back: null, enterWhen: null});
    wrap.remove();
    if (refocus && back && back.isConnected && back !== document.body) back.focus({preventScroll: true});
  }

  /* the field changed: asked 120 ms after the last key, or at once */
  function changed(now = false) {
    clearTimeout(S.timer);
    S.enterWhen = null;
    const run = () => {
      const q = S.input ? S.input.value.trim() : S.q;
      if (q === S.q && S.reply?.q === q) return;
      S.q = q;
      ask(q);
    };
    if (now) run(); else S.timer = setTimeout(run, 120);
  }

  /* Ask the server. Only the newest request's answer is shown; while the files are being read or checked, the same
     query is asked again after 400 ms (20 times at most), so the results settle by themselves. */
  async function ask(q, again = false) {
    clearTimeout(S.retryTimer);
    if (!again) S.retries = 0;
    const seq = ++S.seq;
    let r;
    try { r = await api("/api/search?q=" + encodeURIComponent(q)); }
    catch (e) { if (seq === S.seq) { S.error = `The search didn't answer: ${plain(e.message)}.`; S.enterWhen = null; paintFoot(); } return; }
    if (seq !== S.seq) return;
    const same = S.reply?.q === q;
    if (!same) { S.full = {}; S.expanded = new Set(); S.active = 0; }
    S.reply = {...r, q};
    S.state = r; S.error = "";
    render(same);
    paintFoot();
    for (const kind of S.expanded) more(kind);
    if ((r.checking || r.building) && S.wrap && S.retries < 20) {
      S.retries++;
      S.retryTimer = setTimeout(() => { if (S.wrap && S.q === q && S.seq === seq) ask(q, true); }, 400);
    }
    if (S.enterWhen === q && S.wrap) { S.enterWhen = null; choose(); }
  }

  /* Show all: the whole group (up to 200) in place of its first eight */
  async function more(kind) {
    const q = S.q, seq = S.seq;
    S.expanded.add(kind);
    let r;
    try { r = await api(`/api/search?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}&limit=${MORE}`); }
    catch (e) { if (seq === S.seq) { S.error = `The search didn't answer: ${plain(e.message)}.`; paintFoot(); } return; }
    if (seq !== S.seq || S.q !== q) return;
    const g = r.groups.find(x => x.kind === kind);
    if (g) S.full[kind] = g; else delete S.full[kind];
    render(true);
  }

  function render(keep) {
    if (!S.wrap) return;
    const r = S.reply, q = r?.q || "", was = keep ? S.rows[S.active] : null, rows = [], html = [];
    if (r && q && q === S.q) {
      for (const g0 of r.groups || []) {
        const g = S.full[g0.kind] || g0;
        html.push(`<div class="ls-g" role="presentation">${esc(groupHead(g))}</div>`);
        for (const it of g.items) { html.push(resultHtml(it, rows.length, false)); rows.push({it}); }
        if (g.total > g.items.length && !S.full[g.kind]) {
          html.push(`<div class="ls-i ls-more" role="option" id="ls-${rows.length}" data-i="${rows.length}" aria-selected="false">${esc(moreLabel(g))}</div>`);
          rows.push({more: g.kind});
        }
      }
      if (!rows.length && !r.building) html.push(nothingHtml(q));
    }
    S.rows = rows;
    S.list.innerHTML = html.join("");
    S.input.setAttribute("aria-expanded", String(rows.length > 0));
    gutter();
    // the same row stays marked when the results come again; else the same place in the list
    const k = was ? rows.findIndex(x => was.it ? x.it?.href === was.it.href : x.more === was.more) : -1;
    S.active = k >= 0 ? k : Math.max(0, Math.min(S.active, rows.length - 1));
    mark(true);
  }
  /* a list that scrolls has a scrollbar: the footer's right edge moves in by as much, so the keys line up with the rows' */
  function gutter() {
    if (S.wrap) S.wrap.firstElementChild.style.setProperty("--ls-sb", `${S.list.offsetWidth - S.list.clientWidth}px`);
  }
  addEventListener("resize", gutter);

  function mark(scroll) {
    S.list.querySelectorAll("[data-i]").forEach(x => x.setAttribute("aria-selected", String(+x.dataset.i === S.active)));
    const cur = S.list.querySelector(`[data-i="${S.active}"]`);
    if (!cur) { S.input.removeAttribute("aria-activedescendant"); return; }
    S.input.setAttribute("aria-activedescendant", cur.id);
    if (!scroll) return;
    const head = cur.previousElementSibling;
    if (head?.classList.contains("ls-g")) head.scrollIntoView({block: "nearest"});      // a group's first row shows its heading
    cur.scrollIntoView({block: "nearest"});
  }

  function paintFoot() {
    if (!S.wrap) return;
    $(".ls-st", S.foot).textContent = [countsLine(S.state?.counts), freshness(S.state)].filter(Boolean).join(" · ");
    const errors = [S.error, ...(S.reply?.errors || [])].filter(Boolean);
    let err = $(".ls-err", S.foot);
    if (!errors.length) { err?.remove(); return; }
    if (!err) { err = document.createElement("p"); err.className = "ls-err"; err.setAttribute("role", "alert"); S.foot.prepend(err); }
    err.textContent = errors.join(" ");
  }

  /* Enter or a click: open the marked result, or show all of a group. Typed faster than the answer came: the top result
     of the answer for what is typed opens when it comes. */
  function choose() {
    const q = S.input.value.trim();
    if (q !== S.reply?.q) {
      S.enterWhen = q;
      if (q !== S.q) { clearTimeout(S.timer); S.q = q; ask(q); }
      return;
    }
    const row = S.rows[S.active];
    if (row?.more) more(row.more);
    else if (row) go(row.it);
  }

  function key(e) {
    e.stopPropagation();                 // the design editor's, the book's and the page's shortcuts never see these keys
    if (e.isComposing) return;
    const n = S.rows.length, mod = e.ctrlKey || e.metaKey;
    const move = d => { e.preventDefault(); if (n) { S.active = (S.active + d + n) % n; mark(true); } };
    if (mod && !e.altKey && !e.shiftKey && String(e.key).toLowerCase() === "k") { e.preventDefault(); if (!e.repeat) close(); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown" || (e.key === "Tab" && !e.shiftKey && !mod)) move(1);
    else if (e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey && !mod)) move(-1);
    else if (e.key === "PageDown") move(Math.min(8, n - 1 - S.active) || 0);
    else if (e.key === "PageUp") move(-Math.min(8, S.active) || 0);
    else if (e.key === "Enter") { e.preventDefault(); choose(); }
  }

  /* ——— the jumps (S7): the page opens, then, once it is drawn (3 s at most), the match is selected in it ——— */
  function go(r) {
    if (!r?.href) return;
    const j = r.jump || {};
    close(false);
    // the Design tab opens on it: the editor remembers a poem's design as its own "last." + id, under "studio.ed."
    if (j.type === "design" && j.id && j.slug) pref.set("ed.last." + j.id, j.slug);
    // a research item opens on its board, selected (board.js reads the board first when it is another one)
    if (j.type === "research" && j.id && root.Board?.goTo) { S.jump++; root.Board.goTo(j.board ?? null, j.id); return; }
    const token = ++S.jump;
    // Already on screen (a poem's match on the tab showing it, a piece open in the writing window): the page isn't
    // drawn again, which would lose what is typed there and the text's undo history. The same address again draws the
    // page again only where that is the jump (another design of the poem; a poem or piece not showing yet): a series'
    // or a book's page is already the jump, and drawing it again would drop unsaved edits there.
    const tab = j.type === "poem" ? (j.field === "posting" ? "art" : "write") : null, W = root.BookTools?.state?.W;
    const here = (tab && state.view === "poem" && state.poem?.id === j.id && state.tab === tab)
      || (j.type === "piece" && state.view === "book" && W?.book?.id === j.book && W.piece?.file === j.file);
    if (!here) {
      const before = location.hash;
      if (before !== r.href) {
        S.navigating = true;
        location.hash = r.href;
        if (location.hash === before) S.navigating = false;
      }
      if (location.hash === before && !["series", "book", "research"].includes(j.type)) route();
    }
    if (j.type === "poem" || j.type === "piece") settle(j, token);
  }
  const settle = (j, token) => poll(() => j.type === "poem" ? toPoem(j) : toPiece(j), () => token === S.jump);
  /* a click or a key while the page opens: the author has moved on, so a waiting jump takes nothing over */
  addEventListener("pointerdown", () => { S.jump++; }, true);
  addEventListener("keydown", e => { if (!["Control", "Shift", "Alt", "Meta"].includes(e.key)) S.jump++; }, true);

  const FIELDS = {title: "#title", text: "#text", notes: "#notes"};
  /* a poem's title, text or writing notes (Write tab) or its posting notes (Art tab): false until the page is there */
  function toPoem(j) {
    const tab = j.field === "posting" ? "art" : "write";
    if (state.view !== "poem" || state.poem?.id !== j.id || state.tab !== tab) return false;
    let el;
    if (j.field === "posting") {
      const sec = $("#ad-notes");
      el = sec && $(".ad-text", sec);
      if (!el) return false;
      if (el.hidden) $("[data-mode=write]", sec)?.click();          // the notes show as Markdown: write them
      if (el.hidden) return false;
    } else if (FIELDS[j.field]) el = $(FIELDS[j.field]);
    else return true;
    if (!el) return false;
    const range = findRange(el.value, j.match, j.start);
    if (range) selectIn(el, range);
    return true;
  }
  /* The match selected and focused (so the selection shows). A field that scrolls puts its line a third down; the page
     shows the whole field, or, when the field is taller than the window (a long poem grows with its text), the line in
     the middle. */
  function selectIn(el, [a, b]) {
    el.focus({preventScroll: true});
    el.setSelectionRange(a, b);
    if (el.tagName !== "TEXTAREA") { el.scrollIntoView({block: "center"}); return; }
    const cs = getComputedStyle(el), y = lineTop(el, a, cs), lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.5;
    if (el.scrollHeight > el.clientHeight + 1) el.scrollTop = Math.max(0, y - el.clientHeight / 3);
    const box = el.getBoundingClientRect();
    if (box.height <= innerHeight * 0.6) { el.scrollIntoView({block: "center"}); return; }
    scrollBy({top: box.top + el.clientTop + y - el.scrollTop + lh / 2 - innerHeight / 2});
  }
  /* the top of the line that holds character `at` of a textarea, from the top of its padding box: its text up to there
     in a hidden copy with the same type, width and wrapping (lines wrap, so it isn't the line number times the height) */
  function lineTop(ta, at, cs) {
    const m = document.createElement("div"), s = m.style;
    for (const p of ["fontFamily", "fontSize", "fontWeight", "fontStyle", "fontStretch", "fontVariant", "fontFeatureSettings",
      "fontVariationSettings", "fontKerning", "letterSpacing", "wordSpacing", "lineHeight", "textTransform", "textIndent", "tabSize",
      "paddingTop", "paddingLeft", "paddingRight", "whiteSpace", "wordBreak", "overflowWrap", "direction"]) s[p] = cs[p];
    Object.assign(s, {position: "absolute", top: "0", left: "-10000px", visibility: "hidden", boxSizing: "content-box", border: "0",
      height: "auto", overflow: "hidden", width: Math.max(0, ta.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)) + "px"});
    m.textContent = ta.value.slice(0, at);
    const caret = document.createElement("span");
    caret.textContent = "\u200b";
    m.append(caret);
    document.body.append(m);
    const y = caret.offsetTop;
    m.remove();
    return y;
  }
  /* A piece: once the writing window has it open, the book's Find shows the query (every match lit), and the first match
     in the piece is selected and scrolled to. Without the writing window's tools the page is the jump. */
  function toPiece(j) {
    const BT = root.BookTools;
    if (!BT?.state) return true;
    const W = BT.state.W;
    if (!W || W.book?.id !== j.book || W.piece?.file !== j.file) return false;
    const piece = [BT.activePiece?.(), W.piece].find(p => p?.file === j.file && p.text);
    if (!piece) return false;
    const rail = BT.state.rail;
    if (!rail) return true;
    rail.open("find", {query: j.match});
    const view = piece.text.view, TS = root.PM?.TextSelection;
    const r = view && TS ? docRange(view.state.doc, j.match) : null;
    if (!r) return true;
    // the text takes the focus back from Find first: ProseMirror only scrolls to a selection the page's selection is in
    view.focus();
    view.dispatch(view.state.tr.setSelection(TS.create(view.state.doc, r[0], r[1])).scrollIntoView());
    // then a third down its pane, where the book's own Find puts a result it goes to
    const sc = [W, W.split].find(p => p?.piece === piece)?.hosts?.scroll;
    if (sc) { const c = view.coordsAtPos(r[0], 1), box = sc.getBoundingClientRect(); sc.scrollTop += c.top - box.top - box.height * 0.35; }
    return true;
  }

  /* ——— Ctrl+K anywhere but a book's writing window (whose palette's listener ran first), and the top bar ——— */
  addEventListener("keydown", e => {
    if (e.defaultPrevented || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || String(e.key).toLowerCase() !== "k") return;
    if (state.view === "book" && root.BookTools?.state?.W) return;
    if ($("#dlg").open) return;
    e.preventDefault();
    if (e.repeat) return;                // held down: once, not open and closed in turn
    if (S.wrap) close(); else open();
  });
  /* a new page closes the panel (a jump closed it already) */
  addEventListener("hashchange", () => {
    if (S.navigating) { S.navigating = false; return; }
    if (S.wrap) close();
  });
  $("#search")?.addEventListener("click", () => open());

  root.LibrarySearch = {...helpers, open, close: () => close(), go};       // open(q), search(q): the spec's API
})(typeof window !== "undefined" ? window : globalThis);
