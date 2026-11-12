"use strict";
/* Studio front end: poems, series, and each poem's Write / Art / Design tabs. Plain JS, no build step.
   Everything is read from the files through the API; a quiet 2-second poll picks up Claude's changes. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = $("#app");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
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
};

async function api(path, body) {
  const opt = body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {};
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({error: r.statusText}));
  if (!r.ok) throw new Error(data.error || r.statusText);
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
  flushNotes();
  if (typeof Editor !== "undefined") Editor.unmount();
  document.body.classList.remove("designing", "focus");
  if (window.speechSynthesis) speechSynthesis.cancel();
}
function route() {
  const h = location.hash.slice(1) || "/";
  leaveTab();
  let m;
  if ((m = h.match(/^\/poem\/([^/]+)(?:\/(write|art|design))?$/))) return showPoem(decodeURIComponent(m[1]), m[2] || null);
  if ((m = h.match(/^\/series\/([^/]+)(?:\/(poems|look|rules|concepts))?$/))) return showSeries(decodeURIComponent(m[1]), m[2] || "poems");
  if (h === "/series") return showSeriesIndex();
  if (h === "/settings") return showSettings();
  if (h === "/info") return showInfo();
  return showHome();
}
addEventListener("hashchange", () => {
  if (ignoreHash) { ignoreHash = false; return; }
  if (state.dirty && !confirm("The poem has unsaved changes. Leave without saving?")) {
    ignoreHash = true; location.hash = lastHash; return;
  }
  state.dirty = false;
  lastHash = location.hash;
  route();
});
addEventListener("beforeunload", e => {
  if (state.dirty || (typeof Editor !== "undefined" && Editor.pending())) { e.preventDefault(); e.returnValue = ""; }
});

/* ——— shared pieces ——— */
const swatchBar = pal => `<div class="swatches">${(pal || []).map(c => `<span style="background:${esc(c.hex)}"></span>`).join("")}</div>`;
const palOf = name => (state.home?.series || []).find(s => s.name === name)?.palette || [{hex: "#0C0E11"}, {hex: "#EEEAE2"}, {hex: "#DA291C"}];

