"""Things URL scheme support for scheduling that AppleScript cannot express.

AppleScript can move a todo to Today or schedule it for a date, but it has no
way to put a todo in This Evening or to set a reminder time. The Things URL
scheme can do both via ``things:///update?id=...&when=...``, which needs the
auth token from Things → Settings → General → Enable Things URLs → Manage.

It also has no way to create checklist items, which the URL scheme supports
via ``checklist-items``, ``append-checklist-items`` and ``prepend-checklist-items``,
or to put a to-do under a heading, which it supports via ``heading-id``.

The approach is: parse ``when`` into the part AppleScript handles (the date)
and the part only the URL scheme handles (evening and/or a time), create or
update the todo with AppleScript as before, then apply the URL-only parts by
ID in a single ``things:///update`` call.
"""

import os
import re
import subprocess  # nosec B404 - Required for opening Things URLs
import time
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote, urlencode

from .logging_config import get_logger
from .things_db import TodoState, read_todo_state

logger = get_logger(__name__)

AUTH_TOKEN_ENV = "THINGS_AUTH_TOKEN"  # noqa: S105 - env var name, not a secret

_PLAIN_WHEN = {"today", "tomorrow", "anytime", "someday"}
_TIMED_WHEN = {"today", "tomorrow"}
_TIME_24H = re.compile(r"^(\d{1,2}):(\d{2})$")
_TIME_12H = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?$", re.IGNORECASE)


class WhenParseError(ValueError):
    """Raised when a ``when`` value cannot be understood."""


@dataclass(frozen=True)
class ParsedWhen:
    """A ``when`` value split into its AppleScript and URL scheme parts.

    Attributes:
    ----------
        applescript_when: Value for the AppleScript bridge (today, tomorrow, anytime, someday, YYYY-MM-DD), or None.
        url_when: Value for the URL scheme ``when`` parameter (evening, date@HH:MM), or None if not needed.
    """

    applescript_when: str | None
    url_when: str | None

    @property
    def needs_url_scheme(self) -> bool:
        """Whether the URL scheme step is needed after AppleScript runs."""
        return self.url_when is not None


