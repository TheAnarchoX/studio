"""Studio as a desktop app: its own window, and launchers for Windows, macOS and Linux.

`studio app` opens Studio in a native window (pywebview: WebView2 on Windows, WebKit on macOS, GTK/Qt on
Linux), starting the local server in the same process unless one is already running. Without pywebview it
falls back to a Chrome/Edge app window, then to the default browser.
`studio install` adds a launcher with Studio's icon: a Start menu shortcut on Windows (pin it to the
taskbar), ~/Applications/Studio.app on macOS, a .desktop entry on Linux.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

from . import config, updater

APP_ID = "Studio.PoemStudio"            # Windows AppUserModelID: ties the window to its pinned shortcut
ICONS = Path(__file__).parent / "static" / "icons"
TITLE = "Studio"
LANGUAGE_TAG = config.LANGUAGE_TAG          # books.LANGUAGE too
MAX_LANGUAGES = 12
WEBVIEW2_ARGS = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
USER_ARGS = "STUDIO_WEBVIEW2_USER_ARGUMENTS"        # the user's own WebView2 arguments, before Studio added its languages


def _up(port):
    try:
        with socket.create_connection((config.HOST, port), timeout=.3):
            return True
    except OSError:
        return False


def ensure_server():
    """Start the web server in this process unless one is already listening. True if we started it."""
    if _up(config.PORT):
        return False
    from .web import serve
    threading.Thread(target=serve, kwargs={"quiet": True}, daemon=True).start()
    for _ in range(100):
        if _up(config.PORT):
            break
        time.sleep(.05)
    return True


# ——— the app window's languages: spellcheck in WebView2 ———
def _ui_languages():
    """The OS user's preferred UI languages ("en-US", ...) on Windows; [] elsewhere or when they can't be read."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes
        get = ctypes.windll.kernel32.GetUserPreferredUILanguages
        count, size = wintypes.ULONG(), wintypes.ULONG(0)
        if not get(0x8, ctypes.byref(count), None, ctypes.byref(size)):      # MUI_LANGUAGE_NAME
            return []
        buf = ctypes.create_unicode_buffer(size.value)
        if not get(0x8, ctypes.byref(count), buf, ctypes.byref(size)):
            return []
        return [t for t in buf[:size.value].split("\0") if LANGUAGE_TAG.fullmatch(t)]
    except Exception:  # noqa: BLE001 — no languages is fine: English is added anyway
        return []


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def book_languages(books_root):
    """The language of every book in the library, the most recently written first (a book's newest of book.json and
    its manuscript folder). Example books count only when there is no other book. Read straight from book.json:
    cheap, and nothing else of Studio needs to be up. A book that can't be read, or a folder that can't be listed,
    is left out."""
    own, examples = [], []
    try:
        root = Path(books_root)
        folders = sorted(root.iterdir()) if root.is_dir() else []
    except Exception:  # noqa: BLE001 — an unreadable library gives no languages, never a failure
        return []
    for d in folders:
        try:
            if not d.is_dir() or d.name.startswith((".", "_")):
                continue
            meta = json.loads((d / "book.json").read_text(encoding="utf-8-sig"))
            lang = meta.get("language") if isinstance(meta, dict) else None
            if isinstance(lang, str) and LANGUAGE_TAG.fullmatch(lang.strip()):
                when = max(_mtime(d / "book.json"), _mtime(d / "manuscript"))
                (examples if meta.get("example") is True else own).append((when, lang.strip()))
        except Exception:  # noqa: BLE001 — unreadable, not JSON, nested too deep (RecursionError): left out
            continue
    return [lang for _, lang in sorted(own or examples, key=lambda x: -x[0])]


