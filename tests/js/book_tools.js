/* Runs the writing tools' pure helpers (studio/static/book-tools.js) in node. Used by tests/test_book_tools.py.

     node book_tools.js <prosemirror.js> <book-schema.js> <book-text.js> <book-tools.js>
     output: {"failures": [{"name", "got", "want"}], "checked": n}   */
"use strict";
const fs = require("fs"), vm = require("vm");
const [pm, schema, text, tools] = process.argv.slice(2);
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(pm, "utf8"));
if (typeof PM !== "undefined") globalThis.PM = PM;
vm.runInThisContext(fs.readFileSync(schema, "utf8"));
vm.runInThisContext(fs.readFileSync(text, "utf8"));
vm.runInThisContext(fs.readFileSync(tools, "utf8"));
const T = globalThis.BookTools, S = globalThis.BookSchema, node = json => globalThis.PM.Node.fromJSON(S, json);
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };
const flagged = (text, issues) => issues.map(i => [text.slice(i.from, i.to), i.fix]);

// numbers as words, Dutch and English
eq("Dutch 1–20", [1, 2, 7, 11, 14, 19, 20].map(n => T.numberWord(n, "nl")), ["één", "twee", "zeven", "elf", "veertien", "negentien", "twintig"]);
eq("Dutch 21–99 with en and a trema after e", [21, 22, 23, 24, 28, 38, 80, 99].map(n => T.numberWord(n, "nl")),
  ["eenentwintig", "tweeëntwintig", "drieëntwintig", "vierentwintig", "achtentwintig", "achtendertig", "tachtig", "negenennegentig"]);
eq("English", [1, 9, 12, 15, 20, 21, 40, 99].map(n => T.numberWord(n, "en")), ["one", "nine", "twelve", "fifteen", "twenty", "twenty-one", "forty", "ninety-nine"]);
eq("a region in the language tag", [T.numberWord(3, "nl-BE"), T.numberWord(3, "en-GB")], ["drie", "three"]);
eq("other languages have no words", [T.numberWord(3, "de"), T.numberWord(3, "fr")], [null, null]);

// the style sheet: numbers
const nums = (t, lang = "nl", upto = 10) => flagged(t, T.numberIssues(t, lang, upto));
eq("words to ten: 3, not 12", nums("Ze had 3 broers en 12 zussen."), [["3", "drie"]]);
eq("words to a hundred: 3 and 12", nums("Ze had 3 broers en 12 zussen.", "nl", 100), [["3", "drie"], ["12", "twaalf"]]);
eq("a digit before a full stop", nums("Ik was 3."), [["3", "drie"]]);
eq("at the start of a sentence: a capital", nums("3 mannen kwamen. 1 bleef. „2 gingen.”"), [["3", "Drie"], ["1", "Eén"], ["2", "Twee"]]);
eq("dates, times, decimals, years, references, units, money and codes are left alone",
  nums("Op 3 mei om 12:30 woog het 3,5 kilo; in 1984 zie p. 3 en hoofdstuk 4, 5 km, 50% en €5, 3D, A4, 07 of 0 en 3-4 of 1/2.", "nl", 100), []);
eq("English, and its months", nums("She had 3 cats. On May 3 or 3 May.", "en"), [["3", "three"]]);
eq("other languages: no number check", nums("Er waren 3.", "de"), []);
eq("upto 0 (digits): nothing", nums("Ze had 3 broers.", "nl", 0), []);

// the style sheet: terms
const terms = [{use: "e-mail", not: ["email", "E-mail"], note: ""}, {use: "oké", not: ["ok", "okay"], note: "Zo in de hele tekst"}];
const termText = "Stuur een email of E-mail. Email is ok. Een e-mail is oké. Okay? Een boek of ok-ish.";
eq("terms: the Not forms, whole words, a capital kept", flagged(termText, T.termIssues(termText, terms)),
  [["email", "e-mail"], ["E-mail", "e-mail"], ["Email", "E-mail"], ["ok", "oké"], ["Okay", "Oké"], ["ok", "oké"]]);
