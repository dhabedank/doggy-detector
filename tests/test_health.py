from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.health as health
from src.config import Config, StorageConfig
from src.health import build_health
from src.storage import Storage


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path)


@pytest.fixture
def config(storage):
    return Config(storage=StorageConfig(data_dir=storage.data_dir))


@pytest.fixture
def stable_platform(monkeypatch):
    monkeypatch.setattr(
        health,
        "_add_temperature_check",
        lambda checks: checks.append({"name": "pi_temperature", "state": "ok", "message": "mocked"}),
    )
    monkeypatch.setattr(
        health,
        "_add_load_check",
        lambda checks: checks.append({"name": "load_average", "state": "ok", "message": "mocked"}),
    )
    monkeypatch.setattr(
        health,
        "_add_clock_sync_check",
        lambda checks: checks.append({"name": "clock_sync", "state": "ok", "message": "mocked"}),
    )


def fake_detector(**status_overrides):
    now = datetime.now(timezone.utc)
    status = {
        "startup_at": (now - timedelta(seconds=30)).isoformat(),
        "chunks_processed": 10,
        "last_audio_chunk_at": now.isoformat(),
        "audio_error": None,
        "mono_mode": False,
        "audio_level": 0.2,
        "left_level": 0.1,
        "right_level": 0.1,
        "clipping": False,
        "queue_drops": 0,
    }
    status.update(status_overrides)
    return SimpleNamespace(_running=True, status=status)


def check_map(summary):
    return {check["name"]: check for check in summary["checks"]}


def test_health_ok(config, storage, stable_platform):
    summary = build_health(config, storage, detector=fake_detector())

    assert summary["state"] == "ok"
    assert check_map(summary)["detector"]["state"] == "ok"


def test_health_warns_for_mono_mode(config, storage, stable_platform):
    summary = build_health(config, storage, detector=fake_detector(mono_mode=True))

    assert summary["state"] == "warn"
    assert check_map(summary)["mono_mode"]["state"] == "warn"


def test_health_critical_audio_error(config, storage, stable_platform):
    summary = build_health(config, storage, detector=fake_detector(audio_error="microphone failed"))

    assert summary["state"] == "critical"
    assert check_map(summary)["audio_error"]["state"] == "critical"


def test_health_critical_stale_audio(config, storage, stable_platform):
    now = datetime.now(timezone.utc)
    summary = build_health(
        config,
        storage,
        detector=fake_detector(last_audio_chunk_at=(now - timedelta(seconds=60)).isoformat()),
        now=now,
    )

    assert summary["state"] == "critical"
    assert check_map(summary)["stale_audio"]["state"] == "critical"


def test_health_critical_disk_low(config, storage, stable_platform, monkeypatch):
    usage = SimpleNamespace(total=1000, used=950, free=50 * 1024 * 1024)
    monkeypatch.setattr(health.shutil, "disk_usage", lambda path: usage)

    summary = build_health(config, storage, detector=fake_detector())

    assert summary["state"] == "critical"
    assert check_map(summary)["disk_free"]["state"] == "critical"


def test_health_unknown_when_detector_missing(config, storage, stable_platform):
    summary = build_health(config, storage, detector=None)

    assert summary["state"] == "unknown"
    assert check_map(summary)["detector"]["state"] == "unknown"
