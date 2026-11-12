"""A live Studio server on a temp library, for tests that go through HTTP."""
import contextlib
import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from studio import config
from studio.store import Store
from studio.web import Handler, StudioServer

_ENV = ("STUDIO_ART", "STUDIO_CONFIG", "STUDIO_CACHE")


@contextlib.contextmanager
def temp_studio():
    tmp = Path(tempfile.mkdtemp(prefix="studio-web-"))
    saved_env = {k: os.environ.get(k) for k in _ENV}
    saved_cfg, saved_store = config.CONFIG_FILE, Handler.store
    os.environ["STUDIO_ART"] = str(tmp / "lib")
    os.environ["STUDIO_CONFIG"] = str(tmp / "config.json")
    os.environ["STUDIO_CACHE"] = str(tmp / "cache")
    config.CONFIG_FILE = tmp / "config.json"
    config.refresh()
    (config.POEMS).mkdir(parents=True, exist_ok=True)
    Handler.store = Store()
    server = StudioServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    def call(req):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                code, data, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            code, data, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
        return code, (json.loads(data) if "json" in ctype else data)

    def get(path):
        return call(urllib.request.Request(url + path))

    def post(path, body=None):
        req = urllib.request.Request(url + path, data=json.dumps(body or {}).encode(), method="POST",
                                     headers={"Origin": url, "Content-Type": "application/json"})
        return call(req)

    try:
        yield SimpleNamespace(root=config.POEMS, url=url, get=get, post=post)
    finally:
        server.shutdown()
        server.server_close()
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.CONFIG_FILE = saved_cfg
        config.refresh()
        Handler.store = saved_store
