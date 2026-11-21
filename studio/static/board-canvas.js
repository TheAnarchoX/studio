"use strict";
/* The research board's canvas: the board's items as cards, its frames behind them, on one layer moved as a whole with
   translate(x, y) scale(zoom) (screen = board * zoom + {x, y}; 1 board unit is 1 CSS pixel at 100%). board.js shows
   it in place of the list while the view is "Canvas".
   A classic script after board.js; sets window.BoardCanvas: create(host, ctx), the undo stack board.js keeps (Undo),
   and the helpers. Everything above create() touches no DOM, so tests/js/board_canvas.js runs it in node.

   create(host, ctx) → {render(board, filter), select(ids), selected(), show(id), goToFrame(id), rename(frameId), fit(),
   zoomTo(z, around?), toBoard(clientX, clientY) → {x, y}, destroy()}. ctx (board.js) is:
     key                      the board as the view is kept in the browser: a book's id, or "_shared"
     quotes()                 the quote style of the book ("“…”" on the shared board)
     titleOf(item)            {text, own}; sourceOf(item) the source line as escaped HTML; kindName(type)
     open(id), menu(e, ids), trash(ids) (asks first for more than one), selection(ids, cursor), zoomed(zoom)
     moved(items, frames)     positions {id: {x?, y?, w?, h?, z?, frame?}} and frame changes [{id, …}], one write
     frames({frames?, remove_frames?})
     add(kind, at, frame), clip(url, at, frame), files(files, at, frame), text(text, at, frame)   (`at` in board units)
   The writes return a promise of the server's reply, or of null when it failed (board.js has said why). */
