# Dog Detector MVP Design Specification

## Overview

Dog Detector is an always-on system that runs on a Raspberry Pi 5, listens for barking, saves audio clips, determines direction, and generates evidence reports. This spec covers the MVP implementation.

## MVP Scope

**Included:**
- Continuous stereo audio capture from USB microphone
- Bark detection using YAMNet (pre-trained ML model)
- Incident grouping (bursts of barks → single event)
- Direction detection (left/right channel intensity comparison)
- Audio clip saving with SHA-256 fingerprints
- SQLite database for event storage
- Location metadata and weather context per incident
- Web dashboard (list events, play clips, flag false positives)
- PDF reports with zipped audio clips
- Auto-start on boot via systemd
- Remote access via Tailscale

**Deferred to v2:**
- Dog identity learning (recognizing specific dogs by bark)
- Push notifications
- Calibration wizard
- Advanced health monitoring

## Hardware

- CanaKit Raspberry Pi 5 Starter Kit Turbine Black (8GB RAM, 128GB storage)
- Sony ECM-LV1 Compact Stereo Lavalier Microphone
- 3.5mm to USB-A audio adapter

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Runtime | Python 3.11+ | Best audio/ML ecosystem |
| Audio capture | sounddevice | Cross-platform, USB audio support, stereo |
| ML inference | TensorFlow Lite + YAMNet | Pre-trained bark detection, runs on Pi |
| Database | SQLite | Simple, no server, file-based backup |
| Web framework | FastAPI | Async-native, serves static files |
| PDF generation | weasyprint | HTML-to-PDF, easy styling |
| Process manager | systemd | Standard on Raspberry Pi OS |
| Remote access | Tailscale | One command setup, no domain needed |

## Architecture

Single Python process with async event loop. Audio capture runs in a dedicated thread (required by sounddevice), feeds chunks to an async queue. All other components run in the main async loop.

```
┌─────────────────────────────────────────────────────────────────┐
│                         Main Process                            │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ Audio Thread │───▶│ Async Queue  │───▶│ Bark Detector    │  │
│  │ (sounddevice)│    │ (chunks)     │    │ (YAMNet)         │  │
│  └──────────────┘    └──────────────┘    └────────┬─────────┘  │
│         │                                         │             │
│         │                                         ▼             │
│         │                                ┌──────────────────┐   │
│         │                                │ Incident Manager │   │
│         │                                │ (grouping logic) │   │
│         │                                └────────┬─────────┘   │
│         │                                         │             │
│         ▼                                         ▼             │
│  ┌──────────────┐                        ┌──────────────────┐   │
│  │ Rolling      │───────────────────────▶│ Clip Saver       │   │
│  │ Buffer (5s)  │                        │ (WAV + hash)     │   │
│  └──────────────┘                        └────────┬─────────┘   │
│                                                   │             │
│                                                   ▼             │
│                                          ┌──────────────────┐   │
│                                          │ SQLite Database  │   │
│                                          └────────┬─────────┘   │
│                                                   │             │
│  ┌──────────────────────────────────────────────┐ │             │
│  │ FastAPI Web Server                           │◀┘             │
│  │ - Dashboard (list/play/flag events)          │               │
│  │ - Settings API                               │               │
│  │ - Report generation                          │               │
│  └──────────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

## Components

| Component | Responsibility |
|-----------|----------------|
| Audio Thread | Captures stereo audio from USB mic, pushes chunks to async queue, maintains 5-second rolling buffer |
| Bark Detector | Runs YAMNet inference on audio chunks, outputs bark confidence score |
| Direction Analyzer | Compares left/right channel RMS intensity, determines direction |
| Incident Manager | Groups bark detections into incidents using state machine, tracks start/end times |
| Clip Saver | Extracts audio from rolling buffer, writes WAV file, computes SHA-256 hash |
| Weather Fetcher | Calls Open-Meteo API to get current conditions when incident ends |
| Database | SQLite operations for event storage and retrieval |
| Web Server | FastAPI app serving dashboard, clip playback, and report generation |

## Data Model

### SQLite Schema

```sql
CREATE TABLE events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at         TEXT NOT NULL,      -- ISO 8601 timestamp
    ended_at           TEXT NOT NULL,      -- ISO 8601 timestamp
    duration_sec       REAL NOT NULL,      -- ended_at - started_at
    bark_count         INTEGER NOT NULL,   -- number of bark detections
    peak_score         REAL NOT NULL,      -- highest YAMNet confidence (0-1)
    avg_score          REAL NOT NULL,      -- average confidence
    direction          TEXT,               -- 'left', 'right', 'center', or null
    direction_score    REAL,               -- confidence (0-1)
    clip_path          TEXT,               -- relative: clips/2024-01-15/14-32-05_123.wav
    clip_hash          TEXT,               -- SHA-256 of WAV file
    is_false_pos       INTEGER DEFAULT 0,  -- 1 if flagged as false positive
    false_pos_reason   TEXT,               -- optional note
    weather_temp_f     REAL,               -- temperature at incident time
    weather_wind_mph   REAL,               -- wind speed
    weather_conditions TEXT,               -- "clear", "cloudy", "rain", etc.
    created_at         TEXT NOT NULL       -- when row was inserted
);

