"use strict";
/* Books: the shelf, a new book, and a book's pages: the writing window (book-editor.js) and its settings (details, kind
   and features, look, style sheet). A classic script after styles.js.
   Globals: showBooks(), showBook(id, tab?, file?), showBookSettings(id, tab?), newBookDialog(), importBookDialog(),
   showBookImport() (the review screen, #/books/import), bookHash(id, file?),
   refreshBookView() (the poll calls it when the books changed on disk). */

const bookHash = (id, file) => `#/book/${encodeURIComponent(id)}${file ? "/write/" + encodeURIComponent(file) : ""}`;
const bookTabHash = (id, tab) => tab === "write" ? bookHash(id)
  : `#/book/${encodeURIComponent(id)}/settings${tab && tab !== "details" ? "/" + tab : ""}`;

/* The kinds themselves (their features, first pieces and closing pages, in order) come from the store:
   GET /api/books/kinds, read once (bookKindData). This is only the copy on their cards: kind → [name, what it starts with]. */
const BOOK_KIND_COPY = {
  fiction: ["Fiction", "No notes, sources or index. Chapters and scene breaks."],
  memoir: ["Memoir", "Endnotes per chapter. A dedication and a contents page."],
  nonfiction: ["Non-fiction", "Endnotes, sources and an index. An introduction."],
  academic: ["Academic", "Footnotes, sources, an index and numbered figures. An appendix."],
  poetry: ["Poetry", "No notes. An index of first lines. One poem per piece."],
  essays: ["Essays", "Endnotes per essay. A contents page."],
};
let bookKindData = null, bookLists = {pieces: [], forms: [], autos: []};      // the piece kinds, forms and auto pages
async function loadBookKinds() {
  if (!bookKindData) {
    const r = await api("/api/books/kinds");
    bookLists = {pieces: r.pieces || [], forms: r.forms || [], autos: r.autos || []};
    bookKindData = r.kinds;
  }
  return bookKindData;
}
/* Whether an auto page is in the book as shown: the notes, bibliography and index pages only while their feature is on
   (the entry stays in book.json either way). */
const bookAutoOn = (b, a) => a === "notes" ? !!b.features?.notes && b.features.notes !== "off"
  : a === "bibliography" ? b.features?.sources === true : a === "index" ? !!b.features?.index : true;
const BOOK_STATUSES = ["idea", "draft", "revised", "final"];
const BOOK_LANGUAGES = [["nl", "Nederlands"], ["en", "English"], ["de", "Deutsch"], ["fr", "Français"], ["es", "Español"], ["it", "Italiano"]];
const BOOK_PIECE_NAME = {"content-note": "Content note", "about-author": "About the author"};
const BOOK_AUTO_NAME = {"half-title": "Half-title", "title-page": "Title page", "copyright": "Copyright page", "toc": "Contents",
  "notes": "Notes", "bibliography": "Bibliography", "index": "Index"};
/* Front matter runs from the start while entries are of these kinds, back matter from the end; the rest is the body. */
const BOOK_FRONT = new Set(["half-title", "title-page", "copyright", "toc", "dedication", "epigraph", "content-note", "foreword", "preface"]);
const BOOK_BACK = new Set(["afterword", "acknowledgements", "appendix", "about-author", "notes", "bibliography", "index"]);

const bookKindName = k => BOOK_KIND_COPY[k]?.[0] || (k ? k[0].toUpperCase() + k.slice(1) : "Book");
const pieceKindName = k => BOOK_PIECE_NAME[k] || (k ? k[0].toUpperCase() + k.slice(1) : "Piece");
const autoPageName = (b, a) => a === "index" && b.features?.index === "first-lines" ? "Index of first lines" : BOOK_AUTO_NAME[a] || a;
const bookCount = n => (+n || 0).toLocaleString("en-GB");
const bookWords = n => `${bookCount(n)} word${n === 1 ? "" : "s"}`;
const bookDay = b => b.updated ? day(b.updated * 1000) : "";

/* ——— the language: a select of common ones, and any other code ——— */
const bookLanguageHtml = (value, id) => {
  const known = BOOK_LANGUAGES.some(([c]) => c === value);
  return `<div class="bk-langpick"><select class="select" id="${id}">${BOOK_LANGUAGES.map(([c, l]) => `<option value="${c}" ${c === value ? "selected" : ""}>${esc(l)}</option>`).join("")}
      <option value="" ${known ? "" : "selected"}>Other…</option></select>
    <input class="input" id="${id}-code" value="${known ? "" : esc(value)}" placeholder="Code, like pt" aria-label="Language code" maxlength="16" spellcheck="false" autocomplete="off" ${known ? "hidden" : ""}></div>`;
};
/* Shows the code field for Other; returns a function that reads the language chosen. */
function wireBookLanguage(host, id, onChange) {
  const sel = $("#" + id, host), code = $("#" + id + "-code", host);
  sel.addEventListener("change", () => { code.hidden = !!sel.value; if (!sel.value) code.focus(); onChange?.(); });
  return () => {
    const v = sel.value || code.value.trim();
    if (!v) throw new Error("Give the language as a code, like pt or sv.");
    return v;
  };
}

/* A card for every kind the store has, in its order (the cards' own copy while the kinds can't be read). */
const bookKindCards = (current, name) => Object.keys(bookKindData || BOOK_KIND_COPY).map(k => `<label><input type="radio" name="${name}" value="${esc(k)}" ${k === current ? "checked" : ""}>
  <span class="n">${esc(bookKindName(k))}</span><span class="d">${esc(BOOK_KIND_COPY[k]?.[1] || "")}</span></label>`).join("");

/* ——— the shelf ——— */
async function showBooks() {
  state.view = "books"; setNav("books"); document.title = "Books — Studio";
  try { state.shelf = await api("/api/books"); if (state.view === "books") renderShelf(); }
  catch (e) { app.innerHTML = `<p class="empty">Couldn't read the books: ${esc(e.message)}</p>`; }
}

