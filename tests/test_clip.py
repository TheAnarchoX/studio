"""Web clips: fetching carefully, reading the page, and photographing Studio's script-free copy of it.

No test here touches the internet. The servers are local (127.0.0.1, in a thread); the default rules (public_only) are
exercised by what they refuse, and the fetch tests that need a local server pass an `allow` that lets it through."""
import gzip
import http.client
import http.server
import ipaddress
import re
import shutil
import socket
import tempfile
import threading
import time
import unittest
import zlib
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from PIL import Image

from studio import clip, config
from studio.research import ResearchError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "clip"
ARTICLE_URL = "https://example.org/2025/03/lighthouse-year"
LOCAL = "Studio clips pages on the internet, not on this computer or its network."


def EVERYWHERE(ip):
    """An `allow` that lets the local test servers through."""
    return True


def fixture(name) -> bytes:
    return (FIXTURES / name).read_bytes()


def page(name) -> str:
    return clip.decode_html(fixture(name), None)


@contextmanager
def serve(routes):
    """A local server: `routes` maps a path to a function(handler) that answers it. Yields (base URL, log); the log
    has one {"path", "headers"} per request, the headers as sent (a list of pairs)."""
    log = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            log.append({"path": self.path, "headers": list(self.headers.items())})
            route = routes.get(self.path.split("?")[0])
            if route is None:
                self.send_error(404)
            else:
                route(self)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", log
    finally:
        server.shutdown()
        server.server_close()


def answer(status=200, body=b"", headers=()):
    def route(h):
        h.send_response(status)
        for k, v in headers:
            h.send_header(k, v)
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)
    return route


def names(entry) -> dict:
    """A logged request's headers as {lower-case name: value}."""
    return {k.lower(): v for k, v in entry["headers"]}


