"""Web clips: fetching a page the author asked for, and photographing Studio's own script-free copy of it.

The rules (the spec's "Web clips"), and where each is kept:

- Studio fetches only what the author asked for (Research.clip calls `fetch` once per ask), only http and https, and
  only addresses on the internet. The address is checked on the connected socket itself, before a byte is sent, and
  again for every redirect, so a name that points at this computer or its network is refused whatever DNS says.
- Nothing about the author is sent: no cookies (none are kept), no referrer, no languages, a plain User-Agent.
- A clipped page never runs its scripts. Chrome photographs `safe_page`, a copy with every script, handler, frame and
  refresh taken out and a policy that forbids them put first. Every request Chrome makes for that copy (its styles,
  images and fonts) goes through the Gate, a small proxy on 127.0.0.1 that applies the same address rule.

The readable copy (the details and the Markdown) is made in clip_read.py."""
from __future__ import annotations

import codecs
import http.client
import ipaddress
import re
import select
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import zlib
from collections import namedtuple
from contextlib import contextmanager
from html import escape, unescape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

from . import __version__, config, shoot
from .clip_read import readable, site_of  # noqa: F401 (part of this module's interface: Research.clip uses them)
from .research import ResearchError
from .research_sources import source_key

UA = f"Mozilla/5.0 (compatible; Studio/{__version__})"
HEADERS = (("User-Agent", UA),
           ("Accept", "text/html,application/xhtml+xml,image/*;q=0.9,application/pdf;q=0.9,*/*;q=0.5"),
           ("Accept-Encoding", "gzip, deflate"),
           ("Connection", "close"))
REDIRECTS = (301, 302, 303, 307, 308)
HTML_TYPES = ("text/html", "application/xhtml+xml")
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
PDF = "application/pdf"
# Chrome's own requests are turned off too. Measured on Chrome 157 (13 November 2026) through a Gate that refused
# everything: without the last two flags Chrome asked for clients2.google.com/time (network time), www.gstatic.com
# (Safe Browsing's key fetch), www.google.com (a search preconnect and an AI-mode check that sends the computer's
# country) and accounts.google.com (sign-in's account list, sent nowhere by --gaia-url). Chrome reads only the last
# --disable-features, so they are all in one. WebRTC (which needs scripts) is kept off the network outside the proxy too.
CHROME_FLAGS = (f"--user-agent={UA}", "--accept-lang=en", "--disable-background-networking", "--disable-component-update",
                "--disable-sync", "--disable-default-apps", "--no-pings", "--disable-domain-reliability", "--mute-audio",
                "--disable-quic", "--disable-features=Translate,MediaRouter,OptimizationHints,NetworkTimeServiceQuerying,"
                "SafeBrowsingHashPrefixRealTimeLookups,PreconnectToSearch,AimEnabled", "--gaia-url=http://0.0.0.0:9/",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp")
PICTURE = (1280, 1600)

LOCAL = "Studio clips pages on the internet, not on this computer or its network."
SCHEME = "Only web addresses (http or https) can be clipped."
CREDENTIALS = "Studio doesn't clip addresses with a user name or password in them."
NO_ADDRESS = "Say which page to clip."
SLOW = "The site took too long to answer."
INVALID = "That web address isn't valid."
UNREADABLE = "The site's answer couldn't be read."
NO_CHROME = "Studio found no Chrome or Edge to take the picture with."
NO_PICTURE = "The picture couldn't be taken."

Fetched = namedtuple("Fetched", "url final_url status ctype charset data")


class ClipError(ResearchError):
    """A page that couldn't be clipped: a 400 carrying the reason in the words the board shows."""


# ——— which addresses ———
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_COMPATIBLE = ipaddress.ip_network("::/96")         # IPv4-compatible IPv6 (deprecated): ::7f00:1 is 127.0.0.1


def public_only(ip) -> bool:
    """True for an address on the internet; false for loopback, private, link-local, site-local, shared, reserved and
    multicast ones. An IPv6 address that carries an IPv4 one (mapped, 6to4, the NAT64 prefix) is judged by that IPv4
    address; the old IPv4-compatible range (::/96) is refused outright."""
    if ip.version == 6:
        if ip.is_site_local or ip in _COMPATIBLE:
            return False
        inner = ip.ipv4_mapped or ip.sixtofour or (ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF) if ip in _NAT64 else None)
        if inner is not None:
            return public_only(inner)
    return ip.is_global and not ip.is_multicast


