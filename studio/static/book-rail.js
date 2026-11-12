"use strict";
/* The writing window's rail (book-editor.js, book-tools.js): a column of icons on the right and one panel at a time,
   closed until asked for. Outline (headings, scene breaks and notes of the piece), Sources (sources.json: find, add,
   edit, cite), History (the piece's snapshots: compare with the text now, restore), Comments, and Find and replace
   across the book. A panel about a piece follows the pane last written in.
   Find and replace and Restore change files on disk: the open pieces are saved first, made read-only while it runs,
   and read again after (as one change that undo can take back), so no typing is ever replaced under the cursor.
   A classic script after book-tools.js; sets window.BookRail = {mount(W, tools)}. */
(function (root) {
  const BT = root.BookText, BX = root.BookTools, {TextSelection} = root.PM, N = root.BookSchema.nodes;
  const ICONS = {
    outline: `<path d="M3 4.5h12M6 9h9M6 13.5h9"/>`,
    sources: `<path d="M9 5.2C7.6 4.2 5.6 3.8 3 3.8v10c2.6 0 4.6.4 6 1.4 1.4-1 3.4-1.4 6-1.4v-10c-2.6 0-4.6.4-6 1.4zM9 5.2v10"/>`,
    history: `<circle cx="9" cy="9" r="6.25"/><path d="M9 5.5V9l2.5 1.6"/>`,
    comments: `<path d="M3.25 3.75h11.5v8.5h-6.5l-3.5 2.75v-2.75h-1.5z"/>`,
    find: `<circle cx="7.75" cy="7.75" r="4.5"/><path d="M11 11l4 4"/>`,
  };
  const PANELS = [["outline", "Outline"], ["sources", "Sources"], ["history", "History"], ["comments", "Comments"], ["find", "Find and replace"]];
  const TYPES = [["book", "Book"], ["article-journal", "Article"], ["chapter", "Chapter"], ["webpage", "Web page"], ["report", "Report"]];
  const CONTAINER = {"article-journal": "Journal", chapter: "Book", webpage: "Website"};
  const svg = id => `<svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">${ICONS[id]}</svg>`;
  const yearOf = s => BX.dateText(s.issued);
  /* a snapshot's name (2026-11-12T1835, a second in that minute -2) as the date and time */
  function snapWhen(name) {
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2})(\d{2})(?:-(\d+))?$/.exec(name);
    if (!m) return name;
    return when(new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]).toISOString()) + (m[6] ? ` (${m[6]})` : "");
  }

  function mount(W, tools) {
    const host = W.root.querySelector(".bw-rail");
    host.hidden = false;
    host.innerHTML = `<section class="br-panel" hidden><header class="br-head"><div class="br-k"><h2 class="kicker"></h2>
        <button type="button" class="bw-tog br-x" title="Close the panel">Close</button></div><p class="br-t"></p><p class="br-sub"></p></header>
      <div class="br-body"></div></section>
      <nav class="br-icons" aria-label="Rail">${PANELS.map(([id, name]) => `<button type="button" class="br-i" data-panel="${id}" aria-pressed="false"
        title="${esc(name)}${id === "find" ? " · Ctrl+F" : ""}" aria-label="${esc(name)}">${svg(id)}</button>`).join("")}</nav>`;
    const panel = host.querySelector(".br-panel"), body = host.querySelector(".br-body"), kicker = host.querySelector(".br-head .kicker"), title = host.querySelector(".br-t");
    const sub = host.querySelector(".br-sub"), says = t => { sub.textContent = t; };
    const count = (n, one, many = one + "s") => `${bookCount(n)} ${n === 1 ? one : many}`;
    const S = {open: null, timer: 0, selTimer: 0, find: {q: "", repl: "", whole: false, case: false, results: [], cur: -1, busy: false, msg: ""},
      history: null, sources: null, form: null, filter: ""};
    const book = () => tools.W.book;
    const piece = () => tools.activePiece();
    const text = () => { const p = piece(); return p && p.text && !p.text.destroyed ? p.text : null; };
    const available = () => PANELS.filter(([id]) => id !== "sources" || book().features?.sources === true);

    function paintIcons() {
      const ok = new Set(available().map(([id]) => id));
      host.querySelectorAll(".br-i").forEach(b => { b.hidden = !ok.has(b.dataset.panel); b.setAttribute("aria-pressed", String(b.dataset.panel === S.open)); });
    }
    function open(id, opts = {}) {
      if (!available().some(([x]) => x === id)) return;
      tools.leaveFocus();
      if (S.open !== id) {
        if (!S.open) {                      // the panel takes room: refused (and said) when the texts wouldn't keep 360 px
          panel.hidden = false;
          if (!tools.railOpen(true)) { panel.hidden = true; tools.railOpen(false); return; }      // refused: the room it took is given back
        }
        if (S.open === "find") tools.setFind(null);
        S.open = id;
        panel.hidden = false;
        panel.setAttribute("aria-label", PANELS.find(p => p[0] === id)[1]);
        render();
        if (id === "find" && S.find.q) search();
      }
      paintIcons();
      if (id === "find") {
        if (opts.query) { S.find.q = opts.query; render(); search(); }
        const f = body.querySelector(opts.focus === "repl" ? "[data-f=repl]" : "[data-f=q]");
        f?.focus(); f?.select();               // Find is for typing in: the cursor goes to its field however it opened
      } else if (id === "sources" && opts.add) newSource();
      else if (opts.focus) body.querySelector("input, button")?.focus();
    }
    function close() {
      if (S.open === "find") tools.setFind(null);
      const inside = host.contains(document.activeElement);
      S.open = null;
      panel.hidden = true;
      tools.railOpen(false);
      paintIcons();
      if (inside) text()?.focus();
    }
    host.querySelector(".br-icons").addEventListener("click", e => {
      const b = e.target.closest("[data-panel]");
      if (b) { if (S.open === b.dataset.panel) close(); else open(b.dataset.panel); }
    });
    host.querySelector(".br-x").addEventListener("click", close);
    /* arrows move through a panel's list */
    body.addEventListener("keydown", e => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      const item = e.target.closest(".br-li");
      if (!item) return;
      const all = [...body.querySelectorAll(".br-li")], i = all.indexOf(item);
      const next = all[i + (e.key === "ArrowDown" ? 1 : -1)];
      if (next) { e.preventDefault(); next.focus(); }
    });

    /* the head is the binder's: kicker, title, a quiet line (said by each panel) */
    function head(k, t) { kicker.textContent = k; title.textContent = t; }
    function render() {
      if (!S.open) return;
      const name = PANELS.find(p => p[0] === S.open)[1], p = piece();
      if (S.open === "sources" || S.open === "find") head(name, book().title);
      else head(name, p ? p.name : "");
      says(S.open === "find" ? "Every piece, with its notes and captions" : "");
      ({outline: renderOutline, sources: renderSources, history: renderHistory, comments: renderComments, find: renderFind})[S.open]();
    }
    const empty = msg => `<p class="br-empty">${msg}</p>`;

    /* ——— Outline ——— */
    function renderOutline() {
      const T = text();
      if (!T) { body.innerHTML = empty("Open a piece to see its outline."); return; }
      const items = BX.outline(T.view.state.doc).filter(o => o.kind !== "title"), start = T.ctx.noteStart();
      const k = kind => items.filter(o => o.kind === kind).length;
      says([count(k("heading"), "heading"), count(k("scene"), "scene break"), count(k("note"), "note")].join(" · "));
      let n = start;
      body.innerHTML = items.length ? `<ol class="br-list br-ol">${items.map(o => {
        if (o.kind === "note") n++;
        const inner = o.kind === "heading" ? `<span class="br-o-h">${esc(o.text || "Heading")}</span>`
          : o.kind === "scene" ? `<span class="br-o-s">* * *</span>`
          : `<span class="br-o-n">${n}</span><span class="br-o-x">${o.text ? esc(o.text) : `<i>An empty note</i>`}</span>`;
        return `<li><button type="button" class="br-li br-o ${o.kind}${o.level === 3 ? " l3" : ""}" data-pos="${o.pos}" data-kind="${o.kind}">${inner}</button></li>`;
      }).join("")}</ol>` : empty("No headings, scene breaks or notes in this piece yet.");
      markOutline();
    }
    /* the item the cursor is in: the last one before it */
    function markOutline() {
      const T = text();
      if (S.open !== "outline" || !T) return;
      const h = T.view.state.selection.head, items = [...body.querySelectorAll(".br-o")];
      let cur = null;
      for (const b of items) if (+b.dataset.pos <= h && b.dataset.kind !== "note") cur = b;
      items.forEach(b => { if (b === cur) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current"); });
    }
    function goOutline(b) {
      const T = text();
      if (!T) return;
      const pos = +b.dataset.pos, v = T.view, node = v.state.doc.nodeAt(pos);
      if (!node) return;
      if (b.dataset.kind === "note") { tools.scrollTo(T, pos); T.noteAt(pos)?.open(false); return; }
      const at = b.dataset.kind === "scene" ? Math.min(pos + node.nodeSize + 1, v.state.doc.content.size) : pos + 1;
      try { v.dispatch(v.state.tr.setSelection(TextSelection.near(v.state.doc.resolve(at)))); } catch { /* a place the text no longer has */ }
      tools.scrollTo(T, pos);
      v.focus();
    }

    /* ——— Comments ——— */
    function renderComments() {
      const T = text();
      if (!T) { body.innerHTML = empty("Open a piece to see its comments."); return; }
      const doc = T.view.state.doc, list = BT.commentRanges(doc);
      says(count(list.length, "comment"));
      body.innerHTML = list.length ? `<ol class="br-list br-cl">${list.map((r, i) => `<li class="br-c">
          <button type="button" class="br-li br-c-go" data-i="${i}"><span class="br-c-q">${esc(BX.short(doc.textBetween(r.from, r.to, " ", " "), 90))}</span>
            <span class="br-c-n">${r.mark.attrs.note ? esc(r.mark.attrs.note) : `<i>No comment written yet</i>`}</span></button>
          <button type="button" class="bm-btn br-c-r" data-resolve="${i}">Resolve</button></li>`).join("")}</ol>`
        : empty("No comments in this piece. Select some text and choose Comment, or press Ctrl+Alt+M.");
    }
    function goComment(i) {
      const T = text(), r = T && BT.commentRanges(T.view.state.doc)[i];
      if (!r) return;
      tools.scrollTo(T, r.from);
      setTimeout(() => { T.margin.layout(); T.margin.comments[i]?.ta.focus(); }, 0);
    }
    function resolveComment(i) { const T = text(); if (T) { T.resolveComment(i); render(); } }

    /* ——— History ——— */
    async function renderHistory(keep) {
      const p = piece(), T = text();
      if (!p || !T) { body.innerHTML = empty("Open a piece to see its history."); return; }
      const mine = S.history && S.history.file === p.file ? S.history : (S.history = {file: p.file, list: null, open: null, diff: null});
      if (!keep || !mine.list) {
        body.innerHTML = `<p class="br-empty">Reading the history…</p>`;
        try { mine.list = await api(`/api/book/history?b=${encodeURIComponent(book().id)}&f=${encodeURIComponent(p.file)}`); }
        catch (e) { if (S.open === "history") body.innerHTML = empty(esc(e.message)); return; }
        if (S.open !== "history" || S.history !== mine) return;
      }
      const now = T.words();
      says(count(mine.list.length, "earlier version"));
      body.innerHTML = `<ol class="br-list br-hl"><li class="br-h now"><span class="br-h-w">Now</span><span class="br-h-n">${esc(bookWords(now))}</span></li>
        ${mine.list.map(h => {
          const isOpen = mine.open === h.when, delta = now - h.words;
          return `<li class="br-h${isOpen ? " open" : ""}"><button type="button" class="br-li br-h-go" data-when="${esc(h.when)}" aria-expanded="${isOpen}">
              <span class="br-h-w">${esc(snapWhen(h.when))}</span><span class="br-h-n">${esc(bookWords(h.words))}${delta ? ` <span class="br-h-d">${delta > 0 ? "+" : "−"}${esc(bookCount(Math.abs(delta)))} since</span>` : ""}</span></button>
            ${isOpen ? `<div class="br-diff">${mine.diff == null ? `<p class="br-empty">Comparing…</p>` : mine.diff}
              <div class="br-acts"><button type="button" class="btn small" data-restore="${esc(h.when)}">Restore</button></div></div>` : ""}</li>`;
        }).join("")}</ol>
        ${mine.list.length ? "" : empty("No earlier versions yet.")}
        <p class="br-note">A version is kept when you leave a piece you changed, every 30 minutes of writing, and before a restore or a replace.</p>`;
    }
    async function compare(name) {
      const h = S.history, p = piece(), T = text();
      if (!h || !p || !T) return;
      if (h.open === name) { h.open = null; renderHistory(true); return; }
      h.open = name; h.diff = null; h.snap = null;
      renderHistory(true);
      try {
        const snap = await api(`/api/book/snapshot?b=${encodeURIComponent(book().id)}&f=${encodeURIComponent(p.file)}&when=${encodeURIComponent(name)}`);
        if (S.history !== h || h.open !== name) return;
        h.snap = snap.doc;
        h.diff = diffView(BX.plainBlocks(snap.doc), BX.plainBlocks(T.view.state.doc.toJSON()));
      } catch (e) { h.diff = empty(esc(e.message)); }
      if (S.open === "history") renderHistory(true);
    }
    /* the version against the text now: struck through is only in the version, underlined only in the text now; runs of
       the same paragraphs fold away */
    function diffView(then, now) {
      const ops = BX.diffBlocks(then, now);
      if (ops.every(o => o.t === "=")) return `<p class="br-empty">The same as the text now.</p>`;
      const out = [];
      for (let k = 0; k < ops.length;) {
        if (ops[k].t === "=") {
          let n = 0;
          while (k < ops.length && ops[k].t === "=") { n++; k++; }
          out.push(`<p class="br-same">${n === 1 ? "1 paragraph" : `${n} paragraphs`} the same</p>`);
          continue;
        }
        const o = ops[k++];
        const html = o.t === "~" ? (o.from.length * o.to.length < 4e6 ? diffHtml(o.from, o.to) : `<del>${esc(o.from)}</del> <ins>${esc(o.to)}</ins>`)
          : o.t === "-" ? `<del>${esc(o.text)}</del>` : `<ins>${esc(o.text)}</ins>`;
        out.push(`<p>${html}</p>`);
      }
      return `<p class="br-legend">Struck through: only in this version. Underlined: written since.</p><div class="draftview br-dv">${out.join("")}</div>`;
    }
    /* the open comparison against the text as it is now */
    function recompare() {
      const h = S.history, T = text();
      if (h && h.snap && T && h.file === piece()?.file) h.diff = diffView(BX.plainBlocks(h.snap), BX.plainBlocks(T.view.state.doc.toJSON()));
      renderHistory(true);
    }
    async function restore(name) {
      const p = piece();
      if (!p?.text) return;
      try {
        await guarded([p], () => api("/api/book/restore", {b: book().id, f: p.file, when: name}), "restore");
        toast(`Restored the version of ${snapWhen(name)}. The text it replaced is in History`);
      } catch (e) { toast(plain(e.message), true); }
      if (S.history) { S.history.open = null; S.history.list = null; }
      if (S.open === "history") renderHistory();
    }

    /* ——— Sources ——— */
    async function loadSources() {
      try { S.sources = await api("/api/book/sources?b=" + encodeURIComponent(book().id)); }
      catch (e) { S.sources = null; S.sourcesError = e.message; }
    }
    async function renderSources(reload = true) {
      if (S.form) return renderForm();
      if (reload || !S.sources) {
        if (!S.sources) body.innerHTML = `<p class="br-empty">Reading the sources…</p>`;
        await loadSources();
        if (S.open !== "sources" || S.form) return;
      }
      if (!S.sources) { body.innerHTML = empty(`sources.json can't be read: ${esc(plain(S.sourcesError))}. Its file is unchanged.`); return; }
      says(count(S.sources.length, "source"));
      const had = document.activeElement?.classList.contains("br-sq");
      body.innerHTML = `<div class="br-tools"><input class="input br-sq" type="search" placeholder="Find a source" aria-label="Find a source" value="${esc(S.filter)}" spellcheck="false">
          <button type="button" class="btn small" data-add>Add source</button></div>
        <ol class="br-list br-sl"></ol>`;
      paintSourceList();
      if (had) { const q = body.querySelector(".br-sq"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
    }
    function paintSourceList() {
      const list = body.querySelector(".br-sl");
      if (!list) return;
      const q = BX.fold(S.filter.trim());
      const shown = (S.sources || []).filter(s => !q || BX.fold([s.id, s.title, BX.formatAuthors(s.author), yearOf(s), s["container-title"]].join(" ")).includes(q));
      list.innerHTML = shown.map(s => `<li class="br-s"><button type="button" class="br-li br-s-go" data-id="${esc(s.id)}">
          <span class="br-s-a">${esc(BT.sourceShort(s) || s.id)}</span><span class="br-s-t">${esc(s.title || "")}</span><span class="br-s-k">${esc(s.id)}</span></button>
          <button type="button" class="bm-btn br-s-c" data-cite="${esc(s.id)}" title="Insert a citation of this source at the cursor">Cite</button></li>`).join("")
        || `<li>${empty(S.sources.length ? "No source matches." : "No sources yet. Add the books, articles and pages the text draws on, and cite them with / Citation.")}</li>`;
    }
    /* Add source (the list, or the citation form): a form in progress is offered first, not dropped */
    async function newSource() {
      if (S.form && formDirty() && !(await ask("Start another source?", "The source you are writing hasn't been saved. Starting another one discards it.", "Keep writing", "Discard it"))) {
        renderForm(); body.querySelector("[data-f=title]")?.focus(); return;
      }
      editSource(null);
    }
    async function back() {
      if (S.form && formDirty() && !(await ask("Leave this source?", "It hasn't been saved. Going back to the list discards what you wrote.", "Keep writing", "Discard it"))) return;
      S.form = null;
      renderSources(false);
    }
    /* Studio's own dialog: the first answer (focused) keeps, the second goes on */
    function ask(title, text, keep, go) {
      return new Promise(resolve => {
        let yes = false;
        openDialog(`<form><h2>${esc(title)}</h2><p class="hint" style="margin-top:-12px">${esc(text)}</p>
          <div class="foot"><button type="button" class="btn quiet" data-close autofocus>${esc(keep)}</button><button type="submit" class="btn solid">${esc(go)}</button></div></form>`,
        async () => { yes = true; });
        onDialogClose(() => resolve(yes));
      });
    }
    const formValues = () => Object.fromEntries([...body.querySelectorAll(".br-form [data-f]")].map(e => [e.dataset.f, e.value]));
    const formDirty = () => { const F = S.form; if (body.querySelector(".br-form")) F.values = formValues(); return !!F.values && JSON.stringify(F.values) !== F.initial; };
    function editSource(id) {
      const s = id ? (S.sources || []).find(x => x.id === id) : null;
      if (id && !s) return;
      S.form = {orig: s, id: s ? s.id : "", keyTouched: !!s, values: null, initial: null};
      if (!S.sources) loadSources().then(() => { if (S.form) renderForm(); });
      renderForm();
      body.querySelector("[data-f=title]")?.focus();
    }
    function renderForm() {
      const F = S.form, s = F.orig || {type: "book"};
      const type = s.type || "book", known = TYPES.some(t => t[0] === type);
      const field = (name, label, value, attrs = "") => `<label class="br-f"><span class="label">${label}</span><input class="input" data-f="${name}" value="${esc(value)}" ${attrs}></label>`;
      body.innerHTML = `<form class="br-form" autocomplete="off">
        <button type="button" class="bm-btn br-back" data-back>← All sources</button>
        <label class="br-f"><span class="label">Type</span><select class="select" data-f="type">${TYPES.map(([v, l]) => `<option value="${v}" ${v === type ? "selected" : ""}>${l}</option>`).join("")}
          ${known ? "" : `<option value="${esc(type)}" selected>${esc(type)}</option>`}</select></label>
        ${field("title", "Title", s.title || "", `spellcheck="true" lang="${esc(book().language || "en")}"`)}
        <label class="br-f"><span class="label">Authors</span><input class="input" data-f="authors" value="${esc(BX.formatAuthors(s.author))}" placeholder="van Dijk, Anna; Jansen, M." spellcheck="false">
          <span class="hint">Family name, given names; a semicolon between people. An organisation without a comma.</span></label>
        <div class="br-f2">${field("year", "Year", yearOf(s), `maxlength="12"`)}${field("accessed", "Accessed", BX.dateText(s.accessed), `placeholder="2026-11-12" spellcheck="false" maxlength="40"`)}</div>
        ${field("publisher", "Publisher", s.publisher || "")}
        <div data-cbox ${CONTAINER[type] || s["container-title"] ? "" : "hidden"}>${field("container", `<span data-clabel>${esc(CONTAINER[type] || "In")}</span>`, s["container-title"] || "")}</div>
        ${field("url", "URL", s.URL || "", `type="url" spellcheck="false" placeholder="https://"`)}
        <label class="br-f"><span class="label">Key</span><input class="input" data-f="id" value="${esc(F.id)}" spellcheck="false" placeholder="vandijk2019">
          <span class="hint">${F.orig ? "The text cites this source as @" + esc(F.orig.id) + ". Citations keep their key when it changes here." : "The text cites the source by this key."}</span></label>
        <p class="hint bad br-err" role="alert" hidden></p>
        <div class="br-acts">${F.orig ? `<button type="button" class="btn small quiet" data-remove>Remove…</button>` : ""}<span class="grow"></span>
          ${F.orig ? `<button type="button" class="btn small" data-cite="${esc(F.orig.id)}">Cite</button>` : ""}<button type="submit" class="btn small solid">Save</button></div></form>`;
      const form = body.querySelector("form"), val = n => form.querySelector(`[data-f=${n}]`).value;
      // what was typed, when the form comes back (another panel was open meanwhile)
      if (F.values) for (const [k, v] of Object.entries(F.values)) { const e = form.querySelector(`[data-f="${k}"]`); if (e) e.value = v; }
      const suggest = () => {
        if (F.keyTouched) return;
        const taken = new Set((S.sources || []).map(x => x.id));
        F.id = BX.sourceKey({author: BX.parseAuthors(val("authors")), title: val("title"), issued: BX.dateParts(val("year"))}, taken);
        form.querySelector("[data-f=id]").value = F.id;
      };
      form.addEventListener("input", e => {
        const f = e.target.dataset.f;
        if (f === "id") F.keyTouched = true;
        else if (f === "authors" || f === "title" || f === "year") suggest();
      });
      const typed = () => {           // a journal, a book or a website for the types that have one
        form.querySelector("[data-clabel]").textContent = CONTAINER[val("type")] || "In";
        form.querySelector("[data-cbox]").hidden = !CONTAINER[val("type")] && !val("container").trim();
      };
      form.querySelector("[data-f=type]").addEventListener("change", typed);
      if (!F.orig && !F.values) suggest();
      typed();
      if (F.initial == null) F.initial = JSON.stringify(formValues());
      form.addEventListener("input", () => { F.values = formValues(); });
      form.addEventListener("submit", e => { e.preventDefault(); saveSource(form); });
    }
    async function saveSource(form) {
      const F = S.form, val = n => form.querySelector(`[data-f=${n}]`).value.trim(), err = form.querySelector(".br-err");
      const say = msg => { err.textContent = msg; err.hidden = false; };
      const id = val("id"), orig = F.orig;
      if (!BT.CITE_KEY.test(id)) return say(id ? `${id} can't be a key: use letters, digits, - and _, starting and ending with a letter or digit.` : "Give the source a key, like vandijk2019.");
      let list;
      try { list = await api("/api/book/sources?b=" + encodeURIComponent(book().id)); } catch (e) { return say(plain(e.message) + "."); }
      if (list.some(x => x.id === id && x.id !== orig?.id)) return say(`Another source has the key ${id} already.`);
      // what the form didn't change stays as it was (a raw date, a dropping particle, fields the form doesn't show)
      const made = BX.sourceItem(orig ? list.find(x => x.id === orig.id) || orig : null, formValues());
      if (made.error) return say(made.error);
      const item = made.item;
      const next = orig ? list.map(x => x.id === orig.id ? item : x) : [...list, item];
      if (orig && !list.some(x => x.id === orig.id)) next.push(item);
      try { S.sources = await api("/api/book/sources", {b: book().id, items: next}); }
      catch (e) { return say(plain(e.message) + "."); }
      const W = tools.W;
      W.sources = S.sources;
      tools.texts().forEach(T => T.refresh());
      S.form = null; S.filter = "";
      toast(orig ? `Saved ${BT.sourceShort(item) || id}` : `Added ${BT.sourceShort(item) || id}: cite it with Cite`);
      renderSources(false);
      body.querySelector(`[data-id="${CSS.escape(id)}"]`)?.focus();
    }
    async function removeSource(id) {
      const s = (S.sources || []).find(x => x.id === id);
      if (!s || !confirm(`Remove ${BT.sourceShort(s) || id} from the sources?\n\nCitations of it stay in the text and show their key, ${id}.`)) return;
      try {
        const list = await api("/api/book/sources?b=" + encodeURIComponent(book().id));
        S.sources = await api("/api/book/sources", {b: book().id, items: list.filter(x => x.id !== id)});
        tools.W.sources = S.sources;
        tools.texts().forEach(T => T.refresh());
        S.form = null;
        renderSources(false);
        toast(`Removed ${BT.sourceShort(s) || id}`);
      } catch (e) { toast(plain(e.message), true); }
    }
    /* a citation of the source where the cursor is (in the text, or in the note being written) */
    function cite(id) {
      const T = text();
      if (!T) { toast("Open a piece to cite in."); return; }
      if (T.locked) return;
      const v = tools.writingView(T), pos = v.state.selection.to, $p = v.state.doc.resolve(pos);
      if (!$p.parent.inlineContent || !$p.parent.canReplaceWith($p.index(), $p.index(), N.cite)) { toast("A citation goes in a line of text: put the cursor there first."); return; }
      const tr = v.state.tr.insert(pos, N.cite.create({items: [{key: id, prefix: "", locator: ""}]}));
      v.dispatch(tr.setSelection(TextSelection.create(tr.doc, pos + 1)).scrollIntoView());
      v.focus();
    }

    /* ——— Find and replace, across the book ——— */
    function renderFind() {
      const F = S.find;
      body.innerHTML = `<form class="br-find" autocomplete="off">
          <label class="br-f"><span class="label">Find</span><input class="input" data-f="q" value="${esc(F.q)}" spellcheck="false" aria-describedby="br-fs"></label>
          <label class="br-f"><span class="label">Replace with</span><input class="input" data-f="repl" value="${esc(F.repl)}" spellcheck="false"></label>
          <div class="br-opts"><label class="br-ck"><input type="checkbox" data-f="whole" ${F.whole ? "checked" : ""}><span>Whole words</span></label>
            <label class="br-ck"><input type="checkbox" data-f="case" ${F.case ? "checked" : ""}><span>Match case</span></label></div>
          <div class="br-acts"><span class="grow"></span>
            <button type="button" class="btn small" data-replace>Replace</button><button type="button" class="btn small solid" data-all>Replace all</button></div>
          <p class="br-fs" id="br-fs" role="status"></p></form>
        <div class="br-res"></div>`;
      const form = body.querySelector(".br-find");
      form.addEventListener("input", e => {
        const f = e.target.dataset.f;
        if (f === "q" || f === "repl") F[f] = e.target.value;
        else if (f === "whole" || f === "case") F[f] = e.target.checked;
        if (f !== "repl") { clearTimeout(S.timer); S.timer = setTimeout(search, 250); }
      });
      form.addEventListener("keydown", e => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        if (e.target.dataset.f === "repl") replaceOne();
        else if (e.target.dataset.f === "q") { if (F.results.length && !S.timer) step(e.shiftKey ? -1 : 1); else { clearTimeout(S.timer); search(); } }
      });
      form.addEventListener("submit", e => e.preventDefault());
      paintResults();
    }
    function paintResults() {
      const F = S.find, res = body.querySelector(".br-res"), st = body.querySelector(".br-fs");
      if (!res) return;
      const pieces = new Set(F.results.map(r => r.file)).size;
      st.textContent = F.msg || (!F.q ? "" : F.busy && !F.results.length ? "Looking…" : F.results.length
        ? `${bookCount(F.results.length)} in ${pieces === 1 ? "1 piece" : `${pieces} pieces`}` : "Not in the book");
      body.querySelector("[data-replace]").disabled = !F.results.length || F.busy;
      body.querySelector("[data-all]").disabled = !F.results.length || F.busy;
      const groups = [];
      F.results.forEach((r, i) => { const g = groups.at(-1); if (g && g.file === r.file) g.items.push([r, i]); else groups.push({file: r.file, title: r.title, items: [[r, i]]}); });
      res.innerHTML = groups.map(g => `<section class="br-g"><h3 class="br-g-h"><span>${esc(g.title)}</span><span class="br-g-n">${g.items.length}</span></h3>
        <ol class="br-list">${g.items.map(([r, i]) => `<li><button type="button" class="br-li br-r${i === F.cur ? " on" : ""}" data-r="${i}"${i === F.cur ? ` aria-current="true"` : ""}>
          <span class="br-r-t">${esc(r.before.length >= 40 ? "…" + r.before.replace(/^\S*\s+/, "") : r.before)}<mark>${esc(r.match)}</mark>${esc(r.after.length >= 40 ? r.after.replace(/\s+\S*$/, "") + "…" : r.after)}</span>
          ${r.in !== "text" ? `<span class="br-r-in">${r.in === "note" ? "In a note" : "In a caption"}</span>` : ""}</button></li>`).join("")}</ol></section>`).join("");
    }
    /* the book as it is on disk: what is typed in the open pieces is saved first */
    async function search() {
      clearTimeout(S.timer); S.timer = 0;
      const F = S.find, q = F.q, token = (S.findToken = {});
      if (!q) { F.results = []; F.cur = -1; F.msg = ""; tools.setFind(null); paintResults(); return; }
      F.busy = true; F.msg = ""; paintResults();
      try {
        for (const p of tools.panes().map(x => x.piece)) if (p?.dirty) await p.flush();
        const r = await api(`/api/book/search?b=${encodeURIComponent(book().id)}&q=${encodeURIComponent(q)}&whole=${F.whole ? 1 : 0}&case=${F.case ? 1 : 0}`);
        if (S.findToken !== token) return;
        const keep = F.cur >= 0 ? F.results[F.cur] : null;
        F.results = r;
        F.cur = keep ? r.findIndex(x => x.file === keep.file && x.index === keep.index) : -1;
      } catch (e) { if (S.findToken === token) { F.results = []; F.cur = -1; F.msg = plain(e.message); } }
      finally { if (S.findToken === token) F.busy = false; }
      if (S.open !== "find") return;
      setFind();
      paintResults();
    }
    function setFind() {
      const F = S.find, cur = F.results[F.cur];
      tools.setFind(F.q ? {q: F.q, whole: F.whole, case: F.case, current: cur ? {file: cur.file, index: cur.index} : null} : null);
    }
    function step(d) {
      const F = S.find, n = F.results.length;
      if (n) go((F.cur + d + n) % n);
    }
    /* a result: its piece opened (where it is open, or in the first pane), the match selected and in view */
    async function go(i, {focus = false} = {}) {
      const F = S.find, r = F.results[i];
      if (!r) return;
      F.cur = i; setFind(); paintResults();
      body.querySelector(`[data-r="${i}"]`)?.scrollIntoView({block: "nearest"});
      let p = tools.panes().map(x => x.piece).find(x => x?.file === r.file && x.text && !x.closed);
      if (!p) {
        await BookEditor.openPiece(r.file);
        p = tools.W?.piece;
        if (!p || p.file !== r.file || !p.text) return;
      }
      const T = p.text, m = tools.matchesOf(tools.containersOf(T.view.state.doc, T.ctx.language), F)[r.index];
      if (!m) return;
      if (m.box.kind === "text") {
        const v = T.view;
        v.dispatch(v.state.tr.setSelection(TextSelection.create(v.state.doc, m.box.at[m.from], m.box.at[m.to])));
        tools.scrollTo(T, m.box.at[m.from], 0.35);
        if (focus) v.focus();
      } else if (m.box.kind === "note") {
        const nv = T.noteAt(m.box.pos);
        tools.scrollTo(T, m.box.pos, 0.35);
        if (nv) {
          nv.open(false);
          const inner = nv.inner, off = m.box.pos + 1;
          inner.dispatch(inner.state.tr.setSelection(TextSelection.create(inner.state.doc, m.box.at[m.from] - off, m.box.at[m.to] - off)));
        }
      } else {
        tools.scrollTo(T, m.box.pos, 0.35);
        const cap = T.view.nodeDOM(m.box.pos)?.querySelector?.(".bk-cap");
        if (cap) { cap.focus(); cap.setSelectionRange(m.from, m.to); }
      }
    }
    const openPieces = file => tools.panes().map(x => x.piece).filter(p => p && p.text && !p.closed && (!file || p.file === file));
    async function replaceOne() {
      const F = S.find, r = F.results[F.cur];
      if (F.busy || !F.results.length) return;
      if (!r) return go(0);                            // the first press shows the match, the next replaces it
      F.busy = true; paintResults();
      try {
        const done = await guarded(openPieces(r.file), async () => {
          // the match must still be the one shown: the text may have changed since the search
          const now = await api(`/api/book/search?b=${encodeURIComponent(book().id)}&q=${encodeURIComponent(F.q)}&whole=${F.whole ? 1 : 0}&case=${F.case ? 1 : 0}`);
          const same = now.find(x => x.file === r.file && x.index === r.index);
          if (!same || same.before !== r.before || same.after !== r.after || same.match !== r.match) return null;
          return api("/api/book/replace", {b: book().id, q: F.q, repl: F.repl, whole: F.whole, case: F.case, f: r.file, index: r.index});
        }, "replace");
        if (!done) toast("The text changed since the search: the results are up to date now.");
      } catch (e) { toast(plain(e.message), true); }
      F.busy = false;
      const at = F.cur;
      await search();
      if (F.results.length) go(Math.min(at, F.results.length - 1));
    }
    async function replaceAll() {
      const F = S.find;
      if (!F.results.length || F.busy) return;
      const pieces = new Set(F.results.map(r => r.file)).size;
      F.busy = true; paintResults();
      try {
        const r = await guarded(openPieces(), () => api("/api/book/replace", {b: book().id, q: F.q, repl: F.repl, whole: F.whole, case: F.case}), "replace");
        toast(`Replaced ${bookCount(r.replaced)} in ${pieces === 1 ? "1 piece" : `${pieces} pieces`}. The text before is in each piece's History`);
      } catch (e) { toast(plain(e.message), true); }
      F.busy = false; F.cur = -1;
      search();
    }

    /* Changes on disk while pieces are open (BookTools.guarded): every editor and field of them locked, saved first, read
       again after; saves of pieces left a moment ago land first. */
    const guarded = (pieces, run, by) => BX.guarded(pieces, run, {settled: BookEditor.settled, by});

    /* clicks and right-clicks in the panels */
    body.addEventListener("click", e => {
      const t = e.target;
      const o = t.closest(".br-o"); if (o) return goOutline(o);
      const c = t.closest(".br-c-go"); if (c) return goComment(+c.dataset.i);
      const rs = t.closest("[data-resolve]"); if (rs) return resolveComment(+rs.dataset.resolve);
      const h = t.closest(".br-h-go"); if (h) return compare(h.dataset.when);
      const re = t.closest("[data-restore]"); if (re) return restore(re.dataset.restore);
      if (t.closest("[data-add]")) return newSource();
      const ci = t.closest("[data-cite]"); if (ci) return cite(ci.dataset.cite);
      const s = t.closest(".br-s-go"); if (s) return editSource(s.dataset.id);
      if (t.closest("[data-back]")) return back();
      if (t.closest("[data-remove]")) return removeSource(S.form?.orig?.id);
      const r = t.closest("[data-r]"); if (r) return go(+r.dataset.r, {focus: true});
      if (t.closest("[data-replace]")) return replaceOne();
      if (t.closest("[data-all]")) return replaceAll();
    });
    body.addEventListener("input", e => { if (e.target.classList.contains("br-sq")) { S.filter = e.target.value; paintSourceList(); } });
    body.addEventListener("mousedown", e => { if (e.button === 0 && e.target.closest("[data-cite]")) e.preventDefault(); });
    body.addEventListener("contextmenu", e => {
      const t = e.target;
      if (t.closest("input, textarea, select")) return;
      const o = t.closest(".br-o"), c = t.closest(".br-c-go"), h = t.closest(".br-h-go"), s = t.closest(".br-s-go"), r = t.closest("[data-r]");
      const items = o ? [{label: "Go to", act: () => goOutline(o)}]
        : c ? [{label: "Go to", act: () => goComment(+c.dataset.i)}, {label: "Resolve", act: () => resolveComment(+c.dataset.i)}]
        : h ? [{label: S.history?.open === h.dataset.when ? "Hide the comparison" : "Compare with the text now", act: () => compare(h.dataset.when)},
               {label: "Restore", act: () => restore(h.dataset.when)}]
        : s ? [{label: "Cite", act: () => cite(s.dataset.id)}, {label: "Edit…", act: () => editSource(s.dataset.id)}, "-",
               {label: "Remove…", danger: true, act: () => removeSource(s.dataset.id)}]
        : r ? [{label: "Go to", act: () => go(+r.dataset.r, {focus: true})}, {label: "Replace", act: () => go(+r.dataset.r).then(replaceOne)}]
        : null;
      if (items) StudioMenu.open(e, items);
    });

    paintIcons();
    return {
      panels: available,
      open,
      close,
      unmount() { clearTimeout(S.timer); clearTimeout(S.selTimer); host.replaceChildren(); host.hidden = true; },
      /* the pane last written in shows another piece */
      pieceChanged() { if (S.open && S.open !== "sources" && S.open !== "find") render(); },
      /* a text changed (doc) or its cursor moved */
      changed(T, doc) {
        if (!S.open || T !== text()) return;
        if (doc && (S.open === "outline" || S.open === "comments" || S.open === "history")) {
          if (body.contains(document.activeElement)) return;      // not under the author's hands
          clearTimeout(S.timer); S.timer = setTimeout(() => S.open === "history" ? recompare() : render(), 300);
        } else if (S.open === "outline") { clearTimeout(S.selTimer); S.selTimer = setTimeout(markOutline, 80); }
      },
      /* the book read again (the poll) */
      refresh() {
        paintIcons();
        if (S.open && !available().some(([id]) => id === S.open)) return close();
        if (S.open === "sources" && !S.form && !body.contains(document.activeElement)) renderSources(true);
        if (S.open === "find" && S.find.q && !S.find.busy) { clearTimeout(S.timer); S.timer = setTimeout(search, 400); }
        if (S.open === "outline" || S.open === "history" || S.open === "comments") head(PANELS.find(p => p[0] === S.open)[1], piece()?.name || "");
      },
      /* a save went through; one with a snapshot adds to History */
      saved(p, r) { if (r.snapshot && S.open === "history" && p === piece() && S.history) { S.history.list = null; renderHistory(); } },
    };
  }

  root.BookRail = {mount};
})(window);
