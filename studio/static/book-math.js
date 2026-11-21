"use strict";
/* LaTeX math in the writing window (book-text.js uses it): typing `$tex$` makes inline math as the dialect reads it,
   `$$` + Enter in an empty line and / Math put in display math, and the node views that show math rendered by KaTeX and
   open its source in a small field under it. A classic script after vendor/prosemirror.js, book-schema.js and
   vendor/katex/katex.min.js; sets window.BookMath. The typing rule, the commands and texError touch no DOM, so
   tests/js/book_math.js runs them in node. Spec: docs/superpowers/specs/2026-11-13-book-editor-power-design.md ("Math in
   detail", "Math in the writing window"). */
(function (root) {
  const S = root.BookSchema, N = S.nodes;
  const {TextSelection, NodeSelection, InputRule} = root.PM;
  const isMath = n => !!n && (n.type === N.math || n.type === N.math_display);

  /* ——— typing `$tex$`: the closing dollar makes the math ——— */
  // markdown-it's isWhiteSpace, which manuscript._math_rule uses
  const SPACE = /[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]/, DIGIT = /[0-9]/, LEAF = "\ufffc";
  /* Where the math closed by the last character of `text` opens, reading the line as the dialect does
     (manuscript._math_rule, left to right): the index of its opening `$`, or -1 when that last character is no `$` that
     closes math. An opening `$` has a non-space after it and isn't `$$`; the TeX runs to the first `$` (a backslash and
     the character after it are TeX, and so is a `\text{…}` group, dollars and all); the closing `$` has a non-space
     before it and no digit after it. A backslash before a `$` in the text escapes it; U+FFFC (a note, a citation, other
     math) is never inside math. What comes after the last character is not in `text`: the caller looks for a digit
     there. One thing more than the dialect's reading: a `$` typed inside a `\text{` group still open closes nothing (in
     `$x \text{ als $y$}$` the math is closed by the last dollar, as the finished line reads). */
  function mathStart(text) {
    const end = text.length - 1;
    if (end < 1 || text[end] !== "$") return -1;
    for (let i = 0; i < end; i++) {
      if (text[i] === "\\") { i++; continue; }
      if (text[i] !== "$" || text[i + 1] === "$" || SPACE.test(text[i + 1])) continue;
      let j = i + 1;
      while (j <= end && text[j] !== "$" && text[j] !== LEAF) {
        if (text[j] !== "\\") { j++; continue; }
        if (text[j + 1] === LEAF) { j++; break; }      // a note or citation is no character a backslash takes with it
        const g = textGroupEnd(text, j);
        if (g === OPEN) return -1;
        j = g == null ? j + 2 : g;
      }
      if (j > end || text[j] === LEAF || SPACE.test(text[j - 1]) || DIGIT.test(text[j + 1] || "")) continue;
      if (j === end) return i;
      i = j;           // math from i to j: the line goes on after it
    }
    return -1;
  }
  const OPEN = -1;
  /* Where a `\text{…}` group at `i` ends, just after its closing brace (manuscript._text_group_end): null when there is
     none at `i`, OPEN when its braces aren't closed in `text`. Inside it a backslash and the character after it count as
     one; a group with U+FFFC in it is none (math holds no notes or citations). */
  function textGroupEnd(text, i) {
    if (!text.startsWith("\\text{", i)) return null;
    let depth = 0;
    for (let k = i + 5; k < text.length;) {
      const c = text[k];
      if (c === LEAF || (c === "\\" && text[k + 1] === LEAF)) return null;
      if (c === "\\") { k += 2; continue; }
      depth += c === "{" ? 1 : c === "}" ? -1 : 0;
      k++;
      if (!depth) return k;
    }
    return OPEN;
  }
  /* The writing window's typing rules make typography of ' " -- --- ... as they are typed (book-text.js); in TeX they are
     what was typed: f’(x) is f'(x) again. */
  const TYPED = {"‘": "'", "’": "'", "‚": "'", "‹": "'", "›": "'", "“": "\"", "”": "\"", "„": "\"", "«": "\"", "»": "\"",
    "–": "--", "—": "---", "…": "..."};
  const asTyped = tex => String(tex).replace(/[‘’‚‹›“”„«»–—…]/g, c => TYPED[c]);
  /* the text of $pos's text block before it: other inline nodes as U+FFFC, a note without its own text */
  function textBefore($pos) {
    let s = "";
    $pos.parent.forEach((child, offset) => {
      if (offset < $pos.parentOffset) s += child.isText ? child.text.slice(0, $pos.parentOffset - offset) : LEAF;
    });
    return s;
  }
  /* `$tex$` -> inline math, wherever the text holds math (paragraphs, items, headings, the title, cells, notes, poem
     lines), when the closing `$` is typed: the math takes the marks of its opening `$`, the cursor goes after it, and
     one Backspace right after (undoInputRule) gives back the dollars. */
  function inputRules() {
    return [new InputRule(/\$$/, (state, m, start, end) => {
      const $from = state.doc.resolve(start), $to = state.doc.resolve(end);
      if (!$from.sameParent($to) || !$from.parent.inlineContent) return null;
      const before = textBefore($from) + "$", open = mathStart(before), next = $to.nodeAfter;
      if (open < 0 || (next && next.isText && DIGIT.test(next.text[0]))) return null;
      // mathStart never takes in a note or citation, so from there to here is text only; checked all the same, so that
      // nothing but that text is ever replaced
      const from = start - (before.length - 1 - open);
      if (from < $from.start() || state.doc.textBetween(from, start, null, LEAF) !== before.slice(open, -1)) return null;
      const $open = state.doc.resolve(from), marks = state.doc.nodeAt(from).marks;
      if (!$open.parent.canReplaceWith($open.index(), $open.index(), N.math, marks)) return null;
      const tr = state.tr.replaceWith(from, end, N.math.create({tex: asTyped(before.slice(open + 1, -1))}, null, marks));
      return tr.setSelection(TextSelection.create(tr.doc, from + 1));
    })];
  }

  /* ——— display math: `$$` + Enter, / Math ——— */
  /* Enter after `$$` in a top-level paragraph that holds nothing else: display math in its place with a new line after
     it, selected (the view opens its source). The dialect reads `$$` lines in prose and poem pieces alike. */
  function dollarsEnter(state, dispatch) {
    const $c = state.selection.$cursor;
    if (!$c || state.doc.type !== N.doc || $c.depth !== 1 || $c.parent.type !== N.paragraph) return false;
    const p = $c.parent;
    let text = true;
    p.forEach(c => { if (!c.isText) text = false; });
    if (!text || $c.parentOffset !== p.content.size || p.textContent.trim() !== "$$") return false;
    if (dispatch) {
      const pos = $c.before(1), tr = state.tr.replaceWith(pos, pos + p.nodeSize, [N.math_display.create({tex: ""}), N.paragraph.create()]);
      dispatch(tr.setSelection(NodeSelection.create(tr.doc, pos)).scrollIntoView());
    }
    return true;
  }
  /* / Math: display math at the cursor, placed as the / menu places a block (book-text.js insertBlock): in place of an
     empty paragraph, before or after a paragraph at its edges, between the two halves of a paragraph, or after the
     top-level block the cursor is in; a line to type on after it; the math selected (the view opens its source). */
  function insertDisplay(state, dispatch) {
    if (state.doc.type !== N.doc) return false;
    if (dispatch) {
      const {$from} = state.selection, tr = state.tr, node = N.math_display.create({tex: ""});
      let pos;
      if ($from.depth === 1 && $from.parent.type === N.paragraph) {
        const p = $from.parent;
        if (!p.content.size) { pos = $from.before(1); tr.replaceWith(pos, pos + p.nodeSize, node); }
        else if ($from.parentOffset === 0) { pos = $from.before(1); tr.insert(pos, node); }
        else if ($from.parentOffset === p.content.size) { pos = $from.after(1); tr.insert(pos, node); }
        else { tr.split($from.pos); pos = $from.pos + 1; tr.insert(pos, node); }
      } else if ($from.depth >= 1) { pos = $from.after(1); tr.insert(pos, node); }
      else { pos = $from.pos; tr.insert(pos, node); }
      const after = pos + node.nodeSize, next = tr.doc.resolve(after).nodeAfter;
      if (!next || !next.isTextblock) tr.insert(after, N.paragraph.create());
      dispatch(tr.setSelection(NodeSelection.create(tr.doc, pos)).scrollIntoView());
    }
    return true;
  }
  /* Where the cursor goes after display math at `pos` in tr.doc: the start of the line after it, a paragraph made there
     when none follows it (a table, more math, the piece's end). */
  function lineAfter(tr, pos) {
    const at = pos + tr.doc.nodeAt(pos).nodeSize, next = tr.doc.resolve(at).nodeAfter;
    if (!next || !next.isTextblock) tr.insert(at, N.paragraph.create());
    return at + 1;
  }
  /* Text typed on selected display math goes into the line after it (lineAfter), the cursor after the text, as text
     typed on a selected note or citation goes after it (book-text.js, which calls this): the transaction, or null when
     no display math is selected. */
  function typedAfter(state, text) {
    const sel = state.selection;
    if (!(sel instanceof NodeSelection) || sel.node.type !== N.math_display) return null;
    const tr = state.tr, at = lineAfter(tr, sel.from);
    tr.insertText(text, at);
    return tr.setSelection(TextSelection.create(tr.doc, at + text.length));
  }
  /* Enter, first in book-text's chain: on a selected math it opens the source; after `$$` in an empty line, display math
     with its source open. Nothing while the piece is locked. */
  function enter(T) {
    return (state, dispatch, view) => {
      if (T && T.locked) return false;
      const sel = state.selection;
      if (sel instanceof NodeSelection && isMath(sel.node)) {
        if (dispatch && view) openAt(view, sel.from);
        return true;
      }
      if (!dollarsEnter(state, dispatch)) return false;
      if (dispatch && view) openSelected(view);
      return true;
    };
  }

  /* ——— the source as the dialect writes it ——— */
  /* The TeX the source field writes into the math, as manuscript.py writes it, so the document is what a reload gives.
     Inline (`_inline_tex`): one line, no space at its ends, no lone backslash at its end, a bare `$` as `\$` outside
     `\text{…}` groups (an unclosed group's brace set apart: `\text {`); "" when nothing is left (the math goes). Display
     (`_display_lines`, then `_display_dollars`): no blank lines, no spaces at line ends, no indentation all lines share,
     nothing around it, a `$` next to another `$` as `\$`. */
  function sourceTex(value, display) {
    return display ? displayDollars(displayLines(String(value))) : inlineTex(String(value));
  }
  function inlineTex(tex) {
    let t = tex.replace(/\s*[\r\n]\s*/g, " ").trim();
    while ((t.length - t.replace(/\\+$/, "").length) % 2) t = t.slice(0, -1).trimEnd();
    let out = "";
    for (let i = 0; i < t.length;) {
      if (t[i] !== "\\") { out += t[i] === "$" ? "\\$" : t[i]; i++; continue; }
      const g = textGroupEnd(t, i);
      if (g === OPEN) { out += "\\text "; i += 5; continue; }
      const end = g == null ? i + 2 : g;
      out += t.slice(i, end);
      i = end;
    }
    return out;
  }
  function displayLines(tex) {
    const lines = tex.replace(/\r\n?/g, "\n").split("\n").map(l => l.trimEnd()).filter(l => l.trim());
    let margin = null;          // the indentation all lines share, as textwrap.dedent finds it
    for (const l of lines) {
      const ws = /^[ \t]*/.exec(l)[0];
      if (margin == null) margin = ws;
      else { let k = 0; while (k < margin.length && margin[k] === ws[k]) k++; margin = margin.slice(0, k); }
    }
    return lines.map(l => l.slice((margin || "").length)).join("\n").trim();
  }
  const displayDollars = tex => tex.replace(/(?<!\\)((?:\\\\)*)\$/g, (m, bs, at) => {
    const i = at + m.length - 1;
    return tex[i - 1] === "$" || tex[i + 1] === "$" ? bs + "\\$" : m;
  });

  /* ——— KaTeX ——— */
  const message = e => String((e && (e.rawMessage || e.message)) || e);
  /* KaTeX's options. Nothing is ever trusted: \href, \url, \includegraphics and the \html… commands are refused (the
     function always says no, and keeps the commands it refused in `refused`); strict "ignore", so Unicode in math (é, ∑)
     doesn't fill the console; throwOnError, so what KaTeX can't render shows as an error with its message. */
  function katexOptions(display, refused) {
    return {displayMode: !!display, throwOnError: true, strict: "ignore", errorColor: "var(--red)",
      trust: context => { refused.push(context.command); return false; }};
  }
  const untrusted = command => `${command} isn't allowed here: math has no links, pictures or HTML`;
  /* KaTeX's message when it can't render `tex`, or a refused command's; else null (also when KaTeX isn't loaded:
     nothing to say then). */
  function texError(tex, display = false) {
    if (!root.katex) return null;
    const refused = [];
    try { root.katex.renderToString(String(tex), katexOptions(display, refused)); }
    catch (e) { return message(e); }
    return refused.length ? untrusted(refused[0]) : null;
  }

  /* ——— the node views: the rendering, and the source field under it ——— */
  const MAC = typeof navigator !== "undefined" && /Mac|iP(hone|[oa]d)/.test(navigator.platform || "");
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const views = new WeakMap();                   // a math's DOM -> its MathView
  const opened = new WeakMap();                  // a Text -> the MathViews whose source is open
  const openIn = T => { let s = opened.get(T); if (!s) opened.set(T, s = new Set()); return s; };
  function openAt(view, pos) { const dom = view.nodeDOM(pos), mv = dom && views.get(dom); if (mv) mv.open(); }
  /* the math the view's selection holds, its source opened */
  function openSelected(view) { const sel = view.state.selection; if (sel instanceof NodeSelection && isMath(sel.node)) openAt(view, sel.from); }
  /* Where a click in the view put the cursor (or the selection a drag made), mapped through `tr`: the view reads it from
     the page only after the click, so a change dispatched before that would put back the selection it had. Null when
     the click was not in the view. */
  function clicked(view, tr) {
    const s = view.hasFocus() && view.root.getSelection();
    if (!s || !s.anchorNode || !view.dom.contains(s.anchorNode) || !view.dom.contains(s.focusNode)) return null;
    try {
      const at = (node, offset) => tr.doc.resolve(tr.mapping.map(view.posAtDOM(node, offset)));
      return TextSelection.between(at(s.anchorNode, s.anchorOffset), at(s.focusNode, s.focusOffset));
    } catch (e) { return null; }
  }
  /* KaTeX's rendering of `tex` in `out`; what it can't render, or holds a refused command, is its source in Studio's red
     with the message as its title, as KaTeX shows a parse error (with throwOnError false KaTeX would show an unknown
     command in red in place and render the rest, without a message). Returns the message, or null. */
  function renderTex(tex, out, display) {
    const refused = [], shown = (title, msg) => {
      const s = el("span", "katex-error", tex);        // textContent: the source is never read as HTML
      s.title = title;
      s.style.color = "var(--red)";
      out.replaceChildren(s);
      return msg;
    };
    try { root.katex.render(tex, out, katexOptions(display, refused)); }
    catch (e) { return shown(String(e), message(e)); }          // KaTeX's own title: "ParseError: KaTeX parse error: …"
    return refused.length ? shown(untrusted(refused[0]), untrusted(refused[0])) : null;
  }

  /* Inline math (a span in the line) or display math (a block): KaTeX's rendering, `spellcheck=false`. What KaTeX can't
     render shows its source in Studio's red with KaTeX's message as its title. A click on it, or Enter when it is
     selected, opens its source in a field under it (display math: in the block, under the rendering; inline math: over
     the text, under the math); the rendering follows the typing. Enter (inline) or Ctrl+Enter (display) closes it, and
     so does Escape, going back to the text: the cursor right after inline math, in the line after display math (so a
     letter typed next never replaces the math); a click elsewhere just closes it; an empty source removes the math.
     While the piece is locked nothing opens and nothing typed there counts. */
  class MathView {
    constructor(node, view, getPos, T) {
      Object.assign(this, {node, view, getPos, T, box: null, input: null, msg: null, error: null, pressing: false,
        onResize: null, onPress: null, onRelease: null});
      this.display = node.type === N.math_display;
      this.dom = el(this.display ? "div" : "span", this.display ? "bk-mathd" : "bk-math");
      this.dom.spellcheck = false;
      this.out = this.display ? el("div", "bk-math-r") : this.dom;      // where KaTeX renders
      if (this.display) this.dom.append(this.out);
      this.dom.addEventListener("mousedown", e => this.down(e));
      views.set(this.dom, this);
      this.render();
    }
    render() {
      const tex = this.node.attrs.tex || "";
      this.error = null;
      if (!tex.trim()) this.out.replaceChildren(el("span", "bk-math-ph", "Math"));
      else if (!root.katex) this.out.textContent = tex;           // no KaTeX: the source, as the schema shows it
      else this.error = renderTex(tex, this.out, this.display);
      if (this.box) { this.say(); this.place(); }
      this.T.margin?.schedule();
    }
    down(e) {
      if (e.button !== 0 || (this.box && this.box.contains(e.target)) || this.T.locked) return;
      e.preventDefault();
      this.open();
    }
    open() {
      if (this.box) { this.input.focus(); return; }
      if (this.T.locked) return;
      const box = this.box = el("div", "bk-mathf" + (this.display ? " bk-mathf-d" : ""));
      const input = this.input = el(this.display ? "textarea" : "input", (this.display ? "textarea" : "input") + " bk-mathf-in");
      if (this.display) input.rows = 1; else input.type = "text";
      Object.assign(input, {value: this.node.attrs.tex || "", spellcheck: false, placeholder: "LaTeX, like E = mc^2"});
      input.setAttribute("aria-label", this.display ? "Display math, in LaTeX" : "Math, in LaTeX");
      input.setAttribute("autocomplete", "off"); input.setAttribute("autocapitalize", "off");
      this.msg = el("div", "bk-mathf-msg");
      box.append(input, this.msg);
      box.addEventListener("mousedown", e => { if (e.target !== input) e.preventDefault(); });
      input.addEventListener("input", () => this.typed());
      input.addEventListener("keydown", e => this.key(e));
      // A click elsewhere (or Tab) closes it in place; switching windows keeps it open, its field focused. A click closes
      // it once the button is up: the view has put the cursor where the click was by then, and removing an empty math
      // keeps it there.
      const away = () => this.box === box && !box.contains(document.activeElement);
      this.onPress = e => { this.pressing = !box.contains(e.target); };
      this.onRelease = () => { this.pressing = false; };
      document.addEventListener("mousedown", this.onPress, true);
      document.addEventListener("mouseup", this.onRelease, true);
      input.addEventListener("blur", () => setTimeout(() => {
        if (!away()) return;
        if (!this.pressing) this.close(null);
        else addEventListener("mouseup", () => setTimeout(() => { if (away()) this.close(null); }), {once: true});
      }));
      if (this.display) this.dom.append(box);
      else (this.T.over || this.view.dom.parentNode).append(box);
      this.dom.classList.add("open");
      openIn(this.T).add(this);
      this.onResize = () => this.place();
      addEventListener("resize", this.onResize);
      this.fit(); this.say(); this.place();
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
      this.T.margin?.schedule();
    }
    /* what is typed in the field goes into the math at once (one undo step with the typing around it), as the dialect
       writes it (sourceTex); the field keeps what was typed */
    typed() {
      const pos = this.getPos();
      if (this.T.locked || pos == null) { this.input.value = this.node.attrs.tex || ""; return; }
      const tex = sourceTex(this.input.value, this.display);
      this.fit();
      if (tex !== this.node.attrs.tex) this.view.dispatch(this.view.state.tr.setNodeMarkup(pos, null, {...this.node.attrs, tex}));
    }
    key(e) {
      if (e.isComposing) return;
      if (e.key !== "Escape" && !(e.key === "Enter" && (!this.display || e.ctrlKey || e.metaKey))) return;
      e.preventDefault();
      e.stopPropagation();
      this.close("after");
    }
    /* the textarea as tall as its lines */
    fit() {
      const t = this.input;
      if (!this.display || !t) return;
      t.style.height = "auto";
      t.style.height = t.scrollHeight + (t.offsetHeight - t.clientHeight) + "px";
    }
    /* under the field: KaTeX's message while it can't render the source, else the key that closes it */
    say() {
      const err = this.error;
      this.msg.textContent = err || (this.display ? (MAC ? "Done · ⌘Enter" : "Done · Ctrl+Enter") : "Done · Enter");
      this.msg.classList.toggle("err", !!err);
    }
    /* inline math's field: under the math, kept inside the page */
    place() {
      const box = this.box;
      if (!box || this.display) return;
      const host = box.offsetParent || box.parentNode;
      if (!host || !this.dom.isConnected) return;
      const ref = host.getBoundingClientRect(), rects = this.dom.getClientRects(), r = this.dom.getBoundingClientRect();
      const left = (rects[0] || r).left - ref.left;
      box.style.left = Math.round(Math.max(0, Math.min(left, host.clientWidth - box.offsetWidth))) + "px";
      box.style.top = Math.round(r.bottom - ref.top + 6) + "px";
    }
    /* `how`: "after" puts the cursor after the math (display math: in the line after it, made when there is none),
       null leaves the cursor where it is (a click elsewhere put it there). An empty source removes the math. */
    close(how) {
      if (!this.box) return;
      this.detach();
      this.T.margin?.schedule();
      const pos = this.getPos(), v = this.view;
      if (pos == null || this.T.locked) return;
      const tr = v.state.tr;
      if (!(this.node.attrs.tex || "").trim()) {
        tr.delete(pos, pos + this.node.nodeSize);
        const sel = how ? TextSelection.near(tr.doc.resolve(pos)) : clicked(v, tr);
        if (sel) tr.setSelection(sel);
      } else if (how === "after") {
        const at = this.display ? lineAfter(tr, pos) : pos + this.node.nodeSize;
        tr.setSelection(TextSelection.create(tr.doc, at));
      }
      if (tr.docChanged || tr.selectionSet) v.dispatch(tr.scrollIntoView());
      if (how) v.focus();
    }
    /* the field gone, with what listened while it was open */
    detach() {
      this.box.remove();
      this.box = this.input = this.msg = null;
      removeEventListener("resize", this.onResize);
      document.removeEventListener("mousedown", this.onPress, true);
      document.removeEventListener("mouseup", this.onRelease, true);
      this.dom.classList.remove("open");
      openIn(this.T).delete(this);
    }
    update(node) {
      if (node.type !== this.node.type) return false;
      const changed = node.attrs.tex !== this.node.attrs.tex;
      this.node = node;
      if (changed) {
        if (this.input && document.activeElement !== this.input) { this.input.value = node.attrs.tex || ""; this.fit(); }
        this.render();
      }
      return true;
    }
    selectNode() { this.dom.classList.add("sel"); }
    deselectNode() { this.dom.classList.remove("sel"); }
    /* the field's events are its own; a click on the math is this view's (it opens the source) */
    stopEvent(e) { return (!!this.box && this.box.contains(e.target)) || (e.type === "mousedown" && !this.T.locked); }
    ignoreMutation() { return true; }
    destroy() {
      if (this.box) this.detach();
      views.delete(this.dom);
    }
  }
  /* the node views for book-text.js's views (the text's and a note's) */
  const nodeViews = T => ({
    math: (n, v, g) => new MathView(n, v, g, T),
    math_display: (n, v, g) => new MathView(n, v, g, T),
  });
  /* / Math in the text of `T`: display math at the cursor, its source open */
  function insertDisplayIn(T) {
    if (T.locked) return;
    const v = T.view;
    insertDisplay(v.state, tr => v.dispatch(tr));
    openSelected(v);
  }
  /* every source field open in `T` closed where it is (when book-text.js locks the piece) */
  function closeAll(T) { for (const mv of [...openIn(T)]) mv.close(null); }

  root.BookMath = {
    mathStart, asTyped, inputRules, sourceTex, katexOptions, texError, enter, typedAfter,
    commands: {dollarsEnter, insertDisplay},
    insertDisplay: insertDisplayIn, MathView, nodeViews, closeAll,
  };
})(typeof window !== "undefined" ? window : globalThis);
