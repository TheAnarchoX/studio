/* Loads the vendored editor bundle and book-schema.js in node and checks that documents written by
   studio/manuscript.py survive Node.fromJSON(BookSchema, json).toJSON() unchanged and are valid in the schema.
   Used by tests/test_schema_parity.py.

     node schema_roundtrip.js <prosemirror.js> <book-schema.js> <input.json>
     input: [document, ...]
     output: {"count": n, "failures": [{"index", "problem", ...}], "checks": [...], "names": {"nodes", "marks"}}   */
"use strict";
const fs = require("fs"), vm = require("vm");
const [pm, schema, input] = process.argv.slice(2);
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(pm, "utf8"));
if (typeof PM !== "undefined") globalThis.PM = PM;
vm.runInThisContext(fs.readFileSync(schema, "utf8"));
const S = globalThis.BookSchema;
const docs = JSON.parse(fs.readFileSync(input, "utf8"));
const failures = [];
docs.forEach((doc, index) => {
  try {
    const node = globalThis.PM.Node.fromJSON(S, doc);
    node.check();
    const back = JSON.parse(JSON.stringify(node.toJSON()));
    if (JSON.stringify(back) !== JSON.stringify(doc)) failures.push({index, problem: "differs", back, doc});
  } catch (e) {
    failures.push({index, problem: String(e && e.message || e)});
  }
});

// Paste and display rules, checked without a DOM: rules get tiny stand-in elements.
const checks = [];
const check = (name, ok) => { if (!ok) checks.push(name); };
const el = (attrs = {}, fontWeight = "") => ({getAttribute: n => (n in attrs ? attrs[n] : null), style: {fontWeight}});
const rules = spec => spec.parseDOM || [];
for (const [kind, set] of [["node", S.spec.nodes], ["mark", S.spec.marks]]) {
  set.forEach((name, spec) => rules(spec).forEach(r => {
    if (r.tag && /\.bk-/.test(r.tag)) check(`${kind} ${name}: ${r.tag} outranks generic rules`, r.priority >= 60);
  }));
}
const rejects = (type, child, attrs = null) => { try { S.nodes[type].create(attrs, [S.nodes[child].create()]).check(); return false; } catch (e) { return true; } };
check("heading rejects hard_break", rejects("heading", "hard_break", {level: 2}));
check("a heading needs its level", S.nodes.heading.hasRequiredAttrs());
check("notes are inline atoms", S.nodes.note.isAtom && S.nodes.note.isInline);
check("block default is the paragraph", S.nodes.doc.contentMatch.matchType(S.nodes.title).defaultType === S.nodes.paragraph);
check("title rejects hard_break", rejects("title", "hard_break"));
const imgSpec = S.spec.nodes.get("image"), imgRule = rules(imgSpec)[0];
check("image: data URI dropped", imgRule.getAttrs(el({src: "data:image/png;base64,AAAA"})) === false);
check("image: remote dropped", imgRule.getAttrs(el({src: "https://example.com/a.png"})) === false);
check("image: own kept", JSON.stringify(imgRule.getAttrs(el({src: "../images/a.jpg", alt: "x", "data-width": "60%"}))) === JSON.stringify({src: "../images/a.jpg", alt: "x", width: "60%"}));
check("image: bad width dropped", imgRule.getAttrs(el({src: "../images/a.jpg", "data-width": "1;x:y"})).width === null);
check("image: bad width not in style", !("style" in imgSpec.toDOM({attrs: {src: "../images/a.jpg", alt: "", width: "1;x:y"}})[1]));
check("lang: only own spans", rules(S.spec.marks.get("lang")).every(r => /bk-lang/.test(r.tag)));
const strong = rules(S.spec.marks.get("strong"));
const sRule = strong.find(r => r.style), bRule = strong.find(r => r.tag === "b");
check("strong: style 600, 700 and bold are bold", ["600", "700", "bold"].every(v => sRule.getAttrs(v) === null));
check("strong: style 400 and normal are not", sRule.getAttrs("400") === false && sRule.getAttrs("normal") === false);
check("strong: b normal is not bold", bRule.getAttrs(el({}, "normal")) === false && bRule.getAttrs(el({}, "")) === null);
const liSpec = S.spec.nodes.get("list_item"), liRule = liSpec && rules(liSpec)[0];
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const li = attrs => liRule.getAttrs(el(attrs));
check("a list item needs its style", !!liSpec && S.nodes.list_item.hasRequiredAttrs());
check("list_item: unknown style dropped", !!liRule && li({"data-list": "square"}) === false);
check("list_item: level clamped, start read", !!liRule &&
  same(li({"data-list": "decimal", "data-level": "7", "data-start": "3"}), {list: "decimal", level: 3, start: 3}) &&
  same(li({"data-list": "bullet", "data-level": "-1", "data-start": "x"}), {list: "bullet", level: 0, start: null}));
