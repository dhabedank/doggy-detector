# Dog Detector

An always-on bark detection system for Raspberry Pi that saves audio clips, determines direction, and generates evidence reports.

## Requirements

- **Python 3.11** (recommended) or 3.12
  - Python 3.13+ is not supported (TensorFlow compatibility)
- USB microphone (stereo recommended for direction detection)

## Quick Start (Raspberry Pi)

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

## Local Development

### Linux / Windows (x86)

```bash
# Create virtual environment with Python 3.11
python3.11 -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install TensorFlow first, then other dependencies
pip install tensorflow>=2.15.0
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
pip install tensorflow-macos>=2.15.0
pip install -r requirements.txt

# Run
python -m src.main
```

Dashboard: http://localhost:8080

## Using the Dashboard

### Live Status Bar

The status bar at the top shows real-time detection info:
- **Input**: Audio input level (0-1) - shows if the mic is picking up sound
- **Bark**: Detection score (0-1) - how confident the model is it's hearing a bark
- **Status**: Current state (Listening, BARK DETECTED, INCIDENT IN PROGRESS)
- **Chunks**: Number of audio chunks processed since startup

### Events Table

Lists all detected bark incidents with:
- Timestamp and duration
- Detection confidence score
- Direction (left/right arrow) - requires stereo mic
- Play button for audio clips
- Flag button to mark false positives

### Settings (gear icon)

- **Microphone**: Select specific audio device or auto-detect
- **Detection Sensitivity**: Threshold for bark detection (0.01-1.0)
  - Lower = more sensitive (may catch more false positives)
  - Higher = less sensitive (may miss quieter barks)
  - Start around 0.1-0.2 and adjust based on results
- **Location**: Address and coordinates for weather data in reports

### Reports

Click "Generate Report" to create:
- **PDF Report**: Formatted document with incident summary and weather context
- **CSV Export**: Raw data for spreadsheet analysis

### Test Detection

Click "Test Detection" to verify the model works by running a sample audio file through the detector. Useful for troubleshooting when live detection isn't working.

## How Detection Works

1. Audio is captured in 100ms chunks from the microphone
2. Google's YAMNet model classifies each chunk into 521 sound categories
3. If dog-related classes (Dog, Bark, Animal, etc.) score above threshold, it's a bark
4. Multiple barks within 15 seconds are grouped into a single incident
5. After 15 seconds of silence, the incident ends and is saved with audio

### Mono vs Stereo Mode

- **Stereo mic**: Full functionality including left/right direction detection
- **Mono mic**: Bark detection works, but direction shows as "unknown"

The system automatically falls back to mono if stereo isn't available.

## Configuration

Edit `config.yaml`:

```yaml
location:
  address: "Your address for reports"
  lat: 34.0522      # For weather lookup
  lon: -118.2437

audio:
  device: null      # null=auto, or device ID (integer)
  sample_rate: 16000
  channels: 2

detection:
  threshold: 0.1    # 0.01-1.0, lower=more sensitive

incidents:
  min_barks: 2      # Minimum barks to record incident
  gap_sec: 15.0     # Seconds of silence to end incident

storage:
  data_dir: ./data
  retention_days: 0  # 0=keep forever

web:
  host: 0.0.0.0
  port: 8080
```

### Finding Your Audio Device ID

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

Look for your microphone and note its index number.

## Troubleshooting

### "Input" meter stays at 0
- Check microphone permissions (System Preferences > Privacy > Microphone)
- Verify the correct device is selected in Settings
- Try setting a specific device ID in config.yaml

### Model detects speech/music instead of barks
- The YAMNet model classifies all sounds - `['Silence', 'Speech', 'Music']` means no dog sounds detected
- When barks are heard, you'll see `['Dog', 'Bark', 'Animal']`
- Use "Test Detection" to verify the model works with known bark audio

### Detection too sensitive / not sensitive enough
- Adjust threshold in Settings (gear icon)
- Lower values (0.05-0.15) = more detections
- Higher values (0.3-0.5) = fewer detections

### Audio device keeps resetting
- Set explicit device ID in config.yaml instead of `null`
- Virtual audio devices (Zoom, etc.) can interfere with auto-detection

## Features

- Continuous audio monitoring (mono or stereo)
- YAMNet-based bark detection with configurable sensitivity
- Left/right direction detection (stereo only)
- Automatic incident grouping with 15-second gap
- Audio clip recording (handles 30+ minute incidents)
- SHA-256 fingerprints for evidence integrity
- Weather context for each incident
- PDF reports and CSV export
- Web dashboard for review and flagging
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
sudo systemctl stop dog-detector
sudo systemctl disable dog-detector
sudo rm /etc/systemd/system/dog-detector.service
rm -rf ~/dog-detector
```

## License

MIT
