#!/usr/bin/env bash
# Installs Hatchery as a systemd user service.
# Run from any directory — the script locates Hatchery relative to itself.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HATCHERY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_DEST="${HOME}/.config/systemd/user/hatchery.service"

# Locate uv — prefer the shell's PATH, fall back to the default install location.
UV_BIN="$(command -v uv 2>/dev/null || echo "${HOME}/.local/bin/uv")"
if [[ ! -x "$UV_BIN" ]]; then
    echo "Error: uv not found. Install it from https://docs.astral.sh/uv/ and re-run."
    exit 1
fi

echo "Installing Hatchery service..."
echo "  Directory : $HATCHERY_DIR"
echo "  uv binary : $UV_BIN"
echo "  Service   : $SERVICE_DEST"
echo ""

mkdir -p "$(dirname "$SERVICE_DEST")"

sed \
    -e "s|WorkingDirectory=/path/to/Hatchery|WorkingDirectory=$HATCHERY_DIR|" \
    -e "s|ExecStart=/path/to/uv|ExecStart=$UV_BIN|" \
    "$SCRIPT_DIR/hatchery.service" > "$SERVICE_DEST"

systemctl --user daemon-reload
systemctl --user enable --now hatchery

echo "Service installed and running."
echo "Check status: systemctl --user status hatchery"
echo ""

# Optional: add a short hostname entry to /etc/hosts.
read -r -p "Add 'hatchery.local' to /etc/hosts for a short hostname? [y/N] " REPLY
echo ""
if [[ "${REPLY,,}" == "y" ]]; then
    if grep -q "hatchery\.local" /etc/hosts; then
        echo "hatchery.local is already in /etc/hosts — skipped."
    else
        echo "127.0.0.1  hatchery.local" | sudo tee -a /etc/hosts > /dev/null
        echo "Added. Open http://hatchery.local:5000 in your browser."
    fi
fi

echo ""
echo "Hatchery is running at http://localhost:5000"
