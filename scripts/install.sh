#!/bin/bash
set -e

echo "=== Dog Detector Installer ==="

# Check if running on Pi (optional warning, don't exit)
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "Warning: Not running on Raspberry Pi"
fi

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    portaudio19-dev \
    libcairo2-dev \
    libpango1.0-dev \
    libgdk-pixbuf2.0-dev \
    libffi-dev

# Get project directory (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Prefer Python 3.11, fall back to python3 if not available
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD=python3.11
else
    PYTHON_CMD=python3
    echo "Warning: Python 3.11 not found, using $(python3 --version)"
    echo "TensorFlow requires Python 3.11 or 3.12"
fi

# Create virtual environment
echo "Creating virtual environment with $PYTHON_CMD..."
$PYTHON_CMD -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install tensorflow>=2.15.0
pip install -r requirements.txt

# Create data directories
echo "Creating data directories..."
mkdir -p data/clips data/reports

# Create config if not exists
if [ ! -f config.yaml ]; then
    echo "Creating default config.yaml..."
    cat > config.yaml << 'CONFIGEOF'
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
CONFIGEOF
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

# Print completion message with instructions
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
