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
