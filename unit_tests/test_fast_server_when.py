"""Tests for how add_todo/update_todo tools split and apply when values and checklist items."""

from unittest.mock import patch

import pytest

from things3_mcp import fast_server
from things3_mcp.headings import HeadingError
from things3_mcp.url_scheme import ChecklistUpdate, HeadingChange


@pytest.fixture()
def mocks():
    with (
        patch.object(fast_server, "add_todo", return_value="TODO1") as add_todo,
        patch.object(fast_server, "update_todo", return_value="true") as update_todo,
        patch.object(fast_server, "apply_url_update", return_value=None) as apply_url_update,
        patch("things.get", return_value={"start": "Today"}),
    ):
        yield {"add_todo": add_todo, "update_todo": update_todo, "apply_url_update": apply_url_update}


def test_add_with_time_splits_date_and_reminder(mocks):
    result = fast_server.add_task(title="Call + follow up", when="2026-10-01@2:30pm")
    assert result.startswith("✅")
    assert mocks["add_todo"].call_args.kwargs["when"] == "2026-10-01"
    assert mocks["add_todo"].call_args.kwargs["title"] == "Call + follow up"
    mocks["apply_url_update"].assert_called_once_with("TODO1", when="2026-10-01@14:30", checklist=None, heading=None)


def test_add_evening(mocks):
    fast_server.add_task(title="Read", when="evening")
    assert mocks["add_todo"].call_args.kwargs["when"] == "today"
    mocks["apply_url_update"].assert_called_once_with("TODO1", when="evening", checklist=None, heading=None)


@pytest.mark.parametrize("when", [None, "today", "someday", "2026-10-01"])
def test_add_plain_when_skips_url_step(mocks, when):
    result = fast_server.add_task(title="Plain", when=when)
    assert result.startswith("✅")
    assert mocks["add_todo"].call_args.kwargs["when"] == when
    mocks["apply_url_update"].assert_not_called()


def test_add_bad_when_never_creates(mocks):
    result = fast_server.add_task(title="Nope", when="someday@9am")
    assert result.startswith("⚠️ Error:")
    mocks["add_todo"].assert_not_called()
    mocks["apply_url_update"].assert_not_called()


def test_add_reports_partial_failure(mocks):
    mocks["apply_url_update"].return_value = "THINGS_AUTH_TOKEN is not set."
    result = fast_server.add_task(title="Half done", when="today@18:00")
    assert "Created todo: Half done (ID: TODO1)" in result
    assert "today@18:00" in result
    assert "THINGS_AUTH_TOKEN is not set." in result


def test_add_failed_creation_skips_url_step(mocks):
    mocks["add_todo"].return_value = False
    result = fast_server.add_task(title="Fails", when="evening")
    assert result.startswith("⚠️ Error")
    mocks["apply_url_update"].assert_not_called()


def test_update_with_time(mocks):
    result = fast_server.update_task(id="TODO1", when="evening@9pm")
    assert result.startswith("✅")
    assert mocks["update_todo"].call_args.kwargs["when"] == "today"
    mocks["apply_url_update"].assert_called_once_with("TODO1", when="evening@21:00", checklist=None, heading=None)


def test_update_plain_date_skips_url_step(mocks):
    fast_server.update_task(id="TODO1", when="tomorrow")
    assert mocks["update_todo"].call_args.kwargs["when"] == "tomorrow"
    mocks["apply_url_update"].assert_not_called()


def test_update_bad_when_never_updates(mocks):
    result = fast_server.update_task(id="TODO1", title="Changed", when="anytime@9am")
    assert result.startswith("⚠️ Error:")
    mocks["update_todo"].assert_not_called()


def test_update_reports_partial_failure(mocks):
    mocks["apply_url_update"].return_value = "Could not open Things URL: boom"
    result = fast_server.update_task(id="TODO1", when="today@18:00")
    assert "Updated todo with ID: TODO1" in result
    assert "boom" in result


def test_update_keeps_plus_and_percent_in_text(mocks):
    fast_server.update_task(id="TODO1", title="A+B %20", notes="1+1", list_name="R&D + Ops")
    kwargs = mocks["update_todo"].call_args.kwargs
    assert kwargs["title"] == "A+B %20"
    assert kwargs["notes"] == "1+1"
    assert kwargs["list_name"] == "R&D + Ops"


def test_add_with_checklist_only(mocks):
    result = fast_server.add_task(title="Groceries", checklist_items=["Eggs", "", "Milk + honey"])
    assert result.startswith("✅")
    assert mocks["add_todo"].call_args.kwargs["when"] is None
    mocks["apply_url_update"].assert_called_once_with("TODO1", when=None, checklist=ChecklistUpdate(("Eggs", "Milk + honey"), "replace"), heading=None)


def test_add_with_checklist_and_when_makes_one_call(mocks):
    fast_server.add_task(title="Groceries", when="evening@6pm", checklist_items=["Eggs"])
    mocks["apply_url_update"].assert_called_once_with("TODO1", when="evening@18:00", checklist=ChecklistUpdate(("Eggs",), "replace"), heading=None)


def test_add_accepts_stringified_checklist_array(mocks):
    fast_server.add_task(title="Groceries", checklist_items='["Eggs", "Milk"]')
    assert mocks["apply_url_update"].call_args.kwargs["checklist"] == ChecklistUpdate(("Eggs", "Milk"), "replace")


def test_add_blank_checklist_skips_url_step(mocks):
    fast_server.add_task(title="Groceries", checklist_items=["", " "])
    mocks["apply_url_update"].assert_not_called()


