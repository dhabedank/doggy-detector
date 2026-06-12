# Doggy Detector

An always-on bark detection system for Raspberry Pi that saves audio clips, determines direction, and generates evidence reports.

## Requirements

- **Python 3.11** (recommended) or 3.12
  - Python 3.13+ is not supported (TensorFlow compatibility)
- USB microphone (stereo recommended for direction detection)

## Quick Start (Raspberry Pi)

1. Clone to your Raspberry Pi:
   ```bash
   git clone https://github.com/youruser/doggy-detector.git
   cd doggy-detector
   ```

2. Run the installer:
   ```bash
   ./scripts/install.sh
   ```

3. Start the service:
   ```bash
   sudo systemctl start doggy-detector
   ```

4. View the startup logs and copy the generated dashboard username/password:
   ```bash
   sudo journalctl -u doggy-detector -f
   ```

5. Access the dashboard via Tailscale IP shown during install, log in with those credentials, then use Settings to set your location and preferences.

## Local Development

### Linux / Windows (x86)

```bash
# Create virtual environment with Python 3.11
python3.11 -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install TensorFlow first, then other dependencies
pip install "tensorflow>=2.15.0"
pip install -r requirements.txt

# Run
python -m src.main
```

### macOS (Apple Silicon)

```bash
# Install Python 3.11 via Homebrew if needed
brew install python@3.11

# Create virtual environment
/opt/homebrew/bin/python3.11 -m venv venv
source venv/bin/activate

# Install Apple Silicon TensorFlow, then other dependencies
pip install "tensorflow-macos>=2.15.0"
pip install -r requirements.txt

# Run
python -m src.main
```

Dashboard: http://localhost:8080

The dashboard uses one local login per device. The first startup logs dashboard credentials, and normal restarts keep using those same credentials. The app stores the username and only a bcrypt password hash in `data/events.sqlite`.
Set `DOG_DETECTOR_AUTH_USERNAME` and `DOG_DETECTOR_AUTH_PASSWORD` before first startup if you want to choose them yourself.

If you forget the dashboard password, reset only the login credentials:

```bash
touch data/reset-dashboard-login
sudo systemctl restart doggy-detector
sudo journalctl -u doggy-detector -f
```

The restart logs a new password and keeps existing settings, events, clips, and reports.
For a one-off local run, `DOG_DETECTOR_RESET_AUTH=1 python -m src.main` does the same reset.

## Remote Updates Over Tailscale

After the first install, you can update the unit remotely over Tailscale without plugging in a keyboard, mouse, or monitor.

Installed units check GitHub release tags once per day and show update status in the dashboard Settings page. Daily checks do not auto-install releases. Use the Settings page to check immediately or queue an install sooner.

The updater installs tagged GitHub releases, updates Python dependencies, restarts `doggy-detector`, and writes status/logs under `data/update-state.json`. Runtime data in `data/events.sqlite`, clips, reports, settings, and dashboard login data are left alone.

Create and push releases from your workstation with tags like:

```bash
git tag v0.1.0
git push origin v0.1.0
```

SSH into the Raspberry Pi:

```bash
ssh pi@<tailscale-ip>
cd ~/doggy-detector
```

Update to a tagged GitHub release:

```bash
git fetch --tags
git tag --sort=-v:refname | head
git checkout v0.0.0  # replace with the release tag you want
venv/bin/pip install -r requirements.txt
sudo systemctl restart doggy-detector
```

Check for updates manually:

```bash
venv/bin/python -m src.updater check
venv/bin/python -m src.updater status
```

Queue and apply the latest release from SSH:

```bash
venv/bin/python -m src.updater request latest
sudo systemctl start doggy-detector-updater
```

Check that the service came back healthy:

```bash
curl -fsS http://127.0.0.1:8080/health | python3 -m json.tool
sudo journalctl -u doggy-detector -n 80 --no-pager
sudo journalctl -u doggy-detector-updater -n 80 --no-pager
```

If the update does not behave correctly, roll back to the previous release tag:

```bash
git checkout <previous-release-tag>
venv/bin/pip install -r requirements.txt
sudo systemctl restart doggy-detector
```

Updates replace the application code and Python dependencies only. They do not wipe `data/events.sqlite`, saved clips, report exports, settings, or dashboard login data.

## Using the Dashboard

### Live Status Bar

The status bar at the top shows real-time detection info:
- **Input**: Audio input level (0-1) - shows if the mic is picking up sound
- **Bark**: Detection score (0-1) - how confident the model is it's hearing a bark
- **Status**: Current state (Listening, BARK DETECTED, INCIDENT IN PROGRESS)
- **Chunks**: Number of audio chunks processed since startup

### Deterrence / Deterrence

The dashboard includes manual deterrence controls for audible output, ultrasonic output, or both.
Settings also allow automatic deterrence when bark detections pass a configured threshold.

Deterrence actions are always bounded bursts. The system logs every manual or automatic firing attempt in SQLite with the mode, source, profile, duration, bark score when available, and any actuator error.

Supported output paths:
- **Audible**: plays a short generated chirp/alarm profile through the configured output device.
- **Ultrasonic**: pulses a GPIO-controlled relay or optocoupler that triggers an external ultrasonic deterrent.

For ultrasonic hardware, use a powered ultrasonic deterrent/module with its own driver and a triggerable button or low-voltage input. Do not assume a normal speaker, headset adapter, or bare piezo disc can produce useful ultrasonic deterrence from the Pi audio jack alone.

