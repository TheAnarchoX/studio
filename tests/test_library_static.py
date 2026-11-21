"""The library tools' static files (backups.js, writing.js, search.js and library.css) are served with their types and
loaded by the page; backups.js says sizes as the server does (backup.size_text); search.js marks, says and finds what
the search panel shows and selects, and is wired to the top bar, the book's palette and Info."""
import json
import shutil
import subprocess
import unittest
import urllib.request
from pathlib import Path

from studio import backup
from tests.support import temp_studio

STATIC = Path(__file__).resolve().parent.parent / "studio" / "static"
FILES = {"backups.js": "text/javascript", "writing.js": "text/javascript", "search.js": "text/javascript",
         "library.css": "text/css"}
SEARCH_BUTTON = ('<button class="btn quiet" id="search" type="button" title="Search the library (Ctrl+K)">Search'
                 '</button>')

# loads backups.js in node, without a page, and prints what its helpers make of the input
NODE = r"""
const fs = require("fs"), vm = require("vm");
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(process.argv[1], "utf8"));
const B = globalThis.Backups, input = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify({
  sizes: input.sizes.map(B.sizeText),
  folded: input.fold.map(B.fold),
  matches: input.matches.map(([q, ...texts]) => B.matches(q, texts)),
  sections: [window.settingsSections.map(s => s.id), window.homeSections.map(s => s.id)],
}));
"""

# loads search.js in node, after ProseMirror, the book's schema and app.js's own esc(), and prints what its helpers
# make of the input
NODE_SEARCH = r"""
const fs = require("fs"), vm = require("vm");
const [pm, schema, app, search, input] = process.argv.slice(1);
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(pm, "utf8"));
if (typeof PM !== "undefined") globalThis.PM = PM;
vm.runInThisContext(fs.readFileSync(schema, "utf8"));
vm.runInThisContext(fs.readFileSync(app, "utf8").match(/^const esc = .*$/m)[0].replace(/^const esc/, "globalThis.esc"));
vm.runInThisContext(fs.readFileSync(search, "utf8"));
const L = globalThis.LibrarySearch, I = JSON.parse(input);
const doc = json => globalThis.PM.Node.fromJSON(globalThis.BookSchema, json);
process.stdout.write(JSON.stringify({
  marked: I.marked.map(([text, marks]) => L.marked(text, marks)),
  fresh: I.fresh.map(([st, now]) => L.freshness(st, new Date(now).getTime())),
  counts: I.counts.map(c => L.countsLine(c)),
  ranges: I.ranges.map(([value, match, start]) => L.findRange(value, match, start)),
  docs: I.docs.map(([json, match]) => {
    const d = doc(json), r = L.docRange(d, match);
    return r && [d.textBetween(r[0], r[1], "\n", "￼"), d.resolve(r[0]).parent.type.name];
  }),
  rows: I.rows.map(r => L.resultHtml(r, 0, false)),
  nothing: L.nothingHtml(I.nothing),
  more: I.more.map(g => L.moreLabel(g)),
  heads: I.heads.map(g => L.groupHead(g)),
}));
"""

# loads search.js in node and prints what its poll() and search() do: the jump's wait for a page, and the API call
NODE_POLL = r"""
const fs = require("fs"), vm = require("vm");
globalThis.window = globalThis;
const asked = [];
globalThis.api = async path => { asked.push(path); return {q: "reply"}; };
vm.runInThisContext(fs.readFileSync(process.argv[1], "utf8"));
const L = globalThis.LibrarySearch, out = {};
const later = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let n = 0;
  L.poll(() => ++n >= 3, () => true, 1000, 10);                    // done on the third try
  let m = 0;
  L.poll(() => { m++; return false; }, () => true, 120, 10);       // never done: gives up after `within`
  let k = 0;
  L.poll(() => { k++; return false; }, () => false, 1000, 10);     // the author moved on: never tried
  let t = 0;
  L.poll(() => { t++; throw new Error("gone"); }, () => true, 1000, 10);   // the page changed: it simply opens
  out.sync = [n, m, k, t];                                         // nothing runs before the page has had a turn
  await later(400);
  out.after = [n, m, k, t];
  const seen = m;
  await later(200);
  out.stopped = m === seen;
  out.reply = await L.search("café “sea”");
  out.asked = asked;
  process.stdout.write(JSON.stringify(out));
})();
"""

