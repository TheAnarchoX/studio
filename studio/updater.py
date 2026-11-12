"""Updates: asks GitHub once a day whether a newer release exists (never raises, never prints), and applies one."""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import __version__, config
from .store import StoreError

LATEST_URL = "https://api.github.com/repos/TheAnarchoX/studio/releases/latest"
ASSET = "Studio-windows-x64.zip"
DAY = 24 * 3600
RETRY_AFTER_ERROR = 3600


def parse_version(s):
    nums = re.match(r"v?(\d+(?:\.\d+)*)", str(s or "").strip())
    return tuple(int(n) for n in nums.group(1).split(".")) if nums else (0,)


def install_kind():
    if getattr(sys, "frozen", False):
        return "frozen"
    import studio
    return "source" if (Path(studio.__file__).parent.parent / ".git").exists() else "package"


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": f"Studio/{__version__}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read()


def _cache_file():
    return config.CACHE / "update.json"


def _read_cache():
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(data):
    _write_json(_cache_file(), data)


def _result(latest=None, url=None, notes="", asset=None, checked=0, error=None):
    out = {"current": __version__, "latest": latest, "available": bool(latest) and parse_version(latest) > parse_version(__version__),
           "url": url, "notes": notes, "asset": asset, "checked": checked, "kind": install_kind()}
    if error:
        out["error"] = error
    return out


def check(force=False, now=None, fetch=None):
    now = time.time() if now is None else now
    cached = _read_cache()
    last = cached.get("checked")
    if not force:
        wait = RETRY_AFTER_ERROR if cached.get("error") else DAY
        if not config.UPDATE_CHECK or (last is not None and now - last < wait):
            return _result(cached.get("latest"), cached.get("url"), cached.get("notes", ""), cached.get("asset"), last or 0, cached.get("error"))
    try:
        rel = json.loads((fetch or _fetch)(LATEST_URL).decode("utf-8"))
        asset = next((a.get("browser_download_url") for a in rel.get("assets") or [] if a.get("name") == ASSET), None)
        data = {"latest": str(rel["tag_name"]).lstrip("vV"), "url": rel.get("html_url"),
                "notes": (rel.get("body") or "")[:2000], "asset": asset, "checked": now}
    except Exception as e:
        data = {"latest": cached.get("latest"), "url": cached.get("url"), "notes": cached.get("notes", ""),
                "asset": cached.get("asset"), "checked": now, "error": str(e) or e.__class__.__name__}
    _write_cache(data)
    return _result(**data)


# ——— applying an update ———

PIP_COMMAND = 'python -m pip install --upgrade "studio-poems[app] @ git+https://github.com/TheAnarchoX/studio"'
RELEASES_PAGE = "https://github.com/TheAnarchoX/studio/releases/latest"
TIMEOUT = 300           # seconds git or pip may take before the update gives up
IN_USE = "Claude (or another program) is using Studio's tools. Close it, then update."
FAILED = "The update didn't finish; Studio is still on {version}. See update.log."
INCOMPLETE = "Some of Studio's files couldn't be put back: update again, or download Studio from the release page."
# the helpers' log lines
NOT_CLOSED = "Studio didn't close; the update was not applied."
NOT_PUT_BACK = "not every file could be put back, so the install may be incomplete; the previous files are kept in "
NOT_RESTARTED = "Studio didn't close, so it wasn't started again."
FAILURES = ("update failed", NOT_CLOSED)                             # what in update.log means the update didn't go in


class UpdateError(StoreError):
    """An update that can't go ahead; the message is a sentence for the person."""


def _first_line(text):
    return next((ln.strip() for ln in str(text or "").splitlines() if ln.strip()), "")


def _pull_error(text):
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    tagged = [ln for ln in lines if ln.lower().startswith(("fatal:", "error:"))]
    return (tagged or lines or [""])[-1]


