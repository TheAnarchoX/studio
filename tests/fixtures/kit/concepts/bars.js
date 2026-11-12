/* BARS — the poem on a red bar per line, like a marker pen on a manifesto.
   params: mark (line indices, 0-based; every line when left out). */
concept("bars", {
  name: "Bars",
  build: (r, o) => `<section class="slide bars">${POEM.lines.map((l, i) => `<p class="${!o.mark || o.mark.includes(i) ? "hl" : ""}">${esc(l)}</p>`).join("")}</section>`,
});
