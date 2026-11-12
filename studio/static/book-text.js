"use strict";
/* The text of the writing window (book-editor.js): one piece in a ProseMirror view, with its input rules and keys,
   the node views (notes, citations, images, linked poems), the margin where notes are written and comments stand,
   the selection bar, the / menu and the small citation and index forms.
   A classic script after vendor/prosemirror.js and book-schema.js; sets window.BookText. The helpers at the top
   touch no DOM, so tests/js/book_text.js runs them in node. */
(function (root) {
  const S = root.BookSchema;
  const {EditorState, EditorView, Plugin, PluginKey, TextSelection, NodeSelection, Selection, Decoration, DecorationSet,
    StepMap, keymap, baseKeymap, history, undo, redo, inputRules, InputRule, wrappingInputRule, textblockTypeInputRule,
    undoInputRule, toggleMark, chainCommands, dropCursor, gapCursor} = root.PM;
  const N = S.nodes, M = S.marks;

  /* ——— helpers (no DOM) ——— */

  /* The style sheet's quote marks: [open, close, single open, single close]. */
  const QUOTES = {"“…”": ["“", "”", "‘", "’"], "„…”": ["„", "”", "‚", "’"], "«…»": ["«", "»", "‹", "›"], "‘…’": ["‘", "’", "‘", "’"]};
  const quoteMarks = style => QUOTES[style] || QUOTES["“…”"];
  const unclosed = (s, open, close) => { let n = 0; for (const c of s) { if (c === open) n++; else if (c === close && n) n--; } return n > 0; };
  /* What a straight quote `ch` typed after `before` (the text before the cursor in its block) becomes in the book's quote
     style: " opens or closes the style's pair; ' opens or closes its single pair, and after a letter it is an apostrophe
     (the clitic rule turns ‘s, ‘t … at the start of a word into ’s, ’t once the word is typed). */
  function quoteFor(before, ch, style) {
    const [open, close, sOpen, sClose] = quoteMarks(style), last = before.slice(-1);
    const opening = !last || /[\s([{<—–/]/.test(last) || [open, sOpen, "\"", "'"].includes(last);
    if (ch === "\"") return opening ? open : close;
    if (opening) return sOpen;
    if (/[\p{L}\p{N}]$/u.test(before) && (sClose === "’" || !unclosed(before, sOpen, sClose))) return "’";
    return sClose;
  }
  /* ‘s avonds, ’t, ’n, ’k, ’m, ’r, ’ns, ’em, ’tis, ’twas, ’90, also before a hyphen (’s-Hertogenbosch): an apostrophe, not an opening quote. */
  const CLITIC = /(^|[\s([{<—–])([‘‚‹])(s|t|n|k|m|r|ns|em|tis|twas|\d\d)([\s.,;:!?…)\]-])$/u;

  /* Words as the server counts them (manuscript._word_count): whitespace-separated runs with a letter or digit, where a
     lone clitic ('s) is part of the next word. */
  const WORD = /[\p{L}\p{N}]/u, LONE_CLITIC = /^[(\[„“"«‹]*['’‘](?:s|t|n|k|m|r|ns)$/u;
  const countWords = text => String(text).split(/\s+/).filter(w => w && WORD.test(w) && !LONE_CLITIC.test(w)).length;
  const inlineText = node => { let s = ""; node.forEach(c => { s += c.isText ? c.text : c.type === N.hard_break ? "\n" : ""; }); return s; };
  /* The words of a piece (manuscript.counts "words"): its blocks without the title; no notes, citations or captions. */
  function docWords(doc) {
    const out = [];
    const block = n => {
      if (n.type === N.blockquote || n.type === N.epigraph || n.type === N.poem) n.forEach(block);
      else if (n.type === N.heading || n.type === N.paragraph || n.type === N.attribution) out.push(inlineText(n));
    };
    doc.forEach(n => { if (n.type !== N.title) block(n); });
    return countWords(out.join("\n\n"));
  }

  /* The number before a piece's first note: 0 when notes start again in every piece, else the notes of the pieces before
     it (GET /api/book gives each entry's `notes`). */
  function noteStart(contents, file, numbering) {
    if (numbering !== "book") return 0;
    let n = 0;
    for (const e of contents || []) { if (e.file === file) break; if (e.file) n += +e.notes || 0; }
    return n;
  }

  /* A citation's label from sources.json (CSL-JSON): `Author year, p. 12`, the key when the source is unknown. */
  const year = s => { const i = s.issued || {}; const d = i["date-parts"]?.[0]?.[0]; return d != null ? String(d) : String(i.literal || i.raw || ""); };
  /* a person as cited: the family name with its particles (CSL keeps "van", "de" apart), "van Dijk", "de Wit" */
  const person = p => !p ? "" : p.family ? [p["dropping-particle"], p["non-dropping-particle"], p.family].filter(Boolean).join(" ")
    : p.literal || p.given || "";
  const shortTitle = t => { t = String(t || "").trim(); return t.length > 32 ? t.slice(0, 31) + "…" : t; };
  function sourceShort(s) {
    const people = ((s.author && s.author.length ? s.author : s.editor) || []).map(person).filter(Boolean);
    const who = people.length > 2 ? `${people[0]} et al.` : people.join(" & ") || shortTitle(s.title);
    return [who, year(s)].filter(Boolean).join(" ");
  }
  function citeLabel(items, sources) {
    const by = new Map((sources || []).map(s => [s.id, s]));
    return (items || []).map(i => {
      const s = by.get(i.key), name = (s && sourceShort(s)) || i.key;
      return [i.prefix, name + (i.locator ? ", " + i.locator : "")].filter(Boolean).join(" ");
    }).join("; ");
  }
  const CITE_KEY = /^[\p{L}\p{N}_](?:[\p{L}\p{N}_:.#$%&+?~/-]*[\p{L}\p{N}_])?$/u;      // manuscript.CITE_KEY

  /* The / menu: its items (those of a feature the book has switched off are left out), filtered by what is typed after
     the slash: names starting with it first, then a word starting with it, then any match. */
  const SLASH = [
    {id: "note", label: "Note", on: f => !!f.notes && f.notes !== "off"},
    {id: "cite", label: "Citation", on: f => f.sources === true},
    {id: "scene", label: "Scene break"}, {id: "epigraph", label: "Epigraph"}, {id: "poem", label: "Poem"},
    {id: "image", label: "Image"}, {id: "page", label: "Page break"}, {id: "linked", label: "Linked poem"},
  ];
  function slashItems(query, features) {
    const q = String(query || "").trim().toLowerCase(), items = SLASH.filter(i => !i.on || i.on(features || {}));
    if (!q) return items;
    const rank = i => { const l = i.label.toLowerCase(); return l.startsWith(q) ? 0 : l.split(/\s+/).some(w => w.startsWith(q)) ? 1 : q.length > 1 && l.includes(q) ? 2 : 9; };
    return items.map(i => [rank(i), i]).filter(([r]) => r < 9).sort((a, b) => a[0] - b[0]).map(([, i]) => i);
  }
  /* Which bar buttons a book's features allow (Index only for a subject index, not "first-lines"). */
  const barButtons = f => [["bold", "Bold"], ["italic", "Italic"],
    ...(f.notes && f.notes !== "off" ? [["note", "Note"]] : []), ...(f.sources === true ? [["source", "Source"]] : []),
    ...(f.index === true ? [["index", "Index"]] : []), ["comment", "Comment"]];

  /* The comments of a document as ranges: neighbouring text with the same comment mark is one comment. */
  function commentRanges(doc) {
    const out = [];
    doc.descendants((n, pos) => {
      if (!n.isInline) return true;
      const m = M.comment.isInSet(n.marks), last = out[out.length - 1];
      if (m && last && last.to === pos && last.mark.eq(m)) last.to = pos + n.nodeSize;
      else if (m) out.push({from: pos, to: pos + n.nodeSize, mark: m});
      return false;                     // not into a note's own text
    });
    return out;
  }
  /* An index term as typed: `a>b` is written `a > b`; empty is null. */
  const indexTerm = t => String(t || "").split(">").map(s => s.replace(/\s+/g, " ").trim()).filter(Boolean).join(" > ") || null;
  /* A comment is one line (the Markdown writes it in an attribute): line breaks typed or pasted into it become spaces. */
  const oneLine = s => String(s ?? "").replace(/\r\n|[\r\n]/g, " ");

  /* A piece's title as plain text (document JSON), "" when it has none. */
  const titleOf = doc => { const t = (doc.content || [])[0]; return t && t.type === "title" ? (t.content || []).map(n => n.text || "").join("").replace(/\s+/g, " ").trim() : ""; };
  /* A document (JSON) with another title, the piece's first line: notes and citations in the old title stay; no title
     and nothing kept removes the title. */
  function withTitle(doc, title) {
    const content = [...(doc.content || [])], first = content[0], isTitle = first && first.type === "title";
    const keep = isTitle ? (first.content || []).filter(n => n.type !== "text") : [];
    const node = {type: "title", content: [...(title ? [{type: "text", text: title}] : []), ...keep]};
    if (isTitle) { if (node.content.length) content[0] = node; else content.shift(); }
    else if (node.content.length) content.unshift(node);
    return {...doc, content};
  }

  /* A loaded document made editable: a block to type in when there is none, a paragraph in an empty poem or epigraph. */
  function editableDoc(json) {
    const doc = JSON.parse(JSON.stringify(json && json.type === "doc" ? json : {type: "doc", attrs: {form: "prose"}}));
    doc.content = doc.content || [];
    for (const b of doc.content) {
      if ((b.type === "poem" && !(b.attrs && b.attrs.src) || b.type === "epigraph") && !(b.content || []).some(c => c.type === "paragraph")) {
        b.content = [{type: "paragraph"}, ...(b.content || [])];
      }
    }
    if (!doc.content.some(b => b.type !== "title")) doc.content.push({type: "paragraph"});
    return doc;
  }

  /* ——— poem lines keep their indentation ———
     Markdown drops spaces and tabs at the start of a line; the dialect keeps no-break spaces. So in a poem line (a piece
     whose form is poem, a ::: poem block) spaces typed or pasted at the start of a line become no-break spaces, and a
     tab two. Prose is unchanged. */
  const NBSP = "\u00A0";
  const indent = s => s.replace(/[ \t]/g, c => c === "\t" ? NBSP + NBSP : NBSP);
  const poemLine = $p => $p.parent.type === N.paragraph && inPoem($p);
  /* the line so far: the text of the paragraph before the position, after its last line break */
  const lineSoFar = $p => $p.parent.textBetween(0, $p.parentOffset, null, n => n.type === N.hard_break ? "\n" : "￼").split("\n").pop();
  const atLineStart = $p => /^\u00A0*$/.test(lineSoFar($p));
  /* what typing `text` at `from` puts in: spaces and tabs at the start of a poem line (nothing but no-break spaces before
     them) as no-break spaces; null when it goes in as typed */
  function poemTyped(state, from, text) {
    const $f = state.doc.resolve(from);
    return /^[ \t]+$/.test(text) && poemLine($f) && atLineStart($f) ? indent(text) : null;
  }
  /* Tab in a poem line: two no-break spaces (at the start of the line an indent, further on a gap) */
  function poemTab(state, dispatch) {
    if (!(state.selection instanceof TextSelection) || !poemLine(state.selection.$from)) return false;
    dispatch?.(state.tr.insertText(NBSP + NBSP).scrollIntoView());
    return true;
  }
  /* A slice pasted (or dropped) into a poem line: the spaces and tabs at the start of each of its lines as no-break
     spaces. Its first line continues the line it goes into when the slice is open there, so it counts only when that
     line has nothing before it yet. */
  function poemPasted(slice, lineStart) {
    let first = true;
    const walk = frag => {
      const out = [];
      frag.forEach(n => {
        if (!n.isTextblock) { out.push(n.content.size ? n.copy(walk(n.content)) : n); return; }
        let start = first && slice.openStart > 0 ? lineStart : true;
        first = false;
        const kids = [];
        n.forEach(c => {
          if (c.type === N.hard_break) start = true;
          else if (c.isText && start) {
            const text = c.text.replace(/^[ \t\u00A0]+/, indent);
            start = !text.replace(/\u00A0/g, "");
            if (text !== c.text) c = S.text(text, c.marks);
          } else start = false;
          kids.push(c);
        });
        out.push(n.copy(root.PM.Fragment.from(kids)));
      });
      return root.PM.Fragment.from(out);
    };
    return new root.PM.Slice(walk(slice.content), slice.openStart, slice.openEnd);
  }
  /* Plain text pasted into a poem line keeps its lines (a blank line between stanzas) and their indentation. */
  function poemText(text, marks, lineStart) {
    const body = String(text).replace(/\r\n?/g, "\n").replace(/^\n+|\n+$/g, "");
    const stanzas = body.split(/\n[ \t]*\n(?:[ \t]*\n)*/).map((stanza, i) => {
      const kids = [];
      stanza.split("\n").forEach((line, j) => {
        if (j) kids.push(N.hard_break.create(null, null, marks));
        const t = i || j || lineStart ? line.replace(/^[ \t]+/, indent) : line;
        if (t) kids.push(S.text(t, marks));
      });
      return N.paragraph.create(null, kids);
    });
    return new root.PM.Slice(root.PM.Fragment.from(stanzas), 1, 1);
  }

  /* ——— input rules ——— */
  /* *x* and **x**: the delimiters go and the mark goes on. Checked against the document, so a run that crosses a note
     (whose text the matcher reads inline) is left alone. */
  const markRule = (re, type, len) => new InputRule(re, (state, m, start, end) => {
    const inner = m[2], from = start + m[0].length - m[1].length;
    if (state.doc.textBetween(from, end, "\n", "￼") !== m[1].slice(0, -1)) return null;
    const tr = state.tr;
    if (len > 1) tr.delete(end - (len - 1), end);
    tr.delete(from, from + len);
    return tr.addMark(from, from + inner.length, type.create()).removeStoredMark(type);
  });
  function inlineRules(quotes) {
    return [
      markRule(/(?:^|[^*\p{L}\p{N}\\])(\*\*([^*\s](?:[^*]*[^*\s])?)\*\*)$/u, M.strong, 2),
      markRule(/(?:^|[^*\p{L}\p{N}\\])(\*([^*\s](?:[^*]*[^*\s])?)\*)$/u, M.em, 1),
      new InputRule(CLITIC, (state, m, start, end) => {
        const q = start + m[1].length, at = start + m[0].length - m[4].length;
        if (state.doc.textBetween(q, q + 1) !== m[2]) return null;
        return state.tr.insertText(m[4], at, end).insertText("’", q, q + 1);
      }),
      new InputRule(/["']$/, (state, m, start, end) => state.tr.insertText(quoteFor(m.input.slice(0, m.index), m[0], quotes()), start, end)),
      new InputRule(/\.\.\.$/, "…"),
      new InputRule(/–-$/, "—"),
      new InputRule(/--$/, "–"),
    ];
  }
  function blockRules(quotes) {
    return [
      ...inlineRules(quotes),
      new InputRule(/^(#{2,3})\s$/, (state, m, start, end) => {       // a paragraph becomes a heading; the title stays the title
        const $s = state.doc.resolve(start);
        if ($s.parent.type !== N.paragraph || !$s.node(-1).canReplaceWith($s.index(-1), $s.indexAfter(-1), N.heading)) return null;
        return state.tr.delete(start, end).setBlockType(start, start, N.heading, {level: m[1].length});
      }),
      new InputRule(/^#\s$/, (state, m, start, end) => {      // the piece's title when the first line has none yet, else ##
        const $s = state.doc.resolve(start);
        if ($s.depth !== 1 || $s.parent.type !== N.paragraph) return null;
        const first = $s.index(0) === 0 && state.doc.firstChild.type !== N.title;
        return state.tr.delete(start, end).setBlockType(start, start, first ? N.title : N.heading, first ? null : {level: 2});
      }),
      wrappingInputRule(/^>\s$/, N.blockquote),
      textblockTypeInputRule(/^—\s$/, N.attribution),        // — at the start of an epigraph's last paragraph: who said it
    ];
  }

  /* ——— keys ——— */
  const isLinked = n => !!n && n.type === N.poem && !!n.attrs.src;
  const inPoem = $p => { for (let d = $p.depth; d > 0; d--) if ($p.node(d).type === N.poem) return true; return $p.doc.attrs.form === "poem" && $p.depth === 1 && $p.parent.type === N.paragraph; };
  const SCENE = /^\s*\*\s*\*\s*\*\s*$/;

  /* Enter, for the dialect's blocks: *** becomes a scene break; a title or heading is followed by a paragraph; an empty
     last paragraph leaves an epigraph, poem or quotation; in a poem Enter is a new line and a second Enter a new stanza. */
  function enter(state, dispatch, view, T) {
    const sel = state.selection;
    if (sel instanceof NodeSelection) {
      if (sel.node.type === N.note) { T.noteAt(sel.from)?.open(); return true; }
      if (!sel.node.isBlock) return false;
      const tr = state.tr.insert(sel.to, N.paragraph.create());
      dispatch(tr.setSelection(TextSelection.create(tr.doc, sel.to + 1)).scrollIntoView());
      return true;
    }
    const {$cursor} = sel;
    if (!$cursor) return false;
    const block = $cursor.parent, d = $cursor.depth, atEnd = $cursor.parentOffset === block.content.size;
    if (d === 1 && block.type === N.paragraph && SCENE.test(block.textContent) && block.childCount === 1) {
      const pos = $cursor.before(1), tr = state.tr.replaceWith(pos, pos + block.nodeSize, [N.scene_break.create(), N.paragraph.create()]);
      dispatch(tr.setSelection(TextSelection.create(tr.doc, pos + 2)).scrollIntoView());
      return true;
    }
    if (block.type === N.title || block.type === N.heading) {
      if (atEnd) {
        const after = $cursor.after(d), next = state.doc.resolve(after).nodeAfter;
        if (next && next.type === N.paragraph && !next.content.size) {     // an empty line follows already: into it
          dispatch(state.tr.setSelection(TextSelection.create(state.doc, after + 1)).scrollIntoView());
          return true;
        }
        const tr = state.tr.insert(after, N.paragraph.create());
        dispatch(tr.setSelection(TextSelection.create(tr.doc, after + 1)).scrollIntoView());
      } else if ($cursor.parentOffset === 0) {          // a paragraph before a heading; the title stays first
        if (block.type === N.title) return true;
        const before = $cursor.before(d), tr = state.tr.insert(before, N.paragraph.create());
        dispatch(tr.setSelection(TextSelection.create(tr.doc, before + 3)).scrollIntoView());
      } else dispatch(state.tr.split($cursor.pos, 1, [{type: N.paragraph}]).scrollIntoView());
      return true;
    }
    const box = d >= 2 ? $cursor.node(d - 1) : null;
    if (box && block.type === N.attribution) {               // after the attribution: out of the epigraph
      if (!atEnd) return hardBreak(state, dispatch);
      const after = $cursor.after(d - 1), tr = state.tr.insert(after, N.paragraph.create());
      dispatch(tr.setSelection(TextSelection.create(tr.doc, after + 1)).scrollIntoView());
      return true;
    }
    if (box && [N.epigraph, N.poem, N.blockquote].includes(box.type) && !block.content.size && $cursor.index(d - 1) === box.childCount - 1) {
      const boxPos = $cursor.before(d - 1);
      if (box.childCount === 1) {                            // the only paragraph: the block becomes a paragraph again
        const tr = state.tr.replaceWith(boxPos, boxPos + box.nodeSize, N.paragraph.create());
        dispatch(tr.setSelection(TextSelection.create(tr.doc, boxPos + 1)).scrollIntoView());
      } else {
        const tr = state.tr.delete($cursor.before(d), $cursor.after(d)), after = tr.mapping.map(boxPos + box.nodeSize);
        tr.insert(after, N.paragraph.create());
        dispatch(tr.setSelection(TextSelection.create(tr.doc, after + 1)).scrollIntoView());
      }
      return true;
    }
    if (inPoem($cursor) && block.type === N.paragraph) {
      const before = $cursor.nodeBefore;
      if (atEnd && before && before.type === N.hard_break) {   // a second Enter: a new stanza
        const tr = state.tr.delete($cursor.pos - 1, $cursor.pos);
        dispatch(tr.split($cursor.pos - 1).scrollIntoView());
        return true;
      }
      if (block.content.size) return hardBreak(state, dispatch);
    }
    return false;
  }
  function hardBreak(state, dispatch) {
    const {$from, $to} = state.selection;
    if (!$from.sameParent($to) || !$from.parent.inlineContent || !$from.parent.canReplaceWith($from.index(), $to.index(), N.hard_break)) return false;
    dispatch(state.tr.replaceSelectionWith(N.hard_break.create()).scrollIntoView());
    return true;
  }
  /* Backspace or Delete next to a linked poem selects it instead of pulling text into it. */
  function linkedNeighbour(dir) {
    return (state, dispatch) => {
      const {$cursor} = state.selection;
      if (!$cursor || $cursor.depth < 1) return false;
      const d = $cursor.depth, i = $cursor.index(d - 1), parent = $cursor.node(d - 1);
      if (dir < 0 && ($cursor.parentOffset > 0 || i === 0)) return false;
      if (dir > 0 && ($cursor.parentOffset < $cursor.parent.content.size || i >= parent.childCount - 1)) return false;
      const other = parent.child(dir < 0 ? i - 1 : i + 1);
      if (!isLinked(other)) return false;
      const pos = dir < 0 ? $cursor.before(d) - other.nodeSize : $cursor.after(d);
      dispatch?.(state.tr.setSelection(NodeSelection.create(state.doc, pos)));
      return true;
    };
  }

  /* ——— small DOM helpers ——— */
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const WIDTH = /^\d+(\.\d+)?(%|px)?$/;

  /* ——— notes: a number in the text, its text in the margin (the ProseMirror footnote pattern) ——— */
  class NoteView {
    constructor(node, view, getPos, T) {
      Object.assign(this, {node, outer: view, getPos, T, peeking: false});
      this.dom = el("span", "bk-note-a");
      this.probe = el("i", "bk-bl");             // a zero-size mark on the line's baseline
      this.num = el("sup", "bk-note");
      this.dom.append(this.probe, this.num);
      this.item = el("div", "bm-item bm-note");
      const lab = el("span", "bm-n");
      this.iprobe = el("i", "bk-bl"); this.label = document.createTextNode("");
      lab.append(this.iprobe, this.label);
      const body = el("div", "bm-body");
      this.item.append(lab, body);
      this.inner = new EditorView(body, {
        state: EditorState.create({doc: node, plugins: T.notePlugins(this)}),
        dispatchTransaction: tr => this.dispatchInner(tr),
        nodeViews: {cite: (n, v, g) => new CiteView(n, v, g, T)},
        attributes: {class: "bm-ed", spellcheck: "true", lang: T.lang, "aria-label": "Note"},
        editable: () => !T.locked,
        handleDOMEvents: {
          focus: () => { this.T.noteFocus(this, true); return false; },
          blur: () => { this.T.noteFocus(this, false); return false; },
          mousedown: () => { T.mouseDown = true; T.selbar.hide(); return false; },
        },
        handlePaste: (v, e) => { T.pasteWarning(e); return false; },
        transformPastedHTML: html => cleanPaste(html),
      });
      this.dom.addEventListener("mousedown", e => { if (e.button === 0) { e.preventDefault(); this.open(); } });
      this.empty();
      T.margin.addNote(this);
    }
    empty() { this.item.classList.toggle("empty", !this.node.content.size); this.dom.title = this.node.textContent; }
    setNumber(n) { if (this.num.textContent !== String(n)) { this.num.textContent = n; this.label.data = n; } }
    open(atEnd = true) {
      this.peeking = true; this.item.hidden = false;
      this.T.margin.layout();
      this.inner.focus();
      if (atEnd) this.inner.dispatch(this.inner.state.tr.setSelection(Selection.atEnd(this.inner.state.doc)));
    }
    /* back to the text, after the note's number */
    leave() {
      const pos = this.getPos();
      if (pos == null) return;
      const v = this.outer;
      v.dispatch(v.state.tr.setSelection(TextSelection.create(v.state.doc, pos + this.node.nodeSize)));
      v.focus();
    }
    remove() {
      const pos = this.getPos(), v = this.outer;
      if (pos == null) return;
      const tr = v.state.tr.delete(pos, pos + this.node.nodeSize);
      v.dispatch(tr.setSelection(TextSelection.create(tr.doc, pos)));
      v.focus();
    }
    dispatchInner(tr) {
      const {state, transactions} = this.inner.state.applyTransaction(tr);
      this.inner.updateState(state);
      if (!tr.getMeta("fromOutside")) {
        const pos = this.getPos();
        if (pos != null) {
          const outerTr = this.outer.state.tr, offset = StepMap.offset(pos + 1);
          for (const t of transactions) for (const step of t.steps) outerTr.step(step.map(offset));
          if (outerTr.docChanged) this.outer.dispatch(outerTr);
        }
      }
      this.T.mapPop(this.inner, transactions);
      this.T.margin.schedule();
      this.T.selbar.update();
    }
    update(node) {
      if (!node.sameMarkup(this.node)) return false;
      this.node = node;
      const state = this.inner.state, start = node.content.findDiffStart(state.doc.content);
      if (start != null) {
        let {a: endA, b: endB} = node.content.findDiffEnd(state.doc.content);
        const overlap = start - Math.min(endA, endB);
        if (overlap > 0) { endA += overlap; endB += overlap; }
        this.inner.dispatch(state.tr.replace(start, endB, node.slice(start, endA)).setMeta("fromOutside", true));
      }
      this.empty();
      return true;
    }
    selectNode() { this.dom.classList.add("sel"); this.item.classList.add("on"); }
    deselectNode() { this.dom.classList.remove("sel"); if (!this.inner.hasFocus()) this.item.classList.remove("on"); }
    stopEvent(e) { return e.type === "mousedown"; }
    ignoreMutation() { return true; }
    destroy() { if (this.T.popPos?.view === this.inner) this.T.closePop(); this.inner.destroy(); this.T.margin.removeNote(this); }
  }

  /* ——— a citation: its label; a click opens its form ——— */
  class CiteView {
    constructor(node, view, getPos, T) {
      Object.assign(this, {node, getPos, T});
      this.dom = el("span", "bk-cite");
      this.dom.addEventListener("mousedown", e => { if (e.button === 0) { e.preventDefault(); if (!T.locked) T.citeForm({pos: getPos(), node: this.node}, null, view); } });
      this.render();
      T.cites.add(this);
    }
    render() {
      const items = this.node.attrs.items || [], known = new Set((this.T.ctx.sources() || []).map(s => s.id));
      this.dom.textContent = citeLabel(items, this.T.ctx.sources()) || "Citation";
      const missing = items.filter(i => !known.has(i.key)).map(i => i.key);
      this.dom.classList.toggle("unknown", missing.length > 0);
      this.dom.title = missing.length ? `Not in the sources: ${missing.join(", ")}` : "Citation · click to change";
    }
    update(node) { if (node.type !== N.cite) return false; this.node = node; this.render(); return true; }
    selectNode() { this.dom.classList.add("sel"); }
    deselectNode() { this.dom.classList.remove("sel"); }
    stopEvent(e) { return e.type === "mousedown"; }
    ignoreMutation() { return true; }
    destroy() { this.T.cites.delete(this); }
  }

  /* ——— an image of the book, with its caption ——— */
  class ImageView {
    constructor(node, view, getPos, T) {
      Object.assign(this, {node, view, getPos, T});
      this.dom = el("figure", "bk-fig");
      const url = T.ctx.imageUrl(node.attrs.src);
      if (url) {
        this.img = el("img");
        this.img.src = url; this.img.alt = node.attrs.alt || "";
        if (WIDTH.test(node.attrs.width || "")) this.img.style.width = node.attrs.width;
        this.img.onload = this.img.onerror = () => T.margin.schedule();
        this.dom.append(this.img);
      } else this.dom.append(el("div", "bk-fig-none", `Image not in this book: ${node.attrs.src}`));
      this.cap = el("input", "bk-cap");
      Object.assign(this.cap, {value: node.attrs.alt || "", placeholder: "Caption", spellcheck: true, readOnly: !!T.locked});
      this.cap.setAttribute("lang", T.lang); this.cap.setAttribute("aria-label", "Caption");
      this.cap.addEventListener("input", () => {
        const pos = this.getPos();
        if (pos != null) this.view.dispatch(this.view.state.tr.setNodeMarkup(pos, null, {...this.node.attrs, alt: this.cap.value}));
      });
      this.cap.addEventListener("keydown", e => {
        if ((e.key !== "Enter" && e.key !== "Escape") || T.locked) return;
        e.preventDefault();
        const pos = this.getPos();
        if (pos == null) return;
        const v = this.view, after = pos + this.node.nodeSize, next = v.state.doc.resolve(after).nodeAfter;
        const tr = v.state.tr;
        if (!next || !next.isTextblock) tr.insert(after, N.paragraph.create());
        v.dispatch(tr.setSelection(TextSelection.create(tr.doc, after + 1)).scrollIntoView());
        v.focus();
      });
      this.dom.append(this.cap);
    }
    update(node) {
      if (node.type !== N.image || node.attrs.src !== this.node.attrs.src || node.attrs.width !== this.node.attrs.width) return false;
      this.node = node;
      if (document.activeElement !== this.cap) this.cap.value = node.attrs.alt || "";
      return true;
    }
    selectNode() { this.dom.classList.add("sel"); }
    deselectNode() { this.dom.classList.remove("sel"); }
    stopEvent(e) { return e.target === this.cap; }
    ignoreMutation() { return true; }
  }

  /* ——— a poem from the Poems library: its text shows, quietly; it is edited there ——— */
  class LinkedView {
    constructor(node, view, getPos, T) {
      Object.assign(this, {node, view, getPos, T});
      this.dom = el("div", "bk-linked");
      this.dom.contentEditable = "false";
      this.dom.addEventListener("mousedown", e => {
        if (e.button !== 0) return;
        e.preventDefault();
        const pos = this.getPos();
        if (pos != null) { view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc, pos))); view.focus(); }
      });
      this.render();
      T.linkedViews.add(this);
    }
    render() {
      const src = this.node.attrs.src, p = this.T.ctx.linked()[src];
      this.dom.replaceChildren();
      const head = el("div", "bk-linked-h");
      head.append(el("span", "label", "Linked poem"), el("span", "bk-linked-src", src));
      if (p && !p.missing) {
        const a = el("a", "btn small quiet", "Edit in Poems");
        a.href = poemHash(src, "write");
        head.append(a);
      }
      this.dom.append(head);
      if (!p) { this.dom.append(el("p", "bk-linked-none", "Reading the poem…")); return; }
      if (p.missing) { this.dom.append(el("p", "bk-linked-none", "This poem is no longer in your Poems library.")); return; }
      this.dom.append(el("p", "bk-linked-t", p.title || ""));
      const body = el("div", "bk-linked-lines");
      let stanza = el("p");
      for (const line of p.lines || []) {
        if (!String(line).trim()) { if (stanza.childNodes.length) body.append(stanza); stanza = el("p"); continue; }
        if (stanza.childNodes.length) stanza.append(el("br"));
        stanza.append(document.createTextNode(line));
      }
      if (stanza.childNodes.length) body.append(stanza);
      this.dom.append(body);
    }
    update(node) { if (!isLinked(node) || node.attrs.src !== this.node.attrs.src) return false; this.node = node; return true; }
    selectNode() { this.dom.classList.add("sel"); }
    deselectNode() { this.dom.classList.remove("sel"); }
    stopEvent(e) { return e.type === "mousedown"; }
    ignoreMutation() { return true; }
    destroy() { this.T.linkedViews.delete(this); }
  }

  /* ——— the margin: notes and comments beside the line they belong to, never overlapping ——— */
  const GAP = 10;            // between stacked margin items: two one-line items on neighbouring lines (31 px apart) both keep their line
  class Margin {
    constructor(T, host) {
      Object.assign(this, {T, host, notes: new Set(), comments: [], frame: 0, descent: null, comOffset: null});
      this.ruler = el("div", "bm-item bm-com bm-ruler");
      this.ruler.setAttribute("aria-hidden", "true");
      this.rulerProbe = el("i", "bk-bl");
      const t = el("div", "bm-ta"); t.append("x", this.rulerProbe);
      this.ruler.append(t);
      host.append(this.ruler);
    }
    addNote(nv) { this.notes.add(nv); this.host.append(nv.item); this.schedule(); }
    removeNote(nv) { this.notes.delete(nv); nv.item.remove(); this.schedule(); }
    schedule() { if (!this.frame && !this.T.destroyed) this.frame = requestAnimationFrame(() => { this.frame = 0; this.layout(); }); }
    remeasure() { this.descent = this.comOffset = null; this.comments.forEach(c => this.fit(c.ta)); this.schedule(); }    // a narrower margin (split view) wraps comments anew
    noteViews() {
      return [...this.notes].map(nv => ({nv, pos: nv.getPos()})).filter(x => x.pos != null).sort((a, b) => a.pos - b.pos);
    }
    /* comments: one item per range, kept in order so the one being typed in keeps its textarea */
    sync(doc) {
      if (this.T.destroyed) return;
      const ranges = commentRanges(doc);
      while (this.comments.length > ranges.length) this.comments.pop().el.remove();
      ranges.forEach((r, i) => {
        const c = this.comments[i] || this.makeComment(i);
        c.range = r;
        if (document.activeElement !== c.ta && c.ta.value !== r.mark.attrs.note) { c.ta.value = r.mark.attrs.note; this.fit(c.ta); }
      });
      this.schedule();
    }
    makeComment(i) {
      const c = {el: el("div", "bm-item bm-com"), ta: el("textarea", "bm-ta"), range: null};
      Object.assign(c.ta, {rows: 1, placeholder: "Comment", spellcheck: true, readOnly: !!this.T.locked});
      c.ta.setAttribute("lang", this.T.lang); c.ta.setAttribute("aria-label", "Comment");
      const acts = el("div", "bm-acts"), resolve = el("button", "bm-btn", "Resolve");
      resolve.type = "button";
      resolve.addEventListener("click", () => this.T.resolveComment(this.comments.indexOf(c)));
      acts.append(resolve);
      c.el.append(c.ta, acts);
      c.ta.addEventListener("input", () => {
        if (/[\r\n]/.test(c.ta.value)) { const at = c.ta.selectionStart; c.ta.value = oneLine(c.ta.value); c.ta.setSelectionRange(at, at); }
        this.fit(c.ta); this.T.setComment(this.comments.indexOf(c), c.ta.value); this.schedule();
      });
      c.ta.addEventListener("focus", () => this.T.commentFocus(c.range));
      c.ta.addEventListener("blur", () => this.T.commentFocus(null));
      // Enter is done (the comment is kept as it is typed), as Escape: back to the text
      c.ta.addEventListener("keydown", e => { if ((e.key === "Escape" || e.key === "Enter") && !e.isComposing) { e.preventDefault(); this.T.view.focus(); } });
      this.comments[i] = c;
      this.host.append(c.el);
      return c;
    }
    fit(ta) { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; }
    commentAt(pos) { return this.comments.find(c => c.range && c.range.from <= pos && pos <= c.range.to); }
    /* the text's baseline at a position: the bottom of its character box less the font's descent */
    baselineAt(pos) {
      const view = this.T.view, c = view.coordsAtPos(pos, 1);
      if (this.descent == null) {
        const p = el("p", "bk-ruler"), span = el("span", null, "Hg"), probe = el("i", "bk-bl");
        p.append(span, probe);
        view.dom.append(p);
        this.descent = span.getBoundingClientRect().bottom - probe.getBoundingClientRect().top;
        p.remove();
      }
      return c.bottom - this.descent;
    }
    layout() {
      const T = this.T;
      if (T.destroyed || !T.view || !this.host.isConnected) return;
      const view = T.view;
      const f = T.ctx.features(), showNotes = !!f.notes && f.notes !== "off";
      const hostTop = this.host.getBoundingClientRect().top, items = [];
      let n = T.ctx.noteStart();
      for (const {nv, pos} of this.noteViews()) {
        nv.setNumber(++n);
        const show = showNotes || nv.peeking;
        nv.item.hidden = !show;
        nv.dom.classList.toggle("quiet", !showNotes);
        if (show) items.push({pos, el: nv.item, y: nv.probe.getBoundingClientRect().top - hostTop, probe: nv.iprobe});
      }
      const active = T.view.state.selection.empty ? T.view.state.selection.head : -1;
      for (const c of this.comments) {
        if (!c.range) continue;
        c.el.classList.toggle("on", document.activeElement === c.ta || (c.range.from <= active && active <= c.range.to));
        items.push({pos: c.range.from, el: c.el, y: this.baselineAt(c.range.from) - hostTop, probe: null});
      }
      items.sort((a, b) => a.pos - b.pos);
      if (this.comOffset == null) {
        this.comOffset = this.rulerProbe.getBoundingClientRect().top - this.ruler.getBoundingClientRect().top;
        this.host.style.setProperty("--com-bl", this.comOffset + "px");
      }
      for (const it of items) {          // read everything first, then place
        it.off = it.probe ? it.probe.getBoundingClientRect().top - it.el.getBoundingClientRect().top : this.comOffset;
        it.h = it.el.offsetHeight;
      }
      let bottom = -Infinity;
      for (const it of items) {
        const top = Math.max(Math.round(it.y - it.off), bottom + GAP);
        it.el.style.top = top + "px";
        bottom = top + it.h;
      }
      this.host.style.minHeight = items.length ? Math.ceil(bottom) + "px" : "";
    }
  }

  /* ——— the / menu ——— */
  const slashKey = new PluginKey("bk-slash"), CLOSED = {open: false};
  function slashPlugin(T) {
    return new Plugin({
      key: slashKey,
      state: {
        init: () => CLOSED,
        apply(tr, prev, old, state) {
          const meta = tr.getMeta(slashKey);
          if (meta) return meta.open ? {open: true, from: meta.from, query: ""} : CLOSED;
          if (!prev.open) return prev;
          const from = tr.mapping.map(prev.from), sel = state.selection;
          if (!sel.empty || from >= state.doc.content.size || state.doc.textBetween(from, from + 1) !== "/") return CLOSED;
          const $f = state.doc.resolve(from);
          if (sel.head <= from || sel.head > $f.end()) return CLOSED;
          const query = state.doc.textBetween(from + 1, sel.head, "\n", "￼");
          return query.length > 24 || /[\n￼]/.test(query) ? CLOSED : {open: true, from, query};
        },
      },
      props: {
        handleTextInput(view, from, to, text) {
          if (text !== "/" || from !== to) return false;
          const $f = view.state.doc.resolve(from), before = $f.nodeBefore;
          if (!$f.parent.inlineContent) return false;
          if (before && !(before.type === N.hard_break || before.isText && /\s$/.test(before.text))) return false;
          view.dispatch(view.state.tr.insertText("/", from, to).setMeta(slashKey, {open: true, from}));
          return true;
        },
        handleKeyDown: (view, e) => T.slash.key(view, e),
      },
      view: () => ({update: view => T.slash.update(view), destroy: () => T.slash.hide()}),
    });
  }
  class SlashMenu {
    constructor(T) {
      Object.assign(this, {T, items: [], active: 0, key0: ""});
      this.el = el("div", "bk-slash");
      this.el.setAttribute("role", "listbox"); this.el.setAttribute("aria-label", "Insert");
      this.el.hidden = true;
      this.el.addEventListener("mousedown", e => e.preventDefault());
      this.el.addEventListener("click", e => { const b = e.target.closest("[data-i]"); if (b) this.run(+b.dataset.i); });
      T.over.append(this.el);
    }
    hide() { this.el.hidden = true; }
    update(view) {
      const st = slashKey.getState(view.state);
      if (!st || !st.open || !view.hasFocus()) { this.hide(); return; }
      const items = slashItems(st.query, this.T.ctx.features()), key = items.map(i => i.id).join();
      if (key !== this.key0) { this.active = 0; this.key0 = key; }
      this.items = items;
      if (!items.length) { this.hide(); return; }
      this.el.replaceChildren(...items.map((it, i) => {
        const b = el("button", "bk-slash-i" + (i === this.active ? " on" : ""), it.label);
        Object.assign(b, {type: "button", tabIndex: -1}); b.dataset.i = i;
        b.setAttribute("role", "option"); b.setAttribute("aria-selected", i === this.active);
        return b;
      }));
      this.el.hidden = false;
      const c = view.coordsAtPos(st.from), page = this.T.page.getBoundingClientRect();
      this.el.style.left = Math.round(c.left - page.left) + "px";
      this.el.style.top = Math.round(c.bottom - page.top + 6) + "px";
    }
    key(view, e) {
      const st = slashKey.getState(view.state);
      if (!st || !st.open) return false;
      if (e.key === "Escape") { view.dispatch(view.state.tr.setMeta(slashKey, {open: false})); return true; }
      if (this.el.hidden) return false;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        this.active = (this.active + (e.key === "ArrowDown" ? 1 : -1) + this.items.length) % this.items.length;
        this.update(view);
        return true;
      }
      if (e.key === "Enter" || e.key === "Tab") { this.run(this.active); return true; }
      return false;
    }
    run(i) {
      const it = this.items[i], view = this.T.view, st = slashKey.getState(view.state);
      if (!it || !st || !st.open) return;
      // a note sits against the word before it: the space typed before the / goes with it
      const from = it.id === "note" && st.from > 0 && view.state.doc.textBetween(st.from - 1, st.from) === " " ? st.from - 1 : st.from;
      view.dispatch(view.state.tr.delete(from, view.state.selection.head).setMeta(slashKey, {open: false}));
      this.hide();
      this.T.insert(it.id);
    }
  }

  /* ——— the selection bar ——— */
  /* the bar's keys (Comment as in Google Docs, Index as in Word); shown in the buttons' titles */
  const KEYS = {bold: "Mod-b", italic: "Mod-i", note: "Mod-Alt-f", comment: "Mod-Alt-m", index: "Shift-Alt-x"};
  const MAC = typeof navigator !== "undefined" && /Mac|iP(hone|[oa]d)/.test(navigator.platform);
  const keyName = k => k.split("-").map(p => p === "Mod" ? (MAC ? "⌘" : "Ctrl") : p === "Alt" ? (MAC ? "⌥" : "Alt") : p.length === 1 ? p.toUpperCase() : p).join(MAC ? "" : "+");
  const NOTE_BAR = new Set(["bold", "italic", "source"]);     // what the bar offers inside a note's text
  class SelBar {
    constructor(T) {
      this.T = T;
      this.el = el("div", "bk-selbar");
      this.el.setAttribute("role", "toolbar"); this.el.setAttribute("aria-label", "Selection");
      this.el.hidden = true;
      this.el.addEventListener("mousedown", e => e.preventDefault());
      this.el.addEventListener("click", e => { const b = e.target.closest("[data-cmd]"); if (b) T.command(b.dataset.cmd); });
      T.over.append(this.el);
      this.key0 = "";
    }
    hide() { this.el.hidden = true; }
    update() {
      const T = this.T;
      if (T.destroyed) return;
      const view = T.activeView(), sel = view.state.selection, inNote = view !== T.view;
      if (!view.hasFocus() || T.mouseDown || T.pop || sel.empty || !(sel instanceof TextSelection) || !sel.$from.parent.inlineContent) { this.hide(); return; }
      const buttons = barButtons(T.ctx.features()).filter(([c]) => !inNote || NOTE_BAR.has(c)), key = buttons.map(b => b[0]).join();
      if (key !== this.key0) {
        this.key0 = key;
        this.el.replaceChildren(...buttons.map(([cmd, label]) => {
          const b = el("button", "bk-sb", label);
          b.type = "button"; b.dataset.cmd = cmd; b.tabIndex = -1;
          if (KEYS[cmd]) b.title = `${label} · ${keyName(KEYS[cmd])}`;
          return b;
        }));
      }
      const {from, to} = sel, has = m => view.state.doc.rangeHasMark(from, to, m);
      const pressed = {bold: has(M.strong), italic: has(M.em), index: has(M.idx), comment: has(M.comment)};
      for (const b of this.el.children) if (b.dataset.cmd in pressed) b.setAttribute("aria-pressed", pressed[b.dataset.cmd]);
      this.el.hidden = false;
      const a = view.coordsAtPos(from, 1), z = view.coordsAtPos(to, -1), page = T.page.getBoundingClientRect();
      const col = (inNote ? view.dom : T.textHost).getBoundingClientRect(), w = this.el.offsetWidth, h = this.el.offsetHeight;
      const mid = Math.abs(a.top - z.top) < 4 ? (a.left + z.right) / 2 : a.left + 40;
      const left = Math.max(Math.min(col.left, page.right - w), Math.min(mid - w / 2, col.right - w));
      this.el.style.left = Math.round(left - page.left) + "px";
      this.el.style.top = Math.round(a.top - page.top - h - 10) + "px";
    }
  }

  /* ——— the text of one piece ——— */
  class Text {
    /* hosts: {page, text, margin, over}; opts: {doc, ctx}. ctx: features(), sheet(), sources(), linked() (src → poem),
       noteStart(), imageUrl(src), onChange(transactions), pickImage(), pickPoem(), say(msg), language */
    constructor(hosts, {doc, ctx}) {
      Object.assign(this, {ctx, page: hosts.page, textHost: hosts.text, over: hosts.over, lang: ctx.language || "en",
        cites: new Set(), linkedViews: new Set(), mouseDown: false, pop: null, popPos: null, destroyed: false});
      this.margin = new Margin(this, hosts.margin);
      /* a poem may be edited in Poems, in another window: when this one is back (focus and visibility fire together,
         so one debounced run) every distinct linked poem is read once */
      this.back = () => { clearTimeout(this.backTimer); this.backTimer = setTimeout(() => { if (!document.hidden) this.rereadLinked(); }, 300); };
      addEventListener("focus", this.back); document.addEventListener("visibilitychange", this.back);
      this.selbar = new SelBar(this);
      this.slash = new SlashMenu(this);
      this.commentKey = new PluginKey("bk-comment-on");
      this.view = new EditorView(hosts.text, {
        state: this.makeState(doc),
        dispatchTransaction: tr => this.dispatch(tr),
        nodeViews: {
          note: (n, v, g) => new NoteView(n, v, g, this),
          cite: (n, v, g) => new CiteView(n, v, g, this),
          image: (n, v, g) => new ImageView(n, v, g, this),
          poem: (n, v, g) => isLinked(n) ? new LinkedView(n, v, g, this) : undefined,
        },
        attributes: {class: "bk-text", spellcheck: "true", lang: this.lang, "aria-label": "Text", "aria-multiline": "true"},
        handleDOMEvents: {
          mousedown: () => { this.mouseDown = true; this.selbar.hide(); return false; },
          focus: () => { this.selbar.update(); return false; },
          blur: () => { setTimeout(() => { if (this.destroyed) return; this.selbar.update(); if (!this.view.hasFocus()) this.slash.hide(); }); return false; },
        },
        handlePaste: (view, e) => { this.pasteWarning(e); return false; },
        transformPastedHTML: html => cleanPaste(html),
        // in a poem line, what is pasted keeps the indentation of its lines (and plain text its lines and stanzas)
        clipboardTextParser: (text, $at) => poemLine($at) ? poemText(text, $at.marks(), atLineStart($at)) : null,
        transformPasted: (slice, view) => { const $f = view.state.selection.$from; return poemLine($f) ? poemPasted(slice, atLineStart($f)) : slice; },
      });
      this.onUp = () => { if (this.mouseDown && !this.destroyed) { this.mouseDown = false; this.selbar.update(); } };
      addEventListener("mouseup", this.onUp);
      this.onResize = () => { if (!this.destroyed) { this.margin.remeasure(); this.selbar.update(); } };
      this.ro = typeof ResizeObserver === "function" ? new ResizeObserver(this.onResize) : null;
      this.ro?.observe(hosts.text);
      document.fonts?.ready.then(() => this.margin.remeasure());
      this.margin.sync(this.view.state.doc);
      this.applyFeatures();
    }
    /* marks of a feature that is off stay in the text, quietly */
    applyFeatures() {
      const f = this.ctx.features();
      this.textHost.classList.toggle("noidx", f.index !== true);
      this.textHost.classList.toggle("nocite", f.sources !== true);
    }
    makeState(json) {
      const doc = root.PM.Node.fromJSON(S, editableDoc(json));
      doc.check();
      return EditorState.create({doc, plugins: this.plugins()});
    }
    plugins() {
      const T = this, quotes = () => T.ctx.sheet().quotes;
      return [
        slashPlugin(T),
        new Plugin({props: {handleTextInput(view, from, to, text) {
          const sel = view.state.selection;
          if (sel instanceof NodeSelection && sel.node.isInline) {      // typing on a selected note or citation goes after it
            const tr = view.state.tr.insertText(text, sel.to);
            view.dispatch(tr.setSelection(TextSelection.create(tr.doc, sel.to + text.length)).scrollIntoView());
            return true;
          }
          const spaces = poemTyped(view.state, from, text);         // the indentation of a poem line
          if (spaces == null) return false;
          view.dispatch(view.state.tr.insertText(spaces, from, to).scrollIntoView());
          return true;
        }}}),
        inputRules({rules: blockRules(quotes)}),
        keymap({
          "Enter": (s, d, v) => enter(s, d, v, T),
          "Shift-Enter": hardBreak,
          "Tab": poemTab,
          "Mod-b": toggleMark(M.strong), "Mod-i": toggleMark(M.em),
          [KEYS.note]: () => { if (!barButtons(T.ctx.features()).some(b => b[0] === "note")) return false; T.command("note"); return true; },
          [KEYS.comment]: s => { if (s.selection.empty || !(s.selection instanceof TextSelection)) return false; T.command("comment"); return true; },
          [KEYS.index]: s => { if (s.selection.empty || T.ctx.features().index !== true) return false; T.command("index"); return true; },
          "Mod-z": undo, "Mod-y": redo, "Shift-Mod-z": redo,
          "Backspace": chainCommands(undoInputRule, linkedNeighbour(-1)),
          "Delete": linkedNeighbour(1),
        }),
        keymap(baseKeymap),
        history(),
        dropCursor({class: "bk-drop", width: 2}),
        gapCursor(),
        new Plugin({filterTransaction: tr => !tr.docChanged || !tr.doc.content.content.some(n => isLinked(n) && n.childCount)}),
        new Plugin({appendTransaction: (trs, old, state) => {      // never an empty document: there is always a line to type on
          if (state.doc.childCount) return null;
          const tr = state.tr.insert(0, N.paragraph.create());
          return tr.setSelection(TextSelection.create(tr.doc, 1));
        }}),
        new Plugin({props: {decorations: placeholders}}),
        new Plugin({
          key: this.commentKey,
          state: {init: () => null, apply: (tr, prev) => { const m = tr.getMeta(this.commentKey); return m !== undefined ? m : prev && {from: tr.mapping.map(prev.from), to: tr.mapping.map(prev.to)}; }},
          props: {decorations(state) {
            const r = this.getState(state);
            return r && r.to > r.from ? DecorationSet.create(state.doc, [Decoration.inline(r.from, r.to, {class: "bk-com-on"})]) : null;
          }},
        }),
        ...(root.BookTools ? root.BookTools.plugins(T) : []),      // echoes, the style sheet, find, focus (book-tools.js)
      ];
    }
    notePlugins(nv) {
      const T = this, outer = () => T.view;
      return [
        inputRules({rules: inlineRules(() => T.ctx.sheet().quotes)}),
        keymap({
          "Mod-z": () => undo(outer().state, outer().dispatch), "Mod-y": () => redo(outer().state, outer().dispatch),
          "Shift-Mod-z": () => redo(outer().state, outer().dispatch),
          "Mod-b": toggleMark(M.strong), "Mod-i": toggleMark(M.em),
          "Escape": () => { nv.leave(); return true; },
          "Enter": () => { nv.leave(); return true; },
          "Shift-Enter": (state, dispatch) => { dispatch(state.tr.replaceSelectionWith(N.hard_break.create()).scrollIntoView()); return true; },
          "Backspace": chainCommands(undoInputRule, state => { if (state.doc.content.size) return false; nv.remove(); return true; }),
        }),
        keymap(baseKeymap),
      ];
    }
    dispatch(tr) {
      const {state, transactions} = this.view.state.applyTransaction(tr);
      this.view.updateState(state);
      if (transactions.some(t => t.docChanged)) { this.margin.sync(state.doc); this.ctx.onChange(transactions); }
      this.mapPop(this.view, transactions);
      this.margin.schedule();
      this.selbar.update();
    }
    /* the view the author is writing in: a note's, or the text's */
    activeView() { const nv = [...this.margin.notes].find(n => n.inner.hasFocus()); return nv ? nv.inner : this.view; }
    /* an open form follows its text through changes; it closes when its text is gone */
    mapPop(view, transactions) {
      const at = this.popPos;
      if (!this.pop || !at || at.view !== view) return;
      for (const t of transactions) {
        if (!t.docChanged) continue;
        for (const k of ["pos", "from", "to"]) {
          if (at[k] == null) continue;
          const r = t.mapping.mapResult(at[k], k === "to" ? -1 : 1);
          if (r.deleted && k === "pos" && at.existing) { this.closePop(); return; }
          at[k] = r.pos;
        }
      }
      if (at.from != null && at.to <= at.from) this.closePop();
    }
    /* another version of the piece (the disk's, after Reload or a quiet reload): only the part that differs is replaced,
       so the cursor and the scroll stay; undo brings back what was here */
    replaceDoc(json, meta, {history = true} = {}) {
      const form = this.view.state.doc.attrs.form;          // only a reload brings another form (the piece's form changed)
      if (!meta && (json.attrs || {}).form !== form) json = {...json, attrs: {...json.attrs, form}};
      const next = root.PM.Node.fromJSON(S, editableDoc(json)), cur = this.view.state.doc;
      next.check();
      if (next.attrs.form !== cur.attrs.form) { this.closePop(); this.view.updateState(this.makeState(json)); this.margin.sync(this.view.state.doc); return; }
      const start = next.content.findDiffStart(cur.content);
      if (start == null) return;
      let {a: endA, b: endB} = next.content.findDiffEnd(cur.content);
      const overlap = start - Math.min(endA, endB);
      if (overlap > 0) { endA += overlap; endB += overlap; }
      const tr = this.view.state.tr.replace(start, endB, next.slice(start, endA));
      if (meta) tr.setMeta(meta, true);
      if (!history) tr.setMeta("addToHistory", false);       // a quiet reload: undo can't take back what came from outside
      else if (meta) tr.setTime(Date.now() + 600);           // the disk's text is an undo step of its own, even right after typing
      this.view.dispatch(tr);
    }
    focus() { this.view.focus(); }
    /* While the piece changes on disk (find and replace, restore): nothing in it can be typed in, the text, its notes,
       comments and captions alike; commands of the bar and the / menu wait too. */
    lock(on) {
      this.locked = !!on;
      if (this.locked) this.closePop();            // a citation or index form open now would change the text under the lock
      const editable = () => !this.locked;
      this.view.setProps({editable});
      for (const nv of this.margin.notes) nv.inner.setProps({editable});
      for (const c of this.margin.comments) c.ta.readOnly = this.locked;
      this.view.dom.querySelectorAll(".bk-cap").forEach(i => { i.readOnly = this.locked; });
    }
    async rereadLinked() {
      const known = this.ctx.linked();
      for (const src of new Set([...this.linkedViews].map(l => l.node.attrs.src))) {
        let p;
        try { p = await api("/api/book/poem?src=" + encodeURIComponent(src)); }
        catch { continue; }                 // unreachable for now: the last lines stay
        if (this.destroyed) return;
        if (JSON.stringify(known[src]) === JSON.stringify(p)) continue;
        known[src] = p;
        for (const l of this.linkedViews) if (l.node.attrs.src === src) l.render();       // a poem linked twice shows twice
      }
    }
    refresh() {       // the book's features, sources or linked poems changed
      this.applyFeatures();
      for (const c of this.cites) c.render();
      for (const l of this.linkedViews) l.render();
      this.selbar.key0 = ""; this.selbar.update();
      this.margin.schedule();
    }
    destroy() {
      this.destroyed = true;
      clearTimeout(this.backTimer);
      removeEventListener("focus", this.back); document.removeEventListener("visibilitychange", this.back);
      this.closePop();
      removeEventListener("mouseup", this.onUp);
      this.ro?.disconnect();
      this.view.destroy();
      cancelAnimationFrame(this.margin.frame);
    }
    words() { return docWords(this.view.state.doc); }
    noteAt(pos) { return [...this.margin.notes].find(nv => nv.getPos() === pos); }
    noteFocus(nv, on) {
      nv.item.classList.toggle("on", on); nv.dom.classList.toggle("on", on);
      if (!on) { nv.peeking = false; this.margin.schedule(); }
    }
    commentFocus(range) {
      this.view.dispatch(this.view.state.tr.setMeta(this.commentKey, range ? {from: range.from, to: range.to} : null));
    }

    /* ——— commands of the bar and the / menu ——— */
    command(cmd) {
      if (this.locked) return;
      const v = this.activeView(), s = v.state, {from, to} = s.selection;
      if (cmd === "bold") toggleMark(M.strong)(s, v.dispatch);
      else if (cmd === "italic") toggleMark(M.em)(s, v.dispatch);
      else if (cmd === "source") return this.citeForm(null, to, v);
      else if (v !== this.view) return;
      else if (cmd === "note") return this.insertNote(to);
      else if (cmd === "index") return this.indexForm(from, to);
      else if (cmd === "comment") return this.addComment(from, to);
      v.focus();
    }
    insert(id) {
      if (this.locked) return;
      const pos = this.view.state.selection.from;
      if (id === "note") return this.insertNote(pos);
      if (id === "cite") return this.citeForm(null, pos);
      if (id === "scene") return this.insertBlock(N.scene_break.create());
      if (id === "page") return this.insertBlock(N.page_break.create());
      if (id === "epigraph") return this.insertBlock(N.epigraph.create(null, N.paragraph.create()));
      if (id === "poem") return this.insertBlock(N.poem.create({src: null}, N.paragraph.create()));
      if (id === "image") {
        return this.ctx.pickImage().then(src => { if (src) this.insertBlock(N.image.create({src, alt: "", width: null})); else this.view.focus(); })
          .catch(e => { this.ctx.say(e.message, true); this.view.focus(); });
      }
      if (id === "linked") {
        return this.ctx.pickPoem().then(src => { if (src) this.insertBlock(N.poem.create({src})); else this.view.focus(); })
          .catch(e => { this.ctx.say(e.message, true); this.view.focus(); });
      }
    }
    insertNote(pos) {
      const v = this.view, $p = v.state.doc.resolve(pos);
      if (!$p.parent.inlineContent || !$p.parent.canReplaceWith($p.index(), $p.index(), N.note)) { this.ctx.say("A note goes in a line of text."); return; }
      const tr = v.state.tr.insert(pos, N.note.create());
      v.dispatch(tr.setSelection(TextSelection.create(tr.doc, pos + 2)).scrollIntoView());
      this.noteAt(pos)?.open();
    }
    /* a block at the cursor: in place of an empty paragraph, before or after the paragraph at its edges, between the two
       halves of a paragraph, or after the block the cursor is in */
    insertBlock(node) {
      const v = this.view, {$from} = v.state.selection, tr = v.state.tr;
      let pos;
      if ($from.depth === 1 && $from.parent.type === N.paragraph) {
        const p = $from.parent;
        if (!p.content.size) { pos = $from.before(1); tr.replaceWith(pos, pos + p.nodeSize, node); }
        else if ($from.parentOffset === 0) { pos = $from.before(1); tr.insert(pos, node); }
        else if ($from.parentOffset === p.content.size) { pos = $from.after(1); tr.insert(pos, node); }
        else { tr.split($from.pos); pos = $from.pos + 1; tr.insert(pos, node); }
      } else if ($from.depth >= 1) { pos = $from.after(1); tr.insert(pos, node); }
      else { pos = $from.pos; tr.insert(pos, node); }
      if (node.type === N.epigraph || node.type === N.poem && !node.attrs.src) {
        tr.setSelection(TextSelection.create(tr.doc, pos + 2));
      } else {
        const after = pos + node.nodeSize, next = tr.doc.resolve(after).nodeAfter;
        if (!next || !next.isTextblock) tr.insert(after, N.paragraph.create());
        tr.setSelection(TextSelection.create(tr.doc, after + 1));
      }
      v.dispatch(tr.scrollIntoView());
      v.focus();
    }
    addComment(from, to) {
      const v = this.view, existing = this.margin.commentAt(from);
      if (existing && existing.range.to >= to) { existing.ta.focus(); return; }
      const tr = v.state.tr.addMark(from, to, M.comment.create({note: ""}));
      v.dispatch(tr.setSelection(TextSelection.create(tr.doc, to)));
      this.margin.layout();
      this.margin.commentAt(from)?.ta.focus();
    }
    setComment(i, note) {
      const v = this.view, r = commentRanges(v.state.doc)[i];
      if (!r) return;
      v.dispatch(v.state.tr.removeMark(r.from, r.to, M.comment).addMark(r.from, r.to, M.comment.create({note})));
    }
    resolveComment(i) {
      if (this.locked) return;
      const v = this.view, r = commentRanges(v.state.doc)[i];
      if (!r) return;
      v.dispatch(v.state.tr.removeMark(r.from, r.to, M.comment).setMeta(this.commentKey, null));
      v.focus();
    }

    /* ——— the small forms: below the text they belong to ——— */
    /* at: the positions the form works on ({view, pos | from, to}), mapped through every change while it is open */
    openPop(cls, html, rect, at) {
      this.closePop();
      const f = el("form", "bk-pop " + cls);
      f.innerHTML = html;
      f.setAttribute("autocomplete", "off");
      this.over.append(f);
      const page = this.page.getBoundingClientRect(), col = (at.view === this.view ? this.textHost : at.view.dom).getBoundingClientRect();
      const left = Math.max(Math.min(col.left, page.right - f.offsetWidth - 16), Math.min(rect.left - 16, col.right - f.offsetWidth));
      f.style.left = Math.round(left - page.left) + "px";
      f.style.top = Math.round(rect.bottom - page.top + 10) + "px";
      f.addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.closePop(true); } });
      f.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => this.closePop(true)));
      // the click or key that opened the form is over, so the listener can start at once (and always goes with the form)
      this.outside = e => { if (!f.contains(e.target)) this.closePop(); };
      addEventListener("pointerdown", this.outside, true);
      this.pop = f; this.popPos = at;
      this.selbar.hide();
      return f;
    }
    closePop(refocus) {
      if (this.outside) { removeEventListener("pointerdown", this.outside, true); this.outside = null; }
      if (!this.pop) return;
      const view = this.popPos?.view;
      this.pop.remove(); this.pop = null; this.popPos = null;
      if (refocus && view && !this.destroyed) view.focus();
    }
    /* a citation's sources, prefixes and locators; `at` is a new citation's position, `cur` {pos, node} an existing one;
       `view` the text's view or a note's */
    citeForm(cur, at, view = this.view) {
      const v = view, sources = this.ctx.sources() || [], items = cur ? cur.node.attrs.items : [{key: "", prefix: "", locator: ""}];
      const pos = cur ? cur.pos : at;
      if (pos == null) return;
      const $p = v.state.doc.resolve(pos);
      if (!cur && (!$p.parent.inlineContent || !$p.parent.canReplaceWith($p.index(), $p.index(), N.cite))) { this.ctx.say("A citation goes in a line of text."); return; }
      const known = new Set(sources.map(s => s.id));
      const options = key => sources.map(s => `<option value="${esc(s.id)}" ${s.id === key ? "selected" : ""}>${esc(sourceShort(s) || s.id)}${s.title ? " · " + esc(shortTitle(s.title)) : ""}</option>`).join("")
        + `<option value="" ${key && known.has(key) ? "" : "selected"}>Other key…</option>`;
      const row = it => `<div class="bk-cite-row">
          <label class="bk-f"><span class="label">Source</span><select class="select" data-k="src">${options(it.key)}</select>
            <input class="input" data-k="key" value="${esc(known.has(it.key) ? "" : it.key)}" placeholder="Key, like smith2020" aria-label="Key" spellcheck="false" ${known.has(it.key) ? "hidden" : ""}></label>
          <label class="bk-f"><span class="label">Prefix</span><input class="input" data-k="prefix" value="${esc(it.prefix)}" placeholder="see"></label>
          <label class="bk-f"><span class="label">Locator</span><input class="input" data-k="locator" value="${esc(it.locator)}" placeholder="p. 12"></label>
          <button type="button" class="bm-btn bk-cite-x" data-x aria-label="Remove this source">Remove</button></div>`;
      const f = this.openPop("bk-citef", `<div class="bk-cite-rows">${items.map(row).join("")}</div>
        ${sources.length ? "" : `<p class="hint">This book has no sources yet: cite by key, and describe the source later.</p>`}
        <div class="bk-pop-f"><button type="button" class="bm-btn" data-more>Another source</button>
          ${this.ctx.features().sources === true && this.ctx.addSource ? `<button type="button" class="bm-btn bk-cite-add" data-add>Add source</button>` : ""}<span class="grow"></span>
          ${cur ? `<button type="button" class="btn small quiet" data-rm>Remove citation</button>` : ""}
          <button type="button" class="btn small quiet" data-close>Cancel</button><button type="submit" class="btn small solid">${cur ? "Save" : "Insert"}</button></div>`,
        v.coordsAtPos(pos), {view: v, pos, existing: !!cur});
      const rows = f.querySelector(".bk-cite-rows"), place = () => this.popPos;
      const wire = r => {
        const sel = r.querySelector("[data-k=src]"), key = r.querySelector("[data-k=key]");
        sel.addEventListener("change", () => { key.hidden = !!sel.value; if (!sel.value) key.focus(); });
        r.querySelector("[data-x]").addEventListener("click", () => { if (rows.children.length > 1) r.remove(); });
      };
      [...rows.children].forEach(wire);
      f.querySelector("[data-more]").addEventListener("click", () => {
        rows.insertAdjacentHTML("beforeend", row({key: "", prefix: "", locator: ""}));
        wire(rows.lastElementChild); rows.lastElementChild.querySelector("select").focus();
      });
      f.querySelector("[data-rm]")?.addEventListener("click", () => {
        if (this.locked) return;
        const p = place().pos;
        this.closePop();
        if (v.state.doc.nodeAt(p)?.type === N.cite) v.dispatch(v.state.tr.delete(p, p + 1));
        v.focus();
      });
      f.querySelector("[data-add]")?.addEventListener("click", () => { this.closePop(); this.ctx.addSource(); });     // the rail's Sources panel
      f.addEventListener("submit", e => {
        e.preventDefault();
        const next = [];
        for (const r of rows.children) {
          const pick = r.querySelector("[data-k=src]").value, key = pick || r.querySelector("[data-k=key]").value.trim();
          if (!CITE_KEY.test(key)) { this.ctx.say(key ? `${key} can't be a key: use letters, digits, - and _.` : "Choose a source, or give its key.", true); r.querySelector(pick ? "select" : "[data-k=key]").focus(); return; }
          next.push({key, prefix: r.querySelector("[data-k=prefix]").value.replace(/\s+/g, " ").trim(), locator: r.querySelector("[data-k=locator]").value.replace(/\s+/g, " ").trim()});
        }
        if (this.locked) return;
        const p = place().pos;
        this.closePop();
        const tr = v.state.tr;
        if (cur) { if (v.state.doc.nodeAt(p)?.type !== N.cite) return; tr.setNodeMarkup(p, null, {items: next}); }
        else { tr.insert(p, N.cite.create({items: next})); tr.setSelection(TextSelection.create(tr.doc, p + 1)); }
        v.dispatch(tr.scrollIntoView()); v.focus();
      });
      f.querySelector("select").focus();
    }
    /* the index term of a selection: the selected text by default, `a > b` a subentry */
    indexForm(from, to) {
      const v = this.view, text = v.state.doc.textBetween(from, to, " ", "").replace(/\s+/g, " ").trim();
      let mark = null;
      v.state.doc.nodesBetween(from, to, n => { mark = mark || M.idx.isInSet(n.marks); });
      const f = this.openPop("bk-idxf", `<label class="bk-f"><span class="label">Index term</span>
          <input class="input" name="term" value="${esc(mark ? mark.attrs.term || text : text)}" spellcheck="true" lang="${esc(this.lang)}"></label>
        <p class="hint">Write a subentry as term &gt; subentry, like trauma &gt; childhood.</p>
        <div class="bk-pop-f"><span class="grow"></span>${mark ? `<button type="button" class="btn small quiet" data-rm>Remove from the index</button>` : ""}
          <button type="button" class="btn small quiet" data-close>Cancel</button><button type="submit" class="btn small solid">${mark ? "Save" : "Add to index"}</button></div>`,
        v.coordsAtPos(to, -1), {view: v, from, to});
      const input = f.querySelector("input"), place = () => this.popPos;
      f.querySelector("[data-rm]")?.addEventListener("click", () => {
        if (this.locked) return;
        const {from: a, to: b} = place();
        this.closePop(); v.dispatch(v.state.tr.removeMark(a, b, M.idx)); v.focus();
      });
      f.addEventListener("submit", e => {
        e.preventDefault();
        if (this.locked) return;
        const term = indexTerm(input.value);
        if (!term) { this.ctx.say("Give the term this text is indexed under.", true); input.focus(); return; }
        const {from: a, to: b} = place();
        this.closePop();
        v.dispatch(v.state.tr.removeMark(a, b, M.idx).addMark(a, b, M.idx.create({term: term === text ? null : term})));
        v.focus();
      });
      input.select();
    }
    pasteWarning(e) {
      const data = e.clipboardData;
      if (!data) return;
      const html = data.getData("text/html") || "", images = [...(data.files || [])].some(f => /^image\//.test(f.type));
      if (/<img\b/i.test(html) || (images && !html && !data.getData("text/plain"))) {
        setTimeout(() => this.ctx.say("Images aren't pasted: insert one with / and Image."), 0);
      }
    }
  }

  /* Word and Google Docs leave list bullets and stray line breaks between paragraphs in what they copy; the schema's own
     paste rules do the rest (italic and bold stay, headings become ## and ###, the rest plain paragraphs). */
  function cleanPaste(html) {
    if (!/mso-|urn:schemas-microsoft|docs-internal-guid/i.test(html)) return html;
    const d = new root.DOMParser().parseFromString(html, "text/html");
    d.querySelectorAll("[style]").forEach(e => { if (/mso-list\s*:\s*ignore/i.test(e.getAttribute("style"))) e.remove(); });
    d.querySelectorAll("br").forEach(br => { if (!br.closest("p, li, h1, h2, h3, h4, h5, h6, td, th, blockquote, div:not([id^=docs-internal])")) br.remove(); });
    return d.body.innerHTML;
  }

  /* placeholders for an empty title, an empty piece, an empty attribution, poem or epigraph */
  function placeholders(state) {
    const doc = state.doc, out = [], ph = (pos, n, text) => out.push(Decoration.node(pos, pos + n.nodeSize, {class: "bk-ph", "data-ph": text}));
    const first = doc.firstChild;
    if (first && first.type === N.title && !first.content.size) ph(0, first, "Title");
    const body = first && first.type === N.title ? 1 : 0;
    if (doc.childCount === body + 1 && doc.child(body).type === N.paragraph && !doc.child(body).content.size) {
      ph(body ? first.nodeSize : 0, doc.child(body), "Start writing. Type / for a note, a poem, a scene break and more.");
    }
    doc.forEach((n, pos) => {
      if (n.type === N.epigraph) {
        if (n.firstChild && n.firstChild.type === N.paragraph && !n.textContent) ph(pos + 1, n.firstChild, "Quotation");
        n.forEach((c, off) => { if (c.type === N.attribution && !c.content.size) ph(pos + 1 + off, c, "Who said it"); });
      }
      if (n.type === N.poem && !n.attrs.src && n.childCount === 1 && !n.firstChild.content.size) ph(pos + 1, n.firstChild, "Lines of the poem");
    });
    return out.length ? DecorationSet.create(doc, out) : null;
  }

  root.BookText = {
    create: (hosts, opts) => new Text(hosts, opts),
    // helpers, also for tests/js/book_text.js
    quoteFor, CLITIC, countWords, docWords, noteStart, citeLabel, sourceShort, slashItems, barButtons, commentRanges,
    indexTerm, editableDoc, titleOf, withTitle, CITE_KEY, blockRules, inlineRules, Margin,
    poemTyped, poemTab, poemPasted, poemText, oneLine,
  };
})(typeof window !== "undefined" ? window : globalThis);
