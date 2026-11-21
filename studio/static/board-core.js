"use strict";
/* The research board's helpers and the save queue for an item's text (board.js, board-canvas.js, board-rail.js).
   A classic script after book-text.js; sets window.BoardCore. Nothing here touches the DOM, localStorage or the
   network at load, so tests/js/board.js runs it in node. */
(function (root) {
  const KIND_NAME = {note: "Note", quote: "Quote", source: "Source", clip: "Web clip", image: "Image", piece: "Piece", link: "Link"};
  const MIME = "application/x-studio-research";
  const INLINE_WORDS = 40;
  const ZOOM = {min: 0.25, max: 2};
  /* The same numbers as research.CARD_W and research.CARD_H (the height is an estimate until a card is measured). */
  const CARD_W = {note: 240, quote: 280, source: 260, clip: 300, image: 240, piece: 260, link: 260};
  const CARD_H = {note: 160, quote: 170, source: 120, clip: 280, image: 200, piece: 150, link: 160};
  const ROW = 40;     // frames whose tops lie within this many units are one row in reading order

  /* ——— addresses ——— */

  const boardHash = bookId => bookId ? `#/book/${encodeURIComponent(bookId)}/board` : "#/research";
  const boardParam = bookId => bookId ? `b=${encodeURIComponent(bookId)}` : "";
  const fileUrl = (bookId, rel, w) =>
    `/researchfiles/${bookId ? encodeURIComponent(bookId) : "_shared"}/${String(rel).split("/").map(encodeURIComponent).join("/")}${w ? `?w=${w}` : ""}`;

  /* ——— the canvas ——— */

  /* The smallest frame that contains the point (the higher one when they are equally small), or null. */
  function frameAt(frames, x, y) {
    let best = null, area = Infinity;
    for (const f of frames || []) {
      if (x < f.x || x > f.x + f.w || y < f.y || y > f.y + f.h) continue;
      const a = f.w * f.h;
      if (a < area || (a === area && best && (f.z || 0) > (best.z || 0))) { best = f; area = a; }
    }
    return best ? best.id : null;
  }

  /* Where a card stands: its set size, else a measured height (item._h), else the estimate for its kind. */
  function cardBox(item) {
    const p = item.pos || {};
    const num = v => typeof v === "number" ? v : null;
    return {x: p.x || 0, y: p.y || 0, w: num(p.w) ?? CARD_W[item.type] ?? 260, h: num(p.h) ?? num(item._h) ?? CARD_H[item.type] ?? 160};
  }

  /* Frames as a page is read: rows from the top (tops within 40 units are one row), each row from the left. */
  function readingOrder(frames) {
    const byTop = [...frames].sort((a, b) => a.y - b.y || a.x - b.x);
    const rows = [];
    for (const f of byTop) {
      const row = rows[rows.length - 1];
      if (row && f.y - row.top <= ROW) row.items.push(f); else rows.push({top: f.y, items: [f]});
    }
    return rows.flatMap(row => row.items.sort((a, b) => a.x - b.x));
  }

  const byTitle = (a, b) => String(a.title || "").localeCompare(String(b.title || ""), undefined, {sensitivity: "base"});
  const SORTS = {
    title: byTitle,
    added: (a, b) => (a.created < b.created ? 1 : a.created > b.created ? -1 : 0) || byTitle(a, b),
    kind: (a, b) => Object.keys(KIND_NAME).indexOf(a.type) - Object.keys(KIND_NAME).indexOf(b.type) || byTitle(a, b),
  };

  /* The list view: [{frame, items}] with the frames in reading order, then the items in none ("Not in a frame"). */
  function groups(items, frames, sortBy) {
    const cmp = SORTS[sortBy] || SORTS.title;
    const known = new Set(frames.map(f => f.id));
    const of = id => items.filter(i => (i.pos && i.pos.frame) === id).sort(cmp);
    return [...readingOrder(frames).map(f => ({frame: f, items: of(f.id)})),
      {frame: null, items: items.filter(i => !(i.pos && known.has(i.pos.frame))).sort(cmp)}];
  }

  /* The view that shows every box: screen = world * zoom + {x, y}, centred, zoom within ZOOM. */
  function fitView(boxes, width, height, pad = 48) {
    if (!boxes.length) return {x: 0, y: 0, zoom: 1};
    const x0 = Math.min(...boxes.map(b => b.x)), y0 = Math.min(...boxes.map(b => b.y));
    const x1 = Math.max(...boxes.map(b => b.x + b.w)), y1 = Math.max(...boxes.map(b => b.y + b.h));
    const bw = x1 - x0, bh = y1 - y0;
    const fit = Math.min(bw > 0 ? (width - 2 * pad) / bw : Infinity, bh > 0 ? (height - 2 * pad) / bh : Infinity);
    const zoom = Math.max(ZOOM.min, Math.min(ZOOM.max, Number.isFinite(fit) ? fit : 1));
    return {x: (width - bw * zoom) / 2 - x0 * zoom, y: (height - bh * zoom) / 2 - y0 * zoom, zoom};
  }

  /* ——— quotes in the text ——— */

  /* How a prepared quote (from /api/research/use) stands in the text: a block quote when it runs over paragraphs or
     past INLINE_WORDS, else inline between the style's quote marks. */
  function quoteParts(prepared, style) {
    const q = root.BookText.quoteFor;
    return {block: prepared.paragraphs.length > 1 || prepared.words > INLINE_WORDS, open: q("", "\"", style), close: q("x", "\"", style)};
  }

  /* A quote inside a quote takes the style's single marks: straight double quotes and the style's own double marks
     become the single pair (‚…’ in „…”). */
  function innerQuotes(text, style) {
    const q = root.BookText.quoteFor;
    const dOpen = q("", "\"", style), dClose = q("x", "\"", style);
    const sOpen = q("", "'", style), sClose = q(".", "'", style);   // after a letter ' would be an apostrophe
    let out = "";
    for (const c of text) {
      if (c === "\"") out += q(out, "\"", style) === dOpen ? sOpen : sClose;
      else if (c === dOpen) out += sOpen;
      else if (c === dClose) out += sClose;
      else out += c;
    }
    return out;
  }

  /* ——— plain words ——— */

  /* Markdown as plain words, its paragraphs and lines kept: links and pictures become their words, block markers and
     emphasis go, escaped characters (\[1\], \*) stay as the characters, a hard break is a line break. research._strip
     does the same on one line (the excerpt). */
  function plainText(md) {
    const kept = [];
    let s = String(md || "").replace(/\r\n?/g, "\n").replace(/\\([!-\/:-@\[-`{-~])/g, (m, c) => `\u0000${kept.push(c) - 1}\u0000`);
    s = s.replace(/\\\n/g, "\n").replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/^ {0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)/gm, "").replace(/[*_`~]+/g, "")
      .replace(/\u0000(\d+)\u0000/g, (m, i) => kept[+i]);
    return s.split(/\n[ \t]*\n/).map(p => p.split("\n").map(l => l.replace(/[ \t]+/g, " ").trim()).filter(Boolean).join("\n"))
      .filter(Boolean).join("\n\n");
  }

  /* ——— dragging a card into the text ——— */

  const payload =(bookId, item) => JSON.stringify({board: bookId || null, id: item.id});
  function readPayload(str) {
    let v;
    try { v = JSON.parse(str); } catch (e) { return null; }
    if (!v || typeof v !== "object" || Array.isArray(v) || typeof v.id !== "string" || !v.id) return null;
    if (v.board !== null && typeof v.board !== "string") return null;
    return {board: v.board, id: v.id};
  }

  /* ——— the filter ——— */

  function matches(item, filter) {
    const f = filter || {};
    if (f.kind && item.type !== f.kind) return false;
    if (f.tag && !(item.tags || []).includes(f.tag)) return false;
    if (f.ids && !f.ids.has(item.id)) return false;
    return true;
  }

  /* ——— the save queue ——— */

  /* An item's text, saved after a second of quiet. `save(fields, base, force)` returns a promise of the stored item (its
     `updated` becomes the next base); `keep(fields)` stores the unsaved text where it survives a crash and `drop()`
     forgets it (board.js passes localStorage-backed ones). A failed save keeps the text and tries again; a 409 with
     `data.current` is a stale save: `conflict` holds the server's item and nothing is saved until `reload()` (take
     theirs) or `keepMine()` (save mine over it, with force). A 409 without `current` is the board being busy, like
     any other failure. */
  class Saver {
    constructor(o) {
      this.o = o;
      this.base = o.base ?? null;
      this.fields = null;       // text changed and not yet saved
      this.inflight = null;     // the fields being saved now
      this.timer = null;
      this.saving = null;
      this.conflict = null;
      this.error = null;
      this.delay = o.delay ?? 1000;
      this.retry = o.retry ?? 5000;
    }
    _set(fn, ms) { return (this.o.setTimeout || ((f, t) => root.setTimeout(f, t)))(fn, ms); }
    _clear() {
      if (this.timer !== null) (this.o.clearTimeout || (t => root.clearTimeout(t)))(this.timer);
      this.timer = null;
    }
    _later(ms) { this._clear(); this.timer = this._set(() => { this.timer = null; this._run(); }, ms); }
    _unsaved() { return Object.assign({}, this.inflight, this.fields); }
    change(fields) {
      this.fields = Object.assign(this.fields || {}, fields);
      this.o.keep(this._unsaved());
      if (!this.conflict) this._later(this.delay);
    }
    pending() { return !!(this.fields || this.saving); }
    /* Save now. With `leaving` (the page is closing) the text is stored again first, since the save may not finish. */
    flush(opts) {
      if (opts && opts.leaving && (this.fields || this.inflight)) this.o.keep(this._unsaved());
      return this._run();
    }
    async _run(force = false) {
      this._clear();
      if (this.saving) await this.saving;
      if (!this.fields || (this.conflict && !force)) return undefined;
      this._clear();
      const fields = this.fields;
      this.fields = null; this.inflight = fields;
      this.saving = (async () => {
        try {
          const item = await this.o.save(fields, this.base, force);
          if (item && item.updated != null) this.base = item.updated;
          this.error = null; this.inflight = null;
          if (!this.fields) this.o.drop();
          return item;
        } catch (e) {
          this.error = e; this.fields = Object.assign({}, fields, this.fields); this.inflight = null;
          if (e && e.status === 409 && e.data && e.data.current) this.conflict = e.data.current;
          else this._later(this.retry);
          return undefined;
        } finally { this.saving = null; }
      })();
      return this.saving;
    }
    /* Take the server's text and forget mine; returns the server's item. */
    reload() {
      const theirs = this.conflict;
      this._clear();
      this.conflict = null; this.fields = null; this.error = null;
      if (theirs && theirs.updated != null) this.base = theirs.updated;
      this.o.drop();
      return theirs;
    }
    /* Save mine over the server's. */
    keepMine() {
      if (this.conflict && this.conflict.updated != null) this.base = this.conflict.updated;
      this.conflict = null; this.error = null;
      return this._run(true);
    }
  }

  root.BoardCore = {KIND_NAME, MIME, INLINE_WORDS, ZOOM, CARD_W, CARD_H, boardHash, boardParam, fileUrl, frameAt, cardBox,
    readingOrder, groups, fitView, quoteParts, innerQuotes, plainText, payload, readPayload, matches, Saver};
})(typeof window !== "undefined" ? window : globalThis);
