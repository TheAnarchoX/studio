"""Styles endpoints: the font registry (families, @font-face rules and the font files)."""
import base64

from . import config, examples, fonts, routes, styles
from .store import StoreError


def _used_system(h, reg):
    """The computer's families that any design in the library uses (once the system index is loaded)."""
    return reg.system_used(h.store.fonts_in_designs()) if reg.system_ready() else []


@routes.get("/api/fonts")
def fonts_json(h, q):
    reg = fonts.registry()
    h._send(200, reg.to_json(extra=_used_system(h, reg)))


@routes.get("/api/fonts.css")
def fonts_css(h, q):
    reg = fonts.registry()
    h._send(200, reg.css(q.get("display", "block"), extra=_used_system(h, reg)).encode("utf-8"), ctype="text/css; charset=utf-8")


@routes.post("/api/fonts/add")
def fonts_add(h, body):
    items = []
    for f in body.get("files") if isinstance(body.get("files"), list) else []:
        name = f.get("name") if isinstance(f, dict) else None
        if not isinstance(name, str) or not isinstance(f.get("data"), str):
            raise StoreError("Choose one or more font files.")
        try:
            items.append((name, base64.b64decode(f["data"], validate=True)))
        except ValueError:
            raise StoreError(f"{name} couldn't be read.") from None
    h._send(200, fonts.add_files(items))


@routes.post("/api/fonts/update")
def fonts_update(h, body):
    h._send(200, fonts.update_family(body.get("family"), {k: body[k] for k in ("category", "license") if k in body}))


@routes.post("/api/fonts/remove")
def fonts_remove(h, body):
    name = body.get("family")
    reg = fonts.registry()
    fam = reg.get(name) if isinstance(name, str) else None
    used = len(h.store.designs_using_font(fam.name)) if fam and fam.source in ("file", "google") else 0
    styled = len(h.store.styles_using_font(fam.name)) if fam and fam.source in ("file", "google") else 0
    fonts.remove_family(name, used=used, force=bool(body.get("force")), styled=styled)
    h._send(200, {"ok": True})


@routes.get("/api/fonts/google")
def fonts_google(h, q):
    """Search the Google Fonts catalogue by name and category; at most 60 results."""
    needle, cat = q.get("q", "").strip().lower(), q.get("category", "").strip().lower()
    found = [f for f in fonts.google_catalog() if needle in f["family"].lower() and (not cat or f["category"] == cat)]
    h._send(200, found[:60])


@routes.post("/api/fonts/google/add")
def fonts_google_add(h, body):
    h._send(200, fonts.add_google(body.get("family")))


@routes.get("/api/fonts/system")
def fonts_system(h, q):
    """The computer's own fonts; {"indexing": true} until the background index is built."""
    reg = fonts.registry()
    reg.start_system_index()
    h._send(200, reg.system_json() if reg.system_ready() else {"indexing": True})


@routes.get_prefix("/fonts/")
def font_file(h, rest, q):
    """Only files the registry has indexed: bundled and library files by their path, the computer's fonts by id."""
    found = fonts.registry().open("/fonts/" + rest, q.get("face"))
    if found is None:
        return h._send(404, {"error": "not found"})
    data, ctype = found
    h._send(200, data, ctype)


# ——— palettes, looks and rules ———

@routes.get("/api/styles")
def styles_json(h, q):
    st = h.store.styles
    h._send(200, {"looks": st.looks(), "palettes": st.palettes(), "rules": st.rules(), "default_look": config.DEFAULT_LOOK,
                  "used": h.store.styles_used()})


@routes.post("/api/styles/palette")
def palette_save(h, body):
    h._send(200, h.store.styles.save_palette(body.get("palette")))


@routes.post("/api/styles/palette/delete")
def palette_delete(h, body):
    h.store.styles.delete_palette(body.get("name"))
    h._send(200, {"ok": True})


@routes.post("/api/styles/look")
def look_save(h, body):
    h._send(200, h.store.styles.save_look(body.get("look")))


@routes.post("/api/styles/look/delete")
def look_delete(h, body):
    h.store.styles.delete_look(body.get("name"))
    h._send(200, {"ok": True})


@routes.post("/api/styles/rules")
def rules_save(h, body):
    h._send(200, h.store.styles.save_rules(body.get("text")))


@routes.post("/api/palette/from-image")
def palette_from_image(h, body):
    try:
        data = base64.b64decode(body.get("data") or "", validate=True)
    except (ValueError, TypeError):
        raise StoreError("Studio can't read that image. Try a PNG or JPEG.") from None
    h._send(200, {"swatches": styles.palette_from_image(data)})


@routes.post("/api/series/style")
def series_style(h, body):
    keys = ("look", "palette", "fonts", "detach", "link")
    h._send(200, h.store.update_series(body.get("name"), {k: body[k] for k in keys if k in body}))


@routes.post("/api/poem/style")
def poem_style(h, body):
    h._send(200, h.store.update_poem_style(body.get("id"), {k: body[k] for k in ("look", "palette", "fonts", "clear") if k in body}))


@routes.post("/api/poem/details")
def poem_details(h, body):
    h._send(200, h.store.update_poem_details(body.get("id"), {k: body[k] for k in ("author",) if k in body}))


@routes.get("/api/series/colours")
def series_colours(h, q):
    h._send(200, styles.colours_used(h.store.series_design_files(q.get("name", ""))))


# ——— examples ———

@routes.post("/api/examples")
def examples_add(h, body):
    made = examples.add(h.store, h.store.styles)
    h._send(200, {"added": len(made)})


@routes.post("/api/examples/remove")
def examples_remove(h, body):
    moved = examples.remove(h.store)
    h._send(200, {"removed": len(moved)})