def apply_source(root, run=subprocess.run):
    """Fast-forward a git checkout and reinstall it. Returns log lines. Git never asks for a password (it fails
    instead), and git and pip are stopped after TIMEOUT seconds."""
    root = Path(root)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def call(cmd, what, missing):
        try:
            return run(cmd, cwd=root, capture_output=True, text=True, timeout=TIMEOUT, env=env)
        except FileNotFoundError:
            raise UpdateError(missing) from None
        except subprocess.TimeoutExpired:
            raise UpdateError(f"{what} took longer than {TIMEOUT // 60} minutes, so Studio stopped it. Check the network and try again.") from None

    def git(*args):
        return call(["git", *args], f"git {args[0]}", "Git isn't installed or not on the PATH.")

    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise UpdateError("Studio's folder has changes that aren't committed. Commit or stash them, then update.")
    if git("rev-parse", "--abbrev-ref", "@{u}").returncode != 0:
        raise UpdateError("This checkout doesn't track a remote branch.")
    pull = git("pull", "--ff-only")
    if pull.returncode != 0:
        err = (pull.stderr or "").lower()
        if "fast-forward" in err or "diverg" in err:
            raise UpdateError("This copy of Studio has its own commits, so it can't update itself. Update it by hand with git.")
        raise UpdateError(_pull_error(pull.stderr) or _pull_error(pull.stdout) or "git pull failed.")
    log = [ln for ln in (pull.stdout or "").splitlines() if ln.strip()][-5:]
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "-e", ".[app]"]
    pip = call(cmd, "pip", "Python couldn't run pip.")
    if pip.returncode != 0:
        last = next((ln.strip() for ln in reversed((pip.stderr or "").splitlines()) if ln.strip()), "pip failed.")
        raise UpdateError(f"{last} The new code is downloaded; run `{' '.join(cmd[2:])}` in Studio's folder by hand.")
    return log + ["Installed the new version."]


def prepare_frozen(zip_path, dest):
    """Extract a release zip into dest and return its Studio folder."""
    dest = Path(dest)
    try:
        z = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError):
        raise UpdateError("The download isn't a Studio release.") from None
    with z:
        names = z.namelist()
        if "Studio/Studio.exe" not in names:
            raise UpdateError("The download isn't a Studio release.")
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        base = dest.resolve()
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if base != target and base not in target.parents:
                continue   # never write outside dest
            z.extract(info, dest)
    return dest / "Studio"


def _ps(path):
    """A PowerShell single-quoted literal (no $ or backtick expansion)."""
    return "'" + str(path).replace("'", "''") + "'"


def _wait_for_studio(pid, exe, wait):
    """PowerShell lines that wait up to `wait` seconds for Studio (process `pid`) to exit and set $closed. Studio may
    have closed already and another program taken its pid; that one is not waited for. So the process only counts as
    Studio when its program is `exe`, or has exe's name and started before this script (the same program by another
    spelling of its path, e.g. through a junction): a process that took the pid started after Studio, so after this."""
    return [
        f"$exe = [IO.Path]::GetFullPath({_ps(exe)})",
        "$closed = $true",
        "try {",
        f"  $studio = Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue",
        "  if ($studio -and (($studio.Path -eq $exe) -or (([IO.Path]::GetFileName([string]$studio.Path) -eq [IO.Path]::GetFileName($exe)) -and"
        " ($studio.StartTime -lt (Get-Process -Id $PID).StartTime)))) {",
        f"    if (-not $studio.WaitForExit({int(wait * 1000)})) {{ $closed = $false }}",
        "  }",
        "} catch {}",
    ]


def _start(exe, args):
    return f"Start-Process -FilePath {_ps(exe)}" + (f" -ArgumentList {','.join(_ps(chr(34) + str(a) + chr(34)) for a in args)}" if args else "")


def restart_script(pid, exe, log, args=(), wait=60):
    """PowerShell that waits for Studio (process `pid`, program `exe`) to exit and starts it again. When it hasn't
    closed after `wait` seconds, no second Studio is started and the log says so."""
    return "\n".join([
        f"$log = {_ps(log)}",
        "function Note($m) { try { Add-Content -LiteralPath $log -Value ((Get-Date -Format s) + ' ' + $m) } catch {} }",
        *_wait_for_studio(pid, exe, wait),
        f"if ($closed) {{ {_start(exe, args)} }} else {{ Note {_ps(NOT_RESTARTED)} }}",
    ])


