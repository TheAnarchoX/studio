/* PLAIN — the poem as written, one left edge, signed like a poem. The normal version every carousel needs.
   params: ground ("night" default, or "paper"). */
concept("plain", {
  name: "Plain",
  build: (r, o) => `<section class="slide plain${o.ground === "paper" ? " paper" : ""}">${POEM.lines.map(l => `<p>${esc(l)}</p>`).join("")}</section>`,
});
