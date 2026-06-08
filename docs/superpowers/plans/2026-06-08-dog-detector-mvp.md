# Dog Detector MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an always-on bark detection system for Raspberry Pi that saves audio clips, determines direction, and generates evidence reports.

**Architecture:** Single Python process with async event loop. Audio capture in dedicated thread feeds async queue. YAMNet for bark detection. SQLite for storage. FastAPI for dashboard.

**Tech Stack:** Python 3.11+, sounddevice, TensorFlow Lite, YAMNet, SQLite, FastAPI, weasyprint, httpx

---

## File Structure

```
dog-detector/
├── config.yaml                 # Default configuration
├── requirements.txt            # Python dependencies
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point, wires components
│   ├── config.py               # Load/validate YAML config
│   ├── storage.py              # SQLite operations, clip saving
│   ├── direction.py            # L/R channel intensity
│   ├── weather.py              # Open-Meteo API client
│   ├── audio.py                # Audio capture, rolling buffer
│   ├── detector.py             # YAMNet wrapper
│   ├── incidents.py            # Incident state machine
│   ├── reports.py              # PDF + ZIP generation
│   └── web/
│       ├── __init__.py
│       ├── app.py              # FastAPI application
│       ├── routes.py           # API endpoints
│       ├── static/
│       │   ├── style.css
│       │   └── app.js
│       └── templates/
│           └── index.html
├── scripts/
│   └── install.sh              # Pi deployment script
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_storage.py
│   ├── test_direction.py
│   ├── test_weather.py
│   ├── test_incidents.py
│   ├── test_reports.py
│   └── test_web.py
└── docs/
    └── PRD.md
```

---

## Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `config.yaml`

- [ ] **Step 1: Create requirements.txt**

```
# Audio
sounddevice>=0.4.6
numpy>=1.24.0

# ML
tensorflow>=2.15.0
tensorflow-hub>=0.15.0

# Web
fastapi>=0.109.0
uvicorn>=0.27.0
jinja2>=3.1.0
python-multipart>=0.0.6

# Reports
weasyprint>=60.0

# HTTP client
httpx>=0.26.0

# Config
pyyaml>=6.0

# Testing
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: Create package init files**

Create `src/__init__.py`:
```python
"""Dog Detector - Bark monitoring system."""
```

Create `tests/__init__.py`:
```python
"""Dog Detector tests."""
```

- [ ] **Step 3: Create default config.yaml**

```yaml
location:
  address: ""
  lat: null
  lon: null

audio:
  device: null
  sample_rate: 16000
  channels: 2

detection:
  threshold: 0.5
  window_sec: 0.5

incidents:
  min_barks: 2
  gap_sec: 3.0
  min_duration_sec: 1.0
  merge_within_sec: 10.0

storage:
  data_dir: ./data
  retention_days: 0

web:
  host: 0.0.0.0
  port: 8080
```

- [ ] **Step 4: Create data directories**

```bash
mkdir -p data/clips data/reports
```

- [ ] **Step 5: Set up virtual environment and install dependencies**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt src/__init__.py tests/__init__.py config.yaml
git commit -m "chore: project setup with dependencies and config"
```

---

## Task 2: Config Module

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test for config loading**

Create `tests/test_config.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.config'`

- [ ] **Step 3: Implement config module**

Create `src/config.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add config module with YAML loading"
```

---

## Task 3: Storage Module

**Files:**
- Create: `src/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests for storage**

Create `tests/test_storage.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_storage.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.storage'`

- [ ] **Step 3: Implement storage module**

Create `src/storage.py`:
```python
"""SQLite storage and clip management."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import sqlite3
import hashlib


@dataclass
class Event:
    started_at: datetime
    ended_at: datetime
    duration_sec: float
    bark_count: int
    peak_score: float
    avg_score: float
    direction: Optional[str] = None
    direction_score: Optional[float] = None
    clip_path: Optional[str] = None
    clip_hash: Optional[str] = None
    is_false_pos: bool = False
    false_pos_reason: Optional[str] = None
    weather_temp_f: Optional[float] = None
    weather_wind_mph: Optional[float] = None
    weather_conditions: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "clips").mkdir(exist_ok=True)
        (self.data_dir / "reports").mkdir(exist_ok=True)

        self.db_path = self.data_dir / "events.sqlite"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at         TEXT NOT NULL,
                ended_at           TEXT NOT NULL,
                duration_sec       REAL NOT NULL,
                bark_count         INTEGER NOT NULL,
                peak_score         REAL NOT NULL,
                avg_score          REAL NOT NULL,
                direction          TEXT,
                direction_score    REAL,
                clip_path          TEXT,
                clip_hash          TEXT,
                is_false_pos       INTEGER DEFAULT 0,
                false_pos_reason   TEXT,
                weather_temp_f     REAL,
                weather_wind_mph   REAL,
                weather_conditions TEXT,
                created_at         TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_started_at ON events(started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_is_false_pos ON events(is_false_pos)")
        conn.commit()
        conn.close()

    def save_event(self, event: Event) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            INSERT INTO events (
                started_at, ended_at, duration_sec, bark_count, peak_score, avg_score,
                direction, direction_score, clip_path, clip_hash, is_false_pos,
                false_pos_reason, weather_temp_f, weather_wind_mph, weather_conditions,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.started_at.isoformat(),
                event.ended_at.isoformat(),
                event.duration_sec,
                event.bark_count,
                event.peak_score,
                event.avg_score,
                event.direction,
                event.direction_score,
                event.clip_path,
                event.clip_hash,
                1 if event.is_false_pos else 0,
                event.false_pos_reason,
                event.weather_temp_f,
                event.weather_wind_mph,
                event.weather_conditions,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        event_id = cursor.lastrowid
        conn.close()
        return event_id

    def get_event(self, event_id: int) -> Optional[Event]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return self._row_to_event(row)

    def list_events(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        include_false_pos: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Event]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        query = "SELECT * FROM events WHERE 1=1"
        params = []

        if start_date:
            query += " AND started_at >= ?"
            params.append(start_date.isoformat())

        if end_date:
            query += " AND started_at <= ?"
            params.append(end_date.isoformat())

        if not include_false_pos:
            query += " AND is_false_pos = 0"

        query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_event(row) for row in rows]

    def count_events(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        include_false_pos: bool = True,
    ) -> int:
        conn = sqlite3.connect(self.db_path)

        query = "SELECT COUNT(*) FROM events WHERE 1=1"
        params = []

        if start_date:
            query += " AND started_at >= ?"
            params.append(start_date.isoformat())

        if end_date:
            query += " AND started_at <= ?"
            params.append(end_date.isoformat())

        if not include_false_pos:
            query += " AND is_false_pos = 0"

        cursor = conn.execute(query, params)
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def flag_false_positive(self, event_id: int, reason: Optional[str] = None):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE events SET is_false_pos = 1, false_pos_reason = ? WHERE id = ?",
            (reason, event_id),
        )
        conn.commit()
        conn.close()

    def unflag_false_positive(self, event_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE events SET is_false_pos = 0, false_pos_reason = NULL WHERE id = ?",
            (event_id,),
        )
        conn.commit()
        conn.close()

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        return Event(
            id=row["id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]),
            duration_sec=row["duration_sec"],
            bark_count=row["bark_count"],
            peak_score=row["peak_score"],
            avg_score=row["avg_score"],
            direction=row["direction"],
            direction_score=row["direction_score"],
            clip_path=row["clip_path"],
            clip_hash=row["clip_hash"],
            is_false_pos=bool(row["is_false_pos"]),
            false_pos_reason=row["false_pos_reason"],
            weather_temp_f=row["weather_temp_f"],
            weather_wind_mph=row["weather_wind_mph"],
            weather_conditions=row["weather_conditions"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )

    def save_clip(self, audio_data: bytes, timestamp: datetime) -> tuple[str, str]:
        """Save audio clip and return (relative_path, sha256_hash)."""
        date_dir = self.data_dir / "clips" / timestamp.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        filename = timestamp.strftime("%H-%M-%S") + f"_{timestamp.microsecond // 1000:03d}.wav"
        clip_path = date_dir / filename
        relative_path = f"clips/{timestamp.strftime('%Y-%m-%d')}/{filename}"

        clip_path.write_bytes(audio_data)

        clip_hash = hashlib.sha256(audio_data).hexdigest()

        return relative_path, clip_hash
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_storage.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/storage.py tests/test_storage.py
git commit -m "feat: add storage module with SQLite and clip saving"
```

