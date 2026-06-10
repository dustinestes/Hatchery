#!/usr/bin/env bash
# Removes the Hatchery systemd user service and the optional /etc/hosts entry.
set -euo pipefail

echo "Stopping and disabling Hatchery service..."
systemctl --user stop hatchery 2>/dev/null || true
systemctl --user disable hatchery 2>/dev/null || true

SERVICE_FILE="${HOME}/.config/systemd/user/hatchery.service"
if [[ -f "$SERVICE_FILE" ]]; then
    rm "$SERVICE_FILE"
    systemctl --user daemon-reload
    echo "Service file removed: $SERVICE_FILE"
else
    echo "Service file not found — nothing to remove."
fi

if grep -q "hatchery\.local" /etc/hosts 2>/dev/null; then
    echo "Removing hatchery.local from /etc/hosts..."
    sudo sed -i '/hatchery\.local/d' /etc/hosts
    echo "Done."
else
    echo "No hatchery.local entry found in /etc/hosts — nothing to remove."
fi

echo ""
echo "Hatchery service uninstalled."
