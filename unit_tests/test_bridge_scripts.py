"""Tests for the AppleScript the bridge generates (no Things app needed)."""

import re
from unittest.mock import patch

import pytest

from things3_mcp import applescript_bridge
from things3_mcp.applescript_bridge import add_project, add_todo, update_project, update_todo

EVIL = 'x" & (do shell script "touch /tmp/pwned") & "'


@pytest.fixture()
def scripts():
    captured = []

    def run(script, timeout=8):
        captured.append(script)
        return "true"

    with patch.object(applescript_bridge, "ensure_things_ready", return_value=True), patch.object(applescript_bridge, "run_applescript", side_effect=run):
        yield captured


def string_literals_are_safe(script):
    # Remove every AppleScript string literal; the payload must only have lived inside them.
    # If a quote had broken out, "do shell script" would be left over as code.
    code = re.sub(r'"(?:[^"\\]|\\.)*"', "", script)
    return "do shell script" not in code


def test_update_todo_escapes_id(scripts):
    update_todo(id=EVIL, title="t")
    assert "to do id (" in scripts[0]
    assert string_literals_are_safe(scripts[0])
    assert "(ASCII character 34)" in scripts[0]


def test_update_todo_escapes_list_id_and_list_name(scripts):
    update_todo(id="T-1", list_id=EVIL, list_name=EVIL)
    assert string_literals_are_safe(scripts[0])
    assert 'return "Error: List/Project/Area not found - " & ' in scripts[0]
    assert 'return "Error: Project/Area not found with ID - " & ' in scripts[0]


def test_add_todo_escapes_list_id(scripts):
    add_todo(title="t", list_id=EVIL)
    assert string_literals_are_safe(scripts[0])


def test_project_functions_escape_ids(scripts):
    update_project(id=EVIL, area_id=EVIL)
    update_project(id="P-1", area_title=EVIL)
    add_project(title="p", area_id=EVIL)
    for script in scripts:
        assert string_literals_are_safe(script)
    assert "project id (" in scripts[0]


def test_plain_id_unchanged(scripts):
    update_todo(id="GmYYp83PUPqVif28j5Nac4", title="t")
    assert 'set theTodo to to do id ("GmYYp83PUPqVif28j5Nac4")' in scripts[0]


@pytest.mark.parametrize(("notes", "expected"), [("", 'set notes of theTodo to ""'), ("hi", 'set notes of theTodo to "hi"')])
def test_update_todo_sets_or_clears_notes(scripts, notes, expected):
    update_todo(id="T-1", notes=notes)
    assert expected in scripts[0]


def test_update_todo_leaves_notes_and_tags_alone_when_none(scripts):
    update_todo(id="T-1", title="t")
    assert "set notes" not in scripts[0]
    assert "set tag names" not in scripts[0]


def test_update_todo_clears_tags(scripts):
    update_todo(id="T-1", tags=[])
    assert 'set tag names of theTodo to ""' in scripts[0]


def test_update_project_clears_notes(scripts):
    update_project(id="P-1", notes="")
    assert 'set notes of theProject to ""' in scripts[0]


def test_safety_check_catches_unescaped_payload():
    # Guard against the check itself being too lenient
    assert not string_literals_are_safe('set theTodo to to do id "x" & (do shell script "touch /tmp/pwned") & ""')