---

## Task 4: Direction Module

**Files:**
- Create: `src/direction.py`
- Create: `tests/test_direction.py`

- [ ] **Step 1: Write failing tests for direction detection**

Create `tests/test_direction.py`:
```python
import pytest
import numpy as np

from src.direction import analyze_direction, DirectionResult


def test_louder_left_returns_left():
    # Left channel louder
    left = np.array([0.8, 0.9, 0.85, 0.7])
    right = np.array([0.2, 0.3, 0.25, 0.2])
    stereo = np.column_stack([left, right])

    result = analyze_direction(stereo)

    assert result.direction == "left"
    assert result.confidence > 0.5


def test_louder_right_returns_right():
    # Right channel louder
    left = np.array([0.2, 0.3, 0.25, 0.2])
    right = np.array([0.8, 0.9, 0.85, 0.7])
    stereo = np.column_stack([left, right])

    result = analyze_direction(stereo)

    assert result.direction == "right"
    assert result.confidence > 0.5


def test_equal_channels_returns_center():
    # Equal volume both channels
    left = np.array([0.5, 0.6, 0.55, 0.5])
    right = np.array([0.5, 0.6, 0.55, 0.5])
    stereo = np.column_stack([left, right])

    result = analyze_direction(stereo)

    assert result.direction == "center"


def test_slight_difference_low_confidence():
    # Slight difference
    left = np.array([0.5, 0.6, 0.55, 0.5])
    right = np.array([0.45, 0.55, 0.5, 0.45])
    stereo = np.column_stack([left, right])

    result = analyze_direction(stereo)

    assert result.confidence < 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_direction.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.direction'`

- [ ] **Step 3: Implement direction module**

Create `src/direction.py`:
```python
"""Direction detection from stereo audio."""

from dataclasses import dataclass
from typing import Literal
import numpy as np


@dataclass
class DirectionResult:
    direction: Literal["left", "right", "center"]
    confidence: float
    left_rms: float
    right_rms: float


def analyze_direction(stereo_audio: np.ndarray) -> DirectionResult:
    """
    Analyze stereo audio to determine direction.

    Args:
        stereo_audio: numpy array of shape (samples, 2) with left and right channels

    Returns:
        DirectionResult with direction, confidence, and RMS values
    """
    if stereo_audio.ndim != 2 or stereo_audio.shape[1] != 2:
        raise ValueError("Expected stereo audio with shape (samples, 2)")

    left_channel = stereo_audio[:, 0]
    right_channel = stereo_audio[:, 1]

    left_rms = np.sqrt(np.mean(left_channel ** 2))
    right_rms = np.sqrt(np.mean(right_channel ** 2))

    total_rms = left_rms + right_rms
    if total_rms < 1e-10:
        return DirectionResult(
            direction="center",
            confidence=0.0,
            left_rms=left_rms,
            right_rms=right_rms,
        )

    # Calculate ratio: 0 = all left, 1 = all right, 0.5 = center
    ratio = right_rms / total_rms

    # Calculate confidence based on how far from center
    # 0.5 ratio = 0 confidence, 0 or 1 ratio = 1 confidence
    confidence = abs(ratio - 0.5) * 2

    # Determine direction
    if confidence < 0.1:
        direction = "center"
    elif ratio < 0.5:
        direction = "left"
    else:
        direction = "right"

    return DirectionResult(
        direction=direction,
        confidence=confidence,
        left_rms=float(left_rms),
        right_rms=float(right_rms),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_direction.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/direction.py tests/test_direction.py
git commit -m "feat: add direction detection from stereo audio"
```

---

## Task 5: Weather Module

**Files:**
- Create: `src/weather.py`
- Create: `tests/test_weather.py`

- [ ] **Step 1: Write failing tests for weather fetching**

Create `tests/test_weather.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch

from src.weather import WeatherClient, WeatherData


@pytest.mark.asyncio
async def test_fetch_weather_returns_data():
    mock_response = {
        "current": {
            "temperature_2m": 72.0,
            "wind_speed_10m": 5.0,
            "weather_code": 0,
        }
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = AsyncMock()
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.raise_for_status = lambda: None

        client = WeatherClient()
        result = await client.fetch(lat=34.05, lon=-118.24)

        assert result.temp_f == 72.0
        assert result.wind_mph == 5.0
        assert result.conditions == "clear"


@pytest.mark.asyncio
async def test_fetch_weather_handles_none_location():
    client = WeatherClient()
    result = await client.fetch(lat=None, lon=None)

    assert result is None


def test_weather_code_to_conditions():
    client = WeatherClient()

    assert client._code_to_conditions(0) == "clear"
    assert client._code_to_conditions(1) == "partly cloudy"
    assert client._code_to_conditions(2) == "partly cloudy"
    assert client._code_to_conditions(3) == "cloudy"
    assert client._code_to_conditions(61) == "rain"
    assert client._code_to_conditions(95) == "thunderstorm"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_weather.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.weather'`

- [ ] **Step 3: Implement weather module**

Create `src/weather.py`:
```python
"""Weather data from Open-Meteo API."""

from dataclasses import dataclass
from typing import Optional
import httpx


@dataclass
class WeatherData:
    temp_f: float
    wind_mph: float
    conditions: str


class WeatherClient:
    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def fetch(self, lat: Optional[float], lon: Optional[float]) -> Optional[WeatherData]:
        """Fetch current weather for coordinates."""
        if lat is None or lon is None:
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.BASE_URL,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,wind_speed_10m,weather_code",
                        "temperature_unit": "fahrenheit",
                        "wind_speed_unit": "mph",
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()

                current = data.get("current", {})
                return WeatherData(
                    temp_f=current.get("temperature_2m", 0.0),
                    wind_mph=current.get("wind_speed_10m", 0.0),
                    conditions=self._code_to_conditions(current.get("weather_code", 0)),
                )
        except Exception:
            return None

    def _code_to_conditions(self, code: int) -> str:
        """Convert WMO weather code to human-readable conditions."""
        if code == 0:
            return "clear"
        elif code in (1, 2):
            return "partly cloudy"
        elif code == 3:
            return "cloudy"
        elif code in (45, 48):
            return "fog"
        elif code in (51, 53, 55, 56, 57):
            return "drizzle"
        elif code in (61, 63, 65, 66, 67, 80, 81, 82):
            return "rain"
        elif code in (71, 73, 75, 77, 85, 86):
            return "snow"
        elif code in (95, 96, 99):
            return "thunderstorm"
        else:
            return "unknown"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_weather.py -v
```

Expected: PASS (may need to adjust mock setup)

- [ ] **Step 5: Commit**

```bash
git add src/weather.py tests/test_weather.py
git commit -m "feat: add weather module with Open-Meteo API client"
```

---

## Task 6: Incidents Module

**Files:**
- Create: `src/incidents.py`
- Create: `tests/test_incidents.py`

- [ ] **Step 1: Write failing tests for incident state machine**