function renderShelf() {
  const list = state.shelf || [];
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker">${plural(list.length, "book")}</p><h1 class="display">Books</h1>
      <p class="lede">Each book is a folder in Books, with one Markdown file for every piece, in the order you give them.</p></div>
      <div class="actions"><button class="btn" type="button" data-importbook>Import book</button><button class="btn solid" type="button" data-newbook><span class="plus">+</span>New book</button></div></header>
    <div class="book-grid">${list.map(bookCard).join("")}<button class="bcard new" type="button" data-newbook><span class="plus">+</span>New book</button></div>`;
  $$("[data-newbook]").forEach(b => b.onclick = () => newBookDialog());
  $("[data-importbook]").onclick = () => importBookDialog();
}

/* A book on the shelf: a typographic cover in the book's look, then its kind, words, last written and its pieces' statuses. */
function bookCard(b) {
  if (b.error) {
    return `<a class="bcard" href="${bookHash(b.id)}" data-book="${esc(b.id)}"><div class="bcover broken"><span class="bt">${esc(b.title)}</span></div>
      <div class="info"><span class="kicker">Can't be read</span><span class="t">${esc(b.title)}</span><span class="bk-err">${esc(b.error)}</span></div></a>`;
  }
  const style = b.style || {}, c = Design.colours(style.palette), f = style.fonts || {};
  return `<a class="bcard" href="${bookHash(b.id)}" data-book="${esc(b.id)}">
    <div class="bcover" style="background:${esc(c.background)};color:${esc(c.text)}">
      <span class="bt" style="${f.display ? esc(faceStyle(f.display)) : ""}">${esc(b.title)}</span>
      ${b.author ? `<span class="ba" style="${f.label ? esc(faceStyle(f.label)) : ""}color:${esc(coverQuiet(c))}">${esc(b.author)}</span>` : ""}</div>
    <div class="info"><span class="kicker">${esc(bookKindName(b.kind))}</span><span class="t">${esc(b.title)}</span>
      <span class="row"><span>${esc(bookWords(b.words))}</span><span>${esc(bookDay(b))}</span></span>${bookStatusBar(b)}</div></a>`;
}

/* The cover's quiet line (the author): the muted role where it reads on the background (3:1, as for large or bold
   type), else the text role. contrastOf is styles.js's, the same rule as the palette warnings. */
const coverQuiet = c => HEX6.test(c.muted) && HEX6.test(c.background) && contrastOf(c.muted, c.background) >= 3 ? c.muted : c.text;

/* The pieces by status as one thin bar, idea to final; pieces without a status (a dedication) are left out. */
function bookStatusBar(b) {
  const parts = BOOK_STATUSES.filter(s => b.by_status?.[s]);
  if (!parts.length) return "";
  const says = parts.map(s => `${b.by_status[s]} ${s}`).join(" · ");
  return `<span class="bk-bar" role="img" aria-label="Pieces: ${esc(says)}" title="${esc(says)}">${parts.map(s => `<i class="bs-${s}" style="flex:${+b.by_status[s]}"></i>`).join("")}</span>`;
}

/* ——— a new book ——— */
async function newBookDialog() {
  let signature = state.home?.signature;
  if (signature == null) { try { signature = (await api("/api/settings")).settings.signature || ""; } catch { signature = ""; } }
  await loadBookKinds().catch(() => null);      // without them the cards use their own list
  const nav = String(navigator.language || "").slice(0, 2).toLowerCase();
  let language = () => "en";
  const form = openDialog(`<form class="nb">
    <h2>New book</h2>
    <label><span class="label">Title</span><input class="input big" name="title" required autocomplete="off" placeholder="Title of the book"></label>
    <div class="nb-two"><label><span class="label">Author</span><input class="input" name="author" value="${esc(signature)}" autocomplete="off" placeholder="Your name"></label>
      <div><label class="label" for="nb-lang">Language</label>${bookLanguageHtml(BOOK_LANGUAGES.some(([c]) => c === nav) ? nav : "en", "nb-lang")}</div></div>
    <div><span class="label">Kind · sets the features it starts with; change it any time in the book's settings</span><div class="pick kinds">${bookKindCards("memoir", "kind")}</div></div>
    <p class="muted" style="margin:0">Studio creates <b>Books/&lt;title&gt;/</b> with a book.json and one Markdown file per piece.</p>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Create book</button></div></form>`,
  async f => {
    const b = await api("/api/books", {title: f.get("title"), author: f.get("author"), language: language(), kind: f.get("kind")});
    state.home = null;
    location.hash = bookHash(b.id);
  });
  language = wireBookLanguage(form, "nb-lang");
}

/* ——— a book: the writing window and its settings ——— */
const BOOK_TABS = [["write", "Write"], ["details", "Details"], ["features", "Kind and features"], ["look", "Look"], ["style", "Style sheet"]];
let bookToken = 0;

/* tab "contents" (the route for #/book/<id> and #/book/<id>/write/<file>) is the writing window */
async function showBook(id, tab = "contents", file = null) {
  const my = ++bookToken;
  state.view = "book"; setNav("books");
  try {
    const [b] = await Promise.all([api("/api/book?b=" + encodeURIComponent(id)), tab === "look" ? loadStyles().catch(() => null) : null,
      loadBookKinds().catch(() => null)]);         // the kinds and the lists of piece kinds and forms the window offers
    if (my !== bookToken || state.view !== "book") return;       // went elsewhere meanwhile
    state.book = b; state.bookTab = tab === "contents" ? "write" : tab; state.bookFile = file;
    if (state.bookTab === "write") BookEditor.mount(app, {book: b, file});
    else renderBook();
  } catch (e) {
    if (my !== bookToken || state.view !== "book") return;
    state.view = "missing";
    app.innerHTML = `<header class="pagehead"><h1 class="display">Not found</h1></header><p class="empty">${esc(e.message)} <a href="#/books">Back to the books</a></p>`;
  }
}
const showBookSettings = (id, tab = "details") => showBook(id, tab);

