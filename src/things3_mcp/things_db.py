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
