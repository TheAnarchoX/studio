"""Pixel and metrics regression over every design in a library, for changes to the renderer or the fonts.

    python tools/design_regression.py export --library <dir> --out <dir> [--port 4750]
    python tools/design_regression.py compare <a> <b>

export starts `studio web` from this checkout on the given port against <dir> (the folder that holds Poems/),
with a fresh settings file and a fresh cache (so metrics are measured by the code under test, not read back),
exports every design of every poem through POST /api/design/export, copies the PNGs to --out/<poem id>/, and
writes --out/metrics.json: /api/metrics for every metrics key the designs' text layers use, in every format.
The keys are made by this checkout's own design-core.js (Design.mkey, run with node), exactly as the editor
makes them; without node the images are still exported and metrics.json is left out.

Export writes renders into the library it is given: point it at a scratch copy, never at the real one.

compare reports, per image, identical or the bounding box and number of the pixels that differ, and whether
metrics.json is identical. It exits 1 when anything differs.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

REPO = Path(__file__).resolve().parent.parent
CORE = REPO / "studio" / "static" / "design-core.js"
NODE_DRIVER = r"""
const fs = require("fs"), vm = require("vm");
const [core, input] = process.argv.slice(2);
const ctx = vm.createContext({console});
const Design = vm.runInContext(fs.readFileSync(core, "utf8") + "\n;Design", ctx);
const data = JSON.parse(fs.readFileSync(input, "utf8"));
if (data.fonts && typeof Design.setFonts === "function") Design.setFonts(data.fonts);
const keys = new Set();
for (const d of data.designs) for (const raw of d.elements || []) if (raw.type === "text")
  for (const f of [null, ...Object.keys(raw.at || {})]) keys.add(Design.mkey(f ? Design.resolve(raw, f) : raw));