eq("terms: the tooltip, with the note", T.termIssues("Is het ok", terms).map(i => i.title), ["Style sheet: use oké · Zo in de hele tekst"]);
eq("terms: a form of more words", flagged("Dat is aan  de hand van iets.", T.termIssues("Dat is aan  de hand van iets.", [{use: "met", not: ["aan de hand van"], note: ""}])), [["aan  de hand van", "met"]]);
eq("terms: diacritics are letters", flagged("café cafe", T.termIssues("café cafe", [{use: "café", not: ["cafe"], note: ""}])), [["cafe", "café"]]);

// the style sheet: straight quotes
const qt = "Hij zei \"kom\" en 's avonds zo'n auto's.";
eq("straight quotes in „…”", flagged(qt, T.quoteIssues(qt, "„…”")), [["\"", "„"], ["\"", "”"], ["'", "’"], ["'", "’"], ["'", "’"]]);
eq("straight quotes in “…”", flagged("\"Ja\", zei ze.", T.quoteIssues("\"Ja\", zei ze.", "“…”")), [["\"", "“"], ["\"", "”"]]);
eq("the quote tooltip", T.quoteIssues("\"", "“…”")[0].title, "Style sheet: use “");
eq("the whole sheet", flagged("Ze zei \"3 keer ok\".", T.styleIssues("Ze zei \"3 keer ok\".", {quotes: "“…”", numbers: "words to ten", terms}, {lang: "nl", prose: true})),
  [["\"", "“"], ["3", "drie"], ["ok", "oké"], ["\"", "”"]]);
eq("not in prose (a heading): no numbers", flagged("Deel 3", T.styleIssues("Deel 3", {quotes: "“…”", numbers: "words to ten", terms: []}, {lang: "nl", prose: false})), []);
eq("digits: no numbers", flagged("Ze had 3", T.styleIssues("Ze had 3", {quotes: "“…”", numbers: "digits", terms: []}, {lang: "nl", prose: true})), []);

// echoes: words of five letters or more, again within 150 words
const words = s => T.wordsIn(s).map(w => w.w);
eq("words: apostrophes inside a word, hyphens apart", words("Het was ’s avonds, zo’n tien-tal auto's."), ["Het", "was", "s", "avonds", "zo’n", "tien", "tal", "auto's"]);
const para = "De zomer was lang. In die Zomer liepen we elke avond naar de zee, en de zee was stil omdat het geëerd werd, omdat wij het geëerd hadden.";
const ws = words(para), ech = T.echoes(ws, "nl").map(i => ws[i]);
eq("echoes: zomer (any case) and geëerd; not zee (short) or omdat (a function word)", ech, ["zomer", "Zomer", "geëerd", "geëerd"]);
const far = ["zomer", ...Array(150).fill("x"), "zomer", ...Array(149).fill("x"), "zomer"];
eq("echoes: 151 words on is too far, 150 is near", T.echoes(far, "nl"), [151, 301]);
eq("echoes: English function words", T.echoes(words("Which one, which other, there there"), "en"), []);

// sentences and their words
const sents = "Het was stil. Te stil! Waarom? „Kom je?” vroeg ze. Bijv. dit is geen nieuwe zin… maar wel lang";
eq("sentences", T.sentences(sents).map(s => [sents.slice(s.from, s.to), s.words]),
  [["Het was stil.", 3], ["Te stil!", 2], ["Waarom?", 1], ["„Kom je?” vroeg ze.", 4], ["Bijv. dit is geen nieuwe zin… maar wel lang", 9]]);
eq("no sentences in nothing", T.sentences("  "), []);

