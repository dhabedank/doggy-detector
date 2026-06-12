# Doggy Detector

Doggy Detector is a self-hosted Raspberry Pi application for bark monitoring,
local sonic deterrence, and evidence capture. It listens through a microphone,
detects likely dog vocalizations, groups nearby barks into incidents, saves
audio clips, and serves a local dashboard for review, tuning, logs, reports,
and updates.

The project is designed for local operation. Audio clips, settings, generated
reports, dashboard credentials, and event history stay on the device unless you
choose to copy them elsewhere.

## What It Does

- Monitors microphone input continuously.
- Uses YAMNet to score dog-related sounds.
- Groups repeated barks into incidents instead of saving every isolated hit.
- Records incident audio with pre-roll and SHA-256 clip fingerprints.
- Estimates left/right direction when a real stereo input is available.
- Provides manual and automatic sonic deterrence controls.
- Supports audible output and GPIO-triggered external ultrasonic deterrents.
- Generates PDF/CSV evidence packages with weather context.
- Exposes a password-protected local dashboard for review and configuration.
- Shows service logs, health status, and software update status in the dashboard.
- Supports headless release updates from tagged GitHub releases.

## Hardware

Recommended deployment:

- Raspberry Pi 5 or comparable Linux device
- Python 3.11 or 3.12
- USB microphone
- Optional stereo microphone or stereo USB interface for direction detection
- Optional powered speaker for audible deterrence
- Optional external ultrasonic deterrent that can be triggered by GPIO through
  an appropriate relay, optocoupler, or driver circuit

Normal headset adapters and basic speakers should not be assumed to produce
useful ultrasonic output. Use a purpose-built ultrasonic module or device if
you want ultrasonic deterrence.

## Safety And Privacy

- Do not expose the dashboard directly to the public internet.
- Use a private network, VPN, Tailscale, or an authenticated reverse proxy for
  remote access.
- Deterrence actions are bounded bursts; the app is not designed to leave a
  speaker, relay, or ultrasonic device on continuously.
- You are responsible for local recording, privacy, noise, and animal-control
  laws.
- Saved clips may contain private household or neighborhood audio. Treat
  `data/` as sensitive runtime data.

## Quick Start On Raspberry Pi

```bash
git clone https://github.com/dhabedank/doggy-detector.git
cd doggy-detector
./scripts/install.sh
sudo systemctl start doggy-detector
sudo journalctl -u doggy-detector -f
```

The first startup prints generated dashboard credentials to the service log.
After logging in, use the Settings page to choose the microphone, tune detection
thresholds, configure deterrence, and set report location details if you want
weather context in reports.

The installer creates:

- `doggy-detector.service`
- `doggy-detector-update-check.timer`
- `doggy-detector-updater.service`

## Local Development

Use Python 3.11 or 3.12. Python 3.13+ is not supported by this TensorFlow stack.

### Linux

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install "tensorflow>=2.15.0"
pip install -r requirements.txt
python -m src.main
```

### macOS Apple Silicon

```bash
brew install python@3.11
/opt/homebrew/bin/python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install "tensorflow-macos>=2.15.0"
pip install -r requirements.txt
python -m src.main
```

Dashboard: http://localhost:8080

Run tests:

```bash
venv/bin/python -m pytest -q
```

## Configuration

Runtime settings live in SQLite under the configured data directory. By default:

```text
data/
├── events.sqlite
├── clips/
├── reports/
└── update-state.json
```

Set `DOG_DETECTOR_DATA_DIR` to use a different runtime data folder.

Optional first-run environment variables:

```bash
DOG_DETECTOR_AUTH_USERNAME=admin
DOG_DETECTOR_AUTH_PASSWORD='choose-a-strong-password'
```

If those are not set, the app generates dashboard credentials on first startup
and prints them to the service log. Only the password hash is stored.

To reset dashboard credentials without deleting settings, clips, or events:

```bash
touch data/reset-dashboard-login
sudo systemctl restart doggy-detector
sudo journalctl -u doggy-detector -f
```

For a one-off local reset:

```bash
DOG_DETECTOR_RESET_AUTH=1 python -m src.main
```

## Dashboard

The dashboard includes:

- live input level, bark score, status, and chunk counters
- incident history with audio playback
- false-positive marking and deletion for test incidents
- settings for microphone, detection, incident grouping, reports, and deterrence
- software update status and dashboard-triggered update requests
- service logs with copy support
- health details for audio, disk, system load, and runtime state

## Deterrence

Doggy Detector supports deterrence as a local action tied to bark detection.
Manual firing is available from the dashboard. Automatic firing can be enabled
with thresholds, cooldowns, quiet hours, and maximum firing limits.

Supported output paths:

- Audible: generated chirp or alarm profiles through a configured output device.
- Ultrasonic: GPIO-triggered external ultrasonic hardware.

The app logs every firing attempt, including source, mode, duration, profile,
bark score when available, and actuator errors.

## Reports

Exported report packages include:

- a PDF summary
- a CSV event export
- referenced WAV clips for included incidents
- clip fingerprints for evidence integrity checks

False-positive incidents are excluded from reports by default.

## Updates

Installed devices check GitHub release tags daily and show update status in the
Settings page. Daily checks do not auto-install releases. You can check for an
update or queue an install from the dashboard.

From SSH:

```bash
cd ~/doggy-detector
venv/bin/python -m src.updater check
venv/bin/python -m src.updater status
venv/bin/python -m src.updater request latest
sudo systemctl start doggy-detector-updater
```

The updater installs tagged releases, refreshes Python dependencies, restarts
the service, and preserves `data/`.

## Troubleshooting

List audio devices:

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

If the input meter stays at zero:

- confirm the microphone is connected and selected in Settings
- check OS microphone permissions on desktop systems
- avoid relying on changing system defaults; pin the monitoring device by name
- check `sudo journalctl -u doggy-detector -n 100 --no-pager`

If detection is too sensitive or not sensitive enough:

- adjust the detection threshold in Settings
- review incident peak score, average score, and input level
- test with known bark audio near the monitoring microphone

If direction is unknown:

- confirm the capture device exposes two input channels
- use a true stereo USB interface or two separated microphones
- avoid USB adapters that collapse microphone input to mono

## Development Notes

The public repository intentionally excludes runtime data, local credentials,
private planning notes, generated clips, generated reports, and device-specific
configuration.

## License

MIT
