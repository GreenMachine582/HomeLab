#!/bin/bash

set -e

# Ensure the script is run from the correct directory
HOMELAB_DIR=$(realpath "$(dirname "$0")/..")
cd "$HOMELAB_DIR"
echo "HOMELAB_DIR set to $HOMELAB_DIR"

# Create log directory and set log file path
LOG_DIR="$HOMELAB_DIR/log"
LOG_FILE="$LOG_DIR/monthly-update.log"
mkdir -p "$LOG_DIR"

# Redirect stdout and stderr to log file with tee
exec > >(awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' | tee -a "$LOG_FILE") 2>&1

echo "----- Monthly Update Script Started: $(date) -----"

# Load environment variables from .env
if [ -f "$HOMELAB_DIR/.env" ]; then
  echo "Loading environment variables from .env..."
  export $(grep -v '^#' $HOMELAB_DIR/.env | xargs)
else
  echo "[ERROR] Missing .env file"
  exit 1
fi

send_ntfy() {
  curl -s -X POST "http://0.0.0.0:8085/alerts" \
    -H "Title: $1" \
    -H "Tags: wrench" \
    -d "$2" \
    || echo "[ERROR] Failed to send ntfy boot notification"
}

send_discord() {
  curl -s -H "Content-Type: application/json" -X POST "$DISCORD_WEBHOOK_URL" -d @- > /dev/null <<EOF
{
  "username": "${NOTIFY_USERNAME:-HomeLab}",
  "embeds": [
    {
      "title": "$1",
      "description": "🔧 $2",
      "color": $3
    }
  ]
}
EOF
}

log_and_notify() {
  echo "$1"
  send_ntfy "$2" "$1"
  send_discord "$2" "$1" "$3"
}

# --- Begin update ---
log_and_notify "System update starting on $(hostname)" "Monthly Update Started" 16753920

apt update && apt upgrade -y && apt autoremove -y

# Optional: Docker cleanup
docker system prune -af || echo "Docker not running or not installed."

log_and_notify "System update completed on $(hostname)" "Monthly Update Complete" 8311585

# --- Pre-reboot notification ---
log_and_notify "Rebooting system in 10 seconds..." "System Rebooting" 16711680
sleep 10

# Optional: schedule reboot to allow async delivery
shutdown -r now
