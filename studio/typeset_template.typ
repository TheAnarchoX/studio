// The book's page rules and generated pages (spec: docs/superpowers/specs/2026-11-13-books-part-2-design.md, "Page
// rules" and "Generated pages"). studio/typeset_book.py writes, above this file, the values it reads:
//
//   design      the resolved book design: lengths in mm, type sizes in pt
//   fonts       the families the compiler knows the cut faces by: (text: …, heading: …)
//   book        title, subtitle, author, publisher, year, edition, isbn, nur, rights, set-in (the sentence or none),
//               lang, region, notes, numbering, notes-linked, allow-widows (book.json `checks.allowWidows`: Typst's
//               widow and orphan prevention off), words (the words this file prints, in the book's language: page,
//               missing)
//   pieces      per contents index (as a string): (kind, generated, title, number, bare, start); `bare` is a
//               numbered chapter without a title, whose opening piece-start sets
//   body-start  the contents index of the body's first entry (as the list of pieces groups the book), where arabic
//               page numbers start, or none
//
// and below it `#show: book-setup`, then the book's entries in order: each piece's source (studio/typeset.py) and
// each generated page as a call of the functions here. Every string in those values was written as a literal, so
// nothing here ever evaluates the author's text: it only places it.

// ——— measures ———
#let pitch = design.text.line                       // the distance from one baseline to the next
#let leading = design.text.line - design.text.size  // text edges are fixed to 1 em, so this gives that pitch exactly
#let small = design.notes.size + 1pt                // back matter: notes, bibliography, index, tables
#let small-leading = small * (design.text.line / design.text.size) - small
#let note-leading = design.notes.size * (design.text.line / design.text.size) - design.notes.size
#let measure-width = design.width - design.margins.inside - design.margins.outside
#let text-height = design.height - design.margins.top - design.margins.bottom
#let heading-font = fonts.at("heading", default: fonts.text)
#let mono = "DejaVu Sans Mono"                      // embedded in Typst: TeX source is never the text font's to cover
#let labels = design.pages.labels
#let words = book.words                             // "p." or "blz." and the like, in the book's language

// ——— kinds ———
#let always-right = ("half-title", "title-page", "dedication", "epigraph", "toc", "part", "notes", "bibliography",
  "index")
#let like-chapter = ("chapter", "prologue", "interlude", "epilogue", "afterword", "acknowledgements", "appendix",
  "about-author")
#let unnumbered = ("half-title", "title-page", "copyright", "dedication", "epigraph", "part")
#let untitled = ("dedication", "epigraph")          // their title is the file's name for them, not the page's
#let entry(i) = pieces.at(str(i), default: (kind: "", generated: false, title: "", number: none, bare: false,
  start: none))

// A page's number in its own numbering (roman in the front matter, arabic from the body's first entry).
#let page-of(loc) = {
  let n = loc.page-numbering()
  if n == none { str(loc.page()) } else { numbering(n, ..counter(page).at(loc)) }
}

#let caps(body, tracking: 0.06em) = text(tracking: tracking, smallcaps(all: true, body))

#let cased(body) = {
  let c = design.headings.case
  if c == "smallcaps" { caps(body) } else if c == "caps" { text(tracking: 0.08em, upper(body)) } else { body }
}

// ——— what is on a page: blank or not, its folio and running head ———
// A page is blank when the piece last started before it has ended on an earlier page and none starts on it. Folios
// stay off blank pages, pages before the contents and the pages of half-title, title page, copyright, dedication,
// epigraph and part; running heads also stay off every page where a piece starts.
//
// The facts of every page come from one table built from the markers in a single pass. The function takes no
// arguments and reads no position of its own, so Typst computes it once per layout pass and every page's header and
// footer looks its page up, instead of each scanning all the markers again.
#let page-table() = {
  let starts = query(<piece-start>)
  let ends = query(<piece-end>)
  let opens = (:)                     // page -> a piece starts there
  let closes = (:)                    // page -> a piece ends there
  let ended = (:)                     // contents index -> the page its piece ends on
  for m in starts { opens.insert(str(m.location().page()), true) }
  for m in ends {
    closes.insert(str(m.location().page()), true)
    ended.insert(str(m.value), m.location().page())
  }
  let last = calc.max(1, ..starts.map(m => m.location().page()), ..ends.map(m => m.location().page()))
  let toc = starts.find(m => entry(m.value).kind == "toc")
  let toc-page = if toc != none { toc.location().page() }
  let facts(p, current, opening, closing) = {
    let closed = current != none and ended.at(str(current), default: p) < p
    let blank = not opening and not closing and (current == none or closed)
    let early = toc-page != none and p < toc-page
    let kind = if current != none { entry(current).kind } else { "" }
    (current: current, opening: opening, blank: blank, shown: not blank and not early and kind not in unnumbered)
  }
  let pages = ()
  let k = 0
  let current = none
  for p in range(1, last + 1) {
    while k < starts.len() and starts.at(k).location().page() <= p {
      current = starts.at(k).value
      k += 1
    }
    pages.push(facts(p, current, str(p) in opens, str(p) in closes))
  }
  // any page after the last marker (the blank that makes the total even) has the last piece in effect
  (pages: pages, after: facts(last + 1, current, false, false))
}

