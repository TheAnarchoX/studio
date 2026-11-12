# Series kits

A kit is how a series renders its carousels: `Poems/<Series>/_kit/build.py` plus one JavaScript file per visual
concept in `_kit/concepts/`. Studio imports `build.py` and calls it; it never edits it. A series without a kit
still has poems and designs; its images are made in the Design tab.

## What `build.py` provides

```python
SCALE = 2                       # device pixel ratio of the PNGs

RATIOS = {                      # format key: (file tag, width, height, folder, label), in display order
    "45":  ("4x5",  1080, 1350, "Carousel 4x5",  "Feed · 4:5"),
    "11":  ("1x1",  1080, 1080, "Carousel 1x1",  "Square · 1:1"),
    "916": ("9x16", 1080, 1920, "Carousel 9x16", "Story · 9:16"),
}

VARIANTS = [("1", "With name", ""), ("0", "Without name", "-noname")]   # flag, subfolder, file suffix

CHROME = "/path/to/chrome"      # optional; Studio sets it to the browser from Settings

def build_html(poem, out):
    """Write the self-contained preview page for the poem (a dict from poem.json) to `out`."""

def shoot(page, n, r, sig, out, profile):
    """Screenshot slide n (1-based) of `page` in format r, signed when sig == "1", to the PNG `out`.
    `profile` is a Chrome user-data folder for this worker; Studio runs several shots in parallel."""

def contact_sheet(title, rows, out):
    """Write an overview PNG. rows = {format key: [(slide name, png path), ...]}."""

def concept_names(poem):
    """Display names of the poem's slides, in order."""
```

Studio names the files the way it expects the kit to: `<Poem>/<slug>.html` for the page,
`<Poem>/<RATIOS folder>/<VARIANTS subfolder>/<slug>-<tag>-<n>-<concept><suffix>.png` for each slide, and
`<Poem>/<slug>-carousel-preview.png` for the contact sheet.

## Concepts

Each `_kit/concepts/<id>.js` is one visual concept. Studio reads its leading `/* ... */` comment as the
description and `name: "..."` as its name, and `set_slides` only accepts ids that exist here. A poem's
`slides` in `poem.json` are a list like `[{"concept": "flare", "word": "hold"}, {"concept": "plain"}]`; the
extra keys are the concept's parameters, which the kit interprets.

## For QA

QA renders a **plate** of each slide: the same page with a stylesheet that makes all text inside `.slide`
transparent. Keep text in elements under `.slide` and backgrounds out of text colour, and QA can find the ink.

## In the Art tab

The Art tab drives a kit without Claude: it lists the kit's concepts and lets you choose the slides, write the
brief and posting notes, render, and run QA, all through the functions above. Claude does the same through the
MCP tools, over the same code.

## Rules and briefs

`Poems/<Series>/README.md` holds the series' rules and `_kit/BRIEF-TEMPLATE.md` (optional) the shape of a brief;
Claude reads both through `get_rules` before it writes a brief. `CONCEPTS.md` is the catalogue of concepts
(used, ready, rejected, unbuilt ideas) that `list_concepts` returns next to the built ones.
