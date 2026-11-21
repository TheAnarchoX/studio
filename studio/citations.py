"""Citations and bibliography entries, formatted once for every output.

The PDF composer and the .docx export both ask this module, so a citation reads the same on the page and in Word.
Sources are CSL-JSON items as a book's `sources.json` keeps them. Two styles (`chicago` author-date, `apa`) and
two label languages (`en`, `nl`; anything else reads as `en`). An entry is a list of runs `(text, italic)` so each
output decides how to draw italics; nothing here knows about Typst or Word.
"""
import unicodedata

STYLES = ("chicago", "apa")

_LABELS = {
    "en": {"and": "and", "edited": "edited by", "accessed": "accessed", "nd": "n.d.", "pp": "pp.",
           "months": ("January", "February", "March", "April", "May", "June", "July", "August", "September",
                      "October", "November", "December")},
    "nl": {"and": "en", "edited": "onder redactie van", "accessed": "geraadpleegd op", "nd": "z.j.", "pp": "pp.",
           "months": ("januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september",
                      "oktober", "november", "december")},
}


def _labels(lang):
    return _LABELS.get(str(lang or "en").lower().split("-")[0], _LABELS["en"])


def _style(style):
    return style if style in STYLES else "chicago"


def _s(value):
    return str(value).strip() if value not in (None, "") else ""


# ---------------------------------------------------------------------------------------------------------
# Names

def _people(source, key=None):
    """The listed people of a source: the authors, or the editors when there are none (or when asked for)."""
    for k in ((key,) if key else ("author", "editor")):
        people = source.get(k)
        if isinstance(people, list):
            people = [p for p in people if isinstance(p, dict)]
            if people:
                return people
    return []


def cited_name(person) -> str:
    """"van Dijk": CSL keeps the particles apart from the family name, a citation says them together. A person
    with no family name is a `literal` (an organisation)."""
    if not person.get("family"):
        return _s(person.get("literal"))
    return " ".join(_s(person.get(k)) for k in ("dropping-particle", "non-dropping-particle", "family")
                    if _s(person.get(k)))


def _fold(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).casefold().strip()


def _year(source) -> str:
    try:
        year = source["issued"]["date-parts"][0][0]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(year) if year not in (None, "") else ""


def sort_key(source) -> tuple:
    """Bibliography order: family name without particles ("Dijk" for "van Dijk"), then given name, year, title;
    case and accents folded, so "Émile" sits among the Es."""
    people = _people(source)
    first = people[0] if people else {}
    family = first.get("family") or first.get("literal") or source.get("title") or source.get("id")
    return (_fold(family), _fold(first.get("given")), _year(source), _fold(source.get("title")))


def _given_form(person, apa):
    """The given name as written ("Anna"), or as initials in APA ("A.")."""
    given = _s(person.get("given"))
    if apa and given:
        given = " ".join(w if w.endswith(".") else w[0] + "." for w in given.replace("-", " ").split())
    return given


def _inverted(person, apa):
    """"Dijk, Anna van": family, given, then the particles that are said before the family name."""
    if not person.get("family"):
        return _s(person.get("literal"))
    tail = " ".join(x for x in (_given_form(person, apa), _s(person.get("dropping-particle")),
                                _s(person.get("non-dropping-particle"))) if x)
    return f"{_s(person['family'])}, {tail}" if tail else _s(person["family"])


def _natural(person, apa=False):
    """"Anna van Dijk", for names after the first."""
    if not person.get("family"):
        return _s(person.get("literal"))
    return " ".join(x for x in (_given_form(person, apa), cited_name(person)) if x)


def _join_names(names, word, comma_before_two=False):
    """"A", "A and B", "A, B, and C"; APA's ampersand takes a comma even after two names in a reference list."""
    if len(names) <= 1:
        return "".join(names)
    if len(names) == 2 and not comma_before_two:
        return f"{names[0]} {word} {names[1]}"
    return ", ".join(names[:-1]) + f", {word} {names[-1]}"


# ---------------------------------------------------------------------------------------------------------
# In-text citations

def _author_label(source, style, lang):
    people = _people(source)
    if not people:
        return _s(source.get("title")) or _s(source.get("id"))
    names = [cited_name(p) for p in people]
    if len(names) >= 4:
        return f"{names[0]} et al."
    return _join_names(names, "&" if _style(style) == "apa" else _labels(lang)["and"])


def cite_text(items, sources, style="chicago", lang="en") -> str:
    """`(see van Dijk 2019, p. 12)`; APA puts a comma before the year. Several items are joined with `; ` inside one
    pair of parentheses; an unknown key stands for itself. A source with authors and no year reads `n.d.` (`z.j.`);
    one known only by its editors or title is cited without a year, as part 1 of the book export did."""
    style = _style(style)
    by_id = {s.get("id"): s for s in sources or [] if isinstance(s, dict)}
    parts = []
    for item in items or []:
        key = str(item.get("key") or "")
        src = by_id.get(key)
        if src:
            year = _year(src) or (_labels(lang)["nd"] if _people(src, "author") else "")
            name = _author_label(src, style, lang)
            label = (f"{name}, {year}" if style == "apa" else f"{name} {year}") if year else name
        else:
            label = key
        text = f"{item['prefix']} {label}" if item.get("prefix") else label
        if item.get("locator"):
            text += f", {item['locator']}"
        parts.append(text)
    return "(" + "; ".join(parts) + ")"


# ---------------------------------------------------------------------------------------------------------
# Bibliography entries