class ReadableTest(unittest.TestCase):
    def test_readable_article(self):
        out = clip.readable(page("article.html"), ARTICLE_URL)
        self.assertEqual(out["title"], "The Lighthouse Keeper's Year")
        self.assertEqual(out["site"], "Example Times")
        self.assertEqual(out["author"], "An Example")
        self.assertEqual(out["published"], "2025-03-04")
        self.assertEqual(out["lang"], "en")
        self.assertEqual(out["canonical"], "https://example.org/2025/03/lighthouse-year")
        self.assertEqual(out["markdown"], (
            "## The Lighthouse Keeper's Year\n\n"
            "For twelve months the keeper wrote down the *weather*, the ships and the birds, in a ledger that is now "
            "kept at the [harbour museum](https://example.org/a).\n\n"
            "Every entry starts with the wind. Most of them end with the lamp, lit at dusk and put out at dawn.\n\n"
            "## From the ledger\n\n"
            "> Fog until noon. Two gulls on the rail, then none.\n\n"
            "- The weather, twice a day\n"
            "- Ships, by name\n"
            "- Birds, when there were any"))
        for gone in ("Home", "cookies", "Accept all", "Win a weekend", "offers", "All rights reserved", "Privacy",
                     "Written by a script", "visits", "Georgia"):
            self.assertNotIn(gone, out["markdown"])

    def test_readable_inline_rules(self):
        html = """<html><body><article>
<h3>Small <b>print</b></h3>
<p>One <strong>strong</strong> word, <i>an <em>inner</em> one</i>, <cite>A Book</cite> and <code>x = a*b</code>.</p>
<p>Line one<br>line two<br/>  line three</p>
<p>Stars * and_under [brackets] `ticks` back\\slash</p>
<p># not a heading</p>
<p>- not a list</p>
<p>+ nor this</p>
<p>&gt; nor a quote</p>
<p>2025. A year</p>
<p><a href="javascript:alert(1)">no link</a>, <a href="mailto:a@example.org">mail</a>,
<a href="https://example.org/x y(1)">odd</a>, <a href="#top">top</a> and <a>bare</a>.</p>
<ol><li>First</li><li>Second<ul><li>Inner</li></ul></li></ol>
<pre><code>def f():
    return 1
</code></pre>
<p hidden>Hidden.</p><p aria-hidden="true">Hidden too.</p><p style="color:red; display : none">Hidden three.</p>
<table><tr><td>Table text</td></tr></table>
<p>After<img src="/i.png" alt="an image"> the image.</p>
<div>Loose text in a div</div>
<h4>Deep</h4>
<form><p>Form text</p></form>
<svg><text>Drawing text</text></svg>
</article></body></html>"""
        self.assertEqual(clip.readable(html, "https://example.org/dir/page")["markdown"], (
            "### Small **print**\n\n"
            "One **strong** word, *an inner one*, *A Book* and `x = a*b`.\n\n"
            "Line one\\\nline two\\\nline three\n\n"
            "Stars \\* and\\_under \\[brackets\\] \\`ticks\\` back\\\\slash\n\n"
            "\\# not a heading\n\n"
            "\\- not a list\n\n"
            "\\+ nor this\n\n"
            "\\> nor a quote\n\n"
            "2025\\. A year\n\n"
            "no link, [mail](mailto:a@example.org), [odd](https://example.org/x%20y%281%29), top and bare.\n\n"
            "1. First\n"
            "2. Second\n"
            "   - Inner\n\n"
            "```\ndef f():\n    return 1\n```\n\n"
            "After the image.\n\n"
            "Loose text in a div\n\n"
            "### Deep"))

    def test_meta_charset(self):
        data = fixture("dutch.html")
        self.assertIn(b"\xeb", data)                     # ë as Windows-1252 writes it
        text = clip.decode_html(data, None)
        self.assertIn("Één winter aan zee", text)
        self.assertIn("Tweeëntwintig", text)
        self.assertIn("’s Avonds", text)
        self.assertNotIn("Tweeëntwintig", clip.decode_html(data, "utf-8"))     # the header's charset comes first
        self.assertIn("’s Avonds", clip.decode_html(data, "ISO-8859-1"))      # read as Windows-1252, as browsers do
        bom = b"\xef\xbb\xbf" + "Één".encode("utf-8")
        self.assertEqual(clip.decode_html(bom, "windows-1252"), "Één")          # a byte order mark wins
        self.assertEqual(clip.decode_html("Één".encode("utf-8"), None), "Één")  # nothing said: UTF-8
        self.assertEqual(clip.decode_html(b"caf\xe9", "no-such-charset"), "caf�")
        http_equiv = b'<meta http-equiv="Content-Type" content="text/html; charset=windows-1252"><p>\xeb</p>'
        self.assertIn("ë", clip.decode_html(http_equiv, None))
        out = clip.readable(text, "https://zee.example/winter")
        self.assertEqual((out["title"], out["lang"], out["site"]), ("Één winter aan zee", "nl", "zee.example"))
        self.assertIn("Tweeëntwintig meeuwen", out["markdown"])

    def test_jsonld_details(self):
        out = clip.readable(page("jsonld.html"), "https://www.marsh.example/notes/salt-marsh")
        self.assertEqual(out["title"], "Notes from the Salt Marsh")
        self.assertEqual(out["site"], "marsh.example")
        self.assertEqual(out["author"], "Bo Sample, Cy Sample")
        self.assertEqual(out["published"], "2024-11-02")         # JSON-LD before the first <time>
        self.assertEqual(out["lang"], "en-GB")
        self.assertEqual(out["canonical"], "")
        csl = clip.webpage_csl(out, "https://www.marsh.example/notes/salt-marsh", "2026-11-13T02:00:00", set())
        self.assertEqual(csl["author"], [{"family": "Sample", "given": "Bo"}, {"family": "Sample", "given": "Cy"}])
        self.assertEqual(csl["id"], "sample2024")

    def test_no_article_falls_back_to_densest_block(self):
        out = clip.readable(page("noarticle.html"), "https://tides.example/explained")
        self.assertEqual(out["title"], "Tide tables explained")
        self.assertEqual(out["site"], "tides.example")
        self.assertEqual(out["published"], "2023-06-15")          # the first <time datetime>
        self.assertEqual(out["author"], "")
        self.assertEqual(out["markdown"], (
            "Twice a day the water comes in and twice a day it goes out again.\n\n"
            "A tide table lists the times of high and low water for one harbour, with the height of each.\n\n"
            "Read it from the top: the first line is the first tide after midnight. The "
            "[tables page](https://tides.example/tables) has one for every harbour."))

    def test_details_fall_back(self):
        html = """<html><head><meta property="og:title" content="A og title - Elsewhere">
<meta property="og:site_name" content="Elsewhere"><meta property="article:author" content="https://social.example/someone">
<meta name="author" content="By Jan van der Berg"><title>Ignored | Elsewhere</title></head>
<body><main><p>Words in the main element.</p></main></body></html>"""
        out = clip.readable(html, "https://elsewhere.example/a")
        self.assertEqual((out["title"], out["site"], out["author"]), ("A og title", "Elsewhere", "Jan van der Berg"))
        self.assertEqual(out["markdown"], "Words in the main element.")
        csl = clip.webpage_csl(out, "https://elsewhere.example/a", "2026-11-13T02:00:00", set())
        self.assertEqual(csl["author"], [{"family": "Berg", "given": "Jan", "non-dropping-particle": "van der"}])
        self.assertEqual(csl["id"], "vanderberg")
        self.assertEqual(clip.readable("", "https://www.empty.example/")["markdown"], "")
        self.assertEqual(clip.readable("<p>x", "https://www.empty.example/")["title"], "")

    def test_title_tail_named_like_the_host(self):
        for title, url, want in (("Story | The Guardian", "https://www.theguardian.com/a", "Story"),
                                 ("Lighthouse - Wikipedia", "https://en.wikipedia.org/wiki/Lighthouse", "Lighthouse"),
                                 ("Lighthouse – Example Times", "https://example.org/", "Lighthouse"),   # the site name
                                 ("Plan - B", "https://b.example/", "Plan - B"),              # too short to tell
                                 ("Notes - Elsewhere", "https://example.org/", "Notes - Elsewhere"),
                                 ("Interview - Lee", "https://www.sleepnumber.com/a", "Interview - Lee")):  # not a label
            site = '<meta property="og:site_name" content="Example Times">' if "Example Times" in title else ""
            self.assertEqual(clip.readable(f"{site}<title>{title}</title>", url)["title"], want, title)

    def test_wikipedia_furniture_left_out(self):
        html = """<!DOCTYPE html><html lang="en"><head><title>Lighthouse - Wikipedia</title></head><body><main>
<h2><span class="mw-headline">History</span><span class="mw-editsection"><span class="mw-editsection-bracket">[</span><a
 href="/w/index.php?title=Lighthouse&amp;action=edit&amp;section=1">edit</a><span class="mw-editsection-bracket">]</span></span></h2>
<p>The first lighthouse stood on a rock.<sup id="cite_ref-1" class="reference"><a href="#cite_note-1">[1]</a></sup> It burned
wood.<sup class="noprint Inline-Template"><i><a href="/wiki/Help:Citation_needed">citation needed</a></i></sup></p>
<p>Later ones burned oil. <a href="/w/index.php?title=Oil_lamp&amp;action=edit&amp;redlink=1">Oil lamps</a> were brighter.
<a href="/w/index.php?title=Lighthouse&amp;action=edit">Change this</a></p>
<div class="navbox"><a href="/wiki/A">A</a> <a href="/wiki/B">B</a></div>
<div class="metadata"><p>This article is a stub.</p></div>
</main></body></html>"""
        out = clip.readable(html, "https://en.wikipedia.org/wiki/Lighthouse")
        self.assertEqual(out["title"], "Lighthouse")
        self.assertEqual(out["markdown"], (
            "## History\n\n"
            "The first lighthouse stood on a rock. It burned wood.\n\n"
            "Later ones burned oil. Oil lamps were brighter."))      # a red link keeps its words, not its link


