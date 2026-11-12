"use strict";
/* Studio's visual editor: a full-window canvas per poem, in the series' palette and type.
   Designs live in the poem folder as designs/<slug>.json (Claude can read and write them too);
   exports go to "Design renders/<slug>/<slug>-<format>[-noname].png" at 2x, rendered by Chrome. */
const Editor = (() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const pref = {get: (k, d) => { try { return localStorage.getItem("studio.ed." + k) ?? d; } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem("studio.ed." + k, v); } catch { /* ignore */ } }};
  const M = document.createElement("canvas").getContext("2d");   // measuring context
  const svg = (d, w = 20) => `<svg viewBox="0 0 22 22" width="${w}" height="${w}" aria-hidden="true">${d}</svg>`;
  const ICON = {
    select: '<path d="M6 3.5l11 7.6-5 1.1 2.6 5.6-2.2 1-2.6-5.7L6 16.7z" fill="currentColor"/>',
    text: '<path d="M4.5 5h13M11 5v13M8 18h6" fill="none" stroke="currentColor" stroke-width="1.8"/>',
    rect: '<rect x="4" y="5.5" width="14" height="11" fill="none" stroke="currentColor" stroke-width="1.8"/>',
    ellipse: '<ellipse cx="11" cy="11" rx="7.5" ry="6" fill="none" stroke="currentColor" stroke-width="1.8"/>',
    line: '<path d="M4.5 17.5L17.5 4.5" fill="none" stroke="currentColor" stroke-width="1.8"/>',
    undo: '<path d="M8 6L4 10l4 4M4.5 10H13a4.5 4.5 0 010 9h-2" fill="none" stroke="currentColor" stroke-width="1.7"/>',
    redo: '<path d="M14 6l4 4-4 4M17.5 10H9a4.5 4.5 0 000 9h2" fill="none" stroke="currentColor" stroke-width="1.7"/>',
    guides: '<path d="M3 7h16M3 15h16M7 3v16M15 3v16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="2 2"/>',
    eye: '<path d="M2.5 11s3.2-5.5 8.5-5.5S19.5 11 19.5 11s-3.2 5.5-8.5 5.5S2.5 11 2.5 11z" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="11" cy="11" r="2.4" fill="currentColor"/>',
    eyeoff: '<path d="M2.5 11s3.2-5.5 8.5-5.5S19.5 11 19.5 11s-3.2 5.5-8.5 5.5S2.5 11 2.5 11zM4 18L18 4" fill="none" stroke="currentColor" stroke-width="1.5"/>',
    lock: '<rect x="5.5" y="10" width="11" height="8" fill="currentColor"/><path d="M7.5 10V7.5a3.5 3.5 0 017 0V10" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    unlock: '<rect x="5.5" y="10" width="11" height="8" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M7.5 10V7.5a3.5 3.5 0 016.6-1.6" fill="none" stroke="currentColor" stroke-width="1.5"/>',
    up: '<path d="M11 17V5M6 10l5-5 5 5" fill="none" stroke="currentColor" stroke-width="1.7"/>',
    down: '<path d="M11 5v12M6 12l5 5 5-5" fill="none" stroke="currentColor" stroke-width="1.7"/>',
    trash: '<path d="M5 7h12M9 7V5h4v2M7 7l1 11h6l1-11" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    copy: '<rect x="7" y="7" width="10" height="10" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M5 14V5h9" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    caret: '<path d="M6 9l5 5 5-5" fill="none" stroke="currentColor" stroke-width="1.7"/>',
    back: '<path d="M13.5 5l-6 6 6 6" fill="none" stroke="currentColor" stroke-width="1.8"/>',
    polygon: '<path d="M11 4L18.5 17.5H3.5Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
    star: '<path d="M11 3.5l2.2 4.9 5.3.5-4 3.6 1.2 5.2L11 15l-4.7 2.7 1.2-5.2-4-3.6 5.3-.5z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>',
    pen: '<path d="M11 3l5.5 9L11 19l-5.5-7z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><circle cx="11" cy="11.5" r="1.7" fill="currentColor"/>',
    arc: '<path d="M4 17C4 8 18 8 18 17" fill="none" stroke="currentColor" stroke-width="1.8"/>',
    stamp: '<path d="M8 4h6v6l3 2v3H5v-3l3-2z M5 18h12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>',
  };
  const ALIGN = {
    left: '<path d="M4 3v16" stroke="currentColor" stroke-width="1.6"/><rect x="6" y="6" width="11" height="3.5" fill="currentColor"/><rect x="6" y="12.5" width="7" height="3.5" fill="currentColor"/>',
    hcenter: '<path d="M11 3v16" stroke="currentColor" stroke-width="1.6"/><rect x="4.5" y="6" width="13" height="3.5" fill="currentColor"/><rect x="7" y="12.5" width="8" height="3.5" fill="currentColor"/>',
    right: '<path d="M18 3v16" stroke="currentColor" stroke-width="1.6"/><rect x="5" y="6" width="11" height="3.5" fill="currentColor"/><rect x="9" y="12.5" width="7" height="3.5" fill="currentColor"/>',
    top: '<path d="M3 4h16" stroke="currentColor" stroke-width="1.6"/><rect x="6" y="6" width="3.5" height="11" fill="currentColor"/><rect x="12.5" y="6" width="3.5" height="7" fill="currentColor"/>',
    vcenter: '<path d="M3 11h16" stroke="currentColor" stroke-width="1.6"/><rect x="6" y="4.5" width="3.5" height="13" fill="currentColor"/><rect x="12.5" y="7" width="3.5" height="8" fill="currentColor"/>',
    bottom: '<path d="M3 18h16" stroke="currentColor" stroke-width="1.6"/><rect x="6" y="5" width="3.5" height="11" fill="currentColor"/><rect x="12.5" y="9" width="3.5" height="7" fill="currentColor"/>',
  };
  const TOOLS = [["select", "Select", "V"], ["text", "Text", "T"], ["rect", "Rectangle", "R"], ["ellipse", "Ellipse", "O"], ["polygon", "Polygon (triangle)", "Y"],
    ["star", "Star", "S"], ["line", "Line", "L"], ["arc", "Arc: drag from start to end, then set its bend", "A"], ["pen", "Pen: click for corners, drag for curves, click the first point to close, Enter to finish", "P"]];
  ICON.path = ICON.pen; ICON.shape = ICON.polygon;
  const STARTERS = [["blank", "Blank", "An empty artboard in the series' background colour."], ["page", "Page", "The poem as written, signed like a poem."],
    ["wall", "Wall", "Every line stretched to the full measure, on the accent."], ["field", "Field", "An accent field, the poem flush against its edge."]];

  let root = null, host = null, poem = null, api = null, toast = null, back = "#/", refresh = null, editStyle = null;
  let designs = [], slug = null, d = null, loadedAt = null, remapped = false;   // remapped: opened in another format than the file says
  let anchor = null, inGroup = null, collapsed = new Set(), pen = null, editPts = null;
  let sel = [], tool = "select", view = {z: 1, x: 0, y: 0, auto: true}, guides = pref.get("guides", "1") === "1", signedPreview = true;
  let undo = [], redo = [], lastKey = null, lastTime = 0, dirty = false, saving = null, saveTimer = null, clip = null;
  let canvas, cx, stage, world, board, ro, drag = null, snapLines = [], hover = null, space = false, raf = 0, cursor = null;

  const F = () => Design.FORMATS[d.format] || Design.FORMATS["45"];
  /* The series decides which formats a design has here; the design file keeps every format's layout either way. */
  const SERIES_KEY = {"1:1": "11", "4:5": "45", "9:16": "916"};
  const allowed = () => {
    const want = (poem.series_info?.formats || []).map(f => SERIES_KEY[f]).filter(Boolean);
    const keys = Object.keys(Design.FORMATS).filter(k => want.includes(k));
    return keys.length ? keys : Object.keys(Design.FORMATS);
  };
  const shownFormat = f => allowed().includes(f) ? f : allowed()[0];   // what a design saved in a left-out format opens as
  const formatEntries = () => allowed().map(k => [k, Design.FORMATS[k]]);
  /* The safe margins; on 9:16 the top and bottom are the series' story zone (its design checks). */
  const safeOf = fmt => {
    const s = Design.SAFE[fmt] || Design.SAFE["45"], c = poem.series_info?.checks;
    return fmt === "916" && c ? {...s, t: c.story_top ?? s.t, b: c.story_bottom ?? s.b} : s;
  };
  const S = () => safeOf(d.format);
  /* The palette the poem resolves to (its own, its series', or a look's). */
  const palette = () => poem.style?.palette?.swatches || poem.series_info?.palette || [{name: "Night", hex: "#0C0E11"}, {name: "Paper", hex: "#EEEAE2"}, {name: "Red", hex: "#DA291C"}];
  /* Its background, text, accent and muted colours (by role), and its type roles as element settings: what starters and new elements use. */
  const colours = () => Design.colours(palette());
  const roles = () => Design.typeRoles(poem.style?.fonts);
  /* The poem's fonts (its resolved display, text and label families), then every other family Studio knows. */
  const styleFonts = () => {
    const roles = poem.style?.fonts;
    if (roles) return [...new Set(["display", "text", "label"].map(r => roles[r]?.family).filter(Boolean))];
    return (poem.series_info?.fonts || [{family: "Newsreader"}, {family: "Archivo"}]).map(f => f.family);
  };
  const fonts = () => [...new Set([...styleFonts(), ...Design.fontNames()])];
  const textFont = () => poem.style?.fonts?.text?.family || fonts()[0] || "Newsreader";   // the poem and new text
  const CATEGORIES = [["serif", "Serif"], ["sans", "Sans serif"], ["display", "Display"], ["mono", "Monospace"], ["hand", "Handwriting"]];
  /* The font select's options: the poem's fonts ("This series", or "This poem" when it has its own), then every other
     family by category, then the computer's own fonts. A font Studio doesn't have stays listed as not installed. */
  function fontOptions(cur) {
    const first = styleFonts(), all = Design.fontNames(), rest = all.filter(n => !first.includes(n)).sort((a, b) => a.localeCompare(b));
    const sys = n => Design.family(n)?.source === "system", cat = n => Design.family(n)?.category;
    const own = Object.values(poem.style?.fonts || {}).some(f => f.from === "poem");
    const groups = [[own ? "This poem" : "This series", first],
      ...CATEGORIES.map(([c, l]) => [l, rest.filter(n => !sys(n) && cat(n) === c)]),
      ["Other", rest.filter(n => !sys(n) && !CATEGORIES.some(([c]) => c === cat(n)))], ["On this computer", rest.filter(sys)]];
    const opt = n => `<option value="${esc(n)}" ${n === cur ? "selected" : ""}>${esc(n)}</option>`;
    return (cur && !first.includes(cur) && !all.includes(cur) ? `<option value="${esc(cur)}" selected>${esc(cur)} (not installed)</option>` : "")
      + groups.filter(([, ns]) => ns.length).map(([l, ns]) => `<optgroup label="${esc(l)}">${ns.map(opt).join("")}</optgroup>`).join("");
  }
  /* A new font keeps what it can of the old setting: weight within its range, width and italic only if it has them. */
  const hasItalics = font => { const f = Design.family(font || "Newsreader"); return !f || f.italic; };   // unknown: up to the browser
  const setFont = (e, v) => {
    e.font = v;
    const w = Design.weightsOf(v);
    e.weight = Math.max(w[0], Math.min(w[1], e.weight || 400));
    if (!Design.widthsOf(v).length) delete e.stretch;
    if (!hasItalics(v)) delete e.italic;
  };
  const LAYOUT = new Set(Design.LAYOUT), views = new WeakMap();
  /* The editor works on views: layout (position, size, type size…) belongs to the current format only;
     content, colours and roles are shared by all formats. */
  function px(raw) {
    let v = views.get(raw);
    if (v) return v;
    const cur = () => (d && d.format) || "45";
    v = new Proxy(raw, {
      get(t, k) {
        if (k === "__raw") return t;
        if (LAYOUT.has(k)) { const o = t.at?.[cur()]; if (o && k in o) return o[k]; }
        return t[k];
      },
      set(t, k, val) {
        if (LAYOUT.has(k)) { t.at ||= {}; (t.at[cur()] ||= {})[k] = val; } else t[k] = val;
        return true;
      },
      deleteProperty(t, k) {
        delete t[k];
        if (LAYOUT.has(k)) for (const f in t.at || {}) delete t.at[f][k];
        return true;
      },
      has(t, k) { return k in t || (LAYOUT.has(k) && !!t.at?.[cur()] && k in t.at[cur()]); },
      ownKeys(t) { return [...new Set([...Reflect.ownKeys(t).filter(k => k !== "at"), ...Object.keys(t.at?.[cur()] || {})])]; },
      getOwnPropertyDescriptor(t, k) {
        if (k === "at") return undefined;
        const has = Reflect.has(t, k) || (LAYOUT.has(k) && t.at?.[cur()] && k in t.at[cur()]);
        return has ? {value: this.get(t, k), enumerable: true, configurable: true, writable: true} : undefined;
      },
    });
    views.set(raw, v);
    return v;
  }
  const byId = id => { const r = d.elements.find(e => e.id === id); return r && px(r); };
  const shown = e => Design.shownIn(e.__raw || e, d.format);
  /* Groups: members share e.group; d.groups[gid] = {name}. Clicking a member selects the whole group,
     double-clicking (or picking it in the layers list) goes inside it. */
  const groupOf = id => d.elements.find(e => e.id === id)?.group || null;
  const members = gid => d.elements.filter(e => e.group === gid).map(e => e.id);
  const groupName = gid => d.groups?.[gid]?.name || "Group";
  function expand(ids) {
    const out = new Set();
    for (const id of ids) { const g = groupOf(id); if (g && g !== inGroup) members(g).forEach(x => out.add(x)); else out.add(id); }
    return [...out];
  }
  function maskUnits() {
    const units = [];
    for (const e of d.elements) {
      const u = units.at(-1);
      if (e.clip && u && (u.base.group || null) === (e.group || null)) u.clips.push(e); else units.push({base: e, clips: []});
    }
    return units;
  }
  const unitOfBase = id => maskUnits().find(u => u.base.id === id);
  const baseOf = id => maskUnits().find(u => u.clips.some(c => c.id === id))?.base || null;
  /* Use one layer as the mask for others: they go right above it (and into its group) and show only inside it. */
  function useAsMask(tid, ids) {
    ids = ids.filter(id => id !== tid);
    if (!ids.length) return;
    mutate(() => {
      const target = d.elements.find(e => e.id === tid);
      if (target.clip) { delete target.clip; delete target.clipInvert; }   // a mask isn't masked itself
      const moving = d.elements.filter(e => ids.includes(e.id)), rest = d.elements.filter(e => !ids.includes(e.id));
      let at = rest.indexOf(target) + 1;
      while (at < rest.length && rest[at].clip && (rest[at].group || null) === (target.group || null)) at++;
      moving.forEach(e => { e.clip = true; if (target.group) e.group = target.group; else delete e.group; });
      rest.splice(at, 0, ...moving);
      d.elements = rest;
      pruneGroups();
    });
    toast(`“${label(byId(tid))}” masks ${ids.length === 1 ? "1 layer" : ids.length + " layers"}`);
    panels();
  }
  function releaseMask(ids) {
    if (!ids.length) return;
    mutate(() => ids.forEach(id => { const e = d.elements.find(x => x.id === id); if (e) { delete e.clip; delete e.clipInvert; } }));
    panels();
  }
  /* Right-clicking a layer that isn't selected, while others are: act on the two together. */
  function crossMenu(t) {
    const what = sel.length === 1 ? `“${label(selected()[0])}”` : `${sel.length} layers`;
    return [
      {label: `Use “${label(t)}” as mask for ${what}`, act: () => useAsMask(t.id, [...sel])},
      {label: `Group “${label(t)}” with ${what}`, act: () => { sel = [...new Set([...sel, t.id])]; groupSel(); }},
      "-",
      {label: `Add “${label(t)}” to the selection`, act: () => { sel = [...new Set([...sel, ...expand([t.id])])]; paint(); panels(); }},
      {label: `Select only “${label(t)}”`, act: () => { sel = expand([t.id]); anchor = t.id; paint(); panels(); }},
    ];
  }
  function maskInfo(e) {
    if (e.clip) {
      const b = baseOf(e.id);
      return `<div class="edx-maskbox"><span><b>Masked</b> by “${esc(b ? label(b) : "the layer below")}”</span><button class="btn small" data-act="unmask">Release</button></div>
        <label class="edx-check"><input type="checkbox" data-k="clipInvert" ${e.clipInvert ? "checked" : ""}> <span>Invert: show it only outside the mask</span></label>`;
    }
    const u = unitOfBase(e.id);
    if (u?.clips.length) return `<div class="edx-maskbox"><span><b>Mask</b> for ${u.clips.length === 1 ? "1 layer" : u.clips.length + " layers"}</span><button class="btn small" data-act="unmaskall">Release all</button></div>`;
    return `<p class="edx-note">To mask with this layer: select the layers to show inside it, then right-click this one and choose <b>Use as mask</b>.</p>`;
  }

  function pruneGroups() {
    for (const g of Object.keys(d.groups || {})) if (members(g).length < 1) { d.elements.forEach(e => { if (e.group === g) delete e.group; }); delete d.groups[g]; }
  }
  function cloneRaws(raws) {   // copies keep their groups only when a whole group is copied, as a new group
    const map = {}, ids = new Set(raws.map(r => r.id));
    return raws.map(r => {
      const c = JSON.parse(JSON.stringify(r)); c.id = Design.uid();
      if (c.group && members(c.group).every(id => ids.has(id))) {
        if (!map[c.group]) { map[c.group] = "g" + Design.uid().slice(1); (d.groups ||= {})[map[c.group]] = {name: `${groupName(c.group)} copy`}; }
        c.group = map[c.group];
      } else delete c.group;
      return c;
    });
  }
  const r2 = v => Math.round(v * 100) / 100;
  function moveEl(e, o, dx, dy, rnd = r2) {
    if (e.type === "line") { e.x1 = rnd(o.x1 + dx); e.x2 = rnd(o.x2 + dx); e.y1 = rnd(o.y1 + dy); e.y2 = rnd(o.y2 + dy); }
    else if (e.type === "path") e.pts = Design.movePoints(o.pts, dx, dy);
    else { e.x = rnd(o.x + dx); e.y = rnd(o.y + dy); }
  }
  const shift = (e, dx, dy) => moveEl(e, e, dx, dy);
  const selected = () => sel.map(byId).filter(Boolean);
  const label = e => e.name || (e.type === "text" ? (String(e.text || "").split("\n")[0] || "Text")
    : e.type === "shape" ? (e.kind === "star" ? "Star" : (+e.n || 3) === 3 ? "Triangle" : "Polygon") : e.type[0].toUpperCase() + e.type.slice(1));
  const round = v => Math.round(v * 2) / 2;
  const fmt1 = v => (Math.round(v * 10) / 10).toString();

  /* ——— mount / data ——— */
  async function mount(el, opts) {
    host = el; poem = opts.poem; api = opts.api; toast = opts.toast; back = opts.back || "#/";
    refresh = opts.refresh || null; editStyle = opts.editStyle || null;   // refresh(fresh poem): the app takes it in and calls update()
    root = document.createElement("div");
    root.className = "edx";
    document.body.appendChild(root);
    document.body.classList.add("editing");
    designs = poem.designs || [];
    const want = pref.get("last." + poem.id, null);
    slug = designs.find(x => x.slug === want)?.slug || designs[0]?.slug || null;
    sel = []; undo = []; redo = []; dirty = false; d = null;
    addEventListener("keydown", onKey); addEventListener("keyup", onKeyUp);
    addEventListener("pointerdown", closeMenus, true);
    if (opts.importSlide && poem.art?.page) { hub(); return importFromCarousel(opts.importSlide.n, opts.importSlide.fmt); }
    if (!slug) return hub();
    await load(slug);
  }

  async function load(s) {
    try {
      const nd = await api(`/api/design?id=${encodeURIComponent(poem.id)}&d=${encodeURIComponent(s)}`);
      nd.elements ||= []; nd.elements.forEach(e => { e.id ||= Design.uid(); });
      if (!allowed().includes(nd.format)) { const to = allowed()[0]; fillFormat(nd, nd.format || "45", to); nd.format = to; nd.__remapped = true; }   // the series left that format out
      remapped = nd.__remapped === true; delete nd.__remapped; d = nd; slug = s; loadedAt = designs.find(x => x.slug === s)?.updated; pref.set("last." + poem.id, s);
      sel = []; undo = []; redo = []; dirty = false; view.auto = true; docSeen = [];
      Design.onMetrics = null;            // shell() sets it: metrics that land before then are simply used by the first paint
      await Design.ready(d, {wait: false});   // the fonts; the editor opens at once and repaints when the metrics land
      shell(); fit(); paint(); panels();
    } catch (e) { toast(e.message, true); hub(); }
  }

  function unmount() {
    if (!root) return;
    flush();
    removeEventListener("keydown", onKey); removeEventListener("keyup", onKeyUp); removeEventListener("pointerdown", closeMenus, true);
    ro?.disconnect(); ro = null;
    root.remove(); root = null; d = null;
    document.body.classList.remove("editing");
  }
  const pending = () => dirty;

  /* poll: the poem changed on disk (maybe Claude edited this design) */
  function update(fresh) {
    poem = fresh; designs = fresh.designs || [];
    if (!root) return;
    if (!d) { hub(); return; }
    const mine = designs.find(x => x.slug === slug);
    if (mine && loadedAt && mine.updated !== loadedAt && !dirty && !drag && !saving) {
      loadedAt = mine.updated;
      api(`/api/design?id=${encodeURIComponent(poem.id)}&d=${encodeURIComponent(slug)}`).then(async nd => {
        nd.elements ||= []; nd.elements.forEach(e => { e.id ||= Design.uid(); });
        d = nd; sel = sel.filter(id => byId(id)); await Design.ready(d, {wait: false}); paint(); panels(); toast("Design updated on disk");
      }).catch(() => {});
    }
    panels();
  }

  /* ——— saving ——— */
  function scheduleSave() { dirty = true; clearTimeout(saveTimer); saveTimer = setTimeout(save, 700); setSaveState(); }
  async function save() {
    clearTimeout(saveTimer);
    if (!d || !dirty) return saving;
    dirty = false; setSaveState();
    saving = api("/api/design", {id: poem.id, slug, design: d}).then(r => {
      slug = r.slug; designs = r.designs; loadedAt = designs.find(x => x.slug === slug)?.updated; setSaveState();
    }).catch(e => { dirty = true; setSaveState(); toast(e.message, true); }).finally(() => { saving = null; });
    return saving;
  }
  function flush() { if (dirty) save(); }
  function setSaveState() { const s = $("#ed-saved", root); if (s) { s.textContent = dirty ? "Saving…" : "Saved"; s.classList.toggle("busy", dirty); } }

  /* ——— undo ——— */
  function mutate(fn, key = null) {
    const now = Date.now();
    if (!key || key !== lastKey || now - lastTime > 900) { undo.push(JSON.stringify(d)); if (undo.length > 200) undo.shift(); redo = []; }
    lastKey = key; lastTime = now;
    fn();
    scheduleSave(); paint();
  }
  function step(from, to) {
    if (!from.length) return;
    to.push(JSON.stringify(d)); d = JSON.parse(from.pop()); lastKey = null;
    sel = sel.filter(id => byId(id)); scheduleSave(); paint(); panels();
  }

  /* ——— top bar (shared by hub and editor) ——— */
  function bar(inner) {
    return `<header class="edx-bar">
      <a class="edx-back" href="${esc(back)}" title="Back to the poem">${svg(ICON.back, 18)}<span class="edx-mark">Studio<i></i></span></a>
      <span class="edx-crumb"><span>${esc(poem.series)}</span><b>${esc(poem.title)}</b></span>
      ${inner}</header>`;
  }

  /* ——— hub: your designs + new ones ——— */
  function hub() {
    d = null; ro?.disconnect(); ro = null; board = null;
    const fmt = allowed().includes(pref.get("fmt", "45")) ? pref.get("fmt", "45") : allowed()[0], info = startInfo(fmt), art = poem.art || {};
    const kit = art.formats?.[fmt]?.slides?.filter(x => x.signed) || [];
    root.innerHTML = `${bar(`<span class="edx-spacer"></span><span class="edx-hint">Designs live in <b>${esc(poem.folder)}/designs</b></span>`)}
      <div class="edx-hub"><div class="edx-hub-in">
        <div class="edx-hub-top"><div><span class="label">${esc(poem.series)} · ${esc(poem.title)}</span><h1 class="display edx-hub-title">Design</h1></div>
          <div class="seg" id="st-fmt" aria-label="Format">${formatEntries().map(([k, f]) => `<button data-f="${k}" aria-pressed="${k === fmt}">${f.label}</button>`).join("")}</div></div>
        ${designs.length ? `<section><div class="edx-hub-head"><span class="label">Your designs · ${designs.length}</span></div>
          <div class="edx-cards">${designs.map(x => `<button class="edx-card" data-open="${esc(x.slug)}"><span class="cv" data-cv="${esc(x.slug)}"></span>
            <span class="n">${esc(x.name)}</span><span class="d">${esc(Design.FORMATS[shownFormat(x.format)]?.label || "")} · ${plural(x.elements, "layer")}${Object.keys(x.exports || {}).length ? " · exported" : ""}</span></button>`).join("")}</div></section>` : ""}
        ${kit.length ? `<section><div class="edx-hub-head"><span class="label">From the carousel · open a slide as an editable design</span></div>
          <div class="edx-cards">${kit.map(x => `<button class="edx-card" data-import="${x.n}"><img src="/files/${x.signed.split("/").map(encodeURIComponent).join("/")}?v=${x.signed_v}" alt="">
            <span class="n">${esc(x.name)}</span><span class="d">Slide ${x.n} · ${Design.FORMATS[fmt].label}</span></button>`).join("")}</div></section>` : ""}
        <section><div class="edx-hub-head"><span class="label">Start from</span></div>
          <div class="edx-cards">${STARTERS.map(([k, n, t]) => `<button class="edx-card" data-k="${k}"><span class="cv" data-thumb="${k}" style="aspect-ratio:${info.F.w}/${info.F.h}"></span>
            <span class="n">${n}</span><span class="d">${t}</span></button>`).join("")}</div></section>
      </div></div>`;
    $$("[data-f]", $("#st-fmt", root)).forEach(b => b.onclick = () => { pref.set("fmt", b.dataset.f); hub(); });
    $$("[data-open]", root).forEach(b => {
      b.onclick = () => load(b.dataset.open);
      b.oncontextmenu = ev => StudioMenu.open(ev, [
        {label: "Open", act: () => load(b.dataset.open)},
        {label: "Export PNGs", act: async () => { try { const r = await api("/api/design/export", {id: poem.id, slug: b.dataset.open}); designs = r.designs; toast(`Exported ${r.rels.length} PNGs`); } catch (e) { toast(e.message, true); } }},
        "-",
        {label: "Move to trash", danger: true, act: async () => { if (!confirm("Move this design to the trash?")) return; const r = await api("/api/design/delete", {id: poem.id, slug: b.dataset.open}); designs = r.designs; hub(); }},
      ]);
    });
    $$("[data-import]", root).forEach(b => b.onclick = () => importFromCarousel(+b.dataset.import, fmt, b));
    /* Thumbnails are drawn at once with the metrics at hand, then again exactly once they are in. */
    const swap = (node, dd) => {
      if (!node.isConnected) return node;
      const t = Design.thumb(dd, (node.getBoundingClientRect().width || 242) - 2);
      node.replaceWith(t);
      return t;
    };
    (async () => {
      await Design.ready(null, {wait: false});
      for (const span of $$("[data-thumb]", root)) {
        const dd = await Design.starter(span.dataset.thumb, null, {...info, wait: false});
        await Design.ready(dd, {wait: false});
        const rough = swap(span, dd);
        Design.starter(span.dataset.thumb, null, info).then(async x => { await Design.ready(x); swap(rough, x); }).catch(() => {});
      }
      for (const span of $$("[data-cv]", root)) {
        try {
          const dd = await api(`/api/design?id=${encodeURIComponent(poem.id)}&d=${encodeURIComponent(span.dataset.cv)}`);
          await Design.ready(dd, {wait: false});
          const rough = swap(span, dd);
          Design.ready(dd).then(() => swap(rough, dd)).catch(() => {});
        } catch { /* keep the placeholder */ }
      }
    })();
    $$("[data-k]", root).forEach(b => b.onclick = async () => {
      b.disabled = true;
      try {
        const byFmt = {};
        for (const f of Object.keys(Design.FORMATS)) byFmt[f] = await Design.starter(b.dataset.k, null, startInfo(f));
        const nd = Design.mergeFormats(byFmt, fmt);
        nd.name = b.querySelector(".n").textContent;
        const r = await api("/api/design", {id: poem.id, design: nd}); designs = r.designs; await load(r.slug);
      } catch (e) { toast(e.message, true); b.disabled = false; }
    });
  }

  /* Open one of the carousel's rendered slides (the kit's own page) as an editable design. */
  async function importFromCarousel(n, fmt, btn) {
    const a = poem.art, slide = a.formats[fmt].slides[n - 1];
    if (btn) { btn.disabled = true; btn.querySelector(".d").textContent = "Reading the slide in 1:1, 4:5 and 9:16…"; }
    try {
      const byFmt = {};
      for (const f of a.order) {   // the kit lays the slide out per format; take all three
        const F2 = Design.FORMATS[f], frame = document.createElement("iframe");
        frame.style.cssText = `position:fixed;left:-30000px;top:0;width:${F2.w}px;height:${F2.h}px;border:0`;
        frame.src = `/files/${a.page.split("/").map(encodeURIComponent).join("/")}?export=1&s=${n}&r=${f}&sig=1`;
        document.body.appendChild(frame);
        try {
          await new Promise((res, rej) => { frame.onload = res; setTimeout(() => rej(new Error("The carousel page didn't load")), 20000); });
          const win = frame.contentWindow;
          for (let i = 0; i < 300 && win.document.body?.dataset.ready !== "1"; i++) await new Promise(r => setTimeout(r, 50));
          await win.document.fonts.ready;
          byFmt[f] = await Design.importSlide(win, {name: slide.name, format: f, signature: poem.series_info?.signature,
            source: {slide: n, concept: slide.concept, page: a.page}});
        } finally { frame.remove(); }
      }
      const dd = Design.mergeFormats(byFmt, fmt);
      const r = await api("/api/design", {id: poem.id, design: dd});
      designs = r.designs; await load(r.slug);
      toast(`${slide.name} is now an editable design, in all three formats`);
    } catch (e) { toast(e.message, true); if (btn) btn.disabled = false; }
  }
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const startInfo = fmt => ({F: Design.FORMATS[fmt], format: fmt, lines: poem.lines, colours: colours(), fonts: poem.style?.fonts,
    safe: safeOf(fmt), signature: poem.series_info?.signature, title: poem.title});

  /* ——— the editor ——— */
  function shell() {
    root.innerHTML = `${bar(`
        <div class="edx-doc"><input class="edx-name" id="ed-dname" aria-label="Design name" spellcheck="false">
          <button class="edx-icon" id="ed-menu" title="Designs" aria-haspopup="true">${svg(ICON.caret, 16)}</button>
          <div class="edx-pop" id="ed-pop" hidden></div></div>
        <span class="edx-spacer"></span>
        <div class="seg edx-seg" id="ed-fmt" aria-label="Format">${formatEntries().map(([k, f]) => `<button data-fmt="${k}">${f.label}</button>`).join("")}</div>
        <span class="edx-spacer"></span>
        <div class="edx-group"><button class="edx-icon" id="ed-guides" title="Guides: safe zones and centre lines (G)">${svg(ICON.guides)}</button>
          <div class="seg edx-seg" id="ed-sig" aria-label="Name"><button data-sig="1">Name</button><button data-sig="0">No name</button></div></div>
        <div class="edx-group"><button class="edx-icon" id="ed-undo" title="Undo (Ctrl+Z)">${svg(ICON.undo)}</button>
          <button class="edx-icon" id="ed-redo" title="Redo (Ctrl+Shift+Z)">${svg(ICON.redo)}</button></div>
        <div class="edx-group edx-zoom"><button class="edx-icon" data-zoom="-1" title="Zoom out (−)">−</button>
          <button class="edx-icon edx-pct" id="ed-z" title="Fit to screen (Shift+1)">100%</button><button class="edx-icon" data-zoom="1" title="Zoom in (+)">+</button></div>
        <button class="btn red edx-export" id="ed-export">Export</button>`)}
      <div class="edx-body">
        <nav class="edx-tools" aria-label="Tools">${TOOLS.map(([k, n, key]) =>
          `<button class="edx-tool" data-tool="${k}" title="${n}  ${key}" aria-label="${n}">${svg(ICON[k])}<kbd>${key}</kbd></button>`).join("")}
          <span class="edx-sep"></span>
          <button class="edx-tool word" id="ed-poem" title="Place the poem as text"><b>Poem</b></button>
          <button class="edx-tool word" id="ed-name" title="Place the signature (left out of unsigned exports)"><b>Name</b></button>
          <span class="edx-sep"></span>
          <button class="edx-tool" id="ed-stamps" title="Stamps: reusable pieces for the whole series" aria-label="Stamps">${svg(ICON.stamp)}</button></nav>
        <div class="edx-stamps" id="ed-stampbox" hidden></div>
        <div class="edx-stage" id="ed-stage"><div class="edx-world" id="ed-world"><div class="edx-board" id="ed-board"></div></div><canvas id="ed-canvas"></canvas></div>
        <aside class="edx-side">
          <section class="edx-sec edx-layers-sec"><header><span>Layers</span><span class="edx-acts">
            <button class="edx-icon sm" id="ed-addl" title="Add a layer">+</button>
            <button class="edx-icon sm" id="ed-addg" title="Group the selected layers (Ctrl+G)"><svg viewBox="0 0 22 22" width="16" height="16" aria-hidden="true"><path d="M3 6h6l2 2h8v10H3z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M11 11v5M8.5 13.5h5" stroke="currentColor" stroke-width="1.6"/></svg></button>
            <button class="edx-icon sm" id="ed-up" title="Bring forward ( ] )">${svg(ICON.up, 16)}</button>
            <button class="edx-icon sm" id="ed-down" title="Send backward ( [ )">${svg(ICON.down, 16)}</button></span></header>
            <ol class="edx-layers" id="ed-layers"></ol></section>
          <div id="ed-props"></div>
        </aside>
      </div>
      <footer class="edx-status"><span id="st-doc"></span><span id="st-pos"></span><span id="st-sel"></span><span class="edx-spacer"></span>
        <span id="st-exp"></span><span class="edx-saved" id="ed-saved">Saved</span></footer>`;
    stage = $("#ed-stage", root); canvas = $("#ed-canvas", root); cx = canvas.getContext("2d");
    world = $("#ed-world", root); board = $("#ed-board", root);
    Design.onMetrics = () => { paint(); };
    ro = new ResizeObserver(() => { sizeCanvas(); if (view.auto) fit(); paint(); }); ro.observe(stage);
    sizeCanvas();
    const nameIn = $("#ed-dname", root);
    nameIn.value = d.name;
    nameIn.onchange = () => { mutate(() => { d.name = nameIn.value.trim() || "Untitled"; }); };
    nameIn.onkeydown = e => { if (e.key === "Enter") nameIn.blur(); };
    $("#ed-menu", root).onclick = toggleMenu;
    $$("[data-fmt]", root).forEach(b => b.onclick = () => setFormat(b.dataset.fmt));
    $$("[data-sig]", root).forEach(b => b.onclick = () => { signedPreview = b.dataset.sig === "1"; paint(); });
    $("#ed-guides", root).onclick = () => { guides = !guides; pref.set("guides", guides ? "1" : "0"); paint(); };
    $("#ed-undo", root).onclick = () => step(undo, redo);
    $("#ed-redo", root).onclick = () => step(redo, undo);
    $$("[data-zoom]", root).forEach(b => b.onclick = () => zoomBy(+b.dataset.zoom > 0 ? 1.25 : 0.8));
    $("#ed-z", root).onclick = () => { fit(); paint(); };
    $("#ed-export", root).onclick = exportPng;
    $$("[data-tool]", root).forEach(b => b.onclick = () => setTool(b.dataset.tool));
    $("#ed-poem", root).onclick = insertPoem;
    $("#ed-name", root).onclick = insertName;
    $("#ed-stamps", root).onclick = () => { const b = $("#ed-stampbox", root); b.hidden = !b.hidden; if (!b.hidden) stampsPanel(); };
    $("#ed-up", root).onclick = () => arrange("forward");
    $("#ed-addg", root).onclick = groupSel;
    $("#ed-addl", root).onclick = ev => { const r = ev.currentTarget.getBoundingClientRect(); StudioMenu.open({preventDefault() {}, stopPropagation() {}, clientX: r.left - 160, clientY: r.bottom + 4}, addLayerMenu()); };
    $("#ed-down", root).onclick = () => arrange("backward");
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointerleave", () => { cursor = null; status(); if (hover) { hover = null; paint(); } });
    canvas.addEventListener("dblclick", onDbl);
    canvas.addEventListener("contextmenu", onCtx);
    canvas.addEventListener("wheel", onWheel, {passive: false});
    syncBar();
  }

  function toggleMenu(ev) {
    ev?.stopPropagation();
    const pop = $("#ed-pop", root);
    if (!pop.hidden) { pop.hidden = true; return; }
    pop.innerHTML = `<div class="edx-pop-list">${designs.map(x => `<button data-go="${esc(x.slug)}" class="${x.slug === slug ? "on" : ""}"><span>${esc(x.name)}</span><em>${Design.FORMATS[shownFormat(x.format)]?.label || ""}</em></button>`).join("")}</div>
      <div class="edx-pop-acts"><button data-act="hub">All designs · new…</button><button data-act="dup">Duplicate</button><button data-act="del" class="bad">Move to trash</button></div>`;
    pop.hidden = false;
    $$("[data-go]", pop).forEach(b => b.onclick = () => { pop.hidden = true; flush(); if (b.dataset.go !== slug) load(b.dataset.go); });
    $("[data-act=hub]", pop).onclick = () => { pop.hidden = true; flush(); hub(); };
    $("[data-act=dup]", pop).onclick = () => { pop.hidden = true; duplicateDesign(); };
    $("[data-act=del]", pop).onclick = () => { pop.hidden = true; deleteDesign(); };
  }
  function closeMenus(ev) { const pop = root && $("#ed-pop", root); if (pop && !pop.hidden && !ev.target.closest(".edx-doc")) pop.hidden = true; }

  function syncBar() {
    if (!d || !root || !$("#ed-fmt", root)) return;
    $$("[data-fmt]", root).forEach(b => b.setAttribute("aria-pressed", b.dataset.fmt === d.format));
    $$("[data-sig]", root).forEach(b => b.setAttribute("aria-pressed", (b.dataset.sig === "1") === signedPreview));
    $("#ed-guides", root).setAttribute("aria-pressed", guides);
    $$("[data-tool]", root).forEach(b => b.setAttribute("aria-pressed", b.dataset.tool === tool));
    $("#ed-z", root).textContent = Math.round(view.z * 100) + "%";
    $("#ed-undo", root).disabled = !undo.length; $("#ed-redo", root).disabled = !redo.length;
    const n = $("#ed-dname", root); if (document.activeElement !== n) n.value = d.name;
    status();
  }
  function status() {
    if (!d || !root || !$("#st-doc", root)) return;
    const f = F(), es = selected();
    $("#st-doc", root).textContent = `${f.w} × ${f.h} · ${f.label}`;
    $("#st-pos", root).textContent = cursor ? `x ${Math.round(cursor.x)}  y ${Math.round(cursor.y)}` : "";
    if (es.length === 1) { const b = Design.bounds(es[0]); $("#st-sel", root).textContent = `${label(es[0])} · ${fmt1(b.w)} × ${fmt1(b.h)}`; }
    else $("#st-sel", root).textContent = es.length ? `${es.length} selected` : "";
    const ex = designs.find(x => x.slug === slug)?.exports?.[d.format];
    $("#st-exp", root).innerHTML = ex?.signed ? `<a href="/files/${ex.signed.split("/").map(encodeURIComponent).join("/")}?v=${ex.signed_v}" target="_blank" rel="noopener">Last export ↗</a>` : "";
  }

  /* ——— view ——— */
  function sizeCanvas() {
    const r = stage.getBoundingClientRect(), dpr = devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(r.width * dpr)); canvas.height = Math.max(1, Math.round(r.height * dpr));
    canvas.style.width = r.width + "px"; canvas.style.height = r.height + "px";
  }
  function fit() {
    const r = stage.getBoundingClientRect(), f = F();
    view.z = Math.max(.05, Math.min((r.width - 120) / f.w, (r.height - 110) / f.h));
    view.x = (r.width - f.w * view.z) / 2; view.y = (r.height - f.h * view.z) / 2 + 8; view.auto = true;
    syncBar();
  }
  function zoomBy(k, at) {
    const r = stage.getBoundingClientRect(), px = at ? at.x : r.width / 2, py = at ? at.y : r.height / 2;
    const dx = (px - view.x) / view.z, dy = (py - view.y) / view.z;
    view.z = Math.max(.05, Math.min(8, view.z * k)); view.auto = false;
    view.x = px - dx * view.z; view.y = py - dy * view.z;
    paint();
  }
  const toDesign = ev => { const r = canvas.getBoundingClientRect(); return {x: (ev.clientX - r.left - view.x) / view.z, y: (ev.clientY - r.top - view.y) / view.z, sx: ev.clientX - r.left, sy: ev.clientY - r.top}; };
  const toScreen = (x, y) => ({x: view.x + x * view.z, y: view.y + y * view.z});

  /* ——— painting ——— */
  /* chrome colours on the overlay follow the theme (the design underneath keeps its own) */
  const ink = {red: "#DA291C", handle: "#EEEAE2", onRed: "#0C0E11", fog: "#8E939B"};
  function readInk() {
    const st = getComputedStyle(document.documentElement), v = (n, d) => st.getPropertyValue(n).trim() || d;
    ink.red = v("--red", ink.red); ink.handle = v("--handle", ink.handle); ink.onRed = v("--night", ink.onRed); ink.fog = v("--fog", ink.fog);
  }
  const tint = a => { const n = parseInt(ink.red.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
  function paint() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; paintNow(); }); }
  function paintNow() {
    if (!d || !cx || !root || !board) return;
    readInk();
    const dpr = devicePixelRatio || 1, f = F(), s = S(), z = view.z;
    world.style.transform = `translate(${view.x}px,${view.y}px) scale(${z})`;
    Design.render(board, d, {signed: signedPreview, format: d.format});
    cx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cx.clearRect(0, 0, canvas.width / dpr, canvas.height / dpr);
    cx.font = '600 11px "Archivo"'; cx.letterSpacing = "1.5px"; cx.fillStyle = ink.fog; cx.textBaseline = "alphabetic";
    cx.fillText(`${d.name.toUpperCase()}  ·  ${f.label}`, Math.round(view.x), Math.round(view.y - 12));
    cx.letterSpacing = "0px";
    cx.save(); cx.translate(view.x, view.y); cx.scale(z, z);
    if (guides) {
      cx.lineWidth = 1 / z;
      if (d.format === "916") { cx.fillStyle = "rgba(15,17,20,.38)"; cx.fillRect(0, 0, f.w, s.t); cx.fillRect(0, f.h - s.b, f.w, s.b); }
      cx.setLineDash([5 / z, 4 / z]); cx.strokeStyle = "rgba(120,190,255,.55)";
      for (const y of [s.t, f.h - s.b]) { cx.beginPath(); cx.moveTo(0, y); cx.lineTo(f.w, y); cx.stroke(); }
      for (const x of [s.s, f.w - s.s]) { cx.beginPath(); cx.moveTo(x, 0); cx.lineTo(x, f.h); cx.stroke(); }
      cx.setLineDash([]); cx.strokeStyle = "rgba(120,190,255,.22)";
      cx.beginPath(); cx.moveTo(f.w / 2, 0); cx.lineTo(f.w / 2, f.h); cx.moveTo(0, f.h / 2); cx.lineTo(f.w, f.h / 2); cx.stroke();
    }
    const outline = (e, color, w) => {
      cx.save(); cx.strokeStyle = color; cx.lineWidth = w / z;
      if (e.type === "line") { cx.beginPath(); cx.moveTo(e.x1, e.y1); cx.lineTo(e.x2, e.y2); cx.stroke(); }
      else { const b = Design.bounds(e); rotateAround(cx, e, b); cx.strokeRect(b.x, b.y, b.w, b.h); }
      cx.restore();
    };
    if (hover && !sel.includes(hover) && byId(hover)) outline(byId(hover), tint(.6), 1);
    for (const e of selected()) outline(e, ink.red, 1.5);
    cx.strokeStyle = ink.red; cx.lineWidth = 1 / z;
    for (const l of snapLines) { cx.beginPath(); if (l.x != null) { cx.moveTo(l.x, -4000); cx.lineTo(l.x, f.h + 4000); } else { cx.moveTo(-4000, l.y); cx.lineTo(f.w + 4000, l.y); } cx.stroke(); }
    cx.restore();
    if (sel.length === 1 && !drag?.creating) {
      const e = selected()[0];
      cx.lineWidth = 1.5;
      for (const h of handles(e)) {
        const p = toScreen(h.x, h.y);
        if (h.h === "rot") {
          const c = toScreen(h.cx, h.cy);
          cx.strokeStyle = tint(.7); cx.beginPath(); cx.moveTo(c.x, c.y); cx.lineTo(p.x, p.y); cx.stroke();
          cx.fillStyle = ink.red; cx.beginPath(); cx.arc(p.x, p.y, 5, 0, Math.PI * 2); cx.fill();
          continue;
        }
        cx.fillStyle = ink.handle; cx.strokeStyle = ink.red;
        cx.fillRect(p.x - 4.5, p.y - 4.5, 9, 9); cx.strokeRect(p.x - 4.5, p.y - 4.5, 9, 9);
      }
      const b = Design.bounds(e), at = toScreen(b.x + b.w / 2, b.y + b.h);
      const txt = e.type === "text" ? `${fmt1(b.w)} × ${fmt1(b.h)}  ·  ${fmt1(e.size)} px` : `${fmt1(b.w)} × ${fmt1(b.h)}`;
      if (!e.rotation) badge(txt, at.x, at.y + 12);
    }
    const pe = pen ? byId(pen.id) : editPts ? byId(editPts) : null;
    if (pe?.pts?.length) {
      cx.save(); cx.translate(view.x, view.y); cx.scale(z, z); cx.lineWidth = 1 / z; cx.strokeStyle = ink.red;
      cx.stroke(new Path2D(Design.pathD(pe.pts, pe.closed))); cx.restore();
      if (pen && cursor && !drag) {
        const last = pe.pts.at(-1), a = toScreen(last.x, last.y), o = toScreen(last.ox ?? last.x, last.oy ?? last.y), c2 = toScreen(cursor.x, cursor.y);
        cx.setLineDash([4, 3]); cx.strokeStyle = tint(.85); cx.lineWidth = 1;
        cx.beginPath(); cx.moveTo(a.x, a.y); cx.bezierCurveTo(o.x, o.y, c2.x, c2.y, c2.x, c2.y); cx.stroke(); cx.setLineDash([]);
      }
      cx.lineWidth = 1;
      for (const q of pe.pts) {
        const a = toScreen(q.x, q.y);
        for (const [kx, ky] of [["ix", "iy"], ["ox", "oy"]]) if (q[kx] != null) {
          const h = toScreen(q[kx], q[ky]);
          cx.strokeStyle = tint(.8); cx.beginPath(); cx.moveTo(a.x, a.y); cx.lineTo(h.x, h.y); cx.stroke();
          cx.fillStyle = ink.red; cx.beginPath(); cx.arc(h.x, h.y, 3.5, 0, Math.PI * 2); cx.fill();
        }
        cx.fillStyle = ink.handle; cx.strokeStyle = ink.red; cx.fillRect(a.x - 3.5, a.y - 3.5, 7, 7); cx.strokeRect(a.x - 3.5, a.y - 3.5, 7, 7);
      }
    }
    if (drag?.marquee && drag.rect) {
      const a = toScreen(drag.rect.x, drag.rect.y), b = toScreen(drag.rect.x + drag.rect.w, drag.rect.y + drag.rect.h);
      cx.fillStyle = tint(.08); cx.fillRect(a.x, a.y, b.x - a.x, b.y - a.y);
      cx.strokeStyle = ink.red; cx.lineWidth = 1; cx.strokeRect(a.x + .5, a.y + .5, b.x - a.x, b.y - a.y);
    }
    if (inGroup && members(inGroup).length) {   // inside a group: show the group's box faintly
      const bs = members(inGroup).map(id => Design.bounds(byId(id))), x0 = Math.min(...bs.map(b => b.x)), y0 = Math.min(...bs.map(b => b.y));
      const a = toScreen(x0, y0), b = toScreen(Math.max(...bs.map(b => b.x + b.w)), Math.max(...bs.map(b => b.y + b.h)));
      cx.setLineDash([4, 3]); cx.strokeStyle = tint(.7); cx.lineWidth = 1; cx.strokeRect(a.x - 4.5, a.y - 4.5, b.x - a.x + 9, b.y - a.y + 9); cx.setLineDash([]);
    }
    if (drag?.move && sel.length) {
      const bs = selected().map(e => Design.bounds(e)), x = Math.min(...bs.map(b => b.x)), y = Math.min(...bs.map(b => b.y));
      const p = toScreen(x, y); badge(`${fmt1(x)}, ${fmt1(y)}`, p.x, p.y - 26);
    }
    syncBar();
  }
  function badge(txt, x, y) {
    cx.font = '600 11px "Archivo"'; cx.textBaseline = "middle";
    const w = cx.measureText(txt).width + 14;
    cx.fillStyle = ink.red; cx.fillRect(Math.round(x - w / 2), Math.round(y), Math.round(w), 20);
    cx.fillStyle = ink.onRed; cx.fillText(txt, Math.round(x - w / 2 + 7), Math.round(y + 10.5));
    cx.textBaseline = "alphabetic";
  }
  function rotateAround(c, e, b) {
    if (!e.rotation || e.type === "line") return;
    const x = b.x + b.w / 2, y = b.y + b.h / 2;
    c.translate(x, y); c.rotate(e.rotation * Math.PI / 180); c.translate(-x, -y);
  }
  const rot = (px, py, cxp, cyp, deg) => { const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), dx = px - cxp, dy = py - cyp; return {x: cxp + dx * c - dy * s, y: cyp + dx * s + dy * c}; };

  function ptHandles(e) {   // a path's anchors and curve handles, handles first so they win when they overlap
    const out = [];
    (e.pts || []).forEach((q, i) => {
      if (q.ix != null) out.push({x: q.ix, y: q.iy, k: "i", i});
      if (q.ox != null) out.push({x: q.ox, y: q.oy, k: "o", i});
    });
    (e.pts || []).forEach((q, i) => out.push({x: q.x, y: q.y, k: "a", i}));
    return out;
  }
  function handles(e) {
    if (e.type === "path" && editPts === e.id) return [];
    if (e.type === "line") return [{x: e.x1, y: e.y1, h: "p1"}, {x: e.x2, y: e.y2, h: "p2"}];
    const b = Design.bounds(e), xs = [b.x, b.x + b.w / 2, b.x + b.w], ys = [b.y, b.y + b.h / 2, b.y + b.h];
    const c = {x: b.x + b.w / 2, y: b.y + b.h / 2};
    const hs = [["nw", 0, 0], ["n", 1, 0], ["ne", 2, 0], ["e", 2, 1], ["se", 2, 2], ["s", 1, 2], ["sw", 0, 2], ["w", 0, 1]]
      .filter(([k]) => e.type !== "text" || k.length === 2)
      .map(([h, i, j]) => ({h, x: xs[i], y: ys[j]}));
    hs.push({h: "rot", x: c.x, y: b.y - 28 / view.z, cx: c.x, cy: b.y});
    if (!e.rotation) return hs;
    return hs.map(p => { const q = rot(p.x, p.y, c.x, c.y, e.rotation); const r = p.h === "rot" ? rot(p.cx, p.cy, c.x, c.y, e.rotation) : null;
      return {...p, ...q, ...(r ? {cx: r.x, cy: r.y} : {})}; });
  }

  function hit(p) {
    for (let i = d.elements.length - 1; i >= 0; i--) {
      const e = px(d.elements[i]);
      if (!shown(e) || e.locked || (!signedPreview && e.role === "name")) continue;
      if (e.type === "line") {
        const {x1, y1, x2, y2} = e, L2 = (x2 - x1) ** 2 + (y2 - y1) ** 2;
        const t = L2 ? Math.max(0, Math.min(1, ((p.x - x1) * (x2 - x1) + (p.y - y1) * (y2 - y1)) / L2)) : 0;
        if (Math.hypot(p.x - (x1 + t * (x2 - x1)), p.y - (y1 + t * (y2 - y1))) <= Math.max(6 / view.z, (e.width || 4) / 2)) return e;
        continue;
      }
      const b = Design.bounds(e);
      const q = e.rotation ? rot(p.x, p.y, b.x + b.w / 2, b.y + b.h / 2, -e.rotation) : p;
      const pad = 3 / view.z;
      if (q.x >= b.x - pad && q.x <= b.x + b.w + pad && q.y >= b.y - pad && q.y <= b.y + b.h + pad) return e;
    }
    return null;
  }

  /* ——— snapping: to the frame, the safe lines, the centre, and every other element's ink edges and baselines ——— */
  function targets(skip) {
    const f = F(), s = S(), xs = [0, f.w / 2, f.w, s.s, f.w - s.s], ys = [0, f.h / 2, f.h, s.t, f.h - s.b];
    for (const raw of d.elements) {
      const e = px(raw);
      if (skip.has(e.id) || !shown(e) || e.rotation) continue;
      const b = Design.bounds(e);
      xs.push(b.x, b.x + b.w / 2, b.x + b.w); ys.push(b.y, b.y + b.h / 2, b.y + b.h);
      if (e.type === "text") Design.layout(e).lines.forEach(l => ys.push(e.y + l.base));
    }
    return {xs, ys};
  }
  function snap(vals, tgts) {
    const tol = 6 / view.z;
    let best = null;
    for (const v of vals) for (const t of tgts) { const dl = t - v; if (Math.abs(dl) <= tol && (!best || Math.abs(dl) < Math.abs(best.d))) best = {d: dl, at: t}; }
    return best;
  }

  /* ——— pointer ——— */
  function onDown(ev) {
    if (!d || ev.button === 2) return;
    canvas.setPointerCapture(ev.pointerId);
    const p = toDesign(ev);
    if (space || ev.button === 1) { drag = {pan: true, sx: p.sx, sy: p.sy, vx: view.x, vy: view.y}; canvas.style.cursor = "grabbing"; return; }
    if (tool === "pen") return penDown(p);
    if (tool !== "select") return startCreate(p);
    if (editPts && sel[0] === editPts) {
      const e = byId(editPts);
      const h = e && ptHandles(e).find(q => { const s2 = toScreen(q.x, q.y); return Math.abs(s2.x - p.sx) <= 7 && Math.abs(s2.y - p.sy) <= 7; });
      if (h) { drag = {pt: h, id: e.id, orig: JSON.parse(JSON.stringify(e.pts)), start: p, before: JSON.stringify(d)}; return; }
    }
    if (sel.length === 1) {
      const e = selected()[0];
      const h = handles(e).find(h => { const s = toScreen(h.x, h.y); return Math.abs(s.x - p.sx) <= 7 && Math.abs(s.y - p.sy) <= 7; });
      if (h) {
        const b = Design.bounds(e);
        drag = h.h === "rot" ? {rotate: true, id: e.id, c: {x: b.x + b.w / 2, y: b.y + b.h / 2}, orig: e.rotation || 0, a0: Math.atan2(p.y - (b.y + b.h / 2), p.x - (b.x + b.w / 2)), before: JSON.stringify(d)}
          : {resize: h.h, id: e.id, start: p, orig: JSON.parse(JSON.stringify(e)), before: JSON.stringify(d)};
        return;
      }
    }
    const e = hit(p);
    const additive = ev.shiftKey || ev.ctrlKey || ev.metaKey;
    if (editPts && (!e || e.id !== editPts)) editPts = null;
    if (!e) {   // drag on empty space: select everything the box touches
      inGroup = null;
      drag = {marquee: true, start: p, base: additive ? [...sel] : []};
      if (!additive) sel = [];
      paint(); panels(); return;
    }
    if (inGroup && e.group !== inGroup) inGroup = null;
    const ids = expand([e.id]);
    if (additive) { const all = ids.every(id => sel.includes(id)); sel = all ? sel.filter(x => !ids.includes(x)) : [...new Set([...sel, ...ids])]; }
    else if (!sel.includes(e.id)) sel = ids;
    anchor = e.id;
    const before = JSON.stringify(d);
    if (ev.altKey) {   // alt-drag copies
      const copies = cloneRaws(selected().map(o => o.__raw));
      d.elements.push(...copies); sel = copies.map(c => c.id);
    }
    drag = {move: true, start: p, orig: selected().map(o => JSON.parse(JSON.stringify(o))), before, copied: ev.altKey};
    panels(); paint();
  }

  function onMove(ev) {
    if (!d) return;
    const p = toDesign(ev);
    cursor = p;
    if (!drag) {
      const h = tool === "select" ? hit(p)?.id || null : null;
      if (h !== hover) { hover = h; paint(); } else status();
      let cur = space ? "grab" : tool === "select" ? (h ? "move" : "default") : "crosshair";
      if (tool === "select" && sel.length === 1) {
        const hd = handles(selected()[0]).find(x => { const s = toScreen(x.x, x.y); return Math.abs(s.x - p.sx) <= 7 && Math.abs(s.y - p.sy) <= 7; });
        if (hd) cur = hd.h === "rot" ? "grab" : hd.h.startsWith("p") ? "crosshair" : {n: "ns", s: "ns", e: "ew", w: "ew", nw: "nwse", se: "nwse", ne: "nesw", sw: "nesw"}[hd.h] + "-resize";
      }
      canvas.style.cursor = cur;
      return;
    }
    if (drag.pan) { view.x = drag.vx + p.sx - drag.sx; view.y = drag.vy + p.sy - drag.sy; view.auto = false; paint(); return; }
    if (drag.marquee) {
      const r = drag.rect = {x: Math.min(drag.start.x, p.x), y: Math.min(drag.start.y, p.y), w: Math.abs(p.x - drag.start.x), h: Math.abs(p.y - drag.start.y)};
      const got = [];
      for (const raw of d.elements) {
        const e = px(raw);
        if (!shown(e) || e.locked || (!signedPreview && e.role === "name")) continue;
        const b = Design.bounds(e);
        if (b.x <= r.x + r.w && b.x + b.w >= r.x && b.y <= r.y + r.h && b.y + b.h >= r.y) got.push(e.id);
      }
      const next = [...new Set([...drag.base, ...expand(got)])];
      if (next.join() !== sel.join()) { sel = next; panels(); }
      paint(); return;
    }
    snapLines = [];
    if (drag.rotate) {
      const e = byId(drag.id);
      let a = drag.orig + (Math.atan2(p.y - drag.c.y, p.x - drag.c.x) - drag.a0) * 180 / Math.PI;
      a = ((a % 360) + 540) % 360 - 180;
      if (ev.shiftKey) a = Math.round(a / 15) * 15;
      else if (Math.abs(a) < 2) a = 0;
      e.rotation = Math.round(a * 10) / 10; drag.rotated = true;
    } else if (drag.move) {
      let dx = p.x - drag.start.x, dy = p.y - drag.start.y;
      if (ev.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
      const boxes = drag.orig.map(o => Design.bounds(o));
      const bx = Math.min(...boxes.map(b => b.x)), by = Math.min(...boxes.map(b => b.y));
      const bw = Math.max(...boxes.map(b => b.x + b.w)) - bx, bh = Math.max(...boxes.map(b => b.y + b.h)) - by;
      if (!ev.ctrlKey) {
        const t = targets(new Set(sel));
        const sx = snap([bx + dx, bx + dx + bw / 2, bx + dx + bw], t.xs);
        const extra = drag.orig.length === 1 && drag.orig[0].type === "text" ? Design.layout(drag.orig[0]).lines.map(l => by + dy + l.base) : [];
        const sy = snap([by + dy, by + dy + bh / 2, by + dy + bh, ...extra], t.ys);
        if (sx) { dx += sx.d; snapLines.push({x: sx.at}); }
        if (sy) { dy += sy.d; snapLines.push({y: sy.at}); }
      }
      drag.orig.forEach(o => moveEl(byId(o.id), o, dx, dy, round));
      drag.moved = Math.abs(dx) + Math.abs(dy) > 0;
    } else if (drag.pt) {   // moving a path's anchor or one of its curve handles
      const e = byId(drag.id), pts = JSON.parse(JSON.stringify(drag.orig)), q = pts[drag.pt.i];
      if (drag.pt.k === "a") pts[drag.pt.i] = Design.movePoints([q], p.x - drag.start.x, p.y - drag.start.y)[0];
      else {
        const k = drag.pt.k, other = k === "i" ? "o" : "i";
        q[k + "x"] = r2(p.x); q[k + "y"] = r2(p.y);
        if (!ev.altKey && q[other + "x"] != null) {   // smooth: the other handle mirrors the angle (Alt breaks it)
          const len = Math.hypot(q[other + "x"] - q.x, q[other + "y"] - q.y), a = Math.atan2(q.y - p.y, q.x - p.x);
          q[other + "x"] = r2(q.x + Math.cos(a) * len); q[other + "y"] = r2(q.y + Math.sin(a) * len);
        }
      }
      e.pts = pts; drag.resized = true;
    } else if (drag.penHandle) {   // dragging while placing a point pulls out its curve
      const e = byId(drag.id), pts = e.pts.map(q => ({...q})), q = pts[drag.i];
      if (Math.hypot(p.x - q.x, p.y - q.y) > 3 / view.z) { q.ox = r2(p.x); q.oy = r2(p.y); q.ix = r2(2 * q.x - p.x); q.iy = r2(2 * q.y - p.y); }
      e.pts = pts;
    } else if (drag.resize) resizeTo(p, ev);
    else if (drag.creating) createTo(p, ev);
    paint();
  }

  function onUp() {
    if (!drag) return;
    const was = drag;
    drag = null; snapLines = [];
    if (was.pan) { canvas.style.cursor = space ? "grab" : "default"; return; }
    if (was.marquee) { paint(); panels(); return; }
    if (was.penHandle) { if (was.closing) finishPen(); else { paint(); panels(); } return; }
    if (was.creating) {
      const e = byId(was.id), b = e && Design.bounds(e);
      if (e && b.w < 3 && b.h < 3) { if (e.type === "line") e.x2 = e.x1 + 300; else if (e.type === "path") e.pts = arcPts(e.pts[0], {x: e.pts[0].x + 400, y: e.pts[0].y}, e.bend ?? .5); else { e.w = 240; e.h = 240; } }
      if (e?.__raw.at?.[d.format]) Object.assign(e.__raw, e.__raw.at[d.format]);
      setTool("select");
    }
    if ((was.moved || was.copied || was.resized || was.rotated || was.creating) && was.before) {
      undo.push(was.before); redo = []; lastKey = null; scheduleSave();
    }
    paint(); panels();
  }

  function onDbl(ev) {
    if (pen) { finishPen(); return; }
    const e = hit(toDesign(ev));
    if (!e) return;
    if (e.type === "path") { editPts = e.id; sel = [e.id]; panels(); paint(); toast("Editing points · drag anchors and handles, Alt for a corner, Esc when done"); return; }
    if (e.group && inGroup !== e.group) { inGroup = e.group; sel = [e.id]; anchor = e.id; panels(); paint(); return; }   // go inside the group
    if (e.type === "text") { sel = [e.id]; panels(); paint(); const t = $("#p-text", root); t?.focus(); t?.select(); }
  }

  function onWheel(ev) {
    ev.preventDefault();
    if (ev.ctrlKey || ev.metaKey) { const p = toDesign(ev); zoomBy(ev.deltaY < 0 ? 1.1 : 1 / 1.1, {x: p.sx, y: p.sy}); }
    else { view.x -= ev.shiftKey ? ev.deltaY : ev.deltaX; view.y -= ev.shiftKey ? 0 : ev.deltaY; view.auto = false; paint(); }
  }

  function resizeTo(p, ev) {
    const o = drag.orig, e = byId(drag.id), h = drag.resize;
    if (e.type === "line") {
      let x = p.x, y = p.y;
      const ax = h === "p1" ? o.x2 : o.x1, ay = h === "p1" ? o.y2 : o.y1;
      if (ev.shiftKey) {
        const a = Math.round(Math.atan2(y - ay, x - ax) / (Math.PI / 4)) * Math.PI / 4, len = Math.hypot(x - ax, y - ay);
        x = ax + Math.cos(a) * len; y = ay + Math.sin(a) * len;
      } else if (!ev.ctrlKey) {
        const t = targets(new Set([e.id])), sx = snap([x], t.xs), sy = snap([y], t.ys);
        if (sx) { x += sx.d; snapLines.push({x: sx.at}); } if (sy) { y += sy.d; snapLines.push({y: sy.at}); }
      }
      if (h === "p1") { e.x1 = round(x); e.y1 = round(y); } else { e.x2 = round(x); e.y2 = round(y); }
      drag.resized = true; return;
    }
    const b = Design.bounds(o);
    let x0 = b.x, y0 = b.y, x1 = b.x + b.w, y1 = b.y + b.h, px = p.x, py = p.y;
    if (!ev.ctrlKey && !e.rotation) {
      const t = targets(new Set([e.id]));
      const sx = /[we]/.test(h) ? snap([px], t.xs) : null, sy = /[ns]/.test(h) ? snap([py], t.ys) : null;
      if (sx) { px += sx.d; snapLines.push({x: sx.at}); } if (sy) { py += sy.d; snapLines.push({y: sy.at}); }
    }
    if (h.includes("w")) x0 = Math.min(px, x1 - 4); if (h.includes("e")) x1 = Math.max(px, x0 + 4);
    if (h.includes("n")) y0 = Math.min(py, y1 - 4); if (h.includes("s")) y1 = Math.max(py, y0 + 4);
    if (e.type === "text") {   // text scales its type size from the opposite corner
      e.size = Math.max(1, Math.round(o.size * Math.max((x1 - x0) / b.w, .02) * 10) / 10);
      const nb = Design.bounds(e);
      e.x = round(h.includes("w") ? b.x + b.w - nb.w : b.x);
      e.y = round(h.includes("n") ? b.y + b.h - nb.h : b.y);
    } else {
      if (ev.shiftKey && h.length === 2) {
        const k = Math.max((x1 - x0) / b.w, (y1 - y0) / b.h), w = b.w * k, hh = b.h * k;
        if (h.includes("w")) x0 = x1 - w; else x1 = x0 + w;
        if (h.includes("n")) y0 = y1 - hh; else y1 = y0 + hh;
      }
      if (e.type === "path") {   // scale the points into the new box
        const sx = (x1 - x0) / (b.w || 1), sy = (y1 - y0) / (b.h || 1), m = (x, y) => [r2(x0 + (x - b.x) * sx), r2(y0 + (y - b.y) * sy)];
        e.pts = o.pts.map(q => { const n = {...q}; [n.x, n.y] = m(q.x, q.y); if (q.ix != null) [n.ix, n.iy] = m(q.ix, q.iy); if (q.ox != null) [n.ox, n.oy] = m(q.ox, q.oy); return n; });
      } else { e.x = round(x0); e.y = round(y0); e.w = round(x1 - x0); e.h = round(y1 - y0); }
    }
    drag.resized = true;
  }

  function arcPts(a, b, bend) {
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1, k = bend * len * 2 / 3, nx = dy / len * k, ny = -dx / len * k;   // bends up for a left-to-right drag
    return [{x: r2(a.x), y: r2(a.y), ox: r2(a.x + nx), oy: r2(a.y + ny)}, {x: r2(b.x), y: r2(b.y), ix: r2(b.x + nx), iy: r2(b.y + ny)}];
  }
  function startCreate(p) {
    const {text: light, accent} = colours();
    const x = round(p.x), y = round(p.y), before = JSON.stringify(d);
    let e;
    if (tool === "text") e = {type: "text", text: "Text", font: textFont(), weight: 500, size: 96, leading: 1.15, tracking: 0, color: light, x, y};
    else if (tool === "line") e = {type: "line", x1: x, y1: y, x2: x, y2: y, stroke: accent, width: 6};
    else if (tool === "arc") e = {type: "path", name: "Arc", arc: true, bend: .5, pts: arcPts({x, y}, {x, y}, .5), closed: false, fill: null, stroke: accent, sw: 6};
    else if (tool === "polygon" || tool === "star") e = {type: "shape", kind: tool, n: tool === "star" ? 5 : 3, ...(tool === "star" ? {inner: .45} : {}), x, y, w: 0, h: 0, fill: accent};
    else e = {type: tool, x, y, w: 0, h: 0, fill: accent};
    e.id = Design.uid();
    d.elements.push(e); sel = [e.id];
    if (tool === "text") {
      undo.push(before); redo = []; setTool("select"); scheduleSave(); panels(); paint();
      setTimeout(() => { $("#p-text", root)?.focus(); $("#p-text", root)?.select(); });
      return;
    }
    drag = {creating: true, id: e.id, start: p, before};
  }
  function createTo(p, ev) {
    const e = byId(drag.id), s = drag.start;
    if (e.type === "path") {   // the arc follows the pointer; Shift keeps it level or upright, Alt bends it the other way
      let x = p.x, y = p.y;
      if (ev.shiftKey) { if (Math.abs(x - s.x) > Math.abs(y - s.y)) y = s.y; else x = s.x; }
      e.bend = ev.altKey ? -Math.abs(e.bend ?? .5) : Math.abs(e.bend ?? .5);
      e.pts = arcPts(s, {x, y}, e.bend);
      return;
    }
    if (e.type === "line") {
      let x = p.x, y = p.y;
      if (ev.shiftKey) { const a = Math.round(Math.atan2(y - s.y, x - s.x) / (Math.PI / 4)) * Math.PI / 4, l = Math.hypot(x - s.x, y - s.y); x = s.x + Math.cos(a) * l; y = s.y + Math.sin(a) * l; }
      e.x2 = round(x); e.y2 = round(y);
    } else {
      let w = p.x - s.x, h = p.y - s.y;
      if (ev.shiftKey) { const m = Math.max(Math.abs(w), Math.abs(h)); w = Math.sign(w || 1) * m; h = Math.sign(h || 1) * m; }
      e.x = round(Math.min(s.x, s.x + w)); e.y = round(Math.min(s.y, s.y + h)); e.w = round(Math.abs(w)); e.h = round(Math.abs(h));
    }
  }
  function setTool(t) { if (pen && t !== "pen") finishPen(); tool = t; syncBar(); if (canvas) canvas.style.cursor = t === "select" ? "default" : "crosshair"; }

  /* ——— the pen ——— */
  function penDown(p) {
    const {accent} = colours();
    if (pen && !byId(pen.id)) pen = null;
    if (!pen) {
      const e = {id: Design.uid(), type: "path", name: "Path", pts: [{x: round(p.x), y: round(p.y)}], closed: false, fill: null, stroke: accent, sw: 4};
      pen = {id: e.id, before: JSON.stringify(d)};
      d.elements.push(e); sel = [e.id]; editPts = null;
      drag = {penHandle: true, id: e.id, i: 0};
      paint(); panels(); return;
    }
    const e = byId(pen.id), first = e.pts[0], s0 = toScreen(first.x, first.y);
    if (e.pts.length > 2 && Math.hypot(s0.x - p.sx, s0.y - p.sy) < 9) {   // back at the start: close the shape
      e.closed = true;
      if (!e.fill) e.fill = accent;
      drag = {penHandle: true, id: e.id, i: 0, closing: true};
      return;
    }
    e.pts = [...e.pts, {x: round(p.x), y: round(p.y)}];
    drag = {penHandle: true, id: e.id, i: e.pts.length - 1};
    paint();
  }
  function finishPen() {
    if (!pen) return;
    const e = byId(pen.id), before = pen.before;
    pen = null;
    if (e) {
      e.pts = e.pts.filter((q, i, a) => !i || Math.hypot(q.x - a[i - 1].x, q.y - a[i - 1].y) > .5);   // a double-click leaves doubles
      if (e.pts.length < 2) { d.elements = d.elements.filter(x => x.id !== e.id); sel = []; }
      else if (e.__raw.at?.[d.format]) Object.assign(e.__raw, e.__raw.at[d.format]);
    }
    undo.push(before); redo = []; lastKey = null; scheduleSave();
    tool = "select"; syncBar(); if (canvas) canvas.style.cursor = "default";
    paint(); panels();
  }

  /* ——— commands ——— */
  async function insertPoem() {
    const c = colours(), s = S(), f = F();
    const e = {id: Design.uid(), type: "text", name: "Poem", text: poem.lines.join("\n") || "Your poem", ...roles().text,
      size: 96, leading: 1.1, tracking: -12, color: c.text, accent: c.accent, x: s.s, y: s.t};
    await Design.loadMetrics([Design.mkey(e)]);
    if (Design.layout(e).w > f.w - 2 * s.s) await Design.fitWidth(e, f.w - 2 * s.s);
    mutate(() => { d.elements.push(e); sel = [e.id]; }); panels();
  }
  async function insertName() {
    const s = S(), f = F();
    const e = {id: Design.uid(), type: "text", role: "name", name: "Name", text: poem.series_info?.signature || "Your name",
      ...roles().label, size: 28, tracking: 260, case: "upper", leading: 1, color: colours().muted, x: s.s, y: 0};
    await Design.loadMetrics([Design.mkey(e)]);
    e.y = f.h - s.b - Design.layout(e).h;
    mutate(() => { d.elements.push(e); sel = [e.id]; }); panels();
  }
  function remove() { if (!sel.length) return; mutate(() => { d.elements = d.elements.filter(e => !sel.includes(e.id)); sel = []; pruneGroups(); }); panels(); }
  const offset = (raw, k) => { raw.id = Design.uid(); const c = px(raw); moveEl(c, c, k, k); return raw; };
  function duplicate() {
    if (!sel.length) return;
    const copies = cloneRaws(selected().map(o => o.__raw)).map(c => offset(c, 20));
    mutate(() => { d.elements.push(...copies); sel = copies.map(c => c.id); }); panels();
  }
  function copy() { if (sel.length) { clip = JSON.stringify(selected().map(e => e.__raw)); toast(`Copied ${sel.length === 1 ? "1 layer" : sel.length + " layers"}`); } }
  function paste() {
    if (!clip) return;
    const items = cloneRaws(JSON.parse(clip)).map(o => offset(o, 24));
    clip = JSON.stringify(items);
    mutate(() => { d.elements.push(...items); sel = items.map(c => c.id); }); panels();
  }
  function arrange(where) {
    if (!sel.length) return;
    mutate(() => {
      const isSel = e => sel.includes(e.id), moving = d.elements.filter(isSel), rest = d.elements.filter(e => !isSel(e));
      if (where === "front") d.elements = [...rest, ...moving];
      else if (where === "back") d.elements = [...moving, ...rest];
      else {
        const a = [...d.elements], idx = a.map((e, i) => isSel(e) ? i : -1).filter(i => i >= 0);
        if (where === "forward") for (const i of idx.reverse()) { if (i < a.length - 1 && !isSel(a[i + 1])) [a[i], a[i + 1]] = [a[i + 1], a[i]]; }
        else for (const i of idx) { if (i > 0 && !isSel(a[i - 1])) [a[i], a[i - 1]] = [a[i - 1], a[i]]; }
        d.elements = a;
      }
    });
    panels();
  }

  /* ——— right-click menus ——— */
  function elementMenu(extra = []) {
    const es = selected(), one = es.length === 1 ? es[0] : null;
    if (!es.length) return canvasMenu();
    const all = f => es.every(f);
    const allName = all(e => e.role === "name"), allClip = all(e => e.clip), allLocked = all(e => e.locked), hiddenHere = all(e => (e.hide || []).includes(d.format));
    const set = fn => { mutate(() => es.forEach(fn)); panels(); };
    return [
      ...extra,
      {label: "Copy", kbd: "Ctrl+C", act: copy},
      {label: "Paste", kbd: "Ctrl+V", act: paste, disabled: !clip},
      {label: "Duplicate", kbd: "Ctrl+D", act: duplicate},
      "-",
      {label: "Arrange", items: [
        {label: "Bring to front", kbd: "Ctrl+]", act: () => arrange("front")}, {label: "Bring forward", kbd: "]", act: () => arrange("forward")},
        {label: "Send backward", kbd: "[", act: () => arrange("backward")}, {label: "Send to back", kbd: "Ctrl+[", act: () => arrange("back")}]},
      {label: es.length > 1 ? "Align to each other" : "Align to the frame", items: [["left", "Left"], ["hcenter", "Centre"], ["right", "Right"], ["top", "Top"], ["vcenter", "Middle"], ["bottom", "Bottom"]]
        .map(([k, l]) => ({label: l, act: () => align(k, false)}))},
      ...(es.length > 2 ? [{label: "Even gaps", items: [{label: "Top to bottom", act: () => distribute("v")}, {label: "Left to right", act: () => distribute("h")}]}] : []),
      ...(es.length > 1 ? [{label: "Group", kbd: "Ctrl+G", act: groupSel}] : []),
      ...(es.some(e => e.group) ? [{label: "Ungroup", kbd: "Ctrl+Shift+G", act: ungroupSel}] : []),
      "-",
      ...(allClip ? [{label: one ? `Release from mask “${label(baseOf(one.id) || {type: "layer", name: "below"})}”` : "Release from their masks", act: () => releaseMask(es.map(e => e.id))},
        {label: "Invert mask", checked: all(e => e.clipInvert), act: () => { const v = !all(e => e.clipInvert); set(e => { if (v) e.clipInvert = true; else delete e.clipInvert; }); }}] : []),
      ...(one && unitOfBase(one.id)?.clips.length ? [{label: `Release mask (${unitOfBase(one.id).clips.length} masked)`, act: () => releaseMask(unitOfBase(one.id).clips.map(c => c.id))}] : []),
      {label: "Name (signature)", checked: allName, act: () => set(e => { if (allName) delete e.role; else e.role = "name"; })},
      {label: `Hide in ${F().label}`, checked: hiddenHere, act: () => { set(e => { const h = new Set(e.hide || []); if (hiddenHere) h.delete(d.format); else h.add(d.format); if (h.size) e.hide = [...h]; else delete e.hide; }); if (!hiddenHere) { sel = []; panels(); } }},
      {label: "Lock", checked: allLocked, act: () => { set(e => { e.locked = !allLocked; }); if (!allLocked) { sel = []; panels(); } }},
      ...(one?.type === "path" ? [{label: editPts === one.id ? "Stop editing points" : "Edit points", act: () => { editPts = editPts === one.id ? null : one.id; panels(); paint(); }},
        {label: one.closed ? "Open the path" : "Close the path", act: () => set(e => { e.closed = !one.closed; })}] : []),
      ...(one?.type === "text" ? [{label: "Edit text", kbd: "Double-click", act: () => { const t = $("#p-text", root); t?.focus(); t?.select(); }}] : []),
      "-",
      {label: "Save as stamp…", act: () => { const b = $("#ed-stampbox", root); b.hidden = false; stampsPanel().then(() => $("#st-name", root)?.focus()); }},
      "-",
      {label: es.length > 1 ? `Delete ${es.length} layers` : "Delete", kbd: "Del", danger: true, act: remove},
    ];
  }
  function addLayerMenu() {
    const {text: light, accent} = colours(), f = F(), cxm = f.w / 2, cym = f.h / 2;
    const add = e => { e.id = Design.uid(); mutate(() => { d.elements.push(e); sel = [e.id]; inGroup = null; }); panels(); if (e.type === "text") setTimeout(() => { $("#p-text", root)?.focus(); $("#p-text", root)?.select(); }); };
    return [
      {label: "Text", kbd: "T", act: () => add({type: "text", text: "Text", font: textFont(), weight: 500, size: 120, leading: 1.15, tracking: 0, color: light, x: cxm - 160, y: cym - 40})},
      {label: "Rectangle", kbd: "R", act: () => add({type: "rect", x: cxm - 200, y: cym - 150, w: 400, h: 300, fill: accent})},
      {label: "Ellipse", kbd: "O", act: () => add({type: "ellipse", x: cxm - 200, y: cym - 200, w: 400, h: 400, fill: accent})},
      {label: "Triangle", kbd: "Y", act: () => add({type: "shape", kind: "polygon", n: 3, x: cxm - 200, y: cym - 175, w: 400, h: 350, fill: accent})},
      {label: "Star", kbd: "S", act: () => add({type: "shape", kind: "star", n: 5, inner: .45, x: cxm - 200, y: cym - 200, w: 400, h: 400, fill: accent})},
      {label: "Line", kbd: "L", act: () => add({type: "line", x1: cxm - 240, y1: cym, x2: cxm + 240, y2: cym, stroke: accent, width: 6})},
      {label: "Pen path", kbd: "P", act: () => setTool("pen")},
      "-",
      {label: "The poem", act: insertPoem}, {label: "The name", act: insertName},
      {label: "Stamp…", act: () => { const b = $("#ed-stampbox", root); b.hidden = false; stampsPanel(); }},
    ];
  }
  function canvasMenu() {
    return [
      {label: "Paste", kbd: "Ctrl+V", act: paste, disabled: !clip},
      {label: "Select all", kbd: "Ctrl+A", act: () => { sel = d.elements.filter(e => !e.locked && Design.shownIn(e, d.format)).map(e => e.id); paint(); panels(); }},
      "-",
      {label: "Place the poem", act: insertPoem}, {label: "Place the name", act: insertName},
      {label: "Stamps…", act: () => { const b = $("#ed-stampbox", root); b.hidden = false; stampsPanel(); }},
      "-",
      {label: "Fit to screen", kbd: "Shift+1", act: () => { fit(); paint(); }},
      {label: "Guides", kbd: "G", checked: guides, act: () => { guides = !guides; pref.set("guides", guides ? "1" : "0"); paint(); }},
      {label: "Format", items: formatEntries().map(([k, f]) => ({label: f.label, checked: k === d.format, act: () => setFormat(k)}))},
      {label: "Preview", items: [{label: "With name", checked: signedPreview, act: () => { signedPreview = true; paint(); }}, {label: "Without name", checked: !signedPreview, act: () => { signedPreview = false; paint(); }}]},
      "-",
      {label: "Export PNGs", act: exportPng},
      {label: "Duplicate this design", act: duplicateDesign},
      {label: "All designs…", act: () => { flush(); hub(); }},
      ...(editStyle ? ["-", {label: "Poem style…", act: editStyle}] : []),
    ];
  }
  function onCtx(ev) {
    if (!d) return;
    ev.preventDefault();
    if (pen) finishPen();
    const e = hit(toDesign(ev));
    if (e && sel.length && !sel.includes(e.id) && !expand([e.id]).some(id => sel.includes(id))) { StudioMenu.open(ev, crossMenu(e)); return; }
    if (e && !sel.includes(e.id)) { sel = expand([e.id]); anchor = e.id; panels(); paint(); }
    StudioMenu.open(ev, e ? elementMenu() : canvasMenu());
  }

  function restack(dir) {
    if (sel.length !== 1) return;
    const i = d.elements.findIndex(e => e.id === sel[0]), j = i + dir;
    if (j < 0 || j >= d.elements.length) return;
    mutate(() => { const [e] = d.elements.splice(i, 1); d.elements.splice(j, 0, e); }); panels();
  }
  function nudge(dx, dy) {
    if (!sel.length) return;
    mutate(() => selected().forEach(e => moveEl(e, e, dx, dy)), "nudge");
    panels();
  }
  function align(how, toMargin) {
    const es = selected(); if (!es.length) return;
    const f = F(), s = S(), boxes = es.map(e => Design.bounds(e)), single = es.length === 1;
    const L = single ? (toMargin ? s.s : 0) : Math.min(...boxes.map(b => b.x));
    const R = single ? (toMargin ? f.w - s.s : f.w) : Math.max(...boxes.map(b => b.x + b.w));
    const T = single ? (toMargin ? s.t : 0) : Math.min(...boxes.map(b => b.y));
    const B = single ? (toMargin ? f.h - s.b : f.h) : Math.max(...boxes.map(b => b.y + b.h));
    mutate(() => es.forEach((e, i) => {
      const b = boxes[i]; let dx = 0, dy = 0;
      if (how === "left") dx = L - b.x; if (how === "right") dx = R - (b.x + b.w); if (how === "hcenter") dx = (L + R) / 2 - (b.x + b.w / 2);
      if (how === "top") dy = T - b.y; if (how === "bottom") dy = B - (b.y + b.h); if (how === "vcenter") dy = (T + B) / 2 - (b.y + b.h / 2);
      moveEl(e, e, dx, dy);
    }));
    panels();
  }
  /* Drag and drop in the layers list (top of the list = front). Dropping next to a group's member puts the
     layer in that group; next to an ungrouped layer takes it out. A whole group moves as a block. */
  function dropLayers(ids, li, mode) {
    const tid = li.dataset.id, gid = li.dataset.gid;
    if (tid && ids.includes(tid)) return;
    const g0 = groupOf(ids[0]), whole = !!g0 && ids.every(id => groupOf(id) === g0) && members(g0).length === ids.length;
    if (gid && whole && gid === g0) return;
    const isBase = li.classList.contains("maskbase"), isClip = li.classList.contains("clipped");
    const carried = new Set(maskUnits().filter(u => ids.includes(u.base.id)).flatMap(u => u.clips.map(c => c.id)));   // masked layers travel with their mask
    let made = null;
    mutate(() => {
      const moving = d.elements.filter(e => ids.includes(e.id)), rest = d.elements.filter(e => !ids.includes(e.id));
      const after = b => { let at = rest.indexOf(b) + 1; while (at < rest.length && rest[at].clip && (rest[at].group || null) === (b.group || null)) at++; return at; };
      let at, group = null, maskBy = null;
      if (tid) {
        const t = rest.findIndex(e => e.id === tid), target = rest[t];
        if (isClip && !whole) { at = mode === "below" ? t : t + 1; maskBy = target; }                 // among what a mask holds: masked too
        else if (isBase && mode !== "above" && !whole) { at = after(target); maskBy = target; }          // onto a mask, or just under it: masked by it
        else if (mode === "clip" && !whole) { at = after(target); maskBy = target; made = "mask"; }      // Alt-drop: use it as the mask
        else if (mode === "into" && !whole) {                                                           // onto a layer: group with it
          let g = target.group;
          if (!g) { g = "g" + Design.uid().slice(1); (d.groups ||= {})[g] = {name: `Group ${Object.keys(d.groups).length + 1}`}; target.group = g; }
          at = after(target); group = g; made = "group";
        } else {
          at = mode === "below" ? t : after(target); group = target.group || null;
          if (whole && group) { const idx = rest.map((e, i) => e.group === group ? i : -1).filter(i => i >= 0); at = mode === "below" ? Math.min(...idx) : Math.max(...idx) + 1; group = null; }
        }
      } else {
        const idx = rest.map((e, i) => e.group === gid ? i : -1).filter(i => i >= 0);
        at = Math.max(...idx) + 1;
        group = mode === "above" || whole ? null : gid;   // onto the group or just under its header: into the group, on top
      }
      moving.forEach(e => {
        if (maskBy) { if (!carried.has(e.id)) { if (maskBy.clip) { delete maskBy.clip; delete maskBy.clipInvert; } e.clip = true; } if (maskBy.group) e.group = maskBy.group; else delete e.group; }
        else {
          if (!carried.has(e.id)) { delete e.clip; delete e.clipInvert; }
          if (!whole) { if (group) e.group = group; else delete e.group; }
        }
      });
      rest.splice(at, 0, ...moving);
      d.elements = rest;
      pruneGroups();
    });
    if (made) toast(made === "mask" ? "Masked" : "Grouped");
    panels();
  }

  function groupSel() {
    if (!sel.length) { toast("Select the layers to put in a group"); return; }
    const gid = "g" + Design.uid().slice(1);
    mutate(() => {
      d.groups ||= {};
      d.groups[gid] = {name: `Group ${Object.keys(d.groups).length + 1}`};
      const idx = sel.map(id => d.elements.findIndex(e => e.id === id)).filter(i => i >= 0).sort((a, b) => a - b);
      const mem = idx.map(i => d.elements[i]), top = idx.at(-1);
      const rest = d.elements.filter(e => !sel.includes(e.id));
      let at = rest.findIndex(e => d.elements.indexOf(e) > top);
      if (at < 0) at = rest.length;
      mem.forEach(e => { e.group = gid; });
      rest.splice(at, 0, ...mem);   // members sit together, where the topmost one was
      d.elements = rest;
      pruneGroups();
    });
    inGroup = null; panels(); toast("Grouped · double-click to go inside");
  }
  function ungroupSel() {
    const gids = new Set(selected().map(e => e.group).filter(Boolean));
    if (!gids.size) return;
    mutate(() => { d.elements.forEach(e => { if (gids.has(e.group)) delete e.group; }); gids.forEach(g => { if (d.groups) delete d.groups[g]; }); });
    inGroup = null; panels();
  }
  /* Even gaps between the selected layers (on their ink boxes), or an exact gap in px. */
  function gaps(axis) {
    const es = selected().map(e => ({e, b: Design.bounds(e)})).sort((p, q) => axis === "v" ? p.b.y - q.b.y : p.b.x - q.b.x);
    const g = [];
    for (let i = 1; i < es.length; i++) g.push(axis === "v" ? es[i].b.y - (es[i - 1].b.y + es[i - 1].b.h) : es[i].b.x - (es[i - 1].b.x + es[i - 1].b.w));
    return {es, g};
  }
  function distribute(axis, gap = null) {
    const {es} = gaps(axis);
    if (es.length < 2 || (gap == null && es.length < 3)) return;
    const size = es.reduce((a, x) => a + (axis === "v" ? x.b.h : x.b.w), 0);
    const first = es[0].b, last = es.at(-1).b;
    const span = axis === "v" ? last.y + last.h - first.y : last.x + last.w - first.x;
    const step = gap ?? (span - size) / (es.length - 1);
    mutate(() => {
      let at = axis === "v" ? first.y : first.x;
      for (const {e, b} of es) {
        const d0 = at - (axis === "v" ? b.y : b.x);
        if (axis === "v") shift(e, 0, d0); else shift(e, d0, 0);
        at += (axis === "v" ? b.h : b.w) + step;
      }
    }, "dist" + axis);
    panels();
  }

  /* First visit to a format: start each layer where it sits relative to the safe area; after that, formats are separate. */
  function fillFormat(doc, from, fmt) {
    for (const raw of doc.elements) {
      const r = Design.resolve(raw, from);
      raw.at ||= {};
      raw.at[from] ||= Design.pickLayout(r);
      if (!raw.at[fmt]) raw.at[fmt] = Design.remapLayout(r, from, fmt);
    }
  }

  function setFormat(fmt) {
    if (fmt === d.format || !allowed().includes(fmt)) return;
    const from = d.format;
    const fresh = d.elements.filter(raw => !raw.at?.[fmt]);
    if (fresh.length) {
      mutate(() => { fillFormat(d, from, fmt); d.format = fmt; });
    } else { d.format = fmt; scheduleSave(); }
    sel = sel.filter(id => shown(byId(id)));
    view.auto = true; fit(); paint(); panels();
  }

  async function duplicateDesign() {
    await save();
    const c = JSON.parse(JSON.stringify(d)); c.name = `${d.name} copy`;
    try { const r = await api("/api/design", {id: poem.id, design: c}); designs = r.designs; await load(r.slug); toast("Duplicated"); }
    catch (e) { toast(e.message, true); }
  }
  async function deleteDesign() {
    if (!confirm(`Move “${d.name}” to the trash? It goes to designs/.trash in the poem folder.`)) return;
    clearTimeout(saveTimer); dirty = false;
    try {
      const r = await api("/api/design/delete", {id: poem.id, slug});
      designs = r.designs; slug = null; d = null;
      if (designs.length) await load(designs[0].slug); else hub();
      toast("Moved to the trash");
    } catch (e) { toast(e.message, true); }
  }

  async function exportPng() {
    if (remapped) { dirty = true; remapped = false; }     // the export renders the file: write what the editor showed
    await save(); if (saving) await saving;
    const btn = $("#ed-export", root);
    btn.disabled = true; btn.textContent = "Exporting…";
    try {
      const r = await api("/api/design/export", {id: poem.id, slug});
      designs = r.designs; status(); panels();
      toast(`Exported ${r.rels.length} PNGs (1:1, 4:5, 9:16${r.rels.length > 3 ? ", with and without name" : ""}) to Design renders/${slug}`);
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; btn.textContent = "Export"; }
  }

  /* ——— stamps: saved pieces (one or more layers) in Poems/<Series>/stamps, for any design in the series ——— */
  let stamps = [];
  async function stampsPanel() {
    const box = $("#ed-stampbox", root);
    if (!box || box.hidden) return;
    try { stamps = await api("/api/stamps?series=" + encodeURIComponent(poem.series)); } catch (e) { toast(e.message, true); }
    box.innerHTML = `<header><span>Stamps · ${esc(poem.series)}</span><button class="edx-icon sm" data-x title="Close">×</button></header>
      ${sel.length ? `<div class="edx-stampsave"><input class="edx-in" id="st-name" placeholder="Name this stamp" value="${esc(sel.length === 1 ? label(selected()[0]) : "")}">
        <button class="btn small" id="st-save">Save ${sel.length === 1 ? "layer" : sel.length + " layers"}</button></div>`
        : `<p class="edx-note">Select layers and save them here to reuse them in any ${esc(poem.series)} design.</p>`}
      <div class="edx-stampgrid">${stamps.map(st => `<div class="edx-stamp"><button class="pick" data-stamp="${esc(st.slug)}" title="Place “${esc(st.name)}”"><span class="cv" data-scv="${esc(st.slug)}"></span>
        <span class="n">${esc(st.name)}</span></button><button class="del" data-sdel="${esc(st.slug)}" title="Move to trash">×</button></div>`).join("") || `<p class="edx-note">No stamps yet.</p>`}</div>`;
    $("[data-x]", box).onclick = () => { box.hidden = true; };
    for (const sp of $$("[data-scv]", box)) {
      const st = stamps.find(x => x.slug === sp.dataset.scv);
      await Design.ready({elements: st.elements});
      sp.replaceWith(Design.thumb({background: "transparent", elements: st.elements}, 112, {size: {w: Math.max(1, st.w), h: Math.max(1, st.h)}, maxH: 84}));
    }
    $("#st-save", box) && ($("#st-save", box).onclick = async () => {
      const es = selected(), bs = es.map(e => Design.bounds(e));
      const x0 = Math.min(...bs.map(b => b.x)), y0 = Math.min(...bs.map(b => b.y));
      const w = Math.max(...bs.map(b => b.x + b.w)) - x0, h = Math.max(...bs.map(b => b.y + b.h)) - y0;
      const els = es.map(e => { const flat = JSON.parse(JSON.stringify(Design.resolve(e.__raw, d.format))); delete flat.at; delete flat.hide; delete flat.group; const v = px(flat); moveEl(v, v, -x0, -y0); return flat; });
      try { await api("/api/stamps", {series: poem.series, name: $("#st-name", box).value || "Stamp", elements: els, w, h}); toast("Saved as a stamp"); stampsPanel(); }
      catch (e2) { toast(e2.message, true); }
    });
    $$("[data-stamp]", box).forEach(b => b.onclick = () => placeStamp(stamps.find(x => x.slug === b.dataset.stamp)));
    $$("[data-sdel]", box).forEach(b => b.onclick = async () => {
      if (!confirm("Move this stamp to the trash?")) return;
      try { await api("/api/stamps/delete", {series: poem.series, slug: b.dataset.sdel}); stampsPanel(); } catch (e2) { toast(e2.message, true); }
    });
  }
  async function placeStamp(st) {
    if (!st || !d) return;
    await Design.ready({elements: st.elements});
    const f = F(), dx = (f.w - st.w) / 2, dy = (f.h - st.h) / 2;
    const gid = st.elements.length > 1 ? "g" + Design.uid().slice(1) : null;
    const items = st.elements.map(src => { const c = JSON.parse(JSON.stringify(src)); c.id = Design.uid(); moveEl(c, c, dx, dy); if (gid) c.group = gid; return c; });
    mutate(() => { if (gid) (d.groups ||= {})[gid] = {name: st.name}; d.elements.push(...items); sel = items.map(c => c.id); });
    inGroup = null; panels(); toast(`Placed “${st.name}”`);
  }

  /* ——— keyboard ——— */
  function onKey(ev) {
    if (!root?.isConnected || document.querySelector("dialog[open]")) return;    // a dialog over the editor has the keys
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
    const k = ev.key, mod = ev.ctrlKey || ev.metaKey;
    if (!d) return;
    if (mod && k.toLowerCase() === "s") { ev.preventDefault(); save(); return; }
    if (typing) { if (k === "Escape") document.activeElement.blur(); return; }
    if (mod && k.toLowerCase() === "z") { ev.preventDefault(); ev.shiftKey ? step(redo, undo) : step(undo, redo); return; }
    if (mod && k.toLowerCase() === "y") { ev.preventDefault(); step(redo, undo); return; }
    if (mod && k.toLowerCase() === "d") { ev.preventDefault(); duplicate(); return; }
    if (mod && !ev.altKey && k.toLowerCase() === "g") { ev.preventDefault(); ev.shiftKey ? ungroupSel() : groupSel(); return; }
    if (mod && k.toLowerCase() === "c") { ev.preventDefault(); copy(); return; }
    if (mod && k.toLowerCase() === "v") { ev.preventDefault(); paste(); return; }
    if (mod && k.toLowerCase() === "a") { ev.preventDefault(); sel = d.elements.filter(e => !e.locked && Design.shownIn(e, d.format)).map(e => e.id); paint(); panels(); return; }
    if (mod && (k === "0" || k === "1")) { ev.preventDefault(); fit(); paint(); return; }
    if (k === "Delete" || k === "Backspace") { ev.preventDefault(); remove(); return; }
    if (k.startsWith("Arrow")) {
      ev.preventDefault(); const s = ev.shiftKey ? 10 : 1;
      nudge(k === "ArrowLeft" ? -s : k === "ArrowRight" ? s : 0, k === "ArrowUp" ? -s : k === "ArrowDown" ? s : 0); return;
    }
    if (k === " ") { if (!space) { space = true; canvas.style.cursor = "grab"; } ev.preventDefault(); return; }
    if (k === "Enter" && pen) { ev.preventDefault(); finishPen(); return; }
    if (k === "Escape" && pen) { finishPen(); return; }
    if (k === "Escape" && editPts) { editPts = null; paint(); return; }
    if (k === "Escape") { if (inGroup) { sel = members(inGroup); inGroup = null; } else sel = []; setTool("select"); paint(); panels(); return; }
    if (k === "]") return arrange(mod ? "front" : "forward");
    if (k === "[") return arrange(mod ? "back" : "backward");
    if (ev.shiftKey && (k === "!" || k === "1")) { fit(); paint(); return; }
    if (k === "+" || k === "=") return zoomBy(1.25);
    if (k === "-") return zoomBy(.8);
    if (mod && ev.altKey && k.toLowerCase() === "g") { ev.preventDefault(); if (sel.length) { const all = selected().every(e => e.clip); mutate(() => selected().forEach(e => { if (all) delete e.clip; else e.clip = true; })); panels(); } return; }
    const t = {v: "select", t: "text", r: "rect", o: "ellipse", l: "line", y: "polygon", s: "star", p: "pen", a: "arc"}[k.toLowerCase()];
    if (t && !mod) setTool(t);
    if (k.toLowerCase() === "g" && !mod) { guides = !guides; pref.set("guides", guides ? "1" : "0"); paint(); }
  }
  function onKeyUp(ev) { if (ev.key === " ") { space = false; if (canvas) canvas.style.cursor = "default"; } }

  /* ——— inspector: layers + properties ——— */
  function panels() {
    if (!root || !d) return;
    const list = $("#ed-layers", root);
    if (!list) return;
    const units = maskUnits(), top = [...units].reverse(), rows = [];
    for (let i = 0; i < top.length;) {
      const g = top[i].base.group;
      if (g) { const run = []; while (i < top.length && top[i].base.group === g) run.push(top[i++]); rows.push({g, run}); }
      else rows.push({u: top[i++]});
    }
    const unitIds = u => [u.base.id, ...[...u.clips].reverse().map(e => e.id)];
    const order = rows.flatMap(r => r.g ? r.run.flatMap(unitIds) : unitIds(r.u));
    const row = (e, depth, kind = "") => `<li class="${sel.includes(e.id) ? "on" : ""} ${Design.shownIn(e, d.format) ? "" : "off"} ${kind}" style="--depth:${depth}" data-id="${e.id}" ${!e.hidden && !Design.shownIn(e, d.format) ? `title="Hidden in ${F().label}"` : ""}>
      <span class="ic">${svg(ICON[e.type] || ICON.rect, 15)}</span>
      <span class="nm">${esc(label(e))}${kind === "maskbase" ? '<em class="mk">mask</em>' : ""}${e.role === "name" ? '<em>name</em>' : ""}</span>
      <button class="tg nmt ${e.role === "name" ? "is-on" : ""}" data-role="${e.id}" title="${e.role === "name" ? "Not the name" : "Mark as the name: left out of the unsigned version"}">N</button>
      <button class="tg ${e.hidden ? "is-on" : ""}" data-hide="${e.id}" title="${e.hidden ? "Show" : "Hide"}">${svg(e.hidden ? ICON.eyeoff : ICON.eye, 15)}</button>
      <button class="tg ${e.locked ? "is-on" : ""}" data-lock="${e.id}" title="${e.locked ? "Unlock" : "Lock"}">${svg(e.locked ? ICON.lock : ICON.unlock, 15)}</button></li>`;
    const unitRows = (u, depth) => row(u.base, depth, u.clips.length ? "maskbase" : "") + [...u.clips].reverse().map(c => row(c, depth + 1, "clipped")).join("");
    list.innerHTML = rows.map(r => r.u ? unitRows(r.u, 0) : `<li class="grp ${members(r.g).every(id => sel.includes(id)) ? "on" : ""} ${inGroup === r.g ? "inside" : ""}" data-gid="${r.g}">
        <button class="tw" data-twist="${r.g}" title="${collapsed.has(r.g) ? "Open" : "Close"}">${collapsed.has(r.g) ? "▸" : "▾"}</button>
        <span class="nm">${esc(groupName(r.g))}<em class="cnt">${members(r.g).length}</em></span></li>
        ${collapsed.has(r.g) ? "" : r.run.map(u => unitRows(u, 1)).join("")}`).join("")
      || `<li class="empty-l">Nothing here yet. Draw with the tools on the left, or place the <b>Poem</b>.</li>`;
    const pick = (ids, ev, key) => {
      if (ev.shiftKey && anchor && order.includes(anchor)) {   // everything between the last pick and this one
        const a = order.indexOf(anchor), b = order.indexOf(key), range = order.slice(Math.min(a, b), Math.max(a, b) + 1);
        sel = ev.ctrlKey || ev.metaKey ? [...new Set([...sel, ...range])] : range;
      } else if (ev.ctrlKey || ev.metaKey) {
        const all = ids.every(id => sel.includes(id));
        sel = all ? sel.filter(x => !ids.includes(x)) : [...new Set([...sel, ...ids])];
        anchor = key;
      } else { sel = ids; anchor = key; }
      paint(); panels();
    };
    $$("li[data-id]", list).forEach(li => li.onclick = ev => {
      if (ev.target.closest("button")) return;
      const id = li.dataset.id;
      if (!ev.shiftKey && !ev.ctrlKey && !ev.metaKey) inGroup = groupOf(id);   // picking a member in the list goes inside its group
      pick([id], ev, id);
    });
    $$("li[data-gid]", list).forEach(li => li.onclick = ev => {
      if (ev.target.closest("button")) return;
      const ids = members(li.dataset.gid);
      inGroup = null; pick(ids, ev, ids[0]);
    });
    $$("[data-twist]", list).forEach(b => b.onclick = () => { const g = b.dataset.twist; collapsed.has(g) ? collapsed.delete(g) : collapsed.add(g); panels(); });
    let dragIds = null;
    const clearDrop = () => $$(".drop-above,.drop-below,.drop-into,.drop-clip", list).forEach(x => x.classList.remove("drop-above", "drop-below", "drop-into", "drop-clip"));
    $$("li[data-id], li[data-gid]", list).forEach(li => {
      li.draggable = true;
      li.ondragstart = ev => {
        const id = li.dataset.id, g = li.dataset.gid;
        dragIds = g ? members(g) : sel.includes(id) ? d.elements.filter(e => sel.includes(e.id)).map(e => e.id) : [id];
        dragIds = [...new Set(dragIds.flatMap(x => { const u = units.find(u2 => u2.base.id === x); return u ? [x, ...u.clips.map(c => c.id)] : [x]; }))];
        ev.dataTransfer.effectAllowed = "move"; ev.dataTransfer.setData("text/plain", dragIds.join(","));
        setTimeout(() => li.classList.add("dragging"));
      };
      li.ondragend = () => { li.classList.remove("dragging"); clearDrop(); dragIds = null; };
      const zone = ev => { const r = li.getBoundingClientRect(), t = (ev.clientY - r.top) / r.height; return t < .28 ? "above" : t > .72 ? "below" : ev.altKey ? "clip" : "into"; };
      li.ondragover = ev => {
        if (!dragIds) return;
        ev.preventDefault();
        const z2 = zone(ev);
        clearDrop(); li.classList.add("drop-" + z2);
      };
      li.ondragleave = () => li.classList.remove("drop-above", "drop-below", "drop-into", "drop-clip");
      li.ondrop = ev => { ev.preventDefault(); const z2 = zone(ev), ids = dragIds; dragIds = null; clearDrop(); if (ids) dropLayers(ids, li, z2); };
      li.oncontextmenu = ev => {
        const id = li.dataset.id, g = li.dataset.gid;
        if (!g && sel.length && !sel.includes(id)) { StudioMenu.open(ev, crossMenu(byId(id))); return; }
        if (g) { const ids = members(g); if (!ids.every(x => sel.includes(x))) { sel = ids; inGroup = null; paint(); panels(); } }
        else if (!sel.includes(id)) { sel = [id]; anchor = id; inGroup = groupOf(id); paint(); panels(); }
        const rename = g ? [{label: "Rename group…", act: () => { const n = prompt("Group name", groupName(g)); if (n != null) { mutate(() => { (d.groups ||= {})[g] = {name: n.trim() || "Group"}; }); panels(); } }}, "-"]
          : [{label: "Rename…", act: () => { const inp = $("[data-k=name]", $("#ed-props", root)); inp?.focus(); inp?.select(); }}, "-"];
        StudioMenu.open(ev, elementMenu(rename));
      };
    });
    $$("[data-hide]", list).forEach(b => b.onclick = () => { const e = byId(b.dataset.hide); mutate(() => { e.hidden = !e.hidden; }); panels(); });
    $$("[data-role]", list).forEach(b => b.onclick = () => { const e = byId(b.dataset.role); mutate(() => { if (e.role === "name") delete e.role; else e.role = "name"; }); panels(); });
    $$("[data-lock]", list).forEach(b => b.onclick = () => { const e = byId(b.dataset.lock); mutate(() => { e.locked = !e.locked; }); panels(); });
    props();
    syncBar();
  }

  /* Document colours: every colour a design uses that isn't in the palette (fills, outlines, strokes, letters,
     full stops, background, gradient stops, per-format overrides), as upper-case #RRGGBB, each once, in first-use order.
     palette: [{hex}] or ["#hex"]. order (optional): an array kept between calls so a colour holds its place while the
     design is edited; without it the order is the design's own (background, then layers bottom to top). */
  const PAINTS = new Set(["background", "color", "accent", "stroke", "fill", "c"]);
  function documentColours(design, palette = [], order = []) {
    const used = new Set();
    const walk = (v, k) => {
      if (typeof v === "string") { if (PAINTS.has(k) && /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v)) used.add((v.length === 4 ? "#" + [...v.slice(1)].map(x => x + x).join("") : v).toUpperCase()); }
      else if (Array.isArray(v)) v.forEach(x => walk(x, k));
      else if (v && typeof v === "object") for (const [kk, x] of Object.entries(v)) if (kk !== "pts" && kk !== "text") walk(x, kk);
    };
    walk(design, "");
    for (const c of used) if (!order.includes(c)) order.push(c);
    const inPalette = new Set(palette.map(p => String(p?.hex ?? p).toUpperCase()));
    return order.filter(c => used.has(c) && !inPalette.has(c));
  }
  let docSeen = [];   // first-use order of the open design's colours; reset in load()
  const swatchRow = (key, cur, allowNone = false) => `<div class="edx-sw">${allowNone ? `<button class="none ${!cur ? "on" : ""}" data-sw="${key}" data-v="" title="None">⌀</button>` : ""}${
    palette().map(c => `<button class="${(cur || "").toUpperCase() === c.hex.toUpperCase() ? "on" : ""}" data-sw="${key}" data-v="${esc(c.hex)}" title="${esc(c.name)} ${esc(c.hex)}${c.role ? " · " + esc(c.role) : ""}" style="--c:${esc(c.hex)}"></button>`).join("")}${
    documentColours(d, palette(), docSeen).map(c => `<span class="docw"><button class="doc ${(cur || "").toUpperCase() === c ? "on" : ""}" data-sw="${key}" data-v="${c}" data-doc="${c}" title="${c} · in this design" style="--c:${c}"></button><button class="add" type="button" data-addpal="${c}" title="Add ${c} to the palette" aria-label="Add ${c} to the palette" aria-haspopup="menu">+</button></span>`).join("")}
    <label class="custom" title="Another colour"><input type="color" data-color="${key}" value="${esc(cur && /^#[0-9a-f]{6}$/i.test(cur) ? cur : "#888888")}"></label>
    ${cur ? `<span class="hex">${esc(cur.toUpperCase())}</span>` : ""}</div>`;

  /* Add to palette: a document colour joins the palette the poem resolves to, optionally taking a role from another
     swatch. A poem's or series' own copy changes at once; a palette linked from the library asks first. */
  const ROLE_NAMES = ["background", "text", "accent", "muted"];
  function docMenu(hex) {
    const sw = poem.style?.palette?.swatches || palette(), full = sw.length >= 16, holder = r => sw.find(s => s.role === r);
    return [
      {label: full ? "Add to palette (it has 16 colours)" : "Add to palette", disabled: full, act: () => addToPalette(hex)},
      ...ROLE_NAMES.map(r => ({label: `Add as ${r}${holder(r) ? ` (instead of ${holder(r).name || holder(r).hex})` : ""}`, disabled: full, act: () => addToPalette(hex, r)})),
      "-",
      {label: `Copy ${hex}`, act: () => { navigator.clipboard?.writeText(hex); toast(`Copied ${hex}`); }},
    ];
  }
  async function addToPalette(hex, role = "") {
    const pal = poem.style?.palette;
    if (!pal) return;
    const swatches = [...pal.swatches.map(s => ({name: s.name || s.hex, hex: s.hex, ...(s.role && s.role !== role ? {role: s.role} : {})})),
      {name: hex, hex, ...(role ? {role} : {})}];
    const copy = pal.name ? {name: pal.name, swatches} : swatches;     // an unnamed copy stays a plain list, as Studio 1.0 wrote it
    const level = pal.from === "poem" ? "poem" : "series";
    try {
      let where;
      if (!pal.linked && level === "poem") { await api("/api/poem/style", {id: poem.id, palette: copy}); where = "this poem's palette"; }
      else if (!pal.linked) { await api("/api/series/style", {name: poem.series, palette: copy}); where = `the palette of ${poem.series}`; }
      else {
        const how = await askLibrary(pal, hex, level);
        if (!how) return;
        if (how === "library") { await api("/api/styles/palette", {palette: {name: pal.name, swatches}}); where = `the palette ${pal.name}`; }
        else if (level === "poem") { await api("/api/poem/style", {id: poem.id, palette: copy}); where = "this poem's own palette"; }
        else { await api("/api/series/style", {name: poem.series, palette: copy}); where = `${poem.series}'s own copy of ${pal.name}`; }   // the look and fonts stay
      }
      const fresh = await api(`/api/poem?id=${encodeURIComponent(poem.id)}`);
      if (refresh) refresh(fresh); else update(fresh);
      toast(`Added ${hex} to ${where}`);
    } catch (e) { toast(e.message, true); }
  }
  /* A library palette: change it everywhere, or give the series (or the poem, when it chose the palette) its own copy. */
  async function askLibrary(pal, hex, level) {
    let users = [];
    try { users = (await api("/api/styles")).used?.palettes?.[pal.name] || []; } catch { /* the count is only a courtesy */ }
    const n = users.length;
    return new Promise(resolve => {
      let how = null;
      const form = openDialog(`<form class="ask">
        <div class="ask-head"><i style="background:${esc(hex)}"></i><h2>Add ${esc(hex)} to the palette</h2></div>
        <p class="hint ask-lede">${level === "poem" ? "This poem uses" : `${esc(poem.series)} uses`} “${esc(pal.name)}”, a palette in your library.</p>
        <div class="ask-opts">
          <button type="submit" class="choice" data-how="library"><b>Change the library palette “${esc(pal.name)}”${n ? ` (used by ${n} series)` : ""}</b>
            <span>${n ? `${esc(users.join(", "))} ${n === 1 ? "gets" : "get"} the colour too.` : "Everything that follows it gets the colour."}</span></button>
          <button type="submit" class="choice" data-how="own"><b>Give ${level === "poem" ? "this poem" : "this series"} its own copy</b>
            <span>${level === "poem" ? "The poem keeps its own copy of the palette, with the colour added. Nothing else changes."
              : `${esc(poem.series)} keeps its own copy of the palette, with the colour added. Its look and fonts stay as they are.`}</span></button></div>
        <div class="foot"><span></span><button type="button" class="btn quiet" data-close autofocus>Cancel</button></div></form>`, async () => resolve(how));
      $$("[data-how]", form).forEach(b => b.onclick = () => { how = b.dataset.how; });
      $("#dlg").addEventListener("close", () => resolve(null), {once: true});    // Cancel or Esc (after an answer: no effect)
    });
  }
  const stopSel = {};
  const hexToRgb = h => [1, 3, 5].map(i => parseInt(String(h).slice(i, i + 2), 16));
  const mix = (a, b, t) => "#" + hexToRgb(a).map((v, i) => Math.round(v + (hexToRgb(b)[i] - v) * t).toString(16).padStart(2, "0")).join("").toUpperCase();
  function colorAt(g, p) {
    const st = Design.stopsOf(g);
    if (p <= st[0].p) return st[0].c;
    for (let i = 1; i < st.length; i++) if (p <= st[i].p) return mix(st[i - 1].c, st[i].c, (p - st[i - 1].p) / ((st[i].p - st[i - 1].p) || 1));
    return st.at(-1).c;
  }
  const barCss = g => `linear-gradient(90deg, ${Design.stopsOf(g).map(x => `${x.c} ${x.p * 100}%`).join(", ")})`;
  function paintCtl(key, cur, none = false) {
    const mode = Design.isGrad(cur) ? cur.type : cur ? "solid" : (none ? "none" : "solid");
    const modes = [...(none ? [["none", "None"]] : []), ["solid", "Solid"], ["linear", "Linear"], ["radial", "Radial"]];
    let body = "";
    if (mode === "solid") body = swatchRow(key, cur);
    else if (mode !== "none") {
      const si = Math.min(stopSel[key] ?? 0, cur.stops.length - 1), stop = cur.stops[si];
      body = `<div class="edx-gbar" data-gbar="${key}" title="Click the bar to add a stop; drag stops to move them">
          <div class="track" style="background:${barCss(cur)}"></div>
          ${cur.stops.map((x, i) => `<button class="stop ${i === si ? "on" : ""}" data-stop="${key}|${i}" style="left:${x.p * 100}%;--c:${esc(x.c)}" aria-label="Stop ${i + 1}"></button>`).join("")}</div>
        <div class="edx-gtools">${cur.type === "linear" ? `<label class="edx-num"><span data-gscrub="${key}" title="Drag to change">Angle °</span><input type="number" step="1" data-angle="${key}" value="${+cur.angle || 0}"></label>` : `<span></span>`}
          <label class="edx-num"><span>Location %</span><input type="number" step="1" min="0" max="100" data-stoppos="${key}" value="${Math.round(stop.p * 1000) / 10}"></label>
          <button class="edx-icon sm" data-rev="${key}" title="Reverse the gradient">⇄</button>
          <button class="edx-icon sm" data-delstop="${key}" ${cur.stops.length <= 2 ? "disabled" : ""} title="Delete this stop">${svg(ICON.trash, 16)}</button></div>
        <div class="edx-field"><span>Stop ${si + 1} colour</span>${swatchRow(key + "#stop", stop.c)}</div>`;
    }
    return `<div class="edx-paint" data-paint="${key}"><div class="seg edx-seg small">${modes.map(([m, l]) => `<button data-pmode="${key}|${m}" aria-pressed="${m === mode}">${l}</button>`).join("")}</div>${body}</div>`;
  }
  /* get(k) / set(k, v) read and write the paint; v is null for "none". */
  function wirePaints(el, get, set, id) {
    const clone = v => JSON.parse(JSON.stringify(v));
    const put = (k, v, key) => mutate(() => set(k, v), key);
    $$("[data-pmode]", el).forEach(b => b.onclick = () => {
      const [k, m] = b.dataset.pmode.split("|"), cur = get(k), basec = Design.firstColor(cur) || colours().accent;
      let v = null;
      if (m === "solid") v = basec;
      else if (m === "linear" || m === "radial") {
        const other = palette().find(c => c.hex.toUpperCase() !== String(basec).toUpperCase())?.hex || "#EEEAE2";
        v = Design.isGrad(cur) ? {...clone(cur), type: m} : {type: m, angle: 0, stops: [{c: basec, p: 0}, {c: other, p: 1}]};
        stopSel[k] = 0;
      }
      put(k, v); props();
    });
    const color = (k, v, live) => {
      if (k.endsWith("#stop")) { const key = k.slice(0, -5), g = clone(get(key)); g.stops[Math.min(stopSel[key] ?? 0, g.stops.length - 1)].c = v; put(key, g, "stopc:" + key + id); }
      else put(k, v, "paint:" + k + id);
      if (live) paint(); else props();
    };
    $$("[data-sw]", el).forEach(b => b.onclick = () => color(b.dataset.sw, b.dataset.v || null));
    $$("[data-doc]", el).forEach(b => b.oncontextmenu = ev => StudioMenu.open(ev, docMenu(b.dataset.doc)));
    $$("[data-addpal]", el).forEach(b => b.onclick = () => {
      const r = b.getBoundingClientRect();
      StudioMenu.open({preventDefault() {}, stopPropagation() {}, clientX: r.left, clientY: r.bottom + 4}, docMenu(b.dataset.addpal));
    });
    $$("[data-color]", el).forEach(i => { i.oninput = () => color(i.dataset.color, i.value.toUpperCase(), true); i.onchange = () => props(); });
    $$("[data-gbar]", el).forEach(bar => {
      const key = bar.dataset.gbar, track = $(".track", bar);
      const at = ev => { const r = track.getBoundingClientRect(); return Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)); };
      track.onclick = ev => {   // add a stop where you click, in the colour already there
        const g = clone(get(key)), p = Math.round(at(ev) * 1000) / 1000;
        g.stops.push({c: colorAt(g, p), p}); stopSel[key] = g.stops.length - 1;
        put(key, g); props();
      };
      $$("[data-stop]", bar).forEach(btn => btn.onpointerdown = ev => {
        const i = +btn.dataset.stop.split("|")[1];
        stopSel[key] = i;
        ev.preventDefault(); btn.setPointerCapture(ev.pointerId);
        $$(".stop", bar).forEach(x => x.classList.toggle("on", x === btn));
        let moved = false;
        btn.onpointermove = m => {
          moved = true;
          const g = clone(get(key)); g.stops[i].p = Math.round(at(m) * 1000) / 1000;
          put(key, g, "stopp:" + key + id);
          btn.style.left = g.stops[i].p * 100 + "%"; track.style.background = barCss(g);
          const loc = $(`[data-stoppos="${key}"]`, el); if (loc) loc.value = Math.round(g.stops[i].p * 1000) / 10;
        };
        btn.onpointerup = () => { btn.onpointermove = null; btn.onpointerup = null; props(); if (!moved) $(`[data-stoppos="${key}"]`, el)?.focus(); };
      });
    });
    $$("[data-angle]", el).forEach(inp => { inp.oninput = () => { if (inp.value === "" || isNaN(+inp.value)) return; const g = clone(get(inp.dataset.angle)); g.angle = +inp.value; put(inp.dataset.angle, g, "ang:" + id); paint(); }; inp.onchange = () => props(); });
    $$("[data-gscrub]", el).forEach(lab => lab.onpointerdown = ev => {
      const inp = lab.nextElementSibling; ev.preventDefault(); lab.setPointerCapture(ev.pointerId);
      const x0 = ev.clientX, v0 = +inp.value || 0;
      lab.onpointermove = m => { inp.value = Math.round(v0 + (m.clientX - x0) / 2 * (m.shiftKey ? 15 : 1)); inp.dispatchEvent(new Event("input")); };
      lab.onpointerup = () => { lab.onpointermove = null; lab.onpointerup = null; props(); };
    });
    $$("[data-stoppos]", el).forEach(inp => { inp.oninput = () => { if (inp.value === "" || isNaN(+inp.value)) return; const key = inp.dataset.stoppos, g = clone(get(key)); g.stops[Math.min(stopSel[key] ?? 0, g.stops.length - 1)].p = Math.max(0, Math.min(1, +inp.value / 100)); put(key, g, "stopp:" + key + id); paint(); }; inp.onchange = () => props(); });
    $$("[data-rev]", el).forEach(b => b.onclick = () => { const key = b.dataset.rev, g = clone(get(key)); g.stops.forEach(x => { x.p = Math.round((1 - x.p) * 1000) / 1000; }); put(key, g); props(); });
    $$("[data-delstop]", el).forEach(b => b.onclick = () => { const key = b.dataset.delstop, g = clone(get(key)); if (g.stops.length <= 2) return; g.stops.splice(Math.min(stopSel[key] ?? 0, g.stops.length - 1), 1); stopSel[key] = 0; put(key, g); props(); });
  }
  const num = (key, lbl, v, step = 1, extra = "") => `<label class="edx-num"><span data-scrub="${key}" data-step="${step}" title="Drag to change">${lbl}</span><input type="number" step="${step}" data-k="${key}" value="${v ?? ""}" ${extra}></label>`;
  const sec = (title, body, extra = "") => `<section class="edx-sec"><header><span>${title}</span>${extra}</header>${body}</section>`;
  const alignRow = (many) => `<div class="edx-align">${["left", "hcenter", "right", "top", "vcenter", "bottom"].map(k =>
    `<button class="edx-icon sm" data-align="${k}" title="Align ${k.replace("h", "").replace("v", "")}${many ? "" : " to the frame"}">${svg(ALIGN[k], 18)}</button>`).join("")}</div>
    ${many ? "" : `<label class="edx-check"><input type="checkbox" id="al-m" ${pref.get("alm", "1") === "1" ? "checked" : ""}> to the margins (safe lines)</label>`}`;

  function props() {
    const el = $("#ed-props", root), es = selected();
    if (!el) return;
    if (!es.length) {
      el.innerHTML = sec("Design", `<div class="edx-field"><span>Background</span>${paintCtl("background", d.background || "#0C0E11")}</div>
          <div class="edx-meta"><span>Format</span><b>${F().label} · ${F().w} × ${F().h}</b><span>Layers</span><b>${d.elements.length}</b></div>`)
        + sec("Shortcuts", `<dl class="edx-keys"><dt>V T R O Y S L A P</dt><dd>tools</dd><dt>Shift</dt><dd>straight moves, square shapes, 15° turns</dd>
          <dt>Alt-drag</dt><dd>copy</dd><dt>Ctrl</dt><dd>hold to stop snapping</dd><dt>Space</dt><dd>drag to pan</dd><dt>Ctrl+wheel</dt><dd>zoom</dd>
          <dt>[ ]</dt><dd>back / forward</dd><dt>G</dt><dd>guides</dd></dl>`);
      wirePaints(el, () => d.background || "#0C0E11", (k, v) => { d.background = v || "#0C0E11"; }, "doc");
      return;
    }
    if (es.length > 1) {
      const allName = es.every(e => e.role === "name");
      const g0 = es[0].group, whole = !!g0 && es.every(e => e.group === g0) && members(g0).length === es.length;
      const anyGroup = es.some(e => e.group);
      const gv = gaps("v").g, gh = gaps("h").g;
      const even = g => g.length && Math.max(...g) - Math.min(...g) < .1 ? Math.round(g[0] * 10) / 10 : "";
      const DIST = {v: '<rect x="5" y="3" width="12" height="3" fill="currentColor"/><rect x="5" y="9.5" width="12" height="3" fill="currentColor"/><rect x="5" y="16" width="12" height="3" fill="currentColor"/>',
        h: '<rect x="3" y="5" width="3" height="12" fill="currentColor"/><rect x="9.5" y="5" width="3" height="12" fill="currentColor"/><rect x="16" y="5" width="3" height="12" fill="currentColor"/>'};
      el.innerHTML = sec(whole ? "Group" : `${es.length} layers`,
        (whole ? `<input class="edx-in" id="g-name" value="${esc(groupName(g0))}" aria-label="Group name">` : "")
        + `<div class="edx-field"><span>Align to each other</span>${alignRow(true)}</div>
        <div class="edx-field"><span>Spacing</span><div class="edx-dist">
          <button class="edx-icon sm" data-dist="v" title="Even gaps, top to bottom" ${es.length < 3 ? "disabled" : ""}>${svg(DIST.v, 18)}</button>
          <label class="edx-num"><span data-scrub="gv" data-step="1" title="Drag to change">Gap ↕</span><input type="number" step="1" data-gap="v" value="${even(gv)}" placeholder="mixed"></label>
          <button class="edx-icon sm" data-dist="h" title="Even gaps, left to right" ${es.length < 3 ? "disabled" : ""}>${svg(DIST.h, 18)}</button>
          <label class="edx-num"><span data-scrub="gh" data-step="1" title="Drag to change">Gap ↔</span><input type="number" step="1" data-gap="h" value="${even(gh)}" placeholder="mixed"></label></div>
          <p class="edx-note">Gaps are measured between the ink: cap tops and baselines for text.</p></div>
        <div class="edx-row">${whole || anyGroup ? `<button class="btn small" data-act="ungroup" title="Ctrl+Shift+G">Ungroup</button>` : ""}${!whole ? `<button class="btn small" data-act="group" title="Ctrl+G">Group</button>` : ""}
          <button class="btn small" data-act="dup">Duplicate</button><button class="btn small" data-act="delete">Delete</button>
          <button class="btn small" data-act="name">${allName ? "Not the name" : "Mark as name"}</button></div>`) + multiStyle(es);
      wireMultiStyle(el, es);
      wireAlign(el); $("[data-act=delete]", el).onclick = remove; $("[data-act=dup]", el).onclick = duplicate;
      $("[data-act=group]", el) && ($("[data-act=group]", el).onclick = groupSel);
      $("[data-act=ungroup]", el) && ($("[data-act=ungroup]", el).onclick = ungroupSel);
      $("[data-act=name]", el).onclick = () => { mutate(() => es.forEach(e => { if (allName) delete e.role; else e.role = "name"; })); panels(); };
      $$("[data-dist]", el).forEach(b => b.onclick = () => distribute(b.dataset.dist));
      $$("[data-gap]", el).forEach(inp => { inp.oninput = () => { if (inp.value !== "" && !isNaN(+inp.value)) distribute(inp.dataset.gap, +inp.value); }; inp.onchange = () => props(); });
      $$("[data-scrub]", el).forEach(lab => lab.onpointerdown = ev => {
        const inp = lab.nextElementSibling; ev.preventDefault(); lab.setPointerCapture(ev.pointerId);
        const x0 = ev.clientX, v0 = +inp.value || 0;
        lab.onpointermove = m => { inp.value = Math.round(v0 + (m.clientX - x0) / 2 * (m.shiftKey ? 10 : 1)); inp.dispatchEvent(new Event("input")); };
        lab.onpointerup = () => { lab.onpointermove = null; lab.onpointerup = null; props(); };
      });
      $("#g-name", el) && ($("#g-name", el).onchange = e2 => { mutate(() => { (d.groups ||= {})[g0] = {...(d.groups[g0] || {}), name: e2.target.value.trim() || "Group"}; }); panels(); });
      return;
    }
    const e = es[0], b = Design.bounds(e), weights = Design.weightsOf(e.font), widths = Design.widthsOf(e.font), italics = hasItalics(e.font);
    const acts = `<span class="edx-acts"><button class="edx-icon sm" data-act="dup" title="Duplicate (Ctrl+D)">${svg(ICON.copy, 16)}</button>
      <button class="edx-icon sm" data-act="delete" title="Delete (Del)">${svg(ICON.trash, 16)}</button></span>`;
    let html = "";
    const kind = e.type === "text" ? (e.role === "name" ? "Name" : "Text") : e.type === "rect" ? "Rectangle" : e.type === "ellipse" ? "Ellipse"
      : e.type === "shape" ? label({...e, name: ""}) : e.type === "path" ? "Path" : "Line";
    html += sec(kind, `<input class="edx-in" data-k="name" value="${esc(e.name || "")}" placeholder="${esc(label({...e, name: ""}))}" aria-label="Layer name">
      <label class="edx-check edx-namechk"><input type="checkbox" data-k="role" ${e.role === "name" ? "checked" : ""}> <span><b>Name</b> · part of the signature, left out of the unsigned version</span></label>
      <div class="edx-field"><span>Show in</span><div class="seg edx-seg small">${formatEntries().map(([k, f]) =>
        `<button data-show="${k}" aria-pressed="${!(e.hide || []).includes(k)}" title="${(e.hide || []).includes(k) ? "Show" : "Hide"} this layer in ${f.label}">${f.label}</button>`).join("")}</div></div>
      ${maskInfo(e)}`, acts);
    if (e.type === "text") {
      html += sec("Text", `<textarea class="edx-in edx-text" id="p-text" rows="${Math.min(9, String(e.text).split("\n").length + 1)}" spellcheck="true">${esc(e.text)}</textarea>`);
      html += sec("Type", `<div class="edx-grid2"><label class="edx-field"><span>Font</span><select class="edx-in" data-k="font">${fontOptions(e.font || "Newsreader")}</select></label>
          ${num("weight", "Weight", e.weight || 400, 10, `min="${weights[0]}" max="${weights[1]}"`)}</div>
        <div class="edx-grid3">${num("size", "Size", round(e.size), .5, 'min="1"')}${num("leading", "Leading", e.leading ?? 1.15, .01)}${num("tracking", "Tracking", e.tracking || 0, 5)}</div>
        <div class="edx-grid${widths.length && italics ? 3 : 2}">${widths.length ? `<label class="edx-field"><span>Width</span><select class="edx-in" data-k="stretch">${widths.map(([w, n]) =>
            `<option value="${w}" ${Math.abs((e.stretch || 100) - w) < 1 ? "selected" : ""}>${n.replace("-", " ")}</option>`).join("")}</select></label>` : ""}
          ${italics ? `<label class="edx-field"><span>Style</span><select class="edx-in" data-k="italic"><option value="">Roman</option><option value="1" ${e.italic ? "selected" : ""}>Italic</option></select></label>` : ""}
          <label class="edx-field"><span>Case</span><select class="edx-in" data-k="case"><option value="">As typed</option><option value="upper" ${e.case === "upper" ? "selected" : ""}>UPPER</option><option value="lower" ${e.case === "lower" ? "selected" : ""}>lower</option></select></label></div>
        <div class="edx-field"><span>Lines</span><div class="seg edx-seg small">${["left", "center", "right"].map(a => `<button data-k="align" data-v="${a}" aria-pressed="${(e.align || "left") === a}">${a}</button>`).join("")}</div></div>`);
      html += sec("Colour", `<div class="edx-field"><span>Letters</span>${paintCtl("color", e.color || "#EEEAE2")}</div><div class="edx-field"><span>Full stops</span>${paintCtl("accent", e.accent || null, true)}</div>`);
    } else if (e.type === "line") {
      html += sec("Stroke", `<div class="edx-field"><span>Colour</span>${paintCtl("stroke", e.stroke || "#DA291C")}</div>${num("width", "Weight", e.width || 4, .5, 'min="0.5"')}`);
    } else {
      html += sec("Fill", paintCtl("fill", e.fill === undefined ? "#DA291C" : e.fill, true));
      html += sec("Outline", paintCtl("stroke", e.stroke || null, true) + (e.stroke ? `<div class="edx-grid2">${num("sw", "Weight", e.sw || 4, .5, 'min="0"')}
        <label class="edx-field"><span>Align</span><select class="edx-in" data-k="strokeAlign">${["inside", "center", "outside"].map(a => `<option ${(e.strokeAlign || "inside") === a ? "selected" : ""}>${a}</option>`).join("")}</select></label></div>` : ""));
    }
    if (e.type === "shape") html += sec(e.kind === "star" ? "Star" : "Polygon", `<div class="edx-grid2">${num("n", e.kind === "star" ? "Points" : "Sides", e.n || (e.kind === "star" ? 5 : 3), 1, 'min="3" max="24"')}
      ${e.kind === "star" ? num("inner", "Inner %", Math.round((e.inner || .45) * 100), 1, 'min="5" max="95"') : ""}</div>`);
    if (e.type === "path" && e.arc && (e.pts || []).length === 2) html += sec("Arc", `<div class="edx-grid2">${num("bend", "Bend %", Math.round(Math.abs(e.bend ?? .5) * 100), 1, 'min="0" max="150"')}
      <div class="edx-field"><span>Side</span><button class="btn small" data-act="flip">Flip</button></div></div>
      <p class="edx-note">100% is a half circle; 0 is straight. Drag the label to bend it by eye.</p>`);
    if (e.type === "path") html += sec("Path", `<label class="edx-check"><input type="checkbox" data-k="closed" ${e.closed ? "checked" : ""}> <span>Closed</span></label>
      <div class="edx-row"><button class="btn small" data-act="editpts">${editPts === e.id ? "Done editing" : "Edit points"}</button></div>
      <p class="edx-note">Double-click a path to edit its points. Drag a handle to shape a curve; hold Alt to make a corner.</p>`);
    const cols = e.type === "path" ? [["x", "X"], ["y", "Y"]] : e.type === "text" ? [["x", "X"], ["y", "Y"], ["size", "Size"]] : e.type === "line" ? [["x1", "X1"], ["y1", "Y1"], ["x2", "X2"], ["y2", "Y2"]] : [["x", "X"], ["y", "Y"], ["w", "W"], ["h", "H"]];
    const raw = e.__raw;
    const posVal = (f, k) => { const r = Design.resolve(raw, f); if (k === "x" || k === "y") { const bb = Design.bounds(r); return round(k === "x" ? bb.x : bb.y); } return round(+r[k] || 0); };
    html += sec("Position", `<div class="edx-pos" style="--cols:${cols.length}"><span></span>${cols.map(c => `<span class="h">${c[1]}</span>`).join("")}
      ${formatEntries().map(([f, F2]) => `<span class="f ${f === d.format ? "on" : ""} ${Design.shownIn(raw, f) ? "" : "off"}" title="${f === d.format ? "The format you're editing" : "Edit " + F2.label + " here, or switch to it"}">${F2.label}</span>${
        cols.map(([k]) => `<input class="${f === d.format ? "on" : ""}" type="number" step=".5" data-pos="${f}|${k}" value="${posVal(f, k)}" aria-label="${F2.label} ${k}">`).join("")}`).join("")}</div>
      <p class="edx-note">Each format keeps its own layout: moving or sizing in ${F().label} leaves the others alone.</p>
      ${e.type !== "line" ? `<div class="edx-grid2">${num("rotation", "Rotate", e.rotation || 0, 1)}</div>` : ""}`);
    html += sec("Align", alignRow(false));
    el.innerHTML = html;
    const text = $("#p-text", el);
    if (text) text.oninput = () => { mutate(() => { e.text = text.value; }, "text:" + e.id); const n = $("li.on .nm", root); if (n && !e.name) n.firstChild.textContent = label(e); };
    $$("[data-k]", el).forEach(inp => {
      const k = inp.dataset.k;
      const apply = () => mutate(() => {
        const v = inp.dataset.v ?? (inp.type === "checkbox" ? inp.checked : inp.value);
        if (k === "clip" || k === "clipInvert") { if (v) e[k] = true; else delete e[k]; }
        else if (k === "bend") { if (v === "" || isNaN(+v)) return; e.bend = +v < 0 ? +v / 100 : Math.sign(e.bend || 1) * +v / 100; if ((e.pts || []).length === 2) e.pts = arcPts(e.pts[0], e.pts[1], e.bend); }
        else if (k === "inner") { if (v === "" || isNaN(+v)) return; e.inner = Math.max(.05, Math.min(.95, +v / 100)); }
        else if (k === "n") { if (v === "" || isNaN(+v)) return; e.n = Math.max(3, Math.min(24, Math.round(+v))); }
        else if (k === "role") { if (v) e.role = "name"; else delete e.role; }
        else if (k === "italic") e.italic = !!v;
        else if (["size", "leading", "tracking", "weight", "width", "rotation", "stretch", "w", "h", "x1", "y1", "x2", "y2", "sw"].includes(k)) { if (v === "" || isNaN(+v)) return; e[k] = +v; }
        else if (k === "x" || k === "y") { if (v === "" || isNaN(+v)) return; const bb = Design.bounds(e); e[k] = +v - (k === "x" ? bb.x - e.x : bb.y - e.y); }
        else if (k === "case") { if (v) e.case = v; else delete e.case; }
        else if (k === "font") setFont(e, v);
        else if (k === "name") { if (v.trim()) e.name = v.trim(); else delete e.name; }
        else e[k] = v;
      }, k + ":" + e.id);
      if (inp.tagName === "BUTTON") inp.onclick = () => { apply(); props(); };
      else if (inp.tagName === "SELECT" || inp.type === "checkbox") inp.onchange = () => { apply(); panels(); };
      else if (k === "name") inp.onchange = () => { apply(); panels(); };
      else { inp.oninput = apply; inp.onchange = () => props(); }
    });
    // drag a field's label to scrub its value
    $$("[data-scrub]", el).forEach(lab => lab.onpointerdown = ev => {
      const inp = lab.nextElementSibling; if (inp.disabled) return;
      ev.preventDefault(); lab.setPointerCapture(ev.pointerId);
      const x0 = ev.clientX, v0 = +inp.value || 0, st = +lab.dataset.step || 1;
      lab.onpointermove = m => { const k = m.shiftKey ? 10 : 1; inp.value = Math.round((v0 + Math.round((m.clientX - x0) / 2) * st * k) * 100) / 100; inp.dispatchEvent(new Event("input")); };
      lab.onpointerup = () => { lab.onpointermove = null; lab.onpointerup = null; props(); };
    });
    wirePaints(el, k => e[k], (k, v) => {
      if (v == null) { if (k === "fill") e.fill = null; else delete e[k]; }
      else { e[k] = v; if (k === "stroke" && e.type !== "line" && !(+e.sw > 0)) e.sw = 4; }
    }, e.id);
    $$("[data-show]", el).forEach(b => b.onclick = () => {
      const f = b.dataset.show;
      mutate(() => { const h = new Set(e.hide || []); if (h.has(f)) h.delete(f); else h.add(f); if (h.size) e.hide = [...h]; else delete e.hide; });
      if (f === d.format && !shown(e)) sel = sel.filter(id => id !== e.id);
      panels();
    });
    $$("[data-pos]", el).forEach(inp => {
      const [f, k] = inp.dataset.pos.split("|");
      inp.oninput = () => {
        const v = +inp.value; if (inp.value === "" || isNaN(v)) return;
        mutate(() => {
          const r = Design.resolve(raw, f);
          raw.at ||= {};
          const o = raw.at[f] ||= Design.pickLayout(r);
          if ((k === "x" || k === "y") && r.type === "path") { const bb = Design.bounds(r); o.pts = Design.movePoints(r.pts, k === "x" ? v - bb.x : 0, k === "y" ? v - bb.y : 0); }
          else if (k === "x" || k === "y") { const bb = Design.bounds(r); o[k] = v - (k === "x" ? bb.x - r.x : bb.y - r.y); } else o[k] = v;
        }, "pos:" + f + k + e.id);
      };
      inp.onchange = () => props();
    });
    $("[data-act=delete]", el) && ($("[data-act=delete]", el).onclick = remove);
    $("[data-act=editpts]", el) && ($("[data-act=editpts]", el).onclick = () => { editPts = editPts === e.id ? null : e.id; panels(); paint(); });
    $("[data-act=unmask]", el) && ($("[data-act=unmask]", el).onclick = () => releaseMask([e.id]));
    $("[data-act=flip]", el) && ($("[data-act=flip]", el).onclick = () => { mutate(() => { e.bend = -(e.bend ?? .5); e.pts = arcPts(e.pts[0], e.pts[1], e.bend); }); props(); });
    $("[data-act=unmaskall]", el) && ($("[data-act=unmaskall]", el).onclick = () => releaseMask(unitOfBase(e.id).clips.map(c => c.id)));
    $("[data-act=dup]", el) && ($("[data-act=dup]", el).onclick = duplicate);
    wireAlign(el);
  }
  /* Style several layers of the same kind at once; values that differ show as "mixed". */
  function multiStyle(es) {
    const same = k => { const v0 = JSON.stringify(es[0][k] ?? null); return es.every(e => JSON.stringify(e[k] ?? null) === v0) ? {v: es[0][k]} : null; };
    const nv = (k, lbl, step, extra = "") => { const sv = same(k); return `<label class="edx-num"><span>${lbl}</span><input type="number" step="${step}" data-mk="${k}" value="${sv && sv.v != null ? sv.v : ""}" placeholder="${sv ? "" : "mixed"}" ${extra}></label>`; };
    const sel1 = (k, opts, cur) => `<select class="edx-in" data-mk="${k}">${cur == null ? `<option value="">mixed</option>` : ""}${opts.map(([v, l]) => `<option value="${esc(v)}" ${String(cur) === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    if (es.every(e => e.type === "text")) {
      const f = same("font"), c = same("case"), st = same("stretch"), al = same("align");
      const widthsAll = Design.WIDTHS.filter(([w]) => es.every(e => Design.widthsOf(e.font).some(x => x[0] === w)));   // widths every layer's font has
      return sec(`Type · ${es.length} text layers`, `<div class="edx-grid2"><label class="edx-field"><span>Font</span><select class="edx-in" data-mk="font">${f ? "" : `<option value="">mixed</option>`}${fontOptions(f ? f.v || "Newsreader" : null)}</select></label>${nv("weight", "Weight", 10)}</div>
        <div class="edx-grid3">${nv("size", "Size", .5, 'min="1"')}${nv("leading", "Leading", .01)}${nv("tracking", "Tracking", 5)}</div>
        <div class="edx-grid2">${widthsAll.length ? `<label class="edx-field"><span>Width</span>${sel1("stretch", widthsAll, st ? (st.v || 100) : null)}</label>` : "<span></span>"}
          <label class="edx-field"><span>Case</span>${sel1("case", [["none", "As typed"], ["upper", "UPPER"], ["lower", "lower"]], c ? (c.v || "none") : null)}</label></div>
        <div class="edx-field"><span>Align lines</span><div class="seg edx-seg small">${["left", "center", "right"].map(a => `<button data-mk="align" data-v="${a}" aria-pressed="${!!al && (al.v || "left") === a}">${a}</button>`).join("")}</div></div>`)
        + sec("Colour · all of them", `<div class="edx-field"><span>Letters</span>${paintCtl("color", same("color") ? (same("color").v || "#EEEAE2") : (es[0].color || "#EEEAE2"))}</div>
          <div class="edx-field"><span>Full stops</span>${paintCtl("accent", same("accent") ? (same("accent").v || null) : (es[0].accent || null), true)}</div>`);
    }
    if (es.every(e => ["rect", "ellipse", "shape", "path"].includes(e.type))) {
      const fl = same("fill");
      return sec("Fill · all of them", paintCtl("fill", fl ? (fl.v === undefined ? "#DA291C" : fl.v) : (es[0].fill ?? "#DA291C"), true))
        + sec("Outline · all of them", paintCtl("stroke", same("stroke") ? (same("stroke").v || null) : (es[0].stroke || null), true) + `<div class="edx-grid2">${nv("sw", "Weight", .5, 'min="0"')}</div>`);
    }
    if (es.every(e => e.type === "line")) return sec("Stroke · all of them", paintCtl("stroke", es[0].stroke || "#DA291C") + `<div class="edx-grid2">${nv("width", "Weight", .5, 'min="0.5"')}</div>`);
    return "";
  }
  function wireMultiStyle(el, es) {
    $$("[data-mk]", el).forEach(inp => {
      const k = inp.dataset.mk;
      const apply = () => {
        const v = inp.dataset.v ?? inp.value;
        if (v === "") return;
        mutate(() => es.forEach(e => {
          if (k === "font") setFont(e, v);
          else if (k === "case") { if (v === "none") delete e.case; else e.case = v; }
          else if (["size", "leading", "tracking", "weight", "stretch", "sw", "width"].includes(k)) { if (!isNaN(+v)) e[k] = +v; }
          else e[k] = v;
        }), "multi:" + k);
      };
      if (inp.tagName === "BUTTON") inp.onclick = () => { apply(); props(); };
      else if (inp.tagName === "SELECT") inp.onchange = () => { apply(); props(); };
      else { inp.oninput = apply; inp.onchange = () => props(); }
    });
    wirePaints(el, k => es[0][k], (k, v) => es.forEach(e => {
      if (v == null) { if (k === "fill") e.fill = null; else delete e[k]; }
      else { e[k] = JSON.parse(JSON.stringify(v)); if (k === "stroke" && e.type !== "line" && !(+e.sw > 0)) e.sw = 4; }
    }), "multi");
  }

  function wireSwatches(el, set) {
    $$("[data-sw]", el).forEach(b => b.onclick = () => { set(b.dataset.sw, b.dataset.v); props(); });
    $$("[data-color]", el).forEach(i => { i.oninput = () => set(i.dataset.color, i.value.toUpperCase()); i.onchange = () => props(); });
  }
  function wireAlign(el) {
    const m = $("#al-m", el);
    if (m) m.onchange = () => pref.set("alm", m.checked ? "1" : "0");
    $$("[data-align]", el).forEach(b => b.onclick = () => align(b.dataset.align, m ? m.checked : false));
  }

  return {mount, unmount, update, pending};
})();
