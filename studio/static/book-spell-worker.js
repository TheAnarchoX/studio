"use strict";
/* The spelling worker: Hunspell (vendor/hunspell.js, WebAssembly) with the dictionaries the book editor asks for, off
   the page's thread, so a long piece is checked without the typing waiting for it (book-spell.js talks to it).
   Messages in and out:
     {type: "load", lang, aff: url, dic: url}           → {type: "loaded", lang} or {type: "error", lang, message}
     {type: "check", id, words: [[word, langs], …]}     → {type: "checked", id, bad: [index, …]}
     {type: "suggest", id, word, langs}                 → {type: "suggested", id, words: [up to five]}
   A word is bad when no listed dictionary accepts it. A language without a working dictionary (never loaded, or its
   files failed) accepts everything: what can't be judged is never underlined.
   A classic worker script; tests/js/spell_worker.js runs it in node in a scope made to look like one. */
importScripts("/static/vendor/hunspell.js");

/* the WebAssembly is compiled once, for every dictionary */
let factory = null;
const hunspell = () => factory || (factory = HunspellAsm.loadModule({timeout: 30000}));
const spellers = new Map();           // lang → a promise of its Hunspell, or of null when it couldn't be loaded

async function bytes(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
}
function load(m) {
  if (spellers.has(m.lang)) return spellers.get(m.lang);
  const p = (async () => {
    const [h, aff, dic] = await Promise.all([hunspell(), bytes(m.aff), bytes(m.dic)]);
    const safe = m.lang.replace(/[^\w-]/g, "_");          // the in-memory file's name
    return h.create(h.mountBuffer(aff, safe + ".aff"), h.mountBuffer(dic, safe + ".dic"));
  })();
  const kept = p.catch(() => null);
  spellers.set(m.lang, kept);
  p.then(() => postMessage({type: "loaded", lang: m.lang}),
    e => { spellers.delete(m.lang); postMessage({type: "error", lang: m.lang, message: String(e && e.message || e)}); });
  return kept;
}
/* The Hunspells of these languages that work, in order. */
async function spellersOf(langs) {
  const out = [];
  for (const l of langs) { const s = await (spellers.get(l) || null); if (s) out.push(s); }
  return out;
}
/* Typographic apostrophes as the dictionaries write them: zo’n is zo'n. */
const plain = w => String(w).replace(/[’‘ʼ]/g, "'");
const accepts = (s, w) => { try { return s.spell(w) || (w !== plain(w) && s.spell(plain(w))); } catch { return true; } };

async function check(m) {
  const sets = new Map(), bad = [];
  for (const [, langs] of m.words) { const k = langs.join("\n"); if (!sets.has(k)) sets.set(k, null); }
  for (const k of sets.keys()) sets.set(k, await spellersOf(k ? k.split("\n") : []));
  m.words.forEach(([word, langs], i) => {
    const ss = sets.get(langs.join("\n"));
    if (ss.length === langs.length && !ss.some(s => accepts(s, word))) bad.push(i);
  });
  postMessage({type: "checked", id: m.id, bad});
}
/* Up to five suggestions, the languages' in turn (the book's own first), each once. */
async function suggest(m) {
  const lists = (await spellersOf(m.langs || [])).map(s => { try { return s.suggest(plain(m.word)); } catch { return []; } });
  const out = [];
  for (let i = 0; out.length < 5 && lists.some(l => i < l.length); i++) {
    for (const l of lists) if (i < l.length && l[i] && !out.includes(l[i]) && out.length < 5) out.push(l[i]);
  }
  postMessage({type: "suggested", id: m.id, words: out});
}

self.onmessage = e => {
  const m = e.data || {};
  if (m.type === "load") load(m);
  else if (m.type === "check") check(m).catch(() => postMessage({type: "checked", id: m.id, bad: []}));
  else if (m.type === "suggest") suggest(m).catch(() => postMessage({type: "suggested", id: m.id, words: []}));
};