// fuzzy matching for the palette
eq("fuzzy: letters in order", !!T.fuzzy("hfdst", "Hoofdstuk één"), true);
eq("fuzzy: no match", T.fuzzy("xyz", "Chapter 1"), null);
eq("fuzzy: diacritics fold", T.fuzzy("een", "Één week aan zee").hits, [0, 1, 2]);
eq("fuzzy: ranks starts and shorter titles first", T.rank(["Epilogue", "Chapter 10", "Een kleine regen", "Chapter 1"], "ch1", x => x), ["Chapter 1", "Chapter 10"]);
eq("fuzzy: a word start beats letters scattered", T.rank(["Kleine regen", "Één week aan zee"], "een", x => x), ["Één week aan zee", "Kleine regen"]);
eq("fuzzy: spaces in the query are ignored", !!T.fuzzy("fo mo", "Focus mode"), true);

// authors as typed: Family, Given; Family, Given (with name particles)
const typedAuthors = "van Dijk, Anna; Jansen, M.; van den Berg, K.;  Rijksmuseum ; Dijk, Anna van; van 't Hof, A.";
const parsed = T.parseAuthors(typedAuthors);
eq("authors parsed", parsed, [
  {family: "Dijk", "non-dropping-particle": "van", given: "Anna"}, {family: "Jansen", given: "M."},
  {family: "Berg", "non-dropping-particle": "van den", given: "K."}, {literal: "Rijksmuseum"},
  {family: "Dijk", "non-dropping-particle": "van", given: "Anna"}, {family: "Hof", "non-dropping-particle": "van 't", given: "A."}]);
eq("authors written back", T.formatAuthors(parsed), "van Dijk, Anna; Jansen, M.; van den Berg, K.; Rijksmuseum; van Dijk, Anna; van 't Hof, A.");
eq("authors: round trip", T.parseAuthors(T.formatAuthors(parsed)), parsed);
eq("authors: a dropping particle reads as a particle", T.formatAuthors([{family: "Beethoven", "dropping-particle": "van", given: "Ludwig"}]), "van Beethoven, Ludwig");
eq("authors: spacing, a family name alone, lowercase names", T.parseAuthors("  van  Dijk ,  Anna ; Smit,; hooks, bell"),
  [{family: "Dijk", "non-dropping-particle": "van", given: "Anna"}, {family: "Smit"}, {family: "hooks", given: "bell"}]);
eq("authors: nothing", T.parseAuthors(" ; "), []);

// a new source's key
eq("key from the author and year", T.sourceKey({author: [{family: "Dijk", "non-dropping-particle": "van"}], issued: {"date-parts": [[2019]]}}, new Set()), "vandijk2019");
eq("key taken: b", T.sourceKey({author: [{family: "Dijk", "non-dropping-particle": "van"}], issued: {"date-parts": [[2019]]}}, new Set(["vandijk2019"])), "vandijk2019b");
eq("key from the title, without an article", T.sourceKey({title: "Het grote boek", issued: {"date-parts": [[2020]]}}, new Set()), "grote2020");
eq("key with diacritics folded", T.sourceKey({author: [{family: "Ångström"}]}, new Set()), "angstrom");
eq("key from nothing", T.sourceKey({}, new Set()), "source");
eq("keys can be cited", ["vandijk2019", "grote2020", "source"].every(k => globalThis.BookText.CITE_KEY.test(k)), true);

// find: the server's pattern (whole words, case), never across a note or a line break
eq("find: whole words, any case", T.findIn("De zee, de zeeën en de Zee.", "zee", {whole: true}), [[3, 6], [23, 26]]);
eq("find: case", T.findIn("De zee, de zeeën en de Zee.", "zee", {whole: true, case: true}), [[3, 6]]);
eq("find: inside words", T.findIn("De zee, de zeeën en de Zee.", "zee", {}), [[3, 6], [11, 14], [23, 26]]);
eq("find: an underscore is a word character", T.findIn("_zee zee", "zee", {whole: true}), [[5, 8]]);
eq("find: not across a note or a break", [T.findIn("ab￼c", "b￼c", {}), T.findIn("zee\nzee", "zee\nzee", {})], [[], []]);
eq("find: regex characters are literal", T.findIn("a.b (c) a*b", "(c)", {}), [[4, 7]]);

