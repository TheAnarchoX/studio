"use strict";
/* The research board beside the text, and its items into the text.
   window.BoardPanel draws the writing window's Board panel (book-rail.js hands it the panel's body): the book's board
   or the shared board as compact rows grouped by frame, searched on the server, read again when the board's stamp
   moves. window.BoardDrop is the text's plugin (book-text.js adds it after BookTools'): a quote, a source or an image
   dragged from the panel, or put at the cursor with its button, is prepared by POST /api/research/use and inserted in
   one transaction where it was dropped, mapped through every change made while the server answered.
   A classic script after board-core.js and board.js; it touches no DOM and no network at load, so
   tests/js/board_rail.js runs its helpers in node. */
(function (root) {
  const {Plugin, PluginKey, Fragment, TextSelection} = root.PM;
  const S = root.BookSchema, N = S.nodes, BC = root.BoardCore;

  /* ——— into the text ——— */

  const KEY = new PluginKey("board-drop");
  let seq = 0;

  /* `fn` over the text of a run of inline nodes (JSON) as one string, so quote marks are decided on the paragraph and
     not node by node; each node keeps its share (fn keeps the number of characters). */
  function mapText(list, fn) {
    const parts = list.map(n => n && n.type === "text" ? [...String(n.text || "")] : n && n.type === "hard_break" ? ["\n"] : []);
    const flat = parts.flat(), all = [...fn(flat.join(""))];
    if (all.length !== flat.length) return list;
    let at = 0;
    return list.map((n, i) => {
      const s = all.slice(at, at += parts[i].length).join("");
      return n && n.type === "text" ? {...n, text: s} : n;
    });
  }
  /* inline JSON as nodes; one this schema can't take is kept as its text */
  function inlineNodes(list) {
    const out = [];
    for (const j of list || []) {
      try { out.push(S.nodeFromJSON(j)); }
      catch (e) { if (j && typeof j.text === "string" && j.text) out.push(S.text(j.text)); }
    }
    return out;
  }
  /* straight quotes typed on the board become the style's, as typing them in the text does */
  const curly = style => text => {
    let out = "";
    for (const c of text) out += c === "\"" || c === "'" ? root.BookText.quoteFor(out, c, style) : c;
    return out;
  };
  const citeNode = (key, locator) => N.cite.create({items: [{key, prefix: "", locator: locator || ""}]});

  /* What /api/research/use prepared, as it stands in the text in the quote style `style` (the style sheet's "„…”"):
     {inline: [nodes] | null, block: node, note?: [nodes]}. `inline` goes in a line of text; `block` after the block at
     the place (or, for something inline, where no line of text can take it); `note`, a block quote's inline form, in a
     note, which takes no block. null: nothing to put in (a quote without text). */
  function content(prep, style) {
    if (!prep) return null;
    if (prep.kind === "cite") { const c = citeNode(prep.key, ""); return {inline: [c], block: N.paragraph.create(null, c)}; }
    if (prep.kind === "image") return {inline: null, block: N.image.create({src: prep.src, alt: prep.alt || "", width: null})};
    const paras = prep.kind === "quote" && Array.isArray(prep.paragraphs) ? prep.paragraphs : [];
    if (!paras.some(p => p && p.length)) return null;
    const parts = BC.quoteParts({...prep, paragraphs: paras}, style);
    const tail = prep.key ? [S.text(" "), citeNode(prep.key, prep.locator)] : [];
    const fix = t => curly(style)(BC.innerQuotes(t, style));
    if (parts.block) {
      const fixBlock = curly(style);
      // in a note it runs on between the marks, its paragraphs joined with a space
      const run = paras.filter(p => p && p.length).flatMap((p, i) => [...(i ? [{type: "text", text: " "}] : []), ...p]);
      return {inline: null, note: [S.text(parts.open), ...inlineNodes(mapText(run, fix)), S.text(parts.close), ...tail],
        block: N.blockquote.create(null, paras.map((p, i) =>
          N.paragraph.create(null, [...inlineNodes(mapText(p || [], fixBlock)), ...(i === paras.length - 1 ? tail : [])])))};
    }
    const inline = [S.text(parts.open), ...inlineNodes(mapText(paras[0], fix)), S.text(parts.close), ...tail];
    return {inline, block: N.paragraph.create(null, inline)};
  }

  /* for a line that takes no line breaks or notes (a title, a note's own text): a space for a break, no notes */
  const plainer = list => list.flatMap(n => n.type === N.hard_break ? [S.text(" ")] : n.type === N.note ? [] : [n]);
  const NO_SPACE_AFTER = /[\s([{<—–/„“‘‚«‹"']/u;          // after these the quote needs no space before it
  const SPACE_BEFORE = /[\p{L}\p{N}\uFFFC([„“‘‚«‹"']/u;               // before these it needs one after it
  const charOf = (n, last) => !n ? "" : n.isText ? (last ? n.text.slice(-1) : n.text.slice(0, 1)) : n.type === N.hard_break ? "\n" : "\uFFFC";

  /* Where content goes for a position: {from, to, content, inline}. Inline in the line of text there (a space added
     where it would touch a word); else a block after the top-level block there (in place of it when it is an empty
     paragraph), never inside another block; between blocks, there, but never before the title. */
  function place(doc, pos, c) {
    pos = Math.max(0, Math.min(pos, doc.content.size));
    const $p = doc.resolve(pos);
    const inline = $p.parent.type === N.note ? c.note || c.inline : c.inline;      // a note takes no block
    if (inline && $p.parent.inlineContent) {
      for (const list of [inline, plainer(inline)]) {
        if (!list.length || !$p.parent.canReplace($p.index(), $p.index(), Fragment.fromArray(list))) continue;
        const before = charOf($p.nodeBefore, true), after = charOf($p.nodeAfter, false);
        const nodes = [...(before && !NO_SPACE_AFTER.test(before) ? [S.text(" ")] : []), ...list,
          ...(after && SPACE_BEFORE.test(after) ? [S.text(" ")] : [])];
        return {from: pos, to: pos, content: Fragment.fromArray(nodes), inline: true};
      }
    }
    if ($p.depth >= 1) {
      const top = $p.node(1), start = $p.before(1);
      if (top.type === N.paragraph && !top.content.size) return {from: start, to: start + top.nodeSize, content: c.block, inline: false};
      return {from: $p.after(1), to: $p.after(1), content: c.block, inline: false};
    }
    const first = doc.firstChild, at = first && first.type === N.title && pos < first.nodeSize ? first.nodeSize : pos;
    return {from: at, to: at, content: c.block, inline: false};
  }

  /* The insert as one transaction on `state`: at `pos`, or at the end of the block there when what was at `pos` has
     been deleted (`gone`). With `caret`, the cursor goes after it (a block: into the line after it, made when there is
     none). Returns {tr, at, end}: end is the position after what was inserted. */
  function insert(state, pos, gone, c, {caret = false} = {}) {
    const doc = state.doc, tr = state.tr;
    if (gone) {
      const $g = doc.resolve(Math.max(0, Math.min(pos, doc.content.size)));
      if ($g.parent.inlineContent) pos = $g.end();
    }
    const at = place(doc, pos, c);
    let end;
    if (at.inline) { tr.insert(at.from, at.content); end = at.from + at.content.size; }
    else { tr.replaceWith(at.from, at.to, at.content); end = at.from + at.content.nodeSize; }
    if (caret) caretAfter(tr, at, end);
    return {tr, at, end};
  }
  function caretAfter(tr, at, end) {
    if (at.inline) { tr.setSelection(TextSelection.create(tr.doc, end)); return; }
    if (at.content.isTextblock) { tr.setSelection(TextSelection.create(tr.doc, end - 1)); return; }
    const next = tr.doc.resolve(end).nodeAfter;
    if (!next || !next.isTextblock) tr.insert(end, N.paragraph.create());
    tr.setSelection(TextSelection.create(tr.doc, end + 1));
  }

  /* The inserts waiting for the server: [{id, pos, gone, touched}], mapped through every transaction (pos sticks to
     what was before it, so typing at that very place goes after the insert); gone: what was there was deleted;
     touched: the text or its cursor changed meanwhile, so the cursor is left where the author put it. */
  function applyPending(tr, list) {
    const m = tr.getMeta(KEY) || {};
    let next = list;
    if (next.length && (tr.docChanged || tr.selectionSet)) {
      next = next.map(e => {
        if (!tr.docChanged) return {...e, touched: true};
        const r = tr.mapping.mapResult(e.pos, -1);
        return {...e, pos: r.pos, gone: e.gone || r.deletedAcross, touched: true};
      });
    }
    if (m.add) next = [...next, {gone: false, touched: false, ...m.add}];
    if (m.done != null) next = next.filter(e => e.id !== m.done);
    return next;
  }

  /* only drags from the board (they carry MIME); ProseMirror's own drop never also inserts their text */
  const dropInto = T => (view, e) => {
    const dt = e.dataTransfer;
    if (!dt || ![...(dt.types || [])].includes(BC.MIME)) return false;
    const ref = BC.readPayload(dt.getData(BC.MIME));
    if (!ref) return false;
    e.preventDefault();
    const at = view.posAtCoords({left: e.clientX, top: e.clientY});
    put(T, view, ref, at ? at.pos : view.state.selection.to).catch(err => T.ctx.say(err.message, true));
    return true;
  };
  function plugins(T) {
    return [new Plugin({key: KEY, state: {init: () => [], apply: applyPending}, props: {handleDrop: dropInto(T)}})];
  }
  /* a note's own editor (book-text.js notePlugins): a drop there goes into the note, through the text's pending list */
  function notePlugins(T, nv) {
    return [new Plugin({props: {handleDrop: dropInto(T)}})];
  }

  const noteOf = (T, view) => [...T.margin.notes].find(nv => nv.inner === view) || null;
  const noteAround = (T, pos) => [...T.margin.notes].find(nv => { const p = nv.getPos(); return p != null && pos > p && pos < p + nv.node.nodeSize; }) || null;

  /* An item of a board (ref {board, id}) into the text T: at `pos` of `view` (the text's view or a note's; the cursor
     when pos is left out). Resolves to true when it went in. */
  async function put(T, view, ref, pos) {
    const outer = T && !T.destroyed ? T.view : null, W = root.BookTools && root.BookTools.state.W;
    if (!outer || !W || !ref) return false;
    const say = (m, bad) => T.ctx.say(m, bad);
    if (T.locked) { say("The text is being changed: try again in a moment."); return false; }
    view = view || outer;
    let off = 0;
    if (view !== outer) { const nv = noteOf(T, view), p = nv && nv.getPos(); if (p == null) return false; off = p + 1; }
    const sel = view.state.selection, id = ++seq;
    outer.dispatch(outer.state.tr.setMeta(KEY, {add: {id, pos: off + (pos == null ? sel.to : pos)}}));
    const forget = () => { if (!outer.isDestroyed) outer.dispatch(outer.state.tr.setMeta(KEY, {done: id})); };
    let prep;
    try { prep = await api("/api/research/use", {book: W.book.id, b: ref.board, id: ref.id}); }
    catch (e) { forget(); say(e.message, true); return false; }
    if (T.destroyed || outer.isDestroyed) return false;
    const entry = (KEY.getState(outer.state) || []).find(e => e.id === id);
    if (!entry) return false;
    const c = content(prep, (T.ctx.sheet() || {}).quotes);
    if (!c || T.locked) {
      forget();
      say(T.locked ? "The text is being changed: try again in a moment." : prep.kind === "quote" ? "This quote has no text yet." : "This item can't go into the text.", !T.locked);
      return false;
    }
    let tr, at, end;
    try { ({tr, at, end} = insert(outer.state, entry.pos, entry.gone, c)); }
    catch (e) { forget(); say(`It can't go in there: ${plain(e.message)}.`, true); return false; }
    tr.setMeta(KEY, {done: id});
    // the cursor follows the insert only when the author hasn't moved on meanwhile
    const here = !entry.touched && !view.isDestroyed && view.state.selection.eq(sel);
    const nv = at.inline ? noteAround(T, at.from) : null;
    if (here && !nv) { caretAfter(tr, at, end); tr.scrollIntoView(); }
    outer.dispatch(tr);
    if (here) {
      if (!nv) outer.focus();
      else if (!nv.inner.isDestroyed) {
        const p = nv.getPos(), inner = nv.inner, at2 = p == null ? null : end - p - 1;
        if (at2 != null && at2 >= 0 && at2 <= inner.state.doc.content.size) inner.dispatch(inner.state.tr.setSelection(TextSelection.create(inner.state.doc, at2)));
        inner.focus();
      }
    }
    if (prep.warning) say(prep.warning, true);
    else if (prep.kind === "quote" && !prep.key) say("This quote has no source yet.");
    else if (prep.added) say(prep.kind === "quote" ? "Quoted. Its source is in the book's sources now." : "Cited. The source is in the book's sources now.");
    return true;
  }

  root.BoardDrop = {plugins, notePlugins, put, KEY, content, place, insert, mapText, pending: state => KEY.getState(state) || []};

  /* ——— the panel ——— */

  const ACT = {quote: "Quote at the cursor", cite: "Cite at the cursor", image: "Put in the text"};
  const DRAG = {quote: "Drag into the text to quote it", cite: "Drag into the text to cite it", image: "Drag into the text to put it there"};
  const PLURAL = {note: ["note", "notes"], quote: ["quote", "quotes"], source: ["source", "sources"], clip: ["web clip", "web clips"],
    image: ["image", "images"], piece: ["piece", "pieces"], link: ["link", "links"]};
  /* what an item does in the text: a quote is quoted, an image put in, anything else with a source cited */
  const actOf = i => !i || i.error ? null : i.type === "quote" ? "quote" : i.type === "image" ? "image"
    : i.csl && typeof i.csl === "object" && i.type !== "note" && i.type !== "piece" ? "cite" : null;
  const clean = v => typeof v === "string" ? v.replace(/\s+/g, " ").trim() : "";
  const firstWords = (s, n = 14) => { const w = clean(s).split(" ").filter(Boolean); return w.slice(0, n).join(" ") + (w.length > n ? "…" : ""); };
  const cslOf = i => i.csl && typeof i.csl === "object" ? i.csl : null;
  /* a piece of this book an item links to: its title in the book's contents */
  function pieceTitle(i) {
    if (i.piece && typeof i.piece === "object") return clean(i.piece.title);
    const b = P.ctx && P.ctx.tools.W && P.ctx.tools.W.book;
    const e = b && typeof i.book === "string" && i.book.toLowerCase() === String(b.id).toLowerCase() && (b.contents || []).find(x => x.file === i.file);
    return e ? clean(e.title) : "";
  }
  /* What an item is called, as on the board (board.js titleOf): its title, its source's title, the title of the piece it
     links to, else the first words of its text (own: false, set apart); never its id. */
  function titleOf(i) {
    const t = clean(i.title) || clean(cslOf(i) && cslOf(i).title) || (i.type === "piece" ? pieceTitle(i) : "");
    if (t) return {text: t, own: true};
    return {text: firstWords(i.excerpt) || (i.link && i.link.missing ? "The original is gone" : BC.KIND_NAME[i.type] || "Item"), own: false};
  }
  const nameOf = i => titleOf(i).text;
  /* the line under it: a quote's citation; a citable item's short form (Author year), a clip without an author its site */
  function sourceOf(i) {
    if (i.type === "quote") return clean(i.source_label);
    const csl = cslOf(i), people = csl && [csl.author, csl.editor].some(a => Array.isArray(a) && a.length);
    if (i.type === "clip" && !people) return clean(i.site) || clean(csl && csl["container-title"]);
    if (csl) { try { return root.BookText.sourceShort(csl); } catch (e) { return ""; } }
    return "";
  }

  const P = {root: null, ctx: null, bookId: null, which: "book", cache: new Map(), q: "", hits: null, open: null,
    timer: 0, poll: 0, token: null, loading: null, err: null, full: null};
  const boardOf = () => P.which === "shared" ? null : P.bookId;
  const cacheKey = b => b == null ? "" : "b:" + b;
  const data = () => P.cache.get(cacheKey(boardOf())) || null;
  const itemOf = id => (data()?.items || []).find(i => i.id === id) || null;
  /* the panel is open (shown or not: focus mode hides the rail without closing it) */
  const alive = el => !!el && el === P.root && el.isConnected && !el.closest(".br-panel")?.hidden;
  const emptyP = msg => `<p class="br-empty">${msg}</p>`;

  function render(host, ctx) {
    // drawn there already (another piece is written in, the panel opened again): the board doesn't follow the piece;
    // it is read again, and the search field, the open row and the scroll stay
    if (P.root && P.root.parentNode === host && P.bookId === ctx.book.id) { P.ctx = ctx; startPoll(P.root); refresh(); return; }
    if (P.bookId !== ctx.book.id) Object.assign(P, {bookId: ctx.book.id, which: "book", q: "", hits: null, open: null, err: null, cache: new Map()});
    P.ctx = ctx;
    clearTimeout(P.timer);
    const el = document.createElement("div");
    el.className = "bp";
    el.innerHTML = `<div class="br-tools bp-tools"><input class="input bp-q" type="search" placeholder="Search the board" aria-label="Search the board"
        value="${esc(P.q)}" spellcheck="false"><a class="btn small" data-bp-board href="#">Open the board</a></div>
      <div class="seg bp-which" role="group" aria-label="Which board"><button type="button" data-bp-which="book">This book</button><button type="button" data-bp-which="shared">Shared board</button></div>
      <div class="bp-list"></div>`;
    host.replaceChildren(el);
    P.root = el;
    wire(el);
    paint();
    load();
    if (P.q.trim()) search();
    startPoll(el);
  }

  function head() {
    const b = boardOf(), book = P.ctx.tools.W?.book || P.ctx.book;
    P.ctx.head("Board", b == null ? "Shared board" : book.title || "");
  }
  function counts(d, shown) {
    const n = d.items.length;
    if (P.hits) return `${shown.length} of ${n} ${n === 1 ? "item" : "items"}`;
    if (!n) return "Nothing on it yet";
    const k = d.kinds || {};
    return Object.keys(PLURAL).filter(t => k[t]).map(t => `${k[t]} ${PLURAL[t][k[t] === 1 ? 0 : 1]}`).join(" · ");
  }

  function paint() {
    const el = P.root;
    if (!el || !P.ctx) return;
    el.querySelectorAll("[data-bp-which]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.bpWhich === P.which)));
    el.querySelector("[data-bp-board]").href = BC.boardHash(boardOf());
    head();
    const list = el.querySelector(".bp-list"), d = data();
    const a = document.activeElement, was = a && list.contains(a) ? (a.dataset.bpRow ? `[data-bp-row="${CSS.escape(a.dataset.bpRow)}"]`
      : a.dataset.bpPut ? `[data-bp-put="${CSS.escape(a.dataset.bpPut)}"]` : null) : null;
    if (!d) {
      P.ctx.says("");
      list.innerHTML = emptyP(P.err ? `The board can't be read: ${esc(plain(P.err))}.` : "Reading the board…");
      return;
    }
    const shown = P.hits ? d.items.filter(i => P.hits.ids.has(i.id)) : d.items;
    P.ctx.says(counts(d, shown));
    if (!d.items.length) {
      list.innerHTML = emptyP("Nothing on this board yet. Put quotes, sources and images on it, then drag them into the text.");
      return;
    }
    if (!shown.length) { list.innerHTML = emptyP(P.hits.error ? esc(plain(P.hits.error)) + "." : "Nothing on this board matches."); return; }
    const frames = d.frames || [], groups = BC.groups(shown, frames, "added").filter(g => g.items.length);
    list.innerHTML = groups.map(g => `<section class="br-g bp-g">${frames.length ? `<h3 class="br-g-h"><span>${esc(g.frame ? g.frame.title || "A frame" : "Not in a frame")}</span>
        <span class="br-g-n">${g.items.length}</span></h3>` : ""}<ol class="br-list">${g.items.map(row).join("")}</ol></section>`).join("");
    if (was) list.querySelector(was)?.focus();
  }

  function row(i) {
    const act = actOf(i), open = P.open === i.id, snip = P.hits && P.hits.snips.get(i.id), name = titleOf(i), src = sourceOf(i);
    // opened, an item named by its first words shows them once: in its text below
    const named = !(open && !name.own && clean(i.excerpt));
    return `<li class="bp-i${open ? " open" : ""}"><button type="button" class="br-li bp-row" data-bp-row="${esc(i.id)}" aria-expanded="${open}"
        ${act ? `draggable="true" title="${DRAG[act]}"` : ""}><span class="bp-k">${esc(BC.KIND_NAME[i.type] || i.type)}</span>
        ${named ? `<span class="bp-t${name.own ? "" : " words"}">${esc(name.text)}</span>` : ""}${src ? `<span class="bp-s">${esc(src)}</span>` : ""}
        ${snip ? `<span class="bp-m">${esc(snip)}</span>` : ""}</button>${open ? more(i, act) : ""}</li>`;
  }
  /* an opened row: its picture, its whole text (plain words, its paragraphs kept; the excerpt until it is read), what
     it does in the text, and the way to it on the board */
  function more(i, act) {
    const full = fullText(i), x = typeof full === "string" ? full : String(i.excerpt || "") + (String(i.excerpt || "").length >= 280 ? "…" : "");
    return `<div class="bp-more">${i.type === "image" && i.thumb ? `<img class="bp-img" src="${esc(i.thumb)}" alt="" draggable="false">` : ""}
      ${x.trim() ? `<p class="bp-x">${esc(x)}</p>` : ""}
      ${act ? `<div class="br-acts"><button type="button" class="btn small solid" data-bp-put="${esc(i.id)}">${ACT[act]}</button></div>` : ""}
      <a class="bm-btn bp-open" href="${BC.boardHash(boardOf())}" data-bp-open="${esc(i.id)}">Open on the board</a></div>`;
  }
  /* the open row's whole text (GET /api/research/item): read when it opens and again when the item changed; null while
     it is being read, false when it couldn't be */
  function fullText(i) {
    const b = boardOf(), k = `${cacheKey(b)}\n${i.id}\n${i.updated || ""}`;
    if (P.full && P.full.k === k) return P.full.text;
    const f = P.full = {k, text: null}, el = P.root;
    api(`/api/research/item?${[BC.boardParam(b), "id=" + encodeURIComponent(i.id)].filter(Boolean).join("&")}`)
      .then(it => { f.text = BC.plainText(it && it.text); }, () => { f.text = false; })
      .then(() => { if (P.full === f && alive(el)) paint(); });
    return null;
  }

  /* the board, read when the panel opens, and again when its stamp moved */
  async function load(force = false) {
    const b = boardOf(), k = cacheKey(b), had = P.cache.get(k);
    if (P.loading === k) return;
    P.loading = k;
    let changed = false;
    try {
      if (had && !force) {
        const s = await api(`/api/research/stamp?${BC.boardParam(b)}`);
        if (s.stamp === had.stamp) return;
      }
      P.cache.set(k, await api(`/api/research?${BC.boardParam(b)}`));
      P.err = null; changed = true;
    } catch (e) { if (!had) { P.err = e.message; changed = true; } }
    finally { if (P.loading === k) P.loading = null; }
    // painted in the panel shown now (a render while this read was out is skipped its own read, not its paint)
    if (!changed || !alive(P.root) || cacheKey(boardOf()) !== k) return;
    if (P.q.trim()) search(); else paint();
  }
  function startPoll(el) {
    clearInterval(P.poll);
    const t = P.poll = setInterval(() => {
      if (!alive(el)) { clearInterval(t); return; }          // closed, another panel, or the window gone
      if (document.hidden || !el.offsetParent) return;      // open but not shown now
      load();
    }, 2000);
  }
  function search() {
    const q = P.q.trim(), b = boardOf(), token = (P.token = {}), el = P.root;
    if (!q) { P.hits = null; paint(); return; }
    api(`/api/research/search?${[BC.boardParam(b), "q=" + encodeURIComponent(q)].filter(Boolean).join("&")}`)
      .then(r => { if (P.token === token && alive(el)) { P.hits = {ids: new Set(r.map(h => h.id)), snips: new Map(r.map(h => [h.id, h.snippet || ""]))}; paint(); } })
      .catch(e => { if (P.token === token && alive(el)) { P.hits = {ids: new Set(), snips: new Map(), error: e.message}; paint(); } });
  }

  function putAtCursor(id) {
    const tools = P.ctx.tools, p = tools.activePiece(), T = p && p.text && !p.text.destroyed ? p.text : null;
    if (!T) { toast("Open a piece to put this in."); return; }
    if (T.locked) return;
    root.BoardDrop.put(T, tools.writingView(T), {board: boardOf(), id}).catch(e => toast(e.message, true));
  }

  function wire(el) {
    const q = el.querySelector(".bp-q");
    q.addEventListener("input", () => {
      P.q = q.value;
      clearTimeout(P.timer);
      P.timer = setTimeout(search, 250);
    });
    q.addEventListener("keydown", e => {
      if (e.key !== "Escape" || !q.value) return;           // empty, Escape goes back to the text (the rail's)
      e.preventDefault(); e.stopPropagation();
      q.value = P.q = ""; clearTimeout(P.timer); search();
    });
    el.addEventListener("click", e => {
      const w = e.target.closest("[data-bp-which]");
      if (w) {
        if (w.dataset.bpWhich === P.which) return;
        P.which = w.dataset.bpWhich; P.open = null; P.hits = null; P.token = null;
        paint(); load();
        if (P.q.trim()) search();
        return;
      }
      const put = e.target.closest("[data-bp-put]");
      if (put) return putAtCursor(put.dataset.bpPut);
      const go = e.target.closest("[data-bp-open]");
      if (go) {                   // the board's page, with the item open there (its address alone without board.js)
        if (root.Board && root.Board.goTo) { e.preventDefault(); root.Board.goTo(boardOf(), go.dataset.bpOpen); }
        return;
      }
      const r = e.target.closest("[data-bp-row]");
      if (r) { P.open = P.open === r.dataset.bpRow ? null : r.dataset.bpRow; paint(); }
    });
    // the button keeps the cursor where it is in the text (as the Sources panel's Cite does)
    el.addEventListener("mousedown", e => { if (e.button === 0 && e.target.closest("[data-bp-put]")) e.preventDefault(); });
    el.addEventListener("dragstart", e => {
      const r = e.target.closest && e.target.closest("[data-bp-row]"), i = r && itemOf(r.dataset.bpRow);
      if (!r) return;
      if (!actOf(i)) { e.preventDefault(); return; }
      e.dataTransfer.effectAllowed = "copy";
      e.dataTransfer.setData(BC.MIME, BC.payload(boardOf(), i));
      e.dataTransfer.setData("text/plain", i.type === "quote" ? String(i.excerpt || "") : nameOf(i));
    });
  }

  /* the book was read again, or another piece is the one written in: the head, and the board if it changed */
  function refresh() {
    if (!alive(P.root)) return;
    head();
    load();
  }

  root.BoardPanel = {render, refresh};
})(typeof window !== "undefined" ? window : globalThis);