function poemCard(p) {
  const pal = palOf(p.series), bg = pal[0]?.hex, ink = pal[1]?.hex, accent = pal[2]?.hex || ink;
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

async function showHome() {
  state.view = "home"; setNav("poems"); document.title = "Studio";
  try { const d = await loadHome(); state.stamp = d.stamp; renderHome(); }
  catch (e) { app.innerHTML = `<p class="empty">Couldn't read the poems: ${esc(e.message)}</p>`; }
}

function renderHome() {
  const d = state.home;
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker">${d.signature ? esc(d.signature) + " · " : ""}${plural(d.poems.length, "poem")} in ${plural(d.series.length, "series")}</p>
      <h1 class="display">Poems</h1></div></header>
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
  $("#grid").innerHTML = list.map(poemCard).join("") || `<p class="noresults">${d.poems.length ? "Nothing matches." : "No poems yet. Start one with New poem."}</p>`;
}

/* ——— series ——— */
async function showSeriesIndex() {
  state.view = "seriesIndex"; setNav("series"); document.title = "Series — Studio";
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
  state.view = "series"; setNav("series");
  try {
    const [s] = await Promise.all([api("/api/series?name=" + encodeURIComponent(name)), state.home ? null : loadHome()]);
    state.series = s; state.stamp = s.stamp; state.seriesTab = tab;
    renderSeries();
  } catch (e) { app.innerHTML = `<header class="pagehead"><h1 class="display">Not found</h1></header><p class="empty">${esc(e.message)}</p>`; }
}

function renderSeries() {
  const s = state.series, tab = state.seriesTab;
  document.title = `${s.name} — Studio`;
  const tabs = [["poems", `Poems · ${s.poems.length}`], ["look", "Look"], ["rules", "Rules"], ["concepts", "Concepts"]]
    .filter(([k]) => k !== "concepts" || s.concepts);
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
  } else if (tab === "look") {
    const sample = s.poems.find(p => p.first_line)?.first_line || s.name;
    st.innerHTML = `<section class="section"><span class="label">Palette · click a colour to copy it</span><div class="palette">${
      s.palette.map(c => `<button class="sw" data-hex="${esc(c.hex)}"><span class="c" style="background:${esc(c.hex)}"></span><b>${esc(c.name)}</b><span>${esc(c.hex)}</span></button>`).join("")}</div></section>
      <section class="section"><span class="label">Type</span><div class="specimens">${s.fonts.map(f => `<div class="spec"><span class="label">${esc(f.family)}${f.role ? " · " + esc(f.role) : ""}</span>
        <p class="big" style="font-family:'${esc(f.family)}';font-weight:${f.family === "Archivo" ? 900 : 500};${f.family === "Archivo" ? "text-transform:uppercase;letter-spacing:-.01em" : ""}">${esc(sample)}</p>
        <p style="font-family:'${esc(f.family)}'">Aa Bb Cc 0123 — ${f.family === "Archivo" ? "the command" : "the measured voice"}</p></div>`).join("")}</div></section>
      <section class="section"><span class="label">Formats</span><p class="muted">${s.formats.map(esc).join(" · ")} · signed “${esc(s.signature)}” and unsigned</p></section>`;
    $$("[data-hex]").forEach(b => b.onclick = () => { navigator.clipboard?.writeText(b.dataset.hex); toast(`Copied ${b.dataset.hex}`); });
  } else {
    const src = tab === "rules" ? s.rules : s.concepts;
    st.innerHTML = src ? `<div class="doc md" style="border:0;padding:0">${md(src)}</div>` : `<p class="empty">No ${tab} written for ${esc(s.name)} yet.</p>`;
  }
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

async function newPoemDialog(preset) {
  const d = state.home || await loadHome();
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
      <div><span class="label">Palette</span>${palettePick(d.palettes)}</div></fieldset>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Create poem</button></div></form>`,
  async f => {
    let series = f.get("series");
    if (series === "__new") {
      const s = await api("/api/series", {name: f.get("sname"), tagline: f.get("stag"), palette: f.get("palette")});
      series = s.name;
    }
    const p = await api("/api/poems", {title: f.get("title"), series});
    state.home = null;
    location.hash = poemHash(p.id, "write");
  });
  $$("input[name=series]", form).forEach(r => r.onchange = () => { $("#ns", form).hidden = r.value !== "__new" || !r.checked; });
}

async function newSeriesDialog() {
  const d = state.home || await loadHome();
  openDialog(`<form>
    <h2>New series</h2>
    <label><span class="label">Name</span><input class="input big" name="name" required autocomplete="off" placeholder="e.g. Night Letters"></label>
    <label><span class="label">Tagline</span><input class="input" name="tagline" autocomplete="off" placeholder="One line on what the series is"></label>
    <div><span class="label">Palette · you can change it later in series.json</span>${palettePick(d.palettes)}</div>
    <p class="muted" style="margin:0">Studio creates <b>Poems/&lt;name&gt;/</b> with a series.json and a README for its rules. Ask Claude to build a carousel kit for it when you're ready.</p>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Create series</button></div></form>`,
  async f => {
    const s = await api("/api/series", {name: f.get("name"), tagline: f.get("tagline"), palette: f.get("palette")});
    state.home = null;
    location.hash = seriesHash(s.name);
  });
}
$("#newpoem").onclick = () => newPoemDialog();

/* ——— poem ——— */
async function showPoem(id, tab) {
  state.view = "poem"; setNav("poems");
  try {
    const p = await api("/api/poem?id=" + encodeURIComponent(id));
    const fresh = !state.poem || state.poem.id !== p.id;
    state.poem = p; state.stamp = p.stamp;
    if (fresh) Object.assign(state, {dirty: false, notesDirty: false, openDraft: null, compare: false, savedAt: null});
    state.tab = tab || (["draft", "ready"].includes(p.status) ? "write" : "art");
    renderPoem();
  } catch (e) {
    state.view = "missing";
    app.innerHTML = `<header class="pagehead"><h1 class="display">Not found</h1></header><p class="empty">${esc(e.message)} <a href="#/">Back to the poems</a></p>`;
  }
}

function renderPoem() {
  app.innerHTML = `<header class="poemhead"><div class="kicker" id="pkicker"></div>
      <div class="titlerow"><h1 class="display" id="ptitle"></h1>
        <div class="titleside"><ol class="steps" id="steps" aria-label="Status"></ol>
          <div class="pmenu"><button class="btn quiet small" id="pmore" aria-haspopup="true" title="More">•••</button>
            <div class="pop" id="ppop" hidden><button id="pdel">Move to trash…</button></div></div></div></div>
      <nav class="tabs" role="tablist">${[["write", "Write"], ["art", "Art"], ["design", "Design"]].map(([k, l]) =>
        `<button role="tab" data-tab="${k}">${l}</button>`).join("")}</nav></header>
    <div id="tab"></div>`;
  $("#pmore").onclick = ev => { ev.stopPropagation(); $("#ppop").hidden = !$("#ppop").hidden; };
  $("#pdel").onclick = deletePoem;
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
    location.hash = "#/";
  } catch (e) { toast(e.message, true); }
}
addEventListener("click", e => { const pop = $("#ppop"); if (pop && !pop.hidden && !e.target.closest(".pmenu")) pop.hidden = true; });

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
    return Editor.mount($("#tab"), {poem: state.poem, api, toast, md, back: poemHash(state.poem.id, state.lastTab || "write"), importSlide: imp});
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
  const colours = ["var(--red)", "var(--paper-dim)", "var(--fog)", "rgba(218,41,28,.5)"];
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
    : p.status === "ready" ? `<span class="muted" style="font-size:13px">Ready. Ask Claude: “make the carousel for ${esc(p.title)}”</span> <button class="btn quiet small" id="unready">Back to draft</button>` : "";
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

