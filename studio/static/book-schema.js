// schema: nodes=doc,title,heading,paragraph,blockquote,scene_break,epigraph,attribution,poem,image,page_break,hard_break,note,cite,text; marks=em,strong,idx,comment,smallcaps,lang
/* The book editor's ProseMirror schema: the manuscript dialect of studio/manuscript.py, node for node.
   Documents travel between server and editor as ProseMirror JSON; attribute defaults are null so that
   toJSON writes the same attrs Python does. Needs window.PM (vendor/prosemirror.js); sets window.BookSchema.
   tests/test_schema_parity.py keeps this file and manuscript.SCHEMA in step. */
(function () {
  "use strict";
  const {Schema} = PM;

  // The editor's own elements win over generic ones (p, h1, hr, span) whatever the definition order.
  const OWN = 60;
  const cls = (name, tag = "span") => ({tag: `${tag}.${name}`, priority: OWN});
  const WIDTH = /^\d+(\.\d+)?(%|px)?$/;
  const attr = (dom, name) => dom.getAttribute(name);

  const nodes = {
    doc: {attrs: {form: {default: "prose"}}, content: "title? block*"},
    title: {content: "(text | note | cite)*", defining: true, parseDOM: [cls("bk-title", "h1")],
            toDOM: () => ["h1", {class: "bk-title"}, 0]},
    // level has no default: a heading always says its level, and so the paragraph (not the heading, which comes first
    // in the block group) is what ProseMirror makes wherever it needs "a block" (Enter after a title, typing at a gap).
    heading: {
      attrs: {level: {}}, content: "(text | note | cite)*", group: "block", defining: true,
      parseDOM: [{tag: "h1", attrs: {level: 2}}, {tag: "h2", attrs: {level: 2}}, {tag: "h3", attrs: {level: 3}},
                 {tag: "h4", attrs: {level: 3}}, {tag: "h5", attrs: {level: 3}}, {tag: "h6", attrs: {level: 3}}],
      toDOM: n => ["h" + n.attrs.level, 0],
    },
    paragraph: {content: "inline*", group: "block", parseDOM: [{tag: "p"}], toDOM: () => ["p", 0]},
    blockquote: {content: "paragraph+", group: "block", defining: true, parseDOM: [{tag: "blockquote"}],
                 toDOM: () => ["blockquote", 0]},
    scene_break: {group: "block", parseDOM: [cls("bk-scene", "hr")], toDOM: () => ["hr", {class: "bk-scene"}]},
    epigraph: {content: "paragraph* attribution?", group: "block", defining: true,
               parseDOM: [cls("bk-epigraph", "div")], toDOM: () => ["div", {class: "bk-epigraph"}, 0]},
    attribution: {content: "inline*", defining: true, parseDOM: [cls("bk-attr", "p")],
                  toDOM: () => ["p", {class: "bk-attr"}, 0]},
    poem: {
      attrs: {src: {default: null}}, content: "paragraph*", group: "block", defining: true,
      parseDOM: [{tag: "div.bk-poem", priority: OWN, getAttrs: d => ({src: attr(d, "data-src")})}],
      toDOM: n => ["div", n.attrs.src ? {class: "bk-poem", "data-src": n.attrs.src} : {class: "bk-poem"}, 0],
    },
    image: {
      attrs: {src: {default: ""}, alt: {default: ""}, width: {default: null}}, group: "block", draggable: true,
      // Only the editor's own images come back from a paste (`../images/…`): data: URIs and remote images from
      // Word, Docs or the web are dropped.
      parseDOM: [{tag: "img[src]", priority: OWN, getAttrs: d => {
        const src = attr(d, "src") || "", width = attr(d, "data-width");
        if (!src.startsWith("../images/")) return false;
        return {src, alt: attr(d, "alt") || "", width: WIDTH.test(width || "") ? width : null};
      }}],
      toDOM: n => ["img", Object.assign({src: n.attrs.src, alt: n.attrs.alt, class: "bk-img"},
                                        WIDTH.test(n.attrs.width || "")
                                          ? {"data-width": n.attrs.width, style: `width:${n.attrs.width}`} : {})],
    },
    page_break: {group: "block", parseDOM: [cls("bk-page", "hr")], toDOM: () => ["hr", {class: "bk-page"}]},
    hard_break: {inline: true, group: "inline", selectable: false, parseDOM: [{tag: "br"}], toDOM: () => ["br"]},
    note: {
      // an inline atom: the text shows its number, and its own text is edited in the margin (book-text.js)
      inline: true, group: "inline", content: "(text | hard_break | cite)*", atom: true, isolating: true,
      parseDOM: [cls("bk-note", "sup")], toDOM: () => ["sup", {class: "bk-note"}, 0],
    },
    cite: {
      inline: true, group: "inline", atom: true, attrs: {items: {default: []}},
      parseDOM: [{tag: "span.bk-cite", priority: OWN, getAttrs: d => { try { return {items: JSON.parse(attr(d, "data-items"))}; } catch (e) { return {items: []}; } }}],
      toDOM: n => ["span", {class: "bk-cite", "data-items": JSON.stringify(n.attrs.items)},
                   "[" + n.attrs.items.map(i => (i.prefix ? i.prefix + " " : "") + "@" + i.key +
                                                (i.locator ? ", " + i.locator : "")).join("; ") + "]"],
    },
    text: {group: "inline"},
  };

  const marks = {
    em: {parseDOM: [{tag: "em"}, {tag: "i"}, {style: "font-style=italic"}], toDOM: () => ["em", 0]},
    strong: {parseDOM: [{tag: "strong"}, {tag: "b", getAttrs: d => !/^(normal|[1-5]00)$/.test(d.style.fontWeight) && null},
                        {style: "font-weight", getAttrs: v => /^(bold(er)?|[6-9]00)$/.test(v) && null}],
             toDOM: () => ["strong", 0]},
    idx: {
      attrs: {term: {default: null}}, inclusive: false,
      parseDOM: [{tag: "span.bk-idx", priority: OWN, getAttrs: d => ({term: attr(d, "data-term")})}],
      toDOM: m => ["span", m.attrs.term == null ? {class: "bk-idx"} : {class: "bk-idx", "data-term": m.attrs.term}, 0],
    },
    comment: {
      attrs: {note: {default: ""}}, inclusive: false,
      parseDOM: [{tag: "mark.bk-comment", priority: OWN, getAttrs: d => ({note: attr(d, "data-note") || ""})}],
      toDOM: m => ["mark", {class: "bk-comment", "data-note": m.attrs.note, title: m.attrs.note}, 0],
    },
    smallcaps: {parseDOM: [cls("bk-sc")], toDOM: () => ["span", {class: "bk-sc"}, 0]},
    lang: {
      attrs: {lang: {default: null}}, inclusive: false,
      // Only the editor's own spans: Word and Docs put lang="EN-US" on nearly every run.
      parseDOM: [{tag: "span.bk-lang[lang]", priority: OWN, getAttrs: d => ({lang: attr(d, "lang")})}],
      toDOM: m => ["span", {class: "bk-lang", lang: m.attrs.lang}, 0],
    },
  };

  const schema = new Schema({nodes, marks});
  (typeof window !== "undefined" ? window : globalThis).BookSchema = schema;
})();
