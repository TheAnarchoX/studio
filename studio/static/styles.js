"use strict";
/* Studio's Styles pages: looks, palettes, fonts and the house rules. A classic script after app.js.
   Globals for other views: showStyles(tab), palettePicker(current, onPick, {series}?), fontPicker(current, onPick, {pinned}). */

/* ——— the library's styles (/api/styles), kept for the pages and pickers ——— */
let SD = null;
async function loadStyles() { return SD = await api("/api/styles"); }
const palByName = name => SD?.palettes.find(p => p.name === name) || null;
const stKey = s => String(s || "").trim().replace(/\s+/g, " ").toLowerCase();

/* ——— colour ——— */
const HEX6 = /^#[0-9a-f]{6}$/i;
function lum(hex) {
  const c = i => { const v = parseInt(hex.slice(i, i + 2), 16) / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * c(1) + 0.7152 * c(3) + 0.0722 * c(5);
}
function contrastOf(a, b) { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return Math.round((hi + 0.05) / (lo + 0.05) * 100) / 100; }
const onSwatch = hex => lum(hex) > 0.4 ? "#0C0E11" : "#EEEAE2";     // legible ink on a swatch
const ROLE_LABEL = {background: "Background", text: "Text", accent: "Accent", muted: "Muted"};
/* The same rule as the server: text and accent on the background need 4.5:1. */
function paletteWarnings(sw) {
  const by = {};
  for (const s of sw) if (HEX6.test(s.hex) && s.role && !by[s.role]) by[s.role] = s;
  const out = [];
  for (const role of ["text", "accent"]) {
    if (!by.background || !by[role]) continue;
    const r = contrastOf(by[role].hex, by.background.hex);
    if (r < 4.5) out.push(`${ROLE_LABEL[role]} on background (${by[role].name || by[role].hex} on ${by.background.name || by.background.hex}) is ${r}:1; small text needs 4.5:1.`);
  }
  return out;
}
const stripHtml = (sw, labels) => `<div class="st-strip">${sw.map(s => `<span style="background:${esc(s.hex)};color:${onSwatch(s.hex)}" title="${esc((s.name || s.hex) + " · " + s.hex)}">${
  labels && s.role ? `<i>${ROLE_LABEL[s.role]}</i>` : ""}</span>`).join("")}</div>`;

/* ——— fonts ——— */
const WEIGHT_NAME = {100: "Thin", 200: "Extra light", 300: "Light", 400: "Regular", 500: "Medium", 600: "Semibold", 700: "Bold", 800: "Extra bold", 900: "Black"};
const CATEGORY_NAME = {serif: "Serif", sans: "Sans serif", display: "Display", hand: "Handwriting", mono: "Monospace"};
const SOURCE_NAME = {bundled: "Built in", google: "Google Fonts", file: "Added file", system: "This computer"};
const fontStack = name => `'${String(name).replace(/['\\]/g, "")}'`;
function weightsFor(fam) {
  const f = typeof fam === "string" ? Design.family(fam) : fam;
  if (!f) return [400, 700];
  if (f.files?.some(x => x.axes?.wght) || (f.wght && f.wght[1] > f.wght[0])) {
    const [lo, hi] = f.wght || [100, 900];
    const out = [];
    for (let w = 100; w <= 900; w += 100) if (w >= lo && w <= hi) out.push(w);
    return out.length ? out : [Math.round(lo)];
  }
  return [...new Set((f.files || []).map(x => x.weight))].sort((a, b) => a - b);
}
const weightText = f => {
  if (f.files?.some(x => x.axes?.wght) || (f.wght && f.wght[1] > f.wght[0])) return `${f.wght[0]}–${f.wght[1]}`;
  return weightsFor(f).join(" · ");
};
async function refreshFonts() {
  // a font added or removed, or another library: the registry for the pages, and the @font-face rules for the browser
  Design.setFonts(await api("/api/fonts"));
  lookSlides.clear();
  const link = $('link[href^="/api/fonts.css"]');
  if (link) {
    const next = link.cloneNode();
    next.href = "/api/fonts.css?v=" + Date.now();
    next.onload = () => link.remove();
    link.after(next);
  }
}

/* Runs `fn` once when the dialog closes: when its form submits (the dialog closes right after) or, by `close`, when it is dismissed. */
function onDialogClose(fn, dlg = $("#dlg")) {
  let done = false;
  const run = () => { if (!done) { done = true; fn(); } };
  dlg.addEventListener("close", run, {once: true});
  return run;
}

/* Like openDialog, but when #dlg is already open (a picker's "New palette..." inside the look editor) the form goes in a second
   <dialog> stacked above it, so the dialog underneath keeps its content and state. Returns {form, dlg}. */
function openLayer(html, onSubmit) {
  const base = $("#dlg");
  if (!base.open) return {form: openDialog(html, onSubmit), dlg: base};
  const dlg = document.createElement("dialog");
  dlg.className = "modal";
  dlg.innerHTML = html;
  document.body.appendChild(dlg);
  dlg.addEventListener("close", () => dlg.remove(), {once: true});
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
  return {form, dlg};
}

/* ——— page ——— */
const STYLE_TABS = [["looks", "Looks"], ["palettes", "Palettes"], ["fonts", "Fonts"], ["rules", "House rules"]];
let styleToken = 0;

async function showStyles(tab = "looks") {
  const my = ++styleToken;
  state.view = "styles"; setNav("styles"); document.title = "Styles — Studio";
  app.innerHTML = `
    <header class="pagehead"><div><p class="kicker">Studio</p><h1 class="display">Styles</h1>
      <p class="lede">The palettes, fonts and looks every series and poem draws from.</p></div>
      <div class="actions" id="st-actions"></div></header>
    <nav class="tabs" aria-label="Styles">${STYLE_TABS.map(([k, l]) => `<a href="#/styles/${k}" aria-selected="${k === tab}">${l}</a>`).join("")}</nav>
    <div id="st-body"><p class="muted">Loading…</p></div>`;
  try { await loadStyles(); }
  catch (e) { $("#st-body").innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  if (my !== styleToken) return;
  const paint = () => (({looks: paintLooks, palettes: paintPalettes, fonts: paintFonts, rules: paintRules})[tab] || paintLooks)(() => my === styleToken);
  styleRepaint = async () => { await loadStyles(); if (my === styleToken && state.view === "styles" && $("#st-body")) paint(); };
  paint();
}
let styleRepaint = async () => {};
/* Called when the view changes: a later save from a dialog elsewhere must not paint into another page. */
function leaveStyles() { styleToken++; styleRepaint = async () => { await loadStyles(); }; }
const actionsHost = html => { const h = $("#st-actions"); if (h) h.innerHTML = html; return h; };

/* ——— looks ——— */
const SAMPLE_BOOK = ["The light comes in low", "across the table, the cups,", "the hands. Nobody speaks.", "The kettle ticks as it cools", "and a gate outside swings",
  "once, and settles.", "We have been here before,", "in other rooms, other days,", "and the quiet is the same:", "patient, a little warm."];
const SAMPLE_SLIDE = ["The light comes in", "low across the table,", "and nobody speaks."];
const SAMPLE_TITLE = "First light";

/* A 4:5 sample slide in the look: the Page starter in the look's colours and fonts, with a title in its display face.
   {wait: false} lays it out with the font metrics at hand (see drawLook). */
async function lookDesign(look, {wait = true} = {}) {
  const pal = Design.colours(palByName(look.palette)), F = Design.FORMATS["45"], S = Design.SAFE["45"], m = S.s;
  const d = await Design.starter("page", "45", {lines: SAMPLE_SLIDE, colours: pal, fonts: look.fonts, signature: "Your name", title: look.name, wait});
  const [poem, sig] = d.elements, f = look.fonts;
  const setFont = (e, x) => { e.font = x.family; e.weight = x.weight; if (x.width) e.stretch = x.width; else delete e.stretch; };
  setFont(poem, f.text); setFont(sig, f.label);
  Object.assign(poem, {size: 104, leading: 1.2, tracking: 0, italic: false});
  Object.assign(sig, {italic: false, case: "upper", tracking: 220, size: 26, color: pal.muted});
  const title = {id: Design.uid(), type: "text", name: "Title", text: SAMPLE_TITLE, size: 150, leading: 1, tracking: -10, color: pal.accent, x: poem.x, y: 0};
  setFont(title, f.display);
  d.elements.unshift(title);
  await Design.ready(d, {wait});
  const room = F.w - 2 * (m + 32);
  for (const e of [title, poem]) if (Design.layout(e).w > room) await Design.fitWidth(e, room, {wait});
  const gapT = 70, gapS = poem.size * .8;
  const total = Design.layout(title).h + gapT + Design.layout(poem).h + gapS + Design.layout(sig).h;
  title.y = S.t + (F.h - S.t - S.b - total) / 2;
  poem.y = title.y + Design.layout(title).h + gapT;
  sig.y = poem.y + Design.layout(poem).h + gapS;
  return d;
}

/* Draws the look's sample slide into `host`, `width` wide: at once with the metrics at hand, then exactly once they
   are in (a fresh install measures them first). The exact slide is made once per look and palette (pages repaint
   often); refreshFonts forgets them. */
const lookSlides = new Map(), lookDone = new WeakSet();
function drawLook(host, look, width) {
  const key = JSON.stringify([look, palByName(look.palette)?.swatches]);
  let exact = lookSlides.get(key);
  if (!exact) {
    exact = lookDesign(look);
    lookSlides.set(key, exact);
    exact.then(() => lookDone.add(exact), () => lookSlides.delete(key));
  }
  let done = lookDone.has(exact);
  const put = d => { if (d && host.isConnected) host.replaceChildren(Design.thumb(d, width)); };
  exact.then(d => { done = true; put(d); }, () => { done = true; if (!host.firstChild) host.classList.add("none"); });
  if (!done) lookDesign(look, {wait: false}).then(d => { if (!done) put(d); }).catch(() => {});
}

function bookPage(look) {
  const pal = Design.colours(palByName(look.palette)), f = look.fonts;
  const face = x => esc(`font-family:${fontStack(x.family)};font-weight:${+x.weight || 400};${+x.width ? `font-stretch:${+x.width}%;` : ""}`);
  return `<div class="st-book" style="background:${esc(pal.background)};color:${esc(pal.text)}">
    <span class="run" style="${face(f.label)}color:${esc(pal.muted)}">${esc(SAMPLE_TITLE)}</span>
    <h4 style="${face(f.display)}color:${esc(pal.accent)}">${esc(SAMPLE_TITLE)}</h4>
    <p style="${face(f.text)}">${SAMPLE_BOOK.map(esc).join("<br>")}</p></div>`;
}

const fontLine = f => [...new Set(["display", "text", "label"].map(r => f[r]?.family).filter(Boolean))].join(" · ");

function paintLooks(live) {
  actionsHost(`<button class="btn" id="st-newlook" type="button"><span class="plus">+</span> New look</button>`).querySelector("#st-newlook").onclick = () => lookEditor(null);
  const body = $("#st-body"), used = SD.used.looks || {};
  body.innerHTML = `<div class="st-looks">${SD.looks.map(l => {
    const isDefault = stKey(l.name) === stKey(SD.default_look), users = used[l.name] || [];
    return `<article class="st-look" data-look="${esc(l.name)}">
      <div class="prev"><div class="slide" aria-hidden="true"></div>${bookPage(l)}</div>
      <div class="meta"><h3 class="name">${esc(l.name)}</h3>
        <p class="muted">${esc(l.palette || "No palette")} · ${esc(fontLine(l.fonts))}</p>
        <p class="muted small">${[isDefault ? "Default look" : "", l.source === "own" ? (l.edited ? "Your edit of a built-in look" : "Yours") : "Built in", users.length ? "Used in " + users.map(esc).join(", ") : ""].filter(Boolean).join(" · ")}</p>
        <div class="acts">${isDefault ? "" : `<button class="btn small" type="button" data-act="default">Use as default</button>`}
          <button class="btn small quiet" type="button" data-act="edit">Edit</button>
          <button class="btn small quiet" type="button" data-act="more" aria-label="More actions for ${esc(l.name)}" aria-haspopup="menu">More</button></div></div></article>`;
  }).join("")}</div>`;
  for (const card of $$(".st-look", body)) {
    const look = SD.looks.find(l => l.name === card.dataset.look);
    drawLook($(".slide", card), look, 200);
    const items = () => lookMenu(look);
    card.addEventListener("contextmenu", ev => StudioMenu.open(ev, items()));
    $$("[data-act]", card).forEach(b => b.onclick = ev => {
      if (b.dataset.act === "default") return setDefaultLook(look.name);
      if (b.dataset.act === "edit") return lookEditor(look);
      const r = b.getBoundingClientRect();
      StudioMenu.open({preventDefault() {}, stopPropagation() {}, clientX: r.left, clientY: r.bottom + 4}, items());
    });
  }
}

function lookMenu(look) {
  const isDefault = stKey(look.name) === stKey(SD.default_look);
  return [
    {label: "Use as default", disabled: isDefault, act: () => setDefaultLook(look.name)},
    {label: "Edit…", act: () => lookEditor(look)},
    {label: "Duplicate…", act: () => lookEditor({...look, name: `${look.name} copy`}, {isNew: true})},
    "-",
    {label: look.edited ? "Restore the built-in look" : "Delete", danger: true, disabled: look.source !== "own", act: () => deleteStyle("look", look)},
  ];
}

async function setDefaultLook(name) {
  try { await api("/api/settings", {default_look: name}); toast(`${name} is now the default look`); await styleRepaint(); }
  catch (e) { toast(e.message, true); }
}

async function deleteStyle(kind, item) {
  const users = (SD.used[kind + "s"] || {})[item.name] || [];
  const text = item.edited ? `Go back to the built-in ${kind} ${item.name}? Your changes to it are removed.` : `Delete the ${kind} ${item.name}?`;
  if (!confirm(text + (users.length && !item.edited ? ` ${users.join(", ")} uses it.` : ""))) return;
  try { await api(`/api/styles/${kind}/delete`, {name: item.name}); toast(item.edited ? `${item.name} is built in again` : `Deleted ${item.name}`); await styleRepaint(); }
  catch (e) { toast(e.message, true); }
}

/* The look editor: a name, a palette and a font for each of the three roles. */
async function lookEditor(base, {isNew} = {}) {
  if (!SD) await loadStyles();
  isNew = isNew || !base;
  const look = JSON.parse(JSON.stringify(base || {name: "", palette: SD.palettes[0]?.name, fonts: {
    display: {family: "Newsreader", weight: 600}, text: {family: "Newsreader", weight: 400}, label: {family: "Archivo", weight: 600}}}));
  const form = openDialog(`<form>
    <h2>${isNew ? "New look" : "Edit look"}</h2>
    <label><span class="label">Name</span><input class="input big" name="name" value="${esc(look.name)}" ${isNew ? "" : "readonly"} required autocomplete="off" placeholder="Name of the look"></label>
    <div><span class="label">Palette</span><div id="le-pal"></div></div>
    <div class="st-roles">${[["display", "Display", "Titles and large type"], ["text", "Text", "Poems and body text"], ["label", "Label", "Names, captions and small caps"]].map(([r, l, d]) =>
      `<div><span class="label">${l}</span><p class="hint" style="margin:-6px 0 8px">${d}</p><div data-role="${r}"></div></div>`).join("")}</div>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">${isNew ? "Save look" : "Save changes"}</button></div></form>`, async fd => {
    const name = String(fd.get("name") || "").trim();
    if (isNew && SD.looks.some(l => stKey(l.name) === stKey(name))) throw new Error(`There is already a look called ${name}. Choose another name.`);
    const saved = await api("/api/styles/look", {look: {name, palette: look.palette, fonts: look.fonts}});
    (saved.warnings || []).forEach(w => toast(w, true));
    if (!saved.warnings?.length) toast(`Saved ${saved.name}`);
    await styleRepaint();
  });
  $("#le-pal").replaceWith(Object.assign(palettePicker(look.palette, n => { look.palette = n; }), {id: "le-pal"}));
  for (const r of ["display", "text", "label"]) $(`[data-role=${r}]`, form).replaceWith(fontPicker(look.fonts[r], f => { look.fonts[r] = f; }, {pinned: []}));
}

/* ——— palettes ——— */
function paintPalettes() {
  actionsHost(`<button class="btn" id="st-newpal" type="button"><span class="plus">+</span> New palette</button>`).querySelector("#st-newpal").onclick = () => paletteEditor(null);
  const used = SD.used.palettes || {};
  $("#st-body").innerHTML = `<div class="st-palettes">${SD.palettes.map(p => {
    const users = used[p.name] || [];
    return `<article class="st-pal" data-pal="${esc(p.name)}">
      ${stripHtml(p.swatches, true)}
      <div class="row"><div><h3 class="name">${esc(p.name)}</h3>
        <p class="muted small">${[plural(p.swatches.length, "colour"), p.source === "own" ? (p.edited ? "Your edit of a built-in palette" : "Yours") : "Built in", users.length ? "Used in " + users.map(esc).join(", ") : ""].filter(Boolean).join(" · ")}</p></div>
        <div class="acts"><button class="btn small quiet" type="button" data-act="edit">Edit</button>
          <button class="btn small quiet" type="button" data-act="more" aria-label="More actions for ${esc(p.name)}" aria-haspopup="menu">More</button></div></div>
      ${(p.warnings || []).map(w => `<p class="st-warn">${esc(w)}</p>`).join("")}</article>`;
  }).join("")}</div>`;
  for (const card of $$(".st-pal")) {
    const pal = palByName(card.dataset.pal);
    const items = () => [
      {label: "Edit…", act: () => paletteEditor(pal)},
      {label: "Duplicate…", act: () => paletteEditor({...pal, name: `${pal.name} copy`}, {isNew: true})},
      "-",
      {label: pal.edited ? "Restore the built-in palette" : "Delete", danger: true, disabled: pal.source !== "own", act: () => deleteStyle("palette", pal)},
    ];
    card.addEventListener("contextmenu", ev => StudioMenu.open(ev, items()));
    $$("[data-act]", card).forEach(b => b.onclick = () => {
      if (b.dataset.act === "edit") return paletteEditor(pal);
      const r = b.getBoundingClientRect();
      StudioMenu.open({preventDefault() {}, stopPropagation() {}, clientX: r.left, clientY: r.bottom + 4}, items());
    });
  }
}

/* The palette editor. `base` is a palette (or null for a new one); `opts.series` adds the colours that series uses as candidates;
   `opts.onSaved(palette)` runs after it is saved. A series' or poem's own copy (not in the library) is edited with `opts.own`:
   {title, note, save(palette) → Promise}, which saves it in place of /api/styles/palette. */
async function paletteEditor(base, opts = {}) {
  if (!SD) await loadStyles();
  const own = opts.own || null;
  const isNew = !own && (opts.isNew || !base);
  const sw = (base?.swatches || [{name: "Background", hex: "#0C0E11", role: "background"}, {name: "Text", hex: "#EEEAE2", role: "text"},
    {name: "Accent", hex: "#DA291C", role: "accent"}, {name: "Muted", hex: "#8E939B", role: "muted"}]).map(s => ({name: s.name || "", hex: s.hex.toUpperCase(), role: s.role || ""}));
  const groups = [];            // candidates to add: {title, items: [{hex, count?}]}
  let unwide = () => {};
  const users = !own && !isNew && base ? (SD.used.palettes || {})[base.name] || [] : [];
  const {form, dlg} = openLayer(`<form class="st-pe">
    <h2>${own ? esc(own.title) : isNew ? "New palette" : "Edit palette"}</h2>
    ${own ? `<p class="hint" style="margin-top:-12px">${esc(own.note || "")}</p><input type="hidden" name="name" value="${esc(base?.name || "")}">`
      : `<label><span class="label">Name</span><input class="input big" name="name" value="${esc(base?.name || "")}" ${isNew ? "" : "readonly"} required autocomplete="off" placeholder="Name of the palette"></label>`}
    ${users.length ? `<p class="hint" style="margin-top:-12px">${esc(users.join(", "))} follow${users.length === 1 ? "s" : ""} this palette and will change with it.</p>` : ""}
    <div><div id="pe-strip"></div><div id="pe-warn"></div></div>
    <div id="pe-rows" class="rows"></div>
    <div class="adders"><button type="button" class="btn small" id="pe-add">Add swatch</button>
      <button type="button" class="btn small" id="pe-paste-b" aria-expanded="false">Paste colours</button>
      <label class="btn small" for="pe-img">From an image</label><input type="file" id="pe-img" accept="image/*" hidden></div>
    <div id="pe-paste" hidden><textarea class="textarea" id="pe-paste-t" rows="3" placeholder="Paste any text: every #rrggbb in it becomes a swatch" spellcheck="false"></textarea>
      <div style="margin-top:8px"><button type="button" class="btn small" id="pe-paste-go">Add colours</button></div></div>
    <div id="pe-cands"></div>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">${isNew ? "Save palette" : "Save changes"}</button></div></form>`, async fd => {
    const name = String(fd.get("name") || "").trim();
    if (!name && !own) throw new Error("Give the palette a name.");
    if (isNew && SD.palettes.some(p => stKey(p.name) === stKey(name))) throw new Error(`There is already a palette called ${name}. Choose another name.`);
    if (sw.some(s => s.bad)) throw new Error("A colour isn't a hex code (use #RRGGBB).");
    const palette = {...(name ? {name} : {}), swatches: sw.map(s => ({name: s.name || undefined, hex: s.hex, role: s.role || undefined}))};
    const saved = own ? await own.save(palette) : await api("/api/styles/palette", {palette});
    toast(own ? "Saved the palette" : `Saved ${saved.name}`);
    unwide();
    await styleRepaint();
    opts.onSaved?.(saved);
  });
  unwide = onDialogClose(() => dlg.classList.remove("wide"), dlg);
  dlg.classList.add("wide");

  const paintStrip = () => {
    $("#pe-strip").innerHTML = stripHtml(sw.filter(s => HEX6.test(s.hex)), true);
    const warn = paletteWarnings(sw);
    $("#pe-warn").innerHTML = warn.map(w => `<p class="st-warn">${esc(w)}</p>`).join("");
  };
  const paintRows = () => {
    $("#pe-rows").innerHTML = sw.map((s, i) => `<div class="pe-row" data-i="${i}">
      <input type="color" value="${esc(s.hex.toLowerCase())}" aria-label="Colour ${i + 1}">
      <input class="input" data-f="name" value="${esc(s.name)}" placeholder="${esc(s.hex)}" aria-label="Name of colour ${i + 1}" autocomplete="off">
      <input class="input mono" data-f="hex" value="${esc(s.hex)}" maxlength="7" spellcheck="false" aria-label="Hex code of colour ${i + 1}" ${s.bad ? 'aria-invalid="true"' : ""}>
      <select class="select" data-f="role" aria-label="Role of colour ${i + 1}"><option value="">No role</option>${Object.entries(ROLE_LABEL).map(([r, l]) => `<option value="${r}" ${s.role === r ? "selected" : ""}>${l}</option>`).join("")}</select>
      <button type="button" class="btn small quiet" data-rm aria-label="Remove colour ${i + 1}" ${sw.length < 2 ? "disabled" : ""}>Remove</button></div>`).join("");
    $("#pe-add").disabled = sw.length >= 16;
    paintStrip();
  };
  const paintCands = () => {
    const have = new Set(sw.map(s => s.hex.toUpperCase()));
    $("#pe-cands").innerHTML = groups.map((g, gi) => {
      const items = g.items.filter(c => !have.has(c.hex.toUpperCase()));
      return items.length ? `<div class="cands"><span class="label">${esc(g.title)}</span><div class="list">${items.map(c =>
        `<button type="button" class="cand" data-g="${gi}" data-hex="${esc(c.hex)}" title="Add ${esc(c.hex)}"><span style="background:${esc(c.hex)}"></span>${esc(c.hex.toUpperCase())}${c.count ? `<small>${c.count}</small>` : ""}</button>`).join("")}</div></div>` : "";
    }).join("");
  };
  const repaint = () => { paintRows(); paintCands(); };
  const add = hexes => {
    const have = new Set(sw.map(s => s.hex.toUpperCase()));
    let skipped = 0;
    for (const h of hexes) {
      const hex = h.toUpperCase();
      if (have.has(hex)) continue;
      if (sw.length >= 16) { skipped++; continue; }
      sw.push({name: "", hex, role: ""}); have.add(hex);
    }
    if (skipped) toast("A palette has at most 16 colours", true);
    repaint();
  };

  const rows = $("#pe-rows");
  rows.addEventListener("input", ev => {
    const row = ev.target.closest(".pe-row"); if (!row) return;
    const s = sw[+row.dataset.i], f = ev.target.dataset.f;
    if (ev.target.type === "color") {
      s.hex = ev.target.value.toUpperCase(); s.bad = false;
      const t = $('[data-f=hex]', row); t.value = s.hex; t.removeAttribute("aria-invalid");
    } else if (f === "name") s.name = ev.target.value;
    else if (f === "hex") {
      const v = (ev.target.value.trim().startsWith("#") ? "" : "#") + ev.target.value.trim();
      if (HEX6.test(v)) { s.hex = v.toUpperCase(); s.bad = false; ev.target.removeAttribute("aria-invalid"); $("[type=color]", row).value = s.hex.toLowerCase(); $("[data-f=name]", row).placeholder = s.hex; }
      else { s.bad = true; ev.target.setAttribute("aria-invalid", "true"); }
    }
    if (f !== "role") { paintStrip(); paintCands(); }
  });
  rows.addEventListener("change", ev => {
    if (ev.target.dataset.f !== "role") return;
    const i = +ev.target.closest(".pe-row").dataset.i, role = ev.target.value;
    if (role) sw.forEach((s, j) => { if (j !== i && s.role === role) s.role = ""; });    // each role at most once: it moves here
    sw[i].role = role;
    paintRows();
  });
  rows.addEventListener("click", ev => {
    const b = ev.target.closest("[data-rm]"); if (!b || sw.length < 2) return;
    sw.splice(+b.closest(".pe-row").dataset.i, 1);
    repaint();
  });
  $("#pe-add").onclick = () => { if (sw.length < 16) { sw.push({name: "", hex: "#808080", role: ""}); repaint(); $$("#pe-rows .pe-row").at(-1)?.querySelector("[data-f=name]").focus(); } };
  $("#pe-paste-b").onclick = e => {
    const box = $("#pe-paste"); box.hidden = !box.hidden;
    e.currentTarget.setAttribute("aria-expanded", String(!box.hidden));
    if (!box.hidden) $("#pe-paste-t").focus();
  };
  $("#pe-paste-go").onclick = () => {
    const found = $("#pe-paste-t").value.match(/#[0-9a-fA-F]{6}\b/g) || [];
    if (!found.length) return toast("No #rrggbb colours in that text", true);
    add(found);
    $("#pe-paste-t").value = "";
  };
  $("#pe-img").onchange = async e => {
    const file = e.target.files[0]; e.target.value = "";
    if (!file) return;
    try {
      const data = await fileBase64(file);
      const r = await api("/api/palette/from-image", {data});
      const g = groups.find(x => x.image);
      const items = r.swatches.map(hex => ({hex}));
      if (g) g.items = items; else groups.unshift({image: true, title: "From the image: click the ones to keep", items});
      paintCands();
    } catch (err) { toast(err.message, true); }
  };
  $("#pe-cands").addEventListener("click", ev => {
    const b = ev.target.closest(".cand"); if (b) add([b.dataset.hex]);
  });
  repaint();
  if (opts.series) {
    api("/api/series/colours?name=" + encodeURIComponent(opts.series)).then(list => {
      if (Array.isArray(list) && list.length && $("#pe-cands")) { groups.push({title: "Colours used in this series", items: list}); paintCands(); }
    }).catch(() => {});
  }
}

/* A palette chooser to put in a dialog or panel. `current` is a palette name; onPick(name, palette) runs on each choice.
   Returns an element; `New palette` opens the editor (with the series' colours as candidates when `opts.series` is given). */
let pickerCount = 0;
function palettePicker(current, onPick, opts = {}) {
  const host = document.createElement("div"), group = "pp" + ++pickerCount;
  host.className = "st-palpick";
  let cur = current;
  const paint = async () => {
    if (!SD) { try { await loadStyles(); } catch (e) { host.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; } }
    host.innerHTML = `<div class="pick small">${SD.palettes.map(p => `<label><input type="radio" name="${group}" value="${esc(p.name)}" ${stKey(p.name) === stKey(cur) ? "checked" : ""}>
      <span class="n" style="font-size:17px">${esc(p.name)}</span>${stripHtml(p.swatches, false)}</label>`).join("")}</div>
      <button type="button" class="btn small quiet" data-new>New palette…</button>`;
    $$("input", host).forEach(i => i.onchange = () => { cur = i.value; onPick?.(cur, palByName(cur)); });
    $("[data-new]", host).onclick = () => paletteEditor(null, {series: opts.series, onSaved: p => { cur = p.name; paint(); onPick?.(cur, p); }});
    $("input:checked", host)?.closest("label").scrollIntoView({block: "nearest"});
  };
  paint();
  return host;
}

/* ——— font picker ——— */
/* A font chooser: family, weight and (where the family has the axis) width, with a line set in the choice.
   `current` is {family, weight, width?}; onPick({family, weight, width?}) runs on each change; opts.pinned lists families to put first,
   under opts.pinnedLabel. */
function fontPicker(current, onPick, {pinned = [], pinnedLabel = "Used in this series"} = {}) {
  const host = document.createElement("div");
  host.className = "st-fontpick";
  const cur = {family: current?.family || "Newsreader", weight: current?.weight ?? 400};
  if (current?.width) cur.width = current.width;
  const nearest = (list, v) => list.reduce((a, b) => Math.abs(b - v) < Math.abs(a - v) ? b : a, list[0]);
  const option = (v, label, sel) => `<option value="${esc(v)}" ${sel ? "selected" : ""}>${esc(label)}</option>`;
  const paint = () => {
    const all = Design.fontNames(), known = !!Design.family(cur.family);
    const first = pinned.filter(n => all.includes(n));
    const cats = {};
    for (const n of all) if (!first.includes(n)) (cats[CATEGORY_NAME[Design.family(n).category] || "Other"] ||= []).push(n);
    const weights = weightsFor(cur.family);
    if (!weights.includes(cur.weight)) weights.push(cur.weight), weights.sort((a, b) => a - b);
    const widths = Design.widthsOf(cur.family);
    host.innerHTML = `<div class="fp-row">
        <select class="select fp-family" aria-label="Font family">${known ? "" : option(cur.family, `${cur.family} (not installed)`, true)}
          ${first.length ? `<optgroup label="${esc(pinnedLabel)}">${first.map(n => option(n, n, n === cur.family)).join("")}</optgroup>` : ""}
          ${Object.entries(cats).sort().map(([c, names]) => `<optgroup label="${esc(c)}">${names.map(n => option(n, n, n === cur.family)).join("")}</optgroup>`).join("")}</select>
        <select class="select fp-weight" aria-label="Weight">${weights.map(w => option(w, WEIGHT_NAME[w] ? `${w} ${WEIGHT_NAME[w]}` : String(w), w === cur.weight)).join("")}</select>
        ${widths.length ? `<select class="select fp-width" aria-label="Width">${option("", "Normal width", !cur.width)}${widths.filter(([w]) => w !== 100).map(([w, l]) => option(w, `${l} ${w}%`, +cur.width === w)).join("")}</select>` : ""}</div>
      <div class="fp-sample" style="${esc(`font-family:${fontStack(cur.family)};font-weight:${+cur.weight || 400};${+cur.width ? `font-stretch:${+cur.width}%;` : ""}`)}">Aa — the quiet is the same</div>`;
    $(".fp-family", host).onchange = e => {
      cur.family = e.target.value;
      cur.weight = nearest(weightsFor(cur.family), cur.weight);
      const wd = Design.widthsOf(cur.family);
      if (!wd.length || (cur.width && !wd.some(([w]) => w === +cur.width))) delete cur.width;
      paint(); onPick?.({...cur});
    };
    $(".fp-weight", host).onchange = e => { cur.weight = +e.target.value; paint(); onPick?.({...cur}); };
    const wsel = $(".fp-width", host);
    if (wsel) wsel.onchange = e => { if (e.target.value) cur.width = +e.target.value; else delete cur.width; paint(); onPick?.({...cur}); };
  };
  paint();
  return host;
}

/* ——— fonts ——— */
function paintFonts(live) {
  actionsHost(`<button class="btn" id="st-addfonts" type="button"><span class="plus">+</span> Add fonts</button>`).querySelector("#st-addfonts").onclick = () => addFontsDialog();
  const body = $("#st-body");
  body.innerHTML = `<div class="st-toolbar">
      <label class="grow"><span class="label">Sample text</span><input class="input" id="ft-sample" value="${esc(pref.get("fontSample", "The light comes in low across the table"))}" autocomplete="off" spellcheck="false"></label>
      <label><span class="label">Search</span><input class="input" id="ft-q" placeholder="Family name" autocomplete="off"></label>
      <label><span class="label">Category</span><select class="select" id="ft-cat"></select></label>
      <label><span class="label">Source</span><select class="select" id="ft-src"></select></label></div>
    <div id="ft-list" class="st-fonts"><p class="muted">Loading…</p></div>`;
  let fams = [];
  const used = SD.used.fonts || {};
  const paintList = () => {
    const q = $("#ft-q").value.trim().toLowerCase(), cat = $("#ft-cat").value, src = $("#ft-src").value, sample = $("#ft-sample").value || "Aa";
    const list = fams.filter(f => (!q || f.family.toLowerCase().includes(q)) && (!cat || f.category === cat) && (!src || f.source === src))
      .sort((a, b) => a.family.localeCompare(b.family));
    $("#ft-list").innerHTML = list.length ? list.map(f => {
      const u = used[f.family] || [], widths = f.wdth && f.wdth[1] > f.wdth[0] ? `${f.wdth[0]}–${f.wdth[1]}%` : "";
      return `<article class="st-font" data-family="${esc(f.family)}"><div class="meta"><h3 class="name">${esc(f.family)}</h3>
        <p class="muted small">${[CATEGORY_NAME[f.category] || f.category, SOURCE_NAME[f.source] || f.source, f.license && f.license !== "unknown" ? f.license : "Licence unknown"].map(esc).join(" · ")}</p>
        <p class="muted small">Weights ${esc(weightText(f))}${widths ? ` · widths ${esc(widths)}` : ""}${f.italic ? " · italic" : ""}</p>
        ${u.length ? `<p class="muted small">Used in ${u.map(esc).join(", ")}</p>` : ""}</div>
        <p class="sample" style="${esc("font-family:" + fontStack(f.family))}">${esc(sample)}</p></article>`;
    }).join("") : `<p class="empty">No fonts match.</p>`;
    $$(".st-font").forEach(el => {
      const f = fams.find(x => x.family === el.dataset.family), own = f && (f.source === "file" || f.source === "google");
      const items = () => [
        {label: "Copy family name", act: () => { navigator.clipboard?.writeText(el.dataset.family); toast(`Copied ${el.dataset.family}`); }},
        ...(own ? ["-", {label: "Edit…", act: () => editFontDialog(f, reload)}, {label: "Remove…", act: () => dropFont(f, reload)}] : [])];
      el.addEventListener("contextmenu", ev => StudioMenu.open(ev, items()));
      if (own) {   // a visible way in for those who don't right-click
        $(".meta", el).insertAdjacentHTML("beforeend", `<p class="small st-font-acts"><button type="button" class="btn quiet small" data-edit>Edit…</button> <button type="button" class="btn quiet small" data-drop>Remove…</button></p>`);
        $("[data-edit]", el).onclick = () => editFontDialog(f, reload);
        $("[data-drop]", el).onclick = () => dropFont(f, reload);
      }
    });
  };
  const reload = async () => { await refreshFonts(); fams = await api("/api/fonts"); fill(); paintList(); };
  const fill = () => {
    const opt = (sel, items, all) => { const keep = sel.value; sel.innerHTML = `<option value="">${all}</option>` + items.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join(""); sel.value = keep; };
    opt($("#ft-cat"), [...new Set(fams.map(f => f.category))].sort().map(c => [c, CATEGORY_NAME[c] || c]), "All categories");
    opt($("#ft-src"), [...new Set(fams.map(f => f.source))].sort().map(s => [s, SOURCE_NAME[s] || s]), "All sources");
  };
  $("#ft-sample").oninput = e => { pref.set("fontSample", e.target.value); paintList(); };
  for (const id of ["#ft-q", "#ft-cat", "#ft-src"]) $(id).oninput = $(id).onchange = paintList;
  api("/api/fonts").then(list => { if (!live()) return; fams = list; fill(); paintList(); }).catch(e => { $("#ft-list").innerHTML = `<p class="empty">${esc(e.message)}</p>`; });
}

/* Correct the category and licence of a font you added. */
function editFontDialog(f, done) {
  openDialog(`<form class="st-add">
    <h2>${esc(f.family)}</h2>
    <label class="field"><span class="label">Category</span><select class="select" name="category">${Object.entries(CATEGORY_NAME[f.category] ? CATEGORY_NAME : {...CATEGORY_NAME, [f.category]: f.category}).map(([k, l]) =>
      `<option value="${k}" ${k === f.category ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
    <label class="field"><span class="label">Licence</span><input class="input" name="license" maxlength="60" value="${esc(f.license && f.license !== "unknown" ? f.license : "")}" placeholder="OFL-1.1" autocomplete="off" spellcheck="false"></label>
    <p class="hint">Only what Studio shows about the font changes. The font files stay as they are.</p>
    <div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button><button type="submit" class="btn solid">Save</button></div></form>`,
  async fd => {
    await api("/api/fonts/update", {family: f.family, category: fd.get("category"), license: fd.get("license")});
    await done();
    toast("Saved");
  });
}

/* Take away a font you added: its folder moves to Styles/.trash/fonts. Designs that use it need a second yes. */
async function dropFont(f, done) {
  if (!confirm(`Remove ${f.family}?\n\nIts files move to Styles/.trash/fonts. Move them back to restore it.`)) return;
  try {
    try { await api("/api/fonts/remove", {family: f.family}); }
    catch (e) {
      const designs = +e.data?.designs || 0, styled = +e.data?.styled || 0;     // the server's counts of what uses it
      if (!designs && !styled) throw e;
      const where = [designs ? plural(designs, "design") : "", styled ? `${styled} ${styled === 1 ? "series, poem or book" : "series, poems or books"}` : ""].filter(Boolean).join(" and ");
      const after = designs ? "Those designs will be set in another font until you change them." : "They will use another font until you change them.";
      if (!confirm(`${f.family} is used in ${where}.\n\nRemove it anyway? ${after}`)) return;
      await api("/api/fonts/remove", {family: f.family, force: true});
    }
    await done();
    toast(`Removed ${f.family}`);
  } catch (e) { toast(e.message, true); }
}

/* Add fonts: from Google Fonts, from files, or look at the computer's own. */
function addFontsDialog() {
  const dlg = $("#dlg"), links = [];
  let added = false, poll = null;
  const finish = onDialogClose(async () => {
    clearInterval(poll); dlg.classList.remove("wide"); links.forEach(l => l.remove());
    if (added) { try { await styleRepaint(); } catch { /* the page may have changed */ } }
  });
  const form = openDialog(`<form class="st-add">
    <h2>Add fonts</h2>
    <nav class="tabs" role="tablist">${[["google", "Google Fonts"], ["files", "Files"], ["system", "On this computer"]].map(([k, l], i) =>
      `<button type="button" role="tab" data-tab="${k}" aria-selected="${i === 0}">${l}</button>`).join("")}</nav>
    <div id="af-body"></div>
    <div class="foot"><span class="muted small" id="af-note"></span><button type="submit" class="btn solid">Done</button></div></form>`, async () => finish());
  dlg.classList.add("wide");
  const body = $("#af-body"), note = $("#af-note");
  const didAdd = async (r, what) => {
    added = true;
    await refreshFonts();
    (r.warnings || []).forEach(w => toast(w, true));
    note.textContent = `Added ${(r.added || [what]).join(", ")}`;
    toast(`Added ${(r.added || [what]).join(", ")}`);
  };
  const tab = k => {
    clearInterval(poll);
    $$("[data-tab]", form).forEach(b => b.setAttribute("aria-selected", b.dataset.tab === k));
    ({google: googleTab, files: filesTab, system: systemTab})[k]();
  };

  function googleTab() {
    body.innerHTML = `<div class="st-toolbar"><label class="grow"><span class="label">Search</span><input class="input" id="g-q" placeholder="Family name" autocomplete="off"></label>
      <label><span class="label">Category</span><select class="select" id="g-cat"><option value="">All categories</option>${[["serif", "Serif"], ["sans-serif", "Sans serif"], ["display", "Display"], ["handwriting", "Handwriting"], ["monospace", "Monospace"]].map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label></div>
      <div id="g-list" class="st-glist" role="list"><p class="muted">Loading…</p></div>`;
    const have = new Set(Design.fontNames().map(n => n.toLowerCase()));
    const seen = new Set();
    const io = new IntersectionObserver(es => {
      for (const e of es) {
        if (!e.isIntersecting) continue;
        const fam = e.target.dataset.family;
        io.unobserve(e.target);
        if (seen.has(fam)) continue;
        seen.add(fam);
        const l = document.createElement("link");
        l.rel = "stylesheet"; l.href = "https://fonts.googleapis.com/css2?family=" + encodeURIComponent(fam).replace(/%20/g, "+") + "&display=swap";
        document.head.appendChild(l); links.push(l);
      }
    }, {root: $("#g-list"), rootMargin: "80px"});
    let seq = 0;
    const search = async () => {
      const my = ++seq, q = $("#g-q").value.trim(), cat = $("#g-cat").value;
      let list;
      try { list = await api(`/api/fonts/google?q=${encodeURIComponent(q)}&category=${encodeURIComponent(cat)}`); }
      catch (e) { if (my === seq) $("#g-list").innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
      if (my !== seq) return;
      $("#g-list").innerHTML = list.length ? list.map(f => `<div class="g-row" role="listitem" data-family="${esc(f.family)}">
        <div class="meta"><b>${esc(f.family)}</b><span class="muted small">${esc(CATEGORY_NAME[{"sans-serif": "sans", handwriting: "hand", monospace: "mono"}[f.category] || f.category] || f.category)}</span></div>
        <span class="g-spec" style="${esc("font-family:" + fontStack(f.family) + ",var(--serif)")}">${esc(pref.get("fontSample", "The light comes in low across the table"))}</span>
        ${have.has(f.family.toLowerCase()) ? `<span class="muted small">Added</span>` : `<button type="button" class="btn small" data-add="${esc(f.family)}">Add</button>`}</div>`).join("")
        : `<p class="muted">No Google font matches.</p>`;
      $$(".g-row", body).forEach(r => io.observe(r));
      if (list.length === 60) $("#g-list").insertAdjacentHTML("beforeend", `<p class="muted small" style="padding:10px 0">Showing the first 60. Search to narrow them down.</p>`);
    };
    let t; $("#g-q").oninput = () => { clearTimeout(t); t = setTimeout(search, 250); };
    $("#g-cat").onchange = search;
    $("#g-list").addEventListener("click", async ev => {
      const b = ev.target.closest("[data-add]"); if (!b) return;
      b.disabled = true; b.textContent = "Adding…";
      try {
        const r = await api("/api/fonts/google/add", {family: b.dataset.add});
        await didAdd(r, b.dataset.add);
        have.add(b.dataset.add.toLowerCase());
        b.replaceWith(Object.assign(document.createElement("span"), {className: "muted small", textContent: "Added"}));
      } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = "Add"; }
    });
    search();
  }

  function filesTab() {
    body.innerHTML = `<label class="st-drop" id="f-drop" for="f-in"><b>Drop font files here</b><span class="muted">or choose them: .ttf, .otf, .woff or .woff2</span></label>
      <input type="file" id="f-in" accept=".ttf,.otf,.woff,.woff2,.ttc" multiple hidden>
      <p class="hint">Studio keeps a copy in your library, so the fonts travel with your files.</p>`;
    const send = async files => {
      files = [...files];
      if (!files.length) return;
      const drop = $("#f-drop");
      drop.classList.add("busy");
      try {
        const items = await Promise.all(files.map(async f => ({name: f.name, data: await fileBase64(f)})));
        await didAdd(await api("/api/fonts/add", {files: items}), files[0].name);
      } catch (e) { toast(e.message, true); }
      drop.classList.remove("busy");
    };
    const drop = $("#f-drop");
    ["dragenter", "dragover"].forEach(n => drop.addEventListener(n, e => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach(n => drop.addEventListener(n, e => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", e => send(e.dataTransfer.files));
    $("#f-in").onchange = e => { send(e.target.files); e.target.value = ""; };
  }

  function systemTab() {
    body.innerHTML = `<p class="hint" style="margin:0 0 14px">Fonts from this computer won't travel with your files.</p>
      <label><span class="label">Search</span><input class="input" id="s-q" placeholder="Family name" autocomplete="off" style="max-width:320px"></label>
      <div id="s-list" class="st-glist" style="margin-top:16px"><p class="muted">Looking at the fonts on this computer…</p></div>`;
    let fams = null;
    const paint = () => {
      if (!fams) return;
      const q = $("#s-q").value.trim().toLowerCase();
      const list = fams.filter(f => !q || f.family.toLowerCase().includes(q));
      $("#s-list").innerHTML = list.length ? list.slice(0, 200).map(f => `<div class="g-row sys" role="listitem"><div class="meta"><b>${esc(f.family)}</b>
        <span class="muted small">${esc(CATEGORY_NAME[f.category] || f.category)}${f.license && f.license !== "unknown" ? " · " + esc(f.license) : ""}</span></div></div>`).join("")
        + (list.length > 200 ? `<p class="muted small" style="padding:10px 0">Showing 200 of ${list.length}. Search to narrow them down.</p>` : "")
        : `<p class="muted">No font on this computer matches.</p>`;
    };
    $("#s-q").oninput = paint;
    const load = async () => {
      try {
        const r = await api("/api/fonts/system");
        if (r.indexing) return;
        clearInterval(poll); fams = r; paint();
      } catch (e) { clearInterval(poll); $("#s-list").innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
    };
    load(); poll = setInterval(load, 1500);
  }

  $$("[data-tab]", form).forEach(b => b.onclick = () => tab(b.dataset.tab));
  tab("google");
}

/* ——— house rules ——— */
function paintRules() {
  actionsHost("");
  $("#st-body").innerHTML = `<p class="hint" style="margin:0 0 24px">Claude and everything new in Studio read these first. Write them in Markdown.</p>
    <div class="st-rules"><div><span class="label">Rules</span><textarea class="notesin st-rtext" id="r-text" spellcheck="true" aria-label="House rules">${esc(SD.rules)}</textarea>
      <div class="savebar" style="padding:16px 0 0;border:0"><button class="btn solid" type="button" id="r-save">Save</button><span class="state" id="r-state"></span></div></div>
      <div><span class="label">Preview</span><div class="doc md" id="r-prev" style="border:0;padding:0"></div></div></div>`;
  const text = $("#r-text"), prev = $("#r-prev"), stat = $("#r-state");
  let saved = SD.rules;
  const paint = () => {
    prev.innerHTML = text.value.trim() ? md(text.value) : `<p class="muted">Nothing written yet.</p>`;
    const dirty = text.value !== saved;
    stat.textContent = dirty ? "Unsaved changes" : ""; stat.classList.toggle("dirty", dirty);
  };
  text.oninput = paint;
  text.addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); $("#r-save").click(); } });
  $("#r-save").onclick = async () => {
    try { saved = SD.rules = await api("/api/styles/rules", {text: text.value}); paint(); toast("House rules saved"); }
    catch (e) { toast(e.message, true); }
  };
  paint();
}
