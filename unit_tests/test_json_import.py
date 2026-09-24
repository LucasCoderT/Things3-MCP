"""Tests for batch todos and projects with headings via things:///json."""

import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from things3_mcp import fast_server, json_import
from things3_mcp.json_import import (
    MAX_ITEMS,
    JsonImportError,
    PreparedImport,
    build_json_url,
    import_project,
    import_todos,
    match_created,
    prepare_project,
    prepare_todos,
    send_import,
)

HYGIENE = {"uuid": "P-HYG", "type": "project", "title": "Hygiene"}
HOME = {"uuid": "A-HOME", "type": "area", "title": "Home"}
BODY = {"uuid": "H-BODY", "type": "heading", "title": "Body", "project": "P-HYG"}
ITEMS = {i["uuid"]: i for i in [HYGIENE, HOME, BODY]}


@pytest.fixture(autouse=True)
def fake_things():
    def tasks(type=None, project=None, **_):
        return [BODY] if type == "heading" and project == "P-HYG" else []

    with (
        patch("things.get", side_effect=ITEMS.get),
        patch("things.projects", return_value=[HYGIENE]),
        patch("things.areas", return_value=[HOME]),
        patch("things.tags", return_value=[{"title": "Errand"}]),
        patch("things.tasks", side_effect=tasks),
    ):
        yield


# prepare_todos


def test_prepare_todos_builds_every_field():
    prepared = prepare_todos(
        [
            {
                "title": "Shower + shave",
                "notes": "n",
                "when": "evening@6pm",
                "deadline": "2999-01-01",
                "tags": ["errand", "New Tag"],
                "checklist_items": ["Soap", ""],
                "list_title": "hygiene",
                "heading": "body",
            },
            {"title": "Plain", "when": "today", "list_id": "A-HOME"},
        ]
    )
    assert prepared.items == [
        {
            "type": "to-do",
            "attributes": {
                "title": "Shower + shave",
                "notes": "n",
                "when": "evening@18:00",
                "deadline": "2999-01-01",
                "tags": ["Errand", "New Tag"],
                "checklist-items": [{"type": "checklist-item", "attributes": {"title": "Soap"}}],
                "list-id": "P-HYG",
                "heading-id": "H-BODY",
            },
        },
        {"type": "to-do", "attributes": {"title": "Plain", "when": "today", "list-id": "A-HOME"}},
    ]
    assert prepared.titles == ["Shower + shave", "Plain"]
    assert prepared.new_tags == ["New Tag"]


def test_prepare_todos_dedupes_new_tags_case_insensitively():
    prepared = prepare_todos([{"title": "a", "tags": ["Fresh"]}, {"title": "b", "tags": ["fresh", "FRESH"]}])
    assert prepared.new_tags == ["Fresh"]
    assert prepared.items[1]["attributes"]["tags"] == ["Fresh", "Fresh"]


@pytest.mark.parametrize(
    ("todos", "message"),
    [
        ([], "non-empty array"),
        ("nope", "non-empty array"),
        ([{"title": f"t{i}"} for i in range(MAX_ITEMS + 1)], "at most 100"),
        (["just a string"], "Todo 1 must be an object"),
        ([{"notes": "no title"}], "Todo 1: title must be a non-empty string"),
        ([{"title": "ok"}, {"title": "  "}], "Todo 2: title must be"),
        ([{"title": "a", "due": "x"}], "Todo 1 ('a'): Unknown field(s) due"),
        ([{"title": "a", "when": "2020-01-01"}], "is in the past"),
        ([{"title": "a", "when": "someday@9am"}], "cannot have a reminder time"),
        ([{"title": "a", "deadline": "tomorrow"}], "must be YYYY-MM-DD"),
        ([{"title": "a", "checklist_items": ["x\ny"]}], "contains a newline"),
        ([{"title": "a", "tags": "x", "list_title": "Nowhere"}], "No project or area named 'Nowhere'"),
        ([{"title": "a", "list_id": "MISSING"}], "No project or area with ID 'MISSING'"),
        ([{"title": "a", "list_title": "Hygiene", "heading": "Hair"}], "No heading 'Hair' in project 'Hygiene'. Available headings: Body."),
        ([{"title": "a", "list_title": "Home", "heading": "Body"}], "needs a project"),
        ([{"title": "a", "heading": 3}], "heading must be a string"),
    ],
)
def test_prepare_todos_rejects(todos, message):
    with pytest.raises(JsonImportError, match=message.replace("(", r"\(").replace(")", r"\)")):
        prepare_todos(todos)