(function (root) {
  const core = () => root.BoardCore;
  const CAP = 360;                   // a card grows with its text to this height, then fades
  const EXCERPT = 280;               // research.EXCERPT: a card's words are the first 280 characters of the text
  const FRAME_MIN = 160;             // research.FRAME_MIN
  const CARD_MIN = {w: 160, h: 80}, CARD_MAX = {w: 1200, h: 2000};      // within research.CARD_WIDTHS / CARD_HEIGHTS
  const NEW_FRAME = {w: 480, h: 320};
  const NUDGE = 8, DRAG = 3;         // arrows move by 8 (Shift: 1); a press becomes a drag after 3 screen pixels
  const STEPS = [0.25, 0.33, 0.5, 0.67, 0.75, 1, 1.25, 1.5, 2];
  const UNDO_MAX = 50;

  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const num = (v, d) => typeof v === "number" && Number.isFinite(v) ? v : d;
  const webUrl = s => typeof s === "string" && /^https?:\/\/\S+$/i.test(s.trim()) ? s.trim() : null;

  /* ——— the view ——— */

  /* a point in the host (pixels from its top left) as a board point, and back */
  const boardPoint = (view, sx, sy) => ({x: (sx - view.x) / view.zoom, y: (sy - view.y) / view.zoom});
  const screenPoint = (view, bx, by) => ({x: bx * view.zoom + view.x, y: by * view.zoom + view.y});
  /* the view at zoom z (kept within BoardCore.ZOOM) with the board point under (sx, sy) staying there */
  function zoomAround(view, z, sx, sy) {
    const Z = core().ZOOM, zoom = clamp(z, Z.min, Z.max), b = boardPoint(view, sx, sy);
    return {x: sx - b.x * zoom, y: sy - b.y * zoom, zoom};
  }
  /* the next step of the zoom buttons and keys above (dir 1) or below (-1) z */
  function zoomStep(z, dir) {
    const Z = core().ZOOM;
    if (dir > 0) return STEPS.find(s => s > z + 1e-3) ?? Z.max;
    return [...STEPS].reverse().find(s => s < z - 1e-3) ?? Z.min;
  }
  /* what one Ctrl+wheel event multiplies the zoom by: a mouse notch about 1.16, a trackpad pinch in small steps */
  const wheelZoom = deltaY => Math.exp(-clamp(deltaY, -50, 50) * 0.003);
  /* the view that shows every box (BoardCore.fitView), never closer than `most` (then centred at it) */
  function fitBoxes(boxes, width, height, most = 1, pad = 48) {
    if (!boxes.length) return {x: pad, y: pad, zoom: 1};
    const v = core().fitView(boxes, width, height, pad);
    if (v.zoom <= most) return v;
    const x0 = Math.min(...boxes.map(b => b.x)), y0 = Math.min(...boxes.map(b => b.y));
    const x1 = Math.max(...boxes.map(b => b.x + b.w)), y1 = Math.max(...boxes.map(b => b.y + b.h));
    return {x: (width - (x1 - x0) * most) / 2 - x0 * most, y: (height - (y1 - y0) * most) / 2 - y0 * most, zoom: most};
  }
  /* the view as kept in the browser (pref board.view.<board>): {x, y, zoom}, or null when it isn't one */
  function readView(s) {
    let v = s;
    if (typeof s === "string") { try { v = JSON.parse(s); } catch { return null; } }
    const Z = core().ZOOM;
    if (!v || typeof v !== "object" || ![v.x, v.y, v.zoom].every(Number.isFinite) || v.zoom < Z.min || v.zoom > Z.max) return null;
    return {x: v.x, y: v.y, zoom: v.zoom};
  }
  const viewKey = key => `board.view.${key == null || key === "" ? "_shared" : key}`;

  /* ——— hitting and moving ——— */

  /* the rectangle between two corners */
  const rectOf = (a, b) => ({x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y)});
  /* the ids of the boxes a rectangle touches (a selection box) */
  const within = (boxes, r) => boxes.filter(b => b.x < r.x + r.w && b.x + b.w > r.x && b.y < r.y + r.h && b.y + b.h > r.y).map(b => b.id);
  /* Cards dropped after moving by (dx, dy): {id: {x, y, frame, z?}} in whole units, each in the frame that holds its
     centre (BoardCore.frameAt). With `top` (the highest z on the board) they are raised above everything, keeping
     their order among themselves. */
  function dropped(boxes, dx, dy, frames, top = null) {
    const out = {}, order = top == null ? boxes : [...boxes].sort((a, b) => (a.z || 0) - (b.z || 0));
    order.forEach((b, i) => {
      const x = Math.round(b.x + dx), y = Math.round(b.y + dy);
      out[b.id] = {x, y, frame: core().frameAt(frames, x + b.w / 2, y + b.h / 2), ...(top == null ? {} : {z: top + 1 + i})};
    });
    return out;
  }
  /* A frame moved by its title with the cards that are in it: {items, frames}, for one layout write. */
  function frameMoved(frame, members, dx, dy) {
    const mx = Math.round(dx), my = Math.round(dy), items = {};
    for (const m of members) items[m.id] = {x: Math.round(m.x) + mx, y: Math.round(m.y) + my, frame: frame.id};
    return {items, frames: [{id: frame.id, x: Math.round(frame.x) + mx, y: Math.round(frame.y) + my}]};
  }
  /* a corner dragged by (dx, dy): the new size in whole units, within min and max */
  const resized = (w, h, dx, dy, min, max) => ({w: Math.round(clamp(w + dx, min.w, max.w)), h: Math.round(clamp(h + dy, min.h, max.h))});

  /* What was dropped on the canvas: {files}, {url} (a link: the first web address of a uri-list, or text that is one
     address), {text}, or null. An address of Studio's own (`origin`: a picture dragged from the item panel) is nothing. */
  function readDrop({files = [], uris = "", text = "", origin = root.location ? root.location.origin : ""} = {}) {
    if (files && files.length) return {files: [...files]};
    const url = String(uris || "").split(/\r?\n/).map(l => l.trim()).find(l => l && !l.startsWith("#") && webUrl(l)) || webUrl(text);
    if (url) return ownUrl(url, origin) ? null : {url};
    return String(text || "").trim() ? {text: String(text)} : null;
  }
  const ownUrl = (u, origin) => { try { return !!origin && new URL(u).origin === origin; } catch (e) { return false; } };

  /* What a press, a double-click or a right-click is on (from the element under the pointer, through closest()):
     {what, id} with what "field" (a frame's title being typed), "grip" or "card" (the card's id), "fgrip" or "fbar"
     (the frame's id), or "empty" (the stage, or the inside of a frame). */
  function targetOf(t) {
    if (!t || typeof t.closest !== "function") return {what: "empty", id: null};
    if (t.closest(".bc-fin")) return {what: "field", id: null};
    const card = t.closest(".bc-card");
    if (card) return {what: t.closest(".bc-grip") ? "grip" : "card", id: card.dataset.id};
    const fr = t.closest(".bc-frame");
    if (fr && t.closest(".bc-fgrip")) return {what: "fgrip", id: fr.dataset.id};
    if (fr && t.closest(".bc-fbar")) return {what: "fbar", id: fr.dataset.id};
    return {what: "empty", id: null};
  }

  /* ——— cards ——— */

  /* the style's double quote marks, [open, close] (BookText.quoteFor; “…” without it) */
  function marks(style) {
    const q = root.BookText && root.BookText.quoteFor;
    return q ? [q("", "\"", style || "“…”"), q("x", "\"", style || "“…”")] : ["“", "”"];
  }

  /* A card's inside: its kind, the picture (clips and images), its title, its words (a quote in the serif between the
     style's marks), the source line, where a link's original is, the tags. Every string is escaped here except `source`,
     which is board.js's escaped HTML. o: {title: {text, own}, source, kind, quotes: [open, close]}. An image's picture
     (at most 200 high, board-canvas.css) and caption (three lines) are held short, so its title, source and tags show. */
  function cardHtml(it, o) {
    const title = o.title || {text: "", own: false}, kind = `<p class="bc-k">${esc(o.kind)}</p>`;
    if (it.error) return `${kind}<p class="bc-t">${esc(`${it.id}.md`)}</p><p class="bc-s bc-bad">Can't be read</p>`;
    if (it.link && it.link.missing) return `<p class="bc-k">Link</p><p class="bc-x bc-none">The original of this link is gone.</p>`;
    const words = String(it.excerpt || "").trim(), more = words.length >= EXCERPT ? "…" : "";
    const thumb = (it.type === "clip" || it.type === "image") && typeof it.thumb === "string" && it.thumb ? it.thumb : null;
    const own = title.own && title.text ? title.text : "";
    const out = [kind];
    if (thumb) out.push(`<img class="bc-img${it.type === "clip" ? " bc-shot" : ""}" src="${esc(thumb)}" alt="${esc(title.text)}" loading="lazy" decoding="async" draggable="false">`);
    if (own) out.push(`<p class="bc-t">${esc(own)}</p>`);
    if (it.type === "quote") out.push(words ? `<p class="bc-q">${esc(o.quotes[0] + words + more + o.quotes[1])}</p>` : `<p class="bc-x bc-none">No words yet</p>`);
    else if (it.type === "note") { if (words) out.push(`<p class="bc-x">${esc(words + more)}</p>`); else if (!own) out.push(`<p class="bc-x bc-none">Empty note</p>`); }
    else if (it.type === "clip") { if (!thumb && words) out.push(`<p class="bc-x bc-small bc-clamp">${esc(words + more)}</p>`); }
    else if (words) out.push(`<p class="bc-x bc-small${it.type === "image" ? " bc-clamp bc-c3" : ""}">${esc(words + more)}</p>`);
    if (o.source) out.push(`<p class="bc-s">${o.source}</p>`);
    if (it.link && !it.link.missing) out.push(`<p class="bc-via">From ${esc(it.link.board == null ? "the shared board" : it.link.board_title || it.link.board)}</p>`);
    const tags = Array.isArray(it.tags) ? it.tags.filter(t => typeof t === "string" && t) : [];
    if (tags.length) out.push(`<p class="bc-tags">${esc(tags.join(", "))}</p>`);
    return out.join("");
  }

  /* ——— undo ———
     The board's last actions (board.js keeps one stack while the page is open; the list and the canvas share it). An
     entry is {label, undo(), redo()}; undo and redo resolve to what to say (a toast), or to nothing when they failed,
     and a failed entry is dropped. One runs at a time. undo() and redo() resolve to {entry, said}, or null when there
     was nothing to take back (or one is still running). An action recorded while an undo is under way ends what could
     be redone, that undo's entry included. */
  class Undo {
    constructor(max = UNDO_MAX) { this.max = max; this.done = []; this.undone = []; this.busy = false; this.pushed = 0; }
    push(entry) {
      this.done.push(entry);
      if (this.done.length > this.max) this.done.splice(0, this.done.length - this.max);
      this.undone = [];
      this.pushed++;
    }
    get canUndo() { return this.done.length > 0; }
    get canRedo() { return this.undone.length > 0; }
    clear() { this.done = []; this.undone = []; }
    undo() { return this._run(this.done, "undo"); }
    redo() { return this._run(this.undone, "redo"); }
    async _run(from, how) {
      if (this.busy || !from.length) return null;
      const entry = from.pop(), pushed = this.pushed;
      this.busy = true;
      let said = null;
      try { said = await entry[how](); } catch (e) { console.error(e); said = null; } finally { this.busy = false; }
      const ended = how === "undo" && this.pushed !== pushed;          // a new action came in meanwhile: no redo
      if (said && !ended) {
        const list = how === "undo" ? this.undone : this.done;          // the list as it is now (a push replaces undone)
        list.push(entry);
        if (list.length > this.max) list.splice(0, list.length - this.max);
      }
      return {entry, said: said || null};
    }
  }

  /* ——— the canvas ——— */
  function create(host, ctx) {
    const C = core(), doc = host.ownerDocument;
    host.innerHTML = `<div class="bcv" tabindex="0" aria-label="The board's cards">
      <div class="bc-layer"><div class="bc-frames"></div><div class="bc-cards"></div></div>
      <div class="bc-box" hidden></div>
      <p class="bc-empty" hidden>Nothing on this board yet. Double-click to write a note, or drop a picture, a link or some text here.</p></div>`;
    const el = host.firstElementChild, layer = el.querySelector(".bc-layer");
    const framesEl = el.querySelector(".bc-frames"), cardsEl = el.querySelector(".bc-cards");
    const boxEl = el.querySelector(".bc-box"), emptyEl = el.querySelector(".bc-empty");

    let board = null, filter = {};
    let items = new Map(), frames = new Map();                // the last board's items and frames, by id
    const cards = new Map(), frameEls = new Map();            // id → {el, … what was last written to it}
    const heights = new Map();                                // a card's height as drawn (measured, or its own h)
    const over = new Map(), fover = new Map();                // positions shown while their save is under way
    let sel = new Set(), cursor = null;
    let view = {x: 0, y: 0, zoom: 1}, viewSet = false, wantFit = false, shownZoom = null, pxZoom = null;
    let size = {w: 0, h: 0}, at0 = {left: 0, top: 0};         // the host's size and place (read outside the move loop)
    let drag = null, pending = null, raf = 0, seq = 0, space = false, renaming = null, dead = false;
    let liveOn = false, liveTimer = 0, keepTimer = 0, dropTimer = 0, fitTimer = 0, nudgeTimer = 0;
    const nudged = new Set();

    const ro = new ResizeObserver(measured);
    ro.observe(el);

    /* ——— where things are ——— */
    function rect() {
      const r = el.getBoundingClientRect();
      at0 = {left: r.left, top: r.top};
      size = {w: r.width, h: r.height};
    }
    const local = (cx, cy) => ({x: cx - at0.left, y: cy - at0.top});
    const pointAt = e => { rect(); const p = boardPoint(view, e.clientX - at0.left, e.clientY - at0.top); return {x: Math.round(p.x), y: Math.round(p.y)}; };
    const frameList = () => [...frames.keys()].map(frameOf);
    const frameIn = p => C.frameAt(frameList(), p.x, p.y);
    function posOf(id) {
      const it = items.get(id);
      return {...((it && it.pos) || {}), ...(over.get(id) || {})};
    }
    function boxOf(id) {
      const it = items.get(id), p = posOf(id), type = it ? it.type : "note";
      return {id, x: num(p.x, 0), y: num(p.y, 0), w: num(p.w, C.CARD_W[type] ?? 260), h: num(p.h, heights.get(id) ?? C.CARD_H[type] ?? 160), z: num(p.z, 0)};
    }
    function frameOf(id) {
      const f = frames.get(id);
      return f ? {...f, ...(fover.get(id) || {})} : null;
    }
    const topZ = () => Math.max(0, ...[...items.keys()].map(id => num(posOf(id).z, 0)));
    /* the selection in the board's order */
    const ordered = () => board ? board.items.filter(i => sel.has(i.id)).map(i => i.id) : [...sel];
    const membersOf = fid => board ? board.items.filter(i => posOf(i.id).frame === fid).map(i => i.id) : [];
    const shown = () => !dead && !host.hidden && el.isConnected;

    /* ——— drawing ——— */
    function render(b, f) {
      if (!b || dead) return;
      if (drag && drag.moved && drag.kind !== "pan" && drag.kind !== "box") { pending = [b, f]; return; }
      board = b; filter = f || {};
      const quotes = marks(ctx.quotes ? ctx.quotes() : null);
      frames = new Map();
      for (const fr of b.frames || []) {
        if (fr && typeof fr.id === "string" && [fr.x, fr.y, fr.w].every(Number.isFinite)) frames.set(fr.id, {...fr, h: num(fr.h, FRAME_MIN)});
      }
      for (const fr of frames.values()) paintFrame(fr);
      for (const [id, x] of frameEls) {
        if (frames.has(id)) continue;
        x.el.remove(); frameEls.delete(id); fover.delete(id);
        if (renaming === id) renaming = null;          // deleted elsewhere while its title was being typed
      }
      items = new Map(b.items.map(i => [i.id, i]));
      for (const it of b.items) { const h = heights.get(it.id); if (h != null) it._h = h; paintCard(it, quotes); }
      for (const [id, c] of cards) {
        if (items.has(id)) continue;
        ro.unobserve(c.inner); c.el.remove();
        cards.delete(id); heights.delete(id); over.delete(id);
      }
      for (const id of [...sel]) if (!items.has(id)) sel.delete(id);
      emptyEl.hidden = !!(b.items.length || frames.size);
      if (!viewSet && !wantFit) firstView();
      else tryFit();
    }

    function paintCard(it, quotes) {
      let c = cards.get(it.id);
      if (!c) {
        const e = doc.createElement("div");
        e.className = "bc-card";
        e.dataset.id = it.id;
        e.innerHTML = `<div class="bc-in"></div><span class="bc-grip" title="Drag to resize · double-click to fit the text"></span>`;
        c = {el: e, inner: e.firstElementChild, html: null, kind: null, x: null, y: null, w: null, h: undefined, z: null, on: false, dim: false, long: false, ih: 0};
        cards.set(it.id, c);
        cardsEl.appendChild(e);
        ro.observe(c.inner);
      }
      let html;
      try { html = cardHtml(it, {title: ctx.titleOf(it), source: ctx.sourceOf(it), kind: ctx.kindName(it.type), quotes}); }
      catch (e) { console.error(e); html = `<p class="bc-k">${esc(ctx.kindName(it.type))}</p><p class="bc-x">${esc(it.excerpt || it.id)}</p>`; }
      if (html !== c.html) { c.inner.innerHTML = html; c.html = html; }
      if (c.kind !== it.type) { c.el.dataset.kind = it.type; c.kind = it.type; }
      paintPos(it.id);
      const dim = !C.matches(it, filter), on = sel.has(it.id);
      if (dim !== c.dim) { c.el.classList.toggle("dim", dim); c.dim = dim; }
      if (on !== c.on) { c.el.classList.toggle("on", on); c.on = on; }
    }
    /* a card's place, width, own height and z, written only when they changed */
    function paintPos(id) {
      const c = cards.get(id);
      if (!c) return;
      const b = boxOf(id), h = num(posOf(id).h, null), z = Math.round(b.z);
      if (c.x !== b.x || c.y !== b.y) { c.el.style.transform = `translate(${b.x}px,${b.y}px)`; c.x = b.x; c.y = b.y; }
      if (c.w !== b.w) { c.el.style.width = b.w + "px"; c.w = b.w; }
      if (c.h !== h) { c.el.style.height = h == null ? "" : h + "px"; c.el.classList.toggle("sized", h != null); c.h = h; fitCard(id); }
      if (c.z !== z) { c.el.style.zIndex = String(z); c.z = z; }
    }
    /* a card's height as drawn, from its measured inside: up to CAP (or its own height), fading when there is more */
    function fitCard(id) {
      const c = cards.get(id);
      if (!c || !c.ih) return;
      // + the hairline above and below; an image card is held short by its picture and caption instead of the cap
      const full = c.ih + 2, h = c.h != null ? c.h : c.kind === "image" ? full : Math.min(full, CAP);
      heights.set(id, h);
      const it = items.get(id);
      if (it) it._h = h;
      const long = full > h + 1;
      if (long !== c.long) { c.el.classList.toggle("long", long); c.long = long; }
    }
    function paintFrame(fr) {
      let f = frameEls.get(fr.id);
      if (!f) {
        const e = doc.createElement("div");
        e.className = "bc-frame";
        e.dataset.id = fr.id;
        e.innerHTML = `<div class="bc-fbar" title="Drag to move the frame with its items · double-click to rename"><span class="bc-ft"></span></div><span class="bc-fgrip" title="Drag to resize the frame"></span>`;
        f = {el: e, bar: e.firstElementChild, t: e.querySelector(".bc-ft"), title: null, x: null, y: null, w: null, h: null, z: null};
        frameEls.set(fr.id, f);
        framesEl.appendChild(e);
      }
      const title = fr.title || "Frame";
      if (f.title !== title && renaming !== fr.id) { f.t.textContent = title; f.title = title; }
      paintFramePos(fr.id);
    }
    function paintFramePos(id) {
      const f = frameEls.get(id), fr = frameOf(id);
      if (!f || !fr) return;
      const z = Math.round(num(fr.z, 0));
      if (f.x !== fr.x || f.y !== fr.y) { f.el.style.transform = `translate(${fr.x}px,${fr.y}px)`; f.x = fr.x; f.y = fr.y; }
      if (f.w !== fr.w) { f.el.style.width = fr.w + "px"; f.w = fr.w; }
      if (f.h !== fr.h) { f.el.style.height = fr.h + "px"; f.h = fr.h; }
      if (f.z !== z) { f.el.style.zIndex = String(z); f.z = z; }
    }
    function paintSel() {
      for (const [id, c] of cards) {
        const on = sel.has(id);
        if (on !== c.on) { c.el.classList.toggle("on", on); c.on = on; }
      }
    }
    /* the selection made here, told to the page (the list, the counts) */
    function announce() { paintSel(); ctx.selection(ordered(), cursor); }

    /* The inside of each card measured (layout sizes: the zoom doesn't change them), and the host's size. */
    function measured(entries) {
      if (dead) return;
      for (const en of entries) {
        if (en.target === el) { rect(); continue; }
        const card = en.target.parentElement, id = card && card.dataset.id, c = id != null ? cards.get(id) : null;
        if (!c || c.inner !== en.target) continue;
        const s = en.borderBoxSize && en.borderBoxSize[0], ih = s ? s.blockSize : en.target.offsetHeight;
        if (!(ih > 0)) continue;                     // not laid out (the list is showing)
        c.ih = ih;
        fitCard(id);
      }
      tryFit();
    }

    /* ——— the view ——— */
    function setView(v, live = true) {
      view = {x: Math.round(v.x), y: Math.round(v.y), zoom: v.zoom};
      viewSet = true; wantFit = false;
      layer.style.transform = `translate(${view.x}px,${view.y}px) scale(${view.zoom})`;
      if (view.zoom !== shownZoom) { shownZoom = view.zoom; if (ctx.zoomed) ctx.zoomed(view.zoom); }
      if (!live) { settle(); return; }
      // while it moves the layer is its own picture, scaled; once it rests the text is drawn sharp at the new zoom
      if (!liveOn) { layer.classList.add("live"); liveOn = true; }
      clearTimeout(liveTimer);
      liveTimer = setTimeout(settle, 160);
    }
    function settle() {
      clearTimeout(liveTimer); liveTimer = 0;
      if (liveOn) { layer.classList.remove("live"); liveOn = false; }
      if (pxZoom !== view.zoom) { pxZoom = view.zoom; el.style.setProperty("--bc-px", String(1 / view.zoom)); }     // the red rule stays 2 px on screen
      clearTimeout(keepTimer);
      keepTimer = setTimeout(keepView, 300);
    }
    /* the view kept in the browser; `kept` is the last one written, so leaving writes only a view that changed */
    let kept = null;
    function keepView() {
      keepTimer = 0;
      if (!viewSet) return;
      const v = JSON.stringify(view);
      if (v !== kept) { pref.set(viewKey(ctx.key), v); kept = v; }
    }
    /* the first board drawn: the view this window kept for it, else everything in view once the cards are measured */
    function firstView() {
      const saved = readView(pref.get(viewKey(ctx.key), null));
      if (saved) { setView(saved, false); kept = JSON.stringify(view); return; }
      wantFit = true;
      clearTimeout(fitTimer);
      fitTimer = setTimeout(() => { if (wantFit && size.w) fit(); }, 1000);     // a card that is never measured doesn't hold it up
      tryFit();
    }
    function tryFit() {
      if (!wantFit || !size.w || !board) return;
      for (const id of cards.keys()) if (!heights.has(id)) return;
      fit();
    }
    const contentBoxes = () => [...[...cards.keys()].map(boxOf), ...frameList()];
    function fit() {
      if (!size.w) rect();
      if (!size.w) { wantFit = true; return; }
      setView(fitBoxes(contentBoxes(), size.w, size.h, 1), false);
    }
    function zoomTo(z, around) {
      rect();
      const p = around ? local(around.x, around.y) : {x: size.w / 2, y: size.h / 2};
      setView(zoomAround(view, z, p.x, p.y), false);
    }
    function goToFrame(id) {
      const f = frameOf(id);
      if (!f) return;
      rect();
      if (size.w) setView(fitBoxes([f], size.w, size.h, 1), false);
    }
    /* a card brought into view (centred) when it is outside it */
    function show(id) {
      if (!items.has(id)) return;
      rect();
      if (!size.w) return;
      const b = boxOf(id), a = screenPoint(view, b.x, b.y), z = screenPoint(view, b.x + b.w, b.y + Math.min(b.h, CAP));
      if (a.x >= 0 && a.y >= 0 && z.x <= size.w && z.y <= size.h) return;
      setView({x: size.w / 2 - (b.x + b.w / 2) * view.zoom, y: size.h / 2 - (b.y + Math.min(b.h, CAP) / 2) * view.zoom, zoom: view.zoom}, false);
    }

    /* ——— saving what moved ——— */
    /* Positions (and frame changes) shown at once and written in one layout write; they stay shown while it is under
       way, and go back to the board as it was when it fails. */
    function save(itemsPatch, framesPatch) {
      const n = ++seq, ids = Object.keys(itemsPatch || {}), fids = (framesPatch || []).map(f => f.id);
      for (const id of ids) over.set(id, {...(over.get(id) || {}), ...itemsPatch[id], n});
      for (const f of framesPatch || []) fover.set(f.id, {...(fover.get(f.id) || {}), ...f, n});
      ids.forEach(paintPos);
      fids.forEach(paintFramePos);
      Promise.resolve(ctx.moved(ids.length ? itemsPatch : null, framesPatch && framesPatch.length ? framesPatch : null)).catch(() => null).then(r => {
        if (dead) return;
        for (const id of ids) if (over.get(id) && over.get(id).n === n) over.delete(id);
        for (const id of fids) if (fover.get(id) && fover.get(id).n === n) fover.delete(id);
        if (!r && board && !drag) { render(board, filter); return; }
        ids.forEach(paintPos);
        fids.forEach(paintFramePos);
      });
    }

    /* ——— the pointer ——— */
    function down(e) {
      if (dead) return;
      if (drag) { if (drag.moved) return; drag = null; }        // a press whose release went elsewhere
      const hit = targetOf(e.target);
      if (hit.what === "field" || e.button === 2) return;
      el.focus({preventScroll: true});
      rect();
      const base = {pid: e.pointerId, sx: e.clientX, sy: e.clientY, cx: e.clientX, cy: e.clientY, moved: false};
      if (e.button === 1 || (e.button === 0 && space)) { e.preventDefault(); return start({...base, kind: "pan", vx: view.x, vy: view.y, empty: false}); }
      if (e.button !== 0) return;
      e.preventDefault();                       // no text selection, no dragging the pictures
      if (hit.what === "grip" && cards.has(hit.id)) return pressGrip(base, hit.id);
      if (hit.what === "card" && cards.has(hit.id)) return pressCard(base, hit.id, e);
      if (hit.what === "fgrip" && frameEls.has(hit.id)) {
        const f = frameOf(hit.id);
        return f && start({...base, kind: "fresize", fid: f.id, w0: f.w, h0: f.h, fel: frameEls.get(f.id).el});
      }
      if (hit.what === "fbar" && frameEls.has(hit.id)) return pressFrame(base, hit.id);
      if (e.shiftKey) {
        const boxes = board ? board.items.filter(i => C.matches(i, filter)).map(i => boxOf(i.id)) : [];
        return start({...base, kind: "box", base: e.ctrlKey || e.metaKey ? new Set(sel) : new Set(), boxes});
      }
      start({...base, kind: "pan", vx: view.x, vy: view.y, empty: true, mod: e.ctrlKey || e.metaKey});
    }
    /* A press is followed (the window's pointer events) without capturing the pointer: a press that stays a click
       keeps the element under it as the click's target, so a double-click lands on the card or the frame title it is
       on. The pointer is captured once the press becomes a drag (begin). */
    function start(d) { drag = d; }
    /* A card pressed: it joins the selection (Shift or Ctrl) or becomes it; pressed when selected, the selection stays so
       it can be dragged, and a click without moving makes it the only one (or, with Shift or Ctrl, takes it out). */
    function pressCard(base, id, e) {
      const mod = e.shiftKey || e.ctrlKey || e.metaKey;
      let after = null;
      if (!sel.has(id)) {
        if (!mod) sel = new Set();
        sel.add(id); cursor = id;
        announce();
      } else after = mod ? "out" : "only";
      const list = ordered().filter(x => cards.has(x)).map(x => ({...boxOf(x), el: cards.get(x).el}));
      start({...base, kind: "cards", card: id, after, list});
    }
    function pressGrip(base, id) {
      if (!sel.has(id)) { sel = new Set([id]); cursor = id; announce(); }
      const b = boxOf(id);
      start({...base, kind: "resize", card: id, w0: b.w, h0: b.h, el: cards.get(id).el});
    }
    function pressFrame(base, fid) {
      const f = frameOf(fid);
      if (!f) return;
      const list = membersOf(fid).filter(x => cards.has(x)).map(x => ({...boxOf(x), el: cards.get(x).el}));
      start({...base, kind: "frame", fid, f, list, fel: frameEls.get(fid).el});
    }

    function move(e) {
      const d = drag;
      if (!d || e.pointerId !== d.pid) return;
      d.cx = e.clientX; d.cy = e.clientY;
      if (!d.moved) {
        if (Math.hypot(d.cx - d.sx, d.cy - d.sy) < DRAG) return;
        d.moved = true;
        begin(d);
      }
      if (!raf) raf = requestAnimationFrame(step);
    }
    /* the drag starts: what it moves is lifted above the rest and drawn as its own layer */
    function begin(d) {
      try { el.setPointerCapture(d.pid); } catch { /* the pointer is gone already */ }
      if (d.kind === "pan") el.classList.add("panning");
      else if (d.kind === "box") boxEl.hidden = false;
      else if (d.kind === "cards") {
        for (const m of d.list) { const c = cards.get(m.id); m.el.classList.add("lift"); m.el.style.zIndex = "1000000"; if (c) { c.x = null; c.z = null; } }
      } else if (d.kind === "frame") {
        for (const m of d.list) { m.el.classList.add("lift"); const c = cards.get(m.id); if (c) c.x = null; }
        d.fel.classList.add("lift");
        const f = frameEls.get(d.fid); if (f) f.x = null;
      } else if (d.kind === "resize") { const c = cards.get(d.card); if (c) { c.w = null; c.h = undefined; } d.el.classList.add("sized"); }
      else if (d.kind === "fresize") { const f = frameEls.get(d.fid); if (f) { f.w = null; f.h = null; } }
    }
    /* one frame of the drag: transforms and sizes only, nothing read back from the page */
    function step() {
      raf = 0;
      const d = drag;
      if (!d || !d.moved) return;
      const sx = d.cx - d.sx, sy = d.cy - d.sy, dx = sx / view.zoom, dy = sy / view.zoom;
      if (d.kind === "pan") { setView({x: d.vx + sx, y: d.vy + sy, zoom: view.zoom}); return; }
      if (d.kind === "box") {
        const a = local(d.sx, d.sy), b = local(d.cx, d.cy), r = rectOf(a, b);
        boxEl.style.transform = `translate(${r.x}px,${r.y}px)`;
        boxEl.style.width = r.w + "px";
        boxEl.style.height = r.h + "px";
        const hit = within(d.boxes, rectOf(boardPoint(view, a.x, a.y), boardPoint(view, b.x, b.y)));
        sel = new Set([...d.base, ...hit]);
        paintSel();
        return;
      }
      if (d.kind === "cards" || d.kind === "frame") for (const m of d.list) m.el.style.transform = `translate(${m.x + dx}px,${m.y + dy}px)`;
      if (d.kind === "frame") d.fel.style.transform = `translate(${d.f.x + dx}px,${d.f.y + dy}px)`;
      if (d.kind === "resize") {
        d.size = resized(d.w0, d.h0, dx, dy, CARD_MIN, CARD_MAX);
        d.el.style.width = d.size.w + "px"; d.el.style.height = d.size.h + "px";
      }
      if (d.kind === "fresize") {
        d.size = resized(d.w0, d.h0, dx, dy, {w: FRAME_MIN, h: FRAME_MIN}, {w: 2000000, h: 2000000});
        d.fel.style.width = d.size.w + "px"; d.fel.style.height = d.size.h + "px";
      }
    }
    function up(e) {
      const d = drag;
      if (!d || e.pointerId !== d.pid) return;
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      d.cx = e.clientX; d.cy = e.clientY;
      if (d.moved) step();
      end(d, e.type !== "pointercancel");
    }
    /* the pointer taken away mid-drag (another window, a system gesture): what moved so far is kept */
    function lost(e) {
      const d = drag;
      if (!d || e.pointerId !== d.pid) return;
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      if (d.moved) step();
      end(d, true);
    }
    function end(d, ok) {
      drag = null;
      if (d.moved) { try { el.releasePointerCapture(d.pid); } catch { /* released already */ } }
      el.classList.remove("panning");
      boxEl.hidden = true;
      for (const m of d.list || []) m.el.classList.remove("lift");
      if (d.fel) d.fel.classList.remove("lift");
      if (ok) finish(d);
      else if (d.kind === "box") { sel = d.base; paintSel(); }
      if (pending) { const [b, f] = pending; pending = null; render(b, f); }
      else if (!ok && board) render(board, filter);
    }
    function finish(d) {
      const dx = (d.cx - d.sx) / view.zoom, dy = (d.cy - d.sy) / view.zoom;
      if (d.kind === "pan") {
        if (!d.moved && d.empty && !d.mod && sel.size) { sel = new Set(); cursor = null; announce(); }
        return;
      }
      if (d.kind === "box") { announce(); return; }
      if (d.kind === "cards") {
        if (!d.moved) {
          if (d.after === "only") { sel = new Set([d.card]); cursor = d.card; announce(); }
          else if (d.after === "out") { sel.delete(d.card); announce(); }
          else { cursor = d.card; }
          d.list.forEach(m => paintPos(m.id));
          return;
        }
        if (Math.round(dx) === 0 && Math.round(dy) === 0) { d.list.forEach(m => paintPos(m.id)); return; }
        save(dropped(d.list, dx, dy, frameList(), topZ()));
        return;
      }
      if (d.kind === "frame") {
        if (!d.moved || (Math.round(dx) === 0 && Math.round(dy) === 0)) { d.list.forEach(m => paintPos(m.id)); paintFramePos(d.fid); return; }
        const m = frameMoved(d.f, d.list, dx, dy);
        save(m.items, m.frames);
        return;
      }
      if (d.kind === "resize") {
        if (!d.moved || !d.size) { paintPos(d.card); return; }
        save({[d.card]: {w: d.size.w, h: d.size.h}});
        return;
      }
      if (d.kind === "fresize") {
        if (!d.moved || !d.size) { paintFramePos(d.fid); return; }
        save(null, [{id: d.fid, w: d.size.w, h: d.size.h}]);
      }
    }

    /* what an event is on: its target, or (when the canvas itself is the target, as after a captured drag) the element
       under the pointer */
    function hitAt(e) {
      const t = e.target === el && doc.elementFromPoint ? doc.elementFromPoint(e.clientX, e.clientY) || el : e.target;
      return targetOf(el.contains(t) ? t : el);
    }
    function dbl(e) {
      if (dead) return;
      const hit = hitAt(e);
      if (hit.what === "field" || hit.what === "fgrip") return;
      e.preventDefault();
      if (hit.what === "grip") { if (num(posOf(hit.id).h, null) != null) save({[hit.id]: {h: null}}); return; }
      if (hit.what === "card") { ctx.open(hit.id); return; }
      if (hit.what === "fbar") { rename(hit.id); return; }
      const at = pointAt(e);
      ctx.add("note", at, frameIn(at));
    }

    /* ——— right-click ——— */
    function frameItems(fid) {
      return [{label: "Rename", act: () => rename(fid)}, {label: "Select its items", act: () => selectFrame(fid)},
        "-", {label: "Delete the frame", danger: true, act: () => removeFrame(fid)}];
    }
    function context(e) {
      if (dead || (drag && drag.moved)) return;
      const hit = hitAt(e);
      if (hit.what === "field") return;
      e.preventDefault();
      if (hit.what === "card" || hit.what === "grip") {
        const id = hit.id;
        if (!sel.has(id)) { sel = new Set([id]); cursor = id; announce(); }
        ctx.menu(e, ordered());
        return;
      }
      if (hit.what === "fbar" || hit.what === "fgrip") { StudioMenu.open(e, frameItems(hit.id)); return; }
      const at = pointAt(e), fid = frameIn(at);
      const list = [{label: "New note here", act: () => ctx.add("note", at, fid)}, {label: "New frame here", act: () => ctx.add("frame", at, null)},
        {label: "Paste", act: () => paste(at, fid)}];
      if (fid) list.push("-", ...frameItems(fid));
      StudioMenu.open(e, list);
    }
    function selectFrame(fid) {
      const ids = membersOf(fid);
      if (!ids.length) { toast("There is nothing in that frame yet."); return; }
      sel = new Set(ids); cursor = ids[ids.length - 1];
      announce();
    }
    function removeFrame(fid) {
      const f = frameOf(fid), name = f ? f.title || "Frame" : "Frame";
      Promise.resolve(ctx.frames({remove_frames: [fid]})).then(r => { if (r) toast(`Deleted the frame “${name}”. Its items stay where they are.`); });
    }
    /* the menu's Paste: pictures, else text (a web address is clipped), where the menu was opened */
    async function paste(at, fid) {
      const type = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"};
      try {
        if (navigator.clipboard && navigator.clipboard.read) {
          const files = [];
          for (const c of await navigator.clipboard.read()) {
            const t = c.types.find(x => type[x]);
            if (t) files.push(new File([await c.getType(t)], "Pasted image" + type[t], {type: t}));
          }
          if (files.length) { ctx.files(files, at, fid); return; }
        }
        const words = await navigator.clipboard.readText();
        if (words && words.trim()) ctx.text(words, at, fid);
        else toast("There is nothing to paste.");
      } catch {
        toast("Studio can't read the clipboard from the menu. Press Ctrl+V instead: it pastes in the middle of the view.", true);
      }
    }

    /* ——— a frame's title typed in place ——— */
    function rename(fid) {
      const f = frameEls.get(fid), fr = frameOf(fid);
      if (!f || !fr || renaming) return;
      renaming = fid;
      const old = fr.title || "Frame", input = doc.createElement("input");
      input.className = "bc-fin";
      input.value = old;
      input.maxLength = 80;
      input.spellcheck = false;
      input.autocomplete = "off";
      input.setAttribute("aria-label", "The frame's title");
      f.t.hidden = true;
      f.bar.appendChild(input);
      input.focus({preventScroll: true});
      input.select();
      let done = false;
      const finish = (keep, refocus) => {
        if (done) return;
        done = true;
        const v = input.value.replace(/\s+/g, " ").trim();
        input.remove();
        f.t.hidden = false;
        renaming = null;
        if (keep && v && v !== old) {
          f.t.textContent = v; f.title = v;
          Promise.resolve(ctx.frames({frames: [{id: fid, title: v}]})).then(r => { if (!r && !dead && board) { f.title = null; render(board, filter); } });
        }
        if (refocus) el.focus({preventScroll: true});
      };
      input.addEventListener("keydown", e => {
        if (e.key === "Enter") { e.preventDefault(); finish(true, true); }
        else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false, true); }
      });
      input.addEventListener("blur", () => finish(true, false));
    }

    /* ——— the wheel: pans; with Ctrl it zooms around the pointer ——— */
    function wheel(e) {
      if (dead) return;
      e.preventDefault();
      if (drag) return;
      const k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? size.h || 800 : 1;
      if (e.ctrlKey || e.metaKey) {
        const p = local(e.clientX, e.clientY);
        setView(zoomAround(view, view.zoom * wheelZoom(e.deltaY * k), p.x, p.y));
        return;
      }
      const sideways = e.shiftKey && !e.deltaX;
      setView({x: view.x - (sideways ? e.deltaY : e.deltaX) * k, y: view.y - (sideways ? 0 : e.deltaY) * k, zoom: view.zoom});
    }

    /* ——— dropping files, a link or text ——— */
    function dragover(e) {
      const dt = e.dataTransfer;
      if (dead || !dt || ![...dt.types].some(t => t === "Files" || t === "text/uri-list" || t === "text/plain")) return;
      e.preventDefault();
      dt.dropEffect = "copy";
      el.classList.add("drop");
      clearTimeout(dropTimer);
      dropTimer = setTimeout(() => el.classList.remove("drop"), 150);
    }
    function drop(e) {
      const dt = e.dataTransfer;
      if (dead || !dt) return;
      const what = readDrop({files: [...dt.files], uris: dt.getData("text/uri-list"), text: dt.getData("text/plain")});
      el.classList.remove("drop");
      if (!what) return;
      e.preventDefault();
      const at = pointAt(e), fid = frameIn(at);
      if (what.files) ctx.files(what.files, at, fid);
      else if (what.url) ctx.clip(what.url, at, fid);
      else ctx.text(what.text, at, fid);
    }

    /* ——— keys (while the canvas shows, no field has the focus and no dialog is open) ——— */
    function nudge(dx, dy) {
      const ids = ordered().filter(id => cards.has(id));
      if (!ids.length) return;
      for (const id of ids) {
        const b = boxOf(id);
        over.set(id, {...(over.get(id) || {}), x: Math.round(b.x + dx), y: Math.round(b.y + dy), n: ++seq});
        paintPos(id);
        nudged.add(id);
      }
      clearTimeout(nudgeTimer);
      nudgeTimer = setTimeout(saveNudge, 400);
    }
    /* the arrows' moves saved once they stop, each card in the frame at its centre */
    function saveNudge() {
      nudgeTimer = 0;
      const ids = [...nudged].filter(id => items.has(id));
      nudged.clear();
      if (!ids.length) return;
      save(dropped(ids.map(boxOf), 0, 0, frameList()));
    }
    function keys(e) {
      if (!shown() || e.defaultPrevented || e.isComposing) return;
      if (doc.getElementById("dlg")?.open) return;
      const t = e.target;
      if (t instanceof Element && (t.matches("input, textarea, select") || t.isContentEditable)) return;
      if (!(t === doc.body || t === doc.documentElement || t === doc.getElementById("app") || el.contains(t))) return;
      const k = e.key, mod = e.ctrlKey || e.metaKey;
      if (k === " " && !mod && !e.altKey) {
        e.preventDefault();
        if (!space) { space = true; el.classList.add("grab"); }
        return;
      }
      if (mod && !e.altKey && !e.shiftKey) {
        if (k === "0") { e.preventDefault(); fit(); return; }
        if (k === "1") { e.preventDefault(); zoomTo(1); return; }
        if (k.toLowerCase() === "a") {
          e.preventDefault();
          sel = new Set(board ? board.items.filter(i => C.matches(i, filter)).map(i => i.id) : []);
          announce();
          return;
        }
      }
      if (mod || e.altKey) return;
      if (k === "+" || k === "=") { e.preventDefault(); zoomTo(zoomStep(view.zoom, 1)); return; }
      if (k === "-" || k === "_") { e.preventDefault(); zoomTo(zoomStep(view.zoom, -1)); return; }
      const arrow = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[k];
      if (arrow) {
        if (!sel.size) return;
        e.preventDefault();
        const by = e.shiftKey ? 1 : NUDGE;
        nudge(arrow[0] * by, arrow[1] * by);
        return;
      }
      if (k === "Delete" && sel.size) { e.preventDefault(); ctx.trash(ordered()); return; }
      if (k === "Enter" && sel.size) { e.preventDefault(); ctx.open(sel.has(cursor) ? cursor : ordered()[0]); return; }
      if ((k === "ContextMenu" || (e.shiftKey && k === "F10")) && sel.size) {
        const id = sel.has(cursor) ? cursor : ordered()[0], c = cards.get(id);
        if (!c) return;
        e.preventDefault();
        const r = c.el.getBoundingClientRect();
        ctx.menu({clientX: r.left + 24, clientY: r.top + 24, preventDefault() {}, stopPropagation() {}}, ordered());
      }
    }
    function keyup(e) { if (e.key === " " && space) { space = false; el.classList.remove("grab"); } }
    function blurred() { if (space) { space = false; el.classList.remove("grab"); } }

    el.addEventListener("pointerdown", down);
    // a press is followed through the window (it may leave the canvas before it becomes a drag and is captured)
    addEventListener("pointermove", move, true);
    addEventListener("pointerup", up, true);
    addEventListener("pointercancel", up, true);
    el.addEventListener("lostpointercapture", lost);
    el.addEventListener("mousedown", e => { if (e.button === 1) e.preventDefault(); });        // no autoscroll: the middle button pans
    el.addEventListener("dblclick", dbl);
    el.addEventListener("contextmenu", context);
    el.addEventListener("wheel", wheel, {passive: false});
    el.addEventListener("dragover", dragover);
    el.addEventListener("drop", drop);
    addEventListener("keydown", keys);
    addEventListener("keyup", keyup);
    addEventListener("blur", blurred);

    function destroy() {
      if (dead) return;
      if (nudgeTimer) { clearTimeout(nudgeTimer); saveNudge(); }      // the arrows' last moves are saved
      clearTimeout(keepTimer);
      keepView();                                                       // the view, when it changed since it was last kept
      dead = true;
      clearTimeout(liveTimer); clearTimeout(dropTimer); clearTimeout(fitTimer);
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect();
      removeEventListener("pointermove", move, true);
      removeEventListener("pointerup", up, true);
      removeEventListener("pointercancel", up, true);
      removeEventListener("keydown", keys);
      removeEventListener("keyup", keyup);
      removeEventListener("blur", blurred);
      host.innerHTML = "";
    }

    return {
      render,
      select(ids) { sel = new Set(ids || []); if (!sel.has(cursor)) cursor = ids && ids.length ? ids[ids.length - 1] : null; paintSel(); },
      selected: () => ordered(),
      show, goToFrame, rename, fit, zoomTo,
      toBoard(clientX, clientY) { rect(); const p = boardPoint(view, clientX - at0.left, clientY - at0.top); return {x: Math.round(p.x), y: Math.round(p.y)}; },
      get zoom() { return view.zoom; },
      destroy,
    };
  }

  root.BoardCanvas = {create, Undo, CAP, EXCERPT, NEW_FRAME, NUDGE, STEPS, boardPoint, screenPoint, zoomAround, zoomStep, wheelZoom,
    fitBoxes, readView, viewKey, rectOf, within, dropped, frameMoved, resized, readDrop, targetOf, marks, cardHtml};
})(typeof window !== "undefined" ? window : globalThis);
