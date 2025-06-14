#!/bin/bash

set -e

# Ensure the script is run from the correct directory
HOMELAB_DIR="$(dirname "$PWD")"
cd "$HOMELAB_DIR"
echo "HOMELAB_DIR set to $HOMELAB_DIR"

# Create log directory and set log file path
LOG_DIR="$HOMELAB_DIR/log"
LOG_FILE="$LOG_DIR/on-shutdown.log"
mkdir -p "$LOG_DIR"

# Redirect stdout and stderr to log file with tee
exec > >(awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' | tee -a "$LOG_FILE") 2>&1

echo "----- Shutdown Script Started: $(date) -----"

# Load environment variables from .env
if [ -f ".env" ]; then
  echo "Loading environment variables from .env..."
  export $(grep -v '^#' .env | xargs)
else
  echo "[ERROR] Missing .env file"
  exit 1
fi

send_ntfy() {
  curl -s -X POST "http://0.0.0.0:8085/alerts" \
    -H "Title: $1" \
    -H "Tags: rotating_light" \
    -d "$2" \
    || echo "[ERROR] Failed to send ntfy boot notification"
}

send_discord() {
  curl -s -H "Content-Type: application/json" -X POST "${DISCORD_WEBHOOK_URL}" -d @- <<EOF
{
  "username": "${NOTIFY_USERNAME:-HomeLab}",
  "embeds": [
    {
      "title": "$1",
      "description": "🛑 $2",
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

# --- Begin shutdown notification ---
TIME=$(date "+%Y-%m-%d %H:%M:%S")
log_and_notify "$(hostname) is shutting down or rebooting at $TIME" "Shutdown Event" 16711680

echo "----- Shutdown Script Finished: $(date) -----"

exit 0