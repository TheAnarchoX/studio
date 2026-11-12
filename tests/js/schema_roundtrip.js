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
// the names as the schema is built (the order of marks is the order Python writes them in)
const names = {nodes: Object.keys(S.nodes), marks: Object.keys(S.marks)};
console.log(JSON.stringify({count: docs.length, failures, checks, names}));
