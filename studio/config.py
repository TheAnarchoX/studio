"""Settings live in one config file per user; environment variables override them.

Config file (JSON):
  Windows  %APPDATA%\\Studio\\config.json
  macOS    ~/Library/Application Support/Studio/config.json
  Linux    $XDG_CONFIG_HOME/studio/config.json (~/.config/studio/config.json)
  STUDIO_CONFIG=<file> points somewhere else.

Keys: library (the folder that holds Poems/), signature (the name new poems are signed with),
port, chrome (a Chrome / Chromium / Edge to render with; found automatically when empty),
open_with ("app" or "browser").
Environment overrides: STUDIO_ART (library), STUDIO_PORT, STUDIO_CHROME, STUDIO_CACHE.
"""
import json
import os
import shutil
import sys
from pathlib import Path

HOST = "127.0.0.1"
DEFAULTS = {"library": str(Path.home() / "Studio"), "signature": "", "port": 4747, "chrome": "", "open_with": "app"}


def _config_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Studio"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Studio"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "studio"


def _cache_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Studio" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "Studio"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "studio"


CONFIG_FILE = Path(os.environ.get("STUDIO_CONFIG") or _config_dir() / "config.json")


def load():
    data = dict(DEFAULTS)
    try:
        data.update({k: v for k, v in json.loads(CONFIG_FILE.read_text(encoding="utf-8")).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return data


def save(updates):
    data = load()
    for k, v in (updates or {}).items():
        if k not in DEFAULTS:
            continue
        if k == "port":
            v = int(v)
            if not 1024 <= v <= 65535:
                raise ValueError("the port must be between 1024 and 65535")
        elif k == "open_with" and v not in ("app", "browser"):
            raise ValueError("open_with is 'app' or 'browser'")
        elif k == "library":
            v = str(Path(str(v).strip()).expanduser())
            if not v:
                raise ValueError("choose a folder")
        else:
            v = str(v or "").strip()
        data[k] = v
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    refresh()
    return data


def find_chrome(custom=""):
    """A Chrome, Chromium or Edge to render with (headless). Empty string when none is found."""
    if custom and Path(custom).exists():
        return str(custom)
    found = []
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                found += [Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe",
                          Path(base) / "Chromium" / "Application" / "chrome.exe",
                          Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"]
    elif sys.platform == "darwin":
        for app in ("Google Chrome", "Chromium", "Microsoft Edge", "Brave Browser"):
            found += [Path("/Applications") / f"{app}.app" / "Contents" / "MacOS" / app,
                      Path.home() / "Applications" / f"{app}.app" / "Contents" / "MacOS" / app]
    for p in found:
        if p.exists():
            return str(p)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    return ""


def refresh():
    """Re-read the settings into the module's values (after the config file changed)."""
    global SETTINGS, ART, POEMS, PORT, CHROME, CACHE, SIGNATURE, OPEN_WITH
    SETTINGS = load()
    ART = Path(os.environ.get("STUDIO_ART") or SETTINGS["library"]).expanduser().resolve()
    POEMS = ART / "Poems"
    PORT = int(os.environ.get("STUDIO_PORT") or SETTINGS["port"] or 4747)
    CHROME = find_chrome(os.environ.get("STUDIO_CHROME") or SETTINGS["chrome"])
    CACHE = Path(os.environ.get("STUDIO_CACHE") or _cache_dir())
    SIGNATURE = SETTINGS["signature"]
    OPEN_WITH = SETTINGS["open_with"]


refresh()
