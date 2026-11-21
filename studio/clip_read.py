"""The readable copy of a web page: its details and its text as Markdown, read with the standard library's HTML parser.

`readable(html, url)` is the only entry point (clip.py re-exports it). How it works, in order:

1. The page is parsed into a small tree, closing what browsers close without an end tag (a <p> before a block, an
   <li> before the next one).
2. The details are read from the whole tree: the title (og:title, then <title> without a " | Site" tail), the site
   (og:site_name, then the host without www.), the author (the author and article:author meta, then JSON-LD), the date
   published (article:published_time, then JSON-LD datePublished, then the first <time datetime>), the language and
   the canonical address.
3. What is never the text is dropped: scripts, styles, navigation, headers, footers, asides, forms, menus, dialogs,
   hidden elements, and the images, tables and embeds the copy leaves out (the picture shows them).
4. The text's root is chosen: the <article> with the most text; else <main>; else the block whose paragraphs hold the
   most text with few links.
5. Inside the root, blocks that are mostly links (share bars, "related" boxes) are skipped, and the rest is written as
   Markdown: headings, paragraphs, block quotes, lists, emphasis, links, line breaks and preformatted text."""
from __future__ import annotations

import json
import re
import unicodedata
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

VOID = frozenset("area base br col embed frame hr img input keygen link meta param source track wbr".split())
DROP = frozenset("script style noscript template svg canvas iframe object embed form button input select textarea "
                 "nav header footer aside menu dialog".split())
LEFT_OUT = frozenset("head title img picture video audio source track map area table figcaption math frame frameset "
                     "applet portal".split())
ROLES = frozenset("navigation banner contentinfo complementary dialog alertdialog menu menubar search".split())
# A wiki's furniture, by class: edit links, navigation boxes, notices, things not meant for print; and <sup
# class="reference"> (the [1] markers; the notes they point at aren't in the copy either).
FURNITURE = frozenset("mw-editsection editsection noprint navbox metadata".split())
BLOCK = frozenset("#root address article aside blockquote body center dd details dialog div dl dt fieldset figure footer "
                  "form h1 h2 h3 h4 h5 h6 header hgroup hr html li main nav ol p pre section summary table ul".split())
HEADINGS = frozenset("h1 h2 h3 h4 h5 h6".split())
P_CLOSERS = BLOCK - {"#root", "html", "body", "li", "dd", "dt"}       # a start tag that ends an open <p>
SCOPE = frozenset("applet caption html table td th marquee object template button".split())
MAX_DEPTH = 160                 # deeper elements are read as part of their parent (keeps the walk shallow)
EMPHASIS, STRONG = ("em", "i", "cite"), ("strong", "b")
LINKS = ("http", "https", "mailto")
SEPARATORS = (" | ", " - ", " — ", " – ", " · ")
ARTICLE_TYPES = ("article", "posting", "report")


def _squash(s) -> str:
    return " ".join(str(s or "").split())


def _fold(s) -> str:
    return _squash(s).casefold()


def site_of(url) -> str:
    """The host of an address without www., as a site's name when the page gives none."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


# ——— the tree ———
class _El:
    __slots__ = ("tag", "attrs", "kids", "parent", "size", "links", "blocky", "ptext", "plinks")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.kids, self.parent = tag, attrs, [], parent
        self.size = self.links = self.ptext = self.plinks = 0
        self.blocky = False


class _Tree(HTMLParser):
    """The page as a tree of _El (whose kids are _El or text)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _El("#root", {}, None)
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        self._implied(tag)
        el = self._add(tag, attrs)
        if tag not in VOID and len(self.stack) < MAX_DEPTH:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        if tag in VOID or any(e.tag in ("svg", "math") for e in self.stack):
            self._implied(tag)
            self._add(tag, attrs)
        else:                           # <div/> in HTML is an open <div>, as browsers read it
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].kids.append(data)

    def _add(self, tag, attrs) -> _El:
        first = {}
        for k, v in attrs:              # the first of a repeated attribute counts, as in browsers
            first.setdefault(k, v if v is not None else "")
        el = _El(tag, first, self.stack[-1])
        self.stack[-1].kids.append(el)
        return el

    def _implied(self, tag):
        if tag in HEADINGS and self.stack[-1].tag in HEADINGS:
            self.stack.pop()
        elif tag in P_CLOSERS:
            self._close({"p"}, SCOPE)
        elif tag == "li":
            self._close({"li"}, SCOPE | {"ul", "ol", "menu"})
        elif tag in ("dt", "dd"):
            self._close({"dt", "dd"}, SCOPE | {"dl"})

    def _close(self, tags, stop):
        for i in range(len(self.stack) - 1, 0, -1):
            t = self.stack[i].tag
            if t in tags:
                del self.stack[i:]
                return
            if t in stop:
                return