/* ——— art ——— */
function renderArt() {
  const p = state.poem, a = p.art, tab = $("#tab");
  if (a.no_kit) {
    tab.innerHTML = `<p class="empty">${esc(p.series)} has no carousel kit yet, so there's nothing to render. Use the <b>Design</b> tab to make images by hand, or ask Claude to build a kit for the series.</p>${designShots()}`;
    wireViewer(tab);
    return;
  }
  if (a.error) { tab.innerHTML = `<p class="empty">The series' render engine can't be read: ${esc(a.error)}</p>`; return; }
  if (!a.formats[state.ratio]) state.ratio = a.order[0];
  const f = a.formats[state.ratio];
  const anyArt = Object.values(a.formats).some(x => x.slides.some(s => s.signed || s.unsigned));
  const ask = `“make the carousel for ${esc(p.title)}”`;
  const seg = (attr, items, cur) => items.map(([v, label]) => `<button ${attr}="${v}" aria-pressed="${v === cur}">${label}</button>`).join("");
  const ratioLabels = {"45": "4:5 Feed", "11": "1:1 X", "916": "9:16 Story"};
  tab.innerHTML = `
    <div class="toolbar">
      <div class="seg" role="group" aria-label="Name">${seg("data-sig", [["1", "With name"], ["0", "Without"]], state.signed ? "1" : "0")}</div>
      <div class="seg" role="group" aria-label="Format">${seg("data-ratio", a.order.map(r => [r, ratioLabels[r] || a.formats[r].label]), state.ratio)}</div>
      <div class="links">${a.page ? `<a href="${fileUrl(a.page, p.stamp | 0)}" target="_blank" rel="noopener">Preview page ↗</a>` : ""}
        ${a.sheet ? `<a href="${fileUrl(a.sheet, p.stamp | 0)}" target="_blank" rel="noopener">Contact sheet ↗</a>` : ""}</div>
    </div>
    ${a.stale ? `<p class="notice">The text or the slides changed since this was rendered. Ask Claude to render it again.</p>` : ""}
    ${!anyArt ? `<p class="empty">${p.status === "draft"
        ? `No artwork yet. When the poem is done, mark it <b>Ready for art</b>, then ask Claude: <b>${ask}</b>.`
        : `No artwork yet. Ask Claude: <b>${ask}</b>. The slides appear here as soon as they're rendered.`}</p>`
      : `<div class="slides">${f.slides.map(s => slideCard(s, f)).join("")}</div>`}
    ${designShots()}
    <div class="docs">
      <section class="doc"><span class="label">Brief</span>
        ${p.brief ? `<div class="md">${md(p.brief)}</div>` : `<p class="muted">No brief yet. Claude writes one before making the carousel.</p>`}</section>
      ${p.notes ? `<section class="doc"><span class="label">Posting notes</span><div class="md">${md(p.notes)}</div></section>` : ""}
    </div>`;
  $$("[data-sig]", tab).forEach(b => b.onclick = () => { state.signed = b.dataset.sig === "1"; pref.set("signed", b.dataset.sig); renderArt(); });
  $$("[data-ratio]", tab).forEach(b => b.onclick = () => { state.ratio = b.dataset.ratio; pref.set("ratio", b.dataset.ratio); renderArt(); });
  wireViewer(tab);
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
    const {stamp} = await api("/api/stamp" + q);
    if (state.offline) { state.offline = false; toast("Studio is back"); }
    if (stamp !== state.stamp) {
      if (state.view === "poem") applyFresh(await api("/api/poem?id=" + encodeURIComponent(state.poem.id)));
      else if (state.view === "series") { state.series = await api("/api/series?name=" + encodeURIComponent(state.series.name)); state.stamp = state.series.stamp; if (!document.activeElement?.isContentEditable) renderSeries(); }
      else if (state.view === "home") { const d = await loadHome(); state.stamp = d.stamp; renderGrid(); }
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
async function showSettings() {
  state.view = "settings"; setNav("settings"); document.title = "Settings — Studio";
  let info;
  try { info = await api("/api/settings"); } catch (e) { app.innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
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
      <section class="set"><div class="sh"><h2 class="h2">Signature</h2><p class="muted">The name new poems and series are signed with. Each series can change its own in series.json.</p></div>
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
      <div class="setfoot"><button class="btn solid" type="submit">Save settings</button><span class="muted" id="s-saved"></span></div>
    </form>`;
  let openWith = s.open_with;
  $$("[data-open]").forEach(b => b.onclick = () => { openWith = b.dataset.open; $$("[data-open]").forEach(x => x.setAttribute("aria-pressed", x === b)); });
  if (inApp) $("#s-pick").onclick = async () => { const p = await window.pywebview.api.pick_folder($("#s-lib").value); if (p) $("#s-lib").value = p; };
  $("#sf").onsubmit = async e => {
    e.preventDefault();
    const f = new FormData($("#sf"));
    try {
      const r = await api("/api/settings", {library: f.get("library"), signature: f.get("signature"), chrome: f.get("chrome"), port: +f.get("port"), open_with: openWith, create: true});
      state.home = null;
      $("#s-status").innerHTML = status(r);
      $("#s-saved").textContent = "Saved";
      toast("Settings saved");
    } catch (err) { toast(err.message, true); }
  };
}

/* ——— info: everything about running Studio and connecting Claude, in the app ——— */
async function showInfo() {
  state.view = "info"; setNav("info"); document.title = "Info — Studio";
  let a;
  try { a = await api("/api/about"); } catch (e) { app.innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  const code = (txt, id) => `<div class="code"><pre id="${id}">${esc(txt)}</pre><button class="btn small" data-copy="${id}">Copy</button></div>`;
  const tools = [["list_poems", "the poems and their status"], ["read_poem", "text, drafts, notes, brief, renders, QA"], ["get_rules", "a series' rules (README.md)"],
    ["list_concepts", "a series' visual concepts"], ["write_brief", "write BRIEF.md"], ["set_slides", "choose the carousel's slides"], ["render", "render the carousel with the series' kit"],
    ["qa", "measure the renders: alignment, safe zones, phone size, the name"], ["get_design / save_design", "read and write designs in the Design tab"], ["render_design", "export a design"]];
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker">Studio ${esc(a.version)} · Python ${esc(a.python)}</p><h1 class="display">Info</h1>
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
          ${code(`Poems/
  <Series>/
    series.json        name, tagline, palette, fonts, signature
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
      qa.json          the last QA`, "c4")}</div></section>
      <section class="set"><div class="sh"><h2 class="h2">Running Studio</h2><p class="muted">Studio is a small local server with its own window.</p></div>
        <div class="sb"><ul class="plain">
          <li><b>Launcher:</b> <code>studio install</code> adds Studio to the Start menu (Windows), Applications (macOS) or your app launcher (Linux), with its icon. On Windows, open it once and right-click its taskbar icon → <b>Pin to taskbar</b>.</li>
          <li><b>Browser:</b> <code>studio web --open</code> runs only the server and opens your browser. Choose the default in Settings.</li>
          <li><b>Command line:</b> <code>studio config</code> shows the settings; <code>studio config library="D:\\Poetry"</code> changes one.</li></ul></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Series and kits</h2><p class="muted">A series is a body of work with its own look and rules.</p></div>
        <div class="sb"><p>Create series from <b>New poem</b> or the Series page. A series with a <code>_kit/build.py</code> can render carousels: Studio imports it and uses its <code>RATIOS</code>, <code>VARIANTS</code>, <code>SCALE</code>, <code>build_html</code>, <code>shoot</code>, <code>contact_sheet</code> and <code>concept_names</code>. Without a kit, use the Design tab to make images by hand (or with Claude).</p></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Design editor keys</h2></div>
        <div class="sb"><dl class="kv keys">${[["V T R O Y S L P A", "select, text, rectangle, ellipse, polygon, star, line, pen, arc"], ["Shift", "straight moves, square shapes, 15° turns"], ["Alt-drag", "copy"],
          ["Ctrl", "hold to stop snapping"], ["Space-drag", "pan"], ["Ctrl+wheel", "zoom"], ["Ctrl+G / Ctrl+Shift+G", "group / ungroup"], ["[ ]  Ctrl+[ ]", "back, forward / to back, to front"],
          ["Ctrl+D, C, V", "duplicate, copy, paste"], ["G", "guides"], ["Right-click", "everything else"]].map(([k, v]) => `<dt><kbd>${k}</kbd></dt><dd>${v}</dd>`).join("")}</dl></div></section>
      <section class="set"><div class="sh"><h2 class="h2">Licence</h2></div>
        <div class="sb"><p>Studio is open source under the MIT licence. The bundled typefaces, Newsreader and Archivo, are under the SIL Open Font License (see <code>static/fonts</code>).</p></div></section>
    </div>`;
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

route();
setTimeout(poll, 2000);