@pytest.mark.parametrize("items", [["a\nb"], [f"i{n}" for n in range(101)]])
def test_add_bad_checklist_never_creates(mocks, items):
    result = fast_server.add_task(title="Nope", checklist_items=items)
    assert result.startswith("⚠️ Error:")
    mocks["add_todo"].assert_not_called()
    mocks["apply_url_update"].assert_not_called()


def test_add_reports_checklist_partial_failure(mocks):
    mocks["apply_url_update"].return_value = "THINGS_AUTH_TOKEN is not set."
    result = fast_server.add_task(title="Groceries", checklist_items=["Eggs", "Milk"])
    assert "Created todo: Groceries (ID: TODO1)" in result
    assert "set 2 checklist item(s)" in result
    assert "THINGS_AUTH_TOKEN is not set." in result


@pytest.mark.parametrize("mode", ["replace", "append", "prepend"])
def test_update_checklist_modes(mocks, mode):
    result = fast_server.update_task(id="TODO1", checklist_items=["More"], checklist_mode=mode)
    assert result.startswith("✅")
    mocks["apply_url_update"].assert_called_once_with("TODO1", when=None, checklist=ChecklistUpdate(("More",), mode), heading=None)


def test_update_bad_checklist_mode_never_updates(mocks):
    result = fast_server.update_task(id="TODO1", title="Changed", checklist_items=["x"], checklist_mode="merge")
    assert result.startswith("⚠️ Error:")
    mocks["update_todo"].assert_not_called()


def test_update_failed_applescript_skips_url_step(mocks):
    mocks["update_todo"].return_value = "Error: Can't get to do id"
    result = fast_server.update_task(id="MISSING", checklist_items=["x"])
    assert result.startswith("Error:")
    mocks["apply_url_update"].assert_not_called()


def test_update_reports_checklist_partial_failure(mocks):
    mocks["apply_url_update"].return_value = "Could not open Things URL: boom"
    result = fast_server.update_task(id="TODO1", when="evening", checklist_items=["x"], checklist_mode="append")
    assert "Updated todo with ID: TODO1, but could not set when='evening' and append 1 checklist item(s)" in result


def test_add_with_heading_when_and_checklist_makes_one_call(mocks):
    with (
        patch.object(fast_server, "resolve_add_project", return_value="PROJ") as resolve_project,
        patch.object(fast_server, "resolve_heading", return_value=HeadingChange("Body", "H-BODY")) as resolve_heading,
    ):
        result = fast_server.add_task(title="Scrub", list_title="Hygiene", heading="body", when="today@18:00", checklist_items=["Soap"])
    assert result.startswith("✅")
    assert "heading: Body" in result
    resolve_project.assert_called_once_with(None, "Hygiene")
    resolve_heading.assert_called_once_with("body", "PROJ")
    mocks["apply_url_update"].assert_called_once_with("TODO1", when="today@18:00", checklist=ChecklistUpdate(("Soap",), "replace"), heading=HeadingChange("Body", "H-BODY"))


def test_add_bad_heading_never_creates(mocks):
    with (
        patch.object(fast_server, "resolve_add_project", return_value="PROJ"),
        patch.object(fast_server, "resolve_heading", side_effect=HeadingError("No heading 'Nope'. Available headings: Face, Body.")),
    ):
        result = fast_server.add_task(title="Scrub", list_title="Hygiene", heading="Nope")
    assert result == "⚠️ Error: No heading 'Nope'. Available headings: Face, Body."
    mocks["add_todo"].assert_not_called()
    mocks["apply_url_update"].assert_not_called()


def test_add_blank_heading_is_ignored(mocks):
    with patch.object(fast_server, "resolve_heading") as resolve_heading:
        fast_server.add_task(title="Scrub", heading="  ")
    resolve_heading.assert_not_called()
    mocks["apply_url_update"].assert_not_called()


def test_add_reports_heading_partial_failure(mocks):
    mocks["apply_url_update"].return_value = "THINGS_AUTH_TOKEN is not set."
    with (
        patch.object(fast_server, "resolve_add_project", return_value="PROJ"),
        patch.object(fast_server, "resolve_heading", return_value=HeadingChange("Body", "H-BODY")),
    ):
        result = fast_server.add_task(title="Scrub", list_id="PROJ", heading="Body")
    assert "Created todo: Scrub (ID: TODO1), but could not move it under heading 'Body'" in result


def test_update_with_heading_resolves_against_target_project(mocks):
    with (
        patch.object(fast_server, "resolve_update_project", return_value="PROJ") as resolve_project,
        patch.object(fast_server, "resolve_heading", return_value=HeadingChange("Face", "H-FACE")),
    ):
        result = fast_server.update_task(id="TODO1", heading="Face", list_name="Hygiene")
    assert result.startswith("✅")
    resolve_project.assert_called_once_with("TODO1", None, "Hygiene")
    mocks["apply_url_update"].assert_called_once_with("TODO1", when=None, checklist=None, heading=HeadingChange("Face", "H-FACE"))


def test_update_empty_heading_moves_out_without_project_lookup(mocks):
    with patch.object(fast_server, "resolve_update_project") as resolve_project:
        fast_server.update_task(id="TODO1", heading="")
    resolve_project.assert_not_called()
    mocks["apply_url_update"].assert_called_once_with("TODO1", when=None, checklist=None, heading=HeadingChange(None, None))


def test_update_bad_heading_never_updates(mocks):
    with (
        patch.object(fast_server, "resolve_update_project", return_value=None),
        patch.object(fast_server, "resolve_heading", side_effect=HeadingError("needs a project")),
    ):
        result = fast_server.update_task(id="TODO1", title="Changed", heading="Body")
    assert result.startswith("⚠️ Error:")
    mocks["update_todo"].assert_not_called()
