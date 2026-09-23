"""Reading and validating Things headings (the groups inside a project).

AppleScript can't see headings, so everything here reads through things.py.
Writes go through the URL scheme (see ``url_scheme.py``); this module only
works out which heading a to-do should go under and checks it exists before
anything is written.

Note: in things.py a to-do under a heading has ``project`` set to None and
only its heading points at the project, so project lookups go through the
heading when needed.
"""

import things

from .url_scheme import HeadingChange

# Built-in lists that AppleScript's `move ... to list` accepts. Moving to Inbox
# takes a to-do out of its project; the others keep it where it is.
_BUILT_IN_LISTS = {"inbox", "today", "anytime", "upcoming", "someday", "logbook", "trash"}


class HeadingError(ValueError):
    """Raised when a heading can't be resolved to exactly one heading in a project."""


def list_headings(project_uuid: str) -> list[dict]:
    """Return a project's open headings in display order."""
    return things.tasks(type="heading", project=project_uuid) or []


def project_of(todo: dict) -> str | None:
    """Return the UUID of the project a to-do belongs to, directly or via its heading."""
    if todo.get("project"):
        return todo["project"]
    if todo.get("heading"):
        heading = things.get(todo["heading"])
        if heading:
            return heading.get("project")
    return None


def _project_uuid_by_id(item_id: str) -> str | None:
    item = things.get(item_id)
    if item and item.get("type") == "project":
        return item["uuid"]
    return None


def _project_uuid_by_title(title: str) -> str | None:
    # Mirrors the AppleScript bridge's `first project whose name is ...`, which is case-insensitive
    key = title.casefold()
    for project in things.projects():
        if project["title"].casefold() == key:
            return project["uuid"]
    return None


def resolve_add_project(list_id: str | None, list_title: str | None) -> str | None:
    """Return the project a new to-do will land in, or None if it won't be in a project.

    list_id takes priority over list_title, matching the AppleScript bridge.
    """
    if list_id:
        return _project_uuid_by_id(list_id)
    if list_title:
        return _project_uuid_by_title(list_title)
    return None


def resolve_update_project(todo_id: str, list_id: str | None, list_name: str | None) -> str | None:
    """Return the project a to-do will be in after an update, or None if it won't be in a project.

    Uses the new project if the update moves the to-do, otherwise its current project.

    Raises:
    ------
        HeadingError: If the to-do doesn't exist.
    """
    todo = things.get(todo_id)
    if not todo:
        raise HeadingError(f"Todo '{todo_id}' not found.")

    if list_id:
        return _project_uuid_by_id(list_id)
    if list_name:
        if list_name.strip().casefold() in _BUILT_IN_LISTS:
            return None if list_name.strip().casefold() == "inbox" else project_of(todo)
        return _project_uuid_by_title(list_name)
    return project_of(todo)


def resolve_heading(heading: str | None, project_uuid: str | None) -> HeadingChange | None:
    """Match a heading name against the headings in a project.

    Matching is trimmed and case-insensitive, and must hit exactly one heading.
    An empty string means "move out of its heading" and needs no project.

    Returns:
    -------
        None if heading is None, otherwise the HeadingChange to apply.

    Raises:
    ------
        HeadingError: If there's no project, or the heading is missing or ambiguous.
            The message lists the project's headings.
    """
    if heading is None:
        return None
    name = heading.strip()
    if not name:
        return HeadingChange(title=None, uuid=None)

    if not project_uuid:
        raise HeadingError(f"Heading '{name}' needs a project, but this to-do isn't going into one. Pass list_id or the project's title as well.")

    project = things.get(project_uuid)
    project_title = project["title"] if project else project_uuid
    headings = list_headings(project_uuid)
    available = ", ".join(h["title"] for h in headings) or "none"

    key = name.casefold()
    matches = [h for h in headings if h["title"].strip().casefold() == key]
    if len(matches) == 1:
        return HeadingChange(title=matches[0]["title"], uuid=matches[0]["uuid"])
    if not matches:
        raise HeadingError(f"No heading '{name}' in project '{project_title}'. Available headings: {available}.")
    raise HeadingError(f"Heading '{name}' matches {len(matches)} headings in project '{project_title}', so it's ambiguous. Available headings: {available}.")
