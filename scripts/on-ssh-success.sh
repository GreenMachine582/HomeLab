#!/bin/bash

set -e

# Ensure the script is run from the correct directory
HOMELAB_DIR=$(realpath "$(dirname "$0")/..")
cd "$HOMELAB_DIR"
echo "HOMELAB_DIR set to $HOMELAB_DIR"

# Create log directory and set log file path
LOG_DIR="$HOMELAB_DIR/log"
LOG_FILE="$LOG_DIR/on-ssh-success.log"
mkdir -p "$LOG_DIR"

# Redirect stdout and stderr to log file with tee
exec > >(awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' | tee -a "$LOG_FILE") 2>&1

echo "----- On SSH Success Script Started: $(date) -----"

# Load environment variables from .env
if [ -f "$HOMELAB_DIR/.env" ]; then
  echo "Loading environment variables from .env..."
  export $(grep -v '^#' $HOMELAB_DIR/.env | xargs)
else
  echo "[ERROR] Missing .env file"
  exit 1
fi

send_discord() {
  curl -s -H "Content-Type: application/json" -X POST "$DISCORD_WEBHOOK_URL" -d @- <<EOF
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
  send_discord "$2" "$1" "$3"
}

# --- Begin watching successful ssh logins ---
# SSH login monitor using systemd journal
journalctl -fu ssh | while read -r line; do
  if echo "$line" | grep -q "Accepted"; then
    USER=$(echo "$line" | grep -oP 'for \K\S+')
    IP=$(echo "$line" | grep -oP 'from \K\S+')
    TIME=$(date "+%Y-%m-%d %H:%M:%S")
    MSG="🪪 SSH login: $USER from $IP at $TIME"

    log_and_notify "$MSG" "SSH Login" 16753920
  fi
done

echo "----- On SSH Success Script Finished: $(date) -----"

exit 0