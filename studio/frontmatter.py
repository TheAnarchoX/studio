"""Front matter for research items: YAML that Studio writes as JSON values, one `key: value` per line.

Reading accepts what a person types by hand too: plain strings, quoted strings, block lists and flow lists of plain
values. What Studio can't read (a map, a block scalar, a comment, a stray line) is kept and written back as it was.
No YAML library."""
from __future__ import annotations

import json
import re

ORDER = ("type", "title", "tags", "source", "locator", "from", "url", "site", "author", "published", "fetched", "shot",
         "file", "book", "board", "item", "csl", "created")
_LINE = re.compile(r"([^\s:#][^:]*?)\s*:(?:\s+(.*)|\s*)$")
_ITEM = re.compile(r"\s*-(?:\s+(.*))?$")
# one value of a flow list, `[a, 'b, c', "d"]`: quoted, or plain (not starting with a YAML indicator), then `,` or the end
_FLOW_ITEM = re.compile(r"""\s*('(?:[^']|'')*'|"(?:[^"\\]|\\.)*"|(?:[^\s,\[\]{}'"#&*!|>%@`?-]|-(?=[^\s,\[\]{}]))"""
                        r"""[^,\[\]{}]*?)\s*(?:,|$)""")


class RawYaml(str):
    """A hand-written value Studio doesn't read (a map, a block scalar): the text after `key:`, written back as it was."""


class Loose(RawYaml):
    """Front matter lines that belong to no key (comments, stray text): kept under a key `#1`, `#2`, … that no written
    key can be, and written back as they were."""


class RawList(list):
    """A list a person wrote (a block list, comments between its items, a flow list): read as the list, written back
    as it was while it is unchanged."""

    def __init__(self, items, raw: str):
        super().__init__(items)
        self.raw, self.was = raw, json.dumps(items, ensure_ascii=False)


def _value(s: str):
    """A value as written: JSON when it is JSON, else the plain string without its quotes (`''` is one `'`)."""
    s = s.strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1].replace("''", "'") if s[0] == "'" else s[1:-1]
    return s


def _flow(s: str):
    """A flow list of plain or quoted values, `[childhood, 1987, 'a, b']`, as a list; None for anything else."""
    inner, out, at = s[1:-1], [], 0
    if not inner.strip():
        return []
    while at < len(inner):
        m = _FLOW_ITEM.match(inner, at)
        if not m:
            return None
        item, at = m[1], m.end()
        if item[0] == '"':
            try:
                out.append(json.loads(item))
            except ValueError:
                return None
        elif item[0] == "'":
            out.append(item[1:-1].replace("''", "'"))
        elif re.search(r":(?:\s|$)|\s#", item):         # a map entry or a comment: not a plain value
            return None
        else:
            out.append(_value(item))
    return out


def _inline(raw: str):
    """The value on a key's own line: JSON, a flow list of plain values, any other `[…]` or `{…}` kept as written,
    else a plain or quoted string."""
    try:
        return json.loads(raw)
    except ValueError:
        pass
    if (raw[0], raw[-1]) in (("[", "]"), ("{", "}")):
        items = _flow(raw) if raw[0] == "[" else None
        return RawList(items, f" {raw}") if items is not None else RawYaml(f" {raw}")
    return _value(raw)


def _goes_on(line: str, raw: str) -> bool:
    """Whether a line goes on with the value of the key above it: indented text, or `- item` under an empty `key:`."""
    return bool(line.strip()) and (line[:1] in (" ", "\t") or (not raw and bool(_ITEM.match(line))))


def parse(text: str) -> tuple[dict, str, bool]:
    """(fields, body, had front matter). No closing `---` line means there is no front matter."""
    text = text.lstrip("\ufeff").replace("\r", "")
    lines = text.split("\n")
    if lines[0].rstrip() != "---":
        return {}, text, False
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if end is None:
        return {}, text, False
    fields, loose, i = {}, [], 1

    def keep_loose():
        if loose:
            fields[f"#{sum(isinstance(v, Loose) for v in fields.values()) + 1}"] = Loose("\n".join(loose))
            loose.clear()

    while i < end:
        line = lines[i]
        i += 1
        m = None if line.lstrip().startswith("#") else _LINE.match(line)
        if not m:                       # a comment or a stray line: kept with the ones next to it
            if line.strip():
                loose.append(line)
            continue
        keep_loose()
        key, raw = m[1].strip(), (m[2] or "").strip()
        more = []                       # the lines that go with this key
        while i < end:                  # blank lines and comments go with it when the value goes on after them
            j = i
            while j < end and not _goes_on(lines[j], raw) and (not lines[j].strip() or lines[j].startswith("#")):
                j += 1
            if j == end or not _goes_on(lines[j], raw):
                break
            more, i = more + lines[i:j + 1], j + 1
        listed = [x for x in more if x.strip() and not x.lstrip().startswith("#")]
        if not more:
            fields[key] = _inline(raw) if raw else ""
        elif not raw and all(_ITEM.match(x) for x in listed):
            fields[key] = RawList([_value(_ITEM.match(x)[1] or "") for x in listed], "".join("\n" + x for x in more))
        else:                           # a map, a block scalar, a folded value: kept as written
            fields[key] = RawYaml((f" {raw}" if raw else "") + "".join("\n" + x for x in more))
    keep_loose()
    return fields, "\n".join(lines[end + 1:]), True


def _line(k, v) -> str:
    if isinstance(v, Loose):
        return f"{v}\n"
    if isinstance(v, RawYaml):
        return f"{k}:{v}\n"
    if isinstance(v, RawList) and json.dumps(v, ensure_ascii=False) == v.was:
        return f"{k}:{v.raw}\n"
    return f"{k}: {json.dumps(v, ensure_ascii=False)}\n"


def dump(fields: dict, body: str) -> str:
    """The file's text: front matter (known keys first, in order), then the body with one final newline."""
    keys = [k for k in ORDER if k in fields] + [k for k in fields if k not in ORDER]
    out = ["---\n"] + [_line(k, fields[k]) for k in keys] + ["---\n"]
    body = (body or "").rstrip("\n")
    return "".join(out) + (body + "\n" if body.strip() else "")
