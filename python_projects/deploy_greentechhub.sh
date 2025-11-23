#!/bin/bash
set -e

# Ensure the script is run from the correct directory
HOMELAB_DIR=$(realpath "$(dirname "$0")/..")
cd "$HOMELAB_DIR"
echo "HOMELAB_DIR set to $HOMELAB_DIR"

LOG_FILE="$HOMELAB_DIR/deploy_greentechhub.log"

# Rotate old log
if [[ -f "$LOG_FILE" ]]; then
  mv "$LOG_FILE" "$LOG_FILE.$(date +%Y%m%d-%H%M%S)"
fi

# Redirect stdout and stderr to log file with tee
exec > >(awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' | tee -a "$LOG_FILE") 2>&1

echo "🌿 Running greentechhub deployment as $(whoami)..."

GREENTECHHUB_DIR="$HOMELAB_DIR/python_projects/greentechhub"

# Ensure we are in the greentechhub directory
cd "$GREENTECHHUB_DIR"

# Load environment variables from .env
if [ -f "$HOMELAB_DIR/.env" ]; then
  echo "Loading environment variables from .env..."
  export $(grep -v '^#' $HOMELAB_DIR/.env | xargs)
else
  echo "⚠️ $HOMELAB_DIR/.env not found, continuing without extra env vars."
fi

# Optionally also load a project-specific .env if present
if [[ -f "$GREENTECHHUB_DIR/.env" ]]; then
  echo "📄 Loading environment variables from $GREENTECHHUB_DIR/.env..."
  export $(grep -v '^#' $GREENTECHHUB_DIR/.env | xargs)
fi

if [[ -z "$GITHUB_SSH_KEY_PASSPHRASE" ]]; then
  echo "❌ GITHUB_SSH_KEY_PASSPHRASE is not set. Check your .env file(s)."
  exit 1
fi

# Start ssh-agent and ensure it’s killed on exit
eval "$(ssh-agent -s)"
export SSH_AUTH_SOCK
trap 'echo "🧹 Stopping ssh-agent..."; ssh-agent -k >/dev/null 2>&1 || true' EXIT

# Add GitHub deploy key using expect for the passphrase
echo "🔐 Adding GitHub SSH key via ssh-agent..."
expect << 'EOD'
set passphrase $env(GITHUB_SSH_KEY_PASSPHRASE)
spawn ssh-add /root/.ssh/github
expect "Enter passphrase"
send "$passphrase\r"
expect eof
EOD

echo "📥 Pulling latest greentechhub code..."
git fetch origin main
git reset --hard origin/main

# If greentechhub has its own setup script, run it
if [[ -x ./setup.sh ]]; then
  echo "⚙️ Running greentechhub setup script..."
  bash ./setup.sh
else
  echo "⚙️ No greentechhub setup.sh found or executable, skipping setup step."
fi

echo "🆙 Updating greentechhub containers..."
# Only affects the greentechhub stack defined in this directory
docker compose pull
docker compose up -d --remove-orphans

echo "✅ Greentechhub deployment complete"
