"""The writing log: words written per day, kept in each poem's and book's own .studio/days.json.

Poems are counted when their text is saved (Store.save_text); books keep the same file (books.py).
gather() reads both across the library for the writing view.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

DAYS_FILE = Path(".studio") / "days.json"
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}$")
_WORD = re.compile(r"[^\W_]")
_lock = threading.Lock()


def words(text: str) -> int:
    return sum(1 for token in text.split() if _WORD.search(token))


def _clean(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items()
            if isinstance(k, str) and _DAY.match(k) and isinstance(v, int) and not isinstance(v, bool) and v >= 0}


def read_days(folder: Path) -> dict:
    try:
        raw = json.loads((Path(folder) / DAYS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return _clean(raw)


def add(folder: Path, n: int, when: datetime | None = None) -> None:
    from .store import write_text
    if n <= 0:
        return
    f = Path(folder) / DAYS_FILE
    key = (when or datetime.now()).date().isoformat()
    with _lock:
        days = {}
        if f.exists():
            try:
                days = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return          # never overwrite a log we can't read
            if not isinstance(days, dict):
                return
        days = _clean(days)
        days[key] = days.get(key, 0) + n
        write_text(f, json.dumps(days, indent=2, sort_keys=True) + "\n")


def poem_gain(old_lines: list, new_lines: list) -> int:
    return max(0, words("\n".join(new_lines)) - words("\n".join(old_lines)))


def _meta(f: Path) -> dict:
    try:
        meta = json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _book_info(d: Path) -> dict:
    from .books import BOOK_FILE
    meta = _meta(d / BOOK_FILE)
    title = meta.get("title")
    goals = meta.get("goals")
    goal = goals.get("daily") if isinstance(goals, dict) else 0
    if not isinstance(goal, int) or isinstance(goal, bool) or goal < 0:
        goal = 0
    return {"id": d.name, "title": title if isinstance(title, str) and title else d.name, "goal": goal,
            "example": meta.get("example") is True}


def gather(store, books_root: Path, today: date | None = None) -> dict:
    """The days written across the library, for the writing view. The examples (a series or book marked "example":
    true, as examples.py marks them) are left out: adding them saves their poems and pieces, which isn't writing."""
    from .books import Books
    from .store import SERIES_FILE
    today = today or date.today()
    days: dict = {}

    def put(day, kind, key, n):
        days.setdefault(day, {"poems": {}, "books": {}})[kind][key] = n

    books = []
    for d in Books(books_root).dirs():
        info = _book_info(d)
        if info.pop("example"):
            continue
        mine = {k: v for k, v in read_days(d).items() if v}
        for day, n in mine.items():
            put(day, "books", info["id"], n)
        info["first_day"] = min(mine) if mine else None
        books.append(info)

    poems, examples = {}, {}
    for d in store.poem_dirs():
        mine = {k: v for k, v in read_days(d).items() if v}
        if not mine:
            continue
        if d.parent not in examples:
            examples[d.parent] = _meta(d.parent / SERIES_FILE).get("example") is True
        if examples[d.parent]:
            continue
        try:
            title = store.load(d).get("title")
        except Exception:
            title = None
        pid = store.pid(d)
        poems[pid] = {"title": title if isinstance(title, str) and title else d.name, "series": d.parent.name}
        for day, n in mine.items():
            put(day, "poems", pid, n)

    return {"today": today.isoformat(), "week_start": (today - timedelta(days=today.weekday())).isoformat(),
            "days": days, "books": books, "poems": poems}
