"""The book's design as data: templates per kind, trim sizes, validation and resolution.

`book.json` keeps only what the author changed (`design`); `resolve` fills in the rest from the template, so switching
templates moves everything not set by hand. Lengths are millimetres, type sizes points. Nothing here knows about Typst:
the composer turns the resolved design into pages. Errors are `BooksError` with plain sentences, as everywhere else.
"""
from __future__ import annotations

import copy

from . import citations, config

TRIMS = {"a5": (148, 210), "135x210": (135, 210), "5.5x8.5in": (139.7, 215.9), "6x9in": (152.4, 228.6)}
TRIM_NAMES = {"a5": "A5 · 148 × 210 mm", "135x210": "135 × 210 mm", "5.5x8.5in": "5.5 × 8.5 in", "6x9in": "6 × 9 in"}

KIND_TEMPLATE = {"fiction": "literary", "memoir": "literary", "essays": "literary", "nonfiction": "nonfiction",
                 "academic": "academic", "poetry": "poetry"}

LABELS = {
    "en": {"toc": "Contents", "notes": "Notes", "bibliography": "Bibliography", "index": "Index",
           "first-lines": "Index of first lines", "part": "Part", "chapter": "Chapter"},
    "nl": {"toc": "Inhoud", "notes": "Noten", "bibliography": "Bibliografie", "index": "Register",
           "first-lines": "Register van beginregels", "part": "Deel", "chapter": "Hoofdstuk"},
}
RIGHTS = {
    "en": "All rights reserved. No part of this book may be reproduced in any form without written permission from "
          "the author.",
    "nl": "Alle rechten voorbehouden. Niets uit deze uitgave mag worden verveelvoudigd, opgeslagen in een "
          "geautomatiseerd gegevensbestand of openbaar gemaakt, in enige vorm of op enige wijze, zonder voorafgaande "
          "schriftelijke toestemming van de auteur.",
}

# The text font stays None here: the book's look supplies it when the design is resolved. The trim and margins shown
# are the 135 × 210 defaults; `resolve` recomputes them from the book's language and trim.
_LITERARY = {
    "template": "literary",
    "trim": "135x210", "width": 135, "height": 210,
    "printer": "other", "paper": "cream", "interior": "grey",
    "margins": {"inside": 19, "outside": 15, "top": 18, "bottom": 23},
    "text": {"font": None, "weight": None, "size": 10.5, "line": 14.5, "align": "justify", "hyphenate": True,
             "paragraph": "indent"},
    "headings": {"font": None, "size": 18, "case": "as-written", "number": "none", "sections": "plain", "sink": 42,
                 "start": "right", "opening": "smallcaps"},
    "heads": {"verso": "title", "recto": "piece", "style": "smallcaps", "folio": "bottom-centre"},
    "poems": {"place": "optical-centre", "keepStanzas": True},
    "scene": "asterisks",
    "notes": {"size": 8.5, "pageRefs": True},
    "citations": {"style": "chicago", "list": "cited"},
    "pages": {"labels": {}, "contentsSections": False, "leaders": False, "setIn": True},
}


def _variant(name, **sections):
    out = copy.deepcopy(_LITERARY)
    out["template"] = name
    for k, v in sections.items():
        out[k].update(v)
    return out


TEMPLATES = {
    "literary": {"name": "Literary", **_LITERARY},
    "nonfiction": {"name": "Nonfiction", **_variant("nonfiction", headings={"number": "digits"},
                                                    pages={"contentsSections": True})},
    "academic": {"name": "Academic", **_variant("academic", text={"size": 10, "line": 13.5}, notes={"size": 8},
                                                headings={"start": "next", "sink": 24, "sections": "numbered",
                                                          "opening": "none"})},
    "poetry": {"name": "Poetry", **_variant("poetry", heads={"recto": "none"},
                                            headings={"sink": 30, "opening": "none", "start": "next"})},
}


def _error(message):
    from .books import BooksError       # books imports this module; the error class lives there
    return BooksError(message)


# ——— values: each checker returns the clean value or raises ValueError(plain sentence) ———
def _or(options):
    options = [str(o) for o in options]
    return ", ".join(options[:-1]) + " or " + options[-1] if len(options) > 1 else options[0]


