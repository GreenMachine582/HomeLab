#!/bin/bash
set -e

echo "🚀 Running deployment as $(whoami)..."

# Load .env manually
export $(cat /root/homelab/.env | xargs)

if [[ -z "$GITHUB_SSH_KEY_PASSPHRASE" ]]; then
  echo "❌ GITHUB_SSH_KEY_PASSPHRASE is not set. Check your .env file."
  exit 1
fi

# Start ssh-agent
eval "$(ssh-agent -s)"
export SSH_AUTH_SOCK

# Add masked SSH key
cd ..
expect << 'EOD'
set passphrase $env(GITHUB_SSH_KEY_PASSPHRASE)
spawn ssh-add /root/.ssh/github
expect "Enter passphrase"
send "$passphrase\r"
expect eof
EOD

echo "📥 Pulling latest code..."
cd /root/homelab
git pull origin master

echo "⚙️ Running setup..."
bash setup.sh

echo "🔄 Stopping existing containers..."
docker compose down

echo "🆙 Starting containers..."
docker compose up -d
ssh-agent -k

echo "✅ Deployment complete"
