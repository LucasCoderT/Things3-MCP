"""Tests for heading resolution, the Heading line in format_todo, and get_headings/get_todos."""

from unittest.mock import patch

import pytest

from things3_mcp import fast_server, headings
from things3_mcp.formatters import format_todo
from things3_mcp.headings import HeadingError, resolve_add_project, resolve_heading, resolve_update_project
from things3_mcp.url_scheme import HeadingChange

HYGIENE = {"uuid": "P-HYG", "type": "project", "title": "Hygiene"}
ERRANDS = {"uuid": "P-ERR", "type": "project", "title": "Errands"}
AREA = {"uuid": "A-HOME", "type": "area", "title": "Home"}
HEADINGS = [
    {"uuid": "H-FACE", "type": "heading", "title": "Face", "project": "P-HYG"},
    {"uuid": "H-BODY", "type": "heading", "title": "Body", "project": "P-HYG"},
    {"uuid": "H-SHAVE", "type": "heading", "title": "Shaving", "project": "P-HYG"},
    {"uuid": "H-TEETH", "type": "heading", "title": "Teeth", "project": "P-HYG"},
]
TODO_IN_PROJECT = {"uuid": "T-1", "type": "to-do", "title": "Floss", "project": "P-HYG", "heading": None}
TODO_UNDER_HEADING = {"uuid": "T-2", "type": "to-do", "title": "Scrub", "project": None, "heading": "H-BODY", "heading_title": "Body"}
TODO_LOOSE = {"uuid": "T-3", "type": "to-do", "title": "Loose", "project": None, "heading": None}

ITEMS = {i["uuid"]: i for i in [HYGIENE, ERRANDS, AREA, *HEADINGS, TODO_IN_PROJECT, TODO_UNDER_HEADING, TODO_LOOSE]}


@pytest.fixture(autouse=True)
def fake_things():
    def tasks(type=None, project=None, **_):
        return [h for h in HEADINGS if h["project"] == project] if type == "heading" else []

    with (
        patch("things.get", side_effect=ITEMS.get),
        patch("things.projects", return_value=[HYGIENE, ERRANDS]),
        patch("things.tasks", side_effect=tasks),
    ):
        yield


@pytest.mark.parametrize("name", ["Body", "body", "  BODY  "])
def test_resolve_heading_case_insensitive_and_trimmed(name):
    assert resolve_heading(name, "P-HYG") == HeadingChange("Body", "H-BODY")


def test_resolve_heading_missing_lists_all_headings():
    with pytest.raises(HeadingError) as e:
        resolve_heading("Hair", "P-HYG")
    assert str(e.value) == "No heading 'Hair' in project 'Hygiene'. Available headings: Face, Body, Shaving, Teeth."


def test_resolve_heading_ambiguous():
    dupes = [*HEADINGS, {"uuid": "H-BODY2", "type": "heading", "title": "body ", "project": "P-HYG"}]
    with patch.object(headings, "list_headings", return_value=dupes), pytest.raises(HeadingError, match="matches 2 headings.*ambiguous.*Available headings: Face, Body, Shaving, Teeth, body"):
        resolve_heading("Body", "P-HYG")


def test_resolve_heading_project_without_headings():
    with pytest.raises(HeadingError, match="Available headings: none"):
        resolve_heading("Body", "P-ERR")


def test_resolve_heading_needs_project():
    with pytest.raises(HeadingError, match="needs a project"):
        resolve_heading("Body", None)


@pytest.mark.parametrize("name", ["", "   "])
def test_resolve_heading_empty_means_move_out(name):
    assert resolve_heading(name, None) == HeadingChange(None, None)


def test_resolve_heading_none():
    assert resolve_heading(None, "P-HYG") is None


@pytest.mark.parametrize(
    ("list_id", "list_title", "expected"),
    [
        ("P-HYG", None, "P-HYG"),
        ("A-HOME", None, None),
        ("MISSING", None, None),
        (None, "hygiene", "P-HYG"),
        (None, "Home", None),
        ("P-ERR", "Hygiene", "P-ERR"),
        (None, None, None),
    ],
)
def test_resolve_add_project(list_id, list_title, expected):
    assert resolve_add_project(list_id, list_title) == expected