check("list_item: start only when set", !!liSpec &&
  same(liSpec.toDOM({attrs: {list: "lower-alpha", level: 1, start: null}}),
       ["p", {class: "bk-li", "data-list": "lower-alpha", "data-level": "1"}, 0]) &&
  same(liSpec.toDOM({attrs: {list: "decimal", level: 0, start: 3}}),
       ["p", {class: "bk-li", "data-list": "decimal", "data-level": "0", "data-start": "3"}, 0]));
// alignment: the editor's own divs only (pasted text-align is not kept), centre or right
const alSpec = S.spec.nodes.get("aligned"), alRule = alSpec && rules(alSpec)[0];
const al = attrs => alRule.getAttrs(el(attrs));
check("an aligned block needs its alignment", !!alSpec && S.nodes.aligned.hasRequiredAttrs());
check("aligned: own divs only", !!alSpec && rules(alSpec).length === 1 && alRule.tag === "div.bk-align");
check("aligned: centre and right kept, others dropped", !!alRule && same(al({"data-align": "center"}), {align: "center"}) &&
  same(al({"data-align": "right"}), {align: "right"}) && al({"data-align": "left"}) === false && al({}) === false);
check("aligned: toDOM", !!alSpec &&
  same(alSpec.toDOM({attrs: {align: "right"}}), ["div", {class: "bk-align", "data-align": "right"}, 0]));
check("aligned holds paragraphs", !!alSpec && !rejects("aligned", "paragraph", {align: "center"}) &&
  rejects("aligned", "blockquote", {align: "center"}));
// underline and strikethrough: tags and text-decoration from anywhere; sizes from the editor's own spans only
const markSpec = name => S.spec.marks.get(name) || {};
const styleRule = (name, prop) => rules(markSpec(name)).find(r => r.style === prop);
const decorated = (name, word) => ["text-decoration", "text-decoration-line"].every(prop => {
  const r = styleRule(name, prop);
  return !!r && r.getAttrs(word) === null && r.getAttrs(`${word} solid`) === null && r.getAttrs("none") === false;
});
check("underline: u", rules(markSpec("underline")).some(r => r.tag === "u") && same(markSpec("underline").toDOM?.(), ["u", 0]));
check("underline: text-decoration underline", decorated("underline", "underline") &&
  styleRule("underline", "text-decoration").getAttrs("line-through") === false);
check("strike: del", ["s", "del", "strike"].every(t => rules(markSpec("strike")).some(r => r.tag === t)) &&
  same(markSpec("strike").toDOM?.(), ["s", 0]));
check("strike: text-decoration line-through", decorated("strike", "line-through") &&
  styleRule("strike", "text-decoration").getAttrs("underline") === false);
const sizeSpec = markSpec("size"), sizeRule = rules(sizeSpec)[0];
check("size: own spans only", rules(sizeSpec).length === 1 && /^span\.bk-size/.test(sizeRule.tag) && sizeRule.priority >= 60 &&
  ["x-small", "small", "large", "x-large"].every(size => same(sizeRule.getAttrs(el({"data-size": size})), {size})) &&
  sizeRule.getAttrs(el({"data-size": "medium"})) === false && sizeRule.getAttrs(el({"data-size": "12pt"})) === false);
check("size: a size is always said", !!sizeSpec.attrs && !("default" in sizeSpec.attrs.size));
check("size: toDOM", same(sizeSpec.toDOM?.({attrs: {size: "large"}}), ["span", {class: "bk-size", "data-size": "large"}, 0]));
check("size: one per text", !!S.marks.size && S.marks.size.excludes(S.marks.size));
// tables: a cell is one line of text (no line breaks); the editor's own tables keep header and alignment through copy
// and paste; a pasted table has a header when its first row is all `th` (or in a `thead`), and no alignments
const tbSpec = S.spec.nodes.get("table"), tbRules = tbSpec ? rules(tbSpec) : [];
const ownTb = tbRules.find(r => r.tag === "table.bk-table"), pastedTb = tbRules.find(r => r.tag === "table");
const tableEl = (attrs, rows, thead = false) => ({getAttribute: n => (n in attrs ? attrs[n] : null),
  rows: rows.map((cells, k) => ({cells: cells.map(nodeName => ({nodeName})), parentNode: {nodeName: thead && k === 0 ? "THEAD" : "TBODY"}}))});
check("table: nodes in place", !!tbSpec && !!S.nodes.table_row && !!S.nodes.table_cell && S.nodes.table.isBlock &&
  !!S.nodes.table.spec.isolating && !!S.nodes.table_cell.spec.isolating);
