/* Runs the formatting of the writing window (studio/static/book-format.js) in node: markers, typing triggers, list keys
   and commands, the numbers plugin; alignment, text styles, sizes, marks, clear formatting, what applies and what is on,
   the keys, Make a list of these lines. Used by tests/test_book_format.py.

     node book_format.js <prosemirror.js> <book-schema.js> <book-format.js> <input.json>
     input: {"samples": [{"doc": document, "markers": manuscript_lists.markers(doc content)}],
             "reload": {scenario: document parsed from the scenario's Markdown}}
     output: {"failures": [{"name", "got", "want"}], "checked": n, "reload": {scenario: document after its edit}}   */
"use strict";
const fs = require("fs"), vm = require("vm");
const [pm, schema, format, input] = process.argv.slice(2);
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(pm, "utf8"));
if (typeof PM !== "undefined") globalThis.PM = PM;
vm.runInThisContext(fs.readFileSync(schema, "utf8"));
vm.runInThisContext(fs.readFileSync(format, "utf8"));
const F = globalThis.BookFormat, S = globalThis.BookSchema, P = globalThis.PM, C = F.commands;
const failures = [];
let checked = 0;
const eq = (name, got, want) => { checked++; if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({name, got, want}); };
const IN = JSON.parse(fs.readFileSync(input, "utf8"));

/* ——— documents and states ——— */
const txt = s => ({type: "text", text: s});
const para = s => (s ? {type: "paragraph", content: [txt(s)]} : {type: "paragraph"});
const item = (list, s, level = 0, start = null) => Object.assign({type: "list_item", attrs: {list, level, start}}, s ? {content: [txt(s)]} : {});
const dec = (s, level, start) => item("decimal", s, level, start);
const docOf = (blocks, form = "prose") => P.Node.fromJSON(S, {type: "doc", attrs: {form}, content: blocks});
const posOf = (doc, i) => { let p = 0; for (let k = 0; k < i; k++) p += doc.child(k).nodeSize; return p; };
/* the cursor in top-level block i at offset (its end when null) */
const cursor = (doc, i, offset = null) => posOf(doc, i) + 1 + (offset == null ? doc.child(i).content.size : offset);
const plugins = () => [P.inputRules({rules: F.inputRules()}), P.history(), F.numbersPlugin()];
/* a state on `blocks` with the cursor in block i at offset, or at `pos` when i is {pos} */
function make(blocks, i = 0, offset = null, form = "prose") {
  const doc = docOf(blocks, form), at = typeof i === "object" ? i.pos : cursor(doc, i, offset);
  return P.EditorState.create({doc, plugins: plugins(), selection: P.TextSelection.create(doc, at)});
}
const moveTo = (state, i, offset = null) => state.apply(state.tr.setSelection(P.TextSelection.create(state.doc, cursor(state.doc, i, offset))));
const select = (state, from, to) => state.apply(state.tr.setSelection(P.TextSelection.create(state.doc, from, to)));
/* a command on a state: [what it returned, the state after it] */
function run(state, cmd) { let next = state; const ok = cmd(state, tr => { next = next.apply(tr); }); return [ok, next]; }
const after = (state, cmd) => run(state, cmd)[1];
/* types `text` as the editor does: the input rules first (handleTextInput, as prosemirror-inputrules' own tests), else
   the text goes in as typed */
function type(state, text) {
  for (const ch of text) {
    const view = {composing: false, state, dispatch(tr) { this.state = this.state.apply(tr); }};
    const {from, to} = state.selection;
    if (!state.plugins.some(p => p.props.handleTextInput && p.props.handleTextInput(view, from, to, ch))) view.dispatch(state.tr.insertText(ch, from, to));
    state = view.state;
  }
  return state;
}
const change = state => state.apply(state.tr.insertText("!", state.doc.content.size - 1));   // any edit: the plugin runs
/* the blocks: [list, level, start, text] for an item, [type, text] for anything else */
const shape = state => state.doc.content.content.map(n => n.type.name === "list_item"
  ? [n.attrs.list, n.attrs.level, n.attrs.start, n.textContent] : [n.type.name, n.textContent]);
const shown = state => F.markers(state.doc).map(m => m && m.marker);
const json = state => JSON.stringify(state.doc.toJSON());

/* ——— markers: the same as manuscript_lists.markers for every sample ——— */
IN.samples.forEach((s, i) => eq(`markers:parity sample ${i}`,
  F.markers(P.Node.fromJSON(S, s.doc)).map(m => m && {marker: m.marker, level: m.level, list: m.list, n: m.n, first: m.first, run: m.run}),
  s.markers));
const posDoc = docOf([{type: "title", content: [txt("T")]}, dec("Een"), para("Tekst"), item("bullet", "Twee")]);
eq("markers:pos is each block's position", F.markers(posDoc).map(m => m && m.pos), [null, 3, null, 15]);
eq("markerText", [F.markerText("bullet", 1, 0), F.markerText("bullet", 4, 1), F.markerText("bullet", 1, 2), F.markerText("bullet", 1, 3),
  F.markerText("decimal", 12, 0), F.markerText("decimal", 0, 0), F.markerText("lower-alpha", 28, 0), F.markerText("upper-alpha", 2, 1),
  F.markerText("lower-roman", 4, 2), F.markerText("upper-roman", 1999, 0)],
  ["•", "◦", "▪", "•", "12.", "0.", "ab.", "B.", "iv.", "MCMXCIX."]);
eq("STYLES, NEST, MAX_LEVEL", [F.STYLES, F.NEST, F.MAX_LEVEL],
  [["bullet", "decimal", "lower-alpha", "upper-alpha", "lower-roman", "upper-roman"], ["decimal", "lower-alpha", "lower-roman", "decimal"], 3]);

/* ——— typing ——— */
const typed = (text, blocks = [para()], i = 0, offset = 0, form = "prose") => type(make(blocks, i, offset, form), text);
eq("type:bullet - ", shape(typed("- Een")), [["bullet", 0, null, "Een"]]);
eq("type:bullet •", shape(typed("• Een")), [["bullet", 0, null, "Een"]]);
eq("type:bullet leaves the cursor in the item", typed("- ").selection.from, 1);
eq("type:number 3.", shape(typed("3. Drie")), [["decimal", 0, 3, "Drie"]]);
eq("type:number 1) starts at 1", shape(typed("1) Een")), [["decimal", 0, null, "Een"]]);
eq("type:number 12. and 0.", [shape(typed("12. x")), shape(typed("0. x"))], [[["decimal", 0, 12, "x"]], [["decimal", 0, 0, "x"]]]);
eq("type:letters", ["a. ", "A. ", "i. ", "I. ", "a) ", "A) ", "i) ", "I) "].map(t => shape(typed(t + "x"))[0]),
  [["lower-alpha", 0, null, "x"], ["upper-alpha", 0, null, "x"], ["lower-roman", 0, null, "x"], ["upper-roman", 0, null, "x"],
   ["lower-alpha", 0, null, "x"], ["upper-alpha", 0, null, "x"], ["lower-roman", 0, null, "x"], ["upper-roman", 0, null, "x"]]);
eq("type:no-J J. stays text", shape(typed("J. kwam later")), [["paragraph", "J. kwam later"]]);
eq("type:no-J other letters and numerals stay text", ["b. ", "c) ", "ii. ", "IV. ", "aa. "].map(t => shape(typed(t))[0]),
  [["paragraph", "b. "], ["paragraph", "c) "], ["paragraph", "ii. "], ["paragraph", "IV. "], ["paragraph", "aa. "]]);
eq("type:star * stays text", [shape(typed("* ster")), shape(typed("* * *"))], [[["paragraph", "* ster"]], [["paragraph", "* * *"]]]);
eq("type:keeps-rest", shape(typed("- ", [para("Rest van de zin")])), [["bullet", 0, null, "Rest van de zin"]]);
eq("type:only at the start", shape(typed(" - x", [para("Een")], 0, 3)), [["paragraph", "Een - x"]]);
eq("type:not in a heading", shape(typed("- ", [{type: "heading", attrs: {level: 2}}])), [["heading", "- "]]);
eq("type:not in the title", shape(typed("1. ", [{type: "title"}, para("x")])), [["title", "1. "], ["paragraph", "x"]]);
eq("type:not in a quotation", shape(typed("- ", [{type: "blockquote", content: [para()]}], {pos: 2})), [["blockquote", "- "]]);
const continued = typed("3. Drie", [dec("Een"), dec("Twee"), para()], 2);
eq("type:continues a list above (no start)", [shape(continued), shown(continued)],
  [[["decimal", 0, null, "Een"], ["decimal", 0, null, "Twee"], ["decimal", 0, null, "Drie"]], ["1.", "2.", "3."]]);

/* one Backspace (undoInputRule) right after a trigger gives back what was typed */
const undone = (state) => run(state, P.undoInputRule);
eq("undo:trigger - ", (([ok, st]) => [ok, shape(st), st.selection.from])(undone(typed("- "))), [true, [["paragraph", "- "]], 3]);
eq("undo:trigger a. before text", shape(undone(typed("a. ", [para("Rest")]))[1]), [["paragraph", "a. Rest"]]);
const above = typed("1. ", [para(), dec("Een"), dec("Twee")]);
eq("undo:trigger a list joined", shown(above), ["1.", "2.", "3."]);
const aboveBack = undone(above)[1];
eq("undo:trigger a list joined: its numbers back", [shape(aboveBack), shown(aboveBack)],
  [[["paragraph", "1. "], ["decimal", 0, null, "Een"], ["decimal", 0, null, "Twee"]], [null, "1.", "2."]]);
// a list that started at 4 starts at 4 again (counting on from the taken-back item would give 1)
const aboveFour = undone(typed("1. ", [para(), dec("Vier", 0, 4), dec("Vijf")]))[1];
eq("undo:trigger a list joined: its start back", [shape(aboveFour)[1], shown(aboveFour)], [["decimal", 0, 4, "Vier"], [null, "4.", "5."]]);
eq("undo:trigger continuing", shape(undone(typed("3. ", [dec("Een"), dec("Twee"), para()], 2))[1]),
  [["decimal", 0, null, "Een"], ["decimal", 0, null, "Twee"], ["paragraph", "3. "]]);