# prepare_project


def test_prepare_project_orders_items():
    prepared = prepare_project(title="Morning", notes="n", when="tomorrow", deadline="2999-01-01", tags=["errand"], area_title="home", todos=["Top"], headings={"Face": ["Wash", "Tone"], "Body": [], "Hair": "Brush"})
    (project,) = prepared.items
    assert project["type"] == "project"
    attributes = project["attributes"]
    assert {k: v for k, v in attributes.items() if k != "items"} == {"title": "Morning", "notes": "n", "when": "tomorrow", "deadline": "2999-01-01", "tags": ["Errand"], "area-id": "A-HOME"}
    assert [(i["type"], i["attributes"]["title"]) for i in attributes["items"]] == [
        ("to-do", "Top"),
        ("heading", "Face"),
        ("to-do", "Wash"),
        ("to-do", "Tone"),
        ("heading", "Body"),
        ("heading", "Hair"),
        ("to-do", "Brush"),
    ]
    assert prepared.titles == ["Morning"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"headings": {}}, "headings must be an object"),
        ({"headings": ["Face"]}, "headings must be an object"),
        ({"headings": {"Face": [], "face ": []}}, "Heading 'face' appears more than once"),
        ({"headings": {" ": []}}, "Each heading title must be"),
        ({"headings": {"Face": [1]}}, "The todos under 'Face' must be an array of strings"),
        ({"headings": {"Face": [f"t{i}" for i in range(MAX_ITEMS)]}}, "at most 100"),
        ({"headings": {"Face": []}, "when": "evening"}, "don't support evening"),
        ({"headings": {"Face": []}, "when": "2020-01-01"}, "is in the past"),
        ({"headings": {"Face": []}, "area_title": "Work"}, "No area named 'Work'. Available areas: Home."),
        ({"headings": {"Face": []}, "area_id": "P-HYG"}, "No area with ID 'P-HYG'"),
        ({"headings": {"Face": []}, "deadline": "soon"}, "must be YYYY-MM-DD"),
    ],
)
def test_prepare_project_rejects(kwargs, message):
    with pytest.raises(JsonImportError, match=message):
        prepare_project(title="P", **kwargs)


# URL, matching, sending


def test_build_json_url_round_trips():
    items = [{"type": "to-do", "attributes": {"title": "Milk + honey & 50%20 off", "notes": "line 1\nline 2 — é"}}]
    url = build_json_url(items, "tok")
    assert url.startswith("things:///json?data=")
    assert "+" not in url
    assert "%5Cn" in url  # the JSON escape for a newline
    query = parse_qs(urlparse(url).query)
    assert json.loads(query["data"][0]) == items
    assert query["auth-token"] == ["tok"]


def test_match_created_handles_repeats_and_gaps():
    rows = [("U1", "Same"), ("U2", "Other"), ("U3", "Same")]
    assert match_created(["Same", "Same", "Other", "Missing"], rows) == ["U1", "U3", "U2", None]


def test_send_import_needs_token(monkeypatch):
    monkeypatch.delenv("THINGS_AUTH_TOKEN", raising=False)
    with patch.object(json_import, "ensure_tags") as ensure, patch.object(json_import, "open_things_url") as open_url:
        assert "THINGS_AUTH_TOKEN is not set" in send_import(PreparedImport([], [], ["New"]))
    ensure.assert_not_called()
    open_url.assert_not_called()


def test_send_import_creates_tags_first(monkeypatch):
    monkeypatch.setenv("THINGS_AUTH_TOKEN", "tok")
    calls = []
    with (
        patch.object(json_import, "ensure_tags", side_effect=lambda names: calls.append(("tags", names)) or "true"),
        patch.object(json_import, "open_things_url", side_effect=lambda url: calls.append(("open", url[:15])) or None),
    ):
        assert send_import(PreparedImport([{"type": "to-do"}], ["t"], ["New"])) is None
    assert calls == [("tags", ["New"]), ("open", "things:///json?")]


