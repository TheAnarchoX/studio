"use strict";
/* The writing window's tools (book-editor.js tells them what happens through BookTools.on): the writing tools in the
   status bar (read aloud, echoes, sentence rhythm, the daily goal line), the style sheet's marks in the text, the
   highlights of find and replace, focus mode with typewriter scrolling, a second pane (split view) and the command
   palette (Ctrl+K). The rail's panels are book-rail.js.
   A classic script after book-editor.js; sets window.BookTools. The helpers at the top touch no DOM, so
   tests/js/book_tools.js runs them in node. */
(function (root) {
  const BT = root.BookText;
  const {Plugin, PluginKey, Decoration, DecorationSet, NodeSelection, TextSelection} = root.PM;
  const GAP = "￼";             // an inline node that isn't text (a note, a citation), as the server's search writes it

  /* ——— helpers (no DOM) ——— */

  const squash = s => String(s ?? "").replace(/\s+/g, " ").trim();
  const primary = lang => String(lang || "").toLowerCase().split(/[-_]/)[0];
  /* without accents, lower case: Één → een (a precomposed letter stays one character) */
  const fold = s => String(s ?? "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
  const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  /* a whole word as the server's search has it (Python's \w: letters, digits, the underscore) */
  const NOT_WORD_BEFORE = "(?<![\\p{L}\\p{N}\\p{M}_])", NOT_WORD_AFTER = "(?![\\p{L}\\p{N}\\p{M}_])";

  /* Words: runs of letters and digits; an apostrophe inside a word belongs to it (zo’n, auto's), a hyphen splits. */
  function wordsIn(text) {
    const out = [];
    for (const m of String(text).matchAll(/[\p{L}\p{M}\p{N}]+(?:['’][\p{L}\p{M}\p{N}]+)*/gu)) out.push({w: m[0], from: m.index, to: m.index + m[0].length});
    return out;
  }

  /* Echoes: a word of five letters or more that comes back, in any case, within the next 150 words. Both are marked.
     Short common words that only hold a sentence together are left out (their repeats are noise, not echoes):
       nl: alles allemaal ander andere anders achter boven daarna daarom deden doordat echter eigen elkaar enkele hadden
           hebben hebt heeft hoewel iemand kunnen konden meeste moest moeten mochten mogen naast nadat niemand niets omdat
           onder tegen terwijl tussen totdat voordat waarom waren welke werden wilde willen worden wordt zelfs zichzelf
           zoals zonder zouden
       en: about above after again against along among another anything around because before behind being below
           between could doing during either every having herself himself itself might myself other others ourselves
           should since their theirs themselves there these those though through under until where whether which while
           within without would yourself yourselves */
  const ECHO_STOP = {
    nl: new Set(("alles allemaal ander andere anders achter boven daarna daarom deden doordat echter eigen elkaar enkele hadden hebben hebt "
      + "heeft hoewel iemand kunnen konden meeste moest moeten mochten mogen naast nadat niemand niets omdat onder tegen terwijl tussen "
      + "totdat voordat waarom waren welke werden wilde willen worden wordt zelfs zichzelf zoals zonder zouden").split(" ")),
    en: new Set(("about above after again against along among another anything around because before behind being below between "
      + "could doing during either every having herself himself itself might myself other others ourselves should since their theirs "
      + "themselves there these those though through under until where whether which while within without would yourself yourselves").split(" ")),
  };
  /* the writing tools in the status bar: [id, label, title] */
  const TOOLS = [
    ["focus", "Focus", "Focus mode: the paragraph you write in, the rest dimmed · Ctrl+Shift+F"],
    ["read", "Read aloud", "Read aloud from the cursor, in the book's language"],
    ["echoes", "Echoes", "Words of five letters or more that come back within 150 words, leaving out short common words"],
    ["rhythm", "Rhythm", "A bar beside each sentence, as long as its words"],
    ["goal", "Goal", "The daily goal as a line along the top of this bar"],
  ];
  const letters = w => (w.match(/\p{L}/gu) || []).length;
  function echoes(words, lang, {span = 150, min = 5} = {}) {
    const stop = ECHO_STOP[primary(lang)] || new Set(), last = new Map(), hit = new Set();
    words.forEach((w, i) => {
      const k = String(w).toLocaleLowerCase().replace(/’/g, "'");
      if (letters(k) < min || stop.has(k)) return;
      const j = last.get(k);
      if (j != null && i - j <= span) { hit.add(j); hit.add(i); }
      last.set(k, i);
    });
    return [...hit].sort((a, b) => a - b);
  }

  /* Numbers as words, in Dutch and English (other languages: null). */
  const NL = ["", "één", "twee", "drie", "vier", "vijf", "zes", "zeven", "acht", "negen", "tien", "elf", "twaalf", "dertien", "veertien",
    "vijftien", "zestien", "zeventien", "achttien", "negentien"];
  const NL_TENS = ["", "", "twintig", "dertig", "veertig", "vijftig", "zestig", "zeventig", "tachtig", "negentig"];
  const EN = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
  const EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
  function numberWord(n, lang) {
    const l = primary(lang);
    if (!Number.isInteger(n) || n < 1 || n > 99 || (l !== "nl" && l !== "en")) return null;
    const t = Math.floor(n / 10), u = n % 10;
    if (l === "nl") {
      if (n < 20) return NL[n];
      if (!u) return NL_TENS[t];
      const unit = u === 1 ? "een" : NL[u];
      return unit + (unit.endsWith("e") ? "ën" : "en") + NL_TENS[t];          // tweeëntwintig, eenentwintig
    }
    return n < 20 ? EN[n] : EN_TENS[t] + (u ? "-" + EN[u] : "");
  }

  /* The style sheet. Each check gives [{from, to, kind, fix, title}] for a block's text. */
  const MONTHS = new Set(("januari februari maart april mei juni juli augustus september oktober november december "
    + "jan feb mrt apr jun jul aug sep sept okt nov dec january february march may june july october").split(" "));
  const REFS = new Set(("p pp blz bladzijde pagina page nr no nos nummer number hoofdstuk hfst ch chapter art artikel fig figuur figure "
    + "tabel table vol deel jaargang editie versie version psalm vers").split(" "));
  const UNITS = new Set("km m cm mm kg g mg l ml cl dl ha procent percent euro eur dollar cent".split(" "));
  const SENTENCE_START = /(?:^|[.!?…]["”’»)\]]*\s+)["“„«‘‚(\[]*$/u;
  const capital = w => w === "één" ? "Eén" : w[0].toLocaleUpperCase() + w.slice(1);
  /* Digits 1 to upto-1 standing alone in prose: not in a date, a time, a decimal, a reference, a measure or a code. */
  function numberIssues(text, lang, upto) {
    const s = String(text), out = [], max = (+upto || 0) - 1;
    if (max < 1 || !numberWord(1, lang)) return out;
    for (const m of s.matchAll(/\d+/g)) {
      const i = m.index, j = i + m[0].length, p1 = s[i - 1] || "", p2 = s[i - 2] || "", n1 = s[j] || "", n2 = s[j + 1] || "";
      if (/[\p{L}\p{N}_#€$£¥§@&+±\-–—/\\^°]/u.test(p1) || (/[.,:]/.test(p1) && /\d/.test(p2))) continue;
      if (/[\p{L}\p{N}_%‰°²³\-–/\\]/u.test(n1) || (/[.,:]/.test(n1) && /\d/.test(n2))) continue;
      const n = +m[0];
      if (m[0][0] === "0" || n > max) continue;
      const before = (/([\p{L}.]+)\s+$/u.exec(s.slice(Math.max(0, i - 24), i)) || [])[1]?.toLowerCase().replace(/\.+$/, "") || "";
      const after = (/^\s+(\p{L}+)/u.exec(s.slice(j, j + 24)) || [])[1]?.toLowerCase() || "";
      if (MONTHS.has(after) || MONTHS.has(before) || REFS.has(before) || UNITS.has(after)) continue;
      const word = SENTENCE_START.test(s.slice(0, i)) ? capital(numberWord(n, lang)) : numberWord(n, lang);
      out.push({from: i, to: j, kind: "number", fix: word, title: `Style sheet: use ${word}`});
    }
    return out;
  }
  /* A term's Not forms, as whole words in any case (a capital at the start stays). When a Not form differs from the
     word to use only in case, case counts. */
  function termIssues(text, terms) {
    const s = String(text), out = [];
    for (const t of terms || []) {
      const use = squash(t && t.use);
      if (!use) continue;
      for (const raw of t.not || []) {
        const form = squash(raw);
        if (!form || form === use) continue;
        const exact = form.toLocaleLowerCase() === use.toLocaleLowerCase();
        const re = new RegExp(NOT_WORD_BEFORE + escRe(form).replace(/ /g, "\\s+") + NOT_WORD_AFTER, exact ? "gu" : "giu");
        for (const m of s.matchAll(re)) {
          if (m[0] === use) continue;
          const fix = !exact && /^\p{Lu}/u.test(m[0]) && /^\p{Ll}/u.test(use) && !/^\p{Lu}/u.test(form) ? capital(use) : use;
          out.push({from: m.index, to: m.index + m[0].length, kind: "term", fix, title: `Style sheet: use ${use}` + (t.note ? ` · ${squash(t.note)}` : "")});
        }
      }
    }
    return out.sort((a, b) => a.from - b.from);
  }
  /* Straight quotes: the style's mark for each (an apostrophe in a word or a clitic like 's avonds is ’). */
  const CLITIC_AFTER = /^(?:s|t|n|k|m|r|ns|em|tis|twas|\d\d)(?=[\s.,;:!?…)\]-]|$)/u;
  function quoteIssues(text, style) {
    const s = String(text), out = [];
    for (let i = 0; i < s.length; i++) {
      const ch = s[i];
      if (ch !== "\"" && ch !== "'") continue;
      const before = s.slice(0, i);
      const fix = ch === "'" && /(^|[\s([{<—–])$/.test(before) && CLITIC_AFTER.test(s.slice(i + 1)) ? "’" : BT.quoteFor(before, ch, style);
      out.push({from: i, to: i + 1, kind: "quote", fix, title: `Style sheet: use ${fix}`});
    }
    return out;
  }
  const UPTO = {"words to ten": 10, "words to hundred": 100};
  /* All of a block's style sheet issues in order; numbers only in prose. `numbersText` is the text with passages in
     another language blanked (their numbers follow that language). */
  function styleIssues(text, sheet, {lang = "en", prose = true, numbersText} = {}) {
    sheet = sheet || {};
    return [...termIssues(text, sheet.terms), ...(prose ? numberIssues(numbersText ?? text, lang, UPTO[sheet.numbers] || 0) : []),
      ...(sheet.quotes ? quoteIssues(text, sheet.quotes) : [])].sort((a, b) => a.from - b.from || a.to - b.to);
  }

  /* Sentences of a block's text with their words: an end mark followed by a lowercase word goes on („Kom je?” vroeg ze),
     and so does a full stop after an abbreviation or an initial. */
  const ABBR = new Set(("bijv bv o.a d.w.z dhr mevr mr mrs ms dr prof nr no p pp blz ca etc e.g i.e vs st jr sr e.a m.a.w enz evt resp "
    + "incl excl vgl zgn t.o.v ir ing drs").split(" "));
  function sentences(text) {
    const s = String(text), out = [];
    let start = 0;
    const push = end => {
      const piece = s.slice(start, end), lead = piece.length - piece.trimStart().length, body = piece.trim();
      if (/[\p{L}\p{N}]/u.test(body)) out.push({from: start + lead, to: start + lead + body.length, words: BT.countWords(body)});
      start = end;
    };
    for (const m of s.matchAll(/[.!?…]+["”’»)\]]*(?=\s|$)/gu)) {
      const end = m.index + m[0].length, next = /^\s*["“„«‘‚(\[]*([\p{L}\p{N}])/u.exec(s.slice(end));
      if (next && /\p{Ll}/u.test(next[1])) continue;
      if (m[0] === ".") {
        const word = (/([\p{L}.]+)$/u.exec(s.slice(start, m.index)) || [])[1]?.toLowerCase() || "";
        if (ABBR.has(word) || /^\p{L}$/u.test(word)) continue;
      }
      push(end);
    }
    push(s.length);
    return out;
  }

  /* Fuzzy matching for the palette: the query's letters in order (accents and case aside), best at word starts and
     side by side. {score, hits} or null. */
  function fuzzy(query, text) {
    const q = [...fold(query).replace(/\s+/g, "")], t = [...fold(text)], n = q.length, m = t.length;
    if (!n) return {score: 0, hits: []};
    if (n > m) return null;
    const NEG = -1e9, start = j => j === 0 || !/[\p{L}\p{N}]/u.test(t[j - 1]), S = [], B = [];
    for (let i = 0; i < n; i++) {
      S.push(new Float64Array(m).fill(NEG)); B.push(new Int32Array(m).fill(-1));
      for (let j = i; j < m; j++) {
        if (t[j] !== q[i]) continue;
        const own = start(j) ? 8 : 1;
        if (i === 0) { S[0][j] = own + (j === 0 ? 4 : 0) - Math.min(j, 10) * 0.1; continue; }
        let best = NEG, arg = -1;
        for (let k = i - 1; k < j; k++) {
          if (S[i - 1][k] === NEG) continue;
          const v = S[i - 1][k] + (k === j - 1 ? 6 : -Math.min(3, (j - k - 1) * 0.25));
          if (v > best) { best = v; arg = k; }
        }
        if (arg >= 0) { S[i][j] = best + own; B[i][j] = arg; }
      }
    }
    let end = -1, best = NEG;
    for (let j = 0; j < m; j++) if (S[n - 1][j] > best) { best = S[n - 1][j]; end = j; }
    if (end < 0) return null;
    const hits = [];
    for (let i = n - 1, j = end; i >= 0; j = B[i][j], i--) hits.unshift(j);
    return {score: best, hits};
  }
  /* the items that match, best first; equal scores: the shorter text, then the order they came in */
  const rank = (items, q, key) => items.map((it, i) => ({it, i, m: fuzzy(q, key(it))})).filter(x => x.m)
    .sort((a, b) => b.m.score - a.m.score || [...key(a.it)].length - [...key(b.it)].length || a.i - b.i).map(x => x.it);

  /* Authors as typed, `Family, Given; Family, Given`, and CSL-JSON names. Lowercase words before the family name (or after
     the given names) are its particle: `van Dijk, Anna` and `Dijk, Anna van` are {family: "Dijk", non-dropping-particle: "van",
     given: "Anna"}. A name without a comma is an organisation: {literal}. */
  const PARTICLE = /^[\p{Ll}'’]/u;
  function parseAuthors(s) {
    return String(s ?? "").split(";").map(squash).filter(Boolean).map(part => {
      const i = part.indexOf(",");
      if (i < 0) return {literal: part};
      const fam = squash(part.slice(0, i)).split(" ").filter(Boolean), given = squash(part.slice(i + 1)).split(" ").filter(Boolean);
      const lead = [], trail = [];
      while (fam.length > 1 && PARTICLE.test(fam[0])) lead.push(fam.shift());
      while (given.length > 1 && PARTICLE.test(given[given.length - 1])) trail.unshift(given.pop());
      const o = {family: fam.join(" ")}, particle = [...lead, ...trail].join(" ");
      if (particle) o["non-dropping-particle"] = particle;
      if (given.length) o.given = given.join(" ");
      return o;
    }).filter(o => o.literal || o.family);
  }
  const formatAuthors = list => (list || []).map(p => !p ? "" : p.literal ? squash(p.literal)
    : [[p["dropping-particle"], p["non-dropping-particle"], p.family].filter(Boolean).join(" "), p.given].filter(Boolean).join(", "))
    .filter(Boolean).join("; ");
  /* A new source's key: the first author's name (with its particle) or the title's first word, and the year; b, c… when taken. */
  const ARTICLES = new Set("de het een the a an".split(" "));
  function sourceKey(item, taken) {
    const p = (item.author && item.author[0]) || (item.editor && item.editor[0]);
    let base = p ? fold([p["non-dropping-particle"], p.family || p.literal || p.given].filter(Boolean).join("")).replace(/[^a-z0-9]/g, "") : "";
    if (!base) base = fold(item.title).split(/[^a-z0-9]+/).find(w => w && !ARTICLES.has(w)) || "";
    const y = item.issued && item.issued["date-parts"] && item.issued["date-parts"][0] && item.issued["date-parts"][0][0];
    base = (base || "source") + (y ? String(y).replace(/\D/g, "") : "");
    let key = base;
    for (let n = 0; taken.has(key); n++) key = base + (n < 25 ? String.fromCharCode(98 + n) : "-" + (n - 23));
    return key;
  }

  /* Find as the server finds (books._pattern, _matches): [[from, to]], never across a note or a line break. */
  function findIn(text, q, {whole = false, case: cs = false} = {}) {
    if (!q) return [];
    const re = new RegExp((whole ? NOT_WORD_BEFORE : "") + escRe(String(q)) + (whole ? NOT_WORD_AFTER : ""), cs ? "gu" : "giu"), out = [];
    for (const m of String(text).matchAll(re)) if (m[0] && !m[0].includes(GAP) && !m[0].includes("\n")) out.push([m.index, m.index + m[0].length]);
    return out;
  }

  /* History: the text of a piece as blocks (document JSON), notes and citations as they read in Markdown. */
  const inlinePlain = content => (content || []).map(n => n.type === "text" ? n.text || "" : n.type === "hard_break" ? "\n"
    : n.type === "note" ? `^[${inlinePlain(n.content)}]`
    : n.type === "cite" ? `[${((n.attrs && n.attrs.items) || []).map(i => [i.prefix, "@" + i.key + (i.locator ? ", " + i.locator : "")].filter(Boolean).join(" ")).join("; ")}]`
    : "").join("");
  function plainBlocks(doc) {
    const out = [];
    const walk = n => {
      const t = n.type, a = n.attrs || {};
      if (t === "title" || t === "heading" || t === "paragraph" || t === "attribution") out.push(inlinePlain(n.content));
      else if (t === "blockquote" || t === "epigraph" || (t === "poem" && !a.src)) (n.content || []).forEach(walk);
      else if (t === "poem") out.push(`Linked poem: ${a.src}`);
      else if (t === "scene_break") out.push("* * *");
      else if (t === "page_break") out.push("Page break");
      else if (t === "image") out.push(`Image: ${a.alt || a.src || ""}`);
    };
    ((doc && doc.content) || []).forEach(walk);
    return out.filter(s => s.trim());
  }
  /* Two versions paragraph by paragraph: = the same, - only in the first, + only in the second, ~ changed (a paragraph
     removed where one was added, compared word by word when shown). */
  function diffBlocks(a, b) {
    let head = 0, tail = 0;
    while (head < a.length && head < b.length && a[head] === b[head]) head++;
    while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail++;
    const A = a.slice(head, a.length - tail), B = b.slice(head, b.length - tail), n = A.length, m = B.length, ops = [];
    const dp = Array.from({length: n + 1}, () => new Int32Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (A[i] === B[j]) { ops.push({t: "=", text: A[i]}); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) ops.push({t: "-", text: A[i++]});
      else ops.push({t: "+", text: B[j++]});
    }
    while (i < n) ops.push({t: "-", text: A[i++]});
    while (j < m) ops.push({t: "+", text: B[j++]});
    const out = a.slice(0, head).map(text => ({t: "=", text}));
    for (let k = 0; k < ops.length;) {
      if (ops[k].t === "=") { out.push(ops[k++]); continue; }
      const del = [], add = [];
      while (k < ops.length && ops[k].t !== "=") (ops[k].t === "-" ? del : add).push(ops[k++].text);
      const pairs = Math.min(del.length, add.length);
      for (let x = 0; x < pairs; x++) out.push({t: "~", from: del[x], to: add[x]});
      del.slice(pairs).forEach(text => out.push({t: "-", text}));
      add.slice(pairs).forEach(text => out.push({t: "+", text}));
    }
    return out.concat(a.slice(a.length - tail).map(text => ({t: "=", text})));
  }

  /* A CSL date as the source form shows it: year-month-day from date-parts, else as written (raw, literal). */
  const dateText = d => {
    const p = d && d["date-parts"] && d["date-parts"][0];
    if (p && p.length) return [String(p[0]).padStart(4, "0"), ...p.slice(1).map(x => String(x).padStart(2, "0"))].join("-");
    return d ? String(d.raw ?? d.literal ?? "") : "";
  };
  const dateParts = v => { const m = /^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$/.exec(squash(v)); return m ? {"date-parts": [[+m[1], ...(m[2] ? [+m[2]] : []), ...(m[3] ? [+m[3]] : [])]]} : null; };
  /* A source from the form's fields over the source it edits (null for a new one): {item} or {error}. A field whose text
     is what the form showed keeps the value it had (a raw date, a dropping particle, keys the form doesn't know). */
  function sourceItem(orig, f) {
    const item = {...(orig || {}), id: squash(f.id), type: squash(f.type) || "book"};
    const same = (k, shown) => !!orig && squash(f[k]) === squash(shown);
    const set = (k, v) => { if (v) item[k] = v; else delete item[k]; };
    set("title", squash(f.title));
    if (!same("authors", formatAuthors(orig && orig.author))) { const a = parseAuthors(f.authors); set("author", a.length ? a : null); }
    if (!same("year", dateText(orig && orig.issued))) set("issued", squash(f.year) ? dateParts(f.year) || {literal: squash(f.year)} : null);
    if (!same("accessed", dateText(orig && orig.accessed))) {
      if (squash(f.accessed) && !dateParts(f.accessed)) return {error: "Write the date it was accessed as year-month-day, like 2026-11-12."};
      set("accessed", dateParts(f.accessed));
    }
    set("publisher", squash(f.publisher)); set("container-title", squash(f.container)); set("URL", squash(f.url));
    return {item};
  }

  /* Where a piece is open, or being opened: "main", "split" or null. One piece is in one editor at a time: two would
     undo each other's typing. */
  function whereOpen(file, {main, mainPending, split, splitPending} = {}) {
    if (!file) return null;
    if (file === main || file === mainPending) return "main";
    if (file === split || file === splitPending) return "split";
    return null;
  }

  /* Room for the text: every text column at least 360 px. Things give way in order: the list of pieces (unless it is
     what was just asked for), then the page's side gutters and the notes margin (tight), then the rhythm's gutter
     (compact). measure(state) gives the narrowest text column for a state {binder, tight, compact}. {state, fits}: the
     most generous state that fits, or the tightest when nothing does (the request is then refused). */
  const FLOOR = 360;
  function giveWay(measure, {binder, rhythm, keepBinder = false, floor = FLOOR}) {
    const steps = [{binder, tight: false, compact: false}];
    if (binder && !keepBinder) steps.push({binder: false, tight: false, compact: false});
    const b = steps[steps.length - 1].binder;
    steps.push({binder: b, tight: true, compact: false});
    if (rhythm) steps.push({binder: b, tight: true, compact: true});
    for (const s of steps) if (measure(s) >= floor) return {state: s, fits: true};
    return {state: steps[steps.length - 1], fits: false};
  }
  /* what is said when a request doesn't fit: split, panel, rhythm, binder (the list of pieces) */
  function noRoom(request, {split, panel} = {}) {
    const close = [panel && request !== "panel" ? "the panel" : "", split && request !== "split" ? "the second pane" : ""].filter(Boolean).join(" or ");
    const what = {split: panel ? "two pieces beside the panel" : "two pieces side by side", panel: split ? "the panel beside two pieces" : "the panel",
      rhythm: "the rhythm's bars", binder: "the list of pieces"}[request];
    const fix = ["rhythm", "binder"].includes(request) ? "Close the panel or the second pane, or widen the window." : close ? `Close ${close}, or widen the window.` : "Widen the window.";
    return `There isn't room for ${what} at this width. ${fix}`;
  }
  /* Sentence rhythm's scale, the same in every layout: 1 px a word up to 40 words (20 when compact), 12 px from the text;
     its gutter before the text is 56 px (36 compact), kept by book-tools.css (.bt-rg) while Rhythm is on */
  const RHYTHM = {px: 1, words: 40, compactWords: 20, gap: 12, gutter: 56, compact: 36};
  const rhythmBar = (words, compact = false) => Math.min(words, compact ? RHYTHM.compactWords : RHYTHM.words) * RHYTHM.px;

  /* A change on disk to pieces open in the editor (replace, restore): every editor and field of each piece is locked and
     the piece busy (the poll leaves it alone); saves under way land and what is typed is saved; a save that fails stops
     it all before anything changes. After the change each piece is read again, as one change undo can take back, unless
     it was changed meanwhile after all: then it gets the conflict bar (Reload or Keep mine), so nothing is read over. */
  async function guarded(pieces, run, {settled, by} = {}) {
    pieces = pieces.filter(p => p && p.text && !p.closed);
    for (const p of pieces) { p.busy = true; p.text.lock(true); }
    try {
      if (settled) await settled();
      for (const p of pieces) {
        if (!(await p.flush())) throw new Error(`${p.name} has changes that couldn't be saved, so nothing was changed. Its text is as you left it`);
      }
      const out = await run();
      for (const p of pieces) {
        if (p.closed) continue;
        if (p.dirty) { p.conflict = p.conflict || (by ? {by} : {}); p.win.bar(p); p.win.status(); }
        else await p.reload(false);
      }
      return out;
    } finally {
      for (const p of pieces) { p.busy = false; if (p.text && !p.closed) p.text.lock(false); }
    }
  }

  /* The outline of a piece (a ProseMirror document): its title, headings, scene breaks and notes, with their positions. */
  const short = (s, max = 44) => {
    s = squash(s);
    if (s.length <= max) return s;
    const cut = s.slice(0, max), sp = cut.lastIndexOf(" ");
    return (sp > 12 ? cut.slice(0, sp) : cut).replace(/[\s,;:.–—-]+$/, "") + "…";
  };
  const ownText = n => { let s = ""; n.forEach(c => { s += c.isText ? c.text : c.type.name === "hard_break" ? " " : ""; }); return squash(s); };
  function outline(doc) {
    const out = [];
    doc.descendants((n, pos) => {
      const t = n.type.name;
      if (t === "title") out.push({kind: "title", level: 1, text: ownText(n), pos});
      else if (t === "heading") out.push({kind: "heading", level: n.attrs.level, text: ownText(n), pos});
      else if (t === "scene_break") out.push({kind: "scene", text: "", pos});
      else if (t === "note") { out.push({kind: "note", text: short(n.textContent), pos}); return false; }
      return true;
    });
    return out;
  }

  const helpers = {fold, wordsIn, echoes, ECHO_STOP, TOOLS, numberWord, numberIssues, termIssues, quoteIssues, styleIssues, sentences,
    fuzzy, rank, parseAuthors, formatAuthors, sourceKey, dateText, dateParts, sourceItem, whereOpen, guarded, findIn, plainBlocks,
    diffBlocks, outline, short, squash, primary, giveWay, noRoom, rhythmBar, RHYTHM, FLOOR, GAP};
  if (typeof document === "undefined") { root.BookTools = helpers; return; }          // node: the helpers only

  /* ——— the text as containers: where text lives in a document, in the server's order (books._containers) ——— */
  function inlineText(node, start, lang) {
    let text = "", own = "", p = start;
    const at = [];
    node.forEach(c => {
      if (c.isText) {
        const other = c.marks.some(m => m.type.name === "lang" && m.attrs.lang && primary(m.attrs.lang) !== primary(lang));
        for (let i = 0; i < c.text.length; i++) at.push(p + i);
        text += c.text; own += other ? c.text.replace(/\S/g, "x") : c.text;
      } else {
        const ch = c.type.name === "hard_break" ? "\n" : GAP;
        at.push(p); text += ch; own += ch;
      }
      p += c.nodeSize;
    });
    at.push(p);
    return {text, own, at};
  }
  function containersOf(doc, lang) {
    const out = [];
    const walk = (n, pos, inPoem) => {
      const t = n.type.name;
      if (t === "title" || t === "heading" || t === "paragraph" || t === "attribution") {
        out.push({kind: "text", node: n, pos, inPoem, ...inlineText(n, pos + 1, lang)});
        n.forEach((c, off) => { if (c.type.name === "note") out.push({kind: "note", node: c, pos: pos + 1 + off, ...inlineText(c, pos + 2 + off, lang)}); });
      } else if (t === "blockquote" || t === "epigraph" || t === "poem") n.forEach((c, off) => walk(c, pos + 1 + off, inPoem || t === "poem"));
      else if (t === "image" && n.attrs.alt) out.push({kind: "caption", node: n, pos, text: n.attrs.alt, at: null});
    };
    doc.forEach((c, off) => walk(c, off, false));
    return out;
  }

  /* ——— the window's tools ——— */
  const R = {W: null, focus: false, focusPane: null, active: null, reading: null, find: null, pal: null, prefs: {}, typedAt: 0, sheetKey: ""};
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const reduced = () => root.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const pieceTitle = e => e.title || pieceKindName(e.kind);
  const panes = () => R.W ? [R.W, ...(R.W.split ? [R.W.split] : [])] : [];
  const texts = () => panes().map(p => p.piece?.text).filter(t => t && !t.destroyed);
  const paneOf = T => panes().find(p => p.piece?.text === T) || null;
  /* the pane last written in: the rail, read aloud and the palette work on its piece */
  const activePane = () => R.active && panes().includes(R.active) && R.active.piece?.text && !R.active.piece.closed ? R.active : R.W;
  const activePiece = () => activePane()?.piece || null;
  const langName = l => { try { return new Intl.DisplayNames(["en"], {type: "language"}).of(l) || l; } catch { return l; } };

  /* ——— decorations: echoes, the style sheet, find. Each a set mapped through changes until worked out again ——— */
  const KEYS = {echo: new PluginKey("bt-echo"), style: new PluginKey("bt-style"), find: new PluginKey("bt-find")};
  const decoPlugin = key => new Plugin({key,
    state: {init: () => DecorationSet.empty, apply: (tr, set) => { const m = tr.getMeta(key); return m !== undefined ? m : tr.docChanged ? set.map(tr.mapping, tr.doc) : set; }},
    props: {decorations: state => key.getState(state)}});
  function plugins(T) {
    return [decoPlugin(KEYS.echo), decoPlugin(KEYS.style), decoPlugin(KEYS.find), new Plugin({
      props: {
        decorations: state => focusDecos(T, state),
        handleDOMEvents: {
          keydown: (view, e) => {
            R.typedAt = performance.now();
            // a note or a comment is written in the margin, which focus mode hides: leave it first
            if (R.focus && (e.ctrlKey || e.metaKey) && e.altKey && /^[fm]$/i.test(e.key)) setFocus(false);
            // Esc, before ProseMirror's own (which selects the paragraph): the style sheet's tip, focus mode, the second pane
            if (e.key !== "Escape" || e.ctrlKey || e.altKey || e.metaKey || e.shiftKey || !T.slash.el.hidden) return false;
            if (T.tools?.tipFor) T.tools.hideTip();
            else if (R.focus) setFocus(false);
            else if (paneOf(T)?.split) Split.close();
            else return false;
            e.preventDefault();
            return true;
          },
          contextmenu: (view, e) => styleMenu(T, view, e),
          focus: () => { const p = paneOf(T); if (p && p !== R.active) { R.active = p; R.rail?.pieceChanged(); R.W.status(); } return false; },
          blur: () => { setTimeout(() => { if (!T.destroyed && !T.view.hasFocus()) T.tools?.hideTip(); }, 0); return false; },
        },
        handleKeyDown: (view, e) => {
          const tip = T.tools?.tipFor;
          if (tip && e.key === "Enter" && e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey) { applyFix(T, tip); return true; }
          return false;
        },
      },
      view: view => new ToolView(T, view),
    })];
  }
  function echoDecos(doc, boxes, lang) {
    const toks = [];
    for (const b of boxes) {
      if (b.kind !== "text" || b.node.type.name === "title") continue;
      for (const w of wordsIn(b.text)) toks.push({w: w.w, from: b.at[w.from], to: b.at[w.to]});
    }
    return DecorationSet.create(doc, echoes(toks.map(t => t.w), lang).map(i => Decoration.inline(toks[i].from, toks[i].to, {class: "bt-echo"})));
  }
  function styleDecos(doc, boxes, sheet, lang) {
    const out = [], poemForm = doc.attrs.form === "poem";
    for (const b of boxes) {
      if (b.kind !== "text") continue;
      const prose = !poemForm && !b.inPoem && b.node.type.name === "paragraph";
      for (const i of styleIssues(b.text, sheet, {lang, prose, numbersText: b.own})) {
        const text = b.text.slice(i.from, i.to);
        if (!text.includes(GAP)) out.push(Decoration.inline(b.at[i.from], b.at[i.to], {class: "bt-style", title: i.title}, {issue: {...i, text}}));
      }
    }
    return DecorationSet.create(doc, out);
  }
  /* the matches of the rail's find in this text; the one chosen in the rail stands out. Numbered as the server numbers
     them (text, notes, captions in reading order), so a result's index finds its match here. */
  function matchesOf(boxes, f) {
    const out = [];
    for (const b of boxes) for (const [a, z] of findIn(b.text, f.q, f)) out.push({box: b, from: a, to: z});
    return out;
  }
  function findDecos(T, doc, boxes) {
    const f = R.find;
    if (!f || !f.q) return DecorationSet.empty;
    const file = paneOf(T)?.piece?.file, cur = f.current && f.current.file === file ? f.current.index : -1;
    return DecorationSet.create(doc, matchesOf(boxes, f).map((m, k) => m.box.kind === "text"
      ? Decoration.inline(m.box.at[m.from], m.box.at[m.to], {class: k === cur ? "bt-find on" : "bt-find"}) : null).filter(Boolean));
  }
  /* focus mode: the paragraph being written stays lit, the rest of the text is dimmed by the stylesheet */
  function focusDecos(T, state) {
    if (!R.focus || !R.focusPane || paneOf(T) !== R.focusPane) return null;
    const sel = state.selection;
    let from, to;
    if (sel instanceof NodeSelection && sel.node.isBlock) ({from, to} = sel);
    else {
      const $h = sel.$head;
      let d = $h.depth;
      while (d > 0 && !$h.node(d).isTextblock) d--;
      if (!d) return null;
      from = $h.before(d); to = $h.after(d);
    }
    return DecorationSet.create(state.doc, [Decoration.node(from, to, {class: "bt-cur"})]);
  }

  /* one per text: works the decorations out again after changes, draws the rhythm, keeps the typewriter line */
  class ToolView {
    constructor(T, view) {
      Object.assign(this, {T, view, timer: 0, rtimer: 0, layer: null, bars: [], tip: null, tipFor: null});
      T.tools = this;
      this.ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => this.scheduleRhythm()) : null;
      this.ro?.observe(view.dom);
      this.schedule(0);
    }
    update(view, prev) {
      this.view = view;
      const doc = view.state.doc !== prev.doc, sel = !view.state.selection.eq(prev.selection);
      if (doc) { this.boxes = null; this.schedule(); this.hideTip(); }        // positions from before the change are not used
      else if (sel) this.showTip();
      if (sel || doc) { this.markSentence(); R.rail?.changed(this.T, doc); }
      if ((doc || sel) && R.focus && performance.now() - R.typedAt < 200 && view.hasFocus()) requestAnimationFrame(() => typewriter(this.T, true));
    }
    destroy() {
      clearTimeout(this.timer); clearTimeout(this.rtimer);
      this.ro?.disconnect(); this.layer?.remove(); this.tip?.remove();
      if (this.T.tools === this) this.T.tools = null;
    }
    schedule(ms = 350) { clearTimeout(this.timer); this.timer = setTimeout(() => this.compute(), ms); }
    scheduleRhythm(ms = 120) { clearTimeout(this.rtimer); this.rtimer = setTimeout(() => this.drawRhythm(), ms); }
    compute() {
      const T = this.T, view = this.view;
      if (T.destroyed || !R.W || T.tools !== this) return;
      const doc = view.state.doc, lang = T.ctx.language || "en", boxes = containersOf(doc, lang);
      const tr = view.state.tr
        .setMeta(KEYS.echo, R.prefs.echoes ? echoDecos(doc, boxes, lang) : DecorationSet.empty)
        .setMeta(KEYS.style, R.prefs.style ? styleDecos(doc, boxes, T.ctx.sheet(), lang) : DecorationSet.empty)
        .setMeta(KEYS.find, findDecos(T, doc, boxes));
      view.dispatch(tr);
      this.boxes = boxes;
      this.drawRhythm();
    }
    /* Sentence rhythm: a thin bar per sentence beside the text, in a gutter before it that every layout keeps while Rhythm
       is on and the piece isn't a poem (the text gives way by its width), as long as its words (RHYTHM: 1 px a word, 40
       words at most, 20 when room is short). Bars of sentences on one line stack down. A pane that isn't shown (focus mode
       on the other) draws nothing. */
    drawRhythm() {
      clearTimeout(this.rtimer);
      const T = this.T, col = T.textHost?.parentElement;
      if (T.destroyed || !col) return;
      if (!R.prefs.rhythm) { this.layer?.remove(); this.layer = null; this.bars = []; return; }
      if (!col.offsetParent) return;
      const view = this.view, doc = view.state.doc, boxes = this.boxes || containersOf(doc, T.ctx.language);
      const c0 = col.getBoundingClientRect();
      if (!this.layer) { this.layer = el("div", "bt-rhythm"); this.layer.setAttribute("aria-hidden", "true"); col.append(this.layer); }
      const compact = !!R.W?.root.classList.contains("compact"), bars = [];
      if (doc.attrs.form !== "poem") {
        for (const b of boxes) {
          if (b.kind !== "text" || b.inPoem || b.node.type.name !== "paragraph") continue;
          for (const s of sentences(b.text)) bars.push({from: b.at[s.from], to: b.at[s.to], words: s.words});
        }
      }
      let last = -Infinity;
      const html = [];
      for (const s of bars) {
        let c;
        try { c = view.coordsAtPos(s.from, 1); } catch { continue; }
        const y = Math.max(Math.round((c.top + c.bottom) / 2 - c0.top - 1), last + 5);
        last = y;
        html.push(`<i style="top:${y}px;width:${Math.max(2, rhythmBar(s.words, compact))}px" title="${s.words} word${s.words === 1 ? "" : "s"}"></i>`);
      }
      this.layer.innerHTML = html.join("");
      this.bars = bars;
      this.markSentence();
    }
    markSentence() {
      if (!this.layer || !this.bars.length) return;
      const h = this.view.state.selection.head, k = this.bars.findIndex(s => s.from <= h && h <= s.to);
      [...this.layer.children].forEach((b, i) => b.classList.toggle("on", i === k));
    }
    /* the style sheet's word under the cursor: what to use, and a button that uses it (Alt+Enter) */
    showTip() {
      const T = this.T, view = this.view, sel = view.state.selection;
      if (!R.prefs.style || !sel.empty || !view.hasFocus()) return this.hideTip();
      const d = KEYS.style.getState(view.state).find(sel.head, sel.head).find(x => x.from <= sel.head && sel.head <= x.to && x.spec.issue);
      if (!d) return this.hideTip();
      const issue = d.spec.issue;
      if (!this.tip) {
        this.tip = el("div", "bt-tip");
        this.tip.setAttribute("role", "status");
        this.tip.addEventListener("mousedown", e => e.preventDefault());
        this.tip.addEventListener("click", e => { if (e.target.closest("button") && this.tipFor) applyFix(T, this.tipFor); });
        T.over.append(this.tip);
      }
      this.tipFor = d;
      this.tip.innerHTML = `<span class="bt-tip-t">${esc(issue.title)}</span><button type="button" class="bm-btn" title="Alt+Enter">Use ${esc(issue.fix)}</button>`;
      this.tip.hidden = false;
      const a = view.coordsAtPos(d.from, 1), page = T.page.getBoundingClientRect(), col = T.textHost.getBoundingClientRect();
      const w = this.tip.offsetWidth, h = this.tip.offsetHeight;
      const left = Math.max(col.left, Math.min(a.left - 12, col.right - w));
      this.tip.style.left = Math.round(left - page.left) + "px";
      this.tip.style.top = Math.round(a.top - page.top - h - 10) + "px";
    }
    hideTip() { this.tipFor = null; if (this.tip) this.tip.hidden = true; }
  }
  function applyFix(T, d) {
    if (T.locked) return false;
    const view = T.view, issue = d.spec.issue;
    T.tools?.hideTip();
    const cur = KEYS.style.getState(view.state).find(d.from, d.to).find(x => x.spec.issue === issue);
    if (!cur || view.state.doc.textBetween(cur.from, cur.to, "\n", GAP) !== issue.text) return false;
    view.dispatch(view.state.tr.insertText(issue.fix, cur.from, cur.to).scrollIntoView());
    view.focus();
    return true;
  }
  /* right-click on a marked word: use the style sheet's form */
  function styleMenu(T, view, e) {
    if (!R.prefs.style || typeof StudioMenu === "undefined") return false;
    const at = view.posAtCoords({left: e.clientX, top: e.clientY});
    if (!at) return false;
    const d = KEYS.style.getState(view.state).find(at.pos, at.pos).find(x => x.from <= at.pos && at.pos <= x.to && x.spec.issue);
    if (!d) return false;
    StudioMenu.open(e, [{label: `Use ${d.spec.issue.fix}`, act: () => applyFix(T, d)}]);
    return true;
  }
  /* the caret's line at 45% of the window's height: only while typing, smoothly unless motion is reduced */
  function typewriter(T, smooth) {
    const pane = paneOf(T), scroller = pane?.hosts.scroll;
    if (!scroller || T.destroyed) return;
    // the caret as the browser draws it (at a soft line break: the end of the line above), else the character before it
    const v = T.view, sel = v.hasFocus() && getSelection().rangeCount ? getSelection().getRangeAt(0).getBoundingClientRect() : null;
    const c = sel && sel.height ? sel : v.coordsAtPos(v.state.selection.head, -1), delta = (c.top + c.bottom) / 2 - innerHeight * 0.45;
    if (Math.abs(delta) < 2) return;
    scroller.scrollTo({top: scroller.scrollTop + delta, behavior: smooth && !reduced() ? "smooth" : "auto"});
  }
  /* work every text's decorations out again (a tool switched, the style sheet or the find changed) */
  const recompute = (ms = 0) => texts().forEach(T => T.tools?.schedule(ms));

  /* ——— the writing tools in the status bar, and the daily goal line ——— */
  function mountTools() {
    const foot = R.W.root.querySelector(".bw-status");
    R.toolsEl = el("span", "bw-tools");
    R.toolsEl.setAttribute("role", "group"); R.toolsEl.setAttribute("aria-label", "Writing tools");
    R.toolsEl.innerHTML = TOOLS.map(([id, label, title]) => `<button type="button" class="bw-tog" data-tool="${id}" aria-pressed="false" title="${esc(title)}">${esc(label)}</button>`).join("");
    R.toolsEl.addEventListener("mousedown", e => { if (e.target.closest("[data-tool]")) e.preventDefault(); });      // the text keeps the focus
    R.toolsEl.addEventListener("click", e => { const b = e.target.closest("[data-tool]"); if (b) toggleTool(b.dataset.tool); });
    R.goalEl = el("i", "bw-goal");
    R.goalEl.setAttribute("aria-hidden", "true");
    foot.append(R.toolsEl, R.goalEl);
    paintTools();
  }
  function paintTools() {
    if (!R.toolsEl) return;
    const goal = +R.W?.book.goals?.daily || 0;
    const on = {focus: R.focus, read: !!R.reading, echoes: R.prefs.echoes, rhythm: R.prefs.rhythm, goal: R.prefs.goal};
    for (const b of R.toolsEl.children) b.setAttribute("aria-pressed", String(!!on[b.dataset.tool]));
    R.toolsEl.querySelector("[data-tool=goal]").hidden = !goal;
    R.goalEl.hidden = !goal || !R.prefs.goal;
  }
  const PREF = {echoes: "bookEchoes", rhythm: "bookRhythm", style: "bookStyleMarks", goal: "bookGoalLine"};
  function setPref(k, v) {
    R.prefs[k] = v;
    pref.set(PREF[k], v ? "1" : "0");
    if (k === "rhythm") {
      if (v && !fit("rhythm")) { R.prefs.rhythm = false; pref.set(PREF.rhythm, "0"); fit(); toast(noRoom("rhythm"), true); paintTools(); return; }
      if (!v) fit();
      texts().forEach(T => T.tools?.drawRhythm());
    }
    else if (k !== "goal") recompute();
    paintTools();
  }
  function toggleTool(id) {
    if (id === "focus") setFocus(!R.focus);
    else if (id === "read") readAloud();
    else setPref(id, !R.prefs[id]);
    if (id !== "focus" && id !== "read") activePiece()?.text?.focus();
  }
  function goalLine({today, goal}) {
    if (!R.goalEl) return;
    R.goalEl.style.width = goal ? `${Math.min(100, (today / goal) * 100).toFixed(2)}%` : "0";
    R.goalEl.classList.toggle("done", !!goal && today >= goal);
    paintTools();
  }

  /* ——— read aloud: from the cursor, sentence by sentence, in the book's language ——— */
  function readAloud() {
    if (R.reading) return stopReading();
    const T = activePiece()?.text;
    if (!T) return;
    if (!root.speechSynthesis) { toast("This browser can't read aloud", true); return; }
    const lang = T.ctx.language || "en", doc = T.view.state.doc, from = T.view.state.selection.from, chunks = [];
    for (const b of containersOf(doc, lang)) {
      if (b.kind !== "text" || b.pos + b.node.nodeSize <= from) continue;
      let k = 0;
      if (b.pos < from) { k = b.at.findIndex(p => p >= from); if (k < 0) continue; }
      const text = b.text.slice(k).replace(new RegExp(GAP, "g"), "").replace(/\n/g, " ");
      for (const s of sentences(text)) chunks.push(text.slice(s.from, s.to));
    }
    if (!chunks.length) { toast("There's no text after the cursor to read"); return; }
    const voices = speechSynthesis.getVoices(), want = primary(lang);
    const voice = voices.find(v => v.lang.toLowerCase().replace("_", "-") === lang.toLowerCase()) || voices.find(v => primary(v.lang) === want);
    if (voices.length && !voice) toast(`This computer has no ${langName(lang)} voice: the text is read with another one.`);
    speechSynthesis.cancel();
    const token = R.reading = {piece: activePiece()};
    const say = i => {
      if (R.reading !== token) return;
      if (i >= chunks.length) { stopReading(); return; }
      const u = new SpeechSynthesisUtterance(chunks[i]);
      u.lang = lang;
      if (voice) u.voice = voice;
      u.onend = () => say(i + 1);
      u.onerror = e => { if (R.reading === token && e.error !== "interrupted" && e.error !== "canceled") { toast(`Reading aloud stopped: ${e.error}`, true); stopReading(); } };
      speechSynthesis.speak(u);
    };
    say(0);
    paintTools();
  }
  /* reading stops when its piece leaves its pane (closed, another piece there, the pane closed) */
  function checkReading() {
    const p = R.reading?.piece;
    if (p && (p.closed || !panes().some(x => x.piece === p))) stopReading();
  }
  function stopReading() {
    const was = R.reading;
    R.reading = null;
    if (was && root.speechSynthesis) speechSynthesis.cancel();
    paintTools();
  }

  /* ——— focus mode: binder, rail and margin go, the other paragraphs dim, the caret's line stays at 45% ——— */
  function setFocus(on) {
    const W = R.W;
    if (!W || on === R.focus) return;
    R.focus = on;
    R.focusPane = on ? activePane() : null;
    W.root.classList.toggle("focus", on);
    W.root.classList.toggle("focus-split", on && R.focusPane !== W);
    if (!on) fit();
    texts().forEach(T => { T.view.setProps({}); T.tools?.scheduleRhythm(60); if (!on) T.margin.remeasure(); });
    paintTools();
    const T = (R.focusPane || activePane())?.piece?.text;
    if (!T) return;
    T.focus();
    requestAnimationFrame(() => {
      if (T.destroyed) return;
      if (on) typewriter(T, false);
      else T.view.dispatch(T.view.state.tr.scrollIntoView());
    });
  }

  /* ——— room for the text: every text column at least 360 px (giveWay), rechecked on every split, panel, Rhythm and list
     toggle, piece opened and window resize. The list of pieces shows as the author set it whenever there is room. ——— */
  const shownPanes = () => panes().filter(p => p.hosts.text.offsetParent);
  const narrowest = () => Math.min(...shownPanes().map(p => p.hosts.text.getBoundingClientRect().width));
  const paintPieces = () => R.W?.root.querySelector(".bw-status > .bw-tog")?.setAttribute("aria-pressed", String(!R.W.root.classList.contains("nobinder")));
  const binderWish = () => pref.get("bookBinder", R.binderDefault) === "1";       // the author's setting; the window's default as it opened
  /* the rhythm's gutter, per pane: while Rhythm is on and its piece isn't a poem (no bars ever draw there) */
  function gutters() {
    for (const p of panes()) {
      const file = p.pending?.file || p.piece?.file || p.opening;          // the piece being opened counts already
      const form = p.piece?.text && p.piece.file === file ? p.piece.text.view.state.doc.attrs.form : R.W.book.contents.find(e => e.file === file)?.form || "prose";
      p.hosts.page.classList.toggle("bt-rg", !!R.prefs.rhythm && !!file && form !== "poem");
    }
  }
  /* request: "split", "panel", "rhythm", "binder" (the author showed the list: it doesn't give way), or none. true: fits */
  function fit(request) {
    const W = R.W;
    if (!W) return true;
    gutters();
    if (R.focus) return true;                  // one text, centred
    const root = W.root, apply = s => {
      root.classList.toggle("nobinder", !s.binder); root.classList.toggle("tight", s.tight); root.classList.toggle("compact", s.compact);
    };
    const {state: s, fits} = giveWay(st => { apply(st); return narrowest(); },
      {binder: request === "binder" || binderWish(), rhythm: !!R.prefs.rhythm, keepBinder: request === "binder"});
    apply(s);
    paintPieces();
    texts().forEach(T => T.tools?.scheduleRhythm(0));
    return fits;
  }
  /* the window was resized: a rail panel closes when the texts don't fit; a text never closes */
  let resizeTimer = 0;
  addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (R.W && !fit() && R.W.root.classList.contains("railopen")) { R.rail?.close(); fit(); } }, 120);
  });

  /* ——— split view: a second pane with its own piece, saved as the first is (book-editor's Piece) ——— */
  const Split = {
    build(file) {
      const W = R.W, main = W.root.querySelector(".bw-main");
      const head = el("header", "bw-ph");
      head.innerHTML = `<span class="bw-ph-t"></span><span class="state"></span>`;
      main.prepend(head);
      const sec = el("section", "bw-main bw-split");
      sec.setAttribute("aria-label", "Second piece");
      sec.innerHTML = `<header class="bw-ph"><span class="bw-ph-t"></span><span class="state"></span>
          <button type="button" class="bw-tog bw-ph-x" title="Close the second pane · Esc">Close</button></header>
        <div class="bw-bar" role="status" hidden></div>
        <div class="bw-scroll"><div class="bw-page"><div class="bw-col"><div class="bw-text"></div></div>
          <div class="bw-margin" aria-label="Notes and comments"></div><div class="bw-over"></div></div></div>`;
      main.after(sec);
      W.root.classList.add("split");
      const q = s => sec.querySelector(s);
      const P = {split: true, main: W, sec, head: q(".bw-ph"), mainHead: head, piece: null, pending: null, opening: file, frame: 0,
        hosts: {page: q(".bw-page"), text: q(".bw-text"), margin: q(".bw-margin"), over: q(".bw-over"), scroll: q(".bw-scroll")},
        barEl: q(".bw-bar"),
        get book() { return W.book; }, get linked() { return W.linked; },
        ctx: p => W.ctx(p), saved: (...a) => W.saved(...a), lost: (...a) => W.lost(...a), gone: (...a) => W.gone(...a),
        bar: p => BookEditor.bar(p), status: () => { Split.paint(); W.status(); }};       // the heads, and the status bar when this pane is written in
      q(".bw-ph-x").addEventListener("click", () => Split.close());
      W.split = P;
      Split.look();
      if (!fit("split")) {          // two texts of 360 px don't fit: the pane goes again, and says so
        toast(noRoom("split", {panel: W.root.classList.contains("railopen")}), true);
        Split.close(false);
        return null;
      }
      return P;
    },
    /* the look's font, from the first pane's page */
    look() {
      const P = R.W?.split;
      if (!P) return;
      const main = R.W.hosts.page, page = P.hosts.page;
      for (const k of ["--bk-font", "--bk-weight"]) page.style.setProperty(k, main.style.getPropertyValue(k));
      page.lang = main.lang;
    },
    async open(file) {
      const W = R.W, e = W?.book.contents.find(x => x.file === file);
      if (!e) return;
      let P = W.split;
      const at = whereOpen(file, {main: W.piece?.file, mainPending: W.pending?.file, split: P?.piece && !P.piece.closed ? P.piece.file : null, splitPending: P?.pending?.file});
      if (at === "main") {
        toast(`“${pieceTitle(e)}” is already open on the left. A piece is open in one pane at a time, so that two editors never write over each other.`);
        W.piece?.text?.focus();
        return;
      }
      if (at === "split") { P.piece?.file === file && P.piece.text?.focus(); return; }
      if (R.focus) setFocus(false);
      if (!P) { P = Split.build(file); if (!P) return; }
      const piece = new BookEditor.Piece(P, file), files = W.book.contents.filter(x => x.file), k = files.findIndex(x => x.file === file);
      piece.after_ = files[k - 1]?.file;
      P.pending = piece;
      let p = null;
      await BookEditor.leaving(W.book.id, file);
      try { p = await piece.fetch(); } catch (err) { piece.error = err.message; }
      if (R.W !== W || W.split !== P || P.pending !== piece) { BookEditor.forget(piece); return; }
      P.piece?.close();
      P.piece = piece; P.pending = null;
      P.hosts.text.replaceChildren(); P.hosts.margin.replaceChildren(); P.hosts.over.replaceChildren();
      if (p) piece.attach(p); else BookEditor.forget(piece);
      BookEditor.bar(piece);
      const v = piece.text?.view, place = BookEditor.places.get(`${W.book.id}/${file}`);
      if (v && place) {
        try { const max = v.state.doc.content.size; v.dispatch(v.state.tr.setSelection(TextSelection.create(v.state.doc, Math.min(place.anchor, max), Math.min(place.head, max)))); }
        catch { /* a place the text no longer has */ }
        P.hosts.scroll.scrollTop = place.scroll || 0;
      }
      R.active = P; P.opening = null;
      fit();                       // its piece is in: a poem has no rhythm gutter
      Split.paint();
      W.status();
      piece.text?.focus();
      R.rail?.pieceChanged();
      checkReading();
    },
    /* the second pane goes; its piece is left with a leaving save (kept in this browser until that is answered) */
    close(refocus = true) {
      const W = R.W, P = W?.split;
      if (!P) return;
      if (R.focusPane === P) setFocus(false);
      P.pending = null;
      P.piece?.close();
      cancelAnimationFrame(P.frame);
      P.sec.remove(); P.mainHead.remove();
      W.split = null;
      W.root.classList.remove("split", "focus-split");
      fit();
      if (R.active === P) R.active = W;
      W.status();
      if (refocus) W.piece?.text?.focus();
      R.rail?.pieceChanged();
      checkReading();
    },
    /* the panes' heads: the piece and whether it is saved */
    paint() {
      const P = R.W?.split;
      if (!P || P.frame) return;
      P.frame = requestAnimationFrame(() => {
        P.frame = 0;
        if (R.W?.split !== P) return;
        for (const [head, p] of [[P.head, P.piece], [P.mainHead, R.W.piece]]) {
          head.querySelector(".bw-ph-t").textContent = p ? p.name : "";
          const st = head.querySelector(".state"), say = !p?.text ? "" : p.conflict || p.failed ? "Not saved" : p.saving ? "Saving…" : p.dirty ? "Unsaved changes" : "Saved";
          st.textContent = say;
          st.classList.toggle("dirty", say === "Unsaved changes" || say === "Not saved");
        }
      });
    },
  };

  /* ——— the command palette (Ctrl+K): every piece by its title, and the window's actions ——— */
  /* an export (book.js's downloadBook) of the text on the screen: the open pieces are saved first */
  async function exportBook(format) {
    const W = R.W;
    for (const p of panes().map(x => x.piece)) {
      if (p?.text && !p.closed && !(await p.flush())) { toast(`${p.name} has changes that aren't on disk yet: the export holds the text before them.`, true); break; }
    }
    if (R.W === W) downloadBook(W.book.id, format);
  }
  /* Freeze edition… (book.js's dialog) of the text on the screen: the open pieces are saved first */
  async function freezeBook() {
    const W = R.W;
    for (const p of panes().map(x => x.piece)) {
      if (p?.text && !p.closed && !(await p.flush())) { toast(`${p.name} has changes that aren't on disk yet: the edition holds the text before them.`, true); break; }
    }
    if (R.W === W) freezeEdition(W.book.id);
  }
  async function updateBook(fields, msg) {
    const W = R.W, r = await api("/api/book/update", {b: W.book.id, fields});
    if (R.W === W) BookEditor.refresh(r);
    if (msg) toast(msg);
    return r;
  }
  /* another kind, asking (as the settings do) whether its features replace the book's when they differ */
  async function changeKind(kind) {
    const W = R.W, b = W.book, label = bookKindName(kind), have = b.features || {};
    let want;
    try { want = (await loadBookKinds())[kind]?.features || {}; } catch (e) { toast(e.message, true); return; }
    if (R.W !== W) return;
    const differ = bookKindChanges(have, want), back = () => activePiece()?.text?.focus();      // book.js: one rule, one question
    if (!differ.length) { updateBook({kind}, `Kind: ${label}`).catch(e => toast(e.message, true)).finally(back); return; }
    const form = openDialog(bookKindQuestion(b, kind, differ, have, want),
    async () => { await updateBook({kind, apply_kind_defaults: true}, `Kind: ${label}, with its features`); });
    form.querySelector("[data-keep]").onclick = async () => {
      try { await updateBook({kind}, `Kind: ${label}, features kept`); $("#dlg").close(); } catch (e) { toast(e.message, true); }
    };
    onDialogClose(back);
  }
  /* each feature's other settings, as the settings name them */
  function featureActions(b) {
    const f = b.features || {}, out = [], firstLines = b.kind === "poetry" || f.index === "first-lines";
    const opts = {notes: ["off", "footnotes", "endnotes", "both"], noteNumbering: f.notes && f.notes !== "off" ? ["chapter", "book"] : [],
      sources: [true, false], index: [false, true, ...(firstLines ? ["first-lines"] : [])], figures: [true, false], contentNote: [true, false]};
    const now = {notes: f.notes || "off", noteNumbering: f.noteNumbering || "chapter", sources: !!f.sources, index: f.index ?? false, figures: !!f.figures, contentNote: !!f.contentNote};
    for (const [k, values] of Object.entries(opts)) {
      for (const v of values) {
        if (v === now[k]) continue;
        const text = `${BOOK_FEATURE_NAME[k]}: ${bookFeatureText(k, v)}`;
        out.push({label: text, hint: "Feature", run: () => updateBook({features: {[k]: v}}, text).catch(e => toast(e.message, true))});
      }
    }
    return out;
  }
  function actions() {
    const W = R.W, b = W.book, rail = R.rail, goal = +b.goals?.daily || 0, act = (label, hint, run) => ({label, hint, run});
    const tog = (k, show, hide) => act(R.prefs[k] ? hide : show, "Tool", () => setPref(k, !R.prefs[k]));
    return [
      act("New chapter", "", () => BookEditor.newPiece("chapter")),
      act(R.focus ? "Leave focus mode" : "Focus mode", "Ctrl+Shift+F", () => setFocus(!R.focus)),
      W.split ? act("Close the second pane", "Esc", () => Split.close()) : act("Open a piece beside this one…", "Alt+click", () => Palette.open("beside")),
      act(R.reading ? "Stop reading aloud" : "Read aloud from the cursor", "Tool", () => readAloud()),
      tog("echoes", "Show echoes", "Hide echoes"),
      tog("rhythm", "Show sentence rhythm", "Hide sentence rhythm"),
      tog("style", "Show the style sheet's marks", "Hide the style sheet's marks"),
      ...(goal ? [tog("goal", "Show the daily goal line", "Hide the daily goal line")] : []),
      act(W.root.classList.contains("nobinder") ? "Show the list of pieces" : "Hide the list of pieces", "Ctrl+\\", () => BookEditor.toggleBinder()),
      ...(rail ? rail.panels().map(([id, name]) => act(name, id === "find" ? "Ctrl+F" : "Rail", () => rail.open(id, {focus: true}))) : []),
      ...BOOK_EXPORTS.map(([f, , label]) => act(label, "Export", () => exportBook(f))),
      act("Freeze edition…", "Edition", () => freezeBook()),
      act("Book settings", "Settings", () => { location.hash = bookTabHash(b.id, "details"); }),
      act("Kind and features", "Settings", () => { location.hash = bookTabHash(b.id, "features"); }),
      act("Look", "Settings", () => { location.hash = bookTabHash(b.id, "look"); }),
      act("Style sheet", "Settings", () => { location.hash = bookTabHash(b.id, "style"); }),
      ...Object.keys(bookKindData || BOOK_KIND_COPY).filter(k => k !== b.kind).map(k => act(`Change kind to ${bookKindName(k)}`, "Kind", () => changeKind(k))),
      ...featureActions(b),
    ];
  }
  const highlight = (label, q) => {
    const m = q ? fuzzy(q, label) : null, chars = [...label.normalize("NFC")];
    if (!m) return esc(label);
    const hits = new Set(m.hits);
    return chars.map((c, i) => hits.has(i) ? `<b>${esc(c)}</b>` : esc(c)).join("");
  };
  const Palette = {
    open(mode = "all") {
      if (!R.W) return;
      if (R.pal) Palette.close(false);
      loadBookKinds().catch(() => {});
      const back = document.activeElement, wrap = el("div", "bt-pal-wrap");
      wrap.innerHTML = `<div class="bt-pal" role="dialog" aria-modal="true" aria-label="${mode === "beside" ? "Open beside" : "Go to a piece or run an action"}">
        <input class="bt-pal-q" type="text" role="combobox" aria-expanded="true" aria-controls="bt-pal-list" aria-autocomplete="list" spellcheck="false" autocomplete="off"
          placeholder="${mode === "beside" ? "Open a piece beside this one" : "Go to a piece, or do something"}">
        <div class="bt-pal-list" id="bt-pal-list" role="listbox" aria-label="${mode === "beside" ? "Pieces" : "Pieces and actions"}"></div></div>`;
      document.body.append(wrap);
      const input = wrap.querySelector("input"), list = wrap.querySelector(".bt-pal-list");
      R.pal = {wrap, input, list, mode, back, active: 0, shown: []};
      input.addEventListener("input", () => { R.pal.active = 0; Palette.render(); });
      input.addEventListener("keydown", Palette.key);
      wrap.addEventListener("mousedown", e => { if (!e.target.closest(".bt-pal")) { e.preventDefault(); Palette.close(); } });
      list.addEventListener("mousedown", e => e.preventDefault());
      list.addEventListener("mousemove", e => { const i = e.target.closest("[data-i]"); if (i && +i.dataset.i !== R.pal.active) { R.pal.active = +i.dataset.i; Palette.mark(); } });
      list.addEventListener("click", e => { const i = e.target.closest("[data-i]"); if (i) Palette.run(R.pal.shown[+i.dataset.i], e.altKey); });
      Palette.render();
      input.focus();
    },
    close(refocus = true) {
      const P = R.pal;
      if (!P) return;
      R.pal = null;
      P.wrap.remove();
      if (refocus) (P.back && P.back.isConnected && P.back !== document.body ? P.back : activePiece()?.text?.view.dom)?.focus();
    },
    items() {
      const W = R.W, P = R.pal, open = new Set([W.piece?.file, W.split?.piece?.file].filter(Boolean));
      // an untitled piece (a dedication) is its kind, in italic as in the list of pieces
      const pieces = W.book.contents.filter(e => e.file && !(P.mode === "beside" && e.file === W.piece?.file)).map(e => ({
        label: pieceTitle(e), untitled: !e.title, file: e.file,
        hint: [e.title ? pieceKindName(e.kind) : "", open.has(e.file) ? "open" : ""].filter(Boolean).join(" · ")}));
      return [["Pieces", pieces], ["Actions", P.mode === "beside" ? [] : actions()]];
    },
    render() {
      const P = R.pal, q = P.input.value.trim();
      const groups = Palette.items().map(([name, list]) => [name, q ? rank(list, q, x => x.label) : list]).filter(([, list]) => list.length);
      P.shown = groups.flatMap(([, list]) => list);
      P.active = Math.max(0, Math.min(P.active, P.shown.length - 1));
      let i = 0;
      P.list.innerHTML = groups.map(([name, list]) => `<div class="bt-pal-g" role="presentation">${esc(name)}</div>` + list.map(it => {
        const k = i++;
        return `<div class="bt-pal-i${it.file ? " piece" : ""}${it.untitled ? " untitled" : ""}" role="option" id="bt-pal-${k}" data-i="${k}" aria-selected="${k === P.active}"><span class="t">${highlight(it.label, q)}</span>${it.hint ? `<span class="h">${esc(it.hint)}</span>` : ""}</div>`;
      }).join("")).join("") || `<p class="bt-pal-none">Nothing by that name.</p>`;
      Palette.mark();
    },
    mark() {
      const P = R.pal;
      P.list.querySelectorAll("[data-i]").forEach(x => x.setAttribute("aria-selected", String(+x.dataset.i === P.active)));
      const cur = P.list.querySelector(`[data-i="${P.active}"]`);
      if (cur) { P.input.setAttribute("aria-activedescendant", cur.id); cur.scrollIntoView({block: "nearest"}); }
      else P.input.removeAttribute("aria-activedescendant");
    },
    key(e) {
      const P = R.pal;
      if (!P) return;
      const n = P.shown.length, move = d => { e.preventDefault(); if (n) { P.active = (P.active + d + n) % n; Palette.mark(); } };
      if (e.key === "ArrowDown" || (e.key === "Tab" && !e.shiftKey)) move(1);
      else if (e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey)) move(-1);
      else if (e.key === "PageDown") move(Math.min(8, n - 1 - P.active) || 0);
      else if (e.key === "PageUp") move(-Math.min(8, P.active) || 0);
      else if (e.key === "Enter") { e.preventDefault(); if (P.shown[P.active]) Palette.run(P.shown[P.active], e.altKey); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); Palette.close(); }
    },
    run(it, alt) {
      if (!it || !R.pal) return;
      const beside = R.pal.mode === "beside" || alt;
      Palette.close(!it.file);
      if (it.file) { if (beside) Split.open(it.file); else BookEditor.openPiece(it.file); }
      else it.run();
    },
  };

  /* ——— what the window says ——— */
  function mount(W) {
    Object.assign(R, {W, focus: false, focusPane: null, active: W, reading: null, find: null, sheetKey: JSON.stringify([W.book.style_sheet, W.book.language]),
      binderDefault: W.root.classList.contains("nobinder") ? "0" : "1"});
    R.prefs = {echoes: pref.get(PREF.echoes, "0") === "1", rhythm: pref.get(PREF.rhythm, "0") === "1",
      style: pref.get(PREF.style, "1") === "1", goal: pref.get(PREF.goal, "1") === "1"};
    mountTools();
    R.rail = root.BookRail ? root.BookRail.mount(W, api_) : null;
  }
  function unmount() {
    stopReading();
    Palette.close(false);
    Split.close(false);
    R.rail?.unmount();
    Object.assign(R, {W: null, rail: null, focus: false, focusPane: null, active: null, toolsEl: null, goalEl: null, find: null});
  }
  function opened(piece) {
    if (piece.win !== R.W) return;
    checkReading();
    if (R.focus && R.focusPane === R.W) { piece.text?.view.setProps({}); const T = piece.text; if (T) requestAnimationFrame(() => typewriter(T, false)); }
    Split.paint();
    R.rail?.pieceChanged();
    fit();                       // another piece: a poem has no rhythm gutter
  }
  /* the author showed or hid the list of pieces (Ctrl+\ or Pieces): shown, it must leave every text 360 px, or it goes again */
  function binderToggled(shown) {
    if (!shown || R.focus) { fit(); return; }
    if (fit("binder")) return;
    fit();                               // it gives way again; the author's setting stays, so it comes back when there is room
    toast(noRoom("binder"), true);
  }
  function refreshed(b) {
    checkReading();
    Split.look();
    const key = JSON.stringify([b.style_sheet, b.language]);
    if (key !== R.sheetKey) { R.sheetKey = key; recompute(); }
    paintTools();
    R.rail?.refresh(b);
  }
  function on(ev, a, b) {
    if (ev === "mount") return mount(a);
    if (!R.W) return;
    if (ev === "unmount") unmount();
    else if (ev === "open") opened(a);
    else if (ev === "refresh") refreshed(a);
    else if (ev === "state") Split.paint();
    else if (ev === "counts") goalLine(a);
    else if (ev === "saved") R.rail?.saved(a, b);
    else if (ev === "split") Split.open(a);
    else if (ev === "splitGone") Split.close(false);
    else if (ev === "addSource") R.rail?.open("sources", {add: true});
    else if (ev === "binder") binderToggled(a);
  }

  /* what the rail (book-rail.js) uses */
  const api_ = {
    get W() { return R.W; }, activePane, activePiece, panes, texts, paneOf, containersOf, matchesOf,
    setFind(f) { R.find = f; recompute(); },
    /* a panel opened or closed: the page gives it room */
    /* a panel opens or closes; false when it doesn't fit (it is then refused, and that is said) */
    railOpen(on) {
      const root = R.W.root;
      root.classList.toggle("railopen", on);
      if (!on) { fit(); return true; }
      if (fit("panel")) return true;
      root.classList.remove("railopen");         // the rail hides the panel and calls railOpen(false), which fits again
      toast(noRoom("panel", {split: !!R.W.split}), true);
      return false;
    },
    /* a panel shows: focus mode, which hides the rail, is left */
    leaveFocus() { if (R.focus) setFocus(false); },
    /* where the author writes in this text: a note's editor or the text (the last of them that had the cursor) */
    writingView(T) {
      const v = T.activeView();
      if (v !== T.view) return v;
      const last = T.lastView;
      return last && last !== T.view && [...T.margin.notes].some(nv => nv.inner === last) && !T.view.hasFocus() ? last : T.view;
    },
    get find() { return R.find; },
    split: file => Split.open(file),
    scrollTo(T, pos, frac = 0.3) {
      const scroller = paneOf(T)?.hosts.scroll;
      if (!scroller) return;
      const c = T.view.coordsAtPos(pos, 1), r = scroller.getBoundingClientRect();
      scroller.scrollTo({top: scroller.scrollTop + c.top - r.top - r.height * frac, behavior: reduced() ? "auto" : "smooth"});
    },
  };

  /* ——— keys ——— */
  addEventListener("keydown", e => {
    if (!R.W || state.view !== "book" || e.defaultPrevented && e.key !== "Escape") return;
    const mod = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
    if (mod && !e.altKey && !e.shiftKey && k === "k") { e.preventDefault(); if (R.pal) Palette.close(); else if (!$("#dlg").open) Palette.open(); return; }
    if (R.pal || $("#dlg").open) return;
    if (mod && e.shiftKey && !e.altKey && k === "f") { e.preventDefault(); setFocus(!R.focus); return; }
    if (mod && !e.shiftKey && !e.altKey && (k === "f" || k === "h") && R.rail) {
      e.preventDefault();
      const T = activePiece()?.text, v = T?.activeView?.(), sel = v?.state.selection;
      const text = sel && !sel.empty ? v.state.doc.textBetween(sel.from, sel.to, " ", " ").trim() : "";
      R.rail.open("find", {focus: k === "h" ? "repl" : "q", query: text.length < 80 && !text.includes("\n") ? text : ""});
      return;
    }
    if (e.key === "Escape" && !e.defaultPrevented) {
      const at = document.activeElement;
      if (R.focus) { e.preventDefault(); setFocus(false); }
      else if (R.W.split && at?.closest?.(".bw-split")) { e.preventDefault(); Split.close(); }
      else if (at?.closest?.(".bw-rail") && !at.closest(".bt-keep-esc")) { e.preventDefault(); activePiece()?.text?.focus(); }
    }
  });
  /* the editor last written in, per text (a note's, or the text's): Cite in the rail goes there */
  addEventListener("focusin", e => {
    for (const T of texts()) {
      if (T.view.dom.contains(e.target)) T.lastView = T.view;
      else { const nv = [...T.margin.notes].find(n => n.inner.dom.contains(e.target)); if (nv) T.lastView = nv.inner; }
    }
  });
  /* writing in the margin (a note, a comment) leaves focus mode: the margin is hidden there. Before the click that opens one
     reaches it, so the margin is back when the note or comment takes the focus. */
  addEventListener("focusin", e => { if (R.focus && e.target.closest?.(".bw-margin")) setFocus(false); });
  addEventListener("mousedown", e => {
    if (R.focus && e.button === 0 && e.target.closest?.(".bk-note-a, .bk-selbar [data-cmd=note], .bk-selbar [data-cmd=comment]")) setFocus(false);
  }, true);

  root.BookTools = {...helpers, plugins, on, setFocus, readAloud, Palette, Split, activePiece, get state() { return R; }};
})(typeof window !== "undefined" ? window : globalThis);
