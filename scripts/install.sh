#!/bin/bash
set -e

echo "=== Doggy Detector Installer ==="

# Check if running on Pi (optional warning, don't exit)
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "Warning: Not running on Raspberry Pi"
fi

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
    git \
    python3.11 \
    python3.11-venv \
    python3-pip \
    sudo \
    portaudio19-dev \
    libcairo2-dev \
    libpango1.0-dev \
    libgdk-pixbuf2.0-dev \
    libffi-dev

# Get project directory (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_USER="${SUDO_USER:-$USER}"
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
pip install "tensorflow>=2.15.0"
pip install -r requirements.txt

# Create data directories
echo "Creating data directories..."
mkdir -p data/clips data/reports

# Install systemd service
echo "Installing systemd service..."
sudo tee /etc/systemd/system/doggy-detector.service > /dev/null << EOF
[Unit]
Description=Doggy Detector
After=network.target sound.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python -m src.main
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo "Installing updater service and daily check timer..."
sudo tee /etc/systemd/system/doggy-detector-update-check.service > /dev/null << EOF
[Unit]
Description=Doggy Detector update check
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python -m src.updater check
Environment=PYTHONUNBUFFERED=1
Environment=DOG_DETECTOR_DATA_DIR=$PROJECT_DIR/data
EOF

sudo tee /etc/systemd/system/doggy-detector-update-check.timer > /dev/null << EOF
[Unit]
Description=Daily Doggy Detector update check

[Timer]
OnBootSec=10min
OnUnitActiveSec=24h
Persistent=true
Unit=doggy-detector-update-check.service

[Install]
WantedBy=timers.target
EOF

sudo tee /etc/systemd/system/doggy-detector-updater.service > /dev/null << EOF
[Unit]
Description=Doggy Detector release updater
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python -m src.updater apply-pending
Environment=PYTHONUNBUFFERED=1
Environment=DOG_DETECTOR_DATA_DIR=$PROJECT_DIR/data
EOF

SYSTEMCTL_PATH="$(command -v systemctl)"
sudo tee /etc/sudoers.d/doggy-detector-updater > /dev/null << EOF
$SERVICE_USER ALL=(root) NOPASSWD: $SYSTEMCTL_PATH restart doggy-detector, $SYSTEMCTL_PATH start doggy-detector-updater.service
EOF
sudo chmod 440 /etc/sudoers.d/doggy-detector-updater

sudo systemctl daemon-reload
sudo systemctl enable doggy-detector
sudo systemctl enable --now doggy-detector-update-check.timer

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
echo "  sudo systemctl start doggy-detector"
echo ""
echo "To view logs:"
echo "  sudo journalctl -u doggy-detector -f"
echo ""
echo "To run an update check:"
echo "  sudo systemctl start doggy-detector-update-check"
echo ""
echo "To apply a queued dashboard update:"
echo "  sudo systemctl start doggy-detector-updater"
echo ""
echo "Dashboard URL (local): http://localhost:8080"
echo "Dashboard URL (Tailscale): http://$TAILSCALE_IP:8080"
echo ""
echo "Use the dashboard Settings screen to set your location and preferences."
echo "The first startup logs generated dashboard login credentials."
