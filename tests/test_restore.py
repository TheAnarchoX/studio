"""Restoring (spec B14-B16): a poem, book or piece as a copy next to the current one, in place of it (the current one
goes to the trash first), or where it was when it is missing; a whole backup into a new folder next to the library.
Never over what is there, never outside the destination, every member of the zip checked before anything is written.

The library, config, cache and backup folder are temp folders: the fixtures of test_backup."""
import errno
import json
import os
import shutil
import stat
import sys
import threading
import unittest
import urllib.parse
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import tests.test_backup as tb
from studio import backup, books, config
from studio.books import Books
from studio.store import Store, dump_poem
from tests.support import temp_studio

NOW = tb.NOW
_put = tb._put


def _files(root: Path) -> dict:
    """{path below root: bytes} of every file there."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _hidden(folder: Path) -> list:
    """The dot-named entries of a folder (a restore's temporary folder would be one), but the trash."""
    return sorted(n for n in os.listdir(folder) if n.startswith(".") and n != ".trash")


class RestoreTest(unittest.TestCase):
    library = tb.BackupTest.setUp           # the library of test_backup, then a backup of it
    tearDown = tb.BackupTest.tearDown

    def setUp(self):
        self.library()
        lib = self.lib
        _put(lib / "Poems/Sea/README.md", "# Sea\n")
        _put(lib / "Poems/Sea/stamps/wave.json", "{}")
        _put(lib / "Poems/Sea/Tide/poem.json", json.dumps({"title": "Tide", "slug": "tide"}))
        self.book = lib / "Books/Field Notes"
        _put(self.book / "book.json", json.dumps({"title": "Field Notes", "contents": [
            {"auto": "title-page"}, {"file": "one.md", "kind": "chapter", "form": "prose", "status": "draft"},
            {"file": "two.md", "kind": "chapter", "form": "poem", "status": "revised"},
            {"file": "thanks.md", "kind": "acknowledgements", "form": "prose", "status": "final"}, {"auto": "index"}]}))
        _put(self.book / "manuscript/two.md", "# Two\n\nThe second piece.\n")
        _put(self.book / "manuscript/thanks.md", "# Thanks\n\nTo the harbour.\n")
        self.name = backup.run(now=NOW)["name"]

    def refused(self, *args):
        with self.assertRaises(backup.BackupError) as cm:
            backup.restore_item(*args)
        return cm.exception.code, str(cm.exception)

    def contents(self):
        meta = json.loads((self.book / "book.json").read_text(encoding="utf-8"))
        return [e.get("file") or e.get("auto") for e in meta["contents"]]

    # ——— what a backup holds ———
    def test_items_say_what_exists_now(self):
        it = backup.items(self.name)
        self.assertEqual((it["name"], it["when"], it["library"], it["same_library"]),
                         (self.name, "2026-11-13T03:00:00", str(self.lib), True))
        self.assertEqual(it["poems"], [{"id": "Sea/Harbour", "title": "Harbour", "series": "Sea", "exists": True},
                                       {"id": "Sea/Tide", "title": "Tide", "series": "Sea", "exists": True}])
        self.assertEqual(it["books"], [{"id": "Field Notes", "title": "Field Notes", "exists": True, "pieces": [
            {"file": "one.md", "title": "One", "kind": "chapter", "form": "prose", "exists": True},
            {"file": "two.md", "title": "Two", "kind": "chapter", "form": "poem", "exists": True},
            {"file": "thanks.md", "title": "Thanks", "kind": "acknowledgements", "form": "prose", "exists": True}]}])
        Store(config.POEMS).delete_poem("Sea/Harbour")
        Books(config.BOOKS).delete_piece("Field Notes", "two.md")
        (self.book / "manuscript/thanks.md").unlink()               # in the book, not on disk
        it = backup.items(self.name)
        self.assertEqual([p["exists"] for p in it["poems"]], [False, True])
        self.assertTrue(it["books"][0]["exists"])
        self.assertEqual([p["exists"] for p in it["books"][0]["pieces"]], [True, False, False])
        Books(config.BOOKS).delete_book("Field Notes")
        it = backup.items(self.name)
        self.assertFalse(it["books"][0]["exists"])
        self.assertEqual([p["exists"] for p in it["books"][0]["pieces"]], [False, False, False])
        with self.assertRaises(backup.BackupError) as cm:
            backup.items("Studio backup 2026-11-13 0301.zip")
        self.assertEqual(cm.exception.code, 404)

    # ——— poems ———
    def test_copy_of_a_poem(self):
        notes = "notes written since, ’s nachts\n"
        (self.poem / "writing-notes.md").write_text(notes, encoding="utf-8")
        r = backup.restore_item(self.name, "poem", "Sea/Harbour", "copy")
        copy = self.lib / "Poems/Sea/Harbour (restored 13 Nov 2026)"
        self.assertEqual(r, {"kind": "poem", "title": "Harbour (restored 13 Nov 2026)",
                             "href": "#/poem/Sea%2FHarbour%20%28restored%2013%20Nov%202026%29", "path": str(copy),
                             "trash": None})
        self.assertEqual(json.loads((copy / "poem.json").read_text("utf-8"))["title"], "Harbour (restored 13 Nov 2026)")
        self.assertEqual((copy / "poem.json").read_text("utf-8"),        # a slug of its own: lookups by slug find one
                         dump_poem({"title": "Harbour (restored 13 Nov 2026)", "slug": "harbour-restored-13-nov-2026",
                                    "status": "draft"}))
        self.assertEqual(Store(config.POEMS).resolve("harbour"), self.poem)
        self.assertEqual(Store(config.POEMS).resolve("harbour-restored-13-nov-2026"), copy)
        self.assertFalse((copy / ".studio" / "days.json").exists())          # the log would count those days twice
        self.assertEqual(sorted(_files(copy)), ["designs/night.json", "drafts/2026-11-12T0310.md", "my-photo.png",
                                                "poem.json", "writing-notes.md"])
        self.assertEqual((copy / "writing-notes.md").read_text("utf-8"), "notes, ’s nachts\n")
        self.assertEqual((self.poem / "writing-notes.md").read_text("utf-8"), notes)      # the current one, unchanged
        self.assertEqual(Store(config.POEMS).resolve("Sea/Harbour (restored 13 Nov 2026)"), copy)
        self.assertEqual(backup.restore_item(self.name, "poem", "Sea/Harbour", "copy")["path"], str(copy) + " 2")
        self.assertEqual(_hidden(self.lib / "Poems/Sea"), [])

    def test_replace_a_poem_trashes_the_current_one_and_keeps_its_log(self):
        days = '{"2026-11-12": 4, "2026-11-13": 9}'
        _put(self.poem / ".studio/days.json", days)
        _put(self.poem / "writing-notes.md", "current notes\n")
        _put(self.poem / "harbour-45-2-tide.png", "render 2")
        renders = ["Carousel 4x5/Signed/harbour-45-1-flare.png", "harbour-45-2-tide.png", "harbour.html",
                   "harbour-carousel-preview.png", "Design renders/night/x.png", "designs/.trash/old.json"]
        before = _files(self.poem)
        r = backup.restore_item(self.name, "poem", "Sea/Harbour", "replace")
        self.assertEqual((r["kind"], r["title"], r["href"], r["path"]),
                         ("poem", "Harbour", "#/poem/Sea%2FHarbour", str(self.poem)))
        self.assertEqual((self.poem / "writing-notes.md").read_text("utf-8"), "notes, ’s nachts\n")    # the backup's
        self.assertEqual((self.poem / ".studio/days.json").read_text("utf-8"), days)        # the current log
        for rel in renders:                                                                  # carried over
            self.assertEqual((self.poem / rel).read_bytes(), before[rel], rel)
        self.assertFalse((self.poem / ".poem.json.12.34.tmp").exists())
        trash = Path(r["trash"])
        self.assertEqual(trash.parent, self.lib / "Poems/.trash/Sea")
        self.assertTrue(trash.name.startswith("Harbour "))
        self.assertEqual((trash / "writing-notes.md").read_text("utf-8"), "current notes\n")
        self.assertEqual((trash / ".studio/days.json").read_text("utf-8"), days)        # copied, not moved
        self.assertFalse((trash / "harbour.html").exists())                              # moved, not copied
        self.assertTrue((trash / ".poem.json.12.34.tmp").exists())                       # a temp file stays behind
        self.assertEqual(_hidden(self.lib / "Poems/Sea"), [])

    def test_a_replace_keeps_the_slug_its_renders_are_named_by(self):
        f = self.poem / "poem.json"
        f.write_text(json.dumps({"title": "Harbour", "slug": "early", "status": "draft"}), encoding="utf-8")
        name = backup.run(now=NOW + timedelta(hours=1))["name"]
        f.write_text(json.dumps({"title": "Harbour", "slug": "harbour", "status": "draft"}), encoding="utf-8")
        backup.restore_item(name, "poem", "Sea/Harbour", "replace")
        self.assertEqual(json.loads(f.read_text("utf-8"))["slug"], "harbour")
        self.assertTrue((self.poem / "harbour.html").is_file())

    def test_restore_a_missing_poem_and_its_series(self):
        store = Store(config.POEMS)
        store.delete_poem("Sea/Harbour")
        r = backup.restore_item(self.name, "poem", "Sea/Harbour", "restore")
        self.assertEqual(r, {"kind": "poem", "title": "Harbour", "href": "#/poem/Sea%2FHarbour", "path": str(self.poem),
                             "trash": None})
        self.assertEqual(sorted(_files(self.poem)), [".studio/days.json", "designs/night.json",
                                                     "drafts/2026-11-12T0310.md", "my-photo.png", "poem.json",
                                                     "writing-notes.md"])
        self.assertEqual((self.poem / ".studio/days.json").read_text("utf-8"), '{"2026-11-12": 4}')     # the backup's
        os.replace(self.lib / "Poems/Sea", self.tmp / "renamed outside Studio")
        r = backup.restore_item(self.name, "poem", "Sea/Harbour", "restore")
        sea = self.lib / "Poems/Sea"
        self.assertEqual(r["path"], str(self.poem))
        self.assertEqual(sorted(_files(sea)), [
            "Harbour/.studio/days.json", "Harbour/designs/night.json", "Harbour/drafts/2026-11-12T0310.md",
            "Harbour/my-photo.png", "Harbour/poem.json", "Harbour/writing-notes.md", "README.md", "_kit/build.py",
            "series.json", "stamps/wave.json"])
        self.assertFalse((sea / "Tide").exists())                       # never other poems
        self.assertEqual([d.name for d in store.series_dirs()], ["Sea"])
        self.assertEqual(store.resolve("Sea/Harbour"), self.poem)
        self.assertEqual(_hidden(self.lib / "Poems"), [])

    def test_a_folder_in_the_way_is_never_restored_over(self):
        (self.poem / "poem.json").unlink()                  # Studio doesn't see the poem, but its folder is there
        before = _files(self.poem)
        code, message = self.refused(self.name, "poem", "Sea/Harbour", "restore")
        self.assertEqual(code, 409)
        self.assertIn(str(self.poem), message)
        self.assertEqual(_files(self.poem), before)
        self.assertEqual(_hidden(self.lib / "Poems/Sea"), [])

    # ——— books and pieces ———
    def test_copy_replace_and_restore_a_piece(self):
        b = Books(config.BOOKS)
        one = {"book": "Field Notes", "file": "one.md"}
        r = backup.restore_item(self.name, "piece", one, "copy")
        new = self.book / "manuscript/one restored 2026-11-13.md"
        self.assertEqual(r, {"kind": "piece", "title": "One (restored 13 Nov 2026)",
                             "href": "#/book/Field%20Notes/write/one%20restored%202026-11-13.md", "path": str(new),
                             "trash": None})
        self.assertEqual(new.read_text("utf-8"), "# One (restored 13 Nov 2026)\n\nThe first piece.\n")
        meta = json.loads((self.book / "book.json").read_text("utf-8"))
        self.assertEqual(meta["contents"][2], {"file": "one restored 2026-11-13.md", "kind": "chapter",
                                               "form": "prose", "status": "draft"})
        self.assertEqual((self.book / "book.json").read_text("utf-8"), books._dump(meta))
        self.assertEqual(backup.restore_item(self.name, "piece", one, "copy")["path"],
                         str(self.book / "manuscript/one restored 2026-11-13 2.md"))
        self.assertEqual(self.contents(), ["title-page", "one.md", "one restored 2026-11-13 2.md",
                                           "one restored 2026-11-13.md", "two.md", "thanks.md", "index"])
        self.assertEqual(b.piece("Field Notes", "one restored 2026-11-13.md")["title"], "One (restored 13 Nov 2026)")

        _put(self.book / "manuscript/one.md", "# One\n\nChanged since.\n")
        before = self.contents()
        r = backup.restore_item(self.name, "piece", one, "replace")
        self.assertEqual((r["title"], r["href"], r["path"]),
                         ("One", "#/book/Field%20Notes/write/one.md", str(self.book / "manuscript/one.md")))
        self.assertEqual((self.book / "manuscript/one.md").read_text("utf-8"), "# One\n\nThe first piece.\n")
        trash = Path(r["trash"])
        self.assertEqual(trash.parent, self.lib / "Books/.trash")
        self.assertTrue(trash.name.startswith("Field Notes one ") and trash.suffix == ".md", trash.name)
        self.assertEqual(trash.read_text("utf-8"), "# One\n\nChanged since.\n")
        self.assertEqual(self.contents(), before)                        # its entry stays

        two = {"book": "Field Notes", "file": "two.md"}
        b.delete_piece("Field Notes", "two.md")
        r = backup.restore_item(self.name, "piece", two, "restore")
        self.assertEqual((r["title"], r["path"], r["trash"]), ("Two", str(self.book / "manuscript/two.md"), None))
        self.assertEqual((self.book / "manuscript/two.md").read_text("utf-8"), "# Two\n\nThe second piece.\n")
        self.assertEqual(self.contents(), ["title-page", "one.md", "two.md", "one restored 2026-11-13 2.md",
                                           "one restored 2026-11-13.md", "thanks.md", "index"])  # after one.md again
        entry = json.loads((self.book / "book.json").read_text("utf-8"))["contents"][2]
        self.assertEqual(entry, {"file": "two.md", "kind": "chapter", "form": "poem", "status": "revised"})

        b.delete_piece("Field Notes", "one.md")
        backup.restore_item(self.name, "piece", one, "restore")          # the first piece: after the title page again
        self.assertEqual(self.contents(), ["title-page", "one.md", "two.md", "one restored 2026-11-13 2.md",
                                           "one restored 2026-11-13.md", "thanks.md", "index"])
        self.assertEqual((self.book / "manuscript/one.md").read_text("utf-8"), "# One\n\nThe first piece.\n")

        b.delete_piece("Field Notes", "one.md")
        b.delete_piece("Field Notes", "two.md")
        backup.restore_item(self.name, "piece", two, "restore")          # one.md is gone: before the back matter
        self.assertEqual(self.contents(), ["title-page", "one restored 2026-11-13 2.md", "one restored 2026-11-13.md",
                                           "two.md", "thanks.md", "index"])

        (self.book / "book.json").write_text(json.dumps({"title": "Field Notes", "contents": [
            {"auto": "title-page"}, {"file": "one restored 2026-11-13.md", "kind": "chapter"}]}), encoding="utf-8")
        (self.book / "manuscript/two.md").unlink()
        backup.restore_item(self.name, "piece", two, "restore")          # no back matter: at the end
        self.assertEqual(self.contents(), ["title-page", "one restored 2026-11-13.md", "two.md"])

        (self.book / "manuscript/two.md").unlink()                     # in the book, not on disk: the file only
        self.assertFalse(backup.items(self.name)["books"][0]["pieces"][1]["exists"])
        backup.restore_item(self.name, "piece", two, "restore")
        self.assertEqual(self.contents(), ["title-page", "one restored 2026-11-13.md", "two.md"])
        self.assertEqual((self.book / "manuscript/two.md").read_text("utf-8"), "# Two\n\nThe second piece.\n")

        thanks = self.book / "manuscript/thanks.md"                     # on disk, not in the book: never written over
        thanks.write_text("# Thanks\n\nWritten since.\n", encoding="utf-8")
        code, message = self.refused(self.name, "piece", {"book": "Field Notes", "file": "thanks.md"}, "restore")
        self.assertEqual((code, message), (409, "The manuscript folder of “Field Notes” has a file thanks.md that "
                                                "isn't in the book. Move that file away, then restore it."))
        self.assertEqual(thanks.read_text("utf-8"), "# Thanks\n\nWritten since.\n")
        self.assertEqual(_hidden(self.book / "manuscript"), [])

    def test_a_restored_piece_goes_where_it_was(self):
        at = backup._position
        a, b, toc, index = {"file": "a.md"}, {"file": "b.md"}, {"auto": "toc"}, {"auto": "index"}
        afterword = {"file": "c.md", "kind": "afterword"}
        self.assertEqual(at([toc, b, index], [a, toc, b], "a.md"), 0)              # nothing preceded it: first
        self.assertEqual(at([b, toc, index], [toc, a, b], "a.md"), 2)              # after its auto page
        self.assertEqual(at([toc, b, index], [b, a], "a.md"), 2)                   # after its piece
        self.assertEqual(at([b, afterword, index], [toc, a], "a.md"), 1)           # it is gone: before back matter
        self.assertEqual(at([b], [{"file": "x.md"}, a], "a.md"), 1)                # and with no back matter: at the end
        self.assertEqual(at([b, index], [b], "a.md"), 1)                           # not in the backup's book.json

    def test_a_copied_piece_keeps_its_line_endings(self):
        s = " (restored 13 Nov 2026)"
        self.assertEqual(backup._retitle_piece(b"# One \r\n\r\nText.\r\n", s),
                         b"# One (restored 13 Nov 2026)\r\n\r\nText.\r\n")
        self.assertEqual(backup._retitle_piece("\ufeff# One\nText.".encode("utf-8"), s),
                         "\ufeff# One (restored 13 Nov 2026)\nText.".encode("utf-8"))
        self.assertEqual(backup._retitle_piece(b"Untitled text.\n", s), b"Untitled text.\n")
        self.assertEqual(backup._retitle_piece(b"# Caf\xe9\n", s), b"# Caf\xe9\n")       # not UTF-8: as it was

    def test_restore_a_missing_book_and_refuse_a_piece_without_its_book(self):
        trashed = Books(config.BOOKS).delete_book("Field Notes")
        self.assertEqual(self.refused(self.name, "piece", {"book": "Field Notes", "file": "one.md"}, "restore"),
                         (409, "Restore the book “Field Notes” first."))
        self.assertFalse(self.book.exists())
        r = backup.restore_item(self.name, "book", "Field Notes", "restore")
        self.assertEqual(r, {"kind": "book", "title": "Field Notes", "href": "#/book/Field%20Notes",
                             "path": str(self.book), "trash": None})
        self.assertEqual(_files(self.book), _files(trashed))             # nothing changed since the backup
        self.assertEqual((self.book / ".studio/days.json").read_text("utf-8"), '{"2026-11-12": 40}')
        self.assertEqual(Books(config.BOOKS).read("Field Notes")["title"], "Field Notes")
        self.assertEqual(_hidden(self.lib / "Books"), [])

    def test_copy_and_replace_a_book(self):
        days = '{"2026-11-12": 40, "2026-11-13": 12}'
        _put(self.book / ".studio/days.json", days)
        _put(self.book / "manuscript/one.md", "# One\n\nChanged since.\n")
        r = backup.restore_item(self.name, "book", "Field Notes", "copy")
        copy = self.lib / "Books/Field Notes (restored 13 Nov 2026)"
        self.assertEqual(r, {"kind": "book", "title": "Field Notes (restored 13 Nov 2026)",
                             "href": "#/book/Field%20Notes%20%28restored%2013%20Nov%202026%29", "path": str(copy),
                             "trash": None})
        meta = json.loads((copy / "book.json").read_text("utf-8"))
        self.assertEqual(meta["title"], "Field Notes (restored 13 Nov 2026)")
        self.assertEqual((copy / "book.json").read_text("utf-8"), books._dump(meta))
        self.assertFalse((copy / ".studio/days.json").exists())
        self.assertEqual((copy / "manuscript/one.md").read_text("utf-8"), "# One\n\nThe first piece.\n")
        self.assertEqual(Books(config.BOOKS).read(copy.name)["title"], "Field Notes (restored 13 Nov 2026)")
        self.assertEqual(backup.restore_item(self.name, "book", "Field Notes", "copy")["path"], str(copy) + " 2")

        r = backup.restore_item(self.name, "book", "Field Notes", "replace")
        self.assertEqual((r["title"], r["href"], r["path"]), ("Field Notes", "#/book/Field%20Notes", str(self.book)))
        self.assertEqual((self.book / "manuscript/one.md").read_text("utf-8"), "# One\n\nThe first piece.\n")
        self.assertEqual((self.book / ".studio/days.json").read_text("utf-8"), days)       # the current log
        trash = Path(r["trash"])
        self.assertEqual(trash.parent, self.lib / "Books/.trash")
        self.assertEqual((trash / "manuscript/one.md").read_text("utf-8"), "# One\n\nChanged since.\n")
        self.assertEqual(_hidden(self.lib / "Books"), [])

    # ——— refusals and failures ———
    def test_modes_need_the_right_state(self):
        self.assertEqual(self.refused(self.name, "poem", "Sea/Harbour", "restore"),
                         (409, "“Harbour” is in the library now. Restore a copy or replace it."))
        self.assertEqual(self.refused(self.name, "book", "Field Notes", "restore")[0], 409)
        Store(config.POEMS).delete_poem("Sea/Harbour")
        for mode in ("copy", "replace"):
            self.assertEqual(self.refused(self.name, "poem", "Sea/Harbour", mode),
                             (409, "“Harbour” isn't in the library now. Restore it instead."))
        Books(config.BOOKS).delete_piece("Field Notes", "two.md")
        self.assertEqual(self.refused(self.name, "piece", {"book": "Field Notes", "file": "two.md"}, "copy"),
                         (409, "“Two” isn't in the library now. Restore it instead."))
        self.assertEqual(self.refused(self.name, "poem", "Sea/Nothing", "restore")[0], 404)
        self.assertEqual(self.refused(self.name, "piece", {"book": "Field Notes", "file": "nine.md"}, "restore")[0],
                         404)
        self.assertEqual(self.refused(self.name, "piece", "Field Notes/two.md", "restore")[0], 400)
        self.assertEqual(self.refused("Studio backup 2026-11-13 0301.zip", "poem", "Sea/Harbour", "restore")[0], 404)
        self.assertEqual(self.refused(self.name, "series", "Sea", "restore")[0], 400)
        self.assertEqual(self.refused(self.name, "poem", "Sea/Harbour", "overwrite")[0], 400)
        self.assertFalse(self.poem.exists())
        with mock.patch.object(backup, "RESTORE_WAIT", 0.05):            # a backup that runs on
            self.assertTrue(backup._BUSY.acquire(blocking=False))
            try:
                self.assertEqual(self.refused(self.name, "poem", "Sea/Harbour", "restore"),
                                 (409, "A backup is running. Try again in a minute."))
            finally:
                backup._BUSY.release()
        self.assertTrue(backup._BUSY.acquire(blocking=False))             # one that ends within the wait
        threading.Timer(0.2, backup._BUSY.release).start()
        self.assertEqual(backup.restore_item(self.name, "poem", "Sea/Harbour", "restore")["path"], str(self.poem))
        self.assertTrue(backup._BUSY.acquire(blocking=False))             # released again
        backup._BUSY.release()
        self.assertNotIn("last_error", backup.state())                   # a restore is never a backup failure

    def test_a_library_that_is_not_there_gets_nothing(self):
        gone = self.tmp / "unplugged" / "Library"
        os.environ["STUDIO_ART"] = str(gone)
        config.refresh()
        self.assertEqual(self.refused(self.name, "poem", "Sea/Harbour", "restore"),
                         (400, f"Your library {gone} isn't there. Is the drive connected?"))
        self.assertFalse((self.tmp / "unplugged").exists())

    def test_a_failed_replace_puts_the_current_one_back(self):
        _put(self.poem / "writing-notes.md", "current notes\n")
        _put(self.poem / ".studio/days.json", '{"2026-11-13": 9}')
        before, book_before = _files(self.poem), _files(self.book)
        real = os.rename

        def failing(src, dst, *a, **k):
            if str(src).endswith(".restoring"):
                raise OSError(errno.EIO, "Input/output error")
            return real(src, dst, *a, **k)
        with mock.patch("os.rename", failing):
            self.assertEqual(self.refused(self.name, "poem", "Sea/Harbour", "replace"),
                             (400, "The restore didn't finish: input/output error. Your library is as it was."))
            self.assertEqual(self.refused(self.name, "book", "Field Notes", "replace")[0], 400)
        self.assertEqual(_files(self.poem), before)                 # its text, log, renders and preview page: back
        self.assertEqual(os.listdir(self.lib / "Poems/.trash/Sea"), ["Old"])
        self.assertEqual(_hidden(self.lib / "Poems/Sea"), [])
        self.assertEqual(_files(self.book), book_before)
        self.assertEqual(os.listdir(self.lib / "Books/.trash"), [])
        self.assertEqual(_hidden(self.lib / "Books"), [])

        held = []

        def held_a_moment(src, dst, *a, **k):                       # a virus scanner looks at the new files
            if str(src).endswith(".restoring") and len(held) < 2:
                held.append(src)
                raise PermissionError(13, "Access is denied")
            return real(src, dst, *a, **k)
        with mock.patch("os.rename", held_a_moment), mock.patch.object(backup, "MOVE_WAIT", 0):
            backup.restore_item(self.name, "poem", "Sea/Harbour", "replace")
        self.assertEqual(len(held), 2)
        self.assertEqual((self.poem / "writing-notes.md").read_text("utf-8"), "notes, ’s nachts\n")

    def test_unsafe_members_are_refused(self):
        m = backup.manifest(self.name)
        link = zipfile.ZipInfo("Poems/Sea/Harbour/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        bad = ["Poems/Sea/Harbour/../../evil.txt", "C:/x", link, "/evil.txt", "Poems/Sea/Harbour//x.md",
               "Poems/Sea/Harbour/a|b.md"]
        if sys.platform == "win32":
            bad.append("Poems/Sea/Harbour/nul")                      # a device, not a file
        lib_before, around = _files(self.lib), sorted(os.listdir(self.tmp))
        for i, member in enumerate(bad):
            name = f"Studio backup 2026-11-14 00{i:02d}.zip"
            with zipfile.ZipFile(self.dest / name, "w") as z:
                z.writestr("Poems/Sea/Harbour/poem.json", json.dumps({"title": "Harbour"}))
                z.writestr(member, "elsewhere")
                z.writestr(backup.MANIFEST, json.dumps(m))
            shown = member.filename if isinstance(member, zipfile.ZipInfo) else member
            if shown.endswith("a|b.md"):                            # a backslash: zipfile won't write one
                raw = (self.dest / name).read_bytes().replace(b"a|b.md", b"a\\b.md")
                (self.dest / name).write_bytes(raw)
                shown = shown.replace("|", "\\")
            expected = f"This backup holds a file Studio won't unpack: {shown}."
            for attempt in (lambda: backup.restore_all(name),
                            lambda: backup.restore_item(name, "poem", "Sea/Harbour", "copy")):
                with self.assertRaises(backup.BackupError) as cm:
                    attempt()
                self.assertEqual(str(cm.exception), expected)
        self.assertEqual(_files(self.lib), lib_before)
        self.assertEqual(sorted(os.listdir(self.tmp)), around)
        self.assertFalse(any(p.name == "evil.txt" for p in self.tmp.rglob("*")))

    # ——— the whole backup ———
    def test_restore_all(self):
        p = backup.restore_all(self.name)
        self.assertEqual(p.name, f"{self.lib.name} restored 2026-11-13 0300")
        self.assertEqual(p.parent, self.lib.parent)
        self.assertTrue((p / "Poems/Sea/Harbour/poem.json").exists())
        self.assertFalse((p / "studio-backup.json").exists())
        with zipfile.ZipFile(self.dest / self.name) as z:
            expected = {n: z.read(n) for n in z.namelist() if n != backup.MANIFEST}
            when = z.getinfo("Poems/Sea/Harbour/my-photo.png").date_time
        self.assertEqual(_files(p), expected)
        mtime = (p / "Poems/Sea/Harbour/my-photo.png").stat().st_mtime
        self.assertEqual(datetime.fromtimestamp(mtime).timetuple()[:6], when)        # the time it had
        self.assertEqual(backup.state()["restored"][-1]["path"], str(p))
        self.assertEqual(backup.restore_all(self.name).name, f"{self.lib.name} restored 2026-11-13 0300 2")
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".")], [])
        backup._update_state({"restored": [{"path": f"x{i}"} for i in range(25)]})
        q = backup.restore_all(self.name)
        restored = backup.state()["restored"]
        self.assertEqual((len(restored), restored[0]["path"], restored[-1]["path"]), (20, "x6", str(q)))
        self.assertNotIn("last_error", backup.state())

    def test_accented_names_restore_exactly(self):                        # Review Focus 1
        series = self.lib / "Poems/Zee – één"
        folder = series / "Café, ’s nachts"
        _put(series / "series.json", "{}")
        _put(folder / "poem.json", json.dumps({"title": "Café, ’s nachts", "slug": "cafe-s-nachts"}))
        _put(folder / "café-notes.md", "één")
        name = backup.run(now=NOW + timedelta(hours=1))["name"]
        pid = "Zee – één/Café, ’s nachts"
        r = backup.restore_item(name, "poem", pid, "copy")
        copy = series / "Café, ’s nachts (restored 13 Nov 2026)"
        self.assertEqual(r["path"], str(copy))
        self.assertEqual(urllib.parse.unquote(r["href"].removeprefix("#/poem/")), f"{pid} (restored 13 Nov 2026)")
        self.assertEqual(r["href"], "#/poem/" + urllib.parse.quote(f"{pid} (restored 13 Nov 2026)", safe=""))
        self.assertEqual(json.loads((copy / "poem.json").read_text("utf-8"))["title"],
                         "Café, ’s nachts (restored 13 Nov 2026)")
        self.assertEqual((copy / "café-notes.md").read_text("utf-8"), "één")
        Store(config.POEMS).delete_poem(pid)
        self.assertEqual(backup.restore_item(name, "poem", pid, "restore")["path"], str(folder))
        self.assertEqual(sorted(os.listdir(series)),
                         sorted(["series.json", "Café, ’s nachts", "Café, ’s nachts (restored 13 Nov 2026)"]))
        self.assertEqual(sorted(os.listdir(folder)), ["café-notes.md", "poem.json"])

        other = self.tmp / "Gedichten – één"                              # a library named with them
        _put(other / "Poems/Zee – één/series.json", "{}")
        _put(other / "Poems/Zee – één/Café, ’s nachts/poem.json", json.dumps({"title": "Café, ’s nachts"}))
        os.environ["STUDIO_ART"] = str(other)
        config.refresh()
        name = backup.run(now=NOW + timedelta(hours=2))["name"]
        p = backup.restore_all(name)
        self.assertIn("Gedichten – één restored 2026-11-13 0500", os.listdir(self.tmp))
        self.assertEqual(p, self.tmp / "Gedichten – één restored 2026-11-13 0500")
        self.assertEqual(sorted(os.listdir(p / "Poems/Zee – één")), ["Café, ’s nachts", "series.json"])

    # ——— endpoints ———
    def test_restore_endpoints(self):
        with temp_studio() as st, mock.patch("subprocess.Popen"):
            made = Path(st.root).parent.parent                      # temp_studio's own temp folder
            self.addCleanup(shutil.rmtree, made, True)
            _put(st.root / "Sea/series.json", "{}")
            _put(st.root / "Sea/Harbour/poem.json", json.dumps({"title": "Harbour", "slug": "harbour"}))
            name = backup.run(now=NOW)["name"]
            code, body = st.get("/api/backups/items?name=" + urllib.parse.quote(name))
            self.assertEqual(code, 200)
            self.assertEqual(body["poems"],
                             [{"id": "Sea/Harbour", "title": "Harbour", "series": "Sea", "exists": True}])
            ask = {"name": name, "kind": "poem", "ref": "Sea/Harbour", "mode": "copy"}
            code, body = st.post("/api/backups/restore", ask)
            self.assertEqual((code, body["href"], body["trash"]),
                             (200, "#/poem/Sea%2FHarbour%20%28restored%2013%20Nov%202026%29", None))
            self.assertTrue(Path(body["path"]).is_dir())
            code, body = st.post("/api/backups/restore", {**ask, "mode": "restore"})
            self.assertEqual((code, body["error"]),
                             (409, "“Harbour” is in the library now. Restore a copy or replace it."))
            code, body = st.post("/api/backups/restore", {"name": name, "all": True})
            self.assertEqual(code, 200)
            self.assertTrue(Path(body["path"]).is_dir())
            self.assertEqual(st.post("/api/backups/reveal", {"path": body["path"]})[0], 200)
            self.assertEqual(st.get("/api/backups/items?name=nothing.zip")[0], 404)
            with mock.patch.object(backup, "RESTORE_WAIT", 0.05):
                self.assertTrue(backup._BUSY.acquire(blocking=False))
                try:
                    code, body = st.post("/api/backups/restore", ask)
                finally:
                    backup._BUSY.release()
            self.assertEqual((code, body["error"]), (409, "A backup is running. Try again in a minute."))


if __name__ == "__main__":
    unittest.main()