def _walk(root: _El):
    """Every element under root (root first), parents before their children, in document order."""
    stack = [root]
    while stack:
        el = stack.pop()
        yield el
        stack.extend(k for k in reversed(el.kids) if isinstance(k, _El))


def _text(el: _El) -> str:
    """All the text under an element, as it is, in document order."""
    out, stack = [], [el]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            out.append(node)
        else:
            stack.extend(reversed(node.kids))
    return "".join(out)


def _inside(el: _El, tag) -> bool:
    p = el.parent
    while p is not None:
        if p.tag == tag:
            return True
        p = p.parent
    return False


# ——— the details ———
def _iso_date(value) -> str:
    """A date as YYYY-MM-DD (or YYYY-MM, YYYY) from an ISO date or time, or an e-mail style date; "" when it isn't one."""
    s = str(value or "").strip()
    m = re.match(r"(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?(?!\d)", s)
    if m:
        year, month, day = m[1], m[2], m[3]
        if month and not 1 <= int(month) <= 12:
            month = day = None
        if day and not 1 <= int(day) <= 31:
            day = None
        return "-".join([year] + [f"{int(x):02d}" for x in (month, day if month else None) if x])
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return ""


def _person_name(value) -> str:
    """A name as a byline gives it, without "By " and never an address (article:author is often a profile link)."""
    s = _squash(value)
    s = re.sub(r"^by\s+", "", s, flags=re.I)
    return "" if re.match(r"(?i)https?://", s) else s


def _ld_nodes(data, budget=500):
    """The objects in a JSON-LD block (through @graph and nested lists), at most `budget` of them."""
    stack = [data]
    while stack and budget > 0:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(reversed(node))
        elif isinstance(node, dict):
            budget -= 1
            yield node
            stack.extend(v for v in reversed(list(node.values())) if isinstance(v, (list, dict)))


def _ld_names(author) -> list[str]:
    people = author if isinstance(author, list) else [author]
    out = []
    for p in people:
        name = p.get("name") if isinstance(p, dict) else p
        if isinstance(name, str) and _person_name(name):
            out.append(_person_name(name))
    return out


def _jsonld(blocks) -> tuple[str, str]:
    """(author, date published) from the page's JSON-LD: the first article that has them, else the first object."""
    found = []
    for raw in blocks:
        try:
            data = json.loads(raw, strict=False)
        except ValueError:
            continue
        for node in _ld_nodes(data):
            if "author" in node or "datePublished" in node:
                kind = node.get("@type")
                kinds = " ".join(kind if isinstance(kind, list) else [kind]) if kind else ""
                found.append((not any(a in str(kinds).lower() for a in ARTICLE_TYPES), len(found), node))
    if not found:
        return "", ""
    node = min(found, key=lambda f: f[:2])[2]
    return ", ".join(_ld_names(node.get("author"))), str(node.get("datePublished") or "")


def _letters(s) -> str:
    """A name compared loosely: folded, without accents or spaces ("The Guardian" → "theguardian")."""
    return "".join(c for c in unicodedata.normalize("NFKD", _fold(s)) if not c.isspace() and not unicodedata.combining(c))