/* ——— poems are left alone ——— */
const poemPiece = make([para()], 0, 0, "poem");
const poemBlock = make([para("Proza."), {type: "poem", attrs: {src: null}, content: [para()]}], {pos: 10});
eq("poem:no-list no trigger in a poem piece", shape(type(poemPiece, "- 1. a. ")), [["paragraph", "- 1. a. "]]);
eq("poem:no-list no trigger in a ::: poem block", shape(type(poemBlock, "- ")), [["paragraph", "Proza."], ["poem", "- "]]);
eq("poem:no-list setList refuses", [C.setList("bullet")(poemPiece), C.setList("decimal")(poemBlock),
  C.setList("bullet")(make([para("Een"), para("Twee")], 0, 0, "poem"), () => {})], [false, false, false]);
eq("poem:tab list keys refuse in a poem line", [C.listTab(poemPiece), C.listShiftTab(poemPiece), C.listTab(poemBlock), C.listShiftTab(poemBlock),
  C.listEnter(poemBlock), C.listBackspace(poemBlock)], [false, false, false, false, false, false]);
eq("poem:tab even on an item in a poem piece", C.listTab(make([dec("Een"), dec("Twee")], 1, 0, "poem")), false);

/* ——— Enter ——— */
const split = after(make([dec("Een twee", 0, 3)], 0, 4), C.listEnter);
eq("enter:split", [shape(split), shown(split), split.selection.from], [[["decimal", 0, 3, "Een "], ["decimal", 0, null, "twee"]], ["3.", "4."], 7]);
const splitSub = after(make([dec("Een"), item("lower-alpha", "Sub", 1)], 1), C.listEnter);
eq("enter:split a nested item", [shape(splitSub), shown(splitSub)],
  [[["decimal", 0, null, "Een"], ["lower-alpha", 1, null, "Sub"], ["lower-alpha", 1, null, ""]], ["1.", "a.", "b."]]);
const splitSel = after(select(make([item("bullet", "Een twee drie")]), 5, 9), C.listEnter);
eq("enter:split replaces the selection", shape(splitSel), [["bullet", 0, null, "Een "], ["bullet", 0, null, " drie"]]);
const emptySub = after(make([dec("Een"), item("lower-alpha", "Sub", 1), item("lower-alpha", "", 1)], 2), C.listEnter);
eq("enter:empty-nested one level out", [shape(emptySub)[2], shown(emptySub)], [["decimal", 0, null, ""], ["1.", "a.", "2."]]);
eq("enter:empty-top a paragraph", shape(after(make([dec("Een"), dec("")], 1), C.listEnter)), [["decimal", 0, null, "Een"], ["paragraph", ""]]);
// the list goes on counting across the paragraph, as in Word and Docs
const ended = after(make([dec("Een"), dec(""), dec("Drie"), dec("Vier")], 1), C.listEnter);
eq("enter:keep-numbers", [shape(ended), shown(ended)],
  [[["decimal", 0, null, "Een"], ["paragraph", ""], ["decimal", 0, 2, "Drie"], ["decimal", 0, null, "Vier"]], ["1.", null, "2.", "3."]]);
eq("enter:not in a paragraph", C.listEnter(make([para("Een")])), false);

/* ——— Backspace at an item's start ——— */
const back1 = run(make([dec("Een"), item("lower-alpha", "Sub", 1)], 1, 0), C.listBackspace);
eq("backspace:start one level out", [back1[0], shape(back1[1])[1], shown(back1[1])], [true, ["decimal", 0, null, "Sub"], ["1.", "2."]]);
eq("backspace:start then a paragraph", shape(after(back1[1], C.listBackspace))[1], ["paragraph", "Sub"]);
eq("backspace:start only at the start, with nothing selected", [C.listBackspace(make([dec("Een")], 0, 1)),
  C.listBackspace(select(make([dec("Een")]), 1, 3)), C.listBackspace(make([para("Een")], 0, 0))], [false, false, false]);

/* ——— Tab and Shift+Tab ——— */
const tabbed = (blocks, i, cmd = C.listTab) => run(make(blocks, i), cmd);
const in1 = tabbed([dec("Een"), dec("Twee"), dec("Drie")], 1);
eq("tab:in decimal → lower-alpha", [in1[0], shape(in1[1]), shown(in1[1])],
  [true, [["decimal", 0, null, "Een"], ["lower-alpha", 1, null, "Twee"], ["decimal", 0, null, "Drie"]], ["1.", "a.", "2."]]);
eq("tab:in bullet stays bullet", shown(tabbed([item("bullet", "Een"), item("bullet", "Twee")], 1)[1]), ["•", "◦"]);
eq("tab:in deeper: roman, then numbers again", [shape(tabbed([dec("a"), item("lower-alpha", "b", 1), item("lower-alpha", "c", 1)], 2)[1])[2],
  shape(tabbed([dec("a"), item("lower-alpha", "b", 1), item("lower-roman", "c", 2), item("lower-roman", "d", 2)], 3)[1])[3]],
  [["lower-roman", 2, null, "c"], ["decimal", 3, null, "d"]]);
eq("tab:in takes the style of an item just above at that level",
  [shown(tabbed([dec("Een"), item("upper-roman", "Twee", 1), dec("Drie")], 2)[1]),
   shown(tabbed([dec("Een"), item("lower-alpha", "Twee", 1), item("lower-roman", "Drie", 2), dec("Vier")], 3)[1])],
  [["1.", "I.", "II."], ["1.", "a.", "i.", "b."]]);
eq("tab:in not from a sublist above a shallower item", shown(tabbed([dec("Een"), item("upper-alpha", "Twee", 1), dec("Drie"), dec("Vier")], 3)[1]),
  ["1.", "A.", "2.", "a."]);
const tooDeep = make([dec("Een"), item("lower-alpha", "Twee", 1)], 1), tooDeepRun = run(tooDeep, C.listTab);
eq("tab:in not deeper than the item before + 1", [tooDeepRun[0], json(tooDeepRun[1]) === json(tooDeep), C.indent(1)(tooDeep)], [true, true, false]);
const deepest = make([dec("a"), item("lower-alpha", "b", 1), item("lower-roman", "c", 2), dec("d", 3), dec("e", 3)], 4);
eq("tab:in not past level 3", [run(deepest, C.listTab)[0], json(run(deepest, C.listTab)[1]) === json(deepest), C.indent(1)(deepest)], [true, true, false]);
eq("tab:in the first item stays", json(tabbed([dec("Een"), dec("Twee")], 0)[1]) === json(make([dec("Een"), dec("Twee")], 0)), true);
const out1 = tabbed([dec("Een"), item("lower-alpha", "Twee", 1), item("lower-alpha", "Drie", 1)], 2, C.listShiftTab);
eq("tab:out rejoins the parent list's style", [out1[0], shape(out1[1])[2], shown(out1[1])], [true, ["decimal", 0, null, "Drie"], ["1.", "a.", "2."]]);
eq("tab:out into a sublist above", shown(tabbed([dec("Een"), item("lower-alpha", "Twee", 1), item("lower-roman", "Drie", 2)], 2, C.listShiftTab)[1]),
  ["1.", "a.", "b."]);
eq("tab:out a bullet under numbers", shape(tabbed([dec("Een"), item("bullet", "Twee", 1)], 1, C.listShiftTab)[1])[1], ["decimal", 0, null, "Twee"]);
const top = make([dec("Een"), dec("Twee")], 1), topRun = run(top, C.listShiftTab);
eq("tab:top Shift+Tab at level 0 keeps the key and changes nothing", [topRun[0], json(topRun[1]) === json(top), C.indent(-1)(top)], [true, true, false]);
eq("tab:outside a list the keys pass", [C.listTab(make([para("Een")])), C.listShiftTab(make([para("Een")]))], [false, false]);
const two = make([dec("Een"), dec("Twee"), dec("Drie")]);
const twoIn = after(select(two, cursor(two.doc, 1, 0), cursor(two.doc, 2, 2)), C.listTab);
eq("tab:in every selected item", shown(twoIn), ["1.", "a.", "b."]);
eq("tab:out every selected item", shown(after(select(twoIn, cursor(twoIn.doc, 1, 0), cursor(twoIn.doc, 2, 2)), C.listShiftTab)), ["1.", "2.", "3."]);
// out goes bottom to top, so a deeper selected item isn't flattened by the one above it going out first
const mixed = make([dec("Een"), item("lower-alpha", "a", 1), item("lower-roman", "i", 2), item("lower-roman", "ii", 2), dec("Twee")]);
const mixedOut = after(select(mixed, cursor(mixed.doc, 1, 0), cursor(mixed.doc, 3, 1)), C.listShiftTab);
eq("tab:out every selected item keeps their nesting", [shown(mixedOut), shape(mixedOut).map(b => b[1])], [["1.", "2.", "a.", "b.", "3."], [0, 0, 1, 1, 0]]);

/* ——— setList ——— */
const p1 = make([para("Een")]), p2 = after(p1, C.setList("decimal"));
eq("setList:toggle paragraph → decimal → paragraph", [shape(p2), shape(after(p2, C.setList("decimal")))],
  [[["decimal", 0, null, "Een"]], [["paragraph", "Een"]]]);
eq("setList:toggle bullet → decimal keeps level", shape(after(make([item("bullet", "Een"), item("bullet", "Twee", 1)], 1), C.setList("decimal"))),
  [["bullet", 0, null, "Een"], ["decimal", 1, null, "Twee"]]);
const three = make([para("Een"), para("Twee"), para("Drie")]);
const threeList = after(select(three, 1, three.doc.content.size - 1), C.setList("bullet"));
eq("setList:toggle several paragraphs become one list", [shape(threeList), F.markers(threeList.doc).map(m => m.first)],
  [[["bullet", 0, null, "Een"], ["bullet", 0, null, "Twee"], ["bullet", 0, null, "Drie"]], [true, false, false]]);
eq("setList:toggle all of them back", shape(after(select(threeList, 1, threeList.doc.content.size - 1), C.setList("bullet"))),
  [["paragraph", "Een"], ["paragraph", "Twee"], ["paragraph", "Drie"]]);
eq("setList:toggle without dispatch only answers", [C.setList("decimal")(p1), json(p1) === json(make([para("Een")]))], [true, true]);
eq("setList:toggle not in the title or a quotation", [C.setList("bullet")(make([{type: "title", content: [txt("T")]}, para("x")], 0)),
  C.setList("bullet")(make([{type: "blockquote", content: [para("Citaat")]}], {pos: 2}))], [false, false]);