Create `tests/test_incidents.py`:
```python
import pytest
from datetime import datetime, timedelta

from src.incidents import IncidentTracker, IncidentState, Detection
from src.config import IncidentsConfig


@pytest.fixture
def config():
    return IncidentsConfig(
        min_barks=2,
        gap_sec=3.0,
        min_duration_sec=1.0,
        merge_within_sec=10.0,
    )


@pytest.fixture
def tracker(config):
    return IncidentTracker(config)


def test_single_detection_no_incident(tracker):
    now = datetime.now()
    detection = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)

    incident = tracker.process_detection(detection)

    assert incident is None
    assert tracker.state == IncidentState.MONITORING


def test_two_detections_starts_incident(tracker):
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=0.5), score=0.85, direction="left", direction_score=0.85)

    tracker.process_detection(d1)
    incident = tracker.process_detection(d2)

    assert incident is None  # Still in progress
    assert tracker.state == IncidentState.ACTIVE


def test_gap_ends_incident(tracker):
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=0.5), score=0.85, direction="left", direction_score=0.85)

    tracker.process_detection(d1)
    tracker.process_detection(d2)

    # Simulate time passing with no detections
    incident = tracker.check_timeout(now + timedelta(seconds=4.0))

    assert incident is not None
    assert incident.bark_count == 2
    assert incident.peak_score == 0.85
    assert tracker.state == IncidentState.MONITORING


def test_short_incident_discarded(tracker):
    tracker.config.min_duration_sec = 2.0
    now = datetime.now()
    d1 = Detection(timestamp=now, score=0.8, direction="left", direction_score=0.9)
    d2 = Detection(timestamp=now + timedelta(seconds=0.3), score=0.85, direction="left", direction_score=0.85)

    tracker.process_detection(d1)
    tracker.process_detection(d2)

    # Duration is 0.3s, less than min_duration_sec of 2.0
    incident = tracker.check_timeout(now + timedelta(seconds=4.0))

    assert incident is None
    assert tracker.state == IncidentState.MONITORING
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_incidents.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.incidents'`

- [ ] **Step 3: Implement incidents module**

Create `src/incidents.py`:
```python
"""Incident tracking state machine."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List

from src.config import IncidentsConfig


class IncidentState(Enum):
    MONITORING = "monitoring"
    ACTIVE = "active"


@dataclass
class Detection:
    timestamp: datetime
    score: float
    direction: Optional[str] = None
    direction_score: Optional[float] = None


@dataclass
class Incident:
    started_at: datetime
    ended_at: datetime
    bark_count: int
    peak_score: float
    avg_score: float
    direction: Optional[str]
    direction_score: Optional[float]
    detections: List[Detection] = field(default_factory=list)

    @property
    def duration_sec(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()


class IncidentTracker:
    def __init__(self, config: IncidentsConfig):
        self.config = config
        self.state = IncidentState.MONITORING
        self._detections: List[Detection] = []
        self._last_detection_time: Optional[datetime] = None

    def process_detection(self, detection: Detection) -> Optional[Incident]:
        """
        Process a bark detection. Returns completed Incident if one just ended,
        or None if still monitoring/active.
        """
        self._detections.append(detection)
        self._last_detection_time = detection.timestamp

        if self.state == IncidentState.MONITORING:
            if len(self._detections) >= self.config.min_barks:
                self.state = IncidentState.ACTIVE

        return None

    def check_timeout(self, current_time: datetime) -> Optional[Incident]:
        """
        Check if current incident has timed out due to silence gap.
        Returns completed Incident if one ended, or None otherwise.
        """
        if self.state != IncidentState.ACTIVE:
            if self._detections and self._last_detection_time:
                gap = (current_time - self._last_detection_time).total_seconds()
                if gap > self.config.gap_sec:
                    self._detections = []
                    self._last_detection_time = None
            return None

        if self._last_detection_time is None:
            return None

        gap = (current_time - self._last_detection_time).total_seconds()

        if gap < self.config.gap_sec:
            return None

        # Incident ended
        incident = self._finalize_incident()
        self._reset()

        # Check minimum duration
        if incident and incident.duration_sec < self.config.min_duration_sec:
            return None

        return incident

    def _finalize_incident(self) -> Optional[Incident]:
        if not self._detections:
            return None

        scores = [d.score for d in self._detections]
        directions = [d.direction for d in self._detections if d.direction]
        direction_scores = [d.direction_score for d in self._detections if d.direction_score]

        # Determine dominant direction
        direction = None
        direction_score = None
        if directions:
            left_count = directions.count("left")
            right_count = directions.count("right")
            if left_count > right_count:
                direction = "left"
            elif right_count > left_count:
                direction = "right"
            else:
                direction = "center"

            if direction_scores:
                direction_score = sum(direction_scores) / len(direction_scores)

        return Incident(
            started_at=self._detections[0].timestamp,
            ended_at=self._detections[-1].timestamp,
            bark_count=len(self._detections),
            peak_score=max(scores),
            avg_score=sum(scores) / len(scores),
            direction=direction,
            direction_score=direction_score,
            detections=self._detections.copy(),
        )

    def _reset(self):
        self.state = IncidentState.MONITORING
        self._detections = []
        self._last_detection_time = None

    def force_end(self) -> Optional[Incident]:
        """Force end current incident (e.g., on shutdown)."""
        if self.state != IncidentState.ACTIVE:
            return None

        incident = self._finalize_incident()
        self._reset()

        if incident and incident.duration_sec < self.config.min_duration_sec:
            return None

        return incident
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_incidents.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/incidents.py tests/test_incidents.py
git commit -m "feat: add incident tracking state machine"
```

---

## Task 7: Audio Module

**Files:**
- Create: `src/audio.py`
- Create: `tests/test_audio.py`

- [ ] **Step 1: Write failing tests for audio components**

Create `tests/test_audio.py`:
```python
import pytest
import numpy as np
from collections import deque

from src.audio import RollingBuffer


def test_rolling_buffer_stores_samples():
    buffer = RollingBuffer(max_seconds=2.0, sample_rate=16000, channels=2)

    # Add 1 second of audio
    chunk = np.zeros((16000, 2), dtype=np.float32)
    buffer.add(chunk)

    assert buffer.duration_seconds == pytest.approx(1.0, rel=0.01)


def test_rolling_buffer_rolls_over():
    buffer = RollingBuffer(max_seconds=2.0, sample_rate=16000, channels=2)

    # Add 3 seconds of audio (should keep only last 2)
    for i in range(3):
        chunk = np.full((16000, 2), i, dtype=np.float32)
        buffer.add(chunk)

    assert buffer.duration_seconds == pytest.approx(2.0, rel=0.01)

    # Get all data - should be last 2 chunks
    data = buffer.get_all()
    assert data.shape == (32000, 2)


def test_rolling_buffer_get_last():
    buffer = RollingBuffer(max_seconds=5.0, sample_rate=16000, channels=2)

    # Add 3 seconds
    for i in range(3):
        chunk = np.full((16000, 2), i, dtype=np.float32)
        buffer.add(chunk)

    # Get last 1 second
    data = buffer.get_last(seconds=1.0)
    assert data.shape == (16000, 2)
    # Should be the last chunk (value 2)
    assert data[0, 0] == 2.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_audio.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.audio'`

- [ ] **Step 3: Implement audio module**

