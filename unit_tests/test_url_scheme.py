"""Tests for the Things URL scheme helpers."""

import subprocess
from unittest.mock import patch

import pytest

from things3_mcp.url_scheme import (
    ParsedWhen,
    WhenParseError,
    apply_url_when,
    build_update_url,
    normalize_time,
    parse_when,
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
    url = build_update_url("ABC123", "evening@18:00", "tok en+/=")
    assert url == "things:///update?id=ABC123&when=evening%4018%3A00&auth-token=tok%20en%2B%2F%3D"
    assert "+" not in url


def test_apply_url_when_missing_token(monkeypatch):
    monkeypatch.delenv("THINGS_AUTH_TOKEN", raising=False)
    with patch("things3_mcp.url_scheme.subprocess.run") as run:
        error = apply_url_when("ABC123", "evening")
    assert error is not None
    assert "THINGS_AUTH_TOKEN" in error
    run.assert_not_called()


def test_apply_url_when_opens_in_background(monkeypatch):
    monkeypatch.setenv("THINGS_AUTH_TOKEN", "secret")
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("things3_mcp.url_scheme.subprocess.run", return_value=completed) as run:
        assert apply_url_when("ABC123", "today@18:00") is None
    args = run.call_args.args[0]
    assert args == ["open", "-g", "things:///update?id=ABC123&when=today%4018%3A00&auth-token=secret"]


def test_apply_url_when_reports_open_failure(monkeypatch):
    monkeypatch.setenv("THINGS_AUTH_TOKEN", "secret")
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="LSOpenURLsWithRole() failed")
    with patch("things3_mcp.url_scheme.subprocess.run", return_value=completed):
        error = apply_url_when("ABC123", "evening")
    assert error is not None
    assert "LSOpenURLsWithRole" in error
