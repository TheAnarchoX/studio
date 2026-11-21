r"""Lists in the manuscript dialect (spec: docs/superpowers/specs/2026-11-13-book-editor-power-design.md, "Lists in
detail"): the Markdown list rule, the markers an item shows and is written with, and the rules that keep a document's
lists canonical. `manuscript` uses it for reading and writing; there is no other implementation.

In a document a list is a run of `list_item` blocks at the top level of a piece, never nested: `level` (0-3) says how
deep an item is, `start` the number a list starts at when it isn't 1 (on the item that starts the list, else null).
What an item shows is computed by `markers`, never stored.

`list_rule` is a copy of markdown-it-py's list rule (`list_block` in markdown_it/rules_block/list.py, markdown-it-py
4.3.0; MIT licence, Copyright (c) 2020 ExecutableBookProject; a port of markdown-it, Copyright (c) 2014 Vitaly Puzrin,
Alex Kocharin), extended with the markers of Pandoc's fancy_lists, read as Pandoc reads them:
- `1.`, `a.`, `A.`, `i.`, `I.`, each also with `)`; `i` and `I` alone are roman, another single letter is a letter
  (`v.` is the 22nd), several letters are roman when they make a numeral (`ii.`, `xiv.`, `IV.`);
- the next items of a list are read in its style (`i.` after `h.` is the ninth letter); another style, the other kind
  (bullets, numbers) or another delimiter ends the list;
- a capital letter with a period (also the capital roman numerals one letter long: 1, 5, 10, 50, 100, 500, 1000)
  needs a tab or two spaces after it, so `A. Einstein` and `I. Kant` stay sentences; alone on its line it is an empty
  item;
- a list interrupts a paragraph only when it starts at 1 and its first item isn't empty (CommonMark's rule), and a
  list of letters or roman numerals only inside a list item (nested lists); at the top level such a line after a
  line break stays a line, as in Pandoc, where no list interrupts a paragraph.

The licence of the copied rule (the same MIT terms for both copyright lines above; markdown-it-py ships them as
LICENSE and LICENSE.markdown-it):

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""
import re

from markdown_it.rules_block.list import markTightParagraphs, skipBulletListMarker

STYLES = ("bullet", "decimal", "lower-alpha", "upper-alpha", "lower-roman", "upper-roman")
_BULLETS = "•◦▪•"                              # by level
_ONE_LETTER = {1, 5, 10, 50, 100, 500, 1000}    # the capital roman numerals that are one letter
_MAX_START = 999_999_999                        # CommonMark reads a list number of at most nine digits
_MARKER = re.compile(r"([0-9]{1,9}|[A-Za-z]+)([.)])")
_PAREN = re.compile(r"\(([0-9]{1,9}|[A-Za-z]+)\)(?:[ \t]|$)")
_ROMAN = re.compile(r"m*(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})")
_NUMERALS = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
             (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))


# ---------------------------------------------------------------------------------------------------------
# Numbers and markers

def to_roman(n: int) -> str:
    """14 -> `xiv`."""
    out = ""
    for value, digits in _NUMERALS:
        while n >= value:
            out += digits
            n -= value
    return out


def from_roman(s: str) -> int | None:
    """`xiv` or `XIV` -> 14; None when `s` isn't a roman numeral in one case (`iiii`, `Mr`)."""
    low = s.lower()
    if not s or s not in (low, s.upper()) or not _ROMAN.fullmatch(low):
        return None
    total = 0
    for value, digits in _NUMERALS:
        while low.startswith(digits):
            total += value
            low = low[len(digits):]
    return total


def to_alpha(n: int) -> str:
    """1 -> `a`, 26 -> `z`, 27 -> `aa`."""
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord("a") + r) + out
    return out


def _number(style, n):
    if style == "decimal":
        return str(n)
    if style in ("lower-alpha", "upper-alpha"):
        out = to_alpha(n)
    elif style in ("lower-roman", "upper-roman"):
        out = to_roman(n)
    else:
        raise ValueError(f"unknown list style: {style!r}")
    return out.upper() if style.startswith("upper") else out