// history: paragraphs compared, then words inside a changed one
eq("diff by paragraph", T.diffBlocks(["a", "b c", "d"], ["a", "b x", "d", "e"]),
  [{t: "=", text: "a"}, {t: "~", from: "b c", to: "b x"}, {t: "=", text: "d"}, {t: "+", text: "e"}]);
eq("diff: removed and added", T.diffBlocks(["a", "b"], ["c"]), [{t: "~", from: "a", to: "c"}, {t: "-", text: "b"}]);
const pdoc = {type: "doc", attrs: {form: "prose"}, content: [
  {type: "title", content: [{type: "text", text: "Titel"}]},
  {type: "paragraph", content: [{type: "text", text: "Tekst"}, {type: "note", content: [{type: "text", text: "noot"}]}, {type: "text", text: " "},
    {type: "cite", attrs: {items: [{key: "key", prefix: "zie", locator: "p. 3"}]}}, {type: "text", text: " meer"}, {type: "hard_break"}, {type: "text", text: "regel"}]},
  {type: "scene_break"},
  {type: "blockquote", content: [{type: "paragraph", content: [{type: "text", text: "Citaat"}]}]},
  {type: "image", attrs: {src: "../images/a.png", alt: "Strand", width: null}},
  {type: "poem", attrs: {src: "Zee/Eb"}}]};
eq("the text of a piece, block by block", T.plainBlocks(pdoc), ["Titel", "Tekst^[noot] [zie @key, p. 3] meer\nregel", "* * *", "Citaat", "Image: Strand", "Linked poem: Zee/Eb"]);

// the outline of a piece
const odoc = node({type: "doc", attrs: {form: "prose"}, content: [
  {type: "title", content: [{type: "text", text: "T"}]},
  {type: "paragraph", content: [{type: "text", text: "a"}, {type: "note", content: [{type: "text", text: "Een noot die langer is dan veertig tekens, echt waar."}]}]},
  {type: "heading", attrs: {level: 2}, content: [{type: "text", text: "Kop"}]},
  {type: "scene_break"},
  {type: "heading", attrs: {level: 3}, content: [{type: "text", text: "Sub"}]},
  {type: "blockquote", content: [{type: "paragraph", content: [{type: "note"}]}]}]});
eq("outline", T.outline(odoc).map(o => [o.kind, o.level || 0, o.text, odoc.nodeAt(o.pos)?.type.name]),
  [["title", 1, "T", "title"], ["note", 0, "Een noot die langer is dan veertig tekens…", "note"], ["heading", 2, "Kop", "heading"],
   ["scene", 0, "", "scene_break"], ["heading", 3, "Sub", "heading"], ["note", 0, "", "note"]]);

// echoes: the tool says what it leaves out, and the words it leaves out are there (fix round 1, item 6)
eq("echoes' tooltip", (T.TOOLS.find(t => t[0] === "echoes") || [])[2], "Words of five letters or more that come back within 150 words, leaving out short common words");
eq("echoes leave out omdat, hebben, which, there", ["omdat", "hebben"].every(w => T.ECHO_STOP.nl.has(w)) && ["which", "there"].every(w => T.ECHO_STOP.en.has(w)), true);

// a source from the form: what the form can't show, or didn't change, stays as it was (item 8)
const raw = {id: "kust", type: "webpage", title: "De kust", author: [{family: "Beethoven", "dropping-particle": "van", given: "L."}],
  issued: {literal: "z.j."}, accessed: {raw: "voorjaar 2020"}, note: "eigen veld"};
