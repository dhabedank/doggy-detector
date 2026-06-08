from datetime import datetime, timedelta
from types import SimpleNamespace
import sqlite3

import pytest

from src.config import Config, StorageConfig
from src.incidents import Incident
from src.main import DoggyDetector


class FakeWeatherClient:
    async def fetch(self, lat, lon):
        return None


class FakeRecorder:
    def __init__(self, wav_path):
        self.wav_path = wav_path
        self.duration_seconds = 1.0

    def stop(self):
        return self.wav_path


def sample_incident():
    now = datetime(2024, 1, 15, 10, 0, 0)
    return Incident(
        started_at=now,
        ended_at=now + timedelta(seconds=2),
        bark_count=2,
        peak_score=0.8,
        avg_score=0.7,
        direction="left",
        direction_score=0.9,
    )


@pytest.mark.asyncio
async def test_save_incident_persists_event_when_clip_save_fails(tmp_path, monkeypatch):
    detector = DoggyDetector(Config(storage=StorageConfig(data_dir=tmp_path)))
    detector.weather_client = FakeWeatherClient()
    wav_path = tmp_path / "temp.wav"
    wav_path.write_bytes(b"wav")
    detector.incident_recorder = FakeRecorder(wav_path)
    monkeypatch.setattr(detector.storage, "save_clip", lambda audio_data, timestamp: (_ for _ in ()).throw(OSError("disk full")))

    await detector._save_incident(sample_incident())

    events = detector.storage.list_events()
    assert len(events) == 1
    assert events[0].clip_path is None
    assert events[0].clip_hash is None


@pytest.mark.asyncio
async def test_save_incident_writes_pending_metadata_when_db_fails(tmp_path, monkeypatch):
    detector = DoggyDetector(Config(storage=StorageConfig(data_dir=tmp_path)))
    detector.weather_client = FakeWeatherClient()
    wav_path = tmp_path / "temp.wav"
    wav_path.write_bytes(b"wav")
    detector.incident_recorder = FakeRecorder(wav_path)
    monkeypatch.setattr(detector.storage, "save_event_with_retry", lambda event: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))

    await detector._save_incident(sample_incident())

    clip_files = list((tmp_path / "clips" / "2024-01-15").glob("*.wav"))
    pending_files = list((tmp_path / "pending_events").glob("*.json"))
    assert len(clip_files) == 1
    assert len(pending_files) == 1
    assert "clips/2024-01-15" in pending_files[0].read_text()
