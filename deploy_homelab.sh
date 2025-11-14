#!/bin/bash
set -e

echo "🚀 Running deployment as $(whoami)..."

# Ensure we are in the homelab directory
cd /root/homelab

# Load .env safely (ignore comments / blank lines)
if [[ -f /root/homelab/.env ]]; then
  echo "📄 Loading environment variables from /root/homelab/.env..."
  # shellcheck disable=SC2046
  export $(grep -v '^\s*#' /root/homelab/.env | xargs)
else
  echo "⚠️ /root/homelab/.env not found, continuing without extra env vars."
fi

if [[ -z "$GITHUB_SSH_KEY_PASSPHRASE" ]]; then
  echo "❌ GITHUB_SSH_KEY_PASSPHRASE is not set. Check your .env file."
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

echo "📥 Pulling latest code..."
git fetch origin master
git reset --hard origin/master

echo "⚙️ Running setup script..."
bash setup.sh

echo "🆙 Updating containers (without tearing down tunnel)..."
# Pull latest images and recreate containers, removing old ones,
# but without a brutal 'docker compose down' that would kill cloudflared/SSH mid-session.
docker compose pull
docker compose up -d --remove-orphans

echo "✅ Deployment complete"
