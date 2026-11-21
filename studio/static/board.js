"use strict";
/* The research board: #/research (the shared board) and #/book/<id>/board (a book's). A page with the writing window's
   proportions, fixed under the top bar: the sidebar (the board's head, then its frames, kinds and tags with counts) on
   the left; a toolbar (Canvas / List, search, Add) over the canvas or the list in the middle; the open item (400 px) on
   the right; a status bar. The board is read from GET /api/research and read again when its stamp moves (asked every
   2 s while the page is open), keeping the selection, the list's place and whatever has the focus.
   A classic script after board-core.js; sets window.Board: mount(el, {book}), unmount(), pending(), refresh(book?), and B
   (below); and the global showResearch() for the route.

   B is the page, for the parts that fill it. The canvas (board-canvas.js, made in mount()) is B.canvas =
   {render(board, filter), select(ids), show(id), goToFrame(id), rename(frameId), fit(), zoomTo(z), toBoard(x, y),
   destroy(), …}, shown instead of the list while B.view is "canvas". The rest is theirs to use: B.board (the last
   read), B.filter, B.sel, B.select(ids, opts), B.item(id), B.visible(), B.post(path, body), B.apply(board),
   B.refresh(), B.say(text, dirty), B.failed(error), B.titleOf(item) (what an item is called: {text, own}),
   B.nameOf(item) (the same, short, for toasts), B.sourceOf(item) (the source column, as escaped HTML).
   The open item: B.open(id, {focus}), B.close(), B.pending(), B.flush({leaving}). Adding: B.add(kind, at?, frame?)
   (the Add menu's kinds; `at` in board units), B.addText(text, at?) (a web address is clipped, other text a note),
   B.clip(url, at?, {frame, id}), B.addFiles(files, at?), B.quoteFrom(clipId, text). Menus: B.menu(e, ids),
   B.addMenu(button), B.askTrash(ids).
   Every change to the board goes through B.place(items, frames), B.addItem(fields, at, frame), B.addImage(name,
   data, at, frame), B.clip(…), B.trash(ids), B.restore(names), B.moveTo(ids, to, link) or B.setFrames({frames,
   remove_frames}); each records itself for undo (Ctrl+Z, Ctrl+Shift+Z, Ctrl+Y: "——— undo ———" below) and
   returns what the server returned, or null when it failed (said in a toast). */