def marker_text(style: str, n: int, level: int) -> str:
    """What an item shows: `•` `◦` `▪` `•` by level for bullets, else `1.`, `a.`, `A.`, `iv.`, `IV.`."""
    if style == "bullet":
        return _BULLETS[min(max(level, 0), 3)]
    return _number(style, n) + "."


def md_marker(style: str, n: int, delim: str = ".") -> str:
    """How an item is written, with the spaces after it: `- `, `3. `, `c. `, `C.  `, `iv. `, `IV.  ` (two spaces after
    a capital with a period, for every item of the list), or with `delim` `)`: `C) `; letters past `z` are written
    `z`, which reads back as the same list."""
    if style == "bullet":
        return "- "
    if style in ("lower-alpha", "upper-alpha"):
        n = min(n, 26)
    return _number(style, n) + delim + ("  " if delim == "." and style.startswith("upper") else " ")


def _valid_start(style, start):
    """`start` when a list of `style` can start there (numbers from 0, letters and numerals from 1, at most nine digits
    as CommonMark reads them; roman numerals up to 3999), else None."""
    least = {"decimal": 0, "bullet": None}.get(style, 1)
    most = 3999 if style in ("lower-roman", "upper-roman") else _MAX_START
    return start if least is not None and type(start) is int and least <= start <= most else None


def markers(blocks: list[dict]) -> list[dict | None]:
    """Per top-level block: None, or for a list item {"marker", "level", "list", "n", "first", "run"}.

    Walks the blocks with a stack of open lists, one per level: a block that isn't a list item closes every list; an
    item's level is clamped to at most one deeper than the stack (and 3); lists deeper than the item close; the same
    style at that level continues its list (n + 1), another style or nothing open there starts one at the item's
    `start`. `first`: the item starts a list; `run`: the index in `blocks` of its list's first item."""
    out, stack = [], []         # stack: per level, [style, n, run]
    for k, block in enumerate(blocks):
        if block.get("type") != "list_item":
            stack = []
            out.append(None)
            continue
        attrs = block.get("attrs") or {}
        style, level = attrs.get("list"), attrs.get("level")
        level = min(max(level if type(level) is int else 0, 0), len(stack), 3)
        del stack[level + 1:]
        first = level == len(stack) or stack[level][0] != style
        if first:
            start = _valid_start(style, attrs.get("start"))
            stack[level:] = [[style, 1 if start is None else start, k]]
        else:
            stack[level][1] += 1
        _, n, run = stack[level]
        out.append({"marker": marker_text(style, n, level), "level": level, "list": style, "n": n, "first": first,
                    "run": run})
    return out


def normalize(blocks: list[dict]) -> list[dict]:
    """The top-level blocks with every list item's level clamped (see `markers`) and `start` kept only on an item that
    starts a numbered list at another number than 1 (0 is a start too). An item read from Markdown carries `_n`, the
    number it had there (a list cut by a paragraph goes on at the number it showed); it is dropped here."""
    out = []
    for block, m in zip(blocks, markers(blocks)):
        if m is not None:
            block = dict(block)
            attrs = block.get("attrs") or {}
            n = block.pop("_n", attrs.get("start"))
            start = _valid_start(m["list"], n) if m["first"] else None
            block["attrs"] = {"list": m["list"], "level": m["level"], "start": None if start == 1 else start}
        out.append(block)
    return out


# ---------------------------------------------------------------------------------------------------------
# Reading

def _letters(body, style):
    """A marker's letters -> (style, value), read in `style` when a list of letters or numerals is open, else as
    Pandoc reads a list's first marker; None when they are no marker."""
    case = "lower" if body.islower() else "upper" if body.isupper() else None
    if case is None:
        return None
    alpha = (case + "-alpha", ord(body.lower()) - ord("a") + 1) if len(body) == 1 else None
    roman = from_roman(body)
    roman = None if roman is None else (case + "-roman", roman)
    if style is None:
        return roman if len(body) > 1 or body in "iI" else alpha
    return alpha if style.endswith("alpha") else roman if style.endswith("roman") else None


