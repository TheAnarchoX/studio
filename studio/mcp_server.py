"""Studio's MCP server (stdio): what Claude can do with the poems in the Studio library.

Read: list_poems, read_poem, get_rules, list_concepts. Make: write_brief, set_slides, render. Check: qa.
Everything goes through the same store as the web app, over the same files.
"""
import io
import json
import logging
from typing import Any

import anyio
from PIL import Image as PILImage
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import config, fonts, making, shoot
from .kit import FORMAT_LABEL, Kit, KitError
from .styles import Styles
from .store import STATUSES, Store, StoreError, read_text

INSTRUCTIONS = """\
Studio is a poet's studio. Poems and their artwork are plain files in the Studio library folder
(Poems/<Series>/<Poem>/poem.json, drafts/, writing-notes.md, BRIEF.md, NOTES.md, renders). The poet writes in
the Studio notebook and marks a poem "ready" for art; you make artwork only when asked.

Making a carousel: read_poem -> get_rules and list_concepts (always read the series rules first) ->
write_brief (from the poem's own mechanics) -> set_slides -> render -> qa -> look at the contact sheet,
fix what QA or your eye finds (concept code lives in the series' _kit/concepts/*.js) -> render again.
The poet sees every render live in Studio. A poem can be named by id
("<Series>/<Poem folder>"), folder name, title or slug."""

server = MCPServer("studio", title="Studio", instructions=INSTRUCTIONS, log_level="WARNING")
logging.getLogger("fontTools").setLevel(logging.WARNING)
store = Store()


def _err(e):
    raise ToolError(str(e)) from None


async def _run(fn, *args, **kw):
    try:
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kw))
    except (StoreError, KitError, ValueError) as e:
        _err(e)


