import json
from pathlib import Path

FILE = Path(__file__).parent / "bookings.json"
_bookings = []


def _load():
    global _bookings
    try:
        _bookings = json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        _bookings = []


def _save():
    try:
        FILE.write_text(json.dumps(_bookings, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print("Не удалось сохранить записи:", e)


_load()


def busy(master_id, date_str):
    """Занятые интервалы мастера в этот день: список (начало, конец) в минутах."""
    return [
        (b["start"], b["end"])
        for b in _bookings
        if b["master_id"] == master_id and b["date"] == date_str
    ]


def add(booking):
    booking["id"] = max([b["id"] for b in _bookings], default=0) + 1
    _bookings.append(booking)
    _save()
    return booking