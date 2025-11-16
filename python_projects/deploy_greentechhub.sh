#!/bin/bash
set -e

echo "🌿 Running greentechhub deployment as $(whoami)..."

# Ensure we are in the greentechhub directory
cd /root/homelab/python_projects/greentechhub

# Load env from the main homelab .env
if [[ -f /root/homelab/.env ]]; then
  echo "📄 Loading environment variables from /root/homelab/.env..."
  # shellcheck disable=SC2046
  export $(grep -v '^\s*#' /root/homelab/.env | xargs)
else
  echo "⚠️ /root/homelab/.env not found, continuing without extra env vars."
fi

# Optionally also load a project-specific .env if present
if [[ -f /root/homelab/python_projects/greentechhub/.env ]]; then
  echo "📄 Loading environment variables from /root/homelab/python_projects/greentechhub/.env..."
  export $(grep -v '^\s*#' /root/homelab/greentechhub/.env | xargs)
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
git fetch origin master
git reset --hard origin/master

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