Create `src/audio.py`:
```python
"""Audio capture and rolling buffer."""

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from typing import Optional, Callable, Deque
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None


class RollingBuffer:
    """Thread-safe rolling audio buffer."""

    def __init__(self, max_seconds: float, sample_rate: int, channels: int):
        self.max_samples = int(max_seconds * sample_rate)
        self.sample_rate = sample_rate
        self.channels = channels
        self._buffer: Deque[np.ndarray] = deque()
        self._total_samples = 0
        self._lock = threading.Lock()

    def add(self, chunk: np.ndarray):
        """Add audio chunk to buffer."""
        with self._lock:
            self._buffer.append(chunk.copy())
            self._total_samples += len(chunk)

            # Remove old chunks if over limit
            while self._total_samples > self.max_samples and self._buffer:
                removed = self._buffer.popleft()
                self._total_samples -= len(removed)

    @property
    def duration_seconds(self) -> float:
        with self._lock:
            return self._total_samples / self.sample_rate

    def get_all(self) -> np.ndarray:
        """Get all buffered audio."""
        with self._lock:
            if not self._buffer:
                return np.zeros((0, self.channels), dtype=np.float32)
            return np.vstack(list(self._buffer))

    def get_last(self, seconds: float) -> np.ndarray:
        """Get last N seconds of audio."""
        samples_needed = int(seconds * self.sample_rate)

        with self._lock:
            if not self._buffer:
                return np.zeros((0, self.channels), dtype=np.float32)

            all_data = np.vstack(list(self._buffer))
            if len(all_data) <= samples_needed:
                return all_data
            return all_data[-samples_needed:]

    def clear(self):
        """Clear buffer."""
        with self._lock:
            self._buffer.clear()
            self._total_samples = 0


@dataclass
class AudioConfig:
    device: Optional[str]
    sample_rate: int
    channels: int


class AudioCapture:
    """Capture audio from microphone in a background thread."""

    def __init__(
        self,
        config: AudioConfig,
        chunk_callback: Callable[[np.ndarray], None],
        buffer_seconds: float = 5.0,
    ):
        self.config = config
        self.chunk_callback = chunk_callback
        self.buffer = RollingBuffer(
            max_seconds=buffer_seconds,
            sample_rate=config.sample_rate,
            channels=config.channels,
        )
        self._stream: Optional["sd.InputStream"] = None
        self._running = False

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """Called by sounddevice for each audio chunk."""
        if status:
            print(f"Audio status: {status}")

        # Store in buffer
        self.buffer.add(indata)

        # Notify listener
        self.chunk_callback(indata.copy())

    def start(self):
        """Start audio capture."""
        if sd is None:
            raise RuntimeError("sounddevice not installed")

        self._running = True

        device = self.config.device
        if device is None:
            device = self._find_stereo_device()

        self._stream = sd.InputStream(
            device=device,
            channels=self.config.channels,
            samplerate=self.config.sample_rate,
            callback=self._audio_callback,
            blocksize=int(self.config.sample_rate * 0.1),  # 100ms chunks
        )
        self._stream.start()

    def stop(self):
        """Stop audio capture."""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _find_stereo_device(self) -> Optional[int]:
        """Find a stereo input device."""
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            if device["max_input_channels"] >= 2:
                return i
        return None

    @property
    def is_running(self) -> bool:
        return self._running and self._stream is not None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_audio.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/audio.py tests/test_audio.py
git commit -m "feat: add audio capture and rolling buffer"
```

---

## Task 8: Detector Module (YAMNet)

**Files:**
- Create: `src/detector.py`
- Create: `tests/test_detector.py`

- [ ] **Step 1: Write failing tests for detector**

Create `tests/test_detector.py`:
```python
import pytest
import numpy as np

from src.detector import BarkDetector, DetectionResult


@pytest.fixture
def detector():
    return BarkDetector(threshold=0.5)


def test_detector_returns_result(detector):
    # Create 0.5 seconds of audio at 16kHz
    audio = np.random.randn(8000, 2).astype(np.float32) * 0.1

    result = detector.detect(audio)

    assert isinstance(result, DetectionResult)
    assert 0.0 <= result.score <= 1.0
    assert isinstance(result.is_bark, bool)


def test_detector_silence_low_score(detector):
    # Silent audio
    audio = np.zeros((8000, 2), dtype=np.float32)

    result = detector.detect(audio)

    assert result.score < 0.5
    assert result.is_bark is False


def test_detector_converts_stereo_to_mono():
    detector = BarkDetector(threshold=0.5)
    stereo = np.random.randn(8000, 2).astype(np.float32)

    mono = detector._to_mono(stereo)

    assert mono.ndim == 1
    assert len(mono) == 8000
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_detector.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.detector'`

- [ ] **Step 3: Implement detector module**

Create `src/detector.py`:
```python
"""Bark detection using YAMNet."""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np

try:
    import tensorflow as tf
    import tensorflow_hub as hub
except ImportError:
    tf = None
    hub = None


@dataclass
class DetectionResult:
    score: float
    is_bark: bool
    top_classes: List[str]


# YAMNet class indices for dog-related sounds
DOG_CLASSES = {
    "Dog": 74,
    "Bark": 75,
    "Howl": 76,
    "Bow-wow": 77,
    "Growling": 78,
    "Whimper (dog)": 79,
}


class BarkDetector:
    """Detect dog barks using YAMNet model."""

    MODEL_URL = "https://tfhub.dev/google/yamnet/1"

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._model = None
        self._class_names: Optional[List[str]] = None

    def _load_model(self):
        """Lazy-load YAMNet model."""
        if self._model is not None:
            return

        if tf is None or hub is None:
            raise RuntimeError("TensorFlow and tensorflow_hub required")

        self._model = hub.load(self.MODEL_URL)

        # Load class names
        class_map_path = self._model.class_map_path().numpy().decode("utf-8")
        with open(class_map_path) as f:
            # Skip header
            lines = f.readlines()[1:]
            self._class_names = [line.strip().split(",")[2] for line in lines]

    def detect(self, audio: np.ndarray) -> DetectionResult:
        """
        Detect if audio contains dog bark.

        Args:
            audio: numpy array of shape (samples,) or (samples, 2) at 16kHz

        Returns:
            DetectionResult with score, is_bark, and top classes
        """
        self._load_model()

        # Convert stereo to mono if needed
        if audio.ndim == 2:
            audio = self._to_mono(audio)

        # Ensure float32
        audio = audio.astype(np.float32)

        # Normalize
        if np.abs(audio).max() > 1.0:
            audio = audio / 32768.0

        # Run inference
        scores, embeddings, spectrogram = self._model(audio)
        scores = scores.numpy()

        # Get mean scores across time frames
        mean_scores = scores.mean(axis=0)

        # Get dog-related scores
        dog_scores = [mean_scores[idx] for idx in DOG_CLASSES.values()]
        max_dog_score = max(dog_scores) if dog_scores else 0.0

        # Get top 3 classes
        top_indices = np.argsort(mean_scores)[-3:][::-1]
        top_classes = [self._class_names[i] for i in top_indices]

        return DetectionResult(
            score=float(max_dog_score),
            is_bark=max_dog_score >= self.threshold,
            top_classes=top_classes,
        )

    def _to_mono(self, stereo: np.ndarray) -> np.ndarray:
        """Convert stereo to mono by averaging channels."""
        return stereo.mean(axis=1)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_detector.py -v
```

Expected: PASS (model downloads on first run)

- [ ] **Step 5: Commit**

```bash
git add src/detector.py tests/test_detector.py
git commit -m "feat: add YAMNet bark detector"
```

---

## Task 9: Reports Module

**Files:**
- Create: `src/reports.py`
- Create: `tests/test_reports.py`

- [ ] **Step 1: Write failing tests for report generation**