def helper_script(pid, src, dst, exe, log=None, args=(), backup=None, clean=None, wait=60):
    """PowerShell that waits for Studio to exit, copies the new files over it and starts it again.

    When Studio (its program is `exe`) is still running after `wait` seconds, nothing is copied and no second Studio is
    started ("Studio didn't close; the update was not applied."). Otherwise the copy is all or nothing: every file it will replace is
    first copied to `backup`, then the new files go in (in a fixed order), each noted as touched before it is opened.
    If any of that fails, every touched file is put back from the backup (or taken out again when the update added
    it) and the folders the update made are removed. Only when every one of them really is back (a file that can't be
    written but still holds exactly its backup's bytes counts as back) does the log say "restored the previous version"
    and the backup go; otherwise the backup is kept and the log says where and that the install may be incomplete. A
    backup kept like that by an earlier update is moved aside (`<backup>-<time>`), never deleted, also not by the
    clean-up: after a whole update the folder `clean` (the downloads and the backup) is emptied except for the log and
    those kept backups. Studio is started at the end whatever the copy did."""
    log = log or Path(src).parent / "update.log"
    backup = backup or Path(src).parent / "backup"
    cleanup = ([f"    Get-ChildItem -LiteralPath {_ps(clean)} -Force |"
                " Where-Object { $_.Name -ne 'update.log' -and -not $_.Name.StartsWith($keptPrefix) } |"
                " Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"] if clean else [])
    return "\n".join([
        f"$log = {_ps(log)}",
        f"$src = [IO.Path]::GetFullPath({_ps(src)}).TrimEnd('\\')",
        f"$dst = [IO.Path]::GetFullPath({_ps(dst)}).TrimEnd('\\')",
        f"$backup = [IO.Path]::GetFullPath({_ps(backup)}).TrimEnd('\\')",
        "$keptPrefix = [IO.Path]::GetFileName($backup) + '-'",
        "function Note($m) { try { Add-Content -LiteralPath $log -Value ((Get-Date -Format s) + ' ' + $m) } catch {} }",
        "function Same($a, $b) {   # both files readable and byte for byte the same",
        "  $x = $null; $y = $null",
        "  try {",
        "    $x = [IO.File]::Open($a, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]'ReadWrite, Delete')",
        "    $y = [IO.File]::Open($b, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]'ReadWrite, Delete')",
        "    if ($x.Length -ne $y.Length) { return $false }",
        "    $p = New-Object byte[] 1048576; $q = New-Object byte[] 1048576",
        "    while ($true) {",
        "      $n = $x.Read($p, 0, $p.Length)",
        "      if ($n -le 0) { return $true }",
        "      $m = 0",
        "      while ($m -lt $n) { $k = $y.Read($q, $m, $n - $m); if ($k -le 0) { return $false }; $m += $k }",
        "      if ([Convert]::ToBase64String($p, 0, $n) -ne [Convert]::ToBase64String($q, 0, $n)) { return $false }",
        "    }",
        "  } catch { return $false } finally { if ($x) { $x.Dispose() }; if ($y) { $y.Dispose() } }",
        "}",
        "$touched = New-Object System.Collections.Generic.List[string]",
        "$added = New-Object 'System.Collections.Generic.HashSet[string]'",
        "$made = New-Object System.Collections.Generic.List[string]",
        "$ours = $false",
        "$ok = $false",
        *_wait_for_studio(pid, exe, wait),
        "if (-not $closed) {",
        "  Note " + _ps(NOT_CLOSED),
        "} else {",
        "  $step = 'reading the new files'",
        "  try {",
        "    Start-Sleep -Milliseconds 500",
        "    [string[]]$rels = [IO.Directory]::GetFiles($src, '*', 'AllDirectories') | ForEach-Object { $_.Substring($src.Length + 1) }",
        "    [Array]::Sort($rels, [StringComparer]::Ordinal)",
        "    $step = 'backing up the old files'",
        "    if ([IO.Directory]::Exists($backup)) {   # kept by an earlier update that couldn't put everything back",
        "      $stamp = $backup + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss'); $kept = $stamp; $i = 2",
        "      while ([IO.Directory]::Exists($kept) -or [IO.File]::Exists($kept)) { $kept = $stamp + '-' + $i; $i++ }",
        "      [IO.Directory]::Move($backup, $kept)",
        "      Note ('the backup an earlier update kept is now in ' + $kept)",
        "    }",
        "    $ours = $true",
        "    foreach ($rel in $rels) {",
        "      $t = [IO.Path]::Combine($dst, $rel)",
        "      if ([IO.File]::Exists($t)) {",
        "        $b = [IO.Path]::Combine($backup, $rel)",
        "        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($b))",
        "        [IO.File]::Copy($t, $b, $true)",
        "      }",
        "    }",
        "    $step = 'copying the new files'",
        "    foreach ($rel in $rels) {",
        "      $t = [IO.Path]::Combine($dst, $rel)",
        "      if (-not [IO.File]::Exists($t)) { [void]$added.Add($rel) }",
        "      $touched.Add($rel)",
        "      $d = [IO.Path]::GetDirectoryName($t)",
        "      while ($d -and -not [IO.Directory]::Exists($d)) { $made.Add($d); $d = [IO.Path]::GetDirectoryName($d) }",
        "      [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($t))",
        "      [IO.File]::Copy([IO.Path]::Combine($src, $rel), $t, $true)",
        "    }",
        "    $ok = $true",
        "    Note 'update finished'",
        "  } catch {",
        "    Note ('update failed while ' + $step + ': ' + $_.Exception.Message)",
        "    $whole = $true",
        "    foreach ($rel in $touched) {",
        "      $t = [IO.Path]::Combine($dst, $rel)",
        "      $b = [IO.Path]::Combine($backup, $rel)",
        "      try {",
        "        if ($added.Contains($rel)) { if ([IO.File]::Exists($t)) { [IO.File]::Delete($t) } }",
        "        else { [IO.File]::Copy($b, $t, $true) }",
        "      } catch {",
        "        $why = $_.Exception.Message",
        "        if ($added.Contains($rel) -or -not (Same $t $b)) { $whole = $false; Note ('could not restore ' + $rel + ': ' + $why) }",
        "      }",
        "    }",
        "    foreach ($d in ($made | Sort-Object Length -Descending)) { try { [IO.Directory]::Delete($d) } catch {} }",
        "    if ($whole) {",
        "      Note 'restored the previous version'",
        "      if ($ours) { try { [IO.Directory]::Delete($backup, $true) } catch {} }",
        "    } else {",
        f"      Note ({_ps(NOT_PUT_BACK)} + $backup)",
        "    }",
        "  }",
        *(["  if ($ok) {", *cleanup, "  }"] if cleanup else []),
        "  " + _start(exe, args),
        "}",
    ])