PARA = lambda *content: {"type": "paragraph", "content": list(content)}       # noqa: E731
TEXT = lambda t, *marks: {"type": "text", "text": t, **({"marks": [{"type": m} for m in marks]} if marks else {})}  # noqa: E731


class LibraryStaticTest(unittest.TestCase):
    def test_each_file_is_served_with_its_type(self):
        with temp_studio() as st:
            for name, ctype in FILES.items():
                with self.subTest(name), urllib.request.urlopen(f"{st.url}/static/{name}", timeout=10) as r:
                    self.assertEqual(r.status, 200)
                    self.assertEqual(r.headers["Content-Type"], f"{ctype}; charset=utf-8")
                    self.assertEqual(r.read(), (STATIC / name).read_bytes())

    def test_the_page_loads_them(self):
        with temp_studio() as st:
            page = st.get("/")[1].decode("utf-8")
        self.assertIn('<link rel="stylesheet" href="/static/library.css">', page)
        self.assertIn('<script src="/static/backups.js"></script>', page)
        self.assertIn('<script src="/static/writing.js"></script>', page)
        # after the files whose rules and globals they build on
        self.assertLess(page.index("/static/book-tools.css"), page.index("/static/library.css"))
        self.assertLess(page.index("/static/welcome.js"), page.index("/static/backups.js"))
        self.assertLess(page.index("/static/backups.js"), page.index("/static/writing.js"))
        self.assertIn('<script src="/static/search.js"></script>', page)
        # after book-tools.js, so the book palette's Ctrl+K listener runs first; after the other library scripts
        self.assertLess(page.index("/static/book-tools.js"), page.index("/static/search.js"))
        self.assertLess(page.index("/static/writing.js"), page.index("/static/search.js"))
        # the top bar's Search button, before New
        self.assertIn(SEARCH_BUTTON, page)
        self.assertLess(page.index(SEARCH_BUTTON), page.index('id="new"'))

    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_backups_js_helpers(self):
        sizes = [0, 1, 512, 1023, 1024, 1536, 2560, 960_000, 1024 ** 2 - 1, 1024 ** 2, 1_300_000, 1_310_720,
                 1_835_008, 9_900_000, 10_485_759, 10_485_760, 12_600_000, 13_107_200, 14_155_776, 1024 ** 3 - 1,
                 1024 ** 3, 1_288_490_189, 5 * 1024 ** 4]       # with the ties: 2.5 KB, 1.25 MB, 1.75 MB, 12.5 MB, 13.5 MB
        fold = ["Café, ’s nachts", "ÉÉN", "Gedichten – één"]
        matches = [["cafe", "Café, ’s nachts"], ["NACHTS café", "Café, ’s nachts", "Sea"], ["sea harbour", "Harbour", "Sea"],
                   ["lighthouse", "Harbour", "Sea"], ["", "Harbour"], ["  ", "Harbour"]]
        r = subprocess.run([shutil.which("node"), "-e", NODE, str(STATIC / "backups.js"),
                            json.dumps({"sizes": sizes, "fold": fold, "matches": matches})],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["sizes"], [backup.size_text(n) for n in sizes])
        self.assertEqual(out["folded"], ["cafe, ’s nachts", "een", "gedichten – een"])
        self.assertEqual(out["matches"], [True, True, True, False, True, True])
        self.assertEqual(out["sections"], [["backups"], ["backups"]])

    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_search_js_helpers(self):
        doc = lambda *blocks: {"type": "doc", "content": list(blocks)}       # noqa: E731
        ferry = doc({"type": "title", "content": [TEXT("Night ferry")]},
                    PARA(TEXT("We took the "), TEXT("night", "em"), TEXT(" ferry to the island.")),
                    PARA(TEXT("The Night Ferry left at nine.")))
        quiet = doc(PARA(TEXT("a quiet "), {"type": "note", "content": [TEXT("an aside")]}, TEXT("harbour")),
                    PARA(TEXT("one"), {"type": "hard_break"}, TEXT("two and the quiet harbour")),
                    {"type": "poem", "content": [PARA(TEXT("Het café, ’s nachts"))]})
        result = {"kind": "poem", "title": "<Café> Harbour", "title_marks": [[7, 14]], "where": "Salt & Iron",
                  "field": "notes", "field_label": "Writing notes",
                  "snippet": {"text": "…the \"harbour\" at <night>…", "marks": [[6, 13]]}}
        bare = {"kind": "series", "title": "Harbour", "title_marks": [[0, 7]], "where": "Series", "field": "name",
                "field_label": "", "snippet": None}
        given = {
            "marked": [["Café, ’s nachts <b>", [[0, 4]]], ["a & b < c", [[4, 5], [0, 1]]], ["x<y", [[1, 2]]],
                       ["abc", [[1, 9], [-2, 0], [2, 1]]], ["🌊 gull", [[3, 7]]], ["plain", None], ['say "hi"', [[4, 6]]]],
            "fresh": [[{"checked": "2026-11-13T14:20:00", "checking": False, "building": None}, "2026-11-13T14:20:09"],
                      [{"checked": "2026-11-13T14:20:00", "checking": False, "building": None}, "2026-11-13T14:20:10"],
                      [{"checked": "2026-11-13T14:20:00", "checking": False, "building": None}, "2026-11-13T14:22:30"],
                      [{"checked": "2026-11-13T14:20:00", "checking": True, "building": None}, "2026-11-13T14:20:01"],
                      [{"checked": None, "checking": True, "building": {"done": 1200, "total": 5000}}, "2026-11-13T14:20:01"],
                      [{"checked": None, "checking": True, "building": {"done": 0, "total": 0}}, "2026-11-13T14:20:01"],
                      [{"checked": None, "checking": False, "building": None}, "2026-11-13T14:20:01"]],
            "counts": [{"poems": 312, "books": 2, "designs": 41, "series": 3, "pieces": 40},
                       {"poems": 1, "books": 1, "designs": 1}, {"poems": 1200, "books": 0, "designs": 0}, {}],
            "ranges": [["Hold the line\nwhen they push", "line", 9], ["Hold the line\nwhen they push", "LINE", 0],
                       ["Café au lait", "café", 0], ["no match here", "gull", 3], ["a line, a line", "line", 10],
                       ["🌊 gull", "gull", 3], ["anything", "", 0], ["a.b (c)", "(c)", None]],
            "docs": [[ferry, "the night ferry"], [ferry, "NIGHT FERRY"], [quiet, "quiet harbour"], [quiet, "an aside"],
                     [quiet, "two and"], [quiet, "CAFÉ"], [quiet, "lighthouse"], [quiet, ""]],
            "rows": [result, bare],
            "nothing": '<b>"gull"',
            "more": [{"kind": "poem", "total": 23}, {"kind": "series", "total": 9}, {"kind": "design", "total": 1234},
                     {"kind": "research", "total": 12}],
            "heads": [{"label": "Poems", "total": 23}, {"label": "Designs", "total": 1200}],
        }
        r = subprocess.run([shutil.which("node"), "-e", NODE_SEARCH, str(STATIC / "vendor" / "prosemirror.js"),
                            str(STATIC / "book-schema.js"), str(STATIC / "app.js"), str(STATIC / "search.js"),
                            json.dumps(given)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        # marks go on by index, and every piece of the text is escaped on its own
        self.assertEqual(out["marked"], ["<mark>Café</mark>, ’s nachts &lt;b&gt;", "<mark>a</mark> &amp; <mark>b</mark> &lt; c",
                                         "x<mark>&lt;</mark>y", "a<mark>bc</mark>", "🌊 <mark>gull</mark>", "plain",
                                         "say <mark>&quot;h</mark>i&quot;"])
        self.assertEqual(out["fresh"], ["Checked just now", "Checked 1 min ago", "Checked 2 min ago", "Checking for changes…",
                                        "Reading the library… 1,200 of 5,000", "Reading the library…", ""])
        self.assertEqual(out["counts"], ["312 poems · 2 books · 41 designs", "1 poem · 1 book · 1 design", "1,200 poems", ""])
        self.assertEqual(out["ranges"], [[9, 13], [9, 13], [0, 4], None, [10, 14], [3, 7], None, [4, 7]])
        self.assertEqual(out["docs"], [["the night ferry", "paragraph"], ["Night ferry", "title"],
                                       ["quiet harbour", "paragraph"], None, ["two and", "paragraph"],
                                       ["café", "paragraph"], None, None])
        row, bare_row = out["rows"]
        self.assertIn('<span class="ls-t">&lt;Café&gt; <mark>Harbour</mark></span>', row)
        self.assertIn('<span class="ls-h">Salt &amp; Iron · Writing notes</span>', row)
        self.assertIn('<div class="ls-s">…the &quot;<mark>harbour</mark>&quot; at &lt;night&gt;…</div>', row)
        self.assertIn('role="option"', row)
        self.assertNotIn("<night>", row)
        self.assertIn('<span class="ls-h">Series</span>', bare_row)       # no field label: only where it is
        self.assertNotIn("ls-s", bare_row)                                # no snippet when only the title matches
        self.assertEqual(out["nothing"], '<p class="ls-none">Nothing in the library matches “&lt;b&gt;&quot;gull&quot;”.</p>')
        self.assertEqual(out["more"], ["Show all 23 poems", "Show all 9 series", "Show the first 200 of 1,234 designs",
                                       "Show all 12 research items"])
        self.assertEqual(out["heads"], ["Poems · 23", "Designs · 1,200"])

    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_search_js_poll_and_api(self):
        """A jump waits for its page with timers (requestAnimationFrame stops while the window isn't drawing), for 3
        seconds at most; LibrarySearch.search(q) is the spec's API: the /api/search reply."""
        r = subprocess.run([shutil.which("node"), "-e", NODE_POLL, str(STATIC / "search.js")],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["sync"], [0, 0, 0, 0])
        n, m, k, t = out["after"]
        self.assertEqual((n, k, t), (3, 0, 1))
        self.assertGreater(m, 2)
        self.assertLess(m, 30)                      # about 120 / 10 tries, then no more
        self.assertTrue(out["stopped"])
        self.assertEqual(out["reply"], {"q": "reply"})
        self.assertEqual(out["asked"], ["/api/search?q=caf%C3%A9%20%E2%80%9Csea%E2%80%9D"])
        search = (STATIC / "search.js").read_text(encoding="utf-8")
        self.assertFalse("requestAnimationFrame(" in search, "a jump waits on frames")
        self.assertTrue("const settle = (j, token) => poll(" in search)

    def test_backups_js_follows_the_server(self):
        """Settings says STUDIO_BACKUPS overrides the folder when the server says so (not by comparing paths); Back up
        now while one runs shows that one; the restore dialog offers the whole backup next to Cancel."""
        js = (STATIC / "backups.js").read_text(encoding="utf-8")
        self.assertIn("const env = !!d?.env_folder;", js)
        run_now = js[js.index("async function runNow(v)"):js.index("const reveal = ")]
        self.assertIn("if (e.status === 409) { toast(e.message); v.load(); }", run_now)
        self.assertIn('<div class="foot"><button type="button" class="btn quiet" data-close>Cancel</button>'
                      '<button type="button" class="btn quiet" id="lb-all">Restore the whole backup…</button>', js)
        self.assertIn('$("#lb-all", form).onclick = () => restoreAll(v, b, () => $("#dlg").close());', js)

    def test_search_is_wired_in(self):
        """The book palette's first action searches the library; Info lists Ctrl+K."""
        tools = (STATIC / "book-tools.js").read_text(encoding="utf-8")
        actions = tools[tools.index("  function actions() {"):tools.index("  const highlight = ")]
        self.assertIn('const q = R.pal?.input.value.trim() || "";', actions)
        listed = actions[actions.index("return [") + len("return ["):].lstrip()
        self.assertTrue(listed.startswith("...(root.LibrarySearch ? [act(q ? `Search the library for “${q}”` "
                                          ": \"Search the library…\", \"Library\", () => root.LibrarySearch.open(q))] : []),"),
                        listed[:200])
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        book = (STATIC / "book.js").read_text(encoding="utf-8")      # Info's writing-window keys are book.js's BOOK_KEYS
        self.assertIn('["Commands", "Ctrl+K", "Go to a piece, run an action or search the library"]', book)
        self.assertIn("BOOK_KEYS.flatMap", app)
        self.assertIn('<h2 class="h2">Keys</h2>', app)
        self.assertIn('["Ctrl+K", "search the library"]', app)


if __name__ == "__main__":
    unittest.main()