#let page-facts() = {
  let p = here().page()
  let table = page-table()
  let f = if p <= table.pages.len() { table.pages.at(p - 1) } else { table.after }
  let verso = calc.even(p)
  let head = none
  if f.shown and not f.opening {
    head = if verso {
      if design.heads.verso == "title" { book.title } else if design.heads.verso == "author" { book.author }
    } else {
      if design.heads.recto == "piece" { entry(f.current).title } else if design.heads.recto == "title" {
        book.title
      }
    }
    if head == "" { head = none }
  }
  // A blank page has no folio. (The blank before arabic page 1 already counts in the new numbering.)
  (page: p, folio: if f.blank { none } else { counter(page).display() }, blank: f.blank, shown: f.shown,
    opening: f.opening, verso: verso, head: head)
}

#let running-head() = {
  let f = page-facts()
  let folio-top = f.shown and not f.opening and design.heads.folio == "top-outside"
  set text(size: design.text.size, hyphenate: false)
  set par(justify: false, first-line-indent: 0pt)
  block(width: 100%, {
    if folio-top { place(if f.verso { left } else { right }, f.folio) }
    if f.head != none {
      align(center, if design.heads.style == "smallcaps" { caps(f.head) } else { emph(f.head) })
    }
  })
}

// The footer also tells the composer what each page is: `<page-info>`, one per page, whatever is printed.
#let page-foot() = {
  let f = page-facts()
  [#metadata((page: f.page, folio: f.folio, blank: f.blank, shown: f.shown, head: f.head))<page-info>]
  if f.shown and (f.opening or design.heads.folio != "top-outside") {
    let where = if f.opening or design.heads.folio == "bottom-centre" { center } else if f.verso { left } else {
      right
    }
    set text(size: design.text.size)
    set par(justify: false, first-line-indent: 0pt)
    align(where, f.folio)
  }
}

// ——— the book ———
#let book-setup(body) = {
  set document(title: book.title, author: if book.author != "" { (book.author,) } else { () })
  set page(
    width: design.width, height: design.height, binding: left,
    margin: (inside: design.margins.inside, outside: design.margins.outside, top: design.margins.top,
      bottom: design.margins.bottom),
    numbering: "i",
    header: context running-head(),
    footer: context page-foot(),
  )
  // No overhang: hyphens and stops would hang up to a millimetre into the margin, and the text block's edges are
  // what the print checks measure ink against.
  set text(font: fonts.text, size: design.text.size, top-edge: 0.8em, bottom-edge: -0.2em, lang: book.lang,
    region: book.region, hyphenate: design.text.hyphenate, fill: luma(0), overhang: false,
    costs: if book.allow-widows { (widow: 0%, orphan: 0%) } else { (widow: 100%, orphan: 100%) })
  set par(
    leading: leading,
    spacing: if design.text.paragraph == "indent" { leading } else { leading + pitch },
    justify: design.text.align == "justify",
    first-line-indent: if design.text.paragraph == "indent" { (amount: 1em, all: false) } else { 0pt },
  )
  set footnote.entry(gap: 0.6em, indent: 0em)
  show footnote.entry: set text(size: design.notes.size)
  show footnote.entry: set par(leading: note-leading, spacing: note-leading, first-line-indent: 0pt)
  show footnote.entry: it => {          // the number, a thin space, the note
    let loc = it.note.location()
    [#link(loc, super(numbering(it.note.numbering, ..counter(footnote).at(loc))))#h(0.25em)#it.note.body]
  }
  show heading.where(level: 1): it => {
    set par(justify: false, first-line-indent: 0pt, leading: 0.3em)
    set text(font: heading-font, size: design.headings.size, weight: "regular", hyphenate: false)
    block(width: 100%, above: 0pt, sticky: true, align(center, cased(it.body)))     // below: set by piece-title
  }
  // Typst's own heading styles scale the text of levels 2 and 3; the size is set back to the text's so a section
  // heading takes exactly one line of the grid.
  show heading.where(level: 2): it => block(width: 100%, above: leading + pitch, below: leading, sticky: true, {
    set par(justify: false, first-line-indent: 0pt)
    set text(size: design.text.size, weight: "bold", hyphenate: false)
    if design.headings.sections == "numbered" { context counter("book-section").display("1.1") + h(0.6em) }
    it.body
  })
  show heading.where(level: 3): it => block(width: 100%, above: leading + pitch, below: leading, sticky: true, {
    set par(justify: false, first-line-indent: 0pt)
    set text(size: design.text.size, style: "italic", hyphenate: false)
    if design.headings.sections == "numbered" { context counter("book-section").display("1.1") + h(0.6em) }
    it.body
  })
  show quote.where(block: true): it => block(width: 100%, above: leading + pitch, below: leading + pitch,
    inset: (left: 1.5em, right: 1.5em), it.body)
  body
}