def _running_from(folder, exclude=()):
    """[(pid, path)] of the processes whose program file is inside `folder`, other than the pids in `exclude`
    (Windows, through PowerShell's Get-CimInstance; [] when that can't be asked)."""
    script = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath } |"
              " ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.ExecutablePath }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return []
    base = os.path.normcase(str(Path(folder).resolve())).rstrip("\\/") + os.sep
    out = []
    for line in r.stdout.splitlines():
        pid, _, path = line.strip().partition("|")
        if pid.isdigit() and int(pid) not in exclude and os.path.normcase(path).startswith(base):
            out.append((int(pid), path))
    return out


def _applied_file():
    return config.CACHE / "update-applied.json"


def _mark_applied(version, pid=None):
    """Notes that an update is about to be copied in, so the Studio that starts next can tell whether it went in."""
    log = config.CACHE / "update" / "update.log"
    try:
        size = log.stat().st_size
    except OSError:
        size = 0
    _write_json(_applied_file(), {"from": __version__, "to": version, "pid": os.getpid() if pid is None else pid,
                                  "log_size": size, "at": time.time()})


def _write_json(path, data):
    try:
        from .store import write_text
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, json.dumps(data, ensure_ascii=False))
    except Exception:
        pass


def _update_failure():
    """The sentence for an update that a previous Studio applied and the helper logged as failed; None otherwise.
    Read once: the note is removed, so the failure is shown once."""
    mark = _applied_file()
    try:
        data = json.loads(mark.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("pid") == os.getpid():
        return None          # this Studio applied it and hasn't restarted yet
    try:
        with open(config.CACHE / "update" / "update.log", "rb") as f:
            f.seek(int(data.get("log_size") or 0))
            since = f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        since = ""
    mark.unlink(missing_ok=True)
    if not any(f in since for f in FAILURES):
        return None
    return FAILED.format(version=__version__) + (" " + INCOMPLETE if NOT_PUT_BACK in since else "")


_pending = {}


def apply(fetch=None, running=None):
    """Applies the latest release (`fetch` and `running` stand in for the network and the process list in tests)."""
    global restart_error
    restart_error = ""
    kind = install_kind()
    info = check(fetch=fetch)
    if not info["available"]:
        raise UpdateError("Studio is up to date.")
    if kind == "source":
        return {"ok": True, "restart": True, "log": apply_source(Path(__file__).resolve().parent.parent)}
    if kind == "frozen" and sys.platform == "win32":
        if not info.get("asset"):
            raise UpdateError(f"This release has no download for Windows. Get it from {info.get('url') or RELEASES_PAGE}.")
        install = Path(sys.executable).resolve().parent
        if (running or _running_from)(install, {os.getpid()}):    # e.g. Claude's studio-cli mcp: its files can't be replaced
            raise UpdateError(IN_USE)
        folder = config.CACHE / "update"
        folder.mkdir(parents=True, exist_ok=True)
        zip_path = folder / f"{info['latest']}.zip"
        try:
            zip_path.write_bytes((fetch or _fetch)(info["asset"]))
        except Exception as e:
            raise UpdateError(f"The download failed: {e}") from None
        src = prepare_frozen(zip_path, folder / "extracted")
        _pending.update(src=src, dst=install, exe=Path(sys.executable).resolve())
        _mark_applied(info["latest"])
        return {"ok": True, "restart": True, "log": [f"Downloaded Studio {info['latest']}."]}
    if kind == "frozen":
        raise UpdateError(f"Update Studio from the release page: {info.get('url') or RELEASES_PAGE}")
    raise UpdateError(f"Studio was installed with pip. Update it with: {PIP_COMMAND}")


# ——— restarting ———

_WAIT_AND_START = """
import ctypes, os, subprocess, sys, time
pid = int(sys.argv[1]); cmd = sys.argv[2:]
for _ in range(240):
    if os.name == "nt":
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if not h:
            break
        done = ctypes.windll.kernel32.WaitForSingleObject(h, 250) == 0
        ctypes.windll.kernel32.CloseHandle(h)
        if done:
            break
    else:
        try:
            os.kill(pid, 0)
        except OSError:
            break
        time.sleep(0.25)
time.sleep(0.5)
subprocess.Popen(cmd, close_fds=True, **({"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}))
"""


# How the PowerShell helper is started on Windows: in a console of its own that is never shown, in its own group, so it
# outlives Studio. Not DETACHED_PROCESS: Windows PowerShell started without a console exits without running the script.
HELPER_FLAGS = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)}


