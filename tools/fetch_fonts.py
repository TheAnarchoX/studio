"""Download the bundled open-licence font families into studio/static/fonts and write families.json.

    python tools/fetch_fonts.py            download missing files, verify, write families.json
    python tools/fetch_fonts.py --check    verify what is on disk (no network)

Sources are the google/fonts repository; every family is under the SIL Open Font License 1.1.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FONTS = Path(__file__).resolve().parent.parent / "studio" / "static" / "fonts"
BUDGET = 14 * 1024 * 1024


def _plex(prefix: str) -> list[tuple[str, bool]]:
    return [(f"{prefix}-{s}.ttf", "Italic" in s) for s in ("Regular", "Italic", "Bold", "BoldItalic")]


# (family, category, source dir or None when already on disk, [(file, italic)], licence file)
FAMILIES = [
    ("Newsreader", "serif", None, [("Newsreader-VF.ttf", False), ("Newsreader-Italic-VF.ttf", True)],
     "OFL-Newsreader.txt"),
    ("Archivo", "sans", None, [("Archivo-VF.ttf", False)], "OFL-Archivo.txt"),
    ("Literata", "serif", "literata",
     [("Literata[opsz,wght].ttf", False), ("Literata-Italic[opsz,wght].ttf", True)], "OFL-Literata.txt"),
    ("EB Garamond", "serif", "ebgaramond",
     [("EBGaramond[wght].ttf", False), ("EBGaramond-Italic[wght].ttf", True)], "OFL-EBGaramond.txt"),
    ("Source Serif 4", "serif", "sourceserif4",
     [("SourceSerif4[opsz,wght].ttf", False), ("SourceSerif4-Italic[opsz,wght].ttf", True)],
     "OFL-SourceSerif4.txt"),
    ("Inter", "sans", "inter",
     [("Inter[opsz,wght].ttf", False), ("Inter-Italic[opsz,wght].ttf", True)], "OFL-Inter.txt"),
    ("Work Sans", "sans", "worksans",
     [("WorkSans[wght].ttf", False), ("WorkSans-Italic[wght].ttf", True)], "OFL-WorkSans.txt"),
    ("Fraunces", "display", "fraunces",
     [("Fraunces[SOFT,WONK,opsz,wght].ttf", False), ("Fraunces-Italic[SOFT,WONK,opsz,wght].ttf", True)],
     "OFL-Fraunces.txt"),
    ("Bebas Neue", "display", "bebasneue", [("BebasNeue-Regular.ttf", False)], "OFL-BebasNeue.txt"),
    ("IBM Plex Mono", "mono", "ibmplexmono", _plex("IBMPlexMono"), "OFL-IBMPlexMono.txt"),
    ("Caveat", "hand", "caveat", [("Caveat[wght].ttf", False)], "OFL-Caveat.txt"),
    ("Atkinson Hyperlegible", "sans", "atkinsonhyperlegible", _plex("AtkinsonHyperlegible"),
     "OFL-AtkinsonHyperlegible.txt"),
]


def fetch(directory: str, name: str, dest: Path) -> None:
    url = BASE + directory + "/" + urllib.parse.quote(name)
    req = urllib.request.Request(url, headers={"User-Agent": "Studio-font-fetch"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"FAILED {url}: HTTP {e.code}")
    dest.write_bytes(data)


def verify(path: Path) -> str:
    from fontTools.ttLib import TTFont
    with TTFont(path, lazy=True) as f:
        return f["name"].getBestFamilyName() or "?"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    FONTS.mkdir(parents=True, exist_ok=True)
    manifest = []
    for family, category, directory, files, lic in FAMILIES:
        wanted = [(n, directory) for n, _ in files] + [(lic, directory)]
        for name, d in wanted:
            dest = FONTS / name
            if dest.exists():
                continue
            if check or d is None:
                raise SystemExit(f"MISSING {dest}")
            fetch(d, "OFL.txt" if name == lic else name, dest)
            print("downloaded", name)
        for name, _ in files:
            print(f"ok  {name}  ({verify(FONTS / name)}, {(FONTS / name).stat().st_size // 1024} KB)")
        manifest.append({"family": family, "category": category, "license": "OFL-1.1", "license_file": lic,
                         "files": [{"file": n, "italic": i} for n, i in files]})
    total = sum(p.stat().st_size for p in FONTS.iterdir() if p.is_file() and p.name != "families.json")
    print(f"total {total / 1048576:.1f} MB of {BUDGET // 1048576} MB")
    if total > BUDGET:
        raise SystemExit("over budget: drop the Fraunces italic, then the Inter italic")
    out = FONTS / "families.json"
    text = json.dumps(manifest, indent=2) + "\n"
    if check:
        if not out.exists() or json.loads(out.read_text("utf-8")) != manifest:
            raise SystemExit("families.json is missing or out of date")
    else:
        out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
