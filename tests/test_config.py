import pytest
from pathlib import Path
import tempfile
import yaml

from src.config import load_config, Config


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
    assert config.detection.threshold == 0.5
    assert config.web.port == 8080

    config_path.unlink()
