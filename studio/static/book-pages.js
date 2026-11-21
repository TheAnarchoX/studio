"use strict";
/* The page viewer: a book's set pages as images on a desk, in spreads or one page at a time, at a zoom. Used by Compose
   (book-compose.js) and the pages pane beside the text.
   The pages come from GET /api/book/pages (`show(payload)`): each page is an SVG addressed by its hash, so a page that
   didn't change keeps its <img> and is never fetched again, and the images load only as they come near the view.
   Sizes: a page is the payload's `width` × `height` mm; zoom "real" is 96 CSS px per inch of the page, a number is a
   multiple of that (0.25–4), "width" and "page" fit the desk. Spreads put page 1 alone on the right, as a book opens,
   so the spine stays at the centre of the desk on every row.
   A classic script; sets window.BookPages = {mount(el, opts) -> viewer, watchSetting(book, say) -> stop, settingWords}.
     opts: {book, mode: "spreads"|"single", zoom, size?: {width, height}, hint?, onPage(i), onOpen(i, x, y) (double-click),
            onClick(i, x, y), onZoom(z, label), refetch()}; i is 0-based, x and y where on the page, 0–1 from its top left;
            hint is a tooltip for every page; refetch() asks for the pages again (by default the viewer does, for opts.book).
     viewer: show(payload), go(i, {smooth}), setZoom(z), zoomBy(±1 | factor, at?), setMode(mode), current(), mark(i | null),
             message(text) (shown while there are no pages), zoom(), label(), effective() (the zoom on screen as a number),
             mode, count, desk, destroy(). */
