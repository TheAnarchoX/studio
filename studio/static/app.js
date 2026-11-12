"use strict";
/* Studio front end: poems, series, and each poem's Write / Art / Design tabs. Plain JS, no build step.
   Everything is read from the files through the API; a quiet 2-second poll picks up Claude's changes. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = $("#app");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
/* a server message inside a sentence of ours: without its closing full stop */
const plain = m => String(m || "").trim().replace(/[.!]+$/, "");
/* a chosen file's bytes as base64, for the JSON the API takes */
const fileBase64 = file => new Promise((ok, no) => {
  const r = new FileReader();
  r.onload = () => ok(String(r.result).split(",")[1] || "");
  r.onerror = () => no(new Error(`${file.name || "That file"} couldn't be read.`));
  r.readAsDataURL(file);
});
const fileUrl = (rel, v) => "/files/" + rel.split("/").map(encodeURIComponent).join("/") + (v ? `?v=${v}` : "");
const stem = rel => rel.split("/").pop().replace(/\.png$/i, "");
const pad = n => n == null ? "" : String(n).padStart(2, "0");
const cls = s => String(s).replace(/\s+/g, "-");
const poemHash = (id, tab) => `#/poem/${encodeURIComponent(id)}${tab ? "/" + tab : ""}`;
const seriesHash = (name, tab) => `#/series/${encodeURIComponent(name)}${tab ? "/" + tab : ""}`;
const STATUSES = ["draft", "ready", "in review", "approved", "exported"];

const pref = {
  get(k, d) { try { return localStorage.getItem("studio." + k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("studio." + k, v); } catch { /* private window */ } },
};

const state = {
  view: null, home: null, series: null, poem: null, stamp: null, tab: "write", seriesTab: "poems",
  filter: "all", query: "", ratio: pref.get("ratio", "45"), signed: pref.get("signed", "1") === "1",
  tools: {hinges: pref.get("hinges", "1") === "1", syllables: pref.get("syllables", "0") === "1"},
  dirty: false, notesDirty: false, openDraft: null, compare: false, savedAt: null, offline: false,
  docDirty: null,   // "rules", "concepts" or "details" while the series' editor has unsaved changes
  art: null,        // the Art tab's slides, brief and notes being edited, and the render or QA that runs (see artFor)
};

async function api(path, body) {
  const opt = body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {};
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({error: r.statusText}));
  if (!r.ok) throw Object.assign(new Error(data.error || r.statusText), {status: r.status, data});   // data: the whole reply
  return data;
}

let toastTimer;
function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast on" + (bad ? " bad" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = "toast" + (bad ? " bad" : ""); }, bad ? 4200 : 2000);
}