def _ordered(src, pos, maximum, style=None):
    """An ordered list marker at `pos` (`3.`, `c)`, `iv.`, `A.  `) followed by a space, a tab or the end, read in
    `style` (any when None) -> (style, value, position after the delimiter); None when there is none."""
    m = _MARKER.match(src, pos, maximum)
    if not m:
        return None
    body, end = m[1], m.end()
    found = ("decimal", int(body)) if body[0] in "0123456789" else _letters(body, style)
    if found is None or (style is not None and found[0] != style):
        return None
    gap = end
    while gap < maximum and src[gap] in " \t":
        gap += 1
    if gap == end and end < maximum:                    # `1.5`, `e.g.`: no space after it
        return None
    kind, value = found
    if (m[2] == "." and gap < maximum and (kind == "upper-alpha" or (kind == "upper-roman" and value in _ONE_LETTER))
            and "\t" not in src[end:gap] and gap - end < 2):
        return None                                     # `A. Einstein`, `I. Kant`
    return kind, value, end


def escape_line_start(text: str) -> str:
    """A backslash before what `list_rule` would read as an ordered list marker at a line start (`a\\.`, `iv\\.`,
    `A\\.` before a tab, two spaces or the end, `A\\)`, `3\\.`), and before Pandoc's two-parenthesis markers (`\\(a)`,
    `\\(1)`, which `list_rule` doesn't read); `text` unchanged otherwise (`A. Einstein`, `Mr. Jansen`, `e.g. zo`)."""
    found = _ordered(text, 0, len(text))
    if found:
        return text[:found[2] - 1] + "\\" + text[found[2] - 1:]
    m = _PAREN.match(text)
    return "\\" + text if m and (m[1][0] in "0123456789" or _letters(m[1], None)) else text


def _marker(state, line, style=None):
    return _ordered(state.src, state.bMarks[line] + state.tShift[line], state.eMarks[line], style)