const form = (o, f) => T.sourceItem(o, {type: o.type, title: o.title, authors: T.formatAuthors(o.author), year: T.dateText(o.issued),
  accessed: T.dateText(o.accessed), publisher: "", container: "", url: "", id: o.id, ...f});
eq("source: unchanged fields keep their own shape", form(raw, {}).item, raw);
eq("source: the accessed field shows a raw date", T.dateText(raw.accessed), "voorjaar 2020");
eq("source: a new accessed date is read", form(raw, {accessed: "2026-11-12"}).item.accessed, {"date-parts": [[2026, 11, 12]]});
eq("source: an accessed date that can't be read says so", form(raw, {accessed: "gisteren"}).error, "Write the date it was accessed as year-month-day, like 2026-11-12.");
eq("source: an emptied field goes", form(raw, {accessed: "", year: ""}).item.accessed === undefined && form(raw, {year: ""}).item.issued === undefined, true);
eq("source: a new year", form(raw, {year: "2019"}).item.issued, {"date-parts": [[2019]]});
eq("source: new authors", form(raw, {authors: "van Dijk, Anna"}).item.author, [{family: "Dijk", "non-dropping-particle": "van", given: "Anna"}]);
eq("source: a new one", T.sourceItem(null, {type: "book", title: " Zout ", authors: "", year: "2015", accessed: "", publisher: "Wad", container: "", url: "", id: "zout2015"}).item,
  {id: "zout2015", type: "book", title: "Zout", issued: {"date-parts": [[2015]]}, publisher: "Wad"});

// one piece is never in two editors, also while one of them is still opening it (item 10)
eq("where open: the first pane", T.whereOpen("a.md", {main: "a.md", split: "b.md"}), "main");
eq("where open: opening in the first pane", T.whereOpen("a.md", {main: "c.md", mainPending: "a.md"}), "main");
eq("where open: opening in the second pane", T.whereOpen("a.md", {main: "c.md", splitPending: "a.md"}), "split");
eq("where open: nowhere", T.whereOpen("a.md", {main: "c.md", split: "b.md"}), null);

// room (fix round 2): every text column at least 360 px; the list of pieces gives way first, then the gutters and notes
// margin, then the rhythm's gutter; what still doesn't fit is refused
const widths = table => state => table[[state.binder ? "list" : "", state.tight ? "tight" : "", state.compact ? "compact" : ""].filter(Boolean).join("+") || "plain"];
eq("room: plenty", T.giveWay(widths({"list": 500}), {binder: true, rhythm: false}), {state: {binder: true, tight: false, compact: false}, fits: true});
eq("room: the list goes first", T.giveWay(widths({"list": 300, "plain": 400}), {binder: true, rhythm: true}), {state: {binder: false, tight: false, compact: false}, fits: true});
eq("room: then the gutters and margin", T.giveWay(widths({"list": 200, "plain": 340, "tight": 370}), {binder: true, rhythm: true}), {state: {binder: false, tight: true, compact: false}, fits: true});
eq("room: then the rhythm's gutter", T.giveWay(widths({"plain": 300, "tight": 350, "tight+compact": 362}), {binder: false, rhythm: true}), {state: {binder: false, tight: true, compact: true}, fits: true});
eq("room: no rhythm, no compact step", T.giveWay(widths({"plain": 300, "tight": 350, "tight+compact": 400}), {binder: false, rhythm: false}).fits, false);
eq("room: the list asked for stays (and what doesn't fit is said)", T.giveWay(widths({"list": 300, "list+tight": 350, "list+tight+compact": 359, "plain": 500}), {binder: true, rhythm: true, keepBinder: true}),
  {state: {binder: true, tight: true, compact: true}, fits: false});