class SafePageTest(unittest.TestCase):
    def test_safe_page_strips_everything_active(self):
        html = """<!DOCTYPE html>
<html lang="en" onload="x()">
<head profile="x">
<meta charset="windows-1252">
<meta http-equiv="refresh" content="0; url=https://evil.example/">
<base href="https://evil.example/">
<link rel="prefetch" href="https://evil.example/next">
<link rel="dns-prefetch" href="//evil.example">
<link rel="stylesheet" href="/site.css">
<meta name="referrer" content="unsafe-url">
<script>alert(1)</script>
<style>p > b { color: red }</style>
<title>A &amp; B</title>
</head>
<body onload="alert(2)" class="page">
<p>Kept <b>text</b> &amp; more &lt;tags&gt;</p>
<svg><script>alert(3)</script><circle r="4"/><a xlink:href="javascript:alert(7)">svg link</a></svg>
<a href="javascript:alert(4)">bad link</a>
<a href=" JaVaScRiPt:alert(5)">bad link 2</a>
<a href="/fine" ping="https://evil.example/ping">fine link</a>
<img src="/i.png" onerror="alert(6)" referrerpolicy="unsafe-url" srcset="/i2.png 2x">
<iframe src="https://evil.example/frame"><p>inside frame</p></iframe>
<object data="x.swf"><embed src="x.swf"><p>inside object</p></object>
<embed src="y.swf">
<noscript><img src="/fallback.png"></noscript>
<form action="https://evil.example/post"><input name="q"></form>
</body>
</html>"""
        out = clip.safe_page(html, "https://example.org/page?a=1&b=2")
        low = out.lower()
        for gone in ("<script", "alert", "onload", "onerror", "javascript:", "refresh", "evil.example", "<iframe",
                     "<object", "<embed", "prefetch", "unsafe-url", "referrerpolicy", "windows-1252", "ping=",
                     "inside frame", "inside object", "profile="):
            self.assertNotIn(gone, low)
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        head = out[out.index("<head>") + len("<head>"):]
        csp, rest = head.split(">", 1)
        self.assertTrue(csp.startswith('<meta http-equiv="Content-Security-Policy" content="'))
        for rule in ("script-src 'none'", "object-src 'none'", "frame-src 'none'", "form-action 'none'"):
            self.assertIn(rule, csp)
        self.assertTrue(rest.startswith('<meta name="referrer" content="no-referrer">'
                                        '<base href="https://example.org/page?a=1&amp;b=2">'))
        self.assertEqual(low.count("<head"), 1)
        self.assertEqual(low.count("<base"), 1)
        self.assertEqual(low.count('name="referrer"'), 1)
        for kept in ('<html lang="en">', '<link rel="stylesheet" href="/site.css">', "<style>p > b { color: red }</style>",
                     "<title>A &amp; B</title>", '<body class="page">', "<p>Kept <b>text</b> &amp; more &lt;tags&gt;</p>",
                     '<circle r="4"/>', "svg link", '<a href="/fine">fine link</a>', '<img src="/i.png" srcset="/i2.png 2x">',
                     '<img src="/fallback.png">', "<form"):
            self.assertIn(kept, out)

    def test_safe_page_duplicate_attributes_and_style_comments(self):
        """A repeated attribute counts as its first, as in browsers, in every check; old HTML comment markers in a
        style are left out (CSS ignores them) so its first rule isn't lost to an escaped "<"."""
        for html in ('<meta name="referrer" name="x" content="unsafe-url">',
                     '<link rel="prefetch" rel="stylesheet" href="https://evil.example/next">',
                     '<link rel="dns-prefetch" rel="stylesheet" href="//evil.example">'):
            out = clip.safe_page(html, "https://example.org/")
            self.assertNotIn("unsafe-url", out, html)
            self.assertNotIn("evil.example", out, html)
        out = clip.safe_page('<link rel="stylesheet" rel="prefetch" href="/s.css">', "https://example.org/")
        self.assertIn('<link rel="stylesheet" href="/s.css">', out)
        out = clip.safe_page('<img src="/a.png" attributionsrc="https://evil.example/r">', "https://example.org/")
        self.assertIn('<img src="/a.png">', out)
        self.assertNotIn("evil.example", out)
        out = clip.safe_page("<style><!-- body { color: red } --></style>", "https://example.org/")
        self.assertIn("<style> body { color: red } </style>", out)

    def test_safe_page_without_head_or_doctype(self):
        out = clip.safe_page("<p onclick='x()'>Bare</p>", "https://example.org/")
        self.assertTrue(out.startswith('<html><head><meta http-equiv="Content-Security-Policy"'))
        self.assertIn("<p>Bare</p>", out)
        self.assertNotIn("onclick", out)

    def check_raw_text(self):
        evil = '<img src=x onerror=alert(1)><meta http-equiv="refresh" content="0;url=https://evil.example/"><p>in</p>'
        prelude_end = '<base href="https://example.org/">'
        for case, inside in ((f"<svg><style>{evil}</style></svg>", True),
                             (f"<math><style>{evil}</style></math>", True),
                             (f"<svg><xmp>{evil}</xmp></svg>", True),
                             (f"<xmp>{evil}</xmp>", True),
                             (f"<style>{evil}</style>", True),
                             (f"<title>{evil}</title>", True),
                             (f"<textarea>{evil}</textarea>", True),
                             (f"<xmp><style></xmp>{evil}</style>", False),
                             (f"<textarea><style></textarea>{evil}</style>", False),
                             (f"<title><style></title>{evil}</style>", False)):
            out = clip.safe_page(case, "https://example.org/")
            body = out[out.index(prelude_end) + len(prelude_end):].lower()
            self.assertIsNone(re.search(r"<meta\b", body), case)
            if inside:                  # what was inside the raw text stays text: no element is made of it
                self.assertIsNone(re.search(r"<(img|p)\b", body), case)
            else:                       # after the raw text it is markup, as a browser reads it: filtered as ever
                for gone in ("onerror", "http-equiv", "refresh", "evil.example"):
                    self.assertNotIn(gone, body, case)
        self.assertIn('<style>a::before { content: "\\3c b>" }</style>',
                      clip.safe_page('<style>a::before { content: "<b>" }</style>', "https://example.org/"))
        self.assertIn("<pre>&lt;b&gt;&amp;amp;</pre>", clip.safe_page("<xmp><b>&amp;</xmp>", "https://example.org/"))
        self.assertIn("<title>&lt;b&gt; &amp; c</title>", clip.safe_page("<title><b> &amp; c</title>", "https://example.org/"))

    def test_safe_page_raw_text_never_becomes_markup(self):
        """Text the parser reads raw (style, xmp) or as text (title, textarea) never comes out with a literal "<":
        inside <svg> or <math> Chrome reads a <style>'s content as markup."""
        self.check_raw_text()

    def test_safe_page_raw_text_on_an_older_parser(self):
        """Python 3.11's parser reads only script and style raw, and <title>, <textarea> and <xmp> as markup."""
        with mock.patch.object(clip._SafeCopy, "CDATA_CONTENT_ELEMENTS", ("script", "style")), \
                mock.patch.object(clip._SafeCopy, "RCDATA_CONTENT_ELEMENTS", (), create=True), \
                mock.patch.object(clip, "_RAW_TEXT", frozenset({"script", "style"})), \
                mock.patch.object(clip, "_RCDATA", frozenset()):
            self.check_raw_text()


