"""Read-only access to Things fields that things.py doesn't expose.

things.py has no reminder time or This Evening flag, and we need both to show
them in reads and to check that a URL scheme update actually landed. This
reads them straight from the Things database, opened read-only, using the
path things.py already works out.

Nothing here writes to the database.
"""

import sqlite3
from dataclasses import dataclass

from things.database import Database

from .logging_config import get_logger

logger = get_logger(__name__)

# TMTask.startBucket: 0 is the normal part of a list, 1 is This Evening
_EVENING_BUCKET = 1


@dataclass(frozen=True)
class TodoState:
    """The URL-scheme-managed fields of a to-do, as stored in the database."""

    reminder: str | None
    evening: bool
    heading: str | None
    checklist: tuple[str, ...]


def decode_reminder(value: int | None) -> str | None:
    """Decode TMTask.reminderTime into ``HH:MM``.

    Things packs the hour into bits 26-30 and the minute into bits 20-25.
    """
    if value is None:
        return None
    return f"{(value >> 26) & 0x1F:02d}:{(value >> 20) & 0x3F:02d}"


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Database().filepath}?mode=ro", uri=True)


def read_todo_state(todo_id: str) -> TodoState | None:
    """Read a to-do's reminder, evening flag, heading and checklist, or None if it isn't found."""
    connection = _connect()
    try:
        row = connection.execute("SELECT reminderTime, startBucket, heading FROM TMTask WHERE uuid = ?", (todo_id,)).fetchone()
        if row is None:
            return None
        checklist = connection.execute('SELECT title FROM TMChecklistItem WHERE task = ? ORDER BY "index"', (todo_id,)).fetchall()
    finally:
        connection.close()
    return TodoState(
        reminder=decode_reminder(row[0]),
        evening=row[1] == _EVENING_BUCKET,
        heading=row[2],
        checklist=tuple(title for (title,) in checklist),
    )


def read_schedule_extras(todo_id: str) -> tuple[str | None, bool]:
    """Return ``(reminder, evening)`` for a to-do, or ``(None, False)`` if it can't be read.

    Used by the formatter, so it never raises: a read that fails just leaves
    the extra lines out.
    """
    try:
        connection = _connect()
        try:
            row = connection.execute("SELECT reminderTime, startBucket FROM TMTask WHERE uuid = ?", (todo_id,)).fetchone()
        finally:
            connection.close()
    except Exception as e:
        logger.debug(f"Could not read reminder/evening for {todo_id}: {e}")
        return None, False
    if row is None:
        return None, False
    return decode_reminder(row[0]), row[1] == _EVENING_BUCKET


# TMTask.type values
_TYPE_CODES = {"to-do": 0, "project": 1, "heading": 2}


def created_since(item_type: str, since: float, titles: list[str]) -> list[tuple[str, str]]:
    """Return ``(uuid, title)`` for untrashed items of a type created at or after ``since`` with one of these titles.

    Rows come back in creation order. Things creates a JSON import's items in
    the order they were sent, which is how callers match them back up.
    """
    wanted = set(titles)
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT uuid, title FROM TMTask WHERE type = ? AND trashed = 0 AND creationDate >= ? ORDER BY creationDate, rowid",
            (_TYPE_CODES[item_type], since),
        ).fetchall()
    finally:
        connection.close()
    return [(uuid, title) for uuid, title in rows if title in wanted]


def project_contents(project_id: str) -> tuple[list[str], list[tuple[str, str | None]]]:
    """Return a project's heading titles and its to-dos as ``(title, heading title)`` pairs."""
    connection = _connect()
    try:
        headings = connection.execute('SELECT title FROM TMTask WHERE type = 2 AND trashed = 0 AND project = ? ORDER BY "index"', (project_id,)).fetchall()
        todos = connection.execute(
            """
            SELECT t.title, h.title FROM TMTask t LEFT JOIN TMTask h ON h.uuid = t.heading
            WHERE t.type = 0 AND t.trashed = 0 AND (t.project = ? OR h.project = ?)
            """,
            (project_id, project_id),
        ).fetchall()
    finally:
        connection.close()
    return [title for (title,) in headings], [(title, heading) for title, heading in todos]
