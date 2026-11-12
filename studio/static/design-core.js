"use strict";
/* Studio design core: the design model and its renderer, shared by the editor and the export page.

   A design is {name, format: "11"|"45"|"916", background, elements: [...]}, in slide pixels (1080 wide).
   It renders as HTML, the way a series kit renders its slides, so variable widths, tracking and
   optical sizes come out exactly as in the carousel. Text sits on its ink, like the kit: x is the left
   ink edge, y the cap top of the first line, w the widest line's ink, h from that cap top to the last
   baseline. Ink edges come from the font files (/api/metrics). Elements: text, rect, ellipse, line;
   role "name" is left out of the unsigned version. */
const Design = (() => {
  const FORMATS = {
    "11": {w: 1080, h: 1080, label: "1:1", tag: "1x1"},
    "45": {w: 1080, h: 1350, label: "4:5", tag: "4x5"},
    "916": {w: 1080, h: 1920, label: "9:16", tag: "9x16"},
  };
  const SAFE = {"11": {t: 96, b: 96, s: 88}, "45": {t: 112, b: 112, s: 88}, "916": {t: 280, b: 330, s: 88}};
  const WIDTHS = [[62.5, "Extra condensed"], [75, "Condensed"], [87.5, "Semi condensed"], [100, "Normal"], [112.5, "Semi expanded"], [125, "Expanded"]];
  const WEIGHTS = {Newsreader: [200, 800], Archivo: [100, 900]};
  const CAP0 = {Newsreader: .67, Archivo: .686};
  const OPSZ = [6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40, 48, 56, 64, 72];
  /* Each element keeps its own layout per format: e.at = {"11": {...}, "45": {...}, "916": {...}} overrides these
     keys (anything not overridden comes from the element itself). e.hide = ["916"] leaves it out of a format. */
  const LAYOUT = ["x", "y", "w", "h", "x1", "y1", "x2", "y2", "size", "leading", "tracking", "stretch", "weight", "rotation", "align", "width", "sw", "pts"];
  const resolve = (e, fmt) => { const o = e.at?.[fmt]; return o ? {...e, ...o} : e; };
  const shownIn = (e, fmt) => !e.hidden && !(e.hide || []).includes(fmt);
  const pickLayout = e => { const o = {}; for (const k of LAYOUT) if (e[k] !== undefined) o[k] = e[k]; return o; };
  let n = 0, version = 0, onMetrics = null;
  const uid = () => "e" + Date.now().toString(36) + (n++).toString(36);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

  /* ——— metrics: sidebearings + cap height per font instance, from the font files ——— */
  const metrics = new Map(), pending = new Map();
  function mkey(e) {
    const font = e.font === "Archivo" ? "Archivo" : "Newsreader";
    const italic = font === "Newsreader" && e.italic ? 1 : 0;
    const weight = Math.round((+e.weight || 400) / 10) * 10;
    const width = font === "Archivo" ? Math.round((+e.stretch || 100) * 2) / 2 : 100;
    const s = Math.min(72, Math.max(6, +e.size || 72));
    const opsz = font === "Newsreader" ? OPSZ.reduce((a, b) => Math.abs(b - s) < Math.abs(a - s) ? b : a) : 0;
    return `${font}|${italic}|${weight}|${width}|${opsz}`;
  }
  function loadMetrics(keys) {
    const missing = [...new Set(keys)].filter(k => !metrics.has(k) && !pending.has(k));
    const waits = keys.map(k => pending.get(k)).filter(Boolean);
    if (missing.length) {
      const p = fetch("/api/metrics", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({keys: missing})})
        .then(r => r.json()).then(m => { for (const [k, v] of Object.entries(m)) metrics.set(k, v); })
        .catch(() => {}).finally(() => { missing.forEach(k => pending.delete(k)); version++; onMetrics?.(); });
      missing.forEach(k => pending.set(k, p));
      waits.push(p);
    }
    return Promise.all(waits);
  }
  function metricsOf(e) {
    const k = mkey(e);
    const m = metrics.get(k);
    if (m) return m;
    if (!pending.has(k)) loadMetrics([k]);
    return {cap: CAP0[e.font] || .68, g: {}, rough: true};
  }

  function ensureCss() {
    if (document.getElementById("dz-css")) return;
    const st = document.createElement("style"); st.id = "dz-css";
    st.textContent = ".dz-board{-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}"
      + ".dz-ln{position:absolute;white-space:pre;line-height:1;text-box:trim-both cap alphabetic;font-kerning:normal}";
    document.head.appendChild(st);
  }

  /* ——— measuring in the browser itself: advance widths, and where Chrome puts the baseline ——— */
  let meas = null, probe = null;
  const ccache = new Map();
  /* Distance from the top of a trimmed line box to its baseline: the cap height exactly as Chrome trims it. */
  function capPx(e, size) {
    const k = `${e.font}|${e.weight}|${e.italic}|${e.stretch}|${size}`;
    let c = ccache.get(k);
    if (c != null) return c;
    ensureCss();
    if (!probe) {
      probe = document.createElement("div");
      probe.className = "dz-ln";
      probe.style.left = "-99999px"; probe.style.top = "0"; probe.style.visibility = "hidden";
      probe.innerHTML = '<i style="display:inline-block;width:0;height:0;vertical-align:baseline"></i>H';
      document.body.appendChild(probe);
    }
    fontStyle(probe.style, e, size);
    c = probe.firstChild.getBoundingClientRect().top - probe.getBoundingClientRect().top;
    if (ccache.size > 4000) ccache.clear();
    ccache.set(k, c);
    return c;
  }
  const wcache = new Map();
  function fontStyle(st, e, size) {
    st.fontFamily = `"${e.font || "Newsreader"}"`;
    st.fontWeight = String(e.weight || 400);
    st.fontStyle = e.italic && e.font !== "Archivo" ? "italic" : "normal";
    st.fontStretch = (e.font === "Archivo" ? (+e.stretch || 100) : 100) + "%";
    st.fontSize = size + "px";
    st.letterSpacing = ((+e.tracking || 0) / 1000 * size) + "px";
    st.fontKerning = "normal";
  }
  function advance(e, size, t) {
    const k = `${e.font}|${e.weight}|${e.italic}|${e.stretch}|${size}|${e.tracking}|${t}`;
    let w = wcache.get(k);
    if (w != null) return w;
    if (!meas) {
      meas = document.createElement("span");
      meas.style.cssText = "position:absolute;left:-99999px;top:0;visibility:hidden;white-space:pre;line-height:1";
      document.body.appendChild(meas);
    }
    fontStyle(meas.style, e, size);
    meas.textContent = t;
    w = meas.getBoundingClientRect().width - (+e.tracking || 0) / 1000 * size;   // drop the trailing letter-space
    if (wcache.size > 6000) wcache.clear();
    wcache.set(k, w);
    return w;
  }

  const textLines = e => {
    let t = String(e.text ?? "");
    if (e.case === "upper") t = t.toUpperCase(); else if (e.case === "lower") t = t.toLowerCase();
    return t.split("\n");
  };

  /* Lay out a text element on its ink. */
  function layout(_, el) {
    const e = el || _;
    const size = Math.max(1, +e.size || 100), lead = (e.leading ?? 1.15) * size, m = metricsOf(e), capH = capPx(e, size);
    const lines = textLines(e).map((s, i) => {
      const t = s.replace(/\s+$/, "");
      if (!t) return {s: t, l: 0, r: 0, w: 0, adv: 0, base: capH + i * lead};
      const adv = advance(e, size, t), l = (m.g[t[0]]?.[0] || 0) * size, r = (m.g[t.at(-1)]?.[1] || 0) * size;
      return {s: t, l, r, w: adv - l - r, adv, base: capH + i * lead};
    });
    const w = Math.max(1, ...lines.map(x => x.w));
    return {lines, size, lead, capH, w, h: capH + (lines.length - 1) * lead, rough: !!m.rough};
  }

  /* Pen paths: pts = [{x, y, ix?, iy?, ox?, oy?}] (anchor, in- and out-handles), closed. */
  const r2 = v => Math.round(v * 100) / 100;
  function movePoints(pts, dx, dy) {
    return (pts || []).map(q => {
      const n = {...q, x: r2(q.x + dx), y: r2(q.y + dy)};
      if (q.ix != null) { n.ix = r2(q.ix + dx); n.iy = r2(q.iy + dy); }
      if (q.ox != null) { n.ox = r2(q.ox + dx); n.oy = r2(q.oy + dy); }
      return n;
    });
  }
  function pathD(pts, closed) {
    if (!pts?.length) return "";
    const seg = (a, b) => (a.ox != null || b.ix != null) ? ` C${a.ox ?? a.x} ${a.oy ?? a.y} ${b.ix ?? b.x} ${b.iy ?? b.y} ${b.x} ${b.y}` : ` L${b.x} ${b.y}`;
    let out = `M${pts[0].x} ${pts[0].y}`;
    for (let i = 1; i < pts.length; i++) out += seg(pts[i - 1], pts[i]);
    if (closed && pts.length > 2) out += seg(pts.at(-1), pts[0]) + " Z";
    return out;
  }
  /* Polygon and star corners, stretched to fill a w x h box (so the box is the shape's edge). */
  function shapePoints(e, w, h) {
    const n = Math.max(3, Math.round(+e.n || (e.kind === "star" ? 5 : 3))), star = e.kind === "star", inner = Math.max(.05, Math.min(.95, +e.inner || .45));
    const raw = [];
    for (let i = 0; i < (star ? 2 * n : n); i++) {
      const a = -Math.PI / 2 + i * Math.PI * 2 / (star ? 2 * n : n), r = star && i % 2 ? inner : 1;
      raw.push([Math.cos(a) * r, Math.sin(a) * r]);
    }
    const xs = raw.map(q => q[0]), ys = raw.map(q => q[1]), x0 = Math.min(...xs), y0 = Math.min(...ys);
    const sx = w / ((Math.max(...xs) - x0) || 1), sy = h / ((Math.max(...ys) - y0) || 1);
    return raw.map(([x, y]) => [(x - x0) * sx, (y - y0) * sy]);
  }

  function bounds(_, el) {
    const e = el || _;
    if (e.type === "path") {
      const xs = [], ys = [];
      for (const q of e.pts || []) { xs.push(q.x); ys.push(q.y); if (q.ix != null) { xs.push(q.ix); ys.push(q.iy); } if (q.ox != null) { xs.push(q.ox); ys.push(q.oy); } }
      if (!xs.length) return {x: 0, y: 0, w: 0, h: 0};
      const x = Math.min(...xs), y = Math.min(...ys);
      return {x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y};
    }
    if (e.type === "text") { const L = layout(e); return {x: e.x, y: e.y, w: L.w, h: L.h}; }
    if (e.type === "line") return {x: Math.min(e.x1, e.x2), y: Math.min(e.y1, e.y2), w: Math.abs(e.x2 - e.x1), h: Math.abs(e.y2 - e.y1)};
    return {x: Math.min(e.x, e.x + e.w), y: Math.min(e.y, e.y + e.h), w: Math.abs(e.w), h: Math.abs(e.h)};
  }

  /* ——— rendering (HTML, like the kit) ——— */
  /* ——— paints: a colour is "#RRGGBB", or a gradient {type: "linear"|"radial", angle (0 = left to right,
     counter-clockwise, like Illustrator), stops: [{c: "#RRGGBB", p: 0..1}, ...]} ——— */
  const isGrad = v => !!v && typeof v === "object" && Array.isArray(v.stops) && v.stops.length > 0;
  const stopsOf = g => [...g.stops].sort((a, b) => a.p - b.p);
  const firstColor = v => isGrad(v) ? stopsOf(v)[0].c : v;
  function cssPaint(v, fallback) {
    if (!v) return fallback;
    if (!isGrad(v)) return v;
    const st = stopsOf(v).map(x => `${x.c} ${Math.round(x.p * 10000) / 100}%`).join(", ");
    return v.type === "radial" ? `radial-gradient(ellipse farthest-side at 50% 50%, ${st})` : `linear-gradient(${90 - (+v.angle || 0)}deg, ${st})`;
  }
  /* The same gradient line CSS uses, in user space, so SVG and CSS gradients match exactly. */
  function svgPaint(defs, v, box) {
    if (!isGrad(v)) return v || "none";
    const ns = "http://www.w3.org/2000/svg", id = "g" + uid();
    const g = document.createElementNS(ns, v.type === "radial" ? "radialGradient" : "linearGradient");
    g.setAttribute("id", id);
    g.setAttribute("gradientUnits", "userSpaceOnUse");
    const cx = box.x + box.w / 2, cy = box.y + box.h / 2;
    if (v.type === "radial") {
      g.setAttribute("cx", cx); g.setAttribute("cy", cy); g.setAttribute("r", Math.max(box.w, box.h) / 2);
      if (box.w !== box.h && box.w > 0 && box.h > 0) g.setAttribute("gradientTransform", `translate(${cx} ${cy}) scale(${box.w / Math.max(box.w, box.h)} ${box.h / Math.max(box.w, box.h)}) translate(${-cx} ${-cy})`);
    } else {
      const a = (90 - (+v.angle || 0)) * Math.PI / 180, dx = Math.sin(a), dy = -Math.cos(a);
      const L = Math.abs(box.w * Math.sin(a)) + Math.abs(box.h * Math.cos(a)) || 1;
      g.setAttribute("x1", cx - dx * L / 2); g.setAttribute("y1", cy - dy * L / 2); g.setAttribute("x2", cx + dx * L / 2); g.setAttribute("y2", cy + dy * L / 2);
    }
    for (const x of stopsOf(v)) { const s2 = document.createElementNS(ns, "stop"); s2.setAttribute("offset", x.p); s2.setAttribute("stop-color", x.c); g.appendChild(s2); }
    defs.appendChild(g);
    return `url(#${id})`;
  }

  function build(e, F) {
    const ns = "http://www.w3.org/2000/svg";
    if (e.type === "line") {   // an SVG line, as the kit draws its lines
      const svg = document.createElementNS(ns, "svg"), ln = document.createElementNS(ns, "line"), defs = document.createElementNS(ns, "defs");
      svg.setAttribute("width", F.w); svg.setAttribute("height", F.h); svg.setAttribute("viewBox", `0 0 ${F.w} ${F.h}`);
      svg.style.cssText = "position:absolute;left:0;top:0;overflow:visible;pointer-events:none";
      svg.appendChild(defs);
      const stroke = svgPaint(defs, e.stroke || "#DA291C", bounds(e));
      for (const [k, v] of Object.entries({x1: e.x1, y1: e.y1, x2: e.x2, y2: e.y2, stroke, "stroke-width": +e.width || 4, "stroke-linecap": "butt"})) ln.setAttribute(k, v);
      svg.appendChild(ln);
      return svg;
    }
    if (e.type === "path") {
      const b = bounds(e), svg = document.createElementNS(ns, "svg"), defs = document.createElementNS(ns, "defs"), path = document.createElementNS(ns, "path");
      svg.setAttribute("width", F.w); svg.setAttribute("height", F.h); svg.setAttribute("viewBox", `0 0 ${F.w} ${F.h}`);
      svg.style.cssText = `position:absolute;left:0;top:0;overflow:visible;pointer-events:none;transform-origin:${b.x + b.w / 2}px ${b.y + b.h / 2}px`
        + (e.rotation ? `;transform:rotate(${e.rotation}deg)` : "");
      svg.appendChild(defs);
      path.setAttribute("d", pathD(e.pts, e.closed));
      path.setAttribute("fill", e.fill ? svgPaint(defs, e.fill, b) : "none");
      path.setAttribute("stroke", e.stroke && +e.sw > 0 ? svgPaint(defs, e.stroke, b) : "none");
      path.setAttribute("stroke-width", +e.sw || 0);
      path.setAttribute("stroke-linejoin", "miter"); path.setAttribute("stroke-linecap", "butt");
      svg.appendChild(path);
      return svg;
    }
    if (e.type === "shape" || ((e.type === "rect" || e.type === "ellipse") && e.stroke && +e.sw > 0)) {   // polygons, stars and outlined shapes are SVG
      const b = bounds(e), sw = e.stroke ? +e.sw || 0 : 0, inset = e.strokeAlign === "outside" ? -sw / 2 : e.strokeAlign === "center" ? 0 : sw / 2;
      const svg = document.createElementNS(ns, "svg"), defs = document.createElementNS(ns, "defs");
      svg.setAttribute("width", b.w); svg.setAttribute("height", b.h); svg.setAttribute("viewBox", `0 0 ${b.w} ${b.h}`);
      svg.style.cssText = `position:absolute;left:${b.x}px;top:${b.y}px;overflow:visible;pointer-events:none;transform-origin:${b.w / 2}px ${b.h / 2}px`
        + (e.rotation ? `;transform:rotate(${e.rotation}deg)` : "");
      svg.appendChild(defs);
      const box = {x: 0, y: 0, w: b.w, h: b.h};
      let shape;
      if (e.type === "shape") {
        shape = document.createElementNS(ns, "polygon");
        const k = e.stroke && +e.sw > 0 ? inset : 0, w2 = Math.max(0, b.w - 2 * k), h2 = Math.max(0, b.h - 2 * k);
        shape.setAttribute("points", shapePoints(e, w2, h2).map(([x, y]) => `${r2(x + k)},${r2(y + k)}`).join(" "));
        shape.setAttribute("stroke-linejoin", "miter");
      } else if (e.type === "rect") {
        shape = document.createElementNS(ns, "rect");
        for (const [k, v] of Object.entries({x: inset, y: inset, width: Math.max(0, b.w - 2 * inset), height: Math.max(0, b.h - 2 * inset)})) shape.setAttribute(k, v);
      } else {
        shape = document.createElementNS(ns, "ellipse");
        for (const [k, v] of Object.entries({cx: b.w / 2, cy: b.h / 2, rx: Math.max(0, b.w / 2 - inset), ry: Math.max(0, b.h / 2 - inset)})) shape.setAttribute(k, v);
      }
      shape.setAttribute("fill", e.fill === null ? "none" : svgPaint(defs, e.fill || "#DA291C", box));
      shape.setAttribute("stroke", e.stroke && sw > 0 ? svgPaint(defs, e.stroke, box) : "none");
      shape.setAttribute("stroke-width", sw || 0);
      svg.appendChild(shape);
      return svg;
    }
    const node = document.createElement("div");
    const st = node.style;
    st.position = "absolute";
    if (e.type === "rect" || e.type === "ellipse") {
      const b = bounds(e);
      Object.assign(st, {left: b.x + "px", top: b.y + "px", width: b.w + "px", height: b.h + "px", background: e.fill === null ? "none" : cssPaint(e.fill, "#DA291C")});
      if (e.type === "ellipse") st.borderRadius = "50%";
      if (e.rotation) st.transform = `rotate(${e.rotation}deg)`;
    } else if (e.type === "text") {
      const L = layout(e), grad = isGrad(e.color), color = grad ? "transparent" : (e.color || "#EEEAE2");
      st.left = "0"; st.top = "0";
      if (e.rotation) { st.transformOrigin = `${e.x + L.w / 2}px ${e.y + L.h / 2}px`; st.transform = `rotate(${e.rotation}deg)`; }
      // a gradient spans the whole text block: each line shows its own slice of it
      const gTop = e.y - L.capH * .35, gH = L.h + L.capH * .7;
      const clip = (paint, x0, y0) => `background-image:${cssPaint(paint)};background-size:${L.w}px ${gH}px;background-position:${e.x - x0}px ${gTop - y0}px;background-repeat:no-repeat;-webkit-background-clip:text;background-clip:text;color:transparent`;
      node.innerHTML = L.lines.map(ln => {
        if (!ln.s) return "";
        const left = e.align === "right" ? e.x + L.w - ln.w : e.align === "center" ? e.x + (L.w - ln.w) / 2 : e.x;
        const x0 = left - ln.l, y0 = e.y + ln.base - L.capH;
        const dot = !e.accent ? "" : isGrad(e.accent) ? `<span style="${clip(e.accent, x0, y0)}">.</span>` : `<span style="color:${esc(e.accent)};-webkit-text-fill-color:${esc(e.accent)}">.</span>`;
        const txt = e.accent && ln.s.endsWith(".") ? `${esc(ln.s.slice(0, -1))}${dot}` : esc(ln.s);
        return `<div class="dz-ln" style="left:${x0}px;top:${y0}px;color:${esc(color)};${grad ? clip(e.color, x0, y0) : ""}">${txt}</div>`;
      }).join("");
      for (const ln of node.children) fontStyle(ln.style, e, L.size);
    }
    return node;
  }

  /* ——— masks: a layer with clip: true shows only inside the nearest layer below it that isn't clipped
     (like Krita's inherit alpha, or a clipping mask); clipInvert shows it only outside that shape. ——— */
  const rotPt = (x, y, c, deg) => { if (!deg) return [x, y]; const a = deg * Math.PI / 180, dx = x - c.x, dy = y - c.y; return [c.x + dx * Math.cos(a) - dy * Math.sin(a), c.y + dx * Math.sin(a) + dy * Math.cos(a)]; };
  /* The base's outline as one path (rotation baked in), for clipping; null for text. */
  function outlineD(e) {
    const b = bounds(e), c = {x: b.x + b.w / 2, y: b.y + b.h / 2}, rot = e.rotation || 0;
    const poly = pts => "M" + pts.map(([x, y]) => rotPt(x, y, c, rot).map(r2).join(" ")).join(" L") + " Z";
    if (e.type === "rect") return poly([[b.x, b.y], [b.x + b.w, b.y], [b.x + b.w, b.y + b.h], [b.x, b.y + b.h]]);
    if (e.type === "shape") return poly(shapePoints(e, b.w, b.h).map(([x, y]) => [x + b.x, y + b.y]));
    if (e.type === "ellipse") {
      const [x1, y1] = rotPt(b.x, c.y, c, rot), [x2, y2] = rotPt(b.x + b.w, c.y, c, rot);
      return `M${r2(x1)} ${r2(y1)} A${b.w / 2} ${b.h / 2} ${rot} 1 0 ${r2(x2)} ${r2(y2)} A${b.w / 2} ${b.h / 2} ${rot} 1 0 ${r2(x1)} ${r2(y1)} Z`;
    }
    if (e.type === "line") {
      const w = (+e.width || 4) / 2, len = Math.hypot(e.x2 - e.x1, e.y2 - e.y1) || 1, nx = -(e.y2 - e.y1) / len * w, ny = (e.x2 - e.x1) / len * w;
      return poly([[e.x1 + nx, e.y1 + ny], [e.x2 + nx, e.y2 + ny], [e.x2 - nx, e.y2 - ny], [e.x1 - nx, e.y1 - ny]]);
    }
    if (e.type === "path") {
      const pts = (e.pts || []).map(q => { const n = {}; for (const [kx, ky] of [["x", "y"], ["ix", "iy"], ["ox", "oy"]]) if (q[kx] != null) { const [x, y] = rotPt(q[kx], q[ky], c, rot); n[kx] = r2(x); n[ky] = r2(y); } return n; });
      return pathD(pts, true);
    }
    return null;
  }
  function buildClip(u, F) {
    const ns = "http://www.w3.org/2000/svg", id = "cp" + uid(), base = u.base;
    const wrap = document.createElement("div");
    wrap.style.cssText = `position:absolute;left:0;top:0;width:${F.w}px;height:${F.h}px;pointer-events:none`;
    const svg = document.createElementNS(ns, "svg"), cp = document.createElementNS(ns, "clipPath");
    svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;left:0;top:0";
    cp.setAttribute("id", id); cp.setAttribute("clipPathUnits", "userSpaceOnUse");
    const invert = !!u.items[0].clipInvert, d0 = outlineD(base);
    if (d0) {
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", invert ? `M0 0 H${F.w} V${F.h} H0 Z ${d0}` : d0);
      path.setAttribute("clip-rule", invert ? "evenodd" : "nonzero");
      cp.appendChild(path);
    } else if (base.type === "text") {   // letters as the mask
      const L = layout(base), c = {x: base.x + L.w / 2, y: base.y + L.h / 2};
      for (const ln of L.lines) {
        if (!ln.s) continue;
        const left = base.align === "right" ? base.x + L.w - ln.w : base.align === "center" ? base.x + (L.w - ln.w) / 2 : base.x;
        const t = document.createElementNS(ns, "text");
        t.setAttribute("x", left - ln.l); t.setAttribute("y", base.y + ln.base);
        if (base.rotation) t.setAttribute("transform", `rotate(${base.rotation} ${c.x} ${c.y})`);
        fontStyle(t.style, base, L.size);
        t.style.whiteSpace = "pre";
        t.textContent = ln.s;
        cp.appendChild(t);
      }
    }
    svg.appendChild(cp);
    const inner = document.createElement("div");
    inner.style.cssText = `position:absolute;left:0;top:0;width:${F.w}px;height:${F.h}px;clip-path:url(#${id})`;
    for (const e of u.items) inner.appendChild(build(e, F));
    wrap.append(svg, inner);
    return wrap;
  }

  /* Render a design into `host` (keyed by element id, so re-renders are cheap). */
  function render(host, d, opts = {}) {
    ensureCss();
    const F = opts.size || FORMATS[opts.format] || FORMATS[d.format] || FORMATS["45"];
    host.classList.add("dz-board");
    Object.assign(host.style, {position: "relative", width: F.w + "px", height: F.h + "px", overflow: "hidden", background: cssPaint(d.background, "#0C0E11")});
    const nodes = host._nodes || (host._nodes = new Map());
    const keep = new Set();
    let prev = null;
    const fmt = FORMATS[opts.format] ? opts.format : (FORMATS[d.format] ? d.format : "45");
    // what shows, in order; clipped layers follow their base (and vanish with it)
    const list = [];
    let baseHidden = false;
    for (const raw of d.elements || []) {
      const vis = shownIn(raw, fmt) && !(opts.signed === false && raw.role === "name");
      if (!raw.clip) baseHidden = !vis;
      if (!vis || (raw.clip && baseHidden)) continue;
      list.push(resolve(raw, fmt));
    }
    const units = [];
    for (const e of list) {
      const last = units.at(-1);
      if (e.clip && last) {
        if (last.kind === "clip" && !!last.items[0].clipInvert === !!e.clipInvert) last.items.push(e);
        else units.push({kind: "clip", base: last.kind === "clip" ? last.base : last.e, items: [e]});
        continue;
      }
      units.push({kind: "el", e});
    }
    for (const u of units) {
      const key = (u.kind === "el" ? u.e.id : "c:" + u.items[0].id) || "i" + units.indexOf(u);
      const sig = (u.kind === "el" ? JSON.stringify(u.e) : JSON.stringify([u.base, u.items])) + "|" + version + "|" + fmt + "|" + F.w + "x" + F.h;
      let node = nodes.get(key);
      if (!node || node._sig !== sig) {
        const fresh = u.kind === "el" ? build(u.e, F) : buildClip(u, F);
        fresh._sig = sig;
        if (node) node.replaceWith(fresh); else host.appendChild(fresh);
        node = fresh; nodes.set(key, node);
      }
      if (node.previousElementSibling !== prev) prev ? prev.after(node) : host.prepend(node);
      prev = node; keep.add(key);
    }
    for (const [id, node] of nodes) if (!keep.has(id)) { node.remove(); nodes.delete(id); }
  }

  /* A scaled, static preview of a design (for galleries). */
  function thumb(d, width, opts = {}) {
    const F = opts.size || FORMATS[opts.format] || FORMATS[d.format] || FORMATS["45"], k = Math.min(width / F.w, (opts.maxH || 1e9) / F.h);
    const wrap = document.createElement("div");
    wrap.className = "dz-thumb";
    Object.assign(wrap.style, {width: width + "px", height: Math.round(F.h * k) + "px", overflow: "hidden", position: "relative"});
    const board = document.createElement("div");
    board.style.transformOrigin = "0 0"; board.style.transform = `scale(${k})`;
    wrap.appendChild(board);
    render(board, d, opts);
    return wrap;
  }

  async function ready(d) {
    const faces = new Set(['500 40px "Newsreader"', 'italic 400 40px "Newsreader"', '700 40px "Archivo"']);
    const keys = [];
    for (const raw of d?.elements || []) if (raw.type === "text") for (const f of [null, ...Object.keys(raw.at || {})]) {
      const e = f ? resolve(raw, f) : raw;
      faces.add(`${e.italic && e.font !== "Archivo" ? "italic " : ""}${e.weight || 400} 40px "${e.font || "Newsreader"}"`);
      keys.push(mkey(e));
    }
    await Promise.all([...faces].map(f => document.fonts.load(f).catch(() => null)));
    await document.fonts.ready;
    wcache.clear(); ccache.clear();
    await loadMetrics(keys);
  }

  /* Size a text element so its widest line's ink is exactly `width` wide (exact once metrics are in). */
  async function fitWidth(e, width) {
    for (let i = 0; i < 3; i++) {
      await loadMetrics([mkey(e)]);
      e.size = e.size * width / layout(e).w;
    }
    e.size = Math.round(e.size * 100) / 100;
    return e;
  }

  /* The layout an element gets in a format it hasn't been placed in yet: same place relative to the safe area. */
  function remapLayout(r, from, to) {
    const A = FORMATS[from], B = FORMATS[to], sa = SAFE[from], sb = SAFE[to];
    const map = y => Math.round((sb.t + (y - sa.t) * ((B.h - sb.t - sb.b) / (A.h - sa.t - sa.b))) * 2) / 2;
    const o = pickLayout(r);
    if (r.type === "line") { o.y1 = map(r.y1); o.y2 = map(r.y2); }
    else if (r.type === "path") { const b = bounds(r); o.pts = movePoints(r.pts, 0, map(b.y + b.h / 2) - (b.y + b.h / 2)); }
    else if ((r.type === "rect" || r.type === "ellipse") && Math.min(r.y, r.y + r.h) <= 0 && Math.max(r.y, r.y + r.h) >= A.h) { o.y = 0; o.h = B.h; }
    else { const b = bounds(r); o.y = map(b.y + b.h / 2) - b.h / 2 + (r.y - b.y); }
    return o;
  }

  /* One design from per-format versions with the same elements: the first is the base, the rest go into e.at. */
  function mergeFormats(byFmt, primary) {
    const base = JSON.parse(JSON.stringify(byFmt[primary]));
    base.format = primary;
    for (const [f, dd] of Object.entries(byFmt)) {
      const els = dd.elements;
      const same = els.length === base.elements.length && base.elements.every((e, i) => e.type === els[i].type && (e.type !== "text" || e.text === els[i].text));
      base.elements.forEach((e, i) => { (e.at ||= {})[f] = same ? pickLayout(els[i]) : (f === primary ? pickLayout(e) : remapLayout(e, primary, f)); });
    }
    return base;
  }

  /* ——— starting points, made from the series palette ——— */
  async function starter(kind, _, info) {
    const {lines: poemLines, palette, format, signature, title} = info;
    const F = FORMATS[format], S = SAFE[format], m = S.s;
    const dark = palette[0]?.hex || "#0C0E11", light = palette[1]?.hex || "#EEEAE2";
    const accent = palette[2]?.hex || "#DA291C", quiet = palette[3]?.hex || "#959AA2";
    const text = (poemLines?.length ? poemLines : ["Your poem", "goes here."]).join("\n");
    const d = {name: title || "Design", format, background: dark, elements: []};
    const name = props => ({id: uid(), type: "text", role: "name", name: "Name", text: signature || "Your name", font: "Archivo", weight: 700,
      size: format === "916" ? 32 : 28, tracking: 260, case: "upper", leading: 1, color: quiet, x: m, y: 0, ...props});
    if (kind === "blank") return d;
    if (kind === "page") {
      const poem = {id: uid(), type: "text", name: "Poem", text, font: "Newsreader", weight: 500, size: format === "916" ? 132 : 120,
        leading: 1.1, tracking: -12, color: light, accent, x: m + 32, y: 0};
      await loadMetrics([mkey(poem)]);
      if (layout(poem).w > F.w - 2 * (m + 32)) await fitWidth(poem, F.w - 2 * (m + 32));
      const sig = name({font: "Newsreader", italic: true, weight: 400, tracking: 10, case: undefined, size: format === "916" ? 46 : 40, color: quiet, x: poem.x});
      await loadMetrics([mkey(sig)]);
      const L = layout(poem), gap = poem.size * .7, total = L.h + gap + layout(sig).h;
      poem.y = S.t + (F.h - S.t - S.b - total) / 2;
      sig.y = poem.y + L.h + gap;
      d.elements.push(poem, sig);
      return d;
    }
    if (kind === "wall") {   // every line's ink fills the measure; one width for all lines, chosen to fill the height
      d.background = accent;
      const rows = text.split("\n").filter(Boolean), W = F.w - 2 * m, gap = format === "916" ? 24 : 18;
      const sig = name({color: dark, size: format === "916" ? 31 : 26});
      await loadMetrics([mkey(sig)]);
      const avail = F.h - S.t - S.b - layout(sig).h - 46;
      const mk = wd => rows.map(r => ({id: uid(), type: "text", name: r, text: r, font: "Archivo", weight: 900, stretch: wd,
        size: 100, leading: 1, tracking: -8, case: "upper", color: dark, x: m, y: 0}));
      const tall = els => els.reduce((a, e) => { const L = layout(e); e.size = e.size * W / L.w; return a + layout(e).capH; }, 0) + gap * (rows.length - 1);
      let lo = 62.5, hi = 125, els = mk(hi);
      if (tall(mk(lo)) <= avail) hi = lo;
      else for (let i = 0; i < 12; i++) { const mid = (lo + hi) / 2; if (tall(mk(mid)) > avail) lo = mid; else hi = mid; }
      const wd = Math.round(hi * 2) / 2;
      els = mk(wd);
      for (const e of els) await fitWidth(e, W);
      let sum = els.reduce((a, e) => a + layout(e).capH, 0) + gap * (rows.length - 1);
      if (sum > avail) { const k = (avail - gap * (rows.length - 1)) / (sum - gap * (rows.length - 1)); for (const e of els) await fitWidth(e, W * k); sum = avail; }
      let y = S.t + (avail - sum) / 2;
      for (const e of els) { e.y = Math.round(y * 2) / 2; y += layout(e).capH + gap; }
      sig.y = F.h - S.b - layout(sig).h;
      d.elements.push(...els, {id: uid(), type: "rect", name: "Rule", x: m, y: sig.y - 26, w: W, h: format === "916" ? 6 : 5, fill: dark}, sig);
      return d;
    }
    if (kind === "field") {
      const poem = {id: uid(), type: "text", name: "Poem", text, font: "Archivo", weight: 700, size: 100, leading: 1.3, tracking: 0, color: light, align: "right", x: 0, y: 0};
      await fitWidth(poem, F.w * .5);
      const L = layout(poem), axis = Math.round(F.w * .62);
      poem.x = axis - 28 - L.w;
      poem.y = S.t + (F.h - S.t - S.b - L.h) / 2;
      const sig = name({color: dark, x: axis + 28, size: format === "916" ? 30 : 26});
      await loadMetrics([mkey(sig)]);
      sig.y = F.h - S.b - layout(sig).h;
      d.elements.push({id: uid(), type: "rect", name: "Field", x: axis, y: 0, w: F.w - axis, h: F.h, fill: accent}, poem, sig);
      return d;
    }
    return d;
  }

  /* ——— import: turn a rendered slide (the kit's preview page in export mode) into an editable design ——— */
  async function importSlide(win, info) {
    const doc = win.document, sl = doc.querySelector(".slide");
    if (!sl) throw new Error("no slide on the page");
    const cs = (el, p) => win.getComputedStyle(el, p);
    // pseudo-elements (rules, dashes) become real elements so they can be measured
    const PROPS = ["display", "position", "top", "right", "bottom", "left", "width", "height", "margin-top", "margin-right", "margin-bottom", "margin-left",
      "background-color", "border-top-width", "border-top-style", "border-top-color", "border-bottom-width", "border-bottom-style", "border-bottom-color",
      "transform", "transform-origin", "flex-grow", "flex-shrink", "flex-basis", "align-self", "vertical-align", "box-sizing", "font", "color", "letter-spacing", "order"];
    for (const el of [sl, ...sl.querySelectorAll("*")]) for (const ps of ["::before", "::after"]) {
      const c = cs(el, ps).content;
      if (!c || c === "none" || c === "normal") continue;
      const sp = doc.createElement("span");
      for (const p of PROPS) sp.style.setProperty(p, cs(el, ps).getPropertyValue(p));
      try { sp.textContent = c.startsWith('"') ? JSON.parse(c) : ""; } catch { sp.textContent = ""; }
      ps === "::before" ? el.prepend(sp) : el.append(sp);
    }
    const kill = doc.createElement("style"); kill.textContent = "*::before,*::after{content:none!important}"; doc.head.appendChild(kill);

    const base = sl.getBoundingClientRect();
    const hex = c => {
      const m = String(c).match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const [r, g, b, a = 1] = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
      return a === 0 ? null : "#" + [r, g, b].map(v => Math.round(v).toString(16).padStart(2, "0")).join("").toUpperCase();
    };
    const angle = el => { let a = 0; for (let x = el; x && x !== doc.body; x = x.parentElement) { const t = cs(x).transform, m = t && t.match(/matrix\(([^)]+)\)/); if (m) { const [A, B] = m[1].split(",").map(Number); a += Math.atan2(B, A) * 180 / Math.PI; } } return Math.round(a * 100) / 100; };
    const d = {name: info.name, format: info.format, background: hex(cs(sl).backgroundColor) || "#0C0E11", elements: [], source: info.source};
    const out = d.elements;

    for (const el of sl.querySelectorAll("*")) {
      if (el.namespaceURI === "http://www.w3.org/2000/svg") {
        if (el.tagName === "line") {
          const s = cs(el), x = v => el[v].baseVal.value;
          out.push({id: uid(), type: "line", name: "Line", x1: x("x1"), y1: x("y1"), x2: x("x2"), y2: x("y2"), stroke: hex(s.stroke) || "#DA291C", width: parseFloat(s.strokeWidth) || 4});
        }
        continue;
      }
      const s = cs(el);
      if (s.display === "none" || s.visibility === "hidden") continue;
      const bg = hex(s.backgroundColor), r = el.getBoundingClientRect();
      const inName = !!info.signature && (() => { for (let x = el; x && x !== sl; x = x.parentElement) if (x.textContent.trim().toLowerCase() === info.signature.toLowerCase()) return true; return false; })();
      const nm = inName ? {role: "name"} : {};
      if (bg && el.offsetWidth && el.offsetHeight) {
        const rot = angle(el), w = el.offsetWidth, h = el.offsetHeight, cx = r.left + r.width / 2 - base.left, cy = r.top + r.height / 2 - base.top;
        out.push({id: uid(), type: "rect", name: inName ? "Name mark" : rot ? "Band" : w < 60 || h < 12 ? "Mark" : "Field", x: cx - w / 2, y: cy - h / 2, w, h, fill: bg, ...(rot ? {rotation: rot} : {}), ...nm});
      }
      for (const side of ["top", "bottom"]) {
        const bw = parseFloat(s[`border${side[0].toUpperCase() + side.slice(1)}Width`]), col = hex(s[`border${side[0].toUpperCase() + side.slice(1)}Color`]);
        if (bw > 0 && col && s[`border${side[0].toUpperCase() + side.slice(1)}Style`] !== "none")
          out.push({id: uid(), type: "rect", name: inName ? "Name rule" : "Rule", x: r.left - base.left, y: (side === "top" ? r.top : r.bottom - bw) - base.top, w: r.width, h: bw, fill: col, ...nm});
      }
    }
    // text: every run of text, placed by its own origin and baseline
    const texts = [], walker = doc.createTreeWalker(sl, NodeFilter.SHOW_TEXT);
    const nodes = []; for (let t = walker.nextNode(); t; t = walker.nextNode()) if (/\S/.test(t.data) && !t.parentElement.closest("svg")) nodes.push(t);
    for (let node of nodes) {
      const p = node.parentElement, s = cs(p);
      if (s.display === "none" || s.visibility === "hidden" || !hex(s.color)) continue;
      const lead = node.data.match(/^\s*/)[0].length;
      if (lead) node = node.splitText(lead);
      const mk = () => { const m = doc.createElement("x-mk"); m.style.cssText = "display:inline-block;width:0;height:0;vertical-align:baseline;margin:0;padding:0;border:0"; return m; };
      const wrap = doc.createElement("x-run"), m1 = mk(), m2 = mk();
      node.replaceWith(wrap); wrap.append(m1, node, m2);
      const a = m1.getBoundingClientRect(), b = m2.getBoundingClientRect();
      const family = s.fontFamily.split(",")[0].replace(/["']/g, "").trim();
      const size = parseFloat(s.fontSize), ls = s.letterSpacing === "normal" ? 0 : parseFloat(s.letterSpacing);
      const e = {id: uid(), type: "text", text: node.data.replace(/\s+$/, ""), font: family === "Archivo" ? "Archivo" : "Newsreader",
        weight: parseFloat(s.fontWeight) || 400, size, tracking: Math.round(ls / size * 10000) / 10, leading: 1.15, color: hex(s.color)};
      if (e.font === "Archivo") e.stretch = parseFloat(s.fontStretch) || 100; else if (s.fontStyle === "italic") e.italic = true;
      if (s.textTransform === "uppercase") e.case = "upper"; else if (s.textTransform === "lowercase") e.case = "lower";
      if (info.signature && e.text.toLowerCase() === info.signature.toLowerCase()) { e.role = "name"; e.name = "Name"; }
      const rot = Math.round(Math.atan2(b.top - a.top, b.left - a.left) * 180 / Math.PI * 100) / 100;
      texts.push({e, ox: a.left - base.left, oy: a.top - base.top, rot: Math.abs(rot) < .05 ? 0 : rot});
    }
    await loadMetrics(texts.map(t => mkey(t.e)));
    for (const t of texts) {
      const e = t.e, L = layout(e), l = L.lines[0]?.l || 0;
      if (!t.rot) { e.x = t.ox + l; e.y = t.oy - L.capH; }
      else {   // the origin we measured is rotated about the block's centre: undo that
        const v = {x: -l - L.w / 2, y: L.capH / 2}, a = t.rot * Math.PI / 180;
        const c = {x: t.ox - (v.x * Math.cos(a) - v.y * Math.sin(a)), y: t.oy - (v.x * Math.sin(a) + v.y * Math.cos(a))};
        e.x = c.x - L.w / 2; e.y = c.y - L.capH / 2; e.rotation = t.rot;
      }
      e.x = Math.round(e.x * 100) / 100; e.y = Math.round(e.y * 100) / 100;
    }
    // a red full stop right after its line becomes that line's accent
    const merged = [];
    for (const t of texts) {
      const prev = merged.at(-1);
      if (prev && t.e.text === "." && !prev.e.accent && !prev.rot && !t.rot && Math.abs(prev.oy - t.oy) < .6 && t.e.color !== prev.e.color
          && Math.abs(t.ox - (prev.ox + layout(prev.e).lines[0].adv + (prev.e.tracking || 0) / 1000 * prev.e.size)) < .25 * prev.e.size) {
        prev.e.text += "."; prev.e.accent = t.e.color; continue;
      }
      merged.push(t);
    }
    // lines set the same way, on one edge and evenly spaced, become one block
    const same = (a, b) => ["font", "weight", "size", "tracking", "color", "stretch", "italic", "case", "role"].every(k => a[k] === b[k])
      && (!a.accent || !b.accent || a.accent === b.accent);
    const blocks = [];
    for (const t of merged) {
      const g = blocks.at(-1), e = t.e;
      if (g && !t.rot && !g.rot && same(g.items[0].e, e)) {
        const last = g.items.at(-1), gap = t.oy - last.oy, first = g.items.length > 1 ? g.items[1].oy - g.items[0].oy : gap;
        const R = x => x.e.x + layout(x.e).w;
        const edge = Math.abs(e.x - g.items[0].e.x) < .6 ? "left" : Math.abs(R(t) - R(g.items[0])) < .6 ? "right" : null;
        if (gap > 0 && Math.abs(gap - first) < .6 && edge && (!g.edge || g.edge === edge)) { g.items.push(t); g.edge = edge; continue; }
      }
      blocks.push({items: [t], rot: t.rot, edge: null});
    }
    const textEls = blocks.map(g => {
      if (g.items.length === 1) return g.items[0].e;
      const e0 = g.items[0].e, gap = g.items[1].oy - g.items[0].oy;
      const e = {...e0, id: uid(), text: g.items.map(x => x.e.text).join("\n"), leading: Math.round(gap / e0.size * 10000) / 10000};
      const acc = g.items.find(x => x.e.accent)?.e.accent; if (acc) e.accent = acc;
      if (g.edge === "right") { const R = Math.max(...g.items.map(x => x.e.x + layout(x.e).w)); e.align = "right"; e.x = R - layout(e).w; }
      else e.x = Math.min(...g.items.map(x => x.e.x));
      e.y = g.items[0].e.y;
      return e;
    });
    textEls.forEach(e => { if (!e.name) e.name = e.text.split("\n")[0].slice(0, 40); });
    out.push(...textEls);
    return d;
  }

  return {FORMATS, SAFE, WIDTHS, WEIGHTS, LAYOUT, uid, layout, bounds, render, thumb, ready, fitWidth, starter, importSlide, mkey, loadMetrics,
    resolve, shownIn, pickLayout, remapLayout, mergeFormats, isGrad, cssPaint, stopsOf, firstColor, movePoints, pathD,
    set onMetrics(f) { onMetrics = f; }, get version() { return version; }};
})();