const fmtWhen = new Intl.DateTimeFormat("en-GB", {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"});
const fmtDay = new Intl.DateTimeFormat("en-GB", {day: "numeric", month: "short", year: "numeric"});
const when = iso => { const d = new Date(iso); return isNaN(d) ? iso : fmtWhen.format(d); };
const day = iso => { const d = new Date(iso); return isNaN(d) ? "" : fmtDay.format(d); };
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

/* ——— text tools: syllables, hinge words, diff ——— */
function syllables(word) {
  let w = word.toLowerCase().replace(/[^a-z]/g, "");
  if (!w) return 0;
  if (w.length <= 3) return 1;
  w = w.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, "").replace(/^y/, "");
  const m = w.match(/[aeiouy]{1,2}/g);
  return Math.max(1, m ? m.length : 1);
}
const lineSyllables = l => (l.match(/[A-Za-z’']+/g) || []).reduce((n, w) => n + syllables(w), 0);
const STOP = new Set("a an and the of to in on at is it as or by for with be but so if".split(" "));

/* Words that recur, including inside other words (out / outcast, seek / seeker): the poem's hinges. */
function hinges(lines) {
  const toks = [];
  lines.forEach((l, li) => { for (const m of l.matchAll(/[A-Za-z][A-Za-z’']*/g)) toks.push({w: m[0].toLowerCase().replace(/’/g, "'"), li, at: m.index, raw: m[0]}); });
  const roots = [...new Set(toks.map(t => t.w.replace(/'.*$/, "")))].filter(w => w.length >= 2 && !STOP.has(w));
  const found = [];
  for (const r of roots) {
    const occ = [];
    for (const t of toks) {
      const base = t.w.replace(/'.*$/, "");
      if (base === r) occ.push({...t, s: t.at, e: t.at + r.length, whole: true});
      else if (r.length >= 3) { const i = t.w.indexOf(r); if (i >= 0) occ.push({...t, s: t.at + i, e: t.at + i + r.length, whole: false}); }
    }
    if (occ.length >= 2) found.push({root: r, count: occ.length, occ});
  }
  found.sort((a, b) => b.count - a.count || b.root.length - a.root.length);
  return found;
}

function diffTokens(a, b) {
  const n = a.length, m = b.length, dp = Array.from({length: n + 1}, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push(["=", a[i]]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push(["-", a[i++]]);
    else out.push(["+", b[j++]]);
  }
  while (i < n) out.push(["-", a[i++]]);
  while (j < m) out.push(["+", b[j++]]);
  return out;
}
const diffHtml = (from, to) => diffTokens(from.split(/(\s+)/), to.split(/(\s+)/))
  .map(([k, t]) => k === "=" ? esc(t) : !t.trim() ? (k === "+" ? esc(t) : "") : k === "+" ? `<ins>${esc(t)}</ins>` : `<del>${esc(t)}</del>`).join("");

/* ——— markdown (enough for rules, briefs and notes) ——— */
function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?![*\w])/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
}
function md(src) {
  const L = String(src || "").replace(/\r\n/g, "\n").split("\n"), out = [];
  const isList = l => /^\s*([-*]|\d+\.)\s+/.test(l), isTable = l => /^\s*\|/.test(l);
  const cells = r => r.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim());
  for (let i = 0; i < L.length;) {
    const l = L[i];
    let m;
    if (/^```/.test(l)) {
      const buf = []; i++;
      while (i < L.length && !/^```/.test(L[i])) buf.push(L[i++]);
      i++; out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
    } else if ((m = l.match(/^(#{1,6})\s+(.*)$/))) {
      const n = Math.min(3, m[1].length); out.push(`<h${n}>${inline(m[2])}</h${n}>`); i++;
    } else if (isTable(l)) {
      const rows = [];
      while (i < L.length && isTable(L[i])) rows.push(L[i++]);
      const body = rows.filter((r, k) => !(k === 1 && /^[\s|:-]+$/.test(r)));
      out.push(`<table><thead><tr>${cells(body[0]).map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${
        body.slice(1).map(r => `<tr>${cells(r).map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
    } else if (isList(l)) {
      const ordered = /^\s*\d+\./.test(l), items = [];
      while (i < L.length && isList(L[i])) {
        let it = L[i++].replace(/^\s*([-*]|\d+\.)\s+/, "");
        while (i < L.length && /^\s{2,}\S/.test(L[i]) && !isList(L[i])) it += " " + L[i++].trim();
        items.push(`<li>${inline(it)}</li>`);
      }
      out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
    } else if (/^>\s?/.test(l)) {
      const buf = [];
      while (i < L.length && /^>\s?/.test(L[i])) buf.push(L[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${inline(buf.join(" "))}</blockquote>`);
    } else if (/^\s*(---|\*\*\*)\s*$/.test(l)) {
      out.push("<hr>"); i++;
    } else if (!l.trim()) {
      i++;
    } else {
      const buf = [];
      while (i < L.length && L[i].trim() && !/^(#{1,6}\s|```|>)/.test(L[i]) && !isTable(L[i]) && !isList(L[i])) buf.push(L[i++]);
      out.push(`<p>${inline(buf.join(" "))}</p>`);
    }
  }
  return out.join("\n");
}

/* ——— routing ——— */
let lastHash = location.hash, ignoreHash = false;
function setNav(which) { $$("[data-nav]").forEach(a => a.classList.toggle("on", a.dataset.nav === which)); }
function leaveTab() {
  closeViewer();
  if (typeof leaveStyles === "function") leaveStyles();
  flushNotes();
  if (typeof Editor !== "undefined") Editor.unmount();
  if (typeof BookEditor !== "undefined") BookEditor.unmount();      // the open piece is saved as it is left
  document.body.classList.remove("designing", "focus");
  if (window.speechSynthesis) speechSynthesis.cancel();
}
function route() {
  const h = location.hash.slice(1) || "/";
  leaveTab();
  let m;
  if ((m = h.match(/^\/poem\/([^/]+)(?:\/(write|art|design))?$/))) return showPoem(decodeURIComponent(m[1]), m[2] || null);
  if ((m = h.match(/^\/series\/([^/]+)(?:\/(poems|details|look|rules|concepts))?$/))) return showSeries(decodeURIComponent(m[1]), m[2] || "poems");
  if (h === "/series") return showSeriesIndex();
  if (h === "/books") return showBooks();
  if (h === "/books/import") return showBookImport();
  if ((m = h.match(/^\/book\/([^/]+)\/settings(?:\/(features|look|style))?$/))) return showBookSettings(decodeURIComponent(m[1]), m[2] || "details");
  if ((m = h.match(/^\/book\/([^/]+)(?:\/write\/([^/]+))?$/))) return showBook(decodeURIComponent(m[1]), "contents", m[2] ? decodeURIComponent(m[2]) : null);
  if ((m = h.match(/^\/styles(?:\/(looks|palettes|fonts|rules))?$/))) return showStyles(m[1] || "looks");
  if (h === "/settings") return showSettings();
  if (h === "/info") return showInfo();
  if (h === "/poems") return showPoems();
  return showHomePage();
}
addEventListener("hashchange", () => {
  if (ignoreHash) { ignoreHash = false; return; }
  const owner = state.view === "book" ? state.book?.title : state.series?.name;      // whose details, rules or style sheet
  const unsaved = state.dirty ? "The poem has unsaved changes." : state.docDirty
    ? `The ${state.docDirty} of ${owner} ${state.docDirty.endsWith("s") ? "have" : "has"} unsaved changes.` : artUnsaved();
  if (unsaved && !confirm(unsaved + " Leave without saving?")) {
    ignoreHash = true; location.hash = lastHash; return;
  }
  if (artUnsaved()) state.art = null;     // left without saving: the edits go
  state.dirty = false; state.docDirty = null;
  lastHash = location.hash;
  route();
});
addEventListener("beforeunload", e => {
  if (state.dirty || state.docDirty || artUnsaved() || (typeof Editor !== "undefined" && Editor.pending())
      || (typeof BookEditor !== "undefined" && BookEditor.pending())) { e.preventDefault(); e.returnValue = ""; }
});

/* ——— shared pieces ——— */
const swatchBar = pal => `<div class="swatches">${(pal || []).map(c => `<span style="background:${esc(c.hex)}"></span>`).join("")}</div>`;
const palOf = name => (state.home?.series || []).find(s => s.name === name)?.palette || [{hex: "#0C0E11"}, {hex: "#EEEAE2"}, {hex: "#DA291C"}];

function poemCard(p) {
  const {background: bg, text: ink, accent} = Design.colours(palOf(p.series));
  const tab = ["draft", "ready"].includes(p.status) ? "write" : "art";
  const lines = (p.lines || (p.first_line ? [p.first_line] : [])).slice(0, 8);
  const dot = l => l.endsWith(".") ? `${esc(l.slice(0, -1))}<span style="color:${esc(accent)}">.</span>` : esc(l);
  const cover = p.thumb
    ? `<img src="${fileUrl(p.thumb, Date.parse(p.updated) || "")}" alt="" loading="lazy">`
    : `<div class="page" style="background:${esc(bg)};color:${esc(ink)}">${lines.length ? lines.map(l => `<p>${dot(l)}</p>`).join("") : `<p class="none">No text yet</p>`}
        <span class="sig">${esc(state.home?.signature || "")}</span></div>`;
  return `<a class="pcard" href="${poemHash(p.id, tab)}" data-pid="${esc(p.id)}" data-status="${esc(p.status)}"><div class="cover">${cover}</div>
    <div class="info"><span class="kicker">${p.number != null ? "No. " + pad(p.number) + " · " : ""}${esc(p.series)}</span>
      <span class="t">${esc(p.title)}</span>
      <span class="row"><span class="chip ${cls(p.status)}">${esc(p.status)}</span><span class="date">${day(p.updated)}</span></span></div></a>`;
}

function seriesCard(s) {
  const covers = (s.covers || []).slice(0, 4);
  const pal = s.palette || [];
  const cells = [...covers.map(c => `<img src="${fileUrl(c)}" alt="" loading="lazy">`),
    ...pal.slice(0, 4 - covers.length).map(c => `<span style="background:${esc(c.hex)}"></span>`)];
  const counts = STATUSES.filter(k => s.by_status?.[k]).map(k => `${s.by_status[k]} ${k}`);
  return `<a class="scard" href="${seriesHash(s.name)}" data-series="${esc(s.name)}"><div class="mosaic">${cells.join("")}</div>${swatchBar(pal)}
    <div class="body"><span class="name">${esc(s.name)}</span>${s.tagline ? `<span class="tag">${esc(s.tagline)}</span>` : ""}
      <span class="stats"><span>${plural(s.poems, "poem")}</span>${counts.map(c => `<span>${esc(c)}</span>`).join("")}${s.has_kit ? "" : "<span>no carousel kit yet</span>"}</span></div></a>`;
}

/* ——— home: series + poems ——— */
async function loadHome() { const d = await api("/api/home"); state.home = d; return d; }

async function showPoems() {
  state.view = "poems"; setNav("poems"); document.title = "Poems — Studio";
  try { const d = await loadHome(); state.stamp = d.stamp; renderPoems(); }
  catch (e) { app.innerHTML = `<p class="empty">Couldn't read the poems: ${esc(e.message)}</p>`; }
}

function renderPoems() {
  const d = state.home;
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker">${d.signature ? esc(d.signature) + " · " : ""}${plural(d.poems.length, "poem")} in ${plural(d.series.length, "series")}</p>
      <h1 class="display">Poems</h1></div>
      <div class="actions"><a class="btn" href="#/series">Series</a></div></header>
    <section class="section"><div class="sectionhead"><h2 class="h2">Series</h2><a class="btn quiet" href="#/series">All series →</a></div>
      <div class="series-grid">${d.series.map(seriesCard).join("")}
        <button class="scard new" type="button" data-newseries><span class="plus">+</span>New series</button></div></section>
    <section class="section"><div class="sectionhead"><h2 class="h2">All poems</h2>
      <div class="filters"><div class="tabs-mini" role="group" aria-label="Status" id="filters"></div>
        <label class="search"><input type="search" id="q" placeholder="Search titles and lines" aria-label="Search poems" value="${esc(state.query)}"></label></div></div>
      <div class="poem-grid" id="grid"></div></section>`;
  $("[data-newseries]").onclick = () => newSeriesDialog();
  $("#q").oninput = e => { state.query = e.target.value; renderGrid(); };
  renderGrid();
}

function renderGrid() {
  const d = state.home, q = state.query.trim().toLowerCase();
  const counts = {all: d.poems.length};
  d.poems.forEach(p => { counts[p.status] = (counts[p.status] || 0) + 1; });
  $("#filters").innerHTML = ["all", ...STATUSES].filter(k => k === "all" || counts[k])
    .map(k => `<button data-f="${k}" aria-pressed="${state.filter === k}">${k}<b>${counts[k] || 0}</b></button>`).join("");
  $$("[data-f]").forEach(b => b.onclick = () => { state.filter = b.dataset.f; renderGrid(); });
  const list = d.poems.filter(p => (state.filter === "all" || p.status === state.filter)
    && (!q || p.title.toLowerCase().includes(q) || (p.lines || []).join(" ").toLowerCase().includes(q)));
  $("#grid").innerHTML = list.map(poemCard).join("") || `<p class="noresults">${d.poems.length ? "Nothing matches." : "No poems yet. Start one with New, then Poem."}</p>`;
}

/* ——— series ——— */
async function showSeriesIndex() {
  state.view = "seriesIndex"; setNav("poems"); document.title = "Series — Studio";
  try {
    const d = await loadHome(); state.stamp = d.stamp;
    app.innerHTML = `<header class="pagehead"><div><p class="kicker">${plural(d.series.length, "series")}</p><h1 class="display">Series</h1>
        <p class="lede">A series is a body of work with its own look and rules: a palette, two typefaces, a way of turning poems into images.</p></div>
        <div class="actions"><button class="btn solid" data-newseries><span class="plus">+</span>New series</button></div></header>
      <div class="series-grid">${d.series.map(seriesCard).join("")}<button class="scard new" type="button" data-newseries><span class="plus">+</span>New series</button></div>`;
    $$("[data-newseries]").forEach(b => b.onclick = () => newSeriesDialog());
  } catch (e) { app.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}

async function showSeries(name, tab) {
  state.view = "series"; setNav("poems");
  try {
    const [s] = await Promise.all([api("/api/series?name=" + encodeURIComponent(name)), state.home ? null : loadHome(),
      tab === "look" ? loadStyles().catch(() => null) : null]);      // the library's looks, fresh for the Look tab
    state.series = s; state.stamp = s.stamp; state.seriesTab = tab;
    renderSeries();
  } catch (e) { app.innerHTML = `<header class="pagehead"><h1 class="display">Not found</h1></header><p class="empty">${esc(e.message)}</p>`; }
}

function renderSeries() {
  const s = state.series, tab = state.seriesTab;
  document.title = `${s.name} — Studio`;
  const tabs = [["poems", `Poems · ${s.poems.length}`], ["details", "Details"], ["look", "Look"], ["rules", "Rules"], ["concepts", "Concepts"]];
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker"><a href="#/series">Series</a> · ${plural(s.poems.length, "poem")}${s.has_kit ? " · carousel kit" : ""}</p>
      <h1 class="display">${esc(s.name)}</h1>
      <p class="lede editable" contenteditable="plaintext-only" data-field="tagline" spellcheck="true" title="Click to edit">${esc(s.tagline || "Add a tagline")}</p></div>
      <div class="actions"><button class="btn solid" id="newin"><span class="plus">+</span>New poem in ${esc(s.name)}</button></div></header>
    <nav class="tabs" role="tablist">${tabs.map(([k, l]) => `<a role="tab" href="${seriesHash(s.name, k)}" aria-selected="${k === tab}">${esc(l)}</a>`).join("")}</nav>
    <div id="stab"></div>`;
  $("#newin").onclick = () => newPoemDialog(s.name);
  $$("[data-field]").forEach(el => {
    el.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); el.blur(); } };
    el.onblur = async () => {
      const v = el.textContent.trim(), cur = s[el.dataset.field] || "";
      if (v === cur || (!cur && v === "Add a tagline")) return;
      try { state.series = await api("/api/series/update", {name: s.name, fields: {[el.dataset.field]: v}}); state.stamp = state.series.stamp; toast("Saved"); }
      catch (err) { toast(err.message, true); }
    };
  });
  const st = $("#stab");
  if (tab === "poems") {
    st.innerHTML = `${s.description ? `<p class="lede" style="margin:0 0 36px">${esc(s.description)}</p>` : ""}
      <div class="poem-grid">${s.poems.map(poemCard).join("") || `<p class="noresults">No poems in ${esc(s.name)} yet.</p>`}</div>`;
  } else if (tab === "details") paintSeriesDetails(st);
  else if (tab === "look") paintSeriesLook(st);
  else { paintSeriesDoc(st, tab); if (tab === "rules") paintChecks(st); }
}

/* ——— a series' or poem's style: where each value comes from ——— */
const TYPE_ROLES = [["display", "Display", "Titles and large type"], ["text", "Text", "Poems and body text"], ["label", "Label", "Names, captions and small caps"]];
const fontOf = f => ({family: f.family, weight: +f.weight || 400, ...(+f.width && +f.width !== 100 ? {width: +f.width} : {})});
const sameFont = (a, b) => !!a && !!b && stKey(a.family) === stKey(b.family) && +a.weight === +b.weight && (+a.width || 100) === (+b.width || 100);
const faceStyle = f => `font-family:${fontStack(f.family)},var(--serif);font-weight:${+f.weight || 400};${+f.width ? `font-stretch:${+f.width}%;` : ""}`;
const fontText = f => `${f.family} · ${f.weight}${WEIGHT_NAME[f.weight] ? " " + WEIGHT_NAME[f.weight] : ""}${+f.width && +f.width !== 100 ? ` · ${f.width}% wide` : ""}`;
/* For a resolved style ({look, look_from, palette, fonts}): "look" for each value that follows the look in effect,
   else the level that sets it ("global", "series" or "poem"). Needs the library's looks (SD). */
function styleSources(style) {
  const look = style.look ? SD?.looks.find(l => stKey(l.name) === stKey(style.look)) || null : null;
  const via = (v, same) => !!look && v?.from === style.look_from && same;
  return {
    look,
    palette: via(style.palette, style.palette.linked && stKey(style.palette.name) === stKey(look?.palette)) ? "look" : style.palette.from,
    fonts: Object.fromEntries(TYPE_ROLES.map(([r]) => [r, via(style.fonts[r], sameFont(style.fonts[r], look?.fonts[r])) ? "look" : style.fonts[r]?.from])),
  };
}

/* ——— series: details (tagline, description, signature, formats) ——— */
const SERIES_FORMATS = [["1:1", "1:1", "Square, for X"], ["4:5", "4:5", "Portrait, for the Instagram feed"], ["9:16", "9:16", "Tall, for stories"]];
function paintSeriesDetails(st) {
  const s = state.series;
  st.innerHTML = `<form class="sl sd-details" id="sdt" autocomplete="off">
    <section class="sl-row"><label class="label" for="sdt-tag">Tagline</label>
      <div><input class="input big" id="sdt-tag" name="tagline" value="${esc(s.tagline)}" placeholder="One line about the series"><p class="hint">Shown under the series name.</p></div></section>
    <section class="sl-row"><label class="label" for="sdt-desc">Description</label>
      <div><textarea class="textarea" id="sdt-desc" name="description" rows="4" spellcheck="true" placeholder="A few sentences about what the series is">${esc(s.description)}</textarea><p class="hint">Shown above the poems.</p></div></section>
    <section class="sl-row"><label class="label" for="sdt-sig">Signature</label>
      <div><input class="input" id="sdt-sig" name="signature" value="${esc(s.signature)}" placeholder="Your name" style="max-width:360px">
        <p class="hint">The name on this series' signed images. Every image also exists unsigned.</p></div></section>
    <section class="sl-row"><span class="label">Formats</span>
      <div><div class="fmts">${SERIES_FORMATS.map(([k, l, d]) => `<label class="switch"><input type="checkbox" name="formats" value="${k}" ${s.formats.includes(k) ? "checked" : ""}><span><b>${l}</b> · ${esc(d)}</span></label>`).join("")}</div>
        <p class="hint">The sizes this series is made for. At least one.</p></div></section>
    <div class="savebar"><button class="btn solid" type="submit">Save details</button><span class="state" id="sdt-state"></span></div></form>`;
  const form = $("#sdt", st), stat = $("#sdt-state", st);
  const read = () => ({tagline: form.tagline.value.trim(), description: form.description.value.trim(), signature: form.signature.value.trim(),
    formats: $$('[name="formats"]', form).filter(c => c.checked).map(c => c.value)});
  const dirty = () => { const r = read(), c = state.series; return r.tagline !== (c.tagline || "") || r.description !== (c.description || "")
    || r.signature !== (c.signature || "") || r.formats.join() !== c.formats.join(); };
  const mark = () => { const d = dirty(); state.docDirty = d ? "details" : null; stat.textContent = d ? "Unsaved changes" : ""; stat.classList.toggle("dirty", d); };
  form.oninput = form.onchange = mark;
  st.syncDoc = () => { if (!state.docDirty) paintSeriesDetails(st); };      // the file changed on disk: take it in unless typing
  form.onsubmit = async e => {
    e.preventDefault();
    const f = read();
    if (!f.formats.length) { toast("Formats are 1:1, 4:5 and 9:16: keep at least one.", true); return; }
    try {
      const r = await api("/api/series/update", {name: s.name, fields: f});
      state.series = r; state.stamp = r.stamp; state.home = null; state.docDirty = null;
      toast("Saved the details"); renderSeries();
    } catch (err) { toast(err.message, true); }
  };
}

/* ——— a work's look, palette and fonts: the series' Look tab, and the book's ———
   `w` is the work: {name, noun ("series", "book"), level (the level its own values have in its resolved style),
   style (a getter: the resolved style as it is now), sample (the line each font is set in), save(body, msg) (sends
   {look | palette | fonts | detach | link}, shows the result; throws for a dialog to report), refresh() (reads the
   work again after a library palette it follows changed), colours? (a series whose colours the palette editor
   offers), rows? (more rows, after the fonts)}. */
let lookToken = 0;
async function paintLook(st, w) {
  const my = ++lookToken;
  if (!SD) {
    st.innerHTML = `<p class="muted">Loading…</p>`;
    try { await loadStyles(); } catch (e) { st.innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
    if (my !== lookToken || !st.isConnected) return;
  }
  const style = w.style, pal = style.palette, src = styleSources(style), here = w.level;
  /* what the work sets itself on top of its look: "the palette Blood", "its own palette and display font" */
  const andList = xs => xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs.at(-1);
  const ownRoles = TYPE_ROLES.filter(([r]) => src.fonts[r] === here).map(([, l]) => l.toLowerCase());
  const setHere = [];
  if (src.palette === here) setHere.push(pal.linked ? `the palette ${pal.name}` : "its own palette");
  if (ownRoles.length) setHere.push(`${src.palette === here && !pal.linked ? "" : "its own "}${andList(ownRoles)} font${ownRoles.length > 1 ? "s" : ""}`);
  const lookSrc = style.look ? (style.look_from === "global" ? "from Studio's default" : "linked") + (setHere.length ? `, with ${setHere.join(" and ")}` : "")
    : "its own palette and fonts, not linked to a look";
  const palSrc = src.palette === "look" ? `${pal.name} · from the look` : pal.linked ? `${pal.name} · linked` : `Own${pal.name ? ` copy of ${pal.name}` : ""}`;
  const fontSrc = r => src.fonts[r] === "look" ? "from the look" : src.fonts[r] === here ? "own" : `from ${src.fonts[r]}`;
  st.innerHTML = `<div class="sl">
    <section class="sl-row"><span class="label">Look</span>
      <div><p class="sl-val"><b>${esc(style.look || "Own")}</b> · ${esc(lookSrc)}</p></div>
      <div class="sl-acts">${style.look || pal.linked ? `<button class="btn small" type="button" data-sl="detach" title="Copy the palette and fonts into this ${esc(w.noun)}, so changes to the look no longer reach it">Detach</button>` : ""}
        ${setHere.length || !style.look ? `<button class="btn small" type="button" data-sl="link">Link to a look…</button>` : ""}</div></section>
    <section class="sl-row"><span class="label">Palette</span>
      <div><div class="palette">${pal.swatches.map(c => `<button class="sw" type="button" data-hex="${esc(c.hex)}" title="Copy ${esc(c.hex)}"><span class="c" style="background:${esc(c.hex)}"></span><b>${esc(c.name || c.hex)}</b><span>${esc(c.hex)}</span>${c.role ? `<i>${esc(ROLE_LABEL[c.role] || c.role)}</i>` : ""}</button>`).join("")}</div>
        <p class="sl-src">${esc(palSrc)} · click a colour to copy it</p></div>
      <div class="sl-acts"><button class="btn small" type="button" data-sl="editpal">Edit…</button><button class="btn small" type="button" data-sl="pickpal">Choose…</button>
        ${src.palette === here && style.look ? `<button class="btn small quiet" type="button" data-sl="lookpal">Use the look's</button>` : ""}</div></section>
    ${TYPE_ROLES.map(([r, l, what]) => { const f = style.fonts[r]; return f ? `<section class="sl-row"><span class="label">${l}</span>
      <div><p class="sl-spec ${r}" style="${esc(faceStyle(f))}">${esc(w.sample)}</p><p class="sl-src">${esc(fontText(f))} · ${esc(fontSrc(r))} · ${esc(what.toLowerCase())}</p></div>
      <div class="sl-acts"><button class="btn small" type="button" data-font="${r}">Change…</button>
        ${src.fonts[r] === here && src.look?.fonts[r] ? `<button class="btn small quiet" type="button" data-lookfont="${r}">Use the look's</button>` : ""}</div></section>` : ""; }).join("")}
    ${w.rows || ""}
    <section class="sl-looks-sec"><div class="sectionhead"><h2 class="h2">Looks</h2><a class="btn quiet" href="#/styles/looks">Edit looks →</a></div>
      <p class="hint sl-hint">Choose a look for ${esc(w.name)}: its palette and fonts follow the look from then on.</p>
      <div class="sl-looks">${SD.looks.map(lk => { const on = stKey(lk.name) === stKey(style.look) && style.look_from === here;
        return `<button type="button" class="sl-look" data-look="${esc(lk.name)}" aria-pressed="${on}"><span class="th"></span><span class="n">${esc(lk.name)}</span>
          <span class="d">${stKey(lk.name) === stKey(SD.default_look) ? "Studio's default · " : ""}${esc(fontLine(lk.fonts))}</span>${swatchBar(palByName(lk.palette)?.swatches)}</button>`; }).join("")}</div></section></div>`;
  $$("[data-hex]", st).forEach(b => b.onclick = () => { navigator.clipboard?.writeText(b.dataset.hex); toast(`Copied ${b.dataset.hex}`); });
  const act = {
    detach: () => w.save({detach: true}, `${w.name} keeps its own palette and fonts now`).catch(reportError),
    link: () => linkLookDialog(w),
    editpal: () => editOwnPalette(w),
    pickpal: () => pickPalette(w),
    lookpal: () => w.save({palette: null}, `${w.name} uses the palette of ${style.look} again`).catch(reportError),
  };
  $$("[data-sl]", st).forEach(b => b.onclick = () => act[b.dataset.sl]());
  $$("[data-font]", st).forEach(b => b.onclick = () => fontDialog(w, b.dataset.font));
  $$("[data-lookfont]", st).forEach(b => b.onclick = () => {
    const own = ownFonts(w); delete own[b.dataset.lookfont];
    w.save({fonts: Object.keys(own).length ? own : null}, `The ${b.dataset.lookfont} font follows ${style.look} again`).catch(reportError);
  });
  for (const card of $$(".sl-look", st)) {
    const lk = SD.looks.find(l => l.name === card.dataset.look);
    card.onclick = () => useLook(w, lk.name);
    card.addEventListener("contextmenu", ev => StudioMenu.open(ev, [
      {label: `Use for ${w.name}`, disabled: card.getAttribute("aria-pressed") === "true", act: () => useLook(w, lk.name)},
      {label: "Edit look…", act: () => lookEditor(lk)},
    ]));
    drawLook($(".th", card), lk, 144);
  }
}

const reportError = e => toast(e.message, true);
/* The roles the work sets itself (not through its look), as its file keeps them. */
function ownFonts(w) {
  const style = w.style, src = styleSources(style);
  return Object.fromEntries(TYPE_ROLES.filter(([r]) => src.fonts[r] === w.level).map(([r]) => [r, fontOf(style.fonts[r])]));
}
const lookFamilies = w => [...new Set(TYPE_ROLES.map(([r]) => w.style.fonts[r]?.family).filter(Boolean))];

async function useLook(w, name) {
  const style = w.style, src = styleSources(style);
  const own = src.palette === w.level || TYPE_ROLES.some(([r]) => src.fonts[r] === w.level);
  if (stKey(name) === stKey(style.look) && style.look_from === w.level && !own) return;
  if (own && !confirm(`Link ${w.name} to the look ${name}? Its own palette and fonts are replaced by the look's.`)) return;
  await w.save({link: name}, `${w.name} follows ${name}`).catch(reportError);
}

function linkLookDialog(w) {
  const style = w.style;
  let pick = style.look || SD.default_look;
  const form = openDialog(`<form>
    <h2>Link to a look</h2>
    <p class="hint" style="margin-top:-12px">${esc(w.name)} follows the look: its palette and fonts change when the look does. Its own palette and fonts are replaced.</p>
    <div class="pick small sl-pick">${SD.looks.map(lk => `<label><input type="radio" name="look" value="${esc(lk.name)}" ${stKey(lk.name) === stKey(pick) ? "checked" : ""}>
      <span class="n" style="font-size:17px">${esc(lk.name)}</span><span class="d">${esc(fontLine(lk.fonts))}</span>${swatchBar(palByName(lk.palette)?.swatches)}</label>`).join("")}</div>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Link</button></div></form>`,
  async f => { await w.save({link: f.get("look")}, `${w.name} follows ${f.get("look")}`); });
  $("input:checked", form)?.closest("label").scrollIntoView({block: "nearest"});
}

function editOwnPalette(w) {
  const pal = w.style.palette;
  if (pal.linked) {
    const lib = SD.palettes.find(p => stKey(p.name) === stKey(pal.name));
    if (lib) return paletteEditor(lib, {series: w.colours, onSaved: () => w.refresh().catch(reportError)});
  }
  paletteEditor({name: pal.name || "", swatches: pal.swatches}, {series: w.colours, own: {
    title: `Palette of ${w.name}`, note: `${w.name}'s own colours: changing them changes no other ${w.noun}.`,
    save: p => w.save({palette: p.name ? p : p.swatches})}});     // unnamed: a plain list, as Studio 1.0 wrote it
}

function pickPalette(w) {
  const pal = w.style.palette;
  let pick = pal.linked ? pal.name : null;
  const form = openDialog(`<form>
    <h2>Palette of ${esc(w.name)}</h2>
    <p class="hint" style="margin-top:-12px">${pal.linked ? `${esc(w.name)} follows the palette you choose here.` : `${esc(w.name)} follows the palette you choose here, in place of its own colours.`}</p>
    <div id="sp-pick"></div>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Use this palette</button></div></form>`, async () => {
    if (!pick) throw new Error("Choose a palette.");
    await w.save({palette: pick}, `${w.name} uses the palette ${pick}`);
  });
  $("#sp-pick", form).replaceWith(palettePicker(pick, n => { pick = n; }, {series: w.colours}));
}

function fontDialog(w, role) {
  const [, name, what] = TYPE_ROLES.find(([r]) => r === role);
  let pick = fontOf(w.style.fonts[role]);
  const form = openDialog(`<form>
    <h2>${name} font</h2>
    <p class="hint" style="margin-top:-12px">${esc(what)} in ${esc(w.name)}.</p>
    <div id="sf-pick"></div>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Use this font</button></div></form>`, async () => {
    await w.save({fonts: {...ownFonts(w), [role]: pick}}, `Saved the ${role} font of ${w.name}`);
  });
  $("#sf-pick", form).replaceWith(fontPicker(pick, f => { pick = fontOf(f); }, {pinned: lookFamilies(w), pinnedLabel: `Used in this ${w.noun}`}));
}

/* ——— series: look ——— */
function paintSeriesLook(st) {
  const s = state.series;
  return paintLook(st, {name: s.name, noun: "series", level: "series", get style() { return state.series.style; },
    sample: s.poems.find(p => p.first_line)?.first_line || s.name, save: saveSeriesStyle, refresh: refreshSeries, colours: s.name,
    rows: `<section class="sl-row"><span class="label">Formats</span><div><p class="sl-src sl-first">${s.formats.map(esc).join(" · ")} · ${s.signature ? `signed “${esc(s.signature)}” and unsigned` : "with and without a name"}</p></div>
      <div class="sl-acts"><a class="btn small" href="${seriesHash(s.name, "details")}">Edit details</a></div></section>`});
}

/* Saves part of the series' style (POST /api/series/style) and shows the result; throws for the dialog to report. */
async function saveSeriesStyle(body, msg) {
  const s = await api("/api/series/style", {name: state.series.name, ...body});
  state.home = null;
  if (state.view === "series" && state.series?.name === s.name) { state.series = s; state.stamp = s.stamp; renderSeries(); }
  if (msg) toast(msg);
  return s;
}
async function refreshSeries() {
  if (state.view !== "series") return;
  const s = await api("/api/series?name=" + encodeURIComponent(state.series.name));
  state.series = s; state.stamp = s.stamp; state.home = null; renderSeries();
}

/* ——— series: rules and concepts, in Markdown ——— */
const SERIES_DOCS = {
  rules: {label: "Rules", hint: s => `${esc(s.name)}'s rules, in README.md: palette, type, words, what every image does. Claude reads them before making anything for the series, after the <a href="#/styles/rules">house rules</a>.`,
    empty: "Write the series' rules here, in Markdown."},
  concepts: {label: "Concepts", hint: s => `${esc(s.name)}'s visual concepts, in CONCEPTS.md: one per kind of slide, what it shows and why. Claude reads them with the rules.`,
    empty: "Describe the series' visual concepts here, in Markdown."},
};
function paintSeriesDoc(st, which) {
  const s = state.series, doc = SERIES_DOCS[which];
  st.innerHTML = `<p class="hint sd-hint">${doc.hint(s)}</p>
    <div class="st-rules sd"><div><label class="label" for="sd-text">Markdown</label>
      <textarea class="notesin st-rtext" id="sd-text" spellcheck="true" placeholder="${esc(doc.empty)}"></textarea>
      <div class="savebar"><button class="btn solid" type="button" id="sd-save">Save</button><span class="state" id="sd-state"></span></div></div>
      <div><span class="label">Preview</span><div class="doc md" id="sd-prev"></div></div></div>`;
  const text = $("#sd-text", st), prev = $("#sd-prev", st), stat = $("#sd-state", st);
  let saved = s[which] || "";
  text.value = saved;
  const paint = () => {
    prev.innerHTML = text.value.trim() ? md(text.value) : `<p class="muted">Nothing written yet.</p>`;
    const dirty = text.value !== saved;
    state.docDirty = dirty ? doc.label.toLowerCase() : null;
    stat.textContent = dirty ? "Unsaved changes · Ctrl+S" : ""; stat.classList.toggle("dirty", dirty);
  };
  const save = async () => {
    const sent = text.value;      // what's typed while it saves stays unsaved
    try {
      const r = await api("/api/series/update", {name: s.name, fields: {[which]: sent}});
      state.series = r; state.stamp = r.stamp;
      saved = sent; paint(); toast(`Saved the ${doc.label.toLowerCase()}`);
    } catch (e) { toast(e.message, true); }
  };
  text.oninput = paint;
  text.addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); } });
  $("#sd-save", st).onclick = save;
  /* the file changed on disk (the poll): take it in unless there are unsaved changes here */
  st.syncDoc = () => {
    const fresh = state.series[which] || "";
    if (text.value === saved && fresh !== saved) { saved = text.value = fresh; paint(); }
  };
  paint();
}

/* ——— series: design checks (what QA measures against) ——— */
const CHECK_FIELDS = [
  ["align", "Column tolerance", "px", "Edges this close share a column.", 0, 20, 0.5],
  ["near", "Near-miss reach", "px", "An edge this close to a column, but not on it, is flagged. Must be larger than the column tolerance.", 0, 100, 0.5],
  ["phone", "Phone width", "px", "The width text is judged at for legibility.", 200, 1200, 10],
  ["min_phone", "Smallest text at phone width", "px", "Text shorter than this at phone width is flagged.", 1, 40, 0.5],
  ["story_top", "Story zone, top", "px", "9:16: no text in the top of the slide (1080 × 1920). The Design tab's guides follow it.", 0, 600, 1],
  ["story_bottom", "Story zone, bottom", "px", "9:16: no text in the bottom of the slide.", 0, 600, 1],
];
const CHECK_DEFAULTS = {align: 1, near: 10, phone: 430, min_phone: 7, story_top: 280, story_bottom: 330};
function paintChecks(st) {
  const s = state.series, sec = document.createElement("section");
  sec.className = "sd-checks";
  sec.innerHTML = `<h2 class="h2">Design checks</h2>
    <p class="hint sd-hint">What QA measures ${esc(s.name)}'s renders against. Leave a field at its default unless the series needs otherwise; Reset returns it.</p>
    <div class="ck">${CHECK_FIELDS.map(([k, label, unit, hint, lo, hi, step]) => `
      <div class="ck-row"><label class="label" for="ck-${k}">${esc(label)}</label>
        <div class="ck-in"><input class="input" id="ck-${k}" type="number" data-check="${k}" min="${lo}" max="${hi}" step="${step}">
          <span class="muted">${unit} · default ${CHECK_DEFAULTS[k]}</span>
          <button class="btn" type="button" data-reset="${k}">Reset</button></div>
        <p class="hint">${esc(hint)}</p></div>`).join("")}</div>`;
  st.appendChild(sec);
  const put = () => CHECK_FIELDS.forEach(([k]) => {
    const v = state.series.checks?.[k] ?? CHECK_DEFAULTS[k];
    $(`#ck-${k}`, sec).value = v;
    $(`[data-reset="${k}"]`, sec).disabled = v === CHECK_DEFAULTS[k];
  });
  const save = async (k, v) => {
    try {
      const r = await api("/api/series/update", {name: s.name, fields: {checks: {[k]: v}}});
      state.series = r; state.stamp = r.stamp; toast("Saved");
    } catch (e) { toast(e.message, true); }
    put();
  };
  $$("[data-check]", sec).forEach(el => el.onchange = () => {
    const v = el.value.trim() === "" ? null : Number(el.value);
    save(el.dataset.check, v === CHECK_DEFAULTS[el.dataset.check] ? null : v);
  });
  $$("[data-reset]", sec).forEach(b => b.onclick = () => save(b.dataset.reset, null));
  put();
}

/* ——— dialogs ——— */
function openDialog(html, onSubmit) {
  const dlg = $("#dlg");
  dlg.innerHTML = html;
  const form = $("form", dlg);
  $$("[data-close]", dlg).forEach(b => b.onclick = () => dlg.close());
  form.onsubmit = async e => {
    e.preventDefault();
    const btn = $("button[type=submit]", form);
    btn.disabled = true;
    try { await onSubmit(new FormData(form), form); dlg.close(); }
    catch (err) { toast(err.message, true); }
    finally { btn.disabled = false; }
  };
  dlg.showModal();
  $("input", dlg)?.focus();
  return form;
}

const palettePick = (palettes, name = "palette") => `<div class="pick small">${Object.entries(palettes).map(([k, cols], i) =>
  `<label><input type="radio" name="${name}" value="${esc(k)}" ${i ? "" : "checked"}><span class="n" style="font-size:17px">${esc(k)}</span>
    <div class="swatches">${cols.map(([, h]) => `<span style="background:${h}"></span>`).join("")}</div></label>`).join("")}</div>`;
/* The look a new series follows: a card per look in the library (SD, from styles.js), the default look chosen.
   drawLookPick draws the sample slides once the cards are on screen. */
const lookPick = (name = "look") => `<div class="pick looks">${SD.looks.map(l => `<label><input type="radio" name="${name}" value="${esc(l.name)}" ${stKey(l.name) === stKey(SD.default_look) ? "checked" : ""}>
    <span class="slide" aria-hidden="true"></span><span class="n">${esc(l.name)}</span></label>`).join("")}</div>`;
function drawLookPick(host) {
  for (const label of $$(".pick.looks label", host)) {
    const look = SD.looks.find(l => l.name === $("input", label).value), slide = $(".slide", label);
    if (look && !slide.dataset.drawn) { slide.dataset.drawn = "1"; drawLook(slide, look, Math.round(slide.getBoundingClientRect().width) || 116); }
  }
}
/* The library's looks for the New series and New poem dialogs; null when they can't be read (the dialogs then offer palettes). */
const looksForDialog = async () => SD || await loadStyles().catch(() => null);

async function newPoemDialog(preset) {
  const d = state.home || await loadHome(), looks = await looksForDialog();
  const pick = preset || (state.view === "series" && state.series?.name) || d.series[0]?.name || "__new";
  const form = openDialog(`<form>
    <h2>New poem</h2>
    <label><span class="label">Title</span><input class="input big" name="title" required autocomplete="off" placeholder="Title of the poem"></label>
    <div><span class="label">Series</span><div class="pick">${d.series.map(s => `<label><input type="radio" name="series" value="${esc(s.name)}" ${s.name === pick ? "checked" : ""}>
        <span class="n">${esc(s.name)}</span>${s.tagline ? `<span class="d">${esc(s.tagline)}</span>` : ""}${swatchBar(s.palette)}</label>`).join("")}
      <label class="newone"><input type="radio" name="series" value="__new" ${pick === "__new" ? "checked" : ""}><span>+ New series</span></label></div></div>
    <fieldset class="fieldset" id="ns" ${pick === "__new" ? "" : "hidden"}>
      <label><span class="label">Series name</span><input class="input" name="sname" autocomplete="off" placeholder="e.g. Night Letters"></label>
      <label><span class="label">Tagline</span><input class="input" name="stag" autocomplete="off" placeholder="One line on what the series is"></label>
      ${looks ? `<div><span class="label">Look · colours and type, changed any time on the series' Look tab</span>${lookPick()}</div>` : `<div><span class="label">Palette</span>${palettePick(d.palettes)}</div>`}</fieldset>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Create poem</button></div></form>`,
  async f => {
    let series = f.get("series");
    if (series === "__new") {
      const s = await api("/api/series", {name: f.get("sname"), tagline: f.get("stag"), ...(looks ? {look: f.get("look")} : {palette: f.get("palette")})});
      series = s.name;
    }
    const p = await api("/api/poems", {title: f.get("title"), series});
    state.home = null;
    location.hash = poemHash(p.id, "write");
  });
  const showNew = () => { $("#ns", form).hidden = $("input[name=series]:checked", form)?.value !== "__new"; if (looks && !$("#ns", form).hidden) drawLookPick(form); };
  $$("input[name=series]", form).forEach(r => r.onchange = showNew);
  showNew();
}

async function newSeriesDialog() {
  const d = state.home || await loadHome(), looks = await looksForDialog();
  const form = openDialog(`<form>
    <h2>New series</h2>
    <label><span class="label">Name</span><input class="input big" name="name" required autocomplete="off" placeholder="e.g. Night Letters"></label>
    <label><span class="label">Tagline</span><input class="input" name="tagline" autocomplete="off" placeholder="One line on what the series is"></label>
    ${looks ? `<div><span class="label">Look · colours and type, changed any time on the series' Look tab</span>${lookPick()}</div>`
      : `<div><span class="label">Palette · you can change it later on the series' Look tab</span>${palettePick(d.palettes)}</div>`}
    <p class="muted" style="margin:0">Studio creates <b>Poems/&lt;name&gt;/</b> with a series.json and a README for its rules. Ask Claude to build a carousel kit for it when you're ready.</p>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Create series</button></div></form>`,
  async f => {
    const s = await api("/api/series", {name: f.get("name"), tagline: f.get("tagline"), ...(looks ? {look: f.get("look")} : {palette: f.get("palette")})});
    state.home = null;
    location.hash = seriesHash(s.name);
  });
  if (looks) drawLookPick(form);
}
$("#new").onclick = ev => {
  const r = ev.currentTarget.getBoundingClientRect();
  StudioMenu.open({preventDefault() {}, stopPropagation() {}, clientX: r.left, clientY: r.bottom + 4},
    [{label: "Poem", act: () => newPoemDialog()}, {label: "Series", act: () => newSeriesDialog()}, ...(window.newMenuItems || [])]);
};

/* ——— poem ——— */
const NO_AUTHOR = "Add author";

async function showPoem(id, tab) {
  state.view = "poem"; setNav("poems");
  try {
    const p = await api("/api/poem?id=" + encodeURIComponent(id));
    const fresh = !state.poem || state.poem.id !== p.id;
    state.poem = p; state.stamp = p.stamp;
    if (fresh) Object.assign(state, {dirty: false, notesDirty: false, openDraft: null, compare: false, savedAt: null, art: null});
    state.tab = tab || (["draft", "ready"].includes(p.status) ? "write" : "art");
    renderPoem();
  } catch (e) {
    state.view = "missing";
    app.innerHTML = `<header class="pagehead"><h1 class="display">Not found</h1></header><p class="empty">${esc(e.message)} <a href="#/poems">Back to the poems</a></p>`;
  }
}

function renderPoem() {
  app.innerHTML = `<header class="poemhead"><div class="kicker" id="pkicker"></div>
      <div class="titlerow"><h1 class="display" id="ptitle"></h1>
        <div class="titleside"><ol class="steps" id="steps" aria-label="Status"></ol>
          <div class="pmenu"><button class="btn quiet small" id="pmore" aria-haspopup="true" title="More">•••</button>
            <div class="pop" id="ppop" hidden><button class="item" id="pstyle">Style…</button><div class="sep" role="separator"></div><button id="pdel">Move to trash…</button></div></div></div></div>
      <p class="byline editable" id="pauthor" contenteditable="plaintext-only" spellcheck="false" title="Click to edit the author"></p>
      <nav class="tabs" role="tablist">${[["write", "Write"], ["art", "Art"], ["design", "Design"]].map(([k, l]) =>
        `<button role="tab" data-tab="${k}">${l}</button>`).join("")}</nav></header>
    <div id="tab"></div>`;
  $("#pmore").onclick = ev => { ev.stopPropagation(); $("#ppop").hidden = !$("#ppop").hidden; };
  $("#pstyle").onclick = () => { $("#ppop").hidden = true; poemStyleDialog(); };
  $("#pdel").onclick = deletePoem;
  const au = $("#pauthor");
  au.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); au.blur(); } else if (e.key === "Escape") { au.textContent = state.poem.author || NO_AUTHOR; au.blur(); } };
  au.onfocus = () => { if (!state.poem.author) au.textContent = ""; };
  au.onblur = async () => {
    const p = state.poem, v = au.textContent.trim().replace(/\s+/g, " ");
    if (v === (p.author || "") || (!p.author && !v)) { au.textContent = p.author || NO_AUTHOR; return; }
    try {
      const np = await api("/api/poem/details", {id: p.id, author: v});
      if (state.poem === p) { state.poem = {...p, author: np.author, stamp: np.stamp}; state.stamp = np.stamp; }
      toast("Saved");
    } catch (err) { toast(err.message, true); }
    if (state.poem) renderHeader();
  };
  $$("[data-tab]").forEach(b => b.onclick = () => {
    if (state.tab === b.dataset.tab) return;
    leaveTab();
    state.tab = b.dataset.tab;
    history.replaceState(null, "", poemHash(state.poem.id, state.tab));
    lastHash = location.hash;
    renderHeader(); renderTab();
  });
  renderHeader();
  renderTab();
}

function renderHeader() {
  const p = state.poem, at = STATUSES.indexOf(p.status);
  document.title = `${p.title} — Studio`;
  $("#ptitle").textContent = p.title;
  const au = $("#pauthor");
  if (au && document.activeElement !== au) { au.textContent = p.author || NO_AUTHOR; au.classList.toggle("empty", !p.author); }
  $("#pkicker").innerHTML = `<a href="${seriesHash(p.series)}">${esc(p.series)}</a>${p.number != null ? `<span>No. ${pad(p.number)}</span>` : ""}<span>${plural(p.lines.length, "line")}</span>`;
  $("#steps").innerHTML = STATUSES.map((s, i) => `<li class="${i < at ? "done" : i === at ? "cur" : ""}"><button data-status="${s}" title="Set status: ${s}">${s}</button></li>`).join("");
  $$("[data-status]").forEach(b => b.onclick = () => setStatus(b.dataset.status));
  $$("[data-tab]").forEach(b => b.setAttribute("aria-selected", b.dataset.tab === state.tab));
}

async function deletePoem() {
  const p = state.poem;
  $("#ppop").hidden = true;
  if (!confirm(`Move “${p.title}” to the trash?\n\nIts folder moves to Poems/.trash/${p.series}/ with its drafts, notes and artwork. Move it back to restore it.`)) return;
  try {
    await api("/api/poem/delete", {id: p.id});
    state.dirty = false; state.poem = null; state.home = null;
    toast(`Moved “${p.title}” to the trash`);
    location.hash = "#/poems";
  } catch (e) { toast(e.message, true); }
}
addEventListener("click", e => { const pop = $("#ppop"); if (pop && !pop.hidden && !e.target.closest(".pmenu")) pop.hidden = true; });

/* The poem's own look, palette and fonts (poem.json), each switched on or left to follow the series. */
async function poemStyleDialog() {
  const p = state.poem;
  if (!p?.style) return;
  try { await loadStyles(); } catch (e) { return toast(e.message, true); }
  if (state.poem !== p) return;
  const st = p.style, src = styleSources(st), si = p.series_info || {};
  const ownPal = src.palette === "poem" && !st.palette.linked ? st.palette : null;
  const c = {look: st.look_from === "poem" ? st.look : "",
    palOn: src.palette === "poem", pal: src.palette === "poem" ? (ownPal ? "" : st.palette.name) : null,   // "": its own colours
    fonts: Object.fromEntries(TYPE_ROLES.filter(([r]) => src.fonts[r] === "poem").map(([r]) => [r, fontOf(st.fonts[r])]))};
  const had = !!(c.look || c.palOn || Object.keys(c.fonts).length);
  /* What the poem gets where it doesn't choose: the look chosen here, else the series. */
  const inherited = () => {
    const lk = c.look && SD.looks.find(l => stKey(l.name) === stKey(c.look));
    if (lk) return {from: `the look ${lk.name}`, name: lk.palette, swatches: palByName(lk.palette)?.swatches || si.palette || [], fonts: lk.fonts};
    return {from: p.series, name: st.palette.from !== "poem" && st.palette.linked ? st.palette.name : null, swatches: si.palette || [], fonts: si.font_roles || {}};
  };
  const pinned = (si.fonts || []).map(f => f.family);
  const sw = on => `<label class="switch"><input type="checkbox" ${on ? "checked" : ""}><span>Choose for this poem</span></label>`;
  const form = openDialog(`<form class="ps">
    <h2>Style</h2>
    <p class="hint ps-lede">“${esc(p.title)}” follows ${esc(p.series)} except where you choose otherwise here. Nothing else changes.</p>
    <label class="ps-look"><span class="label">Look</span><select class="select" id="ps-look">
      <option value="">As the series${si.look ? ` · ${esc(si.look)}` : ""}</option>${SD.looks.map(l => `<option value="${esc(l.name)}" ${stKey(l.name) === stKey(c.look) ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select></label>
    <section class="ps-item" data-what="palette"></section>
    ${TYPE_ROLES.map(([r]) => `<section class="ps-item" data-what="${r}"></section>`).join("")}
    <div class="foot"><button type="button" class="btn quiet" id="ps-clear" ${had ? "" : "disabled"}>Use the series' style</button>
      <span class="ps-end"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Save</button></span></div></form>`, async () => {
    const body = {id: p.id, look: c.look || null, fonts: Object.keys(c.fonts).length ? c.fonts : null};
    if (!c.palOn) body.palette = null;
    else if (c.pal) body.palette = c.pal;
    else if (c.pal !== "" || !ownPal) throw new Error("Choose a palette for this poem, or switch it off.");
    applyFresh(await api("/api/poem/style", body));
    toast("Saved the poem's style");
  });
  $("#dlg").classList.add("wide");
  onDialogClose(() => $("#dlg").classList.remove("wide"));
  const paintPal = () => {
    const el = $("[data-what=palette]", form), inh = inherited();
    el.innerHTML = `<div class="ps-head"><span class="label">Palette</span>${sw(c.palOn)}</div><div class="ps-body"></div>`;
    const body = $(".ps-body", el);
    if (!c.palOn) body.innerHTML = `${stripHtml(inh.swatches, false)}<p class="hint">${esc(inh.name ? `${inh.name} · from ${inh.from}` : `From ${inh.from}`)}</p>`;
    else {
      if (ownPal) body.insertAdjacentHTML("beforeend", `<div class="pick small ps-own"><label><input type="radio" name="ps-own" ${c.pal === "" ? "checked" : ""}>
        <span class="n" style="font-size:17px">Its own colours</span>${stripHtml(ownPal.swatches, false)}</label></div>`);
      const picker = palettePicker(c.pal || null, n => { c.pal = n; const o = $("[name=ps-own]", body); if (o) o.checked = false; }, {series: p.series});
      body.append(picker);
      const o = $("[name=ps-own]", body);
      if (o) o.onchange = () => { c.pal = ""; $$("input", picker).forEach(i => { i.checked = false; }); };
    }
    $(".ps-head input", el).onchange = e => { c.palOn = e.target.checked; c.pal = c.palOn ? (ownPal ? "" : inh.name) : null; paintPal(); };
  };
  const paintFont = r => {
    const el = $(`[data-what=${r}]`, form), [, name, what] = TYPE_ROLES.find(x => x[0] === r), inh = inherited().fonts[r];
    el.innerHTML = `<div class="ps-head"><span class="label">${name} font</span>${sw(!!c.fonts[r])}</div><div class="ps-body"></div>`;
    const body = $(".ps-body", el);
    if (c.fonts[r]) body.append(fontPicker(c.fonts[r], f => { c.fonts[r] = fontOf(f); }, {pinned}));
    else body.innerHTML = inh ? `<p class="ps-spec" style="${esc(faceStyle(inh))}">${esc(fontText(inh))}</p><p class="hint">${esc(what)} · from ${esc(inherited().from)}</p>`
      : `<p class="hint">${esc(what)} · not set</p>`;
    $(".ps-head input", el).onchange = e => {
      if (e.target.checked) c.fonts[r] = fontOf(inh || {family: "Newsreader", weight: 400}); else delete c.fonts[r];
      paintFont(r);
    };
  };
  $("#ps-look", form).onchange = e => { c.look = e.target.value; if (!c.palOn) paintPal(); TYPE_ROLES.forEach(([r]) => { if (!c.fonts[r]) paintFont(r); }); };
  $("#ps-clear", form).onclick = async () => {
    try { applyFresh(await api("/api/poem/style", {id: p.id, clear: true})); $("#dlg").close(); toast(`The poem follows ${p.series} again`); }
    catch (e) { toast(e.message, true); }
  };
  paintPal(); TYPE_ROLES.forEach(([r]) => paintFont(r));
}

async function setStatus(status) {
  const p = state.poem;
  if (status === p.status) return;
  if (STATUSES.indexOf(status) < STATUSES.indexOf(p.status) && STATUSES.indexOf(p.status) >= 2
      && !confirm(`This poem is ${p.status}. Move it back to ${status}?`)) return;
  try {
    if (status === "ready" && state.dirty) await saveText(true);
    applyFresh(await api("/api/status", {id: p.id, status}));
    toast(status === "ready" ? "Ready for art" : `Status: ${status}`);
  } catch (e) { toast(e.message, true); }
}

function renderTab() {
  document.body.classList.toggle("designing", state.tab === "design");
  if (state.tab === "art") return renderArt();
  if (state.tab === "design") {
    const imp = state.importSlide; state.importSlide = null;
    return Editor.mount($("#tab"), {poem: state.poem, api, toast, md, back: poemHash(state.poem.id, state.lastTab || "write"), importSlide: imp,
      refresh: applyFresh, editStyle: poemStyleDialog});
  }
  state.lastTab = state.tab;
  renderWrite();
}

/* ——— write ——— */
function renderWrite() {
  const p = state.poem, t = state.tools;
  $("#tab").innerHTML = `<div class="write">
    <div class="desk">
      <div class="desktools" role="toolbar" aria-label="Writing tools">
        <button class="tool" data-tool="hinges" aria-pressed="${t.hinges}" title="Underline words that recur, also inside other words">Hinge words</button>
        <button class="tool" data-tool="syllables" aria-pressed="${t.syllables}" title="Syllables at the end of each line">Syllables</button>
        <button class="tool" id="speak" aria-pressed="false" title="Read the poem aloud">Read aloud</button>
        <button class="tool" id="focus" aria-pressed="false" title="Only the page (Esc to leave)">Focus</button>
        <span class="counts" id="counts"></span>
      </div>
      <div class="sheet">
        <input class="titlein" id="title" aria-label="Title" autocomplete="off" spellcheck="true">
        <div class="ed-wrap"><div class="backdrop" id="backdrop" aria-hidden="true"></div>
          <textarea id="text" aria-label="The poem" spellcheck="true" placeholder="Write the poem here, one line per line."></textarea></div>
      </div>
      <div class="savebar"><button class="btn solid" id="save">Save draft</button><span class="state" id="state"></span>
        <span class="spacer" style="flex:1"></span><span id="readybox"></span></div>
    </div>
    <aside class="side">
      <section class="panel"><span class="label">Mechanics</span><div id="mech"></div></section>
      <section class="panel"><span class="label">Rhythm · syllables per line</span><div class="rhythm" id="rhythm"></div></section>
      <section class="panel"><span class="label">Drafts</span><div id="drafts"></div></section>
      <section class="panel"><label class="label" for="notes">Writing notes</label>
        <textarea class="notesin" id="notes" placeholder="What the poem is for, lines you cut, thoughts on the art…"></textarea>
        <span class="state" id="nstate"></span></section>
    </aside></div>`;
  const title = $("#title"), text = $("#text"), notes = $("#notes");
  title.value = p.title; text.value = p.lines.join("\n"); notes.value = p.writing_notes || "";
  const dirty = () => { state.dirty = true; updateState(); };
  title.oninput = dirty;
  text.oninput = () => { analyse(); dirty(); };
  $("#save").onclick = () => saveText().catch(() => {});
  $$("[data-tool]").forEach(b => b.onclick = () => {
    const k = b.dataset.tool; t[k] = !t[k]; pref.set(k, t[k] ? "1" : "0");
    b.setAttribute("aria-pressed", t[k]); analyse();
  });
  $("#speak").onclick = speak;
  $("#focus").onclick = () => setFocus(!document.body.classList.contains("focus"));
  let timer;
  notes.oninput = () => { state.notesDirty = true; $("#nstate").textContent = ""; clearTimeout(timer); timer = setTimeout(flushNotes, 1200); };
  notes.onblur = flushNotes;
  analyse(); renderDrafts(); updateState(); renderReady();
}

function setFocus(on) {
  document.body.classList.toggle("focus", on);
  $("#focus")?.setAttribute("aria-pressed", on);
  if (on) $("#text")?.focus();
  requestAnimationFrame(analyse);
}

function speak() {
  const b = $("#speak");
  if (!window.speechSynthesis) return toast("This browser can't read aloud", true);
  if (speechSynthesis.speaking) { speechSynthesis.cancel(); b.setAttribute("aria-pressed", "false"); return; }
  const lines = $("#text").value.split("\n").filter(l => l.trim());
  if (!lines.length) return;
  b.setAttribute("aria-pressed", "true");
  const voice = speechSynthesis.getVoices().find(v => /en-GB/i.test(v.lang)) || speechSynthesis.getVoices().find(v => /^en/i.test(v.lang));
  lines.forEach((l, i) => {
    const u = new SpeechSynthesisUtterance(l);
    if (voice) u.voice = voice;
    u.rate = .86; u.pitch = .95;
    if (i === lines.length - 1) u.onend = () => b.setAttribute("aria-pressed", "false");
    speechSynthesis.speak(u);
  });
}

/* live analysis: hinge words, syllables, counts, rhythm */
function analyse() {
  const ta = $("#text");
  if (!ta) return;
  const lines = ta.value.split("\n"), t = state.tools, hs = hinges(lines);
  const marks = lines.map(() => []);
  hs.slice(0, 4).forEach((h, k) => h.occ.forEach(o => {
    const row = marks[o.li];
    if (!row.some(m => o.s < m.e && m.s < o.e)) row.push({s: o.s, e: o.e, k: k + 1});
  }));
  $("#backdrop").innerHTML = lines.map((l, i) => {
    let html = "", at = 0;
    if (t.hinges) for (const m of marks[i].sort((a, b) => a.s - b.s)) { html += esc(l.slice(at, m.s)) + `<mark class="h${m.k}">${esc(l.slice(m.s, m.e))}</mark>`; at = m.e; }
    html += esc(l.slice(at));
    if (t.syllables && l.trim()) html += `<span class="syl" data-n="${lineSyllables(l)}"></span>`;
    return html;
  }).join("\n") + "\n ";
  ta.style.height = "auto";
  ta.style.height = Math.max(360, ta.scrollHeight) + "px";
  const words = (ta.value.match(/[A-Za-z0-9’']+/g) || []).length, filled = lines.filter(l => l.trim());
  const syl = filled.reduce((n, l) => n + lineSyllables(l), 0);
  $("#counts").innerHTML = `<span><b>${words}</b> words</span><span><b>${filled.length}</b> lines</span><span><b>${syl}</b> syllables</span>`;
  const colours = ["var(--red)", "var(--paper-dim)", "var(--fog)", "color-mix(in srgb, var(--red) 50%, transparent)"];
  $("#mech").innerHTML = hs.length ? `<ul class="mech">${hs.slice(0, 6).map((h, k) => {
    const where = [...new Set(h.occ.map(o => o.whole ? lines[o.li].trim() : o.raw))];
    return `<li><span class="w">${k < 4 ? `<span class="k" style="background:${colours[k]}"></span>` : ""}${esc(h.root)}</span><span class="x">×${h.count}</span>
      <span class="in">${where.map(esc).join(" · ")}</span></li>`;
  }).join("")}</ul>` : `<p class="muted" style="margin:0">No word recurs yet. Repeated words, also inside other words (out / outcast), show up here: they're where concepts come from.</p>`;
  const max = Math.max(1, ...filled.map(lineSyllables));
  $("#rhythm").innerHTML = filled.length ? filled.map(l => { const n = lineSyllables(l);
    return `<div><span>${esc(l.trim())}</span><i style="width:${Math.round(n / max * 92)}px"></i><b>${n}</b></div>`; }).join("") : `<p class="muted" style="margin:0">Nothing yet.</p>`;
}

function updateState() {
  const s = $("#state");
  if (!s) return;
  s.className = "state" + (state.dirty ? " dirty" : "");
  s.textContent = state.dirty ? "Unsaved changes · Ctrl+S"
    : state.savedAt ? `Saved ${fmtWhen.format(state.savedAt).split(", ").pop()}` : (state.poem.drafts.length ? "" : "Not saved yet");
}

function renderReady() {
  const box = $("#readybox"), p = state.poem;
  if (!box) return;
  box.innerHTML = p.status === "draft"
    ? `<button class="btn red" id="mkready" title="Mark the poem ready for Claude to make the art">Ready for art</button>`
    : p.status === "ready" ? `<span class="muted" style="font-size:13px">Ready. Make the carousel in the Art tab, or ask Claude: “make the carousel for ${esc(p.title)}”</span> <button class="btn quiet small" id="unready">Back to draft</button>` : "";
  $("#mkready") && ($("#mkready").onclick = () => setStatus("ready"));
  $("#unready") && ($("#unready").onclick = () => setStatus("draft"));
}

async function saveText(quiet = false) {
  const title = $("#title")?.value.trim(), text = $("#text")?.value ?? "";
  if (!title) { toast("Give the poem a title", true); throw new Error("no title"); }
  try {
    const fresh = await api("/api/text", {id: state.poem.id, title, text});
    state.dirty = false; state.savedAt = new Date();
    applyFresh(fresh);
    if (!quiet) toast("Draft saved");
  } catch (e) { toast(e.message, true); throw e; }
}

async function flushNotes() {
  if (!state.notesDirty || !state.poem) return;
  const el = $("#notes");
  if (!el) return;
  state.notesDirty = false;
  try {
    const fresh = await api("/api/notes", {id: state.poem.id, text: el.value});
    state.poem.writing_notes = fresh.writing_notes; state.stamp = fresh.stamp;
    const s = $("#nstate"); if (s) s.textContent = "Saved";
  } catch (e) { state.notesDirty = true; toast(e.message, true); }
}

function renderDrafts() {
  const p = state.poem, el = $("#drafts");
  if (!el) return;
  if (!p.drafts.length) { el.innerHTML = `<p class="muted" style="margin:0">No drafts yet. Each save keeps a dated version here.</p>`; return; }
  const cur = p.lines.join("\n"), editor = $("#text")?.value ?? cur;
  el.innerHTML = `<ol class="timeline">${p.drafts.map((d, i) => {
    const text = d.lines.join("\n"), isCur = i === 0 && text === cur && (d.title || p.title) === p.title, open = state.openDraft === d.name;
    const body = open && state.compare ? `<pre>${diffHtml(text, editor)}</pre>` : `<pre>${esc(text)}</pre>`;
    return `<li class="${isCur ? "cur" : ""} ${open ? "open" : ""}" data-draft="${esc(d.name)}">
      <button class="head" data-d="${esc(d.name)}" aria-expanded="${open}"><span class="when">${esc(when(d.when))}${isCur ? " · current" : ""}</span>
      <span class="gist">${esc(d.lines[0] || "")}</span></button>
      ${open ? `<div class="draftview">${d.title ? `<p class="dt">${esc(d.title)}</p>` : ""}${body}
        <div class="acts">${text === editor ? `<span class="muted" style="font-size:13px">Same as the editor</span>` : `
          <button class="btn small" data-compare aria-pressed="${state.compare}">${state.compare ? "Show the draft" : "Changes since"}</button>
          <button class="btn small" data-restore="${esc(d.name)}">Restore</button>`}</div></div>` : ""}</li>`;
  }).join("")}</ol>`;
  $$("[data-d]", el).forEach(b => b.onclick = () => { state.openDraft = state.openDraft === b.dataset.d ? null : b.dataset.d; state.compare = false; renderDrafts(); });
  $("[data-compare]", el) && ($("[data-compare]", el).onclick = () => { state.compare = !state.compare; renderDrafts(); });
  $$("[data-restore]", el).forEach(b => b.onclick = () => {
    const d = p.drafts.find(x => x.name === b.dataset.restore);
    if (d.title) $("#title").value = d.title;
    $("#text").value = d.lines.join("\n");
    state.dirty = true; analyse(); updateState(); renderDrafts();
    toast("Restored into the editor. Save to keep it");
  });
}

/* ——— art ———
   A series with a kit makes its carousel here as well as through Claude: the slides (concepts and their parameters),
   the brief and the posting notes, render and QA. What is being edited lives in state.art, so the 2-second poll can
   repaint the slides as they render without touching what's being typed. */
const RATIO_LABELS = {"45": "4:5 Feed", "11": "1:1 X", "916": "9:16 Story"};
const ART_DOCS = {
  brief: {label: "Brief", file: "BRIEF.md", api: "/api/brief", done: "Saved the brief",
    empty: "What the carousel does and why, slide by slide. Markdown."},
  notes: {label: "Posting notes", file: "NOTES.md", api: "/api/posting-notes", done: "Saved the posting notes",
    empty: "Where and when it goes out, the caption, the alt text. Markdown."},
};
const mdKey = s => String(s || "").replace(/\r\n/g, "\n").replace(/\s+$/, "");
/* A parameter's value is typed as text: what reads as JSON (a number, true, a list like [1, 2]) is kept as JSON, the rest is text.
   Quotes make text of anything: "2" is the text 2. */
const paramValue = t => { try { return JSON.parse(t); } catch { return t; } };
const paramText = v => typeof v === "string" && paramValue(v) === v ? v : JSON.stringify(v);
const draftOf = slides => (slides || []).map(s => ({concept: s.concept,
  params: Object.entries(s).filter(([k]) => k !== "concept").map(([k, v]) => [k, paramText(v)])}));
const slidesKey = draft => JSON.stringify(draft.map(s => [s.concept, s.params]));
const slidesDirty = A => slidesKey(A.slides) !== A.saved;
const docDirty = d => mdKey(d.text) !== mdKey(d.saved);
const conceptOf = (A, id) => (A.concepts || []).find(c => c.id === id);
const artLive = A => state.art === A && state.poem?.id === A.id;     // still the poem on screen (checked again after every await)
/* The slide's number on disk (0 when it isn't saved): rows keep their identity while they are moved and edited, and A.base
   holds them in the saved order (null when the slides changed on disk under unsaved edits). */
const savedNumber = (A, s) => ((slidesDirty(A) ? A.base : A.slides)?.indexOf(s) ?? -1) + 1;
const anyRendered = a => Object.values(a.formats || {}).some(x => x.slides.some(s => s.signed || s.unsigned));

function artFor(p) {
  if (state.art?.id === p.id) return state.art;
  const A = state.art = {id: p.id, series: p.series, slides: draftOf(p.slides), saved: "", base: null, sel: null, concepts: null,
    scope: {slide: "", format: "", signed: ""}, docs: {}, job: null, last: null, timer: null, repaint: true};
  A.saved = slidesKey(A.slides); A.base = [...A.slides];
  for (const k of Object.keys(ART_DOCS)) { const t = p[k] || ""; A.docs[k] = {saved: t, text: t, mode: mdKey(t) ? "preview" : "write"}; }
  return A;
}

/* Take in what changed on disk (Claude, another window, a save here) unless it's being edited here. */
function syncArt(p, A) {
  const fresh = slidesKey(draftOf(p.slides));
  if (fresh !== A.saved) {
    const dirty = slidesDirty(A);
    A.saved = fresh;
    if (!dirty) { A.slides = draftOf(p.slides); A.base = [...A.slides]; A.sel = null; A.scope.slide = ""; A.repaint = true; }
    else A.base = null;
  }
  for (const [k, d] of Object.entries(A.docs)) {
    const t = p[k] || "";
    if (mdKey(t) === mdKey(d.saved)) continue;
    const dirty = docDirty(d);
    d.saved = t;
    if (!dirty) { d.text = t; d.resync = true; }
  }
}

function artUnsaved() {
  const A = state.art;
  if (!A) return "";
  const what = [slidesDirty(A) ? "the slides" : "", ...Object.entries(A.docs).map(([k, d]) => docDirty(d) ? "the " + ART_DOCS[k].label.toLowerCase() : "")].filter(Boolean);
  return what.length ? `Unsaved changes in ${what.join(" and ")} of “${state.poem?.title || A.id}”.` : "";
}

function renderArt() {
  const p = state.poem, a = p.art, tab = $("#tab");
  if (a.no_kit) {
    tab.innerHTML = `<p class="empty">${esc(p.series)} has no carousel kit yet, so there's nothing to render. Use the <b>Design</b> tab to make images by hand, or ask Claude to build a kit for the series.</p>${designShots()}`;
    wireViewer(tab);
    return;
  }
  if (a.error) { tab.innerHTML = `<p class="empty">The series' render engine can't be read: ${esc(a.error)}</p>`; return; }
  if (!a.formats[state.ratio]) state.ratio = a.order[0];
  const A = artFor(p);
  syncArt(p, A);
  if (!$("#art", tab)) mountArt(tab, A);
  paintArtMain();
  if (A.repaint) paintSlideList(A);
  paintSlideState(A);
  paintRenderPanel(A);
  Object.keys(ART_DOCS).forEach(k => $(`#ad-${k}`)?.sync());
}

function mountArt(tab, A) {
  tab.innerHTML = `<div class="art" id="art">
    <div class="art-main">
      <div class="toolbar" id="art-bar"></div>
      <div id="art-notice"></div>
      <div id="art-gallery"></div>
      <div id="art-designs"></div>
      <div class="docs">${Object.keys(ART_DOCS).map(k => `<section class="doc ad" id="ad-${k}"></section>`).join("")}</div>
    </div>
    <aside class="art-side" aria-label="Make the carousel">
      <section class="mk" id="mk-slides">
        <div class="mk-head"><span class="label">Slides <span id="mk-count"></span></span><span class="state" id="mk-state"></span></div>
        <ol class="mk-list" id="mk-list"></ol>
        <div class="mk-acts"><button type="button" class="btn small" id="mk-add">Add slide</button><span class="grow"></span>
          <button type="button" class="btn quiet small" id="mk-discard">Discard</button><button type="button" class="btn solid small" id="mk-save">Save slides</button></div>
      </section>
      <section class="mk">
        <span class="label">Render</span>
        <div class="mk-scope">
          <label><span class="mk-l">Slides</span><select class="select" id="mk-slide"></select></label>
          <label><span class="mk-l">Format</span><select class="select" id="mk-format"></select></label>
          <label><span class="mk-l">Name</span><select class="select" id="mk-signed"></select></label></div>
        <div class="mk-go"><button type="button" class="btn solid" id="mk-render">Render</button><button type="button" class="btn" id="mk-qa">Run QA</button></div>
        <div class="mk-progress" id="mk-progress" aria-live="polite"></div>
      </section>
    </aside></div>`;
  wireSlideList(A);
  $("#mk-add").onclick = () => addSlideDialog(A);
  $("#mk-save").onclick = () => saveSlides(A);
  $("#mk-discard").onclick = () => { A.slides = draftOf(state.poem.slides); A.base = [...A.slides]; A.sel = null; slidesChanged(A); };
  $("#mk-slides").addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveSlides(A); }
  });
  $("#mk-slide").onchange = e => { A.sel = A.slides[+e.target.value - 1] || null; slidesChanged(A); };
  $("#mk-format").onchange = e => { A.scope.format = e.target.value; };
  $("#mk-signed").onchange = e => { A.scope.signed = e.target.value; };
  $("#mk-render").onclick = () => runJob("render");
  $("#mk-qa").onclick = () => runJob("qa");
  Object.keys(ART_DOCS).forEach(k => mountArtDoc($(`#ad-${k}`), A, k));
  A.repaint = true;
  loadConcepts(A);
  if (A.job) watchJob(A);
  else api("/api/render/progress?id=" + encodeURIComponent(A.id)).then(pr => {     // started before this view (another window, or before leaving)
    if (!pr.running || A.job || !artLive(A)) return;
    A.job = {kind: pr.kind, started: Date.now() - pr.seconds * 1000, done: pr.done, total: pr.total, attached: true};
    A.last = null;
    paintRenderPanel(A); watchJob(A);
  }).catch(() => {});
}

async function loadConcepts(A) {
  try { A.concepts = await api("/api/concepts?series=" + encodeURIComponent(A.series)); }
  catch (e) { A.concepts = A.concepts || []; return toast(e.message, true); }
  if (!artLive(A) || !$("#mk-list")) return;
  if ($("#mk-list").contains(document.activeElement)) paintSlideNames(A); else paintSlideList(A);
  paintRenderPanel(A);
}

/* the gallery: format and name, the rendered slides with their QA lines, designs */
function paintArtMain() {
  const p = state.poem, a = p.art, f = a.formats[state.ratio];
  const ask = `“make the carousel for ${esc(p.title)}”`;
  const seg = (attr, items, cur) => items.map(([v, label]) => `<button ${attr}="${v}" aria-pressed="${v === cur}">${label}</button>`).join("");
  const bar = $("#art-bar");
  bar.innerHTML = `
      <div class="seg" role="group" aria-label="Name">${seg("data-sig", [["1", "With name"], ["0", "Without"]], state.signed ? "1" : "0")}</div>
      <div class="seg" role="group" aria-label="Format">${seg("data-ratio", a.order.map(r => [r, RATIO_LABELS[r] || a.formats[r].label]), state.ratio)}</div>
      <div class="links">${a.page ? `<a href="${fileUrl(a.page, p.stamp | 0)}" target="_blank" rel="noopener">Preview page ↗</a>` : ""}
        ${a.sheet ? `<a href="${fileUrl(a.sheet, p.stamp | 0)}" target="_blank" rel="noopener">Contact sheet ↗</a>` : ""}</div>`;
  $$("[data-sig]", bar).forEach(b => b.onclick = () => { state.signed = b.dataset.sig === "1"; pref.set("signed", b.dataset.sig); renderArt(); });
  $$("[data-ratio]", bar).forEach(b => b.onclick = () => { state.ratio = b.dataset.ratio; pref.set("ratio", b.dataset.ratio); renderArt(); });
  $("#art-notice").innerHTML = a.stale ? `<p class="notice">The text or the slides changed since this was rendered.
    <button type="button" class="btn small" data-render-all>Render everything</button></p>` : "";
  $("#art-notice [data-render-all]") && ($("#art-notice [data-render-all]").onclick = () => runJob("render", {slide: "", format: "", signed: ""}));
  const g = $("#art-gallery"), open = new Set($$("details.qa[open]", g).map(d => d.closest("figure")?.dataset.rel));
  g.innerHTML = !p.slides.length
    ? `<p class="empty">No slides yet. Add them under <b>Slides</b> and render, or ask Claude: <b>${ask}</b>.</p>`
    : `${anyRendered(a) ? "" : `<p class="muted art-hint">Not rendered yet. Render the slides, or ask Claude: ${ask}.</p>`}
      <div class="slides">${f.slides.map(s => slideCard(s, f)).join("")}</div>`;
  $$("figure", g).forEach(fig => { if (fig.dataset.rel && open.has(fig.dataset.rel)) $("details.qa", fig)?.setAttribute("open", ""); });
  $("#art-designs").innerHTML = designShots();
  wireViewer(g); wireViewer($("#art-designs"));
}

/* ——— the slides: a list of concepts with their parameters ——— */
function paintSlideList(A) {
  A.repaint = false;
  const list = $("#mk-list");
  if (!list) return;
  list.innerHTML = A.slides.length ? A.slides.map((s, i) => {
    const c = conceptOf(A, s.concept), missing = A.concepts && !c;
    return `<li class="mk-row${A.sel === s ? " sel" : ""}" data-i="${i}"${A.sel === s ? ' aria-current="true"' : ""}>
      <div class="mk-top"><button type="button" class="mk-grip" aria-label="Move slide ${i + 1}" title="Drag to move (or the arrow keys)"></button>
        <span class="mk-n">${i + 1}</span>
        <span class="mk-name">${esc(c ? c.name : s.concept)}${c && c.name.toLowerCase() !== s.concept ? ` <small>${esc(s.concept)}</small>` : ""}</span>
        <button type="button" class="btn quiet small mk-x" data-rm aria-label="Remove slide ${i + 1}" title="Remove the slide">✕</button></div>
      ${missing ? `<p class="mk-about bad">The kit has no concept “${esc(s.concept)}”.</p>`
        : c?.doc ? `<p class="mk-about" title="${esc(c.doc)}">${esc(c.doc)}</p>` : ""}
      <div class="mk-params">${s.params.map(([k, v], j) => `<div class="mk-param" data-j="${j}">
        <input class="input mk-key" data-f="0" value="${esc(k)}" placeholder="name" aria-label="Slide ${i + 1}, name of parameter ${j + 1}" autocomplete="off" spellcheck="false">
        <input class="input" data-f="1" value="${esc(v)}" placeholder="value" aria-label="Slide ${i + 1}, value of parameter ${j + 1}" autocomplete="off" spellcheck="false">
        <button type="button" class="btn quiet small mk-x" data-rmp aria-label="Remove parameter ${j + 1} of slide ${i + 1}" title="Remove the parameter">✕</button></div>`).join("")}</div>
      <button type="button" class="btn quiet small mk-addp" data-addp>Add parameter</button></li>`;
  }).join("") : `<li class="mk-none">No slides yet. Add the first one from the kit's concepts.</li>`;
}
function paintSlideNames(A) {
  $$("#mk-list .mk-row").forEach(li => {
    const s = A.slides[+li.dataset.i], c = s && conceptOf(A, s.concept);
    if (c) $(".mk-name", li).firstChild.textContent = c.name;
  });
}
function paintSlideState(A) {
  const dirty = slidesDirty(A), st = $("#mk-state");
  if (!st) return;
  $("#mk-count").textContent = A.slides.length ? `· ${A.slides.length}` : "";
  st.textContent = dirty ? "Unsaved changes" : ""; st.classList.toggle("dirty", dirty);
  $("#mk-save").disabled = !dirty || !A.slides.length;
  $("#mk-discard").hidden = !dirty;
  $("#mk-render").title = dirty ? "Saves the slides, then renders" : "";
}
/* After any change to the list: the render scope follows the selected row wherever it went (or is cleared with it). */
function slidesChanged(A) {
  const at = A.sel ? A.slides.indexOf(A.sel) : -1;
  if (at < 0) A.sel = null;
  A.scope.slide = at < 0 ? "" : String(at + 1);
  paintSlideList(A); paintSlideState(A); paintRenderPanel(A);
}

function selectSlide(A, s) {
  A.sel = A.sel === s ? null : s;
  slidesChanged(A);
}
function moveSlide(A, from, to) {          // to: the gap to drop into, 0 … length
  if (to === from || to === from + 1 || to < 0 || to > A.slides.length) return null;
  const [s] = A.slides.splice(from, 1), at = to > from ? to - 1 : to;
  A.slides.splice(at, 0, s);
  slidesChanged(A);
  return at;
}
function removeSlide(A, i) {
  A.slides.splice(i, 1);
  slidesChanged(A);
}
function addParam(A, i) {
  A.slides[i].params.push(["", ""]);
  slidesChanged(A);
  $$(`#mk-list .mk-row[data-i="${i}"] .mk-key`).pop()?.focus();
}

function wireSlideList(A) {
  const list = $("#mk-list");
  const rowOf = el => el.closest(".mk-row");
  list.addEventListener("input", ev => {
    const f = ev.target.dataset.f, li = rowOf(ev.target), p = ev.target.closest(".mk-param");
    if (f == null || !li || !p) return;
    A.slides[+li.dataset.i].params[+p.dataset.j][+f] = ev.target.value;
    paintSlideState(A);
  });
  list.addEventListener("click", ev => {
    const li = rowOf(ev.target);
    if (!li) return;
    const i = +li.dataset.i;
    if (ev.target.closest("[data-rm]")) removeSlide(A, i);
    else if (ev.target.closest("[data-rmp]")) { A.slides[i].params.splice(+ev.target.closest(".mk-param").dataset.j, 1); slidesChanged(A); }
    else if (ev.target.closest("[data-addp]")) addParam(A, i);
    else if (ev.target.closest(".mk-about")) ev.target.closest(".mk-about").classList.toggle("open");
    else if (ev.target.closest(".mk-top") && !ev.target.closest(".mk-grip")) selectSlide(A, A.slides[i]);
  });
  list.addEventListener("keydown", ev => {
    const grip = ev.target.closest(".mk-grip");
    if (!grip || !["ArrowUp", "ArrowDown"].includes(ev.key)) return;
    ev.preventDefault();
    const i = +rowOf(grip).dataset.i, at = moveSlide(A, i, ev.key === "ArrowUp" ? i - 1 : i + 2);
    if (at != null) $(`#mk-list .mk-row[data-i="${at}"] .mk-grip`)?.focus();
  });
  /* drag to reorder: the grip follows the pointer, a red line shows where the slide lands */
  list.addEventListener("pointerdown", ev => {
    const grip = ev.target.closest(".mk-grip");
    if (!grip || ev.button !== 0) return;
    ev.preventDefault();
    const li = rowOf(grip), from = +li.dataset.i, y0 = ev.clientY;
    let to = null;
    try { grip.setPointerCapture(ev.pointerId); } catch { /* the pointer is already gone */ }
    const clear = () => $$(".mk-row", list).forEach(r => r.classList.remove("drop-before", "drop-after"));
    const move = e => {
      if (to == null && Math.abs(e.clientY - y0) < 4) return;
      li.classList.add("dragging");
      const rows = $$(".mk-row", list);
      to = rows.length;
      for (const r of rows) { const b = r.getBoundingClientRect(); if (e.clientY < b.top + b.height / 2) { to = +r.dataset.i; break; } }
      clear();
      if (to < rows.length) rows[to].classList.add("drop-before"); else rows[rows.length - 1].classList.add("drop-after");
    };
    const end = drop => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", onUp);
      grip.removeEventListener("pointercancel", onCancel);
      li.classList.remove("dragging"); clear();
      if (drop && to != null) moveSlide(A, from, to);
    };
    const onUp = () => end(true), onCancel = () => end(false);
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", onUp);
    grip.addEventListener("pointercancel", onCancel);
  });
  list.addEventListener("contextmenu", ev => {
    const li = rowOf(ev.target);
    if (!li || ev.target.closest("input")) return;
    const i = +li.dataset.i, s = A.slides[i], busy = !!A.job;
    StudioMenu.open(ev, [
      {label: "Render this slide", disabled: busy, act: () => runJob("render", {slide: String(i + 1)})},
      {label: "Run QA on this slide", disabled: busy || !anyRendered(state.poem.art), act: () => runJob("qa", {slide: String(i + 1)})},
      "-",
      {label: "Concept", disabled: !A.concepts?.length, items: (A.concepts || []).map(c => ({label: c.name, checked: c.id === s.concept,
        act: () => { s.concept = c.id; slidesChanged(A); }}))},
      {label: "Add parameter", act: () => addParam(A, i)},
      {label: "Duplicate", act: () => { A.slides.splice(i + 1, 0, {concept: s.concept, params: s.params.map(x => [...x])}); slidesChanged(A); }},
      "-",
      {label: "Move up", disabled: i === 0, act: () => moveSlide(A, i, i - 1)},
      {label: "Move down", disabled: i === A.slides.length - 1, act: () => moveSlide(A, i, i + 2)},
      "-",
      {label: "Remove", danger: true, act: () => removeSlide(A, i)},
    ]);
  });
}

function addSlideDialog(A) {
  const cs = A.concepts;
  if (!cs) return toast("The kit's concepts are still loading", true);
  if (!cs.length) return toast(`${A.series}'s kit has no concepts yet`, true);
  let pick = null;
  const form = openDialog(`<form class="mk-pick">
    <h2>Add a slide</h2>
    <p class="hint" style="margin-top:-12px">The concepts in ${esc(A.series)}'s kit. The slide goes at the end; drag it to move it.</p>
    <div class="ask-opts">${cs.map(c => `<button type="submit" class="choice" data-c="${esc(c.id)}"><b>${esc(c.name)}</b><span>${esc(c.doc || c.id)}</span></button>`).join("")}</div>
    <div class="foot"><span></span><button type="button" class="btn quiet" data-close>Cancel</button></div></form>`, async () => {
    if (!pick) return;
    A.slides.push({concept: pick, params: []});
    slidesChanged(A);
    $("#mk-list .mk-row:last-child")?.scrollIntoView({block: "nearest"});
  });
  $$("[data-c]", form).forEach(b => b.onclick = () => { pick = b.dataset.c; });
  $("[data-c]", form)?.focus();
}

/* The slides as poem.json takes them; throws with a sentence when one can't be saved. */
function draftSlides(A) {
  return A.slides.map((s, i) => {
    const out = {concept: s.concept};
    for (const [k, t] of s.params) {
      const key = k.trim();
      if (!key && !t.trim()) continue;
      if (!key) throw new Error(`Slide ${i + 1}: give the parameter a name, or remove it.`);
      if (key === "concept") throw new Error(`Slide ${i + 1}: “concept” is the slide's concept, not a parameter.`);
      if (key in out) throw new Error(`Slide ${i + 1}: the parameter “${key}” is there twice.`);
      out[key] = paramValue(t);
    }
    return out;
  });
}
async function saveSlides(A) {
  let slides;
  try { slides = draftSlides(A); } catch (e) { toast(e.message, true); return false; }
  if (!slides.length) { toast("Add a slide first", true); return false; }
  try {
    const fresh = await api("/api/slides", {id: A.id, slides});
    A.slides = draftOf(fresh.slides); A.saved = slidesKey(A.slides); A.base = [...A.slides]; A.repaint = true;
    if (A.sel) { A.sel = A.slides[+A.scope.slide - 1] || null; if (!A.sel) A.scope.slide = ""; }    // saved in the list's order
    toast("Saved the slides");
    if (artLive(A)) applyFresh(fresh);
    return true;
  } catch (e) { toast(e.message, true); return false; }
}

/* ——— render and QA ——— */
function setOptions(sel, opts, value) {
  const key = JSON.stringify(opts);
  if (sel.dataset.key !== key) { sel.innerHTML = opts.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join(""); sel.dataset.key = key; }
  sel.value = value;
}
function paintRenderPanel(A) {
  const a = state.poem?.art, r = $("#mk-render");
  if (!r || !a?.formats) return;
  if (+A.scope.slide > A.slides.length) A.scope.slide = "";
  setOptions($("#mk-slide"), [["", "All"], ...A.slides.map((s, i) => [String(i + 1), `${i + 1} · ${conceptOf(A, s.concept)?.name || s.concept}`])], A.scope.slide);
  setOptions($("#mk-format"), [["", "All"], ...a.order.map(k => [k, RATIO_LABELS[k] || a.formats[k].label])], A.scope.format);
  setOptions($("#mk-signed"), [["", "Both"], ["1", "With name"], ["0", "Without"]], A.scope.signed);
  r.disabled = !!A.job || !A.slides.length;
  $("#mk-qa").disabled = !!A.job || !anyRendered(a);
  paintProgress(A);
}
function paintProgress(A) {
  const el = $("#mk-progress"), j = A.job;
  if (!el) return;
  if (!j) {
    el.dataset.job = "";
    el.innerHTML = A.last ? `<span class="state${A.last.bad ? " bad" : ""}">${esc(A.last.text)}</span>${A.last.note ? `<p class="hint">${esc(A.last.note)}</p>` : ""}` : "";
    return;
  }
  const pct = j.kind === "render" && j.total ? Math.round(j.done / j.total * 100) : null;
  const what = j.kind === "qa" ? "Running QA" : j.total ? `Rendering ${j.done} of ${plural(j.total, "image")}` : "Building the preview page";
  if (el.dataset.job !== String(j.started)) {
    el.dataset.job = String(j.started);
    el.innerHTML = `<div class="mk-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"><i></i></div><span class="state"></span>`;
  }
  const bar = $(".mk-bar", el);
  bar.classList.toggle("indet", pct == null);
  $("i", bar).style.width = pct == null ? "" : pct + "%";
  if (pct == null) bar.removeAttribute("aria-valuenow"); else bar.setAttribute("aria-valuenow", pct);
  bar.setAttribute("aria-label", what);
  $(".state", el).textContent = `${what} · ${Math.floor((Date.now() - j.started) / 1000)} s`;
}
/* While a render or QA runs: the elapsed time, and how many images are done (the server counts them). */
function watchJob(A) {
  clearInterval(A.timer);
  let asking = false;
  A.timer = setInterval(async () => {
    if (!A.job || state.art !== A) return clearInterval(A.timer);
    paintProgress(A);
    if (asking) return;
    asking = true;
    try {
      const pr = await api("/api/render/progress?id=" + encodeURIComponent(A.id)), j = A.job;
      if (!j) return;
      if (pr.running) Object.assign(j, {done: pr.done, total: pr.total});
      else if (j.attached) {            // a job this view didn't start has finished: show what it made
        A.job = null; clearInterval(A.timer);
        A.last = {text: `${j.kind === "qa" ? "QA" : "The render"} finished after ${Math.round((Date.now() - j.started) / 1000)} s`};
        const fresh = await api("/api/poem?id=" + encodeURIComponent(A.id));
        if (artLive(A)) applyFresh(fresh);    // the view may have moved to another poem while that loaded
      }
    } catch { /* the poll says when Studio has stopped */ }
    finally { asking = false; }
    paintProgress(A);
  }, 500);
}
function qaHeadline(rep) {
  const imgs = (rep.checked || []).map(k => rep.images[k]).filter(Boolean), issues = imgs.flatMap(i => i.issues || []);
  const fails = issues.filter(i => i.level === "fail").length, warns = issues.length - fails;
  return `Checked ${plural(imgs.length, "image")}: ` + (!issues.length ? "all aligned"
    : [fails ? `${fails} problem${fails > 1 ? "s" : ""}` : "", warns ? `${warns} to check` : ""].filter(Boolean).join(", "));
}
/* Render or QA with the panel's choices. scope: choices to set first (a row's menu: its place in the list).
   savedSlide: a slide by its number on disk (the gallery's menu): the job runs on that slide as saved, and unsaved changes to
   the list stay unsaved. Otherwise Render saves the list first, so the list's order is the order on disk; QA never saves, so
   its slide is looked up on disk by the row's identity. */
async function runJob(kind, scope = null, savedSlide = null) {
  const A = state.art;
  if (!A || A.job || !artLive(A)) return;
  if (scope) {
    Object.assign(A.scope, scope);
    A.sel = A.scope.slide ? A.slides[+A.scope.slide - 1] || null : null;
    slidesChanged(A);
  }
  const asSaved = savedSlide != null, unsaved = slidesDirty(A);
  if (!asSaved && kind === "render" && unsaved && !(await saveSlides(A))) return;
  if (A.job || !artLive(A)) return;
  let slide = asSaved ? savedSlide : A.scope.slide ? +A.scope.slide : null;
  if (!asSaved && slide && kind === "qa") {
    slide = savedNumber(A, A.slides[slide - 1]);
    if (!slide) return toast(`Slide ${A.scope.slide} isn't saved yet. Save the slides and render it first.`, true);
  }
  const body = {id: A.id, slide, format: A.scope.format || null};
  if (kind === "render") body.signed = A.scope.signed === "" ? null : A.scope.signed === "1";
  const job = A.job = {kind, started: Date.now(), done: 0, total: 0};
  A.last = null;
  paintRenderPanel(A); watchJob(A);
  try {
    const r = await api(kind === "render" ? "/api/render" : "/api/qa", body);
    const secs = Math.max(1, Math.round(r.seconds ?? (Date.now() - job.started) / 1000));
    A.job = null;
    A.last = kind === "render"
      ? {text: `Rendered ${plural(r.images.length, "image")} in ${secs} s`, note: asSaved && unsaved
          ? `Slide ${savedSlide} was rendered as saved; the changes to the slides here aren't saved yet.`
          : r.rest_stale ? "The text or the slides changed since the last full render, so the images left out still show the old "
            + "version. Render everything to bring them up to date." : ""}
      : {text: qaHeadline(r.report)};
    toast(A.last.text);
    if (artLive(A)) applyFresh(r.poem);
  } catch (e) {
    A.last = {text: e.message.charAt(0).toUpperCase() + e.message.slice(1), bad: true};
    toast(e.message, true);
  } finally {
    if (A.job === job) A.job = null;
    clearInterval(A.timer);
    if (artLive(A)) paintRenderPanel(A);
  }
}

/* ——— brief and posting notes: Markdown, written here or by Claude ——— */
function mountArtDoc(sec, A, k) {
  const spec = ART_DOCS[k], d = A.docs[k];
  sec.innerHTML = `<div class="ad-head"><span class="label">${spec.label}</span><span class="ad-file">${spec.file}</span>
      <div class="seg" role="group" aria-label="${spec.label}"><button type="button" data-mode="write">Write</button><button type="button" data-mode="preview">Preview</button></div></div>
    <textarea class="notesin ad-text" spellcheck="true" placeholder="${esc(spec.empty)}" aria-label="${spec.label}"></textarea>
    <div class="md ad-prev"></div>
    <div class="ad-save"><button type="button" class="btn solid small" data-save>Save</button><span class="state"></span></div>`;
  const text = $(".ad-text", sec), prev = $(".ad-prev", sec), stat = $(".state", sec), btn = $("[data-save]", sec);
  text.value = d.text;
  const paint = () => {
    const writing = d.mode === "write";
    text.hidden = !writing; prev.hidden = writing;
    if (!writing) prev.innerHTML = mdKey(d.text) ? md(d.text) : `<p class="muted">Nothing written yet.</p>`;
    $$("[data-mode]", sec).forEach(b => b.setAttribute("aria-pressed", b.dataset.mode === d.mode));
    const dirty = docDirty(d);
    stat.textContent = dirty ? "Unsaved changes · Ctrl+S" : ""; stat.classList.toggle("dirty", dirty);
    btn.disabled = !dirty;
  };
  const save = async () => {
    if (!docDirty(d)) return;
    try {
      const fresh = await api(spec.api, {id: A.id, text: d.text});
      d.saved = fresh[k] || "";
      toast(spec.done);
      if (artLive(A)) applyFresh(fresh); else paint();
    } catch (e) { toast(e.message, true); }
  };
  text.oninput = () => { d.text = text.value; paint(); };
  text.addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); } });
  $$("[data-mode]", sec).forEach(b => b.onclick = () => {
    d.mode = b.dataset.mode; paint();
    if (d.mode === "write") text.focus();
  });
  btn.onclick = save;
  sec.sync = () => { if (d.resync) { d.resync = false; text.value = d.text; } paint(); };
  paint();
}

/* exported designs (Design tab) for the format in view */
function designShots() {
  const ds = (state.poem.designs || []).filter(x => x.exports?.[state.ratio]);
  if (!ds.length) return "";
  const F = {"45": [1080, 1350], "11": [1080, 1080], "916": [1080, 1920]}[state.ratio];
  return `<section class="section"><div class="sectionhead"><h2 class="h2">Designs <span>${ds.length}</span></h2></div>
    <div class="slides">${ds.map(x => { const e = x.exports[state.ratio], rel = (state.signed ? e.signed : e.unsigned) || e.signed, v = rel === e.signed ? e.signed_v : e.unsigned_v;
      return `<figure><span class="cap"><span>${esc(x.name)}</span><span>design</span></span><a class="shot" href="${fileUrl(rel, v)}" target="_blank" rel="noopener" data-view="design:${esc(x.slug)}" style="aspect-ratio:${F[0]}/${F[1]}"><img src="${fileUrl(rel, v)}" alt="${esc(x.name)}" loading="lazy"></a></figure>`; }).join("")}</div></section>`;
}

/* ——— the viewer: every slide and exported design of the poem, one at a time ——— */
const viewer = {open: false, i: 0, items: []};
function viewerItems() {
  const p = state.poem, a = p.art || {}, out = [];
  const f = a.formats?.[state.ratio];
  for (const s of f?.slides || []) {
    const rel = state.signed ? s.signed : s.unsigned, v = state.signed ? s.signed_v : s.unsigned_v;
    if (rel) out.push({key: "slide:" + s.n, title: s.name, sub: `Slide ${s.n} of ${f.slides.length}`, rel, v, n: s.n});
  }
  for (const x of p.designs || []) {
    const e = x.exports?.[state.ratio];
    if (!e) continue;
    const rel = (state.signed ? e.signed : e.unsigned) || e.signed, v = rel === e.signed ? e.signed_v : e.unsigned_v;
    out.push({key: "design:" + x.slug, title: x.name, sub: "Design", rel, v, slug: x.slug});
  }
  return out;
}
function wireViewer(el) {
  $$("[data-view]", el).forEach(a => a.onclick = ev => {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button === 1) return;   // new tab still works
    ev.preventDefault(); openViewer(a.dataset.view);
  });
}
function openViewer(key) {
  viewer.items = viewerItems();
  viewer.i = Math.max(0, viewer.items.findIndex(x => x.key === key));
  viewer.open = true;
  renderViewer();
}
function closeViewer() { viewer.open = false; $("#viewer")?.remove(); }
function renderViewer() {
  if (!viewer.open) return;
  const items = viewer.items = viewerItems();
  if (!items.length) return closeViewer();
  viewer.i = Math.min(viewer.i, items.length - 1);
  const it = items[viewer.i], a = state.poem.art || {};
  const canShare = !!navigator.canShare;
  let el = $("#viewer");
  if (!el) { el = document.createElement("div"); el.id = "viewer"; el.className = "viewer"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Viewer"); document.body.appendChild(el); }
  const seg = (attr, list, cur) => list.map(([v, l]) => `<button ${attr}="${v}" aria-pressed="${v === cur}">${l}</button>`).join("");
  el.innerHTML = `
    <header class="vbar">
      <div class="vtitle"><span class="kicker">${esc(state.poem.title)} · ${esc(it.sub)}</span><b>${esc(it.title)}</b></div>
      <span class="spacer"></span>
      <div class="seg" aria-label="Name">${seg("data-vsig", [["1", "With name"], ["0", "Without"]], state.signed ? "1" : "0")}</div>
      <div class="seg" aria-label="Format">${seg("data-vratio", (a.order || ["45", "11", "916"]).map(r => [r, {"45": "4:5", "11": "1:1", "916": "9:16"}[r]]), state.ratio)}</div>
      <div class="vacts">
        <button class="btn small" data-vact="copy" title="Copy the image (C)">Copy</button>
        <a class="btn small" data-vact="save" href="${fileUrl(it.rel, it.v)}" download="${esc(it.rel.split("/").pop())}" title="Save a copy (S)">Save</a>
        ${canShare ? `<button class="btn small" data-vact="share" title="Share">Share</button>` : ""}
        <button class="btn small" data-vact="reveal" title="Show the file in its folder">Show in folder</button>
        ${it.n ? `<button class="btn small" data-vact="edit" title="Open this slide as an editable design">Edit</button>` : it.slug ? `<button class="btn small" data-vact="edit" title="Open this design">Edit</button>` : ""}
        <button class="btn quiet" data-vact="close" title="Close (Esc)" aria-label="Close">✕</button></div>
    </header>
    <div class="vstage">
      <button class="vnav prev" data-vnav="-1" aria-label="Previous" ${items.length < 2 ? "disabled" : ""}>‹</button>
      <img src="${fileUrl(it.rel, it.v)}" alt="${esc(it.title)}">
      <button class="vnav next" data-vnav="1" aria-label="Next" ${items.length < 2 ? "disabled" : ""}>›</button>
      <span class="vcount">${viewer.i + 1} / ${items.length}</span>
    </div>
    <footer class="vstrip">${items.map((x, i) => `<button class="${i === viewer.i ? "on" : ""}" data-vgo="${i}" title="${esc(x.title)}"><img src="${fileUrl(x.rel, x.v)}" alt="" loading="lazy"></button>`).join("")}</footer>`;
  $$("[data-vnav]", el).forEach(b => b.onclick = () => stepViewer(+b.dataset.vnav));
  $$("[data-vgo]", el).forEach(b => b.onclick = () => { viewer.i = +b.dataset.vgo; renderViewer(); });
  $$("[data-vsig]", el).forEach(b => b.onclick = () => { state.signed = b.dataset.vsig === "1"; pref.set("signed", b.dataset.vsig); if (state.tab === "art") renderArt(); renderViewer(); });
  $$("[data-vratio]", el).forEach(b => b.onclick = () => { state.ratio = b.dataset.vratio; pref.set("ratio", b.dataset.vratio); if (state.tab === "art") renderArt(); renderViewer(); });
  $("[data-vact=close]", el).onclick = closeViewer;
  $("[data-vact=copy]", el).onclick = () => copyImage(it);
  $("[data-vact=share]", el) && ($("[data-vact=share]", el).onclick = () => shareImage(it));
  $("[data-vact=reveal]", el).onclick = () => api("/api/reveal", {rel: it.rel}).catch(e => toast(e.message, true));
  $("[data-vact=edit]", el) && ($("[data-vact=edit]", el).onclick = () => {
    closeViewer();
    if (it.n) state.importSlide = {n: it.n, fmt: state.ratio};
    else try { localStorage.setItem("studio.ed.last." + state.poem.id, it.slug); } catch { /* ignore */ }
    location.hash = poemHash(state.poem.id, "design");
  });
  el.querySelector(".vstrip .on")?.scrollIntoView({block: "nearest", inline: "center"});
}
function stepViewer(d) { const n = viewer.items.length; if (n) { viewer.i = (viewer.i + d + n) % n; renderViewer(); } }
async function imageBlob(it) { return (await fetch(fileUrl(it.rel, it.v))).blob(); }
async function copyImage(it) {
  try { await navigator.clipboard.write([new ClipboardItem({"image/png": imageBlob(it)})]); toast("Image copied"); }
  catch (e) { toast("Couldn't copy the image here: " + e.message, true); }
}
async function shareImage(it) {
  try {
    const file = new File([await imageBlob(it)], it.rel.split("/").pop(), {type: "image/png"});
    if (navigator.canShare?.({files: [file]})) await navigator.share({files: [file], title: `${state.poem.title} — ${it.title}`});
    else toast("Sharing files isn't available here", true);
  } catch (e) { if (e.name !== "AbortError") toast(e.message, true); }
}
addEventListener("keydown", e => {
  if (!viewer.open || e.target.closest?.("input, textarea")) return;
  if (e.key === "Escape") { e.preventDefault(); closeViewer(); }
  else if (e.key === "ArrowRight") { e.preventDefault(); stepViewer(1); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); stepViewer(-1); }
  else if (e.key.toLowerCase() === "c" && !e.ctrlKey && !e.metaKey) copyImage(viewer.items[viewer.i]);
  else if (e.key.toLowerCase() === "s" && !e.ctrlKey && !e.metaKey) $("#viewer [data-vact=save]")?.click();
});

function slideCard(s, f) {
  const rel = state.signed ? s.signed : s.unsigned, v = state.signed ? s.signed_v : s.unsigned_v;
  const shot = rel
    ? `<a class="shot" href="${fileUrl(rel, v)}" target="_blank" rel="noopener" data-view="slide:${s.n}" style="aspect-ratio:${f.w}/${f.h}"><img src="${fileUrl(rel, v)}" alt="Slide ${s.n}, ${esc(s.name)}" loading="lazy"></a>`
    : `<div class="shot none" style="aspect-ratio:${f.w}/${f.h}">Not rendered</div>`;
  return `<figure data-n="${s.n}" data-rel="${esc(rel || "")}" data-v="${v || ""}"><span class="cap"><span>${s.n} / ${f.slides.length} · ${esc(s.name)}</span><span>${esc(f.label)}</span></span>${shot}${rel ? qaLine(rel, v) : ""}</figure>`;
}

function qaLine(rel, v) {
  const q = state.poem.qa?.images?.[stem(rel)];
  if (!q || q.v !== v) return "";   // no QA for this version of the image
  const issues = q.issues || [], fails = issues.filter(i => i.level === "fail").length, warns = issues.length - fails;
  const m = q.margins, cols = q.columns || {left: [], right: []};
  const facts = [
    m ? `Margins L ${m.left} · R ${m.right} · T ${m.top} · B ${m.bottom}` : "",
    ...["left", "right"].flatMap(side => cols[side].map(c => `${side} edge at ${c.x} (rows ${c.rows.join(", ")})`)),
    q.smallest_at_phone != null ? `smallest text ${q.smallest_at_phone} px on a phone` : "",
  ].filter(Boolean);
  const kind = fails ? "fail" : warns ? "warn" : "ok";
  const summary = fails ? `${fails} problem${fails > 1 ? "s" : ""}${warns ? `, ${warns} to check` : ""}` : warns ? `${warns} to check` : "aligned";
  return `<details class="qa ${kind}"><summary>${summary}</summary><ul>
    ${issues.map(i => `<li class="${i.level}">${esc(i.text)}</li>`).join("")}
    ${facts.map(t => `<li>${esc(t)}</li>`).join("")}</ul></details>`;
}

/* ——— live updates ——— */
function applyFresh(fresh) {
  const p = state.poem;
  state.poem = fresh; state.stamp = fresh.stamp;
  if (state.view !== "poem") return;
  renderHeader();
  if (state.tab === "art") return renderArt();
  if (state.tab === "design") return Editor.update(fresh);
  if (!state.dirty) {
    const t = $("#title"), x = $("#text");
    if (t && x && (t.value !== fresh.title || x.value !== fresh.lines.join("\n"))) {
      t.value = fresh.title; x.value = fresh.lines.join("\n");
    }
  }
  const n = $("#notes");
  if (n && !state.notesDirty && document.activeElement !== n && n.value !== (fresh.writing_notes || "")) n.value = fresh.writing_notes || "";
  if (p && p.drafts.length !== fresh.drafts.length) state.openDraft = null;
  analyse(); renderDrafts(); updateState(); renderReady();
}

async function poll() {
  try {
    const q = state.view === "poem" ? "?id=" + encodeURIComponent(state.poem.id)
      : state.view === "series" ? "?series=" + encodeURIComponent(state.series.name) : "";
    const {stamp, books} = await api("/api/stamp" + q);     // `books`: the books' own stamp, when no poem or series is asked for
    if (state.offline) { state.offline = false; toast("Studio is back"); }
    const booksMoved = books != null && state.booksStamp != null && books !== state.booksStamp;
    if (books != null) state.booksStamp = books;
    if (state.view === "books" || state.view === "book") { if (booksMoved) await refreshBookView(); }
    else if (state.view === "homepage" && booksMoved) { const d = await loadHome(); state.stamp = d.stamp; renderHomePage(); }
    else if (stamp !== state.stamp) {
      if (state.view === "poem") applyFresh(await api("/api/poem?id=" + encodeURIComponent(state.poem.id)));
      else if (state.view === "series") {
        state.series = await api("/api/series?name=" + encodeURIComponent(state.series.name)); state.stamp = state.series.stamp;
        const doc = $("#stab")?.syncDoc;      // the Rules or Concepts editor: keep what's being typed
        if (doc) doc(); else if (!document.activeElement?.isContentEditable) renderSeries();
      }
      else if (state.view === "poems") { const d = await loadHome(); state.stamp = d.stamp; renderGrid(); }
      else if (state.view === "homepage") { const d = await loadHome(); state.stamp = d.stamp; renderHomePage(); }
      else state.stamp = stamp;
    }
  } catch {
    if (!state.offline) { state.offline = true; toast("Studio isn't running. Start it with Start Studio.cmd", true); }
  }
  setTimeout(poll, 2000);
}

addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && state.view === "poem" && state.tab === "write") {
    e.preventDefault(); saveText().catch(() => {});
  }
  if (e.key === "Escape" && document.body.classList.contains("focus")) setFocus(false);
});