def _names_site(tail: str, site: str, host: str) -> bool:
    """Whether a title's tail names the site: its name or host, or a whole label of the host without www. and its
    last part (" - Wikipedia" on en.wikipedia.org, " | The Guardian" on www.theguardian.com, never " - Lee" on
    sleepnumber.com). A label needs three letters, so " - B" on b.example stays."""
    if _fold(tail) in {_fold(site), _fold(host)} - {""}:
        return True
    letters = _letters(tail)
    if letters and letters == _letters(site):
        return True
    labels = (host[4:] if host.startswith("www.") else host).lower().split(".")[:-1]
    return len(letters) >= 3 and letters in labels


def _clean_title(title: str, site: str, host: str) -> str:
    """The title without a trailing " | Site" (or " - ", " — ") when that part names the site."""
    for sep in SEPARATORS:
        head, found, tail = title.rpartition(sep)
        if found and head.strip() and _names_site(tail, site, host):
            return head.strip()
    return title


def _details(root: _El, url: str) -> dict:
    meta, title, canonical, lang, ld, first_time = {}, None, "", "", [], ""
    for el in _walk(root):
        a = el.attrs
        if el.tag == "meta":
            key = (a.get("property") or a.get("name") or "").strip().lower()
            if key and a.get("content") and key not in meta:
                meta[key] = _squash(a["content"])
        elif el.tag == "title" and title is None and not _inside(el, "svg"):
            title = _squash(_text(el))
        elif el.tag == "link" and not canonical and "canonical" in a.get("rel", "").lower().split():
            canonical = _absolute(url, a.get("href"), ("http", "https")) or ""
        elif el.tag == "html" and not lang:
            lang = _squash(a.get("lang"))
        elif el.tag == "script" and "ld+json" in a.get("type", "").lower():
            ld.append(_text(el))
        elif el.tag == "time" and not first_time and a.get("datetime"):
            first_time = a["datetime"]
    host = site_of(url)
    site = meta.get("og:site_name") or host
    ld_author, ld_date = _jsonld(ld)
    title = meta.get("og:title") or title or ""
    author = _person_name(meta.get("author")) or _person_name(meta.get("article:author")) or ld_author
    published = next((d for d in map(_iso_date, (meta.get("article:published_time"), ld_date, first_time)) if d), "")
    return {"title": _clean_title(title, site, host), "site": site, "author": author,
            "published": published, "lang": lang, "canonical": canonical}


# ——— what is never the text ———
def _hidden(el: _El) -> bool:
    a = el.attrs
    return "hidden" in a or a.get("aria-hidden", "").strip().lower() == "true" \
        or re.search(r"display\s*:\s*none", a.get("style", ""), re.I) is not None


def _holds_page(form: _El) -> bool:
    """Some sites put the whole page in one <form>: one that holds an <article>, a <main> or three paragraphs stays."""
    paragraphs = 0
    for e in _walk(form):
        if e.tag in ("article", "main"):
            return True
        if e.tag == "p" and _squash(_text(e)):
            paragraphs += 1
            if paragraphs >= 3:
                return True
    return False


def _edit_link(href) -> bool:
    """A wiki's edit link (action=edit); a red link (a page not written yet, redlink=1) keeps its words."""
    href = str(href or "").lower()
    return "action=edit" in href and "redlink=1" not in href


def _dropped(el: _El) -> bool:
    if el.tag in DROP:
        return not (el.tag == "form" and _holds_page(el))
    classes = set(el.attrs.get("class", "").lower().split())
    if classes & FURNITURE or (el.tag == "sup" and "reference" in classes) or (el.tag == "a" and _edit_link(el.attrs.get("href"))):
        return True
    return el.tag in LEFT_OUT or _hidden(el) or el.attrs.get("role", "").strip().lower() in ROLES


def _prune(root: _El):
    stack = [root]
    while stack:
        el = stack.pop()
        el.kids = [k for k in el.kids if isinstance(k, str) or not _dropped(k)]
        stack.extend(k for k in el.kids if isinstance(k, _El))


