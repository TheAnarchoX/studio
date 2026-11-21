"""Real Word lists for the .docx export: a `w:abstractNum` and a `w:num` per list, so each list restarts at its own
start and Word numbers it itself. `book_export` asks for one `num_id` per list (`manuscript_lists.markers` gives
each item its list's `run`) and applies it to the item's paragraph."""
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

FORMATS = {"bullet": "bullet", "decimal": "decimal", "lower-alpha": "lowerLetter", "upper-alpha": "upperLetter",
           "lower-roman": "lowerRoman", "upper-roman": "upperRoman"}
BULLETS = "•◦▪•"                  # by level


def _el(tag, **attrs):
    el = OxmlElement(tag)
    for k, v in attrs.items():
        el.set(qn("w:" + k), str(v))
    return el


class Numbering:
    def __init__(self, document):
        self.root = document.part.numbering_part.element
        self.next_abstract = 1 + max([int(x) for x in self.root.xpath("w:abstractNum/@w:abstractNumId")] + [-1])
        self.next_num = 1 + max([int(x) for x in self.root.xpath("w:num/@w:numId")] + [0])

    def num_id(self, style: str, level: int, start: int) -> int:
        """A new list of `style` whose level `level` starts at `start` (the other levels at 1) -> its `numId`."""
        fmt = FORMATS[style]
        abstract = _el("w:abstractNum", abstractNumId=self.next_abstract)
        abstract.append(_el("w:multiLevelType", val="hybridMultilevel"))
        # the levels other than `level` are dummies (a nested run gets a dummy level 0): Word numbers by numId and
        # ilvl, so a dummy is never shown
        for i in range(4):
            lvl = _el("w:lvl", ilvl=i)
            lvl.append(_el("w:start", val=start if i == level else 1))
            lvl.append(_el("w:numFmt", val=fmt))
            lvl.append(_el("w:lvlText", val=BULLETS[i] if style == "bullet" else f"%{i + 1}."))
            lvl.append(_el("w:lvlJc", val="left"))
            ppr = OxmlElement("w:pPr")
            ppr.append(_el("w:ind", left=720 + 360 * i, hanging=360))
            lvl.append(ppr)
            abstract.append(lvl)
        # abstractNum elements come before every num element
        first_num = self.root.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(abstract)
        else:
            self.root.append(abstract)
        num = _el("w:num", numId=self.next_num)
        num.append(_el("w:abstractNumId", val=self.next_abstract))
        self.root.append(num)
        self.next_abstract += 1
        self.next_num += 1
        return self.next_num - 1

    @staticmethod
    def apply(paragraph, num_id: int, level: int) -> None:
        ppr = paragraph._p.get_or_add_pPr()
        for old in ppr.findall(qn("w:numPr")):
            ppr.remove(old)
        num_pr = OxmlElement("w:numPr")
        num_pr.append(_el("w:ilvl", val=level))
        num_pr.append(_el("w:numId", val=num_id))
        # numPr follows pStyle/keepNext/…/pageBreakBefore in the schema; before spacing, ind, jc and the rest
        after = [qn("w:" + t) for t in ("pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
                                         "widowControl")]
        anchor = None
        for child in ppr:
            if child.tag in after:
                anchor = child
        if anchor is not None:
            anchor.addnext(num_pr)
        else:
            ppr.insert(0, num_pr)
