/* Runs design-core.js in node with a stand-in for the browser, and prints what Design.starter and Design.colours
   make for the cases given. Used by tests/test_design_core.py.

     node starters.js <design-core.js> <input.json>
     input: {"fonts": [/api/fonts entries], "cases": [{"kind", "format", "info"}], "colours": [palette, ...]}
     output: {"starters": [design, ...], "colours": [{background, text, accent, muted}, ...]}

   The stand-in measures type the same way every time: an advance is half the size per character, wider with the
   font's width and weight, plus the letter-spacing; the cap height is 0.7 of the size; every metric is
   {cap: 0.7, g: {}}. Element ids are left out of the output (they are made from the clock).
   With "cold": true no face is loaded until document.fonts.load asks for it ("700 40px \"Archivo\""); until then
   type in it is measured in a wider fallback (0.6 of the size per character), as a browser would. */
"use strict";
const fs = require("fs"), vm = require("vm");
const [core, input] = process.argv.slice(2);
const data = JSON.parse(fs.readFileSync(input, "utf8"));

const px = v => parseFloat(v) || 0;
const loaded = new Set();
const faceOf = (family, weight, italic) => `${String(family).replace(/["']/g, "").trim().toLowerCase()}|${+weight || 400}|${italic ? 1 : 0}`;
const faceIn = font => { const m = /^(italic )?(\d+) [\d.]+px (.+)$/.exec(font); return m ? faceOf(m[3], m[2], m[1]) : font; };
const isLoaded = face => !data.cold || loaded.has(face);
function node(tag) {
  const el = {
    tagName: tag, style: {}, children: [], parent: null, className: "", id: "", text: "",
    appendChild(c) { c.parent = el; el.children.push(c); return c; },
    get firstChild() { return el.children[0] || null; },
    set innerHTML(html) {   // capPx's probe: a zero-size marker on the baseline, then "H"
      el.children = [];
      if (html.startsWith("<i")) el.appendChild(Object.assign(node("i"), {marker: true}));
    },
    set textContent(t) { el.text = String(t); },
    get textContent() { return el.text; },
    getBoundingClientRect() {
      if (el.marker) return {top: 0.7 * px(el.parent.style.fontSize), left: 0, width: 0, height: 0};
      const s = el.style, size = px(s.fontSize), n = [...el.text].length;
      const stretch = (px(s.fontStretch) || 100) / 100, weight = 1 + ((+s.fontWeight || 400) - 400) / 2000;
      const advance = isLoaded(faceOf(s.fontFamily, s.fontWeight, s.fontStyle === "italic")) ? 0.5 : 0.6;
      return {top: 0, left: 0, width: n * size * advance * stretch * weight + n * px(s.letterSpacing), height: size};
    },
  };
  return el;
}
const document = {head: node("head"), body: node("body"), getElementById: () => null, createElement: node,
  fonts: {load: f => { loaded.add(faceIn(f)); return Promise.resolve([]); }, check: f => isLoaded(faceIn(f)), ready: Promise.resolve()}};
const fetch = (url, opt) => {
  const keys = JSON.parse(opt.body).keys;
  return Promise.resolve({json: () => Promise.resolve(Object.fromEntries(keys.map(k => [k, {cap: 0.7, g: {}}])))});
};
const ctx = vm.createContext({console, document, fetch});
const Design = vm.runInContext(fs.readFileSync(core, "utf8") + "\n;Design", ctx);
Design.setFonts(data.fonts);

const noIds = v => Array.isArray(v) ? v.map(noIds) : v && typeof v === "object"
  ? Object.fromEntries(Object.entries(v).filter(([k]) => k !== "id").map(([k, x]) => [k, noIds(x)])) : v;
(async () => {
  const starters = [];
  for (const c of data.cases) starters.push(noIds(await Design.starter(c.kind, c.format ?? null, c.info)));
  const colours = (data.colours || []).map(p => Design.colours ? Design.colours(p) : null);
  process.stdout.write(JSON.stringify({starters, colours}));
})().catch(e => { console.error(e); process.exit(1); });