def normalize_time(value: str) -> str:
    """Normalize a time like ``18:00``, ``9:05``, ``6pm`` or ``6:30 PM`` to ``HH:MM``.

    Raises:
    ------
        WhenParseError: If the time is not in a recognized format or out of range.
    """
    text = value.strip()

    match = _TIME_24H.match(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            raise WhenParseError(f"Time '{value}' is out of range. Use 24-hour HH:MM (e.g. 18:00) or 12-hour with am/pm (e.g. 6pm, 6:30pm).")
        return f"{hour:02d}:{minute:02d}"

    match = _TIME_12H.match(text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if not 1 <= hour <= 12 or minute > 59:
            raise WhenParseError(f"Time '{value}' is out of range. 12-hour times need an hour from 1 to 12 (e.g. 6pm, 12:30am).")
        hour %= 12
        if match.group(3).lower() == "p":
            hour += 12
        return f"{hour:02d}:{minute:02d}"

    raise WhenParseError(f"Could not understand time '{value}'. Use 24-hour HH:MM (e.g. 18:00) or 12-hour with am/pm (e.g. 6pm, 6:30pm).")


def _is_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def reject_past_date(when: str | None) -> None:
    """Raise if ``when`` starts with a YYYY-MM-DD date before today.

    AppleScript would otherwise quietly schedule a past date for today.

    Raises:
    ------
        WhenParseError: If the date is in the past.
    """
    if not when:
        return
    day = when.strip().partition("@")[0].strip()
    if _is_date(day) and datetime.strptime(day, "%Y-%m-%d").date() < date.today():
        raise WhenParseError(f"Date {day} is in the past. Use today or a later date.")


def parse_when(when: str | None) -> ParsedWhen:
    """Split a ``when`` value into its AppleScript and URL scheme parts.

    Supported values:
        today, tomorrow, anytime, someday, YYYY-MM-DD   AppleScript only
        evening                                          Today via AppleScript, then This Evening via URL
        today@TIME, tomorrow@TIME, YYYY-MM-DD@TIME       date via AppleScript, reminder via URL
        evening@TIME                                     This Evening with a reminder

    Raises:
    ------
        WhenParseError: If the value is not one of the supported forms.
    """
    if when is None:
        return ParsedWhen(None, None)

    text = when.strip()
    if not text:
        return ParsedWhen(None, None)

    reject_past_date(text)
    date_part, sep, time_part = text.partition("@")
    date_part = date_part.strip()
    keyword = date_part.lower()

    if not sep:
        if keyword in _PLAIN_WHEN:
            return ParsedWhen(keyword, None)
        if keyword == "evening":
            return ParsedWhen("today", "evening")
        if _is_date(date_part):
            return ParsedWhen(date_part, None)
        raise WhenParseError(f"Unsupported when value '{when}'. Use today, tomorrow, evening, anytime, someday or YYYY-MM-DD, optionally with @time (e.g. today@18:00).")

    if keyword in ("anytime", "someday"):
        raise WhenParseError(f"'{date_part}' cannot have a reminder time. Reminders need a date: use today@TIME, tomorrow@TIME, evening@TIME or YYYY-MM-DD@TIME.")

    time = normalize_time(time_part)

    if keyword == "evening":
        return ParsedWhen("today", f"evening@{time}")
    if keyword in _TIMED_WHEN:
        return ParsedWhen(keyword, f"{keyword}@{time}")
    if _is_date(date_part):
        return ParsedWhen(date_part, f"{date_part}@{time}")

    raise WhenParseError(f"Unsupported date '{date_part}' in when value '{when}'. Use today, tomorrow, evening or YYYY-MM-DD before the @.")


_CHECKLIST_PARAMS = {
    "replace": "checklist-items",
    "append": "append-checklist-items",
    "prepend": "prepend-checklist-items",
}
MAX_CHECKLIST_ITEMS = 100


class ChecklistError(ValueError):
    """Raised when checklist items or the checklist mode are invalid."""


@dataclass(frozen=True)
class ChecklistUpdate:
    """Validated checklist items plus how they combine with existing ones."""

    items: tuple[str, ...]
    mode: str = "replace"

    @property
    def param(self) -> str:
        """The URL scheme parameter name for this mode."""
        return _CHECKLIST_PARAMS[self.mode]


def parse_checklist(items: list[str] | str | None, mode: str = "replace") -> ChecklistUpdate | None:
    """Validate checklist items for the URL scheme.

    Blank items are dropped. Returns None if nothing is left, so an empty list
    leaves the todo's checklist unchanged.

    Raises:
    ------
        ChecklistError: If the mode is unknown, an item is not a string or contains
            a newline, or there are more than 100 items.
    """
    if mode not in _CHECKLIST_PARAMS:
        raise ChecklistError(f"Unknown checklist_mode '{mode}'. Use replace, append or prepend.")
    if items is None:
        return None
    if isinstance(items, str):
        items = [items]

    kept = []
    for item in items:
        if not isinstance(item, str):
            raise ChecklistError(f"Checklist items must be strings, got {type(item).__name__}: {item!r}")
        if not item.strip():
            continue
        if "\n" in item or "\r" in item:
            raise ChecklistError(f"Checklist item {item!r} contains a newline. Pass each item as a separate array entry.")
        kept.append(item)

    if len(kept) > MAX_CHECKLIST_ITEMS:
        raise ChecklistError(f"Too many checklist items ({len(kept)}). Things accepts at most {MAX_CHECKLIST_ITEMS}.")
    if not kept:
        return None
    return ChecklistUpdate(tuple(kept), mode)


@dataclass(frozen=True)
class HeadingChange:
    """A heading to move a to-do under, or None for both fields to move it out of its heading."""

    title: str | None
    uuid: str | None


def describe_url_update(when: str | None = None, checklist: ChecklistUpdate | None = None, heading: HeadingChange | None = None) -> str:
    """Describe what a URL update sets, for log and error messages."""
    parts = []
    if when:
        parts.append(f"set when={when!r}")
    if checklist:
        verb = {"replace": "set", "append": "append", "prepend": "prepend"}[checklist.mode]
        parts.append(f"{verb} {len(checklist.items)} checklist item(s)")
    if heading:
        parts.append(f"move it under heading {heading.title!r}" if heading.uuid else "move it out of its heading")
    return " and ".join(parts)


MISSING_TOKEN_MESSAGE = f"{AUTH_TOKEN_ENV} is not set. Copy the token from Things → Settings → General → Enable Things URLs → Manage and add it to the MCP server's env."
UNAPPLIED_HINT = f"This usually means {AUTH_TOKEN_ENV} is wrong or out of date; Things shows the error in its own window."


def auth_token() -> str | None:
    """Return the Things auth token from the environment, or None if it isn't set."""
    return os.environ.get(AUTH_TOKEN_ENV, "").strip() or None


def open_things_url(url: str) -> str | None:
    """Open a Things URL with ``open -g`` so Things stays in the background.

    Returns:
    -------
        None if the URL was handed to Things, otherwise an error message. Success
        only means ``open`` worked; Things may still reject the URL.
    """
    try:
        result = subprocess.run(["open", "-g", url], capture_output=True, text=True, timeout=10, check=False)  # nosec B603 B607
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.error(f"Failed to open Things URL: {e}")
        return f"Could not open Things URL: {e}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"exit code {result.returncode}"
        logger.error(f"open -g failed: {detail}")
        return f"Could not open Things URL: {detail}"
    return None


def build_update_url(
    todo_id: str,
    token: str,
    when: str | None = None,
    checklist: ChecklistUpdate | None = None,
    heading: HeadingChange | None = None,
) -> str:
    """Build one ``things:///update`` URL carrying any of ``when``, checklist items and heading.

    A heading is set by ``heading-id`` since it's already been resolved to one
    heading. Moving out of a heading uses an empty ``heading``, which was
    checked against Things directly.

    Uses percent-encoding throughout so spaces become %20 and newlines %0A,
    never +, which Things would otherwise read literally.
    """
    params = {"id": todo_id}
    if when:
        params["when"] = when
    if checklist:
        params[checklist.param] = "\n".join(checklist.items)
    if heading:
        if heading.uuid:
            params["heading-id"] = heading.uuid
        else:
            params["heading"] = ""
    params["auth-token"] = token
    query = urlencode(params, quote_via=quote)
    return f"things:///update?{query}"


def find_unapplied(
    before: TodoState | None,
    after: TodoState,
    when: str | None = None,
    checklist: ChecklistUpdate | None = None,
    heading: HeadingChange | None = None,
) -> list[str]:
    """Compare a to-do's state with what a URL update asked for, and list what's missing.

    ``before`` is the state read before the URL was opened. It's needed to tell
    whether appended or prepended items were actually added, since the same
    text may already be in the checklist.
    """
    missing = []
    if when:
        day, _, reminder = when.partition("@")
        if day == "evening" and not after.evening:
            missing.append("This Evening")
        if reminder and after.reminder != reminder:
            missing.append(f"reminder at {reminder}")
    if checklist:
        want = [item.strip() for item in checklist.items]
        have = [item.strip() for item in after.checklist]
        added = len(have) - len(before.checklist) if before else len(want)
        if checklist.mode == "replace":
            landed = have == want
        elif checklist.mode == "append":
            landed = have[-len(want) :] == want and added == len(want)
        else:
            landed = have[: len(want)] == want and added == len(want)
        if not landed:
            missing.append("checklist items")
    if heading and after.heading != heading.uuid:
        missing.append(f"heading {heading.title!r}" if heading.uuid else "moving out of its heading")
    return missing


def wait_for_url_update(
    todo_id: str,
    before: TodoState | None,
    when: str | None = None,
    checklist: ChecklistUpdate | None = None,
    heading: HeadingChange | None = None,
    timeout: float = 5.0,
    interval: float = 0.25,
) -> str | None:
    """Wait for Things to apply a URL update, and report what didn't land.

    Things applies the URL on its own time, and ``open`` succeeds whether or
    not Things accepts it. A wrong auth token only shows as an error inside
    Things, so reading the to-do back is the only way to notice.

    Returns:
    -------
        None once everything has landed (or if the database can't be read to check),
        otherwise a message naming what never showed up.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            after = read_todo_state(todo_id)
        except Exception as e:
            logger.warning(f"Could not read {todo_id} back to check the URL update: {e}")
            return None
        if after is None:
            return f"Todo {todo_id} could not be found after the URL update."

        missing = find_unapplied(before, after, when, checklist, heading)
        if not missing:
            return None
        if time.monotonic() >= deadline:
            logger.error(f"URL update for {todo_id} not applied after {timeout}s: {missing}")
            return f"Things didn't apply {', '.join(missing)} within {timeout:g}s. {UNAPPLIED_HINT}"
        time.sleep(interval)


def apply_url_update(todo_id: str, when: str | None = None, checklist: ChecklistUpdate | None = None, heading: HeadingChange | None = None) -> str | None:
    """Apply URL-scheme-only changes (``when``, checklist items, heading) to an existing todo.

    Everything goes in a single URL, opened with ``open -g`` so Things stays
    in the background. Afterwards the to-do is read back to check the change
    actually landed.

    Returns:
    -------
        None on success, otherwise an error message describing what went wrong.
    """
    token = auth_token()
    if not token:
        return MISSING_TOKEN_MESSAGE

    try:
        before = read_todo_state(todo_id)
    except Exception as e:
        logger.warning(f"Could not read {todo_id} before the URL update: {e}")
        before = None

    url = build_update_url(todo_id, token, when=when, checklist=checklist, heading=heading)
    logger.info(f"Applying {describe_url_update(when, checklist, heading)} to {todo_id} via Things URL scheme")

    open_error = open_things_url(url)
    if open_error:
        return open_error

    return wait_for_url_update(todo_id, before, when=when, checklist=checklist, heading=heading)
