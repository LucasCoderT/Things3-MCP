"""Tests for the Things URL scheme helpers."""

import subprocess
from datetime import date
from unittest.mock import patch

import pytest

from things3_mcp.url_scheme import (
    ChecklistError,
    ChecklistUpdate,
    HeadingChange,
    ParsedWhen,
    WhenParseError,
    apply_url_update,
    build_update_url,
    describe_url_update,
    normalize_time,
    parse_checklist,
    parse_when,
    reject_past_date,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("18:00", "18:00"),
        ("9:05", "09:05"),
        ("0:00", "00:00"),
        ("23:59", "23:59"),
        ("6pm", "18:00"),
        ("6:30 PM", "18:30"),
        ("6:30pm", "18:30"),
        ("12am", "00:00"),
        ("12pm", "12:00"),
        ("12:15am", "00:15"),
        ("9am", "09:00"),
        (" 7 am ", "07:00"),
    ],
)
def test_normalize_time_valid(value, expected):
    assert normalize_time(value) == expected


@pytest.mark.parametrize("value", ["", "18", "24:00", "12:60", "13pm", "0am", "6:5pm", "noon", "18:00:00", "6 o'clock"])
def test_normalize_time_invalid(value):
    with pytest.raises(WhenParseError):
        normalize_time(value)


@pytest.mark.parametrize(
    ("when", "applescript_when", "url_when"),
    [
        (None, None, None),
        ("", None, None),
        ("today", "today", None),
        ("tomorrow", "tomorrow", None),
        ("anytime", "anytime", None),
        ("someday", "someday", None),
        ("2026-10-01", "2026-10-01", None),
        ("evening", "today", "evening"),
        ("today@18:00", "today", "today@18:00"),
        ("tomorrow@9am", "tomorrow", "tomorrow@09:00"),
        ("2026-10-01@14:30", "2026-10-01", "2026-10-01@14:30"),
        ("evening@6pm", "today", "evening@18:00"),
        ("evening@9:30 PM", "today", "evening@21:30"),
    ],
)
def test_parse_when(when, applescript_when, url_when):
    parsed = parse_when(when)
    assert parsed == ParsedWhen(applescript_when, url_when)
    assert parsed.needs_url_scheme is (url_when is not None)


@pytest.mark.parametrize(
    ("when", "message"),
    [
        ("anytime@9am", "cannot have a reminder time"),
        ("someday@9am", "cannot have a reminder time"),
        ("2026-13-01", "Unsupported when value"),
        ("2026-02-30@9am", "Unsupported date"),
        ("next week", "Unsupported when value"),
        ("today@noon", "Could not understand time"),
        ("today@25:00", "out of range"),
        ("today@", "Could not understand time"),
    ],
)
def test_parse_when_rejects(when, message):
    with pytest.raises(WhenParseError, match=message):
        parse_when(when)


def test_build_update_url_uses_percent_encoding():
    url = build_update_url("ABC123", "tok en+/=", when="evening@18:00")
    assert url == "things:///update?id=ABC123&when=evening%4018%3A00&auth-token=tok%20en%2B%2F%3D"
    assert "+" not in url


def test_apply_url_update_missing_token(monkeypatch):
    monkeypatch.delenv("THINGS_AUTH_TOKEN", raising=False)
    with patch("things3_mcp.url_scheme.subprocess.run") as run:
        error = apply_url_update("ABC123", when="evening")
    assert error is not None
    assert "THINGS_AUTH_TOKEN" in error
    run.assert_not_called()


def test_apply_url_update_opens_in_background(monkeypatch):
    monkeypatch.setenv("THINGS_AUTH_TOKEN", "secret")
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("things3_mcp.url_scheme.subprocess.run", return_value=completed) as run:
        assert apply_url_update("ABC123", when="today@18:00") is None
    args = run.call_args.args[0]
    assert args == ["open", "-g", "things:///update?id=ABC123&when=today%4018%3A00&auth-token=secret"]


def test_apply_url_update_reports_open_failure(monkeypatch):
    monkeypatch.setenv("THINGS_AUTH_TOKEN", "secret")
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="LSOpenURLsWithRole() failed")
    with patch("things3_mcp.url_scheme.subprocess.run", return_value=completed):
        error = apply_url_update("ABC123", when="evening")
    assert error is not None
    assert "LSOpenURLsWithRole" in error


def test_build_update_url_with_when_and_checklist():
    checklist = ChecklistUpdate(("Eggs", "Milk + honey"))
    url = build_update_url("ABC123", "secret", when="today@18:00", checklist=checklist)
    assert url == "things:///update?id=ABC123&when=today%4018%3A00&checklist-items=Eggs%0AMilk%20%2B%20honey&auth-token=secret"


