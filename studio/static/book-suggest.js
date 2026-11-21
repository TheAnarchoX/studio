"use strict";
/* Claude's suggestions in the writing window (suggestions.json, through the book's API): the helpers here touch no DOM,
   so tests/js/book_suggest.js runs them in node. `locate` is suggestions.locate in JavaScript, over
   BookTools.containersOf: tests/fixtures/suggest-locate.json keeps the two in step. A classic script after
   book-rail.js; sets window.BookSuggest. */
(function (root) {
  const BT = root.BookText, Tools = root.BookTools;
  const CONTEXT = 32;             // suggestions.CONTEXT: the characters of text kept either side of a quote
  const KIND_NAME = {edit: "Edit", note: "Note", index: "Index", cite: "Citation", comment: "Comment"};

  /* ——— helpers (no DOM) ——— */

  /* text as the row shows it: a note number or citation (GAP) and a line break are spaces */
  const shown = text => String(text ?? "").replace(new RegExp(`[${Tools.GAP}\\n]`, "g"), " ");

  /* How much of the stored context sits next to a match: the common run before it plus the common run after
     (suggestions.score). Python counts characters (code points), so the runs are compared as code points; start and
     end are positions in the text (UTF-16 units). */
  function score(text, start, end, before, after) {
    const a = Array.from(text.slice(0, start)), b = Array.from(before), c = Array.from(text.slice(end)), d = Array.from(after);
    let n = 0, m = 0;
    while (n < Math.min(a.length, b.length) && a[a.length - 1 - n] === b[b.length - 1 - n]) n++;
    while (m < Math.min(c.length, d.length) && c[m] === d[m]) m++;
    return n + m;
  }

  /* The suggestion's words in the text's boxes (BookTools.containersOf): {box, from, to, index} or null. `index` is
     the place among all the matches of the quote, in every kind of box and captions too (the numbering Find uses);
     the candidates are those in the box kind s.in. Several: the best score of before and after, the first on a tie;
     null when there is stored context and no candidate shares any of it. */
  function locate(boxes, s) {
    const all = [];
    for (const box of boxes) for (const [from, to] of Tools.findIn(box.text, s.quote, {case: true})) all.push({box, from, to, index: all.length});
    const kind = s.in || "text", found = all.filter(m => m.box.kind === kind);
    if (!found.length) return null;
    if (found.length === 1) return found[0];
    const before = s.before || "", after = s.after || "";
    let best = null, top = -1;
    for (const m of found) {
      const sc = score(m.box.text, m.from, m.to, before, after);
      if (sc > top) { best = m; top = sc; }
    }
    return before + after && top === 0 ? null : best;
  }

  /* ——— a suggestion's row: the inner HTML ——— */
  const length = s => Array.from(s).length;
  /* The stored context is CONTEXT characters at most: a shorter one reached the start or end of its line (nothing
     more to show), a full one was cut, maybe in a word: whole words only, and "…" for the rest. */
  const wordsBefore = s => (s = shown(s), length(s) >= CONTEXT ? {text: s.replace(/^\S*\s+/, ""), cut: true} : {text: s, cut: false});
  const wordsAfter = s => (s = shown(s), length(s) >= CONTEXT ? {text: s.replace(/\s+\S*$/, ""), cut: true} : {text: s, cut: false});
  /* the last words of a quote, as many as fit in `max` characters (the first word stays when the cut falls between words) */
  function tail(s, max = 40) {
    const cps = Array.from(shown(s));
    if (cps.length <= max) return cps.join("");
    const from = cps.length - max, part = cps.slice(from).join("");
    return /\s/.test(cps[from - 1]) ? part : part.replace(/^\S*\s+/, "");
  }

  function rowHtml(s, {sources, showPiece} = {}) {
    const quote = shown(s.quote);
    let change;
    if (s.kind === "edit") {
      const b = wordsBefore(s.before || ""), a = wordsAfter(s.after || "");
      change = `${b.cut ? "…" : ""}${esc(b.text)}<del>${esc(quote)}</del><ins>${esc(shown(s.text))}</ins>${esc(a.text)}${a.cut ? "…" : ""}`;
    } else if (s.kind === "note") change = `After ‘…${esc(tail(quote))}’: ${esc(shown(s.text))}`;
    else if (s.kind === "index") change = esc(quote) + (s.term && s.term !== s.quote ? ` → ${esc(shown(s.term))}` : "");
    else if (s.kind === "cite") {
      const label = BT.citeLabel([{key: s.source, prefix: "", locator: s.locator || ""}], sources || []);
      change = `After ‘…${esc(tail(quote))}’: ${esc(label)}`;
    } else change = `‘${esc(quote)}’: ${esc(shown(s.text))}`;
    const kind = (KIND_NAME[s.kind] || s.kind) + (showPiece && s.piece ? ` · ${s.piece}` : "");
    return `<span class="bs-k">${esc(kind)}</span><span class="bs-x">${change}</span>` + (s.why ? `<span class="bs-w">${esc(s.why)}</span>` : "");
  }

  /* ——— a suggestion in the text while the panel is open: what its words get (cls, title) and what is drawn after them
     (widget: {tag, cls, text, title}). Every one is underlined; the current one (`on`) shows its change: an edit's words
     struck through and the new after them, underlined; a note as a faint note mark; a citation as its faint label; an
     index term with its term in a tooltip; a comment highlighted as comments are, its remark in a tooltip. Only text:
     a widget is filled with textContent ——— */
  function previewOf(s, on, {sources} = {}) {
    if (!on) return {cls: "bs-u"};
    if (s.kind === "edit") {
      const text = shown(s.text);
      return {cls: "bs-u on bs-del", ...(text ? {widget: {tag: "ins", cls: "bs-ins", text}} : {})};
    }
    if (s.kind === "note") return {cls: "bs-u on", widget: {tag: "sup", cls: "bs-ghost bs-gn", text: "+", title: shown(s.text)}};
    if (s.kind === "cite") return {cls: "bs-u on", widget: {tag: "span", cls: "bs-ghost bs-gc", text: BT.citeLabel([{key: s.source, prefix: "", locator: s.locator || ""}], sources || [])}};
    if (s.kind === "index") return {cls: "bs-u on", title: "Index: " + shown(s.term || s.quote)};
    if (s.kind === "comment") return {cls: "bs-u on bk-com-on", title: shown(s.text)};
    return {cls: "bs-u on"};
  }

  const helpers = {KIND_NAME, locate, score, shown, rowHtml, previewOf};
  if (typeof document === "undefined") { root.BookSuggest = helpers; return; }          // node: the helpers only

  /* ——— the Suggestions panel: the rail's sixth (book-rail.js mounts it with its body, head line, dialog and guard) ———
     The list is the book's open suggestions, read when the panel opens and again when the book is (the poll, or a
     decision here); grouped by the call that made them, the newest group first, each group in book order. Whether a
     suggestion can still be accepted is worked out on the text in the editor for an open piece (typing not yet saved
     counts) and as the server found it on disk for the rest; the server locates again before it applies anything.
     Accepting changes pieces (BookTools.guarded: the open ones saved, locked, and read again as one undo step);
     rejecting and bringing back change only suggestions.json. While it is open the texts show the list (the preview,
     below). */
  const {TextSelection, Plugin, PluginKey, Decoration, DecorationSet} = root.PM;
  const SCOPE = "bookSuggestScope", DECIDED_SHOWN = 50;
  const SAID = {accepted: "Accepted", rejected: "Rejected", withdrawn: "Withdrawn"};
  const many = (n, one, more = one + "s") => `${bookCount(n)} ${n === 1 ? one : more}`;
  const empty = msg => `<p class="br-empty">${msg}</p>`;
  const DECIDE = "/api/book/suggestions/decide";

  function panel({body, says, tools, guarded, ask, book, isOpen}) {
    const S = {list: null, error: "", decided: null, decError: "", decOpen: false, loaded: false, busy: false, token: 0, decToken: 0,
      timer: 0, ptimer: 0, first: false, here: new Map(), groups: []};
    const query = status => `/api/book/suggestions?b=${encodeURIComponent(book().id)}&status=${status}`;
    const scope = () => pref.get(SCOPE, "book") === "piece" ? "piece" : "book";
    const pieceFile = () => tools.activePiece()?.file || null;
    const inScope = s => scope() === "book" || s.file === pieceFile();
    const waiting = id => (S.list || []).find(s => s.id === id) || null;
    /* its words are there to change: in an open piece as the editor has them now, elsewhere as the server found them */
    const can = s => !s.missing && (S.here.has(s.id) ? S.here.get(s.id) : !!s.found);
    const openPieces = files => tools.panes().map(x => x.piece).filter(p => p && p.text && !p.closed && files.has(p.file));
    const noLonger = n => n === 1 ? "That suggestion was no longer waiting: the list is up to date now." : `${bookCount(n)} were no longer waiting: the list is up to date now.`;

    /* the open suggestions of open pieces, found again in the editors' documents */
    function relocate() {
      S.here.clear();
      const texts = new Map(), boxes = new Map();
      for (const p of tools.panes().map(x => x.piece)) if (p?.text && !p.closed && !p.text.destroyed) texts.set(p.file, p.text);
      for (const s of S.list || []) {
        const T = texts.get(s.file);
        if (!T || s.missing) continue;
        if (!boxes.has(s.file)) boxes.set(s.file, Tools.containersOf(T.view.state.doc, T.ctx.language));
        S.here.set(s.id, !!locate(boxes.get(s.file), s));
      }
    }
    /* the list from the server (and the decided ones while Decided is unfolded); false when a newer read overtook it */
    async function load() {
      const token = ++S.token, dec = S.decOpen, decToken = dec ? ++S.decToken : 0;
      const [o, d] = await Promise.allSettled([api(query("open")), dec ? api(query("decided")) : null]);
      if (token !== S.token) return false;
      S.list = o.status === "fulfilled" ? o.value : null;
      S.error = o.status === "fulfilled" ? "" : o.reason.message;
      if (dec && decToken === S.decToken) { S.decided = d.status === "fulfilled" ? d.value : null; S.decError = d.status === "fulfilled" ? "" : d.reason.message; }
      relocate();
      return true;
    }
    const state = () => JSON.stringify([S.list, S.error, S.decided, S.decError, [...S.here]]);

    /* ——— painting ——— */
    function paint() {
      if (!isOpen()) return;
      const all = S.list || [], here = scope() === "piece", file = pieceFile(), sources = tools.W?.sources || [];
      says(all.length ? `${bookCount(all.length)} waiting in ${many(new Set(all.map(s => s.file)).size, "piece")}` : "");
      const shown = all.filter(inScope);
      S.groups = groupsOf(shown);
      let list;
      if (!S.list) list = S.error ? empty(esc(plain(S.error)) + "." + (/can't be read/.test(S.error) ? " Its file is unchanged." : "")) : empty("Reading the suggestions…");
      else if (!all.length) list = empty("No suggestions waiting. When you ask Claude for edits, notes, index terms or citations, they wait here until you accept or reject them.");
      else if (here && !file) list = empty("Open a piece to see its suggestions.");
      else if (!shown.length) list = empty("No suggestions waiting in this piece.");
      else list = S.groups.map((g, i) => groupHtml(g, i, sources, !here)).join("");
      const keep = focusOf(), top = body.scrollTop;
      body.innerHTML = `<div class="bs">
        <div class="bs-scope" role="group" aria-label="Suggestions in">${[["book", "Whole book"], ["piece", "This piece"]].map(([v, l]) =>
          `<button type="button" data-scope="${v}" aria-pressed="${scope() === v}">${l}</button>`).join("")}</div>
        <div class="bs-list">${list}</div>
        ${S.list ? decidedHtml(sources, !here) : ""}</div>`;
      body.firstElementChild.style.setProperty("--bs-font", tools.W?.hosts.page.style.getPropertyValue("--bk-font") || "var(--serif)");      // the book's text font
      body.querySelector(".bs-dec")?.addEventListener("toggle", toggled);       // toggle doesn't bubble
      body.scrollTop = top;
      refocus(keep);
      if (S.first && body.contains(document.activeElement)) first();
      if (S.list || S.error) S.first = false;          // read: once, and not later if the author has gone on to the text
      preview();
    }
    /* the texts show what the list shows (not while a decision runs: it paints everything after) */
    const preview = () => { if (!S.busy) paintTexts(); };
    /* opened from the palette: the first suggestion takes the focus; the switch has it until the list is read */
    const first = () => (body.querySelector(".bs-row .bs-go") || body.querySelector("[data-scope]"))?.focus();
    /* one group per call that made them (one each without), the newest first; the server's book order within. Groups made
       in the same second keep one order (by their id) however many of their suggestions are decided */
    function groupsOf(list) {
      const out = [], at = new Map();
      for (const s of list) {
        const key = s.group ? "g:" + s.group : "s:" + s.id;
        let g = at.get(key);
        if (!g) { at.set(key, g = {key, label: s.label || "", made: s.made || "", items: []}); out.push(g); }
        g.items.push(s);
        if ((s.made || "") > g.made) g.made = s.made;
      }
      const desc = (x, y) => x < y ? 1 : x > y ? -1 : 0;
      return out.sort((a, b) => desc(a.made, b.made) || desc(a.key, b.key));
    }
    function groupHtml(g, i, sources, showPiece) {
      const acts = g.items.length < 2 ? "" : `<div class="bs-g-a"><button type="button" class="btn small quiet" data-sg="reject-all">Reject all</button>
        <button type="button" class="btn small" data-sg="accept-all"${g.items.some(can) ? "" : " disabled"}>Accept all</button></div>`;
      return `<section class="bs-g" data-g="${i}"><div class="bs-g-h"><h3 class="bs-g-t">${esc(g.label || `Suggested ${when(g.made)}`.trim())}</h3>${acts}</div>
        <ol class="br-list">${g.items.map(s => rowOf(s, sources, showPiece)).join("")}</ol></section>`;
    }
    function rowOf(s, sources, showPiece) {
      const ok = can(s), say = s.missing ? "This piece is no longer in the book." : ok ? "" : "The words this was about have changed.";
      return `<li class="bs-row${ok ? "" : " gone"}" data-id="${esc(s.id)}">
        <button type="button" class="br-li bs-go" data-sg="go">${rowHtml(s, {sources, showPiece})}${say ? `<span class="bs-say">${say}</span>` : ""}</button>
        <div class="bs-acts"><button type="button" class="btn small quiet" data-sg="reject" title="Reject · R">Reject</button>${ok
          ? `<button type="button" class="btn small solid" data-sg="accept" title="Accept · A">Accept</button>` : ""}</div></li>`;
    }
    /* Decided, folded: the newest 50, each rejected or withdrawn one with Bring back (the undo of a rejection) */
    function decidedHtml(sources, showPiece) {
      let inner = "";
      if (S.decOpen) {
        const list = (S.decided || []).filter(inScope).slice(0, DECIDED_SHOWN);
        inner = S.decError ? empty(esc(plain(S.decError)) + ".") : !S.decided ? empty("Reading…")
          : !list.length ? empty(scope() === "piece" ? "Nothing decided in this piece yet." : "Nothing decided yet.")
          : `<ol class="br-list bs-dl">${list.map(s => `<li class="bs-d" data-id="${esc(s.id)}"><div class="bs-d-x">${rowHtml(s, {sources, showPiece})}</div>
              <div class="bs-acts"><span class="bs-d-s">${esc(`${SAID[s.status] || s.status} ${when(s.decided)}`)}</span>${s.status === "rejected" || s.status === "withdrawn"
                ? `<button type="button" class="btn small quiet" data-sg="reopen">Bring back</button>` : ""}</div></li>`).join("")}</ol>`;
      }
      return `<details class="bs-dec"${S.decOpen ? " open" : ""}><summary>Decided</summary>${inner}</details>`;
    }
    function toggled(e) {
      if (e.target.open === S.decOpen) return;          // painted so
      S.decOpen = e.target.open;
      if (!S.decOpen) return;
      S.decided = null; S.decError = "";
      paint();
      const token = ++S.decToken, mine = () => token === S.decToken;         // a newer read (or the panel closed) overtakes it
      api(query("decided")).then(list => { if (mine()) S.decided = list; }, err => { if (mine()) S.decError = err.message; })
        .then(() => { if (mine() && isOpen() && S.decOpen && !S.busy) paint(); });
    }
    /* the focus survives a repaint: the same button, or the row that took the place of one just decided */
    function focusOf() {
      const a = document.activeElement;
      if (!a || !body.contains(a)) return null;
      const row = a.closest("[data-id]");
      return {id: row?.dataset.id, sg: a.dataset.sg, scope: a.dataset.scope, summary: a.matches("summary"), g: a.closest(".bs-g")?.dataset.g,
        index: row ? [...body.querySelectorAll(".bs-row")].indexOf(row) : -1};
    }
    function refocus(k) {
      if (!k) return;
      const rows = [...body.querySelectorAll(".bs-row")];
      let el = null;
      if (k.scope) el = body.querySelector(`[data-scope="${k.scope}"]`);
      else if (k.summary) el = body.querySelector(".bs-dec summary");
      else if (k.id) {
        const row = body.querySelector(`[data-id="${CSS.escape(k.id)}"]`);
        el = row && (row.querySelector(`[data-sg="${k.sg}"]`) || row.querySelector("[data-sg]"));
        if (!el && k.index >= 0) el = rows[Math.min(k.index, rows.length - 1)]?.querySelector(".bs-go");
      } else if (k.g != null) el = body.querySelector(`.bs-g[data-g="${k.g}"] [data-sg="${k.sg}"]`);
      (el || rows[0]?.querySelector(".bs-go") || body.querySelector("[data-scope]"))?.focus();
    }

    /* ——— deciding: one at a time, in the book of the click; after it the list and the book (its count, for the status bar
       and the icon) are read again, unless the window has left that book meanwhile ——— */
    async function decide(b, run) {
      S.busy = true;
      body.querySelector(".bs-list")?.setAttribute("aria-busy", "true");
      try { await run(); }
      catch (e) { toast(plain(e.message), true); }
      finally {
        try { if (tools.W?.book.id === b) { await BookEditor.reloadBook(); await load(); } }
        catch { /* the window was left meanwhile: nothing here to read again */ }
        S.busy = false;
        paint();
      }
    }
    async function accept(ids) {
      const items = ids.map(waiting).filter(s => s && can(s));
      if (!items.length || S.busy) return;
      const b = book().id, files = new Set(items.map(s => s.file));
      if (items.length > 1 && !(await ask(`Accept ${bookCount(items.length)} suggestions in ${many(files.size, "piece")}?`,
        files.size === 1 ? "The piece keeps its text before in History." : "Each piece keeps its text before in History.", "Cancel", "Accept all"))) return;
      if (S.busy) return;
      const pieces = openPieces(files);
      await decide(b, async () => {
        const r = await guarded(pieces, () => api(DECIDE, {b, ids: items.map(s => s.id), decision: "accept"}), {by: "suggestion", keep: false});
        const done = r.accepted || [], changed = (r.changed || []).length;
        const where = new Set(done.map(id => items.find(s => s.id === id)?.file));
        const said = !done.length ? ""
          : done.length === 1 ? (pieces.some(p => where.has(p.file) && !p.closed) ? "Accepted. Ctrl+Z in the text takes it back" : "Accepted. The text before is in the piece's History")
          : `Accepted ${bookCount(done.length)} in ${many(where.size, "piece")}. The text before is in ${where.size === 1 ? "the piece's" : "each piece's"} History`;
        if (changed) toast(`${done.length ? `Accepted ${bookCount(done.length)}; ` : ""}${bookCount(changed)} couldn't be applied: ${changed === 1 ? "its words have" : "their words have"} changed`, true);
        else if (said) toast(said);
        else if ((r.unknown || []).length) toast(noLonger(r.unknown.length));
      });
    }
    async function reject(ids) {
      const items = ids.map(waiting).filter(Boolean);
      if (!items.length || S.busy) return;
      const b = book().id;
      if (items.length > 1 && !(await ask(`Reject ${bookCount(items.length)} suggestions?`, "You can bring them back from Decided, at the end of the list.", "Cancel", "Reject all"))) return;
      if (S.busy) return;
      await decide(b, async () => {
        const r = await api(DECIDE, {b, ids: items.map(s => s.id), decision: "reject"}), n = (r.rejected || []).length;
        if (n) toast(n === 1 ? "Rejected. Bring it back from Decided" : `Rejected ${bookCount(n)}. Bring them back from Decided`);
        else if ((r.unknown || []).length) toast(noLonger(r.unknown.length));
      });
    }
    async function reopen(ids) {
      if (S.busy) return;
      const b = book().id;
      await decide(b, async () => {
        const r = await api(DECIDE, {b, ids, decision: "reopen"});
        if (!(r.reopened || []).length) toast("That suggestion is no longer rejected: the list is up to date now.");
      });
    }

    /* ——— going to one: its piece opened (where it is open, or in the first pane), the words selected and in view. A click
       gives the text the focus, as Find does; Enter keeps it on the row, so A and R go on working ——— */
    async function go(s, {focus = false} = {}) {
      if (!s || s.missing) return;
      let p = tools.panes().map(x => x.piece).find(x => x?.file === s.file && x.text && !x.closed);
      if (!p) {
        await BookEditor.openPiece(s.file);
        p = tools.W?.piece;
        if (!p || p.file !== s.file || !p.text) return;
        if (!focus) body.querySelector(`.bs-row[data-id="${CSS.escape(s.id)}"] .bs-go`)?.focus();     // opening gave the text the focus
      }
      const T = p.text, m = locate(Tools.containersOf(T.view.state.doc, T.ctx.language), s);
      if (!m) { if (focus) T.focus(); return; }
      const from = m.box.at[m.from], to = m.box.at[m.to];
      if (m.box.kind === "note") {
        const nv = T.noteAt(m.box.pos), off = m.box.pos + 1;
        tools.scrollTo(T, m.box.pos, 0.35);
        if (!nv) return;
        nv.open(false);
        nv.inner.dispatch(nv.inner.state.tr.setSelection(TextSelection.create(nv.inner.state.doc, from - off, to - off)));
        if (focus) nv.inner.focus();
      } else {
        const v = T.view;
        v.dispatch(v.state.tr.setSelection(TextSelection.create(v.state.doc, from, to)));
        tools.scrollTo(T, from, 0.35);
        if (focus) v.focus();
      }
    }

    /* ——— clicks, keys (on a row only, never in the text) and the right-click menu ——— */
    body.addEventListener("click", e => {
      if (!isOpen()) return;
      const sc = e.target.closest("[data-scope]");
      if (sc) { pref.set(SCOPE, sc.dataset.scope); paint(); return; }
      const b = e.target.closest("[data-sg]");
      if (!b || b.disabled) return;
      const act = b.dataset.sg, id = b.closest("[data-id]")?.dataset.id, g = S.groups[+b.closest(".bs-g")?.dataset.g];
      if (act === "go") go(waiting(id), {focus: e.detail > 0});        // detail 0: Enter or Space
      else if (act === "accept") accept([id]);
      else if (act === "reject") reject([id]);
      else if (act === "reopen") reopen([id]);
      else if (act === "accept-all" && g) accept(g.items.filter(can).map(s => s.id));
      else if (act === "reject-all" && g) reject(g.items.map(s => s.id));
    });
    body.addEventListener("keydown", e => {
      if (!isOpen() || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
      const k = e.key.toLowerCase(), row = e.target.closest(".bs-row"), s = row && waiting(row.dataset.id);
      if ((k !== "a" && k !== "r") || !s) return;
      e.preventDefault();
      if (k === "r") reject([s.id]);
      else if (can(s)) accept([s.id]);
    });
    body.addEventListener("contextmenu", e => {
      const row = e.target.closest(".bs-row"), s = row && waiting(row.dataset.id);
      if (!s || !isOpen()) return;
      StudioMenu.open(e, [
        {label: "Go to", kbd: "Enter", disabled: !!s.missing, act: () => go(s, {focus: true})},
        {label: "Accept", kbd: "A", disabled: !can(s), act: () => accept([s.id])},
        {label: "Reject", kbd: "R", act: () => reject([s.id])},
      ]);
    });
    /* the row with the focus is the one the text previews */
    const moved = () => { clearTimeout(S.ptimer); S.ptimer = setTimeout(preview, 0); };
    body.addEventListener("focusin", moved);
    body.addEventListener("focusout", moved);
    /* Show in Suggestions (right-click on its words): its row, with the focus */
    const show = id => body.querySelector(`.bs-row[data-id="${CSS.escape(id)}"] .bs-go`)?.focus();
    /* the suggestion of the row with the focus (the in-text preview shows it), or null */
    function current() {
      const row = document.activeElement?.closest?.(".bs-row");
      return row && body.contains(row) ? waiting(row.dataset.id) : null;
    }

    /* the preview's side of the panel: what it lists, the row with the focus, and the panel's own decisions */
    live = {tools, on: () => isOpen() && !!S.list, row: current, waiting, can,
      list: () => (S.list || []).filter(s => inScope(s) && !s.missing),
      accept: id => accept([id]), reject: id => reject([id]), show};

    return {
      /* the panel opens, or the pane last written in shows another piece: read the first time, painted every time */
      render() {
        relocate();
        paint();
        if (!S.loaded) { S.loaded = true; load().then(ok => { if (ok) paint(); }); }
      },
      /* the book was read again: so is the list, painted when anything in it changed (and nothing is being decided: the
         decision reads it again after) */
      refresh() {
        if (S.busy || !S.loaded) return;
        const before = state();
        load().then(ok => { if (ok && !S.busy && state() !== before) paint(); });
      },
      /* a text changed: whether its suggestions' words are still there (the preview follows); its cursor moved: the
         suggestion under it */
      changed(T, doc) {
        if (!S.list?.length) return;
        if (!doc) { clearTimeout(S.ptimer); S.ptimer = setTimeout(preview, 60); return; }
        clearTimeout(S.timer);
        S.timer = setTimeout(() => {
          if (!isOpen() || S.busy) return;                // a decision reads everything again after it
          const before = state();
          relocate();
          if (state() !== before) paint();
          else preview();
        }, 300);
      },
      /* every mark leaves the texts: nothing shows while writing */
      closed() {
        clearTimeout(S.timer); clearTimeout(S.ptimer);
        Object.assign(S, {list: null, error: "", decided: null, decError: "", decOpen: false, loaded: false, token: S.token + 1,
          decToken: S.decToken + 1, first: false, groups: []});
        S.here.clear();
        paintTexts();
      },
      /* opened from the palette: the first suggestion takes the focus */
      focus() { S.first = !S.list && !S.error; first(); },
      current,
      /* the open suggestions the panel shows (the scope's), each with whether its words are there now */
      list: () => (S.list || []).filter(inScope).map(s => ({...s, here: can(s)})),
    };
  }

  /* ——— the preview in the text, while the panel is open (book-tools.js gives every text this plugin) ———
     The words of every suggestion the panel lists, in the text's own piece, get a dotted underline; the current one (the
     row with the focus, or else the one under the cursor of the text last written in) shows its change in place
     (previewOf). Worked out again by the panel (paintTexts) when the list, the row with the focus, the scope or a text
     changes, and mapped through the text's changes meanwhile; emptied when the panel closes, and not drawn (nor its
     menu offered) in focus mode, which hides the rail. The words are found on the live document, as Find finds its
     matches: only those in the text itself are marked, not a note's or a caption. */
  const KEY = new PluginKey("bs-preview");
  let live = null;                    // the mounted panel's side of the preview
  const drawn = new WeakMap();        // text → {set, sig}: the set last given to it, and what it shows
  const seen = new WeakMap();         // text → {doc, key, words}: its suggestions' words, found again when either changes

  function plugins(T) {
    return [new Plugin({key: KEY,
      state: {init: () => DecorationSet.empty, apply: (tr, set) => { const m = tr.getMeta(KEY); return m !== undefined ? m : tr.docChanged ? set.map(tr.mapping, tr.doc) : set; }},
      // focus mode: setFocus has every text read its decorations again (setProps)
      props: {decorations: state => Tools.state?.focus ? null : KEY.getState(state), handleDOMEvents: {contextmenu: (view, e) => menu(view, e)}},
      view: () => { setTimeout(() => paintText(T), 0); return {}; },          // a text opened while the panel is
    })];
  }
  /* the suggestions' words in the text: {s, from, to} */
  function wordsOf(T, list) {
    const doc = T.view.state.doc, key = list.map(s => s.id).join(" "), had = seen.get(T);
    if (had && had.doc === doc && had.key === key) return had.words;
    const boxes = Tools.containersOf(doc, T.ctx.language), words = [];
    for (const s of list) {
      const m = locate(boxes, s);
      if (m && m.box.kind === "text") words.push({s, from: m.box.at[m.from], to: m.box.at[m.to]});
    }
    seen.set(T, {doc, key, words});
    return words;
  }
  function decosOf(T) {
    const L = live, file = L?.on() ? L.tools.paneOf(T)?.piece?.file : null;
    const words = file ? wordsOf(T, L.list().filter(s => s.file === file)) : [];
    if (!words.length) return {set: DecorationSet.empty, sig: ""};
    const row = L.row(), head = T.view.state.selection.head;
    const cur = row ? words.find(w => w.s.id === row.id) : L.tools.activePiece()?.text === T ? words.find(w => w.from <= head && head <= w.to) : null;
    const doc = T.view.state.doc, sources = L.tools.W?.sources || [], out = [], sig = [];
    for (const w of words) {
      const on = w === cur, p = previewOf(w.s, on, {sources});
      out.push(Decoration.inline(w.from, w.to, p.title ? {class: p.cls, title: p.title} : {class: p.cls}, {sid: w.s.id, on}));
      if (p.widget) {
        // the new words keep the marks of the words they replace; a note or a citation takes those on both sides (suggestions.apply)
        const $to = doc.resolve(w.to), before = $to.nodeBefore?.marks || [], after = $to.nodeAfter?.marks || [];
        const marks = w.s.kind === "edit" ? before : before.filter(m => m.isInSet(after)), x = p.widget;
        out.push(Decoration.widget(w.to, () => widget(x, w.s.id), {side: 1, marks, key: `bs:${w.s.id}:${JSON.stringify(x)}`}));
      }
      sig.push(`${w.s.id}@${w.from}-${w.to}${on ? "=" + JSON.stringify(p) : ""}`);
    }
    return {set: DecorationSet.create(doc, out), sig: sig.join(" ")};
  }
  function widget(x, id) {
    const e = document.createElement(x.tag);
    e.className = x.cls;
    e.textContent = x.text;
    if (x.title) e.title = x.title;
    e.dataset.sid = id;
    return e;
  }
  function paintText(T) {
    if (!T || T.destroyed || !T.view) return;
    const now = KEY.getState(T.view.state);
    if (now === undefined) return;                  // a text without the plugin
    const {set, sig} = decosOf(T), last = drawn.get(T);
    if (last ? last.set === now && last.sig === sig : now === DecorationSet.empty && !sig) return;
    T.view.dispatch(T.view.state.tr.setMeta(KEY, set));
    drawn.set(T, {set: KEY.getState(T.view.state), sig});
  }
  const paintTexts = () => (live?.tools.texts() || []).forEach(paintText);

  /* right-click on a suggestion's words (or on its preview): accept or reject it, or show it in the panel. True: the
     style sheet's menu doesn't open as well */
  function menu(view, e) {
    if (Tools.state?.focus) return false;            // nothing is drawn there
    const L = live, hit = e.target.closest?.(".bs-u, .bs-ins, .bs-ghost");
    if (!hit || !L?.on() || typeof StudioMenu === "undefined") return false;
    let id = hit.dataset.sid;
    if (!id) {                // words: the one the cursor previews there, else the shortest (suggestions may share words)
      const at = view.posAtCoords({left: e.clientX, top: e.clientY});
      const here = at ? KEY.getState(view.state).find(at.pos, at.pos, spec => !!spec.sid).filter(d => d.from <= at.pos && at.pos <= d.to) : [];
      id = (here.find(d => d.spec.on) || here.sort((a, b) => (a.to - a.from) - (b.to - b.from))[0])?.spec.sid;
    }
    const s = id && L.waiting(id);
    if (!s) return false;
    // the cursor stays in the text (accepting locks it while the piece changes, which takes its focus: it comes back after)
    const back = () => { if (!view.isDestroyed && (!document.activeElement || document.activeElement === document.body)) view.focus(); };
    StudioMenu.open(e, [
      {label: "Accept suggestion", disabled: !L.can(s), act: () => { back(); L.accept(s.id).then(back); }},
      {label: "Reject suggestion", act: () => { back(); L.reject(s.id); }},
      "-",
      {label: "Show in Suggestions", act: () => L.show(s.id)},
    ]);
    return true;
  }

  root.BookSuggest = {...helpers, panel, plugins, paint: paintTexts};
})(typeof window !== "undefined" ? window : globalThis);