CREATE INDEX idx_events_started_at ON events(started_at);
CREATE INDEX idx_events_is_false_pos ON events(is_false_pos);
```

## Configuration

### config.yaml

```yaml
# Location metadata
location:
  address: ""           # Property address for report header
  lat: null             # Latitude for weather lookup
  lon: null             # Longitude for weather lookup

# Audio input
audio:
  device: null          # null = auto-detect stereo USB input
  sample_rate: 16000    # YAMNet expects 16kHz
  channels: 2           # Stereo required

# Bark detection
detection:
  threshold: 0.5        # YAMNet confidence to count as bark (0-1)
  window_sec: 0.5       # Audio chunk size for inference

# Incident grouping
incidents:
  min_barks: 2          # Minimum detections to start incident
  gap_sec: 3.0          # Silence gap to end incident
  min_duration_sec: 1.0 # Discard incidents shorter than this
  merge_within_sec: 10.0 # Merge incidents this close together

# Storage
storage:
  data_dir: ./data      # Where clips and DB live
  retention_days: 0     # 0 = keep forever

# Web server
web:
  host: 0.0.0.0
  port: 8080
```

## Project Structure

```
dog-detector/
├── config.yaml
├── data/
│   ├── events.sqlite
│   ├── clips/
│   │   └── YYYY-MM-DD/
│   │       └── HH-MM-SS_mmm.wav
│   └── reports/
│       └── report-YYYY-MM-DD-to-YYYY-MM-DD.zip
├── src/
│   ├── __init__.py
│   ├── main.py             # Entry point
│   ├── config.py           # Load/validate config.yaml
│   ├── audio.py            # Audio capture, rolling buffer
│   ├── detector.py         # YAMNet wrapper
│   ├── direction.py        # L/R intensity comparison
│   ├── incidents.py        # Incident state machine
│   ├── storage.py          # SQLite + clip saving
│   ├── weather.py          # Open-Meteo API client
│   ├── reports.py          # PDF + ZIP generation
│   └── web/
│       ├── __init__.py
│       ├── app.py          # FastAPI app
│       ├── routes.py       # API endpoints
│       ├── static/
│       │   ├── style.css
│       │   └── app.js
│       └── templates/
│           └── index.html
├── scripts/
│   └── install.sh
├── tests/
├── docs/
│   └── PRD.md
├── requirements.txt
└── README.md
```

## Web Dashboard

Single-page interface, clean and utilitarian. No JavaScript framework, just vanilla HTML/CSS/JS.

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Dog Detector                              ● Running         │
├─────────────────────────────────────────────────────────────┤
│  [Today ▼]  [All ▼]  [Generate Report]                      │
├─────────────────────────────────────────────────────────────┤
│  TIME        DURATION   SCORE   DIR     CLIP     ACTIONS    │
│  ─────────────────────────────────────────────────────────  │
│  14:32:05    8.2s       0.87    ← Left  [▶ Play] [✗ Flag]   │
│  13:15:22    3.1s       0.72    → Right [▶ Play] [✗ Flag]   │
│  11:45:00    12.4s      0.91    ← Left  [▶ Play] [✗ Flag]   │
├─────────────────────────────────────────────────────────────┤
│  Page 1 of 12                           [← Prev] [Next →]   │
└─────────────────────────────────────────────────────────────┘
```