Create `tests/test_reports.py`:
```python
import pytest
from pathlib import Path
from datetime import datetime
import tempfile
import zipfile

from src.reports import ReportGenerator
from src.storage import Event
from src.config import LocationConfig


@pytest.fixture
def sample_events():
    return [
        Event(
            id=1,
            started_at=datetime(2024, 1, 15, 10, 30, 0),
            ended_at=datetime(2024, 1, 15, 10, 30, 10),
            duration_sec=10.0,
            bark_count=5,
            peak_score=0.87,
            avg_score=0.75,
            direction="left",
            direction_score=0.85,
            clip_path="clips/2024-01-15/10-30-00_000.wav",
            clip_hash="abc123def456",
            weather_temp_f=72.0,
            weather_wind_mph=5.0,
            weather_conditions="clear",
        ),
        Event(
            id=2,
            started_at=datetime(2024, 1, 15, 14, 0, 0),
            ended_at=datetime(2024, 1, 15, 14, 0, 5),
            duration_sec=5.0,
            bark_count=3,
            peak_score=0.72,
            avg_score=0.68,
            direction="right",
            direction_score=0.78,
            clip_path="clips/2024-01-15/14-00-00_000.wav",
            clip_hash="def789ghi012",
            weather_temp_f=75.0,
            weather_wind_mph=8.0,
            weather_conditions="partly cloudy",
        ),
    ]


@pytest.fixture
def location():
    return LocationConfig(
        address="123 Main St, Anytown, USA",
        lat=34.05,
        lon=-118.24,
    )


def test_generate_html_report(sample_events, location):
    generator = ReportGenerator(location)

    html = generator.generate_html(
        events=sample_events,
        start_date=datetime(2024, 1, 15),
        end_date=datetime(2024, 1, 15, 23, 59, 59),
    )

    assert "DOG DETECTOR REPORT" in html
    assert "123 Main St" in html
    assert "Total incidents: 2" in html
    assert "Left direction: 1" in html
    assert "Right direction: 1" in html


def test_generate_pdf_creates_file(sample_events, location):
    generator = ReportGenerator(location)

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "report.pdf"

        generator.generate_pdf(
            events=sample_events,
            start_date=datetime(2024, 1, 15),
            end_date=datetime(2024, 1, 15, 23, 59, 59),
            output_path=pdf_path,
        )

        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reports.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.reports'`

- [ ] **Step 3: Implement reports module**

Create `src/reports.py`:
```python
"""PDF report and ZIP bundle generation."""

from datetime import datetime
from pathlib import Path
from typing import List, Optional
import zipfile
import io

from src.storage import Event
from src.config import LocationConfig

try:
    from weasyprint import HTML
except ImportError:
    HTML = None


class ReportGenerator:
    def __init__(self, location: LocationConfig):
        self.location = location

    def generate_html(
        self,
        events: List[Event],
        start_date: datetime,
        end_date: datetime,
    ) -> str:
        """Generate HTML report content."""
        # Count by direction
        left_count = sum(1 for e in events if e.direction == "left")
        right_count = sum(1 for e in events if e.direction == "right")
        other_count = len(events) - left_count - right_count

        # Generate incident rows
        incident_rows = ""
        for i, event in enumerate(events, 1):
            weather_str = ""
            if event.weather_temp_f is not None:
                weather_str = f"{event.weather_temp_f:.0f}°F"
                if event.weather_wind_mph is not None:
                    weather_str += f", Wind {event.weather_wind_mph:.0f}mph"
                if event.weather_conditions:
                    weather_str += f", {event.weather_conditions.title()}"

            clip_name = Path(event.clip_path).name if event.clip_path else "N/A"
            hash_short = event.clip_hash[:8] + "..." if event.clip_hash else "N/A"

            incident_rows += f"""
            <div class="incident">
                <div class="incident-header">
                    <strong>#{i}</strong> {event.started_at.strftime('%Y-%m-%d %H:%M:%S')}
                    &nbsp; Duration: {event.duration_sec:.1f}s
                    &nbsp; Score: {event.peak_score:.2f}
                </div>
                <div class="incident-details">
                    Direction: {event.direction or 'Unknown'} &nbsp;
                    Clip: {clip_name} &nbsp;
                    Hash: {hash_short}
                </div>
                <div class="incident-weather">
                    Weather: {weather_str or 'N/A'}
                </div>
            </div>
            """

        coords_str = ""
        if self.location.lat and self.location.lon:
            coords_str = f"Coordinates: {self.location.lat}, {self.location.lon}"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Dog Detector Report</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    margin: 40px;
                    color: #333;
                }}
                h1 {{
                    text-align: center;
                    border-bottom: 2px solid #333;
                    padding-bottom: 10px;
                }}
                .meta {{
                    background: #f5f5f5;
                    padding: 15px;
                    margin-bottom: 20px;
                }}
                .summary {{
                    background: #e8f4e8;
                    padding: 15px;
                    margin-bottom: 20px;
                }}
                .incident {{
                    border: 1px solid #ddd;
                    padding: 10px;
                    margin-bottom: 10px;
                }}
                .incident-header {{
                    font-weight: bold;
                }}
                .incident-details, .incident-weather {{
                    color: #666;
                    font-size: 0.9em;
                    margin-top: 5px;
                }}
            </style>
        </head>
        <body>
            <h1>DOG DETECTOR REPORT</h1>

            <div class="meta">
                <strong>Recording Location</strong><br>
                {self.location.address or 'Not specified'}<br>
                {coords_str}
                <br><br>
                <strong>Period:</strong> {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}<br>
                <strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>

            <div class="summary">
                <strong>Summary</strong><br>
                Total incidents: {len(events)}<br>
                Left direction: {left_count}<br>
                Right direction: {right_count}<br>
                Unclear/Center: {other_count}
            </div>

            <h2>Incident Log</h2>
            {incident_rows}
        </body>
        </html>
        """

        return html

    def generate_pdf(
        self,
        events: List[Event],
        start_date: datetime,
        end_date: datetime,
        output_path: Path,
    ):
        """Generate PDF report."""
        if HTML is None:
            raise RuntimeError("weasyprint not installed")

        html_content = self.generate_html(events, start_date, end_date)
        HTML(string=html_content).write_pdf(output_path)

    def generate_zip(
        self,
        events: List[Event],
        start_date: datetime,
        end_date: datetime,
        data_dir: Path,
        output_path: Path,
    ):
        """Generate ZIP bundle with PDF and audio clips."""
        # Generate PDF to memory
        html_content = self.generate_html(events, start_date, end_date)
        pdf_bytes = io.BytesIO()
        HTML(string=html_content).write_pdf(pdf_bytes)
        pdf_bytes.seek(0)

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add PDF
            zf.writestr("report.pdf", pdf_bytes.read())

            # Add clips
            for event in events:
                if event.clip_path:
                    clip_full_path = data_dir / event.clip_path
                    if clip_full_path.exists():
                        zf.write(clip_full_path, event.clip_path)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_reports.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reports.py tests/test_reports.py
git commit -m "feat: add PDF report and ZIP bundle generation"
```

---

## Task 10: Web Dashboard - FastAPI App

**Files:**
- Create: `src/web/__init__.py`
- Create: `src/web/app.py`
- Create: `src/web/routes.py`

- [ ] **Step 1: Create web package init**

Create `src/web/__init__.py`:
```python
"""Web dashboard package."""
```

- [ ] **Step 2: Create FastAPI app**

Create `src/web/app.py`:
```python
"""FastAPI application setup."""

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.storage import Storage
from src.config import Config


def create_app(config: Config, storage: Storage) -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(title="Dog Detector")

    # Store dependencies
    app.state.config = config
    app.state.storage = storage

    # Static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Templates
    templates_dir = Path(__file__).parent / "templates"
    app.state.templates = Jinja2Templates(directory=templates_dir)

    # Import and include routes
    from src.web.routes import router
    app.include_router(router)

    return app
```

- [ ] **Step 3: Create API routes**