(function (root) {
  const PX_MM = 96 / 25.4;                  // CSS px per mm at real size
  const STEPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];
  const MIN = 0.25, MAX = 4;
  // the desk's padding, the space between rows (the same, so a row gone to shows none of the row above), the folio line
  const PAD = 32, GAP = 32, LABEL = 22;
  const PAPER = {white: "#FFFFFF", cream: "#F7F2E6"};
  const pageUrl = h => "/api/book/page?h=" + encodeURIComponent(h);
  const clampZoom = z => Math.min(MAX, Math.max(MIN, z));

  /* the zoom as a word: "Fit width", "Fit page", "Real size" or "150 %" */
  function zoomLabel(z) {
    if (z === "width") return "Fit width";
    if (z === "page") return "Fit page";
    if (z === "real" || z === 1) return "Real size";
    return `${Math.round(z * 100)} %`;
  }

  function mount(el, opts = {}) {
    let mode = opts.mode === "single" ? "single" : "spreads";
    let zoom = opts.zoom ?? "page";
    let size = opts.size?.width && opts.size?.height ? {width: +opts.size.width, height: +opts.size.height} : null;
    let paper = PAPER.white;
    let pages = [], rows = [], slots = [], marked = -1, wanted = -1, last = -1, frame = 0, refetching = 0, dead = false;
    let pw = 0, ph = 0;                     // a page's size on screen, whole CSS px

    el.innerHTML = `<div class="bp-desk" tabindex="0" role="region" aria-label="Pages"><div class="bp-pages"></div><p class="bp-say" hidden></p></div>`;
    const desk = el.querySelector(".bp-desk"), host = desk.querySelector(".bp-pages"), say = desk.querySelector(".bp-say");

    /* images load when their page comes within a screen of the view */
    const io = new IntersectionObserver(entries => {
      for (const e of entries) if (e.isIntersecting) load(slots[+e.target.dataset.i]);
    }, {root: desk, rootMargin: "100% 50%"});

    function load(s) {
      if (!s || s.loaded === s.hash || !s.hash) return;
      // after a failure the address differs, so the browser asks again instead of remembering the failure
      const url = pageUrl(s.hash) + (s.tries ? `&try=${s.tries}` : "");
      if (!s.loaded) { s.img.src = url; s.loaded = s.hash; return; }
      // a page that changed: the new image is decoded before it takes the old one's place, so nothing flashes
      const want = s.hash, next = new Image();
      next.src = url;
      next.decode().catch(() => {}).then(() => { if (s.hash === want && !dead) { s.img.src = url; s.loaded = want; } });
      s.loaded = want;
    }

    /* A page image that can't be had (the server forgot it, after a restart): the pages are asked for again, once. */
    function missing() {
      if (dead || refetching) return;
      refetching = 1;
      Promise.resolve(opts.refetch ? opts.refetch() : api("/api/book/pages?b=" + encodeURIComponent(opts.book?.id || "")).then(show))
        .catch(() => {}).finally(() => { setTimeout(() => { refetching = 0; }, 5000); });
    }

    function newImg() {
      const img = document.createElement("img");
      img.decoding = "async"; img.loading = "lazy"; img.draggable = false;
      img.addEventListener("error", () => {
        if (!img.getAttribute("src")) return;
        const s = slots.find(x => x && x.img === img);
        if (s) s.failed = true;
        missing();
      });
      return img;
    }

    /* the rows: spreads are [-1, 0], [1, 2], [3, 4] …; single pages one per row */
    function layoutRows(n) {
      const out = [];
      if (mode === "single") for (let i = 0; i < n; i++) out.push([i]);
      else for (let i = -1; i < n; i += 2) out.push([i, i + 1 < n ? i + 1 : -1]);
      return out;
    }

    /* builds the rows again (the number of pages or the mode changed); images with an unchanged hash move along */
    function build() {
      const keep = new Map();
      for (const s of slots) if (s && s.img && s.loaded && !s.failed) { const k = keep.get(s.loaded) || []; k.push(s.img); keep.set(s.loaded, k); }
      io.disconnect();
      host.replaceChildren();
      rows = layoutRows(pages.length);
      slots = new Array(pages.length);
      rows.forEach((r, k) => {
        const row = document.createElement("div");
        row.className = "bp-row" + (mode === "spreads" ? " spread" : "") + (mode === "spreads" ? (r[0] < 0 ? " r" : r[1] < 0 ? " l" : " lr") : "");
        row.dataset.row = k;
        for (const i of r) {
          const slot = document.createElement("div");
          slot.className = "bp-slot";
          if (i < 0) { slot.classList.add("none"); row.append(slot); continue; }
          const p = pages[i], reuse = keep.get(p.hash)?.pop();
          const page = document.createElement("div");
          page.className = "bp-page";
          page.dataset.i = i;
          if (opts.hint) page.title = opts.hint;
          const img = reuse || newImg();
          img.alt = `Page ${p.folio || i + 1}`;
          const label = document.createElement("span");
          label.className = "bp-folio" + (p.shown ? "" : " quiet");
          label.textContent = p.folio || "";
          page.append(img);
          slot.append(page, label);
          row.append(slot);
          slots[i] = {i, el: page, img, label, hash: p.hash, loaded: reuse ? p.hash : null};
          io.observe(page);
        }
        host.append(row);
      });
      if (marked >= 0) slots[marked]?.el.classList.add("mark");
    }

    /* the page size on screen for the zoom, and the zoom that gives it */
    function measure() {
      if (!size) return;
      const cols = mode === "spreads" ? 2 : 1;
      const real = size.width * PX_MM;
      const availW = Math.max(40, desk.clientWidth - 2 * PAD), availH = Math.max(40, desk.clientHeight - 2 * PAD - LABEL);
      let w;
      if (zoom === "width") w = availW / cols;
      else if (zoom === "page") w = Math.min(availW / cols, availH * size.width / size.height);
      else if (zoom === "real") w = real;
      else w = real * clampZoom(+zoom || 1);
      const was = pw;
      pw = Math.max(24, zoom === "width" || zoom === "page" ? Math.floor(w) : Math.round(w));      // a fit never overflows by a rounding
      ph = Math.round(pw * size.height / size.width);
      if (pw !== was) opts.onZoom?.(zoom, zoomLabel(zoom));        // a fit's percentage follows the desk and the page size
      host.style.setProperty("--bp-pw", pw + "px");
      host.style.setProperty("--bp-ph", ph + "px");
      // centred in a desk of odd width, the pages would sit on half pixels and their edges blur: the column they are
      // centred in is made a pixel narrower when that is so
      const spare = desk.clientWidth - cols * pw;
      host.style.minWidth = spare > 0 ? desk.clientWidth - (spare % 2) + "px" : "";
    }
    const effective = () => size ? pw / (size.width * PX_MM) : 1;

    function place() {
      host.style.setProperty("--bp-pad", PAD + "px");
      host.style.setProperty("--bp-gap", GAP + "px");
      host.style.setProperty("--bp-label", LABEL + "px");
      host.style.setProperty("--bp-paper", paper);
    }

    /* Shows a set of pages. Unchanged pages keep their image; changed ones load again when in view. */
    function show(payload) {
      if (dead || !payload) return;
      if (payload.width && payload.height) size = {width: +payload.width, height: +payload.height};
      paper = PAPER[payload.paper] || PAPER.white;
      const next = payload.pages || [];
      const at = current();
      const same = next.length === pages.length && rows.length === layoutRows(next.length).length && slots.length === next.length;
      pages = next;
      place();
      if (!same) build();
      else {
        for (const s of slots) {
          const p = pages[s.i];
          s.img.alt = `Page ${p.folio || s.i + 1}`;
          s.label.textContent = p.folio || "";
          s.label.classList.toggle("quiet", !p.shown);
          if (s.failed) {                   // asked for again, now that the server has the pages
            s.failed = false; s.tries = (s.tries || 0) + 1; s.loaded = null; s.hash = p.hash;
            s.img.removeAttribute("src"); io.unobserve(s.el); io.observe(s.el);
          } else if (s.hash !== p.hash) {
            s.hash = p.hash;
            if (s.loaded) {                 // on screen or near it: loaded again now; further off, when it comes near
              const r = s.el.getBoundingClientRect(), d = desk.getBoundingClientRect();
              if (r.bottom > d.top - d.height && r.top < d.bottom + d.height) load(s);
              else { s.loaded = null; s.img.removeAttribute("src"); io.unobserve(s.el); io.observe(s.el); }
            }
          }
        }
      }
      say.hidden = !!pages.length;
      measure();
      if (!same && pages.length) go(Math.min(Math.max(0, wanted >= 0 ? wanted : at), pages.length - 1));
      wanted = -1;
      changed();
    }

    /* scrolls page i into view: its row's top at the desk's padding, the page itself in view across */
    function go(i, {smooth = false} = {}) {
      if (!pages.length) { wanted = i; return; }
      i = Math.max(0, Math.min(pages.length - 1, i | 0));
      const s = slots[i];
      if (!s) return;
      last = i;
      const row = s.el.closest(".bp-row"), d = desk.getBoundingClientRect(), r = s.el.getBoundingClientRect();
      const top = desk.scrollTop + row.getBoundingClientRect().top - d.top - PAD;
      let left = desk.scrollLeft;
      if (r.left < d.left || r.right > d.right) left = desk.scrollLeft + r.left - d.left - (d.width - r.width) / 2;
      desk.scrollTo({top, left, behavior: smooth && !reduced() ? "smooth" : "auto"});
      changed(true);
    }
    const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* the page in view: the row across the desk's upper middle; in a spread its right-hand page, unless the page last
       gone to is the other one */
    function current() {
      if (!pages.length || !rows.length) return Math.max(0, last);
      const d = desk.getBoundingClientRect(), y = d.top + Math.min(d.height * 0.4, PAD + ph / 2);
      // at the end of the book the last rows can't scroll up to the reading line: the page gone to counts while in view
      if (last >= 0 && slots[last] && desk.scrollTop + desk.clientHeight >= desk.scrollHeight - 2) {
        const r = slots[last].el.getBoundingClientRect();
        if (r.bottom > d.top && r.top < d.bottom) return last;
      }
      let k = 0;
      const els = host.children;
      for (let j = 0; j < els.length; j++) {
        const r = els[j].getBoundingClientRect();
        if (r.top <= y) k = j; else break;
      }
      const row = rows[k] || [];
      if (row.includes(last)) return last;
      return row[1] >= 0 ? row[1] : row[0] >= 0 ? row[0] : 0;
    }

    /* The pages within a screen of the view load now. The observer does this as the desk scrolls; this covers pages
       made or moved without a scroll (rows built again, a zoom), whose first notice the observer can be slow to give. */
    function fill() {
      const d = desk.getBoundingClientRect(), lo = d.top - d.height, hi = d.bottom + d.height;
      for (const row of host.children) {
        const r = row.getBoundingClientRect();
        if (r.bottom < lo) continue;
        if (r.top > hi) break;
        for (const page of row.querySelectorAll(".bp-page")) load(slots[+page.dataset.i]);
      }
    }

    function changed(now) {
      if (frame) cancelAnimationFrame(frame);
      const run = () => {
        frame = 0;
        fill();
        const i = current();
        if (i !== changed.was) { changed.was = i; opts.onPage?.(i); }
      };
      if (now) run(); else frame = requestAnimationFrame(run);
    }

    /* a new zoom, keeping the point at (clientX, clientY), or the desk's centre, where it is */
    function setZoom(z, at) {
      if (z !== "width" && z !== "page" && z !== "real") z = clampZoom(+z || 1);
      if (z === 1) z = "real";
      const anchor = anchorAt(at);
      zoom = z;
      measure();
      if (anchor) restore(anchor);
      opts.onZoom?.(zoom, zoomLabel(zoom));
      changed();
    }
    function anchorAt(at) {
      if (!pages.length) return null;
      const d = desk.getBoundingClientRect();
      const x = at?.x ?? d.left + d.width / 2, y = at?.y ?? d.top + Math.min(d.height / 2, PAD + ph / 2);
      let best = null, dist = Infinity;
      for (const s of slots) {
        if (!s) continue;
        const r = s.el.getBoundingClientRect();
        const dx = x < r.left ? r.left - x : x > r.right ? x - r.right : 0, dy = y < r.top ? r.top - y : y > r.bottom ? y - r.bottom : 0;
        const dd = dx * dx + dy * dy;
        if (dd < dist) { dist = dd; best = {s, fx: (x - r.left) / r.width, fy: (y - r.top) / r.height, x, y}; }
        if (!dd) break;
      }
      return best;
    }
    function restore(a) {
      const r = a.s.el.getBoundingClientRect();
      desk.scrollLeft += r.left + a.fx * r.width - a.x;
      desk.scrollTop += r.top + a.fy * r.height - a.y;
    }
    /* one step in or out of STEPS (dir ±1), or a factor (a wheel's), from the zoom as it is on screen */
    function zoomBy(step, at) {
      const now = effective();
      let z;
      if (step === 1 || step === -1) {
        z = step > 0 ? STEPS.find(s => s > now + 1e-3) ?? MAX : [...STEPS].reverse().find(s => s < now - 1e-3) ?? MIN;
      } else z = clampZoom(now * step);
      setZoom(Math.round(z * 1000) / 1000, at);
    }

    function setMode(m) {
      m = m === "single" ? "single" : "spreads";
      if (m === mode) return;
      const i = current();
      mode = m;
      build();
      measure();
      go(i);
    }

    function mark(i) {
      slots[marked]?.el.classList.remove("mark");
      marked = i == null ? -1 : i;
      slots[marked]?.el.classList.add("mark");
    }

    /* where on a page a pointer is: the page's index, and x and y from its top left, 0–1 */
    function hit(e) {
      const page = e.target.closest?.(".bp-page");
      if (!page || !host.contains(page)) return null;
      const r = page.getBoundingClientRect();
      return [+page.dataset.i, Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
    }

    desk.addEventListener("scroll", () => changed(), {passive: true});
    desk.addEventListener("dblclick", e => { const h = hit(e); if (h) { e.preventDefault(); opts.onOpen?.(...h); } });
    desk.addEventListener("click", e => { const h = hit(e); if (h) opts.onClick?.(...h); });
    /* Ctrl+wheel zooms about the pointer (the browser's own page zoom stays out of it) */
    desk.addEventListener("wheel", e => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      zoomBy(Math.exp(-dy * 0.002), {x: e.clientX, y: e.clientY});
    }, {passive: false});
    const ro = new ResizeObserver(() => {           // a fit follows the desk's size; any zoom keeps its pixels whole
      const a = anchorAt();
      measure();
      if (a) restore(a);
      changed();
    });
    ro.observe(desk);

    function destroy() {
      dead = true;
      io.disconnect(); ro.disconnect();
      if (frame) cancelAnimationFrame(frame);
      el.replaceChildren();
    }

    function message(text) { say.textContent = text || ""; say.hidden = !text || !!pages.length; }

    place();
    return {show, go, setZoom, zoomBy, setMode, current, mark, destroy, message, desk,
      zoom: () => zoom, label: () => zoomLabel(zoom), effective, get mode() { return mode; }, get count() { return pages.length; }};
  }

  /* What a wait for the pages is: "Setting the pages…", or, while the faces a new font, weight or size needs are cut for
     print (some 18 s, once), which font. `watchSetting(book, say)` asks the server once a second, after the first
     second, and calls say(words) whenever they change; it returns stop(). The pages request itself waits for the cut,
     so this is a request of its own (GET /api/book/cutting, answered at once). */
  const SETTING = "Setting the pages…";
  const settingWords = families => families?.length
    ? `Preparing ${families.length > 1 ? families.slice(0, -1).join(", ") + " and " + families.at(-1) : families[0]} for print (once)…` : SETTING;
  function watchSetting(book, say) {
    let timer = 0, stopped = false, said = SETTING;
    const ask = async () => {
      try {
        const r = await api("/api/book/cutting?b=" + encodeURIComponent(book));
        const words = settingWords(r?.families);
        if (!stopped && words !== said) { said = words; say(words); }
      } catch { /* the pages request says what went wrong */ }
      if (!stopped) timer = setTimeout(ask, 1000);
    };
    timer = setTimeout(ask, 1000);
    return () => { stopped = true; clearTimeout(timer); };
  }

  root.BookPages = {mount, zoomLabel, STEPS, SETTING, settingWords, watchSetting};
})(typeof window !== "undefined" ? window : globalThis);
