from datetime import date
from unittest.mock import MagicMock

import pytest
from io import BytesIO
from fastapi import HTTPException, UploadFile
from starlette.requests import Request

import database
import main
from parsing import parse_grid_cell


def entry():
    return {"course": "Ecology", "course_type": "lecture", "teacher": "T",
            "location": "101", "date": "2026-09-07", "periods": [1, 2]}


def connection(monkeypatch):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(database, "connect", lambda: conn)
    return conn, cursor


def test_import_commits_once_and_deduplicates_input(monkeypatch):
    conn, cursor = connection(monkeypatch)
    cursor.fetchone.side_effect = [{"acquired": 1}, None]
    cursor.fetchall.return_value = [{"id": 3}]
    assert database.import_courses([entry(), entry()]) == {"parsed_count": 1, "added": 1, "skipped": 0}
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    conn.close.assert_called_once()


def test_existing_session_skipped(monkeypatch):
    conn, cursor = connection(monkeypatch)
    cursor.fetchone.side_effect = [{"acquired": 1}, {"id": 9}]
    cursor.fetchall.return_value = [{"id": 3}]
    assert database.import_courses([entry()])["skipped"] == 1
    assert not any("INSERT" in call.args[0] for call in cursor.execute.call_args_list)


def test_database_failure_rolls_back(monkeypatch):
    conn, cursor = connection(monkeypatch)
    cursor.fetchone.return_value = {"acquired": 1}
    cursor.fetchall.side_effect = RuntimeError("simulated failure")
    with pytest.raises(RuntimeError):
        database.import_courses([entry()])
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    conn.close.assert_called_once()


def test_four_period_cell():
    item = parse_grid_cell("Ecology[lecture]\nT\n5-05060708\nLab")
    assert item["periods"] == [5, 6, 7, 8]
    assert item["location"] == "Lab"


def test_frontend_data_shape(monkeypatch):
    _, cursor = connection(monkeypatch)
    cursor.fetchall.return_value = [{"id": 1, "name": "Ecology[lecture]", "teacher": "T",
        "class_date": date(2027, 1, 1), "start_period": 5, "end_period": 8, "location": "Lab"}]
    row = database.read_courses()[0]
    assert row["week"] == 17
    assert row["weekday"] == 5
    assert row["course"] == "Ecology"
    assert row["periods"] == [5, 6, 7, 8]


def test_upload_and_read_routes(monkeypatch):
    saved = []
    monkeypatch.setattr(main, "parse_file", lambda name, data: [entry()])
    def save(entries):
        saved.extend(entries)
        return {"parsed_count": 1, "added": 1, "skipped": 0}
    monkeypatch.setattr(main, "import_courses", save)
    monkeypatch.setattr(main, "read_courses", lambda: saved)
    request = Request({"type": "http", "scheme": "http", "path": "/api/parse",
                       "headers": [], "server": ("localhost", 8000)})
    response = main.parse_upload(request, UploadFile(BytesIO(b"example"), filename="test.xls"))
    assert response["added"] == 1
    assert main.get_courses() == saved
    assert main.index().path.name == "index.html"
    with pytest.raises(HTTPException) as error:
        main.parse_upload(request, UploadFile(BytesIO(b""), filename="test.xls"))
    assert error.value.status_code == 400
    request = Request({"type": "http", "scheme": "http", "path": "/api/parse",
                       "headers": [(b"origin", b"https://other.example")],
                       "server": ("localhost", 8000)})
    with pytest.raises(HTTPException) as error:
        main.parse_upload(request, UploadFile(BytesIO(b"example"), filename="test.xls"))
    assert error.value.status_code == 403
