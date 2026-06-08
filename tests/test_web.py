import pytest
from pathlib import Path
from datetime import datetime
import tempfile

from fastapi.testclient import TestClient

from src.web.app import create_app
from src.config import Config
from src.storage import Storage, Event


@pytest.fixture
def temp_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Storage(Path(tmpdir))


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def client(config, temp_storage):
    app = create_app(config, temp_storage)
    return TestClient(app)


def test_get_status(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_list_events_empty(client):
    response = client.get("/api/events")
    assert response.status_code == 200
    data = response.json()
    assert data["events"] == []
    assert data["total"] == 0


def test_list_events_with_data(client, temp_storage):
    event = Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
    )
    temp_storage.save_event(event)

    response = client.get("/api/events")
    assert response.status_code == 200
    data = response.json()
    assert len(data["events"]) == 1
    assert data["events"][0]["bark_count"] == 3


def test_flag_event(client, temp_storage):
    event = Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
    )
    event_id = temp_storage.save_event(event)

    response = client.post(
        f"/api/events/{event_id}/flag",
        json={"reason": "test"},
    )
    assert response.status_code == 200

    retrieved = temp_storage.get_event(event_id)
    assert retrieved.is_false_pos is True
