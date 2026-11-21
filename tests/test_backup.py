"""Backups: what goes in, the zip and its manifest, the locks, the failures as sentences, the settings, the endpoints.

Every test points STUDIO_ART, STUDIO_CONFIG, STUDIO_CACHE and STUDIO_BACKUPS at a temp folder: no test reads or writes
the real library, config or backup folder."""
import errno
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from studio import backup, config
from tests.support import temp_studio

NOW = datetime(2026, 11, 13, 3, 0)
_ENV = ("STUDIO_ART", "STUDIO_CONFIG", "STUDIO_CACHE", "STUDIO_BACKUPS")


def _put(path: Path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fake(path: Path, manifest: dict):
    """A minimal backup zip with this manifest."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Poems/Sea/series.json", "{}")
        z.writestr(backup.MANIFEST, json.dumps(manifest))


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-backup-")).resolve()
        self.lib, self.dest = self.tmp / "lib", self.tmp / "backups"
        self.saved_env = {k: os.environ.get(k) for k in _ENV}
        self.saved_cfg = config.CONFIG_FILE
        os.environ.update({"STUDIO_ART": str(self.lib), "STUDIO_CONFIG": str(self.tmp / "config.json"),
                           "STUDIO_CACHE": str(self.tmp / "cache"), "STUDIO_BACKUPS": str(self.dest)})
        config.CONFIG_FILE = self.tmp / "config.json"
        config.refresh()
        backup._first_check_done = False        # as in a Studio that just started
        lib = self.lib
        _put(lib / "Poems/Sea/series.json", json.dumps({"name": "Sea"}))
        _put(lib / "Poems/Sea/_kit/build.py", "RATIOS = {}\n")
        _put(lib / "Poems/Sea/_kit/__pycache__/b.pyc")
        self.poem = lib / "Poems/Sea/Harbour"
        _put(self.poem / "poem.json", json.dumps({"title": "Harbour", "slug": "harbour", "status": "draft"}))
        _put(self.poem / "drafts/2026-11-12T0310.md", "# Harbour\n\nsalt on the rope\n")
        _put(self.poem / "writing-notes.md", "notes, ’s nachts\n")
        _put(self.poem / ".studio/days.json", '{"2026-11-12": 4}')
        _put(self.poem / "designs/night.json", "{}")
        _put(self.poem / "designs/.trash/old.json", "{}")
        _put(self.poem / "Design renders/night/x.png")
        _put(self.poem / "harbour.html")
        _put(self.poem / "Carousel 4x5/Signed/harbour-45-1-flare.png")
        _put(self.poem / "harbour-carousel-preview.png")
        _put(self.poem / "my-photo.png")
        _put(self.poem / ".poem.json.12.34.tmp")
        _put(lib / "Poems/.trash/Sea/Old/poem.json", json.dumps({"title": "Old", "slug": "old"}))
        book = lib / "Books/Field Notes"
        _put(book / "book.json", json.dumps({"title": "Field Notes", "contents": [
            {"auto": "title-page"}, {"file": "one.md", "kind": "chapter", "form": "prose", "status": "draft"},
            {"file": "gone.md", "kind": "chapter"}]}))
        _put(book / "manuscript/one.md", "# One\n\nThe first piece.\n")
        _put(book / "exports/Field Notes 2026-11-12 1405.docx")
        _put(book / ".studio/days.json", '{"2026-11-12": 40}')
        _put(lib / "Styles/rules.md")
        _put(lib / "Research/n.md")
        _put(lib / "Research/.trash/x.md")
        _put(lib / "Other/big.bin", "0123456789")
        _put(lib / "top.txt", "top")

    def tearDown(self):
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.CONFIG_FILE = self.saved_cfg
        config.refresh()
        backup._first_check_done = False
        shutil.rmtree(self.tmp, ignore_errors=True)

    def use_backups(self, folder: Path):
        os.environ["STUDIO_BACKUPS"] = str(folder)
        config.refresh()

    # ——— what goes in ———
    def test_included_follows_the_skip_rules(self):
        self.assertEqual([a for _, a in backup.included(self.lib)], sorted([
            "Books/Field Notes/.studio/days.json", "Books/Field Notes/book.json",
            "Books/Field Notes/exports/Field Notes 2026-11-12 1405.docx", "Books/Field Notes/manuscript/one.md",
            "Poems/Sea/Harbour/.studio/days.json", "Poems/Sea/Harbour/designs/night.json",
            "Poems/Sea/Harbour/drafts/2026-11-12T0310.md", "Poems/Sea/Harbour/my-photo.png",
            "Poems/Sea/Harbour/poem.json", "Poems/Sea/Harbour/writing-notes.md", "Poems/Sea/_kit/build.py",
            "Poems/Sea/series.json", "Research/n.md", "Styles/rules.md"]))
        self.assertEqual(backup.included(self.lib)[0][0], self.lib / "Books/Field Notes/.studio/days.json")

    def test_links_inside_are_never_followed(self):
        elsewhere = _put(self.tmp / "elsewhere/secret.md").parent
        link = self.poem / "linked"
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(str(elsewhere), str(link))
        else:
            os.symlink(elsewhere, link)
        self.assertFalse(any("linked" in a for _, a in backup.included(self.lib)))
        self.assertEqual(backup.outside(self.lib)["folders"], ["Other"])

    def test_fingerprint_follows_names_sizes_and_times(self):
        files = backup.included(self.lib)
        first = backup.fingerprint(files)
        self.assertEqual(first, backup.fingerprint(backup.included(self.lib)))
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        (self.poem / "writing-notes.md").write_text("longer notes now", encoding="utf-8")
        self.assertNotEqual(first, backup.fingerprint(backup.included(self.lib)))

    def test_outside(self):
        self.assertEqual(backup.outside(self.lib)["folders"], ["Other"])
        self.assertEqual(backup.outside(self.lib)["files"], 1)
        self.assertEqual(backup.outside(self.lib)["bytes"], 13)
        _put(self.lib / "More/a.bin")
        self.assertEqual(backup.outside(self.lib)["folders"], ["Other"])      # cached for 10 minutes

    # ——— the zip ———
    def test_run_makes_a_verified_zip(self):
        seen = []
        r = backup.run(now=NOW, progress=lambda done, total: seen.append((done, total, backup.status()["running"])))
        self.assertEqual(r["name"], "Studio backup 2026-11-13 0300.zip")
        self.assertEqual(r["result"], "made")
        self.assertEqual((r["files"], r["warnings"]), (14, []))
        self.assertEqual(r["bytes"], (self.dest / r["name"]).stat().st_size)
        with zipfile.ZipFile(self.dest / r["name"]) as z:
            m = json.loads(z.read("studio-backup.json"))
            self.assertEqual(sorted(n for n in z.namelist() if n != "studio-backup.json"),
                             [a for _, a in backup.included(self.lib)])
            self.assertEqual(z.read("Poems/Sea/Harbour/writing-notes.md"),
                             (self.poem / "writing-notes.md").read_bytes())
            self.assertEqual(z.namelist()[-1], "studio-backup.json")
            self.assertEqual(z.getinfo("Poems/Sea/Harbour/my-photo.png").compress_type, zipfile.ZIP_STORED)
            self.assertEqual(z.getinfo("Poems/Sea/Harbour/poem.json").compress_type, zipfile.ZIP_DEFLATED)
        self.assertEqual((m["format"], m["library"], m["files"]), (1, str(self.lib), 14))
        self.assertEqual((m["computer"], m["created"], m["warnings"]), (platform.node(), "2026-11-13T03:00:00", []))
        self.assertEqual(m["fingerprint"], backup.fingerprint(backup.included(self.lib)))
        self.assertEqual(m["items"]["series"], [{"name": "Sea"}])
        self.assertEqual(m["items"]["poems"], [{"id": "Sea/Harbour", "title": "Harbour", "series": "Sea"}])
        self.assertEqual(m["items"]["books"], [{"id": "Field Notes", "title": "Field Notes", "pieces": [
            {"file": "one.md", "title": "One", "kind": "chapter", "form": "prose"}]}])
        self.assertEqual(m["items"]["books"][0]["pieces"][0]["file"], "one.md")
        self.assertEqual(list(self.dest.glob("*.partial")), [])
        self.assertFalse((self.dest / backup.LOCK).exists())
        self.assertEqual(seen[-1][:2], (14, 14))
        self.assertEqual(seen[-1][2], {"reason": "manual", "done": 14, "total": 14})
        self.assertIsNone(backup.status()["running"])
        state = backup.status()["state"]
        self.assertEqual((state["last_ok"]["name"], state["last_result"], state["last_check"]),
                         (r["name"], "made", "2026-11-13T03:00:00"))

    def test_same_minute_gets_a_number(self):
        backup.run(now=NOW)
        self.assertEqual(backup.run(now=NOW)["name"], "Studio backup 2026-11-13 0300-2.zip")
        self.assertEqual(backup.run(now=NOW)["name"], "Studio backup 2026-11-13 0300-3.zip")

    def test_unchanged_makes_no_zip_unless_asked(self):
        backup.run(now=NOW)
        r = backup.run("daily", now=NOW + timedelta(days=2))
        self.assertEqual((r["result"], r["name"]), ("unchanged", "Studio backup 2026-11-13 0300.zip"))
        self.assertEqual(len(list(self.dest.glob("*.zip"))), 1)
        self.assertEqual(backup.status()["state"]["last_check"], "2026-11-15T03:00:00")
        self.assertEqual(backup.status()["state"]["last_result"], "unchanged")
        self.assertEqual(backup.run("manual", now=NOW + timedelta(days=2))["result"], "made")
        (self.poem / "writing-notes.md").write_text("changed", encoding="utf-8")
        self.assertEqual(backup.run("daily", now=NOW + timedelta(days=3))["result"], "made")

    def test_leftovers_are_cleaned_and_foreign_files_left_alone(self):
        self.dest.mkdir()
        (self.dest / "Studio backup 2026-11-12 0100.zip.partial").write_bytes(b"x")
        (self.dest / "notes.txt").write_text("mine")
        (self.dest / "Studio backup final.zip").write_bytes(b"y")
        (self.dest / "Studio backup final.zip.partial").write_bytes(b"z")
        backup.run(now=NOW)
        self.assertFalse((self.dest / "Studio backup 2026-11-12 0100.zip.partial").exists())
        self.assertTrue((self.dest / "notes.txt").exists())
        self.assertTrue((self.dest / "Studio backup final.zip").exists())
        self.assertTrue((self.dest / "Studio backup final.zip.partial").exists())

    def test_a_missing_folder_is_made_when_its_parent_is_there(self):
        self.use_backups(self.tmp / "made-now")
        self.assertEqual(backup.run(now=NOW)["result"], "made")
        self.assertTrue((self.tmp / "made-now" / "Studio backup 2026-11-13 0300.zip").is_file())

    # ——— reading the library safely ———
    @unittest.skipUnless(sys.platform == "win32", "Windows sharing modes")
    def test_a_save_never_waits_on_the_backup(self):
        f = self.poem / "writing-notes.md"
        old = f.read_bytes()
        tmp = f.with_name("new.tmp")
        tmp.write_text("new", encoding="utf-8")
        with backup.open_shared(f) as g:
            os.replace(tmp, f)          # would raise PermissionError with a plain open()
            self.assertEqual(g.read(), old)
        self.assertEqual(f.read_text(encoding="utf-8"), "new")

    def test_open_shared_raises_like_open(self):
        with self.assertRaises(FileNotFoundError):
            backup.open_shared(self.poem / "nothing.md")
        with self.assertRaises(FileNotFoundError):
            backup.open_shared(self.poem / "no folder" / "nothing.md")
        with self.assertRaises(OSError):
            backup.open_shared(self.poem)

    def test_read_stable(self):
        data, st, stable = backup.read_stable(self.poem / "poem.json")
        self.assertEqual((data, st.st_size, stable), ((self.poem / "poem.json").read_bytes(), len(data), True))

    def test_changed_while_read_is_retried_then_noted(self):
        real, opened = backup.open_shared, []

        def bumping(path):
            if Path(path).name == "writing-notes.md":
                opened.append(path)
                t = time.time() + 10 * len(opened)
                os.utime(path, (t, t))
            return real(path)
        with mock.patch.object(backup, "open_shared", bumping):
            r = backup.run(now=NOW)
        self.assertIn("Poems/Sea/Harbour/writing-notes.md changed while it was copied.", r["warnings"])
        self.assertEqual(len(opened), 3)
        with zipfile.ZipFile(self.dest / r["name"]) as z:
            self.assertIn("Poems/Sea/Harbour/writing-notes.md", z.namelist())
            self.assertEqual(json.loads(z.read(backup.MANIFEST))["warnings"], r["warnings"])

    def test_unreadable_file_is_left_out_with_a_warning(self):           # Review Focus 3
        real = backup.open_shared

        def refusing(path):
            if Path(path).name == "writing-notes.md":
                raise PermissionError(13, "Permission denied", str(path))
            return real(path)
        with mock.patch.object(backup, "open_shared", refusing):
            r = backup.run(now=NOW)
        self.assertEqual(r["result"], "made")
        self.assertTrue(any("writing-notes.md couldn't be read" in w for w in r["warnings"]))
        self.assertEqual(r["files"], 13)
        with zipfile.ZipFile(self.dest / r["name"]) as z:
            m = json.loads(z.read(backup.MANIFEST))
            self.assertNotIn("Poems/Sea/Harbour/writing-notes.md", z.namelist())
        self.assertEqual((m["files"], m["warnings"]), (13, r["warnings"]))
        self.assertEqual(backup.status()["state"]["last_ok"]["warnings"], r["warnings"])

    def test_a_file_that_vanished_is_left_out_quietly(self):
        real = backup.open_shared

        def vanishing(path):
            if Path(path).name == "writing-notes.md":
                raise FileNotFoundError(2, "No such file", str(path))
            return real(path)
        with mock.patch.object(backup, "open_shared", vanishing):
            r = backup.run(now=NOW)
        self.assertEqual((r["result"], r["files"], r["warnings"]), ("made", 13, []))

    def test_a_file_that_could_not_be_read_is_tried_again(self):
        """The manifest's fingerprint is of the files the backup holds: one left out because it couldn't be read makes
        the next scheduled run (when due) see a change, and try it again."""
        real = backup.open_shared

        def refusing(path):
            if Path(path).name == "writing-notes.md":
                raise PermissionError(13, "Permission denied", str(path))
            return real(path)
        config.BACKUPS_ON = True
        with mock.patch.object(backup, "open_shared", refusing):
            first = backup.auto(True, now=NOW)
        self.assertEqual((first["result"], first["files"]), ("made", 13))
        self.assertNotEqual(backup.manifest(first["name"])["fingerprint"],
                            backup.fingerprint(backup.included(self.lib)))
        later = backup.auto(False, now=NOW + timedelta(hours=25))           # due: a day on, and readable now
        self.assertEqual((later["result"], later["files"], later["warnings"]), ("made", 14, []))
        with zipfile.ZipFile(self.dest / later["name"]) as z:
            self.assertEqual(z.read("Poems/Sea/Harbour/writing-notes.md"),
                             (self.poem / "writing-notes.md").read_bytes())
        self.assertEqual(backup.manifest(later["name"])["fingerprint"], backup.fingerprint(backup.included(self.lib)))
        self.assertEqual(backup.auto(False, now=NOW + timedelta(hours=50))["result"], "unchanged")    # all in now

    def test_a_name_a_backup_cannot_store_is_left_out_with_a_warning(self):
        """A name that isn't valid UTF-16 (a lone surrogate, which some file systems allow) can't go in a zip: that file
        is left out, with a sentence naming its folder, and the backup is made."""
        real, other = backup.included, self.poem / "writing-notes.md"       # any file: only its name in the zip counts

        def with_odd_names(library, warnings=None):
            return real(library, warnings) + [(other, "Poems/Sea/Harbour/sea\udc80salt.md"),
                                              (other, "Poems/Sea/Odd\ud800/poem.json"),
                                              (other, "Poems/Sea/Odd\ud800/drafts/one.md")]
        with mock.patch.object(backup, "included", with_odd_names):
            r = backup.run(now=NOW)
            self.assertEqual(backup.run("daily", now=NOW + timedelta(days=1))["result"], "unchanged")
        self.assertEqual((r["result"], r["files"]), ("made", 14))
        self.assertEqual(r["warnings"], [
            "A file in Poems/Sea/Harbour has a name a backup can't store; rename it to include it.",
            "A folder in Poems/Sea has a name a backup can't store; rename it to include it."])
        with zipfile.ZipFile(self.dest / r["name"]) as z:
            self.assertEqual(len(z.namelist()), 15)
            self.assertEqual(json.loads(z.read(backup.MANIFEST))["warnings"], r["warnings"])

    def test_old_and_future_file_times(self):                            # Review Focus 2
        os.utime(self.poem / "poem.json", (0, 0))
        os.utime(self.poem / "writing-notes.md", (5e9, 5e9))
        r = backup.run(now=NOW)
        self.assertEqual(r["result"], "made")
        with zipfile.ZipFile(self.dest / r["name"]) as z:
            self.assertEqual(z.getinfo("Poems/Sea/Harbour/poem.json").date_time, (1980, 1, 1, 0, 0, 0))
            self.assertEqual(z.getinfo("Poems/Sea/Harbour/writing-notes.md").date_time[0], 2107)

    def test_names_with_accents_round_trip(self):                         # Review Focus 1
        folder = self.lib / "Poems/Zee – één/Café, ’s nachts"
        _put(self.lib / "Poems/Zee – één/series.json", "{}")
        _put(folder / "poem.json", json.dumps({"title": "Café, ’s nachts", "slug": "cafe-s-nachts"}))
        _put(folder / "café-notes.md", "één")
        r = backup.run(now=NOW)
        with zipfile.ZipFile(self.dest / r["name"]) as z:
            self.assertIn("Poems/Zee – één/Café, ’s nachts/poem.json", z.namelist())
            self.assertEqual(z.read("Poems/Zee – één/Café, ’s nachts/café-notes.md").decode("utf-8"), "één")
            items = json.loads(z.read(backup.MANIFEST))["items"]
        self.assertIn({"id": "Zee – één/Café, ’s nachts", "title": "Café, ’s nachts", "series": "Zee – één"},
                      items["poems"])

    # ——— failures ———
    def assert_failure(self, text=None, contains=()):
        with self.assertRaises(backup.BackupError) as cm:
            backup.run(now=NOW)
        message = str(cm.exception)
        if text is not None:
            self.assertEqual(message, text)
        for part in contains:
            self.assertIn(part, message)
        self.assertEqual(backup.status()["state"]["last_error"]["message"], message)
        self.assertEqual(list(self.dest.glob("*.partial")) if self.dest.exists() else [], [])
        self.assertEqual(list(self.dest.glob("*.zip")) if self.dest.exists() else [], [])
        self.assertFalse((self.dest / backup.LOCK).exists())
        return message

    def test_failures_are_sentences_in_the_state(self):
        missing = self.tmp / "missing-drive" / "Backups"
        self.use_backups(missing)
        self.assert_failure(f"The backup folder {missing} isn't there. Is the drive connected?")
        self.assertFalse(missing.exists())
        self.use_backups(self.lib / "backups")
        self.assert_failure("Choose a backup folder outside your library.")
        self.use_backups(self.tmp)
        self.assert_failure("Your library is inside that folder. Choose a folder outside it.")
        _put(self.tmp / "a-file")
        self.use_backups(self.tmp / "a-file")
        self.assert_failure(f"That's a file, not a folder: {self.tmp / 'a-file'}.")
        self.use_backups(self.dest)
        _put(self.lib / "Research/long.md", "word " * 40_000)
        need = int(1.2 * sum(p.stat().st_size for p, _ in backup.included(self.lib)))       # no backup yet: 1.2 x all
        full = SimpleNamespace(total=1 << 30, used=0, free=1024)
        with mock.patch.object(backup.shutil, "disk_usage", return_value=full):
            message = self.assert_failure(contains=("is full", "Free some space or choose another folder."))
        self.assertEqual(message, f"The disk with {self.dest} is full (1 KB free; a backup needs about "
                                  f"{backup.size_text(need)}). Free some space or choose another folder.")
        self.assertEqual(backup.size_text(need), "235 KB")
        with mock.patch.object(zipfile.ZipFile, "writestr", side_effect=OSError(errno.ENOSPC, "No space")):
            self.assert_failure(contains=(f"The disk with {self.dest} is full",
                                          "Free some space or choose another folder."))
        with mock.patch.object(zipfile.ZipFile, "writestr", side_effect=PermissionError(13, "Permission denied")):
            self.assert_failure(f"Studio can't write in {self.dest}. Choose another folder.")
        with mock.patch.object(zipfile.ZipFile, "writestr", side_effect=OSError(errno.EIO, "Input/output error")):
            self.assert_failure("The backup didn't finish: input/output error.")
        self.assertEqual(backup.status()["state"]["last_result"], "failed")
        self.assertEqual(backup.run(now=NOW)["result"], "made")
        self.assertNotIn("last_error", backup.status()["state"])

    def test_a_library_that_is_not_there_is_not_backed_up_as_empty(self):
        gone = self.tmp / "unplugged" / "Library"
        os.environ["STUDIO_ART"] = str(gone)
        config.refresh()
        self.assert_failure(f"Your library {gone} isn't there. Is the drive connected?")

    def test_a_backup_that_does_not_read_back_is_not_kept(self):
        with mock.patch.object(zipfile.ZipFile, "testzip", return_value="Poems/Sea/series.json"):
            self.assert_failure(contains=("The backup didn't finish",))

    def test_sizes_in_sentences(self):
        self.assertEqual([backup.size_text(n) for n in (0, 1, 940 * 1024, 12 * 1024 ** 2, int(1.24 * 1024 ** 3),
                                                        int(9.5 * 1024 ** 2), 150 * 1024 ** 3)],
                         ["1 KB", "1 KB", "940 KB", "12 MB", "1.2 GB", "9.5 MB", "150 GB"])

    def test_a_corrupt_state_file_is_read_as_empty(self):
        f = Path(config.CACHE) / "backups" / "state.json"
        _put(f, "{not json")
        self.assertEqual(backup.status()["state"], {})
        backup.run(now=NOW)
        self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["last_result"], "made")

    def test_locks(self):
        self.assertTrue(backup._BUSY.acquire(blocking=False))
        try:
            with self.assertRaises(backup.BackupError) as cm:
                backup.run(now=NOW)
            self.assertEqual(cm.exception.code, 409)
        finally:
            backup._BUSY.release()
        self.assertNotIn("last_error", backup.status()["state"])      # another run's business, not a failure
        self.dest.mkdir()
        lock = self.dest / backup.LOCK
        lock.write_text(json.dumps({"pid": 1, "when": "2026-11-13T02:59:00"}))
        with self.assertRaises(backup.BackupError) as cm:
            backup.run(now=NOW)
        self.assertEqual(cm.exception.code, 409)
        self.assertIn("Another Studio", str(cm.exception))
        self.assertTrue(lock.exists())                                  # never someone else's lock
        old = time.time() - 3 * 3600
        os.utime(lock, (old, old))
        self.assertEqual(backup.run(now=NOW)["result"], "made")
        self.assertFalse(lock.exists())

    def test_a_lock_names_this_computer_and_process(self):
        self.dest.mkdir()
        seen = []
        real = backup._write

        def peek(*args, **kwargs):
            seen.append(json.loads((self.dest / backup.LOCK).read_text(encoding="utf-8")))
            return real(*args, **kwargs)
        with mock.patch.object(backup, "_write", peek):
            backup.run(now=NOW)
        self.assertEqual((seen[0]["pid"], seen[0]["computer"]), (os.getpid(), platform.node()))

    def test_a_lock_left_by_a_studio_that_stopped_is_replaced(self):
        """The app's server is a daemon thread: closing the window can end it mid-backup, before it lets go of the
        lock. A lock from this computer whose process isn't running is stale at once."""
        self.dest.mkdir()
        lock = self.dest / backup.LOCK
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        lock.write_text(json.dumps({"pid": gone.pid, "computer": platform.node(), "when": NOW.isoformat()}))
        self.assertFalse(backup._running_here(gone.pid))
        self.assertEqual(backup.run(now=NOW)["result"], "made")
        self.assertFalse(lock.exists())

    def test_a_fresh_lock_of_a_running_studio_or_another_computer_refuses(self):
        self.dest.mkdir()
        lock = self.dest / backup.LOCK
        alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        try:
            self.assertTrue(backup._running_here(alive.pid))
            for holder in ({"pid": alive.pid, "computer": platform.node()},       # a Studio here that is backing up
                           {"pid": gone.pid, "computer": "OTHER-PC"}):           # its pid says nothing here
                lock.write_text(json.dumps({**holder, "when": NOW.isoformat()}))
                with self.assertRaises(backup.BackupError) as cm:
                    backup.run(now=NOW)
                self.assertEqual(cm.exception.code, 409)
                self.assertTrue(lock.exists())
        finally:
            alive.kill()
            alive.wait()

    def test_the_lock_is_let_go_when_studio_exits(self):
        self.dest.mkdir()
        mine = backup._lock_folder(self.dest)
        self.assertTrue((self.dest / backup.LOCK).exists())
        backup._let_go_at_exit()                    # registered with atexit
        self.assertFalse((self.dest / backup.LOCK).exists())
        (self.dest / backup.LOCK).write_bytes(b"someone else's")
        backup._unlock_folder(self.dest, mine)      # never someone else's
        backup._let_go_at_exit()
        self.assertTrue((self.dest / backup.LOCK).exists())

    def test_a_lock_file_that_cannot_be_written_is_not_left_behind(self):
        """A full FAT or exFAT drive makes the lock's entry and then fails its write: the half-made lock must go, or
        every run for 2 hours would say another Studio is backing up."""
        real = os.fdopen

        class Full:
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.f.close()

            def write(self, data):
                raise OSError(errno.ENOSPC, "No space left on device")

        def fdopen(fd, mode="r", *args, **kwargs):
            f = real(fd, mode, *args, **kwargs)
            return Full(f) if "w" in mode else f      # only the lock file is written through os.fdopen
        self.dest.mkdir()
        with mock.patch.object(backup.os, "fdopen", fdopen):
            self.assert_failure(f"The disk with {self.dest} is full. Free some space or choose another folder.")
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertEqual(backup.run(now=NOW)["result"], "made")
        self.assertFalse((self.dest / backup.LOCK).exists())

    # ——— the list ———
    def test_list_backups(self):
        first = backup.run(now=NOW)["name"]
        second = backup.run(now=NOW + timedelta(hours=1))["name"]
        base = {"format": 1, "computer": platform.node(), "files": 1, "fingerprint": "x"}
        _fake(self.dest / "Studio backup 2026-11-14 0000.zip",
              {**base, "library": str(self.tmp / "another"), "created": "2026-11-14T00:00:00"})
        _fake(self.dest / "Studio backup 2026-11-15 0000.zip",
              {**base, "library": str(self.lib), "computer": "OTHER-PC", "created": "2026-11-15T00:00:00"})
        (self.dest / "Studio backup 2026-01-01 0000.zip").write_bytes(b"not a zip")
        (self.dest / "notes.txt").write_text("mine")
        listed = backup.list_backups()
        self.assertEqual([(b["name"], b["same_library"], b["readable"]) for b in listed], [
            ("Studio backup 2026-11-15 0000.zip", False, True), ("Studio backup 2026-11-14 0000.zip", False, True),
            (second, True, True), (first, True, True), ("Studio backup 2026-01-01 0000.zip", False, False)])
        self.assertEqual(listed[0]["computer"], "OTHER-PC")
        self.assertEqual(listed[2]["when"], "2026-11-13T04:00:00")
        self.assertEqual(listed[2]["files"], 14)
        self.assertEqual(listed[2]["bytes"], (self.dest / second).stat().st_size)
        self.assertEqual(listed[2]["library"], str(self.lib))
        self.assertEqual(listed[-1]["when"], "2026-01-01T00:00:00")
        self.assertEqual(listed[-1]["bytes"], 9)
        self.assertEqual(backup.newest()["name"], second)
        self.assertEqual(backup.newest(now=NOW + timedelta(minutes=30))["name"], first)   # none from the future
        self.assertEqual(backup.list_backups(self.dest), listed)

    def test_manifest(self):
        name = backup.run(now=NOW)["name"]
        self.assertEqual(backup.manifest(name)["files"], 14)
        for bad in ("../x", "Studio backup 2026-11-13 0301.zip", "notes.txt", None):
            with self.assertRaises(backup.BackupError) as cm:
                backup.manifest(bad)
            self.assertEqual(cm.exception.code, 404)
        (self.dest / "Studio backup 2026-01-01 0000.zip").write_bytes(b"not a zip")
        with self.assertRaises(backup.BackupError) as cm:
            backup.manifest("Studio backup 2026-01-01 0000.zip")
        self.assertEqual(cm.exception.code, 400)

    def test_same_disk(self):
        self.dest.mkdir()
        self.assertTrue(backup.same_disk(self.dest, self.lib))          # both in the temp folder
        self.assertTrue(backup.same_disk(self.dest / "not" / "yet", self.lib))   # nearest existing parent
        self.assertFalse(backup.same_disk(self.dest, self.tmp / "no library"))

    def test_status(self):
        s = backup.status()
        self.assertEqual((s["on"], s["folder"], s["folder_problem"], s["running"], s["state"]),
                         (True, str(self.dest), None, None, {}))
        self.assertTrue(s["same_disk"])
        self.assertTrue(s["default_folder"].endswith("Studio backups"))
        self.assertIs(s["env_folder"], True)           # STUDIO_BACKUPS overrides the setting: Settings says so
        os.environ.pop("STUDIO_BACKUPS")
        config.refresh()
        self.assertIs(backup.status()["env_folder"], False)

    # ——— settings ———
    def test_config_validates_the_backup_settings(self):
        with self.assertRaisesRegex(ValueError, "outside your library"):
            config.save({"backup_folder": str(self.lib / "x")})
        with self.assertRaisesRegex(ValueError, "Your library is inside that folder"):
            config.save({"backup_folder": str(self.tmp)})
        for relative in ("backups", "E:" if sys.platform == "win32" else "./backups"):
            with self.assertRaisesRegex(ValueError, "^Choose a backup folder by its full path.$"):
                config.save({"backup_folder": relative})
        with self.assertRaisesRegex(ValueError, "backups is on or off"):
            config.save({"backups": "maybe"})
        self.assertFalse(config.save({"backups": "off"})["backups"])
        self.assertFalse(config.BACKUPS_ON)
        self.assertTrue(config.save({"backups": True})["backups"])
        self.assertEqual(config.BACKUPS, self.dest)          # STUDIO_BACKUPS wins
        elsewhere = self.tmp / "elsewhere"
        self.assertEqual(config.save({"backup_folder": f"  {elsewhere}  "})["backup_folder"], str(elsewhere))
        self.assertEqual(config.save({"backup_folder": ""})["backup_folder"], "")
        config.save({"backup_folder": str(elsewhere)})
        os.environ.pop("STUDIO_BACKUPS")
        config.refresh()
        self.assertEqual(config.BACKUPS, elsewhere)          # then the setting
        config.save({"backup_folder": ""})
        self.assertEqual(config.BACKUPS, config.default_backups())      # then the default

    def test_the_default_folder(self):
        home = self.tmp / "home"
        (home / "Documents").mkdir(parents=True)
        with mock.patch.object(config.Path, "home", return_value=home):
            self.assertEqual(config.default_backups(), home / "Documents" / "Studio backups")
            (home / "Documents").rmdir()
            self.assertEqual(config.default_backups(), home / "Studio backups")
        with mock.patch.object(config.Path, "home", return_value=self.lib):     # the library is the home folder
            self.assertEqual(config.default_backups(), self.tmp / "lib backups")
        self.assertFalse((home / "Studio backups").exists())

    # ——— when, and what is kept ———
    def make_fake(self, when: datetime, library=None, readable=True):
        name = f"Studio backup {when:%Y-%m-%d %H%M}.zip"
        path = self.dest / name
        self.dest.mkdir(exist_ok=True)
        if not readable:
            path.write_bytes(b"not a zip")
            return path
        m = {"format": 1, "computer": platform.node(), "library": str(library or self.lib), "created": when.isoformat(),
             "files": 0, "fingerprint": "x"}
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(backup.MANIFEST, json.dumps(m))
        return path

    def test_prune_keeps_24_hours_7_days_4_weeks_12_months(self):
        day = datetime(2025, 10, 9, 20)
        while day <= datetime(2026, 11, 12, 20):
            self.make_fake(day)
            day += timedelta(days=1)
        self.make_fake(datetime(2026, 11, 13, 9))
        self.make_fake(datetime(2025, 1, 1, 0), library=self.tmp / "other")
        (self.dest / "Studio backup 2025-02-02 0000.zip").write_bytes(b"not a zip")
        (self.dest / "notes.txt").write_text("keep", encoding="utf-8")
        total = len(list(self.dest.glob("Studio backup *.zip")))
        deleted = backup.prune(now=datetime(2026, 11, 13, 12, 0))
        kept = sorted(p.name for p in self.dest.glob("Studio backup *.zip"))
        expected = {"2026-11-13 0900", "2026-11-12 2000",
                    "2026-11-11 2000", "2026-11-10 2000", "2026-11-09 2000", "2026-11-08 2000", "2026-11-07 2000",
                    "2026-11-01 2000", "2026-10-25 2000",
                    "2026-10-31 2000", "2026-09-30 2000", "2026-08-31 2000", "2026-07-31 2000", "2026-06-30 2000",
                    "2026-05-31 2000", "2026-04-30 2000", "2026-03-31 2000", "2026-02-28 2000", "2026-01-31 2000",
                    "2025-12-31 2000",
                    "2025-01-01 0000", "2025-02-02 0000"}
        self.assertEqual(kept, sorted(f"Studio backup {x}.zip" for x in expected))
        self.assertTrue((self.dest / "notes.txt").exists())
        self.assertEqual(len(deleted) + len(kept), total)

    def test_prune_turns_a_failed_delete_into_a_warning(self):
        for d in range(2, 12):
            self.make_fake(datetime(2026, 11, d, 20))
        real = os.remove

        def refuse(path, *a, **k):
            if "2026-11-02" in str(path):
                raise PermissionError(13, "denied")
            return real(path, *a, **k)
        warnings = []
        with mock.patch("os.remove", refuse):
            deleted = backup._prune(datetime(2026, 11, 13, 12), warnings)
        self.assertEqual(len(warnings), 1)
        self.assertIn("2026-11-02", warnings[0])
        self.assertNotIn("Studio backup 2026-11-02 2000.zip", deleted)

    def test_run_prunes_after_a_made_backup(self):
        for d in (1, 2, 3):
            self.make_fake(datetime(2026, 11, d, 20))
        for d in (8, 9, 10, 11, 12):
            self.make_fake(datetime(2026, 11, d, 20))
        r = backup.run(now=datetime(2026, 11, 13, 12))
        self.assertEqual(r["result"], "made")
        self.assertFalse((self.dest / "Studio backup 2026-11-02 2000.zip").exists())    # not the newest of anything
        self.assertTrue((self.dest / "Studio backup 2026-11-12 2000.zip").exists())

    def test_due(self):
        t = datetime(2026, 11, 13, 12)
        self.assertTrue(backup.due(t, False, None))
        self.assertFalse(backup.due(t, True, {"when": "2026-11-13T11:30:00"}))
        self.assertTrue(backup.due(t, True, {"when": "2026-11-13T10:30:00"}))
        self.assertFalse(backup.due(t, False, {"when": "2026-11-12T13:00:00"}))
        self.assertTrue(backup.due(t, False, {"when": "2026-11-12T12:00:00"}))

    def test_auto(self):
        config.BACKUPS_ON = False
        self.assertIsNone(backup.auto(True, now=NOW))
        self.assertFalse(self.dest.exists() and list(self.dest.glob("*.zip")))
        config.BACKUPS_ON = True
        self.assertEqual(backup.auto(True, now=NOW)["result"], "made")
        later = NOW + timedelta(hours=2)
        self.assertEqual(backup.auto(True, now=later)["result"], "unchanged")
        (self.poem / "writing-notes.md").write_text("more notes than before", encoding="utf-8")
        self.assertEqual(backup.auto(True, now=later)["result"], "made")
        self.assertIsNone(backup.auto(False, now=later + timedelta(hours=2)))
        self.assertEqual(len(list(self.dest.glob("Studio backup *.zip"))), 2)

    def test_auto_swallows_a_failure_that_is_in_the_state(self):
        config.BACKUPS_ON = True
        shutil.rmtree(self.lib)
        self.assertIsNone(backup.auto(True, now=NOW))
        self.assertIn("last_error", backup.state())

    def test_a_busy_refusal_is_not_a_failure(self):
        self.dest.mkdir()
        (self.dest / backup.LOCK).write_text(json.dumps({"pid": 1, "when": NOW.isoformat()}))
        backup._update_state({"last_error": {"when": "2026-11-12T03:00:00", "message": "The disk is full.",
                                             "reason": "daily"}})
        before = backup.state()["last_error"]
        with self.assertRaises(backup.BackupError) as cm:
            backup.run(now=NOW)
        self.assertEqual(cm.exception.code, 409)
        self.assertEqual(backup.state()["last_error"], before)
        backup._update_state({"last_error": {"when": "2026-11-13T02:00:00", "message": backup.FOLDER_BUSY,
                                             "reason": "start"}})
        config.BACKUPS_ON = True
        self.assertIsNone(backup.brief(now=NOW)["problem"])           # a record of one is ignored too

    def test_scheduler_runs_once_per_process(self):
        with mock.patch.object(backup, "auto") as a:
            self.assertFalse(backup._first_check_done)
            self.assertTrue(backup.start_scheduler(first_delay=0, every=0.05))
            self.assertFalse(backup.start_scheduler())
            self.assertIn("studio-backups", [t.name for t in threading.enumerate()])
            deadline = time.time() + 5
            while a.call_count < 2 and time.time() < deadline:
                time.sleep(0.01)
            backup.stop_scheduler()
        self.assertGreaterEqual(a.call_count, 2)
        self.assertEqual(a.call_args_list[0], mock.call(True))
        self.assertEqual(a.call_args_list[1], mock.call(False))
        self.assertNotIn("studio-backups", [t.name for t in threading.enumerate()])
        self.assertTrue(backup._first_check_done)       # from now on Home may say backups stopped

    def test_scheduler_survives_an_unexpected_error(self):
        with mock.patch.object(backup, "auto", side_effect=RuntimeError("boom")) as a, \
                mock.patch.object(sys, "stderr", io.StringIO()):
            backup.start_scheduler(first_delay=0, every=0.02)
            deadline = time.time() + 5
            while a.call_count < 3 and time.time() < deadline:
                time.sleep(0.01)
            backup.stop_scheduler()
        self.assertGreaterEqual(a.call_count, 3)
        self.assertTrue(backup._first_check_done)       # a check that failed has still finished

    def test_with_backups_off_the_scheduler_has_checked_nothing(self):
        """Turned on later, an old backup isn't a failure until the scheduler has looked."""
        config.BACKUPS_ON = False
        with mock.patch.object(backup, "auto") as a:
            backup.start_scheduler(first_delay=0, every=0.02)
            deadline = time.time() + 5
            while a.call_count < 2 and time.time() < deadline:
                time.sleep(0.01)
            backup.stop_scheduler()
        self.assertGreaterEqual(a.call_count, 2)
        self.assertFalse(backup._first_check_done)

    def test_test_servers_never_back_up(self):
        with temp_studio():
            self.assertNotIn("studio-backups", [t.name for t in threading.enumerate()])

    def test_the_library_changes(self):                                   # Review Focus 5
        self.assertEqual(backup.run(now=NOW)["result"], "made")
        a_name = backup.newest()["name"]
        other = self.tmp / "lib-b"
        _put(other / "Poems/Tide/series.json", "{}")
        os.environ["STUDIO_ART"] = str(other)
        config.refresh()
        self.assertIsNone(backup.newest())
        r = backup.run("start", now=NOW + timedelta(days=40))
        self.assertEqual(r["result"], "made")
        self.assertEqual(backup.manifest(r["name"])["library"], str(other))
        backup.prune(now=NOW + timedelta(days=400))
        self.assertTrue((self.dest / a_name).exists())

    def test_brief(self):
        now = datetime(2026, 11, 13, 12)
        config.BACKUPS_ON = True
        backup._first_check_done = True
        self.assertEqual(backup.brief(now=now), {"problem": None})
        backup._update_state({"last_error": {"when": "2026-11-13T09:00:00", "message": "The disk is full.",
                                             "reason": "daily"}, "last_result": "failed"})
        self.assertEqual(backup.brief(now=now), {"problem": "The disk is full."})
        backup._update_state({"last_ok": {"when": "2026-11-13T10:00:00"}, "last_check": "2026-11-13T10:00:00"})
        self.assertIsNone(backup.brief(now=now)["problem"])
        backup._update_state({"last_ok": {"when": "2026-11-09T10:00:00"}, "last_check": "2026-11-09T10:00:00"},
                             drop=("last_error",))
        self.assertEqual(backup.brief(now=now)["problem"], "Studio hasn't been able to back up since 9 Nov 2026.")
        config.BACKUPS_ON = False
        self.assertIsNone(backup.brief(now=now)["problem"])

    def test_brief_waits_for_the_first_check_after_a_start(self):
        """Studio was closed for days: the last backup is old, but nothing failed. Until this Studio's scheduler has
        made its first check, the age of the last backup says nothing."""
        now = datetime(2026, 11, 13, 12)
        config.BACKUPS_ON = True
        backup._update_state({"last_ok": {"when": "2026-11-09T10:00:00"}, "last_check": "2026-11-09T10:00:00"})
        self.assertIsNone(backup.brief(now=now)["problem"])
        backup._first_check_done = True
        self.assertEqual(backup.brief(now=now)["problem"], "Studio hasn't been able to back up since 9 Nov 2026.")

    def test_brief_says_nothing_while_backups_are_off(self):
        now = datetime(2026, 11, 13, 12)
        backup._first_check_done = True
        backup._update_state({"last_error": {"when": "2026-11-13T09:00:00", "message": "The disk is full.",
                                             "reason": "manual"}, "last_result": "failed"})
        config.BACKUPS_ON = False
        self.assertIsNone(backup.brief(now=now)["problem"])
        config.BACKUPS_ON = True
        self.assertEqual(backup.brief(now=now)["problem"], "The disk is full.")

    def test_dates_in_sentences_are_english_in_any_locale(self):
        """The Home line and a restored copy's name say the month as Studio's English words do, whatever the
        computer's locale (strftime's %b follows it)."""
        import locale
        saved = locale.setlocale(locale.LC_TIME)
        for name in ("nl_NL.UTF-8", "nl_NL", "Dutch_Netherlands.1252", "nl-NL"):
            try:
                locale.setlocale(locale.LC_TIME, name)
                break
            except locale.Error:
                continue
        try:
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            self.assertEqual([backup._suffix(datetime(2026, m, 3, 3, 0)) for m in range(1, 13)],
                             [f" (restored 3 {x} 2026)" for x in months])
            config.BACKUPS_ON, backup._first_check_done = True, True
            backup._update_state({"last_ok": {"when": "2026-10-09T10:00:00"}, "last_check": "2026-10-09T10:00:00"})
            self.assertEqual(backup.brief(now=datetime(2026, 10, 13, 12))["problem"],
                             "Studio hasn't been able to back up since 9 Oct 2026.")
        finally:
            locale.setlocale(locale.LC_TIME, saved)

    def test_brief_endpoint(self):
        with temp_studio() as st:
            self.assertEqual(st.get("/api/backups/brief"), (200, {"problem": None}))

    # ——— endpoints ———
    def test_endpoints(self):
        with temp_studio() as st, mock.patch("subprocess.Popen") as popen:
            _put(st.root / "Sea" / "series.json", "{}")
            code, body = st.get("/api/backups")
            self.assertEqual(code, 200)
            for key in ("backups", "outside", "on", "folder", "default_folder", "folder_problem", "same_disk", "state",
                        "running"):
                self.assertIn(key, body)
            self.assertNotEqual(body["folder"], str(self.dest))      # temp_studio's own backup folder
            code, body = st.post("/api/backups/run")
            self.assertEqual(code, 200)
            self.assertIn("running", body)
            deadline = time.time() + 10
            while time.time() < deadline:
                code, body = st.get("/api/backups")
                if body["running"] is None:
                    break
                time.sleep(0.05)
            self.assertIsNone(body["running"])
            self.assertEqual(len(body["backups"]), 1, body["state"])
            name = body["backups"][0]["name"]
            self.assertEqual(st.post("/api/backups/reveal", {"name": "../x"})[0], 404)
            self.assertEqual(st.post("/api/backups/reveal", {"path": str(self.tmp)})[0], 404)
            popen.assert_not_called()
            self.assertEqual(st.post("/api/backups/reveal", {"name": name}), (200, {"ok": True}))
            self.assertIn(name, " ".join(popen.call_args.args[0]))
            self.assertEqual(st.post("/api/backups/reveal", {})[0], 200)
            req = urllib.request.Request(st.url + "/api/backups/run", data=b"{}", method="POST",
                                         headers={"Origin": "http://evil", "Content-Type": "application/json"})
            self.assertEqual(_status(req), 403)

    def test_run_endpoint_says_when_one_is_running(self):
        with temp_studio() as st:
            self.assertTrue(backup._BUSY.acquire(blocking=False))
            try:
                code, body = st.post("/api/backups/run")
            finally:
                backup._BUSY.release()
            self.assertEqual((code, body["error"]), (409, "A backup is already running."))

    def test_a_folder_that_cannot_be_listed_is_a_sentence(self):
        with temp_studio() as st:
            missing = Path(st.root).parent.parent / "no drive" / "Backups"
            os.environ["STUDIO_BACKUPS"] = str(missing)
            config.refresh()
            code, body = st.get("/api/backups")
            self.assertEqual((code, body["backups"]), (200, []))
            self.assertEqual(body["folder_problem"],
                             f"The backup folder {missing} isn't there. Is the drive connected?")

    def test_reveal_a_restored_folder(self):
        with temp_studio() as st, mock.patch("subprocess.Popen") as popen:
            restored = Path(st.root).parent.parent / "lib restored 2026-11-13 0300"
            restored.mkdir()
            backup._update_state({"restored": [str(restored)]})
            self.assertEqual(st.post("/api/backups/reveal", {"path": str(restored)})[0], 200)
            self.assertIn(str(restored), popen.call_args.args[0])


def _status(req):
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


if __name__ == "__main__":
    unittest.main()
