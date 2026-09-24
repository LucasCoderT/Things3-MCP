"""Tests for the read-only Things database helpers."""

import sqlite3

import pytest

from things3_mcp import things_db
from things3_mcp.things_db import TodoState, created_since, decode_reminder, project_contents, read_schedule_extras, read_todo_state


def encode(hour, minute):
    return (hour << 26) | (minute << 20)


@pytest.fixture()
def fake_db(tmp_path, monkeypatch):
    path = tmp_path / "main.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE TMTask (uuid TEXT, reminderTime INTEGER, startBucket INTEGER, heading TEXT,
                             type INTEGER DEFAULT 0, trashed INTEGER DEFAULT 0, creationDate REAL DEFAULT 0,
                             title TEXT, project TEXT, "index" INTEGER DEFAULT 0);
        CREATE TABLE TMChecklistItem (uuid TEXT, title TEXT, "index" INTEGER, task TEXT);
        """
    )
    db.execute("INSERT INTO TMTask (uuid, reminderTime, startBucket, heading) VALUES ('T-1', ?, 1, 'H-FACE')", (encode(21, 0),))
    db.execute("INSERT INTO TMTask (uuid, reminderTime, startBucket, heading) VALUES ('T-2', NULL, 0, NULL)")
    db.executemany(
        'INSERT INTO TMTask (uuid, type, trashed, creationDate, title, project, heading, "index") VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [
            ("P-1", 1, 0, 100.0, "Proj", None, None, 0),
            ("H-B", 2, 0, 100.1, "Body", "P-1", None, 5),
            ("H-A", 2, 0, 100.1, "Face", "P-1", None, -5),
            ("N-1", 0, 0, 100.2, "Top", "P-1", None, 0),
            ("N-2", 0, 0, 100.3, "Wash", None, "H-A", 0),
            ("N-3", 0, 1, 100.4, "Trashed", "P-1", None, 0),
            ("OLD", 0, 0, 50.0, "Wash", None, None, 0),
            ("N-4", 0, 0, 100.5, "Wash", None, None, 0),
        ],
    )
    db.executemany("INSERT INTO TMChecklistItem VALUES (?, ?, ?, 'T-1')", [("c2", "Rinse", 5), ("c1", "Soap + scrub", -3), ("c3", "Dry", 9)])
    db.commit()
    db.close()
    monkeypatch.setattr(things_db, "_connect", lambda: sqlite3.connect(f"file:{path}?mode=ro", uri=True))


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (933232640, "13:58"), (1409286144, "21:00"), (encode(0, 0), "00:00"), (encode(9, 5), "09:05")],
)
def test_decode_reminder(value, expected):
    # 933232640 and 1409286144 were read from Things during the live reminder tests
    assert decode_reminder(value) == expected


def test_read_todo_state(fake_db):
    assert read_todo_state("T-1") == TodoState(reminder="21:00", evening=True, heading="H-FACE", checklist=("Soap + scrub", "Rinse", "Dry"))
    assert read_todo_state("T-2") == TodoState(reminder=None, evening=False, heading=None, checklist=())
    assert read_todo_state("MISSING") is None


def test_read_schedule_extras(fake_db):
    assert read_schedule_extras("T-1") == ("21:00", True)
    assert read_schedule_extras("T-2") == (None, False)
    assert read_schedule_extras("MISSING") == (None, False)


def test_read_schedule_extras_never_raises():
    # The autouse fixture makes the database unreadable
    assert read_schedule_extras("T-1") == (None, False)


def test_created_since(fake_db):
    assert created_since("to-do", 100.0, ["Wash", "Top", "Trashed"]) == [("N-1", "Top"), ("N-2", "Wash"), ("N-4", "Wash")]
    assert created_since("project", 100.0, ["Proj"]) == [("P-1", "Proj")]
    assert created_since("to-do", 100.0, []) == []


def test_project_contents(fake_db):
    headings, todos = project_contents("P-1")
    assert headings == ["Face", "Body"]
    assert sorted(todos) == [("Top", None), ("Wash", "Face")]