### Events Table

Lists all detected bark incidents with:
- Timestamp and duration
- Detection confidence score
- Direction (left/right arrow) - requires stereo mic
- Details button with larger clip playback, weather, scores, and clip fingerprint
- False-positive reason picker
- Delete button to remove test incidents and their saved clips

### Settings (gear icon)

- **Microphone**: Use the system default input or pin a monitoring microphone by name
- **Detection Threshold**: Exact threshold for bark detection (0.001-1.0)
  - Lower = more sensitive (may catch more false positives)
  - Higher = less sensitive (may miss quieter barks)
  - Fresh installs default to 0.15; use incident scores and calibration data to tune
- **Barking Sessions**:
  - Barks to start: detections required before a session becomes real
  - Silence gap: seconds without a bark above threshold before cooldown starts
  - Merge window: extra seconds where resumed barking continues the same session
  - Pre-roll audio: 5/10/15/20 seconds included before the session starts
  - Minimum duration: very short confirmed sessions below this length are discarded
- **Location**: Address and coordinates for weather data in reports
- **Deterrence**: audible/ultrasonic enablement, manual and automatic firing, burst length, cooldown, maximum automatic firings, quiet hours, GPIO pin, and audible output profile

### Reports

Click "Export Results" to download a ZIP evidence package containing:
- **PDF Report**: Formatted document with incident summary, calibration values, weather context, report key, and evidence-package explanation
- **CSV Export**: Raw data for spreadsheet analysis, including threshold, input-level calibration fields, and full clip hashes
- **Audio Clips**: Referenced WAV clips for non-false-positive incidents in the report period

## How Detection Works

1. Audio is captured in short chunks from the microphone using the configured detection window
2. Google's YAMNet model classifies each chunk into 521 sound categories
3. If dog-related classes (Dog, Bark, Animal, etc.) score above threshold, it's a bark
4. A session starts after the configured number of bark detections
5. Once a session is confirmed, recording includes the configured pre-roll audio from the rolling buffer
6. If no bark is detected for the silence gap, the session enters cooldown
7. If barking returns inside the merge window, the same session continues
8. If no bark returns, the session is saved after `silence gap + merge window`

With defaults, the detector enters cooldown after 15 seconds without a bark above threshold and saves the session after 25 seconds without a new bark.

### Mono vs Stereo Mode

- **Stereo mic**: Full functionality including left/right direction detection
- **Mono mic**: Bark detection works, but direction shows as "unknown"

The system automatically falls back to mono if stereo isn't available.

## Configuration

Runtime settings live in `data/events.sqlite`, not in a live `config.yaml` file. Use the dashboard Settings screen to adjust:

- microphone device
- detection threshold
- barking session timing
- report location and weather coordinates

On first startup only, an existing `config.yaml` is migrated into SQLite and renamed to `config.yaml.migrated` when possible.

Set `DOG_DETECTOR_DATA_DIR` if you need the database, clips, and reports somewhere other than `./data`.

### Finding Your Audio Device

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

Settings stores newly selected microphones by device name and host API, not by index number. This is more stable when other devices like AirPods are connected or removed.

## Troubleshooting

### "Input" meter stays at 0
- Check microphone permissions (System Preferences > Privacy > Microphone)
- Verify the correct device is selected in Settings
- Pin the mounted monitoring microphone in Settings instead of using the system default input

### Model detects speech/music instead of barks
- The YAMNet model classifies all sounds - `['Silence', 'Speech', 'Music']` means no dog sounds detected
- When barks are heard, you'll see `['Dog', 'Bark', 'Animal']`
- Watch the live Bark score while playing known bark audio near the microphone

### Detection too sensitive / not sensitive enough
- Adjust threshold in Settings (gear icon)
- Lower values (0.03-0.15) = more detections
- Higher values (0.3-0.5) = fewer detections
- Review each incident's peak score, average score, threshold used, and input level to tune the threshold.

### Audio device keeps resetting
- Pin the mounted monitoring microphone by name in Settings instead of using the system default input
- If a pinned microphone is missing, the detector reports an audio error instead of silently switching to another mic
- Virtual audio devices and call devices such as AirPods can change the system default input

## Features

- Continuous audio monitoring (mono or stereo)
- YAMNet-based bark detection with configurable sensitivity
- Left/right direction detection (stereo only)
- Automatic incident grouping with configurable silence and merge windows
- Audio clip recording (handles 30+ minute incidents)
- SHA-256 fingerprints for evidence integrity
- Weather context for each incident
- PDF reports and CSV export
- Web dashboard for review and flagging
- Test incident deletion from the dashboard
- Today and all-time summary cards
- Health details panel
- Auto-start on boot (Raspberry Pi)

## Hardware

- Raspberry Pi 5 (8GB recommended) or any computer for testing
- USB microphone (stereo recommended)
  - Sony ECM-LV1 lavalier pair
  - Or any stereo USB mic

## Uninstall

### Local Development
```bash
deactivate          # Exit virtual environment
rm -rf venv         # Remove virtual environment
rm -rf data         # Remove data (optional)
```

### Raspberry Pi
```bash
sudo systemctl stop doggy-detector
sudo systemctl disable doggy-detector
sudo rm /etc/systemd/system/doggy-detector.service
rm -rf ~/doggy-detector
```

## License

MIT