def address(text) -> str:
    """The address to fetch from what the author typed or dropped: trimmed, and https:// when it has no scheme of its
    own (example.org/a, example.org:8080/a, //example.org/a)."""
    if not isinstance(text, str) or not text.strip():
        raise ClipError(NO_ADDRESS)
    text = text.strip()
    if text.startswith("//"):
        return "https:" + text
    return text if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:(?!\d)", text) else "https://" + text


def file_name(url) -> str:
    """The last part of an address's path, decoded (`Tide%20Report.pdf` → `Tide Report.pdf`)."""
    try:
        return unquote(urlsplit(url).path.rsplit("/", 1)[-1]).strip()
    except ValueError:
        return ""


# ——— fetching ———
def _checked(url):
    """The address split, when Studio may fetch it: http or https, a host, no user name or password."""
    try:
        s = urlsplit(url)
        s.port                          # a port that isn't a number raises here
    except (ValueError, TypeError):
        raise ClipError(SCHEME) from None
    if s.scheme.lower() not in ("http", "https") or not s.hostname or any(ord(c) <= 32 for c in s.netloc):
        raise ClipError(SCHEME)
    if s.username is not None or s.password is not None:
        raise ClipError(CREDENTIALS)
    return s


def _ascii(host: str) -> str:
    if host.isascii():
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        raise ClipError(INVALID) from None


def _peer(sock) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """The address a socket is connected to (an IPv6 zone such as %12 left off)."""
    return ipaddress.ip_address(sock.getpeername()[0].split("%", 1)[0])


def _left(deadline) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise ClipError(SLOW)
    return left