// Each piece is set in a scope of its own (`#[#show: piece-body.with(kind) … ]`), so a kind can style its text.
#let piece-body(kind, body) = {
  if kind == "dedication" {
    set align(center)
    set par(justify: false, first-line-indent: 0pt)
    set text(style: "italic")
    body
  } else { body }
}

// A piece's opening, sunk from the top of the text area: the chapter's number (or none), then the title (or none).
// The space under the last of them is measured so the text below starts on the page's line grid, level with the
// lines of the facing page and of the other side of the leaf. (Measuring lays the title out apart from the page, so
// the markers in it are never placed twice.) The number leaves `<chapter-number>` metadata where it stands.
#let opening(number, body, lab) = {
  let numeral(below) = block(width: 100%, below: below, sticky: true, align(center, text(font: heading-font,
    size: design.headings.size, [#metadata(number)<chapter-number>#number])))
  context {
    let used = design.headings.sink
    if body != none {
      used += measure(width: measure-width, heading(level: 1, outlined: false, bookmarked: false, body)).height
    }
    if number != none {
      used += measure(width: measure-width, numeral(0pt)).height + if body != none { pitch } else { 0pt }
    }
    let below = calc.ceil((used + 1.5 * pitch) / pitch) * pitch - used
    v(design.headings.sink)
    if body == none {
      if number != none { numeral(below) }
    } else {
      if number != none { numeral(pitch) }
      show heading: set block(below: below)        // a show-set rule: it wins over Typst's own heading spacing
      [#heading(level: 1, outlined: false, bookmarked: true, body)#lab]
    }
  }
}

// The page break rule: right-hand pages for the title pages, dedication, epigraph, contents, parts and the generated
// back pages, and for chapters and back matter when the design starts chapters on the right; the next page for the
// rest. Arabic page numbers start at 1 with the body's first entry, a prologue or introduction as much as a part or
// chapter (typeset_book switches the numbering to "1" just before it), always on a right-hand page, whatever the
// design says; footnotes count from 1 again in every piece unless they are numbered through the book.
#let piece-start(i, kind) = {
  let right = (kind in always-right or (kind in like-chapter and design.headings.start == "right")
    or i == body-start)
  pagebreak(weak: true, to: if right { "odd" } else { none })
  if i == body-start { counter(page).update(1) }
  if book.numbering != "book" { counter(footnote).update(0) }
  counter("book-section").update(0)
  [#metadata(i)<piece-start>]
  if kind in untitled { v(text-height / 5) }
  if entry(i).bare { opening(entry(i).number, none, none) }     // a numbered chapter without a title: its number
}

#let piece-end(i) = {
  [#metadata(i)<piece-end>]
  if entry(i).kind == "part" { pagebreak(weak: true, to: "odd") }      // a part page has a blank back
}

// The piece's title: a level-1 heading (a bookmark in the PDF, not in Typst's own outline) labelled <piece-i>, in the
// piece's opening; a part's title centred on its own page under its number. Its body is shown here only: running
// heads and the contents use the plain titles in `pieces`.
#let piece-title(i, body) = {
  let p = entry(i)
  if p.kind not in untitled {
    let lab = label("piece-" + str(i))
    if p.kind == "part" {
      v(1fr)
      block(width: 100%, below: 1.5 * pitch, sticky: true, align(center,
        text(font: heading-font, size: design.text.size, caps([#labels.part #p.number], tracking: 0.1em))))
      [#heading(level: 1, outlined: false, bookmarked: true, body)#lab]
      v(1.5fr)
    } else {
      opening(p.number, body, lab)
    }
  }
}

#let section(level, body) = {
  counter("book-section").step(level: level - 1)
  heading(level: level, outlined: false, bookmarked: true, body)
}

// ——— blocks inside pieces ———
// Blocks keep the line pitch where they can: a block standing for one line takes `leading` above and below; one set
// off from the text takes a blank line (`leading + pitch`).
#let scene-break() = block(width: 100%, height: 1em, above: leading, below: leading, breakable: false, align(center,
  if design.scene == "asterisks" { range(3).map(_ => "*").join(h(1em)) } else if design.scene == "asterism" { "⁂" }))

// An epigraph sits towards the outside edge, in a narrower measure, italic as written (emph turns the author's own
// italics upright), the attribution after an em dash.
#let epigraph(paras, attribution) = context {
  let recto = calc.odd(here().page())
  let narrow = measure-width / 4
  block(width: 100%, above: leading + pitch, below: leading + pitch, pad(
    left: if recto { narrow } else { 0pt }, right: if recto { 0pt } else { narrow }, {
      set par(justify: false, first-line-indent: 0pt)
      if paras.len() > 0 { emph(paras.join(parbreak())) }
      if attribution != none {
        parbreak()
        align(right, [— #attribution])
      }
    }))
}

// A poem: lines as written, never justified or hyphenated, a line too long for the measure wrapping with a hanging
// indent. With the optical centre the block's left edge sits at (measure − longest line) / 2, so the longest line is
// centred and the others hang from the same edge. Measuring lays the lines out apart from the page, so the markers
// inside them are never placed twice. Stanzas stay whole when they fit on a page.
#let poem(stanzas) = context {
  let lines = stanzas.flatten()
  let longest = calc.max(0pt, ..lines.map(l => measure(l).width))
  let offset = if design.poems.place == "optical-centre" and longest < measure-width {
    (measure-width - longest) / 2
  } else { 0pt }
  for s in stanzas {
    let body = {
      set par(justify: false, first-line-indent: 0pt, hanging-indent: 1em, spacing: leading)
      set text(hyphenate: false)
      s.map(l => par(l)).join()
    }
    let keep = design.poems.keepStanzas and measure(width: measure-width - offset, body).height <= text-height
    block(width: 100%, inset: (left: offset), above: leading + pitch, below: leading + pitch, breakable: not keep,
      body)
  }
}

// An image (or the frame standing in for a missing one) with its caption half a line beneath, whatever the
// paragraph spacing. The staged image is already grey for a grey interior (the composer converts it).
#let figure-block(picture, caption) = block(width: 100%, above: leading + pitch, below: leading + pitch,
  breakable: false, stack(dir: ttb, spacing: 0.5 * pitch, align(center, picture),
    ..if caption != none { (align(center, text(size: design.notes.size, caption)),) }))

#let image-block(path, width, caption) = figure-block(image(path, width: width), caption)

#let missing-image(caption) = figure-block(rect(width: 100%, height: 3 * pitch, stroke: 0.4pt + luma(0),
  align(center + horizon, text(size: design.notes.size, words.missing))), caption)

// One element, so the label the piece source puts after it (<noteref-i-n>) is the reference the notes page links to.
#let note-ref(i, n) = if book.notes-linked {
  link(label("note-" + str(i) + "-" + str(n)), super(str(n)))
} else { super(str(n)) }

// A list item hangs 1.5 em per level, its marker right-aligned in the indent.
#let list-item(level, marker, body) = block(width: 100%, above: leading, below: leading,
  inset: (left: 1.5em * (level + 1)), {
    set par(first-line-indent: 0pt, hanging-indent: 0pt)
    par[#h(-1.5em)#box(width: 1.1em, align(right, marker))#h(0.4em)#body]
  })

#let aligned(where, body) = block(width: 100%, above: leading, below: leading, {
  set par(justify: false, first-line-indent: 0pt)
  align(if where == "center" { center } else { right }, body)
})