class FetchTest(unittest.TestCase):
    def test_fetch_refuses(self):
        for url, why in (("ftp://x", "Only web addresses (http or https) can be clipped."),
                         ("mailto:a@example.org", "Only web addresses (http or https) can be clipped."),
                         ("http:///nohost", "Only web addresses (http or https) can be clipped."),
                         ("http://user:pw@example.org/", clip.CREDENTIALS)):
            with self.assertRaises(clip.ClipError) as cm:
                clip.fetch(url)
            self.assertEqual(str(cm.exception), why, url)
            self.assertEqual(cm.exception.code, 400)
        self.assertTrue(issubclass(clip.ClipError, ResearchError))
        with serve({"/": answer(body=b"<p>home</p>")}) as (base, log):
            for url in (base + "/", base.replace("127.0.0.1", "localhost") + "/"):
                with self.assertRaises(clip.ClipError) as cm:
                    clip.fetch(url)
                self.assertEqual(str(cm.exception), LOCAL)
            self.assertEqual(log, [])                   # refused before a byte was sent
        for ip in ("10.0.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "::1", "::ffff:127.0.0.1", "224.0.0.1",
                   "127.0.0.1", "0.0.0.0", "172.16.0.1", "fc00::1", "fe80::1", "ff02::1", "::ffff:10.0.0.1",
                   "2002:7f00:1::", "64:ff9b::7f00:1", "64:ff9b::a00:1", "198.18.0.1", "240.0.0.1",
                   "::7f00:1", "::a00:1", "::5db8:d70e", "fec0::1", "feff::1"):     # IPv4-compatible, site-local
            self.assertFalse(clip.public_only(ipaddress.ip_address(ip)), ip)
        for ip in ("93.184.215.14", "2606:4700::1111", "::ffff:93.184.215.14", "64:ff9b::5db8:d70e", "1.1.1.1"):
            self.assertTrue(clip.public_only(ipaddress.ip_address(ip)), ip)

    def test_fetch_local_server(self):
        html = "<!DOCTYPE html><p>Één pagina</p>".encode("utf-8")
        routes = {"/start": answer(302, headers=[("Location", "/page?x=1")]),
                  "/page": answer(body=gzip.compress(html), headers=[("Content-Type", "text/html; charset=UTF-8"),
                                                                      ("Content-Encoding", "gzip")]),
                  "/deflate": answer(body=zlib.compress(html), headers=[("Content-Type", "text/html"),
                                                                        ("Content-Encoding", "deflate")]),
                  "/raw-deflate": answer(body=zlib.compress(html)[2:-4], headers=[("Content-Encoding", "deflate")]),
                  "/pdf": answer(body=b"%PDF-1.4\n%\xe2\xe3\n", headers=[("Content-Type", "application/octet-stream")])}
        with serve(routes) as (base, log):
            got = clip.fetch(base + "/start", allow=EVERYWHERE)
            self.assertIsInstance(got, clip.Fetched)
            self.assertEqual((got.url, got.final_url, got.status), (base + "/start", base + "/page?x=1", 200))
            self.assertEqual((got.ctype, got.charset, got.data), ("text/html", "utf-8", html))
            self.assertEqual([e["path"] for e in log], ["/start", "/page?x=1"])
            for entry in log:
                self.assertEqual(names(entry), {
                    "host": base[len("http://"):], "user-agent": clip.UA,
                    "accept": "text/html,application/xhtml+xml,image/*;q=0.9,application/pdf;q=0.9,*/*;q=0.5",
                    "accept-encoding": "gzip, deflate", "connection": "close"})
            self.assertRegex(clip.UA, r"^Mozilla/5\.0 \(compatible; Studio/\d+\.\d+\.\d+\)$")
            self.assertEqual(clip.fetch(base + "/deflate", allow=EVERYWHERE).data, html)
            raw = clip.fetch(base + "/raw-deflate", allow=EVERYWHERE)
            self.assertEqual((raw.data, raw.ctype), (html, "text/html"))       # no type said: the bytes tell
            self.assertEqual(clip.fetch(base + "/pdf", allow=EVERYWHERE).ctype, "application/pdf")

    def test_fetch_errors_from_the_site(self):
        routes = {"/forbidden": answer(403), "/gone": answer(404), "/broken": answer(500)}
        with serve(routes) as (base, log):
            for path, why in (("/forbidden", "The site refused the request (403)."),
                              ("/gone", "The site answered 404 (Not Found)."),
                              ("/broken", "The site answered 500 (Internal Server Error).")):
                with self.assertRaises(clip.ClipError) as cm:
                    clip.fetch(base + path, allow=EVERYWHERE)
                self.assertEqual(str(cm.exception), why)
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        with self.assertRaises(clip.ClipError) as cm:
            clip.fetch(f"http://127.0.0.1:{port}/", allow=EVERYWHERE, timeout=5)
        self.assertEqual(str(cm.exception), "Studio couldn't reach 127.0.0.1.")
        with socket.socket() as silent:         # accepts the connection, never answers
            silent.bind(("127.0.0.1", 0))
            silent.listen()
            with self.assertRaises(clip.ClipError) as cm:
                clip.fetch(f"http://127.0.0.1:{silent.getsockname()[1]}/", allow=EVERYWHERE, timeout=0.5)
            self.assertEqual(str(cm.exception), "The site took too long to answer.")

    def test_time_limit_is_a_total(self):
        """A site that sends its answer a byte at a time can't hold the request past the limit: each read is quick,
        the whole isn't."""
        stop = threading.Event()

        def drip(server):
            conn, _ = server.accept()
            with conn:
                conn.recv(65536)
                for b in b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\nX-Slow: " + b"a" * 60:
                    if stop.wait(0.2):
                        return
                    try:
                        conn.sendall(bytes([b]))
                    except OSError:
                        return

        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            t = threading.Thread(target=drip, args=(server,), daemon=True)
            t.start()
            began = time.monotonic()
            with self.assertRaises(clip.ClipError) as cm:
                clip.fetch(f"http://127.0.0.1:{server.getsockname()[1]}/", allow=EVERYWHERE, timeout=1)
            took = time.monotonic() - began
            stop.set()
            t.join(5)
        self.assertEqual(str(cm.exception), "The site took too long to answer.")
        self.assertLess(took, 3)

    def test_malformed_host(self):
        for url in ("http://a..b/", clip.address("example..org"), "https://" + "x" * 70 + ".example/"):
            with self.assertRaises(clip.ClipError) as cm:
                clip.fetch(url)
            self.assertEqual(str(cm.exception), "That web address isn't valid.", url)

    def test_redirect_to_loopback_refused(self):
        calls = []

        def first_only(ip):
            calls.append(ip)
            return len(calls) == 1

        routes = {"/away": lambda h: answer(302, headers=[("Location", f"http://127.0.0.1:{h.server.server_address[1]}/x")])(h),
                  "/x": answer(body=b"<p>secret</p>")}
        with serve(routes) as (base, log):
            with self.assertRaises(clip.ClipError) as cm:
                clip.fetch(base + "/away", allow=first_only)
            self.assertEqual(str(cm.exception), LOCAL)
            self.assertEqual([e["path"] for e in log], ["/away"])
            self.assertEqual([str(ip) for ip in calls], ["127.0.0.1", "127.0.0.1"])

    def test_too_large(self):
        routes = {"/big": answer(body=b"x" * 5000),
                  "/unsaid": lambda h: (h.send_response(200), h.send_header("Connection", "close"), h.end_headers(),
                                        h.wfile.write(b"y" * 5000)),
                  "/bomb": answer(body=gzip.compress(b"z" * 50_000), headers=[("Content-Encoding", "gzip")])}
        with serve(routes) as (base, log):
            for path in ("/big", "/unsaid", "/bomb"):
                with self.assertRaises(clip.ClipError) as cm:
                    clip.fetch(base + path, allow=EVERYWHERE, limit=1000)
                self.assertEqual(str(cm.exception), "The page is larger than 1 KB.", path)
            self.assertEqual(clip.fetch(base + "/big", allow=EVERYWHERE, limit=5000).data, b"x" * 5000)
        self.assertEqual(clip._size(10_000_000), "10 MB")

    def test_too_many_redirects(self):
        with serve({"/loop": answer(301, headers=[("Location", "/loop")])}) as (base, log):
            with self.assertRaises(clip.ClipError) as cm:
                clip.fetch(base + "/loop", allow=EVERYWHERE)
            self.assertEqual(str(cm.exception), "Studio stopped after 5 redirects.")
            self.assertEqual(len(log), 6)               # the page and the 5 redirects it was allowed

    def test_address(self):
        self.assertEqual(clip.address(" example.org/a "), "https://example.org/a")
        self.assertEqual(clip.address("example.org:8080/a"), "https://example.org:8080/a")
        self.assertEqual(clip.address("//example.org/a"), "https://example.org/a")
        self.assertEqual(clip.address("HTTP://example.org"), "HTTP://example.org")
        self.assertEqual(clip.address("ftp://x"), "ftp://x")
        for empty in ("", "  ", None, 3):
            with self.assertRaises(clip.ClipError):
                clip.address(empty)


