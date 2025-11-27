#!/bin/bash
set -e

#############################################
# Argument parsing
#############################################
if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <project_path> <project_name> <branch>"
  echo "Example: $0 python_projects/greentechhub GreenTechHub main"
  exit 1
fi

PROJECT_PATH="$1"        # e.g. python_projects/greentechhub
PROJECT_NAME="$2"        # e.g. GreenTechHub
PROJECT_BRANCH="$3"      # e.g. main

#############################################
# Directories and logging
#############################################
HOMELAB_DIR=$(realpath "$(dirname "$0")/..")
cd "$HOMELAB_DIR"
echo "HOMELAB_DIR set to $HOMELAB_DIR"

LOG_FILE="$HOMELAB_DIR/deploy_${PROJECT_NAME,,}.log"

# Rotate old log
if [[ -f "$LOG_FILE" ]]; then
  mv "$LOG_FILE" "$LOG_FILE.$(date +%Y%m%d-%H%M%S)"
fi

# Log redirection
exec > >(awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' | tee -a "$LOG_FILE") 2>&1

echo "🚀 Deploying ${PROJECT_NAME} as $(whoami)..."

PROJECT_DIR="$HOMELAB_DIR/$PROJECT_PATH"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "❌ Project directory not found: $PROJECT_DIR"
  exit 1
fi

cd "$PROJECT_DIR"

#############################################
# Environment variables
#############################################
if [[ -f "$HOMELAB_DIR/.env" ]]; then
  echo "📄 Loading homelab .env..."
  export $(grep -v '^#' "$HOMELAB_DIR/.env" | xargs)
else
  echo "⚠️ No homelab .env found."
fi

if [[ -f "$PROJECT_DIR/.env" ]]; then
  echo "📄 Loading project .env ($PROJECT_NAME)..."
  export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
fi

if [[ -z "$GITHUB_SSH_KEY_PASSPHRASE" ]]; then
  echo "❌ GITHUB_SSH_KEY_PASSPHRASE missing. Add it to .env"
  exit 1
fi

#############################################
# SSH key loading
#############################################
eval "$(ssh-agent -s)"
trap 'echo "🧹 Stopping ssh-agent..."; ssh-agent -k >/dev/null || true' EXIT

echo "🔐 Adding GitHub SSH key..."
expect << 'EOD'
set passphrase $env(GITHUB_SSH_KEY_PASSPHRASE)
spawn ssh-add /root/.ssh/github
expect "Enter passphrase"
send "$passphrase\r"
expect eof
EOD

#############################################
# Git updates
#############################################
echo "📥 Pulling latest code for ${PROJECT_NAME}..."
git fetch origin "$PROJECT_BRANCH"
git reset --hard "origin/$PROJECT_BRANCH"

#############################################
# Project-specific setup
#############################################
if [[ -x ./setup.sh ]]; then
  echo "⚙️ Running setup.sh for ${PROJECT_NAME}..."
  bash ./setup.sh
else
  echo "ℹ️ No setup.sh found for ${PROJECT_NAME}, skipping."
fi

#############################################
# Docker deployment
#############################################
echo "🆙 Updating Docker stack for ${PROJECT_NAME}..."
docker compose pull
docker compose up -d --remove-orphans

echo "✅ Deployment finished for ${PROJECT_NAME}!"
