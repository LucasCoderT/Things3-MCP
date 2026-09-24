"""Creating several items in one call through ``things:///json``.

Used for projects with headings (AppleScript can't create headings, and a
JSON ``update`` can't add them to an existing project, so the whole project
has to be created in one JSON call) and for creating a batch of to-dos.

Everything is validated before anything is written. ``open`` can't hand back
the IDs Things assigns, so afterwards the new items are found in the database
by title and creation time, and checked against what was sent.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote, urlencode

import things

from .applescript_bridge import ensure_tags
from .headings import HeadingError, resolve_heading
from .logging_config import get_logger
from .things_db import created_since, project_contents
from .url_scheme import (
    MISSING_TOKEN_MESSAGE,
    UNAPPLIED_HINT,
    ChecklistError,
    WhenParseError,
    auth_token,
    open_things_url,
    parse_checklist,
    parse_when,
)

logger = get_logger(__name__)

# A conservative cap per call. Things rate-limits imports, and a bigger batch
# makes a partial failure harder to sort out.
MAX_ITEMS = 100

TODO_FIELDS = ("title", "notes", "when", "deadline", "tags", "checklist_items", "list_id", "list_title", "heading")


class JsonImportError(ValueError):
    """Raised when an import request is invalid. Nothing has been written."""


@dataclass
class PreparedImport:
    """A validated import, ready to send."""

    items: list[dict]
    titles: list[str]
    new_tags: list[str] = field(default_factory=list)


# Validation helpers


def _text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JsonImportError(f"{what} must be a non-empty string.")
    return value


def _string_list(value: object, what: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise JsonImportError(f"{what} must be an array of strings.")
    return [v for v in value if v.strip()]


def _deadline(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise JsonImportError(f"Deadline '{value}' must be YYYY-MM-DD.") from None
    return value


class _Tags:
    """Maps requested tags to existing ones (case-insensitive) and remembers the rest."""

    def __init__(self) -> None:
        self.known = {t["title"].casefold(): t["title"] for t in things.tags()}
        self.new: dict[str, str] = {}

    def resolve(self, tags: list[str]) -> list[str]:
        resolved = []
        for tag in tags:
            key = tag.strip().casefold()
            if key in self.known:
                resolved.append(self.known[key])
            else:
                resolved.append(self.new.setdefault(key, tag.strip()))
        return resolved


def _resolve_list(list_id: str | None, list_title: str | None) -> tuple[str | None, str | None]:
    """Return ``(list id, project id)`` for a to-do's destination. Projects win over areas by title, like the AppleScript bridge."""
    if list_id:
        item = things.get(list_id)
        if not item or item.get("type") not in ("project", "area"):
            raise JsonImportError(f"No project or area with ID '{list_id}'.")
        return item["uuid"], item["uuid"] if item["type"] == "project" else None
    if list_title:
        key = list_title.strip().casefold()
        for project in things.projects():
            if project["title"].casefold() == key:
                return project["uuid"], project["uuid"]
        for area in things.areas():
            if area["title"].casefold() == key:
                return area["uuid"], None
        raise JsonImportError(f"No project or area named '{list_title}'. Look them up with get_projects or get_areas.")
    return None, None


def _resolve_area(area_id: str | None, area_title: str | None) -> str | None:
    if area_id:
        item = things.get(area_id)
        if not item or item.get("type") != "area":
            raise JsonImportError(f"No area with ID '{area_id}'.")
        return item["uuid"]
    if area_title:
        key = area_title.strip().casefold()
        areas = things.areas()
        for area in areas:
            if area["title"].casefold() == key:
                return area["uuid"]
        available = ", ".join(a["title"] for a in areas) or "none"
        raise JsonImportError(f"No area named '{area_title}'. Available areas: {available}.")
    return None


def _json_when(when: str | None) -> str | None:
    parsed = parse_when(when)
    return parsed.url_when or parsed.applescript_when


# Building imports


