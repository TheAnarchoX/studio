"use strict";
/* Compose (#/book/<id>/compose, …/compose/<page>, …/compose?entry=<i>): the book as its set pages. On the left the
   book's contents (generated pages included), each entry with the page it starts on; in the middle the pages on a
   desk (book-pages.js), in spreads or one at a time; on the right the design panel, or the print checks. Above, the
   trim size, spreads or pages, the zoom, Check and Export PDF; below, how many pages and how long they took to set.
   The pages are Typst's (GET /api/book/pages): the same compile makes the PDF, so what shows here is what prints.
   A design change is sent 400 ms after the last input (POST /api/book/design), then the pages are asked for again;
   only pages that changed load again. The poll asks again when the book changes on disk.
   A classic script after book-pages.js; sets showBookCompose(id, {page, entry}) for the route and
   window.BookCompose = {mount(el, {book, page, entry}), unmount(), refresh(book), exportPdf(id)} (exportPdf: the one
   Export PDF dialog, from anywhere). */

/* the route: the book is read, then the view mounts (as showBook does for the writing window) */
async function showBookCompose(id, at = {}) {
  const my = ++bookToken;
  state.view = "book"; setNav("books");
  try {
    const [b] = await Promise.all([api("/api/book?b=" + encodeURIComponent(id)), loadBookKinds().catch(() => null)]);
    if (my !== bookToken || state.view !== "book") return;
    state.book = b; state.bookTab = "compose"; state.bookFile = null;
    BookCompose.mount(app, {book: b, page: at.page, entry: at.entry});
  } catch (e) {
    if (my !== bookToken || state.view !== "book") return;
    state.view = "missing";
    app.innerHTML = `<header class="pagehead"><h1 class="display">Not found</h1></header><p class="empty">${esc(e.message)} <a href="#/books">Back to the books</a></p>`;
  }
}