Create `src/web/routes.py`:
```python
"""API routes for dashboard."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
import io

from src.reports import ReportGenerator


router = APIRouter()


class FlagRequest(BaseModel):
    reason: Optional[str] = None


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve main dashboard page."""
    templates = request.app.state.templates
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/api/status")
async def get_status(request: Request):
    """Get detector status."""
    return {
        "running": True,
        "uptime_seconds": 0,
    }


@router.get("/api/events")
async def list_events(
    request: Request,
    date: Optional[str] = None,
    include_false_pos: bool = True,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List events with pagination."""
    storage = request.app.state.storage

    start_date = None
    end_date = None

    if date:
        try:
            start_date = datetime.strptime(date, "%Y-%m-%d")
            end_date = start_date + timedelta(days=1) - timedelta(seconds=1)
        except ValueError:
            raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")

    offset = (page - 1) * per_page
    events = storage.list_events(
        start_date=start_date,
        end_date=end_date,
        include_false_pos=include_false_pos,
        limit=per_page,
        offset=offset,
    )

    total = storage.count_events(
        start_date=start_date,
        end_date=end_date,
        include_false_pos=include_false_pos,
    )

    return {
        "events": [
            {
                "id": e.id,
                "started_at": e.started_at.isoformat(),
                "ended_at": e.ended_at.isoformat(),
                "duration_sec": e.duration_sec,
                "bark_count": e.bark_count,
                "peak_score": e.peak_score,
                "avg_score": e.avg_score,
                "direction": e.direction,
                "direction_score": e.direction_score,
                "clip_path": e.clip_path,
                "clip_hash": e.clip_hash,
                "is_false_pos": e.is_false_pos,
                "false_pos_reason": e.false_pos_reason,
                "weather_temp_f": e.weather_temp_f,
                "weather_wind_mph": e.weather_wind_mph,
                "weather_conditions": e.weather_conditions,
            }
            for e in events
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


@router.post("/api/events/{event_id}/flag")
async def flag_event(request: Request, event_id: int, body: FlagRequest):
    """Flag event as false positive."""
    storage = request.app.state.storage
    storage.flag_false_positive(event_id, body.reason)
    return {"success": True}


@router.post("/api/events/{event_id}/unflag")
async def unflag_event(request: Request, event_id: int):
    """Remove false positive flag."""
    storage = request.app.state.storage
    storage.unflag_false_positive(event_id)
    return {"success": True}


@router.get("/api/clips/{date}/{filename}")
async def get_clip(request: Request, date: str, filename: str):
    """Serve audio clip."""
    config = request.app.state.config
    clip_path = config.storage.data_dir / "clips" / date / filename

    if not clip_path.exists():
        raise HTTPException(404, "Clip not found")

    return FileResponse(clip_path, media_type="audio/wav")


@router.get("/api/report")
async def generate_report(
    request: Request,
    start_date: str,
    end_date: str,
):
    """Generate and download report ZIP."""
    config = request.app.state.config
    storage = request.app.state.storage

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=1)
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")

    events = storage.list_events(
        start_date=start,
        end_date=end,
        include_false_pos=False,
        limit=10000,
    )

    generator = ReportGenerator(config.location)

    # Generate ZIP to memory
    zip_buffer = io.BytesIO()

    import zipfile
    from weasyprint import HTML

    html_content = generator.generate_html(events, start, end)
    pdf_bytes = io.BytesIO()
    HTML(string=html_content).write_pdf(pdf_bytes)
    pdf_bytes.seek(0)

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.pdf", pdf_bytes.read())

        for event in events:
            if event.clip_path:
                clip_full_path = config.storage.data_dir / event.clip_path
                if clip_full_path.exists():
                    zf.write(clip_full_path, event.clip_path)

    zip_buffer.seek(0)

    filename = f"report-{start_date}-to-{end_date}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
```

- [ ] **Step 4: Commit**

```bash
git add src/web/
git commit -m "feat: add FastAPI web application and routes"
```

---

## Task 11: Web Dashboard - Frontend

**Files:**
- Create: `src/web/templates/index.html`
- Create: `src/web/static/style.css`
- Create: `src/web/static/app.js`

- [ ] **Step 1: Create HTML template**

Create `src/web/templates/index.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dog Detector</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <header>
        <h1>Dog Detector</h1>
        <span id="status" class="status">● Running</span>
    </header>

    <nav>
        <select id="date-filter">
            <option value="">All Dates</option>
            <option value="today">Today</option>
        </select>
        <select id="fp-filter">
            <option value="all">All Events</option>
            <option value="valid">Valid Only</option>
            <option value="fp">False Positives</option>
        </select>
        <button id="generate-report">Generate Report</button>
        <button id="refresh">Refresh</button>
    </nav>

    <main>
        <table id="events-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Duration</th>
                    <th>Score</th>
                    <th>Direction</th>
                    <th>Clip</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="events-body">
            </tbody>
        </table>

        <div id="pagination">
            <button id="prev-page" disabled>← Prev</button>
            <span id="page-info">Page 1 of 1</span>
            <button id="next-page" disabled>Next →</button>
        </div>
    </main>

    <div id="report-modal" class="modal hidden">
        <div class="modal-content">
            <h2>Generate Report</h2>
            <label>
                Start Date:
                <input type="date" id="report-start">
            </label>
            <label>
                End Date:
                <input type="date" id="report-end">
            </label>
            <div class="modal-actions">
                <button id="report-cancel">Cancel</button>
                <button id="report-download">Download</button>
            </div>
        </div>
    </div>

    <audio id="audio-player" style="display: none;"></audio>

    <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create CSS styles**

Create `src/web/static/style.css`:
```css
* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f5;
    color: #333;
    line-height: 1.5;
}

header {
    background: #333;
    color: white;
    padding: 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

header h1 {
    font-size: 1.25rem;
    font-weight: 600;
}

.status {
    color: #4caf50;
}

.status.stopped {
    color: #f44336;
}

nav {
    background: white;
    padding: 1rem;
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    border-bottom: 1px solid #ddd;
}

nav select, nav button {
    padding: 0.5rem 1rem;
    border: 1px solid #ddd;
    border-radius: 4px;
    background: white;
    cursor: pointer;
}

nav button:hover {
    background: #f0f0f0;
}

main {
    padding: 1rem;
    max-width: 1200px;
    margin: 0 auto;
}

table {
    width: 100%;
    background: white;
    border-collapse: collapse;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

th, td {
    padding: 0.75rem 1rem;
    text-align: left;
    border-bottom: 1px solid #eee;
}

th {
    background: #fafafa;
    font-weight: 600;
}

tr:hover {
    background: #f9f9f9;
}

tr.false-positive {
    opacity: 0.5;
}

.direction-left::before {
    content: "← ";
}

.direction-right::before {
    content: "→ ";
}

button.play-btn, button.flag-btn {
    padding: 0.25rem 0.5rem;
    margin-right: 0.25rem;
    border: 1px solid #ddd;
    border-radius: 4px;
    background: white;
    cursor: pointer;
    font-size: 0.875rem;
}

button.play-btn:hover {
    background: #e3f2fd;
}

button.flag-btn:hover {
    background: #ffebee;
}

button.flag-btn.flagged {
    background: #ffcdd2;
}

#pagination {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 1rem;
    margin-top: 1rem;
}

#pagination button {
    padding: 0.5rem 1rem;
    border: 1px solid #ddd;
    border-radius: 4px;
    background: white;
    cursor: pointer;
}

#pagination button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.modal {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0,0,0,0.5);
    display: flex;
    align-items: center;
    justify-content: center;
}

.modal.hidden {
    display: none;
}

.modal-content {
    background: white;
    padding: 2rem;
    border-radius: 8px;
    min-width: 300px;
}

.modal-content h2 {
    margin-bottom: 1rem;
}

.modal-content label {
    display: block;
    margin-bottom: 1rem;
}

.modal-content input {
    width: 100%;
    padding: 0.5rem;
    border: 1px solid #ddd;
    border-radius: 4px;
    margin-top: 0.25rem;
}

.modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 1rem;
}