def accept_languages(books_root, ui=None, spelling="auto"):
    """WebView2's --accept-lang: the language chosen in Settings → Spelling (or, when that is automatic, the books'
    languages, the most recently written first), then the OS user's UI languages, then English, de-duplicated and at
    most MAX_LANGUAGES. WebView2 checks spelling in the first language of the list, in the whole window (checked in the
    app window: with en-US first a Dutch book's words were all underlined, with nl first only the misspelt one)."""
    try:
        chosen = [spelling] if isinstance(spelling, str) and LANGUAGE_TAG.fullmatch(spelling) else []
        tags = [*chosen, *book_languages(books_root), *(_ui_languages() if ui is None else ui)]
    except Exception:  # noqa: BLE001
        tags = []
    seen, out = set(), []
    for tag in tags:
        if isinstance(tag, str) and LANGUAGE_TAG.fullmatch(tag) and tag.lower() not in seen and len(out) < MAX_LANGUAGES - 1:
            seen.add(tag.lower())
            out.append(tag)
    if "en" not in seen:
        out.append("en")
    return ",".join(out)


def webview2_arguments(user, languages):
    """The user's own WebView2 arguments with --accept-lang added, unless they set one themselves."""
    user = (user or "").strip()
    if "--accept-lang" in user:
        return user
    return (user + " " if user else "") + f"--accept-lang={languages}"


def set_webview2_languages(environ, books_root, ui=None, spelling="auto"):
    """Sets WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS for the app window. The user's own arguments are remembered in
    STUDIO_WEBVIEW2_USER_ARGUMENTS the first time, so a Studio started by Studio (an update's restart inherits the
    environment) adds a fresh list to them instead of keeping the old one. Never raises: the window always opens."""
    try:
        if USER_ARGS not in environ:
            environ[USER_ARGS] = environ.get(WEBVIEW2_ARGS, "")
        environ[WEBVIEW2_ARGS] = webview2_arguments(environ[USER_ARGS], accept_languages(books_root, ui, spelling))
    except Exception:  # noqa: BLE001 — e.g. a value the environment refuses: WebView2 starts with what it had
        pass


class Api:
    """Called from the page (window.pywebview.api) when Studio runs as an app."""
    def pick_folder(self, start=""):
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        res = webview.windows[0].create_file_dialog(kind, directory=start or str(Path.home()))
        return res[0] if res else None