def test_send_import_stops_if_tags_fail(monkeypatch):
    monkeypatch.setenv("THINGS_AUTH_TOKEN", "tok")
    with patch.object(json_import, "ensure_tags", return_value="Error: nope"), patch.object(json_import, "open_things_url") as open_url:
        assert send_import(PreparedImport([], [], ["New"])) == "Could not create tags New: Error: nope"
    open_url.assert_not_called()


# import_todos / import_project


def test_import_todos_reports_ids():
    with patch.object(json_import, "send_import", return_value=None), patch.object(json_import, "wait_for_created", return_value=["U1", "U2"]):
        result = import_todos([{"title": "A"}, {"title": "B"}])
    assert result == "✅ Created 2 todos:\n- A (ID: U1)\n- B (ID: U2)"


def test_import_todos_reports_partial():
    with patch.object(json_import, "send_import", return_value=None), patch.object(json_import, "wait_for_created", return_value=["U1", None]):
        result = import_todos([{"title": "A"}, {"title": "B"}])
    assert result.startswith("⚠️ Only 1 of 2 todos showed up in Things.")
    assert "- B (not found)" in result


def test_import_todos_invalid_never_sends():
    with patch.object(json_import, "send_import") as send:
        result = import_todos([{"title": "A"}, {"title": "B", "when": "2020-01-01"}])
    assert result.startswith("⚠️ Error: Todo 2 ('B'): Date 2020-01-01 is in the past")
    send.assert_not_called()


def test_import_todos_send_error():
    with patch.object(json_import, "send_import", return_value="THINGS_AUTH_TOKEN is not set."):
        assert import_todos([{"title": "A"}]) == "⚠️ Error: THINGS_AUTH_TOKEN is not set."


def project_patches(contents, project_id="P-NEW"):
    return (
        patch.object(json_import, "send_import", return_value=None),
        patch.object(json_import, "wait_for_created", return_value=[project_id]),
        patch.object(json_import, "project_contents", return_value=contents),
    )


def test_import_project_success():
    send, wait, contents = project_patches((["Face", "Body"], [("Top", None), ("Wash", "Face")]))
    with send, wait, contents:
        result = import_project(title="Morning", todos=["Top"], headings={"Face": ["Wash"], "Body": []})
    assert result == "✅ Successfully created project: Morning (ID: P-NEW) with 2 headings (Face, Body) and 2 todos"


def test_import_project_mismatch(monkeypatch):
    monkeypatch.setattr(json_import.time, "sleep", lambda _: None)
    monkeypatch.setattr(json_import.time, "monotonic", iter(range(0, 1000, 10)).__next__)
    send, wait, contents = project_patches((["Face"], []))
    with send, wait, contents:
        result = import_project(title="Morning", headings={"Face": ["Wash"], "Body": []})
    assert result.startswith("⚠️ Created project: Morning (ID: P-NEW), but it has 1 headings (Face) and 0 todos; expected 2 headings and 1 todos.")


def test_import_project_not_found():
    send, _, _ = project_patches(([], []))
    with send, patch.object(json_import, "wait_for_created", return_value=[None]):
        result = import_project(title="Morning", headings={"Face": []})
    assert result.startswith("⚠️ Project 'Morning' didn't show up in Things.")


# tool wiring


def test_add_project_with_headings_uses_json():
    with patch.object(fast_server, "import_project", return_value="ok") as json_path, patch.object(fast_server, "add_project") as applescript_path:
        assert fast_server.add_new_project(title="P", todos=["Top"], headings='{"Face": ["Wash"]}', area_title="Home") == "ok"
    applescript_path.assert_not_called()
    kwargs = json_path.call_args.kwargs
    assert kwargs["headings"] == {"Face": ["Wash"]}
    assert kwargs["todos"] == ["Top"]
    assert kwargs["area_title"] == "Home"


def test_add_project_without_headings_uses_applescript():
    with patch.object(fast_server, "import_project") as json_path, patch.object(fast_server, "add_project", return_value="P-1") as applescript_path:
        fast_server.add_new_project(title="P", todos=["Top"])
    json_path.assert_not_called()
    applescript_path.assert_called_once()


def test_add_todos_parses_stringified_array():
    with patch.object(fast_server, "import_todos", return_value="ok") as batch:
        assert fast_server.add_todos('[{"title": "A"}]') == "ok"
    batch.assert_called_once_with([{"title": "A"}])