process.stdout.write(JSON.stringify([...keys].sort()));
"""


def _request(url, body=None, timeout=300):
    data = None if body is None else json.dumps(body).encode("utf-8")
    origin = url.split("/", 3)[:3]
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json", "Origin": "/".join(origin)} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if "json" in (r.headers.get("Content-Type") or "") else raw


def _answers(base):
    try:
        _request(base + "/api/about", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


def export(library: Path, out: Path, port: int):
    library = library.resolve()
    if not (library / "Poems").is_dir():
        raise SystemExit(f"no Poems folder in {library}")
    base = f"http://127.0.0.1:{port}"
    if _answers(base):
        raise SystemExit(f"something already answers on port {port}; choose another --port")
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="studio-regress-"))
    (tmp / "config.json").write_text(json.dumps({"update_check": False}), encoding="utf-8")
    env = dict(os.environ, STUDIO_ART=str(library), STUDIO_PORT=str(port), STUDIO_CONFIG=str(tmp / "config.json"),
               STUDIO_CACHE=str(tmp / "cache"))
    log = open(tmp / "server.log", "wb")
    server = subprocess.Popen([sys.executable, "-m", "studio", "web"], cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(150):
            if server.poll() is not None:
                raise SystemExit(f"studio web stopped; see {tmp / 'server.log'}")
            if _answers(base):
                break
            time.sleep(0.2)
        else:
            raise SystemExit("studio web did not answer in 30 s")
        about = _request(base + "/api/about")
        if Path(about["library"]).resolve() != library:
            raise SystemExit(f"the server on port {port} uses {about['library']}, not {library}")
        jobs = []
        for poem in _request(base + "/api/home")["poems"]:
            pid = poem["id"]
            for d in _request(base + "/api/poem?id=" + quote(pid))["designs"]:
                jobs.append((pid, d["slug"], _request(f"{base}/api/design?id={quote(pid)}&d={quote(d['slug'])}")))
        designs = [j[2] for j in jobs]
        # metrics first: metrics.json, and a warm cache so the exports don't wait on measuring
        try:
            fonts = _request(base + "/api/fonts")
        except urllib.error.HTTPError:
            fonts = None
        keys = _keys(designs, fonts, tmp)
        if keys is None:
            print("node not found: metrics.json left out", file=sys.stderr)
        else:
            metrics = {}
            for i in range(0, len(keys), 4):
                metrics.update(_request(base + "/api/metrics", {"keys": keys[i:i + 4]}, timeout=900))
                print(f"metrics: {min(i + 4, len(keys))}/{len(keys)}", flush=True)
            missing = [k for k in keys if k not in metrics]
            (out / "metrics.json").write_text(json.dumps({"keys": keys, "missing": missing, "metrics": dict(sorted(metrics.items()))},
                                                         indent=1, sort_keys=True), encoding="utf-8")
            print(f"metrics: {len(keys)} keys, {len(missing)} missing", flush=True)
        count, failed = 0, []
        for pid, slug, _ in jobs:
            try:
                res = _request(base + "/api/design/export", {"id": pid, "slug": slug}, timeout=900)
            except urllib.error.HTTPError as e:
                failed.append(f"{pid} / {slug}: {e.read().decode('utf-8', 'replace')}")
                print("FAILED " + failed[-1], flush=True)
                continue
            dest = out / Path(*pid.split("/"))
            dest.mkdir(parents=True, exist_ok=True)
            for p in res["paths"]:
                shutil.copy2(p, dest / Path(p).name)
                count += 1
            print(f"exported {pid} / {slug}: {len(res['paths'])} images", flush=True)
        if failed:
            raise SystemExit(f"{len(failed)} designs failed to export:\n" + "\n".join(failed))
        print(f"{count} images from {len(designs)} designs in {out}")
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


def _keys(designs, fonts, tmp: Path):
    node = shutil.which("node")
    if not node:
        return None
    (tmp / "driver.js").write_text(NODE_DRIVER, encoding="utf-8")
    (tmp / "input.json").write_text(json.dumps({"designs": designs, "fonts": fonts}), encoding="utf-8")
    run = subprocess.run([node, str(tmp / "driver.js"), str(CORE), str(tmp / "input.json")], capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


def compare(a: Path, b: Path) -> int:
    import numpy as np
    from PIL import Image
    names = sorted({p.relative_to(a).as_posix() for p in a.rglob("*.png")} | {p.relative_to(b).as_posix() for p in b.rglob("*.png")})
    bad = 0
    for n in names:
        pa, pb = a / n, b / n
        if not pa.exists() or not pb.exists():
            print(f"{n}: only in {a if pa.exists() else b}")
            bad += 1
            continue
        x = np.asarray(Image.open(pa).convert("RGBA"))
        y = np.asarray(Image.open(pb).convert("RGBA"))
        if x.shape != y.shape:
            print(f"{n}: size {x.shape[1]}x{x.shape[0]} vs {y.shape[1]}x{y.shape[0]}")
            bad += 1
            continue
        diff = (x != y).any(axis=2)
        count = int(diff.sum())
        if not count:
            print(f"{n}: identical")
            continue
        ys, xs = np.nonzero(diff)
        print(f"{n}: {count} pixels differ in x {xs.min()}-{xs.max()}, y {ys.min()}-{ys.max()}")
        bad += 1
    ma, mb = a / "metrics.json", b / "metrics.json"
    if not ma.exists() or not mb.exists():
        print("metrics.json: missing in " + " and ".join(str(p.parent) for p in (ma, mb) if not p.exists()))
        bad += 1
    else:
        ja, jb = json.loads(ma.read_text(encoding="utf-8")), json.loads(mb.read_text(encoding="utf-8"))
        if ja == jb:
            print(f"metrics.json: identical ({len(ja['keys'])} keys)")
        else:
            bad += 1
            ka, kb = set(ja["keys"]), set(jb["keys"])
            for k in sorted(ka - kb):
                print(f"metrics.json: key only in {a}: {k}")
            for k in sorted(kb - ka):
                print(f"metrics.json: key only in {b}: {k}")
            for k in sorted(ka & kb):
                if ja["metrics"].get(k) != jb["metrics"].get(k):
                    print(f"metrics.json: {k} differs")
            if ja.get("missing") != jb.get("missing"):
                print(f"metrics.json: unanswered keys differ: {ja.get('missing')} vs {jb.get('missing')}")
    print(f"{len(names)} images, {bad} differences" if bad else f"{len(names)} images: all identical")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--library", required=True, type=Path)
    ex.add_argument("--out", required=True, type=Path)
    ex.add_argument("--port", type=int, default=4750)
    cp = sub.add_parser("compare")
    cp.add_argument("a", type=Path)
    cp.add_argument("b", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "export":
        export(args.library, args.out, args.port)
        return 0
    return compare(args.a, args.b)


if __name__ == "__main__":
    sys.exit(main())
