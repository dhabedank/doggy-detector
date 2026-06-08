import pytest
from pathlib import Path
import tempfile
import sqlite3
from datetime import datetime

from src.storage import Storage, Event


@pytest.fixture
def temp_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Storage(Path(tmpdir))
        yield storage


def test_storage_creates_database(temp_storage):
    db_path = temp_storage.data_dir / "events.sqlite"
    assert db_path.exists()


def test_storage_creates_clips_dir(temp_storage):
    clips_dir = temp_storage.data_dir / "clips"
    assert clips_dir.exists()


def test_save_event(temp_storage):
    event = Event(
        started_at=datetime(2024, 1, 15, 14, 32, 5),
        ended_at=datetime(2024, 1, 15, 14, 32, 13),
        duration_sec=8.0,
        bark_count=5,
        peak_score=0.87,
        avg_score=0.72,
        direction="left",
        direction_score=0.85,
        clip_path="clips/2024-01-15/14-32-05_000.wav",
        clip_hash="abc123",
        weather_temp_f=72.0,
        weather_wind_mph=5.0,
        weather_conditions="clear",
    )

    event_id = temp_storage.save_event(event)
    assert event_id == 1

    retrieved = temp_storage.get_event(event_id)
    assert retrieved.bark_count == 5
    assert retrieved.direction == "left"
    assert retrieved.clip_hash == "abc123"


def test_list_events_with_date_filter(temp_storage):
    event1 = Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
    )
    event2 = Event(
        started_at=datetime(2024, 1, 16, 10, 0, 0),
        ended_at=datetime(2024, 1, 16, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
    )

    temp_storage.save_event(event1)
    temp_storage.save_event(event2)

    events = temp_storage.list_events(
        start_date=datetime(2024, 1, 15),
        end_date=datetime(2024, 1, 15, 23, 59, 59),
    )

    assert len(events) == 1
    assert events[0].started_at.day == 15


def test_flag_false_positive(temp_storage):
    event = Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
    )

    event_id = temp_storage.save_event(event)
    temp_storage.flag_false_positive(event_id, reason="lawn mower")

    retrieved = temp_storage.get_event(event_id)
    assert retrieved.is_false_pos is True
    assert retrieved.false_pos_reason == "lawn mower"