class GateTest(unittest.TestCase):
    def raw(self, port, request: bytes) -> bytes:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
            s.sendall(request)
            out = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    return out
                out += chunk

    def test_gate(self):
        routes = {"/hello": answer(body=b"hello", headers=[("Content-Type", "text/plain")]),
                  "/big": answer(body=b"b" * 5000)}
        with serve(routes) as (base, log):
            host = base[len("http://"):]
            with clip.Gate(allow=lambda ip: True) as gate:
                conn = http.client.HTTPConnection("127.0.0.1", gate.port, timeout=10)
                conn.request("GET", base + "/hello?x=1", headers={
                    "Cookie": "a=1", "Referer": "https://example.org/", "Accept-Language": "nl,en;q=0.8",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130", "Proxy-Authorization": "Basic eA==",
                    "Accept": "image/*"})
                resp = conn.getresponse()
                self.assertEqual((resp.status, resp.read(), resp.getheader("Content-Type")), (200, b"hello", "text/plain"))
                conn.close()
                sent = names(log[-1])
                self.assertEqual(log[-1]["path"], "/hello?x=1")
                self.assertEqual((sent["user-agent"], sent["accept"], sent["host"]), (clip.UA, "image/*", host))
                for gone in ("cookie", "referer", "accept-language", "proxy-authorization"):
                    self.assertNotIn(gone, sent)
                # a tunnel (how Chrome asks for https) carries bytes both ways once the address is allowed
                reply = self.raw(gate.port, f"CONNECT {host} HTTP/1.1\r\nHost: {host}\r\n\r\n"
                                            f"GET /hello HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
                self.assertTrue(reply.startswith(b"HTTP/1.1 200 Connection established\r\n\r\nHTTP/1.0 200"), reply[:80])
                self.assertTrue(reply.endswith(b"hello"))
                self.assertEqual(gate.refused, [])
                # only GET, HEAD and CONNECT
                self.assertIn(b" 403 ", self.raw(gate.port, f"POST {base}/hello HTTP/1.1\r\nHost: {host}\r\n"
                                                            "Content-Length: 0\r\n\r\n".encode())[:20])
                self.assertIn(b" 403 ", self.raw(gate.port, f"GET /hello HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())[:20])
            count = len(log)
            with clip.Gate() as gate:                   # the default rule: this computer is refused
                conn = http.client.HTTPConnection("127.0.0.1", gate.port, timeout=10)
                conn.putrequest("CONNECT", host, skip_host=True, skip_accept_encoding=True)
                conn.endheaders()
                self.assertEqual(conn.getresponse().status, 403)
                conn.close()
                conn = http.client.HTTPConnection("127.0.0.1", gate.port, timeout=10)
                conn.request("GET", base + "/hello")
                self.assertEqual(conn.getresponse().status, 403)
                conn.close()
                self.assertEqual(gate.refused, ["127.0.0.1", "127.0.0.1"])
            self.assertEqual(len(log), count)           # nothing reached the server
            with clip.Gate(allow=lambda ip: True, limit=1000) as gate:
                reply = self.raw(gate.port, f"GET {base}/big HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
                self.assertTrue(reply.startswith(b"HTTP/1.1 200"))
                self.assertLessEqual(len(reply), 1000)      # cut off at the limit
                self.assertGreater(len(reply), 100)
                self.assertIn(b" 403 ", self.raw(gate.port, f"GET {base}/hello HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())[:20])

    def test_chrome_flags(self):
        self.assertEqual(clip.CHROME_FLAGS, (
            f"--user-agent={clip.UA}", "--accept-lang=en", "--disable-background-networking", "--disable-component-update",
            "--disable-sync", "--disable-default-apps", "--no-pings", "--disable-domain-reliability", "--mute-audio",
            "--disable-quic", "--disable-features=Translate,MediaRouter,OptimizationHints,NetworkTimeServiceQuerying,"
            "SafeBrowsingHashPrefixRealTimeLookups,PreconnectToSearch,AimEnabled", "--gaia-url=http://0.0.0.0:9/",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"))
        self.assertEqual(sum(f.startswith("--disable-features=") for f in clip.CHROME_FLAGS), 1)   # Chrome reads the last


class CslTest(unittest.TestCase):
    def test_webpage_csl(self):
        details = {"title": "", "site": "Example Times", "author": "An Example", "published": "2025-03-04"}
        csl = clip.webpage_csl(details, ARTICLE_URL, "2026-11-13T01:20:00", set())
        self.assertEqual(csl, {"type": "webpage", "id": "example2025", "author": [{"family": "Example", "given": "An"}],
                               "issued": {"date-parts": [[2025, 3, 4]]}, "container-title": "Example Times",
                               "URL": ARTICLE_URL, "accessed": {"date-parts": [[2026, 11, 13]]}})
        self.assertEqual(clip.webpage_csl(details, ARTICLE_URL, "2026-11-13T01:20:00", {"example2025"})["id"], "example2025b")
        titled = {"title": "The Lighthouse Keeper's Year", "site": "Example Times", "author": "", "published": "2025-03"}
        csl = clip.webpage_csl(titled, ARTICLE_URL, "2026-11-13T01:20:00", set())
        self.assertEqual((csl["id"], csl["title"], csl["issued"]), ("lighthouse2025", titled["title"], {"date-parts": [[2025, 3]]}))
        self.assertNotIn("author", csl)
        bare = clip.webpage_csl({"title": "", "site": "", "author": "", "published": ""}, ARTICLE_URL, "2026-11-13T01:20:00", set())
        self.assertEqual(bare, {"type": "webpage", "id": "source", "URL": ARTICLE_URL, "accessed": {"date-parts": [[2026, 11, 13]]}})
        self.assertEqual(clip.webpage_csl({"author": "Example, An"}, ARTICLE_URL, "2026-11-13", set())["author"],
                         [{"family": "Example", "given": "An"}])
        self.assertEqual(clip.webpage_csl({"author": "Newsroom"}, ARTICLE_URL, "2026-11-13", set())["author"],
                         [{"literal": "Newsroom"}])
        for org in ("Contributors to Wikimedia projects", "The Example Times Editorial Board Staff", "staff writers"):
            self.assertEqual(clip.webpage_csl({"author": org}, ARTICLE_URL, "2026-11-13", set())["author"], [{"literal": org}])
        self.assertEqual(clip.webpage_csl({"author": "Contributors to Wikimedia projects", "published": "2005-01-02"},
                                          ARTICLE_URL, "2026-11-13", set())["id"], "contributorstowikimediaprojects2005")
        self.assertEqual(clip.webpage_csl({"author": "Anna de la Cruz"}, ARTICLE_URL, "2026-11-13", set())["author"],
                         [{"family": "Cruz", "given": "Anna", "non-dropping-particle": "de la"}])

    def test_bylines_with_several_people(self):
        def people(byline, published=""):
            csl = clip.webpage_csl({"author": byline, "published": published}, ARTICLE_URL, "2026-11-13", set())
            return csl["author"], csl["id"]
        self.assertEqual(people("Ann One, Bob Two, Cy Three", "2025"),
                         ([{"family": "One", "given": "Ann"}, {"family": "Two", "given": "Bob"},
                           {"family": "Three", "given": "Cy"}], "one2025"))
        self.assertEqual(people("Mary Ann Smith and John Paul Jones")[0],
                         [{"family": "Smith", "given": "Mary Ann"}, {"family": "Jones", "given": "John Paul"}])
        self.assertEqual(people("Jan van der Berg and Anna de la Cruz")[0],
                         [{"family": "Berg", "given": "Jan", "non-dropping-particle": "van der"},
                          {"family": "Cruz", "given": "Anna", "non-dropping-particle": "de la"}])
        self.assertEqual(people("Jan van Dam en Piet Jansen; Bo Sample & Cy Sample")[0],
                         [{"family": "Dam", "given": "Jan", "non-dropping-particle": "van"},
                          {"family": "Jansen", "given": "Piet"}, {"family": "Sample", "given": "Bo"},
                          {"family": "Sample", "given": "Cy"}])
        self.assertEqual(people("Contributors to Wikimedia projects")[0], [{"literal": "Contributors to Wikimedia projects"}])
        self.assertEqual(people("An Example, the newsroom")[0], [{"family": "Example", "given": "An"}, {"literal": "the newsroom"}])


def _pixel(img, x, y):
    return img.getpixel((x, y))[:3]


@unittest.skipUnless(config.CHROME, "no Chrome or Edge found")
class PictureTest(unittest.TestCase):
    def test_picture_runs_no_scripts(self):
        gates = []

        class Recording(clip.Gate):
            def __enter__(self):
                gates.append(self)
                return super().__enter__()

            def _connect(self, host, port):
                if host in ("127.0.0.1", "localhost"):      # the page's own requests: the default rule decides
                    return super()._connect(host, port)
                self.asked.append(host)                     # anything else is Chrome's own: noted, never let out
                self.refused.append(host)
                return None

        with serve({"/probe.png": answer(body=b"\x89PNG\r\n\x1a\n")}) as (base, log):
            html = f"""<!DOCTYPE html><html><head><style>
body {{ margin: 0; background: rgb(255, 255, 255); }}
#box {{ position: absolute; left: 40px; top: 40px; width: 300px; height: 300px; background: rgb(0, 160, 0); }}
.dot {{ position: absolute; top: 40px; width: 10px; height: 10px; }}
</style></head><body>
<div id="box"></div>
<script>document.getElementById("box").style.background = "rgb(255, 0, 0)";</script>
<img class="dot" style="left: 600px" src="missing.png" onerror="document.body.style.background = 'rgb(0, 0, 255)'">
<img class="dot" style="left: 700px" src="{base}/probe.png">
<img class="dot" style="left: 800px" src="{base.replace("127.0.0.1", "localhost")}/probe.png">
<svg width="10" height="10"><style><meta http-equiv="refresh" content="0;url=http://refresh.invalid/"><img src="http://img.invalid/x.png"></style></svg>
</body></html>"""
            tmp = Path(tempfile.mkdtemp(prefix="studio-picture-test-"))
            self.addCleanup(shutil.rmtree, tmp, True)
            out = tmp / "shot.jpg"
            with mock.patch.object(clip, "Gate", Recording):
                got, why = clip.picture(html, base + "/page.html", out)
            self.assertEqual((got, why), (out, ""))
            with Image.open(out) as img:
                self.assertEqual((img.format, img.size), ("JPEG", (1280, 1600)))
                r, g, b = _pixel(img, 190, 190)
                self.assertTrue(g > 120 and r < 80 and b < 80, (r, g, b))            # the script didn't paint it red
                self.assertTrue(min(_pixel(img, 1000, 1000)) > 230, _pixel(img, 1000, 1000))   # onerror didn't paint blue
            self.assertEqual(log, [])                   # Chrome's requests for this computer were refused
            self.assertEqual(len(gates), 1)
            self.assertEqual(set(gates[0].refused), {"127.0.0.1", "localhost"})   # through the gate, which said no
            self.assertEqual(set(gates[0].asked), {"127.0.0.1", "localhost"})     # and Chrome asked for nothing of its own,
            # nor for refresh.invalid or img.invalid: the <style> inside <svg> stayed text, so no refresh, no image


class PictureFailureTest(unittest.TestCase):
    def test_picture_without_chrome(self):
        with mock.patch.object(config, "CHROME", ""):
            self.assertEqual(clip.picture("<p>x</p>", "https://example.org/", Path("x.jpg")),
                             (None, "Studio found no Chrome or Edge to take the picture with."))

    def test_picture_when_chrome_fails(self):
        tmp = Path(tempfile.mkdtemp(prefix="studio-picture-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(config, "CHROME", "chrome"), \
                mock.patch.object(clip.shoot, "screenshot", side_effect=RuntimeError("crashed")):
            self.assertEqual(clip.picture("<p>x</p>", "https://example.org/", tmp / "x.jpg"),
                             (None, "The picture couldn't be taken."))
        self.assertEqual(list(tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
