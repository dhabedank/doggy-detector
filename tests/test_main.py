from datetime import datetime, timedelta
from types import SimpleNamespace
import sqlite3

import numpy as np
import pytest

from src.config import Config, IncidentsConfig, StorageConfig
from src.incidents import Detection, Incident
from src.main import DoggyDetector, resample_audio


class FakeWeatherClient:
    async def fetch(self, lat, lon):
        return None


class FakeRecorder:
    def __init__(self, wav_path, duration_seconds=1.0):
        self.wav_path = wav_path
        self.duration_seconds = duration_seconds
        self.is_recording = True
        self.cancelled = False

    def stop(self):
        self.is_recording = False
        return self.wav_path

    def cancel(self):
        self.is_recording = False
        self.cancelled = True


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


def test_resample_audio_preserves_duration_and_channels():
    audio = np.column_stack(
        [
            np.linspace(-1.0, 1.0, 4800, dtype=np.float32),
            np.linspace(1.0, -1.0, 4800, dtype=np.float32),
        ]
    )

    resampled = resample_audio(audio, source_rate=48000, target_rate=16000)

    assert resampled.shape == (1600, 2)
    assert resampled.dtype == np.float32
    assert resampled[0, 0] == pytest.approx(audio[0, 0])
    assert resampled[0, 1] == pytest.approx(audio[0, 1])


def test_discarded_short_incident_cancels_active_recording(tmp_path):
    config = Config(
        incidents=IncidentsConfig(
            min_barks=2,
            gap_sec=3.0,
            min_duration_sec=2.0,
            merge_within_sec=1.0,
        ),
        storage=StorageConfig(data_dir=tmp_path),
    )
    detector = DoggyDetector(config)
    recorder = FakeRecorder(tmp_path / "temp.wav")
    detector.incident_recorder = recorder
    now = datetime(2024, 1, 15, 10, 0, 0)

    detector.incident_tracker.process_detection(
        Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    )
    detector.incident_tracker.process_detection(
        Detection(
            timestamp=now + timedelta(seconds=0.5),
            score=0.9,
            direction="left",
            direction_score=0.9,
        )
    )
    detector.incident_tracker.check_timeout(now + timedelta(seconds=4.0))
    incident = detector.incident_tracker.check_timeout(now + timedelta(seconds=5.0))

    assert incident is None
    assert detector.incident_tracker.last_discard_reason == "min_duration"

    detector._cancel_discarded_incident_recording()

    assert recorder.cancelled is True
    assert recorder.is_recording is False


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
async def test_save_incident_discards_implausibly_long_recording(tmp_path, monkeypatch):
    detector = DoggyDetector(Config(storage=StorageConfig(data_dir=tmp_path)))
    detector.weather_client = FakeWeatherClient()
    wav_path = tmp_path / "temp.wav"
    wav_path.write_bytes(b"wav")
    detector.incident_recorder = FakeRecorder(wav_path, duration_seconds=3600.0)
    monkeypatch.setattr(
        detector.storage,
        "save_clip",
        lambda audio_data, timestamp: (_ for _ in ()).throw(
            AssertionError("stale clip should not be saved")
        ),
    )

    await detector._save_incident(sample_incident())

    events = detector.storage.list_events()
    assert len(events) == 1
    assert events[0].clip_path is None
    assert events[0].clip_hash is None
    assert detector.incident_recorder.cancelled is True


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
