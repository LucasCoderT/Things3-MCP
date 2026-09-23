"""Things URL scheme support for scheduling that AppleScript cannot express.

AppleScript can move a todo to Today or schedule it for a date, but it has no
way to put a todo in This Evening or to set a reminder time. The Things URL
scheme can do both via ``things:///update?id=...&when=...``, which needs the
auth token from Things → Settings → General → Enable Things URLs → Manage.

The approach is: parse ``when`` into the part AppleScript handles (the date)
and the part only the URL scheme handles (evening and/or a time), create or
update the todo with AppleScript as before, then apply the URL part by ID.
"""

import os
import re
import subprocess  # nosec B404 - Required for opening Things URLs
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlencode

from .logging_config import get_logger

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


def build_update_url(todo_id: str, when: str, token: str) -> str:
    """Build a ``things:///update`` URL that sets ``when`` on a todo.

    Uses percent-encoding throughout so spaces become %20, never +, which
    Things would otherwise read literally.
    """
    query = urlencode({"id": todo_id, "when": when, "auth-token": token}, quote_via=quote)
    return f"things:///update?{query}"


def apply_url_when(todo_id: str, url_when: str) -> str | None:
    """Apply a URL scheme ``when`` value to an existing todo.

    Opens the URL with ``open -g`` so Things stays in the background.

    Returns:
    -------
        None on success, otherwise an error message describing what went wrong.
    """
    token = os.environ.get(AUTH_TOKEN_ENV, "").strip()
    if not token:
        return f"{AUTH_TOKEN_ENV} is not set. Copy the token from Things → Settings → General → Enable Things URLs → Manage and add it to the MCP server's env."

    url = build_update_url(todo_id, url_when, token)
    logger.info(f"Applying when={url_when!r} to {todo_id} via Things URL scheme")

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
