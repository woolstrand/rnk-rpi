#!/usr/bin/env bash
#
# One-shot setup for the rnk-rpi project on a Raspberry Pi.
#
# What it does:
#   1. Installs system dependencies (python3-venv, python3-pip, ffmpeg)
#   2. Creates a .venv virtualenv in the project root and installs requirements,
#      and creates .env from .env.example if missing (camera IP/credentials)
#   3. Adds the current user to the "gpio" group (required for /dev/gpiomem)
#   4. Installs the rnk-rpi systemd service (enabled + started)
#
# Usage:
#   git clone <repo-url> rnk-rpi
#   cd rnk-rpi
#   ./scripts/setup.sh
#
# Re-running the script is safe: it refreshes dependencies and restarts
# the service.
#
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
USER_NAME="$(id -un)"

echo "==> rnk-rpi setup in ${PROJECT_DIR} for user ${USER_NAME}"

# ---------------------------------------------------------------------------
# 1. System dependencies
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null; then
    echo "==> Installing python3, python3-venv, python3-pip"
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip
else
    echo "==> python3 already present"
fi

if ! command -v ffmpeg >/dev/null; then
    echo "==> Installing ffmpeg (needed for camera snapshot capture)"
    sudo apt-get update
    sudo apt-get install -y ffmpeg
else
    echo "==> ffmpeg already present"
fi

# ---------------------------------------------------------------------------
# 2. Virtualenv + Python dependencies
# ---------------------------------------------------------------------------
if [ ! -d .venv ]; then
    echo "==> Creating virtualenv .venv"
    python3 -m venv .venv
fi
echo "==> Installing Python requirements"
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
    echo "==> Creating .env from .env.example (edit it with your camera's IP/credentials)"
    cp .env.example .env
fi

# ---------------------------------------------------------------------------
# 3. GPIO group membership (needed to access /dev/gpiomem)
# ---------------------------------------------------------------------------
if id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx gpio; then
    echo "==> ${USER_NAME} is already in the gpio group"
else
    echo "==> Adding ${USER_NAME} to the gpio group"
    sudo usermod -aG gpio "$USER_NAME"
    echo "    NOTE: the group change takes effect after you log out and back in."
    echo "    The service itself runs with SupplementaryGroups=gpio, so it works"
    echo "    immediately; only your interactive shell needs a re-login."
fi

# ---------------------------------------------------------------------------
# 4. systemd service (auto-starts at boot, runs as the current user)
# ---------------------------------------------------------------------------
echo "==> Installing systemd service"
sed -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    -e "s|__USER__|${USER_NAME}|g" \
    scripts/rnk-rpi.service | sudo tee /etc/systemd/system/rnk-rpi.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable rnk-rpi
sudo systemctl restart rnk-rpi

# ---------------------------------------------------------------------------
# 5. Passwordless service control (sudoers drop-in + wrapper script)
# ---------------------------------------------------------------------------
echo "==> Installing passwordless service control"

# 5a. sudoers drop-in: lets the user run the exact systemctl/journalctl
#     commands in scripts/rnk-rpi without a password. Validate before
#     installing so a typo can never break the user's sudo access.
SUDOERS_SRC="$(mktemp)"
sed -e "s|__USER__|${USER_NAME}|g" scripts/rnk-rpi.sudoers > "$SUDOERS_SRC"
if ! sudo visudo -c -f "$SUDOERS_SRC" >/dev/null; then
    echo "ERROR: sudoers file failed validation; NOT installing it." >&2
    cat "$SUDOERS_SRC" >&2
    rm -f "$SUDOERS_SRC"
    exit 1
fi
sudo install -m 0440 "$SUDOERS_SRC" /etc/sudoers.d/rnk-rpi
rm -f "$SUDOERS_SRC"
echo "    installed /etc/sudoers.d/rnk-rpi (passwordless for ${USER_NAME})"

# 5b. wrapper script for start/stop/restart/status/logs
chmod +x scripts/rnk-rpi
echo "    installed scripts/rnk-rpi wrapper"

echo
echo "==> Done. Service status:"
sudo systemctl --no-pager status rnk-rpi || true
echo
echo "Next steps (no password needed):"
echo "  * Manage service:    ./scripts/rnk-rpi start|stop|restart|status"
echo "  * Follow logs:       ./scripts/rnk-rpi logs"
echo "  * Try the API:       curl -X POST http://localhost:5000/rnk/schedule \\"
echo "                        -H 'Content-Type: application/json' -d '{\"move\": 5}'"
echo "  * Calibrate:         edit app/motor/constants.py (see README, 'Calibration')"
echo "  * Camera:            edit .env with the camera's IP/credentials, then"
echo "                        ./scripts/rnk-rpi restart (see README, 'Camera control')"
echo
echo "The service starts automatically at boot (systemd, WantedBy=multi-user.target)."