def _windows_icon():
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.FindWindowW.restype = wintypes.HWND
    u.LoadImageW.restype = wintypes.HANDLE
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    ico = str(ICONS / "studio.ico")
    for _ in range(40):
        hwnd = u.FindWindowW(None, TITLE)
        if hwnd:
            for size, which in ((16, 0), (32, 1)):   # ICON_SMALL, ICON_BIG
                h = u.LoadImageW(None, ico, 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
                if h:
                    u.SendMessageW(hwnd, 0x80, which, h)          # WM_SETICON
            return
        time.sleep(.1)


def _mac_icon():
    try:
        from AppKit import NSApplication, NSImage
        from PyObjCTools import AppHelper
        img = NSImage.alloc().initWithContentsOfFile_(str(ICONS / "studio.icns"))
        AppHelper.callAfter(lambda: NSApplication.sharedApplication().setApplicationIconImage_(img))
    except Exception:  # noqa: BLE001 — only cosmetic
        pass


def run_app():
    url = f"http://{config.HOST}:{config.PORT}/"
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:  # noqa: BLE001
            pass
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        lnk = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Studio.lnk"
        if not lnk.exists():   # the packaged app adds itself to the Start menu on its first run (so it can be pinned)
            try:
                install()
            except Exception:  # noqa: BLE001
                pass
    started = ensure_server()
    if config.OPEN_WITH == "browser":
        webbrowser.open(url)
        return _hold(started)
    try:
        import webview
    except ImportError:
        return _fallback(url, started)
    if sys.platform.startswith("linux"):
        try:
            from gi.repository import GLib
            GLib.set_prgname("studio")          # matches StartupWMClass in the .desktop entry
        except Exception:  # noqa: BLE001
            pass
    win = webview.create_window(TITLE, url, width=1480, height=940, min_size=(960, 640), background_color="#F4F2EE" if config.THEME == "light" else "#141619", js_api=Api())
    updater.on_quit = lambda: win.destroy()          # a restart after an update closes the window cleanly
    if sys.platform == "win32":
        win.events.shown += lambda: threading.Thread(target=_windows_icon, daemon=True).start()
    elif sys.platform == "darwin":
        win.events.shown += _mac_icon
    (config.CACHE / "webview").mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":     # spellcheck (Settings → Spelling); read when WebView2 starts, so a change needs a restart
        set_webview2_languages(os.environ, config.BOOKS, spelling=config.SPELLING)
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True          # Save in the viewer
    except Exception:  # noqa: BLE001
        pass
    try:
        webview.start(private_mode=False, storage_path=str(config.CACHE / "webview"))
    except Exception:  # noqa: BLE001 — no GUI backend (e.g. Linux without GTK or Qt): use a browser window
        return _fallback(url, started)


def _fallback(url, started):
    """No pywebview: a Chrome/Edge app window (its own profile, so it stays one window), else the browser."""
    if config.CHROME:
        profile = config.CACHE / "app-window"
        p = subprocess.Popen([config.CHROME, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"])
        if started:
            p.wait()
        return
    webbrowser.open(url)
    _hold(started)


def _hold(started):
    if started:
        print(f"Studio is running at http://{config.HOST}:{config.PORT}/ (Ctrl+C to stop)", file=sys.stderr)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


# ——— launchers ———
def _launch_command():
    """What a launcher runs: the packaged app, or this Python with `-m studio app`."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable), []
    py = Path(sys.executable)
    if sys.platform == "win32" and (py.parent / "pythonw.exe").exists():
        py = py.parent / "pythonw.exe"                    # no console window
    return py, ["-m", "studio", "app"]


def _windows_shortcut(lnk: Path, target: Path, args, icon: str):
    """A .lnk with Studio's icon and AppUserModelID, so the running window groups under a pinned shortcut."""
    cs = r'''
using System; using System.Runtime.InteropServices; using System.Runtime.InteropServices.ComTypes;
[ComImport, Guid("00021401-0000-0000-C000-000000000046")] class CShellLink {}
[ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
interface IShellLinkW {
  void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder f, int c, IntPtr p, uint fl);
  void GetIDList(out IntPtr p); void SetIDList(IntPtr p);
  void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder n, int c);
  void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string n);
  void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder d, int c);
  void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string d);
  void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder a, int c);
  void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string a);
  void GetHotkey(out short h); void SetHotkey(short h); void GetShowCmd(out int s); void SetShowCmd(int s);
  void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder p, int c, out int i);
  void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string p, int i);
  void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string p, uint r); void Resolve(IntPtr h, uint f);
  void SetPath([MarshalAs(UnmanagedType.LPWStr)] string f);
}
[ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
interface IPropertyStore { void GetCount(out uint c); void GetAt(uint i, out PKey k); void GetValue(ref PKey k, out PVar v); void SetValue(ref PKey k, ref PVar v); void Commit(); }
[StructLayout(LayoutKind.Sequential, Pack = 4)] public struct PKey { public Guid fmtid; public uint pid; }
[StructLayout(LayoutKind.Explicit)] public struct PVar { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; [FieldOffset(8)] public long pad; }
public static class StudioLnk {
  public static void Make(string lnk, string target, string args, string dir, string icon, string appId, string desc) {
    var link = (IShellLinkW)new CShellLink();
    link.SetPath(target); link.SetArguments(args); link.SetWorkingDirectory(dir); link.SetIconLocation(icon, 0); link.SetDescription(desc);
    var store = (IPropertyStore)link;
    var key = new PKey { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
    var v = new PVar { vt = 31, p = Marshal.StringToCoTaskMemUni(appId) };
    store.SetValue(ref key, ref v); store.Commit();
    ((IPersistFile)link).Save(lnk, true);
    Marshal.FreeCoTaskMem(v.p);
  }
}'''
    q = lambda s: "'" + str(s).replace("'", "''") + "'"   # noqa: E731 — PowerShell single-quoted string
    script = (f"Add-Type -TypeDefinition @'\n{cs}\n'@\n"
              f"[StudioLnk]::Make({q(lnk)}, {q(target)}, {q(' '.join(args))}, {q(Path.home())}, {q(icon)}, {q(APP_ID)}, 'Studio')")
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as f:
        f.write(script)
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", f.name], check=True, capture_output=True, text=True,
                       creationflags=0x08000000)   # CREATE_NO_WINDOW
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"couldn't create the shortcut: {e.stderr.strip() or e.stdout.strip()}") from None
    finally:
        os.unlink(f.name)


def install(desktop=False):
    """Add Studio to the Start menu / Applications / app launcher. Returns the paths it wrote."""
    target, args = _launch_command()
    made = []
    if sys.platform == "win32":
        icon = f"{target}" if getattr(sys, "frozen", False) else str(ICONS / "studio.ico")
        programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        places = [programs] + ([Path.home() / "Desktop"] if desktop else [])
        for place in places:
            lnk = place / "Studio.lnk"
            _windows_shortcut(lnk, target, args, icon)
            made.append(lnk)
    elif sys.platform == "darwin":
        app = Path.home() / "Applications" / "Studio.app"
        (app / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
        (app / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
        shutil.copy(ICONS / "studio.icns", app / "Contents" / "Resources" / "studio.icns")
        (app / "Contents" / "Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Studio</string><key>CFBundleDisplayName</key><string>Studio</string>
  <key>CFBundleIdentifier</key><string>io.github.theanarchox.studio</string>
  <key>CFBundleExecutable</key><string>Studio</string><key>CFBundleIconFile</key><string>studio.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string><key>NSHighResolutionCapable</key><true/>
</dict></plist>
""", encoding="utf-8")
        run = app / "Contents" / "MacOS" / "Studio"
        run.write_text("#!/bin/sh\nexec " + " ".join(f'"{a}"' for a in [target, *args]) + "\n", encoding="utf-8")
        run.chmod(0o755)
        made.append(app)
    else:
        share = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        icon = share / "icons" / "hicolor" / "512x512" / "apps" / "studio.png"
        icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ICONS / "icon-512.png", icon)
        entry = share / "applications" / "studio.desktop"
        entry.parent.mkdir(parents=True, exist_ok=True)
        exec_line = " ".join(f'"{a}"' for a in [target, *args])
        entry.write_text(f"""[Desktop Entry]
Type=Application
Name=Studio
Comment=A studio for poems and their artwork
Exec={exec_line}
Icon={icon}
Terminal=false
Categories=Graphics;Office;
StartupWMClass=studio
""", encoding="utf-8")
        entry.chmod(0o755)
        made.append(entry)
        if desktop:
            d = Path.home() / "Desktop" / "studio.desktop"
            if d.parent.exists():
                shutil.copy(entry, d)
                d.chmod(0o755)
                made.append(d)
    return made


def uninstall():
    gone = []
    if sys.platform == "win32":
        for p in (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Studio.lnk", Path.home() / "Desktop" / "Studio.lnk"):
            if p.exists():
                p.unlink(); gone.append(p)
    elif sys.platform == "darwin":
        app = Path.home() / "Applications" / "Studio.app"
        if app.exists():
            shutil.rmtree(app); gone.append(app)
    else:
        share = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        for p in (share / "applications" / "studio.desktop", share / "icons" / "hicolor" / "512x512" / "apps" / "studio.png", Path.home() / "Desktop" / "studio.desktop"):
            if p.exists():
                p.unlink(); gone.append(p)
    return gone
