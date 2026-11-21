// Stand-ins for the template functions studio/typeset_template.typ defines, so a piece's Typst source compiles on its
// own in tests/test_typeset.py. Each one just shows its body; a few also leave metadata (labels `stub-…`) that the
// tests read back to see the structure they were called with.
#let piece-start(i, kind) = none
#let piece-title(i, body) = block(body)
#let piece-end(i) = none
#let section(level, body) = block(body)
#let scene-break() = block[\* \* \*]
#let epigraph(paras, attribution) = block[#paras.join(parbreak()) #attribution]
#let poem(stanzas) = [#metadata(stanzas.map(s => s.len()))<stub-poem>#stanzas.map(s => s.join(linebreak())).join(parbreak())]
#let image-block(path, width, caption) = [#metadata((path: path, width: repr(width)))<stub-image>#block(caption)]
#let missing-image(caption) = block[Image missing #caption]
#let note-ref(i, n) = super(str(n))
#let list-item(level, marker, body) = [#metadata((level: level, marker: marker))<stub-list>#block[#marker #body]]
#let aligned(align, body) = block(body)
#let book-table(header, aligns, rows) = [#metadata((header: header, aligns: aligns.map(repr), rows: rows.map(r => r.len())))<stub-table>#table(columns: aligns.len(), ..rows.flatten())]
#let math-tex(s) = raw(s)
#let math-tex-block(s) = raw(s, block: true)
