"""Configuration loading and validation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class LocationConfig:
    address: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class AudioConfig:
    device: Optional[str] = None
    sample_rate: int = 16000
    channels: int = 2


@dataclass
class DetectionConfig:
    threshold: float = 0.5
    window_sec: float = 0.5


@dataclass
class IncidentsConfig:
    min_barks: int = 2
    gap_sec: float = 3.0
    min_duration_sec: float = 1.0
    merge_within_sec: float = 10.0


@dataclass
class StorageConfig:
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    retention_days: int = 0

    def __post_init__(self):
        if isinstance(self.data_dir, str):
            self.data_dir = Path(self.data_dir)


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class Config:
    location: LocationConfig = field(default_factory=LocationConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    incidents: IncidentsConfig = field(default_factory=IncidentsConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)


def load_config(path: Path) -> Config:
    """Load configuration from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    return Config(
        location=LocationConfig(**data.get("location", {})),
        audio=AudioConfig(**data.get("audio", {})),
        detection=DetectionConfig(**data.get("detection", {})),
        incidents=IncidentsConfig(**data.get("incidents", {})),
        storage=StorageConfig(**data.get("storage", {})),
        web=WebConfig(**data.get("web", {})),
    )
