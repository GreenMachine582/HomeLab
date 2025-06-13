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
  curl -s -X POST "http://0.0.0.0:8085/alerts" \
    -H "Title: $1" \
    -H "Tags: wrench" \
    -d "$2" \
    || echo "[ERROR] Failed to send ntfy boot notification"
}

send_discord() {
  curl -s -H "Content-Type: application/json" -X POST "$DISCORD_WEBHOOK_URL" -d @- <<EOF
{
  "username": "${NOTIFY_USERNAME:-HomeLab}",
  "embeds": [
    {
      "title": "$1",
      "description": "🔧$2",
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

# --- Begin boot notification ---
TIME=$(date "+%Y-%m-%d %H:%M:%S")
log_and_notify "$(hostname) booted at $TIME" "Boot Event" 5763719