# ——— where the text is ———
def _measure(root: _El) -> list:
    """Every element's text length, link text length and whether it holds a block; and for the blocks that hold
    paragraphs, their paragraphs' text and link text (a paragraph counts fully for its parent, half for the parent's
    parent, so text whose paragraphs are each wrapped in a <div> is still found). Returns the elements in order."""
    order = list(_walk(root))
    for el in reversed(order):
        size = links = 0
        blocky = el.tag in BLOCK
        for k in el.kids:
            if isinstance(k, str):
                size += len(_squash(k))
            else:
                size, links, blocky = size + k.size, links + k.links, blocky or k.blocky
        el.size, el.links, el.blocky = size, (size if el.tag == "a" else links), blocky
    for el in order:
        if el.tag == "p" and el.size and el.parent is not None:
            el.parent.ptext += el.size
            el.parent.plinks += el.links
            if el.parent.parent is not None:
                el.parent.parent.ptext += el.size / 2
                el.parent.parent.plinks += el.links / 2
    return order


def _root(order: list):
    """The <article> with the most text; else <main> (or role=main); else the block whose paragraphs hold the most
    text with link text under a third of it. An <article> or <main> is passed over when that block holds more than
    three times its text (a teaser beside the real text)."""
    dense = max((e for e in order if e.ptext and e.plinks * 3 < e.ptext), key=lambda e: e.ptext, default=None)
    for wanted in (lambda e: e.tag == "article",
                   lambda e: e.tag == "main" or e.attrs.get("role", "").strip().lower() == "main"):
        found = [e for e in order if wanted(e)]
        if found:
            best = max(found, key=lambda e: e.size)
            if dense is None or dense.ptext <= 3 * best.size:
                return best
    return dense or next((e for e in order if e.tag == "body"), order[0] if order else None)


# ——— Markdown ———
def _esc(text: str) -> str:
    return re.sub(r"([\\`*_\[\]])", r"\\\1", text)


def _lead(line: str) -> str:
    """A line that would start a heading, quote, list or numbered list is escaped."""
    m = re.match(r"\d{1,9}(?=[.)](\s|$))", line)
    if m:
        return line[:m.end()] + "\\" + line[m.end():]
    return "\\" + line if line[:1] in ("#", ">", "-", "+") else line


def _paragraphs(run: str) -> list[str]:
    """Inline Markdown (with "\\n" for each <br>) as paragraphs: two breaks in a row end one, a single break is a hard
    break, runs of spaces are one."""
    run = re.sub(r" *\n *", "\n", run)
    out = []
    for part in re.split(r"\n{2,}", run):
        lines = [re.sub(r" {2,}", " ", line).strip() for line in part.split("\n")]
        lines = [_lead(line) for line in lines if line]
        if lines:
            out.append("\\\n".join(lines))
    return out


def _absolute(url, href, schemes=LINKS):
    """href made absolute against the page, when it is one of `schemes`; None for in-page anchors and the rest."""
    if not isinstance(href, str):
        return None
    href = re.sub(r"[\t\r\n]", "", href).strip()
    if not href or href.startswith("#"):
        return None
    try:
        out = urljoin(url, href)
        scheme = urlsplit(out).scheme.lower()
    except ValueError:
        return None
    if scheme not in schemes:
        return None
    return re.sub(r"[\s()<>]", lambda m: "%{:02X}".format(ord(m[0])), out)


def _wrap(inner: str, marker: str) -> str:
    """Emphasis around inner text, its edge spaces moved outside the markers (`* a *` isn't emphasis)."""
    core = inner.strip(" \n")
    if not core:
        return inner
    lead = inner[:len(inner) - len(inner.lstrip(" \n"))]
    trail = inner[len(inner.rstrip(" \n")):]
    return f"{lead}{marker}{core}{marker}{trail}"


