"""Shared setup for unit tests that don't need a live Things app."""

import os
import sqlite3
import sys

import pytest

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def no_real_things_db(monkeypatch):
    """Keep unit tests away from the real Things database.

    Reads fail as if the database were missing: formatters leave out the
    reminder/evening lines and URL updates skip the read-back check. Tests
    that need those paths patch the readers themselves.
    """
    from things3_mcp import things_db

    def refuse():
        raise sqlite3.OperationalError("unit tests don't read the real Things database")

    monkeypatch.setattr(things_db, "_connect", refuse)