const Board = (() => {
  const C = BoardCore, KINDS = Object.keys(C.KIND_NAME);
  const POLL = 2000, SEARCH_AFTER = 200;
  /* the column of cards the server makes for unplaced items, and the room a frame keeps around its cards */
  const GAP = 24, COLUMN_GAP = 80, FRAME_PAD = 24, FRAME_HEAD = 48;
  const BUSY = "The board is busy. Try again in a moment.";
  const COLUMNS = [["kind", "Kind", "bd-c-kind", "Sort each group by kind"], ["title", "Title", "bd-c-title", "Sort each group by title"],
    [null, "Source", "bd-c-src"], [null, "Tags", "bd-c-tags"], ["added", "Added", "bd-c-date", "Sort each group by date added, newest first"]];
  const SORTS = COLUMNS.map(c => c[0]).filter(Boolean);
  const ADD = [["note", "Note"], ["quote", "Quote"], ["source", "Source…"], ["clip", "Web clip…"], ["image", "Image…"],
    ["piece", "Link to a piece…"], ["frame", "Frame"]];

  const kindName = k => C.KIND_NAME[k] || (k ? k[0].toUpperCase() + k.slice(1) : "Item");
  const kindRank = k => { const i = KINDS.indexOf(k); return i < 0 ? KINDS.length : i; };
  const byName = (a, b) => a.localeCompare(b, undefined, {sensitivity: "base"});
  /* a 409 without the current item: the board's lock is held (a move, another window); not a stale save */
  const busy = e => !!e && e.status === 409 && !(e.data && e.data.current);
  const firstWords = i => String(i.excerpt || "").replace(/\s+/g, " ").trim();
  const same = (a, b) => (a || null) === (b || null) || (!!a && !!b && String(a).toLowerCase() === String(b).toLowerCase());
  const unhash = h => { try { return decodeURIComponent(h); } catch { return h; } };
  const menuAt = el => { const r = el.getBoundingClientRect(); return {clientX: r.left, clientY: r.bottom + 4, preventDefault() {}, stopPropagation() {}}; };

  /* {board, id, hash, until}: an item to open once its board has been read (a match on another board). Taken only by a
     board opened at that address within GOTO_MS of asking (a refused hash change leaves nothing to fire later). */
  let goTo = null;
  const GOTO_MS = 10000;

  const B = {
    root: null,         // the .bd element while the page is open
    book: null,         // the book (GET /api/book) on a book's board; null on the shared board
    id: null,           // the board as the API names it: the book's id, or null for the shared board
    board: null,        // the board as last read: {board, title, items, frames, tags, kinds, stamp}
    error: null,        // why the board couldn't be read, while it can't
    filter: {kind: null, tag: null, ids: null},   // BoardCore.matches: one kind, one tag, and the search's matches
    sel: new Set(),     // the selected items' ids
    cursor: null,       // the item the keys move from: the last one clicked or moved to
    anchor: null,       // where a Shift range starts
    view: "canvas",     // "canvas" or "list" (pref boardView); the list stands in until there is a canvas
    sort: "added",      // the list's order within each group (pref boardSort)
    q: "", every: false, results: null,       // the search; with every, the matches on every board
    canvas: null,       // the canvas (board-canvas.js) once it has been made
    panel: null,        // <aside class="bd-panel">, the open item's column (hidden while nothing is open)
    drag: null,         // rows being dragged onto a frame: {ids}
    readToken: 0, searchToken: 0, reading: 0, pollTimer: 0, searchTimer: 0, hush: 0,
  };

  const $r = s => B.root && B.root.querySelector(s);
  const path = (p, more) => { const qs = [C.boardParam(B.id), more].filter(Boolean).join("&"); return qs ? `${p}?${qs}` : p; };
  const item = id => (B.board && B.board.items.find(i => i.id === id)) || null;
  const visible = () => (B.board ? B.board.items : []).filter(i => C.matches(i, B.filter));
  const filtering = () => !!(B.filter.kind || B.filter.tag || B.filter.ids);
  const hitsShown = () => B.every && B.q.length >= 2;
  const listShown = () => !!B.root && !$r(".bd-lhost").hidden;
  const text = v => typeof v === "string" ? v.replace(/\s+/g, " ").trim() : "";

  /* A piece an item links to, as its summary carries it (`piece`, read from the book by the server): {title, book}
     (the book's title; the piece's kind when it has no title); null when it can't be found. */
  function pieceOf(i) {
    const p = i && i.type === "piece" && i.piece && typeof i.piece === "object" ? i.piece : null;
    return p && !p.missing ? {title: text(p.title) || (p.kind ? pieceKindName(p.kind) : ""), book: text(p.book_title)} : null;
  }

  /* What an item is called wherever it is listed: its title; else the title in its CSL (a source, a clip, an image with
     a source); else the title of the piece it links to; else the first words of its text. A link is summarised as its
     original, so this is the original's. {text, own}: own is false for the first words or a stand-in, set apart in
     italics. Notes and excerpts are only ever the second line. */
  function titleOf(i) {
    if (!i) return {text: "", own: false};
    const p = pieceOf(i);
    const t = text(i.title) || text(i.csl && typeof i.csl === "object" ? i.csl.title : "") || text(p && p.title);
    if (t) return {text: t, own: true};
    const w = firstWords(i);
    if (w) return {text: w, own: false};
    return {text: i.error ? `${i.id}.md` : kindName(i.type), own: false};
  }
  const nameOf = i => {
    const t = titleOf(i).text;
    return t.length > 60 ? t.slice(0, 60).trimEnd() + "…" : t;
  };

  /* The source column: a quote's citation; a citable item's short form (Author year), a clip without an author its
     site; a piece of another book that book's title. */
  function sourceOf(i) {
    if (i.error) return `<span class="bad">Can't be read</span>`;
    if (i.type === "link") return "Original gone";          // a link whose original is found reads as that original
    if (i.type === "quote") return esc(i.source_label || "");
    const csl = i.csl && typeof i.csl === "object" ? i.csl : null;
    const people = csl && [csl.author, csl.editor].some(a => Array.isArray(a) && a.length);
    if (i.type === "clip" && !people) return esc(i.site || (csl && text(csl["container-title"])) || "");
    if (csl) { try { return esc(BookText.sourceShort(csl)); } catch { return ""; } }     // a hand-written CSL it can't read
    if (i.type === "piece") { const p = pieceOf(i); return p && p.book && !(B.book && same(B.book.id, i.book)) ? esc(p.book) : ""; }
    return "";
  }
  const failed = e => toast(busy(e) ? BUSY : e.message, true);
  const say = (text, dirty = false) => {
    const el = $r("#bd-state");
    if (el) { el.textContent = text || ""; el.classList.toggle("dirty", !!dirty); }
  };

  /* ——— the page ——— */
  function mount(el, {book = null} = {}) {
    unmount();
    const side = pref.get("boardSide", innerWidth >= 1000 ? "1" : "0") === "1";
    const sort = pref.get("boardSort", "added");
    Object.assign(B, {book, id: book ? book.id : null, board: null, error: null, filter: {kind: null, tag: null, ids: null}, sel: new Set(),
      cursor: null, anchor: null, view: pref.get("boardView", "canvas") === "list" ? "list" : "canvas", sort: SORTS.includes(sort) ? sort : "added",
      q: "", every: false, results: null, drag: null, reading: 0});
    document.title = book ? `Board — ${book.title}` : "Research — Studio";
    if (goTo && (unhash(goTo.hash) !== unhash(location.hash) || performance.now() > goTo.until)) goTo = null;
    el.innerHTML = `<div class="bd${side ? "" : " noside"}">
      <aside class="bd-side" aria-label="The board"></aside>
      <section class="bd-main">
        <div class="bd-tools">
          <div class="seg bd-views" role="group" aria-label="View"><button type="button" data-view="canvas">Canvas</button><button type="button" data-view="list">List</button></div>
          <div class="bd-find"><input class="input bd-q" type="search" placeholder="Search the board" aria-label="Search the board" title="Search the board · / or Ctrl+F" spellcheck="false" autocomplete="off">
            <label class="bd-ck"><input type="checkbox" class="bd-every"><span>Every board</span></label></div>
          <button type="button" class="btn small bd-add" aria-haspopup="menu"><span class="plus">+</span>Add</button>
        </div>
        <div class="bd-pend" aria-live="polite" hidden></div>
        <div class="bd-view"><div class="bd-canvas" hidden></div><div class="bd-lhost"></div></div>
      </section>
      <aside class="bd-panel" aria-label="The open item" hidden></aside>
      <footer class="bd-status"><button type="button" class="bw-tog bd-tog" aria-pressed="${side}" title="Show or hide the sidebar · Ctrl+\\">Board</button>
        <span class="bd-counts"></span><span class="state" id="bd-state"></span><span class="bd-zoom" hidden></span></footer></div>`;
    B.root = $(".bd", el);
    B.panel = $r(".bd-panel");
    B.clipping = [];
    boards = null;
    U = typeof BoardCanvas !== "undefined" ? new BoardCanvas.Undo(UNDO_MAX) : null;
    wire();
    wirePanel();
    makeCanvas();
    paintSide(); paintTools(); paintView(); paintCounts();
    read();
    loadBoards();
    schedule();
  }

  function unmount() {
    if (!B.root) return;
    try {                                                       // the open item's leaving save
      const p = P;
      if (p) {
        commitTag(p);
        if (p.invalid && !p.gone) toast(`The accessed date of “${nameOf(p.item)}” wasn't saved. What you typed is kept and offered when you open the source again.`, true);
        release(p, true);
      }
      flush({leaving: true});
    } catch (e) { console.error(e); }
    try { B.canvas?.destroy(); } catch (e) { console.error(e); }
    if (U) U.clear();
    U = null;
    renamed.clear();
    clearTimeout(B.pollTimer); clearTimeout(B.searchTimer);
    B.readToken++; B.searchToken++;
    Object.assign(B, {root: null, panel: null, canvas: null, board: null, drag: null});
  }

  /* The board read again: now, and on the poll when its stamp moved. With the book (book.js, when the books changed),
     its head shows the book as it is now. */
  function refresh(book) {
    if (!B.root) return Promise.resolve();
    if (book && B.book && book.id === B.book.id) { B.book = book; document.title = `Board — ${book.title}`; paintSide(); }
    return read();
  }

  async function read() {
    const my = ++B.readToken, root = B.root;
    let board;
    B.reading++;
    try {
      board = await api(path("/api/research"));
    } catch (e) {
      if (my !== B.readToken || B.root !== root) return;
      if (e.status === 404 && B.book) return gone();
      if (busy(e) || !e.status) return;           // busy, or Studio not answering: the poll reads again
      B.error = e.message;
      if (!B.board) paintView();
      return;
    } finally {
      if (B.root === root) B.reading--;
    }
    if (my !== B.readToken || B.root !== root) return;
    B.error = null;
    apply(board);
    if (B.q.length >= 2) runSearch();          // what matches may have changed too
    if (goTo) { const g = goTo; goTo = null; if (same(g.board, B.id)) reveal(g.id); }
  }

  /* Shows a board read from the server (a read, or the board a change returns): the selection keeps what is still on
     it, a filter whose kind or tag is gone is dropped. */
  function apply(board) {
    if (!B.root) return;
    B.board = board;
    const ids = new Set(board.items.map(i => i.id));
    B.sel = new Set([...B.sel].filter(id => ids.has(id)));
    if (B.cursor && !ids.has(B.cursor)) B.cursor = null;
    if (B.filter.kind && !(board.kinds || {})[B.filter.kind]) B.filter.kind = null;
    if (B.filter.tag && !(board.tags || {})[B.filter.tag]) B.filter.tag = null;
    paintSide(); paintView(); paintCounts();
    panelSync();
  }

  function schedule() { clearTimeout(B.pollTimer); B.pollTimer = setTimeout(tick, POLL); }
  async function tick() {
    const root = B.root;
    if (!root) return;
    try {
      const {stamp} = B.reading ? {} : await api(path("/api/research/stamp"));      // a read under way says it all
      if (B.root !== root) return;
      if (!B.reading && (!B.board || stamp !== B.board.stamp)) await read();
    } catch (e) {
      if (B.root !== root) return;
      if (e.status === 404 && B.book) return gone();
      // busy, or Studio not answering (app.js says so): asked again on the next tick
    }
    if (B.root === root) schedule();
  }

  function gone() {
    const title = B.book ? B.book.title : "The book";
    unmount();
    toast(`${title} is no longer in Books`, true);
    location.hash = "#/books";
  }

  /* ——— the parts of the page ——— */
  function paintTools() {
    for (const b of $$(".bd-views [data-view]", B.root)) b.setAttribute("aria-pressed", String(b.dataset.view === B.view));
  }

  function paintSide() {
    const host = $r(".bd-side"), sc = $(".bd-scroll", host), scroll = sc ? sc.scrollTop : 0;
    const focused = host.contains(document.activeElement) ? document.activeElement.closest("[data-f]")?.dataset.f : null;
    const b = B.board, book = B.book, f = B.filter;
    // the kicker alone on its line, the title, and on a book's board its pages as tabs: Write · Board · Settings
    const head = book
      ? `<div class="bd-head tabbed"><p class="kicker bd-k"><a href="#/books">Books</a> · ${esc(bookKindName(book.kind))}</p><p class="bd-book">${esc(book.title)}</p>
          <nav class="bd-tabs" role="tablist" aria-label="The book's pages">${bookViewTabs(book.id, "board")}</nav></div>`
      : `<div class="bd-head"><p class="kicker bd-k">Research</p><p class="bd-book">${esc(b ? b.title : "Shared board")}</p></div>`;
    // a row: frames go to their group (no pressed state); a kind or a tag is a filter, on or off
    const row = (key, label, n, on, drop) => `<li class="bd-fr${on ? " on" : ""}"><button type="button" class="bd-fa" data-f="${esc(key)}"${on == null ? "" : ` aria-pressed="${on}"`}${drop == null ? "" : ` data-drop="${esc(drop)}"`}>
      <span class="bd-ft">${esc(label)}</span><span class="bd-fn">${esc(bookCount(n))}</span></button></li>`;
    const section = (label, rows, none) => `<section class="bd-sec"><h2 class="label">${label}</h2>${rows.length ? `<ul class="bd-fl">${rows.join("")}</ul>` : `<p class="bd-snone">${none}</p>`}</section>`;
    let lists = "";
    if (b) {
      const frames = C.readingOrder(b.frames || []).map(fr => row(`frame:${fr.id}`, fr.title || "Frame", b.items.filter(i => i.pos && i.pos.frame === fr.id).length, null, fr.id));
      const kinds = Object.keys(b.kinds || {}).filter(k => b.kinds[k] > 0).sort((x, y) => kindRank(x) - kindRank(y))
        .map(k => row(`kind:${k}`, kindName(k) + "s", b.kinds[k], f.kind === k));
      const tags = Object.keys(b.tags || {}).sort(byName).map(t => row(`tag:${t}`, t, b.tags[t], f.tag === t));
      lists = `<nav class="bd-filters" aria-label="Frames, kinds and tags">${section("Frames", frames, "No frames yet.")}${section("Kinds", kinds, "Nothing on this board yet.")}${section("Tags", tags, "No tags yet.")}</nav>`;
    }
    host.innerHTML = `<div class="bd-scroll">${head}${lists}</div>`;
    $(".bd-scroll", host).scrollTop = scroll;
    if (focused) $$("[data-f]", host).find(x => x.dataset.f === focused)?.focus();
  }

  function sideClick(key) {
    const at = key.indexOf(":"), type = key.slice(0, at), value = key.slice(at + 1);
    if (type === "frame") return goToFrame(value);
    if (type === "kind") B.filter.kind = B.filter.kind === value ? null : value;
    else if (type === "tag") B.filter.tag = B.filter.tag === value ? null : value;
    paintSide(); paintView(); paintCounts();
  }

  function goToFrame(id) {
    if (B.canvas && !listShown()) return B.canvas.goToFrame(id);
    if (hitsShown()) return;
    const g = $$(".bd-list .bd-group", B.root).find(x => x.dataset.frame === id);
    if (g) g.scrollIntoView({block: "start"});
    else toast("Nothing in that frame matches.");
  }

  /* the canvas once the board has been read (until then the list says it is being read, or why it can't be), or the
     list; the matches on every board while that search is on */
  function paintView() {
    if (!B.root) return;
    const hits = hitsShown(), canvas = !hits && B.view === "canvas" && !!B.canvas && !!B.board;
    $r(".bd-canvas").hidden = !canvas;
    $r(".bd-lhost").hidden = canvas;
    $r(".bd-zoom").hidden = !canvas;
    if (canvas) B.canvas.render(B.board, B.filter);
    else if (hits) paintResults();
    else paintList();
  }
  const canvasShown = () => !!B.root && !!B.canvas && !$r(".bd-canvas").hidden;

  /* The canvas (board-canvas.js), with what it asks of the page; and the status bar's Fit, −, the zoom, + */
  function makeCanvas() {
    if (typeof BoardCanvas === "undefined") return;
    B.canvas = BoardCanvas.create($r(".bd-canvas"), {
      key: B.id == null ? "_shared" : B.id,
      quotes: () => B.book && typeof bookStyleSheet === "function" ? bookStyleSheet(B.book).quotes : "“…”",
      titleOf, sourceOf, kindName,
      open: id => open(id),
      menu: (e, ids) => menu(e, ids),
      trash: ids => askTrash(ids),
      selection: (ids, cursor) => { select(ids, {cursor: cursor ?? undefined, canvas: false}); if (cursor) B.anchor = cursor; },
      moved: (items, frames) => place(items, frames),
      frames: change => setFrames(change),
      add: (kind, at, frame) => add(kind, at, frame),
      clip: (url, at, frame) => clip(url, at, {frame}),
      files: (files, at, frame) => addFiles(files, at, frame),
      text: (words, at, frame) => addText(words, at, frame),
      zoomed: paintZoom,
    });
    const z = $r(".bd-zoom");
    z.innerHTML = `<button type="button" class="bw-tog" data-z="fit" title="Everything in view · Ctrl+0">Fit</button>
      <button type="button" class="bw-tog bd-zs" data-z="out" aria-label="Zoom out" title="Zoom out · −">−</button>
      <button type="button" class="bw-tog bd-zp" data-z="one" title="Zoom to 100% · Ctrl+1">100%</button>
      <button type="button" class="bw-tog bd-zs" data-z="in" aria-label="Zoom in" title="Zoom in · +">+</button>`;
    z.onclick = e => {
      const b = e.target.closest("[data-z]"), c = B.canvas;
      if (!b || !c) return;
      const how = b.dataset.z;
      if (how === "fit") c.fit();
      else if (how === "one") c.zoomTo(1);
      else c.zoomTo(BoardCanvas.zoomStep(c.zoom, how === "in" ? 1 : -1));
    };
  }
  function paintZoom(zoom) {
    const el = $r(".bd-zp");
    if (el) el.textContent = `${Math.round(zoom * 100)}%`;
  }

  function paintCounts() {
    const el = $r(".bd-counts"), b = B.board;
    if (!el) return;
    if (hitsShown() && B.results) {
      const boards = new Set(B.results.map(x => x.board ?? "")).size;
      el.textContent = `${B.results.length} ${B.results.length === 1 ? "match" : "matches"} on ${plural(boards, "board")}`;
      return;
    }
    if (!b) { el.textContent = ""; return; }
    const n = b.items.length;
    const parts = [filtering() ? `${visible().length} of ${plural(n, "item")}` : plural(n, "item"), plural((b.frames || []).length, "frame")];
    el.textContent = parts.join(", ") + (B.sel.size > 1 ? ` · ${B.sel.size} selected` : "");
  }

  /* ——— the list ——— */
  function paintList() {
    const host = $r(".bd-lhost"), old = $(".bd-lscroll[data-mode=list]", host), scroll = old ? old.scrollTop : 0;
    const focus = host.contains(document.activeElement) ? document.activeElement.closest(".bd-list .bd-row")?.dataset.id : null;
    const b = B.board;
    if (!b) {
      host.innerHTML = `<div class="bd-lscroll" data-mode="list"><p class="bd-none">${B.error ? `The board couldn't be read: ${esc(plain(B.error))}.` : "Reading the board…"}</p></div>`;
      return;
    }
    const frames = b.frames || [], heads = frames.length > 0, shown = visible();
    const ids = [];
    let body;
    if (!b.items.length && !frames.length) {
      body = `<p class="bd-none">Nothing on this board yet. Add a note, a quote, a source or a web clip with <b>Add</b>.</p>`;
    } else if (b.items.length && !shown.length) {
      const why = B.filter.ids && !B.filter.kind && !B.filter.tag ? `Nothing on this board matches “${esc(B.q)}”.` : "Nothing on this board matches these filters.";
      body = `<p class="bd-none">${why} <button type="button" class="btn small quiet" data-clear>Show everything</button></p>`;
    } else {
      // sorted by the titles as shown (a source's CSL title, a piece's title), not only the title field
      const real = new Map(shown.map(i => [i.id, i]));
      const groups = C.groups(shown.map(i => ({...i, title: titleOf(i).text})), frames, B.sort)
        .map(g => ({frame: g.frame, items: g.items.map(i => real.get(i.id))}))
        .filter(g => g.items.length || (g.frame && !filtering()));
      groups.forEach(g => g.items.forEach(i => ids.push(i.id)));
      const cur = ids.includes(B.cursor) ? B.cursor : ids.find(id => B.sel.has(id)) ?? ids[0];
      const group = g => {
        const title = g.frame ? g.frame.title || "Frame" : "Not in a frame", fid = g.frame ? g.frame.id : "";
        return `<section class="bd-group${heads ? "" : " nohead"}" role="group" aria-label="${esc(title)}" data-frame="${esc(fid)}">
          ${heads ? `<div class="bd-ghead" data-drop="${esc(fid)}" aria-hidden="true"><h2 class="bd-gt">${esc(title)}</h2><span class="bd-gn">${esc(bookCount(g.items.length))}</span></div>` : ""}
          <div class="bd-rows">${g.items.length ? g.items.map(i => row(i, cur, heads)).join("") : `<p class="bd-gnone" aria-hidden="true">Nothing in this frame yet.</p>`}</div></section>`;
      };
      body = `<div class="bd-list" role="listbox" aria-multiselectable="true" aria-label="Items on the board">${groups.map(group).join("")}</div>`;
    }
    const head = `<div class="bd-lhead">${COLUMNS.map(([s, label, c, tip]) => s
      ? `<button type="button" class="bd-h bd-sort ${c}" data-sort="${s}" aria-pressed="${B.sort === s}" title="${tip}">${label}</button>`
      : `<span class="bd-h ${c}">${label}</span>`).join("")}</div>`;
    host.innerHTML = `<div class="bd-lscroll" data-mode="list">${b.items.length ? head : ""}${body}</div>`;
    const sc = $(".bd-lscroll", host), lh = $(".bd-lhead", sc);
    sc.style.scrollPaddingTop = (lh ? Math.ceil(lh.getBoundingClientRect().height) + 8 : 0) + "px";     // rows the keys go to stay clear of the column heads
    sc.scrollTop = scroll;
    if (focus) rowEl(focus)?.focus({preventScroll: true});
  }

  /* A row: the kind, what the item is called (titleOf), its source, the tags, the date added. A link shows its
     original, with where that is. The text itself is only the tooltip when the row shows its first words. */
  function row(i, cur, drag) {
    const on = B.sel.has(i.id), name = titleOf(i);
    const via = i.link && !i.link.missing ? `<span class="bd-via">From ${esc(i.link.board == null ? "the shared board" : i.link.board_title)}</span>` : "";
    const tip = i.error || (name.own ? "" : firstWords(i));
    return `<div class="bd-row${on ? " on" : ""}${name.own ? "" : " untitled"}" role="option" aria-selected="${on}" tabindex="${i.id === cur ? 0 : -1}" data-id="${esc(i.id)}"${drag ? ' draggable="true"' : ""}${tip ? ` title="${esc(tip)}"` : ""}>
      <span class="bd-c-kind">${esc(kindName(i.type))}</span><span class="bd-c-title"><span class="bd-t">${esc(name.text)}</span>${via}</span>
      <span class="bd-c-src">${sourceOf(i)}</span><span class="bd-c-tags">${esc((i.tags || []).join(", "))}</span><span class="bd-c-date">${esc(day(i.created))}</span></div>`;
  }

  const rowEl = id => id == null ? null : $$(".bd-list .bd-row", B.root).find(r => r.dataset.id === id) || null;
  const rowIds = () => $$(".bd-list .bd-row", B.root).map(r => r.dataset.id);
  /* the selection in the list's order (then any the list doesn't show) */
  const selectedIds = () => { const order = rowIds(); return [...order.filter(id => B.sel.has(id)), ...[...B.sel].filter(id => !order.includes(id))]; };

  function paintSel() {
    if (!B.root) return;
    const rows = $$(".bd-list .bd-row", B.root), ids = rows.map(r => r.dataset.id);
    const cur = ids.includes(B.cursor) ? B.cursor : ids.find(id => B.sel.has(id)) ?? ids[0];
    for (const r of rows) {
      const on = B.sel.has(r.dataset.id);
      r.classList.toggle("on", on);
      r.setAttribute("aria-selected", String(on));
      r.tabIndex = r.dataset.id === cur ? 0 : -1;
    }
    paintCounts();
  }

  /* Selects these items (and nothing else). `cursor`: the one the keys go on from; `canvas: false` when the canvas
     itself says what is selected. */
  function select(ids, {cursor, canvas = true} = {}) {
    B.sel = new Set(ids);
    if (cursor !== undefined) B.cursor = cursor;
    else if (!B.sel.has(B.cursor)) B.cursor = ids.length ? ids[ids.length - 1] : null;
    paintSel();
    if (canvas && B.canvas) B.canvas.select([...B.sel]);
  }

  function clickRow(e, id) {
    const ids = rowIds(), mod = e.ctrlKey || e.metaKey;
    if (e.shiftKey && B.anchor && ids.includes(B.anchor)) {
      const a = ids.indexOf(B.anchor), z = ids.indexOf(id), range = ids.slice(Math.min(a, z), Math.max(a, z) + 1);
      select(mod ? [...new Set([...B.sel, ...range])] : range, {cursor: id});
    } else if (mod) {
      const s = new Set(B.sel);
      if (s.has(id)) s.delete(id); else s.add(id);
      select([...s], {cursor: id});
      B.anchor = id;
    } else {
      select([id], {cursor: id});
      B.anchor = id;
    }
  }

  /* the keys in the list: up and down (Shift: the range from where it started), Home and End */
  function step(d, extend) {
    const hits = hitsShown(), rows = $$(hits ? ".bd-hits .bd-row" : ".bd-list .bd-row", B.root);
    if (!rows.length) return;
    const k = hits ? rows.indexOf(document.activeElement && document.activeElement.closest(".bd-row")) : rows.findIndex(r => r.dataset.id === B.cursor);
    const n = d === Infinity ? rows.length - 1 : d === -Infinity ? 0 : k < 0 ? (d > 0 ? 0 : rows.length - 1) : Math.max(0, Math.min(rows.length - 1, k + d));
    const r = rows[n];
    if (!hits) {
      const ids = rows.map(x => x.dataset.id), id = ids[n];
      if (extend && B.anchor && ids.includes(B.anchor)) {
        const a = ids.indexOf(B.anchor);
        select(ids.slice(Math.min(a, n), Math.max(a, n) + 1), {cursor: id});
      } else { select([id], {cursor: id}); B.anchor = id; }
    }
    r.focus({preventScroll: true});
    r.scrollIntoView({block: "nearest"});
  }

  /* An item shown and opened: the filters that hide it go, it is selected and scrolled to. */
  function reveal(id) {
    const it = item(id);
    if (!it) { toast("That item is no longer on this board."); return; }
    if (!C.matches(it, B.filter)) { B.filter = {kind: null, tag: null, ids: null}; clearSearch(true); paintSide(); paintView(); }
    select([id], {cursor: id});
    B.anchor = id;
    const r = rowEl(id);
    if (r && listShown()) { r.scrollIntoView({block: "nearest"}); r.focus({preventScroll: true}); }
    else if (canvasShown()) B.canvas.show(id);
    B.open(id);
  }

  /* ——— search ——— */
  async function runSearch() {
    clearTimeout(B.searchTimer);
    const q = B.q, every = B.every, my = ++B.searchToken, root = B.root;
    if (!root) return;
    if (q.length < 2) {            // the server finds nothing under two characters: no search, everything shows
      const had = B.filter.ids || B.results;
      B.filter.ids = null; B.results = null;
      if (had) { paintView(); paintCounts(); }
      return;
    }
    if (every && !B.results) paintView();       // "Searching every board…"
    try {
      const r = await api(path("/api/research/search", `q=${encodeURIComponent(q)}${every ? "&every=1" : ""}`));
      if (my !== B.searchToken || B.root !== root) return;
      if (every) { B.results = r; B.filter.ids = null; }
      else { B.filter.ids = new Set(r.map(x => x.id)); B.results = null; }
      paintView(); paintCounts();
    } catch (e) {
      if (my !== B.searchToken || B.root !== root) return;
      if (busy(e) || !e.status) { B.searchTimer = setTimeout(runSearch, POLL); return; }      // asked again
      toast(e.message, true);
    }
  }

  function clearSearch(quiet) {
    B.q = ""; B.every = false; B.results = null; B.filter.ids = null; B.searchToken++;
    clearTimeout(B.searchTimer);
    const q = $r(".bd-q"), ev = $r(".bd-every");
    if (q) q.value = "";
    if (ev) ev.checked = false;
    if (!quiet) { paintView(); paintCounts(); }
  }

  /* text with the search's words lit (as typed, ignoring case) */
  function lit(text, q) {
    const s = String(text || ""), k = q ? s.toLowerCase().indexOf(q.toLowerCase()) : -1;
    return k < 0 ? esc(s) : `${esc(s.slice(0, k))}<mark>${esc(s.slice(k, k + q.length))}</mark>${esc(s.slice(k + q.length))}`;
  }

  /* Every board: the matches grouped by board, each opening on its own board. */
  function paintResults() {
    const host = $r(".bd-lhost"), r = B.results;
    // the same search drawn again (the board changed): its place and the focused match stay
    const old = $(".bd-lscroll[data-mode=hits]", host), again = !!old && old.dataset.q === B.q;
    const scroll = again ? old.scrollTop : 0, at = again && host.contains(document.activeElement) ? document.activeElement.closest(".bd-hit") : null;
    const focus = at ? `${at.dataset.board}\n${at.dataset.id}` : null;
    let body;
    if (!r) body = `<p class="bd-none">Searching every board…</p>`;
    else if (!r.length) body = `<p class="bd-none">Nothing on any board matches “${esc(B.q)}”.</p>`;
    else {
      const by = new Map();
      for (const x of r) {
        const k = x.board ?? "";
        if (!by.has(k)) by.set(k, {title: x.board_title || (x.board ? x.board : "Shared board"), here: same(x.board, B.id), items: []});
        by.get(k).items.push(x);
      }
      let first = true;
      // a match here is called as its row is (titleOf); one elsewhere by the server's title, else its snippet; the
      // snippet is the second line whenever it says more than the title
      const hit = (x, k) => {
        const tab = first ? 0 : -1, here = same(x.board, B.id) && item(x.id);
        const name = here ? titleOf(here) : text(x.title) ? {text: text(x.title), own: !x.untitled} : {text: text(x.snippet) || kindName(x.type), own: false};
        const snip = text(x.snippet) && text(x.snippet) !== name.text ? x.snippet : "";
        first = false;
        return `<div class="bd-row bd-hit${name.own ? "" : " untitled"}" role="option" aria-selected="false" tabindex="${tab}" data-board="${esc(k)}" data-id="${esc(x.id)}">
          <span class="bd-c-kind">${esc(kindName(x.type))}</span><span class="bd-c-hit"><span class="bd-t">${lit(name.text, B.q)}</span>${snip ? `<span class="bd-snip">${lit(snip, B.q)}</span>` : ""}</span></div>`;
      };
      body = `<div class="bd-hits" role="listbox" aria-label="Matches on every board">${[...by.entries()].map(([k, g]) => `<section class="bd-group" role="group" aria-label="${esc(g.title)}">
        <div class="bd-ghead" aria-hidden="true"><h2 class="bd-gt">${esc(g.title)}${g.here ? `<span class="bd-gsub">This board</span>` : ""}</h2><span class="bd-gn">${esc(bookCount(g.items.length))}</span></div>
        <div class="bd-rows">${g.items.map(x => hit(x, k)).join("")}</div></section>`).join("")}</div>`;
    }
    host.innerHTML = `<div class="bd-lscroll" data-mode="hits" data-q="${esc(B.q)}">${body}</div>`;
    $(".bd-lscroll", host).scrollTop = scroll;
    if (focus) $$(".bd-hit", host).find(x => `${x.dataset.board}\n${x.dataset.id}` === focus)?.focus({preventScroll: true});
  }

  /* A match opens on its board: the search is put away, the board is read if it is another one, the item opened. */
  function openHit(board, id) {
    B.hush = performance.now() + 450;          // the rest of a double click doesn't land on the list drawn under it
    clearSearch(true);
    if (same(board, B.id)) { paintView(); paintCounts(); reveal(id); return; }
    goTo = {board, id, hash: C.boardHash(board), until: performance.now() + GOTO_MS};
    location.hash = goTo.hash;
  }
  /* An item opened on its board from elsewhere (the writing window's Board panel): the board's page, then the item. */
  function goToItem(board, id) {
    if (B.root && B.board && same(board, B.id)) { reveal(id); return; }
    goTo = {board: board || null, id, hash: C.boardHash(board), until: performance.now() + GOTO_MS};
    location.hash = goTo.hash;
  }

  /* ——— moving rows into a frame (dragged onto a group's head, or a frame in the sidebar) ———
     Into a frame: below its cards, at its left, the frame growing to hold them. Out of the frames: a column right of
     everything, as the server places new things. Positions go through POST /api/research/layout. */
  function intoFrame(ids, fid) {
    const b = B.board;
    if (!b) return;
    const frames = b.frames || [], known = new Set(frames.map(f => f.id)), frame = fid ? frames.find(f => f.id === fid) : null;
    if (fid && !frame) return;
    const moving = ids.map(item).filter(i => i && (frame ? !(i.pos && i.pos.frame === fid) : i.pos && known.has(i.pos.frame)));
    if (!moving.length) return;
    const out = {};
    let grow = null;
    if (frame) {
      const stay = b.items.filter(i => i.pos && i.pos.frame === fid && !ids.includes(i.id)).map(C.cardBox);
      let y = Math.max(frame.y + FRAME_HEAD, ...stay.map(c => c.y + c.h + GAP)), w = frame.w;
      for (const i of moving) {
        const c = C.cardBox(i);
        out[i.id] = {x: frame.x + FRAME_PAD, y, frame: fid};
        y += c.h + GAP;
        w = Math.max(w, c.w + 2 * FRAME_PAD);
      }
      const h = y - GAP + FRAME_PAD - frame.y;
      if (w > frame.w || h > frame.h) grow = [{id: fid, w: Math.max(w, frame.w), h: Math.max(h, frame.h)}];
    } else {
      const boxes = [...b.items.filter(i => !ids.includes(i.id)).map(C.cardBox), ...frames];
      const x = boxes.length ? Math.max(...boxes.map(r => r.x + r.w)) + COLUMN_GAP : 0;
      let y = boxes.length ? Math.min(...boxes.map(r => r.y)) : 0;
      for (const i of moving) { out[i.id] = {x, y, frame: null}; y += C.cardBox(i).h + GAP; }
    }
    const what = moving.length === 1 ? `“${nameOf(moving[0])}”` : `${moving.length} items`;
    place(out, grow).then(ok => {
      if (ok) toast(frame ? `Moved ${what} into ${frame.title || "the frame"}` : `Moved ${what} out of ${moving.length === 1 ? "its frame" : "their frames"}`);
    });
  }

  /* Positions (and frames) written, and recorded for undo; the board that comes back is shown and returned (null when
     it failed). */
  function place(items, frames) { return changeLayout({items, frames}); }

  function dragStart(e) {
    const r = e.target.closest && e.target.closest(".bd-list .bd-row");
    if (!r) return;
    const id = r.dataset.id;
    if (!B.sel.has(id)) { select([id], {cursor: id}); B.anchor = id; }
    const ids = selectedIds();
    B.drag = {ids};
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", ids.map(x => nameOf(item(x))).join("\n"));
    requestAnimationFrame(() => B.drag && $$(".bd-list .bd-row", B.root).forEach(x => x.classList.toggle("dragging", B.drag.ids.includes(x.dataset.id))));
  }
  function dragOver(e) {
    if (!B.drag) return;
    const t = e.target.closest && e.target.closest("[data-drop]");
    $$("[data-drop].drop", B.root).forEach(x => { if (x !== t) x.classList.remove("drop"); });
    if (!t) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    t.classList.add("drop");
  }
  function drop(e) {
    if (!B.drag) return;
    const t = e.target.closest && e.target.closest("[data-drop]"), ids = B.drag.ids;
    endDrag();
    if (!t) return;
    e.preventDefault();
    intoFrame(ids, t.dataset.drop || null);
  }
  function endDrag() {
    B.drag = null;
    if (B.root) $$(".dragging, [data-drop].drop", B.root).forEach(x => x.classList.remove("dragging", "drop"));
  }

  /* ——— the controls ——— */
  function setView(v) {
    if (v !== "canvas" && v !== "list") return;
    B.view = v;
    pref.set("boardView", v);
    paintTools(); paintView();
  }
  function setSort(s) {
    if (!SORTS.includes(s) || s === B.sort) return;
    const had = document.activeElement && document.activeElement.closest(".bd-lhead");
    B.sort = s;
    pref.set("boardSort", s);
    paintList();
    if (had) $r(`.bd-lhead [data-sort="${s}"]`)?.focus();
  }
  function toggleSide() {
    if (!B.root) return;
    const hide = !B.root.classList.contains("noside");
    B.root.classList.toggle("noside", hide);
    $r(".bd-tog").setAttribute("aria-pressed", String(!hide));
    pref.set("boardSide", hide ? "0" : "1");
  }
  function focusSearch() { const q = $r(".bd-q"); if (q) { q.focus(); q.select(); } }
  function showEverything() { B.filter = {kind: null, tag: null, ids: null}; clearSearch(true); paintSide(); paintView(); paintCounts(); }

  function wire() {
    const r = B.root, q = $r(".bd-q");
    $r(".bd-tog").onclick = toggleSide;
    $r(".bd-views").onclick = e => { const b = e.target.closest("[data-view]"); if (b) setView(b.dataset.view); };
    q.addEventListener("input", () => {
      B.q = q.value.trim();
      clearTimeout(B.searchTimer);
      B.searchTimer = setTimeout(runSearch, SEARCH_AFTER);
    });
    $r(".bd-every").onchange = e => {
      B.every = e.target.checked; B.results = null;
      paintView(); paintCounts();
      if (B.q.length >= 2) runSearch();
    };
    $r(".bd-add").onclick = e => B.addMenu(e.currentTarget);
    $r(".bd-side").addEventListener("click", e => { const f = e.target.closest("[data-f]"); if (f) sideClick(f.dataset.f); });
    const list = $r(".bd-lhost");
    list.addEventListener("mousedown", e => { if (e.shiftKey && e.target.closest(".bd-list .bd-row")) e.preventDefault(); });     // no text selection on Shift-click
    list.addEventListener("click", e => {
      if (performance.now() < B.hush) return;
      const s = e.target.closest("[data-sort]");
      if (s) return setSort(s.dataset.sort);
      if (e.target.closest("[data-clear]")) return showEverything();
      const hit = e.target.closest(".bd-hit");
      if (hit) return openHit(hit.dataset.board || null, hit.dataset.id);
      const row = e.target.closest(".bd-list .bd-row");
      if (row) return clickRow(e, row.dataset.id);
      if (!e.shiftKey && !e.ctrlKey && !e.metaKey && e.target.closest(".bd-lscroll") && !e.target.closest("button, a")) select([]);
    });
    list.addEventListener("dblclick", e => {
      if (performance.now() < B.hush) return;
      const row = e.target.closest(".bd-list .bd-row");
      if (row) B.open(row.dataset.id);
    });
    list.addEventListener("contextmenu", e => {
      const row = e.target.closest(".bd-list .bd-row");
      if (!row) return;
      const id = row.dataset.id;
      if (!B.sel.has(id)) { select([id], {cursor: id}); B.anchor = id; }
      B.menu(e, selectedIds());
    });
    r.addEventListener("dragstart", dragStart);
    r.addEventListener("dragover", dragOver);
    r.addEventListener("drop", drop);
    r.addEventListener("dragend", endDrag);
  }

  /* ——— keys ———
     Ctrl+\ the sidebar; / or Ctrl+F the search; Escape clears the search, then the selection. In the list: up and down
     (Shift extends), Home and End, Ctrl+A, Enter opens, Delete to the trash, the context-menu key or Shift+F10 the
     menu. In the item panel, Escape closes it (the panel's own listener). In both views, outside a text field: Ctrl+Z
     undoes the board's last action, Ctrl+Shift+Z or Ctrl+Y does it again. The canvas's own keys: board-canvas.js. */
  addEventListener("keydown", e => {
    if (!B.root || e.defaultPrevented || e.isComposing || $("#dlg").open) return;
    const mod = e.ctrlKey || e.metaKey, k = e.key, t = e.target;
    const field = t instanceof Element && (t.matches("input, textarea, select") || t.isContentEditable);
    const search = t === $r(".bd-q");
    if (mod && !e.altKey && k === "\\") { e.preventDefault(); toggleSide(); return; }
    if (mod && !e.altKey && !e.shiftKey && k.toLowerCase() === "f") { e.preventDefault(); focusSearch(); return; }
    if (k === "Escape") {
      if (field && !search) return;                 // the item panel's fields keep their own Escape
      if (B.q || $r(".bd-q").value) { e.preventDefault(); clearSearch(); }
      else if (search) { e.preventDefault(); t.blur(); }
      else if (B.sel.size) { e.preventDefault(); select([]); }
      return;
    }
    if (field) return;
    if (mod && !e.altKey && (k.toLowerCase() === "z" || (k.toLowerCase() === "y" && !e.shiftKey))) {
      e.preventDefault();
      undoStep(k.toLowerCase() === "z" && !e.shiftKey);
      return;
    }
    if (k === "/" && !mod && !e.altKey) { e.preventDefault(); focusSearch(); return; }
    if (!listShown() || !(t === document.body || t === app || $r(".bd-lhost").contains(t))) return;     // the canvas has its own keys
    if (t.closest && t.closest("button, a")) return;          // a column head or Show everything keeps its own keys
    if (k === "ArrowDown" || k === "ArrowUp") { e.preventDefault(); step(k === "ArrowDown" ? 1 : -1, e.shiftKey); }
    else if (k === "Home" || k === "End") { e.preventDefault(); step(k === "End" ? Infinity : -Infinity, e.shiftKey); }
    else if (k === "Enter") {
      const hit = t.closest && t.closest(".bd-hit");
      if (hit) { e.preventDefault(); openHit(hit.dataset.board || null, hit.dataset.id); }
      else if (B.cursor && B.sel.has(B.cursor) && !hitsShown()) { e.preventDefault(); B.open(B.cursor); }
    } else if (mod && !e.altKey && k.toLowerCase() === "a" && !hitsShown()) { e.preventDefault(); select(rowIds()); }
    else if (k === "Delete" && !mod && !e.altKey && !hitsShown() && B.sel.size) { e.preventDefault(); B.askTrash(selectedIds()); }
    else if ((k === "ContextMenu" || (e.shiftKey && k === "F10")) && !hitsShown()) {
      const r = rowEl(B.cursor);
      if (!r || !B.sel.has(B.cursor)) return;
      e.preventDefault();
      const box = r.getBoundingClientRect();
      B.menu({clientX: box.left + 24, clientY: box.bottom, preventDefault() {}, stopPropagation() {}}, selectedIds());
    }
  });

  /* ——— changing the board ———
     Every change to the board goes through one of these. Each returns what the server returned (null when it failed,
     after saying why in a toast) and shows the board as it is after it. The …Now ones only write; the others also
     record the change for undo (below). */

  /* Positions and frames (POST /api/research/layout): items {id: {x, y, w?, h?, z?, frame?}}, frames added or changed
     by id, remove_frames. The board. */
  async function layoutNow({items, frames, remove_frames} = {}) {
    const root = B.root;
    if (!root) return null;
    try {
      const board = await api("/api/research/layout", {b: B.id, ...(items ? {items} : {}), ...(frames ? {frames} : {}), ...(remove_frames ? {remove_frames} : {})});
      if (B.root === root) apply(board);
      return board;
    } catch (e) {
      if (B.root === root) failed(e);
      return null;
    }
  }
  /* Frames added, changed (by id) or removed: the board. */
  function setFrames({frames, remove_frames} = {}) { return changeLayout({frames, remove_frames}); }

  /* An item added (POST /api/research/item): the item in full. */
  function addItem(fields, at, frame) { return added(addItemNow(fields, at, frame)); }
  async function addItemNow(fields, at, frame) {
    const root = B.root;
    if (!root) return null;
    try {
      const it = await api("/api/research/item", {b: B.id, fields, ...(at ? {at} : {}), ...(frame ? {frame} : {})});
      if (B.root === root) await read();
      return it;
    } catch (e) {
      if (B.root === root) failed(e);
      return null;
    }
  }
  /* An image added from its bytes (base64): the item in full. */
  function addImage(name, data, at, frame) { return added(addImageNow(name, data, at, frame)); }
  async function addImageNow(name, data, at, frame) {
    const root = B.root;
    if (!root) return null;
    try {
      const it = await api("/api/research/image", {b: B.id, name, data, ...(at ? {at} : {}), ...(frame ? {frame} : {})});
      if (B.root === root) await read();
      return it;
    } catch (e) {
      if (B.root === root) failed(e);
      return null;
    }
  }
  /* Items to the board's .trash: {trash: [file names]}, the names restore() takes, in the order of the ids. Whatever
     was typed in them is saved first; an open one closes. */
  async function trash(ids) {
    const root = B.root, uniq = [...new Set(ids || [])];
    const st = uniq.map(item).filter(Boolean).map(it => ({id: it.id, type: it.type, name: named(it), pos: posOf(it), trashed: null}));
    const r = await trashNow(uniq);
    if (r && B.root === root && st.length === uniq.length && sameLength(r.trash, st)) remember(trashStep(st, r.trash));
    return r;
  }
  async function trashNow(ids) {
    const root = B.root;
    if (!root || !ids.length) return null;
    await settle(ids);
    try {
      const r = await api("/api/research/delete", {b: B.id, ids});
      if (B.root === root) { if (P && ids.includes(P.id)) leftBoard(P); await read(); }
      return r;
    } catch (e) {
      if (B.root === root) failed(e);
      return null;
    }
  }
  /* Items back from the trash: {items}, in the order of the names (new ids when theirs were taken meanwhile). */
  async function restoreNow(names) {
    const root = B.root;
    if (!root || !names.length) return null;
    try {
      const r = await api("/api/research/restore", {b: B.id, names});
      if (B.root === root) await read();
      return r;
    } catch (e) {
      if (B.root === root) failed(e);
      return null;
    }
  }
  /* Items moved to another board (`to`: a book's id, or null for the shared board), or with `link` linked there:
     {items} as they are on that board, in the order asked, each with `warnings` when a board kept its links as they
     were. A move (not a link) is recorded for undo. */
  async function moveTo(ids, to, link = false) {
    if (link) return moveNow(ids, to, true);
    const root = B.root, uniq = [...new Set(ids || [])], where = boardTitle(to);
    const st = uniq.map(item).filter(Boolean).map(it => ({id: it.id, type: it.type, name: named(it), pos: posOf(it), link: !!it.link, there: null, back: true}));
    const r = await moveNow(uniq, to);
    if (r && B.root === root && st.length === uniq.length && sameLength(r.items, st)) remember(moveStep(st, r.items, to ?? null, where));
    return r;
  }
  /* `from`: the board they are on, when it isn't this one (an undo moving them back here) */
  async function moveNow(ids, to, link = false, from = undefined) {
    const root = B.root, here = from === undefined;
    if (!root || !ids.length) return null;
    if (here) await settle(ids);
    try {
      const r = await api("/api/research/move", {b: here ? B.id : from, ids, to: to ?? null, ...(link ? {link: true} : {})});
      if (B.root === root) { if (here && !link && P && ids.includes(P.id)) leftBoard(P); await read(); }
      boards = null;                  // their counts changed
      return r;
    } catch (e) {
      if (B.root === root) failed(e);
      return null;
    }
  }

  /* ——— undo ———
     The board's own changes in this window, the last 50 (a BoardCanvas.Undo, kept while the page is open and shared
     by the list and the canvas): moves and resizes, frames (added, moved, resized, renamed, deleted), items added
     (undone to the trash), items trashed (brought back from it, then put where they were), items moved to another
     board (moved back, then put where they were). Each step's undo() and redo() call the writes above that don't
     record, and resolve to the toast saying what was done, or to null when a write failed (it said why); a failed step
     is dropped. Typing in the item panel has its field's own undo. */
  const UNDO_MAX = 50;
  let U = null;
  const remember = step => { if (U) U.push(step); };
  const sameLength = (list, st) => Array.isArray(list) && list.length === st.length;
  /* where an item is, as the layout write takes it back */
  const posOf = it => it && it.pos ? {x: it.pos.x, y: it.pos.y, w: it.pos.w, h: it.pos.h ?? null, z: it.pos.z ?? 0, frame: it.pos.frame ?? null} : null;
  /* an item as a toast names it: “its title or first words”, else "the note" */
  function named(it) {
    if (!it) return "the item";
    const t = titleOf(it);
    return t.own || firstWords(it) ? `“${nameOf(it)}”` : `the ${kindName(it.type).toLowerCase()}`;
  }
  /* the items of a step: one by its name (as it is now, when it is on this board), several by their kind or as items */
  function whatOf(st) {
    if (st.length === 1) { const it = item(st[0].id); if (it) st[0].name = named(it); return st[0].name || "the item"; }
    return `${st.length} ${new Set(st.map(s => s.type)).size === 1 ? kindName(st[0].type).toLowerCase() + "s" : "items"}`;
  }
  const boardTitle = b => b == null ? "the shared board" : ((boards || []).find(x => same(x.board, b)) || {}).title || b;
  function stray() {
    toast("The board changed meanwhile, so that step can't be taken back.", true);
    return null;
  }
  /* a step whose items and frames are all gone from the board: said, and dropped */
  function goneNow(back) {
    toast(back ? "Nothing to undo there any more." : "Nothing to redo there any more.");
    return null;
  }
  /* Ids an undo gave items anew (restore and moving back give `-2` … when the old id was taken meanwhile): old → new,
     so the steps recorded before still find them. */
  const renamed = new Map();
  const follow = id => { let x = id; for (let n = 0; renamed.has(x) && n < UNDO_MAX; n++) x = renamed.get(x); return x; };
  /* the step's items given the ids they have now */
  const now = st => { for (const s of st) s.id = follow(s.id); return st; };
  /* the ids a write gave the step's items here, in order, remembered when they changed */
  const reid = (st, list) => list.forEach((x, i) => { if (st[i].id !== x.id) renamed.set(st[i].id, x.id); st[i].id = x.id; });

  async function undoStep(back) {
    if (!U || !B.root || U.busy) return;
    const r = back ? await U.undo() : await U.redo();
    if (!B.root) return;
    if (!r) { toast(back ? "There is nothing to undo on this board." : "There is nothing to redo on this board."); return; }
    if (r.said) toast(r.said);
  }

  /* items put back where they were; a frame that is gone meanwhile is none */
  function placeBack(st) {
    const known = new Set(((B.board && B.board.frames) || []).map(f => f.id)), items = {};
    for (const s of st) if (s.pos && item(s.id)) items[s.id] = {...s.pos, frame: s.pos.frame && known.has(s.pos.frame) ? s.pos.frame : null};
    return Object.keys(items).length ? layoutNow({items}) : Promise.resolve(B.board);
  }

  /* Items added: undone to the trash (where they were is kept), redone back from it. */
  async function added(p) {
    const root = B.root, it = await p;
    if (it && typeof it.id === "string" && B.root === root) remember(addStep([it]));
    return it;
  }
  function addStep(list) {
    const st = list.map(it => ({id: it.id, type: it.type, name: null, pos: null, trashed: null}));
    return {
      label: `Added ${whatOf(st)}`,
      async undo() {
        for (const s of now(st)) { const it = item(s.id); if (it) s.pos = posOf(it); }
        const what = whatOf(st), r = await trashNow(st.map(s => s.id));
        if (!r) return null;
        if (!sameLength(r.trash, st)) return stray();
        r.trash.forEach((n, i) => { st[i].trashed = n; });
        return `Moved ${what} to the trash`;
      },
      async redo() {
        const r = await restoreNow(st.map(s => s.trashed));
        if (!r) return null;
        if (!sameLength(r.items, st)) return stray();
        reid(st, r.items);
        await placeBack(st);
        return `Brought ${whatOf(st)} back from the trash`;
      },
    };
  }

  /* Items trashed: undone from the trash (restore, by the names delete gave) and put where they were. */
  function trashStep(st, names) {
    names.forEach((n, i) => { st[i].trashed = n; });
    return {
      label: `Moved ${whatOf(st)} to the trash`,
      async undo() {
        const r = await restoreNow(st.map(s => s.trashed));
        if (!r) return null;
        if (!sameLength(r.items, st)) return stray();
        reid(st, r.items);
        await placeBack(st);
        return `Brought ${whatOf(st)} back from the trash`;
      },
      async redo() {
        for (const s of now(st)) { const it = item(s.id); if (it) s.pos = posOf(it); }
        const what = whatOf(st), r = await trashNow(st.map(s => s.id));
        if (!r) return null;
        if (!sameLength(r.trash, st)) return stray();
        r.trash.forEach((n, i) => { st[i].trashed = n; });
        return `Moved ${what} to the trash again`;
      },
    };
  }

  /* Items moved to another board: undone by moving them back (by their ids there) and putting them where they were. A
     link taken to the board of its original is that original there now: it stays. */
  function moveStep(st, there, to, where) {
    st.forEach((s, i) => { s.there = there[i].id; s.back = !!there[i].link === s.link; });
    const what = list => list.length === 1 ? list[0].name : `${list.length} items`;
    return {
      label: `Moved ${what(st)} to ${where}`,
      async undo() {
        const go = st.filter(s => s.back);
        if (!go.length) { toast(`That can't be moved back: on ${where} it is the original now.`, true); return null; }
        const r = await moveNow(go.map(s => s.there), B.id, false, to);
        if (!r) return null;
        if (!sameLength(r.items, go)) return stray();
        reid(now(go), r.items);
        await placeBack(go);
        return `Moved ${what(go)} back from ${where}`;
      },
      async redo() {
        const go = now(st.filter(s => s.back));
        for (const s of go) { const it = item(s.id); if (it) { s.pos = posOf(it); s.name = named(it); } }
        const r = await moveNow(go.map(s => s.id), to);
        if (!r) return null;
        if (!sameLength(r.items, go)) return stray();
        r.items.forEach((x, i) => { go[i].there = x.id; });
        return `Moved ${what(go)} to ${where} again`;
      },
    };
  }

  /* Positions and frames: undone by writing back the earlier positions and frames (a deleted frame comes back with its
     id, and its items into it; a frame the change made goes), redone by writing the change again. */
  async function changeLayout(change) {
    const root = B.root, b = B.board;
    const frames0 = new Map(((b && b.frames) || []).map(f => [f.id, {...f}]));
    const items0 = {};
    for (const id of Object.keys(change.items || {})) { const p = posOf(item(id)); if (p) items0[id] = p; }
    const removed = (change.remove_frames || []).filter(id => frames0.has(id))
      .map(id => ({frame: frames0.get(id), members: ((b && b.items) || []).filter(i => i.pos && i.pos.frame === id).map(i => i.id)}));
    const r = await layoutNow(change);
    if (!r || B.root !== root) return r;
    const made = (r.frames || []).filter(f => !frames0.has(f.id)).map(f => ({...f}));
    const changed = (change.frames || []).filter(f => f && f.id && frames0.has(f.id)).map(f => frames0.get(f.id));
    if (Object.keys(items0).length || made.length || changed.length || removed.length) remember(layoutStep(change, items0, made, changed, removed));
    return r;
  }
  function layoutStep(change, items0, made, changed, removed) {
    const said = layoutWords(change, items0, made, changed, removed), madeIds = made.map(f => f.id);
    /* positions whose frame isn't there are in none (the write refuses a frame it doesn't have) */
    const fit = (items, also) => {
      const known = new Set([...((B.board && B.board.frames) || []).map(f => f.id), ...also]), out = {};
      for (const [id, p] of Object.entries(items || {})) out[id] = p && p.frame && !known.has(p.frame) ? {...p, frame: null} : p;
      return out;
    };
    /* the positions of the items still on the board (by the ids they have now) */
    const present = list => {
      const out = {};
      for (const [id, p] of Object.entries(list || {})) { const cur = follow(id); if (item(cur)) out[cur] = {...(out[cur] || {}), ...p}; }
      return out;
    };
    const framesHere = () => new Set(((B.board && B.board.frames) || []).map(f => f.id));
    return {
      label: said.label,
      async undo() {
        const here = framesHere(), back = {...items0};
        for (const m of removed) for (const id of m.members) back[id] = {...(back[id] || {}), frame: m.frame.id};
        const items = present(back);
        // frames changed that are still there, frames deleted that aren't back yet, frames made that are still there
        const frames = [...changed.filter(f => here.has(f.id)), ...removed.map(m => m.frame).filter(f => !here.has(f.id))];
        const gone = madeIds.filter(id => here.has(id));
        if (!Object.keys(items).length && !frames.length && !gone.length) return goneNow(true);
        const r = await layoutNow({items: fit(items, frames.map(f => f.id)), frames: frames.length ? frames : null, remove_frames: gone.length ? gone : null});
        return r ? said.undo : null;
      },
      async redo() {
        const here = framesHere(), items = present(change.items);
        const frames = [...(change.frames || []).filter(f => f && f.id && !madeIds.includes(f.id) && here.has(f.id)), ...made.filter(f => !here.has(f.id))];
        const gone = (change.remove_frames || []).filter(id => here.has(id));
        if (!Object.keys(items).length && !frames.length && !gone.length) return goneNow(false);
        const r = await layoutNow({items: fit(items, madeIds), frames: frames.length ? frames : null, remove_frames: gone.length ? gone : null});
        return r ? said.redo : null;
      },
    };
  }
  /* what a layout step is called, and what its undo and redo say */
  function layoutWords(change, items0, made, changed, removed) {
    const frameName = f => `the frame “${f.title || "Frame"}”`;
    const ids = Object.keys(items0), what = ids.length === 1 ? named(item(ids[0])) : `${ids.length} items`;
    if (removed.length) {
      const t = removed.length === 1 ? frameName(removed[0].frame) : `${removed.length} frames`;
      return {label: `Deleted ${t}`, undo: `Brought back ${t}`, redo: `Deleted ${t} again`};
    }
    if (made.length) {
      const t = made.length === 1 ? frameName(made[0]) : `${made.length} frames`;
      return {label: `Added ${t}`, undo: `Removed ${t}`, redo: `Added ${t} again`};
    }
    const ch = (change.frames || []).find(f => f && f.id && changed.some(c => c.id === f.id)), old = ch ? changed.find(c => c.id === ch.id) : null;
    if (ch && "title" in ch && ch.title !== old.title) {
      return {label: `Renamed ${frameName(old)}`, undo: `Renamed the frame back to “${old.title || "Frame"}”`, redo: `Renamed the frame to “${ch.title}” again`};
    }
    if (ch && ("x" in ch || "y" in ch)) return {label: `Moved ${frameName(old)}`, undo: `Moved ${frameName(old)} back`, redo: `Moved ${frameName(old)} again`};
    if (ids.some(id => ["x", "y", "frame"].some(k => k in change.items[id]))) return {label: `Moved ${what}`, undo: `Moved ${what} back`, redo: `Moved ${what} again`};
    if (ids.length) return {label: `Resized ${what}`, undo: `Put ${what} back to ${ids.length === 1 ? "its" : "their"} size`, redo: `Resized ${what} again`};
    if (old) return {label: `Resized ${frameName(old)}`, undo: `Put ${frameName(old)} back to its size`, redo: `Resized ${frameName(old)} again`};
    return {label: "Changed the board", undo: "Took back the change to the board", redo: "Made the change to the board again"};
  }

  /* ——— the open item (the panel on the right) ———
     One item at a time (P). Its fields save through a BoardCore.Saver: typing a second after it stops, a choice at once,
     and whatever is waiting when the panel closes, another item opens or the page is left (then with keepalive). Until
     a save goes through, the unsaved fields are kept in this browser (studio.board.<board or _shared>/<id>) and offered
     when the item opens again. A save answered 409 with the current item shows the bar (Reload / Keep mine); answered
     404, the item was deleted elsewhere: its saving stops and the text stays in the panel and in the browser. */
  const KEEP = "studio.board.";
  const MAX_IMAGE = 28000000;           // the server takes 40 MB of JSON; base64 is a third larger
  const LEAVING_MAX = 60000;            // a keepalive request carries at most 64 KB
  const FRAME_W = 640, FRAME_H = 400, TAG_MAX = 40;
  const SOURCE_TYPES = [["book", "Book"], ["article-journal", "Article"], ["chapter", "Chapter"], ["webpage", "Web page"], ["report", "Report"]];
  const CONTAINER = {"article-journal": "Journal", chapter: "Book", webpage: "Website"};
  const IMAGE_EXT = /\.(png|jpe?g|gif|webp)$/i, IMAGE_TYPE = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"};

  let P = null;                  // the open item: {id, board, root, key, item, saver, mtime, tags, tab, conflict, failed, gone, halt, rescues, invalid, closed, dead, leaving}
  const live = new Set();        // closed items whose last save hasn't gone through yet
  let boards = null;             // GET /api/research/boards, for Move to and Link on
  let pendSeq = 0;

  /* the browser's copy of unsaved fields; never throws (a private window, a full store) */
  const kept = {
    get(k) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : null; } catch { return null; } },
    put(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* the panel still has it */ } },
    drop(k) { try { localStorage.removeItem(k); } catch { /* as above */ } },
  };
  const keepKey = (board, id) => `${KEEP}${board == null ? "_shared" : board}/${id}`;
  /* Texts that weren't saved, offered with Put it back / Discard: a list of {fields, at} in a slot of their own, so
     typing (which keeps its unsaved fields in the item's slot) never writes over one. Only those two buttons take an
     entry out. */
  const rescueKey = key => key + "#rescue";
  const rescuesOf = key => { const v = kept.get(rescueKey(key)); return Array.isArray(v) ? v.filter(x => x && x.fields && typeof x.fields === "object") : []; };
  const putRescues = (key, list) => { if (list.length) kept.put(rescueKey(key), list); else kept.drop(rescueKey(key)); };
  const addRescue = (key, entry) => putRescues(key, [...rescuesOf(key), entry]);
  const itemPath = id => path("/api/research/item", "id=" + encodeURIComponent(id));
  const squash = v => String(v ?? "").replace(/\s+/g, " ").trim();
  const shortOf = csl => { try { return BookText.sourceShort(csl) || (csl && csl.id) || ""; } catch { return (csl && csl.id) || ""; } };
  const hostOf = u => { try { return new URL(/^[a-z][a-z0-9+.-]*:/i.test(u) ? u : "https://" + u).hostname.replace(/^www\./, "") || u; } catch { return u; } };
  const webUrl = u => typeof u === "string" && /^https?:\/\/\S+$/i.test(u.trim()) ? u.trim() : null;
  /* a thumbnail address (…?w=640&v=…) at another width, or at full size */
  const sized = (thumb, w) => thumb.replace(/([?&])w=\d+/, `$1w=${w}`);
  const fullSize = thumb => thumb.replace(/([?&])w=\d+&?/, "$1").replace(/[?&]$/, "");
  const wordCount = s => (String(s || "").match(/\S+/g) || []).length;
  const fieldLang = () => B.book && B.book.language ? ` lang="${esc(B.book.language)}"` : "";
  const isImage = f => IMAGE_EXT.test(f.name || "") || !!IMAGE_TYPE[f.type];
  const boardName = b => b == null ? "the shared board" : b;
  const truncate = (s, n) => s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;

  /* POST like api(), and with keepalive while the page is being left (small bodies only) */
  async function send(p, body, keepalive) {
    const json = JSON.stringify(body);
    const small = keepalive && new Blob([json]).size < LEAVING_MAX;          // bytes, not UTF-16 units
    const r = await fetch(p, {method: "POST", headers: {"Content-Type": "application/json"}, body: json, ...(small ? {keepalive: true} : {})});
    const data = await r.json().catch(() => ({error: r.statusText}));
    if (!r.ok) throw Object.assign(new Error(data.error || r.statusText), {status: r.status, data});
    return data;
  }

  /* Opens an item in the panel (the one open before is saved and closed). focus: "title", "text" or "tags". */
  async function open(id, {focus = null, force = false} = {}) {
    if (!B.root || typeof id !== "string" || !id) return;
    if (P && P.id !== id && holdsInvalid(P)) return;           // a field it can't save yet: said, and the panel stays
    if (!(B.sel.size === 1 && B.sel.has(id))) { select([id], {cursor: id}); B.anchor = id; }
    if (P && P.id === id && P.item && !force) { if (focus) focusField(focus); return; }
    if (P) { commitTag(P); release(P); }
    const root = B.root, key = keepKey(B.id, id), s = item(id);
    const p = P = {id, board: B.id, root, key, item: null, saver: null, mtime: null, tags: [], tab: null, citable: null,
      conflict: null, failed: null, gone: false, halt: false, rescues: [], invalid: null, closed: false, dead: false, leaving: false};
    hideQuote();
    B.panel.hidden = false;
    B.panel.innerHTML = `${headHtml(kindName(s && s.type), `<p class="bd-ptitle bd-ptitle-s">${esc(s ? nameOf(s) : "")}</p>`, "", false)}
      <div class="bd-pbody"><p class="bd-pnone">Reading the item…</p></div>`;
    // the same item still saving from before: that save first, so the panel opens on the saved file
    for (const q of [...live]) {
      if (q.key !== key) continue;
      live.delete(q);
      try { await q.saver.flush(); } catch { /* kept in the browser */ }
      q.dead = true;
    }
    if (P !== p) return;
    let it;
    try { it = await api(itemPath(id)); }
    catch (e) {
      if (P !== p) return;
      const why = e.status === 404 ? "This item is no longer on this board." : `The item couldn't be read: ${esc(plain(e.message))}.`;
      $(".bd-pbody", B.panel).innerHTML = `<p class="bd-pnone">${why}</p>`;
      return;
    }
    if (P !== p || B.root !== root) return;
    p.item = it; p.mtime = it.mtime;
    p.tags = Array.isArray(it.tags) ? [...it.tags] : [];
    p.tab = it.type === "clip" && !String(it.text || "").trim() && it.thumb ? "picture" : "text";
    if (!it.error && !(it.link && it.link.missing)) {
      p.saver = saverFor(p);
      // what an earlier panel kept and didn't save joins the rescues (their own slot); those the file now says too go
      const k = kept.get(key);
      let list = rescuesOf(key);
      if (k && k.fields && typeof k.fields === "object") list.push(k);
      kept.drop(key);
      list = list.filter(x => differs(x.fields, it));
      putRescues(key, list);
      p.rescues = list;
    }
    paintPanel(p, {focus});
  }

  function saverFor(p) {
    return new C.Saver({
      base: p.mtime,
      save: (fields, base, force) => saveItem(p, fields, force),
      keep: fields => kept.put(p.key, {fields, at: Date.now()}),
      drop: () => kept.drop(p.key),
      // an item that is gone, closed for good, or refused its fields (400) isn't tried again on its own
      setTimeout: (fn, ms) => p.dead || p.gone || p.halt ? null : setTimeout(fn, ms),
      clearTimeout: t => { if (t != null) clearTimeout(t); },
    });
  }

  /* The Saver's save: the fields over the file as this panel last saw it (mtime); never throws past the Saver. */
  async function saveItem(p, fields, force) {
    Promise.resolve().then(() => stateOf(p));           // "Saving…" once the Saver has noted it
    let it;
    try {
      it = await send("/api/research/update", {b: p.board, id: p.id, fields, base_mtime: p.mtime, ...(force ? {force: true} : {})}, p.leaving);
    } catch (e) {
      if (e.status === 404) { p.gone = true; p.failed = null; }
      else if (e.status === 409 && e.data && e.data.current) { p.conflict = e.data.current; p.failed = null; }
      else {
        p.failed = busy(e) ? "the board is busy" : e.status ? plain(e.message) : "Studio can't be reached";
        if (e.status === 400) p.halt = true;          // the same fields would be refused again
      }
      later(p);
      if (p.closed && (p.gone || p.conflict)) lost(p);
      else if (p.closed && p.failed && !p.told) {          // said once; the Saver keeps trying, the browser keeps the text
        p.told = true;
        toast(`${p.item ? nameOf(p.item) : p.id} couldn't be saved: ${p.failed}. Your text is kept in this window.`, true);
      }
      throw e;
    }
    p.mtime = it.mtime; p.failed = null; p.halt = false;
    p.item = it;
    later(p);
    return {...it, updated: it.mtime};
  }
  /* the bar and the save state, once the Saver has taken the answer in */
  function later(p) {
    setTimeout(() => {
      if (P === p) { paintBar(p); paintFresh(p); if (p.gone) readOnly(); }
      stateOf(p);
    }, 0);
  }
  /* a closed item whose save can't go through: said once; its text stays in the browser */
  function lost(p) {
    if (p.dead) return;
    p.dead = true; live.delete(p);
    const name = p.item ? nameOf(p.item) : p.id;
    toast(p.gone ? `“${name}” was deleted elsewhere, so your last changes to it weren't saved.`
      : `“${name}” changed outside the board, so your text wasn't saved over it. It is kept and offered when you open the item again.`, true);
  }

  /* fields typed: to the Saver (and saved at once for a choice) */
  function change(p, fields, now = false) {
    if (!p.saver || p.gone || p.dead) return;
    p.halt = false;
    p.saver.change(fields);
    stateOf(p);
    if (now) p.saver.flush().then(() => { if (B.root === p.root && !p.saver.pending()) read(); });
  }
  function stateOf(p) {
    if (!B.root || B.root !== p.root || (P !== p && P)) return;
    const s = p.saver;
    if (!s) return;
    const word = p.gone || p.conflict || p.failed || p.invalid ? "Not saved" : s.saving ? "Saving…" : s.fields ? "Unsaved changes" : "Saved";
    say(word, word === "Not saved" || word === "Unsaved changes");
  }

  /* A field the panel can't save yet (a source's accessed date that isn't a date): closing it, or opening another
     item, is refused and said, with the field focused. */
  function holdsInvalid(p) {
    if (!p || !p.invalid || p.gone || p.dead || !B.panel) return false;
    toast(`${p.invalid.message.replace(/\.$/, "")}, or clear the field. The source's other fields are saved.`, true);
    const f = $(`[data-sf=${p.invalid.field}]`, B.panel);
    if (f) { f.focus(); f.select?.(); }
    return true;
  }
  /* the page left with such a field: the source as typed is kept with the rescues, offered when it opens again */
  function keepInvalid(p) {
    if (!p.invalid || p.invalidKept === p.invalid.value) return;
    p.invalidKept = p.invalid.value;
    addRescue(p.key, {fields: {csl: p.invalid.csl}, at: Date.now()});
  }
  /* a tag typed and not yet added, added before the panel goes */
  function commitTag(p) {
    const t = P === p && B.panel && $("[data-tagin]", B.panel);
    if (t && !t.readOnly && t.value.trim()) { const v = t.value; t.value = ""; addTags(p, [v]); }
  }

  /* An item left (closed, or another opened): what is waiting is saved; a stale one is said and kept. */
  function release(p, leaving = false) {
    p.closed = true;
    if (leaving) p.leaving = true;
    if (P === p) P = null;
    if (!p.saver || p.gone || p.dead) return;
    if (p.invalid) keepInvalid(p);
    if (p.conflict) { lost(p); return; }
    if (p.saver.pending()) { live.add(p); p.saver.flush(leaving ? {leaving: true} : undefined); }
  }
  /* an item that left the board (trash, moved): nothing more is saved for it */
  function leftBoard(p) {
    p.dead = true; p.closed = true; live.delete(p);
    if (P === p) { P = null; hidePanel(); }
  }
  /* the typing in these items saved before they are moved or trashed */
  async function settle(ids) {
    for (const p of [P, ...live]) {
      if (p && same(p.board, B.id) && ids.includes(p.id) && p.saver && !p.gone && !p.dead && p.saver.pending()) {
        try { await p.saver.flush(); } catch { /* kept in the browser */ }
      }
    }
  }

  function close() {
    const p = P;
    if (!p || holdsInvalid(p)) return;
    commitTag(p);
    const had = B.panel && B.panel.contains(document.activeElement);
    release(p);
    hidePanel();
    stateOf(p);
    if (had && listShown()) rowEl(p.id)?.focus({preventScroll: true});
  }
  function hidePanel() {
    hideQuote();
    if (B.panel) { B.panel.hidden = true; B.panel.innerHTML = ""; }
  }
  /* save now: the open item and those still saving; `leaving`, with keepalive */
  function flush({leaving = false} = {}) {
    for (const p of [P, ...live]) {
      if (!p || !p.saver || p.dead || p.gone) continue;
      if (leaving) { p.leaving = true; keepInvalid(p); }
      p.saver.flush(leaving ? {leaving: true} : undefined);
    }
  }
  function pending() {
    for (const p of live) if (p.dead || p.gone || !p.saver.pending()) live.delete(p);
    return !!(P && P.invalid && !P.gone) || [P, ...live].some(p => p && p.saver && !p.dead && !p.gone && p.saver.pending());
  }

  /* the board read again: the open item follows a change made elsewhere while nothing is being typed in it, and says
     so when it left the board */
  function panelSync() {
    const p = P;
    if (!p || !p.item || !B.board || p.root !== B.root) return;
    const s = item(p.id);
    if (!s) {
      if (p.gone || (p.saver && p.saver.pending())) return;     // its save will say
      const name = nameOf(p.item);
      leftBoard(p);
      toast(`“${name}” is no longer on this board.`);
      return;
    }
    if (s.updated !== p.item.updated && !p.fetching) freshen(p);
  }
  async function freshen(p) {
    p.fetching = true;
    let it;
    try { it = await api(itemPath(p.id)); } catch { p.fetching = false; return; }
    p.fetching = false;
    if (P !== p || p.gone || p.conflict || p.invalid || (p.saver && p.saver.pending())) return;
    const a = document.activeElement;
    if (a && a.matches && a.matches("[data-tagin]") && a.value) return;      // a tag being typed: the next read tries again
    const moved = it.mtime !== p.mtime;
    p.item = it; p.mtime = it.mtime;
    if (moved) { p.tags = Array.isArray(it.tags) ? [...it.tags] : []; paintPanel(p, {keep: true}); }
    else paintFresh(p);
  }

  /* kept fields that say something else than the item now */
  function differs(fields, it) {
    const norm = v => v == null || v === "" || (Array.isArray(v) && !v.length) ? null : v;
    const key = v => JSON.stringify(v, (k, x) => x && typeof x === "object" && !Array.isArray(x)        // the same CSL in another key order
      ? Object.fromEntries(Object.keys(x).sort().map(n => [n, x[n]])) : x);
    return Object.keys(fields).some(k => key(norm(fields[k])) !== key(norm(k === "text" ? it.text : it[k])));
  }

  /* ——— the panel drawn ——— */
  function headHtml(kicker, title, sub, more) {
    return `<header class="bd-ph"><div class="bd-pk"><p class="kicker">${esc(kicker)}</p><span class="bd-pk-a">${more
      ? `<button type="button" class="bw-tog" data-act="more" aria-haspopup="menu" title="Open, move, link, copy or trash it">More</button>` : ""}
      <button type="button" class="bw-tog" data-act="close" title="Close · Escape">Close</button></span></div>${title}<p class="bd-psub">${esc(sub)}</p></header>`;
  }

  /* what the title field holds: a source's title is its CSL's; a clip's or an image's its own, else its CSL's */
  function titleValue(it) {
    const cslTitle = it.csl && typeof it.csl === "object" && typeof it.csl.title === "string" ? it.csl.title : "";
    if (it.type === "source") return cslTitle;
    if (it.type === "clip" || it.type === "image") return it.title || cslTitle;
    return it.title || "";
  }
  function subOf(it) {
    const l = it.link;
    if (l && !l.missing) return `From ${l.board == null ? "the shared board" : l.board_title || l.board}`;
    if (it.type === "note") return plural(wordCount(it.text), "word");
    if (it.type === "quote") return it.source_label || "No source yet";
    if (it.type === "source") return it.csl && it.csl.id ? `@${it.csl.id}` : "";
    if (it.type === "clip") return "";               // its details line under the head says the site
    if (it.type === "image") return typeof it.file === "string" ? it.file.split("/").pop() : "";
    if (it.type === "piece") { const pc = pieceOf(it); return pc && pc.book && !(B.book && same(B.book.id, it.book)) ? pc.book : ""; }
    return "";
  }

  /* The panel for p.item (with `view`'s fields over it: a kept text put back). keep: the focused field and its caret
     stay where they were. */
  function paintPanel(p, {focus = null, view = null, keep = false} = {}) {
    if (P !== p || !B.panel || !p.item) return;
    const el = B.panel, was = keep ? caret() : null, top = keep ? $(".bd-pbody", el)?.scrollTop || 0 : 0;
    const it = view ? {...p.item, ...view} : p.item;
    const kind = it.type, link = it.link, missing = !!(link && link.missing);
    let title, body;
    if (it.error) {
      title = `<p class="bd-ptitle bd-ptitle-s">${esc(`${p.id}.md`)}</p>`;
      body = `<p class="bd-pnone bad">${esc(it.error)}</p>`;
    } else if (missing) {
      title = `<p class="bd-ptitle bd-ptitle-s">Link</p>`;
      body = `<p class="bd-pnone">The original of this link is gone. It was ${esc(link.item || "an item")} on ${esc(link.board == null ? "the shared board" : link.board_title || link.board)}.</p>
        <div class="bd-pacts"><button type="button" class="btn small" data-act="remove-link">Remove</button></div>`;
    } else {
      const ph = kind === "source" ? "Title of the work" : kind === "piece" ? (pieceOf(it)?.title || "Add a title") : "Add a title";
      title = `<textarea class="bd-ptitle" data-f="title" rows="1" placeholder="${esc(ph)}" aria-label="Title" spellcheck="true"${fieldLang()}>${esc(titleValue(it))}</textarea>`;
      const bodies = {note: noteBody, quote: quoteBody, source: sourceBody, clip: clipBody, image: imageBody, piece: pieceBody};
      body = (link ? `<div class="bd-pacts bd-porig"><button type="button" class="btn small" data-act="original">Go to the original</button></div>` : "")
        + (bodies[kind] || noteBody)(it, p) + tagsHtml(p) + `<p class="bd-pdates" data-dates>${datesOf(it)}</p>`;
    }
    el.innerHTML = `${headHtml(missing ? "Link" : kindName(kind) + (link ? " · Link" : ""), title, missing || it.error ? "" : subOf(it), !missing)}
      <div class="bd-pbar" role="status" hidden></div>
      <div class="bd-pbody">${body}<button type="button" class="btn small bd-qbtn" data-act="quote" hidden>Quote</button></div>`;
    $$(".bd-copy a[href]", el).forEach(a => { a.target = "_blank"; a.rel = "noopener noreferrer"; });     // the system's browser
    $$("textarea", el).forEach(grow);
    paintBar(p);
    stateOf(p);
    if (p.gone) readOnly();
    if (kind === "quote" && !missing) loadCitable(p);
    if (kind === "piece" && !missing) loadPiece(p);
    $(".bd-pbody", el).scrollTop = top;
    if (was) restoreCaret(was);
    else if (focus) focusField(focus);
  }
  const datesOf = it => [it.created ? `Added ${esc(day(it.created))}` : "", it.updated ? `Changed ${esc(when(it.updated))}` : ""].filter(Boolean).join(" · ");
  /* what a save changed beside the fields: the line under the title, the dates, the quote's source label */
  function paintFresh(p) {
    if (P !== p || !B.panel || !p.item) return;
    const sub = $(".bd-psub", B.panel), d = $("[data-dates]", B.panel);
    if (sub && !(p.item.link && p.item.link.missing)) sub.textContent = p.item.type === "note" ? plural(wordCount($("[data-f=text]", B.panel)?.value), "word") : subOf(p.item);
    if (d) d.innerHTML = datesOf(p.item);
  }

  const noteBody = it => `<textarea class="bd-ptext" data-f="text" placeholder="Write the note" aria-label="The note" spellcheck="true"${fieldLang()}>${esc(it.text || "")}</textarea>`;

  function quoteBody(it, p) {
    const from = it.from ? item(it.from) : null;
    return `<textarea class="bd-ptext serif" data-f="text" placeholder="The quoted words" aria-label="The quote" spellcheck="true"${fieldLang()}>${esc(it.text || "")}</textarea>
      <div class="bd-pf2 bd-qsrc"><label class="bd-pf"><span class="label">Source</span><select class="select" data-f="source">${sourceOptions(it.source || "", p.citable)}</select></label>
        <label class="bd-pf"><span class="label">Locator</span><input class="input" data-f="locator" value="${esc(it.locator || "")}" placeholder="p. 12" spellcheck="false" autocomplete="off"></label></div>
      ${it.from ? `<p class="bd-pnote">Quoted from ${from ? `<button type="button" class="bd-plink" data-open="${esc(it.from)}">${esc(nameOf(from))}</button>` : `a clip that is no longer on this board`}</p>` : ""}`;
  }
  /* the quote's Source: no source, the sources in reach (this board, the shared board, the book's sources.json), and
     New source…; a key that isn't in reach stays chosen, said so */
  function sourceOptions(cur, list) {
    const opt = (key, label) => `<option value="${esc(key)}"${key === cur ? " selected" : ""}>${esc(truncate(label, 72))}</option>`;
    const label = c => c.label + (c.title && !c.label.includes(c.title) ? ` — ${c.title}` : "");
    const groups = [["On this board", []], ["Shared board", []], ["The book's sources", []]];
    for (const c of list || []) groups[c.id == null ? 2 : c.board == null && B.id != null ? 1 : 0][1].push(opt(c.key, label(c)));
    const known = (list || []).some(c => c.key === cur);
    return opt("", "No source")
      + (cur && !known ? opt(cur, list ? `${cur} (not in reach of this board)` : cur) : "")
      + groups.filter(g => g[1].length).map(([g, o]) => `<optgroup label="${esc(g)}">${o.join("")}</optgroup>`).join("")
      + `<option value="__new">New source…</option>`;
  }
  async function loadCitable(p) {
    let list;
    try { list = await api(path("/api/research/citable")); } catch { return; }
    if (P !== p || !B.panel) return;
    p.citable = list;
    const sel = $("[data-f=source]", B.panel);
    if (!sel) return;
    const v = sel.value === "__new" ? (p.item.source || "") : sel.value;
    sel.innerHTML = sourceOptions(v, list);
    sel.value = v;
  }
  async function pickSource(p, sel) {
    const v = sel.value;
    if (v !== "__new") { change(p, {source: v}, true); return; }
    const prev = p.saver && p.saver.fields && "source" in p.saver.fields ? p.saver.fields.source : p.item.source || "";
    sel.value = prev;                      // until the new source is made
    const csl = await sourceDialog({heading: "New source", submit: "Add the source"});
    if (!csl || P !== p) return;
    const made = await addItem({type: "source", csl, text: ""});
    if (!made || P !== p) return;
    const key = made.csl && made.csl.id ? made.csl.id : csl.id;
    toast(`Added ${shortOf(made.csl || csl)} to the board`);
    await loadCitable(p);
    const s = P === p && $("[data-f=source]", B.panel);
    if (!s) return;
    if (![...s.options].some(o => o.value === key)) s.insertAdjacentHTML("afterbegin", `<option value="${esc(key)}">${esc(key)}</option>`);
    s.value = key;
    change(p, {source: key}, true);
  }

  function sourceBody(it) {
    const key = it.csl && it.csl.id ? it.csl.id : "";
    return `<form class="bd-pform" autocomplete="off">${sourceFields(it.csl, {err: true})}</form>
      <div class="bd-pkey"><span class="label">Key</span><p class="bd-pkv">@${esc(key)}</p><p class="hint">Quotes cite the source by this key.</p></div>
      ${bookLine(it)}
      <label class="bd-pf bd-pnotes"><span class="label">Notes</span><textarea class="bd-ptext small" data-f="text" placeholder="Notes about the source" spellcheck="true"${fieldLang()}>${esc(it.text || "")}</textarea></label>`;
  }
  /* a citable item on a book's board: in the book's sources.json, or a button that puts it there */
  function bookLine(it) {
    if (!B.book || !it.csl || typeof it.csl !== "object") return "";
    return `<div class="bd-pbook" data-book-line>${it.in_book ? `<p class="bd-pin">In the book's sources</p>`
      : `<button type="button" class="btn small" data-act="to-book">Add to the book's sources</button>`}</div>`;
  }
  /* the source form's fields (part 1's, as the rail's source form has them); the panel's title is the head's field */
  function sourceFields(csl, {title = false, key = null, err = false} = {}) {
    const s = csl && typeof csl === "object" ? csl : {type: "book"}, type = s.type || "book", known = SOURCE_TYPES.some(t => t[0] === type);
    const field = (name, label, value, attrs = "") => `<label class="bd-pf"><span class="label">${label}</span><input class="input" data-sf="${name}" value="${esc(value)}" ${attrs}></label>`;
    const BX = BookTools;
    return `<label class="bd-pf"><span class="label">Type</span><select class="select" data-sf="type">${SOURCE_TYPES.map(([v, l]) => `<option value="${v}"${v === type ? " selected" : ""}>${l}</option>`).join("")}
        ${known ? "" : `<option value="${esc(type)}" selected>${esc(type)}</option>`}</select></label>
      ${title ? field("title", "Title", s.title || "", `spellcheck="true"${fieldLang()}`) : ""}
      <label class="bd-pf"><span class="label">Authors</span><input class="input" data-sf="authors" value="${esc(BX.formatAuthors(s.author))}" placeholder="van Dijk, Anna; Jansen, M." spellcheck="false">
        <span class="hint">Family name, given names; a semicolon between people. An organisation without a comma.</span></label>
      <div class="bd-pf2">${field("year", "Year", BX.dateText(s.issued), `maxlength="12"`)}${field("accessed", "Accessed", BX.dateText(s.accessed), `placeholder="2026-11-12" spellcheck="false" maxlength="40"`)}</div>
      ${err ? `<p class="hint bad bd-serr" role="alert" hidden></p>` : ""}
      ${field("publisher", "Publisher", s.publisher || "")}
      <div data-cbox ${CONTAINER[type] || s["container-title"] ? "" : "hidden"}>${field("container", `<span data-clabel>${esc(CONTAINER[type] || "In")}</span>`, s["container-title"] || "")}</div>
      ${field("url", "URL", s.URL || "", `type="url" spellcheck="false" placeholder="https://"`)}
      ${key !== null ? `<label class="bd-pf"><span class="label">Key</span><input class="input" data-sf="id" value="${esc(key)}" spellcheck="false" placeholder="vandijk2019">
        <span class="hint">Quotes cite the source by this key.</span></label>` : ""}`;
  }
  const sourceValues = host => Object.fromEntries($$("[data-sf]", host).map(e => [e.dataset.sf, e.value]));
  /* a journal, a book or a website for the types that have one */
  function typedForm(host) {
    const v = sourceValues(host), lab = $("[data-clabel]", host), box = $("[data-cbox]", host);
    if (lab) lab.textContent = CONTAINER[v.type] || "In";
    if (box) box.hidden = !CONTAINER[v.type] && !String(v.container || "").trim();
  }
  /* The source item's CSL from the form and the head's title, saved as it is typed. An accessed date that isn't one
     (the one field sourceItem refuses) is said at once under the field and the state is "Not saved"; the other fields
     are saved with the date as it was, and what was typed is held (p.invalid) until it is a date or cleared. */
  function sourceChanged(p) {
    const form = $(".bd-pform", B.panel), err = $(".bd-serr", B.panel), acc = $("[data-sf=accessed]", B.panel);
    if (!form) return;
    const orig = p.item.csl && typeof p.item.csl === "object" ? p.item.csl : null;
    const values = {...sourceValues(form), title: $("[data-f=title]", B.panel)?.value || "", id: orig && orig.id ? orig.id : ""};
    const first = BookTools.sourceItem(orig, values);
    let made = first;
    if (first.error) {
      const typed = values.accessed;
      made = BookTools.sourceItem(orig, {...values, accessed: BookTools.dateText(orig && orig.accessed)});
      if (made.error) return;
      p.invalid = {field: "accessed", value: typed, message: first.error, csl: {...made.item, accessed: {raw: typed}}};
      if (err) { err.textContent = p.invalid.message; err.hidden = false; }
      acc?.setAttribute("aria-invalid", "true");
    } else {
      p.invalid = null;
      if (err) err.hidden = true;
      acc?.removeAttribute("aria-invalid");
      if (p.invalidKept != null) {          // kept when leaving was asked and then cancelled: the date is right now
        const raw = p.invalidKept;
        putRescues(p.key, rescuesOf(p.key).filter(x => !(x.fields.csl && x.fields.csl.accessed && x.fields.csl.accessed.raw === raw)));
        p.invalidKept = null;
      }
    }
    change(p, {csl: made.item});
  }

  function clipBody(it, p) {
    const det = [it.site, it.author, it.published ? day(it.published) || it.published : ""].filter(v => typeof v === "string" && v).join(" · ");
    const url = webUrl(it.url), html = String(it.html || "").trim(), tab = p.tab || "text";
    const thumb = typeof it.thumb === "string" ? it.thumb : null;
    return `${det ? `<p class="bd-pdet">${esc(det)}</p>` : ""}
      <p class="bd-pdet bd-pclip">${it.fetched ? `<span>Clipped ${esc(day(it.fetched))}</span>` : ""}${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open the page ↗</a>` : ""}</p>
      ${typeof it.file === "string" && it.file ? `<div class="bd-pacts"><button type="button" class="btn small" data-act="reveal">Show the file</button></div>` : ""}
      ${bookLine(it)}
      <div class="bd-ptabs" role="tablist" aria-label="The clip"><button type="button" role="tab" data-tab="text" aria-selected="${tab === "text"}">Text</button><button type="button" role="tab" data-tab="picture" aria-selected="${tab === "picture"}">Picture</button></div>
      <div class="bd-copy" data-pane="text" ${tab === "text" ? "" : "hidden"}>${html || `<p class="bd-pnone">This clip has no readable copy.</p>`}</div>
      <div class="bd-pic" data-pane="picture" ${tab === "picture" ? "" : "hidden"}>${thumb
        ? `<a href="${esc(fullSize(thumb))}" target="_blank" rel="noopener noreferrer" title="The picture at full size" draggable="false"><img src="${esc(sized(thumb, 960))}" alt="The page as it was when it was clipped" draggable="false"></a>`
        : `<p class="bd-pnone">No picture was taken of this page.</p>`}</div>`;
  }

  function imageBody(it) {
    const thumb = typeof it.thumb === "string" ? it.thumb : null;
    return `${thumb ? `<a class="bd-pimg" href="${esc(fullSize(thumb))}" target="_blank" rel="noopener noreferrer" title="The image at full size" draggable="false"><img src="${esc(sized(thumb, 960))}" alt="${esc(titleOf(it).text)}" draggable="false"></a>`
        : `<p class="bd-pnone">The image file${typeof it.file === "string" ? " " + esc(it.file) : ""} is missing.</p>`}
      <label class="bd-pf"><span class="label">Caption and notes</span><textarea class="bd-ptext small" data-f="text" placeholder="A caption, or notes about the image" spellcheck="true"${fieldLang()}>${esc(it.text || "")}</textarea></label>
      <div class="bd-psrc" data-image-source>${imageSource(it)}</div>`;
  }
  function imageSource(it) {
    const csl = it.csl && typeof it.csl === "object" ? it.csl : null;
    return csl ? `<span class="label">Source</span><p class="bd-psrc-t">${esc(shortOf(csl))}${csl.title ? ` — <i>${esc(csl.title)}</i>` : ""}</p>
        <div class="bd-pacts"><button type="button" class="btn small" data-act="edit-source">Edit the source…</button><button type="button" class="btn small quiet" data-act="drop-source">Remove the source</button></div>`
      : `<div class="bd-pacts"><button type="button" class="btn small" data-act="add-source">Add a source…</button></div>`;
  }
  async function imageSourceDialog(p, edit) {
    const orig = edit && p.item.csl && typeof p.item.csl === "object" ? p.item.csl : null;
    const csl = await sourceDialog({heading: orig ? "Source of the image" : "Add a source", submit: orig ? "Save" : "Add the source", csl: orig, keep: !!orig});
    if (!csl || P !== p) return;
    p.item = {...p.item, csl};
    const host = $("[data-image-source]", B.panel);
    if (host) host.innerHTML = imageSource(p.item);
    change(p, {csl}, true);
    toast(orig ? `Saved the source, ${shortOf(csl)}` : `The image's source is ${shortOf(csl)}`);
  }

  function pieceBody(it) {
    return `<p class="bd-pdet" data-pmeta>Reading the piece…</p>
      <blockquote class="bd-plines" data-plines hidden></blockquote>
      <div class="bd-pacts"><a class="btn small" href="${esc(bookHash(it.book, it.file))}">Open in the writing window</a></div>
      <label class="bd-pf"><span class="label">Why it's here</span><textarea class="bd-ptext small" data-f="text" placeholder="Why this piece is on the board" spellcheck="true"${fieldLang()}>${esc(it.text || "")}</textarea></label>`;
  }
  /* the piece's kind, status and words, and its first lines (GET /api/book/piece) */
  async function loadPiece(p) {
    const it = p.item;
    let pc, why = null;
    try { pc = await api(`/api/book/piece?b=${encodeURIComponent(it.book)}&f=${encodeURIComponent(it.file)}`); }
    catch (e) { why = e.status === 404 ? "The piece is no longer in its book." : `The piece couldn't be read: ${plain(e.message)}.`; }
    if (P !== p || !B.panel) return;
    const meta = $("[data-pmeta]", B.panel), lines = $("[data-plines]", B.panel);
    if (!meta) return;
    if (why) { meta.textContent = why; return; }
    const status = typeof pc.status === "string" && pc.status ? pc.status[0].toUpperCase() + pc.status.slice(1) : "";
    meta.textContent = [pieceKindName(pc.kind), status, bookWords(pc.words || 0)].filter(Boolean).join(" · ");
    const first = String(pc.md || "").replace(/\r/g, "").split("\n").map(l => l.trim())
      .filter(l => l && !/^#{1,6}\s/.test(l) && !/^([-*_]\s*){3,}$/.test(l) && !/^(<!--|:::|\{)/.test(l))
      .slice(0, 3).map(l => l.replace(/^>\s?/, "").replace(/^([-*+]|\d+\.)\s+/, "").replace(/\^\[[^\]]*\]/g, "").replace(/\[@[^\]]*\]/g, "")
        .replace(/(\*\*|__|\*|_)(\S(?:.*?\S)?)\1/g, "$2").trim()).filter(Boolean);
    if (first.length) { lines.innerHTML = first.map(l => `<p>${esc(l)}</p>`).join(""); lines.hidden = false; }
    if (!$("[data-f=title]", B.panel)?.value && pc.title) $("[data-f=title]", B.panel).placeholder = pc.title;
  }

  /* Tags: the item's, each with a remove button, then a field; suggestions are the board's other tags. Comma or Enter
     adds, Backspace in the empty field removes the last. */
  function tagsHtml(p) {
    const own = new Set(p.tags.map(t => t.toLowerCase()));
    const sugg = Object.entries((B.board && B.board.tags) || {}).filter(([t]) => !own.has(t.toLowerCase())).sort((a, b) => b[1] - a[1] || byName(a[0], b[0]));
    return `<div class="bd-ptags" data-tags><span class="label" id="bd-tagl">Tags</span><div class="bd-tagbox">${p.tags.map(t => `<span class="bd-tag">${esc(t)}<button type="button" class="bd-tagx" data-untag="${esc(t)}" aria-label="Remove the tag ${esc(t)}" title="Remove">×</button></span>`).join("")}
      <input class="bd-tagin" data-tagin list="bd-tagsugg" placeholder="${p.tags.length ? "" : "Add a tag"}" aria-labelledby="bd-tagl" autocomplete="off" spellcheck="false" maxlength="${TAG_MAX}"></div>
      <datalist id="bd-tagsugg">${sugg.map(([t]) => `<option value="${esc(t)}"></option>`).join("")}</datalist></div>`;
  }
  function paintTags(p) {
    const host = P === p && $("[data-tags]", B.panel);
    if (!host) return;
    const had = document.activeElement && document.activeElement.matches("[data-tagin]");
    host.outerHTML = tagsHtml(p);
    if (had) $("[data-tagin]", B.panel)?.focus();
    if (p.gone) readOnly();
  }
  function addTags(p, list) {
    const next = [...p.tags];
    for (const raw of list) {
      const t = squash(raw);
      if (!t) continue;
      if (t.length > TAG_MAX) { toast(`A tag is at most ${TAG_MAX} characters.`, true); continue; }
      if (!next.some(x => x.toLowerCase() === t.toLowerCase())) next.push(t);
    }
    if (next.length !== p.tags.length) setTags(p, next);
  }
  function setTags(p, tags) {
    p.tags = tags;
    paintTags(p);
    change(p, {tags}, true);
  }

  /* the bar over the panel's body: changed elsewhere, deleted elsewhere, not saved, a kept text */
  function paintBar(p) {
    const bar = P === p && B.panel && $(".bd-pbar", B.panel);
    if (!bar) return;
    const row = (t, acts) => `<div class="bd-pbar-row"><span class="bd-pbar-t">${t}</span>${acts ? `<span class="bd-pbar-a">${acts}</span>` : ""}</div>`;
    const btn = (act, label, quiet) => `<button type="button" class="btn small${quiet ? " quiet" : ""}" data-act="${act}">${label}</button>`;
    let h = "";
    if (p.gone) h = row("This item was deleted elsewhere. Your text is kept in this window.", btn("copy", "Copy text"));
    else if (p.conflict) h = row("This item changed outside the board.", btn("reload", "Reload") + btn("keep", "Keep mine"));
    else if (p.failed) h = row(`Not saved: ${esc(p.failed)}.${p.halt ? "" : " Studio tries again every few seconds; the text stays here."}`, btn("retry", "Try now"));
    const r = p.rescues[p.rescues.length - 1], more = p.rescues.length - 1;      // the newest first
    if (r && !p.gone) h += row(`Text you wrote here on ${esc(when(new Date(r.at || Date.now()).toISOString()))} wasn't saved.${more ? ` ${more} more ${more === 1 ? "is" : "are"} kept.` : ""}`,
      btn("discard", "Discard it…", true) + btn("putback", "Put it back"));
    bar.innerHTML = h;
    bar.hidden = !h;
  }
  /* the fields of an item deleted elsewhere: still there to copy, no longer typed into */
  function readOnly() {
    if (!B.panel) return;
    $$("textarea, input", B.panel).forEach(e => { e.readOnly = true; });
    $$('select, [data-act="to-book"], [data-act$="-source"], .bd-tagx', B.panel).forEach(e => { e.disabled = true; });
  }

  /* ——— the panel's controls ——— */
  function grow(t) {
    const body = t.closest(".bd-pbody"), top = body ? body.scrollTop : 0;
    t.style.height = "auto";
    t.style.height = t.scrollHeight + (t.offsetHeight - t.clientHeight) + "px";
    if (body) body.scrollTop = top;
  }
  function focusField(which) {
    const el = which === "tags" ? $("[data-tagin]", B.panel) : $(`[data-f=${which}]`, B.panel) || $("[data-f=title]", B.panel);
    if (!el) return;
    el.focus();
    if (typeof el.setSelectionRange === "function" && el.value != null) { const n = el.value.length; try { el.setSelectionRange(n, n); } catch { /* not a text field */ } }
    el.scrollIntoView({block: "nearest"});
  }
  function caret() {
    const a = document.activeElement;
    if (!B.panel || !a || !B.panel.contains(a)) return null;
    const sel = a.dataset.f ? `[data-f=${a.dataset.f}]` : a.dataset.sf ? `[data-sf=${a.dataset.sf}]` : a.matches("[data-tagin]") ? "[data-tagin]" : null;
    return sel ? {sel, start: a.selectionStart, end: a.selectionEnd} : null;
  }
  function restoreCaret(c) {
    const el = $(c.sel, B.panel);
    if (!el) return;
    el.focus({preventScroll: true});
    try { if (c.start != null) el.setSelectionRange(c.start, c.end); } catch { /* a select */ }
  }

  function wirePanel() {
    const el = B.panel;
    el.addEventListener("input", e => {
      const p = P, t = e.target;
      if (!p || !p.item) return;
      if (t.matches("textarea")) grow(t);
      const f = t.dataset.f;
      if (f === "title") { if (p.item.type === "source") sourceChanged(p); else change(p, {title: t.value}); }
      else if (f === "text") {
        change(p, {text: t.value});
        if (p.item.type === "note") $(".bd-psub", el).textContent = plural(wordCount(t.value), "word");
      } else if (f === "locator") change(p, {locator: t.value});
      else if (t.dataset.sf) sourceChanged(p);
      else if (t.matches("[data-tagin]")) {
        const suggested = e.inputType === "insertReplacementText" || e.inputType == null;      // a suggestion chosen
        if (/[,;]/.test(t.value)) { const parts = t.value.split(/[,;]/); t.value = parts.pop(); addTags(p, parts); }
        else if (suggested && Object.keys((B.board && B.board.tags) || {}).includes(t.value)) { const v = t.value; t.value = ""; addTags(p, [v]); }
      }
    });
    el.addEventListener("change", e => {
      const p = P, t = e.target;
      if (!p || !p.item) return;
      if (t.dataset.f === "source") { pickSource(p, t); return; }
      if (t.dataset.sf === "type") typedForm(t.closest("form"));
    });
    el.addEventListener("focusout", e => {          // a tag typed and left is added (not when its way out is a tag's ×)
      const p = P, t = e.target, to = e.relatedTarget;
      if (!p || !t.matches || !t.matches("[data-tagin]") || t.readOnly || !t.value.trim()) return;
      if (to && to.closest && to.closest(".bd-tagx")) return;
      const v = t.value; t.value = ""; addTags(p, [v]);
    });
    el.addEventListener("keydown", e => {
      const p = P, t = e.target;
      if (!p || e.isComposing) return;
      if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); close(); return; }
      if (t.dataset && t.dataset.f === "title" && e.key === "Enter") {
        e.preventDefault();
        ($("[data-f=text]", el) || $("[data-tagin]", el))?.focus();
        return;
      }
      if (t.matches && t.matches("[data-tagin]")) {
        if (e.key === "Enter" || e.key === ",") {
          e.preventDefault();
          if (t.value.trim()) { const v = t.value; t.value = ""; addTags(p, [v]); }
        } else if (e.key === "Backspace" && !t.value && p.tags.length && !t.readOnly) {
          e.preventDefault();
          setTags(p, p.tags.slice(0, -1));
        }
      }
    });
    el.addEventListener("submit", e => e.preventDefault());
    el.addEventListener("pointerdown", e => { if (e.target.closest(".bd-qbtn")) e.preventDefault(); });     // the selection stays
    el.addEventListener("click", e => {
      const p = P;
      if (!p) return;
      const tab = e.target.closest("[data-tab]");
      if (tab) {
        p.tab = tab.dataset.tab;
        $$("[data-tab]", el).forEach(b => b.setAttribute("aria-selected", String(b === tab)));
        $$("[data-pane]", el).forEach(x => { x.hidden = x.dataset.pane !== p.tab; });
        hideQuote();
        return;
      }
      const untag = e.target.closest("[data-untag]");
      if (untag && !untag.disabled) { setTags(p, p.tags.filter(t => t !== untag.dataset.untag)); return; }
      const from = e.target.closest("[data-open]");
      if (from) { open(from.dataset.open); return; }
      if (e.target.matches(".bd-tagbox")) { $("[data-tagin]", el)?.focus(); return; }
      const b = e.target.closest("[data-act]");
      if (b && !b.disabled) act(p, b.dataset.act, b);
    });
  }

  async function act(p, what, btn) {
    const it = p.item;
    if (what === "close") return close();
    if (what === "more") return menu(menuAt(btn), [p.id]);
    if (what === "reload") {
      const theirs = p.saver.reload();
      p.conflict = null; p.failed = null; p.invalid = null;
      if (theirs) { p.item = theirs; p.mtime = theirs.mtime; p.tags = Array.isArray(theirs.tags) ? [...theirs.tags] : []; }
      paintPanel(p);
      toast("Reloaded the item as it is on disk");
      return;
    }
    if (what === "keep") {
      p.conflict = null;
      paintBar(p);
      await p.saver.keepMine();
      later(p);
      return;
    }
    if (what === "retry") { p.failed = null; p.halt = false; paintBar(p); p.saver.flush(); return; }
    if (what === "copy") {
      const words = $("[data-f=text]", B.panel)?.value || $("[data-f=title]", B.panel)?.value || "";
      try { await navigator.clipboard.writeText(words); toast("Copied the text"); } catch { toast("The text couldn't be copied. Select it and press Ctrl+C.", true); }
      return;
    }
    if (what === "putback" || what === "discard") {
      const r = p.rescues[p.rescues.length - 1];
      if (!r) return;
      if (what === "discard" && !(await ask("Discard the text?", `What you wrote in “${nameOf(it)}” on ${when(new Date(r.at || Date.now()).toISOString())} is kept only in this browser. Once discarded it can't be brought back.`, "Discard"))) return;
      if (P !== p) return;
      p.rescues = p.rescues.filter(x => x !== r);
      putRescues(p.key, rescuesOf(p.key).filter(x => x.at !== r.at || JSON.stringify(x.fields) !== JSON.stringify(r.fields)));
      if (what === "discard") { paintBar(p); toast("Discarded the text"); return; }
      const f = r.fields;
      if (Array.isArray(f.tags)) p.tags = [...f.tags];
      paintPanel(p, {view: f});
      if (p.item.type === "source") { sourceChanged(p); const {csl, ...rest} = f; if (Object.keys(rest).length) change(p, rest); }      // the form checks it again
      else change(p, f);
      toast("Put back the text you wrote");
      return;
    }
    if (what === "to-book") return addToBook(p.id);
    if (what === "original") return openHit(it.link.board ?? null, it.link.item);
    if (what === "remove-link") { const r = await trash([p.id]); if (r) toast("Removed the link"); return; }
    if (what === "reveal") {
      try { await api("/api/research/reveal", {b: B.id, id: p.id}); } catch (e) { failed(e); }
      return;
    }
    if (what === "add-source" || what === "edit-source") return imageSourceDialog(p, what === "edit-source");
    if (what === "drop-source") {
      p.item = {...p.item, csl: null};
      const host = $("[data-image-source]", B.panel);
      if (host) host.innerHTML = imageSource(p.item);
      change(p, {csl: null}, true);
      toast("Removed the image's source");
      return;
    }
    if (what === "quote") { const s = quoteSel(); if (s) quoteFrom(p.id, s.text); }
  }

  /* ——— quoting from a clip: a selection in its readable copy shows a Quote button beside it ——— */
  function quoteSel() {
    const copy = P && B.panel && $(".bd-copy:not([hidden])", B.panel), s = getSelection();
    if (!copy || !s || s.isCollapsed || !s.rangeCount) return null;
    const r = s.getRangeAt(0);
    if (!copy.contains(r.commonAncestorContainer)) return null;
    const words = s.toString().replace(/\r/g, "").replace(/[ \t\u00a0]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    return words ? {text: words, rect: r.getBoundingClientRect()} : null;
  }
  let quoteFrame = 0;
  function quoteButton() {
    quoteFrame = 0;
    const btn = P && B.panel && $(".bd-qbtn", B.panel), body = btn && btn.parentElement;
    if (!btn) return;
    const s = quoteSel();
    if (!s) { btn.hidden = true; return; }
    btn.hidden = false;
    const box = body.getBoundingClientRect(), w = btn.offsetWidth;
    btn.style.top = Math.round(s.rect.bottom - box.top + body.scrollTop + 6) + "px";
    btn.style.left = Math.round(Math.max(20, Math.min(s.rect.right - box.left - w, body.clientWidth - w - 20))) + "px";
  }
  function hideQuote() { const b = B.panel && $(".bd-qbtn", B.panel); if (b) b.hidden = true; }
  document.addEventListener("selectionchange", () => { if (P && B.root && !quoteFrame) quoteFrame = requestAnimationFrame(quoteButton); });

  /* A quote of words from a clip: its source the clip's key, `from` the clip, placed right of the clip's card; opened. */
  async function quoteFrom(clipId, words) {
    const t = String(words || "").replace(/\r/g, "").replace(/\n{3,}/g, "\n\n").trim();
    if (!t || !B.root) return null;
    const c = item(clipId) || (P && P.id === clipId ? P.item : null);
    const key = c && c.csl && typeof c.csl === "object" && typeof c.csl.id === "string" ? c.csl.id : null;
    let at = null, frame = null;
    if (c && c.pos) {
      const box = C.cardBox(c);
      at = {x: box.x + box.w + 40, y: box.y};
      frame = C.frameAt((B.board && B.board.frames) || [], at.x + C.CARD_W.quote / 2, at.y + C.CARD_H.quote / 2);
    }
    getSelection()?.removeAllRanges();
    const it = await addItem({type: "quote", text: t, ...(key ? {source: key} : {}), from: clipId}, at, frame);
    if (it) { toast(c ? `Added a quote from “${nameOf(c)}”` : "Added a quote"); open(it.id); }
    return it;
  }

  /* ——— adding ——— */
  function addMenu(btn) {
    StudioMenu.open(menuAt(btn), ADD.map(([kind, label]) => ({label, act: () => add(kind)})));
  }
  /* Add → Note, Quote, Source…, Web clip…, Image…, Link to a piece…, Frame; `at` in board units (the canvas). */
  async function add(kind, at = null, frame = null) {
    if (!B.root) return null;
    if (kind === "note" || kind === "quote") {
      const it = await addItem({type: kind, text: ""}, at, frame);
      if (it) { toast(kind === "note" ? "Added a note" : "Added a quote"); open(it.id, {focus: "text"}); }
      return it;
    }
    if (kind === "source") {
      const csl = await sourceDialog({heading: "New source", submit: "Add the source"});
      if (!csl || !B.root) return null;
      const it = await addItem({type: "source", csl, text: ""}, at, frame);
      if (it) { toast(`Added ${shortOf(it.csl || csl)}`); open(it.id); }
      return it;
    }
    if (kind === "clip") return clipDialog(at, frame);
    if (kind === "image") return pickImages(at, frame);
    if (kind === "piece") {
      const pc = await pickPiece();
      if (!pc || !B.root) return null;
      const it = await addItem({type: "piece", book: pc.book, file: pc.file, text: ""}, at, frame);
      if (it) { toast(`Added the piece “${pc.title}”`); open(it.id); }
      return it;
    }
    if (kind === "frame") return addFrame(at);
    return null;
  }

  /* text dropped or pasted: a web address is clipped, anything else becomes a note (opened) */
  async function addText(words, at = null, frame = null) {
    const s = String(words || "").replace(/\r\n?/g, "\n").trim();
    if (!s || !B.root) return null;
    const url = webUrl(s);
    if (url) return clip(url, at, {frame});
    const it = await addItem({type: "note", text: s}, at, frame);
    if (it) { toast("Added a note"); open(it.id); }
    return it;
  }

  /* placeholders while a page is clipped or an image is sent: a line over the view, "Clipping example.org…" */
  function pend(kind, words) {
    const n = ++pendSeq;
    B.clipping.push({n, kind, text: words});
    paintPend();
    return n;
  }
  function unpend(n) { B.clipping = B.clipping.filter(x => x.n !== n); paintPend(); }
  function paintPend() {
    const el = $r(".bd-pend");
    if (!el) return;
    el.innerHTML = B.clipping.map(x => `<div class="bd-pending"><span class="bd-c-kind">${esc(kindName(x.kind))}</span><span class="bd-pt">${esc(x.text)}</span></div>`).join("");
    el.hidden = !B.clipping.length;
  }

  function clipDialog(at, frame) {
    return new Promise(resolve => {
      let url = null;
      openDialog(`<form autocomplete="off"><h2>Clip a web page</h2>
        <p class="hint" style="margin-top:-12px">Studio fetches the page once and keeps its text and a picture of it. Studio clips pages on the internet, not on this computer or its network.</p>
        <label><span class="label">Address</span><input class="input" name="url" inputmode="url" placeholder="https://example.org/an-article" spellcheck="false" autocomplete="off"></label>
        <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Clip</button></div></form>`,
      async f => {
        const u = String(f.get("url") || "").trim();
        if (!u) throw new Error("Paste or type the address of a page.");
        url = u;
      });
      onDialogClose(() => resolve(url && B.root ? clip(url, at, {frame}) : null));
    });
  }

  /* A page clipped (POST /api/research/clip): the item (an image item when the address is an image), or null; a new
     one is recorded for undo. With `id`, that clip is fetched again (not undone: the earlier copy is gone). A `warning`
     (no picture) is said. */
  function clip(url, at = null, {frame = null, id = null} = {}) {
    return id ? clipNow(url, at, {frame, id}) : added(clipNow(url, at, {frame}));
  }
  async function clipNow(url, at = null, {frame = null, id = null} = {}) {
    const root = B.root, u = String(url || "").trim();
    if (!root || !u) return null;
    const n = pend("clip", `Clipping ${hostOf(u)}…`);
    try {
      const it = await api("/api/research/clip", {b: B.id, url: u, ...(at ? {at} : {}), ...(frame ? {frame} : {}), ...(id ? {id} : {})});
      if (B.root !== root) return it;
      await read();
      const name = nameOf(it) || hostOf(u);
      if (it.warning) toast(`${id ? "Clipped again" : "Clipped"} “${name}”. ${it.warning}`, true);
      else toast(`${id ? "Clipped again" : "Clipped"} “${name}”`);
      if (id ? P && P.id === it.id : !(B.panel && B.panel.contains(document.activeElement))) open(it.id, {force: !!id});
      return it;
    } catch (e) {
      if (B.root === root) failed(e);
      return null;
    } finally {
      unpend(n);
    }
  }

  function pickImages(at, frame) {
    return new Promise(resolve => {
      const input = document.createElement("input");
      input.type = "file";
      input.multiple = true;
      input.accept = "image/png,image/jpeg,image/gif,image/webp,.png,.jpg,.jpeg,.gif,.webp";
      input.addEventListener("change", () => resolve(input.files && input.files.length ? addFiles(input.files, at, frame) : []));
      input.addEventListener("cancel", () => resolve([]));
      input.click();
    });
  }
  /* Image files added (chosen, pasted or dropped), each through addImage; several are stacked 24 apart from `at`, and
     are one step for undo. */
  async function addFiles(files, at = null, frame = null) {
    const root = B.root, all = [...(files || [])], ok = all.filter(isImage), out = [];
    if (!root) return out;
    if (all.length > ok.length) toast(`${all.find(f => !isImage(f)).name || "That file"} isn't an image Studio can add: use .jpg, .png, .gif or .webp.`, true);
    for (const [i, f] of ok.entries()) {
      if (f.size > MAX_IMAGE) { toast(`${f.name || "The image"} is larger than 28 MB.`, true); continue; }
      let name = String(f.name || "").split(/[\\/]/).pop() || "image";
      if (!IMAGE_EXT.test(name)) name += IMAGE_TYPE[f.type] || ".png";
      const n = pend("image", `Adding ${name}…`);
      let it = null;
      try {
        const data = await fileBase64(f);
        if (B.root === root) it = await addImageNow(name, data, at ? {x: at.x + 24 * i, y: at.y + 24 * i} : null, frame);
      } catch (e) {
        if (B.root === root) toast(e.message, true);
      } finally {
        unpend(n);
      }
      if (it) out.push(it);
      if (B.root !== root) return out;
    }
    if (!out.length) return out;
    remember(addStep(out));
    toast(out.length === 1 ? `Added the image “${nameOf(out[0])}”` : `Added ${out.length} images`);
    if (out.length === 1) open(out[0].id);
    else select(out.map(x => x.id), {cursor: out[out.length - 1].id});
    return out;
  }

  /* Add → Frame. On the canvas: a 480 × 320 frame at `at` (its top left), else in the middle of the view, its title
     typed in place. In the list: a title asked for, the frame put to the right of everything. */
  function addFrame(at) {
    if (canvasShown()) return frameHere(at);
    return new Promise(resolve => {
      let title = null;
      openDialog(`<form autocomplete="off"><h2>New frame</h2>
        <label><span class="label">Title</span><input class="input big" name="title" autocomplete="off" maxlength="80" placeholder="Frame"></label>
        <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Add the frame</button></div></form>`,
      async f => { title = squash(f.get("title")) || "Frame"; });
      onDialogClose(async () => {
        if (title == null || !B.root) { resolve(null); return; }
        const before = new Set(((B.board && B.board.frames) || []).map(f => f.id)), spot = at || rightOfAll();
        const board = await setFrames({frames: [{title, x: Math.round(spot.x), y: Math.round(spot.y), w: FRAME_W, h: FRAME_H}]});
        const fr = board && (board.frames || []).find(f => !before.has(f.id));
        if (fr) { toast(`Added the frame ${fr.title || title}`); goToFrame(fr.id); }
        resolve(fr || null);
      });
    });
  }
  async function frameHere(at) {
    const {w, h} = BoardCanvas.NEW_FRAME, c = at ? null : pasteAt();
    const spot = at || (c ? {x: c.x - w / 2, y: c.y - h / 2} : rightOfAll());
    const before = new Set(((B.board && B.board.frames) || []).map(f => f.id));
    const board = await setFrames({frames: [{title: "Frame", x: Math.round(spot.x), y: Math.round(spot.y), w, h}]});
    const fr = board && (board.frames || []).find(f => !before.has(f.id));
    if (fr && B.canvas) B.canvas.rename(fr.id);
    return fr || null;
  }
  function rightOfAll() {
    const b = B.board, boxes = b ? [...b.items.map(C.cardBox), ...(b.frames || []).filter(f => typeof f.x === "number" && typeof f.y === "number")] : [];
    if (!boxes.length) return {x: 0, y: 0};
    return {x: Math.max(...boxes.map(r => r.x + (r.w || 0))) + COLUMN_GAP, y: Math.min(...boxes.map(r => r.y))};
  }

  /* Studio's own dialog for a yes or no: Cancel is focused */
  function ask(title, words, go) {
    return new Promise(resolve => {
      let yes = false;
      openDialog(`<form><h2>${esc(title)}</h2><p class="hint" style="margin-top:-12px">${esc(words)}</p>
        <div class="foot"><button type="button" class="btn quiet" data-close autofocus>Cancel</button><button type="submit" class="btn solid">${esc(go)}</button></div></form>`,
      async () => { yes = true; });
      onDialogClose(() => resolve(yes));
    });
  }

  /* The source form in a dialog: a new source (its key suggested from the authors or title and the year, not one in
     reach of the board), or an image's source (`keep`: its key stays). The CSL item, or null when cancelled. */
  async function sourceDialog({heading, submit, csl = null, keep = false}) {
    let list = [];
    try { list = await api(path("/api/research/citable")); } catch { /* the server checks the key again */ }
    const taken = new Set(list.map(c => c.key));
    if (csl && csl.id) taken.delete(csl.id);
    return new Promise(resolve => {
      let out = null, touched = !!(csl && csl.id);
      const form = openDialog(`<form class="bd-sdlg" autocomplete="off"><h2>${esc(heading)}</h2>
        <div class="bd-sfields">${sourceFields(csl, {title: true, key: keep ? null : (csl && csl.id) || ""})}
          ${keep && csl && csl.id ? `<p class="hint">Quotes cite it as @${esc(csl.id)}.</p>` : ""}</div>
        <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">${esc(submit)}</button></div></form>`,
      async () => {
        const v = sourceValues(form), id = keep && csl ? csl.id : squash(v.id);
        if (!BookText.CITE_KEY.test(id)) throw new Error(id ? `${id} can't be a key: use letters, digits, - and _, starting and ending with a letter or digit.` : "Give the source a key, like vandijk2019.");
        if (!keep && taken.has(id)) throw new Error(`Another source in reach of this board has the key ${id} already.`);
        const made = BookTools.sourceItem(csl, {...v, id});
        if (made.error) throw new Error(made.error);
        out = made.item;
      });
      const val = n => ($(`[data-sf=${n}]`, form) || {}).value || "";
      const suggest = () => {
        if (touched || keep) return;
        const BX = BookTools, k = $("[data-sf=id]", form);
        if (k) k.value = BX.sourceKey({author: BX.parseAuthors(val("authors")), title: val("title"), issued: BX.dateParts(val("year"))}, taken);
      };
      form.addEventListener("input", e => {
        const f = e.target.dataset.sf;
        if (f === "id") touched = true;
        else if (f === "authors" || f === "title" || f === "year") suggest();
      });
      $("[data-sf=type]", form).addEventListener("change", () => typedForm(form));
      suggest();
      onDialogClose(() => resolve(out));
    });
  }

  /* Link to a piece…: a book's board picks from its book; the shared board from every book, then its pieces */
  async function pickPiece() {
    let list;
    try { list = B.book ? [B.book] : (await api("/api/books")).filter(b => b && b.id && !b.error); }
    catch (e) { failed(e); return null; }
    if (!list.length) { toast("There are no books yet."); return null; }
    const books = new Map();         // the books read while the dialog is open
    const read1 = async id => {
      if (books.has(id)) return books.get(id);
      const b = await api("/api/book?b=" + encodeURIComponent(id));
      books.set(id, b);
      return b;
    };
    let first;
    try { first = B.book ? await api("/api/book?b=" + encodeURIComponent(B.book.id)) : await read1(list[0].id); }
    catch (e) { failed(e); return null; }
    if (!B.root) return null;
    return new Promise(resolve => {
      let chosen = null, cur = first;
      const piecesOf = b => (b.contents || []).filter(e => e.file);
      const rows = b => piecesOf(b).map(e => `<label class="bk-pp-i"><input type="radio" name="piece" value="${esc(e.file)}"${e.missing ? " disabled" : ""}>
          <span>${esc(e.title || pieceKindName(e.kind))}</span><span class="bd-pp-k">${esc([pieceKindName(e.kind), e.missing ? "missing" : e.status || ""].filter(Boolean).join(" · "))}</span></label>`).join("")
        || `<p class="hint" style="margin:0">This book has no pieces yet.</p>`;
      const form = openDialog(`<form class="bk-pp bd-pp" autocomplete="off"><h2>Link to a piece</h2>
        <p class="hint" style="margin-top:-12px">The board shows the piece's kind, status and first lines. The piece itself stays in its book.</p>
        ${B.book ? "" : `<label><span class="label">Book</span><select class="select" data-book>${list.map(b => `<option value="${esc(b.id)}">${esc(b.title || b.id)}</option>`).join("")}</select></label>`}
        <input class="input" type="search" data-q placeholder="Find a piece" aria-label="Find a piece" autocomplete="off">
        <div class="bk-pp-list" data-pieces>${rows(first)}</div>
        <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Add</button></div></form>`,
      async f => {
        const file = f.get("piece");
        if (!file) throw new Error("Choose a piece.");
        const e = piecesOf(cur).find(x => x.file === file);
        chosen = {book: cur.id, file, title: e ? e.title || pieceKindName(e.kind) : file};
      });
      const filter = () => {
        const q = $("[data-q]", form).value.trim().toLowerCase();
        $$(".bk-pp-i", form).forEach(l => { l.hidden = !!q && !l.textContent.toLowerCase().includes(q); });
      };
      $("[data-q]", form).addEventListener("input", filter);
      $("[data-book]", form)?.addEventListener("change", async e => {
        const id = e.target.value, host = $("[data-pieces]", form);
        host.innerHTML = `<p class="hint" style="margin:0">Reading the book…</p>`;
        try { cur = await read1(id); } catch (err) { host.innerHTML = `<p class="hint bad" style="margin:0">${esc(err.message)}</p>`; return; }
        if (e.target.value !== id) return;
        host.innerHTML = rows(cur);
        filter();
      });
      onDialogClose(() => resolve(chosen));
    });
  }

  /* ——— the right-click menu: one item or the selection ——— */
  async function loadBoards() {
    try { boards = await api("/api/research/boards"); } catch { /* the menu says so */ }
    return boards;
  }
  function menu(e, ids) {
    e.preventDefault?.(); e.stopPropagation?.();
    const at = {clientX: e.clientX, clientY: e.clientY, preventDefault() {}, stopPropagation() {}};
    const root = B.root, show = () => { if (B.root === root) StudioMenu.open(at, menuItems(ids)); };
    if (boards) { show(); loadBoards(); }
    else loadBoards().then(show);
  }
  function menuItems(ids) {
    const its = ids.map(item).filter(Boolean), one = its.length === 1 ? its[0] : null, n = its.length;
    if (!n) return [{label: "Open", disabled: true}];
    const live1 = one && !one.error && !(one.link && one.link.missing) ? one : null;
    const others = (boards || []).filter(b => !same(b.board, B.id));
    const sub = link => boards == null ? [{label: "The boards can't be listed", disabled: true}]
      : others.length ? others.map(b => ({label: b.title || (b.board == null ? "Shared board" : b.board), act: () => moveAct(its, b, link)}))
      : [{label: "There are no other boards", disabled: true}];
    const out = [{label: "Open", disabled: !one, act: () => open(one.id)}, {label: "Edit tags…", disabled: !live1, act: () => open(one.id, {focus: "tags"})},
      "-", {label: "Move to", items: sub(false)}, {label: "Link on", items: sub(true)}];
    const extra = [];
    if (live1 && live1.type === "clip") {
      const sel = P && P.id === live1.id ? quoteSel() : null;
      extra.push({label: "Quote this", act: () => {
        if (sel) return quoteFrom(live1.id, sel.text);
        open(live1.id);
        toast("Select the words to quote in the clip's text, then choose Quote.");
      }});
      const url = webUrl(live1.url);
      if (url) extra.push({label: "Open the page ↗", act: () => window.open(url, "_blank", "noopener,noreferrer")});
      if (live1.url) extra.push({label: "Clip again", act: () => clip(live1.url, null, {id: live1.id})});
    }
    if (live1 && B.book && live1.type !== "image" && live1.csl && typeof live1.csl === "object") {
      extra.push(live1.in_book ? {label: "In the book's sources", disabled: true} : {label: "Add to the book's sources", act: () => addToBook(live1.id)});
    }
    if (live1 && live1.type === "piece" && live1.book && live1.file) extra.push({label: "Open the piece", act: () => { location.hash = bookHash(live1.book, live1.file); }});
    if (extra.length) out.push("-", ...extra);
    out.push("-", {label: "Copy text", disabled: !its.some(i => !i.error), act: () => copyText(its.map(i => i.id))},
      "-", {label: "Move to the trash", danger: true, act: () => askTrash(its.map(i => i.id))});
    return out;
  }

  async function moveAct(its, target, link) {
    const r = await moveTo(its.map(i => i.id), target.board, link);
    if (!r) return;
    const what = its.length === 1 ? `“${nameOf(its[0])}”` : `${its.length} items`;
    const where = target.board == null ? "the shared board" : target.title || target.board;
    const warn = [...new Set((r.items || []).flatMap(i => Array.isArray(i.warnings) ? i.warnings : []))];
    toast(`${link ? "Linked" : "Moved"} ${what} ${link ? "on" : "to"} ${where}${warn.length ? ". " + warn.join(" ") : ""}`, warn.length > 0);
  }

  /* Move to the trash, asked first for more than one */
  async function askTrash(ids) {
    const its = ids.map(item).filter(Boolean);
    if (!its.length) return null;
    if (its.length > 1 && !(await ask(`Move ${its.length} items to the trash?`, "They go to the board's .trash folder.", "Move to the trash"))) return null;
    const r = await trash(its.map(i => i.id));
    if (r) toast(its.length === 1 ? `Moved “${nameOf(its[0])}” to the trash` : `Moved ${its.length} items to the trash`);
    return r;
  }

  async function copyText(ids) {
    const out = [];
    for (const id of ids) {
      let words;
      if (P && P.id === id && P.item && B.panel) words = $("[data-f=text]", B.panel)?.value ?? P.item.text;
      else { try { words = (await api(itemPath(id))).text; } catch (e) { failed(e); return; } }
      if (words && item(id)?.type === "clip") words = C.plainText(words);     // made from the page: its words, not its Markdown
      if (words && words.trim()) out.push(words.trim());
    }
    if (!out.length) { toast("There is no text to copy."); return; }
    try {
      await navigator.clipboard.writeText(out.join("\n\n"));
      toast(out.length === 1 ? "Copied the text" : `Copied the text of ${out.length} items`);
    } catch { toast("The text couldn't be copied.", true); }
  }

  /* Add to the book's sources: POST /api/research/use puts the item's source in the book's sources.json */
  async function addToBook(id) {
    if (!B.book) return;
    const root = B.root;
    try {
      const r = await api("/api/research/use", {book: B.book.id, b: B.id, id});
      toast(r.added ? `Added to the book's sources as ${r.key}` : `Already in the book's sources as ${r.key}`);
      if (B.root !== root) return;
      if (P && P.id === id && P.item) {
        P.item = {...P.item, in_book: true};
        const line = $("[data-book-line]", B.panel);
        if (line) line.outerHTML = bookLine(P.item);
      }
      read();
    } catch (e) {
      if (B.root === root) failed(e);
    }
  }

  /* ——— pasting on the page (not in a field): images, a web address (clipped), or text (a note) ——— */
  function pasteAt() {
    if (!B.canvas || listShown() || typeof B.canvas.toBoard !== "function") return null;
    const r = $r(".bd-canvas").getBoundingClientRect();
    return B.canvas.toBoard(r.left + r.width / 2, r.top + r.height / 2);
  }
  addEventListener("paste", e => {
    if (!B.root || e.defaultPrevented || $("#dlg").open) return;
    const t = e.target;
    if (t instanceof Element && (t.closest("input, textarea, select, [contenteditable]") || t.isContentEditable)) return;
    const dt = e.clipboardData;
    if (!dt) return;
    const files = [...dt.files].filter(isImage);
    if (files.length) { e.preventDefault(); addFiles(files, pasteAt()); return; }
    const words = dt.getData("text/plain");
    if (words && words.trim()) { e.preventDefault(); addText(words, pasteAt()); }
  });
  /* leaving the page: what is being typed is sent with keepalive (and kept in the browser) */
  addEventListener("pagehide", () => flush({leaving: true}));
  addEventListener("beforeunload", () => flush({leaving: true}));
  addEventListener("blur", () => { if (P && P.saver && !P.gone && !P.dead) P.saver.flush(); });

  Object.assign(B, {open, close, menu, addMenu, pending, flush, add, addText, clip, addFiles, quoteFrom, askTrash,
    addItem, addImage, trash, restore: restoreNow, moveTo, setFrames, clipping: []});
  /* … and what the parts share */
  Object.assign(B, {select, item, visible, apply, place, refresh, say, failed, titleOf, nameOf, sourceOf, reveal, paintView, paintCounts,
    post: (p, body) => api(p, {b: B.id, ...body})});

  return {mount, unmount, refresh, goTo: goToItem, pending: () => !!B.pending(), get B() { return B; }};
})();
window.Board = Board;

/* #/research: the shared board */
function showResearch() {
  state.view = "research"; setNav("research");
  Board.mount(app, {book: null});
}