### Features

- Status indicator (running/stopped)
- Filter by date and false-positive status
- Expandable rows showing weather and false-positive reason input
- Inline clip playback (HTML5 audio)
- Flag/unflag false positives with optional reason
- Generate Report: date picker modal, downloads ZIP containing PDF and clips
- Manual refresh (no live updates in MVP)
- Mobile-friendly, system fonts

## Report Generation

### PDF Contents

```
┌─────────────────────────────────────────────────────────────┐
│                     DOG DETECTOR REPORT                      │
│                                                              │
│  RECORDING LOCATION                                          │
│  123 Main St, Anytown, USA                                   │
│  Coordinates: 34.0522, -118.2437                            │
│                                                              │
│  Period: 2024-01-01 to 2024-01-15                           │
│  Generated: 2024-01-15 16:32:00                             │
├─────────────────────────────────────────────────────────────┤
│  SUMMARY                                                     │
│  Total incidents: 47                                         │
│  Left direction: 31                                          │
│  Right direction: 14                                         │
│  Unclear: 2                                                  │
├─────────────────────────────────────────────────────────────┤
│  INCIDENT LOG                                                │
│                                                              │
│  #1  2024-01-01 08:15:22  Duration: 12.4s  Score: 0.91      │
│      Direction: Left    Clip: 08-15-22_401.wav               │
│      Hash: a3f2c8...                                         │
│      Weather: 72°F, Wind 5mph, Clear                         │
│  ...                                                         │
└─────────────────────────────────────────────────────────────┘
```

### ZIP Bundle

```
report-2024-01-01-to-2024-01-15.zip
├── report.pdf
└── clips/
    ├── 2024-01-01/
    │   ├── 08-15-22_401.wav
    │   └── 09-45-10_882.wav
    └── 2024-01-02/
        └── ...
```

False positives excluded by default.

## Deployment

### install.sh

The install script handles complete Pi setup:

1. Install system dependencies (python3, pip, portaudio)
2. Create virtualenv and install Python packages
3. Create data directories
4. Generate default config.yaml if missing
5. Install and enable systemd service
6. Install Tailscale and prompt for authentication
7. Print dashboard URL

### systemd Service

```ini
[Unit]
Description=Dog Detector
After=network.target sound.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/dog-detector
ExecStart=/home/pi/dog-detector/venv/bin/python -m src.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Tailscale

- Installed via official install script
- `sudo tailscale up` prompts for browser authentication
- Pi gets stable 100.x.x.x IP accessible from any device on the tailnet
- Dashboard accessible at `http://100.x.x.x:8080`

## Error Handling

- If USB mic not found: log error, set health status to critical, retry periodically
- If clip write fails: save event row anyway with null clip_path
- If weather API fails: save event with null weather fields, log warning
- If database write fails: log error, do not lose audio (retry with backoff)
- Service crashes: systemd restarts automatically after 5 seconds

## Testing Strategy

- Unit tests for each component (detector, incidents, direction, storage)
- Integration test with sample audio files
- Manual testing on Pi hardware before deployment

## Open Questions (Resolved)

All design questions resolved during brainstorming session.
