#!/bin/sh

# Redirect stdout and stderr to log file
mkdir -p ./log
exec > >(awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' | tee -a ./log/setup.log) 2>&1

echo "Starting setup script..."

# Load environment variables from .env
echo "Loading environment variables from .env..."
export $(cat .env | xargs)

# Get the directory of the current script
HOMELAB_DIR="$(cd "$(dirname "$0")" && pwd)"
export HOMELAB_DIR
echo "HOMELAB_DIR set to $HOMELAB_DIR"

# Set destination for shutdown script
DST_ON_SHUTDOWN="/lib/systemd/system-shutdown/on-shutdown.sh"

# Generate and move shutdown script
echo "Generating on-shutdown.sh from template..."
envsubst '${HOMELAB_DIR} ${DISCORD_WEBHOOK_URL} ${NOTIFY_USERNAME}' < ./on-shutdown.sh.tmpl > ./on-shutdown.sh
echo "Moving on-shutdown.sh to system-shutdown directory..."
mv ./on-shutdown.sh "$DST_ON_SHUTDOWN"
chmod +x "$DST_ON_SHUTDOWN"
echo "Shutdown script installed and made executable."

# Setup Alertmanager configuration
echo "Generating Alertmanager configuration from template..."
envsubst < ./alertmanager/alertmanager.yml.tmpl > ./alertmanager/alertmanager.yml
echo "Alertmanager configuration completed."

echo "Setup script finished."