/* ——— settings ——— */
/* ——— updates: the Settings section and the line on Info ——— */
function checkedAgo(t) {
  if (!t) return "not checked yet";
  const d = Math.floor((Date.now() / 1000 - t) / 86400);
  return d < 1 ? "checked today" : d === 1 ? "checked yesterday" : `checked ${d} days ago`;
}
const updateLine = u => u.available
  ? `Studio ${esc(u.latest)} is available`
  : `Studio ${esc(u.current)} · up to date · ${checkedAgo(u.checked)}`;
/* An update that didn't go in before this Studio started (the server says it once). */
const updateFailed = u => u?.update_failed ? `<p class="hint bad" role="alert">${esc(u.update_failed)}</p>` : "";
const updateActions = u => u.available
  ? `<button type="button" class="btn solid small" data-update>Update</button>${u.url ? ` <a class="btn quiet small" href="${esc(u.url)}" target="_blank" rel="noopener">What’s new</a>` : ""}` : "";
async function applyUpdate(host, restore) {
  if (!confirm("Studio will close, update and open again.")) return;
  const before = (await api("/api/about").catch(() => ({}))).version;
  host.innerHTML = `<span class="muted">Updating…</span>`;
  try {
    await api("/api/update/apply", {});
    api("/api/restart", {}).catch(() => {});
  } catch (e) { toast(e.message, true); restore(); return; }
  let wentDown = false;
  for (let i = 0; i < 180; i++) {
    await new Promise(r => setTimeout(r, 1000));
    try {
      const a = await api("/api/about");
      if (a.version !== before || wentDown) { location.reload(); return; }
      const u = await api("/api/update").catch(() => null);
      if (u?.restart_failed) { toast(u.error, true); restore(); return; }
    } catch { wentDown = true; }
  }
  host.innerHTML = `<span class="muted">Studio didn’t come back. Open it again from the Start menu.</span>`;
}

