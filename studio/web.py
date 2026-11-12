"""Studio's web app: a small JSON API over the store, the static front end, and the poem files.

Local only: binds 127.0.0.1, answers only to localhost Host headers, and accepts writes only as JSON
from its own origin. Files are served only from inside Poems/.
"""
import json
import mimetypes
import os
import socket
import subprocess
import sys
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import config, metrics, shoot
from .store import FONTS, PALETTES, STATUSES, Store, StoreError

STATIC = Path(__file__).parent / "static"
TYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".md": "text/markdown",
         ".webmanifest": "application/manifest+json", ".ico": "image/x-icon",
         ".json": "application/json", ".png": "image/png", ".ttf": "font/ttf", ".svg": "image/svg+xml"}


class Handler(BaseHTTPRequestHandler):
    store: Store = None
    server_version = "Studio/1"

    # ——— plumbing ———
    def log_message(self, fmt, *args):  # quiet; errors are printed where they happen
        pass

    def _allowed_host(self):
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _send(self, code, body, ctype="application/json; charset=utf-8", cache="no-cache"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path):
        ctype = TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith(("text/", "application/json")):
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    def _guard(self, fn):
        if not self._allowed_host():
            return self._send(403, {"error": "Studio only answers on localhost"})
        try:
            fn()
        except StoreError as e:
            self._send(400, {"error": str(e)})
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:  # noqa: BLE001
            if sys.stderr:
                traceback.print_exc(file=sys.stderr)
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    # ——— GET ———
    def do_GET(self):
        self._guard(self._get)

    def _get(self):
        url = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        path = unquote(url.path)
        s = self.store
        if path in ("/", "/index.html"):
            return self._file(STATIC / "index.html")
        if path == "/favicon.ico":
            return self._file(STATIC / "icons" / "studio.ico")
        if path == "/api/settings":
            return self._send(200, settings_info())
        if path == "/api/about":
            return self._send(200, about_info(self.server.server_address[1]))
        if path.startswith("/static/"):
            p = (STATIC / path[len("/static/"):]).resolve()
            if STATIC.resolve() not in p.parents or not p.is_file():
                return self._send(404, {"error": "not found"})
            return self._file(p)
        if path.startswith("/files/"):
            return self._file(s.file(path[len("/files/"):]))
        if path in ("/api/home", "/api/poems"):
            poems = s.list()
            return self._send(200, {"series": s.series_list(poems), "statuses": STATUSES, "poems": poems, "signature": config.SIGNATURE,
                                    "stamp": s.stamp(), "root": str(s.root), "palettes": PALETTES, "fonts": FONTS})
        if path == "/api/series":
            return self._send(200, s.series_read(q.get("name", "")))
        if path == "/api/design":
            return self._send(200, s.read_design(q.get("id", ""), q.get("d", "")))
        if path == "/api/stamps":
            return self._send(200, s.stamps(q.get("series", "")))
        if path == "/api/poem":
            return self._send(200, s.read(q.get("id", "")))
        if path == "/api/stamp":
            if q.get("id"):
                return self._send(200, {"stamp": s.stamp(s.resolve(q["id"]))})
            if q.get("series"):
                return self._send(200, {"stamp": s.stamp_series(s.series_dir(q["series"]))})
            return self._send(200, {"stamp": s.stamp()})
        self._send(404, {"error": "not found"})

    # ——— POST ———
    def do_POST(self):
        self._guard(self._post)

    def _post(self):
        port = self.server.server_address[1]
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            return self._send(403, {"error": "wrong origin"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._send(415, {"error": "send JSON"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 40_000_000:
            return self._send(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, {"error": "bad JSON"})
        s, path = self.store, urlparse(self.path).path
        if path == "/api/poems":
            return self._send(200, s.create(body.get("title"), body.get("series")))
        if path == "/api/text":
            return self._send(200, s.save_text(body.get("id"), body.get("title"), body.get("text", "")))
        if path == "/api/stamps":
            slug = s.save_stamp(body.get("series"), body.get("name"), body.get("elements"), body.get("w"), body.get("h"))
            return self._send(200, {"slug": slug})
        if path == "/api/stamps/delete":
            s.delete_stamp(body.get("series"), body.get("slug"))
            return self._send(200, {"ok": True})
        if path == "/api/settings":
            fields = {k: v for k, v in body.items() if k in config.DEFAULTS}
            try:
                config.save(fields)
            except ValueError as e:
                raise StoreError(str(e)) from None
            if body.get("create") and not config.POEMS.exists():
                config.POEMS.mkdir(parents=True)
            Handler.store = Store()
            return self._send(200, settings_info())
        if path == "/api/reveal":   # show a file in the system's file manager
            target = s.file(body.get("rel", ""))
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(target)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target.parent)])
            return self._send(200, {"ok": True})
        if path == "/api/poem/delete":
            dest = s.delete_poem(body.get("id"))
            return self._send(200, {"trash": str(dest)})
        if path == "/api/notes":
            return self._send(200, s.save_notes(body.get("id"), body.get("text", "")))
        if path == "/api/status":
            return self._send(200, s.set_status(body.get("id"), body.get("status")))
        if path == "/api/series":
            return self._send(200, s.create_series(body.get("name"), body.get("tagline", ""),
                                                   body.get("palette"), body.get("description", "")))
        if path == "/api/series/update":
            return self._send(200, s.update_series(body.get("name"), body.get("fields") or {}))
        if path == "/api/design":
            slug = s.save_design(body.get("id"), body.get("design"), body.get("slug"))
            return self._send(200, {"slug": slug, "designs": s.designs(s.resolve(body.get("id")))})
        if path == "/api/design/delete":
            s.delete_design(body.get("id"), body.get("slug"))
            return self._send(200, {"designs": s.designs(s.resolve(body.get("id")))})
        if path == "/api/design/export":
            outs = shoot.export_design(s, f"http://127.0.0.1:{port}", body.get("id"), body.get("slug"))
            return self._send(200, {"paths": [str(o) for o in outs], "rels": [s.rel(o) for o in outs],
                                    "designs": s.designs(s.resolve(body.get("id")))})
        if path == "/api/metrics":
            return self._send(200, metrics.many([str(k) for k in body.get("keys") or []]))
        self._send(404, {"error": "not found"})


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # on Windows, reuse would let a second Studio bind the same port
    # An export starts four headless Chromes at once; with the default queue of 5, Windows refuses some of their
    # connections and a font or the metrics fail to load, so the image comes out in a fallback font.
    request_queue_size = 64

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def settings_info():
    lib = config.ART
    poems = config.POEMS
    series = [d for d in Store().series_dirs()] if poems.exists() else []
    return {"settings": config.load(), "config_file": str(config.CONFIG_FILE), "library": str(lib),
            "library_exists": lib.exists(), "poems_exists": poems.exists(), "series": len(series),
            "env_library": bool(os.environ.get("STUDIO_ART")), "chrome_found": config.CHROME}


def cli_command():
    """How to start Studio's command line on this machine (for Claude's MCP settings)."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        cli = exe.with_name("studio-cli.exe" if sys.platform == "win32" else "studio-cli")
        return [str(cli if cli.exists() else exe)]
    scripts = Path(sys.executable).parent
    for name in ("studio.exe", "studio"):
        if (scripts / name).exists():
            return [str(scripts / name)]
    return [sys.executable, "-m", "studio"]


def about_info(port):
    from . import __version__
    cmd = cli_command()
    server = {"command": cmd[0], "args": cmd[1:] + ["mcp"]}
    desktop = {"win32": r"%APPDATA%\Claude\claude_desktop_config.json", "darwin": "~/Library/Application Support/Claude/claude_desktop_config.json"}
    quote = (lambda a: f'"{a}"' if " " in a else a)
    return {"version": __version__, "python": sys.version.split()[0], "platform": sys.platform, "url": f"http://{config.HOST}:{port}",
            "config_file": str(config.CONFIG_FILE), "library": str(config.ART), "cache": str(config.CACHE), "chrome": config.CHROME,
            "mcp": {"server": server,
                    "claude_code": "claude mcp add studio --scope user -- " + " ".join(quote(a) for a in server["args"][:0] + [server["command"]] + server["args"]),
                    "mcp_json": json.dumps({"mcpServers": {"studio": server}}, indent=2),
                    "desktop_file": desktop.get(sys.platform, "~/.config/Claude/claude_desktop_config.json")}}


def serve(open_browser=False, host=None, port=None, store=None, quiet=False):
    host, port = host or config.HOST, port or config.PORT
    Handler.store = store or Store()
    url = f"http://{host}:{port}/"
    try:
        httpd = StudioServer((host, port), Handler)
    except OSError:
        print(f"Studio already seems to be running at {url}", file=sys.stderr)
        if open_browser:
            webbrowser.open(url)
        return
    if not quiet:
        print(f"Studio: {url}  (poems in {Handler.store.root})  Ctrl+C to stop", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