check("table_cell rejects hard_break", !!S.nodes.table_cell && rejects("table_cell", "hard_break"));
check("table_cell holds notes and citations", !!S.nodes.table_cell && !rejects("table_cell", "note") && !rejects("table_cell", "cite"));
check("table: header true and align [] by default", !!tbSpec && S.nodes.table.create(null, [S.nodes.table_row.createAndFill()]).attrs.header === true &&
  same(S.nodes.table.create(null, [S.nodes.table_row.createAndFill()]).attrs.align, []));
check("table: toDOM", !!tbSpec && same(tbSpec.toDOM({attrs: {header: false, align: [null, "center", "right"]}}),
  ["table", {class: "bk-table", "data-header": "false", "data-align": ",center,right"}, ["tbody", 0]]));
check("table: own tables keep header and align", !!ownTb && ownTb.priority >= 60 &&
  same(ownTb.getAttrs(tableEl({"data-header": "false", "data-align": ",center,right"}, [["TD", "TD", "TD"]])),
       {header: false, align: [null, "center", "right"]}) &&
  same(ownTb.getAttrs(tableEl({"data-header": "true", "data-align": "left,justify"}, [["TD", "TD", "TD"], ["TD"]])),
       {header: true, align: ["left", null, null]}));
check("table: pasted, a th row is the header", !!pastedTb &&
  same(pastedTb.getAttrs(tableEl({}, [["TH", "TH"], ["TD", "TD", "TD"]])), {header: true, align: [null, null, null]}) &&
  same(pastedTb.getAttrs(tableEl({}, [["TD", "TD"], ["TD", "TD"]], true)), {header: true, align: [null, null]}) &&
  same(pastedTb.getAttrs(tableEl({}, [["TH", "TD"], ["TH", "TD"]])), {header: false, align: [null, null]}) &&
  same(pastedTb.getAttrs(tableEl({}, [["TD", "TD"]])), {header: false, align: [null, null]}));
check("table rows and cells from tr, td and th", !!S.spec.nodes.get("table_row") &&
  rules(S.spec.nodes.get("table_row")).some(r => r.tag === "tr") &&
  ["td", "th"].every(t => rules(S.spec.nodes.get("table_cell") || {}).some(r => r.tag === t)));
// math: inline math is an atom wherever a citation can be (a paragraph made a heading keeps its math); display math is a
// block of its own, at the top level only; both keep their TeX through copy and paste
const mSpec = S.spec.nodes.get("math"), mdSpec = S.spec.nodes.get("math_display");
check("math: nodes in place", !!S.nodes.math && !!S.nodes.math_display && S.nodes.math.isAtom && S.nodes.math.isInline &&
  S.nodes.math_display.isAtom && S.nodes.math_display.isBlock && S.nodes.math.create().attrs.tex === "" &&
  S.nodes.math_display.create().attrs.tex === "");
const holds = (type, child, attrs = null) => { try { S.nodes[type].create(attrs, [S.nodes[child].create({tex: "x"})]).check(); return true; } catch (e) { return false; } };
check("a heading holds inline math (a paragraph made a heading keeps it)", !!S.nodes.math && holds("heading", "math", {level: 2}) &&
  holds("heading", "math", {level: 3}));
check("math in titles, paragraphs, items, attributions, notes and cells", !!S.nodes.math &&
  holds("title", "math") && holds("paragraph", "math") && holds("list_item", "math", {list: "bullet"}) &&
  holds("attribution", "math") && holds("note", "math") && holds("table_cell", "math"));
check("display math only at the top level", !!S.nodes.math_display &&
  S.nodes.doc.contentMatch.matchType(S.nodes.math_display) !== null && !holds("blockquote", "math_display") &&
  !holds("aligned", "math_display", {align: "center"}) && !holds("paragraph", "math_display"));
check("math: toDOM and parseDOM", !!mSpec && !!mdSpec &&
  same(mSpec.toDOM({attrs: {tex: "x^2"}}), ["span", {class: "bk-math", "data-tex": "x^2"}, "x^2"]) &&
  same(mdSpec.toDOM({attrs: {tex: "y"}}), ["div", {class: "bk-mathd", "data-tex": "y"}, "y"]) &&
  rules(mSpec).length === 1 && rules(mSpec)[0].tag === "span.bk-math" && same(rules(mSpec)[0].getAttrs(el({"data-tex": "a+b"})), {tex: "a+b"}) &&
  rules(mdSpec).length === 1 && rules(mdSpec)[0].tag === "div.bk-mathd" && same(rules(mdSpec)[0].getAttrs(el({"data-tex": "c"})), {tex: "c"}) &&
  rules(mSpec)[0].getAttrs(el({})).tex === "" );
// the names as the schema is built (the order of marks is the order Python writes them in)
const names = {nodes: Object.keys(S.nodes), marks: Object.keys(S.marks)};
console.log(JSON.stringify({count: docs.length, failures, checks, names}));
