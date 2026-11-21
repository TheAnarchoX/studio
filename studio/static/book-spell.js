"use strict";
/* Spelling in the book's text, in several languages at once. The window's own spell checker (WebView2) knows one
   language for the whole window, so a Dutch book with English words is flagged everywhere; here Studio checks the
   text itself: Hunspell in a worker (book-spell-worker.js) with the bundled dictionaries (Dutch, English, British
   English), and a wavy underline as a decoration on every word none of its languages knows.
   A word is right when any of the book's spelling languages knows it, or it is in the book's word list. Text in a
   lang span is checked in that language only; a language without a dictionary here is left unchecked (and for the
   text's own language, to the window's spelling: book-text.js turns the editor's spellcheck on where covers() is
   false). Notes are checked in their own editors, like the text.
   A classic script after book-tools.js; sets window.BookSpell. The helpers at the top touch no DOM, so
   tests/js/book_spell.js runs them in node. */
(function (root) {
  const wordsIn = text => root.BookTools.wordsIn(text);     // apostrophes inside a word kept, hyphens split

  /* ——— helpers (no DOM) ——— */

  const BUNDLED = new Set(["nl", "en", "en-GB"]);
  const failed = new Set();               // dictionaries that couldn't be loaded here: their languages aren't covered
  /* The bundled dictionary for a language tag: nl for any Dutch, en-GB for British English, en for any other English
     (en-US and en share it); null for every other language. */
  function dictOf(lang) {
    const tag = String(lang || "").trim().toLowerCase().replace(/_/g, "-"), primary = tag.split("-")[0];
    if (primary === "nl") return "nl";
    if (primary === "en") return tag === "en-gb" ? "en-GB" : "en";
    return null;
  }
  /* Whether Studio checks this language itself (so the window's own spelling stays off for it). */
  const covers = lang => { const d = dictOf(lang); return !!d && BUNDLED.has(d) && !failed.has(d); };
  /* The dictionaries for text in these languages, the text's own first: none when its own has no dictionary here (a
     word can't be called wrong without its own language), else every one that has a dictionary, once. */
  function dictsFor(langs) {
    if (!langs || !langs.length || !covers(langs[0])) return [];
    return [...new Set(langs.filter(covers).map(dictOf))];
  }

  /* zo’n and zo'n are one word */
  const plain = w => String(w).replace(/[’‘ʼ]/g, "'");
  /* the book's word list as looked up: each word as written, apostrophes made one kind */
  const wordList = words => new Set((words || []).map(plain));
  /* Words left alone: with a digit (3D, A4), all capitals (NAVO, IJ), a single letter, or in the book's word list as
     written or in lower case. */
  function skipped(w, list) {
    if (/\p{N}/u.test(w)) return true;
    if ((w.match(/\p{L}/gu) || []).length < 2) return true;
    if (w === w.toLocaleUpperCase() && w !== w.toLocaleLowerCase()) return true;
    const p = plain(w);
    return !!list && (list.has(p) || list.has(p.toLocaleLowerCase()));
  }

  /* The text of the textblocks that touch from..to, as runs of one language: [{from, to, lang, dicts, words: [{w, from,
     to}]}] (lang: the lang span's, null for the book's languages), and the range those blocks cover (hull, null when
     there are none). A note or a citation ends a run: a citation shows its key, not text, and a note's text is checked
     in its own editor (a note's editor has the note as its document, and that document is one textblock). */
  function runsIn(doc, from, to, bookLangs) {
    const runs = [];
    let hull = null;
    const block = (node, start) => {
      let run = null;
      const flush = () => {
        if (!run) return;
        run.words = wordsIn(run.text).map(m => ({w: m.w, from: run.from + m.from, to: run.from + m.to}));
        run.to = run.from + run.text.length;
        delete run.text;
        runs.push(run);
        run = null;
      };
      node.forEach((c, off) => {
        if (!c.isText) { flush(); return; }
        const m = c.marks.find(k => k.type.name === "lang" && k.attrs.lang), lang = m ? m.attrs.lang : null;
        if (run && run.lang === lang) run.text += c.text;
        else { flush(); run = {from: start + off, lang, dicts: dictsFor(lang ? [lang] : bookLangs), text: c.text}; }
      });
      flush();
      const a = start - (node === doc ? 0 : 1), z = node === doc ? doc.content.size : a + node.nodeSize;
      hull = hull ? {from: Math.min(hull.from, a), to: Math.max(hull.to, z)} : {from: a, to: z};
    };
    if (doc.inlineContent) block(doc, 0);
    else doc.nodesBetween(Math.max(0, from), Math.min(doc.content.size, to), (n, pos) => {
      if (n.inlineContent) { block(n, pos + 1); return false; }
      return !n.isInline;
    });
    return {runs, hull};
  }
  /* The words to look up: each with its dictionaries; none in a run nobody here can check, none skipped or ignored. */
  function wordsToCheck(runs, list, ignored) {
    const out = [];
    for (const r of runs) {
      if (!r.dicts.length) continue;
      for (const w of r.words) if (!skipped(w.w, list) && !(ignored && ignored.has(plain(w.w)))) out.push({...w, dicts: r.dicts});
    }
    return out;
  }

  const helpers = {dictOf, covers, dictsFor, plain, wordList, skipped, runsIn, wordsToCheck};
  if (typeof document === "undefined") { root.BookSpell = helpers; return; }          // node: the helpers only

  /* ——— the worker: one for the window, started when a book's text first needs it ——— */
  const {Plugin, PluginKey, Decoration, DecorationSet} = root.PM;
  const DELAY = 300;                      // ms after typing stops before the changed blocks are checked
  const SLICE = 12000;                    // positions of text checked in one turn (some 2,500 words, about 10 ms)
  let worker = null, seq = 0, broken = false;
  const waiting = new Map();              // id → resolve
  const loading = new Set();              // the dictionaries asked for (the worker holds checks until they are in)
  const known = new Map();                // dicts + "\n" + word → true when right
  const asked = new Map();                // the same key → the promise of the check under way
  const suggestions = new Map();          // the same key → [words]
  const suggesting = new Map();           // the same key → the promise of them
  const ignored = new Set();              // Ignore: for this session
  let B = null;                           // the book: {id, langs, words, list}
  const live = new Set();                 // the checkers of the open texts and notes

  function start() {
    if (worker || broken) return worker;
    try {
      worker = new Worker("/static/book-spell-worker.js");
    } catch (e) { giveUp(); return null; }
    worker.onmessage = e => {
      const m = e.data || {};
      if (m.type === "error") { failed.add(m.lang); handBack(); return; }       // its language is left to the window
      if (m.type === "loaded") return;
      const resolve = waiting.get(m.id);
      if (resolve) { waiting.delete(m.id); resolve(m); }
    };
    worker.onerror = e => { e.preventDefault?.(); giveUp(); };
    return worker;
  }
  /* The worker can't run (no WebAssembly, the script failed): no dictionary is covered, the window's spelling is back. */
  function giveUp() {
    broken = true;
    worker?.terminate?.();
    worker = null;
    BUNDLED.forEach(d => failed.add(d));
    for (const [, resolve] of waiting) resolve({bad: [], words: []});
    waiting.clear();
    handBack();
  }
  /* A dictionary that can't be used: its underlines go, and the editors ask covers() again now (book-text.js sets their
     spellcheck from it on every update), so the window's own spelling is back at once. */
  function handBack() {
    recheckAll();
    for (const c of live) if (!c.view.isDestroyed) c.view.setProps({});
  }
  function ask(msg) {
    const w = start();
    if (!w) return Promise.resolve({bad: [], words: []});
    const id = ++seq;
    return new Promise(resolve => { waiting.set(id, resolve); w.postMessage({...msg, id}); });
  }
  /* loads a dictionary once (the worker answers checks for it after it is in) */
  function ensure(d) {
    if (!d || loading.has(d) || failed.has(d)) return;
    const w = start();
    if (!w) return;
    loading.add(d);
    w.postMessage({type: "load", lang: d, aff: `/static/dictionaries/${d}/index.aff`, dic: `/static/dictionaries/${d}/index.dic`});
  }
  const keyOf = (dicts, w) => dicts.join(",") + "\n" + plain(w);
  /* Looks up the words not known yet; a promise when there were any (null when every one is known). */
  function lookUp(words) {
    const fresh = new Map(), under = new Set();
    for (const w of words) {
      const k = w.key || keyOf(w.dicts, w.w);
      if (known.has(k)) continue;
      if (asked.has(k)) under.add(asked.get(k));
      else if (!fresh.has(k)) fresh.set(k, [plain(w.w), w.dicts]);
    }
    if (fresh.size) {
      const keys = [...fresh.keys()], list = [...fresh.values()];
      list.forEach(([, dicts]) => dicts.forEach(ensure));
      const p = ask({type: "check", words: list}).then(r => {
        const bad = new Set(r.bad || []);
        keys.forEach((k, i) => { known.set(k, !bad.has(i)); asked.delete(k); });
      });
      keys.forEach(k => asked.set(k, p));
      under.add(p);
    }
    return under.size ? Promise.all(under) : null;
  }

  /* ——— the book ——— */
  /* The open book (GET /api/book's reply; book.js calls this when a book is shown or read again): its spelling
     languages and word list. Its dictionaries load now; a change of languages or words checks every open text again. */
  function setBook(book) {
    if (!book) return;
    const sp = book.spelling || {}, langs = sp.languages && sp.languages.length ? sp.languages : [book.language || "en"];
    const stored = Array.isArray(sp.words) ? sp.words : [];
    const words = [...stored, ...[...adding].filter(([w, id]) => id === book.id && !stored.includes(w)).map(([w]) => w)];
    const changed = !B || B.id !== book.id || JSON.stringify(B.langs) !== JSON.stringify(langs) || JSON.stringify(B.words) !== JSON.stringify(words);
    B = {id: book.id, langs, words, list: wordList(words)};
    dictsFor(langs).forEach(ensure);
    if (changed) recheckAll();
  }
  function recheckAll() { for (const c of live) { c.all = true; c.schedule(0); } }

  /* ——— the plugin: decorations mapped through changes, the changed blocks checked when typing stops ——— */
  const KEY = new PluginKey("bk-spell");
  const union = (a, b) => !a ? b : !b ? a : {from: Math.min(a.from, b.from), to: Math.max(a.to, b.to)};
  function plugins(T) {
    return [new Plugin({
      key: KEY,
      state: {
        init: () => ({set: DecorationSet.empty, dirty: null, held: null}),
        apply(tr, s) {
          const m = tr.getMeta(KEY);
          if (m) return m;
          if (!tr.docChanged) return s;
          let set = s.set.map(tr.mapping, tr.doc), dirty = s.dirty, held = s.held;
          const map = r => r && {from: tr.mapping.map(r.from, -1), to: tr.mapping.map(r.to, 1)};
          dirty = map(dirty); held = map(held);
          tr.mapping.maps.forEach((sm, i) => sm.forEach((a, b, na, nb) => {
            const rest = tr.mapping.slice(i + 1), r = {from: rest.map(na, -1), to: rest.map(nb, 1)};
            dirty = union(dirty, r);
            set = set.remove(set.find(r.from, r.to, spec => spec.word != null));    // no underline under what is being typed
          }));
          return {set, dirty, held};
        },
      },
      props: {
        decorations: state => KEY.getState(state).set,
        handleDOMEvents: {
          contextmenu: (view, e) => menu(T, view, e),
          blur: view => { if (KEY.getState(view.state).held) checkers.get(view)?.schedule(0); return false; },
          // the pointer resting on an underlined word: its suggestions are looked for now, so a right-click finds them
          mouseover: (view, e) => { prefetch(view, e.target); return false; },
        },
      },
      view: view => new Checker(T, view),
    })];
  }
  const checkers = new WeakMap();         // view → its checker

  /* one per editor (the text, each note): checks what changed a moment after typing stops */
  class Checker {
    constructor(T, view) {
      Object.assign(this, {T, view, timer: 0, all: true, gone: false});
      live.add(this);
      checkers.set(view, this);
      this.schedule(0);
    }
    update(view, prev) {
      this.view = view;
      const s = KEY.getState(view.state);
      if (view.state.doc !== prev.doc) this.schedule(DELAY);
      // the word that was being typed is checked once the cursor leaves it
      else if (s.held && !view.state.selection.eq(prev.selection)) {
        const h = view.state.selection.head;
        if (h < s.held.from || h > s.held.to || !view.hasFocus()) this.schedule(0);
      }
    }
    destroy() { this.gone = true; clearTimeout(this.timer); live.delete(this); }
    schedule(ms) { clearTimeout(this.timer); this.timer = setTimeout(() => this.run(), ms); }
    /* Checks what is left to check (the changed blocks, the word the cursor left, or the whole text), a slice at a time:
       the rest waits for the next turn (or, while typing goes on, until it stops), so typing never waits for a long text. */
    run() {
      const view = this.view;
      if (this.gone || !B) return;
      const state = view.state, s = KEY.getState(state), doc = state.doc;
      const range = this.all ? {from: 0, to: doc.content.size} : union(s.dirty, s.held);
      if (!range) return;
      // a block that only touches the change (a split, a join) is checked too
      const end = Math.min(range.to, range.from + SLICE);
      const {runs, hull} = runsIn(doc, range.from - 1, end + 1, B.langs);
      const words = wordsToCheck(runs, B.list, ignored);
      words.forEach(w => { w.key = keyOf(w.dicts, w.w); });
      const pending = lookUp(words);
      if (pending) { pending.then(() => this.schedule(0)); return; }
      // the word being typed (the cursor in it or at its end, and it changed since the last check, or was waiting
      // already) waits until the cursor leaves it, as the familiar checkers do
      const sel = state.selection, typing = view.hasFocus() && sel.empty && !this.all;
      const touches = (w, r) => r && w.from <= r.to && w.to >= r.from;
      let held = null;
      const out = [];
      for (const w of words) {
        if (known.get(w.key) !== false) continue;
        if (typing && w.from < sel.head && sel.head <= w.to && (touches(w, s.dirty) || touches(w, s.held))) { held = {from: w.from, to: w.to}; continue; }
        out.push(Decoration.inline(w.from, w.to, {class: "bk-spell"}, {word: w.w, dicts: w.dicts}));
      }
      // a span Studio checks in a text the window checks: the window's spelling stays off inside it
      if (!covers(this.T.lang)) for (const r of runs) if (r.lang && r.dicts.length && r.to > r.from) out.push(Decoration.inline(r.from, r.to, {spellcheck: "false"}));
      const done = hull ? Math.max(hull.to, end) : end, rest = done < range.to ? {from: done, to: range.to} : null;
      if (!held && s.held && hull && (s.held.to < hull.from || s.held.from > hull.to)) held = s.held;     // not in this slice
      const set = hull ? s.set.remove(s.set.find(hull.from, hull.to)).add(doc, out) : s.set;
      this.all = false;
      if (set !== s.set || JSON.stringify([rest, held]) !== JSON.stringify([s.dirty, s.held])) {
        view.dispatch(state.tr.setMeta(KEY, {set, dirty: rest, held}).setMeta("addToHistory", false));
      }
      if (rest) this.schedule(0);
    }
  }

  /* ——— right-click on an underlined word: suggestions, the book's word list, Ignore ——— */
  function decoAt(view, pos) {
    const s = KEY.getState(view.state);
    return s && s.set.find(pos, pos, spec => spec.word != null).find(d => d.from <= pos && pos <= d.to) || null;
  }
  /* A word's suggestions, asked of the worker once: a promise of up to five, with the text's kind of apostrophe. */
  function suggestFor(word, dicts) {
    const k = keyOf(dicts, word);
    if (!suggesting.has(k)) suggesting.set(k, ask({type: "suggest", word: plain(word), langs: dicts}).then(r => {
      const list = (r.words || []).map(s => word.includes("’") || !word.includes("'") ? s.replace(/'/g, "’") : s);
      suggestions.set(k, list);
      return list;
    }));
    return suggesting.get(k);
  }
  /* The pointer resting on an underlined word for a moment: its suggestions (half a second in Dutch) are looked for now,
     so the right-click menu opens with them. Passing over words asks nothing. */
  let restTimer = 0;
  function prefetch(view, target) {
    clearTimeout(restTimer);
    const el = target && target.closest ? target.closest(".bk-spell") : null;
    if (!el || !view.dom.contains(el)) return;
    restTimer = setTimeout(() => {
      if (view.isDestroyed || !el.isConnected) return;
      let pos;
      try { pos = view.posAtDOM(el, 0); } catch { return; }
      const d = decoAt(view, pos);
      if (d) suggestFor(d.spec.word, d.spec.dicts);
    }, 250);
  }
  function menu(T, view, e) {
    if (typeof StudioMenu === "undefined") return false;
    const at = view.posAtCoords({left: e.clientX, top: e.clientY}), d = at && decoAt(view, at.pos);
    if (!d) return false;
    const {word, dicts} = d.spec, place = {from: d.from, to: d.to}, pick = s => () => replace(T, view, place, word, s);
    const list = suggestions.get(keyOf(dicts, word));
    const rows = list == null ? [{label: "Looking for suggestions…", disabled: true}]
      : list.length ? list.map(s => ({label: s, act: pick(s)})) : [{label: "No suggestions", disabled: true}];
    StudioMenu.open(e, [...rows, "-", {label: "Add to this book's words", act: () => addWord(word), disabled: !B}, {label: "Ignore", act: () => ignore(word)}]);
    if (list == null) {
      const m = [...document.querySelectorAll("body > .ctx:not(.sub)")].pop(), wait = m && m.querySelector("button[disabled]");
      suggestFor(word, dicts).then(found => { if (m && m.isConnected && wait && wait.isConnected) fillIn(m, wait, found, pick); });
    }
    return true;
  }
  /* The suggestions in place of "Looking for suggestions…" in the open menu, which grows upwards by their height: Add and
     Ignore stay where they are under the pointer, and the focus stays where it is. */
  function fillIn(m, wait, found, pick) {
    if (!found.length) { wait.querySelector(".lb").textContent = "No suggestions"; return; }
    const before = m.offsetHeight;
    wait.replaceWith(...found.map(s => {
      const b = document.createElement("button");
      b.setAttribute("role", "menuitem");
      b.innerHTML = `<span class="ck"></span><span class="lb"></span><span class="kb"></span>`;
      b.querySelector(".lb").textContent = s;
      b.onclick = ev => { ev.stopPropagation(); StudioMenu.close(); pick(s)(); };
      return b;
    }));
    m.style.top = Math.max(4, (parseFloat(m.style.top) || 0) - (m.offsetHeight - before)) + "px";
  }
  /* The suggestion in place of the word, in one step (undone in one). The word is found by its text where it was
     right-clicked, not by its underline: a re-check while the menu is open makes new underlines. If the text there
     changed meanwhile, the nearest underline of the same word is used. */
  function replace(T, view, place, word, s) {
    if (T.locked || T.destroyed || view.isDestroyed) return;
    const doc = view.state.doc, holds = r => r && r.to <= doc.content.size && doc.textBetween(r.from, r.to) === word ? r : null;
    let r = holds(place);
    if (!r) {
      const near = KEY.getState(view.state).set.find(undefined, undefined, spec => spec.word === word)
        .sort((a, b) => Math.abs(a.from - place.from) - Math.abs(b.from - place.from))[0];
      r = near && holds({from: near.from, to: near.to});
    }
    if (!r) { T.ctx?.say?.(`“${word}” changed meanwhile. Right-click it again.`, true); return; }
    view.dispatch(view.state.tr.insertText(s, r.from, r.to).scrollIntoView());
    view.focus();
  }
  function ignore(word) { ignored.add(plain(word)); recheckAll(); }
  /* The word goes into book.json's word list (POST /api/book/update); its underline goes at once. One add at a time,
     each to the list as it is on disk just before (another window or the settings may have changed it). */
  const adding = new Map();               // word → book: on its way to book.json, kept in the list whatever setBook brings
  let addQueue = Promise.resolve();
  function addWord(word) {
    if (!B || B.list.has(plain(word))) return addQueue;
    const id = B.id;
    adding.set(word, id);
    B = {...B, words: [...B.words, word], list: wordList([...B.words, word])};
    recheckAll();
    return addQueue = addQueue.then(async () => {
      try {
        const now = (await root.api("/api/book?b=" + encodeURIComponent(id))).spelling?.words || [];
        const r = await root.api("/api/book/update", {b: id, fields: {spelling: {words: now.includes(word) ? now : [...now, word]}}});
        adding.delete(word);
        if (B && B.id === r.id) setBook(r);
      } catch (err) {
        adding.delete(word);
        if (B && B.id === id) { B = {...B, words: B.words.filter(w => w !== word)}; B.list = wordList(B.words); recheckAll(); }
        root.toast?.(err.message, true);
      }
    });
  }

  root.BookSpell = {...helpers, setBook, plugins, menu, get book() { return B; }};
})(typeof window !== "undefined" ? window : globalThis);
