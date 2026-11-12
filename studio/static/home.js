"use strict";
/* Home: pick up where you left off, start something, see the series, the books and the latest work.
   Other areas add their own sections, shown after the series: window.homeSections.push({id, render(d) -> html,
   bind?(root, d)}), and entries for the New menu: window.newMenuItems.push({label, act}). */
window.homeSections = window.homeSections || [];

const KIND_LABEL = {poem: "Poem", design: "Design", series: "Series", piece: "Piece", book: "Book"};
/* What Home calls an item: its own label when the source gives one (a piece is "Chapter", "Foreword"), else its kind. */
const itemLabel = i => i.label || KIND_LABEL[i.kind] || i.kind;

function homeContinue(c) {
  if (!c) return "";
  return `<section class="section home-continue" aria-label="Continue">
    <a class="continue" href="${esc(c.href)}">
      <span class="kicker">Continue · ${esc(itemLabel(c))}</span>
      <span class="cq">${c.excerpt ? esc(c.excerpt) : esc(c.title)}</span>
      <span class="cmeta">${esc(c.title)}${c.where ? " · " + esc(c.where) : ""} · ${esc(day(c.when))}</span>
      <span class="btn solid cgo">Continue</span>
    </a></section>`;
}

function homeSeries(d) {
  if (!d.series.length) return "";
  return `<section class="section"><div class="sectionhead"><h2 class="h2">Series</h2><a class="btn quiet" href="#/series">All series →</a></div>
    <ul class="hrows">${d.series.map(s => `<li><a class="hrow" href="${seriesHash(s.name)}" data-series="${esc(s.name)}">
      ${swatchBar(s.palette)}<span class="ht">${esc(s.name)}</span>
      <span class="hm">${s.tagline ? esc(s.tagline) + " · " : ""}${plural(s.poems, "poem")}${s.by_status?.ready ? ` · ${s.by_status.ready} ready for art` : ""}</span></a></li>`).join("")}</ul></section>`;
}

function homeRecent(d) {
  const rows = d.recent || [];
  if (!rows.length) return "";
  const after = (href, prefix) => esc(decodeURIComponent(href.slice(prefix.length)));
  return `<section class="section"><div class="sectionhead"><h2 class="h2">Recent</h2></div>
    <ul class="hrows">${rows.map(i => `<li><a class="hrow" href="${esc(i.href)}"${i.kind === "poem" ? ` data-pid="${after(i.href, "#/poem/")}"` : ""}${
      i.kind === "series" ? ` data-series="${esc(i.title)}"` : ""}${i.kind === "book" ? ` data-book="${after(i.href, "#/book/")}"` : ""}>
      <span class="hk">${esc(itemLabel(i))}</span><span class="ht">${esc(i.title)}</span>
      <span class="hm">${i.where ? esc(i.where) + " · " : ""}${esc(day(i.when))}</span></a></li>`).join("")}</ul></section>`;
}

function renderHomePage() {
  const d = state.home;
  const empty = !d.series.length && !d.poems.length && !(d.recent || []).length;      // recent work spans every area
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker">${d.signature ? esc(d.signature) : "Studio"}</p><h1 class="display">Home</h1></div>
      <div class="actions"><button class="btn" type="button" data-newpoem>New poem</button><button class="btn" type="button" data-newseries>New series</button><button class="btn" type="button" data-newbook>New book</button><button class="btn" type="button" data-importbook>Import book</button></div></header>
    ${homeContinue(d.continue)}
    ${empty ? `<p class="empty">Nothing here yet. Use <b>New</b> to start a poem, a series or a book.</p>` : ""}
    ${homeSeries(d)}
    <div id="home-extra">${(window.homeSections || []).map(s => `<div data-section="${esc(s.id)}">${s.render(d) || ""}</div>`).join("")}</div>
    ${homeRecent(d)}`;
  $("[data-newpoem]").onclick = () => newPoemDialog();
  $("[data-newseries]").onclick = () => newSeriesDialog();
  $("[data-newbook]").onclick = () => newBookDialog();
  $("[data-importbook]").onclick = () => importBookDialog();
  for (const s of window.homeSections || []) s.bind?.($(`[data-section="${s.id}"]`), d);
}

async function showHomePage() {
  state.view = "homepage"; setNav("home"); document.title = "Studio";
  try { const d = await loadHome(); state.stamp = d.stamp; renderHomePage(); }
  catch (e) { app.innerHTML = `<p class="empty">Couldn't read the library: ${esc(e.message)}</p>`; }
}
