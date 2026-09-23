"""Tests for how add_todo/update_todo tools split and apply when values."""

from unittest.mock import patch

import pytest

from things3_mcp import fast_server


@pytest.fixture()
def mocks():
    with (
        patch.object(fast_server, "add_todo", return_value="TODO1") as add_todo,
        patch.object(fast_server, "update_todo", return_value="true") as update_todo,
        patch.object(fast_server, "apply_url_when", return_value=None) as apply_url_when,
        patch("things.get", return_value={"start": "Today"}),
    ):
        yield {"add_todo": add_todo, "update_todo": update_todo, "apply_url_when": apply_url_when}


def test_add_with_time_splits_date_and_reminder(mocks):
    result = fast_server.add_task(title="Call + follow up", when="2026-10-01@2:30pm")
    assert result.startswith("✅")
    assert mocks["add_todo"].call_args.kwargs["when"] == "2026-10-01"
    assert mocks["add_todo"].call_args.kwargs["title"] == "Call + follow up"
    mocks["apply_url_when"].assert_called_once_with("TODO1", "2026-10-01@14:30")


def test_add_evening(mocks):
    fast_server.add_task(title="Read", when="evening")
    assert mocks["add_todo"].call_args.kwargs["when"] == "today"
    mocks["apply_url_when"].assert_called_once_with("TODO1", "evening")


@pytest.mark.parametrize("when", [None, "today", "someday", "2026-10-01"])
def test_add_plain_when_skips_url_step(mocks, when):
    result = fast_server.add_task(title="Plain", when=when)
    assert result.startswith("✅")
    assert mocks["add_todo"].call_args.kwargs["when"] == when
    mocks["apply_url_when"].assert_not_called()


def test_add_bad_when_never_creates(mocks):
    result = fast_server.add_task(title="Nope", when="someday@9am")
    assert result.startswith("⚠️ Error:")
    mocks["add_todo"].assert_not_called()
    mocks["apply_url_when"].assert_not_called()


def test_add_reports_partial_failure(mocks):
    mocks["apply_url_when"].return_value = "THINGS_AUTH_TOKEN is not set."
    result = fast_server.add_task(title="Half done", when="today@18:00")
    assert "Created todo: Half done (ID: TODO1)" in result
    assert "today@18:00" in result
    assert "THINGS_AUTH_TOKEN is not set." in result


def test_add_failed_creation_skips_url_step(mocks):
    mocks["add_todo"].return_value = False
    result = fast_server.add_task(title="Fails", when="evening")
    assert result.startswith("⚠️ Error")
    mocks["apply_url_when"].assert_not_called()


def test_update_with_time(mocks):
    result = fast_server.update_task(id="TODO1", when="evening@9pm")
    assert result.startswith("✅")
    assert mocks["update_todo"].call_args.kwargs["when"] == "today"
    mocks["apply_url_when"].assert_called_once_with("TODO1", "evening@21:00")


def test_update_plain_date_skips_url_step(mocks):
    fast_server.update_task(id="TODO1", when="tomorrow")
    assert mocks["update_todo"].call_args.kwargs["when"] == "tomorrow"
    mocks["apply_url_when"].assert_not_called()


def test_update_bad_when_never_updates(mocks):
    result = fast_server.update_task(id="TODO1", title="Changed", when="anytime@9am")
    assert result.startswith("⚠️ Error:")
    mocks["update_todo"].assert_not_called()


def test_update_reports_partial_failure(mocks):
    mocks["apply_url_when"].return_value = "Could not open Things URL: boom"
    result = fast_server.update_task(id="TODO1", when="today@18:00")
    assert "Updated todo with ID: TODO1" in result
    assert "boom" in result


def test_update_keeps_plus_and_percent_in_text(mocks):
    fast_server.update_task(id="TODO1", title="A+B %20", notes="1+1", list_name="R&D + Ops")
    kwargs = mocks["update_todo"].call_args.kwargs
    assert kwargs["title"] == "A+B %20"
    assert kwargs["notes"] == "1+1"
    assert kwargs["list_name"] == "R&D + Ops"
