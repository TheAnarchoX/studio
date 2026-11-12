"""The app window's languages: WebView2 starts with --accept-lang holding the books' languages (the most recently written
first: WebView2 checks spelling in the first of them), the OS user's UI languages and English. Nothing in the library
can stop the window from opening, and a restart by Studio itself starts from the user's own arguments again."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio import books, config, desktop

ARGS = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"


class AcceptLanguagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-desktop-"))
        self.books = self.tmp / "Books"
        self.books.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def book(self, name, language, when, **more):
        d = self.books / name
        (d / "manuscript").mkdir(parents=True)
        (d / "book.json").write_text(json.dumps({"title": name, "language": language, **more}), encoding="utf-8")
        for p in (d / "book.json", d / "manuscript"):
            os.utime(p, (when, when))
        return d

    def test_books_first_newest_first_then_the_os_then_english(self):
        self.book("Oud", "nl", 1_700_000_000)
        self.book("Nieuw", "pt-BR", 1_700_000_500)
        self.book("Engels", "en", 1_699_000_000)
        self.book("Vreemd", "x<y>", 1_700_000_900)          # not a language tag: left out
        broken = self.books / "Kapot"
        broken.mkdir()
        (broken / "book.json").write_text("not json", encoding="utf-8")
        self.book(".trash", "fr", 1_700_000_900)            # the trash is no book
        self.assertEqual(desktop.accept_languages(self.books, ui=["en-US", "NL"]), "pt-BR,nl,en,en-US")

    def test_no_books_no_os_languages(self):
        self.assertEqual(desktop.accept_languages(self.tmp / "missing", ui=[]), "en")

    def test_arguments_keep_what_is_there(self):
        self.assertEqual(desktop.webview2_arguments("", "nl,en"), "--accept-lang=nl,en")
        self.assertEqual(desktop.webview2_arguments("--remote-debugging-port=9351", "nl,en"),
                         "--remote-debugging-port=9351 --accept-lang=nl,en")
        self.assertEqual(desktop.webview2_arguments("--accept-lang=de", "nl,en"), "--accept-lang=de")

    # ——— a broken library never stops the window ———
    def test_a_book_json_nested_too_deep_is_left_out(self):
        d = self.books / "Diep"
        d.mkdir()
        (d / "book.json").write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")     # RecursionError in json
        self.book("Gewoon", "nl", 1_700_000_000)
        self.assertEqual(desktop.accept_languages(self.books, ui=[]), "nl,en")

    def test_language_tags_are_capped_as_books_caps_them(self):
        self.book("Lang", "nl-" + "-".join(["abcdefgh"] * 5000), 1_700_000_900)
        self.book("Zeven", "nl-aa-bb-cc-dd-ee-ff-gg", 1_700_000_800)     # seven subtags
        self.book("Goed", "pt-BR", 1_700_000_000)
        self.assertEqual(desktop.accept_languages(self.books, ui=[]), "pt-BR,en")
        self.assertEqual(desktop.LANGUAGE_TAG.pattern, books.LANGUAGE.pattern)
        self.assertIsNone(books.LANGUAGE.fullmatch("nl-aa-bb-cc-dd-ee-ff-gg"))
        self.assertIsNone(books.LANGUAGE.fullmatch("en-" + "a" * 8 + "-bbbbbbbb-cccccccc-dddddddd"))      # 39 characters
        self.assertIsNotNone(books.LANGUAGE.fullmatch("zh-Hant-TW"))

    def test_an_unreadable_books_folder_gives_english(self):
        with mock.patch.object(Path, "iterdir", side_effect=PermissionError("no")):
            self.assertEqual(desktop.accept_languages(self.books, ui=[]), "en")

    def test_the_environment_refusing_the_value_is_no_failure(self):
        class Refusing(dict):
            def __setitem__(self, k, v):
                if k == ARGS:
                    raise ValueError("the environment variable is too long")
                super().__setitem__(k, v)
        env = Refusing({ARGS: "--remote-debugging-port=9351"})
        desktop.set_webview2_languages(env, self.books, ui=[])          # no exception
        self.assertEqual(env[ARGS], "--remote-debugging-port=9351")
        with mock.patch.object(desktop, "accept_languages", side_effect=RuntimeError("anything")):
            desktop.set_webview2_languages({}, self.books, ui=[])       # nor here

    # ——— Studio's own restart ———
    def test_a_restart_starts_from_the_users_arguments(self):
        self.book("Oud", "nl", 1_700_000_000)
        env = {ARGS: "--remote-debugging-port=9351"}
        desktop.set_webview2_languages(env, self.books, ui=[])
        self.assertEqual(env[ARGS], "--remote-debugging-port=9351 --accept-lang=nl,en")
        self.book("Nieuw", "de", 1_700_000_500)
        child = dict(env)                     # the relaunched Studio inherits the environment
        desktop.set_webview2_languages(child, self.books, ui=[])
        self.assertEqual(child[ARGS], "--remote-debugging-port=9351 --accept-lang=de,nl,en")
        alone = {}
        desktop.set_webview2_languages(alone, self.books, ui=[])
        desktop.set_webview2_languages(alone, self.books, ui=["en-GB"])
        self.assertEqual(alone[ARGS], "--accept-lang=de,nl,en-GB,en")
        own = {ARGS: "--accept-lang=fr"}       # the user's own choice wins, every time
        desktop.set_webview2_languages(own, self.books, ui=[])
        desktop.set_webview2_languages(own, self.books, ui=[])
        self.assertEqual(own[ARGS], "--accept-lang=fr")

    # ——— example books ———
    def test_example_books_count_only_when_there_are_no_others(self):
        self.book("Voorbeeld", "en", 1_700_000_900, example=True)
        self.assertEqual(desktop.accept_languages(self.books, ui=[]), "en")
        self.book("Eigen", "nl", 1_700_000_000)
        self.assertEqual(desktop.accept_languages(self.books, ui=[]), "nl,en")

    # ——— Settings → Spelling: one language for the whole window ———
    def test_a_chosen_spelling_language_comes_first(self):
        self.book("Oud", "nl", 1_700_000_000)
        self.assertEqual(desktop.accept_languages(self.books, ui=["en-GB"], spelling="de"), "de,nl,en-GB,en")
        self.assertEqual(desktop.accept_languages(self.books, ui=["en-GB"], spelling="auto"), "nl,en-GB,en")
        self.assertEqual(desktop.accept_languages(self.books, ui=[], spelling="NL"), "NL,en")       # no second nl
        self.assertEqual(desktop.accept_languages(self.books, ui=[], spelling="x<y>"), "nl,en")     # not a tag: automatic
        env = {}
        desktop.set_webview2_languages(env, self.books, ui=[], spelling="fr")
        self.assertEqual(env[ARGS], "--accept-lang=fr,nl,en")


class SpellingSettingTest(unittest.TestCase):
    """Settings → Spelling: "auto" (the language of the book written in last) or a language tag; read at the next start."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-spelling-"))
        self.saved = config.CONFIG_FILE
        config.CONFIG_FILE = self.tmp / "config.json"
        config.refresh()

    def tearDown(self):
        config.CONFIG_FILE = self.saved
        config.refresh()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_setting(self):
        self.assertEqual(config.DEFAULTS["spelling"], "auto")
        self.assertEqual(config.SPELLING, "auto")
        self.assertEqual(config.save({"spelling": " nl "})["spelling"], "nl")
        self.assertEqual(config.SPELLING, "nl")
        self.assertEqual(config.save({"spelling": "pt-BR"})["spelling"], "pt-BR")
        for auto in ("auto", "AUTO", "", None):
            self.assertEqual(config.save({"spelling": auto})["spelling"], "auto")
        for bad in ("x<y>", "nederlands", "nl-aa-bb-cc-dd-ee-ff-gg", 5):
            with self.assertRaises(ValueError):
                config.save({"spelling": bad})
        self.assertEqual(config.load()["spelling"], "auto")
        self.assertEqual(config.LANGUAGE_TAG.pattern, books.LANGUAGE.pattern)
        config.CONFIG_FILE.write_text(json.dumps({"spelling": "<b>"}), encoding="utf-8")    # edited by hand
        config.refresh()
        self.assertEqual(config.SPELLING, "auto")

    def test_the_setting_over_http(self):
        from tests.support import temp_studio
        with temp_studio() as st:
            self.assertEqual(st.get("/api/settings")[1]["settings"]["spelling"], "auto")
            self.assertEqual(st.post("/api/settings", {"spelling": "de"})[0], 200)
            self.assertEqual(st.get("/api/settings")[1]["settings"]["spelling"], "de")
            self.assertEqual(st.post("/api/settings", {"spelling": "not a language"})[0], 400)


if __name__ == "__main__":
    unittest.main()