def _todo_item(spec: dict, tags: _Tags) -> dict:
    unknown = set(spec) - set(TODO_FIELDS)
    if unknown:
        raise JsonImportError(f"Unknown field(s) {', '.join(sorted(unknown))}. Allowed: {', '.join(TODO_FIELDS)}.")

    attributes: dict = {"title": _text(spec.get("title"), "title")}
    if spec.get("notes"):
        attributes["notes"] = spec["notes"]
    when = _json_when(spec.get("when"))
    if when:
        attributes["when"] = when
    deadline = _deadline(spec.get("deadline"))
    if deadline:
        attributes["deadline"] = deadline
    tag_names = tags.resolve(_string_list(spec.get("tags"), "tags"))
    if tag_names:
        attributes["tags"] = tag_names
    checklist = parse_checklist(spec.get("checklist_items"))
    if checklist:
        attributes["checklist-items"] = [{"type": "checklist-item", "attributes": {"title": item}} for item in checklist.items]

    list_id, project_id = _resolve_list(spec.get("list_id"), spec.get("list_title"))
    if list_id:
        attributes["list-id"] = list_id
    heading = spec.get("heading")
    if heading is not None and not isinstance(heading, str):
        raise JsonImportError("heading must be a string.")
    if heading and heading.strip():
        change = resolve_heading(heading, project_id)
        if change and change.uuid:
            attributes["heading-id"] = change.uuid

    return {"type": "to-do", "attributes": attributes}


def prepare_todos(todos: list) -> PreparedImport:
    """Validate a batch of to-dos and build the JSON items.

    Raises:
    ------
        JsonImportError: If anything in the batch is invalid, naming the to-do.
    """
    if not isinstance(todos, list) or not todos:
        raise JsonImportError("todos must be a non-empty array of objects.")
    if len(todos) > MAX_ITEMS:
        raise JsonImportError(f"Too many todos ({len(todos)}). Send at most {MAX_ITEMS} per call.")

    tags = _Tags()
    items = []
    for number, spec in enumerate(todos, start=1):
        label = f"Todo {number}"
        if not isinstance(spec, dict):
            raise JsonImportError(f"{label} must be an object with at least a title.")
        if isinstance(spec.get("title"), str) and spec["title"].strip():
            label += f" ('{spec['title']}')"
        try:
            items.append(_todo_item(spec, tags))
        except (JsonImportError, WhenParseError, ChecklistError, HeadingError) as e:
            raise JsonImportError(f"{label}: {e}") from None

    return PreparedImport(items=items, titles=[i["attributes"]["title"] for i in items], new_tags=list(tags.new.values()))


def prepare_project(  # noqa: PLR0913
    title: str,
    notes: str | None = None,
    when: str | None = None,
    deadline: str | None = None,
    tags: list[str] | None = None,
    area_id: str | None = None,
    area_title: str | None = None,
    todos: list[str] | None = None,
    headings: dict | None = None,
) -> PreparedImport:
    """Validate a project with headings and build its JSON item.

    ``headings`` maps each heading title to the to-do titles under it, in
    order. ``todos`` are the to-dos that go above the first heading.

    Raises:
    ------
        JsonImportError: If anything is invalid.
    """
    try:
        attributes: dict = {"title": _text(title, "title")}
        if notes:
            attributes["notes"] = notes
        parsed = parse_when(when)
        if parsed.needs_url_scheme:
            raise JsonImportError("Projects don't support evening or reminder times here. Use today, tomorrow, anytime, someday or YYYY-MM-DD.")
        if parsed.applescript_when:
            attributes["when"] = parsed.applescript_when
        if _deadline(deadline):
            attributes["deadline"] = deadline
        tag_resolver = _Tags()
        tag_names = tag_resolver.resolve(_string_list(tags, "tags"))
        if tag_names:
            attributes["tags"] = tag_names
        area = _resolve_area(area_id, area_title)
        if area:
            attributes["area-id"] = area
    except (WhenParseError, ChecklistError) as e:
        raise JsonImportError(str(e)) from None

    if not isinstance(headings, dict) or not headings:
        raise JsonImportError("headings must be an object mapping each heading title to an array of todo titles.")

    items = [{"type": "to-do", "attributes": {"title": t}} for t in _string_list(todos, "todos")]
    seen = set()
    for heading, heading_todos in headings.items():
        name = _text(heading, "Each heading title").strip()
        if name.casefold() in seen:
            raise JsonImportError(f"Heading '{name}' appears more than once.")
        seen.add(name.casefold())
        items.append({"type": "heading", "attributes": {"title": name}})
        items.extend({"type": "to-do", "attributes": {"title": t}} for t in _string_list(heading_todos, f"The todos under '{name}'"))

    if len(items) > MAX_ITEMS:
        raise JsonImportError(f"Too many headings and todos ({len(items)}). A project can be created with at most {MAX_ITEMS} here.")

    attributes["items"] = items
    return PreparedImport(items=[{"type": "project", "attributes": attributes}], titles=[attributes["title"]], new_tags=list(tag_resolver.new.values()))