/* ——— the numbers plugin ——— */
eq("numbers:levels clamped", shape(change(make([dec("Een", 2), dec("Twee", 3), dec("Drie", 3)]))).map(b => b[1]), [0, 1, 2]);
eq("numbers:start-dropped from items that continue a list", shape(change(make([dec("Een", 0, 4), dec("Twee", 0, 7), item("bullet", "b", 0, 3), dec("x", 0, 1)])))
  .map(b => b[2]), [4, null, null, null]);
const list4 = () => make([dec("Een"), dec("Twee"), dec("Drie"), dec("Vier")]);
const between = (st => st.apply(st.tr.insert(posOf(st.doc, 2), S.nodes.scene_break.create())))(list4());
eq("numbers:block-between", [shape(between)[3], shape(between)[4], shown(between)], [["decimal", 0, 3, "Drie"], ["decimal", 0, null, "Vier"], ["1.", "2.", null, "3.", "4."]]);
const deleted = (st => st.apply(st.tr.delete(0, posOf(st.doc, 2))))(list4());
eq("numbers:deleted-renumber", [shape(deleted), shown(deleted)], [[["decimal", 0, null, "Drie"], ["decimal", 0, null, "Vier"]], ["1.", "2."]]);
const deletedText = (st => st.apply(st.tr.delete(1, cursor(st.doc, 2, 0))))(list4());
eq("numbers:deleted-renumber across items", [shape(deletedText), shown(deletedText)], [[["decimal", 0, null, "Drie"], ["decimal", 0, null, "Vier"]], ["1.", "2."]]);
eq("numbers:counts on across another style", shown(after(moveTo(list4(), 1), C.setList("bullet"))), ["1.", "•", "2.", "3."]);
const twoBullets = (st => after(select(st, cursor(st.doc, 1, 0), cursor(st.doc, 2, 1)), C.setList("bullet")))(list4());
eq("numbers:counts on across several blocks", [shown(twoBullets), shape(twoBullets)[3]], [["1.", "•", "•", "2."], ["decimal", 0, 2, "Vier"]]);
eq("numbers:an item given another style starts its own list", shown(after(moveTo(list4(), 2), C.setList("lower-alpha"))), ["1.", "2.", "a.", "3."]);
const twoBreaks = (st => st.apply(st.tr.insert(posOf(st.doc, 3), S.nodes.scene_break.create()).insert(posOf(st.doc, 1), S.nodes.scene_break.create())))(
  make([dec("Een"), dec("Twee"), dec("Drie"), dec("Vier"), dec("Vijf")]));
eq("numbers:counts on across two blocks put in at once", shown(twoBreaks), ["1.", null, "2.", "3.", null, "4.", "5."]);
// a list that counted on from the one above (start = its last number + 1) is the same list; a fresh one is not
const backAt = (blocks, i) => shown(after(make(blocks, i, 0), C.listBackspace));
eq("numbers:a list that counted on is the same list", backAt([dec("Een"), dec("Twee"), para("Tussen"), dec("Drie", 0, 3), dec("Vier")], 3),
  ["1.", "2.", null, null, "3."]);
eq("numbers:a list that counted on twice is the same list",
  backAt([dec("Een"), dec("Twee"), para("x"), dec("Drie", 0, 3), para("y"), dec("Vier", 0, 4), dec("Vijf")], 5), ["1.", "2.", null, "3.", null, null, "4."]);
eq("numbers:a list that counted on across another style is the same list",
  backAt([dec("Een"), item("bullet", "Twee"), dec("Drie", 0, 2), dec("Vier")], 2), ["1.", "•", null, "2."]);
eq("numbers:another list above doesn't count", [backAt([dec("Een"), dec("Twee"), para("Tussen"), dec("Drie"), dec("Vier")], 3),
  backAt([dec("Een"), dec("Twee"), para("Tussen"), dec("Drie", 0, 5), dec("Vier")], 3),
  backAt([dec("Een"), dec("Twee"), para("Tussen"), item("lower-alpha", "Drie"), item("lower-alpha", "Vier")], 3)],
  [["1.", "2.", null, null, "1."], ["1.", "2.", null, null, "1."], ["1.", "2.", null, null, "a."]]);
// a sublist belongs to its parent item: it never counts on across a shallower item
const subOut = make([dec("A"), item("lower-alpha", "B", 1), item("lower-alpha", "X", 1), item("lower-alpha", "D", 1)], 2);
eq("numbers:a sublist doesn't count on across a shallower item", [shown(after(subOut, C.listShiftTab)), shape(after(subOut, C.listShiftTab))[3]],
  [["1.", "a.", "2.", "a."], ["lower-alpha", 1, null, "D"]]);
// ...but across a sibling that left its list (another style, same level) it does
const subStyled = make([dec("A"), item("lower-alpha", "B", 1), item("lower-alpha", "X", 1), item("lower-alpha", "D", 1)], 2);
eq("numbers:a sublist counts on across a sibling of another style", shown(after(subStyled, C.setList("bullet"))), ["1.", "a.", "◦", "b."]);
// a paragraph between sub-items closes every list: the item after it is level 0 (the markers rule) and starts afresh
const subPara = (st => st.apply(st.tr.insert(posOf(st.doc, 2), S.nodes.paragraph.create(null, S.text("Tussen")))))(
  make([dec("A"), item("lower-alpha", "B", 1), item("lower-alpha", "C", 1)]));
eq("numbers:a paragraph between sub-items: the next is level 0", [shown(subPara), shape(subPara)[3]], [["1.", "a.", null, "a."], ["lower-alpha", 0, null, "C"]]);
// paste (replaceSelection, as the view pastes) into "Twee" of 1–4: at its start, over its text, in the middle, at the end
const pasteInto = (blocks, from, to = from) => (st => { st = select(st, cursor(st.doc, 1, from), cursor(st.doc, 1, to));
  return shown(st.apply(st.tr.replaceSelection(new P.Slice(P.Fragment.fromJSON(S, blocks), 1, 1)))); })(list4());
const twoParas = [para("Foo"), para("Bar")];
eq("numbers:paste of paragraphs into an item", [pasteInto(twoParas, 0), pasteInto(twoParas, 0, 4), pasteInto(twoParas, 2), pasteInto(twoParas, 4)],
  [["1.", "2.", null, "3.", "4."], ["1.", "2.", null, "3.", "4."], ["1.", "2.", null, "3.", "4."], ["1.", "2.", null, "3.", "4."]]);
eq("numbers:paste of an item and a paragraph at an item's start", pasteInto([item("bullet", "X"), para("Y")], 0), ["1.", "2.", null, "3.", "4."]);
eq("numbers:paste with a scene break at an item's start", pasteInto([para("A"), {type: "scene_break"}, para("B")], 0), ["1.", "2.", null, null, "3.", "4."]);
// a bullet list that counts on needs no start: nothing is appended
const bullets = make([item("bullet", "Een"), item("bullet", "Twee"), item("bullet", "Drie"), item("bullet", "Vier")]);
eq("numbers:bullets append nothing", bullets.applyTransaction(bullets.tr.insert(posOf(bullets.doc, 2), S.nodes.scene_break.create())).transactions.length, 1);
// the plugin runs on every keystroke: linear in the document, not quadratic
const big = make(Array.from({length: 1000}, (_, i) => dec("Punt " + i)), 500), t0 = Date.now();
type(big, "twintig tekens erbij");
const took = Date.now() - t0;
eq("numbers:20 keystrokes in a 1000-item list take under 200 ms", took < 200 ? "fast" : `${took} ms`, "fast");
const firstGone = after(moveTo(list4(), 0, 0), C.listBackspace);
eq("numbers:the first item made a paragraph", [shape(firstGone)[1], shown(firstGone)], [["decimal", 0, null, "Twee"], [null, "1.", "2.", "3."]]);
eq("numbers:the sublist after an outdented item starts afresh",
  shown(after(make([dec("Een"), item("lower-alpha", "Twee", 1), item("lower-alpha", "Drie", 1)], 1), C.listShiftTab)), ["1.", "2.", "a."]);
const joined = after(make([dec("Een"), dec("Twee"), para("Tussen"), dec("Drie", 0, 3), dec("Vier")], 2), C.setList("decimal"));
eq("numbers:a paragraph made an item joins the lists", [shown(joined), shape(joined)[3]], [["1.", "2.", "3.", "4.", "5."], ["decimal", 0, null, "Drie"]]);
// a list that counted on follows the list it counted on when that one grows or shrinks (Word, Docs)
const countedOn = (i, offset = null) => make([dec("Een"), dec("Twee"), para("Tussen"), dec("Drie", 0, 3), dec("Vier")], i, offset);
const grown = after(countedOn(1), C.listEnter);
eq("numbers:follows a list that grew (Enter after 2)", [shown(grown), shape(grown)[4]], [["1.", "2.", "3.", null, "4.", "5."], ["decimal", 0, 4, "Drie"]]);
eq("numbers:follows a list that grew (1. typed in a paragraph after 2)",
  shown(type(make([dec("Een"), dec("Twee"), para(), para("Tussen"), dec("Drie", 0, 3), dec("Vier")], 2, 0), "1. Nieuw")), ["1.", "2.", "3.", null, "4.", "5."]);
const shrunk = (st => st.apply(st.tr.delete(posOf(st.doc, 1), posOf(st.doc, 2))))(countedOn(0));
eq("numbers:follows a list that shrank (item 2 deleted)", [shown(shrunk), shape(shrunk)[2]], [["1.", null, "2.", "3."], ["decimal", 0, 2, "Drie"]]);
eq("numbers:follows a list that shrank (item 2 made a paragraph)", backAt([dec("Een"), dec("Twee"), para("Tussen"), dec("Drie", 0, 3), dec("Vier")], 1),
  ["1.", null, null, "2.", "3."]);
eq("numbers:follows down a chain of lists", shown(after(make([dec("Een"), dec("Twee"), para("x"), dec("Drie", 0, 3), para("y"), dec("Vier", 0, 4), dec("Vijf")], 1), C.listEnter)),
  ["1.", "2.", "3.", null, "4.", null, "5.", "6."]);
eq("numbers:a list started elsewhere doesn't follow", shown(after(make([dec("Een"), dec("Twee"), para("x"), dec("Vijf", 0, 5), dec("Zes")], 1), C.listEnter)),
  ["1.", "2.", "3.", null, "5.", "6."]);
