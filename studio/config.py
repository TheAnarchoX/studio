"""Settings live in one config file per user; environment variables override them.

Config file (JSON):
  Windows  %APPDATA%\\Studio\\config.json
  macOS    ~/Library/Application Support/Studio/config.json
  Linux    $XDG_CONFIG_HOME/studio/config.json (~/.config/studio/config.json)
  STUDIO_CONFIG=<file> points somewhere else.

Keys: library (the folder that holds Poems/), signature (the name new poems are signed with),
port, chrome (a Chrome / Chromium / Edge to render with; found automatically when empty),
open_with ("app" or "browser"), update_check (ask GitHub daily for a newer release), default_look (the look
new series start from and every work falls back to; Studio's starters or the library's own Styles/looks),
theme ("system", "light" or "dark"), spelling (the language Studio's own window checks spelling in: "auto", the
language of the book written in last, or a language tag such as "nl"; read when the window starts).
Environment overrides: STUDIO_ART (library), STUDIO_PORT, STUDIO_CHROME, STUDIO_CACHE.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

HOST = "127.0.0.1"
DEFAULTS = {"library": str(Path.home() / "Studio"), "signature": "", "port": 4747, "chrome": "", "open_with": "app", "update_check": True,
            "default_look": "Editorial light", "theme": "system", "spelling": "auto"}
THEMES = ("system", "light", "dark")
LANGUAGE_TAG = re.compile(r"(?=.{2,35}$)[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,6}")      # at most 35 characters, 6 subtags


def spelling_of(value):
    """The spelling setting as read: a language tag, or "auto" for anything else."""
    v = " ".join(str(value or "").split())
    return v if LANGUAGE_TAG.fullmatch(v) else "auto"


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
        elif k == "update_check":
            if isinstance(v, str):
                if v.strip().lower() not in ("true", "false", "1", "0", "on", "off"):
                    raise ValueError("update_check is on or off")
                v = v.strip().lower() in ("true", "1", "on")
            else:
                v = bool(v)
        elif k == "theme":
            v = str(v or "").strip().lower()
            if v not in THEMES:
                raise ValueError("theme is 'system', 'light' or 'dark'")
        elif k == "spelling":
            v = " ".join(str(v or "").split()) if isinstance(v, str) or v is None else None
            if v is None or not (v.lower() in ("", "auto") or LANGUAGE_TAG.fullmatch(v)):
                raise ValueError("Spelling is automatic or a language code, like nl or en-GB.")
            v = "auto" if v.lower() in ("", "auto") else v
        elif k == "default_look":
            v = " ".join(str(v or "").split())
            if not 1 <= len(v) <= 60:
                raise ValueError("choose a look (a name of 1 to 60 characters)")
        elif k == "library":
            if not str(v or "").strip():
                raise ValueError("choose a folder")
            v = str(Path(str(v).strip()).expanduser())
        else:
            v = str(v or "").strip()
        data[k] = v
    from .store import write_text       # here, not at the top: store imports this module
    write_text(CONFIG_FILE, json.dumps(data, ensure_ascii=False, indent=2) + "\n")     # atomic: never half a file
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
    global SETTINGS, ART, POEMS, BOOKS, PORT, CHROME, CACHE, SIGNATURE, OPEN_WITH, UPDATE_CHECK, DEFAULT_LOOK, THEME, SPELLING
    SETTINGS = load()
    ART = Path(os.environ.get("STUDIO_ART") or SETTINGS["library"]).expanduser().resolve()
    POEMS = ART / "Poems"
    BOOKS = ART / "Books"
    PORT = int(os.environ.get("STUDIO_PORT") or SETTINGS["port"] or 4747)
    CHROME = find_chrome(os.environ.get("STUDIO_CHROME") or SETTINGS["chrome"])
    CACHE = Path(os.environ.get("STUDIO_CACHE") or _cache_dir())
    SIGNATURE = SETTINGS["signature"]
    OPEN_WITH = SETTINGS["open_with"]
    UPDATE_CHECK = bool(SETTINGS["update_check"])
    THEME = SETTINGS["theme"] if SETTINGS["theme"] in THEMES else "system"
    DEFAULT_LOOK = str(SETTINGS["default_look"] or DEFAULTS["default_look"])
    SPELLING = spelling_of(SETTINGS["spelling"])


refresh()
