#!/bin/bash

set -e
cd "$(dirname "$0")"

# Load env
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
else
  echo "Missing .env file"
  exit 1
fi

send_ntfy() {
  curl -s -X POST "$NTFY_URL" \
    -H "Title: $1" \
    -H "Tags: wrench" \
    -d "$2" > /dev/null
}

send_discord() {
  curl -s -H "Content-Type: application/json" -X POST "$DISCORD_WEBHOOK_URL" -d @- > /dev/null <<EOF
{
  "username": "${NOTIFY_USERNAME:-HomeLab}",
  "embeds": [
    {
      "title": "$1",
      "description": "$2",
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