// a sublist under another item is never counted on from the sublist of an item before: its own start stays
eq("numbers:a sublist's own start under the next item stays",
  shown(change(make([dec("A"), item("lower-alpha", "x", 1), item("lower-alpha", "y", 1), dec("B"), item("lower-alpha", "z", 1, 3)]))), ["1.", "a.", "b.", "2.", "c."]);

/* ——— undo is exact ——— */
const undo = state => after(state, P.undo);
const tabStart = make([dec("Een"), dec("Twee"), dec("Drie")], 1);
eq("undo:tab", json(undo(after(tabStart, C.listTab))) === json(tabStart), true);
const enterStart = make([dec("Een"), dec(""), dec("Drie"), dec("Vier")], 1);
eq("undo:enter", json(undo(after(enterStart, C.listEnter))) === json(enterStart), true);
// the list after the paragraph went on at 5 (hand-written Markdown); counting on from Twee would give 3
const joinStart = make([dec("Een"), dec("Twee"), para("Tussen"), dec("Vijf", 0, 5), dec("Zes")], 2);
const joinBack = undo(after(joinStart, C.setList("decimal")));
eq("undo:setList puts the numbers back", [json(joinBack) === json(joinStart), shown(joinBack)], [true, ["1.", "2.", null, "5.", "6."]]);

/* ——— alignment, text styles, sizes, marks, clear formatting ——— */
const al = (align, ...texts) => ({type: "aligned", attrs: {align}, content: texts.map(para)});
const bq = (...texts) => ({type: "blockquote", content: texts.map(para)});
const hd = (s, level = 2) => ({type: "heading", attrs: {level}, content: [txt(s)]});
const titled = s => ({type: "title", content: [txt(s)]});
const epigraph = s => ({type: "epigraph", content: [para(s)]});
const poemBox = s => ({type: "poem", attrs: {src: null}, content: [para(s)]});
/* the blocks: a container with its paragraphs' texts, a heading with its level, an item as in `shape` */
const tree = state => state.doc.content.content.map(n => n.type.name === "aligned" ? ["aligned", n.attrs.align, ...n.content.content.map(c => c.textContent)]
  : n.type.name === "blockquote" ? ["blockquote", ...n.content.content.map(c => c.textContent)]
  : n.type.name === "list_item" ? [n.attrs.list, n.attrs.level, n.attrs.start, n.textContent]
  : n.type.name === "heading" ? ["heading", n.attrs.level, n.textContent] : [n.type.name, n.textContent]);
/* the position of the first text `s` in `doc`, plus `offset` */
function textAt(doc, s, offset = 0) {
  let at = null;
  doc.descendants((n, pos) => { if (at == null && n.isText && n.text.includes(s)) at = pos + n.text.indexOf(s) + offset; return at == null; });
  if (at == null) throw new Error(`no text ${s}`);
  return at;
}
const fresh = (blocks, form = "prose") => P.EditorState.create({doc: docOf(blocks, form), plugins: plugins()});
/* the cursor at the start of the text `s`; the text from `a` to the end of `b` selected */
const at = (state, s) => select(state, textAt(state.doc, s), textAt(state.doc, s));
const on = (blocks, s, form) => at(fresh(blocks, form), s);
const over = (blocks, a, b, form) => (st => select(st, textAt(st.doc, a), textAt(st.doc, b, b.length)))(fresh(blocks, form));
const noteState = P.EditorState.create({doc: S.nodes.note.create(null, S.text("Noot"))});

/* alignment */
const centred = run(on([para("Een"), para("Twee")], "Een"), C.setAlign("center"));
eq("align:wrap centre a paragraph", [centred[0], tree(centred[1]), centred[1].selection.from === textAt(centred[1].doc, "Een")],
  [true, [["aligned", "center", "Een"], ["paragraph", "Twee"]], true]);
eq("align:wrap several paragraphs make one block", tree(after(over([para("Een"), para("Twee"), para("Drie")], "Een", "Twee"), C.setAlign("right"))),
  [["aligned", "right", "Een", "Twee"], ["paragraph", "Drie"]]);
eq("align:join centring the next paragraph joins it", tree(after(on([al("center", "Een"), para("Twee")], "Twee"), C.setAlign("center"))),
  [["aligned", "center", "Een", "Twee"]]);
eq("align:join on both sides", tree(after(on([al("center", "Een"), para("Twee"), al("center", "Drie")], "Twee"), C.setAlign("center"))),
  [["aligned", "center", "Een", "Twee", "Drie"]]);
eq("align:join not with another alignment", tree(after(on([al("right", "Een"), para("Twee")], "Twee"), C.setAlign("center"))),
  [["aligned", "right", "Een"], ["aligned", "center", "Twee"]]);
const switched = after(on([al("center", "Een", "Twee", "Drie")], "Twee"), C.setAlign("right"));
eq("align:switch right on one paragraph of three", [tree(switched), switched.selection.from === textAt(switched.doc, "Twee")],
  [[["aligned", "center", "Een"], ["aligned", "right", "Twee"], ["aligned", "center", "Drie"]], true]);
eq("align:switch a whole block", tree(after(over([al("center", "Een", "Twee")], "Een", "Twee"), C.setAlign("right"))), [["aligned", "right", "Een", "Twee"]]);
eq("align:off", [tree(after(on([al("center", "Een")], "Een"), C.setAlign(null))),
  tree(after(on([al("center", "Een", "Twee", "Drie")], "Twee"), C.setAlign(null))),
  tree(after(over([al("center", "Een", "Twee", "Drie")], "Twee", "Drie"), C.setAlign(null)))],
  [[["paragraph", "Een"]], [["aligned", "center", "Een"], ["paragraph", "Twee"], ["aligned", "center", "Drie"]],
   [["aligned", "center", "Een"], ["paragraph", "Twee"], ["paragraph", "Drie"]]]);
const sameAlign = on([al("center", "Een", "Twee")], "Twee"), sameRun = run(sameAlign, C.setAlign("center"));
eq("align:same changes nothing", [sameRun[0], json(sameRun[1]) === json(sameAlign), run(on([para("Een")], "Een"), C.setAlign(null))[0]], [true, true, true]);
eq("align:not-items only paragraphs, in prose", [C.setAlign("center")(on([dec("Een")], "Een")), C.setAlign("center")(on([hd("Kop")], "Kop")),
  C.setAlign("center")(on([titled("Titel"), para("x")], "Titel")), C.setAlign("center")(on([bq("Citaat")], "Citaat")),
  C.setAlign(null)(on([dec("Een")], "Een")), C.setAlign("center")(over([para("Een"), dec("Twee")], "Een", "Twee")),
  C.setAlign("center")(on([para("Regel")], "Regel", "poem")), C.setAlign("center")(noteState), C.setAlign("left")(on([para("Een")], "Een"))],
  [false, false, false, false, false, false, false, false, false]);

/* text styles */
eq("style:heading a paragraph and a list item", [tree(after(on([para("Een")], "Een"), C.setTextStyle("heading"))),
  tree(after(on([item("bullet", "Een")], "Een"), C.setTextStyle("heading"))), tree(after(on([para("Een")], "Een"), C.setTextStyle("subheading"))),
  tree(after(on([hd("Kop")], "Kop"), C.setTextStyle("subheading")))],
  [[["heading", 2, "Een"]], [["heading", 2, "Een"]], [["heading", 3, "Een"]], [["heading", 3, "Kop"]]]);
eq("style:heading lifts out of a centred block and a quotation first", [
  tree(after(on([al("center", "Een", "Twee", "Drie")], "Twee"), C.setTextStyle("heading"))),
  tree(after(on([bq("Een", "Twee")], "Een"), C.setTextStyle("heading")))],
  [[["aligned", "center", "Een"], ["heading", 2, "Twee"], ["aligned", "center", "Drie"]], [["heading", 2, "Een"], ["blockquote", "Twee"]]]);
const headed = after(on([dec("Een"), dec("Twee"), dec("Drie"), dec("Vier")], "Twee"), C.setTextStyle("heading"));
eq("style:heading a middle item keeps the numbers after it", [tree(headed), shown(headed)],
  [[["decimal", 0, null, "Een"], ["heading", 2, "Twee"], ["decimal", 0, 2, "Drie"], ["decimal", 0, null, "Vier"]], ["1.", null, "2.", "3."]]);
eq("style:heading a line break becomes a space",
  tree(after(fresh([{type: "paragraph", content: [txt("Een"), {type: "hard_break"}, txt("twee")]}]), C.setTextStyle("heading"))), [["heading", 2, "Een twee"]]);
eq("style:heading never the title", [C.setTextStyle("heading")(on([titled("Titel"), para("Tekst")], "Titel")),
  tree(after(over([titled("Titel"), para("Tekst")], "Titel", "Tekst"), C.setTextStyle("heading")))], [false, [["title", "Titel"], ["heading", 2, "Tekst"]]]);
eq("style:heading not in an epigraph, a poem block or a note", [C.setTextStyle("heading")(on([epigraph("Motto")], "Motto")),
  C.setTextStyle("quotation")(on([poemBox("Regel")], "Regel")), C.setTextStyle("heading")(noteState),
  C.setTextStyle("heading")(over([para("Een"), epigraph("Motto")], "Een", "Motto")), C.setTextStyle("kop")(on([para("Een")], "Een"))],
  [false, false, false, false, false]);
eq("style:heading in a poem piece", [tree(after(on([para("Regel")], "Regel", "poem"), C.setTextStyle("heading"))),
  tree(after(on([para("Regel")], "Regel", "poem"), C.setTextStyle("quotation")))], [[["heading", 2, "Regel"]], [["blockquote", "Regel"]]]);
eq("style:paragraph", [tree(after(on([hd("Kop", 3)], "Kop"), C.setTextStyle("paragraph"))),
  tree(after(on([bq("Een", "Twee")], "Twee"), C.setTextStyle("paragraph"))),
  tree(after(on([dec("Een")], "Een"), C.setTextStyle("paragraph"))), tree(after(on([al("right", "Een")], "Een"), C.setTextStyle("paragraph")))],
  [[["paragraph", "Kop"]], [["blockquote", "Een"], ["paragraph", "Twee"]], [["decimal", 0, null, "Een"]], [["aligned", "right", "Een"]]]);