/* Settings → Spelling: Automatic, the languages a book offers (book.js), or another code. */
function spellingPick(value) {
  const langs = typeof BOOK_LANGUAGES !== "undefined" ? BOOK_LANGUAGES : [];
  const known = value === "auto" || langs.some(([c]) => c === value);
  return `<div class="bk-langpick" style="max-width:none"><select class="select" id="s-spell">
      <option value="auto" ${value === "auto" ? "selected" : ""}>Automatic (the language of the book you wrote in last)</option>
      ${langs.map(([c, l]) => `<option value="${esc(c)}" ${c === value ? "selected" : ""}>${esc(l)}</option>`).join("")}
      <option value="" ${known ? "" : "selected"}>Other…</option></select>
    <input class="input" id="s-spell-code" value="${known ? "" : esc(value)}" placeholder="Code, like pt" aria-label="Language code" maxlength="35" spellcheck="false" autocomplete="off" ${known ? "hidden" : ""}></div>`;
}

async function showSettings() {
  state.view = "settings"; setNav("settings"); document.title = "Settings — Studio";
  let info, upd;
  try { info = await api("/api/settings"); } catch (e) { app.innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  try { upd = await api("/api/update"); } catch { upd = null; }
  let looks = [];
  try { looks = (await api("/api/styles")).looks; } catch { /* the row then offers only the current look */ }
  const s = info.settings, inApp = !!window.pywebview?.api;
  const status = i => !i.library_exists ? `<span class="bad">This folder doesn't exist yet.</span> Saving creates it with a Poems folder inside.`
    : i.poems_exists ? `<span class="good">✓</span> Poems folder found · ${plural(i.series, "series")}`
    : `There's no Poems folder here yet. Saving creates one.`;
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker">Studio</p><h1 class="display">Settings</h1>
      <p class="lede">Stored in <code class="path">${esc(info.config_file)}</code></p></div></header>
    <form class="settings" id="sf">
      <section class="set"><div class="sh"><h2 class="h2">Library</h2><p class="muted">The folder Studio works in. Your poems live in its <b>Poems</b> folder, one folder per series.</p></div>
        <div class="sb"><label class="label" for="s-lib">Library folder</label>
          <div class="pathrow"><input class="input" id="s-lib" name="library" value="${esc(s.library)}" spellcheck="false" autocomplete="off">
            ${inApp ? `<button type="button" class="btn" id="s-pick">Choose…</button>` : ""}</div>
          <p class="hint" id="s-status">${status(info)}</p>
          ${info.env_library ? `<p class="hint bad">STUDIO_ART is set in the environment and overrides this (now ${esc(info.library)}).</p>` : ""}</div></section>
      <section class="set"><div class="sh"><h2 class="h2">Signature</h2><p class="muted">The name new poems and series are signed with. Each series can set its own under Details on its page.</p></div>
        <div class="sb"><label class="label" for="s-sig">Your name</label><input class="input big" id="s-sig" name="signature" value="${esc(s.signature)}" placeholder="Your name" autocomplete="off"></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Rendering</h2><p class="muted">Carousels and design exports are rendered by a Chromium browser (Chrome, Chromium or Edge), headless.</p></div>
        <div class="sb"><label class="label" for="s-ch">Browser to render with</label>
          <input class="input" id="s-ch" name="chrome" value="${esc(s.chrome)}" placeholder="${esc(info.chrome_found || "None found: enter the path to chrome, chromium or msedge")}" spellcheck="false">
          <p class="hint">${info.chrome_found ? `Using <code>${esc(info.chrome_found)}</code>. Leave empty to find one automatically.` : `<span class="bad">No Chrome, Chromium or Edge found.</span> Install one, or enter its path.`}</p></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Opening</h2><p class="muted">How Studio opens from its launcher, and the local port it listens on.</p></div>
        <div class="sb"><span class="label">Open Studio in</span>
          <div class="seg" id="s-open">${[["app", "Its own window"], ["browser", "My browser"]].map(([v, l]) => `<button type="button" data-open="${v}" aria-pressed="${s.open_with === v}">${l}</button>`).join("")}</div>
          <label class="label" for="s-port" style="margin-top:22px">Port</label><input class="input" id="s-port" name="port" type="number" min="1024" max="65535" value="${esc(s.port)}" style="max-width:160px">
          <p class="hint">A new port takes effect the next time Studio starts.</p></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Appearance</h2><p class="muted">Light, dark, or whatever your system is set to. The change applies at once.</p></div>
        <div class="sb"><span class="label">Theme</span>
          <div class="seg" id="s-theme">${[["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) => `<button type="button" data-theme-set="${v}" aria-pressed="${(s.theme || "system") === v}">${l}</button>`).join("")}</div></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Spelling</h2><p class="muted">The language Studio's own window checks spelling in, everywhere: poems, books and designs alike.</p></div>
        <div class="sb"><label class="label" for="s-spell">Check spelling in</label>${spellingPick(s.spelling || "auto")}
          <p class="hint">${inApp ? "Takes effect the next time Studio starts." : "For Studio's own window, from the next time it starts. A browser checks spelling in its own languages."}</p></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Default look</h2><p class="muted">The look new series and poems start from. <a href="#/styles/looks">Edit looks</a></p></div>
        <div class="sb"><label class="label" for="s-look">Look</label>
          <select class="select" id="s-look" style="max-width:320px">${(looks.some(l => l.name === s.default_look) ? looks : [...looks, {name: s.default_look}]).map(l => `<option ${l.name === s.default_look ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Examples</h2><p class="muted">A small series of example poems with designs, to try Studio with. Removing them moves them to the trash folder in Poems.</p></div>
        <div class="sb"><button type="button" class="btn" id="s-ex">${info.has_examples ? "Remove examples" : "Add examples"}</button></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Updates</h2><p class="muted">Studio asks GitHub once a day whether a newer release exists. It sends nothing about you.</p></div>
        <div class="sb">
          <label class="switch"><input type="checkbox" id="s-upd" ${s.update_check ? "checked" : ""}><span>Check for updates</span></label>
          <div class="updline" id="s-updline"></div></div></section>
      <div class="setfoot"><button class="btn solid" type="submit">Save settings</button><span class="muted" id="s-saved"></span></div>
    </form>`;
  const paintUpdate = u => {
    const host = $("#s-updline");
    host.innerHTML = u ? `${updateFailed(u)}<p class="hint" style="margin-top:14px">${updateLine(u)}${u.error && !u.available ? ` · <span class="muted">couldn’t reach GitHub</span>` : ""}</p>
      <div class="updrow">${updateActions(u)} <button type="button" class="btn quiet small" data-check>Check now</button></div>` : "";
    host.querySelector("[data-update]")?.addEventListener("click", () => applyUpdate(host, () => paintUpdate(u)));
    host.querySelector("[data-check]")?.addEventListener("click", async () => {
      try { paintUpdate(await api("/api/update/check", {})); } catch (e) { toast(e.message, true); }
    });
  };
  paintUpdate(upd);
  $("#s-upd").onchange = async e => {
    try { await api("/api/settings", {update_check: e.target.checked}); } catch (err) { toast(err.message, true); e.target.checked = !e.target.checked; }
  };
  const spell = $("#s-spell"), spellCode = $("#s-spell-code");
  const saveSpelling = async (v, name) => {
    try { await api("/api/settings", {spelling: v}); toast(`Studio checks spelling in ${name} from its next start`); }
    catch (err) { toast(err.message, true); }
  };
  spell.onchange = () => {
    spellCode.hidden = !!spell.value;
    if (!spell.value) { spellCode.focus(); return; }
    saveSpelling(spell.value, spell.value === "auto" ? "the language of the book you wrote in last" : spell.selectedOptions[0].textContent);
  };
  spellCode.onchange = () => { const v = spellCode.value.trim(); if (v) saveSpelling(v, v); };
  $("#s-look").onchange = async e => {
    try { await api("/api/settings", {default_look: e.target.value}); toast(`${e.target.value} is now the default look`); }
    catch (err) { toast(err.message, true); }
  };
  $$("[data-theme-set]").forEach(b => b.onclick = async () => {
    const was = document.documentElement.dataset.theme || "system", v = b.dataset.themeSet;
    document.documentElement.dataset.theme = v;
    $$("[data-theme-set]").forEach(x => x.setAttribute("aria-pressed", x === b));
    try { await api("/api/settings", {theme: v}); } catch (err) {
      document.documentElement.dataset.theme = was; toast(err.message, true);
      $$("[data-theme-set]").forEach(x => x.setAttribute("aria-pressed", x.dataset.themeSet === was));
    }
  });
  $("#s-ex").onclick = async e => {
    const b = e.currentTarget, removing = b.textContent === "Remove examples";
    b.disabled = true;
    try {
      const r = await api(removing ? "/api/examples/remove" : "/api/examples", {});
      state.home = null; b.textContent = removing ? "Add examples" : "Remove examples";
      toast(removing ? (r.removed ? "Examples moved to the trash" : "No examples to remove") : (r.added ? "Examples added" : "The examples are already there"));
    } catch (err) { toast(err.message, true); }
    b.disabled = false;
  };
  let openWith = s.open_with;
  $$("[data-open]").forEach(b => b.onclick = () => { openWith = b.dataset.open; $$("[data-open]").forEach(x => x.setAttribute("aria-pressed", x === b)); });
  if (inApp) $("#s-pick").onclick = async () => { const p = await window.pywebview.api.pick_folder($("#s-lib").value); if (p) $("#s-lib").value = p; };
  $("#sf").onsubmit = async e => {
    e.preventDefault();
    const f = new FormData($("#sf"));
    try {
      const r = await api("/api/settings", {library: f.get("library"), signature: f.get("signature"), chrome: f.get("chrome"), port: +f.get("port"), open_with: openWith, create: true});
      state.home = null;
      if (r.library !== info.library) {       // another library: its own fonts, looks and palettes
        info = r; SD = null;
        await refreshFonts().catch(() => toast("The fonts of the new library didn't load. Reload Studio to see them", true));
      }
      $("#s-status").innerHTML = status(r);
      $("#s-saved").textContent = "Saved";
      toast("Settings saved");
    } catch (err) { toast(err.message, true); }
  };
}

/* ——— info: everything about running Studio and connecting Claude, in the app ——— */
async function showInfo() {
  state.view = "info"; setNav("info"); document.title = "Info — Studio";
  let a, upd;
  try { a = await api("/api/about"); } catch (e) { app.innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  try { upd = await api("/api/update"); } catch { upd = null; }
  const code = (txt, id) => `<div class="code"><pre id="${id}">${esc(txt)}</pre><button class="btn small" data-copy="${id}">Copy</button></div>`;
  const tools = [["list_poems", "the poems and their status"], ["read_poem", "text, drafts, notes, brief, renders, QA"], ["get_rules", "a series' rules (README.md)"],
    ["list_concepts", "a series' visual concepts"], ["write_brief", "write BRIEF.md"], ["set_slides", "choose the carousel's slides"], ["render", "render the carousel with the series' kit"],
    ["qa", "measure the renders: alignment, safe zones, phone size, the name"], ["get_design / save_design", "read and write designs in the Design tab"], ["render_design", "export a design"]];
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker">Studio ${esc(a.version)} · Python ${esc(a.python)}</p><h1 class="display">Info</h1>
      ${updateFailed(upd)}${upd?.available ? `<p class="updline" id="i-upd">${updateLine(upd)} <span class="updrow">${updateActions(upd)}</span></p>` : ""}
      <p class="lede">A local studio for poems and their artwork. Everything stays on this computer: your poems are plain files, and Claude works on them only when you ask.</p></div></header>
    <div class="info">
      <section class="set"><div class="sh"><h2 class="h2">Connect Claude</h2><p class="muted">Studio gives Claude a set of tools over MCP. Add it once; Claude starts Studio's MCP server itself.</p></div>
        <div class="sb">
          <span class="label">Claude Code (in a terminal)</span>${code(a.mcp.claude_code, "c1")}
          <span class="label">Claude Desktop (${esc(a.mcp.desktop_file)}) or a project's .mcp.json</span>${code(a.mcp.mcp_json, "c2")}
          <p class="hint">Then ask Claude, for example: <b>“make the carousel for my new poem”</b> or <b>“draft a 9:16 design for it”</b>. You see the work appear here as it happens.</p>
          <span class="label" style="margin-top:22px">The tools</span>
          <dl class="tools">${tools.map(([n, d]) => `<dt><code>${n}</code></dt><dd>${d}</dd>`).join("")}</dl></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Your files</h2><p class="muted">No database: Studio, you and Claude read and write the same folders.</p></div>
        <div class="sb"><dl class="kv"><dt>Library</dt><dd><code>${esc(a.library)}</code></dd><dt>Settings</dt><dd><code>${esc(a.config_file)}</code></dd><dt>Cache</dt><dd><code>${esc(a.cache)}</code></dd>
          <dt>Renders with</dt><dd><code>${esc(a.chrome || "no browser found: see Settings")}</code></dd><dt>Address</dt><dd><code>${esc(a.url)}</code></dd></dl>
          ${code(`Styles/            looks, palettes, fonts you added, rules.md
Poems/
  <Series>/
    series.json        name, tagline, palette, fonts, signature, checks
    README.md          the series' rules (Claude reads them first)
    CONCEPTS.md        its visual concepts (optional)
    _kit/build.py      its carousel renderer (optional)
    stamps/            reusable pieces for the Design tab
    <Poem>/
      poem.json        title, lines, slides, status
      drafts/          one file per saved version
      writing-notes.md
      BRIEF.md         Claude's brief
      designs/         Design tab files
      Design renders/  exported designs
      qa.json          the last QA
Books/
  <Book>/
    book.json          details, kind, features, order
    manuscript/        one Markdown file per piece
    images/, drafts/, editions/, sources.json, exports/`, "c4")}</div></section>
      <section class="set"><div class="sh"><h2 class="h2">Running Studio</h2><p class="muted">Studio is a small local server with its own window.</p></div>
        <div class="sb"><ul class="plain">
          <li><b>Launcher:</b> <code>studio install</code> adds Studio to the Start menu (Windows), Applications (macOS) or your app launcher (Linux), with its icon. On Windows, open it once and right-click its taskbar icon → <b>Pin to taskbar</b>.</li>
          <li><b>Browser:</b> <code>studio web --open</code> runs only the server and opens your browser. Choose the default in Settings.</li>
          <li><b>Command line:</b> <code>studio config</code> shows the settings; <code>studio config library="D:\\Poetry"</code> changes one.</li></ul></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Series and kits</h2><p class="muted">A series is a body of work with its own look and rules.</p></div>
        <div class="sb"><p>Create series from <b>New poem</b> or the Series page. A series with a <code>_kit/build.py</code> can render carousels: Studio imports it and uses its <code>RATIOS</code>, <code>VARIANTS</code>, <code>SCALE</code>, <code>build_html</code>, <code>shoot</code>, <code>contact_sheet</code> and <code>concept_names</code>. Without a kit, use the Design tab to make images by hand (or with Claude).</p></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Styles</h2><p class="muted">Looks, palettes, fonts and house rules.</p></div>
        <div class="sb"><p>Set a look once for the library; a series and a poem inherit it and can <b>Detach</b> to their own or <b>Link</b> back. Fonts come from twelve bundled families, Google Fonts, your own files and the computer. Claude reads the house rules first.</p></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Books</h2><p class="muted">A writing window for whole books.</p></div>
        <div class="sb"><p>Create a book from <b>New book</b>; its kind sets whether it has notes, sources and an index, and you can change that in the book's settings. A book is a folder, <code>Books/&lt;Book&gt;/</code>, with one Markdown file per piece, so any editor can open it. Import a .docx or Markdown file from the Books page, freeze an edition from the book's settings, and export a .docx, Markdown or zip from the shelf; each export also leaves a dated copy in the book's <code>exports</code> folder.</p></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Writing window keys</h2></div>
        <div class="sb"><dl class="kv keys">${[["Ctrl+K", "command palette: jump to a piece or run an action"], ["Ctrl+Shift+F", "focus mode"], ["Ctrl+\\", "show or hide the list of pieces"],
          ["Ctrl+F / Ctrl+H", "find / find and replace across the book"], ["Ctrl+S", "save now (it also saves after a pause)"], ["/", "insert menu: note, citation, scene break, epigraph, poem, image, page break"],
          ["Ctrl+B / Ctrl+I", "bold / italic"], ["Ctrl+Alt+F / Ctrl+Alt+M", "note / comment on the selection"], ["Shift+Alt+X", "index term for the selection"],
          ["Alt+Enter", "apply the fix for the style-sheet tip under the cursor"], ["Alt-click", "open a piece in a second pane"], ["Alt+Up / Alt+Down", "move the focused piece in the list of pieces"],
          ["Esc", "leave focus mode, close the second pane, return from the rail to the text"], ["Right-click", "everything else"]].map(([k, v]) => `<dt><kbd>${k}</kbd></dt><dd>${v}</dd>`).join("")}</dl></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Updates</h2><p class="muted">Settings → Updates.</p></div>
        <div class="sb"><p>Studio checks for a newer release once a day. Source installs pull and reinstall; the Windows app downloads the release and swaps its files. Nothing about you is sent.</p></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Design editor keys</h2></div>
        <div class="sb"><dl class="kv keys">${[["V T R O Y S L P A", "select, text, rectangle, ellipse, polygon, star, line, pen, arc"], ["Shift", "straight moves, square shapes, 15° turns"], ["Alt-drag", "copy"],
          ["Ctrl", "hold to stop snapping"], ["Space-drag", "pan"], ["Ctrl+wheel", "zoom"], ["Ctrl+G / Ctrl+Shift+G", "group / ungroup"], ["[ ]  Ctrl+[ ]", "back, forward / to back, to front"],
          ["Ctrl+D, C, V", "duplicate, copy, paste"], ["G", "guides"], ["Right-click", "everything else"]].map(([k, v]) => `<dt><kbd>${k}</kbd></dt><dd>${v}</dd>`).join("")}</dl></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Licence</h2></div>
        <div class="sb"><p>Studio is open source under the MIT licence. The twelve bundled open-licence typefaces (see Styles → Fonts) are under the SIL Open Font License (see <code>static/fonts</code>).</p></div></section>
    </div>`;
  $("#i-upd [data-update]")?.addEventListener("click", () => applyUpdate($("#i-upd .updrow"), showInfo));
  $$("[data-copy]").forEach(b => b.onclick = () => { navigator.clipboard?.writeText($("#" + b.dataset.copy).textContent); toast("Copied"); });
}

/* ——— right-click menus across the studio ——— */
async function quickStatus(id, status) {
  try { await api("/api/status", {id, status}); state.home = null; toast(status === "ready" ? "Ready for art" : `Status: ${status}`); route(); }
  catch (e) { toast(e.message, true); }
}
addEventListener("contextmenu", ev => {
  if (ev.target.closest(".edx, input, textarea, [contenteditable]")) return;   // the editor has its own; text fields keep the browser's
  const card = ev.target.closest("[data-pid]"), series = ev.target.closest("[data-series]"), fig = ev.target.closest("figure[data-n]"), draft = ev.target.closest("[data-draft]");
  if (card) {
    const id = card.dataset.pid, st = card.dataset.status;
    StudioMenu.open(ev, [
      {label: "Open", items: [["write", "Write"], ["art", "Art"], ["design", "Design"]].map(([t, l]) => ({label: l, act: () => { location.hash = poemHash(id, t); }}))},
      "-",
      ...(st === "draft" ? [{label: "Ready for art", act: () => quickStatus(id, "ready")}] : st === "ready" ? [{label: "Back to draft", act: () => quickStatus(id, "draft")}] : []),
      {label: "Status", items: STATUSES.map(s => ({label: s, checked: s === st, act: () => quickStatus(id, s)}))},
      "-",
      {label: "Move to trash…", danger: true, act: async () => {
        if (!confirm(`Move “${card.querySelector(".t")?.textContent || id}” to the trash? Its folder moves to Poems/.trash.`)) return;
        try { await api("/api/poem/delete", {id}); state.home = null; toast("Moved to the trash"); route(); } catch (e) { toast(e.message, true); }
      }},
    ]);
  } else if (series) {
    const name = series.dataset.series;
    StudioMenu.open(ev, [
      {label: "Open", act: () => { location.hash = seriesHash(name); }},
      {label: "New poem in " + name, act: () => newPoemDialog(name)},
      "-",
      {label: "Look", act: () => { location.hash = seriesHash(name, "look"); }},
      {label: "Rules", act: () => { location.hash = seriesHash(name, "rules"); }},
    ]);
  } else if (fig && state.poem) {
    const n = +fig.dataset.n, rel = fig.dataset.rel, a = state.poem.art;
    StudioMenu.open(ev, [
      {label: "Open the image", disabled: !rel, act: () => open(fileUrl(rel, fig.dataset.v), "_blank")},
      {label: "Open the preview page", disabled: !a.page, act: () => open(fileUrl(a.page), "_blank")},
      {label: "Copy the file path", disabled: !rel, act: () => { navigator.clipboard?.writeText(state.poem.path.slice(0, -state.poem.id.length) + rel.replace(/\//g, "\\")); toast("Path copied"); }},
      "-",
      {label: "Render this slide", disabled: !state.art || !!state.art.job, act: () => runJob("render", null, n)},
      {label: "Run QA on this slide", disabled: !state.art || !!state.art.job || !rel, act: () => runJob("qa", null, n)},
      "-",
      {label: "Open as an editable design", disabled: !a.page, act: () => { state.importSlide = {n, fmt: state.ratio}; state.tab = "design"; history.replaceState(null, "", poemHash(state.poem.id, "design")); lastHash = location.hash; renderHeader(); renderTab(); }},
    ]);
  } else if (draft && state.poem) {
    const d0 = state.poem.drafts.find(x => x.name === draft.dataset.draft);
    StudioMenu.open(ev, [
      {label: "Show this draft", act: () => { state.openDraft = d0.name; state.compare = false; renderDrafts(); }},
      {label: "Changes since this draft", act: () => { state.openDraft = d0.name; state.compare = true; renderDrafts(); }},
      "-",
      {label: "Restore into the editor", act: () => { if (d0.title) $("#title").value = d0.title; $("#text").value = d0.lines.join("\n"); state.dirty = true; analyse(); updateState(); renderDrafts(); toast("Restored into the editor. Save to keep it"); }},
    ]);
  }
});

/* The font registry first: the design renderer and the editor take families, weights and widths from it. */
async function loadFonts(tries = 4) {
  for (let i = 1; ; i++) {
    try { return Design.setFonts(await api("/api/fonts")); }
    catch (e) {
      if (i >= tries) return toast("The font list didn't load, so type may look wrong. Reload Studio to try again", true);
      await new Promise(r => setTimeout(r, 400 * i));
    }
  }
}
/* Start once every script has run (styles.js comes after this one and route() calls into it). */
const boot = async () => {
  await loadFonts();
  try { const info = await api("/api/settings"); if (info.first_run) await showWelcome(info); } catch { /* no welcome: go straight in */ }
  route();
};
document.readyState === "loading" ? addEventListener("DOMContentLoaded", boot) : boot();
setTimeout(poll, 2000);