function renderBook() {
  const b = state.book, tab = state.bookTab;
  document.title = `${b.title} — Studio`;
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker"><a href="#/books">Books</a> · ${esc(bookKindName(b.kind))} · ${esc(bookWords(b.words))}</p>
      <h1 class="display">${esc(b.title)}</h1>
      ${b.subtitle ? `<p class="lede">${esc(b.subtitle)}</p>` : ""}${b.author ? `<p class="byline bk-by">${esc(b.author)}</p>` : ""}</div></header>
    <nav class="tabs bk-tabs" role="tablist">${BOOK_TABS.map(([k, l]) => `<a role="tab" href="${bookTabHash(b.id, k)}" aria-selected="${k === tab}">${esc(l)}</a>`).join("")}</nav>
    <div id="btab"></div>`;
  ({details: paintBookDetails, features: paintBookFeatures, look: paintBookLook, style: paintBookStyleSheet}[tab] || paintBookDetails)($("#btab"));
}

/* Saves fields of book.json (POST /api/book/update) and shows the result; throws for a dialog to report. */
async function saveBook(fields, msg) {
  const r = await api("/api/book/update", {b: state.book.id, fields});
  if (state.view === "book" && state.book?.id === r.id) { state.book = r; renderBook(); }
  if (msg) toast(msg);
  return r;
}

/* The books, or the looks and palettes in Styles/ they draw on, changed on disk (Claude, another window, or this one):
   show them again, keeping what is being typed. */
async function refreshBookView(force = false) {
  if (state.view === "books") {
    const list = await api("/api/books");
    if (state.view === "books" && JSON.stringify(list) !== JSON.stringify(state.shelf)) { state.shelf = list; renderShelf(); }
    return;
  }
  if (state.view !== "book" || !state.book) return;
  const id = state.book.id;
  let b;
  try { b = await api("/api/book?b=" + encodeURIComponent(id)); }
  catch (e) {
    if (e.status === 404 && state.view === "book" && state.book?.id === id) { toast(`${state.book.title} is no longer in Books`, true); state.docDirty = null; location.hash = "#/books"; }
    return;
  }
  if (state.bookTab === "write") { if (state.view === "book" && state.book?.id === id) BookEditor.refresh(b); return; }
  let looksMoved = false;
  if (state.bookTab === "look") {           // the Look tab also shows the library's looks: read them again too
    const before = JSON.stringify(SD);
    await loadStyles().catch(() => null);
    looksMoved = JSON.stringify(SD) !== before;
  }
  if (state.view !== "book" || state.book?.id !== id || (!force && !looksMoved && JSON.stringify(b) === JSON.stringify(state.book))) return;
  state.book = b;
  const typing = app.contains(document.activeElement) && document.activeElement.matches("input, textarea, select");
  if (!state.docDirty && (force || !typing)) renderBook();
}

async function trashBook(id, title) {
  if (!confirm(`Move “${title}” to the trash?\n\nIts folder moves to Books/.trash with its pieces, drafts and editions. Move it back to restore it.`)) return;
  try {
    await api("/api/book/delete", {b: id});
    toast(`Moved “${title}” to the trash`);
    state.home = null;
    if (state.view === "book") { state.docDirty = null; location.hash = "#/books"; } else route();
  } catch (e) { toast(e.message, true); }
}

/* ——— the pieces in three groups: front matter, body, back matter (the binder of the writing window) ——— */
function bookGroups(contents) {
  const kind = e => e.auto || e.kind;
  let a = 0, z = contents.length;
  while (a < z && BOOK_FRONT.has(kind(contents[a]))) a++;
  while (z > a && BOOK_BACK.has(kind(contents[z - 1]))) z--;
  return [["Front matter", contents.slice(0, a)], ["Body", contents.slice(a, z)], ["Back matter", contents.slice(z)]];
}

/* ——— details ——— */
function paintBookDetails(host) {
  const b = state.book, d = b.details || {}, note = !!b.features?.contentNote;
  const field = (name, label, value, attrs = "") => `<label><span class="label">${label}</span><input class="input" name="${name}" value="${esc(value ?? "")}" ${attrs}></label>`;
  host.innerHTML = `<form class="sl sd-details" id="bdt" autocomplete="off">
    <section class="sl-row"><label class="label" for="bd-title">Title</label>
      <div><input class="input big" id="bd-title" name="title" value="${esc(b.title)}" required><p class="hint">The folder stays Books/${esc(b.id)} when the title changes.</p></div></section>
    <section class="sl-row"><label class="label" for="bd-sub">Subtitle</label>
      <div><input class="input" id="bd-sub" name="subtitle" value="${esc(b.subtitle)}"></div></section>
    <section class="sl-row"><label class="label" for="bd-author">Author</label>
      <div><input class="input bk-short" id="bd-author" name="author" value="${esc(b.author)}" placeholder="Your name"><p class="hint">On the title page and the cover.</p></div></section>
    <section class="sl-row"><label class="label" for="bd-lang">Language</label>
      <div>${bookLanguageHtml(b.language, "bd-lang")}<p class="hint">The language the book is written in: for spelling, quote marks and numbers.</p></div></section>
    <section class="sl-row"><span class="label">Publication</span>
      <div><div class="bk-fields">${field("publisher", "Publisher", d.publisher)}${field("edition", "Edition", d.edition, 'placeholder="First edition"')}
        ${field("year", "Year", d.year, 'inputmode="numeric" maxlength="4"')}${field("isbn", "ISBN", d.isbn, 'spellcheck="false"')}</div>
        <p class="hint">On the copyright page.</p></div></section>
    <section class="sl-row"><label class="label" for="bd-copy">Copyright</label>
      <div><input class="input" id="bd-copy" name="copyright" value="${esc(d.copyright)}" placeholder="© ${new Date().getFullYear()} ${esc(b.author || "Your name")}"><p class="hint">The line on the copyright page.</p></div></section>
    ${note ? `<section class="sl-row"><label class="label" for="bd-note">Content note</label>
      <div><textarea class="textarea" id="bd-note" name="contentNote" rows="4" spellcheck="true" placeholder="What the book deals with, for readers who want to know before they start">${esc(d.contentNote)}</textarea>
        <p class="hint">Its own page, before the text.</p></div></section>` : ""}
    <div class="savebar"><button class="btn solid" type="submit">Save details</button><span class="state" id="bd-state"></span></div></form>
    <div class="sl bk-end"><section class="sl-row"><span class="label">Exports</span>
      <div><p class="sl-src sl-first">The whole book, in order. Unsaved details are saved first. A dated copy is also kept in Books/${esc(b.id)}/exports.</p></div>
      <div class="sl-acts">${BOOK_EXPORTS.map(([f, l]) => `<button class="btn small" type="button" data-export="${f}">${l}</button>`).join("")}</div></section></div>
    <div class="sl bk-end bk-end2"><section class="sl-row"><span class="label">Editions</span>
      <div><p class="sl-src sl-first">A dated copy of the whole book, kept in Books/${esc(b.id)}/editions. Nothing changes in the book.</p>
        <ul class="bk-eds" id="bd-eds" aria-live="polite"></ul></div>
      <div class="sl-acts"><button class="btn small" type="button" id="bd-freeze">Freeze edition…</button></div></section></div>
    <div class="sl bk-end bk-end2"><section class="sl-row"><span class="label">Trash</span>
      <div><p class="sl-src sl-first">The book's folder moves to Books/.trash with its pieces, drafts and editions. Move it back to restore it.</p></div>
      <div class="sl-acts"><button class="btn small" type="button" id="bd-trash">Move to trash…</button></div></section></div>`;
  const form = $("#bdt", host), stat = $("#bd-state", host), val = n => form.elements.namedItem(n).value.trim();     // not form.title: that is the form's own attribute
  const mark = () => {
    let dirty;
    try { dirty = JSON.stringify(read(false)) !== JSON.stringify(saved()); } catch { dirty = true; }
    state.docDirty = dirty ? "details" : null; stat.textContent = dirty ? "Unsaved changes · Ctrl+S" : ""; stat.classList.toggle("dirty", dirty);
  };
  const language = wireBookLanguage(form, "bd-lang", mark);
  const details = () => ({publisher: d.publisher ?? "", edition: d.edition ?? "", year: String(d.year ?? ""), isbn: d.isbn ?? "", copyright: d.copyright ?? "",
    ...(note ? {contentNote: d.contentNote ?? ""} : {})});
  const saved = () => ({title: b.title, subtitle: b.subtitle || "", author: b.author || "", language: b.language, details: details()});
  const read = (strict = true) => ({title: val("title"), subtitle: val("subtitle"), author: val("author"),
    language: strict ? language() : ($("#bd-lang", form).value || $("#bd-lang-code", form).value.trim()),
    details: Object.fromEntries(Object.keys(details()).map(k => [k, val(k)]))});
  form.oninput = form.onchange = mark;
  form.onsubmit = async e => {
    e.preventDefault();
    try {
      const fields = read();
      if (!fields.title) throw new Error("Give the book a title.");
      if (fields.details.year && !/^\d{1,4}$/.test(fields.details.year)) throw new Error("The year is a number, like 2026.");
      state.docDirty = null;
      await saveBook(fields, "Saved the details");
    } catch (err) { toast(err.message, true); mark(); }
  };
  $$("[data-export]", host).forEach(btn => btn.onclick = () => exportFromSettings(btn.dataset.export));
  $("#bd-trash", host).onclick = () => trashBook(b.id, b.title);
  $("#bd-freeze", host).onclick = async () => { if (await saveDetailsFirst()) freezeEdition(b.id); };
  paintEditions(b.id);
}

/* ——— editions: dated copies of the whole book ——— */
async function paintEditions(id) {
  const ul = $("#bd-eds");
  if (!ul) return;
  try {
    const list = await api(`/api/book/editions?b=${encodeURIComponent(id)}`);
    if ($("#bd-eds") !== ul || state.book?.id !== id) return;
    ul.innerHTML = list.map(e => `<li><span class="bk-ed-d">${esc(e.date)}</span><span class="bk-ed-n">${esc(e.name)}</span>
      <button class="btn small quiet" type="button" data-show="${esc(`${e.date} ${e.name}`)}" title="Show this edition's folder">Show in folder</button></li>`).join("");
    $$("[data-show]", ul).forEach(btn => btn.onclick = () => api("/api/book/reveal", {b: id, edition: btn.dataset.show}).catch(e => toast(e.message, true)));
  } catch { ul.innerHTML = ""; }
}
function freezeEdition(id) {
  const title = (state.shelf || []).find(b => b.id === id)?.title || (state.book?.id === id ? state.book.title : id);
  openDialog(`<form class="nb">
    <h2>Freeze edition</h2>
    <p class="muted" style="margin:0">An edition is a dated copy of the whole book (its pieces, images, sources and cover) kept in <b>Books/${esc(id)}/editions</b>. Nothing changes in the book; use it to keep a version you sent to someone.</p>
    <label><span class="label">Name</span><input class="input big" name="name" required autocomplete="off" placeholder="First proof"></label>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Freeze edition</button></div></form>`,
  async f => {
    const r = await api("/api/book/edition", {b: id, name: f.get("name")});
    toast(`Froze “${title}” as ${r.name} in Books/${id}/editions`);
    paintEditions(id);
  });
}

const BOOK_EXPORTS = [["docx", "Word (.docx)", "Export as Word (.docx)"], ["md", "Markdown", "Export as Markdown"], ["zip", "Zip", "Export as zip"]];
function exportName(res, fallback) {
  const cd = res.headers.get("Content-Disposition") || "";
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd), ascii = /filename="([^"]*)"/i.exec(cd);
  try { if (star) return decodeURIComponent(star[1]); } catch { /* fall back to the ASCII name */ }
  return ascii ? ascii[1] : fallback;
}
/* The export is a POST (it also writes a dated copy into the book's exports/ folder), fetched so a refusal shows as a
   message; the file is saved under the name the server gives it. */
async function downloadBook(id, format) {
  try {
    const res = await fetch("/api/book/export", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({b: id, format})});
    if (!res.ok) {
      let msg = "";
      try { msg = (await res.json()).error; } catch { /* not JSON */ }
      throw new Error(msg || "The export didn't work.");
    }
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), {href: url, download: exportName(res, `${id}.${format}`)});
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (e) { toast(e.message, true); }
}
/* From the settings: unsaved details are saved first, so an export or an edition holds what is on the screen.
   False when the details were refused (the form says why). */
async function saveDetailsFirst() {
  const form = $("#bdt"), before = state.book;
  if (form && state.docDirty === "details") {
    form.requestSubmit();
    for (let i = 0; i < 50 && state.book === before && !state.docDirty; i++) await new Promise(r => setTimeout(r, 100));
    if (state.book === before) return false;
  }
  return true;
}
async function exportFromSettings(format) {
  if (await saveDetailsFirst()) downloadBook(state.book.id, format);
}

/* ——— kind and features ——— */
const BOOK_FEATURE_NAME = {notes: "Notes", noteNumbering: "Note numbers", sources: "Sources", index: "Index", figures: "Figures", contentNote: "Content note"};
const bookFeatureText = (k, v) => k === "notes" ? {off: "off", footnotes: "footnotes", endnotes: "endnotes", both: "footnotes and endnotes"}[v] || v
  : k === "noteNumbering" ? (v === "book" ? "through the book" : "per chapter")
  : k === "index" ? (v === "first-lines" ? "first lines" : v ? "subject index" : "off") : v ? "on" : "off";

function paintBookFeatures(host) {
  const b = state.book, f = b.features || {}, firstLines = b.kind === "poetry" || f.index === "first-lines";
  const goal = +b.goals?.daily || 0;
  const seg = (key, opts, value) => `<div class="seg" role="group" aria-label="${esc(BOOK_FEATURE_NAME[key])}" data-feature="${key}">${opts.map(([v, l]) =>
    `<button type="button" data-v="${esc(JSON.stringify(v))}" aria-pressed="${v === value}">${esc(l)}</button>`).join("")}</div>`;
  const sw = (key, text) => `<label class="switch"><input type="checkbox" data-feature="${key}" ${f[key] ? "checked" : ""}><span>${esc(text)}</span></label>`;
  host.innerHTML = `<div class="sl bk-features">
    <section class="sl-row"><span class="label">Kind</span>
      <div><div class="pick kinds" role="radiogroup" aria-label="Kind">${bookKindCards(b.kind, "bk-kind")}</div>
        <p class="hint">A kind sets the features a book starts with. Every feature below can be switched on or off whatever the kind.</p></div></section>
    <section class="sl-row"><span class="label">Notes</span>
      <div>${seg("notes", [["off", "Off"], ["footnotes", "Footnotes"], ["endnotes", "Endnotes"], ["both", "Both"]], f.notes || "off")}
        <p class="hint">Footnotes stand on the page, endnotes at the back of the book; both puts every note in both places.</p></div></section>
    ${f.notes && f.notes !== "off" ? `<section class="sl-row"><span class="label">Note numbers</span>
      <div>${seg("noteNumbering", [["chapter", "Per chapter"], ["book", "Through the book"]], f.noteNumbering || "chapter")}
        <p class="hint">Per chapter starts again at 1 in every piece.</p></div></section>` : ""}
    <section class="sl-row"><span class="label">Sources</span><div>${sw("sources", "Citations in the text and a bibliography at the back")}</div></section>
    <section class="sl-row"><span class="label">Index</span>
      <div>${seg("index", [[false, "Off"], [true, "Subject index"], ...(firstLines ? [["first-lines", "First lines"]] : [])], f.index ?? false)}
        <p class="hint">${firstLines ? "A subject index of the terms you mark in the text, or an index of first lines made from the poems." : "An index of the terms you mark in the text."}</p></div></section>
    <section class="sl-row"><span class="label">Figures</span><div>${sw("figures", "Figures and tables numbered through the book")}</div></section>
    <section class="sl-row"><span class="label">Content note</span>
      <div>${sw("contentNote", "A page before the text on what the book deals with")}
        ${f.contentNote ? `<p class="hint">Write it under <a href="${bookTabHash(b.id, "details")}">Details</a>.</p>` : ""}</div></section>
    <section class="sl-row"><label class="label" for="bk-goal">Daily goal</label>
      <div><div class="ck-in"><input class="input" id="bk-goal" type="number" min="0" step="50" value="${goal}"><span class="muted">words a day</span></div>
        <p class="hint">Shown as a quiet line while you write. 0 shows none.</p></div></section></div>`;
  const save = (key, value) => saveBook({features: {[key]: value}}, "Saved").then(() => {
    $(`[data-feature="${key}"] [aria-pressed="true"], input[data-feature="${key}"]`)?.focus();
  }).catch(reportError);
  $$(".seg[data-feature] button", host).forEach(btn => btn.onclick = () => {
    if (btn.getAttribute("aria-pressed") === "true") return;
    save(btn.parentElement.dataset.feature, JSON.parse(btn.dataset.v));
  });
  $$("input[data-feature]", host).forEach(inp => inp.onchange = () => save(inp.dataset.feature, inp.checked));
  $$('input[name="bk-kind"]', host).forEach(r => r.onchange = () => changeBookKind(r.value));
  $("#bk-goal", host).onchange = e => {
    const n = Number(e.target.value);
    if (!Number.isFinite(n) || n < 0) { toast("The daily goal is a number of words, 0 or more.", true); e.target.value = goal; return; }
    saveBook({goals: {daily: Math.round(n)}}, n ? `Daily goal: ${bookCount(Math.round(n))} words` : "No daily goal").catch(reportError);
  };
}

/* The features a kind would change in a book (`want`: the kind's own, from the store; `have`: the book's). Used here and
   by the writing window's palette (book-tools.js). */
const bookKindChanges = (have, want) => Object.keys(want).filter(k => want[k] !== (have[k] ?? (k === "notes" ? "off" : k === "noteNumbering" ? "chapter" : false))
  && !(k === "noteNumbering" && want.notes === "off"));
/* The question when they differ: use the kind's features, or keep the book's (submit: use them; [data-keep]: keep). */
const bookKindQuestion = (b, kind, changes, have, want) => `<form>
    <h2>Change the kind</h2>
    <p class="hint" style="margin-top:-12px">${esc(bookKindName(kind))} books start with other features. Use them for ${esc(b.title)}, or keep the ones it has? The kind becomes ${esc(bookKindName(kind))} either way.</p>
    <ul class="bk-diff">${changes.map(k => `<li><span class="label">${esc(BOOK_FEATURE_NAME[k])}</span><span>${esc(bookFeatureText(k, have[k]))} → <b>${esc(bookFeatureText(k, want[k]))}</b></span></li>`).join("")}</ul>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button>
      <span class="ps-end"><button type="button" class="btn" data-keep>Keep its features</button><button type="submit" class="btn solid" autofocus>Use these features</button></span></div></form>`;

/* Another kind: asks whether its features (from the store's kinds) replace the book's own, when they differ. Whatever
   fails or is cancelled, the cards go back to the kind the book has. */
async function changeBookKind(kind) {
  const b = state.book, label = bookKindName(kind), have = b.features || {};
  const back = e => { if (e) toast(e.message, true); if (state.view === "book" && state.bookTab === "features") renderBook(); };
  let want;
  try { want = (await loadBookKinds())[kind]?.features || {}; } catch (e) { return back(e); }
  if (state.view !== "book" || state.book !== b) return;
  const differ = bookKindChanges(have, want);
  if (!differ.length) return saveBook({kind}, `Kind: ${label}`).catch(back);
  const form = openDialog(bookKindQuestion(b, kind, differ, have, want),
  async () => { await saveBook({kind, apply_kind_defaults: true}, `Kind: ${label}, with its features`); });
  onDialogClose(() => back());       // cancelled, or a save that failed: the cards show the kind the book has
  $("[data-keep]", form).onclick = async () => {
    try { await saveBook({kind}, `Kind: ${label}, features kept`); $("#dlg").close(); } catch (e) { toast(e.message, true); }
  };
}

/* ——— look ——— */
function paintBookLook(host) {
  const b = state.book;
  return paintLook(host, {name: b.title, noun: "book", level: "book", get style() { return state.book.style; }, sample: b.title,
    save: saveBook, refresh: () => refreshBookView(true)});
}

/* ——— style sheet: quote marks, numbers, terms and notes (book.json "style") ——— */
const BOOK_QUOTES = ["“…”", "„…”", "«…»", "‘…’"];
const BOOK_NUMBERS = [["words to ten", "Words to ten"], ["words to hundred", "Words to a hundred"], ["digits", "Digits"]];
/* The style sheet: the reply's `style` is the resolved look, so the store sends book.json's "style" as `style_sheet`,
   every key present and every term {use, not, note}. */
const bookStyleSheet = b => {
  const s = b.style_sheet || {};
  return {quotes: s.quotes || "“…”", numbers: s.numbers || "words to ten", terms: s.terms || [], notes: s.notes || ""};
};

function paintBookStyleSheet(host) {
  const b = state.book, sheet = bookStyleSheet(b);
  const cur = {quotes: sheet.quotes, numbers: sheet.numbers};
  const termRow = t => `<div class="bk-term"><input class="input" data-t="use" value="${esc(t.use)}" aria-label="Use" placeholder="e.g. e-mail">
    <input class="input" data-t="not" value="${esc(t.not.join(", "))}" aria-label="Not" placeholder="email, E-mail">
    <input class="input" data-t="note" value="${esc(t.note)}" aria-label="Note">
    <button type="button" class="btn small quiet" data-rm>Remove</button></div>`;
  host.innerHTML = `<form class="sl sd-details bk-sheet" id="bss" autocomplete="off">
    <section class="sl-row"><span class="label">Quote marks</span>
      <div><div class="seg bk-quotes" role="group" aria-label="Quote marks" data-sheet="quotes">${BOOK_QUOTES.map(q => `<button type="button" data-v="${esc(q)}" aria-pressed="${q === cur.quotes}" aria-label="${esc(q)}">${esc(q.replace("…", "quote"))}</button>`).join("")}</div>
        <p class="hint">Straight quotes in the text are marked while you write.</p></div></section>
    <section class="sl-row"><span class="label">Numbers</span>
      <div><div class="seg" role="group" aria-label="Numbers" data-sheet="numbers">${BOOK_NUMBERS.map(([v, l]) => `<button type="button" data-v="${esc(v)}" aria-pressed="${v === cur.numbers}">${esc(l)}</button>`).join("")}</div>
        <p class="hint">Words to ten: nine, 10. Words to a hundred: ninety-nine, 100. Digits: 9.</p></div></section>
    <section class="sl-row"><span class="label">Terms</span>
      <div><div class="bk-terms" id="bss-terms"><div class="bk-term head" aria-hidden="true"><span class="label">Use</span><span class="label">Not · separated by commas</span><span class="label">Note</span><span></span></div>
        ${sheet.terms.map(termRow).join("")}</div>
        <button type="button" class="btn small" id="bss-add">Add term</button>
        <p class="hint">A word written as one of its Not forms is marked in the text, with the form to use.</p></div></section>
    <section class="sl-row"><label class="label" for="bss-notes">Notes</label>
      <div><textarea class="textarea" id="bss-notes" name="notes" rows="5" spellcheck="true" placeholder="Anything else about how this book is written">${esc(sheet.notes)}</textarea></div></section>
    <div class="savebar"><button class="btn solid" type="submit">Save style sheet</button><span class="state" id="bss-state"></span></div></form>`;
  const form = $("#bss", host), terms = $("#bss-terms", host), stat = $("#bss-state", host);
  const squash = s => s.replace(/\s+/g, " ").trim();      // as the store keeps a word
  const rows = () => $$(".bk-term:not(.head)", terms).map(r => ({row: r, use: squash($("[data-t=use]", r).value),
    not: $("[data-t=not]", r).value.split(",").map(squash).filter(Boolean), note: $("[data-t=note]", r).value.trim()}));
  const read = () => ({quotes: cur.quotes, numbers: cur.numbers,
    terms: rows().filter(t => t.use || t.not.length || t.note).map(({use, not, note}) => ({use, not, note})),
    notes: form.elements.namedItem("notes").value.trim()});
  const saved = JSON.stringify({...sheet, notes: sheet.notes.trim()});
  const mark = () => {
    const dirty = JSON.stringify(read()) !== saved;
    state.docDirty = dirty ? "style sheet" : null; stat.textContent = dirty ? "Unsaved changes · Ctrl+S" : ""; stat.classList.toggle("dirty", dirty);
  };
  $$("[data-sheet] button", host).forEach(btn => btn.onclick = () => {
    const key = btn.parentElement.dataset.sheet;
    cur[key] = btn.dataset.v;
    $$("button", btn.parentElement).forEach(x => x.setAttribute("aria-pressed", x === btn));
    mark();
  });
  $("#bss-add", host).onclick = () => {
    terms.insertAdjacentHTML("beforeend", termRow({use: "", not: [], note: ""}));
    $$(".bk-term:not(.head)", terms).at(-1).querySelector("[data-t=use]").focus();
  };
  terms.addEventListener("click", e => { const rm = e.target.closest("[data-rm]"); if (rm) { rm.closest(".bk-term").remove(); mark(); } });
  form.oninput = mark;
  form.onsubmit = async e => {
    e.preventDefault();
    const missing = rows().find(t => !t.use && (t.not.length || t.note));
    if (missing) { toast("Each term needs the word to use.", true); $("[data-t=use]", missing.row).focus(); return; }
    const sent = read();
    try { state.docDirty = null; await saveBook({style_sheet: sent}, "Saved the style sheet"); }
    catch (err) { toast(err.message, true); mark(); }
  };
}

/* Ctrl+S saves the details or the style sheet. */
addEventListener("keydown", e => {
  if (!((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") || state.view !== "book") return;
  const form = $("#bdt") || $("#bss");
  if (form) { e.preventDefault(); form.requestSubmit(); }
});

/* ——— right-click a book, on the shelf or at Home ——— */
addEventListener("contextmenu", ev => {
  const el = ev.target.closest("[data-book]");
  if (!el || ev.target.closest("input, textarea, [contenteditable]")) return;
  const id = el.dataset.book, title = (state.shelf || []).find(b => b.id === id)?.title || $(".t, .ht", el)?.textContent || id;
  StudioMenu.open(ev, [
    {label: "Open", act: () => { location.hash = bookHash(id); }},
    {label: "Settings", act: () => { location.hash = bookTabHash(id, "details"); }},
    {label: "Freeze edition…", act: () => freezeEdition(id)},
    "-",
    ...BOOK_EXPORTS.map(([f, , l]) => ({label: l, act: () => downloadBook(id, f)})),
    "-",
    {label: "Move to trash…", danger: true, act: () => trashBook(id, title)},
  ]);
});

/* ——— Home: the books, after the series; New → Book ——— */
let homeBooksHtml = "";
function homeBooks(list) {
  if (!list?.length) return "";
  return `<section class="section"><div class="sectionhead"><h2 class="h2">Books</h2><a class="btn quiet" href="#/books">All books →</a></div>
    <ul class="hrows">${list.map(b => `<li><a class="hrow" href="${bookHash(b.id)}" data-book="${esc(b.id)}">
      ${swatchBar(b.style?.palette?.swatches)}<span class="ht">${esc(b.title)}</span>
      <span class="hm">${b.error ? "Can't be read" : [bookKindName(b.kind), bookWords(b.words), bookDay(b)].filter(Boolean).map(esc).join(" · ")}</span></a></li>`).join("")}</ul></section>`;
}
window.homeSections = window.homeSections || [];
window.homeSections.push({
  id: "books",
  render: () => (homeBooksHtml = homeBooks(state.shelf)),        // the shelf as last read; bind reads it again
  bind: async root => {
    try {
      const list = await api("/api/books");
      state.shelf = list;
      const html = homeBooks(list);
      if (html !== homeBooksHtml && root?.isConnected) root.innerHTML = html;
      homeBooksHtml = html;
    } catch { /* Home shows the rest */ }
  },
});
/* ——— importing a book from a .docx or a Markdown file ———
   The file goes to POST /api/book/import, which answers with a proposal and writes nothing. The review screen
   (#/books/import) edits that proposal in memory; Import sends it to /api/book/import/commit. Cancel just drops it. */
const IMPORT_LIMIT = 28 * 1024 * 1024;      // the server takes 40,000,000 bytes of request, and the file travels as base64 (28 MiB is 39.1 MB)
let bookImport = null, bookImportFrom = "#/books", bookImportId = 0;

function importBookDialog() {
  const form = openDialog(`<form class="nb">
    <h2>Import a book</h2>
    <p class="muted" style="margin:0">Choose a Word document (.docx) or a Markdown file. Studio shows what it found, and nothing is written until you have looked it over.</p>
    <label><span class="label">File</span><input class="input" type="file" name="file" accept=".docx,.md,.markdown,.txt" required></label>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Read the file</button></div></form>`,
  async f => {
    const file = f.get("file"), btn = $("button[type=submit]", form);
    if (!file || !file.name) throw new Error("Choose a file first.");
    if (!/\.(docx|md|markdown|txt)$/i.test(file.name)) throw new Error("Studio imports .docx, .md, .markdown and .txt files.");
    if (file.size > IMPORT_LIMIT) throw new Error("That file is too large to import (the limit is about 28 MB).");
    btn.textContent = "Reading…";
    try {
      const p = await api("/api/book/import", {name: file.name, data: await fileBase64(file)});
      const nav = String(navigator.language || "").slice(0, 2).toLowerCase();
      bookImport = {...p, source: file.name, kind: "memoir", language: BOOK_LANGUAGES.some(([c]) => c === nav) ? nav : "en",
        pieces: p.pieces.map(x => ({...x, id: ++bookImportId, retitled: false}))};
      bookImportFrom = location.hash && location.hash !== "#/books/import" ? location.hash : "#/books";
      if (location.hash === "#/books/import") route(); else location.hash = "#/books/import";
    } finally { btn.textContent = "Read the file"; }
  });
}

/* Paragraphs of a piece's Markdown: blocks between blank lines, a `:::` block (epigraph, poem) kept whole. */
function importBlocks(md) {
  const out = [];
  let cur = [], colons = 0;
  for (const line of md.replace(/\r\n?/g, "\n").split("\n")) {
    const t = line.trim();
    if (t.startsWith(":::")) { colons = t === ":::" ? Math.max(0, colons - 1) : colons + 1; cur.push(line); continue; }
    if (!t && !colons) { if (cur.length) out.push(cur.join("\n")); cur = []; continue; }
    cur.push(line);
  }
  if (cur.length) out.push(cur.join("\n"));
  return out;
}
/* Rough plain text of Markdown, for the words shown next to a piece that was merged or split (the server counts for real). */
const importPlain = s => s.replace(/!\[[^\]]*\]\((?:<[^>]*>|[^)]*)\)/g, "").replace(/\^\[[^\]]*\]/g, "").replace(/^:::.*$/gm, "").replace(/^#+ /gm, "").replace(/\[([^\]]*)\]\{[^}]*\}/g, "$1").replace(/\\(.)/g, "$1").replace(/[*_]+/g, "");
const importWords = md => importPlain(md).split(/\s+/).filter(w => /[\p{L}\p{N}]/u.test(w)).length;
function importFirst(md) {
  const body = md.replace(/^# .*\n?/, "").replace(/^::: epigraph\n[\s\S]*?\n:::\n?/, "");
  const words = importPlain(body).split(/\s+/).filter(Boolean);
  return words.slice(0, 12).join(" ") + (words.length > 12 ? " …" : "");
}
const importJoin = blocks => blocks.join("\n\n") + "\n";
const importFresh = piece => ({...piece, first: importFirst(piece.md), words: importWords(piece.md)});

/* The next piece's title becomes a heading inside this one (as edited, when it was): `lines` from its top. */
function importDemote(lines, b) {
  const k = lines.findIndex(l => l.trim()), head = k >= 0 && /^# /.test(lines[k]);
  if (b.retitled) {
    const t = b.title.trim().replace(/\s+/g, " ").replace(/[\\*_\[\]`^]/g, "\\$&");
    if (head) lines.splice(k, 1);
    if (t) lines.splice(Math.max(k, 0), 0, "## " + t);
  } else if (head) lines[k] = "#" + lines[k];
  return lines;
}
/* the line Studio's Markdown export writes before each piece (`<!-- kind: chapter; form: poem -->`) */
const IMPORT_MARK = /^\s*<!--\s*kind:[^>]*-->\s*$/;
function importMerge(i) {
  const [a, b] = bookImport.pieces.slice(i, i + 2);
  const bb = importBlocks(b.md), head = /^# /.test(bb[0] || "");
  bb.splice(0, head ? 1 : 0, ...importDemote(head ? [bb[0]] : [], b));
  const merged = {...a, md: importJoin([...importBlocks(a.md), ...bb]), words: a.words + b.words};
  // the Markdown both came from, one after the other: the form chosen for the merged piece reads it again
  const bs = typeof b.source === "string" ? b.source.replace(/\r\n?/g, "\n").split("\n").filter((l, k) => k || !IMPORT_MARK.test(l)) : null;
  merged.source = typeof a.source === "string" && bs ? a.source.replace(/\s+$/, "") + "\n\n" + importDemote(bs, b).join("\n") : undefined;
  merged.first = a.first || importFirst(merged.md);
  bookImport.pieces.splice(i, 2, merged);
  renderBookImport();
}