const quoted = after(on([para("Een")], "Een"), C.setTextStyle("quotation"));
eq("style:quotation toggles", [tree(quoted), tree(after(quoted, C.setTextStyle("quotation")))], [[["blockquote", "Een"]], [["paragraph", "Een"]]]);
eq("style:quotation several blocks become one quotation",
  tree(after(over([para("Een"), dec("Twee"), hd("Drie"), al("center", "Vier")], "Een", "Vier"), C.setTextStyle("quotation"))),
  [["blockquote", "Een", "Twee", "Drie", "Vier"]]);
eq("style:quotation joins a quotation next to it", [tree(after(on([bq("Een"), para("Twee")], "Twee"), C.setTextStyle("quotation"))),
  tree(after(over([bq("Een"), para("Twee")], "Een", "Twee"), C.setTextStyle("quotation")))], [[["blockquote", "Een", "Twee"]], [["blockquote", "Een", "Twee"]]]);
const middleOut = after(on([bq("Een", "Twee", "Drie")], "Twee"), C.setTextStyle("quotation"));
eq("style:quotation off in the middle, and on again", [tree(middleOut), tree(after(middleOut, C.setTextStyle("quotation")))],
  [[["blockquote", "Een"], ["paragraph", "Twee"], ["blockquote", "Drie"]], [["blockquote", "Een", "Twee", "Drie"]]]);
eq("quote:in and out (Ctrl+] and Ctrl+[ outside lists)", [tree(after(on([para("Een")], "Een"), C.quote(1))), C.quote(1)(on([bq("Een")], "Een")),
  tree(after(on([bq("Een", "Twee")], "Een"), C.quote(-1))), C.quote(-1)(on([para("Een")], "Een")), C.quote(1)(on([hd("Kop")], "Kop")),
  tree(after(over([para("Een"), hd("Kop"), para("Twee")], "Een", "Twee"), C.quote(1)))],
  [[["blockquote", "Een"]], false, [["paragraph", "Een"], ["blockquote", "Twee"]], false, false, [["blockquote", "Een"], ["heading", 2, "Kop"], ["blockquote", "Twee"]]]);

/* sizes */
const sizes = state => { const out = []; state.doc.descendants(n => { if (n.isText) out.push((n.marks.find(m => m.type.name === "size") || {attrs: {size: null}}).attrs.size); }); return out; };
const whole = over([para("Een twee")], "Een", "Een twee");
const steps = [];
[1, 1, 1, -1, -1, -1, -1, -1].reduce((st, dir) => { const next = after(st, C.stepSize(dir)); steps.push(sizes(next)); return next; }, whole);
eq("size:step none → large → x-large → x-large, down to x-small", steps,
  [["large"], ["x-large"], ["x-large"], ["large"], [null], ["small"], ["x-small"], ["x-small"]]);
eq("size:step Normal", sizes(after(after(whole, C.setSize("large")), C.setSize(null))), [null]);
const partly = after(select(whole, 1, 4), C.setSize("large"));
eq("size:step a mixed selection steps from its start, one size for all", [sizes(partly), sizes(after(select(partly, 1, 9), C.stepSize(1))),
  sizes(after(select(partly, 4, 9), C.stepSize(-1)))], [["large", null], ["x-large"], ["large", "small"]]);
const cur = on([para("Een")], "Een");
eq("size:step an empty selection sets what is typed next", [after(cur, C.setSize("large")).storedMarks.map(m => m.attrs.size),
  sizes(type(after(cur, C.stepSize(-1)), "x")), json(after(cur, C.setSize("large"))) === json(cur), C.setSize("medium")(cur)],
  [["large"], ["small", null], true, false]);
eq("size:step in a note", sizes(after(noteState.apply(noteState.tr.setSelection(P.TextSelection.create(noteState.doc, 0, 4))), C.setSize("small"))), ["small"]);

/* marks */
const MARKS = ["strong", "em", "underline", "strike", "smallcaps"];
const word = over([para("Een twee")], "twee", "twee");
eq("marks:toggle on and off", MARKS.map(m => { const one = after(word, C.toggle(m)), off = after(one, C.toggle(m));
  return [one.doc.rangeHasMark(5, 9, S.marks[m]), off.doc.rangeHasMark(5, 9, S.marks[m]), one.doc.rangeHasMark(1, 4, S.marks[m])]; }),
  MARKS.map(() => [true, false, false]));
eq("marks:toggle with a cursor sets what is typed next", MARKS.map(m => after(cur, C.toggle(m)).storedMarks.map(k => k.type.name)), MARKS.map(m => [m]));
eq("marks:toggle only the five", [C.toggle("idx")(word), C.toggle("comment")(word), C.toggle("size")(word)], [false, false, false]);

/* clear formatting */
const mark = (type, attrs) => (attrs ? {type, attrs} : {type});
const ALL = [mark("em"), mark("strong"), mark("underline"), mark("strike"), mark("smallcaps"), mark("size", {size: "large"}),
  mark("idx", {term: "x"}), mark("comment", {note: "c"}), mark("lang", {lang: "en"})];
const rich = {type: "aligned", attrs: {align: "center"}, content: [{type: "paragraph", content: [{type: "text", text: "Een ", marks: ALL},
  {type: "note", content: [{type: "text", text: "noot", marks: [mark("em")]}]}, {type: "cite", attrs: {items: [{key: "smith"}]}},
  {type: "text", text: " twee", marks: [mark("strong")]}]}]};
const inlines = state => { const out = []; state.doc.descendants(n => { if (n.isInline) out.push([n.type.name, n.isText ? n.text : null, n.marks.map(m => m.type.name)]); }); return out; };
const cleared = after(over([rich, al("center", "Daarna")], "Een", "twee"), C.clearFormatting);
eq("clear:keeps index terms, comments, languages, notes and sources", [inlines(cleared), tree(cleared)],
  [[["text", "Een ", ["idx", "comment", "lang"]], ["note", null, []], ["text", "noot", ["em"]], ["cite", null, []], ["text", " twee", []], ["text", "Daarna", []]],
   [["paragraph", "Een noot twee"], ["aligned", "center", "Daarna"]]]);
const curCleared = after(select(fresh([rich]), 3, 3), C.clearFormatting);     // inside "Een": index terms, comments, languages too
eq("clear:keeps with a cursor only what is typed next", [curCleared.storedMarks.map(m => m.type.name), tree(curCleared)],
  [["idx", "comment", "lang"], [["aligned", "center", "Een noot twee"]]]);
eq("clear:keeps headings, lists and quotations", tree(after(over([hd("Kop"), dec("Een"), bq("Citaat")], "Kop", "Citaat"), C.clearFormatting)),
  [["heading", 2, "Kop"], ["decimal", 0, null, "Een"], ["blockquote", "Citaat"]]);

/* A note's own text (edited in the margin) keeps its formatting: the toggles pass it, as current() does, so the panel
   shows what a toggle will do; they and the sizes act on the note itself. */
const withNote = (noteMarks = []) => fresh([{type: "paragraph", content: [txt("Een "),
  {type: "note", marks: noteMarks, content: [{type: "text", text: "noot", marks: [mark("em")]}]}, txt(" twee")]}]);
const noteAll = (st => select(st, 1, st.doc.child(0).nodeSize - 1))(withNote());
const noteNode = st => st.apply(st.tr.setSelection(P.NodeSelection.create(st.doc, 5)));       // the note, selected
const italic = after(noteAll, C.toggle("em"));
eq("marks:toggle agrees with current() past a note's own text", [F.current(noteAll).marks.em, inlines(italic), F.current(italic).marks.em,
  inlines(after(italic, C.toggle("em")))],
  [false, [["text", "Een ", ["em"]], ["note", null, ["em"]], ["text", "noot", ["em"]], ["text", " twee", ["em"]]], true,
   [["text", "Een ", []], ["note", null, []], ["text", "noot", ["em"]], ["text", " twee", []]]]);
eq("marks:toggle a selected note marks the note, not its text", [inlines(after(noteNode(withNote()), C.toggle("em"))).slice(1, 3),
  inlines(after(noteNode(withNote([mark("strong")])), C.toggle("strong"))).slice(1, 3), F.current(noteNode(withNote())).marks.em],
  [[["note", null, ["em"]], ["text", "noot", ["em"]]], [["note", null, []], ["text", "noot", ["em"]]], false]);
eq("marks:toggle leaves the spaces at the selection's edges", inlines(after(select(fresh([para("Een twee drie")]), 4, 10), C.toggle("strong"))),
  [["text", "Een ", []], ["text", "twee", ["strong"]], ["text", " drie", []]]);
/* every inline node: [type, its size] */
const inlineSizes = state => { const out = []; state.doc.descendants(n => { if (n.isInline) out.push([n.type.name, (n.marks.find(m => m.type.name === "size") || {attrs: {size: null}}).attrs.size]); }); return out; };
const largeNote = () => withNote([mark("size", {size: "large"})]), fromNote = () => select(largeNote(), 5, 16);
eq("size:step from a note at the selection's start", [F.current(noteNode(largeNote())).size, inlineSizes(after(noteNode(largeNote()), C.stepSize(1))),
  F.current(fromNote()).size, inlineSizes(after(fromNote(), C.stepSize(1)))],
  ["large", [["text", null], ["note", "x-large"], ["text", null], ["text", null]],
   "mixed", [["text", null], ["note", "x-large"], ["text", null], ["text", "x-large"]]]);
const noteBreak = fresh([{type: "paragraph", content: [txt("Kop"), {type: "note", content: [txt("Een"), {type: "hard_break"}, txt("twee")]}]}]);
eq("style:heading line breaks in its notes become spaces too (a heading's note is one line)", inlines(after(noteBreak, C.setTextStyle("heading"))),
  [["text", "Kop", []], ["note", null, []], ["text", "Een twee", []]]);

/* what applies, what is on */
// `table` (book-table.js, not loaded here: false) is tested with the panel (tests/js/book_panel.js)
const ONLY = {text: false, list: false, align: false, size: true, style: true, table: false}, EVERY = {text: true, list: true, align: true, size: true, style: true, table: false};
eq("applies:note-title-poem", [F.applies(noteState), F.applies(on([titled("Titel"), para("x")], "Titel")), F.applies(on([epigraph("Motto")], "Motto")),
  F.applies(on([poemBox("Regel")], "Regel")), F.applies(on([para("Regel")], "Regel", "poem"))],
  [ONLY, ONLY, ONLY, ONLY, {text: true, list: false, align: false, size: true, style: true, table: false}]);