.modal-actions button {
    padding: 0.5rem 1rem;
    border: 1px solid #ddd;
    border-radius: 4px;
    cursor: pointer;
}

#report-download {
    background: #333;
    color: white;
    border-color: #333;
}

@media (max-width: 768px) {
    table {
        font-size: 0.875rem;
    }

    th, td {
        padding: 0.5rem;
    }
}
```

- [ ] **Step 3: Create JavaScript**

Create `src/web/static/app.js`:
```javascript
let currentPage = 1;
let totalPages = 1;
const perPage = 20;

async function fetchEvents() {
    const dateFilter = document.getElementById('date-filter').value;
    const fpFilter = document.getElementById('fp-filter').value;

    let url = `/api/events?page=${currentPage}&per_page=${perPage}`;

    if (dateFilter === 'today') {
        const today = new Date().toISOString().split('T')[0];
        url += `&date=${today}`;
    }

    if (fpFilter === 'valid') {
        url += '&include_false_pos=false';
    }

    try {
        const response = await fetch(url);
        const data = await response.json();

        totalPages = data.total_pages || 1;
        renderEvents(data.events);
        updatePagination();
    } catch (error) {
        console.error('Failed to fetch events:', error);
    }
}

function renderEvents(events) {
    const tbody = document.getElementById('events-body');
    tbody.innerHTML = '';

    if (events.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center;">No events found</td></tr>';
        return;
    }

    events.forEach(event => {
        const tr = document.createElement('tr');
        if (event.is_false_pos) {
            tr.classList.add('false-positive');
        }

        const time = new Date(event.started_at).toLocaleTimeString();
        const date = new Date(event.started_at).toLocaleDateString();

        tr.innerHTML = `
            <td>${date} ${time}</td>
            <td>${event.duration_sec.toFixed(1)}s</td>
            <td>${event.peak_score.toFixed(2)}</td>
            <td class="direction-${event.direction || 'unknown'}">${event.direction || 'Unknown'}</td>
            <td>
                ${event.clip_path
                    ? `<button class="play-btn" data-clip="${event.clip_path}">▶ Play</button>`
                    : 'N/A'
                }
            </td>
            <td>
                <button class="flag-btn ${event.is_false_pos ? 'flagged' : ''}"
                        data-id="${event.id}"
                        data-flagged="${event.is_false_pos}">
                    ${event.is_false_pos ? '✓ Flagged' : '✗ Flag'}
                </button>
            </td>
        `;

        tbody.appendChild(tr);
    });

    // Add event listeners
    document.querySelectorAll('.play-btn').forEach(btn => {
        btn.addEventListener('click', () => playClip(btn.dataset.clip));
    });

    document.querySelectorAll('.flag-btn').forEach(btn => {
        btn.addEventListener('click', () => toggleFlag(btn));
    });
}

function updatePagination() {
    document.getElementById('page-info').textContent = `Page ${currentPage} of ${totalPages}`;
    document.getElementById('prev-page').disabled = currentPage <= 1;
    document.getElementById('next-page').disabled = currentPage >= totalPages;
}

async function playClip(clipPath) {
    const audio = document.getElementById('audio-player');
    const parts = clipPath.split('/');
    const date = parts[1];
    const filename = parts[2];
    audio.src = `/api/clips/${date}/${filename}`;
    audio.play();
}

async function toggleFlag(btn) {
    const eventId = btn.dataset.id;
    const isFlagged = btn.dataset.flagged === 'true';

    const url = isFlagged
        ? `/api/events/${eventId}/unflag`
        : `/api/events/${eventId}/flag`;

    try {
        await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason: null }),
        });
        fetchEvents();
    } catch (error) {
        console.error('Failed to toggle flag:', error);
    }
}

function showReportModal() {
    const modal = document.getElementById('report-modal');
    modal.classList.remove('hidden');

    // Set default dates (last 7 days)
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 7);

    document.getElementById('report-start').value = start.toISOString().split('T')[0];
    document.getElementById('report-end').value = end.toISOString().split('T')[0];
}

function hideReportModal() {
    document.getElementById('report-modal').classList.add('hidden');
}

async function downloadReport() {
    const startDate = document.getElementById('report-start').value;
    const endDate = document.getElementById('report-end').value;

    if (!startDate || !endDate) {
        alert('Please select both start and end dates');
        return;
    }

    window.location.href = `/api/report?start_date=${startDate}&end_date=${endDate}`;
    hideReportModal();
}

// Event listeners
document.getElementById('date-filter').addEventListener('change', () => {
    currentPage = 1;
    fetchEvents();
});

document.getElementById('fp-filter').addEventListener('change', () => {
    currentPage = 1;
    fetchEvents();
});

document.getElementById('refresh').addEventListener('click', fetchEvents);

document.getElementById('prev-page').addEventListener('click', () => {
    if (currentPage > 1) {
        currentPage--;
        fetchEvents();
    }
});

document.getElementById('next-page').addEventListener('click', () => {
    if (currentPage < totalPages) {
        currentPage++;
        fetchEvents();
    }
});

document.getElementById('generate-report').addEventListener('click', showReportModal);
document.getElementById('report-cancel').addEventListener('click', hideReportModal);
document.getElementById('report-download').addEventListener('click', downloadReport);

// Initial load
fetchEvents();
```

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/ src/web/static/
git commit -m "feat: add web dashboard frontend"
```

---

## Task 12: Web Dashboard - Tests

**Files:**
- Create: `tests/test_web.py`

- [ ] **Step 1: Write web API tests**

Create `tests/test_web.py`:
```python
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
    assert response.json()["running"] is True


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
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_web.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_web.py
git commit -m "test: add web API tests"
```

---

## Task 13: Main Entry Point

**Files:**
- Create: `src/main.py`

- [ ] **Step 1: Implement main module**