def _shut(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


class _Watchdog:
    """Ends a fetch when its time is up, whatever it is waiting for. Every read has a timeout, but a site that sends
    its TLS handshake or its headers a byte at a time could stretch the whole past the limit; when time is up the
    watchdog shuts the connection down, which wakes the read, and the fetch says the site took too long. It watches a
    duplicate of the socket, so this works under TLS too (the TLS socket takes the original over)."""

    def __init__(self, seconds):
        self.fired = False
        self._sock = None
        self._lock = threading.Lock()
        self._timer = threading.Timer(max(0.0, seconds), self._fire)
        self._timer.daemon = True
        self._timer.start()

    def watch(self, sock):
        dup = sock.dup()
        with self._lock:
            old, self._sock, fired = self._sock, dup, self.fired
        if old is not None:
            old.close()
        if fired:
            _shut(dup)

    def _fire(self):
        with self._lock:
            self.fired, sock = True, self._sock
        if sock is not None:
            _shut(sock)

    def stop(self):
        self._timer.cancel()
        with self._lock:
            sock, self._sock = self._sock, None
        if sock is not None:
            sock.close()


@contextmanager
def _network(host, dog):
    """Network failures as the board says them: past the time limit, the site was too slow; a host name that can't be
    one, the address isn't valid; anything else, the site couldn't be reached."""
    try:
        yield
    except ClipError:
        raise
    except (OSError, http.client.HTTPException, ValueError) as e:
        if dog.fired or isinstance(e, TimeoutError):
            raise ClipError(SLOW) from None
        if isinstance(e, UnicodeError):         # a name like a..b: the IDNA codec refuses its empty label
            raise ClipError(INVALID) from None
        raise ClipError(f"Studio couldn't reach {host}.") from None


def _open(s, allow, deadline, dog):
    """(connection, response, socket) of one GET of the address in `s`. The socket's peer is checked with `allow`
    before anything is sent (TLS included); the request carries HEADERS and nothing else. The socket is returned too:
    http.client hands it to the response and forgets it."""
    https = s.scheme.lower() == "https"
    name = _ascii(s.hostname)
    sock = socket.create_connection((name, s.port or (443 if https else 80)), timeout=_left(deadline))
    try:
        dog.watch(sock)
        if not allow(_peer(sock)):
            raise ClipError(LOCAL)
        if https:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=name)
        conn = http.client.HTTPConnection(name, s.port, timeout=_left(deadline))
        conn.sock = sock
        target = (s.path or "/") + (f"?{s.query}" if s.query else "")
        conn.putrequest("GET", re.sub(r"[^\x21-\x7e]", lambda m: quote(m[0], safe=""), target),
                        skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", (f"[{name}]" if ":" in name else name) + (f":{s.port}" if s.port else ""))
        for k, v in HEADERS:
            conn.putheader(k, v)
        conn.endheaders()
        return conn, conn.getresponse(), sock
    except BaseException:
        sock.close()
        raise


def _size(n) -> str:
    return f"{n / 1_000_000:g} MB" if n >= 1_000_000 else f"{n / 1000:g} KB"


def _inflate(data: bytes, wbits, limit) -> bytes:
    d = zlib.decompressobj(wbits)
    out = d.decompress(data, limit + 1)
    if len(out) <= limit:
        out += d.flush()
    if len(out) > limit:
        raise ClipError(f"The page is larger than {_size(limit)}.")
    return out


def _decoded(data: bytes, encoding, limit) -> bytes:
    """The body unpacked (gzip, deflate with or without its zlib wrapper), never past `limit`."""
    enc = (encoding or "").strip().lower()
    try:
        if enc in ("", "identity"):
            return data
        if enc in ("gzip", "x-gzip"):
            return _inflate(data, 16 + zlib.MAX_WBITS, limit)
        if enc == "deflate":
            try:
                return _inflate(data, zlib.MAX_WBITS, limit)
            except zlib.error:
                return _inflate(data, -zlib.MAX_WBITS, limit)
    except zlib.error:
        pass
    raise ClipError(UNREADABLE)


def _body(resp, sock, limit, deadline, dog) -> bytes:
    said = resp.getheader("Content-Length", "").strip()
    if said.isdigit() and int(said) > limit:
        raise ClipError(f"The page is larger than {_size(limit)}.")
    chunks, n = [], 0
    while not resp.isclosed():          # the response closes the socket once it has its whole body
        sock.settimeout(_left(deadline))
        chunk = resp.read1(65536)
        if not chunk:
            break
        n += len(chunk)
        if n > limit:
            raise ClipError(f"The page is larger than {_size(limit)}.")
        chunks.append(chunk)
    if dog.fired:                       # the body ended because time was up, not because it was whole
        raise ClipError(SLOW)
    return _decoded(b"".join(chunks), resp.getheader("Content-Encoding"), limit)


def _sniff(data: bytes):
    """The type the bytes show, for an answer that didn't say (or said only "octet-stream")."""
    head = data[:512]
    for sig, ctype in ((b"%PDF-", PDF), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
                       (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif")):
        if head.startswith(sig):
            return ctype
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.lstrip(b"\xef\xbb\xbf \t\r\n").lower().startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "text/html"
    return None


def _answered(resp) -> ClipError:
    if resp.status in (401, 403):
        return ClipError(f"The site refused the request ({resp.status}).")
    phrase = http.client.responses.get(resp.status) or " ".join(str(resp.reason or "").split()) or "no reason given"
    return ClipError(f"The site answered {resp.status} ({phrase}).")


def fetch(url, *, allow=public_only, timeout=20, limit=10_000_000, max_redirects=5) -> Fetched:
    """One page, the way the spec allows: the address checked (http or https, a host, no user), every hop's connected
    address checked with `allow` before a byte is sent, HEADERS only, at most `max_redirects` redirects, `timeout`
    seconds in all (a watchdog holds it to that) and `limit` bytes (unpacked too). Errors are ClipError in the board's
    words."""
    deadline = time.monotonic() + timeout
    dog = _Watchdog(timeout)
    try:
        return _fetch(url, allow, limit, max_redirects, deadline, dog)
    finally:
        dog.stop()


def _fetch(url, allow, limit, max_redirects, deadline, dog) -> Fetched:
    current = url
    for hop in range(max_redirects + 1):
        s = _checked(current)
        with _network(s.hostname, dog):
            conn, resp, sock = _open(s, allow, deadline, dog)
            try:
                location = resp.getheader("Location")
                if resp.status in REDIRECTS and location:
                    if hop == max_redirects:
                        raise ClipError(f"Studio stopped after {max_redirects} redirects.")
                    try:                # a Location sent as UTF-8 reads as Latin-1 in http.client
                        location = location.encode("latin-1").decode("utf-8")
                    except UnicodeError:
                        pass
                    current = urljoin(current, location.strip())
                    continue
                if not 200 <= resp.status < 300:
                    raise _answered(resp)
                data = _body(resp, sock, limit, deadline, dog)
            finally:
                resp.close()
                conn.close()
                sock.close()
        said = resp.getheader("Content-Type")
        ctype = resp.headers.get_content_type() if said else ""
        if ctype in ("", "application/octet-stream", "binary/octet-stream", "application/unknown"):
            ctype = _sniff(data) or ctype or "application/octet-stream"
        return Fetched(url, current, resp.status, ctype, resp.headers.get_content_charset() if said else None, data)
    raise ClipError(f"Studio stopped after {max_redirects} redirects.")


# ——— reading the bytes as text ———
def _codec(name):
    """A Python codec for a page's charset label; Latin-1 and ASCII read as Windows-1252, as browsers read them."""
    if not name:
        return None
    try:
        enc = codecs.lookup(str(name).strip().strip("\"'")).name
    except (LookupError, ValueError):
        return None
    if enc in ("latin-1", "iso8859-1", "ascii"):
        return "cp1252"
    if "escape" in enc or enc in ("undefined", "punycode", "idna", "rot-13", "utf-7", "unicode-internal"):
        return None
    return enc


def decode_html(data: bytes, charset) -> str:
    """The page's text: by its byte order mark, else the header's charset, else a <meta charset> (or http-equiv) in
    the first 4096 bytes, else UTF-8; bytes that don't decode become U+FFFD."""
    for bom, enc in ((codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")):
        if data.startswith(bom):
            return data[len(bom):].decode(enc, "replace")
    meta = re.search(r"<meta[^>]*?charset\s*=\s*[\"']?\s*([-\w.:]+)", data[:4096].decode("latin-1"), re.I)
    for name in (charset, meta[1] if meta else None):
        enc = _codec(name)
        if enc:
            try:
                return data.decode(enc, "replace")
            except (LookupError, UnicodeError, TypeError):
                continue
    return data.decode("utf-8", "replace")


# ——— the copy Chrome photographs ———
POLICY = ("default-src https: http: data:; style-src https: http: data: 'unsafe-inline'; script-src 'none'; "
          "object-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; form-action 'none'; "
          "connect-src 'none'; manifest-src 'none'")
_GONE = frozenset("script iframe frameset object applet portal fencedframe noembed noframes".split())   # with content
_GONE_VOID = frozenset("embed base frame param keygen".split())
_GONE_ATTRS = frozenset("referrerpolicy ping srcdoc action formaction autoplay http-equiv attributionsrc".split())
_NAME = re.compile(r"[a-z_:][-a-z0-9_:.]*\Z")
_AS_PRE = {"xmp": "pre", "plaintext": "pre"}        # raw-text elements written as <pre> with their text escaped
_ESCAPABLE = ("title", "textarea")                  # browsers read their content as text, whatever it holds
_RAW_TEXT = frozenset(getattr(HTMLParser, "CDATA_CONTENT_ELEMENTS", ()))   # what this Python's parser reads raw …
_RCDATA = frozenset(getattr(HTMLParser, "RCDATA_CONTENT_ELEMENTS", ()))    # … and as text (3.13 and later)


def _active(value: str) -> bool:
    """An attribute value that could run or load something the policy should never see: a javascript: or vbscript:
    URL anywhere in it, or a file: URL (the copy is opened from a file)."""
    v = re.sub(r"[\x00-\x20]", "", value).lower()
    return "javascript:" in v or "vbscript:" in v or v.startswith("file:")


class _SafeCopy(HTMLParser):
    """Re-writes a page tag by tag, leaving out everything active (see safe_page)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.doctype, self.html_attrs, self.skip = [], "", None, None

    def _attrs(self, attrs) -> list:
        out, seen = [], set()
        for k, v in attrs:
            if k in seen or not _NAME.match(k) or k.startswith("on") or k in _GONE_ATTRS or (v is not None and _active(v)):
                continue
            seen.add(k)
            out.append((k, v))
        return out

    @staticmethod
    def _write(tag, attrs, closed) -> str:
        parts = [tag] + [k if v is None else f'{k}="{escape(v)}"' for k, v in attrs]
        return "<" + " ".join(parts) + ("/>" if closed else ">")

    def _tag(self, tag, attrs, closed):
        if self.skip:                   # inside something left out with its content
            if tag == self.skip[0] and not closed:
                self.skip[1] += 1
            return
        a = {}
        for k, v in attrs:              # a repeated attribute counts as its first, as in browsers (and in _attrs)
            a.setdefault(k, v or "")
        if not _NAME.match(tag) or tag in _GONE_VOID or tag in ("noscript", "head"):
            return                      # noscript is unwrapped: its content shows, as without scripts it would
        if tag in _GONE:
            self.skip = None if closed else [tag, 1]
            return
        if tag == "meta" and ("http-equiv" in a or "charset" in a or a.get("name", "").strip().lower() == "referrer"):
            return
        if tag == "link" and a.get("rel", "").strip().lower().split() != ["stylesheet"]:
            return                      # prefetch, preload, preconnect, icons, manifests …
        if tag == "html":
            if self.html_attrs is None:
                self.html_attrs = self._attrs(attrs)
            return
        self.out.append(self._write(_AS_PRE.get(tag, tag), self._attrs(attrs), closed))
        if not closed and ((tag == "xmp" and tag not in _RAW_TEXT) or (tag in _ESCAPABLE and tag not in _RCDATA)):
            self.set_cdata_mode(tag)    # an older parser reads these as markup; browsers read their content as text

    def handle_starttag(self, tag, attrs):
        self._tag(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._tag(tag, attrs, True)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] -= 1
                if self.skip[1] == 0:
                    self.skip = None
            return
        if _NAME.match(tag) and tag not in _GONE and tag not in _GONE_VOID and tag not in ("noscript", "html", "head"):
            self.out.append(f"</{_AS_PRE.get(tag, tag)}>")

    def handle_data(self, data):
        """Text never comes out with a literal "<", so no element can be made of it: inside <svg> or <math> Chrome reads
        a <style>'s content as markup, and an older parser reads <title> and <textarea> as markup."""
        if self.skip:
            return
        elem = self.cdata_elem
        if elem == "style":             # CSS as written, "<" as the CSS escape \3c (it only occurs inside CSS strings);
            data = data.replace("<!--", "").replace("-->", "")      # old comment markers around CSS, which ignores them
            self.out.append(data.replace("<", "\\3c "))
        elif elem in _ESCAPABLE and elem not in _RCDATA:
            self.out.append(escape(unescape(data), quote=False))       # read raw: its character references undone first
        else:                           # text, and xmp's raw content (written as <pre>)
            self.out.append(escape(data, quote=False))

    def handle_decl(self, decl):
        if not self.doctype and decl.lower().startswith("doctype") and "<" not in decl and ">" not in decl:
            self.doctype = f"<!{decl}>"


def safe_page(html: str, url: str) -> str:
    """Studio's copy of a page for its picture: every <script>, inline event handler, javascript: URL, <base>,
    <meta http-equiv> (refresh among them), <iframe>, <object>, <embed>, prefetch hint and referrer setting removed;
    its <head> starts with a Content-Security-Policy that forbids scripts, frames, objects and form posts, then
    no-referrer, then a <base> with the page's own address (so its styles, images and fonts load from the site)."""
    p = _SafeCopy()
    try:
        p.feed(html or "")
        p.close()
    except (AssertionError, ValueError):      # a declaration the parser can't read: the copy ends before it
        pass
    base = f'<base href="{escape(url)}">' if re.match(r"(?i)https?://", url or "") else ""
    head = f'<meta http-equiv="Content-Security-Policy" content="{POLICY}"><meta name="referrer" content="no-referrer">'
    return p.doctype + _SafeCopy._write("html", p.html_attrs or [], False) + "<head>" + head + base + "".join(p.out)


# ——— the Gate: Chrome's own requests go through the same rules ———
_HOP = frozenset("connection keep-alive proxy-connection proxy-authorization proxy-authenticate te trailer trailers "
                 "transfer-encoding upgrade".split())
_HELD_BACK = frozenset("cookie referer accept-language user-agent host x-client-data".split())


class _GateServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False     # nobody else may bind this port while it is open


class _GateHandler(BaseHTTPRequestHandler):
    """One request to the Gate. Plain http comes as an absolute-URI GET or HEAD and is forwarded with the author's
    traces dropped; https comes as CONNECT host:port and is tunnelled (its bytes are encrypted, so only the address is
    checked). Everything else, and every refused address, is a 403."""
    rbufsize = 0                    # read the request unbuffered: a tunnel's first bytes stay on the socket for the pipe

    def setup(self):
        super().setup()
        self.gate = self.server.gate
        self.connection.settimeout(self.gate.timeout)
        self.gate._track(self.connection)

    def finish(self):
        try:
            super().finish()
        finally:
            self.gate._untrack(self.connection)

    def __getattr__(self, name):    # any other method (POST, PUT, OPTIONS …) is refused
        if name.startswith("do_"):
            return self._deny
        raise AttributeError(name)

    def log_message(self, *args):
        pass

    def _deny(self):
        self.close_connection = True
        try:
            self.connection.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except OSError:
            pass

    def do_GET(self):
        self.close_connection = True
        gate = self.gate
        try:
            s = urlsplit(self.path)
            port = s.port or 80
        except ValueError:
            return self._deny()
        if gate.spent or s.scheme.lower() != "http" or not s.hostname or s.username is not None or s.password is not None:
            return self._deny()
        upstream = gate._connect(s.hostname, port)
        if upstream is None:
            return self._deny()
        try:
            self._relay(upstream, s)
        except (OSError, http.client.HTTPException):
            pass
        finally:
            gate._untrack(upstream)
            upstream.close()

    do_HEAD = do_GET

    def _relay(self, upstream, s):
        """The request as Chrome sent it, without cookies, referrer, languages or proxy headers and with Studio's
        User-Agent; the answer back with its own framing undone (the connection closes after it)."""
        target = (s.path or "/") + (f"?{s.query}" if s.query else "")
        lines = [f"{self.command} {target} HTTP/1.1", f"Host: {s.netloc}"]
        lines += [f"{k}: {v}" for k, v in self.headers.items()
                  if not (k.lower() in _HOP or k.lower() in _HELD_BACK or k.lower().startswith(("proxy-", "sec-ch-")))]
        lines += [f"User-Agent: {UA}", "Connection: close"]
        upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1", "replace"))
        resp = http.client.HTTPResponse(upstream, method=self.command)
        resp.begin()
        head = [f"HTTP/1.1 {resp.status} {resp.reason}"]
        head += [f"{k}: {v}" for k, v in resp.getheaders() if k.lower() not in _HOP] + ["Connection: close"]
        if not self.gate._send(self.connection, ("\r\n".join(head) + "\r\n\r\n").encode("latin-1", "replace")):
            return
        while True:
            chunk = resp.read1(65536)
            if not chunk or not self.gate._send(self.connection, chunk):
                return

    def do_CONNECT(self):
        self.close_connection = True
        gate = self.gate
        host, _, port = self.path.rpartition(":")
        host = host.strip("[]")
        if gate.spent or not host or not port.isdigit():
            return self._deny()
        upstream = gate._connect(host, int(port))
        if upstream is None:
            return self._deny()
        try:
            if gate._send(self.connection, b"HTTP/1.1 200 Connection established\r\n\r\n"):
                gate._pipe(self.connection, upstream)
        finally:
            gate._untrack(upstream)
            upstream.close()


class Gate:
    """The filtering proxy a picture's Chrome uses (`--proxy-server`), alive while it is open:

        with Gate() as gate:  … --proxy-server=http://127.0.0.1:{gate.port} …

    It resolves each host itself, connects, and checks the connected address with `allow` before passing a byte: for
    plain http (where it also drops Cookie, Referer, Accept-Language and proxy headers and sets the User-Agent) and for
    https tunnels (CONNECT, where only the address can be checked). At most `limit` bytes pass in all, and each
    connection lives at most `timeout` seconds. `asked` lists every host asked for, `refused` those refused."""

    def __init__(self, allow=public_only, limit=20_000_000, timeout=30):
        self.allow, self.limit, self.timeout = allow, limit, timeout
        self.asked, self.refused = [], []
        self.used, self.port = 0, None
        self._lock = threading.Lock()
        self._open = set()
        self._server = self._thread = None

    def __enter__(self):
        self._server = _GateServer(("127.0.0.1", 0), _GateHandler)
        self._server.gate = self
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        with self._lock:
            still = list(self._open)
        for s in still:                 # a tunnel Chrome left open ends with the Gate
            try:
                s.close()
            except OSError:
                pass
        return False

    @property
    def spent(self) -> bool:
        return self.used >= self.limit

    def _track(self, sock):
        with self._lock:
            self._open.add(sock)

    def _untrack(self, sock):
        with self._lock:
            self._open.discard(sock)

    def _connect(self, host, port):
        """A connection to host:port when its connected address is allowed, else None (a refusal is recorded)."""
        self.asked.append(host)
        try:
            sock = socket.create_connection((host, port), timeout=self.timeout)
        except (OSError, UnicodeError, ValueError):
            return None
        try:
            ok = self.allow(_peer(sock))
        except (OSError, ValueError):
            ok = False
        if not ok:
            self.refused.append(host)
            sock.close()
            return None
        self._track(sock)
        return sock

    def _send(self, sock, data: bytes) -> bool:
        """Pass data on, within the limit: False when the limit cut it (or the other side is gone)."""
        with self._lock:
            n = max(0, min(len(data), self.limit - self.used))
            self.used += n
        try:
            if n:
                sock.sendall(data[:n])
        except OSError:
            return False
        return n == len(data)

    def _pipe(self, a, b):
        """Bytes both ways between a and b until either side closes, the limit is reached or `timeout` has passed."""
        deadline = time.monotonic() + self.timeout
        other = {a: b, b: a}
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return
            try:
                ready, _, _ = select.select([a, b], [], [], left)
                for src in ready:
                    data = src.recv(65536)
                    if not data or not self._send(other[src], data):
                        return
            except (OSError, ValueError):
                return
            if not ready:
                return


# ——— the picture ———
def picture(html: str, url: str, out: Path, *, allow=public_only) -> tuple:
    """(out, "") with `out` a JPEG (quality 85) of the page's safe copy in a 1280 × 1600 window at 1×, taken by headless
    Chrome in a throwaway profile whose every request goes through a Gate; (None, why) without Chrome or when it
    fails. The copy's folder and the Gate are always closed."""
    if not config.CHROME:
        return None, NO_CHROME
    folder = Path(tempfile.mkdtemp(prefix="studio-clip-"))
    try:
        copy = folder / "page.html"
        copy.write_text(safe_page(html, url), encoding="utf-8-sig")     # the BOM fixes the encoding, whatever it said
        png = folder / "page.png"
        with Gate(allow) as gate:
            flags = CHROME_FLAGS + (f"--proxy-server=http://127.0.0.1:{gate.port}", "--proxy-bypass-list=<-loopback>")
            shoot.screenshot(copy.as_uri(), *PICTURE, png, scale=1, flags=flags, timeout=60)
        from PIL import Image
        with Image.open(png) as im:
            rgb = im.convert("RGB")
        jpg = folder / "page.jpg"
        rgb.save(jpg, "JPEG", quality=85)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(jpg), str(out))
        return out, ""
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return None, NO_PICTURE
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ——— the clip as a source ———
PARTICLES = frozenset("van von de der den het ten ter te da di du des del della le la 't zu vom dos das".split())


def _person(name: str) -> dict:
    """A name as CSL: the last word is the family name, lower-case particles before it (van, de, von …) its
    non-dropping particle, the rest the given names; a single word is a literal name."""
    words = name.split()
    if len(words) == 1:
        return {"literal": name}
    given, family, particle = words[:-1], words[-1], []
    while len(given) > 1 and given[-1].lower() in PARTICLES:
        particle.insert(0, given.pop())
    out = {"family": family, "given": " ".join(given)}
    if particle:
        out["non-dropping-particle"] = " ".join(particle)
    return out


def _organisation(words) -> bool:
    """A byline that names an organisation, not people: more than four words, or a lower-case word that isn't a name
    particle ("Contributors to Wikimedia projects", "staff writers")."""
    return len(words) > 4 or any(w[:1].islower() and w.lower() not in PARTICLES for w in words)


def _people(names) -> list[dict]:
    """A byline as CSL names: "An Example", "A One, B Two, C Three", "A One and B Two" (or &, ;, Dutch "en"), or
    "Family, Given". Each name is judged on its own: one that reads as an organisation is a literal name."""
    names = " ".join(str(names or "").split())
    if not names:
        return []
    m = re.fullmatch(r"([^,\s]+),\s*([^,]+)", names)
    if m and len(m[2].split()) <= 2 and not _organisation(m[2].split()):
        return [{"family": m[1], "given": m[2]}]
    parts = [n for n in re.split(r"\s*(?:;|,|&|\band\b|\ben\b)\s*", names) if n.strip()]
    return [{"literal": n} if _organisation(n.split()) else _person(n) for n in parts]


def _date_parts(value) -> list[int] | None:
    m = re.match(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", str(value or "").strip())
    return [int(x) for x in m.groups() if x] if m else None


def webpage_csl(details: dict, url: str, fetched_iso: str, taken) -> dict:
    """A clip's CSL item (type webpage): its title, author, `issued` from the date published, the site as
    container-title, the URL and `accessed` from the fetch date; keyed like the board's sources (family name and year,
    else the title's first word that isn't an article) and made unique among `taken`."""
    csl = {"type": "webpage"}
    if details.get("title"):
        csl["title"] = details["title"]
    people = _people(details.get("author"))
    if people:
        csl["author"] = people
    issued = _date_parts(details.get("published"))
    if issued:
        csl["issued"] = {"date-parts": [issued]}
    if details.get("site"):
        csl["container-title"] = details["site"]
    csl["URL"] = url
    accessed = _date_parts(str(fetched_iso or "")[:10])
    if accessed:
        csl["accessed"] = {"date-parts": [accessed]}
    csl["id"] = source_key(csl, set(taken))
    return csl