def _quit():
    time.sleep(0.5)
    os._exit(0)


def on_quit():
    """Closes Studio after a restart was scheduled; the desktop window replaces this."""
    threading.Thread(target=_quit, daemon=True).start()


restart_error = ""


def restart_safely():
    """What the restart timer runs: a failure is logged and shown in the next status, not lost in a thread."""
    global restart_error
    try:
        restart()
    except Exception as e:  # noqa: BLE001
        _pending.clear()
        restart_error = f"Studio couldn't restart itself ({e.__class__.__name__}: {e}). Close it and open it again."
        print(restart_error, file=sys.stderr)


def status():
    """check(), with a restart that failed in this Studio, or (once) an update that didn't go in before it started."""
    out = check()
    if restart_error:
        out = {**out, "error": restart_error, "restart_failed": True}
    failed = _update_failure()
    if failed:
        out = {**out, "update_failed": failed}
    return out


def restart():
    detached = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
    args = sys.argv[1:]
    me = str(os.getpid())
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            if _pending:
                folder = config.CACHE / "update"
                script = helper_script(os.getpid(), _pending["src"], _pending["dst"], _pending["exe"], folder / "update.log",
                                       backup=folder / "backup", clean=folder)
            else:
                folder = config.CACHE / "update"
                folder.mkdir(parents=True, exist_ok=True)
                script = restart_script(os.getpid(), Path(sys.executable).resolve(), folder / "update.log")
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script], close_fds=True, **HELPER_FLAGS)
        else:
            sh = 'while kill -0 "$0" 2>/dev/null; do sleep 0.25; done; exec "$@"'
            subprocess.Popen(["sh", "-c", sh, me, sys.executable, *args], close_fds=True, **detached)
    else:
        subprocess.Popen([sys.executable, "-c", _WAIT_AND_START, me, sys.executable, "-m", "studio", *args], close_fds=True, **detached)
    on_quit()