def _enum(*options, what):
    def check(v):
        if not isinstance(v, str) or v not in options:
            raise ValueError(f"The {what} is " + _or(options) + ".")
        return v
    return check


def _num(lo, hi, what, unit):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise ValueError(f"The {what} is {lo:g} to {hi:g} {unit}.")
        return v
    return check


def _bool(what):
    def check(v):
        if not isinstance(v, bool):
            raise ValueError(f"The {what} setting is on or off.")
        return v
    return check


def _family(what, null=False):
    def check(v):
        if v is None and null:
            return None
        v = " ".join(v.split()) if isinstance(v, str) else ""
        if not v or len(v) > 100:
            raise ValueError(f"The {what} is a font family name.")
        return v
    return check


def _weight(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 100 <= v <= 900 or v != int(v):
        raise ValueError("The font weight is 100 to 900.")
    return int(v)


def _labels(v):
    if not isinstance(v, dict):
        raise ValueError("The page names are an object.")
    out = {}
    for k, text in v.items():
        if k not in LABELS["en"]:
            raise ValueError("The page name " + str(k)[:40] + " is not one Studio uses.")
        if not isinstance(text, str) or len(text.strip()) > 60:
            raise ValueError("A page name is text of up to 60 characters.")
        out[k] = text.strip()
    return out


_SECTIONS = {
    "margins": {"inside": _num(5, 60, "inside margin", "mm"), "outside": _num(5, 60, "outside margin", "mm"),
                "top": _num(5, 60, "top margin", "mm"), "bottom": _num(5, 60, "bottom margin", "mm")},
    "text": {"font": _family("text font"), "weight": _weight, "size": _num(7, 16, "text size", "pt"),
             "line": _num(7, 40, "line height", "pt"), "align": _enum("justify", "left", what="text alignment"),
             "hyphenate": _bool("hyphenation"), "paragraph": _enum("indent", "space", what="paragraph style")},
    "headings": {"font": _family("heading font", null=True), "size": _num(8, 48, "heading size", "pt"),
                 "case": _enum("as-written", "smallcaps", "caps", what="heading case"),
                 "number": _enum("none", "digits", "words", "roman", what="chapter numbering"),
                 "sections": _enum("plain", "numbered", what="section numbering"),
                 "sink": _num(0, 120, "chapter sink", "mm"),
                 "start": _enum("right", "next", what="chapter start"),
                 "opening": _enum("smallcaps", "none", what="chapter opening")},
    "heads": {"verso": _enum("title", "author", "none", what="left running head"),
              "recto": _enum("piece", "title", "none", what="right running head"),
              "style": _enum("smallcaps", "italic", what="running head style"),
              "folio": _enum("bottom-centre", "bottom-outside", "top-outside", what="page number place")},
    "poems": {"place": _enum("optical-centre", "left", what="poem place"), "keepStanzas": _bool("keep stanzas")},
    "notes": {"size": _num(6, 12, "note size", "pt"), "pageRefs": _bool("page references")},
    "citations": {"style": _enum(*citations.STYLES, what="citation style"),
                  "list": _enum("cited", "all", what="bibliography list")},
    "pages": {"labels": _labels, "contentsSections": _bool("contents sections"), "leaders": _bool("dot leaders"),
              "setIn": _bool("set-in note")},
}
_SCALARS = {
    "trim": _enum(*TRIMS, "custom", what="trim size"),
    "width": _num(90, 250, "page width", "mm"), "height": _num(120, 330, "page height", "mm"),
    "printer": _enum("kdp", "ingramspark", "other", what="printer"),
    "paper": _enum("white", "cream", what="paper"), "interior": _enum("grey", "colour", what="interior"),
    "scene": _enum("asterisks", "asterism", "space", what="scene break"),
}


def _primary(language) -> str:
    return str(language or "en").strip().lower().split("-")[0] or "en"


def _round_half(v):
    return round(v * 2) / 2


def _stored_ok(check, given, key):
    """The stored value for `key` when it passes `check`, else a marker meaning 'not usable'."""
    if key not in given:
        return _MISSING
    try:
        return check(given[key])
    except ValueError:
        return _MISSING


_MISSING = object()


def _is_template(v) -> bool:
    return isinstance(v, str) and v in TEMPLATES


def resolve(meta: dict, look: dict) -> dict:
    """The complete design for this book. Never raises: a stored value that is not allowed falls back to the template's."""
    stored = meta.get("design") if isinstance(meta.get("design"), dict) else {}
    kind = meta.get("kind") if isinstance(meta.get("kind"), str) else ""      # hand-edited files can hold anything
    name = stored["template"] if _is_template(stored.get("template")) else KIND_TEMPLATE.get(kind, "literary")
    out = copy.deepcopy(TEMPLATES[name])
    out.pop("name", None)
    language = str(meta.get("language") or "en").strip().lower()

    for key in ("printer", "paper", "interior", "scene"):
        v = _stored_ok(_SCALARS[key], stored, key)
        if v is not _MISSING:
            out[key] = v
    for section, checks in _SECTIONS.items():
        given = stored.get(section)
        if isinstance(given, dict):
            for key, check in checks.items():
                v = _stored_ok(check, given, key)
                if v is not _MISSING:
                    out[section][key] = v

    # the trim: a stored one wins; otherwise the language's usual size
    trim = _stored_ok(_SCALARS["trim"], stored, "trim")
    width, height = _stored_ok(_SCALARS["width"], stored, "width"), _stored_ok(_SCALARS["height"], stored, "height")
    if trim == "custom" and (width is _MISSING or height is _MISSING):
        trim = _MISSING
    if trim is _MISSING:
        trim = "5.5x8.5in" if language == "en" or language.startswith("en-") else "135x210"
    out["trim"] = trim
    out["width"], out["height"] = (width, height) if trim == "custom" else TRIMS[trim]

    # margins follow the trim unless the author set them
    w, h = out["width"], out["height"]
    defaults = {"inside": 0.14 * w, "outside": 0.11 * w, "top": 0.085 * h, "bottom": 0.11 * h}
    given = stored.get("margins") if isinstance(stored.get("margins"), dict) else {}
    for key, value in defaults.items():
        v = _stored_ok(_SECTIONS["margins"][key], given, key)
        out["margins"][key] = _round_half(value) if v is _MISSING else v

    # the text font and weight default to the book's look
    text = out["text"]
    font = ((look or {}).get("fonts") or {}).get("text") or {}
    if text["font"] is None:
        text["font"] = font.get("family") or "Source Serif 4"
    if text["weight"] is None:
        text["weight"] = font["weight"] if isinstance(font.get("weight"), int) and 100 <= font["weight"] <= 900 \
            else 400
    # a line height must suit the size: pull a stored size or line that no longer fits back into range
    text["line"] = min(max(text["line"], text["size"]), 2.5 * text["size"])

    labels = dict(LABELS.get(_primary(language), LABELS["en"]))
    pages = stored.get("pages") if isinstance(stored.get("pages"), dict) else {}
    for k, v in (pages.get("labels") if isinstance(pages.get("labels"), dict) else {}).items():
        try:                                    # entry by entry: one bad rename does not void the others
            labels.update({a: b for a, b in _labels({k: v}).items() if b})
        except (ValueError, TypeError):
            pass
    out["pages"]["labels"] = labels
    out["rights"] = RIGHTS.get(_primary(language), RIGHTS["en"])
    return out


def _check(check, value):
    try:
        return check(value)
    except ValueError as e:
        raise _error(str(e)) from None


def clean(stored: dict, changes: dict) -> dict:
    """The stored design after a partial change: nested sections merged, every known value checked. Unknown keys stay.

    `None` for a known value takes the stored one away, so the template speaks again (a heading font of null is a
    value of its own: it means the text font)."""
    stored = copy.deepcopy(stored) if isinstance(stored, dict) else {}
    if not isinstance(changes, dict):
        raise _error("The design is an object.")
    for key, value in changes.items():
        if key == "template":
            if not _is_template(value):
                raise _error("The template is " + _or(list(TEMPLATES)) + ".")
            stored["template"] = value
        elif key in _SCALARS:
            if value is None:
                stored.pop(key, None)
            else:
                stored[key] = _check(_SCALARS[key], value)
        elif key in _SECTIONS:
            if not isinstance(value, dict):
                raise _error(f"The {key} setting is an object.")
            section = dict(stored[key]) if isinstance(stored.get(key), dict) else {}
            for sub, v in value.items():
                check = _SECTIONS[key].get(sub)
                if check is None:
                    section[sub] = v
                elif key == "pages" and sub == "labels":
                    labels = dict(section["labels"]) if isinstance(section.get("labels"), dict) else {}
                    for k, text in _check(check, v).items():
                        if text:
                            labels[k] = text
                        else:
                            labels.pop(k, None)          # an empty name is the default again
                    section["labels"] = labels
                elif v is None and not (key == "headings" and sub == "font"):
                    section.pop(sub, None)
                else:
                    section[sub] = _check(check, v)
            stored[key] = section
        else:
            stored[key] = value
    if stored.get("trim") == "custom" and not all(isinstance(stored.get(k), (int, float)) for k in ("width", "height")):
        raise _error("A custom trim needs a width and a height.")
    text = stored.get("text") if isinstance(stored.get("text"), dict) else {}
    if "line" in text:
        size = text.get("size")
        if not isinstance(size, (int, float)):
            template = stored["template"] if _is_template(stored.get("template")) else "literary"
            size = TEMPLATES[template]["text"]["size"]
        if not size <= text["line"] <= 2.5 * size:
            raise _error(f"The line height is {size:g} to {2.5 * size:g} pt at this text size.")
    return stored


def reset(stored: dict, sections: list[str] | str) -> dict:
    """Back to the template: "all" keeps only the template; otherwise the named parts go (`trim` takes its size along)."""
    stored = copy.deepcopy(stored) if isinstance(stored, dict) else {}
    if sections == "all":
        return {"template": stored["template"]} if "template" in stored else {}
    if isinstance(sections, str):
        sections = [sections]
    if not isinstance(sections, (list, tuple)) or not all(isinstance(s, str) for s in sections):
        raise _error("Name the parts of the design to reset.")
    for s in sections:
        if s != "template":
            stored.pop(s, None)
        if s == "trim":
            stored.pop("width", None)
            stored.pop("height", None)
    return stored


# ——— spelling ———
def spelling(meta: dict) -> dict:
    """The book's spelling settings as the editor uses them; the file keeps what was stored."""
    own = _primary(meta.get("language"))
    given = meta.get("spelling") if isinstance(meta.get("spelling"), dict) else {}
    langs = given.get("languages") if isinstance(given.get("languages"), list) else []
    languages = [x for x in langs if isinstance(x, str) and config.LANGUAGE_TAG.fullmatch(x)]
    if not languages:
        languages = [own] + ([] if own == "en" else ["en"])
    elif _primary(languages[0]) != own:         # the first is always the book's own, even after the language changed
        languages = [own] + [x for x in languages if _primary(x) != own]
    words = given.get("words") if isinstance(given.get("words"), list) else []
    return {"languages": languages[:4], "words": [w for w in words if isinstance(w, str)]}


def clean_spelling(given) -> dict:
    """The parts of a spelling change that were given, checked: 1 to 4 language codes and up to 5,000 words."""
    if not isinstance(given, dict):
        raise _error("The spelling is an object.")
    out = {}
    if "languages" in given:
        langs = given["languages"]
        if not (isinstance(langs, list) and 1 <= len(langs) <= 4 and all(
                isinstance(x, str) and config.LANGUAGE_TAG.fullmatch(x.strip()) for x in langs)):
            raise _error("The spelling languages are one to four codes like nl or en.")
        seen, out["languages"] = set(), []
        for x in (x.strip() for x in langs):
            if x.lower() not in seen:
                seen.add(x.lower())
                out["languages"].append(x)
    if "words" in given:
        words = given["words"]
        if not isinstance(words, list) or len(words) > 5000:
            raise _error("The word list holds up to 5,000 words.")
        seen, out["words"] = set(), []
        for w in words:
            w = w.strip() if isinstance(w, str) else ""
            if not w or len(w) > 60 or any(c.isspace() for c in w):
                raise _error("A word in the list is one word of up to 60 characters.")
            if w not in seen:
                seen.add(w)
                out["words"].append(w)
    return out