const BookCompose = (() => {
  const SEND_AFTER = 400;
  const MM_IN = 25.4;
  const WEIGHTS = [[100, "Thin"], [200, "Extra light"], [300, "Light"], [400, "Regular"], [500, "Medium"], [600, "Semibold"],
    [700, "Bold"], [800, "Extra bold"], [900, "Black"]];
  const LEVELS = [["fail", "Fix"], ["warn", "Look at"], ["info", "For information"]];
  const LABEL_NAMES = [["toc", "Contents"], ["notes", "Notes"], ["bibliography", "Bibliography"], ["index", "Index"],
    ["first-lines", "Index of first lines"], ["part", "Part, before its number"], ["chapter", "Chapter, before its number"]];

  /* The design panel, section by section: `reset` names the stored parts Reset to template takes away; each field is
     {k: path in the design, t: type, …}. Types: sel (options [value, label]), seg (the same, as buttons), num (min, max,
     step, unit), sw (a switch with its sentence), font, weight, label (a generated page's name), and the special ones. */
  const SECTIONS = [
    {id: "size", name: "Size and printer", reset: ["trim", "printer", "paper", "interior"], fields: [
      {t: "trim"},
      {k: "printer", t: "printer", label: "Printer"},
      {k: "paper", t: "seg", label: "Paper", opts: [["white", "White"], ["cream", "Cream"]]},
      {k: "interior", t: "seg", label: "Interior", opts: [["grey", "Grey"], ["colour", "Colour"]],
        hint: "A grey interior prints the images in grey; the preview shows them as they will print."},
    ]},
    {id: "margins", name: "Margins", reset: ["margins"], fields: [{t: "margins"}]},
    {id: "text", name: "Text", reset: ["text", "scene"], fields: [
      {k: "text.font", t: "font", label: "Font"},
      {k: "text.weight", t: "weight", label: "Weight"},
      {t: "pair", fields: [{k: "text.size", t: "num", label: "Size", min: 7, max: 16, step: 0.25, unit: "pt"},
        {k: "text.line", t: "num", label: "Line", min: 7, max: 40, step: 0.25, unit: "pt"}]},
      {k: "text.align", t: "seg", label: "Alignment", opts: [["justify", "Justified"], ["left", "Left"]]},
      {k: "text.hyphenate", t: "sw", text: "Hyphenate in the book's language"},
      {k: "text.paragraph", t: "seg", label: "Paragraphs", opts: [["indent", "Indented"], ["space", "Spaced"]]},
      {k: "scene", t: "sel", label: "Scene breaks", opts: [["asterisks", "Asterisks  * * *"], ["asterism", "Asterism  ⁂"], ["space", "A blank line"]]},
    ]},
    {id: "headings", name: "Headings and openings", reset: ["headings"], fields: [
      {k: "headings.font", t: "font", label: "Font", same: true},
      {t: "pair", fields: [{k: "headings.size", t: "num", label: "Size", min: 8, max: 48, step: 0.5, unit: "pt"},
        {k: "headings.sink", t: "num", label: "Sink", min: 0, max: 120, step: 1, unit: "mm"}]},
      {k: "headings.case", t: "sel", label: "Chapter titles", opts: [["as-written", "As written"], ["smallcaps", "Small capitals"], ["caps", "Capitals"]]},
      {k: "headings.number", t: "sel", label: "Chapter numbers", opts: [["none", "None"], ["digits", "1, 2, 3"], ["words", "One, two, three"], ["roman", "I, II, III"]]},
      {k: "headings.sections", t: "seg", label: "Sections", opts: [["plain", "Plain"], ["numbered", "Numbered"]]},
      {k: "headings.start", t: "seg", label: "Chapters start", opts: [["right", "On a right-hand page"], ["next", "On the next page"]]},
      {k: "headings.opening", t: "seg", label: "Opening words", opts: [["smallcaps", "Small capitals"], ["none", "As written"]]},
    ]},
    {id: "heads", name: "Running heads and numbers", reset: ["heads"], fields: [
      {k: "heads.verso", t: "sel", label: "Left-hand pages", opts: [["title", "The book's title"], ["author", "The author"], ["none", "Nothing"]]},
      {k: "heads.recto", t: "sel", label: "Right-hand pages", opts: [["piece", "The piece's title"], ["title", "The book's title"], ["none", "Nothing"]]},
      {k: "heads.style", t: "seg", label: "Set in", opts: [["smallcaps", "Small capitals"], ["italic", "Italic"]]},
      {k: "heads.folio", t: "sel", label: "Page numbers", opts: [["bottom-centre", "At the foot, centred"], ["bottom-outside", "At the foot, outside"], ["top-outside", "At the head, outside"]]},
    ]},
    {id: "poems", name: "Poems", reset: ["poems"], fields: [
      {k: "poems.place", t: "seg", label: "Place", opts: [["optical-centre", "Optical centre"], ["left", "Left edge"]],
        hint: "Optical centre puts a poem's longest line in the middle of the text block."},
      {k: "poems.keepStanzas", t: "sw", text: "Keep each stanza on one page"},
    ]},
    {id: "notes", name: "Notes", reset: ["notes"], fields: [
      {k: "notes.size", t: "num", label: "Size", min: 6, max: 12, step: 0.25, unit: "pt"},
      {k: "notes.pageRefs", t: "sw", text: "Page references in the list of notes"},
      {t: "notesKind"},
    ]},
    {id: "citations", name: "Citations", reset: ["citations"], fields: [
      {k: "citations.style", t: "seg", label: "Style", opts: [["chicago", "Chicago"], ["apa", "APA"]]},
      {k: "citations.list", t: "seg", label: "The bibliography lists", opts: [["cited", "Cited sources"], ["all", "All sources"]]},
    ]},
    {id: "pages", name: "Generated pages", reset: ["pages"], fields: [
      {t: "labels"},
      {k: "pages.contentsSections", t: "sw", text: "Sections in the contents"},
      {k: "pages.leaders", t: "sw", text: "Dot leaders in the contents"},
      {k: "pages.setIn", t: "sw", text: "A “Set in” line on the copyright page"},
    ]},
  ];

  let C = null;                     // the open view
  const seen = new Map();           // book id -> the page last in view, for coming back to Compose

  const get = (o, path) => path.split(".").reduce((v, k) => v == null ? v : v[k], o);
  /* {a: {b: v}} from "a.b" */
  const nest = (path, v) => path.split(".").reduceRight((acc, k) => ({[k]: acc}), v);
  function merge(a, b) {
    const out = {...a};
    for (const [k, v] of Object.entries(b)) out[k] = v && typeof v === "object" && !Array.isArray(v) && out[k] && typeof out[k] === "object" ? merge(out[k], v) : v;
    return out;
  }
  const num = v => (Math.round(v * 100) / 100).toLocaleString("en-GB", {maximumFractionDigits: 2});
  const inches = mm => String(Math.round(mm / MM_IN * 1000) / 1000);
  const plainNum = v => String(Math.round(v * 100) / 100);
  const viewPref = (k, d) => pref.get("compose." + k, d);

  /* ——— the view ——— */
  function mount(el, {book, page, entry} = {}) {
    unmount();
    el.innerHTML = `<div class="bc">
      <header class="bc-bar">
        <nav class="bc-tabs" role="tablist" aria-label="${esc(book.title)}">${tabs(book.id)}</nav>
        <div class="bc-tools">
          <span class="bc-trim"><select class="select bc-ctl" data-k="trim" aria-label="Trim size"></select>
            <span class="bc-custom" hidden><span class="bc-num"><input class="input bc-ctl" data-k="cw" inputmode="decimal" aria-label="Page width"><span class="bc-u"></span></span>
              <span class="bc-times" aria-hidden="true">×</span><span class="bc-num"><input class="input bc-ctl" data-k="ch" inputmode="decimal" aria-label="Page height"><span class="bc-u"></span></span></span></span>
          <div class="seg bc-mode" role="group" aria-label="Show the pages as"><button type="button" data-mode="spreads">Spreads</button><button type="button" data-mode="single">Pages</button></div>
          <div class="bc-zoom" role="group" aria-label="Zoom"><button type="button" data-zoom="-1" title="Zoom out · Ctrl+−" aria-label="Zoom out">−</button>
            <button type="button" class="bc-zl" aria-haspopup="menu" title="Zoom"><span class="bc-zl-l"></span><span class="bc-zl-s"></span></button>
            <button type="button" data-zoom="1" title="Zoom in · Ctrl+=" aria-label="Zoom in">+</button></div>
        </div>
        <div class="bc-acts"><button type="button" class="btn small bc-check" data-act="check">Check</button>
          <button type="button" class="btn small" data-act="export">Export PDF</button>
          <button type="button" class="bc-tog" data-act="panel" aria-pressed="true" title="Show or hide the design panel">Design</button></div>
      </header>
      <aside class="bc-contents" aria-label="Contents"></aside>
      <section class="bc-main" aria-label="Pages"></section>
      <aside class="bc-side" aria-label="Design"></aside>
      <footer class="bc-foot"><button type="button" class="bw-tog" data-act="contents" aria-pressed="true" title="Show or hide the contents">Contents</button>
        <span class="bc-state" role="status"></span><span class="bc-where"></span></footer></div>`;
    const root = $(".bc", el);
    C = {book, root, design: null, pages: null, report: null, side: "design", pending: null, timer: 0, sending: null,
      unanswered: [], epoch: 0, recent: "panel", loading: false, again: false, error: null, entryAt: -1, page: -1, checking: false, urlTimer: 0,
      initial: page ? {page: page - 1} : entry != null ? {entry} : seen.has(book.id) ? {page: seen.get(book.id)} : {page: 0},
      contents: $(".bc-contents", root), side_: $(".bc-side", root), foot: $(".bc-state", root), where: $(".bc-where", root)};
    document.title = `${book.title} — Compose — Studio`;
    C.viewer = BookPages.mount($(".bc-main", root), {
      book, mode: viewPref("mode", "spreads"), zoom: zoomFromPref(), hint: "Double-click to open the text here",
      onPage: i => onPage(i), onOpen: (i, x, y) => openText(i, x, y), onZoom: () => paintZoom(),
      refetch: () => loadPages(),
    });
    paintMode(); paintZoom(); paintContents(); paintSide(); paintFoot();
    fit();
    // a window made narrower gives the pages their room again (the window's own event as well: it comes even when the
    // window draws no frames, as a hidden one doesn't)
    C.ro = new ResizeObserver(() => fit());
    C.ro.observe(root);
    addEventListener("resize", fit);
    wire();
    loadDesign();
    loadPages();
    api("/api/book/preflight?b=" + encodeURIComponent(book.id)).then(r => { if (C && C.book.id === book.id && r && r.items) { C.report = r; paintCheck(); } }).catch(() => {});
  }

  function unmount() {
    if (!C) return;
    const c = C;
    if (c.pending) flush();                 // a change typed just now still goes
    clearTimeout(c.urlTimer);
    c.ro?.disconnect();
    removeEventListener("resize", fit);
    c.viewer.destroy();
    C = null;
  }

  /* the poll: the book changed on disk (a save in another window, Claude, a design change made here) */
  function refresh(b) {
    if (!C || b.id !== C.book.id) return;
    C.book = b;
    paintContents();
    loadPages();
    if (!C.pending && !C.sending) loadDesign();
  }

  const tabs = id => bookViewTabs(id, "compose");       // book.js: Write · Compose · Settings

  /* ——— reading ——— */
  async function loadDesign() {
    const c = C;
    if (c.unanswered.length) return;            // the answer to that post brings the design
    const epoch = c.epoch;
    try {
      const d = await api("/api/book/design?b=" + encodeURIComponent(c.book.id));
      // a change posted while this was under way may not be in it: the post's own answer is newer
      if (C !== c || c.epoch !== epoch || c.unanswered.length) return;
      const first = !c.design;
      c.design = d;
      if (first || c.side !== "design") paintSide(); else syncPanel();       // what is being typed stays
      paintTrim();
      paintContents();
    } catch (e) { if (C === c) { c.designError = e.message; paintSide(); } }
  }

  /* The pages, compiled when the book changed. One request at a time; a change meanwhile asks once more after it. */
  async function loadPages() {
    const c = C;
    if (!c) return;
    if (c.loading) { c.again = true; return; }
    c.loading = true; c.again = false; c.waitWords = BookPages.SETTING;
    const slow = setTimeout(() => { if (C === c && c.loading) paintFoot(); }, 150);       // a quick answer doesn't flicker
    const stopWatch = BookPages.watchSetting(c.book.id, words => { if (C === c && c.loading) { c.waitWords = words; paintFoot(); } });
    try {
      const r = await api("/api/book/pages?b=" + encodeURIComponent(c.book.id));
      if (C !== c) return;
      c.error = null;
      c.pages = r;
      c.viewer.show(r);
      if (c.initial && r.count) {
        const at = c.initial;
        c.initial = null;
        const i = at.entry != null ? firstPage(+at.entry) : at.page;
        c.viewer.go(i >= 0 ? Math.min(i, r.count - 1) : 0);
      }
      if (r.count) onPage(c.viewer.current());          // the same page may now belong to another entry
      paintContents();
      paintMargins();
      paintCheck();
      if (c.side === "checks") paintSide();
    } catch (e) {
      if (C === c) c.error = e.message;
    } finally {
      clearTimeout(slow);
      stopWatch();
      if (C === c) {
        c.loading = false;
        paintFoot();
        if (c.again) loadPages();
      }
    }
  }

  /* the first page (0-based) of contents entry i, or -1 when it has none */
  function firstPage(i) {
    const list = C.pages?.pages || [];
    return list.findIndex(p => p.entry === i);
  }

  /* ——— the contents on the left ——— */
  function paintContents() {
    const b = C.book, pages = C.pages?.pages || [], host = C.contents;
    const scroll = $(".bb-scroll", host)?.scrollTop || 0;
    const first = new Map();
    pages.forEach((p, i) => { if (p.entry != null && !first.has(p.entry)) first.set(p.entry, i); });
    // the generated pages left out (their feature is off, or nothing to list): shown, muted, as not in the pages
    const left = new Map((C.pages?.left || []).map(x => [x.entry, x.why]));
    let inPart = false;
    const row = (e, i, group) => {
      if (group !== "Body") inPart = false;
      const isPart = e.kind === "part", indent = inPart && !isPart && group === "Body";
      if (isPart) inPart = true;
      const at = first.get(i), title = e.auto ? printedName(e.auto) : e.title || pieceKindName(e.kind), out = at == null && left.has(i);
      const cls = `bb-row${e.auto ? " auto" : ""}${isPart ? " part" : ""}${indent ? " in" : ""}${!e.auto && !e.title ? " untitled" : ""}${out ? " out" : ""}${i === C.entryAt ? " cur" : ""}`;
      const folio = at == null ? "" : pages[at].folio || String(at + 1);
      const tip = at != null ? `Page ${folio}` : e.missing ? "Missing from the manuscript folder"
        : out ? `Not in the pages: ${left.get(i)}.` : "Not in the pages";
      return `<li class="${cls}" data-i="${i}"><button type="button" class="bb-a" data-entry="${i}" ${at == null ? "disabled" : ""}${i === C.entryAt ? ' aria-current="true"' : ""}
          title="${esc(tip)}">
        <span class="bk-dot ${e.auto ? "" : esc(e.status || "")}" aria-hidden="true"></span><span class="bb-t">${esc(title)}${out ? `<span class="bb-out">Not in the pages</span>` : ""}</span>
        <span class="bb-w">${e.missing ? `<span class="bad">missing</span>` : esc(folio)}</span></button></li>`;
    };
    const groups = bookGroups(b.contents).map(([name, items]) => [name, items.filter(e => !e.auto || bookAutoOn(b, e.auto))])
      .filter(([, items]) => items.length)
      .map(([name, items]) => `<section class="bb-group"><div class="bb-ghead"><h2 class="label">${esc(name)}</h2></div>
        <ol class="bb-list">${items.map(e => row(e, b.contents.indexOf(e), name)).join("")}</ol></section>`).join("");
    const d = C.design?.design, size = C.pages?.width ? sizeName(C.pages.width, C.pages.height) : d ? sizeName(d.width, d.height) : "";
    host.innerHTML = `<div class="bb-scroll"><div class="bb-head"><div class="bb-k"><span class="kicker"><a href="#/books">Books</a> · ${esc(bookKindName(b.kind))}</span></div>
        <p class="bb-book">${esc(b.title)}</p><p class="bb-total">${esc([C.pages?.count ? plural(C.pages.count, "page") : "", size].filter(Boolean).join(" · "))}</p></div>
      <nav class="bb-groups" aria-label="Contents">${groups || `<p class="bb-empty">Nothing in this book yet.</p>`}</nav></div>`;
    $(".bb-scroll", host).scrollTop = scroll;
  }
  /* a generated page as its heading prints it (Noten, Inhoud), or by Studio's name when it prints none (Half-title) */
  function printedName(auto) {
    const labels = C.design?.design?.pages?.labels || {};
    const key = auto === "index" && C.book.features?.index === "first-lines" ? "first-lines" : auto;
    return labels[key] || autoPageName(C.book, auto);
  }
  /* the size as the trim list names it, or in mm */
  const sizeName = (w, h) => trimName(C.design?.trims, w, h);

  /* the entry of the page in view: marked, and kept in view in the list */
  function markEntry(i) {
    if (i === C.entryAt) return;
    C.entryAt = i;
    for (const r of $$(".bb-row", C.contents)) {
      const on = +r.dataset.i === i, a = $(".bb-a", r);
      r.classList.toggle("cur", on);
      if (on) { a.setAttribute("aria-current", "true"); r.scrollIntoView({block: "nearest"}); }
      else a.removeAttribute("aria-current");
    }
  }

  function onPage(i) {
    if (!C) return;
    C.page = i;
    seen.set(C.book.id, i);
    const p = C.pages?.pages?.[i];
    if (p) markEntry(p.entry);
    paintWhere();
    clearTimeout(C.urlTimer);
    const c = C;
    C.urlTimer = setTimeout(() => {         // the address follows, so a reload comes back to this page
      if (C === c && state.view === "book" && state.bookTab === "compose") history.replaceState(null, "", bookComposeHash(c.book.id, i + 1));
    }, 400);
  }

  /* ——— the foot ——— */
  function paintFoot() {
    const c = C, el = c.foot, p = c.pages;
    el.classList.remove("bad");
    if (c.loading) el.textContent = c.waitWords || BookPages.SETTING;       // or the font being cut for print
    else if (c.error) { el.textContent = c.error; el.classList.add("bad"); }
    else if (p?.error) { el.textContent = `The book can't be set: ${plain(p.error)}.${p.count ? " The pages shown are the last that could be." : ""}`; el.classList.add("bad"); }
    else if (p) el.textContent = `${bookCount(p.count)} page${p.count === 1 ? "" : "s"} · set in ${Math.max(0.1, +p.seconds || 0).toLocaleString("en-GB", {minimumFractionDigits: 1, maximumFractionDigits: 1})} s`;
    else el.textContent = "";
    if (!p?.count) C.viewer.message(c.loading || !p ? c.waitWords || BookPages.SETTING : p.error ? `The book can't be set: ${plain(p.error)}.` : "This book has no pages yet.");
    paintWhere();
  }
  function paintWhere() {
    const pages = C.pages?.pages || [], i = C.page;
    if (!pages.length || i < 0 || i >= pages.length) { C.where.textContent = ""; return; }
    let a = i, z = i;
    if (C.viewer.mode === "spreads") { a = i % 2 ? i : Math.max(0, i - 1); z = i % 2 ? Math.min(pages.length - 1, i + 1) : i; if (i === 0) a = z = 0; }
    // by their page numbers; a blank page has none, and a spread of two blank pages says where it is in the book
    const named = [...new Set([a, z])].map(k => pages[k].folio).filter(Boolean);
    C.where.textContent = named.length === 2 ? `Pages ${named[0]}–${named[1]}` : named.length ? `Page ${named[0]}`
      : a === z ? `Page ${a + 1} of ${pages.length}` : `Pages ${a + 1}–${z + 1} of ${pages.length}`;
  }

  /* ——— the bar: trim, spreads or pages, zoom, Check ——— */
  function paintMode() {
    $$(".bc-mode button", C.root).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.mode === C.viewer.mode)));
  }
  function zoomFromPref() {
    const z = viewPref("zoom", "page");
    return z === "width" || z === "page" || z === "real" ? z : Math.min(4, Math.max(0.25, +z || 1));
  }
  function paintZoom() {
    if (!C) return;
    const z = C.viewer.zoom(), btn = $(".bc-zl", C.root), pct = `${Math.round(C.viewer.effective() * 100)} %`;
    $(".bc-zl-l", btn).textContent = C.viewer.label();
    $(".bc-zl-s", btn).textContent = pct;            // a narrow bar shows the zoom as a percentage, its name in the menu
    btn.title = `Zoom: ${C.viewer.label()}${typeof z === "string" && z !== "real" ? `, ${pct} of real size` : ""}`;
    pref.set("compose.zoom", String(z));
    fitBar();
  }
  function zoomMenu(btn) {
    const r = btn.getBoundingClientRect(), z = C.viewer.zoom();
    const item = (v, label, kbd) => ({label, kbd, checked: z === v, act: () => C?.viewer.setZoom(v)});
    const mode = m => ({label: m === "spreads" ? "Spreads" : "Pages", checked: C.viewer.mode === m, act: () => C && setMode(m)});
    StudioMenu.open({clientX: r.left, clientY: r.bottom + 4, preventDefault() {}, stopPropagation() {}}, [
      ...(+C.root.dataset.fold >= 5 ? [mode("spreads"), mode("single"), "-"] : []),        // Spreads | Pages folded in
      item("width", "Fit width"), item("page", "Fit page", "Ctrl+0"), item("real", "Real size"), "-",
      ...[0.5, 0.75, 1.25, 1.5, 2, 3, 4].map(v => item(v, `${Math.round(v * 100)} %`)),
    ]);
  }
  function setMode(m) {
    C.viewer.setMode(m);
    pref.set("compose.mode", m);
    paintMode(); paintWhere();
  }
  /* the trim: the four sizes and Custom…, whose width and height are in the unit of the size it came from */
  const unitKey = () => "compose.unit." + C.book.id;
  function unit() { return pref.get(unitKey(), /^en\b/.test(C.book.language || "") ? "in" : "mm"); }
  function paintTrim() {
    if (!C?.design) return;
    const d = shown();
    for (const sel of $$("[data-k=trim]", C.root)) {
      if (sel === document.activeElement) continue;
      // the bar names A5 by its name alone, so the select is as narrow as the other sizes; the panel gives its size too
      const name = t => t.id === "custom" ? "Custom…" : sel.closest(".bc-bar") ? t.name.split(" · ")[0] : t.name;
      sel.innerHTML = C.design.trims.map(t => `<option value="${esc(t.id)}" ${t.id === d.trim ? "selected" : ""} title="${esc(t.name)}">${esc(name(t))}</option>`).join("");
    }
    const u = unit();
    for (const box of $$(".bc-custom", C.root)) {
      box.hidden = d.trim !== "custom";
      $$(".bc-u", box).forEach(s => { s.textContent = u; });
      const w = $("[data-k=cw]", box), h = $("[data-k=ch]", box);
      if (d.trim !== "custom" || !(d.width > 0 && d.height > 0)) continue;
      if (w !== document.activeElement) w.value = u === "in" ? inches(d.width) : plainNum(d.width);
      if (h !== document.activeElement) h.value = u === "in" ? inches(d.height) : plainNum(d.height);
    }
    fitBar();
  }
  function trimChosen(id) {
    const d = C.design && shown();
    if (!d) return;
    if (id === "custom") {
      pref.set(unitKey(), /in$/.test(d.trim) ? "in" : d.trim === "custom" ? unit() : "mm");
      send({trim: "custom", width: d.width, height: d.height});
    } else send({trim: id, width: null, height: null});        // a custom size isn't kept behind a preset
  }
  function customTyped(box, final) {
    const u = unit(), w = parseFloat($("[data-k=cw]", box).value.replace(",", ".")), h = parseFloat($("[data-k=ch]", box).value.replace(",", "."));
    const mm = v => u === "in" ? Math.round(v * MM_IN * 100) / 100 : v;
    const ok = Number.isFinite(w) && Number.isFinite(h) && mm(w) >= 90 && mm(w) <= 250 && mm(h) >= 120 && mm(h) <= 330;
    if (ok) send({trim: "custom", width: mm(w), height: mm(h)});
    else if (final) { toast(u === "in" ? "A page is 3.54 to 9.84 in wide and 4.72 to 12.99 in tall." : "A page is 90 to 250 mm wide and 120 to 330 mm tall.", true); paintTrim(); }
  }

  /* the Check button: the last report's failures and warnings */
  function paintCheck() {
    const btn = $(".bc-check", C.root), r = C.report;
    if (!btn) return;
    btn.disabled = C.checking;
    if (C.checking) { btn.textContent = "Checking…"; fitBar(); return; }
    if (!r) { btn.textContent = "Check"; btn.title = "Run the print checks"; fitBar(); return; }
    const fails = r.items.filter(x => x.level === "fail").length, warns = r.items.filter(x => x.level === "warn").length;
    const parts = [fails ? `${fails} to fix` : "", warns ? `${warns} to look at` : ""].filter(Boolean);
    // failures first, as everywhere; a narrow bar shows the first count only, or none (fitBar); the tooltip has both
    btn.innerHTML = `<span>Check<span class="bc-ck"> · <span class="bc-ck-1">${esc(parts[0] || "nothing to fix")}</span>${parts[1] ? `<span class="bc-ck-2">, ${esc(parts[1])}</span>` : ""}</span></span>`;
    btn.title = `${parts.length ? parts.join(", ").replace(/^./, x => x.toUpperCase()) : "Nothing to fix"}. `
      + (stale() ? "From the last check, made before the latest changes: check again." : `Checked ${when(r.at)}.`);
    fitBar();
  }
  const stale = () => !!(C.report && C.pages && C.report.signature && C.report.signature !== C.pages.signature);

  async function runCheck() {
    const c = C;
    if (!c || c.checking) return null;
    if (c.pending) await flush();
    c.checking = true;
    paintCheck();
    if (c.side === "checks") paintSide();
    try {
      const r = await api("/api/book/preflight", {b: c.book.id});
      if (C !== c) return r;
      c.report = r;
      return r;
    } catch (e) { if (C === c) toast(e.message, true); return null; }
    finally {
      if (C === c) {
        c.checking = false;
        paintCheck();
        showSide("checks");
      }
    }
  }

  /* ——— room: the columns, then the bar ———
     The contents and the panel are shown as last chosen while the pages keep MIN_DESK px between them; when they
     wouldn't, the column opened longer ago gives way (not for good: it is back when the window is wide again). The one
     chosen last always stays, however narrow the window: it is what was asked for. */
  const MIN_DESK = 480, LEFT = 272, RIGHT = 320;
  function fit() {
    if (!C) return;
    const w = C.root.clientWidth;
    let c = viewPref("contents", "1") === "1", p = viewPref("panel", "1") === "1";
    if (c && p && w - LEFT - RIGHT < MIN_DESK) {
      if (C.recent === "contents") p = false; else c = false;
    }
    C.root.classList.toggle("nocontents", !c);
    C.root.classList.toggle("nopanel", !p);
    $("[data-act=contents]", C.root).setAttribute("aria-pressed", String(c));
    $("[data-act=panel]", C.root).setAttribute("aria-pressed", String(p));
    gutter();
    fitBar();
  }
  /* the panel's scrollbar, so the bar's Design toggle ends where the panel's head and fields do */
  function gutter() {
    const sc = $(".bc-scroll", C.side_);
    if (sc && sc.offsetWidth) C.root.style.setProperty("--bc-gutter", sc.offsetWidth - sc.clientWidth + "px");
  }
  /* The bar never squeezes its controls: when they don't fit it folds, a step at a time (book-compose.css says what each
     step does), until they do. Whether they fit is measured to the fraction of a pixel (scrollWidth rounds, and let a
     pixel through). */
  function fitBar() {
    if (!C) return;
    const bar = $(".bc-bar", C.root);
    delete C.root.dataset.fold;
    for (let k = 1; k <= 6 && barNeeds(bar) > bar.getBoundingClientRect().width + 0.01; k++) C.root.dataset.fold = String(k);
  }
  /* The width the bar's parts take at their own size: the tabs' and the actions' widths, and the page tools up to the
     right edge of their last control and their padding (they grow to fill the bar, so their own width says nothing). */
  function barNeeds(bar) {
    let need = 0;
    for (const part of bar.children) {
      const r = part.getBoundingClientRect();
      if (!r.width) continue;
      if (!part.classList.contains("bc-tools")) { need += r.width; continue; }
      const ends = [...part.children].map(c => c.getBoundingClientRect()).filter(x => x.width).map(x => x.right);
      need += Math.max(r.left, ...ends) - r.left + parseFloat(getComputedStyle(part).paddingRight || 0);
    }
    return need;
  }

  /* ——— the right: the design panel or the checks ——— */
  function showSide(which) {
    C.side = which;
    if (C.root.classList.contains("nopanel")) setPanel(true);
    paintSide();
  }
  function setPanel(on) {
    pref.set("compose.panel", on ? "1" : "0");
    if (on) C.recent = "panel";
    fit();
  }
  function setContents(on) {
    pref.set("compose.contents", on ? "1" : "0");
    if (on) C.recent = "contents";
    fit();
  }

  function paintSide() {
    const host = C.side_;
    const scroll = $(".bc-scroll", host)?.scrollTop || 0, same = host.dataset.side === C.side;
    const at = host.contains(document.activeElement) ? document.activeElement : null;
    const focusKey = at && (at.dataset.k ? `[data-k="${at.dataset.k}"]` : at.dataset.act ? `[data-act="${at.dataset.act}"]` : at.dataset.reset ? `[data-reset="${at.dataset.reset}"]` : null);
    host.dataset.side = C.side;
    host.setAttribute("aria-label", C.side === "checks" ? "Checks" : "Design");
    host.innerHTML = `<div class="bc-scroll">${C.side === "checks" ? checksHtml() : designHtml()}</div>`;
    if (same) $(".bc-scroll", host).scrollTop = scroll;
    gutter();
    if (focusKey) $(focusKey, host)?.focus({preventScroll: true});          // a repaint doesn't take the focus away
    if (C.side === "design") { paintTrim(); paintMargins(); }
  }

  /* ——— the design panel ———
     It shows the design as it will be: the server's last answer with the changes not answered yet on top (posted, or
     still gathering), so the answer to an earlier change never undoes a later one on screen. */
  function shown() {
    let d = C.design.design;
    for (const ch of C.unanswered) d = merge(d, ch);
    if (C.pending) d = merge(d, C.pending);
    const t = C.design.trims.find(x => x.id === d.trim && x.width);       // a preset chosen: its size, not the custom one's
    return t ? {...d, width: t.width, height: t.height} : d;
  }
  const openSections = () => { try { return new Set(JSON.parse(viewPref("sections", '["size","margins","text"]'))); } catch { return new Set(["size", "margins", "text"]); } };
  function designHtml() {
    const D = C.design;
    const head = (title, sub) => `<header class="br-head bc-head"><div class="br-k"><h2 class="kicker">Design</h2>
        <button type="button" class="bw-tog br-x" data-act="close" title="Hide the design panel">Close</button></div>
      <p class="br-t">${esc(title)}</p><p class="br-sub">${esc(sub)}</p></header>`;
    if (!D) return head("", "") + `<div class="bc-body"><p class="br-empty">${esc(C.designError || "Reading the design…")}</p></div>`;
    const d = shown(), open = openSections();
    const printer = D.printers.find(p => p.id === d.printer)?.name || "";
    const sections = SECTIONS.map(s => {
      const isOpen = open.has(s.id), changed = s.reset.some(k => D.stored[k] !== undefined || (k === "trim" && (D.stored.width !== undefined || D.stored.height !== undefined)));
      return `<section class="bc-sec" data-sec="${s.id}"><div class="bc-sh"><button type="button" class="bc-st" aria-expanded="${isOpen}" aria-controls="bc-sb-${s.id}">${esc(s.name)}</button></div>
        <div class="bc-sb" id="bc-sb-${s.id}" ${isOpen ? "" : "hidden"}>${s.fields.map(f => field(f, d)).join("")}
          <div class="bc-rs"><button type="button" class="bm-btn" data-reset="${s.id}" ${changed ? "" : "disabled"} title="${changed ? "Take this section back to the template's settings" : "As the template sets it"}">Reset to template</button></div></div></section>`;
    }).join("");
    return head(D.templates.find(t => t.id === d.template)?.name || "", `${sizeName(d.width, d.height)} · ${printer}`) + `<div class="bc-body">
      <div class="bc-tpl"><label class="label" for="bc-template">Template</label>
        <select class="select" id="bc-template" data-k="template">${D.templates.map(t => `<option value="${esc(t.id)}" ${t.id === d.template ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select>
        <p class="hint">A template sets everything below; what you change here stays when you switch.</p></div>
      ${sections}</div>`;
  }

  const opts = (list, cur) => list.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(cur) ? "selected" : ""}>${esc(l)}</option>`).join("");
  const segHtml = (k, list, cur, label) => `<div class="seg" role="group" aria-label="${esc(label)}" data-k="${esc(k)}">${list.map(([v, l]) =>
    `<button type="button" data-v="${esc(v)}" aria-pressed="${String(v) === String(cur)}">${esc(l)}</button>`).join("")}</div>`;
  const wrap = (label, inner, hint, forId) => `<div class="bc-f">${label ? `<${forId ? `label for="${forId}"` : "span"} class="label">${esc(label)}</${forId ? "label" : "span"}>` : ""}${inner}${hint ? `<p class="hint">${hint}</p>` : ""}</div>`;
  const idOf = k => "bc-" + k.replace(/\./g, "-");

  function field(f, d) {
    const v = f.k ? get(d, f.k) : undefined;
    switch (f.t) {
      case "sel": return wrap(f.label, `<select class="select" id="${idOf(f.k)}" data-k="${f.k}">${opts(f.opts, v)}</select>`, f.hint, idOf(f.k));
      case "seg": return wrap(f.label, segHtml(f.k, f.opts, v, f.label), f.hint && esc(f.hint));
      case "sw": return `<div class="bc-f"><label class="switch"><input type="checkbox" data-k="${f.k}" ${v ? "checked" : ""}><span>${esc(f.text)}</span></label></div>`;
      case "num": return wrap(f.label, numHtml(f, v), f.hint, idOf(f.k));
      case "pair": return `<div class="bc-2">${f.fields.map(x => field(x, d)).join("")}</div>`;
      case "font": {
        const list = C.design.fonts.includes(v) || v == null ? C.design.fonts : [v, ...C.design.fonts];
        return wrap(f.label, `<select class="select" id="${idOf(f.k)}" data-k="${f.k}">${f.same ? `<option value="" ${v == null ? "selected" : ""}>Same as the text</option>` : ""}${opts(list.map(n => [n, n]), v)}</select>`, "", idOf(f.k));
      }
      case "weight": return wrap(f.label, `<select class="select" id="${idOf(f.k)}" data-k="${f.k}">${opts(WEIGHTS.map(([n, l]) => [n, `${l} · ${n}`]), v)}</select>`,
        "A weight the family doesn't have is set in the nearest it has.", idOf(f.k));
      case "printer": return wrap(f.label, `<select class="select" id="${idOf(f.k)}" data-k="${f.k}">${opts(C.design.printers.map(p => [p.id, p.name]), v)}</select>`, "", idOf(f.k));
      case "trim": return wrap("Trim size", `<select class="select" id="bc-trim2" data-k="trim"></select>
        <div class="bc-custom bc-2" hidden><span class="bc-num"><input class="input" data-k="cw" inputmode="decimal" aria-label="Page width"><span class="bc-u"></span></span>
          <span class="bc-num"><input class="input" data-k="ch" inputmode="decimal" aria-label="Page height"><span class="bc-u"></span></span></div>`, "", "bc-trim2");
      case "margins": return `<div class="bc-2">${["inside", "outside", "top", "bottom"].map(k => wrap(k[0].toUpperCase() + k.slice(1),
        numHtml({k: "margins." + k, min: 5, max: 60, step: 0.5, unit: "mm"}, d.margins[k]), "", idOf("margins." + k))).join("")}</div>
        <p class="hint bc-min" id="bc-min"></p>`;
      case "labels": return `<div class="bc-f"><span class="label">Page names</span><div class="bc-labels">${LABEL_NAMES.map(([k, name]) =>
        `<label class="bc-lab"><span>${esc(name)}</span><input class="input" data-k="pages.labels.${k}" value="${esc(d.pages.labels[k] || "")}" maxlength="60" autocomplete="off" spellcheck="false" aria-label="${esc(name)}"></label>`).join("")}</div>
        <p class="hint">In the book's language. Empty gives the usual name back.</p></div>`;
      case "notesKind": {
        const n = C.book.features?.notes, said = {footnotes: "Notes are footnotes", endnotes: "Notes are endnotes", both: "Notes are footnotes and endnotes"}[n] || "Notes are off";
        return `<p class="hint bc-f">${esc(said)} in this book: change it under <a href="${bookTabHash(C.book.id, "features")}">Kind and features</a>.</p>`;
      }
    }
    return "";
  }
  /* a number as text, written with a point as the rest of Studio writes numbers (a comma typed is read as one), with
     its unit; Up and Down step it, Shift ten steps */
  const numHtml = (f, v) => `<span class="bc-num"><input class="input" id="${idOf(f.k)}" data-k="${f.k}" data-num value="${v == null ? "" : plainNum(v)}"
    data-min="${f.min}" data-max="${f.max}" data-step="${f.step}" inputmode="decimal" autocomplete="off" spellcheck="false"><span class="bc-u">${esc(f.unit)}</span></span>`;
  const readNum = s => { const t = String(s).trim().replace(",", "."); return /^\d*\.?\d+$/.test(t) ? Number(t) : NaN; };

  /* the printer's smallest inside margin at this many pages, beside the margins */
  function paintMargins() {
    const el = $("#bc-min", C.side_), D = C.design;
    if (!el || !D) return;
    const d = shown(), p = D.printers.find(x => x.id === d.printer), count = C.pages?.count;
    if (!p?.inside?.length) { el.textContent = ""; return; }
    let min = p.inside[p.inside.length - 1][1];
    if (count) for (const [most, mm] of p.inside) if (most == null || count <= most) { min = mm; break; }
    const short = d.margins.inside < min - 1e-9;
    el.classList.toggle("bad", short);
    el.textContent = `${p.name} asks for an inside margin of at least ${num(min)} mm${count ? ` at ${bookCount(count)} pages` : ""}`
      + (p.min ? `, and ${num(Math.max(p.min.outside, p.min.top, p.min.bottom))} mm on the other sides` : "") + "." + (short ? " This inside margin is narrower." : "");
  }

  /* the panel's fields from the design, leaving alone the one being typed in */
  function syncPanel() {
    if (!C?.design || C.side !== "design") return;
    const d = shown(), host = C.side_;
    const t = C.design.templates.find(x => x.id === d.template)?.name || "";
    const head = $(".br-t", host);
    if (head && head.textContent !== t) head.textContent = t;
    const sub = $(".br-sub", host);
    if (sub) sub.textContent = `${sizeName(d.width, d.height)} · ${C.design.printers.find(p => p.id === d.printer)?.name || ""}`;
    for (const el of $$("[data-k]", host)) {
      const k = el.dataset.k;
      if (el === document.activeElement || k === "trim" || k === "cw" || k === "ch") continue;
      const v = get(d, k);
      if (el.classList.contains("seg")) $$("button", el).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === String(v))));
      else if (el.type === "checkbox") el.checked = !!v;
      else if (el.tagName === "SELECT") el.value = v == null ? "" : String(v);
      else if ("num" in el.dataset) el.value = v == null ? "" : plainNum(v);
      else el.value = v ?? "";
    }
    for (const s of SECTIONS) {
      const btn = $(`[data-reset="${s.id}"]`, host), D = C.design;
      if (btn) btn.disabled = !s.reset.some(k => D.stored[k] !== undefined || (k === "trim" && (D.stored.width !== undefined || D.stored.height !== undefined)));
    }
    paintMargins();
  }

  /* ——— sending changes: gathered, then sent 400 ms after the last ——— */
  function send(changes, now = false) {
    if (!C) return;
    C.pending = merge(C.pending || {}, changes);
    clearTimeout(C.timer);
    if (now) flush(); else C.timer = setTimeout(flush, SEND_AFTER);
  }
  async function flush() {
    const c = C;
    if (!c || !c.pending) return;
    clearTimeout(c.timer);
    const changes = c.pending;
    c.pending = null;
    await post(c, {changes});
  }
  /* one request at a time, in order */
  function post(c, body) {
    const mine = body.changes || {};
    c.unanswered.push(mine);
    c.epoch++;
    const answered = () => { c.unanswered.splice(c.unanswered.indexOf(mine), 1); c.epoch++; };
    const run = async () => {
      try {
        const d = await api("/api/book/design", {b: c.book.id, ...body});
        answered();
        if (C !== c) return;
        c.design = d;
        if (body.template || body.reset) paintSide(); else syncPanel();
        paintTrim();
        paintContents();
        loadPages();
      } catch (e) {
        answered();
        if (C !== c) return;
        toast(e.message, true);
        try { c.design = await api("/api/book/design?b=" + encodeURIComponent(c.book.id)); } catch { /* keep what is shown */ }
        if (C === c) { paintSide(); paintTrim(); }
      }
    };
    const chain = c.sending = (c.sending || Promise.resolve()).then(run);
    chain.finally(() => { if (c.sending === chain) c.sending = null; });
    return chain;
  }

  /* a field's value as the design takes it */
  function valueOf(el) {
    const k = el.dataset.k;
    if (el.type === "checkbox") return el.checked;
    if ("num" in el.dataset) return readNum(el.value);
    if (k === "text.weight") return +el.value;
    if (k === "headings.font") return el.value || null;
    return el.value;
  }
  function changed(el, final) {
    const k = el.dataset.k;
    if (k === "template") { if (C.pending) flush(); post(C, {template: el.value}); return; }
    if (k === "trim") { trimChosen(el.value); return; }
    if (k === "cw" || k === "ch") { customTyped(el.closest(".bc-custom"), final); return; }
    let v = valueOf(el);
    if (final && el.tagName === "INPUT" && el.dataset.sent === JSON.stringify(v)) return;      // sent while typing
    if ("num" in el.dataset) {
      const lo = +el.dataset.min, hi = +el.dataset.max;
      if (!Number.isFinite(v) || v < lo || v > hi) {
        if (final) { toast(`${el.closest(".bc-f")?.querySelector(".label")?.textContent || "The value"} is ${num(lo)} to ${num(hi)} ${el.nextElementSibling?.textContent || ""}.`.replace(/ \.$/, "."), true); syncPanel(); }
        return;
      }
    }
    if (el.tagName === "INPUT") el.dataset.sent = JSON.stringify(v);
    send(nest(k, v));
  }

  /* ——— checks ——— */
  function checksHtml() {
    const r = C.report, head = (title, sub) => `<header class="br-head bc-head"><div class="br-k"><h2 class="kicker">Checks</h2>
        <button type="button" class="bw-tog br-x" data-act="design" title="Back to the design panel">Design</button></div>
      <p class="br-t">${esc(title)}</p><p class="br-sub">${esc(sub)}</p></header>`;
    if (C.checking && !r) return head("", "") + `<div class="bc-body"><p class="br-empty">Checking the pages…</p></div>`;
    if (!r) return head("", "") + `<div class="bc-body"><p class="br-empty">Not checked yet. The checks look for widows and orphans, lines too long for the measure, fonts, image resolution, and the page count and margins against the printer.</p>
      <div class="bc-ck-acts"><button type="button" class="btn small" data-act="recheck">Check</button></div></div>`;
    const pages = C.pages?.pages || [];
    const where = it => it.page ? `p. ${pages[it.page - 1]?.folio || it.page}` : "";
    const groups = LEVELS.map(([level, name]) => {
      const items = r.items.map((it, n) => [it, n]).filter(([it]) => it.level === level);
      if (!items.length) return "";
      return `<section class="bc-ck-g"><h3 class="label">${esc(name)} · ${items.length}</h3><ul class="br-list">${items.map(([it, n]) => {
        const text = `${where(it) ? `<span class="bc-item-p">${esc(where(it))}</span> · ` : ""}${esc(it.message)}`;
        return `<li class="bc-item ${esc(level)}">${it.page ? `<button type="button" class="br-li" data-item="${n}">${text}</button>` : `<p class="bc-item-t">${text}</p>`}
          ${it.file && it.block != null ? `<button type="button" class="bm-btn bc-show" data-show="${n}">Show in the text</button>` : ""}</li>`;
      }).join("")}</ul></section>`;
    }).join("");
    return head(r.summary || "", `Checked ${when(r.at)} · ${plural(r.pages || 0, "page")}`) + `<div class="bc-body">
      <div class="bc-ck-acts"><button type="button" class="btn small" data-act="recheck" ${C.checking ? "disabled" : ""}>${C.checking ? "Checking…" : "Check again"}</button>
        ${stale() ? `<span class="hint">The book has changed since this check.</span>` : ""}</div>
      ${groups || `<p class="br-empty">Nothing to look at.</p>`}</div>`;
  }

  /* ——— Export PDF ———
     One dialog wherever a PDF is asked for: Compose's bar, the book's settings, the palette and the shelf menu (book.js's
     downloadBook sends each of them here). It shows the latest checks' summary and can check first, but never blocks:
     Export PDF is always there. Compose gives what it has (`view`: its report, pages and design, its own Check, a design
     change still to send); anywhere else the dialog reads them itself, the report at once and the pages after (a
     compile, which the export needs anyway). */
  function exportDialog() {
    const c = C;
    exportPdf(c.book.id, {report: () => c.report, pages: () => c.pages, design: () => c.design, check: () => runCheck(),
      before: async () => { if (C === c && c.pending) await flush(); }});
  }
  function exportPdf(id, view = null) {
    const S = {report: view?.report() || null, pages: view?.pages() || null, design: view?.design() || null};
    const stale = () => !!(S.report && S.pages && S.report.signature && S.report.signature !== S.pages.signature);
    const summary = () => !S.report ? `<p class="bc-xs">Not checked yet.</p>`
      : `<p class="bc-xs">Checked ${esc(when(S.report.at))}: <b>${esc(S.report.summary)}</b>.${stale() ? " The book has changed since." : ""}</p>`;
    const what = () => {
      const d = S.design?.design, w = S.pages?.width ?? d?.width, h = S.pages?.height ?? d?.height;
      const said = [S.pages?.count ? plural(S.pages.count, "page") : "", w && h ? trimName(S.design?.trims, w, h) : ""].filter(Boolean).join(" at ");
      return `The interior for the printer${said ? `: ${said}` : ""}, with the fonts embedded${d?.interior === "colour" ? "" : " and the text and images in grey"}. A dated copy is also kept in Books/${id}/exports.`;
    };
    const form = openDialog(`<form class="nb bc-export">
      <h2>Export PDF</h2>
      <p class="muted bc-xw" style="margin:0"></p>
      <div class="bc-xsum"></div>
      <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button>
        <span class="ps-end"><button type="button" class="btn" data-check>Check first</button><button type="submit" class="btn solid">Export PDF</button></span></div></form>`,
    async (f, fm) => {
      const btn = $("button[type=submit]", fm);
      btn.textContent = "Exporting…";
      try { await view?.before(); await downloadBook(id, "pdf", true); } finally { btn.textContent = "Export PDF"; }
    });
    const check = $("[data-check]", form);
    const paint = () => {
      if (!form.isConnected) return;
      $(".bc-xw", form).textContent = what();
      $(".bc-xsum", form).innerHTML = summary();
      if (check.disabled) return;
      check.textContent = S.report ? "Check again" : "Check first";
      check.hidden = !!S.report && !stale();
    };
    paint();
    check.onclick = async () => {
      check.disabled = true; check.textContent = "Checking…";
      let r = null;
      try { r = view ? await view.check() : await api("/api/book/preflight", {b: id}); } catch (e) { toast(e.message, true); }
      if (r?.items) S.report = r;
      if (view) S.pages = view.pages() || S.pages;
      check.disabled = false;
      paint();
    };
    if (!view) {
      api("/api/book/preflight?b=" + encodeURIComponent(id)).then(r => { if (r?.items && !S.report) { S.report = r; paint(); } }).catch(() => {});
      api("/api/book/design?b=" + encodeURIComponent(id)).then(d => { S.design = d; paint(); }).catch(() => {});
      api("/api/book/pages?b=" + encodeURIComponent(id)).then(p => { S.pages = p; paint(); }).catch(() => {});
    }
    return form;
  }
  /* a size as the trim list names it (A5, 5.5 × 8.5 in), or in mm */
  function trimName(trims, w, h) {
    const t = (trims || []).find(x => x.width && Math.abs(x.width - w) < 0.05 && Math.abs(x.height - h) < 0.05);
    return t ? t.name.replace(/^A5 · /, "A5, ") : `${num(w)} × ${num(h)} mm`;
  }

  /* ——— going to the text ——— */
  /* Double-click on a page: the writing window at the block nearest to where the page was clicked (blocks map each
     top-level block to its page; one that starts on an earlier page and runs onto this one counts, at its top). */
  function openText(i, x, y) {
    const p = C.pages?.pages?.[i], e = p ? C.book.contents[p.entry] : null;
    if (!e) return;
    if (!e.file) { toast(`${printedName(e.auto)} is made by Studio from the book's details and pieces.`); return; }
    const blocks = C.pages.blocks?.[e.file] || [];
    const on = [], before = blocks.reduce((k, pg, b) => pg < i ? b : k, -1);
    blocks.forEach((pg, b) => { if (pg === i) on.push(b); });
    const choices = before >= 0 ? [before, ...on] : on;
    const block = choices.length ? choices[Math.min(choices.length - 1, Math.floor(y * choices.length))] : Math.max(0, before);
    BookEditor.reveal(e.file, block);
  }

  /* ——— wiring ——— */
  function wire() {
    const root = C.root;
    root.addEventListener("click", e => {
      const t = e.target;
      const act = t.closest("[data-act]")?.dataset.act;
      if (act === "check") return void runCheck();
      if (act === "recheck") return void runCheck();
      if (act === "export") return exportDialog();
      if (act === "panel") return setPanel(root.classList.contains("nopanel"));
      if (act === "close") return setPanel(false);
      if (act === "design") return showSide("design");
      if (act === "contents") return setContents(root.classList.contains("nocontents"));
      const mode = t.closest("[data-mode]")?.dataset.mode;
      if (mode) return setMode(mode);
      const z = t.closest("[data-zoom]")?.dataset.zoom;
      if (z) return C.viewer.zoomBy(+z);
      if (t.closest(".bc-zl")) return zoomMenu(t.closest(".bc-zl"));
      const entry = t.closest(".bc-contents [data-entry]");
      if (entry) {
        const i = firstPage(+entry.dataset.entry);
        if (i >= 0) { C.viewer.go(i, {smooth: true}); markEntry(+entry.dataset.entry); }
        return;
      }
      const item = t.closest("[data-item]");
      if (item) {
        const it = C.report?.items[+item.dataset.item];
        if (it?.page) {
          C.viewer.go(it.page - 1, {smooth: true});
          C.viewer.mark(it.page - 1);
          $$("[data-item]", C.side_).forEach(b => b.toggleAttribute("aria-current", b === item));
        }
        return;
      }
      const show = t.closest("[data-show]");
      if (show) { const it = C.report?.items[+show.dataset.show]; if (it?.file) BookEditor.reveal(it.file, it.block); return; }
      const sec = t.closest(".bc-st");
      if (sec) {
        const s = sec.closest(".bc-sec"), open = sec.getAttribute("aria-expanded") !== "true", set = openSections();
        sec.setAttribute("aria-expanded", String(open));
        $(".bc-sb", s).hidden = !open;
        if (open) set.add(s.dataset.sec); else set.delete(s.dataset.sec);
        pref.set("compose.sections", JSON.stringify([...set]));
        return;
      }
      const reset = t.closest("[data-reset]");
      if (reset) {
        const s = SECTIONS.find(x => x.id === reset.dataset.reset);
        if (s) { if (C.pending) flush(); post(C, {reset: s.reset}); }
        return;
      }
      const seg = t.closest(".bc-side .seg[data-k] button");
      if (seg && seg.getAttribute("aria-pressed") !== "true") {
        const group = seg.parentElement;
        $$("button", group).forEach(b => b.setAttribute("aria-pressed", String(b === seg)));
        send(nest(group.dataset.k, seg.dataset.v));
      }
    });
    root.addEventListener("change", e => {
      const el = e.target.closest("[data-k]");
      if (el && el.matches("select, input")) changed(el, true);
    });
    root.addEventListener("input", e => {
      const el = e.target.closest("input[data-k]");
      if (el && el.type !== "checkbox") changed(el, false);
    });
    root.addEventListener("keydown", e => {
      if (e.key === "Enter" && e.target.matches?.("input[data-k]")) { e.preventDefault(); changed(e.target, true); if (C.pending) flush(); }
      else if ((e.key === "ArrowUp" || e.key === "ArrowDown") && e.target.matches?.("input[data-num]") && !e.altKey && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        const el = e.target, unit = +el.dataset.step, now = readNum(el.value);
        const from = Number.isFinite(now) ? now : get(shown(), el.dataset.k) ?? +el.dataset.min;
        const to = from + (e.key === "ArrowUp" ? 1 : -1) * unit * (e.shiftKey ? 10 : 1);
        el.value = plainNum(Math.min(+el.dataset.max, Math.max(+el.dataset.min, Math.round(to / unit) * unit)));
        changed(el, false);
      }
    });
  }

  /* zoom keys anywhere in Compose (the browser's own zoom stays out of it); Left and Right go a spread or page on */
  addEventListener("keydown", e => {
    if (!C || state.view !== "book" || state.bookTab !== "compose" || $("#dlg").open) return;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && !e.altKey && (e.key === "=" || e.key === "+")) { e.preventDefault(); C.viewer.zoomBy(1); return; }
    if (mod && !e.altKey && (e.key === "-" || e.key === "_")) { e.preventDefault(); C.viewer.zoomBy(-1); return; }
    if (mod && !e.altKey && e.key === "0") { e.preventDefault(); C.viewer.setZoom("page"); return; }
    if (mod || e.altKey || e.target.closest?.("input, textarea, select, [contenteditable]")) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      const step = C.viewer.mode === "spreads" ? 2 : 1, i = C.viewer.current(), dir = e.key === "ArrowRight" ? 1 : -1;
      let to = i + dir * step;
      if (C.viewer.mode === "spreads") to = dir > 0 ? (i % 2 ? i + 2 : i + 1) : (i % 2 ? i - 1 : i - 2);
      e.preventDefault();
      C.viewer.go(Math.max(0, Math.min((C.pages?.count || 1) - 1, to)));
    }
  });

  return {mount, unmount, refresh, exportPdf, get view() { return C; }};
})();
