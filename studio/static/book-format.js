"use strict";
/* The writing window's formatting (book-text.js uses it). Lists: the marker an item shows, the list commands and keys,
   the typing triggers, and the plugin that keeps a list's numbers where they were. Then alignment, text styles
   (paragraph, heading, subheading, quotation), sizes, marks and clear formatting; what applies and what is on where the
   cursor is (the format panel shows it); the keys, and KEYS, one row per command for the panel and the palette. Last,
   what the writing window takes from here: the markers shown in the text, the clipboard's plain text, and pasted lists.
   A classic script after vendor/prosemirror.js and book-schema.js; sets window.BookFormat. Only pasteLists touches the
   DOM (the browser's DOMParser), so tests/js/book_format.js runs the rest in node. Spec:
   docs/superpowers/specs/2026-11-13-book-editor-power-design.md ("Lists in detail", "Alignment in detail", "Marks in
   detail", "Typing", "In a list", "The format panel", "Keys", "Clear formatting", "Paste", "Look"). */
(function (root) {
  const S = root.BookSchema, N = S.nodes, M = S.marks;
  const {EditorState, Plugin, PluginKey, TextSelection, NodeSelection, InputRule, Mapping, Decoration, DecorationSet, Fragment,
    Slice} = root.PM;

  /* ——— markers: the rule of manuscript_lists.py (markers, marker_text), the same everywhere ——— */
  const STYLES = ["bullet", "decimal", "lower-alpha", "upper-alpha", "lower-roman", "upper-roman"];
  const MAX_LEVEL = 3;
  /* the style a numbered item takes going in, by its new level (Word's and Docs' multilevel default) */
  const NEST = ["decimal", "lower-alpha", "lower-roman", "decimal"];
  const BULLETS = "•◦▪•";      // by level
  const NUMERALS = [[1000, "m"], [900, "cm"], [500, "d"], [400, "cd"], [100, "c"], [90, "xc"], [50, "l"], [40, "xl"],
    [10, "x"], [9, "ix"], [5, "v"], [4, "iv"], [1, "i"]];
  /* 14 -> `xiv` */
  function toRoman(n) { let out = ""; for (const [value, digits] of NUMERALS) while (n >= value) { out += digits; n -= value; } return out; }
  /* 1 -> `a`, 26 -> `z`, 27 -> `aa` */
  function toAlpha(n) { let out = ""; while (n > 0) { out = String.fromCharCode(97 + (n - 1) % 26) + out; n = Math.floor((n - 1) / 26); } return out; }
  /* What an item shows: `•` `◦` `▪` `•` by level for bullets, else `1.`, `a.`, `A.`, `iv.`, `IV.`. */
  function markerText(list, n, level) {
    if (list === "bullet") return BULLETS[Math.min(Math.max(level, 0), MAX_LEVEL)];
    const s = list === "decimal" ? String(n) : /-alpha$/.test(list) ? toAlpha(n) : /-roman$/.test(list) ? toRoman(n) : null;
    if (s == null) throw new RangeError(`unknown list style: ${list}`);
    return (list.startsWith("upper") ? s.toUpperCase() : s) + ".";
  }
  /* `start` when a list of `list` can start there (numbers from 0, letters and numerals from 1, at most nine digits as
     CommonMark reads them, roman numerals up to 3999), else null: manuscript_lists._valid_start */
  const MAX_START = 999999999;
  function validStart(list, start) {
    const least = list === "decimal" ? 0 : list === "bullet" ? null : 1;
    const most = list === "lower-roman" || list === "upper-roman" ? 3999 : MAX_START;
    return least != null && Number.isInteger(start) && start >= least && start <= most ? start : null;
  }
  /* Per top-level block of `doc`: null, or for a list item {pos, marker, level, list, n, first, run}. A stack of open
     lists, one per level: a block that isn't an item closes every list; an item's level is clamped to at most one deeper
     than the stack (and MAX_LEVEL); lists deeper than it close; the same style at its level continues that list (n + 1),
     another style or nothing open there starts one at the item's `start`. `first`: the item starts a list; `run`: the
     index of its list's first item. */
  function markers(doc) {
    const out = [];
    let stack = [];             // per level: {list, n, run}
    doc.forEach((node, pos, k) => {
      if (node.type !== N.list_item) { stack = []; out.push(null); return; }
      const {list, level: stored, start} = node.attrs;
      const level = Math.min(Math.max(Number.isInteger(stored) ? stored : 0, 0), stack.length, MAX_LEVEL);
      stack.length = Math.min(stack.length, level + 1);
      const first = level === stack.length || stack[level].list !== list;
      if (first) { const s = validStart(list, start); stack.length = level; stack.push({list, n: s == null ? 1 : s, run: k}); }
      else stack[level].n++;
      const {n, run} = stack[level];
      out.push({pos, marker: markerText(list, n, level), level, list, n, first, run});
    });
    return out;
  }

  /* The list items of the document in `tr` as a reload gives them (manuscript_lists.normalize): levels clamped, `start`
     only on an item that starts a list at another number than 1. Adds the changes to `tr` and returns it. */
  function canonical(tr) {
    const doc = tr.doc, ms = markers(doc);
    doc.forEach((node, pos, i) => {
      const m = ms[i];
      if (!m) return;
      let start = m.first ? validStart(m.list, node.attrs.start) : null;
      if (start === 1) start = null;
      if (node.attrs.level !== m.level || node.attrs.start !== start) tr.setNodeMarkup(pos, null, {list: m.list, level: m.level, start});
    });
    return tr;
  }

  /* ——— commands: (state, dispatch?) => boolean; without dispatch they only say whether they apply ——— */
  const prose = state => state.doc.type === N.doc && state.doc.attrs.form !== "poem";
  /* the top-level blocks of `doc` that [from, to] touches: [{node, pos, index}] */
  function topsIn(doc, from, to) {
    const $from = doc.resolve(from), $to = doc.resolve(to), out = [];
    const last = $to.depth ? $to.index(0) : $to.index(0) - 1;
    for (let index = $from.index(0), pos = $from.depth ? $from.before(1) : from; index <= last; index++) {
      const node = doc.child(index);
      out.push({node, pos, index});
      pos += node.nodeSize;
    }
    return out;
  }
  /* the top-level text blocks the selection touches, the title left out: [{node, pos, index}] */
  function touched(state) {
    if (state.doc.type !== N.doc) return [];
    return topsIn(state.doc, state.selection.from, state.selection.to).filter(b => b.node.isTextblock && b.node.type !== N.title);
  }
  /* The attributes of item `index` one level in (dir 1) or out (-1), null when it can't go: in at most one deeper than
     the item before it (none before: not at all) and not past MAX_LEVEL; out not past level 0. It takes the style of the
     nearest item above it at the new level (before a shallower one), so it joins that list; else going in, a numbered
     item takes NEST's style and a bullet stays a bullet, and going out it keeps its own. */
  function shifted(doc, index, dir) {
    const ms = markers(doc), m = ms[index], prev = index > 0 ? ms[index - 1] : null;
    if (!m) return null;
    const level = m.level + dir;
    if (level < 0 || level > Math.min(prev ? prev.level + 1 : 0, MAX_LEVEL)) return null;
    let list = null;
    for (let k = index - 1; k >= 0 && ms[k] && ms[k].level >= level; k--) if (ms[k].level === level) { list = ms[k].list; break; }
    return {list: list || (dir > 0 && m.list !== "bullet" ? NEST[level] : m.list), level, start: null};
  }
  /* One level out, or a paragraph at level 0 (Enter on an empty item, Backspace at an item's start). */
  function outOrEnd(state, dispatch, pos, index) {
    if (!dispatch) return true;
    const attrs = shifted(state.doc, index, -1);
    dispatch((attrs ? state.tr.setNodeMarkup(pos, null, attrs) : state.tr.setNodeMarkup(pos, N.paragraph)).scrollIntoView());
    return true;
  }

  /* Every top-level text block the selection touches becomes an item of `style` (an item keeps its level, anything else
     goes to level 0); when they all are items of that style already, they become paragraphs again. */
  function setList(style) {
    return (state, dispatch) => {
      if (!prose(state) || !STYLES.includes(style)) return false;
      const blocks = touched(state);
      if (!blocks.length) return false;
      if (dispatch) {
        const off = blocks.every(b => b.node.type === N.list_item && b.node.attrs.list === style), tr = state.tr;
        for (const {node, pos} of blocks) {
          if (off) tr.setNodeMarkup(pos, N.paragraph);
          else if (node.type === N.list_item) tr.setNodeMarkup(pos, null, {...node.attrs, list: style});
          else tr.setNodeMarkup(pos, N.list_item, {list: style, level: 0, start: null});
        }
        dispatch(tr.scrollIntoView());
      }
      return true;
    };
  }
  /* Every selected item one level in (dir 1, top to bottom) or out (-1, bottom to top: an item going out above a deeper
     one would clamp that one); false when none can move. */
  function indent(dir) {
    return (state, dispatch) => {
      if (!prose(state)) return false;
      const tr = state.tr, blocks = touched(state);
      if (dir < 0) blocks.reverse();
      for (const {node, pos, index} of blocks) {
        const attrs = node.type === N.list_item && shifted(tr.doc, index, dir);
        if (attrs) tr.setNodeMarkup(pos, null, attrs);
      }
      if (!tr.docChanged) return false;
      dispatch?.(tr.scrollIntoView());
      return true;
    };
  }
  const inList = state => prose(state) && touched(state).some(b => b.node.type === N.list_item);
  /* Tab and Shift+Tab: in a list the key is the list's, even when the item can't move; elsewhere it passes on (a poem's
     Tab indents its line). */
  const listTab = (state, dispatch) => { if (!inList(state)) return false; indent(1)(state, dispatch); return true; };
  const listShiftTab = (state, dispatch) => { if (!inList(state)) return false; indent(-1)(state, dispatch); return true; };
  /* Enter in an item: a new item of the same style and level with the rest of the line; on an empty item, one level
     out, at level 0 a paragraph (the list ends there). */
  function listEnter(state, dispatch) {
    const sel = state.selection, {$from, $to} = sel;
    if (!prose(state) || !(sel instanceof TextSelection) || $from.depth !== 1 || $from.parent.type !== N.list_item || !$from.sameParent($to)) return false;
    const item = $from.parent;
    if (!item.content.size) return outOrEnd(state, dispatch, $from.before(1), $from.index(0));
    if (dispatch) {
      const tr = state.tr.deleteSelection();
      tr.split(tr.mapping.map($from.pos), 1, [{type: N.list_item, attrs: {...item.attrs, start: null}}]);
      dispatch(tr.scrollIntoView());
    }
    return true;
  }
  /* Backspace at an item's start (nothing selected): one level out, at level 0 a paragraph. */
  function listBackspace(state, dispatch) {
    const {$cursor} = state.selection;
    if (!prose(state) || !$cursor || $cursor.depth !== 1 || $cursor.parentOffset !== 0 || $cursor.parent.type !== N.list_item) return false;
    return outOrEnd(state, dispatch, $cursor.before(1), $cursor.index(0));
  }

  /* ——— typing: at the start of a top-level paragraph of a prose piece ——— */
  const LETTERS = {a: "lower-alpha", A: "upper-alpha", i: "lower-roman", I: "upper-roman"};
  const TRIGGERS = [
    [/^[-•] $/, () => ["bullet", null]],
    [/^(\d{1,9})[.)] $/, m => ["decimal", +m[1]]],
    [/^([aAiI])[.)] $/, m => [LETTERS[m[1]], null]],      // letters and numerals only from their first value: `J. ` stays
  ];
  function inputRules() {
    return TRIGGERS.map(([re, style]) => new InputRule(re, (state, m, start, end) => {
      const $s = state.doc.resolve(start);
      if (!prose(state) || $s.depth !== 1 || $s.parent.type !== N.paragraph || $s.parentOffset !== 0) return null;
      const [list, n] = style(m);
      const tr = state.tr.delete(start, end).setNodeMarkup($s.before(1), N.list_item, {list, level: 0, start: n});
      // already as the numbers plugin leaves it (no start when it continues a list above), so nothing is appended and
      // one Backspace (undoInputRule) takes it back
      return canonical(tr);
    }));
  }

  /* ——— the numbers plugin ——— */
  /* Undo and redo and taking a typing trigger back put back a document that was: its numbers stay as they were then. */
  function restores(trs, old, state) {
    // prosemirror-history marks its transactions with its plugin key, PluginKey("history"), whose string is "history$"
    // (the bundle's only key of that name); a change there would show in tests/js/book_format.js `undo:setList`
    if (trs.some(tr => tr.getMeta("history$"))) return true;
    for (const p of old.plugins) {
      const typed = p.spec.isInputRules && p.getState(old);
      if (!typed || !typed.transform) continue;
      const tr = EditorState.create({doc: typed.transform.before}).tr;     // the document before the trigger, as typed
      if (typed.text) tr.replaceWith(typed.from, typed.to, S.text(typed.text, tr.doc.resolve(typed.from).marks()));
      else tr.delete(typed.from, typed.to);
      if (tr.doc.eq(state.doc)) return true;
    }
    return false;
  }
  /* Per list (the index of its first item, from `markers`): the first list of the lists it is one with. A list that
     counted on from an earlier one (it starts at the number after the last item of the nearest earlier list of the same
     style and level, whatever came between, but not before a shallower item: a sublist belongs to its parent item) is
     that list. */
  function chains(ms) {
    const chain = new Map(), last = [];      // per level: style -> the last item seen there, {n, run}
    ms.forEach((m, k) => {
      if (!m) return;
      last.length = m.level + 1;             // a shallower item: the deeper lists before it are no one's to count on
      const at = last[m.level] || (last[m.level] = new Map()), prev = at.get(m.list);
      if (m.first) chain.set(k, prev && m.n === prev.n + 1 ? chain.get(prev.run) : k);
      at.set(m.list, {n: m.n, run: m.run});
    });
    return chain;
  }
  /* The index of the top-level block of `doc` that `pos` lies inside, -1 between blocks; `ends` are the blocks' ends. */
  function blockAt(ends, doc, pos) {
    let lo = 0, hi = ends.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (ends[mid] <= pos) lo = mid + 1; else hi = mid; }
    return lo < ends.length && ends[lo] - doc.child(lo).nodeSize < pos ? lo : -1;
  }
  /* A list goes on counting across what comes between its items, as in Word and Docs, and follows the list it counted on
     from when that one grows or shrinks. An item that before the transactions `trs` continued a list, or started a list
     that counted on from an earlier one, and that starts a list in `tr`'s document with the same style and level, gets as
     its `start` the number after the last item now of the nearest earlier list that holds an item of the list it belonged
     to (its own, or one it counted on from or that counted on from it), looking back no further than a shallower item (a
     sublist belongs to its parent item); with none left (deleted, made paragraphs, moved, or under another item) it
     starts at 1. An item whose own style or level changed starts afresh; a list started at a number of its own stays
     there. Items are followed by their inner position, mapped to the left (content put in at an item's start stays in
     that item) and lost only when deleted across. `now` is markers(tr.doc). One pass over the document; adds the changes
     to `tr`. */
  function countOn(tr, trs, old, now) {
    const mapping = new Mapping(), before = markers(old.doc), from = new Map();      // block index now -> old block index
    for (const t of trs) mapping.appendMapping(t.mapping);
    const ends = [];
    tr.doc.forEach((node, pos) => ends.push(pos + node.nodeSize));
    old.doc.forEach((node, pos, i) => {
      if (!before[i]) return;
      const r = mapping.mapResult(pos + 1, -1), j = r.deletedAcross ? -1 : blockAt(ends, tr.doc, r.pos);
      if (j >= 0 && !from.has(j)) from.set(j, i);
    });
    const chain = chains(before), chainOf = i => chain.get(before[i].run);
    const runLast = new Map();      // a list now (the index of its first item) -> the number of its last item so far
    const seen = [];                // per level: style -> (the old list an item belonged to -> the list it is in now)
    let ms = now;
    for (let j = 0; j < ms.length; j++) {
      let m = ms[j];
      if (!m) continue;
      seen.length = m.level + 1;
      const at = seen[m.level] || (seen[m.level] = new Map()), i = from.get(j), was = i == null ? null : before[i];
      if (m.first && was && m.list === was.list && m.level === was.level && (!was.first || chain.get(i) !== i)) {
        const r = at.get(m.list)?.get(chainOf(i));
        let start = validStart(m.list, r == null ? null : runLast.get(r) + 1);
        if (start === 1) start = null;
        const node = tr.doc.child(j);
        if (node.attrs.start !== start) {
          tr.setNodeMarkup(m.pos, null, {...node.attrs, start});
          ms = markers(tr.doc);         // the numbers of the items from here on change (the ones before stay)
          m = ms[j];
        }
      }
      runLast.set(m.run, m.n);
      if (was) {
        if (!at.has(m.list)) at.set(m.list, new Map());
        at.get(m.list).set(chainOf(i), m.run);
      }
    }
    return tr;
  }
  /* After every change: lists count on (countOn); then `start` goes from items that continue a list and levels are
     clamped, so the editor's document is what a reload gives. Linear in the document (it runs on every keystroke). */
  function numbersPlugin() {
    return new Plugin({
      appendTransaction(trs, old, state) {
        if (!trs.some(tr => tr.docChanged)) return null;
        const now = markers(state.doc);
        if (!now.some(Boolean)) return null;          // no list: nothing to do
        const tr = canonical(restores(trs, old, state) ? state.tr : countOn(state.tr, trs, old, now));
        return tr.docChanged ? tr : null;
      },
    });
  }

  /* ——— blocks: alignment, text styles, quotations. Block choices apply to every block the selection touches ——— */
  /* Lifts the paragraphs that [from, to] touches inside the containers `which` picks (aligned blocks, quotations) out to
     the top level; what is left of a container stays around them. */
  function liftOut(tr, from, to, which) {
    for (const {node, pos} of topsIn(tr.doc, from, to).filter(b => which(b.node)).reverse()) {
      let a = null, b = null;
      node.forEach((child, offset) => {
        const start = pos + 1 + offset, end = start + child.nodeSize;
        if (from < end && to > start) { if (a == null) a = start; b = end; }
      });
      if (a != null) tr.lift(tr.doc.resolve(a + 1).blockRange(tr.doc.resolve(b - 1)), 0);
    }
  }
  /* Wraps every run of top-level blocks that [from, to] touches and `ok` accepts in a block of `type`. */
  function wrapRuns(tr, from, to, type, attrs, ok) {
    const runs = [];
    let last = -2;
    for (const {node, pos, index} of topsIn(tr.doc, from, to)) {
      if (!ok(node)) continue;
      if (index === last + 1) runs[runs.length - 1].end = pos + node.nodeSize;
      else runs.push({start: pos, end: pos + node.nodeSize});
      last = index;
    }
    for (const {start, end} of runs.reverse()) tr.wrap(tr.doc.resolve(start + 1).blockRange(tr.doc.resolve(end - 1)), [{type, attrs}]);
  }
  /* Joins the top-level blocks [from, to] touches, and the ones next to them, where `same(before, after)`. */
  function joinAround(tr, from, to, same) {
    const doc = tr.doc, cuts = [];
    const lo = doc.resolve(from).index(0) - 1, hi = doc.resolve(to).index(0) + 1;
    doc.forEach((node, pos, k) => { if (k > lo && k <= hi && k > 0 && same(doc.child(k - 1), node)) cuts.push(pos); });
    for (const pos of cuts.reverse()) tr.join(pos);
  }

  /* Alignment: "as the book" (null), "center", "right"; only top-level paragraphs and the paragraphs of aligned blocks,
     in a prose piece. */
  const ALIGNS = ["center", "right"];
  function alignable(state) {
    if (!prose(state)) return false;
    const blocks = topsIn(state.doc, state.selection.from, state.selection.to);
    return blocks.length > 0 && blocks.every(b => b.node.type === N.paragraph || b.node.type === N.aligned);
  }
  const sameAlign = (a, b) => a.type === N.aligned && b.type === N.aligned && a.attrs.align === b.attrs.align;
  /* Every paragraph the selection touches gets `align`: out of an aligned block of another alignment (it splits around
     them), into one of its own; neighbouring blocks of the same alignment are joined, as a reload gives them. */
  function setAlign(align) {
    return (state, dispatch) => {
      if ((align != null && !ALIGNS.includes(align)) || !alignable(state)) return false;
      if (dispatch) {
        const tr = state.tr, {from, to} = state.selection, map = p => tr.mapping.map(p);
        liftOut(tr, from, to, n => n.type === N.aligned && n.attrs.align !== align);
        if (align) wrapRuns(tr, map(from), map(to), N.aligned, {align}, n => n.type === N.paragraph);
        joinAround(tr, map(from), map(to), sameAlign);
        if (tr.docChanged) dispatch(tr.scrollIntoView());
      }
      return true;
    };
  }

  /* Text styles apply to paragraphs, headings, list items, and the paragraphs of aligned blocks and quotations; the title
     and blocks without text are passed over; an epigraph, a poem or a table in the selection stops them (and a note). */
  const TEXT_STYLES = ["paragraph", "heading", "subheading", "quotation"], HEADINGS = {heading: 2, subheading: 3};
  const STYLED = new Set([N.paragraph, N.heading, N.list_item, N.aligned, N.blockquote]);
  const PASSED = new Set([N.title, N.scene_break, N.page_break, N.image]);
  /* the top-level blocks the selection touches when a text style applies to them, else null */
  function styleable(state) {
    if (state.doc.type !== N.doc) return null;
    const blocks = topsIn(state.doc, state.selection.from, state.selection.to);
    const ok = blocks.every(b => STYLED.has(b.node.type) || PASSED.has(b.node.type)) && blocks.some(b => STYLED.has(b.node.type));
    return ok ? blocks : null;
  }
  const isQuote = n => n.type === N.blockquote;
  /* a block's line breaks as spaces, those in its notes too: a heading is one line, and so is a note in it as written */
  function unbreak(tr, pos, node) {
    node.descendants((child, offset) => {      // one position for one: the offsets after it stay
      if (child.type === N.hard_break) tr.replaceWith(pos + 1 + offset, pos + 2 + offset, S.text(" ", child.marks));
    });
  }
  /* Paragraph: a heading becomes a paragraph, a quotation's paragraph comes out of it; a list item or an aligned
     paragraph already is one. Heading, subheading: out of an aligned block or a quotation first; paragraphs, items and
     headings become headings of that level. Quotation toggles: off when everything selected is quoted already. */
  function setTextStyle(style) {
    return (state, dispatch) => {
      const blocks = TEXT_STYLES.includes(style) && styleable(state);
      if (!blocks) return false;
      if (style === "quotation") {
        return blocks.filter(b => STYLED.has(b.node.type)).every(b => isQuote(b.node)) ? unquote(state, dispatch) : quoteIn(state, dispatch, true);
      }
      if (dispatch) {
        const tr = state.tr, {from, to} = state.selection, level = HEADINGS[style] || null;
        liftOut(tr, from, to, n => isQuote(n) || (level != null && n.type === N.aligned));
        for (const {node, pos} of topsIn(tr.doc, tr.mapping.map(from), tr.mapping.map(to)).reverse()) {
          if (level == null) { if (node.type === N.heading) tr.setNodeMarkup(pos, N.paragraph); }
          else if (node.type === N.paragraph || node.type === N.list_item || (node.type === N.heading && node.attrs.level !== level)) {
            unbreak(tr, pos, node);
            tr.setNodeMarkup(pos, N.heading, {level});
          }
        }
        if (tr.docChanged) dispatch(tr.scrollIntoView());
      }
      return true;
    };
  }
  /* The paragraphs the selection touches into a quotation, joined with a quotation next to it: out of aligned blocks and
     quotations first; with `convert` (the Quotation style) list items and headings become paragraphs too, else (Ctrl+])
     they stay between. */
  function quoteIn(state, dispatch, convert) {
    if (dispatch) {
      const tr = state.tr, {from, to} = state.selection, map = p => tr.mapping.map(p);
      liftOut(tr, from, to, n => isQuote(n) || n.type === N.aligned);
      if (convert) {
        for (const {node, pos} of topsIn(tr.doc, map(from), map(to))) {
          if (node.type === N.list_item || node.type === N.heading) tr.setNodeMarkup(pos, N.paragraph);
        }
      }
      wrapRuns(tr, map(from), map(to), N.blockquote, null, n => n.type === N.paragraph);
      joinAround(tr, map(from), map(to), (a, b) => isQuote(a) && isQuote(b));
      dispatch(tr.scrollIntoView());
    }
    return true;
  }
  /* the quoted paragraphs the selection touches out of their quotation */
  function unquote(state, dispatch) {
    if (dispatch) {
      const tr = state.tr;
      liftOut(tr, state.selection.from, state.selection.to, isQuote);
      dispatch(tr.scrollIntoView());
    }
    return true;
  }
  /* Ctrl+] and Ctrl+[ outside a list: paragraphs into a quotation (1), quoted paragraphs out of it (-1). */
  function quote(dir) {
    return (state, dispatch) => {
      const blocks = styleable(state);
      if (!blocks) return false;
      if (dir < 0) return blocks.some(b => isQuote(b.node)) && unquote(state, dispatch);
      return blocks.some(b => b.node.type === N.paragraph || b.node.type === N.aligned) && quoteIn(state, dispatch, false);
    };
  }

  /* ——— characters: sizes, marks, clear formatting. They apply to the selection; with a cursor, to what is typed next ——— */
  const SIZE_STEPS = ["x-small", "small", null, "large", "x-large"];       // Normal, no size mark, in the middle
  const MARKS = ["strong", "em", "underline", "strike", "smallcaps"];
  const CLEARED = ["em", "strong", "underline", "strike", "smallcaps", "size"];
  /* text, or a cursor where text is typed (not a selected image, not between blocks) */
  function marksApply(state) {
    const sel = state.selection;
    return sel.empty ? sel.$from.parent.inlineContent : !(sel instanceof NodeSelection) || sel.node.isInline;
  }
  const sizeOf = marks => { const m = M.size.isInSet(marks); return m ? m.attrs.size : null; };
  /* the selection's [from, to] spans */
  const spans = state => state.selection.ranges.map(r => [r.$from.pos, r.$to.pos]);
  /* The [from, to] spans `within` `doc` in ranges that leave out their notes, and the positions of the notes they hold: a
     note's own text (edited in the margin) keeps its formatting. */
  function pieces(doc, within) {
    const ranges = [], notes = [];
    for (const [from, to] of within) {
      let at = from;
      doc.nodesBetween(from, to, (node, pos) => {
        if (node.type !== N.note) return true;
        if (pos > at) ranges.push([at, pos]);
        if (pos >= from && pos + node.nodeSize <= to) notes.push(pos);
        at = Math.max(at, pos + node.nodeSize);
        return false;
      });
      if (to > at) ranges.push([at, to]);
    }
    return {ranges, notes};
  }
  /* Calls f(node) for every node that carries the selection's marks, in order: its text, sources and the notes it holds,
     never a note's own text (as `pieces`); f returns true to stop. current() and the toggles both read the marks so, so
     the panel shows what a toggle will do. */
  function eachCarrier(state, f) {
    let stop = false;
    for (const {$from, $to} of state.selection.ranges) {
      state.doc.nodesBetween($from.pos, $to.pos, (node, pos) => {
        if (stop) return false;
        if (node.type === N.note) { if (pos >= $from.pos && pos + node.nodeSize <= $to.pos) stop = !!f(node); return false; }
        if (node.isText || node.type === N.cite) stop = !!f(node);
        return !stop;
      });
      if (stop) break;
    }
  }
  /* the mark types the selection holds (as eachCarrier reads them); with a cursor, those of what is typed next */
  function marksHeld(state) {
    const sel = state.selection, held = new Set();
    if (sel.empty) for (const m of state.storedMarks || sel.$from.marks()) held.add(m.type);
    else eachCarrier(state, node => { for (const m of node.marks) held.add(m.type); });
    return held;
  }
  /* Size `size` (a step of SIZE_STEPS; null: Normal) for the selection, one size for all of it. */
  function setSize(size) {
    return (state, dispatch) => {
      if (!SIZE_STEPS.includes(size) || !marksApply(state)) return false;
      if (dispatch) {
        const tr = state.tr, mark = size && M.size.create({size});
        if (state.selection.empty) {
          tr.removeStoredMark(M.size);
          if (mark) tr.addStoredMark(mark);
          dispatch(tr);
          return true;
        }
        const {ranges, notes} = pieces(state.doc, spans(state));
        for (const [a, b] of ranges) { tr.removeMark(a, b, M.size); if (mark) tr.addMark(a, b, mark); }
        for (const pos of notes) { tr.removeNodeMark(pos, M.size); if (mark) tr.addNodeMark(pos, mark); }
        if (!tr.doc.eq(state.doc)) dispatch(tr.scrollIntoView());
      }
      return true;
    };
  }
  /* the size at the selection's start: its first text, source or note, or what is typed next */
  function sizeAt(state) {
    const sel = state.selection;
    let marks = sel.empty ? state.storedMarks || sel.$from.marks() : null;
    if (!marks) eachCarrier(state, node => { marks = node.marks; return true; });
    return sizeOf(marks || sel.$from.marks());
  }
  /* One step larger (1) or smaller (-1) than the size at the selection's start, for all of it; at the end of the scale
     it stays there. */
  function stepSize(dir) {
    return (state, dispatch) => {
      if (!marksApply(state)) return false;
      const k = Math.min(Math.max(SIZE_STEPS.indexOf(sizeAt(state)) + dir, 0), SIZE_STEPS.length - 1);
      return setSize(SIZE_STEPS[k])(state, dispatch);
    };
  }
  /* Bold, italic, underline, strikethrough, small caps on and off: off when some of the selection has the mark (as
     current() shows it pressed), else on, the spaces at the selection's edges left out (as prosemirror's toggleMark);
     on the notes it holds, never on a note's own text. With a cursor, for what is typed next. */
  function toggle(name) {
    return (state, dispatch) => {
      if (!MARKS.includes(name) || !marksApply(state)) return false;
      if (!dispatch) return true;
      const type = M[name], sel = state.selection, tr = state.tr, off = marksHeld(state).has(type);
      if (sel.empty) {
        dispatch(off ? tr.removeStoredMark(type) : tr.addStoredMark(type.create()));
        return true;
      }
      // going on, the spaces at the selection's edges stay plain when that leaves something
      const edges = off ? spans(state) : sel.ranges.map(({$from, $to}) => {
        const start = $from.nodeAfter, end = $to.nodeBefore;
        const lead = start && start.isText ? /^\s*/.exec(start.text)[0].length : 0;
        const trail = end && end.isText ? /\s*$/.exec(end.text)[0].length : 0;
        return $from.pos + lead < $to.pos ? [$from.pos + lead, $to.pos - trail] : [$from.pos, $to.pos];
      });
      const {ranges, notes} = pieces(state.doc, edges);
      for (const [a, b] of ranges) { if (off) tr.removeMark(a, b, type); else tr.addMark(a, b, type.create()); }
      for (const pos of notes) { if (off) tr.removeNodeMark(pos, type); else tr.addNodeMark(pos, type.create()); }
      if (tr.docChanged) dispatch(tr.scrollIntoView());
      return true;
    };
  }
  /* Bold, italic, underline, strikethrough, small caps and size off the selection, and the paragraphs it touches back to
     the book's alignment; with a cursor, off what is typed next. Index terms, comments, languages, notes and sources stay,
     and so do headings, lists and quotations (spec, "Clear formatting"). */
  function clearFormatting(state, dispatch) {
    if (!marksApply(state)) return false;
    if (dispatch) {
      const tr = state.tr, sel = state.selection;
      if (sel.empty) {
        for (const name of CLEARED) tr.removeStoredMark(M[name]);
        dispatch(tr);
        return true;
      }
      const {ranges, notes} = pieces(state.doc, spans(state));
      for (const name of CLEARED) {
        for (const [a, b] of ranges) tr.removeMark(a, b, M[name]);
        for (const pos of notes) tr.removeNodeMark(pos, M[name]);
      }
      if (prose(state)) liftOut(tr, sel.from, sel.to, n => n.type === N.aligned);
      if (tr.docChanged) dispatch(tr.scrollIntoView());
    }
    return true;
  }

  /* ——— Make a list of these lines: paragraphs that start with a typed marker, as earlier imports and v1.2 wrote them ——— */
  const MARKER = /^(?:([•-])|(\d{1,9})[.)]|([a-z]+|[A-Z]+)[.)]) +/;
  /* `xiv` -> 14, either case; null when it isn't a roman numeral as toRoman writes it */
  function fromRoman(s) {
    const t = s.toLowerCase();
    let n = 0, i = 0;
    for (const [value, digits] of NUMERALS) while (t.startsWith(digits, i)) { n += value; i += digits.length; }
    return i === t.length && n > 0 && toRoman(n) === t ? n : null;
  }
  /* The list a paragraph's leading `text` makes, after an item of style `prev` (or none): [list, start, marker length],
     or null. As Pandoc reads them: within a list a marker is read in that list's style (`i.` after `h.` is a letter);
     else a lone `i` or `I` is roman, another lone letter a letter, and several letters roman when they are a numeral. */
  function typedMarker(text, prev) {
    const m = MARKER.exec(text);
    if (!m) return null;
    if (m[1]) return ["bullet", null, m[0].length];
    if (m[2]) return ["decimal", +m[2], m[0].length];
    const w = m[3], upper = w !== w.toLowerCase(), alpha = upper ? "upper-alpha" : "lower-alpha", roman = upper ? "upper-roman" : "lower-roman";
    const letter = w.length === 1 ? w.toLowerCase().charCodeAt(0) - 96 : null, numeral = fromRoman(w);
    const list = prev === alpha && letter ? alpha : prev === roman && numeral ? roman
      : letter && w.toLowerCase() !== "i" ? alpha : numeral ? roman : null;
    return list && [list, list === alpha ? letter : numeral, m[0].length];
  }
  const leadingText = node => { let s = ""; for (let i = 0; i < node.childCount && node.child(i).isText; i++) s += node.child(i).text; return s; };
  /* Every selected top-level paragraph that starts with a typed marker (`•`, `-`, `1.`, `1)`, `a.`, `A.`, `i.`, `I.` …
     and a space) becomes an item of that style at level 0, starting at the marker's number, the marker gone; the rest
     stay as they are. False when none does, and in a poem piece. */
  function listFromMarkers(state, dispatch) {
    if (!prose(state)) return false;
    const blocks = topsIn(state.doc, state.selection.from, state.selection.to), found = [];
    const above = blocks.length && blocks[0].index > 0 ? state.doc.child(blocks[0].index - 1) : null;
    let prev = above && above.type === N.list_item ? above.attrs.list : null;
    for (const {node, pos} of blocks) {
      const m = node.type === N.paragraph ? typedMarker(leadingText(node), prev) : null;
      if (m) found.push({pos, list: m[0], start: m[1], length: m[2]});
      prev = m ? m[0] : node.type === N.list_item ? node.attrs.list : null;
    }
    if (!found.length) return false;
    if (dispatch) {
      const tr = state.tr;
      for (const {pos, list, start, length} of found.reverse()) {
        tr.delete(pos + 1, pos + 1 + length).setNodeMarkup(pos, N.list_item, {list, level: 0, start: validStart(list, start)});
      }
      dispatch(canonical(tr).scrollIntoView());
    }
    return true;
  }

  /* ——— what is on and what applies where the cursor is (the format panel) ——— */
  /* the one value of `values`; "mixed" when they differ; null when there are none */
  const one = values => (!values.length ? null : values.every(v => v === values[0]) ? values[0] : "mixed");
  /* {text: "paragraph" | "heading" | "subheading" | "quotation" | null (none: the title, an epigraph, a poem, a note),
      list: a list style | null, align: "center" | "right" | null (as the book), size: a size | null (Normal),
      marks: {strong, em, underline, strike, smallcaps}, table: BookTable.current (the cell's table) | null}: each "mixed"
     when the selection holds more than one. Marks: true when some of the selection has them (as the toggles take them off
     then), or what is typed next. */
  function current(state) {
    const sel = state.selection, texts = [], lists = [], aligns = [];
    if (state.doc.type === N.doc) {
      state.doc.nodesBetween(sel.from, sel.to, (node, pos, parent) => {
        if (!node.isTextblock) return true;
        const plain = node.type === N.list_item || (node.type === N.paragraph && (parent.type === N.doc || parent.type === N.aligned));
        texts.push(isQuote(parent) ? "quotation" : node.type === N.heading ? (node.attrs.level === 3 ? "subheading" : "heading")
          : plain ? "paragraph" : null);
        lists.push(node.type === N.list_item ? node.attrs.list : null);
        aligns.push(parent.type === N.aligned ? parent.attrs.align : null);
        return false;
      });
    }
    const held = marksHeld(state), sizes = new Set();
    if (sel.empty) sizes.add(sizeOf(state.storedMarks || sel.$from.marks()));
    else eachCarrier(state, node => { sizes.add(sizeOf(node.marks)); });
    const size = sizes.size ? one([...sizes]) : sizeOf(sel.$from.marks());
    return {text: one(texts), list: one(lists), align: one(aligns), size, marks: Object.fromEntries(MARKS.map(name => [name, held.has(M[name])])),
      table: root.BookTable ? root.BookTable.current(state) : null};
  }
  /* {text, list, align, size, style, table}: which rows of the format panel apply. In a note's text (its own editor, whose
     document is the note), the title, an epigraph or a `::: poem` only size and style; no list or alignment in a poem
     piece; alignment only where every selected block is a top-level paragraph (or an aligned one). In a table's cell
     size, style and the table's own commands (book-table.js): a table stops the text styles, lists and alignment. */
  function applies(state) {
    const style = marksApply(state);
    if (state.doc.type !== N.doc) return {text: false, list: false, align: false, size: style, style, table: false};
    return {text: !!styleable(state), list: setList("bullet")(state), align: alignable(state), size: style, style,
      table: !!root.BookTable && root.BookTable.inTable(state)};
  }

  /* ——— keys ——— */
  const MAC = typeof navigator !== "undefined" && /Mac|iP(hone|[oa]d)/.test(navigator.platform || "");
  const toPanel = T => { root.BookFormat.openPanel?.(T); return true; };       // the format panel, BookFormat.openPanel, once loaded
  /* a command on the view the author is writing in, a note's or the text's; nothing while the piece is locked */
  const onView = cmd => T => {
    if (T.locked) return;
    const view = (T.activeView && T.activeView()) || T.view;
    cmd(view.state, tr => view.dispatch(tr), view);
  };
  const row = (id, label, key, group, cmd) => ({id, label, key, group, run: onView(cmd)});
  /* One row per command, in the palette's order: its key as the spec's table writes it (null: none), its group. The
     groups "Text", "List", "Align", "Size" and "Style" are the format panel's rows, and the panel builds its rows from
     those five; a sixth, "Format", holds only the row of the panel itself (Format…, Alt+O), for the palette and the keys
     sheet. Indent's key, Ctrl+], also puts paragraphs outside a list into a quotation (keymap). */
  const KEYS = [
    row("paragraph", "Paragraph", "Ctrl+Alt+0", "Text", setTextStyle("paragraph")),
    row("heading", "Heading", "Ctrl+Alt+2", "Text", setTextStyle("heading")),
    row("subheading", "Subheading", "Ctrl+Alt+3", "Text", setTextStyle("subheading")),
    row("quotation", "Quotation", null, "Text", setTextStyle("quotation")),
    row("bullet", "Bulleted list", "Ctrl+Shift+8", "List", setList("bullet")),
    row("decimal", "Numbered list", "Ctrl+Shift+7", "List", setList("decimal")),
    row("lower-alpha", "Lettered list", null, "List", setList("lower-alpha")),
    row("upper-alpha", "Lettered list (capitals)", null, "List", setList("upper-alpha")),
    row("upper-roman", "Roman list", null, "List", setList("upper-roman")),
    row("lower-roman", "Roman list (small)", null, "List", setList("lower-roman")),
    row("indent", "Indent", "Ctrl+]", "List", indent(1)),
    row("outdent", "Outdent", "Ctrl+[", "List", indent(-1)),
    row("from-markers", "Make a list of these lines", null, "List", listFromMarkers),
    row("align-book", "Align as the book", "Ctrl+Shift+L", "Align", setAlign(null)),
    row("align-center", "Centre", "Ctrl+Shift+E", "Align", setAlign("center")),
    row("align-right", "Right", "Ctrl+Shift+R", "Align", setAlign("right")),
    row("larger", "Larger", "Ctrl+Shift+.", "Size", stepSize(1)),
    row("smaller", "Smaller", "Ctrl+Shift+,", "Size", stepSize(-1)),
    row("size-normal", "Normal size", null, "Size", setSize(null)),
    row("strong", "Bold", "Ctrl+B", "Style", toggle("strong")),
    row("em", "Italic", "Ctrl+I", "Style", toggle("em")),
    row("underline", "Underline", "Ctrl+U", "Style", toggle("underline")),
    row("strike", "Strikethrough", "Alt+Shift+5", "Style", toggle("strike")),
    row("smallcaps", "Small caps", "Ctrl+Shift+K", "Style", toggle("smallcaps")),
    row("clear", "Clear formatting", "Ctrl+Space", "Style", clearFormatting),
    {id: "format", label: "Format…", key: "Alt+O", group: "Format", run: T => { if (!T.locked) toPanel(T); }},
  ];
  /* The keys for book-text.js's keymap. Every one keeps the key where its command doesn't apply (Ctrl+Shift+R never
     reloads the window), and does nothing while the piece is locked. Tab, Enter and Backspace stay book-text's: a poem
     line's Tab comes first. On a keyboard where Ctrl+Alt+digit types a character, the character wins (ProseMirror). */
  function keymap(T) {
    const key = cmd => (state, dispatch, view) => { if (!T.locked) cmd(state, dispatch, view); return true; };
    const deeper = dir => (state, dispatch) => (inList(state) ? indent(dir) : quote(dir))(state, dispatch);
    return {
      "Mod-b": key(toggle("strong")), "Mod-i": key(toggle("em")), "Mod-u": key(toggle("underline")),
      "Alt-Shift-5": key(toggle("strike")), "Mod-Shift-k": key(toggle("smallcaps")),
      // Ctrl+Shift+. comes as `>` on most layouts: both names
      "Mod-Shift-.": key(stepSize(1)), "Mod->": key(stepSize(1)), "Mod-Shift-,": key(stepSize(-1)), "Mod-<": key(stepSize(-1)),
      "Mod-Space": key(clearFormatting),
      "Mod-Alt-0": key(setTextStyle("paragraph")), "Mod-Alt-2": key(setTextStyle("heading")), "Mod-Alt-3": key(setTextStyle("subheading")),
      "Mod-Shift-8": key(setList("bullet")), "Mod-Shift-7": key(setList("decimal")),
      "Mod-]": key(deeper(1)), "Mod-[": key(deeper(-1)),
      "Mod-Shift-l": key(setAlign(null)), "Mod-Shift-e": key(setAlign("center")), "Mod-Shift-r": key(setAlign("right")),
      // ⌃⌥O on macOS, where ⌥O types ø
      [MAC ? "Ctrl-Alt-o" : "Alt-o"]: key(() => toPanel(T)),
    };
  }

  /* ——— the markers in the text: each item hangs its marker in a gutter (book-format.css) ——— */
  /* A marker's width in em as the default face (Source Serif) sets it, a little wide: what the gutter takes in node and
     until the marker is measured in the text's own face. */
  const GLYPH = {".": .3, I: .4, J: .45, M: .95, W: .95, i: .3, j: .3, l: .3, f: .4, r: .42, t: .4, m: .85, w: .85};
  const markerWidth = s => [...s].reduce((w, c) => w + (GLYPH[c] ?? (/[0-9a-z]/.test(c) ? .56 : /[A-Z]/.test(c) ? .75 : .6)), 0);
  const GAP = .5;         // em between a marker's gutter and its text: book-format.css's --bk-gap
  const em = x => Math.round(x * 100) / 100 + "em";
  /* Per list item what its node decoration says (`[pos, end, attrs]`): `data-marker`, the marker it shows; `--bk-mw`, its
     gutter: as wide as the widest marker of its list (`width`, in em; a list counted on from an earlier one is that list),
     at least 1em, so `9.` and `10.` and `VIII.` line up on their full stops and every item of a list has one text edge;
     `--bk-in`, its indent: a sublist starts at its parent item's text edge (its indent, gutter and GAP), so its markers
     never stand left of the parent's text; the class `bk-li-apart` on the first item of a list right after another
     list's item at level 0, set apart by the space between paragraphs. */
  function markerAttrs(doc, width = markerWidth) {
    const ms = markers(doc), out = [];
    if (!ms.some(Boolean)) return out;
    const chain = chains(ms), widest = new Map();
    for (const m of ms) if (m) { const k = chain.get(m.run); widest.set(k, Math.max(widest.get(k) || 1, width(m.marker))); }
    let edges = [];           // per level: the text edge of the item last seen there
    doc.forEach((node, pos, k) => {
      const m = ms[k];
      if (!m) { edges = []; return; }
      const mw = Math.ceil(widest.get(chain.get(m.run)) * 20 - 1e-6) / 20;      // in twentieths of an em
      const indent = m.level ? edges[m.level - 1] || 0 : 0;
      edges.length = m.level;
      edges.push(indent + mw + GAP);
      const attrs = {"data-marker": m.marker, style: `--bk-mw:${em(mw)};--bk-in:${em(indent)}`};
      if (m.first && !m.level && k > 0 && ms[k - 1]) attrs.class = "bk-li-apart";
      out.push([pos, pos + node.nodeSize, attrs]);
    });
    return out;
  }
  const decorate = (doc, items) => DecorationSet.create(doc, items.map(([from, to, attrs]) => Decoration.node(from, to, attrs)));
  /* the decorations of `items` from the old `set` mapped through `tr`, when they are the same ones where they should be;
     else null */
  function mapped(set, tr, items) {
    const next = set.map(tr.mapping, tr.doc), found = next.find().sort((a, b) => a.from - b.from);
    if (found.length !== items.length) return null;
    for (let k = 0; k < items.length; k++) {
      const d = found[k], [from, to, attrs] = items[k], was = d.type.attrs;
      if (d.from !== from || d.to !== to || was["data-marker"] !== attrs["data-marker"] || was.style !== attrs.style || was.class !== attrs.class) return null;
    }
    return next;
  }
  /* Markers measured in the text's own face (the book's look sets it): a hidden probe beside the text, set as the marker
     is (book-format.css), once per marker and face. */
  class MarkerMeasure {
    constructor(view) { Object.assign(this, {view, font: "", cache: new Map()}); }
    /* true when the text's face changed since it was last read (and so every marker is measured again) */
    changed() {
      if (!this.view.dom.isConnected) return false;
      const cs = getComputedStyle(this.view.dom), font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      if (font === this.font) return false;
      this.font = font;
      this.cache.clear();
      return true;
    }
    width(s) {
      let w = this.cache.get(s);
      if (w == null) {
        const probe = document.createElement("span");         // beside the editable text, where ProseMirror doesn't look
        probe.style.cssText = "position:absolute;left:0;top:0;visibility:hidden;white-space:nowrap;font-style:normal;" +
          "font-variant-numeric:lining-nums tabular-nums;font-variant-ligatures:none;font-feature-settings:'liga' 0";
        probe.textContent = s;
        this.view.dom.parentNode.append(probe);
        w = probe.getBoundingClientRect().width / (parseFloat(getComputedStyle(probe).fontSize) || 16);
        probe.remove();
        if (!w) return markerWidth(s);        // a text not shown just now (a hidden pane): measured another time
        w += .02;                             // a hair to spare: a marker never overflows its gutter
        this.cache.set(s, w);
      }
      return w;
    }
  }
  const markersKey = new PluginKey("bk-markers");
  /* The markers' decorations: mapped through a change while every item keeps its marker, gutter, indent and place (typing
     in an item), made anew when one changes. Once the text is on the page its gutters are measured in its face, again
     when the face changes: the book's look (a style on the page), a font finishing loading. */
  function markersPlugin() {
    let measure = null;
    const width = s => (measure ? measure.width(s) : markerWidth(s));
    return new Plugin({
      key: markersKey,
      state: {
        init: (config, state) => decorate(state.doc, markerAttrs(state.doc, width)),
        apply(tr, set, old, state) {
          if (!tr.docChanged && !tr.getMeta(markersKey)) return set;
          const items = markerAttrs(state.doc, width);
          if (!items.length) return DecorationSet.empty;
          return (!tr.getMeta(markersKey) && mapped(set, tr, items)) || decorate(state.doc, items);
        },
      },
      props: {decorations: state => markersKey.getState(state)},
      view(view) {
        if (typeof document === "undefined" || typeof requestAnimationFrame !== "function") return {};
        const m = new MarkerMeasure(view);
        let frame = 0;
        const check = () => {
          frame = frame || requestAnimationFrame(() => {
            frame = 0;
            if (!m.changed()) return;
            measure = m;
            if (markers(view.state.doc).some(Boolean)) view.dispatch(view.state.tr.setMeta(markersKey, true));
          });
        };
        const loaded = () => { m.font = ""; check(); };
        document.fonts?.addEventListener("loadingdone", loaded);
        // the look sets the text's face on the page (book-editor.js, look): its style changes
        const page = view.dom.closest?.(".bw-page"), looked = page && typeof MutationObserver === "function" ? new MutationObserver(check) : null;
        looked?.observe(page, {attributes: true, attributeFilter: ["style"]});
        check();
        return {
          update: (v, prev) => { if (v.state.doc !== prev.doc) check(); },
          destroy: () => { cancelAnimationFrame(frame); document.fonts?.removeEventListener("loadingdone", loaded); looked?.disconnect(); },
        };
      },
    });
  }
  /* The plugins of the writing window's text (book-text.js): the markers, and the numbers plugin. */
  const plugins = T => [markersPlugin(), numbersPlugin()];

  /* ——— the clipboard's plain text ——— */
  /* A slice without the empty list items at its open ends, which a copy brings along when it only touches a neighbouring
     item (to its start, from its end): {content, openStart, openEnd, first: 1 when one went at the start}. As it is when
     nothing else would be left. */
  function trimmed(slice) {
    let c = slice.content, {openStart, openEnd} = slice, first = 0;
    const bare = n => n.type === N.list_item && !n.content.size;
    const end = openEnd > 0 && bare(c.lastChild), start = openStart > 0 && bare(c.firstChild);
    if (c.childCount - end - start < 1) return {content: c, openStart, openEnd, first};
    if (end) { c = c.cut(0, c.size - c.lastChild.nodeSize); openEnd = 0; }
    if (start) { c = c.cut(c.firstChild.nodeSize); openStart = 0; first = 1; }
    return {content: c, openStart, openEnd, first};
  }
  /* a leaf's text: math as its source, between dollars as the dialect writes it */
  const leafText = n => (n.type.spec.leafText ? n.type.spec.leafText(n) : n.type.name === "math" ? `$${n.attrs.tex}$`
    : n.type.name === "math_display" ? `$$${n.attrs.tex}$$` : "");
  /* a text block's text: its line breaks as new lines; notes and citations left out */
  const lineText = node => { let s = ""; node.forEach(c => { s += c.isText ? c.text : c.type === N.hard_break ? "\n" : c.isLeaf ? leafText(c) : ""; }); return s; };
  /* a block that isn't a list item as plain text, one string per block in it */
  function plainBlocks(node) {
    if (node.type === N.scene_break) return ["* * *"];
    if (node.type === N.table) { const rows = []; node.forEach(row => { const cells = []; row.forEach(c => cells.push(lineText(c))); rows.push(cells.join("\t")); }); return [rows.join("\n")]; }
    if (node.isTextblock) return [(node.type === N.attribution ? "— " : "") + lineText(node)];
    if (node.isLeaf) { const t = leafText(node); return t ? [t] : []; }
    const out = [];
    node.forEach(c => out.push(...plainBlocks(c)));
    return out;
  }
  /* The plain text of a slice (book-text.js's clipboardTextSerializer), so that a list pasted into an email keeps its
     numbers: blocks on lines with a blank line between them; a list's items on lines of their own, each led by its marker
     after two spaces per level, a line break in an item going on under its text; a poem's lines; a scene break `* * *`;
     a table's rows, cells between tabs. Given `state`, whose selection the slice is, the markers are the numbers the text
     shows, else they are counted in the slice. An item the copy starts inside of shows no marker (unless the copy starts
     at its start and goes on past it): copied from inside one block, the text is only its words. */
  function clipboardText(slice, state = null) {
    const ours = !!state && slice.eq(state.selection.content()), {content, openStart, openEnd, first} = trimmed(slice);
    const all = ours ? markers(state.doc) : markers(content), at = ours ? state.selection.$from.index(0) + first : 0;
    const firstWhole = !openStart || (ours && content.childCount > 1 && state.selection.$from.parentOffset === 0);
    const blocks = [];
    let inList = false;
    content.forEach((node, _, k) => {
      const m = node.type === N.list_item ? all[at + k] : null;
      if (!m) { inList = false; blocks.push(...plainBlocks(node)); return; }
      const bare = (k === 0 && !firstWhole) || (k === content.childCount - 1 && openEnd > 0 && !node.content.size);   // an empty end: no marker
      const lead = bare ? "" : "  ".repeat(m.level) + m.marker + " ";
      const line = lead + lineText(node).replace(/\n/g, "\n" + " ".repeat(lead.length));
      if (inList && !(m.first && !m.level)) blocks[blocks.length - 1] += "\n" + line;     // another list: a blank line between
      else blocks.push(line);
      inList = true;
    });
    return blocks.join("\n\n");
  }

  /* ——— paste ——— */
  /* Pasted into a poem line (book-text.js's poemPasted): list items become paragraphs led by their marker, after two
     no-break spaces per level; the first item, when the slice is open at its start (copied from its middle), keeps its
     text alone. */
  function itemsAsLines(fragment, openStart = 0) {
    const ms = markers(fragment), out = [];
    fragment.forEach((node, _, k) => {
      if (node.type !== N.list_item) { out.push(node); return; }
      const lead = k === 0 && openStart > 0 ? "" : "\u00A0\u00A0".repeat(ms[k].level) + ms[k].marker + " ", kids = [];
      node.forEach(c => kids.push(c));
      out.push(N.paragraph.create(null, lead ? [S.text(lead), ...kids] : kids));
    });
    return Fragment.from(out);
  }
  const CSS_LISTS = {decimal: "decimal", "decimal-leading-zero": "decimal", "lower-alpha": "lower-alpha", "lower-latin": "lower-alpha",
    "upper-alpha": "upper-alpha", "upper-latin": "upper-alpha", "lower-roman": "lower-roman", "upper-roman": "upper-roman",
    disc: "bullet", circle: "bullet", square: "bullet"};
  const TYPES = {1: "decimal", a: "lower-alpha", A: "upper-alpha", i: "lower-roman", I: "upper-roman"};
  /* The style of a pasted HTML list item: its `list-style-type` (`css`), else the list's `type`, else numbers for an `ol`
     and bullets for a `ul`. */
  function listStyleOf(css, type, ordered) {
    return CSS_LISTS[String(css || "").trim().toLowerCase()] || TYPES[String(type || "").trim()] || (ordered ? "decimal" : "bullet");
  }
  /* [style, number] from the marker text Word writes before a list paragraph (`1.`, `3)`, `(b)`, `iv.`, `·`, `o`, `§`),
     read as typed markers are, after an item of style `prev` at that level (`i.` after `h.` is a letter); number null
     where none shows (bullets, Word's `1.2.`). */
  function wordMarker(text, prev = null) {
    const t = String(text || "").trim().replace(/^\((?=.+\)$)/, "");
    if (/^\d{1,9}(\.\d{1,9})+\.?$/.test(t)) return ["decimal", null];
    if (!/^(\d{1,9}|[a-z]+|[A-Z]+)[.)]$/.test(t)) return ["bullet", null];
    const m = typedMarker(t + " ", prev);
    return m ? [m[0], m[1]] : [/[A-Z]/.test(t) ? "upper-alpha" : "lower-alpha", null];
  }
  /* an element made one of the editor's own flat items, as the schema reads them (book-schema.js, list_item) */
  function asItem(el, list, level, start) {
    el.className = "bk-li";
    el.setAttribute("data-list", list);
    el.setAttribute("data-level", String(Math.min(Math.max(level, 0), MAX_LEVEL)));
    const s = validStart(list, start);
    if (s != null && s !== 1) el.setAttribute("data-start", String(s)); else el.removeAttribute("data-start");
    return el;
  }
  /* Word's list paragraphs (`mso-list: lN levelM`): items at level M - 1, their style and number from the marker Word
     wrote before the text (a `mso-list: Ignore` span), which goes. Every item gets its number as its start: the numbers
     plugin keeps it only where a list starts. Not in table cells. */
  function wordItems(d) {
    const prev = [];          // per level: the style of the item before, for reading the next marker
    for (const p of d.querySelectorAll("p[style]")) {
      const m = /mso-list\s*:\s*l\d+\s+level(\d+)/i.exec(p.getAttribute("style"));
      if (!m || p.closest("td, th")) continue;
      const level = Math.min(Math.max(+m[1] - 1, 0), MAX_LEVEL);
      let text = null;
      for (const s of p.querySelectorAll("[style]")) {
        if (s.isConnected && /mso-list\s*:\s*ignore/i.test(s.getAttribute("style"))) { if (text == null) text = s.textContent; s.remove(); }
      }
      const [list, n] = wordMarker(text, prev[level]);
      prev.length = level;     // deeper lists end here
      prev[level] = list;
      asItem(p, list, level, n);
    }
  }
  const LIST_TAGS = /^(UL|OL)$/, PARA_TAGS = /^(P|DIV|H[1-6])$/, BLOCK_TAGS = /^(P|DIV|H[1-6]|BLOCKQUOTE|PRE|TABLE|FIGURE|SECTION|ARTICLE|HR)$/;
  /* An HTML list as the editor's flat items, in order: an item's level is its nesting (`depth`) or Docs' `aria-level`; its
     text up to its first paragraph, or that paragraph's text, is the item; more blocks in it come after it, and its
     nested lists. */
  function flatList(d, list, depth) {
    const out = [], ordered = list.nodeName === "OL";
    let first = true;
    for (const li of [...list.children]) {
      if (LIST_TAGS.test(li.nodeName)) { out.push(...flatList(d, li, depth + 1)); continue; }    // a list right in a list
      if (li.nodeName !== "LI") { out.push(li); continue; }
      const aria = parseInt(li.getAttribute("aria-level"), 10);
      const style = listStyleOf(li.style.listStyleType || list.style.listStyleType, li.getAttribute("type") || list.getAttribute("type"), ordered);
      const item = asItem(d.createElement("p"), style, aria > 0 ? aria - 1 : depth, first && ordered ? parseInt(list.getAttribute("start"), 10) : null);
      const after = [];
      let filled = false, loose = null, div;
      // a div around an item's blocks (`<li><div><p>…</p></div></li>`) is no block of its own
      const wrapper = () => [...li.children].find(e => e.nodeName === "DIV" && [...e.children].some(c => BLOCK_TAGS.test(c.nodeName) || LIST_TAGS.test(c.nodeName)));
      while ((div = wrapper())) div.replaceWith(...div.childNodes);
      for (const c of [...li.childNodes]) {
        if (c.nodeType === 1 && LIST_TAGS.test(c.nodeName)) { after.push(...flatList(d, c, depth + 1)); loose = null; }
        else if (c.nodeType === 1 && BLOCK_TAGS.test(c.nodeName)) {
          if (!filled && PARA_TAGS.test(c.nodeName) && !/\S/.test(item.textContent)) item.append(...c.childNodes);
          else { after.push(c); loose = null; }
          filled = true;
        } else if (!filled) item.append(c);
        else if (c.nodeType === 1 || (c.nodeType === 3 && /\S/.test(c.data))) {      // text after a block: a paragraph of its own
          if (!loose) after.push(loose = d.createElement("p"));
          loose.append(c);
        }
      }
      first = false;
      out.push(item, ...after);
    }
    return out;
  }
  /* a link's underline off, on the link and inside it (the link itself isn't kept, so it would read as underlined text);
     strikethrough stays */
  function unlink(a) {
    for (const e of [a, ...a.querySelectorAll("*")]) {
      if (e.nodeName === "U") { e.replaceWith(...e.childNodes); continue; }
      for (const prop of ["text-decoration", "text-decoration-line"]) {
        const v = e.style.getPropertyValue(prop);
        if (!/underline/i.test(v)) continue;
        e.style.removeProperty(prop);
        if (/line-through/i.test(v)) e.style.setProperty("text-decoration-line", "line-through");
      }
    }
  }
  let itemsPasted = false;        // pasteLists made list items of the HTML being pasted right now
  /* HTML pasted from outside, before the schema reads it (book-text.js's cleanPaste runs this first): lists, nested or
     with Docs' `aria-level`, and Word's list paragraphs become the editor's own flat items, `<p class="bk-li" data-list
     data-level data-start>`; links lose their underline. Lists in table cells stay as they are. Without the browser's
     DOMParser the HTML is left as it is. */
  function pasteLists(html) {
    if (typeof root.DOMParser !== "function") return html;
    const d = new root.DOMParser().parseFromString(html, "text/html"), had = d.querySelectorAll("p.bk-li").length;
    wordItems(d);
    for (const list of [...d.querySelectorAll("ul, ol")]) {
      if (list.isConnected && !list.parentElement.closest("ul, ol, td, th")) list.replaceWith(...flatList(d, list, 0));
    }
    d.querySelectorAll("a").forEach(unlink);
    if (d.querySelectorAll("p.bk-li").length > had) {
      itemsPasted = true;
      Promise.resolve().then(() => { itemsPasted = false; });      // the paste is over by then (ProseMirror reads it at once)
    }
    return d.body.innerHTML;
  }
  /* A slice about to be pasted or dropped (book-text.js's transformPasted). ProseMirror opens a slice at its ends, so its
     first and last blocks run into the line at the cursor, and an item there would lose its list: so an item at either
     end of a list pasted from outside (pasteLists made it), or of a copy of more than one block, comes in whole, as an
     item; an empty item the copy only touched at an end stays behind (trimmed). Words copied from inside one item still
     run into the line, and a copy of nothing but a line's end and the next line's start is a line break. */
  function pastedLists(slice) {
    const outside = itemsPasted;
    itemsPasted = false;
    if (!outside && slice.content.childCount < 2) return slice;
    const item = n => !!n && n.type === N.list_item;
    let words = false;
    slice.content.forEach(n => { words = words || !item(n) || n.content.size > 0; });
    if (!words) return slice;
    const {content: c, openStart, openEnd} = trimmed(slice);
    const start = item(c.firstChild) ? 0 : openStart, end = item(c.lastChild) ? 0 : openEnd;
    return c === slice.content && start === slice.openStart && end === slice.openEnd ? slice : new Slice(c, start, end);
  }

  root.BookFormat = {
    STYLES, MAX_LEVEL, NEST, SIZE_STEPS, markers, markerText, toAlpha, toRoman,
    commands: {setList, indent, listEnter, listBackspace, listTab, listShiftTab,
      setAlign, setTextStyle, quote, stepSize, setSize, toggle, clearFormatting, listFromMarkers},
    current, applies, KEYS, keymap, inputRules, numbersPlugin,
    plugins, clipboardText, itemsAsLines, pasteLists, pastedLists, listStyleOf, wordMarker,
  };
})(typeof window !== "undefined" ? window : globalThis);
