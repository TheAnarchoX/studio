"""The Examples a fresh install can add (and take away again): a series of two short poems with a design each, and an
example book (add_book / remove_books, hooked into EXTRA / EXTRA_REMOVE at the end of this file).

The series is marked "example": true in its series.json, so removing finds it without a name. Removing moves
folders to Poems/.trash/ (the book to Books/.trash/); nothing is destroyed. EXTRA / EXTRA_REMOVE are zero-argument callables that add or
remove more examples (they return the paths they made or moved)."""
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import config, styles
from .books import Books
from .store import StoreError, folder_name, write_text

SERIES = "Examples"
TAGLINE = "Two short poems to try Studio with."
LOOK = "Editorial light"
POEMS = [
    ("Morning, Unfinished", ["The kettle starts before I do.", "The window holds a grey it hasn't named.",
                             "I write one line and leave it open,", "like a door for the day to come through."]),
    ("What the River Keeps", ["Stones, mostly. A shoe.", "The shape of every bridge, upside down.",
                              "Whatever you tell it,", "it carries a little further."]),
]
README = """# Examples

Two short poems to try Studio with. Delete the series whenever you like (Settings, Remove examples).

## The rules

- **Palette and type:** they follow the look, so changing the look changes every poem here.
- **Words:** only the poem's own words and the name.
- **Formats:** each poem has a 4:5 design to start from; add 1:1 and 9:16 from the Design tab.
"""

EXTRA: list[Callable[[], list[Path]]] = []
EXTRA_REMOVE: list[Callable[[], list[Path]]] = []

W, H, SAFE_T, SAFE_B, SIDE = 1080, 1350, 112, 112, 88 + 32


def _design(title, lines, look, pal, signature):
    f = look["fonts"]
    colour = styles.colours(pal)        # by role, else by place: the library's own copy of the palette may have no roles
    size, leading = 50, 1.4
    block, sig_size, gap = len(lines) * size * leading, 26, 56
    y = SAFE_T + (H - SAFE_T - SAFE_B - block - gap - sig_size * 1.15) / 2

    def font(role):
        x = f[role]
        out = {"font": x["family"], "weight": int(x.get("weight") or 400)}
        if x.get("width"):
            out["stretch"] = x["width"]
        return out
    poem = {"id": "poem", "type": "text", "name": "Poem", "text": "\n".join(lines), **font("text"), "size": size,
            "leading": leading, "tracking": 0, "color": colour["text"], "x": SIDE, "y": round(y, 1)}
    name = {"id": "name", "type": "text", "role": "name", "name": "Name", "text": signature or "Your name", **font("label"),
            "size": sig_size, "tracking": 220, "case": "upper", "leading": 1.15, "color": colour["muted"], "x": SIDE,
            "y": round(y + block + gap, 1)}
    return {"name": title, "format": "45", "background": colour["background"], "elements": [poem, name]}


def example_dirs(store):
    out = []
    for d in store.series_dirs():
        try:
            if json.loads((d / "series.json").read_text(encoding="utf-8")).get("example") is True:
                out.append(d)
        except (OSError, ValueError, AttributeError):
            pass
    return out


def add(store, library, signature=None):
    """Make the Examples series (`library` is the store's Styles). Returns the paths made; [] when the series already
    exists. When something fails part-way, the half-made series is taken away again and the error raised."""
    if (store.root / SERIES).exists():
        return []
    signature = config.SIGNATURE if signature is None else signature
    look = library.look(LOOK)
    pal = library.palette(look["palette"])
    d = store.root / SERIES
    store.create_series(SERIES, TAGLINE, look=LOOK)     # fails, and takes nothing away, when another add() just made it
    try:
        meta = store.series_json(d)
        meta["example"] = True
        store.write_series(d, meta)
        write_text(d / "README.md", README)
        made = [d]
        for title, lines in POEMS:
            p = store.create(title, SERIES)
            store.save_text(p["id"], title, "\n".join(lines))
            store.save_design(p["id"], _design(title, lines, look, pal, signature), slug="page")
            made.append(store.resolve(p["id"]))
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)     # made by this call's create_series: nothing of anyone's is in it
        raise
    try:
        made += add_book(Books(store.root.parent / "Books"))      # the library of this store, never the configured one
        for fn in EXTRA:
            made += fn()
    except BaseException:
        for path in made:           # all made by this call a moment ago: the whole add is taken away, so it can be run again
            shutil.rmtree(path, ignore_errors=True)
        raise
    return made


def _trash(store, folder):
    trash = store.root / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{folder.name} {datetime.now().strftime('%Y-%m-%d %H%M%S')}"
    for attempt in range(10):
        try:
            os.replace(folder, dest)
            return dest
        except PermissionError:
            if attempt == 9:
                raise StoreError("Windows won't let go of a file in the examples (is it open somewhere?). Try again.") from None
            time.sleep(.2)


def remove(store):
    """Move every example series to Poems/.trash/. Returns where they went."""
    moved = [_trash(store, d) for d in example_dirs(store)]
    moved += remove_books(Books(store.root.parent / "Books"))
    for fn in EXTRA_REMOVE:
        moved += fn()
    return moved


# ——— the example book ———