def _date(value, lang):
    """A CSL date as "4 March 2020"; `date-parts`, `raw` and `literal` are all met in the wild."""
    if not isinstance(value, dict):
        return _s(value)
    try:
        parts = [int(x) for x in value["date-parts"][0]]
    except (KeyError, IndexError, TypeError, ValueError):
        return _s(value.get("raw") or value.get("literal"))
    out = [str(parts[0])]
    if len(parts) > 1 and 1 <= parts[1] <= 12:
        out.insert(0, _labels(lang)["months"][parts[1] - 1])
        if len(parts) > 2:
            out.insert(0, str(parts[2]))
    return " ".join(out)


def _merge(runs):
    out = []
    for text, italic in runs:
        if not text:
            continue
        if out and out[-1][1] == italic:
            out[-1] = (out[-1][0] + text, italic)
        else:
            out.append((text, italic))
    return out


def _stop(runs):
    """End a unit with a full stop unless it already ends in one (or in a closing quote, which holds it)."""
    runs = _merge(runs)
    if runs and runs[-1][0][-1] not in ".?!”":
        runs.append((".", False))
    return runs


def _authors(source, apa, lang):
    people = _people(source)
    if apa:
        return _join_names([_inverted(p, True) for p in people[:20]], "&", comma_before_two=True)
    return _join_names([_inverted(people[0], False)] + [_natural(p) for p in people[1:]], _labels(lang)["and"]) \
        if people else ""


def _imprint(source, apa):
    publisher, place = _s(source.get("publisher")), _s(source.get("publisher-place"))
    return f"{place}: {publisher}" if place and publisher and not apa else publisher


def entry(source, style="chicago", lang="en"):
    """One bibliography entry as runs `(text, italic)`. Books, reports and theses carry an italic title; articles
    a quoted title and an italic container; chapters sit `In *Container*, edited by …`; web pages end with the
    address and the date it was read. Anything else is laid out as a book."""
    apa = _style(style) == "apa"
    lab = _labels(lang)
    kind = source.get("type") or "book"
    title = _s(source.get("title"))
    container = _s(source.get("container-title"))
    pages = _s(source.get("page"))
    article = kind in ("article-journal", "article-magazine", "article-newspaper")
    chapter, web = kind == "chapter", kind == "webpage"
    quoted = (article or chapter or web) and not apa

    units = []
    names = _authors(source, apa, lang)
    if names:
        units.append(_stop([(names, False)]))
    year = _year(source) or lab["nd"]
    units.append(_stop([(f"({year})" if apa else year, False)]))

    if title:
        if quoted:
            units.append([(f"“{title}{'' if title[-1] in '.?!' else '.'}”", False)])
        elif (article or chapter) or (web and not apa):
            units.append(_stop([(title, False)]))
        else:
            units.append(_stop([(title, True)]))

    if article:
        volume, issue = _s(source.get("volume")), _s(source.get("issue"))
        if apa:
            number = volume + (f"({issue})" if issue and volume else "")
            tail = ", ".join(x for x in (number, pages) if x)
            tail = (", " if container and tail else "") + tail
        else:
            tail = " ".join(x for x in (volume, f"({issue})" if issue else "") if x)
            tail += ((": " if tail else "") + pages) if pages else ""
            tail = (" " if container and tail else "") + tail
        units.append(_stop([(container, True), (tail, False)]))
    elif chapter:
        run = [("In ", False), (container, True)]
        editors = _people(source, "editor")
        if editors:
            by = _join_names([_natural(p, apa) for p in editors], "&" if apa else lab["and"])
            run.append((f"{', ' if container else ''}{lab['edited']} {by}", False))
        if pages:
            run.append((f", {lab['pp']} {pages}" if apa else f", {pages}", False))
        units.append(_stop(run))
        if _imprint(source, apa):
            units.append(_stop([(_imprint(source, apa), False)]))
    elif web:
        if container:
            units.append(_stop([(container, apa)]))
    elif _imprint(source, apa):
        units.append(_stop([(_imprint(source, apa), False)]))

    if web:
        when = _date(source.get("accessed"), lang)
        if source.get("URL"):           # a stop after the address when the date it was read follows it
            url = [(_s(source["URL"]), False)]
            units.append(_stop(url) if when else url)
        if when:
            word = lab["accessed"]
            units.append(_stop([(f"{word[0].upper()}{word[1:]} {when}", False)]))

    runs = []
    for unit in units:
        if runs:
            runs.append((" ", False))
        runs.extend(unit)
    return _merge(runs)


def bibliography(sources, keys=None, style="chicago", lang="en"):
    """The entries for `keys` (every source when `None`) in bibliography order; keys with no source are left out."""
    sources = [s for s in sources or [] if isinstance(s, dict)]
    if keys is not None:
        by_id = {s.get("id"): s for s in sources}
        sources = [by_id[k] for k in dict.fromkeys(keys) if k in by_id]
    return [entry(s, style, lang) for s in sorted(sources, key=sort_key)]


# ---------------------------------------------------------------------------------------------------------
# Which sources are cited

def cited_keys(docs) -> list:
    """Source keys in order of first citation across ProseMirror documents, notes included."""
    found = []

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "cite":
            for item in (node.get("attrs") or {}).get("items") or []:
                key = item.get("key") if isinstance(item, dict) else None
                if key and key not in found:
                    found.append(key)
        for child in node.get("content") or []:
            walk(child)

    for doc in docs or []:
        walk(doc)
    return found
