"""Writes studio/static/fonts/metrics-seed.json: the letter-edge metrics (studio.metrics) of the font instances a
fresh install uses first, so the looks, the starters and the examples draw at once instead of after seconds of
measuring per instance.

    python tools/seed_metrics.py [--jobs N] [--check]

The instances: every role (display, text, label) of every bundled look (studio/static/styles/looks) and of a
Studio 1.0 series (Newsreader for the text, Archivo for display and labels, at 1.0's weights), and what the
starters set themselves in a 1.0 series (the Page starter's Newsreader 500 poem and italic signature, the Wall's
Archivo 900 at every width its search can reach). Each at every optical size its family has, because the starters
and the look previews size text to fit. The Examples series follows a bundled look, so its text is covered too.

Measuring is studio.metrics.measure, the instancer the app itself uses, so the seed holds exactly what the app
would measure; metrics.instance() reads the seed for bundled font files before measuring. Run this after a
bundled font, a bundled look or the measuring changes, and commit the file. --check measures again and reports
whether the committed file is still exact (exit 1 when not).
"""
import argparse
import json
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOOKS = REPO / "studio" / "static" / "styles" / "looks"
OUT = REPO / "studio" / "static" / "fonts" / "metrics-seed.json"
LEGACY = {"display": {"family": "Archivo", "weight": 900}, "text": {"family": "Newsreader", "weight": 400},
          "label": {"family": "Archivo", "weight": 700}}
# what the starters set in a 1.0 series besides the roles: (family, italic, weight, widths)
STARTERS = [("Newsreader", False, 500, [100]), ("Newsreader", True, 400, [100]), ("Archivo", False, 700, [100]),
            ("Archivo", False, 900, [w / 2 for w in range(125, 251)])]      # the Wall: 62.5 to 125 in half steps


def _isolate():
    """A library and cache of nobody's: the registry then holds the bundled families only."""
    tmp = Path(tempfile.mkdtemp(prefix="studio-seed-"))
    (tmp / "lib").mkdir()
    os.environ.update(STUDIO_ART=str(tmp / "lib"), STUDIO_CACHE=str(tmp / "cache"), STUDIO_CONFIG=str(tmp / "config.json"))
    sys.path.insert(0, str(REPO))
    return tmp


def instances():
    """[(key, font file, face index)] for every instance the seed holds."""
    from studio import fonts, metrics
    reg = fonts.registry()
    wanted = {(f, i, w, tuple(ws)) for f, i, w, ws in STARTERS}
    for path in sorted(LOOKS.glob("*.json")):
        look = json.loads(path.read_text(encoding="utf-8"))
        for role in look.get("fonts", {}).values():
            wanted.add((role["family"], False, role.get("weight") or 400, (role.get("width") or 100,)))
    for role in LEGACY.values():
        wanted.add((role["family"], False, role["weight"], (100,)))
    out = {}
    for family, italic, weight, widths in sorted(wanted):
        fam = reg.get(family)
        if fam is None or fam.source != "bundled":
            raise SystemExit(f"{family} is not a bundled family")
        for width in widths:
            for size in metrics.OPSZ:
                k = metrics.key(family, italic, weight, width, size)
                if k not in out:
                    f = reg.file_for(family, italic, weight)
                    out[k] = (str(f.path), f.index)
    return [(k, p, i) for k, (p, i) in sorted(out.items())]


def _measure(job):
    k, path, index = job
    from studio import metrics
    return k, metrics.measure(k, Path(path), index)


def dump(seed):
    """One instance per line, so a change shows as a small diff."""
    return "{\n" + ",\n".join(json.dumps(k) + ":" + json.dumps(v, separators=(",", ":")) for k, v in sorted(seed.items())) + "\n}\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--check", action="store_true", help="measure again and compare with the committed file")
    args = ap.parse_args(argv)
    _isolate()
    jobs = instances()
    print(f"{len(jobs)} instances", flush=True)
    seed = {}
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for n, (k, m) in enumerate(pool.map(_measure, jobs, chunksize=2), 1):
            seed[k] = m
            if n % 20 == 0 or n == len(jobs):
                print(f"measured {n}/{len(jobs)}", flush=True)
    text = dump(seed)
    if args.check:
        same = OUT.exists() and json.loads(OUT.read_text(encoding="utf-8")) == json.loads(text)
        print("metrics-seed.json is exact" if same else "metrics-seed.json differs from a fresh measurement")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)} ({len(text) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
