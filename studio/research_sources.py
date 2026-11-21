"""Citation keys, labels and "the same source" for the research board: the Python twins of `sourceKey` in
book-tools.js and `sourceShort` in book-text.js, and the rule `Research.use` follows when a board's source joins a
book's sources.json."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from . import manuscript

_ARTICLES = {"de", "het", "een", "the", "a", "an"}


def _fold(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if not unicodedata.category(c).startswith("M")).lower()


def source_key(csl: dict, taken) -> str:
    """A new source's key: the first author's name (with its particle) or the title's first word, and the year; `b`,
    `c` … when taken. The same as `sourceKey` in book-tools.js."""
    people = csl.get("author") or csl.get("editor")
    p = people[0] if isinstance(people, list) and people and isinstance(people[0], dict) else None
    base = ""
    if p:
        base = re.sub(r"[^a-z0-9]", "", _fold("".join(filter(None, [p.get("non-dropping-particle"),
                                                                    p.get("family") or p.get("literal") or p.get("given")]))))
    if not base:
        base = next((w for w in re.split(r"[^a-z0-9]+", _fold(csl.get("title"))) if w and w not in _ARTICLES), "")
    parts = (csl.get("issued") or {}).get("date-parts") if isinstance(csl.get("issued"), dict) else None
    year = parts[0][0] if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0] else None
    base = (base or "source") + (re.sub(r"\D", "", str(year)) if year else "")
    key, n = base, 0
    while key in taken:
        key = base + (chr(98 + n) if n < 25 else f"-{n - 23}")
        n += 1
    return key


def _next_key(key: str, n: int) -> str:
    """The n-th key after a taken one (from 0): `b`, `c` … after a digit, as source_key; else `-2`, `-3` …"""
    if key[-1:].isdigit():
        return key + (chr(98 + n) if n < 25 else f"-{n - 23}")
    return f"{key}-{n + 2}"


def _person(p) -> str:
    """A person as cited: the family name with its particles ("van Dijk"), else the literal or given name."""
    if not isinstance(p, dict):
        return ""
    if p.get("family"):
        return " ".join(str(x) for x in (p.get("dropping-particle"), p.get("non-dropping-particle"), p.get("family")) if x)
    return str(p.get("literal") or p.get("given") or "")


def _year(csl: dict) -> str:
    issued = csl.get("issued")
    if not isinstance(issued, dict):
        return ""
    parts = issued.get("date-parts")
    first = parts[0][0] if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0] else None
    if first is not None:
        return str(int(first)) if isinstance(first, float) and first.is_integer() else str(first)
    return str(issued.get("literal") or issued.get("raw") or "")


def short_label(csl: dict) -> str:
    """A source as cited: `van Dijk 1998`, `Dijk & Vos 2001`, `Dijk et al. 2003`; with no author the title cut to 32
    characters; then the year. The twin of `sourceShort` in book-text.js."""
    if not isinstance(csl, dict):
        return ""
    people = csl.get("author") if isinstance(csl.get("author"), list) and csl.get("author") else csl.get("editor")
    names = [n for n in map(_person, people if isinstance(people, list) else []) if n]
    title = str(csl.get("title") or "").strip()
    who = f"{names[0]} et al." if len(names) > 2 else " & ".join(names) or (title[:31] + "…" if len(title) > 32 else title)
    return " ".join(x for x in (who, _year(csl)) if x)


def _url_key(u) -> str:
    if not isinstance(u, str) or not u.strip():
        return ""
    try:
        s = urlsplit(u.strip())
    except ValueError:
        return u.strip().rstrip("/")
    return urlunsplit((s.scheme.lower(), s.netloc.lower(), s.path, s.query, s.fragment)).rstrip("/")


def same_source(a: dict, b: dict) -> bool:
    """Two CSL items for one source: equal apart from their keys; the same URL (the host in any case, with or without
    a closing /); or the same title (without case, accents and spacing) and the same first year."""
    if {k: v for k, v in a.items() if k != "id"} == {k: v for k, v in b.items() if k != "id"}:
        return True
    ua = _url_key(a.get("URL"))
    if ua and ua == _url_key(b.get("URL")):
        return True
    ta, tb = (re.sub(r"\s+", "", _fold(x.get("title"))) for x in (a, b))
    return bool(ta) and ta == tb and _year(a) == _year(b)


def _first_name(csl: dict) -> str:
    """The first author's (else editor's) family name, else literal name, without case, accents and spacing."""
    people = csl.get("author") if isinstance(csl.get("author"), list) and csl.get("author") else csl.get("editor")
    p = people[0] if isinstance(people, list) and people and isinstance(people[0], dict) else None
    return re.sub(r"\s+", "", _fold(p.get("family") or p.get("literal"))) if p else ""


def same_work(a: dict, b: dict) -> bool:
    """Two CSL items under one key for one work, whatever their titles say (the author corrected it in sources.json):
    the same type, the same first author's family name and the same year."""
    name = _first_name(a)
    return bool(name) and a.get("type") == b.get("type") and name == _first_name(b) and _year(a) == _year(b)


def _cite_key(value) -> bool:
    return isinstance(value, str) and manuscript.CITE_KEY.fullmatch(value) is not None