#let book-table(header, aligns, rows) = block(width: 100%, above: leading + pitch, below: leading + pitch, {
  set text(size: small, hyphenate: false)
  set par(justify: false, first-line-indent: 0pt, leading: small-leading)
  let cells = rows.map(r => r.map(c => table.cell(c)))
  table(
    columns: (1fr,) * aligns.len(),
    stroke: none,
    inset: (x: 0.4em, y: 0.35em),
    align: (x, y) => { let a = aligns.at(x); if a == auto { start } else { a } },
    table.hline(stroke: 0.6pt),
    ..if header and cells.len() > 0 {
      (table.header(..cells.first()), table.hline(stroke: 0.4pt)) + cells.slice(1).flatten()
    } else { cells.flatten() },
    table.hline(stroke: 0.6pt),
  )
})

#let math-tex(s) = text(font: mono, size: 0.9em, hyphenate: false, s)
#let math-tex-block(s) = block(width: 100%, above: leading + pitch, below: leading + pitch, align(center,
  text(font: mono, size: 0.9em, hyphenate: false, s)))

// ——— generated pages ———
#let half-title() = {
  v(text-height / 5)
  block(width: 100%, align(center, {
    set par(justify: false, first-line-indent: 0pt, leading: 0.3em)
    text(font: heading-font, size: design.headings.size, hyphenate: false, book.title)
  }))
}

