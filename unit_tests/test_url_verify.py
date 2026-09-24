"""Tests for checking that a URL scheme update actually landed."""

import subprocess
from unittest.mock import patch

import pytest

from things3_mcp import url_scheme
from things3_mcp.things_db import TodoState
from things3_mcp.url_scheme import ChecklistUpdate, HeadingChange, apply_url_update, find_unapplied, wait_for_url_update


def state(reminder=None, evening=False, heading=None, checklist=()):
    return TodoState(reminder=reminder, evening=evening, heading=heading, checklist=tuple(checklist))


@pytest.mark.parametrize(
    ("after", "when", "missing"),
    [
        (state(evening=True), "evening", []),
        (state(), "evening", ["This Evening"]),
        (state(evening=True, reminder="18:00"), "evening@18:00", []),
        (state(evening=True, reminder="17:00"), "evening@18:00", ["reminder at 18:00"]),
        (state(), "evening@18:00", ["This Evening", "reminder at 18:00"]),
        (state(reminder="09:30"), "2026-10-01@09:30", []),
        (state(), "today@09:30", ["reminder at 09:30"]),
    ],
)
def test_find_unapplied_when(after, when, missing):
    assert find_unapplied(state(), after, when=when) == missing


@pytest.mark.parametrize(
    ("before", "after", "mode", "items", "landed"),
    [
        (["Old"], ["A", "B"], "replace", ("A", "B"), True),
        (["Old"], ["Old"], "replace", ("A", "B"), False),
        ([], ["A ", "B"], "replace", ("A", "B"), True),  # Things may trim whitespace
        (["X"], ["X", "A"], "append", ("A",), True),
        (["A"], ["A"], "append", ("A",), False),  # same text already there, nothing added
        (["X"], ["A", "X"], "prepend", ("A",), True),
        (["X"], ["X", "A"], "prepend", ("A",), False),
    ],
)
def test_find_unapplied_checklist(before, after, mode, items, landed):
    missing = find_unapplied(state(checklist=before), state(checklist=after), checklist=ChecklistUpdate(items, mode))
    assert missing == ([] if landed else ["checklist items"])


def test_find_unapplied_heading():
    body = HeadingChange("Body", "H-BODY")
    assert find_unapplied(state(), state(heading="H-BODY"), heading=body) == []
    assert find_unapplied(state(), state(heading="H-FACE"), heading=body) == ["heading 'Body'"]
    assert find_unapplied(state(), state(), heading=HeadingChange(None, None)) == []
    assert find_unapplied(state(), state(heading="H-FACE"), heading=HeadingChange(None, None)) == ["moving out of its heading"]


def test_wait_returns_once_things_catches_up():
    reads = [state(), state(), state(evening=True)]
    with patch.object(url_scheme, "read_todo_state", side_effect=reads) as read:
        assert wait_for_url_update("T-1", state(), when="evening", timeout=5, interval=0) is None
    assert read.call_count == 3


def test_wait_times_out_and_blames_the_token():
    with patch.object(url_scheme, "read_todo_state", return_value=state()):
        error = wait_for_url_update("T-1", state(), when="evening@18:00", timeout=0.05, interval=0.01)
    assert error.startswith("Things didn't apply This Evening, reminder at 18:00 within 0.05s.")
    assert "THINGS_AUTH_TOKEN is wrong or out of date" in error


def test_wait_reports_missing_todo():
    with patch.object(url_scheme, "read_todo_state", return_value=None):
        assert "could not be found" in wait_for_url_update("T-1", state(), when="evening", timeout=0)


def test_wait_gives_up_quietly_if_db_unreadable():
    # The autouse fixture makes the database unreadable: nothing to check against, so don't claim failure
    assert wait_for_url_update("T-1", None, when="evening", timeout=0) is None


def test_apply_url_update_reads_before_and_checks_after(monkeypatch):
    monkeypatch.setenv("THINGS_AUTH_TOKEN", "secret")
    before = state(checklist=["X"])
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    checklist = ChecklistUpdate(("A",), "append")
    with (
        patch.object(url_scheme, "read_todo_state", return_value=before),
        patch("things3_mcp.url_scheme.subprocess.run", return_value=completed),
        patch.object(url_scheme, "wait_for_url_update", return_value="Things didn't apply checklist items") as wait,
    ):
        error = apply_url_update("T-1", checklist=checklist)
    assert error == "Things didn't apply checklist items"
    wait.assert_called_once_with("T-1", before, when=None, checklist=checklist, heading=None)