const cellDoc = [{type: "table", attrs: {header: true, align: [null]}, content: [{type: "table_row", content: [{type: "table_cell", content: [txt("Cel")]}]}]}];
eq("applies:a table's cell size and style only", [F.applies(on(cellDoc, "Cel")), F.current(on(cellDoc, "Cel")).text, F.current(on(cellDoc, "Cel")).align],
  [ONLY, null, null]);
const imageSel = (st => st.apply(st.tr.setSelection(P.NodeSelection.create(st.doc, posOf(st.doc, 1)))))(fresh([para("Een"), {type: "image", attrs: {src: "../images/a.png"}}]));
eq("applies:prose", [F.applies(on([para("Een")], "Een")), F.applies(on([dec("Een")], "Een")), F.applies(on([al("center", "Een")], "Een")),
  F.applies(on([hd("Kop")], "Kop")), F.applies(on([bq("Citaat")], "Citaat")), F.applies(imageSel)],
  [EVERY, {...EVERY, align: false}, {...EVERY, list: false}, {...EVERY, align: false}, {...EVERY, list: false, align: false},
   {text: false, list: false, align: false, size: false, style: false, table: false}]);
const BLANK = {strong: false, em: false, underline: false, strike: false, smallcaps: false};
eq("current:a paragraph", F.current(cur), {text: "paragraph", list: null, align: null, size: null, marks: BLANK, table: null});
eq("current:blocks", [F.current(on([hd("Kop", 3)], "Kop")).text, F.current(on([hd("Kop")], "Kop")).text, F.current(on([bq("Citaat")], "Citaat")).text,
  F.current(on([item("lower-roman", "Een")], "Een")).list, F.current(on([item("lower-roman", "Een")], "Een")).text,
  F.current(on([al("right", "Een")], "Een")).align, F.current(on([titled("Titel")], "Titel")).text, F.current(noteState).text],
  ["subheading", "heading", "quotation", "lower-roman", "paragraph", "right", null, null]);
eq("current:mixed", [F.current(over([para("Een"), hd("Twee")], "Een", "Twee")).text, F.current(over([al("center", "Een"), al("right", "Twee")], "Een", "Twee")).align,
  F.current(over([dec("Een"), para("Twee")], "Een", "Twee")).list, F.current(select(partly, 1, 9)).size, F.current(select(partly, 1, 4)).size],
  ["mixed", "mixed", "mixed", "mixed", "large"]);
eq("current:marks of the selection and of what is typed next", [F.current(after(word, C.toggle("em"))).marks,
  F.current(after(cur, C.toggle("smallcaps"))).marks, F.current(after(cur, C.setSize("small"))).size, F.current(on([rich], "Een")).marks],
  [{...BLANK, em: true}, {...BLANK, smallcaps: true}, "small", {strong: true, em: true, underline: true, strike: true, smallcaps: true}]);

/* keys */
const bindingOf = key => key.split("+").map((p, i, a) => (p === "Ctrl" ? "Mod" : i === a.length - 1 && /^[A-Z]$/.test(p) ? p.toLowerCase() : p)).join("-");
const fakeView = state => ({state, dispatch(tr) { this.state = this.state.apply(tr); }});
const T0 = {locked: false, view: fakeView(on([para("Een")], "Een"))};
T0.activeView = () => T0.view;
const km = F.keymap(T0), keyed = F.KEYS.filter(k => k.key), row = id => F.KEYS.find(k => k.id === id);
eq("keys:table every KEYS key is bound in keymap", keyed.filter(k => typeof km[bindingOf(k.key)] !== "function").map(k => k.key), []);
eq("keys:table the spec's keys", ["Mod-b", "Mod-i", "Mod-u", "Alt-Shift-5", "Mod-Shift-k", "Mod-Shift-.", "Mod->", "Mod-Shift-,", "Mod-<", "Mod-Space",
  "Mod-Alt-0", "Mod-Alt-2", "Mod-Alt-3", "Mod-Shift-7", "Mod-Shift-8", "Mod-]", "Mod-[", "Mod-Shift-l", "Mod-Shift-e", "Mod-Shift-r", "Alt-o"]
  .filter(k => typeof km[k] !== "function"), []);
eq("keys:table leaves Tab, Enter and Backspace to book-text", ["Tab", "Shift-Tab", "Enter", "Backspace"].filter(k => k in km), []);
eq("keys:table rows", [new Set(F.KEYS.map(k => k.id)).size === F.KEYS.length, new Set(keyed.map(k => k.key)).size === keyed.length,
  [...new Set(F.KEYS.map(k => k.group))], F.KEYS.filter(k => !k.key).map(k => k.label), F.KEYS.every(k => typeof k.run === "function"),
  ["align-center", "larger", "strike", "clear", "format"].map(id => [row(id).label, row(id).key])],
  [true, true, ["Text", "List", "Align", "Size", "Style", "Format"],
   ["Quotation", "Lettered list", "Lettered list (capitals)", "Roman list", "Roman list (small)", "Make a list of these lines", "Normal size"], true,
   [["Centre", "Ctrl+Shift+E"], ["Larger", "Ctrl+Shift+."], ["Strikethrough", "Alt+Shift+5"], ["Clear formatting", "Ctrl+Space"], ["Format…", "Alt+O"]]]);
/* a key on a state: the state after it (book-text's keymap plugin passes state and dispatch) */
const press = (name, st, keys = km) => { let next = st; const ok = keys[name](st, tr => { next = next.apply(tr); }, null); return ok === true ? next : "passed"; };
const nowhere = [on([titled("Titel"), para("x")], "Titel"), noteState, on([para("Regel")], "Regel", "poem"), on([hd("Kop")], "Kop"), imageSel];
eq("keys:table every key stays in the text where it doesn't apply", nowhere.map(st => Object.keys(km).filter(k => press(k, st) === "passed")), nowhere.map(() => []));
eq("keys:Ctrl+Shift+R in a heading changes nothing", json(press("Mod-Shift-r", on([hd("Kop")], "Kop"))) === json(on([hd("Kop")], "Kop")), true);
eq("keys:Ctrl+] a list level in a list, a quotation outside", [shown(press("Mod-]", make([dec("Een"), dec("Twee")], 1))), tree(press("Mod-]", cur)),
  tree(press("Mod-[", on([bq("Een")], "Een"))), shown(press("Mod-[", make([dec("Een"), item("lower-alpha", "Twee", 1)], 1)))],
  [["1.", "a."], [["blockquote", "Een"]], [["paragraph", "Een"]], ["1.", "2."]]);
eq("keys:a key does what its row does", [tree(press("Mod-Shift-e", cur)), sizes(press("Mod->", whole)), sizes(press("Mod-Shift-,", whole)),
  tree(press("Mod-Alt-3", cur)), shape(press("Mod-Shift-7", cur)), inlines(press("Mod-Space", select(fresh([rich]), 2, 3)))[0]],
  [[["aligned", "center", "Een"]], ["large"], ["small"], [["heading", 3, "Een"]], [["decimal", 0, null, "Een"]], ["text", "E", ["idx", "comment", "lang"]]]);
let opened = null;
F.openPanel = T => { opened = T; };
press("Alt-o", cur);
eq("keys:Alt+O opens the panel", opened === T0, true);
const locked = {locked: true, view: fakeView(cur)}, lockedKeys = F.keymap(locked);
locked.activeView = () => locked.view;
opened = null;
eq("keys:locked every key keeps the key and does nothing", [Object.keys(lockedKeys).filter(k => press(k, cur, lockedKeys) !== cur), opened],
  [[], null]);
delete F.openPanel;
row("align-center").run(T0);
row("larger").run(locked);
eq("keys:run applies its command to the active view", [tree(T0.view.state), locked.view.state === cur], [[["aligned", "center", "Een"]], true]);
T0.activeView = undefined; T0.view = fakeView(cur);
row("heading").run(T0);
eq("keys:run without activeView uses the view", tree(T0.view.state), [["heading", 2, "Een"]]);

/* undo is exact */
const alignStart = on([para("Een"), al("center", "Twee", "Drie")], "Een");
const switchStart = on([al("center", "Een", "Twee", "Drie")], "Twee");
eq("undo:align", [json(undo(after(alignStart, C.setAlign("center")))) === json(alignStart), json(undo(after(switchStart, C.setAlign("right")))) === json(switchStart),
  json(undo(after(switchStart, C.setAlign(null)))) === json(switchStart)], [true, true, true]);
eq("undo:size", [json(undo(after(whole, C.stepSize(1)))) === json(whole), json(undo(after(partly, C.clearFormatting))) === json(partly)], [true, true]);
const quoteStart = on([bq("Een"), para("Twee"), bq("Drie")], "Twee");
eq("undo:style", [json(undo(after(quoteStart, C.setTextStyle("quotation")))) === json(quoteStart),
  json(undo(after(quoteStart, C.setTextStyle("heading")))) === json(quoteStart)], [true, true]);

/* Make a list of these lines */
const lines = after(select(...(st => [st, 1, st.doc.content.size - 1])(fresh([para("- vier"), para("3) vijf"), para("A. zes"), para("iv. zeven"),
  para("Geen marker"), para("c. acht"), para("•niet"), para("i. negen"), para("h. tien"), para("i. elf")]))), C.listFromMarkers);
eq("markers:from-text every style", shape(lines),
  [["bullet", 0, null, "vier"], ["decimal", 0, 3, "vijf"], ["upper-alpha", 0, null, "zes"], ["lower-roman", 0, 4, "zeven"], ["paragraph", "Geen marker"],
   ["lower-alpha", 0, 3, "acht"], ["paragraph", "•niet"], ["lower-roman", 0, null, "negen"], ["lower-alpha", 0, 8, "tien"], ["lower-alpha", 0, null, "elf"]]);
eq("markers:from-text only selected top-level paragraphs, in prose", [shape(after(on([para("- een"), para("- twee")], "- een"), C.listFromMarkers)),
  C.listFromMarkers(on([para("- een")], "- een", "poem")), C.listFromMarkers(on([para("Een")], "Een")), C.listFromMarkers(on([bq("- een")], "- een")),
  C.listFromMarkers(on([al("center", "- een")], "- een"))],
  [[["bullet", 0, null, "een"], ["paragraph", "- twee"]], false, false, false, false]);

