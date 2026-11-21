// schema: nodes=doc,title,heading,paragraph,list_item,aligned,blockquote,scene_break,epigraph,attribution,poem,image,page_break,table,table_row,table_cell,math_display,hard_break,note,cite,math,text; marks=em,strong,idx,comment,smallcaps,lang,underline,strike,size
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
  const LISTS = ["bullet", "decimal", "lower-alpha", "upper-alpha", "lower-roman", "upper-roman"];
  const ALIGNS = ["center", "right"], SIZES = ["x-small", "small", "large", "x-large"];     // manuscript.ALIGNS, SIZES
  const COLUMN_ALIGNS = ["left", "center", "right"];                                         // manuscript.COLUMN_ALIGNS
  // a table element's columns: its longest row (at least one)
  const columns = d => Math.max(1, ...Array.from(d.rows || [], r => r.cells.length));
  const attr = (dom, name) => dom.getAttribute(name);
  const int = s => (/^-?\d+$/.test(s || "") ? parseInt(s, 10) : null);
  // style rules for a text-decoration line (`underline`, `line-through`), shorthand or longhand
  const decoration = line => ["text-decoration", "text-decoration-line"].map(style => (
    {style, getAttrs: v => String(v).split(/\s+/).includes(line) && null}));

  const nodes = {
    doc: {attrs: {form: {default: "prose"}}, content: "title? block*"},
    title: {content: "(text | note | cite | math)*", defining: true, parseDOM: [cls("bk-title", "h1")],
            toDOM: () => ["h1", {class: "bk-title"}, 0]},
    // level has no default: a heading always says its level, and so the paragraph (not the heading, which comes first
    // in the block group) is what ProseMirror makes wherever it needs "a block" (Enter after a title, typing at a gap).
    heading: {
      attrs: {level: {}}, content: "(text | note | cite | math)*", group: "block", defining: true,
      parseDOM: [{tag: "h1", attrs: {level: 2}}, {tag: "h2", attrs: {level: 2}}, {tag: "h3", attrs: {level: 3}},
                 {tag: "h4", attrs: {level: 3}}, {tag: "h5", attrs: {level: 3}}, {tag: "h6", attrs: {level: 3}}],
      toDOM: n => ["h" + n.attrs.level, 0],
    },
    paragraph: {content: "inline*", group: "block", parseDOM: [{tag: "p"}], toDOM: () => ["p", 0]},
    // A list is a run of items at the top level, never nested: `level` (0-3) says how deep an item is, `start` the
    // number its list starts at (manuscript_lists.py). `list` has no default: ProseMirror never makes an item itself.
    list_item: {
      attrs: {list: {}, level: {default: 0}, start: {default: null}}, content: "inline*", group: "block",
      parseDOM: [{tag: "p.bk-li", priority: OWN, getAttrs: d => {
        const list = attr(d, "data-list"), level = int(attr(d, "data-level")) || 0;
        if (!LISTS.includes(list)) return false;
        return {list, level: Math.min(Math.max(level, 0), 3), start: int(attr(d, "data-start"))};
      }}],
      toDOM: n => ["p", Object.assign({class: "bk-li", "data-list": n.attrs.list, "data-level": String(n.attrs.level)},
                                      n.attrs.start != null ? {"data-start": String(n.attrs.start)} : {}), 0],
    },
    // Centred or right-aligned paragraphs (`::: center`); "as the book" is no block. `align` has no default, so
    // ProseMirror never makes one itself; only the editor's own divs come back from a paste, not text-align.
    aligned: {
      attrs: {align: {}}, content: "paragraph+", group: "block", defining: true,
      parseDOM: [{tag: "div.bk-align", priority: OWN, getAttrs: d => {
        const align = attr(d, "data-align");
        return ALIGNS.includes(align) ? {align} : false;
      }}],
      toDOM: n => ["div", {class: "bk-align", "data-align": n.attrs.align}, 0],
    },
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
    // A pipe table: rows of cells, each cell one line of text. `header`: the first row is the header; `align`: one
    // alignment per column (null, "left", "center", "right"). The editor's own tables keep both through copy and paste
    // (data attributes); a pasted table has a header when its first row is all `th` or in a `thead`, and no alignments
    // (pasted text-align is not kept, as for paragraphs). It comes after the paragraph in the block group, so the
    // paragraph stays what ProseMirror makes wherever it needs "a block".
    table: {
      attrs: {header: {default: true}, align: {default: []}}, content: "table_row+", group: "block", isolating: true,
      parseDOM: [
        {tag: "table.bk-table", priority: OWN, getAttrs: d => {
          const align = (attr(d, "data-align") || "").split(",");
          return {header: attr(d, "data-header") !== "false",
                  align: Array.from({length: columns(d)}, (_, k) => (COLUMN_ALIGNS.includes(align[k]) ? align[k] : null))};
        }},
        {tag: "table", getAttrs: d => {
          const first = d.rows && d.rows[0], cells = first ? Array.from(first.cells) : [];
          const header = cells.length > 0 && (cells.every(c => c.nodeName === "TH") ||
                                               (!!first.parentNode && first.parentNode.nodeName === "THEAD"));
          return {header, align: Array(columns(d)).fill(null)};
        }},
      ],
      toDOM: n => ["table", {class: "bk-table", "data-header": String(n.attrs.header),
                             "data-align": n.attrs.align.map(a => a || "").join(",")}, ["tbody", 0]],
    },
    table_row: {content: "table_cell+", parseDOM: [{tag: "tr"}], toDOM: () => ["tr", 0]},
    // no hard_break in a cell: a pipe table's row is one line
    table_cell: {content: "(text | note | cite | math)*", isolating: true, parseDOM: [{tag: "td"}, {tag: "th"}],
                 toDOM: () => ["td", 0]},
    // LaTeX math: `tex` is its source. Display math is a block of its own at the top level (`$$` lines); inline math an
    // atom wherever a citation can be. Without a node view (book-math.js) both show their source; the editor's own
    // elements keep the source through copy and paste.
    math_display: {
      attrs: {tex: {default: ""}}, group: "block", atom: true,
      parseDOM: [{tag: "div.bk-mathd", priority: OWN, getAttrs: d => ({tex: attr(d, "data-tex") || ""})}],
      toDOM: n => ["div", {class: "bk-mathd", "data-tex": n.attrs.tex}, n.attrs.tex],
    },
    hard_break: {inline: true, group: "inline", selectable: false, parseDOM: [{tag: "br"}], toDOM: () => ["br"]},
    note: {
      // an inline atom: the text shows its number, and its own text is edited in the margin (book-text.js)
      inline: true, group: "inline", content: "(text | hard_break | cite | math)*", atom: true, isolating: true,
      parseDOM: [cls("bk-note", "sup")], toDOM: () => ["sup", {class: "bk-note"}, 0],
    },
    cite: {
      inline: true, group: "inline", atom: true, attrs: {items: {default: []}},
      parseDOM: [{tag: "span.bk-cite", priority: OWN, getAttrs: d => { try { return {items: JSON.parse(attr(d, "data-items"))}; } catch (e) { return {items: []}; } }}],
      toDOM: n => ["span", {class: "bk-cite", "data-items": JSON.stringify(n.attrs.items)},
                   "[" + n.attrs.items.map(i => (i.prefix ? i.prefix + " " : "") + "@" + i.key +
                                                (i.locator ? ", " + i.locator : "")).join("; ") + "]"],
    },
    math: {
      inline: true, group: "inline", atom: true, attrs: {tex: {default: ""}},
      parseDOM: [{tag: "span.bk-math", priority: OWN, getAttrs: d => ({tex: attr(d, "data-tex") || ""})}],
      toDOM: n => ["span", {class: "bk-math", "data-tex": n.attrs.tex}, n.attrs.tex],
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
    // Underline and strikethrough come in from anywhere (tags or text-decoration); a size only from the editor's own
    // spans, so pasted point sizes are not kept. One size per text: a size mark excludes another.
    underline: {parseDOM: [{tag: "u"}, ...decoration("underline")], toDOM: () => ["u", 0]},
    strike: {parseDOM: [{tag: "s"}, {tag: "del"}, {tag: "strike"}, ...decoration("line-through")], toDOM: () => ["s", 0]},
    size: {
      attrs: {size: {}},
      parseDOM: [{tag: "span.bk-size[data-size]", priority: OWN, getAttrs: d => {
        const size = attr(d, "data-size");
        return SIZES.includes(size) ? {size} : false;
      }}],
      toDOM: m => ["span", {class: "bk-size", "data-size": m.attrs.size}, 0],
    },
  };

  const schema = new Schema({nodes, marks});
  (typeof window !== "undefined" ? window : globalThis).BookSchema = schema;
})();
