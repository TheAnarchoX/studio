"use strict";
/* The writing window of a book (#/book/<id>/write/<file>): the binder of its pieces on the left, the text of one piece
   with its margin in the middle (book-text.js), a status bar with the words; the rail on the right, the palette, focus
   mode, a second pane and the writing tools are book-tools.js and book-rail.js, told what happens here by tools().
   Saving: 1.5 s after the last change, on leaving the piece, when the window loses focus and before it closes. A save
   carries the file's mtime; a piece changed outside the editor (another window, Claude, find and replace) shows a bar
   with Reload and Keep mine, or reloads quietly when nothing here is unsaved. A save that fails stays on a quiet bar
   and is tried again, and until one goes through the text is also kept in this browser, so nothing typed is lost.
   A classic script after book.js and book-text.js; sets window.BookEditor:
   mount(el, {book, file}), unmount() (saves the piece as a leaving save), pending(), refresh(book) (the poll), and for
   the tools the window (win), Piece, bar and a few of the window's own actions. */

const BookEditor = (() => {
  // the piece kinds, forms and auto pages are the store's (GET /api/books/kinds, read by book.js into bookLists)
  const UNTITLED = new Set(["dedication", "epigraph"]);       // pieces that start without a title
  const SAVE_AFTER = 1500, RETRY = 5000, RELOAD = "bk-reload";

  let W = null;                     // the open window
  const live = new Set();           // pieces with something not yet on disk (the open one, or one still saving after it closed)
  const places = new Map();         // book/file -> {anchor, head, scroll}: where the cursor was in a piece

  /* ——— the text kept in this browser until a save goes through ———
     A list per piece, newest first, of {id, doc, at, title}. A piece in the editor keeps its own entry (its id) up to
     date and drops it once a save goes through; an older entry stays until the author puts it back or discards it. */
  const rescue = {
    key: (b, f) => `studio.rescue.${b}/${f}`,
    list(b, f) {
      try {
        const v = JSON.parse(localStorage.getItem(this.key(b, f)) || "[]");
        return Array.isArray(v) ? v.filter(x => x && x.doc) : v && v.doc ? [{id: "earlier", ...v}] : [];     // a single copy of round 1
      } catch { return []; }
    },
    save(b, f, list) {
      try { if (list.length) localStorage.setItem(this.key(b, f), JSON.stringify(list)); else localStorage.removeItem(this.key(b, f)); return true; }
      catch { return false; }
    },
    put(b, f, entry) { return this.save(b, f, [entry, ...this.list(b, f).filter(x => x.id !== entry.id)]); },
    drop(b, f, id) { this.save(b, f, this.list(b, f).filter(x => x.id !== id)); },
  };
  /* Text written in a piece that is no longer in the book (moved to the trash by another window, or its book gone):
     kept per book in this browser and offered at the top of the window as a new piece, until kept or discarded. */
  const orphans = {
    key: b => `studio.orphans.${b}`,
    get(b) { try { const v = JSON.parse(localStorage.getItem(this.key(b)) || "[]"); return Array.isArray(v) ? v : []; } catch { return []; } },
    set(b, list) { try { if (list.length) localStorage.setItem(this.key(b), JSON.stringify(list)); else localStorage.removeItem(this.key(b)); } catch { /* private window */ } },
    add(b, o) { this.set(b, [...this.get(b).filter(x => x.at !== o.at), o]); },        // one row per `at`: a second add updates it
    drop(b, at) { this.set(b, this.get(b).filter(x => x.at !== at)); },
  };
  /* two documents with the same text, leaving out empty paragraphs (Markdown has none) */
  const solid = json => JSON.stringify(json, (k, v) => Array.isArray(v) && k === "content" ? v.filter(n => !(n && n.type === "paragraph" && !(n.content || []).length)) : v);
  /* the kept texts of a piece that is no longer in the book become orphans: offered as new pieces, never dropped unasked */
  function strand(book, file, info, except) {
    for (const r of rescue.list(book, file)) {
      if (r.id !== except) orphans.add(book, {doc: r.doc, title: r.title || info.title, kind: info.kind, form: info.form, file, at: r.at, after: info.after});
    }
    rescue.save(book, file, []);
  }

  const {titleOf, withTitle} = BookText;
  const pieceTitle = e => e.title || pieceKindName(e.kind);
  /* the rail, palette, focus mode, split view and writing tools (book-tools.js) hear what happens here */
  const tools = (ev, ...a) => { try { window.BookTools?.on(ev, ...a); } catch (e) { console.error(e); } };
  const todayKey = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

  /* ——— one piece in the editor ——— */
  class Piece {
    constructor(win, file) {
      Object.assign(this, {win, file, book: win.book.id, text: null, mtime: null, version: 0, savedVersion: 0, touched: false,
        saving: null, queued: null, timer: 0, retry: 0, conflict: null, failed: null, rescued: null, error: null, closed: false,
        finalDoc: null, words: 0, keepId: `${Date.now()}-${Math.random().toString(36).slice(2)}`, orphanAt: null});
      live.add(this);
    }
    get dirty() { return this.version !== this.savedVersion; }
    get entry() { return this.win.book.contents.find(e => e.file === this.file); }
    get name() { return this.text ? titleOf(this.docJSON()) || pieceTitle(this.entry || {}) : pieceTitle(this.entry || {}); }
    fetch() { return api(`/api/book/piece?b=${encodeURIComponent(this.book)}&f=${encodeURIComponent(this.file)}`); }
    /* shows the piece read from the server; a document the editor can't take is shown as a bar and never saved over */
    attach(p) {
      Object.assign(this.win.linked, p.linked || {});
      this.mtime = p.mtime; this.form = p.form; this.kind = p.kind; this.words = p.words || 0;
      try { this.text = BookText.create(this.win.hosts, {doc: p.doc, ctx: this.win.ctx(this)}); }
      catch (e) { this.error = `This piece can't be opened in the editor: ${e.message}. Its file is unchanged.`; live.delete(this); this.win.bar(this); return; }
      this.nextRescue();
    }
    /* the newest kept text that differs from the piece as it opened, offered with Put it back / Discard it */
    nextRescue() {
      const here = solid(this.docJSON());
      this.rescued = null;
      for (const r of rescue.list(this.book, this.file)) {
        if (r.id === this.keepId) continue;
        if (solid(BookText.editableDoc(r.doc)) === here) { rescue.drop(this.book, this.file, r.id); continue; }
        this.rescued = r;
        break;
      }
      this.win.bar(this);
    }
    docJSON() { return this.closed ? this.finalDoc : this.text.view.state.doc.toJSON(); }
    changed(trs) {
      if (this.closed) return;
      this.version++;
      if (trs.some(t => t.getMeta(RELOAD))) { this.savedVersion = this.version; this.win.status(); return; }
      this.touched = true;
      live.add(this);
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.save(), SAVE_AFTER);
      this.win.status();
    }
    keep(doc) { rescue.put(this.book, this.file, {id: this.keepId, doc, at: Date.now(), title: this.name}); }
    unkeep() { rescue.drop(this.book, this.file, this.keepId); }
    /* Saves what is in the editor: one save at a time, a change during a save is saved after it. A leaving save is sent
       when anything was saved during the visit, so the server can take its snapshot. */
    save({leaving = false, force = false} = {}) {
      clearTimeout(this.timer);
      if (!this.text) return Promise.resolve(true);
      if (this.saving) {
        this.queued = {leaving: leaving || !!this.queued?.leaving, force: force || !!this.queued?.force};
        return this.saving.then(() => this.after || true);
      }
      if (this.conflict && !force) { if (this.dirty) this.keep(this.docJSON()); this.settle(); return Promise.resolve(false); }
      if (!this.dirty && !force && !(leaving && this.touched)) { this.settle(); return Promise.resolve(true); }
      const doc = this.docJSON(), version = this.version;
      this.after = null;
      const body ={b: this.book, f: this.file, doc, base_mtime: this.mtime, ...(leaving ? {leaving: true} : {}), ...(force ? {force: true} : {})};
      this.saving = api("/api/book/piece", body).then(r => {
        this.mtime = r.mtime; this.savedVersion = Math.max(this.savedVersion, version);
        this.conflict = this.failed = null;
        clearTimeout(this.retry);
        if (leaving) this.touched = false;
        if (!this.dirty) this.unkeep();          // its own copy only: an older kept text waits for Put it back or Discard
        this.win.saved(this, r, doc);
        this.win.bar(this);
        return true;
      }, e => {
        const unsaved = version !== this.savedVersion;
        if (e.status === 404) { this.lostFile(doc, unsaved); return false; }
        if (!unsaved && leaving && this.closed) return false;        // only the snapshot was asked for: nothing is lost
        this.keep(doc);
        if (e.status === 409) { this.conflict = e.data?.current || {}; this.failed = null; }
        else {
          this.failed = e.status ? plain(e.message) : "Studio can't be reached";      // a TypeError from fetch: no answer at all
          clearTimeout(this.retry);
          if (!this.closed) this.retry = setTimeout(() => this.save(), RETRY);
        }
        if (this.closed) this.win.lost(this, e);
        else this.win.bar(this);
        return false;
      }).finally(() => {
        this.saving = null;
        const q = this.queued;
        this.queued = null;
        if (q) this.after = this.save(q);
        else this.settle();
        this.win.status();
      });
      this.win.status();
      return this.saving;
    }
    /* The piece's file is no longer in the book (a save answered 404): what isn't on disk becomes an orphan. The text
       kept is the newest: the editor's (typing may have gone on while the save was under way), or the one it closed with. */
    lostFile(doc, unsaved) {
      const first = !this.goneAway, latest = this.closed ? this.finalDoc || doc : this.docJSON();
      const pending = unsaved || this.dirty;
      this.goneAway = true;
      clearTimeout(this.timer); clearTimeout(this.retry);
      this.conflict = this.failed = null;
      this.strand();
      if (pending) this.orphan(latest);
      if (first) this.win.gone(this, pending);
      else this.win.bar(null);
    }
    /* this piece's unsaved text as an orphan: one row per piece, updated when called again */
    orphan(doc) {
      this.orphanAt = this.orphanAt || Date.now();
      orphans.add(this.book, {doc, title: this.name, kind: this.kind || this.entry?.kind, form: this.form, file: this.file, at: this.orphanAt, after: this.after_});
    }
    strand() { strand(this.book, this.file, {title: this.name, kind: this.kind, form: this.form, after: this.after_}, this.keepId); }
    /* settled: nothing waits for the disk any more */
    settle() { if (!this.saving && (this.closed || !this.dirty) && !(this.closed ? false : this.conflict || this.failed)) live.delete(this); }
    flush() { return this.save(); }
    /* the piece on disk is newer than the one here (the poll) */
    disk(mtime, form) {
      if (!this.text || this.closed || this.goneAway || this.saving || this.busy || mtime == null || this.mtime == null) return;
      if (mtime <= this.mtime + 1e-6 && (!form || form === this.form)) return;
      if (this.dirty || this.conflict) { if (!this.conflict) { this.conflict = {}; this.win.bar(this); } return; }
      this.reload(true);
    }
    /* takes in the piece as it is on disk: quietly (nothing unsaved here), or after Reload */
    async reload(quiet) {
      let p;
      try { p = await this.fetch(); }
      catch (e) { toast(e.message, true); return; }
      if (this.closed || !this.text) return;
      if (quiet && (this.dirty || this.saving)) { if (p.mtime > this.mtime + 1e-6) { this.conflict = p; this.win.bar(this); } return; }
      Object.assign(this.win.linked, p.linked || {});
      // Reload: the text it replaces stays offered (Put it back), not only in the undo history, so leaving keeps it
      const mine = quiet ? null : this.docJSON();
      if (mine && solid(BookText.editableDoc(mine)) !== solid(BookText.editableDoc(p.doc))) {
        rescue.put(this.book, this.file, {id: `reload-${Date.now()}`, doc: mine, at: Date.now(), title: this.name});
      }
      try { this.text.replaceDoc(p.doc, RELOAD, {history: !quiet}); }
      catch (e) { this.error = `This piece can't be opened in the editor: ${e.message}`; this.win.bar(this); return; }
      this.mtime = p.mtime; this.form = p.form; this.words = p.words || 0;
      this.version++; this.savedVersion = this.version;
      this.conflict = this.failed = null;
      this.unkeep();                          // its own copy; the text Reload replaced and older kept texts stay offered
      this.text.refresh();
      this.nextRescue(); this.win.status();
      this.settle();
    }
    /* Keep mine: saved over the disk's text. When that text came from this window's replace or restore (conflict.by), it
       goes into History first (a leaving save of the same text makes the snapshot), so it can be brought back. */
    async keepMine() {
      const by = this.conflict?.by;
      this.conflict = null; this.win.bar(this);
      if (by) {
        try { const cur = await this.fetch(); await api("/api/book/piece", {b: this.book, f: this.file, doc: cur.doc, base_mtime: cur.mtime, leaving: true}); }
        catch { /* not in History then; yours is still saved below */ }
      }
      return this.save({force: true});
    }
    /* a change like any other: saved over the disk's text, undo takes it back. Its copy goes once this piece keeps it */
    putBack() {
      const r = this.rescued;
      if (!r?.doc) return;
      this.text.replaceDoc(r.doc);
      this.keep(this.docJSON());
      rescue.drop(this.book, this.file, r.id);
      this.nextRescue();
    }
    async discardRescue() {
      const r = this.rescued;
      if (!r || !(await confirmDiscard(this.name, r.at))) return;
      rescue.drop(this.book, this.file, r.id);
      this.nextRescue();
    }
    setTitle(title) { this.text.replaceDoc(withTitle(this.docJSON(), title)); }
    /* leaves the piece: the last save is a leaving save; the view goes */
    close({save = true} = {}) {
      if (this.closed) return this.saving || Promise.resolve(true);
      if (save && this.text && this.conflict && this.dirty) {
        toast(`${this.name} changed outside the editor, so your version wasn't saved over it. It is kept and offered when you open the piece again.`);
      }
      clearTimeout(this.timer); clearTimeout(this.retry);
      if (this.text) {
        this.finalDoc = this.text.view.state.doc.toJSON();
        const v = this.text.view;
        places.set(`${this.book}/${this.file}`, {anchor: v.state.selection.anchor, head: v.state.selection.head, scroll: this.win.hosts.scroll.scrollTop});
      }
      this.closed = true;
      if (save && this.text && this.dirty) this.keep(this.finalDoc);       // kept until the leaving save is answered, should the window go first
      const done = save && this.text ? this.save({leaving: true}) : Promise.resolve(true);
      this.text?.destroy();
      this.settle();
      return done;
    }
    /* the window is closing: keep the text, and send it if it is small enough for a keepalive request */
    emergency() {
      if (!this.text || !this.dirty) return;
      const doc = this.docJSON();
      this.keep(doc);
      const body = JSON.stringify({b: this.book, f: this.file, doc, base_mtime: this.mtime, leaving: true});
      if (body.length < 60000) {
        try { fetch("/api/book/piece", {method: "POST", headers: {"Content-Type": "application/json"}, body, keepalive: true}); } catch { /* kept above */ }
      }
    }
  }

  /* ——— the window ——— */
  function mount(el, {book, file}) {
    unmount();
    const entries = book.contents.filter(e => e.file);
    const want = file && entries.some(e => e.file === file) ? file
      : [...entries].filter(e => !e.missing).sort((a, b) => (b.mtime || 0) - (a.mtime || 0))[0]?.file || entries[0]?.file || null;
    if (file && want !== file) toast(`There's no piece ${file} in this book`, true);
    if (want && location.hash !== bookHash(book.id, want)) history.replaceState(null, "", bookHash(book.id, want));
    state.bookFile = want;
    const showBinder = pref.get("bookBinder", innerWidth >= 1000 ? "1" : "0") === "1";
    el.innerHTML = `<div class="bw${showBinder ? "" : " nobinder"}">
      <aside class="bw-binder" aria-label="Pieces"></aside>
      <section class="bw-main">
        <div class="bw-bar" role="status" hidden></div>
        <div class="bw-scroll"><div class="bw-page">
          <div class="bw-col"><div class="bw-text"></div></div>
          <div class="bw-margin" aria-label="Notes and comments"></div>
          <div class="bw-over"></div>
        </div></div>
      </section>
      <aside class="bw-rail" hidden></aside>
      <footer class="bw-status"><button type="button" class="bw-tog" aria-pressed="${showBinder}" title="Show or hide the pieces · Ctrl+\\">Pieces</button>
        <span class="state" id="bw-state"></span><span class="bw-counts" id="bw-counts"></span></footer></div>`;
    const root = $(".bw", el);
    W = {book, root, piece: null, linked: {}, sources: [], today: book.days?.[todayKey()] || 0, frame: 0, drag: null, orphans: orphans.get(book.id),
      hosts: {page: $(".bw-page", root), text: $(".bw-text", root), margin: $(".bw-margin", root), over: $(".bw-over", root), scroll: $(".bw-scroll", root)},
      binder: $(".bw-binder", root), barEl: $(".bw-bar", root)};
    Object.assign(W, {ctx, bar, status, saved, lost, gone});
    look();
    renderBinder();
    wireBinder();
    $(".bw-tog", root).onclick = toggleBinder;
    loadSources();
    bar(null);
    tools("mount", W);
    if (want) openPiece(want, {push: false});
    else { W.hosts.text.innerHTML = `<p class="bw-none">This book has no pieces yet. Add one with <b>+ Chapter</b> in the list of pieces.</p>`; status(); }
  }

  function unmount() {
    if (!W) return;
    tools("unmount", W);              // the second pane closes first, with its own leaving save
    W.piece?.close();
    cancelAnimationFrame(W.frame); clearTimeout(W.countTimer);
    W = null;
  }

  const pending = () => [...live].some(p => p.dirty || p.saving || (!p.closed && (p.conflict || p.failed)));

  /* the book read again (the poll, or after a change made here) */
  function refresh(b) {
    if (!W || b.id !== W.book.id) return;
    const before_ = W.book.contents;
    const before = JSON.stringify({f: W.book.features, s: W.book.style_sheet, st: W.book.style?.fonts?.text});
    W.book = b; state.book = b;
    W.today = b.days?.[todayKey()] || 0;
    if (!W.drag) renderBinder();
    look();
    loadSources();
    const changed = JSON.stringify({f: b.features, s: b.style_sheet, st: b.style?.fonts?.text}) !== before;
    const s = W.split?.piece;           // the second pane (book-tools.js)
    if (s && !s.closed) {
      const e = b.contents.find(x => x.file === s.file);
      if (!e) { strandGone(s, before_); tools("splitGone"); bar(null); }
      else { s.disk(e.mtime, e.form || "prose"); if (changed) s.text?.refresh(); }
    }
    tools("refresh", b);
    const p = W.piece;
    if (p) {
      const e = b.contents.find(x => x.file === p.file);
      if (!e) return pieceGone(p, before_);
      p.disk(e.mtime, e.form || "prose");
      if (changed) p.text?.refresh();
    }
    status();
  }
  /* the open piece left the book (another window moved it to the trash): unsaved text becomes an orphan to keep */
  function pieceGone(p, contents) {
    strandGone(p, contents);
    W.piece = null;
    openFirst();
  }
  function strandGone(p, contents) {
    const files = contents.filter(x => x.file), k = files.findIndex(x => x.file === p.file);
    if (p.after_ === undefined) p.after_ = files[k - 1]?.file;
    const already = p.goneAway;
    p.goneAway = true;
    p.strand();
    if (p.text && p.dirty) p.orphan(p.docJSON());        // its one row: made now, or brought up to date if a save made it
    else if (!already && !p.orphanAt) toast(`${p.name} is no longer in this book`);
    p.close({save: false});
  }
  /* a save found the piece gone: its book may be gone too */
  async function gone(piece, unsaved) {
    let b = null;
    try { b = await api("/api/book?b=" + encodeURIComponent(piece.book)); } catch { /* no book */ }
    const here = W && W.book.id === piece.book;
    if (!b) {
      if (unsaved) toast(`${piece.name} wasn't saved: its book is no longer in Books. Studio keeps the text and offers it when the book is back in Books under its old folder name (from Books/.trash).`, true);
      return;
    }
    if (!here) { if (unsaved) toast(`${piece.name} is no longer in ${b.title}. The text you wrote in it is offered when you open the book.`, true); return; }
    W.orphans = orphans.get(piece.book);
    refresh(b);
    bar(W.piece);
  }
  async function keepOrphan(o) {
    const w = W, after = o.after && w.book.contents.some(e => e.file === o.after) ? o.after : undefined;
    if (w.keeping) return;
    w.keeping = true;
    $$("[data-act^=orphan]", w.barEl).forEach(b => { b.disabled = true; });
    try {
      const n = await api("/api/book/piece/new", {b: w.book.id, kind: bookLists.pieces.includes(o.kind) ? o.kind : "chapter",
        form: bookLists.forms.includes(o.form) ? o.form : "prose", title: titleOf(o.doc), ...(after ? {after} : {})});
      await api("/api/book/piece", {b: w.book.id, f: n.file, doc: o.doc, base_mtime: n.mtime});
      orphans.drop(w.book.id, o.at);
      if (w !== W) return;
      W.orphans = orphans.get(w.book.id);
      await reloadBook();
      openPiece(n.file);
      toast(`Kept as ${titleOf(o.doc) || "a new " + pieceKindName(o.kind || "chapter").toLowerCase()}`);
    } catch (e) { toast(e.message, true); }
    finally { w.keeping = false; if (w === W) bar(null); }
  }
  /* 5: discarding a kept text is the author's choice, asked in Studio's own dialog */
  function confirmDiscard(title, at) {
    return new Promise(resolve => {
      let yes = false;
      openDialog(`<form><h2>Discard the text?</h2>
        <p class="hint" style="margin-top:-12px">What you wrote in “${esc(title || "this piece")}” on ${esc(when(new Date(at).toISOString()))} is kept only in Studio. Once discarded it can't be brought back.</p>
        <div class="foot"><button type="button" class="btn quiet" data-close>Keep it</button><button type="submit" class="btn solid">Discard</button></div></form>`,
      async () => { yes = true; });
      onDialogClose(() => resolve(yes));
    });
  }
  async function reloadBook() {
    if (!W) return;
    try { refresh(await api("/api/book?b=" + encodeURIComponent(W.book.id))); } catch (e) { toast(e.message, true); }
  }
  async function loadSources() {
    const w = W;
    try {
      const list = await api("/api/book/sources?b=" + encodeURIComponent(w.book.id));
      if (w === W && JSON.stringify(list) !== JSON.stringify(w.sources)) { w.sources = list; w.piece?.text?.refresh(); w.split?.piece?.text?.refresh(); }
    } catch { /* a sources.json that can't be read: citations show their keys */ }
  }
  /* the look's text font for the text and the notes */
  function look() {
    const f = W.book.style?.fonts?.text, page = W.hosts.page;
    page.style.setProperty("--bk-font", f?.family ? `${fontStack(f.family)}, var(--serif)` : "var(--serif)");
    page.style.setProperty("--bk-weight", String(+f?.weight || 400));
    page.lang = W.book.language || "en";
  }

  function ctx(piece) {
    const w = W;
    return {
      language: w.book.language || "en",
      features: () => w.book.features || {},
      sheet: () => w.book.style_sheet || {},
      sources: () => w.sources,
      linked: () => w.linked,
      noteStart: () => BookText.noteStart(w.book.contents, piece.file, w.book.features?.noteNumbering),
      imageUrl: src => /^\.\.\/images\/[^/\\]+$/.test(src || "") ? `/bookfiles/${encodeURIComponent(w.book.id)}/images/${encodeURIComponent(src.slice(10))}` : null,
      onChange: trs => piece.changed(trs),
      pickImage: () => pickImage(w.book.id),
      pickPoem: () => pickPoem(w),
      say: (msg, bad) => toast(msg, bad),
      addSource: () => tools("addSource"),          // the citation form's Add source: the rail's Sources panel
    };
  }

  /* opens a piece in place (the binder, new pieces): the URL follows; Back goes through route() */
  async function openPiece(file, {push = true, selectTitle = false} = {}) {
    if (!W) return;
    const w = W, old = w.piece, there = w.split?.piece;
    // open in the second pane, or being opened there: it is shown there (one piece, one editor)
    if (BookTools.whereOpen(file, {split: there && !there.closed ? there.file : null, splitPending: w.split?.pending?.file}) === "split") { there?.text?.focus(); return; }
    if (old && old.file === file && old.text) {
      if (w.pending) { w.pending = null; markCurrent(file); state.bookFile = file; if (push) history.pushState(null, "", bookHash(w.book.id, file)); }
      old.text.focus();
      return;
    }
    const piece = new Piece(w, file);
    piece.after_ = (() => { const files = w.book.contents.filter(x => x.file), k = files.findIndex(x => x.file === file); return files[k - 1]?.file; })();
    state.bookFile = file;
    if (push) history.pushState(null, "", bookHash(w.book.id, file));
    w.pending = piece;
    markCurrent(file);
    let p;
    const leaving = [...live].find(x => x.closed && x.saving && x.book === w.book.id && x.file === file);
    while (leaving?.saving) await leaving.saving.catch(() => {});      // its leaving save first, so what opens is what was left
    try { p = await piece.fetch(); }
    catch (e) { p = null; piece.error = e.message; }
    if (w !== W || w.pending !== piece) { live.delete(piece); return; }
    old?.close();
    w.piece = piece; w.pending = null;
    w.hosts.text.replaceChildren(); w.hosts.margin.replaceChildren(); w.hosts.over.replaceChildren();
    if (p) piece.attach(p); else live.delete(piece);
    bar(piece);
    document.title = `${piece.name} — ${w.book.title}`;
    const place = places.get(`${w.book.id}/${file}`), v = piece.text?.view;
    if (v) {
      try {
        if (selectTitle && v.state.doc.firstChild?.type.name === "title") {
          v.dispatch(v.state.tr.setSelection(PM.TextSelection.create(v.state.doc, 1, v.state.doc.firstChild.nodeSize - 1)));
        } else if (place) {
          const max = v.state.doc.content.size;
          v.dispatch(v.state.tr.setSelection(PM.TextSelection.create(v.state.doc, Math.min(place.anchor, max), Math.min(place.head, max))));
        }
      } catch { /* a place the text no longer has */ }
      w.hosts.scroll.scrollTop = selectTitle ? 0 : place?.scroll || 0;
      if (!$("#dlg").open) v.focus();
    }
    status();
    tools("open", piece);
  }
  function openFirst() {
    const first = W?.book.contents.find(e => e.file && e.file !== W.split?.piece?.file);
    if (first) openPiece(first.file);
    else if (W) { W.hosts.text.innerHTML = `<p class="bw-none">This book has no pieces yet. Add one with <b>+ Chapter</b> in the list of pieces.</p>`; bar(null); status(); }
  }

  /* ——— the bar over the text: changed outside, not saved, kept text, can't open ——— */
  /* the conflict after this window's own replace or restore, when something was typed meanwhile after all */
  const CHANGED_BY = {
    replace: "The replace changed this piece while you were typing. Reload shows the replaced text; Keep mine keeps yours, and the replaced text stays in History.",
    restore: "The restore changed this piece while you were typing. Reload shows the restored text; Keep mine keeps yours, and the restored text stays in History.",
  };
  function bar(piece) {
    if (!W) return;
    const P = piece?.win?.main === W ? piece.win : W;     // the second pane (book-tools.js) has a bar of its own
    if (piece && piece !== P.piece) return;
    if (P === W) W.orphans = orphans.get(W.book.id);
    const el = P.barEl, p = piece || P.piece, o = P === W ? W.orphans[0] : null;
    const row = (text, acts) => `<div class="bw-bar-row"><span class="bw-bar-t">${text}</span>${acts}</div>`;
    const back = o && W.book.contents.some(e => e.file === o.file);      // the piece itself is in the book again (from the trash)
    const more = n => n > 1 ? ` ${n - 1} more ${n === 2 ? "is" : "are"} kept.` : "";
    let html = o ? row((back ? `Text you wrote in “${esc(o.title || "a piece")}” on ${esc(when(new Date(o.at).toISOString()))} wasn't saved.`
      : `“${esc(o.title || "A piece")}” is no longer in this book. The text you wrote in it wasn't saved.`) + more(W.orphans.length),
      `<button type="button" class="btn small quiet" data-act="orphan-drop">Discard it…</button><button type="button" class="btn small" data-act="orphan-keep">Keep as a new piece</button>`) : "";
    if (p?.error) html += row(esc(p.error), "");
    else if (p?.conflict) html += row(CHANGED_BY[p.conflict.by] || "This piece changed outside the editor.",
      `<button type="button" class="btn small" data-act="reload">Reload</button><button type="button" class="btn small" data-act="keep">Keep mine</button>`);
    else if (p?.failed) html += row(`Not saved: ${esc(p.failed)}. Studio tries again every few seconds; the text stays here.`,
      `<button type="button" class="btn small" data-act="retry">Try now</button>`);
    else if (p?.rescued) html += row(`Text you wrote here on ${esc(when(new Date(p.rescued.at).toISOString()))} wasn't saved.`,
      `<button type="button" class="btn small quiet" data-act="discard">Discard it…</button><button type="button" class="btn small" data-act="putback">Put it back</button>`);
    el.innerHTML = html;
    el.hidden = !html;
    if (W.keeping) $$("[data-act^=orphan]", el).forEach(b => { b.disabled = true; });
    el.onclick = async e => {
      const act = e.target.closest("[data-act]:not(:disabled)")?.dataset.act;
      if (!act || !W) return;
      if (act === "orphan-keep" && o) return keepOrphan(o);
      if (act === "orphan-drop" && o) {
        if (await confirmDiscard(o.title, o.at) && W) { orphans.drop(W.book.id, o.at); bar(null); }
        return;
      }
      if (P.piece !== p || !p) return;
      if (act === "reload") p.reload(false);
      if (act === "keep") p.keepMine();
      if (act === "retry") p.save();
      if (act === "putback") p.putBack();
      if (act === "discard") p.discardRescue();
    };
  }
  function lost(piece, e) {
    toast(`${piece.name} wasn't saved (${e.status === 409 ? "it changed outside the editor" : e.status ? plain(e.message) : "Studio can't be reached"}). The text is kept: open the piece to put it back.`, true);
  }

  /* ——— the status bar: saved or not, words in the piece, words today ——— */
  /* the piece being written in: the second pane's when that was written in last (book-tools.js) */
  const written = () => { const a = window.BookTools?.activePiece?.(); return a && !a.closed && a.win?.main === W ? a : W.piece; };
  function status() {
    if (!W || W.frame) return;
    W.frame = requestAnimationFrame(() => {
      if (!W) return;
      W.frame = 0;
      const p = written(), st = $("#bw-state", W.root);
      if (!st) return;
      const say = !p?.text ? "" : p.conflict || p.failed ? "Not saved" : p.saving ? "Saving…" : p.dirty ? "Unsaved changes" : "Saved";
      st.textContent = say;
      st.classList.toggle("dirty", say === "Unsaved changes" || say === "Not saved");
      tools("state", p, say);
      if (!W.countTimer) W.countTimer = setTimeout(counts, W.counted ? 400 : 0);
    });
  }
  /* words in the piece; words today and the goal */
  function counts() {
    if (!W) return;
    W.countTimer = 0; W.counted = true;
    const p = written(), el = $("#bw-counts", W.root);
    if (!el) return;
    if (!p?.text) { el.textContent = ""; return; }
    const words = p.text.words(), today = W.today + Math.max(0, words - p.words), goal = +W.book.goals?.daily || 0;
    el.textContent = `${bookWords(words)} · ${goal ? `${bookCount(today)} of ${bookCount(goal)} words today` : `${bookWords(today)} today`}`;
    tools("counts", {today, goal});
  }
  /* a save went through: the piece's words in the binder and the words written today */
  function saved(piece, r, doc) {
    const gained = (r.counts?.words ?? piece.words) - piece.words;
    piece.words = r.counts?.words ?? piece.words;
    if (!W || (piece.win !== W && piece.win.main !== W)) return;
    tools("saved", piece, r);
    if (gained > 0) W.today += gained;
    const e = W.book.contents.find(x => x.file === piece.file);
    if (e) { Object.assign(e, r.counts || {}, {mtime: r.mtime, title: titleOf(doc)}); if (!W.drag) renderBinder(); }
    status();
  }

  /* ——— the binder ——— */
  function renderBinder() {
    const b = W.book, host = W.binder, list = $(".bb-scroll", host), scroll = list?.scrollTop || 0;
    const focused = W.focusKey || document.activeElement?.closest?.(".bb-row")?.dataset.key;
    W.focusKey = null;
    const cur = W.pending?.file || W.piece?.file;
    let inPart = false;
    const row = (e, i, group) => {
      if (group !== "Body") inPart = false;
      const isPart = e.kind === "part", indent = inPart && !isPart && group === "Body";
      if (isPart) inPart = true;
      const cls = `bb-row${e.auto ? " auto" : ""}${isPart ? " part" : ""}${indent ? " in" : ""}${e.file && e.file === cur ? " cur" : ""}${e.file && !e.title ? " untitled" : ""}`;
      if (e.auto) {
        return `<li class="${cls}" data-i="${i}" data-key="auto:${esc(e.auto)}" draggable="true"><span class="bb-a" tabindex="0" title="Made by Studio from the book's details and text">
          <span class="bk-dot" aria-hidden="true"></span><span class="bb-t">${esc(autoPageName(b, e.auto))}</span><span class="bb-w">auto</span></span></li>`;
      }
      const kind = pieceKindName(e.kind) + (e.form && e.form !== "prose" ? ` · ${e.form}` : "") + (e.status ? ` · ${e.status}` : "");
      return `<li class="${cls}" data-i="${i}" data-file="${esc(e.file)}" data-key="${esc(e.file)}" draggable="true"><a class="bb-a" href="${bookHash(b.id, e.file)}" title="${esc(kind)}"${e.file === cur ? ' aria-current="page"' : ""}>
        <span class="bk-dot ${esc(e.status || "")}" aria-hidden="true"></span><span class="bb-t">${esc(pieceTitle(e))}</span>
        <span class="bb-w">${e.missing ? `<span class="bad">missing</span>` : e.unreadable ? `<span class="bad" title="Not UTF-8 text: its file is left as it is">unreadable</span>` : esc(bookCount(e.words))}</span></a></li>`;
    };
    // auto pages of a feature that is off are left out of the list; they stay in book.json and are back when it is on
    const groups = bookGroups(b.contents).map(([name, items]) => [name, items.filter(e => !e.auto || bookAutoOn(b, e.auto))])
      .filter(([, items]) => items.length).map(([name, items]) => {
      const words = items.reduce((n, e) => n + (e.words || 0), 0), pieces = items.filter(e => e.file).length;
      return `<section class="bb-group"><div class="bb-ghead"><h2 class="label">${esc(name)}</h2><span class="label">${pieces ? esc(bookCount(words)) : ""}</span></div>
        <ol class="bb-list">${items.map(e => row(e, b.contents.indexOf(e), name)).join("")}</ol></section>`;
    }).join("");
    host.innerHTML = `<div class="bb-scroll"><div class="bb-head"><div class="bb-k"><span class="kicker"><a href="#/books">Books</a> · ${esc(bookKindName(b.kind))}</span>
        <a class="kicker bb-set" href="${bookTabHash(b.id, "details")}">Settings</a></div>
        <p class="bb-book">${esc(b.title)}</p><p class="bb-total">${esc(bookWords(b.contents.reduce((n, e) => n + (e.words || 0), 0)))}</p></div>
      <nav class="bb-groups">${groups || `<p class="bb-empty">Nothing in this book yet.</p>`}</nav></div>
      <div class="bb-foot"><button type="button" class="btn small" data-new="chapter"><span class="plus">+</span>Chapter</button>
        <button type="button" class="btn small quiet" data-add aria-haspopup="menu">Add…</button></div>`;
    const scroller = $(".bb-scroll", host);
    // focus and nudges stop below the head, with a little air
    scroller.style.scrollPaddingTop = Math.ceil($(".bb-head", host).getBoundingClientRect().height) + 8 + "px";
    scroller.scrollTop = scroll;
    if (focused) $$(".bb-row", host).find(r => r.dataset.key === focused)?.querySelector(".bb-a")?.focus();
  }
  function markCurrent(file) {
    for (const r of $$(".bb-row", W.binder)) {
      const on = !!file && r.dataset.file === file;
      r.classList.toggle("cur", on);
      const a = $("a.bb-a", r);
      if (a) { if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); }
    }
  }
  function toggleBinder() {
    if (!W) return;
    const hide = !W.root.classList.contains("nobinder");
    W.root.classList.toggle("nobinder", hide);
    $(".bw-tog", W.root).setAttribute("aria-pressed", String(!hide));
    pref.set("bookBinder", hide ? "0" : "1");
    tools("binder", !hide);           // shown: only when every text keeps its 360 px
  }

  function wireBinder() {
    const host = W.binder;
    host.addEventListener("click", e => {
      if (e.target.closest("[data-new]")) return newPiece(e.target.closest("[data-new]").dataset.new);
      if (e.target.closest("[data-add]")) return addMenu(e.target.closest("[data-add]"));
      const a = e.target.closest("a.bb-a");
      if (a && e.button === 0 && e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey) {       // Alt-click: in the second pane
        e.preventDefault();
        return tools("split", a.closest(".bb-row").dataset.file);
      }
      if (!a || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      openPiece(a.closest(".bb-row").dataset.file);
    });
    host.addEventListener("contextmenu", e => {
      const row = e.target.closest(".bb-row");
      if (row) rowMenu(e, +row.dataset.i);
    });
    host.addEventListener("keydown", e => {
      const row = e.target.closest(".bb-row");
      if (!row) return;
      if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); nudge(+row.dataset.i, e.key === "ArrowUp" ? -1 : 1); }
      else if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
        e.preventDefault();
        const r = row.getBoundingClientRect();
        rowMenu({clientX: r.left + 24, clientY: r.bottom, preventDefault() {}, stopPropagation() {}}, +row.dataset.i);
      }
    });
    /* drag and drop: before or after a row; after a part is into it (its pieces are the ones that follow it) */
    host.addEventListener("dragstart", e => {
      const row = e.target.closest(".bb-row");
      if (!row) return;
      W.drag = {span: span(+row.dataset.i), over: null};
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", $(".bb-t", row).textContent);
      requestAnimationFrame(() => W?.drag && $$(".bb-row", host).forEach(r => { const i = +r.dataset.i; r.classList.toggle("dragging", i >= W.drag.span[0] && i <= W.drag.span[1]); }));
    });
    host.addEventListener("dragover", e => {
      if (!W?.drag) return;
      const row = e.target.closest(".bb-row");
      if (!row) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      const r = row.getBoundingClientRect(), after = e.clientY > r.top + r.height / 2, i = +row.dataset.i;
      W.drag.over = {i, after};
      $$(".bb-row.drop-before, .bb-row.drop-after", host).forEach(x => { if (x !== row) x.classList.remove("drop-before", "drop-after"); });
      row.classList.toggle("drop-before", !after); row.classList.toggle("drop-after", after);
    });
    host.addEventListener("drop", e => {
      if (!W?.drag) return;
      e.preventDefault();
      const {span: s, over} = W.drag;
      endDrag();
      if (over) move(s, over.i + (over.after ? 1 : 0));
    });
    host.addEventListener("dragend", endDrag);
  }
  function endDrag() {
    if (!W) return;
    W.drag = null;
    $$(".bb-row", W.binder).forEach(r => r.classList.remove("dragging", "drop-before", "drop-after"));
  }
  /* an entry with what belongs to it: a part takes the pieces after it, up to the next part or the back matter */
  function span(i) {
    const c = W.book.contents;
    if (c[i]?.kind !== "part") return [i, i];
    const back = bookGroups(c)[2][1][0], end = back ? c.indexOf(back) : c.length;
    let j = i + 1;
    while (j < end && c[j].kind !== "part") j++;
    return [i, j - 1];
  }
  function move([a, z], to) {
    if (to >= a && to <= z + 1) return;
    const list = [...W.book.contents], moving = list.splice(a, z - a + 1);
    list.splice(to > z ? to - moving.length : to, 0, ...moving);
    saveContents(list);
  }
  /* Alt+Up and Alt+Down: one place up or down in the list as shown (a part with its pieces), past auto pages left out */
  function nudge(i, dir) {
    const c = W.book.contents, s = span(i), e = c[i], shown = k => !c[k].auto || bookAutoOn(W.book, c[k].auto);
    W.focusKey = e.file || "auto:" + e.auto;
    let k = dir < 0 ? s[0] - 1 : s[1] + 1;
    while (k >= 0 && k < c.length && !shown(k)) k += dir;
    if (k < 0 || k >= c.length) return;
    move(s, dir < 0 ? k : k + 1);
  }
  async function saveContents(list, msg) {
    const w = W;
    try {
      const b = await api("/api/book/update", {b: w.book.id, fields: {contents: list}});
      if (w === W) refresh(b);
      if (msg) toast(msg);
      return b;
    } catch (e) { toast(e.message, true); if (w === W) renderBinder(); throw e; }
  }
  /* changes the entry with this file as the book is now (the poll may have moved it since the menu opened) */
  const setEntry = (file, fields, msg) => {
    if (!W.book.contents.some(e => e.file === file)) { toast("That piece is no longer in this book", true); return Promise.reject(new Error("gone")); }
    return saveContents(W.book.contents.map(e => e.file === file ? {...e, ...fields} : e), msg);
  };

  /* ——— the binder's menus ——— */
  function rowMenu(ev, i) {
    const b = W.book, e = b.contents[i];
    if (!e) return;
    if (e.auto) {
      return StudioMenu.open(ev, [{label: "Remove from the book", act: () => {
        const c = W.book.contents, k = c.findIndex(x => x.auto === e.auto);
        if (k >= 0) saveContents(c.filter((x, j) => j !== k), `${autoPageName(b, e.auto)} is no longer in the book`).catch(() => {});
      }}]);
    }
    const next = b.contents.slice(i + 1).find(x => x.file), open = W.piece?.file === e.file && W.piece.text;
    StudioMenu.open(ev, [
      {label: "Rename…", act: () => renameDialog(e)},
      {label: "Kind", items: bookLists.pieces.map(k => ({label: pieceKindName(k), checked: e.kind === k, act: () => e.kind !== k && setEntry(e.file, {kind: k}, `${pieceTitle(e)} is now a ${pieceKindName(k).toLowerCase()}`).catch(() => {})}))},
      {label: "Form", items: bookLists.forms.map(f => ({label: f[0].toUpperCase() + f.slice(1), checked: (e.form || "prose") === f, act: () => (e.form || "prose") !== f && setForm(e.file, f)}))},
      {label: "Status", items: BOOK_STATUSES.map(s => ({label: s[0].toUpperCase() + s.slice(1), checked: e.status === s, act: () => e.status !== s && setEntry(e.file, {status: s}).catch(() => {})}))},
      "-",
      {label: "Duplicate", act: () => duplicate(e)},
      {label: "Split here", disabled: !open, act: () => splitHere(e)},
      {label: "Merge with next", disabled: !next, act: () => mergeNext(e, next)},
      "-",
      {label: "Move to trash…", danger: true, act: () => trashPiece(e)},
    ]);
  }
  function addMenu(btn) {
    const r = btn.getBoundingClientRect(), have = new Set(W.book.contents.map(e => e.auto).filter(Boolean));
    const autos = bookLists.autos.filter(a => !have.has(a) && bookAutoOn(W.book, a));      // not one that would be left out
    StudioMenu.open({clientX: r.left, clientY: r.top - 8, preventDefault() {}, stopPropagation() {}}, [
      ...bookLists.pieces.filter(k => k !== "chapter").map(k => ({label: pieceKindName(k), act: () => newPiece(k)})),
      ...(autos.length ? ["-", {label: "Page made by Studio", items: autos.map(a => ({label: autoPageName(W.book, a), act: () => addAuto(a)}))}] : []),
    ]);
  }
  /* A new piece. Front matter goes after the front matter there is; a body piece after the open piece when that is in
     the body, else at the end of the body; back matter before the closing pages (the server's default). */
  async function newPiece(kind) {
    const w = W, c = w.book.contents, count = c.filter(e => e.kind === kind).length + 1;
    const title = kind === "chapter" ? `Chapter ${count}` : kind === "part" ? `Part ${count}` : UNTITLED.has(kind) ? "" : pieceKindName(kind);
    const [front, body] = bookGroups(c), cur = w.piece?.file;
    let after, at = null;
    if (BOOK_FRONT.has(kind)) { after = front[1].filter(x => x.file).at(-1)?.file; if (!after) at = front[1].length; }
    else if (!BOOK_BACK.has(kind)) {
      after = cur && body[1].some(e => e.file === cur) ? cur : body[1].filter(x => x.file).at(-1)?.file;
      if (!after) at = front[1].length;
    }
    try {
      await w.piece?.flush();
      const n = await api("/api/book/piece/new", {b: w.book.id, kind, title, ...(after ? {after} : {})});
      let b = await api("/api/book?b=" + encodeURIComponent(w.book.id));
      if (at != null) {
        const list = b.contents.filter(e => e.file !== n.file);
        list.splice(at, 0, b.contents.find(e => e.file === n.file));
        b = await api("/api/book/update", {b: w.book.id, fields: {contents: list}});
      }
      if (w !== W) return;
      refresh(b);
      openPiece(n.file, {selectTitle: !!title});
    } catch (e) { toast(e.message, true); }
  }
  /* a page made by Studio: the title pages in their order at the start, the contents after the front matter, the rest at the end */
  function addAuto(a) {
    const list = [...W.book.contents], order = ["half-title", "title-page", "copyright"], k = order.indexOf(a);
    let at = list.length;
    if (k >= 0) { at = 0; while (at < list.length && order.slice(0, k).includes(list[at].auto)) at++; }
    else if (a === "toc") at = bookGroups(list)[0][1].length;
    list.splice(at, 0, {auto: a});
    return saveContents(list, `${autoPageName(W.book, a)} is in the book`).catch(() => {});
  }
  function renameDialog(e) {
    const w = W;
    openDialog(`<form><h2>Rename</h2>
      <label><span class="label">Title</span><input class="input big" name="title" value="${esc(e.title || "")}" autocomplete="off" placeholder="${esc(pieceKindName(e.kind))}"></label>
      <p class="hint" style="margin-top:-12px">The title is the first line of the piece. Its file stays ${esc(e.file)}.</p>
      <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Rename</button></div></form>`,
    async f => {
      const title = String(f.get("title") || "").replace(/\s+/g, " ").trim();
      if (w !== W) return;
      if (w.piece?.file === e.file && w.piece.text) { w.piece.setTitle(title); await w.piece.flush(); return; }
      const p = await api(`/api/book/piece?b=${encodeURIComponent(w.book.id)}&f=${encodeURIComponent(e.file)}`);
      await api("/api/book/piece", {b: w.book.id, f: e.file, doc: withTitle(p.doc, title), base_mtime: p.mtime});
      await reloadBook();
    });
  }
  /* a piece's form changes how its file is read: the open piece is saved first and read again after */
  async function setForm(file, form) {
    const e = W.book.contents.find(x => x.file === file), p = W.piece?.file === file ? W.piece : null;
    if (!e) return;
    if (p && !(await p.flush())) { toast("Save the piece first: it has changes that aren't on disk.", true); return; }
    try { await setEntry(file, {form}, `${pieceTitle(e)} is now ${form}`); } catch { return; }
    if (p && p === W?.piece) p.reload(true);
  }
  /* Duplicate: a new piece of the same kind and form right after it, holding the same text (title + " (copy)") */
  async function duplicate(e) {
    const w = W;
    try {
      if (w.piece?.file === e.file && !(await w.piece.flush())) throw new Error("The piece has changes that aren't on disk yet.");
      const p = await api(`/api/book/piece?b=${encodeURIComponent(w.book.id)}&f=${encodeURIComponent(e.file)}`);
      const title = p.title ? `${p.title} (copy)` : "";
      const n = await api("/api/book/piece/new", {b: w.book.id, kind: e.kind, form: e.form || "prose", title, after: e.file});
      await api("/api/book/piece", {b: w.book.id, f: n.file, doc: title ? withTitle(p.doc, title) : p.doc, base_mtime: n.mtime});
      if (e.status && e.status !== "idea") {
        const b = await api("/api/book?b=" + encodeURIComponent(w.book.id));
        await api("/api/book/update", {b: w.book.id, fields: {contents: b.contents.map(x => x.file === n.file ? {...x, status: e.status} : x)}});
      }
      if (w !== W) return;
      await reloadBook();
      toast(`Duplicated as ${title || pieceKindName(e.kind)}`);
      openPiece(n.file);
    } catch (err) { toast(err.message, true); }
  }
  /* Split here: from the cursor on, the text goes to a new piece right after this one (a ## heading at the cut becomes its
     title). The new piece is written first; only then does the text leave this one, as an edit undo can take back. */
  async function splitHere(e) {
    const w = W, piece = w.piece;
    if (!piece?.text || piece.file !== e.file) return;
    const view = piece.text.view;
    piece.text.lock(true);
    piece.busy = true;
    let made = null;
    try {
      if (!(await piece.flush())) throw new Error("The piece has changes that aren't on disk yet.");
      const state = view.state, {$from} = state.selection, tr = state.tr;
      let cut;
      if ($from.depth === 0) cut = $from.pos;
      else if ($from.depth === 1 && $from.parentOffset === 0) cut = $from.before(1);
      else if ($from.depth === 1 && $from.parentOffset === $from.parent.content.size) cut = $from.after(1);
      else if ($from.depth === 1 && $from.parent.type.name === "paragraph") { tr.split($from.pos); cut = $from.pos + 1; }
      else cut = $from.after(1);
      const doc = tr.doc, head = doc.cut(0, cut), restContent = doc.content.cut(cut).toJSON() || [];
      const headText = head.content.toJSON()?.filter(n => n.type !== "title" && solid({content: [n]}) !== '{"content":[]}') || [];
      if (!headText.length || !restContent.some(n => !(n.type === "paragraph" && !(n.content || []).length))) {
        throw new Error("Put the cursor where the new piece should start, with text before and after it.");
      }
      let title = "";
      if (restContent[0]?.type === "heading") {
        const h = restContent.shift();
        restContent.unshift({type: "title", content: h.content});
        title = (h.content || []).map(n => n.text || "").join("").replace(/\s+/g, " ").trim();
      }
      made = await api("/api/book/piece/new", {b: w.book.id, kind: e.kind, form: e.form || "prose", title, after: e.file});
      await api("/api/book/piece", {b: w.book.id, f: made.file, doc: {type: "doc", attrs: doc.attrs, content: restContent}, base_mtime: made.mtime});
      if (e.status && e.status !== "idea") {
        const b = await api("/api/book?b=" + encodeURIComponent(w.book.id));
        await api("/api/book/update", {b: w.book.id, fields: {contents: b.contents.map(x => x.file === made.file ? {...x, status: e.status} : x)}});
      }
      made = null;                      // the new piece holds the rest: now it can leave this one
      piece.text.lock(false);
      if (view.state !== state) throw new Error("The piece changed meanwhile: its text is in both pieces now.");
      tr.delete(cut, tr.doc.content.size);
      if (!tr.doc.childCount || tr.doc.lastChild.type.name === "title") tr.insert(tr.doc.content.size, BookSchema.nodes.paragraph.create());
      view.dispatch(tr.scrollIntoView());
      await piece.flush();
      await reloadBook();
      toast(`Split: the rest is in ${title || "a new " + pieceKindName(e.kind).toLowerCase()}`);
    } catch (err) {
      toast(err.message, true);
      if (made) api("/api/book/piece/delete", {b: w.book.id, f: made.file}).then(reloadBook).catch(() => {});
    } finally { piece.busy = false; if (piece.text && !piece.closed) piece.text.lock(false); }
  }
  /* Merge with next: the next piece's text goes at the end of this one (its title becoming a ## heading); only when that
     is saved does the next piece's file move to the trash. */
  async function mergeNext(e, next) {
    const w = W;
    if (!confirm(`Merge “${pieceTitle(e)}” with “${pieceTitle(next)}”?\n\nThe text of ${pieceTitle(next)} goes at the end of ${pieceTitle(e)}, its title becoming a heading, and its file moves to Books/.trash.`)) return;
    try {
      if (w.piece?.file === next.file) {
        const closing = w.piece;
        await openPiece(e.file);
        if (!(await closing.save())) throw new Error(`${pieceTitle(next)} has changes that couldn't be saved; nothing was merged.`);
      }
      const open = W.piece?.file === e.file ? W.piece : null;
      if (open && !(await open.flush())) throw new Error("The piece has changes that aren't on disk yet.");
      const get = f => api(`/api/book/piece?b=${encodeURIComponent(w.book.id)}&f=${encodeURIComponent(f)}`);
      const [a, b] = await Promise.all([get(e.file), get(next.file)]);
      const tail = (b.doc.content || []).map((n, k) => k === 0 && n.type === "title" ? {type: "heading", attrs: {level: 2}, content: n.content} : n);
      if (!tail.length) throw new Error(`${pieceTitle(next)} is empty: move it to the trash instead.`);
      if (open && open.text) {
        const v = open.text.view, frag = PM.Fragment.fromJSON(BookSchema, tail);
        v.dispatch(v.state.tr.insert(v.state.doc.content.size, frag));
        if (!(await open.flush())) throw new Error("The merged text couldn't be saved; nothing was moved to the trash.");
      } else {
        await api("/api/book/piece", {b: w.book.id, f: e.file, doc: {...a.doc, content: [...(a.doc.content || []), ...tail]}, base_mtime: a.mtime});
      }
      await api("/api/book/piece/delete", {b: w.book.id, f: next.file});
      await reloadBook();
      toast(`Merged: ${pieceTitle(next)} is now part of ${pieceTitle(e)}`);
    } catch (err) { toast(err.message, true); }
  }
  async function trashPiece(e) {
    const w = W;
    if (!confirm(`Move “${pieceTitle(e)}” to the trash?\n\nIts file moves to Books/.trash, with its history in drafts/. Move it back to restore it.`)) return;
    try {
      if (w.piece?.file === e.file) {
        const files = w.book.contents.filter(x => x.file), k = files.findIndex(x => x.file === e.file);
        const other = files[k - 1] || files[k + 1];
        const closing = w.piece;
        if (other) await openPiece(other.file);
        else { w.piece = null; await closing.close(); w.hosts.text.replaceChildren(); w.hosts.margin.replaceChildren(); }
        if (!(await closing.save())) throw new Error("Its last changes couldn't be saved, so it stays.");
      }
      await api("/api/book/piece/delete", {b: w.book.id, f: e.file});
      strand(w.book.id, e.file, {title: pieceTitle(e), kind: e.kind, form: e.form});
      await reloadBook();
      if (W && !W.piece) openFirst();
      toast(`Moved “${pieceTitle(e)}” to the trash`);
    } catch (err) { toast(err.message, true); }
  }

  /* ——— pickers ——— */
  function pickImage(book) {
    return new Promise((resolve, reject) => {
      const input = Object.assign(document.createElement("input"), {type: "file", accept: "image/png,image/jpeg,image/gif,image/webp"});
      input.addEventListener("cancel", () => resolve(null));
      input.addEventListener("change", async () => {
        const f = input.files[0];
        if (!f) return resolve(null);
        try { resolve((await api("/api/book/image", {b: book, name: f.name, data: await fileBase64(f)})).src); }
        catch (e) { reject(e); }
      });
      input.click();
    });
  }
  async function pickPoem(w) {
    const d = await api("/api/poems"), poems = (d.poems || []).filter(p => !p.error);
    if (!poems.length) throw new Error("The Poems library has no poems yet.");
    const series = [...new Set(poems.map(p => p.series))];
    let chosen = null;
    return new Promise(resolve => {
      const form = openDialog(`<form class="bk-pp"><h2>Linked poem</h2>
        <p class="hint" style="margin-top:-12px">The poem's text comes from the Poems library: change it there and the book follows.</p>
        <input class="input" type="search" data-q placeholder="Find a poem" aria-label="Find a poem" autocomplete="off">
        <div class="bk-pp-list">${series.map(s => `<section><h3 class="label">${esc(s)}</h3>${poems.filter(p => p.series === s).map(p =>
          `<label class="bk-pp-i"><input type="radio" name="poem" value="${esc(p.id)}"><span>${esc(p.title)}</span></label>`).join("")}</section>`).join("")}</div>
        <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Insert</button></div></form>`,
      async f => {
        const id = f.get("poem");
        if (!id) throw new Error("Choose a poem.");
        const p = await api("/api/poem?id=" + encodeURIComponent(id));
        w.linked[id] = {title: p.title, lines: p.lines || []};
        chosen = id;
      });
      $("[data-q]", form).addEventListener("input", e => {
        const q = e.target.value.trim().toLowerCase();
        $$(".bk-pp-i", form).forEach(l => { l.hidden = !!q && !l.textContent.toLowerCase().includes(q); });
        $$(".bk-pp-list section", form).forEach(s => { s.hidden = !$$(".bk-pp-i:not([hidden])", s).length; });
      });
      onDialogClose(() => resolve(chosen));
    });
  }

  /* ——— keys and the window ——— */
  addEventListener("keydown", e => {
    if (!W || state.view !== "book") return;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key === "\\") { e.preventDefault(); toggleBinder(); }
    else if (mod && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "s") { e.preventDefault(); W.piece?.save(); W.split?.piece?.save(); }
  });
  addEventListener("blur", () => { W?.piece?.save(); W?.split?.piece?.save(); });
  addEventListener("pagehide", () => { W?.piece?.emergency(); W?.split?.piece?.emergency(); });

  /* for book-tools.js: a second pane is a Piece on other hosts, with the same saving; the tools reach the window too */
  const forget = piece => live.delete(piece);
  /* a leaving save of this piece still under way, so what opens is what was left */
  async function leaving(book, file) {
    const l = [...live].find(x => x.closed && x.saving && x.book === book && x.file === file);
    while (l?.saving) await l.saving.catch(() => {});
  }
  /* every save under way, of open and closed pieces */
  const settled = () => Promise.all([...live].map(p => p.saving).filter(Boolean)).catch(() => {});
  return {mount, unmount, pending, refresh,
    get win() { return W; }, Piece, bar, places, forget, leaving, settled, openPiece, newPiece, toggleBinder, reloadBook};
})();