def test_build_update_url_checklist_only():
    url = build_update_url("ABC123", "secret", checklist=ChecklistUpdate(("A", "B")))
    assert "when=" not in url
    assert "checklist-items=A%0AB" in url


@pytest.mark.parametrize(
    ("mode", "param"),
    [("replace", "checklist-items"), ("append", "append-checklist-items"), ("prepend", "prepend-checklist-items")],
)
def test_build_update_url_checklist_modes(mode, param):
    url = build_update_url("ABC123", "secret", checklist=parse_checklist(["X"], mode))
    assert f"&{param}=X&" in url
    assert url.count("checklist-items") == 1


def test_parse_checklist_drops_blanks_and_keeps_text_exact():
    parsed = parse_checklist(["  Eggs ", "", "   ", 'a+b %20 \\ "q"'])
    assert parsed == ChecklistUpdate(("  Eggs ", 'a+b %20 \\ "q"'), "replace")


@pytest.mark.parametrize("items", [None, [], ["", "  "]])
def test_parse_checklist_nothing_to_do(items):
    assert parse_checklist(items) is None


def test_parse_checklist_single_string_is_one_item():
    assert parse_checklist("Only one").items == ("Only one",)


def test_parse_checklist_allows_100_items():
    assert len(parse_checklist([f"item {i}" for i in range(100)]).items) == 100


@pytest.mark.parametrize(
    ("items", "mode", "message"),
    [
        (["a\nb"], "replace", "contains a newline"),
        (["a\rb"], "replace", "contains a newline"),
        ("line one\nline two", "replace", "contains a newline"),
        ([f"item {i}" for i in range(101)], "replace", "at most 100"),
        (["ok", 3], "replace", "must be strings"),
        (["ok"], "overwrite", "Unknown checklist_mode"),
        (None, "overwrite", "Unknown checklist_mode"),
    ],
)
def test_parse_checklist_rejects(items, mode, message):
    with pytest.raises(ChecklistError, match=message):
        parse_checklist(items, mode)


def test_describe_url_update():
    assert describe_url_update("evening", None) == "set when='evening'"
    assert describe_url_update(None, ChecklistUpdate(("a",), "append")) == "append 1 checklist item(s)"
    assert describe_url_update("today@18:00", ChecklistUpdate(("a", "b"))) == "set when='today@18:00' and set 2 checklist item(s)"


def test_apply_url_update_sends_one_url_with_everything(monkeypatch):
    monkeypatch.setenv("THINGS_AUTH_TOKEN", "secret")
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("things3_mcp.url_scheme.subprocess.run", return_value=completed) as run:
        assert apply_url_update("ABC123", when="evening", checklist=ChecklistUpdate(("A", "B"), "prepend")) is None
    run.assert_called_once()
    assert run.call_args.args[0] == ["open", "-g", "things:///update?id=ABC123&when=evening&prepend-checklist-items=A%0AB&auth-token=secret"]


def test_build_update_url_with_heading_when_and_checklist():
    url = build_update_url("ABC123", "secret", when="today@18:00", checklist=ChecklistUpdate(("Soap", "Scrub")), heading=HeadingChange("Body", "H-BODY"))
    assert url == "things:///update?id=ABC123&when=today%4018%3A00&checklist-items=Soap%0AScrub&heading-id=H-BODY&auth-token=secret"


def test_build_update_url_clears_heading_with_empty_heading():
    url = build_update_url("ABC123", "secret", heading=HeadingChange(None, None))
    assert url == "things:///update?id=ABC123&heading=&auth-token=secret"


def test_describe_url_update_heading():
    assert describe_url_update(heading=HeadingChange("Body", "H")) == "move it under heading 'Body'"
    assert describe_url_update(heading=HeadingChange(None, None)) == "move it out of its heading"


@pytest.mark.parametrize("when", ["2020-01-01", "2020-01-01@9am", " 2020-01-01 "])
def test_parse_when_rejects_past_dates(when):
    with pytest.raises(WhenParseError, match="is in the past"):
        parse_when(when)


def test_parse_when_accepts_today_as_a_date():
    today = date.today().isoformat()
    assert parse_when(today) == ParsedWhen(today, None)
    assert parse_when(f"{today}@23:59") == ParsedWhen(today, f"{today}@23:59")


@pytest.mark.parametrize("when", [None, "", "today", "someday", "2999-01-01", "evening@6pm"])
def test_reject_past_date_allows(when):
    reject_past_date(when)