eq("room: the floor is 360", T.giveWay(widths({"plain": 360}), {binder: false, rhythm: false}).fits && !T.giveWay(widths({"plain": 359.5, "tight": 359.9}), {binder: false, rhythm: false}).fits, true);
eq("room: refusals in plain sentences", [T.noRoom("split", {panel: true}), T.noRoom("split", {}), T.noRoom("panel", {split: true}), T.noRoom("rhythm", {split: true}), T.noRoom("binder", {panel: true})], [
  "There isn't room for two pieces beside the panel at this width. Close the panel, or widen the window.",
  "There isn't room for two pieces side by side at this width. Widen the window.",
  "There isn't room for the panel beside two pieces at this width. Close the second pane, or widen the window.",
  "There isn't room for the rhythm's bars at this width. Close the panel or the second pane, or widen the window.",
  "There isn't room for the list of pieces at this width. Close the panel or the second pane, or widen the window."]);

// the rhythm (fix round 2): one scale, 1 px a word; 40 words at most (20 when compact); a gutter of at most 56 px
eq("rhythm: a bar per word count", [1, 12, 40, 75].map(n => T.rhythmBar(n)), [1, 12, 40, 40]);
eq("rhythm: compact caps at 20 words, same scale", [12, 30].map(n => T.rhythmBar(n, true)), [12, 20]);
eq("rhythm: the gutter", [T.RHYTHM.gutter, T.RHYTHM.compact, T.RHYTHM.gap], [56, 36, 12]);
eq("rhythm: bars and gap fit in the gutter", T.rhythmBar(1000) + T.RHYTHM.gap <= T.RHYTHM.gutter && T.rhythmBar(1000, true) + T.RHYTHM.gap <= T.RHYTHM.compact, true);

// changes on disk with the pieces open (item 1): everything locked, saved, changed, read again; typing that got in
// anyway is never read over; a save that fails stops it all
(async () => {
  const piece = (name, opts = {}) => {
    const log = [];
    return {name, log, dirty: false, closed: false, busy: false, conflict: null, ...opts,
      text: {lock: on => log.push(on ? "lock" : "unlock")},
      flush: async () => { log.push("flush"); return opts.flushOk ?? true; },
      reload: async q => { log.push("reload:" + q); },
      win: {bar: () => log.push("bar"), status: () => {}}};
  };
  const a = piece("A"), b = piece("B");
  let busyDuring = null;
  const r = await T.guarded([a, b], async () => { busyDuring = [a.busy, b.busy]; a.log.push("run"); b.dirty = true; return 7; }, {settled: async () => a.log.push("settled")});
  eq("guarded: the answer", r, 7);
  eq("guarded: busy while it runs, not after", [busyDuring, a.busy, b.busy], [[true, true], false, false]);
  eq("guarded: lock, wait, save, change, read again, unlock", a.log, ["lock", "settled", "flush", "run", "reload:false", "unlock"]);
  eq("guarded: a piece typed in meanwhile isn't read over: it gets the conflict bar", [b.log, !!b.conflict], [["lock", "flush", "bar", "unlock"], true]);
  const f = piece("F");
  await T.guarded([f], async () => { f.dirty = true; }, {by: "replace"});
  eq("guarded: the conflict says what changed the piece (Keep mine keeps that text in History)", f.conflict, {by: "replace"});
  const c = piece("C", {flushOk: false});
  let ran = false, err = null;
  try { await T.guarded([c], async () => { ran = true; }); } catch (e) { err = e.message; }
  eq("guarded: a save that fails stops it", [ran, err, c.log, c.busy], [false, "C has changes that couldn't be saved, so nothing was changed. Its text is as you left it", ["lock", "flush", "unlock"], false]);
  const d = piece("D");
  try { await T.guarded([d], async () => { throw new Error("schijf vol"); }); } catch (e) { err = e.message; }
  eq("guarded: a change that fails: nothing read again, unlocked", [err, d.log], ["schijf vol", ["lock", "flush", "unlock"]]);
  const e = piece("E", {closed: true});
  await T.guarded([e], async () => 1);
  eq("guarded: closed pieces take no part", e.log, []);
  console.log(JSON.stringify({failures, checked}));
})();