def _preview(path, box=1600):
    with PILImage.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((box, box), PILImage.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return Image(data=buf.getvalue(), format="jpeg")


@server.tool(structured_output=False)
async def list_poems(series: str | None = None, status: str | None = None) -> str:
    """List the poems with their status (draft, ready, in review, approved, exported).

    Filter by series name and/or status. "ready" means the poet marked it ready for art."""
    if status and status not in STATUSES:
        _err(f"status must be one of: {', '.join(STATUSES)}")
    poems = await _run(store.list, series, status)
    keep = ("id", "number", "title", "status", "first_line", "line_count", "slides", "updated", "error")
    return json.dumps([{k: p[k] for k in keep if k in p} for p in poems], ensure_ascii=False, indent=1)


@server.tool(structured_output=False)
async def read_poem(poem: str, drafts: int = 3) -> str:
    """Everything about one poem: text, status, slides, the latest drafts, writing notes, brief,
    posting notes, what has been rendered (with image paths) and whether the renders are out of date."""
    def go():
        p = store.read(poem)
        folder = store.resolve(p["id"])
        art, images = p["art"], {}
        for r, f in (art.get("formats") or {}).items():
            got = [str(store.root / s["signed"]) if s["signed"] else None for s in f["slides"]]
            if any(got):
                images[f["label"]] = got
        qa = p.get("qa") or {}
        qa_issues = {k: [i["text"] for i in v.get("issues", [])] for k, v in (qa.get("images") or {}).items()
                     if v.get("issues")}
        return {
            "id": p["id"], "path": p["path"], "title": p["title"], "number": p["number"], "slug": p["slug"],
            "author": p["author"], "status": p["status"], "lines": p["lines"], "slides": p["slides"],
            "drafts": [{"when": d["when"], "title": d["title"], "lines": d["lines"]}
                       for d in p["drafts"][:max(0, drafts)]],
            "draft_count": len(p["drafts"]), "writing_notes": p["writing_notes"] or None,
            "brief": p["brief"], "posting_notes": p["notes"],
            "art": {"no_kit": True} if art.get("no_kit") else {"error": art["error"]} if "error" in art else {
                "rendered": art["rendered"], "out_of_date": art["stale"],
                "preview_page": str(store.root / art["page"]) if art["page"] else None,
                "contact_sheet": str(store.root / art["sheet"]) if art["sheet"] else None,
                "signed_images": images},
            "last_qa": {"when": qa.get("when"), "issues": qa_issues} if qa else None,
            "designs": [{"slug": x["slug"], "name": x["name"], "format": FORMAT_LABEL.get(x["format"], x["format"]),
                         "layers": x["elements"], "exported": [FORMAT_LABEL[f] for f in x["exports"]]} for x in p["designs"]],
            "series": p["series_info"],
            "style": p.get("style"),
            "folder_files": sorted(x.name for x in folder.iterdir()),
        }
    return json.dumps(await _run(go), ensure_ascii=False, indent=1)


@server.tool(structured_output=False)
async def get_rules(series: str) -> str:
    """The house rules (when there are any), the series' rules (README.md) and its brief template. Read these before briefing or rendering.

    series: the series name (the first part of a poem id)."""
    def go():
        d = store.series_dir(series)
        parts = []
        house = Styles(config.ART).rules().strip()
        if house:
            parts.append("# House rules (they apply to every series)\n\n" + house)
        parts += [f"# Rules — {d.name} (from {d / 'README.md'})\n\n" + (read_text(d / "README.md") or "(none)")]
        tpl = read_text(d / "_kit" / "BRIEF-TEMPLATE.md")
        if tpl:
            parts.append(f"# Brief template (write BRIEF.md in this shape)\n\n{tpl}")
        return "\n\n---\n\n".join(parts)
    return await _run(go)


@server.tool(structured_output=False)
async def list_concepts(series: str) -> str:
    """The series' visual concepts: every built one (id, name, params from its source), which poems use
    each, and the catalogue (CONCEPTS.md: used, ready, rejected and unbuilt ideas)."""
    def go():
        d = store.series_dir(series)
        used = {}
        for p in store.list(d.name):
            for c in p.get("slides") or []:
                used.setdefault(c, []).append(p["id"])
        built = [{**c, "used_in": used.get(c["id"], [])} for c in Kit(d).concepts()]
        return (json.dumps({"built": built, "concept_code": str(d / "_kit" / "concepts")}, ensure_ascii=False,
                           indent=1) + "\n\n# Catalogue (CONCEPTS.md)\n\n" + (read_text(d / "CONCEPTS.md") or "(none)"))
    return await _run(go)


@server.tool(structured_output=False)
async def write_brief(poem: str, brief: str) -> str:
    """Write the poem's BRIEF.md (markdown, in the series' brief template shape). Replaces the old one.
    The poet reads it in the Art tab."""
    path = await _run(store.write_brief, poem, brief)
    return f"Wrote {path}"


@server.tool(structured_output=False)
async def set_slides(poem: str, slides: list[dict[str, Any]]) -> str:
    """Set the carousel: the slides in posting order, each {"concept": <built concept id>, ...params}.

    Example: [{"concept": "flare"}, {"concept": "plain"}, {"concept": "outside", "key": "out"},
    {"concept": "cast", "isolate": "outcast."}]. An optional "label" overrides the slide's display name.
    Params are passed to the concept as-is (see list_concepts)."""
    clean = await _run(store.set_slides, poem, slides)
    return "Slides set:\n" + "\n".join(f"{i}. {json.dumps(s, ensure_ascii=False)}" for i, s in enumerate(clean, 1))


@server.tool(structured_output=False)
async def render(poem: str, slide: int | None = None, format: str | None = None,
                 signed: bool | None = None) -> list:
    """Render the carousel with the series' kit: every slide in 1:1, 4:5 and 9:16, with and without
    the name, at 2x, plus the self-contained preview page and the contact sheet.

    Narrow it with slide (1-based), format ("1:1", "4:5" or "9:16") and signed (true = with name only,
    false = without). Returns the files and a picture of the result. Run qa afterwards."""
    def go():
        res = making.render(store, poem, slide=slide, format=format, signed=signed)
        folder = store.root / res["id"]
        images = [store.root / x for x in res["images"]]
        sheet = store.root / res["sheet"] if res["sheet"] else None
        lines = [f"Rendered {len(images)} images in {res['seconds']:.0f} s for {res['id']} (status: {res['status']}).",
                 f"Preview page: {store.root / res['page']}"]
        if sheet:
            lines.append(f"Contact sheet: {sheet}")
        lines += [f"  {x.relative_to(folder).as_posix()}" for x in images]
        if res["rest_stale"]:
            lines.append("Note: the text or slides changed since the last full render, so the images you didn't "
                         "re-render now show the old version. Render everything to bring them up to date.")
        lines.append("Next: run qa, and look at the picture.")
        pic = images[0] if res["partial"] and len(images) <= 2 else (sheet or images[0])
        return ["\n".join(lines), _preview(pic, 1100 if pic != sheet else 1600)]
    return await _run(go)


@server.tool(structured_output=False)
async def qa(poem: str, slide: int | None = None, format: str | None = None) -> str:
    """Measure the rendered images (on the ink, not the font boxes): margins, each row's left and right
    ink edges, which edges share a column and which miss one by a few px, story safe zones (9:16),
    text touching the frame, the smallest text at phone width (430 px), and whether the unsigned version
    differs from the signed one only in the name. Saves qa.json next to the poem; the poet sees a QA line per
    slide in the web view. Narrow it with slide (1-based) and format ("1:1", "4:5", "9:16")."""
    return (await _run(making.run_qa, store, poem, slide=slide, format=format))["summary"]


DESIGN_DOC = """A design saved in a format its series no longer uses keeps that layout until it's opened and saved in Studio.
A design is JSON: {"name", "format": "11"|"45"|"916" (1:1, 4:5, 9:16), "background": "#RRGGBB",
"elements": [...]} in slide pixels (1080 wide), drawn in order (later = on top). Elements:
- text: {"type":"text", "text": "lines\\nseparated by newlines", "font": a family name (default Newsreader), "weight": 100-900,
  "stretch": 62.5-125 (Archivo width, %), "italic": bool (Newsreader), "size": px, "leading": line gap / size,
  "tracking": thousandths of an em, "case": "upper"|"lower", "align": "left"|"center"|"right", "color": hex,
  "accent": hex for a closing full stop, "x": LEFT INK EDGE, "y": CAP TOP of the first line, "rotation": degrees}.
  Text sits on its ink, the way a series kit sets type: x/y are where the letters' ink starts, not the font box.
- rect / ellipse: {"x","y","w","h","fill","rotation"}, optional outline "stroke", "sw" (weight), "strokeAlign":
  "inside"|"center"|"outside"; "fill": null for no fill.
- shape: {"type":"shape", "kind": "polygon"|"star", "n": sides or points, "inner": 0-1 (star), "x","y","w","h", fill, outline}.
  The polygon or star is stretched to fill its box.
- path (pen): {"type":"path", "pts": [{"x","y", "ix","iy" (in-handle), "ox","oy" (out-handle)}], "closed": bool, fill, "stroke", "sw"}.
- line: {"x1","y1","x2","y2","stroke","width"}.
Colours (background, color, accent, fill, stroke) are "#RRGGBB" or a gradient:
  {"type": "linear"|"radial", "angle": degrees (linear; 0 = left to right, counter-clockwise), "stops": [{"c": "#RRGGBB", "p": 0-1}, ...]}.
Masks: "clip": true shows a layer only inside the nearest unclipped layer below it (its shape, or its letters for text);
"clipInvert": true shows it only outside. Groups: elements sharing "group": "<gid>", named in design "groups": {gid: {"name"}}.
Any element: "name" (layer name), "role": "name" (part of the signature: left out of the unsigned version),
"hidden", "locked", "hide": ["916"] (left out of those formats).
Every design exists in all three formats. Layout (x, y, w, h, x1..y2, pts, size, leading, tracking, stretch, weight,
rotation, align, width, sw) can differ per format: "at": {"11": {...}, "45": {...}, "916": {...}} overrides the element's
own values in that format; content, fonts and colours are shared. "format" is the format the editor opens in.
Fonts: set each text layer's "font" from the poem's style (read_poem -> style.fonts: display, text and label, each
with family, weight and width); any family Studio has is allowed (the bundled ones, the library's Styles/fonts and the
computer's fonts), and saving a design with an unknown family is refused with the list of available ones.
Colours: use the poem's style palette (read_poem -> style.palette.swatches) and the series info (read_poem -> series). A series' README may set rules (flat colour only,
for example); follow them."""


def unknown_fonts(design) -> list[str]:
    """Families of the design's text layers that Studio doesn't have (no font set means Newsreader, which it has)."""
    elements = (design.get("elements") or []) if isinstance(design, dict) else []
    return fonts.registry().resolve_missing(e.get("font") for e in elements
                                            if isinstance(e, dict) and e.get("type") == "text")


def _available_fonts(reg) -> str:
    out = ", ".join(sorted(f.name for f in reg.families()))
    n = len(reg.families(include_system=True)) - len(reg.families()) if reg.system_ready() else 0
    return out + (f", and {n} fonts on this computer" if n else "")


@server.tool(structured_output=False)
async def get_design(poem: str, design: str) -> str:
    """Read one of the poem's designs (made in Studio's Design tab or by you). See save_design for the format."""
    return json.dumps(await _run(store.read_design, poem, design), ensure_ascii=False, indent=1)


@server.tool(structured_output=False, description="""Create or replace a design in the poem's Design tab
(designs/<slug>.json). The poet sees it live and can refine it by hand; call render_design to see it. Without slug a new
design is made from its name.

""" + DESIGN_DOC)
async def save_design(poem: str, design: dict[str, Any], slug: str | None = None) -> str:
    bad = unknown_fonts(design)
    if bad:
        reg = fonts.registry()
        _err(f"Unknown fonts: {', '.join(bad)}. Available: {_available_fonts(reg)}")
    s2 = await _run(store.save_design, poem, design, slug)
    return f"Saved design {s2!r}. Render it with render_design to look at it."


@server.tool(structured_output=False)
async def render_design(poem: str, design: str) -> list:
    """Render a design to PNG with Chrome (2x, like the carousel) in 1:1, 4:5 and 9:16, with and without the name
    when it has a name layer: writes "Design renders/<slug>/" in the poem folder and returns a picture of each format."""
    def go():
        outs = shoot.export_design(store, _render_server(), poem, design)
        signed = [o for o in outs if not o.stem.endswith("-noname")]
        return ["Rendered:\n" + "\n".join(f"  {o}" for o in outs)] + [_preview(o, 900) for o in signed]
    return await _run(go)


_server_url = None


def _render_server():
    """Designs render from Studio's own page, so the MCP process runs a private web server for Chrome."""
    global _server_url
    if _server_url is None:
        import threading
        from .web import Handler, StudioServer
        Handler.store = store
        httpd = StudioServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        _server_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    return _server_url



def main():
    server.run()


if __name__ == "__main__":
    main()
