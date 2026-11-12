import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from studio import config, updater
from tests.support import temp_studio


def release(tag="v9.0.0"):
    return json.dumps({
        "tag_name": tag, "html_url": "https://example.test/release", "body": "x" * 3000,
        "assets": [{"name": "other.txt", "browser_download_url": "https://example.test/other.txt"},
                   {"name": updater.ASSET, "browser_download_url": "https://example.test/" + updater.ASSET}],
    }).encode()


class Fetcher:
    def __init__(self, data):
        self.data, self.calls = data, 0

    def __call__(self, url):
        self.calls += 1
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (config.CACHE, config.UPDATE_CHECK)
        config.CACHE = Path(self.tmp.name)
        config.UPDATE_CHECK = True

    def tearDown(self):
        config.CACHE, config.UPDATE_CHECK = self.saved
        self.tmp.cleanup()

    def test_parse_version(self):
        self.assertEqual(updater.parse_version("v1.2.0"), (1, 2, 0))
        self.assertGreater(updater.parse_version("1.10"), updater.parse_version("1.9"))
        self.assertEqual(updater.parse_version("nonsense"), (0,))

    def test_newer_release_is_available(self):
        r = updater.check(fetch=Fetcher(release()), now=1000)
        self.assertTrue(r["available"])
        self.assertEqual(r["latest"], "9.0.0")
        self.assertTrue(r["asset"].endswith("Studio-windows-x64.zip"))
        self.assertEqual(len(r["notes"]), 2000)
        self.assertEqual(r["url"], "https://example.test/release")
        self.assertIn(r["kind"], ("frozen", "source", "package"))

    def test_same_version_is_not_available(self):
        from studio import __version__
        r = updater.check(fetch=Fetcher(release("v" + __version__)), now=1000)
        self.assertFalse(r["available"])

    def test_check_is_cached_for_a_day(self):
        f = Fetcher(release())
        updater.check(fetch=f, now=1000)
        updater.check(fetch=f, now=1000 + 23 * 3600)
        self.assertEqual(f.calls, 1)
        updater.check(fetch=f, now=1000 + 25 * 3600)
        self.assertEqual(f.calls, 2)

    def test_check_respects_the_setting(self):
        config.UPDATE_CHECK = False
        f = Fetcher(release())
        r = updater.check(fetch=f, now=1000)
        self.assertEqual(f.calls, 0)
        self.assertFalse(r["available"])
        updater.check(force=True, fetch=f, now=1000)
        self.assertEqual(f.calls, 1)

    def test_check_survives_network_errors(self):
        errors = [urllib.error.URLError("offline"),
                  urllib.error.HTTPError("u", 403, "rate limited", {}, None),
                  b"not json"]
        for e in errors:
            r = updater.check(force=True, fetch=Fetcher(e), now=1000)
            self.assertFalse(r["available"])
            self.assertIsInstance(r["error"], str)

    def test_update_setting_coerces_to_bool(self):
        with temp_studio():
            for raw, want in ((False, False), ("off", False), ("0", False), ("true", True), ("on", True), ("1", True)):
                self.assertEqual(config.save({"update_check": raw})["update_check"], want)
            self.assertEqual(config.UPDATE_CHECK, True)

    def test_endpoints(self):
        saved = updater._fetch
        updater._fetch = Fetcher(release())
        try:
            with temp_studio() as s:
                code, body = s.get("/api/update")
                self.assertEqual((code, body["available"]), (200, True))
                code, body = s.post("/api/update/check")
                self.assertEqual((code, body["latest"]), (200, "9.0.0"))
        finally:
            updater._fetch = saved


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git isn't installed")
class ApplySourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.remote, self.clone, self.other = base / "remote.git", base / "clone", base / "other"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.remote)], check=True, capture_output=True)
        for d in (self.clone, self.other):
            subprocess.run(["git", "clone", str(self.remote), str(d)], check=True, capture_output=True)
            _git(d, "config", "user.email", "t@example.test")
            _git(d, "config", "user.name", "T")
            _git(d, "config", "commit.gpgsign", "false")  # never inherit the developer's signing setup
            _git(d, "config", "tag.gpgsign", "false")
        (self.other / "a.txt").write_text("one")
        _git(self.other, "add", "."); _git(self.other, "commit", "-m", "one"); _git(self.other, "push", "origin", "HEAD:main")
        _git(self.clone, "pull", "origin", "main"); _git(self.clone, "branch", "--set-upstream-to=origin/main")
        self.pips = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_(self, cmd, **kw):
        if cmd[0] == "git":
            return subprocess.run(cmd, **kw)
        self.pips.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def remote_commit(self, name="b.txt"):
        (self.other / name).write_text("x")
        _git(self.other, "add", "."); _git(self.other, "commit", "-m", name); _git(self.other, "push", "origin", "HEAD:main")
        return _git(self.other, "rev-parse", "HEAD")

    def test_source_update_pulls_and_installs(self):
        new = self.remote_commit()
        log = updater.apply_source(self.clone, run=self.run_)
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD"), new)
        self.assertEqual(len(self.pips), 1)
        self.assertEqual(self.pips[0][1:], ["-m", "pip", "install", "--quiet", "-e", ".[app]"])
        self.assertTrue(log)

    def test_dirty_checkout_is_refused(self):
        self.remote_commit()
        head = _git(self.clone, "rev-parse", "HEAD")
        (self.clone / "a.txt").write_text("changed")
        with self.assertRaisesRegex(updater.UpdateError, "aren't committed"):
            updater.apply_source(self.clone, run=self.run_)
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD"), head)
        self.assertEqual(self.pips, [])

    def test_no_upstream_is_refused(self):
        _git(self.clone, "branch", "--unset-upstream")
        with self.assertRaisesRegex(updater.UpdateError, "track a remote"):
            updater.apply_source(self.clone, run=self.run_)

    def test_diverged_checkout_is_refused(self):
        self.remote_commit()
        (self.clone / "c.txt").write_text("local")
        _git(self.clone, "add", "."); _git(self.clone, "commit", "-m", "local")
        head = _git(self.clone, "rev-parse", "HEAD")
        with self.assertRaisesRegex(updater.UpdateError, "has its own commits.*by hand with git"):
            updater.apply_source(self.clone, run=self.run_)
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD"), head)
        self.assertEqual(self.pips, [])

    def test_missing_git_is_refused(self):
        def run(cmd, **kw):
            raise FileNotFoundError("git")
        with self.assertRaisesRegex(updater.UpdateError, "Git isn't installed"):
            updater.apply_source(self.clone, run=run)

    def test_untracked_files_do_not_block_the_update(self):
        new = self.remote_commit()
        (self.clone / "notes.txt").write_text("mine")
        updater.apply_source(self.clone, run=self.run_)
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD"), new)

    def test_git_and_pip_cannot_hang(self):
        self.remote_commit()
        seen = []

        def run(cmd, **kw):
            seen.append((cmd[0], kw.get("timeout"), (kw.get("env") or {}).get("GIT_TERMINAL_PROMPT")))
            return self.run_(cmd, **kw)
        updater.apply_source(self.clone, run=run)
        self.assertTrue(seen)
        self.assertTrue(all(t == updater.TIMEOUT and p == "0" for _, t, p in seen), seen)

    def test_a_command_that_takes_too_long_is_stopped(self):
        def run(cmd, **kw):
            if cmd[:2] == ["git", "pull"]:
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
            return self.run_(cmd, **kw)
        self.remote_commit()
        with self.assertRaisesRegex(updater.UpdateError, "took longer than"):
            updater.apply_source(self.clone, run=run)

    def test_pip_failure_is_reported(self):
        self.remote_commit()
        def run(cmd, **kw):
            if cmd[0] == "git":
                return subprocess.run(cmd, **kw)
            return subprocess.CompletedProcess(cmd, 1, "", "line one\nERROR: no network\n")
        with self.assertRaisesRegex(updater.UpdateError, "no network"):
            updater.apply_source(self.clone, run=run)


class FrozenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_zip(self, names):
        z = self.base / "r.zip"
        with zipfile.ZipFile(z, "w") as f:
            for n in names:
                f.writestr(n, "x")
        return z

    def test_prepare_frozen_rejects_other_zips(self):
        with self.assertRaisesRegex(updater.UpdateError, "isn't a Studio release"):
            updater.prepare_frozen(self.make_zip(["readme.txt"]), self.base / "out")

    def test_prepare_frozen_extracts(self):
        out = updater.prepare_frozen(self.make_zip(["Studio/Studio.exe", "Studio/lib/a.dll"]), self.base / "out")
        self.assertTrue((out / "Studio.exe").is_file())
        self.assertTrue((out / "lib" / "a.dll").is_file())

    def test_prepare_frozen_ignores_paths_outside_dest(self):
        out = updater.prepare_frozen(self.make_zip(["Studio/Studio.exe", "../evil.txt"]), self.base / "out")
        self.assertFalse((self.base / "evil.txt").exists())
        self.assertTrue((out / "Studio.exe").is_file())

    def test_helper_script_waits_copies_and_starts(self):
        s = updater.helper_script(1234, Path("C:/tmp/Studio"), Path("C:/Apps/Studio"), Path("C:/Apps/Studio/Studio.exe"))
        self.assertIn("Get-Process -Id 1234", s)
        self.assertIn(".WaitForExit(60000)", s)                                   # a minute, unless given
        self.assertIn(".WaitForExit(5000)", updater.helper_script(1, Path("C:/a"), Path("C:/b"), Path("C:/b/S.exe"), wait=5))
        self.assertIn("[IO.Directory]::GetFiles($src", s)
        self.assertIn("$backup = [IO.Path]::GetFullPath('C:\\tmp\\backup')", s)   # next to the new files unless given
        self.assertLess(s.index("WaitForExit"), s.index("GetFiles"))
        self.assertLess(s.index("$backup, $rel"), s.index("$src, $rel"))   # every file backed up before any is replaced
        self.assertIn("update.log", s)
        start = s.index("Start-Process")                                   # after both outcomes of the copy
        self.assertLess(max(s.index("update finished"), s.index("restored the previous version"), s.index("may be incomplete")), start)

    def test_helper_script_quotes_paths_literally(self):
        s = updater.helper_script(1, Path("C:/a $x/it's"), Path("C:/b`c"), Path("C:/b`c/Studio.exe"))
        self.assertIn("$x", s)
        self.assertIn("it''s'", s)
        self.assertIn("'C:\\b`c'", s)
        self.assertNotIn('"C:', s)

    def test_pull_error_prefers_fatal_line(self):
        text = "From https://example.test/x\n * branch main -> FETCH_HEAD\nfatal: refusing to merge\n"
        self.assertEqual(updater._pull_error(text), "fatal: refusing to merge")
        self.assertEqual(updater._pull_error("just this\n"), "just this")

    def test_status_reports_a_failed_update_once(self):
        with mock.patch.object(config, "CACHE", self.base / "cache"), mock.patch.object(config, "UPDATE_CHECK", False):
            log = config.CACHE / "update" / "update.log"
            log.parent.mkdir(parents=True)
            log.write_text("2026-11-01T10:00:00 update failed: an older failure\n")
            updater._mark_applied("9.0.0", pid=os.getpid())
            self.assertNotIn("update_failed", updater.status())          # this Studio applied it and hasn't restarted
            updater._mark_applied("9.0.0", pid=os.getpid() + 100000)     # as the Studio before a restart left it
            self.assertNotIn("update_failed", updater.status())          # the old failure is from before this update
            updater._mark_applied("9.0.0", pid=os.getpid() + 100000)
            with log.open("a") as f:
                f.write("2026-11-12T10:00:00 update failed: The process cannot access the file\n")
            from studio import __version__
            s = updater.status()
            self.assertEqual(s["update_failed"], f"The update didn't finish; Studio is still on {__version__}. See update.log.")
            self.assertNotIn("update_failed", updater.status())          # shown once

    def frozen_apply(self, running):
        """apply() as the packaged app runs it on Windows, from an install in the temp folder; returns (result or
        error, the URLs fetched)."""
        install = self.base / "install"
        install.mkdir()
        (install / "Studio.exe").write_text("old")
        release_zip = self.make_zip(["Studio/Studio.exe", "Studio/_internal/new.txt"]).read_bytes()
        urls = []

        def fetch(url):
            urls.append(url)
            return release() if url == updater.LATEST_URL else release_zip
        with mock.patch.object(config, "CACHE", self.base / "cache"), mock.patch.object(config, "UPDATE_CHECK", True), \
                mock.patch.object(updater, "install_kind", return_value="frozen"), \
                mock.patch.object(updater.sys, "executable", str(install / "Studio.exe")):
            try:
                return updater.apply(fetch=fetch, running=running), urls
            except updater.UpdateError as e:
                return e, urls

    @unittest.skipUnless(sys.platform == "win32", "the packaged update is for Windows")
    def test_frozen_update_is_refused_while_studio_tools_run(self):
        asked = []

        def running(folder, exclude):
            asked.append((folder, exclude))
            return [(4321, str(folder / "studio-cli.exe"))]
        err, urls = self.frozen_apply(running)
        self.assertIsInstance(err, updater.UpdateError)
        self.assertEqual(str(err), "Claude (or another program) is using Studio's tools. Close it, then update.")
        self.assertEqual(asked, [((self.base / "install").resolve(), {os.getpid()})])
        self.assertEqual(urls, [updater.LATEST_URL])                    # nothing downloaded
        self.assertFalse((self.base / "cache" / "update").exists())
        self.assertEqual(updater._pending, {})

    @unittest.skipUnless(sys.platform == "win32", "the packaged update is for Windows")
    def test_frozen_update_downloads_when_nothing_else_runs(self):
        try:
            out, urls = self.frozen_apply(lambda folder, exclude: [])
            self.assertTrue(out["ok"], out)
            self.assertEqual(len(urls), 2)
            self.assertTrue((updater._pending["src"] / "_internal" / "new.txt").is_file())
            self.assertEqual(updater._pending["dst"], (self.base / "install").resolve())
            mark = json.loads((self.base / "cache" / "update-applied.json").read_text(encoding="utf-8"))
            self.assertEqual((mark["pid"], mark["to"]), (os.getpid(), "9.0.0"))
        finally:
            updater._pending.clear()

    @unittest.skipUnless(sys.platform == "win32", "needs Windows")
    def test_running_from_finds_programs_in_the_folder(self):
        folder = self.base / "app"
        folder.mkdir()
        exe = folder / "tool.exe"
        shutil.copy2(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE", exe)
        p = subprocess.Popen([str(exe), "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            found = updater._running_from(folder, exclude={os.getpid()})
            self.assertEqual([pid for pid, _ in found], [p.pid])
            self.assertEqual(updater._running_from(folder, exclude={p.pid}), [])
            self.assertEqual(updater._running_from(self.base / "elsewhere", exclude=set()), [])
        finally:
            p.kill()
            p.wait()

    def test_restart_failure_is_surfaced(self):
        saved = (updater.restart, dict(updater._pending), updater.restart_error)

        def boom():
            raise OSError("powershell missing")
        try:
            updater._pending.update(src=1)
            updater.restart = boom
            with contextlib.redirect_stderr(io.StringIO()) as err:
                updater.restart_safely()
            self.assertIn("Studio couldn't restart itself (OSError: powershell missing)", err.getvalue())
            self.assertEqual(updater._pending, {})
            s = updater.status()
            self.assertTrue(s["restart_failed"])
            self.assertIn("powershell missing", s["error"])
        finally:
            updater.restart, updater.restart_error = saved[0], saved[2]
            updater._pending.clear()
            updater._pending.update(saved[1])


@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell"), "needs Windows PowerShell")
class HelperScriptRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        b = self.base = Path(self.tmp.name)
        self.src, self.dst = b / "new Studio", b / "installed"
        (self.src / "sub dir").mkdir(parents=True)
        self.dst.mkdir()
        self.files = {"a.txt": "new a", "sub dir/b.txt": "new b", "we[ir]d $x.txt": "new weird"}
        for name, text in self.files.items():
            (self.src / name).write_text(text)
        (self.dst / "a.txt").write_text("old a")
        (self.dst / "sub dir").mkdir()          # an install already has its folders (e.g. _internal)
        (self.dst / "sub dir" / "b.txt").write_text("old b")
        (self.dst / "sub dir" / "stale.txt").write_text("stale")
        self.files["sub dir/new.txt"] = "new file"                 # not in the install yet
        (self.src / "sub dir" / "new.txt").write_text("new file")
        self.marker = b / "started.txt"
        (b / "mark.py").write_text(f"open({str(self.marker)!r}, 'w').write('ok')")
        self.cache = b / "cache"                                   # CACHE/update: downloads, backup and the log
        self.cache.mkdir()
        (self.cache / "9.0.0.zip").write_text("an old download")
        self.log, self.backup = self.cache / "update.log", self.cache / "backup"
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        self.pid = gone.pid
        self.exe = Path(sys.executable).with_name("pythonw.exe")     # "Studio's program": what the helper starts
        if not self.exe.exists():
            self.skipTest("no pythonw.exe")

    def tearDown(self):
        self.tmp.cleanup()

    def run_ps(self, script, starts=True):
        """Runs a helper script with Windows PowerShell, then waits for the Studio it starts; with starts=False, waits a
        moment to see that none is started."""
        ps1 = self.base / "helper.ps1"
        ps1.write_text(script, encoding="utf-8-sig")
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)], check=True, capture_output=True, timeout=120)
        if not starts:
            time.sleep(2)
            return
        for _ in range(100):
            if self.marker.exists():
                break
            time.sleep(0.1)

    def run_script(self, pid=None, wait=None, starts=True):
        """Runs the update helper as Studio's restart does (waiting for `pid`, by default one that has already exited)."""
        self.run_ps(updater.helper_script(pid or self.pid, self.src, self.dst, self.exe, self.log, args=[self.base / "mark.py"],
                                          backup=self.backup, clean=self.cache, **({"wait": wait} if wait else {})), starts)

    def studio(self, code):
        """A stand-in for the Studio that is closing: Studio's own program (as the real one is), running `code`."""
        p = subprocess.Popen([str(self.exe), "-c", code])
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        return p

    def failure_shown(self):
        """What the next Studio's status() says after this run's log (an update another Studio applied)."""
        cache = self.base / "C"
        with mock.patch.object(config, "CACHE", cache), mock.patch.object(config, "UPDATE_CHECK", False):
            (cache / "update").mkdir(parents=True, exist_ok=True)
            updater._mark_applied("9.0.0", pid=os.getpid() + 100000)      # as the Studio that asked for the update left it
            shutil.copy(self.log, cache / "update" / "update.log")
            return updater.status().get("update_failed")

    def hold(self, path, share, lock_at):
        """Opens `path` as another program might (reading and writing, sharing `share`: 1 read, 2 write, 4 delete) and
        locks the byte at `lock_at`, so a copy over it opens the file, writes up to there and fails, as a full disk or
        an I/O error would. Returns a function that lets go."""
        import ctypes
        from ctypes import wintypes

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p), ("Offset", wintypes.DWORD),
                        ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k32.CreateFileW(str(path), 0xC0000000, share, None, 3, 0x80, None)      # read and write, open existing
        self.assertNotEqual(h, wintypes.HANDLE(-1).value)
        ov = OVERLAPPED(Offset=lock_at)
        self.assertTrue(k32.LockFileEx(h, 0x3, 0, 1, 0, ctypes.byref(ov)))           # exclusive, fail at once
        return lambda: k32.CloseHandle(h)

    def big_file_last(self):
        """z.bin, last in the copy order: 1 MB installed, 2 MB in the release. Returns the installed bytes."""
        old = b"O" * (1 << 20)
        (self.dst / "z.bin").write_bytes(old)
        (self.src / "z.bin").write_bytes(b"N" * (2 << 20))
        return old

    def assert_old_install(self):
        self.assertEqual((self.dst / "a.txt").read_text(), "old a")
        self.assertEqual((self.dst / "sub dir" / "b.txt").read_text(), "old b")
        self.assertEqual((self.dst / "sub dir" / "stale.txt").read_text(), "stale")
        self.assertFalse((self.dst / "sub dir" / "new.txt").exists())     # a file the update added is taken out again

    def test_script_copies_everything_and_restarts(self):
        self.run_script()
        for name, text in self.files.items():
            self.assertEqual((self.dst / name).read_text(), text, name)
        self.assertNotIn("update failed", self.log.read_text())
        self.assertIn("update finished", self.log.read_text())
        self.assertTrue(self.marker.exists())
        self.assertFalse((self.dst / "sub dir" / "sub dir").exists())   # no nested copy of an existing folder
        self.assertTrue((self.dst / "sub dir" / "stale.txt").exists())  # merged, not replaced
        self.assertEqual([p.name for p in self.cache.iterdir()], ["update.log"])   # downloads and backup cleaned, the log kept

    def test_failed_copy_restores_the_old_files_and_studio_still_starts(self):
        (self.dst / "we[ir]d $x.txt").mkdir()   # a folder where the last file must go: the copy fails after the others
        self.run_script()
        log = self.log.read_text()
        self.assertIn("update failed", log)
        self.assertIn("restored the previous version", log)
        self.assert_old_install()
        self.assertTrue(self.marker.exists())
        self.assertTrue((self.cache / "9.0.0.zip").exists())             # nothing cleaned after a failure
        self.assertFalse(self.backup.exists())

    def test_restart_starts_a_helper_that_runs(self):
        """restart() as the packaged app runs it with an update waiting: the helper it starts (detached from Studio,
        which exits) copies the files and starts Studio again."""
        real, quits = updater.helper_script, []
        saved = dict(updater._pending)
        updater._pending.clear()
        updater._pending.update(src=self.src, dst=self.dst, exe=self.exe)
        try:
            with mock.patch.object(updater, "helper_script", lambda pid, *a, **kw: real(self.pid, *a, **{**kw, "args": [self.base / "mark.py"]})), \
                    mock.patch.object(updater.sys, "frozen", True, create=True), mock.patch.object(config, "CACHE", self.cache.parent), \
                    mock.patch.object(updater, "on_quit", lambda: quits.append(1)):
                helper = self.restart()
        finally:
            updater._pending.clear()
            updater._pending.update(saved)
        self.assertEqual(helper.wait(timeout=60), 0)
        for _ in range(100):
            if self.marker.exists():
                break
            time.sleep(0.1)
        self.assertEqual(quits, [1])
        self.assertTrue(self.marker.exists())
        for name, text in self.files.items():
            self.assertEqual((self.dst / name).read_text(), text, name)

    def restart(self):
        """updater.restart(); returns the helper process it started (so the test can wait for it)."""
        started, popen = [], subprocess.Popen

        def keep(*a, **kw):
            started.append(popen(*a, **kw))
            return started[-1]
        with mock.patch.object(updater.subprocess, "Popen", keep):
            updater.restart()
        self.assertEqual(len(started), 1)
        return started[0]

    def test_a_plain_restart_starts_studio_again(self):
        """restart() as the packaged app runs it with no update waiting (e.g. after a setting that needs one)."""
        real, quits = updater.restart_script, []
        saved = dict(updater._pending)
        updater._pending.clear()
        try:
            with mock.patch.object(updater, "restart_script", lambda pid, *a, **kw: real(self.pid, self.exe, *a[1:], **{**kw, "args": [self.base / "mark.py"]})), \
                    mock.patch.object(updater.sys, "frozen", True, create=True), mock.patch.object(config, "CACHE", self.cache.parent), \
                    mock.patch.object(updater, "on_quit", lambda: quits.append(1)):
                helper = self.restart()
        finally:
            updater._pending.update(saved)
        self.assertEqual(helper.wait(timeout=60), 0)
        for _ in range(100):
            if self.marker.exists():
                break
            time.sleep(0.1)
        self.assertEqual(quits, [1])
        self.assertTrue(self.marker.exists())

    def test_a_plain_restart_never_starts_a_second_studio(self):
        """The plain restart waits for Studio as the update helper does: when Studio hasn't closed, it starts no second
        one and says so in the log; when it closes, Studio is started again."""
        studio = self.studio("import time; time.sleep(60)")
        self.run_ps(updater.restart_script(studio.pid, self.exe, self.log, args=[self.base / "mark.py"], wait=1), starts=False)
        self.assertIsNone(studio.poll())
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.log.read_text().strip()[20:], "Studio didn't close, so it wasn't started again.")
        self.assertIsNone(self.failure_shown())                            # not an update
        studio = self.studio("import time; time.sleep(2)")
        self.run_ps(updater.restart_script(studio.pid, self.exe, self.log, args=[self.base / "mark.py"], wait=30))
        self.assertIsNotNone(studio.poll())
        self.assertTrue(self.marker.exists())

    def test_a_locked_file_restores_the_old_files(self):
        """A file another program holds open (as Claude's studio-cli holds Studio's DLLs) stops the copy part-way."""
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        locked = self.dst / "we[ir]d $x.txt"
        locked.write_text("old weird")
        h = k32.CreateFileW(str(locked), 0x80000000, 1, None, 3, 0x80, None)    # others may read it, not write it: like a loaded DLL
        self.assertNotEqual(h, wintypes.HANDLE(-1).value)
        try:
            self.run_script()
        finally:
            k32.CloseHandle(h)
        log = self.log.read_text()
        self.assertIn("update failed while copying the new files", log)     # backed up, then stopped part-way through the copy
        self.assertIn("restored the previous version", log)
        self.assert_old_install()
        self.assertEqual(locked.read_text(), "old weird")
        self.assertTrue(self.marker.exists())

    def test_a_copy_that_fails_part_way_puts_that_file_back_too(self):
        """The copy opens z.bin, writes part of it and fails: z.bin goes back as well as every file before it, and a
        folder the update made is taken out again."""
        old = self.big_file_last()
        (self.src / "new dir").mkdir()
        (self.src / "new dir" / "c.txt").write_text("new c")
        let_go = self.hold(self.dst / "z.bin", share=1 | 2, lock_at=1536 * 1024)    # not delete: the half-written file stays
        try:
            self.run_script()
        finally:
            let_go()
        log = self.log.read_text()
        self.assertIn("update failed while copying the new files", log)
        self.assertEqual((self.dst / "z.bin").read_bytes(), old)
        self.assert_old_install()
        self.assertFalse((self.dst / "we[ir]d $x.txt").exists())
        self.assertFalse((self.dst / "new dir").exists())
        self.assertIn("restored the previous version", log)
        self.assertNotIn("could not restore", log)
        self.assertFalse(self.backup.exists())
        self.assertTrue(self.marker.exists())
        from studio import __version__
        self.assertEqual(self.failure_shown(), f"The update didn't finish; Studio is still on {__version__}. See update.log.")

    def test_a_file_that_cannot_be_put_back_keeps_the_backup(self):
        """The copy fails part-way through z.bin and Windows deletes the half-written file, but another program still
        holds it, so nothing can be put in its place: the backup, the only copy left of z.bin, is kept and the log says
        so instead of claiming the old version is back."""
        old = self.big_file_last()
        let_go = self.hold(self.dst / "z.bin", share=1 | 2 | 4, lock_at=1536 * 1024)
        try:
            self.run_script()
        finally:
            let_go()
        log = self.log.read_text()
        self.assertIn("update failed while copying the new files", log)
        self.assert_old_install()                                          # every file before it is back
        self.assertFalse((self.dst / "we[ir]d $x.txt").exists())
        self.assertNotIn("restored the previous version", log)
        self.assertIn("could not restore z.bin", log)
        self.assertIn("may be incomplete", log)
        self.assertIn(str(self.backup), log)
        self.assertEqual((self.backup / "z.bin").read_bytes(), old)
        self.assertTrue((self.cache / "9.0.0.zip").exists())
        self.assertTrue(self.marker.exists())
        from studio import __version__
        self.assertEqual(self.failure_shown(), f"The update didn't finish; Studio is still on {__version__}. See update.log. "
                                               "Some of Studio's files couldn't be put back: update again, or download Studio from the release page.")

    def test_a_kept_backup_survives_later_updates(self):
        """A backup an earlier update kept is the only copy of some files: a later update moves it aside and says so,
        whether that update fails or goes in, and never deletes it."""
        (self.backup / "sub dir").mkdir(parents=True)
        (self.backup / "sub dir" / "b.txt").write_text("kept b")
        (self.dst / "we[ir]d $x.txt").mkdir()      # this update fails
        self.run_script()
        kept = [p for p in self.cache.iterdir() if p.name.startswith("backup-")]
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0] / "sub dir" / "b.txt").read_text(), "kept b")
        log = self.log.read_text()
        self.assertIn(str(kept[0]), log)
        self.assertIn("restored the previous version", log)
        self.assert_old_install()
        self.assertFalse(self.backup.exists())                            # this update's own backup, no longer needed
        (self.dst / "we[ir]d $x.txt").rmdir()
        self.marker.unlink()
        self.run_script()                                                  # the next one goes in
        self.assertIn("update finished", self.log.read_text())
        for name, text in self.files.items():
            self.assertEqual((self.dst / name).read_text(), text, name)
        self.assertEqual(sorted(p.name for p in self.cache.iterdir()), sorted(["update.log", kept[0].name]))   # cleaned, but not the kept backup
        self.assertEqual((kept[0] / "sub dir" / "b.txt").read_text(), "kept b")

    def test_studio_still_running_means_nothing_is_copied(self):
        """When Studio hasn't closed after the wait, the helper copies nothing and starts no second Studio (the first is
        still there), and the next Studio reports it as a failed update."""
        studio = self.studio("import time; time.sleep(60)")
        self.run_script(pid=studio.pid, wait=1, starts=False)
        self.assertIsNone(studio.poll())
        self.assertEqual(self.log.read_text().strip()[20:], "Studio didn't close; the update was not applied.")
        self.assert_old_install()
        self.assertFalse((self.dst / "we[ir]d $x.txt").exists())
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.backup.exists())
        self.assertTrue((self.cache / "9.0.0.zip").exists())
        from studio import __version__
        self.assertEqual(self.failure_shown(), f"The update didn't finish; Studio is still on {__version__}. See update.log.")

    def test_a_program_that_took_studios_pid_is_not_waited_for(self):
        """Studio has closed and another program now runs under its pid (any long-running program that isn't Studio's):
        the helper doesn't take it for Studio, so the update goes in and Studio starts."""
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])   # python.exe, not Studio's program
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        self.run_script(pid=other.pid, wait=1)
        self.assertIsNone(other.poll())
        self.assertIn("update finished", self.log.read_text())
        self.assertNotIn("didn't close", self.log.read_text())
        for name, text in self.files.items():
            self.assertEqual((self.dst / name).read_text(), text, name)
        self.assertTrue(self.marker.exists())

    def test_studio_started_by_another_path_is_still_waited_for(self):
        """Studio's program by another spelling of its path (here a copy of it in another folder, as a junction or a
        short name would spell it) that started before the helper is Studio: it is waited for."""
        other = self.base / "elsewhere"
        other.mkdir()
        shutil.copy2(self.exe, other / self.exe.name)
        venv_cfg = self.exe.parent.parent / "pyvenv.cfg"      # a venv's launcher finds its Python through this
        if venv_cfg.exists():
            shutil.copy2(venv_cfg, other / "pyvenv.cfg")
        studio = subprocess.Popen([str(other / self.exe.name), "-c", "import time; time.sleep(60)"])
        try:
            time.sleep(1)
            self.assertIsNone(studio.poll())
            self.run_script(pid=studio.pid, wait=1, starts=False)
            self.assertIsNone(studio.poll())
        finally:
            studio.kill()           # here, not in a cleanup: the temp folder (its program is in it) goes before cleanups run
            studio.wait()
        self.assertEqual(self.log.read_text().strip()[20:], "Studio didn't close; the update was not applied.")
        self.assertFalse(self.marker.exists())

    def test_the_helper_waits_for_studio_to_close(self):
        """The stand-in looks at the install just before it exits: nothing has been copied yet. Afterwards everything has."""
        seen = self.base / "seen.txt"
        studio = self.studio(f"import time, pathlib; time.sleep(2); "
                             f"pathlib.Path({str(seen)!r}).write_text(pathlib.Path({str(self.dst / 'a.txt')!r}).read_text())")
        self.run_script(pid=studio.pid, wait=30)
        self.assertIsNotNone(studio.poll())
        self.assertEqual(seen.read_text(), "old a")                     # Studio was still there: the update waited
        self.assertIn("update finished", self.log.read_text())
        for name, text in self.files.items():
            self.assertEqual((self.dst / name).read_text(), text, name)
        self.assertTrue(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
