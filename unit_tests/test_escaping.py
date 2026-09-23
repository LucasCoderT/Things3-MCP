"""Tests for escape_applescript_string."""

import pytest

from things3_mcp.applescript_bridge import escape_applescript_string


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a + b", '"a + b"'),
        ("C++", '"C++"'),
        ("50%20off", '"50%20off"'),
        ("back\\slash", '"back\\\\slash"'),
        ("\\", '"\\\\"'),
        ('say "hi"', '"say " & (ASCII character 34) & "hi" & (ASCII character 34)'),
        ('\\"', '"\\\\" & (ASCII character 34)'),
        ("", '""'),
    ],
)
def test_escape_applescript_string(text, expected):
    assert escape_applescript_string(text) == expected
