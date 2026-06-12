import pytest
from pathlib import Path
import tempfile
import sqlite3
from datetime import datetime, timedelta

from src.storage import Storage, Event, DeterrenceEvent


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


def test_storage_migrates_calibration_columns(tmp_path):
    db_path = tmp_path / "events.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            duration_sec REAL NOT NULL,
            bark_count INTEGER NOT NULL,
            peak_score REAL NOT NULL,
            avg_score REAL NOT NULL,
            direction TEXT,
            direction_score REAL,
            clip_path TEXT,
            clip_hash TEXT,
            is_false_pos INTEGER DEFAULT 0,
            false_pos_reason TEXT,
            weather_temp_f REAL,
            weather_wind_mph REAL,
            weather_conditions TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    Storage(tmp_path)

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    conn.close()
    assert {"detection_threshold", "peak_audio_level", "avg_audio_level"}.issubset(columns)


def test_save_event(temp_storage):
    event = Event(
        started_at=datetime(2024, 1, 15, 14, 32, 5),
        ended_at=datetime(2024, 1, 15, 14, 32, 13),
        duration_sec=8.0,
        bark_count=5,
        peak_score=0.87,
        avg_score=0.72,
        detection_threshold=0.12,
        peak_audio_level=0.34,
        avg_audio_level=0.22,
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
    assert retrieved.detection_threshold == 0.12
    assert retrieved.peak_audio_level == 0.34
    assert retrieved.avg_audio_level == 0.22


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


def test_save_clip_does_not_overwrite_same_timestamp(temp_storage):
    timestamp = datetime(2024, 1, 15, 14, 32, 5)

    path1, hash1 = temp_storage.save_clip(b"first", timestamp)
    path2, hash2 = temp_storage.save_clip(b"second", timestamp)

    assert path1 != path2
    assert hash1 != hash2
    assert (temp_storage.data_dir / path1).read_bytes() == b"first"
    assert (temp_storage.data_dir / path2).read_bytes() == b"second"


def test_prune_retention_removes_rows_and_matching_clips(temp_storage):
    now = datetime(2024, 1, 20, 12, 0, 0)
    old_clip = temp_storage.data_dir / "clips" / "2024-01-01" / "old.wav"
    new_clip = temp_storage.data_dir / "clips" / "2024-01-19" / "new.wav"
    old_clip.parent.mkdir(parents=True, exist_ok=True)
    new_clip.parent.mkdir(parents=True, exist_ok=True)
    old_clip.write_bytes(b"old")
    new_clip.write_bytes(b"new")

    old_id = temp_storage.save_event(Event(
        started_at=now - timedelta(days=10),
        ended_at=now - timedelta(days=10, seconds=-5),
        duration_sec=5.0,
        bark_count=2,
        peak_score=0.8,
        avg_score=0.7,
        clip_path="clips/2024-01-01/old.wav",
    ))
    new_id = temp_storage.save_event(Event(
        started_at=now - timedelta(days=1),
        ended_at=now - timedelta(days=1, seconds=-5),
        duration_sec=5.0,
        bark_count=2,
        peak_score=0.8,
        avg_score=0.7,
        clip_path="clips/2024-01-19/new.wav",
    ))

    result = temp_storage.prune_retention(retention_days=7, now=now)

    assert result == {"events_deleted": 1, "clips_deleted": 1}
    assert temp_storage.get_event(old_id) is None
    assert temp_storage.get_event(new_id) is not None
    assert not old_clip.exists()
    assert new_clip.exists()


def test_delete_event_removes_row_and_clip(temp_storage):
    clip_path = temp_storage.data_dir / "clips" / "2024-01-15" / "test.wav"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(b"test")

    event_id = temp_storage.save_event(Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
        clip_path="clips/2024-01-15/test.wav",
    ))

    deleted = temp_storage.delete_event(event_id)

    assert deleted is not None
    assert deleted.id == event_id
    assert temp_storage.get_event(event_id) is None
    assert not clip_path.exists()


def test_delete_event_missing_returns_none(temp_storage):
    assert temp_storage.delete_event(999) is None


def test_summarize_events_excludes_false_positives_by_default(temp_storage):
    valid = Event(
        started_at=datetime(2024, 1, 15, 10, 0, 0),
        ended_at=datetime(2024, 1, 15, 10, 0, 5),
        duration_sec=5.0,
        bark_count=3,
        peak_score=0.8,
        avg_score=0.7,
    )
    false_pos = Event(
        started_at=datetime(2024, 1, 15, 11, 0, 0),
        ended_at=datetime(2024, 1, 15, 11, 0, 20),
        duration_sec=20.0,
        bark_count=5,
        peak_score=0.95,
        avg_score=0.8,
        is_false_pos=True,
    )
    temp_storage.save_event(valid)
    temp_storage.save_event(false_pos)

    summary = temp_storage.summarize_events()
    summary_with_false_pos = temp_storage.summarize_events(include_false_pos=True)

    assert summary == {
        "incident_count": 1,
        "total_duration_sec": 5.0,
        "longest_duration_sec": 5.0,
        "peak_score": 0.8,
    }
    assert summary_with_false_pos["incident_count"] == 2
    assert summary_with_false_pos["total_duration_sec"] == 25.0


def test_deterrence_events_are_saved_and_listed(temp_storage):
    first_id = temp_storage.save_deterrence_event(DeterrenceEvent(
        fired_at=datetime(2026, 1, 1, 12, 0, 0),
        source="manual",
        mode="audible",
        profile="chirp",
        status="fired",
        bark_score=None,
        audio_level=None,
        duration_sec=2.0,
    ))
    second_id = temp_storage.save_deterrence_event(DeterrenceEvent(
        fired_at=datetime(2026, 1, 1, 12, 1, 0),
        source="auto",
        mode="ultrasonic",
        profile="chirp",
        status="failed",
        bark_score=0.8,
        audio_level=0.2,
        duration_sec=2.0,
        error="gpio missing",
    ))

    events = temp_storage.list_deterrence_events()

    assert [event.id for event in events] == [second_id, first_id]
    assert events[0].source == "auto"
    assert events[0].error == "gpio missing"
    assert temp_storage.count_deterrence_events(
        start_at=datetime(2026, 1, 1),
        status="fired",
    ) == 1
