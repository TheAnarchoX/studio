"""Render a design to PNG the way a series kit renders slides: headless Chrome, 2x, from a page.

The page is Studio's own render view (static/render.html), served by a running Studio web server,
so the export is the same browser typography as the editor shows."""
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import tempfile
from pathlib import Path
from urllib.parse import quote

from . import config, fonts
from .store import DESIGN_FORMATS, RENDERS, StoreError


def screenshot(url, w, h, out: Path, scale=2):
    if not config.CHROME:
        raise RuntimeError("no Chrome, Chromium or Edge found to render with; set one in Studio's settings")
    out.parent.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="studio-shot-"))
    tmp = out.with_name(f".{out.stem}.shot.png")
    try:
        subprocess.run([config.CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        "--no-default-browser-check", f"--user-data-dir={profile}", f"--force-device-scale-factor={scale}",
                        f"--window-size={w},{h}", "--virtual-time-budget=12000", "--run-all-compositor-stages-before-draw",
                        f"--screenshot={tmp}", url], check=True, capture_output=True, timeout=120,
                       creationflags=0x08000000 if sys.platform == "win32" else 0)
        tmp.replace(out)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
        tmp.unlink(missing_ok=True)
    return out


def check_fonts(design):
    """Stop before Chrome runs when the export would be set in the wrong type (the page can't report that itself)."""
    reg = fonts.registry()
    if not reg.families():
        raise StoreError("Studio couldn't load its fonts, so the export was stopped.")
    names = [e.get("font") for e in design.get("elements") or []     # no font set means Newsreader, as before
             if isinstance(e, dict) and e.get("type") == "text"]
    missing = reg.resolve_missing(names, 10)    # asks the computer's fonts too
    if missing:
        raise StoreError("This design uses fonts Studio doesn't have: " + ", ".join(missing) + ".")


def export_design(store, base_url, ref, slug, formats=None):
    """Write Design renders/<slug>/<slug>-<tag>.png (and -noname.png when the design has a name layer)."""
    folder = store.resolve(ref)
    d = store.read_design(folder, slug)
    check_fonts(d)
    allowed = store.design_formats(folder)       # the series decides which formats exist
    fmts = [f for f in (formats or ["45", "11", "916"]) if f in DESIGN_FORMATS and f in allowed]
    named = any(e.get("role") == "name" and not e.get("hidden") for e in d["elements"])
    jobs = []
    for fmt in fmts:
        w, h, tag = DESIGN_FORMATS[fmt]
        for signed in [True] + ([False] if named else []):
            url = f"{base_url}/static/render.html?id={quote(store.pid(folder))}&d={quote(slug)}&sig={int(signed)}&f={fmt}"
            jobs.append((url, w, h, folder / RENDERS / slug / f"{slug}-{tag}{'' if signed else '-noname'}.png"))
    with ThreadPoolExecutor(4) as ex:
        return list(ex.map(lambda j: screenshot(*j), jobs))