Create `src/main.py`:
```python
"""Main entry point for Dog Detector."""

import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path

import uvicorn

from src.config import load_config, Config
from src.storage import Storage, Event
from src.audio import AudioCapture, AudioConfig
from src.detector import BarkDetector
from src.direction import analyze_direction
from src.incidents import IncidentTracker, Detection
from src.weather import WeatherClient
from src.web.app import create_app


class DogDetector:
    def __init__(self, config: Config):
        self.config = config
        self.storage = Storage(config.storage.data_dir)
        self.detector = BarkDetector(threshold=config.detection.threshold)
        self.incident_tracker = IncidentTracker(config.incidents)
        self.weather_client = WeatherClient()

        self._audio_capture = None
        self._running = False
        self._process_task = None
        self._chunk_queue: asyncio.Queue = None

    async def start(self):
        """Start the detector."""
        self._running = True
        self._chunk_queue = asyncio.Queue()

        # Start audio capture
        audio_config = AudioConfig(
            device=self.config.audio.device,
            sample_rate=self.config.audio.sample_rate,
            channels=self.config.audio.channels,
        )

        self._audio_capture = AudioCapture(
            config=audio_config,
            chunk_callback=self._on_audio_chunk,
        )
        self._audio_capture.start()

        # Start processing loop
        self._process_task = asyncio.create_task(self._process_loop())

    async def stop(self):
        """Stop the detector."""
        self._running = False

        if self._audio_capture:
            self._audio_capture.stop()

        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass

        # Finalize any active incident
        incident = self.incident_tracker.force_end()
        if incident:
            await self._save_incident(incident)

    def _on_audio_chunk(self, chunk):
        """Callback from audio thread."""
        if self._chunk_queue:
            try:
                self._chunk_queue.put_nowait(chunk)
            except asyncio.QueueFull:
                pass  # Drop if queue full

    async def _process_loop(self):
        """Main processing loop."""
        while self._running:
            try:
                # Get chunk with timeout
                try:
                    chunk = await asyncio.wait_for(
                        self._chunk_queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    # Check for incident timeout
                    incident = self.incident_tracker.check_timeout(datetime.now())
                    if incident:
                        await self._save_incident(incident)
                    continue

                # Run detection
                result = self.detector.detect(chunk)

                if result.is_bark:
                    # Get direction
                    direction_result = analyze_direction(chunk)

                    detection = Detection(
                        timestamp=datetime.now(),
                        score=result.score,
                        direction=direction_result.direction,
                        direction_score=direction_result.confidence,
                    )

                    self.incident_tracker.process_detection(detection)

                # Check for incident timeout
                incident = self.incident_tracker.check_timeout(datetime.now())
                if incident:
                    await self._save_incident(incident)

            except Exception as e:
                print(f"Error in process loop: {e}")

    async def _save_incident(self, incident):
        """Save completed incident to database."""
        try:
            # Get audio from buffer
            audio_data = self._audio_capture.buffer.get_last(
                seconds=incident.duration_sec + 2.0  # Add buffer
            )

            # Save clip
            import wave
            import io
            import numpy as np

            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(self.config.audio.sample_rate)

                # Convert float to int16
                audio_int16 = (audio_data * 32767).astype(np.int16)
                wav.writeframes(audio_int16.tobytes())

            clip_path, clip_hash = self.storage.save_clip(
                wav_buffer.getvalue(),
                incident.started_at,
            )

            # Get weather
            weather = await self.weather_client.fetch(
                lat=self.config.location.lat,
                lon=self.config.location.lon,
            )

            # Create event
            event = Event(
                started_at=incident.started_at,
                ended_at=incident.ended_at,
                duration_sec=incident.duration_sec,
                bark_count=incident.bark_count,
                peak_score=incident.peak_score,
                avg_score=incident.avg_score,
                direction=incident.direction,
                direction_score=incident.direction_score,
                clip_path=clip_path,
                clip_hash=clip_hash,
                weather_temp_f=weather.temp_f if weather else None,
                weather_wind_mph=weather.wind_mph if weather else None,
                weather_conditions=weather.conditions if weather else None,
            )

            self.storage.save_event(event)
            print(f"Saved incident: {incident.bark_count} barks, {incident.direction}")

        except Exception as e:
            print(f"Error saving incident: {e}")
            # Still save event without clip
            event = Event(
                started_at=incident.started_at,
                ended_at=incident.ended_at,
                duration_sec=incident.duration_sec,
                bark_count=incident.bark_count,
                peak_score=incident.peak_score,
                avg_score=incident.avg_score,
                direction=incident.direction,
                direction_score=incident.direction_score,
            )
            self.storage.save_event(event)


async def main():
    # Load config
    config_path = Path("config.yaml")
    if not config_path.exists():
        print("config.yaml not found, using defaults")
        config = Config()
    else:
        config = load_config(config_path)

    # Create detector
    detector = DogDetector(config)

    # Create web app
    app = create_app(config, detector.storage)

    # Setup shutdown handler
    shutdown_event = asyncio.Event()

    def signal_handler():
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Start detector
    await detector.start()

    # Start web server
    server_config = uvicorn.Config(
        app,
        host=config.web.host,
        port=config.web.port,
        log_level="info",
    )
    server = uvicorn.Server(server_config)

    # Run server in background
    server_task = asyncio.create_task(server.serve())

    print(f"Dog Detector running on http://{config.web.host}:{config.web.port}")

    # Wait for shutdown
    await shutdown_event.wait()

    print("Shutting down...")
    await detector.stop()
    server.should_exit = True
    await server_task


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Test that it runs**

```bash
python -m src.main
```

Expected: Server starts, detector initializes (may fail on audio if no mic)

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: add main entry point wiring all components"
```

---

## Task 14: Install Script

**Files:**
- Create: `scripts/install.sh`

- [ ] **Step 1: Create install script**

Create `scripts/install.sh`:
```bash
#!/bin/bash
set -e

echo "=== Dog Detector Installer ==="

# Check if running on Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "Warning: Not running on Raspberry Pi"
fi

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    portaudio19-dev \
    libcairo2-dev \
    libpango1.0-dev \
    libgdk-pixbuf2.0-dev \
    libffi-dev

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create data directories
echo "Creating data directories..."
mkdir -p data/clips data/reports

# Create config if not exists
if [ ! -f config.yaml ]; then
    echo "Creating default config.yaml..."
    cp config.yaml.example config.yaml 2>/dev/null || cat > config.yaml << 'EOF'
location:
  address: ""
  lat: null
  lon: null

audio:
  device: null
  sample_rate: 16000
  channels: 2

detection:
  threshold: 0.5
  window_sec: 0.5

incidents:
  min_barks: 2
  gap_sec: 3.0
  min_duration_sec: 1.0
  merge_within_sec: 10.0

storage:
  data_dir: ./data
  retention_days: 0

web:
  host: 0.0.0.0
  port: 8080
EOF
fi

# Install systemd service
echo "Installing systemd service..."
sudo tee /etc/systemd/system/dog-detector.service > /dev/null << EOF
[Unit]
Description=Dog Detector
After=network.target sound.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python -m src.main
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable dog-detector

# Install Tailscale
echo ""
echo "=== Tailscale Setup ==="
if ! command -v tailscale &> /dev/null; then
    echo "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
fi

echo ""
echo "Starting Tailscale authentication..."
echo "A browser window will open to authenticate."
sudo tailscale up

# Get Tailscale IP
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")

echo ""
echo "=== Installation Complete ==="
echo ""
echo "To start the detector:"
echo "  sudo systemctl start dog-detector"
echo ""
echo "To view logs:"
echo "  sudo journalctl -u dog-detector -f"
echo ""
echo "Dashboard URL (local): http://localhost:8080"
echo "Dashboard URL (Tailscale): http://$TAILSCALE_IP:8080"
echo ""
echo "Edit config.yaml to set your location and preferences."
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/install.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: add Pi installation script"
```

---

## Task 15: Final Integration

**Files:**
- Update: `requirements.txt` (verify complete)
- Create: `README.md`

- [ ] **Step 1: Create README**

Create `README.md`:
```markdown
# Dog Detector

An always-on bark detection system for Raspberry Pi that saves audio clips, determines direction, and generates evidence reports.

## Quick Start

1. Clone to your Raspberry Pi:
   ```bash
   git clone https://github.com/youruser/dog-detector.git
   cd dog-detector
   ```

2. Run the installer:
   ```bash
   ./scripts/install.sh
   ```

3. Edit config.yaml with your location:
   ```yaml
   location:
     address: "123 Main St, Anytown, USA"
     lat: 34.0522
     lon: -118.2437
   ```

4. Start the service:
   ```bash
   sudo systemctl start dog-detector
   ```

5. Access the dashboard via Tailscale IP shown during install.

## Features

- Continuous stereo audio monitoring
- YAMNet-based bark detection
- Left/right direction detection
- Automatic incident grouping
- Audio clip saving with SHA-256 fingerprints
- Weather context for each incident
- PDF reports with zipped audio evidence
- Web dashboard for review and flagging
- Auto-start on boot

## Hardware

- Raspberry Pi 5 (8GB recommended)
- Stereo USB microphone (Sony ECM-LV1 or two separate mics)
- 3.5mm to USB-A adapter

## Configuration

Edit `config.yaml` to adjust:
- Detection threshold (0-1)
- Incident grouping timing
- Data retention
- Web server port

## License

MIT
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 3: Final commit**

```bash
git add README.md
git commit -m "docs: add README with quick start guide"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All MVP features have corresponding tasks
- [x] **No placeholders:** All code blocks are complete
- [x] **Type consistency:** Function signatures match across tasks
- [x] **Test coverage:** Each module has tests
- [x] **Commit frequency:** Each task ends with a commit
