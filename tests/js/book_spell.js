/* Runs the spelling plugin's pure helpers (studio/static/book-spell.js) in node: which dictionary a language uses, which
   words of a document are checked and in which languages, and which are left alone. Used by tests/test_spelling.py.

     node book_spell.js <prosemirror.js> <book-schema.js> <book-text.js> <book-tools.js> <book-spell.js>
     output: {"failures": [{"name", "got", "want"}], "checked": n}   */
"use strict";
const fs = require("fs"), vm = require("vm");
const files = process.argv.slice(2);
globalThis.window = globalThis;
for (const f of files) {
  vm.runInThisContext(fs.readFileSync(f, "utf8"), {filename: f});
  if (typeof PM !== "undefined") globalThis.PM = PM;
}
const B = globalThis.BookSpell, S = globalThis.BookSchema, node = json => globalThis.PM.Node.fromJSON(S, json);
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };

// the bundled dictionaries: nl, en (en-US and every other English) and en-GB
eq("dictionaries", ["nl", "nl-BE", "NL", "en", "en-US", "en-us", "en-GB", "en_gb", "de", "", null].map(B.dictOf),
  ["nl", "nl", "nl", "en", "en", "en", "en-GB", "en-GB", null, null, null]);
eq("covers", ["nl", "nl-NL", "en", "en-GB", "fr", "de-AT"].map(B.covers), [true, true, true, true, false, false]);
eq("a book's languages, without the ones that have no dictionary", B.dictsFor(["nl", "en", "fr"]), ["nl", "en"]);
eq("en-US and en are one dictionary", B.dictsFor(["en-US", "en"]), ["en"]);
eq("a text whose own language has no dictionary is not checked", B.dictsFor(["de", "en"]), []);
eq("nothing", B.dictsFor([]), []);

// words left alone: digits, all capitals, a single letter, the book's word list (as written or in lower case)
const list = B.wordList(["Pietje", "gigantsiche", "zo’n"]);
const skip = w => B.skipped(w, list);
eq("digits", ["3D", "A4", "1984", "tweede"].map(skip), [true, true, true, false]);
eq("all capitals", ["NAVO", "IJ", "Navo", "iPhone"].map(skip), [true, true, false, false]);
eq("single letters", ["a", "é", "ik"].map(skip), [true, true, false]);
eq("the word list", ["Pietje", "pietje", "gigantsiche", "Gigantsiche", "GIGANTSICHE", "zo’n", "zo'n", "Zo’n", "anders"].map(skip),
  [true, false, true, true, true, true, true, true, false]);
eq("apostrophes are one kind", B.plain("zo’n auto‘s"), "zo'n auto's");

// the runs of a document: per language, words and their positions; notes (their own editor), citations left out
const doc = node({type: "doc", content: [
  {type: "title", content: [{type: "text", text: "Een titel"}]},
  {type: "paragraph", content: [
    {type: "text", text: "Op maandag zag ik "},
    {type: "text", text: "a beautfil day", marks: [{type: "lang", attrs: {lang: "en"}}]},
    {type: "text", text: " in de "},
    {type: "text", text: "kliniek", marks: [{type: "em"}]},
    {type: "cite", attrs: {items: [{key: "smit2020"}]}},
    {type: "text", text: " zo’n e-mail van 3 NAVO-leden"},
    {type: "note", content: [{type: "text", text: "Een notitie"}]},
    {type: "text", text: "."},
  ]},
  {type: "scene_break"},
  {type: "poem", content: [{type: "paragraph", content: [{type: "text", text: "Ein Lied", marks: [{type: "lang", attrs: {lang: "de"}}]}]}]},
]});
const langs = ["nl", "en"];
const all = B.runsIn(doc, 0, doc.content.size, langs);
const shape = r => ({lang: r.lang, dicts: r.dicts, words: r.words.map(w => w.w)});
eq("runs", all.runs.map(shape), [
  {lang: null, dicts: ["nl", "en"], words: ["Een", "titel"]},
  {lang: null, dicts: ["nl", "en"], words: ["Op", "maandag", "zag", "ik"]},
  {lang: "en", dicts: ["en"], words: ["a", "beautfil", "day"]},
  {lang: null, dicts: ["nl", "en"], words: ["in", "de", "kliniek"]},
  {lang: null, dicts: ["nl", "en"], words: ["zo’n", "e", "mail", "van", "3", "NAVO", "leden"]},
  {lang: null, dicts: ["nl", "en"], words: []},
  {lang: "de", dicts: [], words: ["Ein", "Lied"]},
]);
eq("every word is where it says", all.runs.flatMap(r => r.words).filter(w => doc.textBetween(w.from, w.to) !== w.w).map(w => w.w), []);
eq("a run is where it says", all.runs.filter(r => r.lang).map(r => doc.textBetween(r.from, r.to)), ["a beautfil day", "Ein Lied"]);
eq("the whole document's blocks: the title to the poem's line", all.hull, {from: 0, to: doc.content.size - 1});
const toCheck = B.wordsToCheck(all.runs, list, new Set()).map(w => [w.w, w.dicts]);
eq("the words to check", toCheck, [["Een", ["nl", "en"]], ["titel", ["nl", "en"]], ["Op", ["nl", "en"]], ["maandag", ["nl", "en"]],
  ["zag", ["nl", "en"]], ["ik", ["nl", "en"]], ["beautfil", ["en"]], ["day", ["en"]], ["in", ["nl", "en"]], ["de", ["nl", "en"]],
  ["kliniek", ["nl", "en"]], ["mail", ["nl", "en"]], ["van", ["nl", "en"]], ["leden", ["nl", "en"]]]);
eq("ignored for the session", B.wordsToCheck(all.runs, list, new Set(["maandag", "kliniek"])).map(w => w.w).includes("maandag"), false);

// only the blocks a change touches
const para = doc.child(1), paraFrom = doc.child(0).nodeSize, paraTo = paraFrom + para.nodeSize;
const part = B.runsIn(doc, paraFrom + 5, paraFrom + 6, langs);
eq("a change in a paragraph: its blocks", part.hull, {from: paraFrom, to: paraTo});
eq("a change in a paragraph: its words", part.runs.flatMap(r => r.words).map(w => w.w).slice(0, 4), ["Op", "maandag", "zag", "ik"]);
eq("a change in a scene break: no words", B.runsIn(doc, paraTo + 1, paraTo + 1, langs).runs, []);

// a note's own editor: the note is the document
const note = node({type: "note", content: [{type: "text", text: "Een "}, {type: "text", text: "gigantsiche", marks: [{type: "strong"}]}, {type: "hard_break"}, {type: "text", text: "notitie"}]});
const inNote = B.runsIn(note, 0, note.content.size, langs);
eq("a note's words", inNote.runs.flatMap(r => r.words).map(w => [w.w, note.textBetween(w.from, w.to)]),
  [["Een", "Een"], ["gigantsiche", "gigantsiche"], ["notitie", "notitie"]]);
eq("a note's blocks", inNote.hull, {from: 0, to: note.content.size});

// a Dutch book with an English span, in a German book, and with only the book's own language
eq("an English span in a German book is checked", B.runsIn(doc, 0, doc.content.size, ["de", "en"]).runs.map(r => r.dicts),
  [[], [], ["en"], [], [], [], []]);
eq("a book of one language", B.runsIn(doc, 0, doc.content.size, ["nl"]).runs[0].dicts, ["nl"]);

process.stdout.write(JSON.stringify({failures, checked}));