/* ——— after an edit the document is what a reload gives (the runner checks parse(serialize(doc)) == doc) ——— */
const reload = {};
const scenario = (name, edit) => { const doc = IN.reload[name]; if (!doc) { eq(`reload ${name}`, "missing", "given"); return; }
  const st = edit(P.EditorState.create({doc: P.Node.fromJSON(S, doc), plugins: plugins()})); reload[name] = st.doc.toJSON(); return st; };
const fromText = scenario("from-text", st => after(select(st, 1, st.doc.content.size - 1), C.listFromMarkers));
eq("markers:from-text v1.2 Markdown (`• een`, `1\\. twee`, `a. drie`)", fromText && shape(fromText),
  [["paragraph", "Tekst"], ["bullet", 0, null, "een"], ["decimal", 0, null, "twee"], ["lower-alpha", 0, null, "drie"]]);
const centreJoin = scenario("centre-join", st => after(at(after(at(after(at(st, "Een"), C.setAlign("center")), "Twee"), C.setAlign("center")), "Drie"), C.setAlign("right")));
eq("reload centre-join", centreJoin && tree(centreJoin), [["aligned", "center", "Een", "Twee"], ["aligned", "right", "Drie"]]);
const headingInList = scenario("heading-in-list", st => after(at(st, "Twee"), C.setTextStyle("heading")));
eq("reload heading-in-list", headingInList && shown(headingInList), ["1.", null, "2.", "3."]);
const quoteJoin = scenario("quotation-join", st => after(at(after(at(st, "Twee"), C.setTextStyle("quotation")), "Drie"), C.quote(1)));
eq("reload quotation-join", quoteJoin && tree(quoteJoin), [["paragraph", "Een"], ["blockquote", "Twee", "Drie"]]);
const sizeSteps = scenario("size-steps", st => { const twee = after(after(select(st, textAt(st.doc, "twee"), textAt(st.doc, "twee", 4)), C.stepSize(1)), C.stepSize(1));
  return after(select(twee, textAt(twee.doc, "drie"), textAt(twee.doc, "drie", 4)), C.stepSize(-1)); });
eq("reload size-steps", sizeSteps && sizes(sizeSteps), [null, "x-large", null, "small"]);
eq("reload heading-note-break: the note holds a line break", JSON.stringify(IN.reload["heading-note-break"] || null).includes("hard_break"), true);
const noteBroken = scenario("heading-note-break", st => after(at(st, "Kop"), C.setTextStyle("heading")));
eq("reload heading-note-break", noteBroken && inlines(noteBroken), [["text", "Kop", []], ["note", null, []], ["text", "Een twee", []]]);
// the first Enter makes an empty item 3 (Drie shows 4); the second ends the list there, and Drie goes on from Twee
const enterEnds = scenario("enter-ends-list", st => type(after(after(moveTo(st, 1), C.listEnter), C.listEnter), "Tussendoor."));
eq("reload enter-ends-list", enterEnds && shown(enterEnds), ["1.", "2.", null, "3.", "4."]);
const nests = scenario("tab-nests", st => after(after(moveTo(after(moveTo(st, 1), C.listTab), 2), C.listTab), C.listTab));
eq("reload tab-nests", nests && shown(nests), ["1.", "a.", "i.", "2."]);
const scene = scenario("scene-between", st => st.apply(st.tr.insert(posOf(st.doc, 2), S.nodes.scene_break.create())));
eq("reload scene-between", scene && shown(scene), ["1.", "2.", null, "3.", "4."]);
const bullet = scenario("bullet-in-numbers", st => after(moveTo(st, 1), C.setList("bullet")));
eq("reload bullet-in-numbers", bullet && shown(bullet), ["1.", "•", "2.", "3."]);
const grows = scenario("counted-on-grows", st => type(after(moveTo(st, 1), C.listEnter), "Nieuw"));
eq("reload counted-on-grows", grows && shown(grows), ["1.", "2.", "3.", null, "4.", "5."]);
const shrinks = scenario("counted-on-shrinks", st => st.apply(st.tr.delete(posOf(st.doc, 1), posOf(st.doc, 2))));
eq("reload counted-on-shrinks", shrinks && shown(shrinks), ["1.", null, "2.", "3."]);

/* ——— the writing window: marker decorations, the clipboard's text, paste ——— */
/* the marker decorations of a state made with BookFormat.plugins: per decorated item [marker, gutter in em, indent in em] */
const decosOf = state => state.plugins.map(p => p.props.decorations && p.props.decorations.call(p, state)).filter(Boolean).flatMap(s => s.find())
  .sort((a, b) => a.from - b.from);
const gutters = blocks => decosOf(P.EditorState.create({doc: docOf(blocks), plugins: F.plugins({})})).map(d => {
  const a = d.type.attrs, mw = /--bk-mw:([\d.]+)em/.exec(a.style || ""), ind = /--bk-in:([\d.]+)em/.exec(a.style || "");
  return [a["data-marker"], mw ? +mw[1] : null, ind ? +ind[1] : null];
});
const apart = blocks => decosOf(P.EditorState.create({doc: docOf(blocks), plugins: F.plugins({})})).map(d => d.type.attrs.class === "bk-li-apart");
eq("plugins:the numbers plugin is one of them", shape(change(P.EditorState.create({doc: docOf([dec("Een", 2)]), plugins: F.plugins({})}))), [["decimal", 0, null, "Een!"]]);
const nine = gutters(Array.from({length: 9}, (_, i) => dec("Punt " + i))), ten = gutters(Array.from({length: 10}, (_, i) => dec("Punt " + i)));
eq("decorations:every item shows its marker", nine.map(g => g[0]), ["1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."]);
eq("decorations:the attributes", decosOf(P.EditorState.create({doc: docOf([dec("Een")]), plugins: F.plugins({})})).map(d => [d.from, d.to, d.type.attrs]),
  [[0, 5, {"data-marker": "1.", style: "--bk-mw:1em;--bk-in:0em"}]]);
eq("decorations:one gutter for a list, at least 1em", [new Set(nine.map(g => g[1])).size, nine[0][1], new Set(ten.map(g => g[1])).size, ten[0][1] > 1],
  [1, 1, 1, true]);
const roman = gutters([item("upper-roman", "a", 0, 8), item("upper-roman", "b")]);
eq("decorations:VIII. is wider than 10.", [roman.map(g => g[0]), roman[0][1] === roman[1][1], roman[0][1] > ten[0][1]], [["VIII.", "IX."], true, true]);
eq("decorations:bullets 1em; a sublist at its parent's text edge (gutter + .5em)", gutters([item("bullet", "a"), item("bullet", "b", 1), item("bullet", "c", 2), dec("d", 3)]),
  [["•", 1, 0], ["◦", 1, 1.5], ["▪", 1, 3], ["1.", 1, 4.5]]);
const near = (a, b) => Math.abs(a - b) < 1e-6;
const underWide = gutters([item("upper-roman", "a", 0, 8), item("upper-roman", "b"), item("lower-alpha", "c", 1), item("lower-roman", "d", 2), item("upper-roman", "e")]);
eq("decorations:a sublist under a wide marker starts at its parent's text edge",
  [underWide[0][1] > 2, [0, 1, 4].map(k => underWide[k][2]), near(underWide[2][2], underWide[0][1] + .5), near(underWide[3][2], underWide[2][2] + underWide[2][1] + .5)],
  [true, [0, 0, 0], true, true]);
const underTen = gutters([...Array.from({length: 10}, (_, i) => dec("Punt " + i)), item("lower-alpha", "sub", 1)]);
eq("decorations:a sublist under 10. starts at 10.'s text edge", near(underTen[10][2], underTen[9][1] + .5), true);
eq("decorations:two lists side by side are set apart, nothing else",
  apart([dec("a"), dec("b"), item("upper-roman", "c"), item("upper-roman", "d"), para("x"), item("bullet", "e"), dec("f", 1), item("lower-alpha", "g")]),
  [false, false, true, false, false, false, true]);
eq("decorations:a sublist has its own gutter", gutters([dec("a", 0, 98), dec("b"), item("lower-alpha", "c", 1), dec("d")]).map(g => [g[0], g[1] > 1]),
  [["98.", true], ["99.", true], ["a.", false], ["100.", true]]);
eq("decorations:a list counted on across a paragraph keeps its gutter", (g => [g[0][1] === g[1][1], g[1][0]])(gutters([dec("a", 0, 9), para("x"), dec("b", 0, 10)])),
  [true, "10."]);
eq("decorations:paragraphs and other blocks get none", gutters([para("Een"), hd("Kop"), bq("Citaat")]), []);
const emptyDoc = docOf([para()]);
const typedOn = type(P.EditorState.create({doc: emptyDoc, plugins: [P.inputRules({rules: F.inputRules()}), ...F.plugins({})],
  selection: P.TextSelection.create(emptyDoc, 1)}), "1. Een");
eq("decorations:follow the document", decosOf(typedOn).map(d => d.type.attrs["data-marker"]), ["1."]);
// typing in an item keeps the decorations (mapped, the same ones); a new item makes them anew
const keptDoc = docOf([dec("Een"), dec("Twee")]);
const keptBefore = P.EditorState.create({doc: keptDoc, plugins: F.plugins({}), selection: P.TextSelection.create(keptDoc, 2)});
const keptAfter = type(keptBefore, "xy"), keptSplit = after(keptAfter, C.listEnter);
eq("decorations:kept while the markers stay, made anew when they change",
  [decosOf(keptAfter).map((d, k) => d.type === decosOf(keptBefore)[k].type), decosOf(keptAfter).map(d => [d.from, d.to]),
   decosOf(keptSplit).map(d => d.type.attrs["data-marker"])],
  [[true, true], [[0, 7], [7, 13]], ["1.", "2.", "3."]]);
const bigDoc = docOf(Array.from({length: 1000}, (_, i) => dec("Punt " + i)));
const bigState = P.EditorState.create({doc: bigDoc, plugins: [P.inputRules({rules: F.inputRules()}), P.history(), ...F.plugins({})],
  selection: P.TextSelection.create(bigDoc, cursor(bigDoc, 500))}), t1 = Date.now();
const bigTyped = type(bigState, "twintig tekens erbij");
const tookDecos = Date.now() - t1;
eq("decorations:20 keystrokes in a 1000-item list take under 300 ms", [tookDecos < 300 ? "fast" : `${tookDecos} ms`, decosOf(bigTyped).length], ["fast", 1000]);