function importSplit(i, at) {
  const p = bookImport.pieces[i], blocks = importBlocks(p.md);
  const tail = blocks.slice(at);
  let title = "";
  const h = /^#{2,3} (.*)$/.exec(tail[0]);
  if (h) { tail[0] = "# " + h[1]; title = importPlain(h[1]).trim(); }
  // the halves have no source of their own: the form chosen for them reads the Markdown shown here
  bookImport.pieces.splice(i, 1, importFresh({...p, md: importJoin(blocks.slice(0, at)), source: undefined}),
    importFresh({kind: "chapter", form: p.form, title, md: importJoin(tail), id: ++bookImportId, retitled: false}));
  renderBookImport();
}

function importSplitDialog(i) {
  const blocks = importBlocks(bookImport.pieces[i].md);
  const gist = b => {
    if (/^!\[/.test(b)) return "Image";
    const text = importPlain(b).replace(/\s+/g, " ").trim(), head = /^#{2,3} /.test(b);
    return (head ? "Heading · " : "") + (text.replace(/^#+ /, "").slice(0, 110) || "…") + (text.length > 110 ? "…" : "");
  };
  openDialog(`<form class="nb">
    <h2>Split this piece</h2>
    <p class="muted" style="margin:0">Choose the paragraph where the new piece starts. A heading chosen here becomes the new piece's title.</p>
    <div class="bi-split">${blocks.slice(1).map((b, j) => `<label><input type="radio" name="at" value="${j + 1}" ${j ? "" : "checked"}><span>${esc(gist(b))}</span></label>`).join("")}</div>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Split</button></div></form>`,
  f => importSplit(i, +f.get("at")));
}

function showBookImport() {
  if (!bookImport) { toast("The import was closed. Choose the file again."); location.hash = "#/books"; return; }
  state.view = "bookimport"; setNav("books"); document.title = "Import a book — Studio";
  loadBookKinds().catch(() => null).then(() => { if (state.view === "bookimport" && bookImport) renderBookImport(); });
}

function renderBookImport() {
  const b = bookImport, kinds = Object.keys(bookKindData || BOOK_KIND_COPY), images = Object.keys(b.images || {}).length;
  const opts = (list, cur) => list.map(([v, l]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`).join("");
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker"><a href="#/books">Books</a> · Import</p><h1 class="display">Review the import</h1>
      <p class="lede">What Studio found in ${esc(b.source)}. Nothing is written until you choose Import.</p></div>
      <div class="actions"><button class="btn quiet" type="button" data-cancel>Cancel</button><button class="btn solid" type="button" data-go>Import</button></div></header>
    <div class="bi">
      <div class="bk-fields bi-fields">
        <div class="bi-2"><label class="label" for="bi-title">Title</label><input class="input big" id="bi-title" value="${esc(b.title)}" autocomplete="off">
          ${b.title_cased ? `<p class="hint">The title was in capitals, so it has been set in title case.</p>` : ""}</div>
        <div class="bi-2"><label class="label" for="bi-sub">Subtitle</label><input class="input big" id="bi-sub" value="${esc(b.subtitle)}" autocomplete="off"></div>
        <div class="bi-2"><label class="label" for="bi-author">Author</label><input class="input" id="bi-author" value="${esc(b.author)}" autocomplete="off"></div>
        <div><label class="label" for="bi-kind">Kind</label><select class="select" id="bi-kind">${opts(kinds.map(k => [k, bookKindName(k)]), b.kind)}</select></div>
        <div><label class="label" for="bi-lang">Language</label>${bookLanguageHtml(b.language, "bi-lang")}</div>
      </div>
      ${(b.warnings || []).map(w => `<p class="notice bi-warn">${esc(w)}</p>`).join("")}
      <section class="bi-pieces"><div class="bi-head"><span class="label">${esc(plural(b.pieces.length, "piece"))}</span>
        ${images ? `<span class="hint">${esc(plural(images, "image"))} will come with them.</span>` : ""}</div>
        ${b.pieces.length ? "" : `<p class="empty">Studio found no text in this file.</p>`}
        <ol class="bi-list">${b.pieces.map((p, i) => `<li class="bi-row" data-i="${i}">
          <select class="select" data-k="kind" aria-label="Kind of piece ${i + 1}">${opts((bookLists.pieces.length ? bookLists.pieces : [p.kind]).map(k => [k, pieceKindName(k)]), p.kind)}</select>
          <select class="select" data-k="form" aria-label="Form of piece ${i + 1}">${opts((bookLists.forms.length ? bookLists.forms : [p.form || "prose"]).map(f => [f, f[0].toUpperCase() + f.slice(1)]), p.form || "prose")}</select>
          <input class="input" data-k="title" value="${esc(p.title)}" placeholder="Untitled" aria-label="Title of piece ${i + 1}" autocomplete="off">
          <span class="bi-first">${esc(p.first)}</span><span class="bi-w">${esc(bookWords(p.words))}</span>
          <span class="bi-acts"><button class="btn small quiet" type="button" data-merge ${i === b.pieces.length - 1 ? "disabled" : ""}>Merge with next</button>
            <button class="btn small quiet" type="button" data-split ${importBlocks(p.md).length < 2 ? "disabled" : ""}>Split…</button></span></li>`).join("")}</ol>
      </section></div>`;
  const language = wireBookLanguage(app, "bi-lang", () => { try { b.language = language(); } catch { /* an empty code is reported by Import */ } });
  $("#bi-title").oninput = e => { b.title = e.target.value; };
  $("#bi-sub").oninput = e => { b.subtitle = e.target.value; };
  $("#bi-author").oninput = e => { b.author = e.target.value; };
  $("#bi-kind").onchange = e => { b.kind = e.target.value; };
  $$(".bi-row").forEach(row => {
    const i = +row.dataset.i, p = b.pieces[i];
    $("[data-k=kind]", row).onchange = e => { p.kind = e.target.value; };
    $("[data-k=form]", row).onchange = e => { p.form = e.target.value; };
    $("[data-k=title]", row).oninput = e => { p.title = e.target.value; p.retitled = true; };
    $("[data-merge]", row).onclick = () => importMerge(i);
    $("[data-split]", row).onclick = () => importSplitDialog(i);
  });
  const cancel = $("[data-cancel]"), go = $("[data-go]");
  cancel.onclick = () => { bookImport = null; location.hash = bookImportFrom; };
  go.onclick = async () => {
    try {
      if (!b.title.trim()) { $("#bi-title").focus(); throw new Error("Give the book a title."); }
      b.language = language();
      go.disabled = cancel.disabled = true; go.textContent = "Importing…";
      const made = await api("/api/book/import/commit", {title: b.title, subtitle: b.subtitle, author: b.author, kind: b.kind, language: b.language,
        pieces: b.pieces.map(({kind, form, title, md, source, retitled}) => ({kind, form, title, md, source, retitled})), images: b.images || {}});
      bookImport = null; state.home = null;
      location.hash = bookHash(made.id);
    } catch (e) { toast(e.message, true); go.disabled = cancel.disabled = false; go.textContent = "Import"; }
  };
}

window.newMenuItems = window.newMenuItems || [];
window.newMenuItems.push({label: "Book", act: () => newBookDialog()});
window.newMenuItems.push({label: "Import book", act: () => importBookDialog()});