#let title-page() = {
  set par(justify: false, first-line-indent: 0pt, leading: 0.3em)
  set text(font: heading-font, hyphenate: false)
  v(text-height / 5)
  block(width: 100%, below: pitch, align(center, text(size: 1.5 * design.headings.size, book.title)))
  if book.subtitle != "" {
    block(width: 100%, below: pitch, align(center, text(size: 0.8 * design.headings.size, book.subtitle)))
  }
  if book.author != "" {
    v(2 * pitch)
    block(width: 100%, align(center, text(size: design.headings.size, book.author)))
  }
  if book.publisher != "" {
    v(1fr)
    block(width: 100%, align(center, text(size: design.text.size, caps(book.publisher))))
  }
}

// The copyright page: a verso, set small at the foot of the page.
#let copyright-page() = {
  v(1fr)
  set text(size: design.notes.size, hyphenate: false)
  set par(justify: false, first-line-indent: 0pt, leading: note-leading, spacing: note-leading)
  let holder = (book.year, book.author).filter(x => x != "")
  let facts = ()
  if holder.len() > 0 { facts.push([© #holder.join(" ")]) }
  if book.edition != "" { facts.push(book.edition) }
  if book.isbn != "" { facts.push([ISBN #book.isbn]) }
  if book.nur != "" { facts.push([NUR #book.nur]) }
  if book.publisher != "" { facts.push(book.publisher) }
  let notices = ()
  if book.rights != "" { notices.push(book.rights) }
  if book.set-in != none { notices.push(book.set-in) }             // "Set in Literata." in the book's language
  for f in facts { par(f) }
  if facts.len() > 0 and notices.len() > 0 { v(design.notes.size + note-leading) }
  for n in notices { par(n) }
}

// `body` as a link to `loc` (a location in the book), or as it is without one.
#let linked(loc, body) = if loc != none { link(loc, body) } else { body }

// A line of the contents or of the first lines: the number in a column as wide as the widest number (so every title
// starts at the same place), the title, dot leaders or space, and the page right-aligned in a column as wide as the
// widest page number. The dots are set from that column without being spread, so they line up from line to line.
// `<toc-title>` marks where the title starts. With `loc` the title and the page number are links to it, so the PDF
// is also a reading copy.
#let toc-line(title, shown, key: none, number: none, number-width: 0pt, indent: 0pt, page-width: 0pt,
  loc: none) = block(width: 100%, above: leading, below: leading, inset: (left: indent), {
    set par(justify: false, first-line-indent: 0pt, hanging-indent: if number != none { number-width } else { 1em })
    let fill = if design.pages.leaders {
      h(0.4em) + box(width: 1fr, align(right, repeat(gap: 0.3em, justify: false)[.]))
    } else { h(1fr) }
    let lead = if number != none { box(width: number-width, number) }
    let mark = if key != none { [#metadata(key)<toc-title>] }
    let folio = box(width: page-width, align(right, if shown != none { linked(loc, shown) }))
    par[#lead#mark#linked(loc, title)#fill#h(0.5em)#folio]
  })

// The widest of some short strings (numbers) as set here.
#let widest(items) = calc.max(0pt, ..items.map(x => measure(x).width))

// The contents: every line shows the page its target is on, as Typst laid the book out, in that page's numbering.
// `entries`: ((level, title, number, target: <piece-i> | (p: i, b: k), part: bool), …), built by typeset_book.
// Each line also leaves `<toc-entry>` metadata, (target, shown), for the tests and the composer. Sections sit at the
// titles' left edge (or 1.5 em in, when no title has a number). Titles and page numbers link to their pages.
#let contents-page(entries) = context {
  let blk-at = (:)                    // the section markers, looked up once
  if entries.any(e => type(e.target) == dictionary) {
    for m in query(<blk>) { blk-at.insert(str(m.value.p) + "-" + str(m.value.b), m.location()) }
  }
  let lines = entries.map(e => {
    let key = if type(e.target) == label { str(e.target) } else { str(e.target.p) + "-" + str(e.target.b) }
    let loc = if type(e.target) == label {
      let found = query(e.target)
      if found.len() > 0 { found.first().location() }
    } else { blk-at.at(key, default: none) }
    (..e, key: if type(e.target) == label { key } else { "blk-" + key }, shown: if loc != none { page-of(loc) },
      loc: loc)
  })
  let numbers = lines.filter(l => l.number != none and not l.part).map(l => l.number)
  let number-width = widest(numbers) + 0.8em
  let page-width = widest(lines.filter(l => l.shown != none).map(l => l.shown))
  for l in lines {
    [#metadata((target: l.key, shown: l.shown))<toc-entry>]
    if l.part {
      block(width: 100%, above: leading + pitch, below: leading, sticky: true, {
        set par(justify: false, first-line-indent: 0pt)
        par[#linked(l.loc, [#caps([#labels.part #l.number])#h(0.8em)#l.title])#h(1fr)#box(width: page-width,
          align(right, if l.shown != none { linked(l.loc, l.shown) }))]
      })
    } else {
      let indent = if l.level == 1 { 0pt } else if numbers.len() > 0 { number-width } else { 1.5em }
      toc-line(l.title, l.shown, key: l.key, number: l.number, number-width: number-width, indent: indent,
        page-width: page-width, loc: l.loc)
    }
  }
}

// The notes, under the titles of their pieces; each number links back to its reference and, with page references
// on, the page the reference is on follows it. `groups`: ((title, notes: ((n, body, ref, label), …)), …).
#let notes-page(groups) = context {
  set text(size: small)
  set par(justify: false, first-line-indent: 0pt, hanging-indent: 1.5em, leading: small-leading,
    spacing: small-leading)
  for g in groups {
    if g.title != "" {
      block(width: 100%, above: small-leading + 1.5 * pitch, below: small-leading + 0.5 * pitch, sticky: true,
        caps(g.title))
    }
    for n in g.notes {
      let refs = query(n.ref)
      let num = if refs.len() > 0 { link(n.ref, str(n.n)) } else { str(n.n) }
      let where = if design.notes.pageRefs and refs.len() > 0 {
        [(#words.page #page-of(refs.first().location()))#h(0.4em)]
      }
      [#par[#box(width: 1.5em, num)#where#n.body]#n.label]
    }
  }
}

#let bibliography-page(entries) = {
  set text(size: small)
  set par(justify: false, first-line-indent: 0pt, hanging-indent: 1.5em, leading: small-leading,
    spacing: small-leading)
  for e in entries { par(e) }
}

// The pages an index key's markers are on: each page once, in its own numbering, runs of three or more arabic pages
// joined with an en dash (12–14). Returns (shown, physical pages, the same as content with every number a link to
// its page).
#let index-pages(locs) = {
  let seen = ()
  let items = ()
  for loc in locs {
    let p = loc.page()
    if p not in seen {
      seen.push(p)
      items.push((page: p, folio: page-of(loc), arabic: loc.page-numbering() == "1", loc: loc))
    }
  }
  let parts = ()
  let links = ()
  let k = 0
  while k < items.len() {
    let j = k
    while (j + 1 < items.len() and items.at(k).arabic and items.at(j + 1).arabic
      and items.at(j + 1).page == items.at(j).page + 1) { j += 1 }
    let (a, z) = (items.at(k), items.at(j))
    if j - k >= 2 {
      parts.push(a.folio + "–" + z.folio)
      links.push([#link(a.loc, a.folio)–#link(z.loc, z.folio)])
      k = j + 1
    } else {
      parts.push(a.folio)
      links.push(link(a.loc, a.folio))
      k += 1
    }
  }
  (if parts.len() > 0 { parts.join(", ") } else { "" }, seen, links.join(", "))
}

#let index-line(term, key, marks, indent) = {
  let (shown, pages, links) = if key == none { ("", (), none) } else { index-pages(marks.at(key, default: ())) }
  if key != none { [#metadata((key: key, shown: shown, pages: pages))<index-entry>] }
  block(width: 100%, above: small-leading, below: small-leading, inset: (left: indent),
    par[#term#if shown != "" [, #links]])
}

// The index in two columns, by letter. `groups`: ((letter, terms: ((term, key, subs: ((term, key), …)), …)), …),
// sorted by typeset_book with case and accents ignored. Each term with a key leaves `<index-entry>` metadata.
// Typst doesn't balance columns, so an index that fits on its page is split by height into two columns of its own,
// never right after a letter; a longer one flows through the columns page after page.
#let index-page(groups) = context {
  let marks = (:)
  for m in query(<idx>) {
    let k = m.value.t
    marks.insert(k, marks.at(k, default: ()) + (m.location(),))
  }
  let items = ()
  for g in groups {
    if g.letter != "" {
      items.push((letter: true, body: block(width: 100%, above: small-leading + pitch, below: small-leading,
        sticky: true, strong(g.letter))))
    }
    for t in g.terms {
      items.push((letter: false, body: {
        index-line(t.term, t.key, marks, 0pt)
        for s in t.subs { index-line(s.term, s.key, marks, 1em) }
      }))
    }
  }
  let gutter = 1.5 * small
  let column = (measure-width - gutter) / 2
  // the index's own styles go with the items, so they are measured as they will be set
  let join(part) = {
    set text(size: small)
    set par(justify: false, first-line-indent: 0pt, hanging-indent: 2em, leading: small-leading,
      spacing: small-leading)
    if part.len() > 0 { part.map(x => x.body).join() }
  }
  let height(a, b) = measure(width: column, join(items.slice(a, b))).height
  let n = items.len()
  let total = height(0, n)
  // the first k items whose height reaches half of the whole (a binary search: a few measurements), then the
  // split one item earlier when that balances better, never right after a letter
  let lo = 0
  let hi = n
  while lo < hi {
    let mid = calc.quo(lo + hi, 2)
    if 2 * height(0, mid) < total { lo = mid + 1 } else { hi = mid }
  }
  let k = lo
  if k > 0 and calc.max(height(0, k - 1), height(k - 1, n)) < calc.max(height(0, k), height(k, n)) { k -= 1 }
  while k > 0 and items.at(k - 1).letter { k -= 1 }
  let room = design.height - design.margins.bottom - here().position().y
  if n > 1 and calc.max(height(0, k), height(k, n)) + small-leading <= room {
    grid(columns: (1fr, 1fr), column-gutter: gutter, join(items.slice(0, k)), join(items.slice(k)))
  } else {
    columns(2, gutter: gutter, join(items))
  }
}

// Every poem's first line and the page its poem starts on, both links to that page. `lines`: ((text, piece), …),
// sorted by typeset_book.
#let first-lines-page(lines) = context {
  let at = (:)                        // contents index -> where its piece starts, looked up once
  for m in query(<piece-start>) { at.insert(str(m.value), m.location()) }
  let locs = lines.map(l => at.at(str(l.piece), default: none))
  let shown = locs.map(loc => if loc != none { page-of(loc) })
  let page-width = widest(shown.filter(x => x != none))
  for (l, s, loc) in lines.zip(shown, locs) { toc-line(l.text, s, page-width: page-width, loc: loc) }
}

// The total made even: a blank page at the end when the last page is a recto. The page is read from a marker
// placed before the break, so the answer can't change by breaking.
#let blank-to-even() = [#metadata(none)<book-end>#context if calc.odd(locate(<book-end>).page()) { pagebreak() }]