def list_rule(state, startLine, endLine, silent):
    """markdown-it's `list_block` with the markers above. The list's open token carries meta {"list": style,
    "start": n}."""
    isTerminatingParagraph = False
    tight = True

    if state.is_code_block(startLine):
        return False

    # Special case:
    #  - item 1
    #   - item 2
    #    - item 3
    #     - item 4
    #      - this one is a paragraph continuation
    if (
        state.listIndent >= 0
        and state.sCount[startLine] - state.listIndent >= 4
        and state.sCount[startLine] < state.blkIndent
    ):
        return False

    # limit conditions when list can interrupt a paragraph (validation mode only)
    if silent and state.parentType == "paragraph" and state.sCount[startLine] >= state.blkIndent:
        isTerminatingParagraph = True

    # Detect list type and position after marker
    found = _marker(state, startLine)
    if found:
        isOrdered = True
        style, markerValue, posAfterMarker = found
        # A list right after a paragraph starts at 1 (in every style), and letters and roman numerals start one only
        # inside a list item: at the top level a line after a line break stays a line (`a. een` after `Regel\`).
        if isTerminatingParagraph and (markerValue != 1 or (style != "decimal" and state.listIndent < 0)):
            return False
    else:
        posAfterMarker = skipBulletListMarker(state, startLine)
        if posAfterMarker < 0:
            return False
        isOrdered, style, markerValue = False, "bullet", 1

    # A list right after a paragraph has a first line that isn't empty.
    if isTerminatingParagraph and state.skipSpaces(posAfterMarker) >= state.eMarks[startLine]:
        return False

    # We should terminate list on delimiter change. Remember first one to compare.
    markerChar = state.src[posAfterMarker - 1]

    # For validation mode we can terminate immediately
    if silent:
        return True

    # Start list
    listTokIdx = len(state.tokens)

    if isOrdered:
        token = state.push("ordered_list_open", "ol", 1)
        if markerValue != 1:
            token.attrs = {"start": markerValue}
    else:
        token = state.push("bullet_list_open", "ul", 1)
    token.meta = {"list": style, "start": markerValue}
    token.map = listLines = [startLine, 0]
    token.markup = markerChar

    # Iterate list items
    nextLine = startLine
    prevEmptyEnd = False
    terminatorRules = state.md.block.ruler.getRules("list")

    oldParentType = state.parentType
    state.parentType = "list"

    while nextLine < endLine:
        pos = posAfterMarker
        maximum = state.eMarks[nextLine]

        initial = offset = state.sCount[nextLine] + posAfterMarker - (state.bMarks[startLine] + state.tShift[startLine])

        while pos < maximum:
            ch = state.src[pos]
            if ch == "\t":
                offset += 4 - (offset + state.bsCount[nextLine]) % 4
            elif ch == " ":
                offset += 1
            else:
                break
            pos += 1

        contentStart = pos

        # trimming space in "-    \n  3" case, indent is 1 here
        indentAfterMarker = 1 if contentStart >= maximum else offset - initial

        # If we have more than 4 spaces, the indent is 1 (the rest is just indented code block)
        if indentAfterMarker > 4:
            indentAfterMarker = 1

        # "  -  test"
        #  ^^^^^ - calculating total length of this thing
        indent = initial + indentAfterMarker

        # Run subparser & write tokens
        token = state.push("list_item_open", "li", 1)
        token.markup = markerChar
        token.map = itemLines = [startLine, 0]

        # change current state, then restore it after parser subcall
        oldTight = state.tight
        oldTShift = state.tShift[startLine]
        oldSCount = state.sCount[startLine]

        #  - example list
        # ^ listIndent position will be here
        #   ^ blkIndent position will be here
        oldListIndent = state.listIndent
        state.listIndent = state.blkIndent
        state.blkIndent = indent

        state.tight = True
        state.tShift[startLine] = contentStart - state.bMarks[startLine]
        state.sCount[startLine] = offset

        if contentStart >= maximum and state.isEmpty(startLine + 1):
            # workaround for this case
            # (list item is empty, list terminates before "foo"):
            # ~~~~~~~~
            #   -
            #
            #     foo
            # ~~~~~~~~
            state.line = min(state.line + 2, endLine)
        else:
            state.md.block.tokenize(state, startLine, endLine)

        # If any of list item is tight, mark list as tight
        if (not state.tight) or prevEmptyEnd:
            tight = False

        # Item become loose if finish with empty line,
        # but we should filter last element, because it means list finish
        prevEmptyEnd = (state.line - startLine) > 1 and state.isEmpty(state.line - 1)

        state.blkIndent = state.listIndent
        state.listIndent = oldListIndent
        state.tShift[startLine] = oldTShift
        state.sCount[startLine] = oldSCount
        state.tight = oldTight

        token = state.push("list_item_close", "li", -1)
        token.markup = markerChar

        nextLine = startLine = state.line
        itemLines[1] = nextLine

        if nextLine >= endLine:
            break

        # Try to check if list is terminated or continued.
        if state.sCount[nextLine] < state.blkIndent:
            break

        if state.is_code_block(startLine):
            break

        # fail if terminating block found
        terminate = False
        for terminatorRule in terminatorRules:
            if terminatorRule(state, nextLine, endLine, True):
                terminate = True
                break

        if terminate:
            break

        # fail if the next marker is of another kind, or not in the list's style
        if isOrdered:
            found = _marker(state, nextLine, style)
            if not found:
                break
            posAfterMarker = found[2]
        else:
            posAfterMarker = skipBulletListMarker(state, nextLine)
            if posAfterMarker < 0:
                break

        if markerChar != state.src[posAfterMarker - 1]:
            break

    # Finalize list
    if isOrdered:
        token = state.push("ordered_list_close", "ol", -1)
    else:
        token = state.push("bullet_list_close", "ul", -1)

    token.markup = markerChar

    listLines[1] = nextLine
    state.line = nextLine

    state.parentType = oldParentType

    # mark paragraphs tight if needed
    if tight:
        markTightParagraphs(state, listTokIdx)

    return True