# Sending and checking


def build_json_url(items: list[dict], token: str) -> str:
    """Build a ``things:///json`` URL, percent-encoded throughout."""
    return "things:///json?" + urlencode({"data": json.dumps(items, ensure_ascii=False), "auth-token": token}, quote_via=quote)


def send_import(prepared: PreparedImport) -> str | None:
    """Create any missing tags, then send the import. Returns an error message, or None if it was handed to Things."""
    token = auth_token()
    if not token:
        return MISSING_TOKEN_MESSAGE
    if prepared.new_tags:
        logger.info(f"Creating tags before import: {prepared.new_tags}")
        result = ensure_tags(prepared.new_tags)
        if result != "true":
            return f"Could not create tags {', '.join(prepared.new_tags)}: {result}"
    return open_things_url(build_json_url(prepared.items, token))


def match_created(titles: list[str], rows: list[tuple[str, str]]) -> list[str | None]:
    """Match requested titles to created rows in order, so repeated titles each get their own ID."""
    remaining = list(rows)
    ids: list[str | None] = []
    for title in titles:
        index = next((i for i, (_, row_title) in enumerate(remaining) if row_title == title), None)
        ids.append(remaining.pop(index)[0] if index is not None else None)
    return ids


def wait_for_created(item_type: str, titles: list[str], since: float, timeout: float = 5.0, interval: float = 0.25) -> list[str | None]:
    """Poll the database until every title has a newly created item, or the timeout passes."""
    deadline = time.monotonic() + timeout
    while True:
        ids = match_created(titles, created_since(item_type, since, sorted(set(titles))))
        if all(ids) or time.monotonic() >= deadline:
            return ids
        time.sleep(interval)


def import_todos(todos: list) -> str:
    """Validate, send and check a batch of to-dos. Returns the message for the tool."""
    try:
        prepared = prepare_todos(todos)
    except JsonImportError as e:
        return f"⚠️ Error: {e}"

    since = time.time() - 1
    error = send_import(prepared)
    if error:
        return f"⚠️ Error: {error}"

    ids = wait_for_created("to-do", prepared.titles, since)
    lines = [f"- {title} (ID: {uuid})" if uuid else f"- {title} (not found)" for title, uuid in zip(prepared.titles, ids, strict=True)]
    found = sum(1 for uuid in ids if uuid)
    if found == len(ids):
        return f"✅ Created {found} todos:\n" + "\n".join(lines)
    return f"⚠️ Only {found} of {len(ids)} todos showed up in Things. {UNAPPLIED_HINT}\n" + "\n".join(lines)


def import_project(**kwargs: object) -> str:
    """Validate, send and check a project with headings. Returns the message for the tool."""
    try:
        prepared = prepare_project(**kwargs)
    except JsonImportError as e:
        return f"⚠️ Error: {e}"

    project = prepared.items[0]["attributes"]
    expected_headings = [i["attributes"]["title"] for i in project["items"] if i["type"] == "heading"]
    expected_todos = sum(1 for i in project["items"] if i["type"] == "to-do")

    since = time.time() - 1
    error = send_import(prepared)
    if error:
        return f"⚠️ Error: {error}"

    (project_id,) = wait_for_created("project", prepared.titles, since)
    if not project_id:
        return f"⚠️ Project '{project['title']}' didn't show up in Things. {UNAPPLIED_HINT}"

    deadline = time.monotonic() + 5.0
    while True:
        headings, todos = project_contents(project_id)
        if (headings == expected_headings and len(todos) == expected_todos) or time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    summary = f"{len(headings)} headings ({', '.join(headings) or 'none'}) and {len(todos)} todos"
    if headings != expected_headings or len(todos) != expected_todos:
        return f"⚠️ Created project: {project['title']} (ID: {project_id}), but it has {summary}; expected {len(expected_headings)} headings and {expected_todos} todos."
    return f"✅ Successfully created project: {project['title']} (ID: {project_id}) with {summary}"