BOOK_TITLE = "A Year of Small Things"
BOOK_LOOK = "Warm linen"
SOURCES = [{"id": "field-notes", "type": "book", "title": "Field Notes", "author": [{"family": "Example", "given": "An"}],
            "issued": {"date-parts": [[2026]]}}]
# (kind, form, title, Markdown in the manuscript dialect)
BOOK_PIECES = [
    ("dedication", "prose", "", "For whoever finds this useful.\n"),
    ("foreword", "prose", "Foreword", """# Foreword

This is an example book. It is here so you can see what a book looks like in Studio before you write one of your own: a dedication, a foreword, two chapters and a poem, set in a look called Warm linen.

Everything in it is invented. Change a word and the page changes with it; delete a piece and the book closes up around the gap. Nothing here is precious, and the whole book moves to the trash when you choose Remove examples in Settings.

A book is mostly patience.^[This is a note. In a memoir, notes are gathered at the back of the book and numbered by chapter; you can move them to the foot of each page in the book's settings.] The pages add up slowly, a few lines on a good day and none on the others, and what you end up holding is a record of having kept going. Small habits are what carry it, as the field guide in the sources puts it [@field-notes, p. 4].

Open the settings to see where this book keeps its look, its notes and its list of sources.
"""),
    ("chapter", "prose", "The Kitchen Table", """# The Kitchen Table

The table was older than the house. Someone had carried it in through the window, the story went, because the door was too narrow, and no one had thought to ask whether it would ever come out again.

Mornings began there. The kettle, a chipped blue cup, the radio turned low enough not to wake the street. I would sit with a notebook open and write down whatever had happened since the night before, which was usually nothing, and that was the point. A page of nothing, written down, turned out to be a good place to start.

***

By spring the notebook was half full. I had written about the neighbour's [bicycle]{.idx}, about the way the light crossed the floor at ten past eight, about a soup that failed and a soup that did not. None of it was important. All of it was mine, and I found I was reluctant to stop.
"""),
    ("chapter", "prose", "A Walk in March", """# A Walk in March

On the first mild day I went out without a plan. The path behind the allotments was still soft, and every puddle held a small, clean piece of sky.

I noticed things I had walked past all winter. A gate that had been painted green a long time ago and never again. A wall with a lemon-coloured moss on its north side. Two children arguing, very seriously, about whether a stick was a sword or a bridge, and arriving at a treaty in which it was both.

It is easy to believe that a year is made of large events. Mine was made of gates and puddles and good soup, of bread that rose, of a letter that arrived on a day I had stopped expecting it. When I tried to describe the year to a friend, I found I could only list these things, one after another, and that the list was enough.
"""),
    ("chapter", "poem", "What Was Kept", """# What Was Kept

A gate, painted once.
A cup with a chip.
The sound of the kettle
before the street wakes.

A page of nothing
written down carefully.
A stick that was a sword
and then a bridge.

Soup, and the other soup.
Bread, rising.
A letter on the day
I had stopped waiting.

Rain on the allotment path,
every puddle a piece of sky.
Moss the colour of a lemon
on the shady side of a wall.

A year can be made of this:
small things, kept in order,
each one set down gently
so that it can be found again.

None of it large.
All of it here.
Set it on the table
and see how it holds.
"""),
]


def _example_books(books):
    out = []
    for d in books.dirs():
        try:
            if json.loads((d / "book.json").read_text(encoding="utf-8-sig")).get("example") is True:
                out.append(d)
        except (OSError, ValueError, AttributeError):
            pass
    return out


def add_book(books):
    """Make the example book in Books/ (written through Books, so it is canonical). Returns [its folder]; [] when an
    example book already exists or the folder name is taken by another book. When something fails part-way the half-made folder is taken away again."""
    if _example_books(books) or (books.root / folder_name(BOOK_TITLE)).exists():
        return []       # already there, or the poet has a book of that title of their own: left alone
    book = books.create(BOOK_TITLE, author="Studio", language="en", kind="memoir", look=BOOK_LOOK, start=False)
    d = books.dir(book["id"])
    try:
        meta_file = d / "book.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta["example"] = True
        write_text(meta_file, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        for kind, form, title, md in BOOK_PIECES:
            piece = books.new_piece(book["id"], kind, form=form, title=title)
            books.save_piece(book["id"], piece["file"], md=md)
        books.save_sources(book["id"], SOURCES)
        pieces = [e for e in books.read(book["id"])["contents"] if e.get("file")]
        contents = [{"auto": a} for a in ("half-title", "title-page", "copyright")]
        contents += [{"file": e["file"], "kind": e["kind"], "form": e["form"], "status": "final"} for e in pieces[:1]]
        contents.append({"auto": "toc"})
        contents += [{"file": e["file"], "kind": e["kind"], "form": e["form"], "status": "final"} for e in pieces[1:]]
        contents += [{"auto": a} for a in ("notes", "bibliography")]
        books.update(book["id"], {"features": {"sources": True}, "contents": contents})
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)     # made by this call's create a moment ago
        raise
    return [d]


def remove_books(books):
    """Move every example book to Books/.trash/. Returns where they went."""
    return [books.delete_book(d.name) for d in _example_books(books)]