def _code(text: str) -> str:
    text = _squash(text)
    if not text:
        return ""
    ticks = "`" * (max((len(r) for r in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{ticks}{pad}{text}{pad}{ticks}"


def _inline(el: _El, url: str, marks: frozenset) -> str:
    """An inline element as Markdown; `marks` are the emphasis and link already open around it."""
    t = el.tag
    if t == "br":
        return "\n"
    if t == "code":
        return _code(_text(el))
    marker, href = "", None
    if t in EMPHASIS and "em" not in marks:
        marker, marks = "*", marks | {"em"}
    elif t in STRONG and "strong" not in marks:
        marker, marks = "**", marks | {"strong"}
    elif t == "a" and "a" not in marks:
        href = None if "action=edit" in el.attrs.get("href", "").lower() else _absolute(url, el.attrs.get("href"))
        if href:
            marks = marks | {"a"}
    inner = "".join(_esc(re.sub(r"\s+", " ", k)) if isinstance(k, str) else _inline(k, url, marks) for k in el.kids)
    if marker:
        return _wrap(inner, marker)
    if href:
        text = inner.replace("\n", " ")
        core = text.strip()
        if not core:
            return text
        return text[:len(text) - len(text.lstrip())] + f"[{core}]({href})" + text[len(text.rstrip()):]
    return inner


def _blocks(el: _El, url: str) -> list[str]:
    """An element's content as Markdown blocks."""
    out, run = [], []
    for kid in el.kids:
        if isinstance(kid, str):
            run.append(_esc(re.sub(r"\s+", " ", kid)))
        elif not kid.blocky:
            run.append(_inline(kid, url, frozenset()))
        else:
            out += _paragraphs("".join(run))
            run = []
            out += _block(kid, url)
    return out + _paragraphs("".join(run))


def _block(el: _El, url: str) -> list[str]:
    t = el.tag
    if t in ("div", "section") and el.size and el.links * 2 >= el.size:
        return []                       # mostly links: a share bar, a "related" box, an ad
    if t in HEADINGS:
        text = " ".join(_blocks(el, url)).replace("\\\n", " ")
        return [("## " if t in ("h1", "h2") else "### ") + text] if text else []
    if t == "blockquote":
        inner = "\n\n".join(_blocks(el, url))
        return ["\n".join("> " + line if line else ">" for line in inner.split("\n"))] if inner else []
    if t in ("ul", "ol"):
        return _list(el, url)
    if t == "pre":
        return _pre(el)
    if t == "hr":
        return []
    return _blocks(el, url)


def _list(el: _El, url: str) -> list[str]:
    start = el.attrs.get("start", "")
    n = int(start) if el.tag == "ol" and start.isdigit() else 1
    items = []
    for li in el.kids:
        if isinstance(li, str) or li.tag != "li":
            continue
        blocks = _blocks(li, url)
        if not blocks:
            continue
        text = blocks[0]
        for b in blocks[1:]:            # a list inside an item follows its line; anything else is a new paragraph
            text += ("\n" if re.match(r"(- |\d+\. )", b) else "\n\n") + b
        marker = f"{n}. " if el.tag == "ol" else "- "
        pad = " " * len(marker)
        items.append(marker + "\n".join(pad + line if line and i else line for i, line in enumerate(text.split("\n"))))
        n += 1
    return ["\n".join(items)] if items else []


def _pre(el: _El) -> list[str]:
    def raw(node) -> str:
        if isinstance(node, str):
            return node
        return "\n" if node.tag == "br" else "".join(raw(k) for k in node.kids)

    code = raw(el)
    code = (code[1:] if code.startswith("\n") else code).rstrip()
    if not code.strip():
        return []
    fence = "`" * max(3, max((len(r) for r in re.findall(r"`+", code)), default=0) + 1)
    return [f"{fence}\n{code}\n{fence}"]


def readable(html: str, url: str) -> dict:
    """{"title", "site", "author", "published", "lang", "canonical", "markdown"} of a page: every value a string, ""
    when the page doesn't say. `url` is the page's address (links are made absolute against it)."""
    tree = _Tree()
    try:
        tree.feed(html or "")
        tree.close()
    except (AssertionError, ValueError):      # a declaration the parser can't read: what came before it is kept
        pass
    details = _details(tree.root, url)
    _prune(tree.root)
    order = _measure(tree.root)
    root = _root(order)
    details["markdown"] = "\n\n".join(_blocks(root, url)) if root is not None else ""
    return details