/* the clipboard's plain text: blocks on lines, a blank line between them; a list's items on lines of their own, led by
   their marker after two spaces per level; a line break inside an item goes on under its text */
const sliceAll = blocks => (doc => doc.slice(0, doc.content.size))(docOf(blocks));
const listDoc = [para("Tekst"), dec("Een"), item("lower-alpha", "Sub", 1), dec("Twee"), item("bullet", "Punt"), para("Slot")];
eq("clipboard:text lists with markers", F.clipboardText(sliceAll(listDoc)), "Tekst\n\n1. Een\n  a. Sub\n2. Twee\n\n• Punt\n\nSlot");
eq("clipboard:text a line break in an item, and a poem",
  F.clipboardText(sliceAll([{type: "list_item", attrs: {list: "decimal", level: 0, start: 12}, content: [txt("Een"), {type: "hard_break"}, txt("twee")]},
    {type: "poem", attrs: {src: null}, content: [{type: "paragraph", content: [txt("regel"), {type: "hard_break"}, txt("regel")]}, para("strofe")]}])),
  "12. Een\n    twee\n\nregel\nregel\n\nstrofe");
eq("clipboard:text containers, scene breaks; notes left out",
  F.clipboardText(sliceAll([titled("Titel"), {type: "epigraph", content: [para("Motto"), {type: "attribution", content: [txt("Wie")]}]},
    {type: "paragraph", content: [txt("Een"), {type: "note", content: [txt("noot")]}, txt(" twee")]}, {type: "scene_break"}, al("center", "Midden"), bq("Citaat")])),
  "Titel\n\nMotto\n\n— Wie\n\nEen twee\n\n* * *\n\nMidden\n\nCitaat");
eq("clipboard:text math as its source", F.clipboardText(sliceAll([{type: "paragraph", content: [txt("Zie "), {type: "math", attrs: {tex: "x^2"}}]},
  {type: "math_display", attrs: {tex: "a+b"}}, dec("met "), {type: "table", content: [{type: "table_row", content: [{type: "table_cell", content: [txt("a")]},
  {type: "table_cell", content: [txt("b")]}]}, {type: "table_row", content: [{type: "table_cell", content: [txt("c")]}, {type: "table_cell"}]}]}])),
  "Zie $x^2$\n\n$$a+b$$\n\n1. met \n\na\tb\nc\t");
const fourDoc = docOf([dec("Een"), dec("Twee"), dec("Drie"), dec("Vier")]);
const partOf = (from, to) => P.EditorState.create({doc: fourDoc, selection: P.TextSelection.create(fourDoc, from, to)});
const mid = partOf(cursor(fourDoc, 1, 1), cursor(fourDoc, 2));     // from inside "Twee" to the end of "Drie"
eq("clipboard:text an item copied from its middle has no marker", F.clipboardText(mid.selection.content()), "wee\n2. Drie");
const lastTwo = partOf(cursor(fourDoc, 2, 0), cursor(fourDoc, 3));      // from the start of "Drie"'s text to the end of "Vier"
eq("clipboard:text with the editor's state: the numbers it shows, from an item's start", [F.clipboardText(mid.selection.content(), mid),
  F.clipboardText(lastTwo.selection.content(), lastTwo), F.clipboardText(lastTwo.selection.content(), mid)],
  ["wee\n3. Drie", "3. Drie\n4. Vier", "Drie\n2. Vier"]);
const inOne = partOf(cursor(fourDoc, 1, 1), cursor(fourDoc, 1, 3)), wholeOne = partOf(cursor(fourDoc, 1, 0), cursor(fourDoc, 1));
eq("clipboard:text inside one item: only the words", [F.clipboardText(inOne.selection.content()), F.clipboardText(inOne.selection.content(), inOne),
  F.clipboardText(wholeOne.selection.content(), wholeOne)], ["we", "we", "Twee"]);
// a copy that only touches a neighbouring item (to its start, from its end) brings no empty item along
const toNextStart = partOf(cursor(fourDoc, 1, 0), cursor(fourDoc, 3, 0)), fromPrevEnd = partOf(cursor(fourDoc, 0), cursor(fourDoc, 2));
eq("clipboard:text no empty item at an edge", [F.clipboardText(toNextStart.selection.content(), toNextStart), F.clipboardText(fromPrevEnd.selection.content(), fromPrevEnd),
  F.clipboardText(fromPrevEnd.selection.content())], ["2. Twee\n3. Drie", "2. Twee\n3. Drie", "1. Twee\n2. Drie"]);

/* paste into a poem line: list items become lines led by their marker */
const asLines = (blocks, open = 0) => F.itemsAsLines(P.Fragment.fromJSON(S, blocks), open).toJSON().map(n => [n.type, (n.content || []).map(c => c.text || c.type).join("")]);
eq("paste:poem items become lines with their marker", asLines([dec("Een"), item("lower-alpha", "Sub", 1), para("Tekst"), item("bullet", "Punt")]),
  [["paragraph", "1. Een"], ["paragraph", "\u00A0\u00A0a. Sub"], ["paragraph", "Tekst"], ["paragraph", "• Punt"]]);
eq("paste:poem an item open at the start keeps its text alone", asLines([dec("wee"), dec("Drie")], 1), [["paragraph", "wee"], ["paragraph", "2. Drie"]]);
eq("paste:poem marks stay", F.itemsAsLines(P.Fragment.fromJSON(S, [{type: "list_item", attrs: {list: "bullet", level: 0, start: null},
  content: [{type: "text", text: "vet", marks: [{type: "strong"}]}]}]), 0).toJSON()[0].content, [{type: "text", text: "• "}, {type: "text", marks: [{type: "strong"}], text: "vet"}]);

/* paste from outside: the list style of an HTML list item, Word's marker text */
eq("paste:style of an HTML list", [F.listStyleOf("lower-latin", null, true), F.listStyleOf(null, "I", true), F.listStyleOf(null, "a", true),
  F.listStyleOf(null, null, true), F.listStyleOf(null, null, false), F.listStyleOf("disc", null, false), F.listStyleOf("square", null, true),
  F.listStyleOf("decimal", null, false), F.listStyleOf("none", null, true), F.listStyleOf("upper-roman", "a", true), F.listStyleOf(" Upper-Alpha ", null, false),
  F.listStyleOf("decimal-leading-zero", null, true)],
  ["lower-alpha", "upper-roman", "lower-alpha", "decimal", "bullet", "bullet", "bullet", "decimal", "decimal", "upper-roman", "upper-alpha", "decimal"]);
eq("paste:Word's marker text", [F.wordMarker("1."), F.wordMarker("3)"), F.wordMarker("a."), F.wordMarker("(b)"), F.wordMarker("i."),
  F.wordMarker("i.", "lower-alpha"), F.wordMarker("IV."), F.wordMarker("·"), F.wordMarker("o"), F.wordMarker("§"), F.wordMarker("1.2."), F.wordMarker(""),
  F.wordMarker("aa.")],
  [["decimal", 1], ["decimal", 3], ["lower-alpha", 1], ["lower-alpha", 2], ["lower-roman", 1], ["lower-alpha", 9], ["upper-roman", 4],
   ["bullet", null], ["bullet", null], ["bullet", null], ["decimal", null], ["bullet", null], ["lower-alpha", null]]);
eq("paste:without a DOM the HTML is left as it is", F.pasteLists("<ul><li>Een</li></ul>"), "<ul><li>Een</li></ul>");
/* the editor's own copy: words from inside one item run into the line; items at the ends of a copy of several blocks
   come in whole */
const words = inOne.selection.content(), several = mid.selection.content(), closed = F.pastedLists(several);
const itemThenText = partOf(cursor(fourDoc, 1, 1), cursor(fourDoc, 1)).selection.content();
eq("paste:own copies", [F.pastedLists(words) === words, [several.openStart, several.openEnd], [closed.openStart, closed.openEnd], closed.content.eq(several.content),
  F.pastedLists(itemThenText) === itemThenText],
  [true, [1, 1], [0, 0], true, true]);
const mixed2 = (st => st.selection.content())(P.EditorState.create({doc: docOf([para("Een"), dec("Twee"), para("Drie")]),
  selection: P.TextSelection.create(docOf([para("Een"), dec("Twee"), para("Drie")]), 2, 13)}));
eq("paste:own copies close only an item's end", (s => [s.openStart, s.openEnd])(F.pastedLists(mixed2)), [1, 1]);
const shapeOf = s => [s.content.toJSON().map(n => [n.type, (n.content || []).map(c => c.text).join("")]), s.openStart, s.openEnd];
const lineOnlyState = partOf(cursor(fourDoc, 0), cursor(fourDoc, 1, 0)), lineOnly = lineOnlyState.selection.content();   // from the end of Een to Twee's start
eq("clipboard:text a copy of a line's end and the next one's start is a line break", [F.clipboardText(lineOnly, lineOnlyState), F.clipboardText(lineOnly)], ["\n", "\n"]);
eq("paste:own copies bring no empty item from an edge", [shapeOf(F.pastedLists(toNextStart.selection.content())), shapeOf(F.pastedLists(fromPrevEnd.selection.content())),
  F.pastedLists(lineOnly) === lineOnly],
  [[[["list_item", "Twee"], ["list_item", "Drie"]], 0, 0], [[["list_item", "Twee"], ["list_item", "Drie"]], 0, 0], true]);
// pasted into empty line between two paragraphs, as the view pastes
const pastedAt = sl => { const d = docOf([para("x"), para(), para("y")]); let st = P.EditorState.create({doc: d, plugins: [F.numbersPlugin()], selection: P.TextSelection.create(d, 4)});
  st = st.apply(st.tr.replaceSelection(sl)); return st.doc.toJSON().content.map(n => [n.type, (n.content || []).map(c => c.text).join("")]); };
eq("paste:own copies of items into an empty line", [pastedAt(F.pastedLists(toNextStart.selection.content())), pastedAt(F.pastedLists(fromPrevEnd.selection.content()))],
  [[["paragraph", "x"], ["list_item", "Twee"], ["list_item", "Drie"], ["paragraph", "y"]], [["paragraph", "x"], ["list_item", "Twee"], ["list_item", "Drie"], ["paragraph", "y"]]]);

console.log(JSON.stringify({failures, checked, reload}));
