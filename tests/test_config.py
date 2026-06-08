import pytest
from pathlib import Path
from datetime import datetime
import tempfile
import yaml

from src.config import (
    AUTH_RESET_SENTINEL,
    AUTH_PASSWORD_HASH_KEY,
    AUTH_USERNAME_KEY,
    LEGACY_MIGRATION_KEY,
    SettingsStore,
    load_config,
    load_runtime_config,
    verify_password,
)
from src.storage import Event, Storage


def test_load_config_from_file():
    config_data = {
        "location": {"address": "123 Main St", "lat": 34.05, "lon": -118.24},
        "audio": {"device": None, "sample_rate": 16000, "channels": 2},
        "detection": {"threshold": 0.5, "window_sec": 0.5},
        "incidents": {
            "min_barks": 2,
            "gap_sec": 3.0,
            "min_duration_sec": 1.0,
            "merge_within_sec": 10.0,
        },
        "storage": {"data_dir": "./data", "retention_days": 0},
        "web": {"host": "0.0.0.0", "port": 8080},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)

    config = load_config(config_path)

    assert config.location.address == "123 Main St"
    assert config.location.lat == 34.05
    assert config.audio.sample_rate == 16000
    assert config.detection.threshold == 0.5
    assert config.incidents.gap_sec == 3.0
    assert config.storage.data_dir == Path("./data")
    assert config.web.port == 8080

    config_path.unlink()


def test_load_config_uses_defaults():
    config_data = {}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)

    config = load_config(config_path)

    assert config.audio.sample_rate == 16000
    assert config.audio.channels == 2
    assert config.detection.threshold == 0.15
    assert config.web.port == 8080

    config_path.unlink()


def test_runtime_config_seeds_sqlite_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        config, store, credentials = load_runtime_config(
            data_dir=data_dir,
            legacy_config_path=Path(tmpdir) / "missing.yaml",
        )

        assert config.storage.data_dir == data_dir
        assert config.audio.sample_rate == 16000
        assert store.get_section("audio")["device"] is None
        assert credentials is not None
        assert credentials["username"] == "admin"
        assert store.get(AUTH_USERNAME_KEY) == "admin"
        assert store.get(AUTH_PASSWORD_HASH_KEY) != credentials["password"]
        assert verify_password(credentials["password"], store.get(AUTH_PASSWORD_HASH_KEY))


def test_runtime_config_migrates_legacy_yaml_once():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        legacy_path = tmp_path / "config.yaml"
        legacy_path.write_text(yaml.dump({
            "location": {"address": "123 Main St", "lat": 34.05, "lon": -118.24},
            "audio": {"device": 3, "sample_rate": 16000, "channels": 2},
            "detection": {"threshold": 0.25, "window_sec": 0.75},
            "storage": {"data_dir": "/ignored", "retention_days": 7},
        }))

        data_dir = tmp_path / "data"
        config, store, credentials = load_runtime_config(data_dir=data_dir, legacy_config_path=legacy_path)

        assert config.location.address == "123 Main St"
        assert config.audio.device == 3
        assert config.detection.threshold == 0.25
        assert config.storage.data_dir == data_dir
        assert config.storage.retention_days == 7
        assert store.get(LEGACY_MIGRATION_KEY) is True
        assert credentials is not None
        assert not legacy_path.exists()
        assert (tmp_path / "config.yaml.migrated").exists()

        new_legacy_path = tmp_path / "config.yaml"
        new_legacy_path.write_text(yaml.dump({"detection": {"threshold": 0.9}}))
        config_again, _, second_credentials = load_runtime_config(data_dir=data_dir, legacy_config_path=new_legacy_path)

        assert config_again.detection.threshold == 0.25
        assert second_credentials is None


def test_settings_store_auth_password_hash_only():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SettingsStore(Path(tmpdir))
        credentials = store.ensure_auth_credentials(username="admin", password="secret")

        assert credentials == {"username": "admin", "password": "secret"}
        assert store.get_auth_username() == "admin"
        assert store.get_auth_password_hash() != "secret"
        assert verify_password("secret", store.get_auth_password_hash())
        assert store.ensure_auth_credentials() is None


def test_runtime_config_auth_reset_rotates_password_without_losing_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        config, store, credentials = load_runtime_config(
            data_dir=data_dir,
            legacy_config_path=Path(tmpdir) / "missing.yaml",
        )
        assert credentials is not None
        config.detection.threshold = 0.23
        store.update_config(config)
        storage = Storage(data_dir)
        clip_path = data_dir / "clips" / "2024-01-15" / "reset-safe.wav"
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        clip_path.write_bytes(b"keep")
        event_id = storage.save_event(Event(
            started_at=datetime(2024, 1, 15, 10, 0, 0),
            ended_at=datetime(2024, 1, 15, 10, 0, 5),
            duration_sec=5.0,
            bark_count=3,
            peak_score=0.8,
            avg_score=0.7,
            clip_path="clips/2024-01-15/reset-safe.wav",
        ))
        first_hash = store.get(AUTH_PASSWORD_HASH_KEY)

        (data_dir / AUTH_RESET_SENTINEL).write_text("reset")
        reset_config, reset_store, reset_credentials = load_runtime_config(
            data_dir=data_dir,
            legacy_config_path=Path(tmpdir) / "missing.yaml",
        )

        assert reset_credentials is not None
        assert reset_credentials["username"] == credentials["username"]
        assert reset_store.get(AUTH_PASSWORD_HASH_KEY) != first_hash
        assert verify_password(reset_credentials["password"], reset_store.get(AUTH_PASSWORD_HASH_KEY))
        assert reset_config.detection.threshold == 0.23
        assert Storage(data_dir).get_event(event_id) is not None
        assert clip_path.read_bytes() == b"keep"
        assert not (data_dir / AUTH_RESET_SENTINEL).exists()