@pytest.mark.parametrize(
    ("todo_id", "list_id", "list_name", "expected"),
    [
        ("T-1", None, None, "P-HYG"),  # current project
        ("T-2", None, None, "P-HYG"),  # current project via its heading
        ("T-3", None, None, None),  # not in a project
        ("T-3", "P-HYG", None, "P-HYG"),  # moving by id
        ("T-3", None, "Hygiene", "P-HYG"),  # moving by name
        ("T-1", "A-HOME", None, None),  # moving to an area
        ("T-1", None, "Today", "P-HYG"),  # built-in list keeps the project
        ("T-1", None, "Inbox", None),  # Inbox takes it out of the project
    ],
)
def test_resolve_update_project(todo_id, list_id, list_name, expected):
    assert resolve_update_project(todo_id, list_id, list_name) == expected


def test_resolve_update_project_missing_todo():
    with pytest.raises(HeadingError, match="not found"):
        resolve_update_project("NOPE", None, None)


def test_format_todo_shows_project_and_heading_for_todo_under_heading():
    text = format_todo(TODO_UNDER_HEADING)
    assert "\nProject: Hygiene\nHeading: Body" in text


def test_format_todo_without_heading_has_no_heading_line():
    text = format_todo(TODO_IN_PROJECT)
    assert "Project: Hygiene" in text
    assert "Heading:" not in text


def test_get_headings_lists_in_order():
    assert fast_server.get_headings("P-HYG") == "Title: Face\nUUID: H-FACE\n\n---\n\nTitle: Body\nUUID: H-BODY\n\n---\n\nTitle: Shaving\nUUID: H-SHAVE\n\n---\n\nTitle: Teeth\nUUID: H-TEETH"


def test_get_headings_empty_and_invalid():
    assert fast_server.get_headings("P-ERR") == "No headings in project 'Errands'"
    assert fast_server.get_headings("A-HOME").startswith("Error: Invalid project UUID")


def test_get_todos_groups_by_heading_in_display_order():
    todos = [
        {**TODO_UNDER_HEADING, "uuid": "T-teeth", "title": "Brush", "heading": "H-TEETH", "heading_title": "Teeth"},
        {**TODO_IN_PROJECT, "title": "Root one"},
        {**TODO_UNDER_HEADING, "uuid": "T-face", "title": "Wash face", "heading": "H-FACE", "heading_title": "Face"},
        {**TODO_UNDER_HEADING, "title": "Scrub"},
        {**TODO_IN_PROJECT, "uuid": "T-root2", "title": "Root two"},
    ]
    with patch("things.todos", return_value=todos):
        out = fast_server.get_todos("P-HYG")
    titles = [line.removeprefix("Title: ") for line in out.splitlines() if line.startswith("Title: ")]
    assert titles == ["Root one", "Root two", "Wash face", "Scrub", "Brush"]


def test_format_todo_shows_evening_and_reminder():
    todo = {**TODO_IN_PROJECT, "start_date": "2026-09-24"}
    with patch("things3_mcp.formatters.read_schedule_extras", return_value=("21:00", True)):
        text = format_todo(todo)
    assert "\nStart Date: 2026-09-24\nEvening: yes\nReminder: 21:00" in text


def test_format_todo_reminder_only():
    todo = {**TODO_IN_PROJECT, "start_date": "2026-09-24"}
    with patch("things3_mcp.formatters.read_schedule_extras", return_value=("09:00", False)):
        text = format_todo(todo)
    assert "Reminder: 09:00" in text
    assert "Evening" not in text


def test_format_todo_skips_extras_without_start_date():
    with patch("things3_mcp.formatters.read_schedule_extras") as extras:
        text = format_todo(TODO_IN_PROJECT)
    extras.assert_not_called()
    assert "Reminder" not in text
