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

# Make scripts executable
echo "Modifying script files..."
chmod +x "./scripts/on-boot.sh"
chmod +x "./scripts/on-shutdown.sh"
chmod +x "./scripts/monthly-update.sh"
echo "Scripts made executable."

# Setup systemd services
echo "Generating systemd services from template..."
envsubst '${HOMELAB_DIR}' < ./scripts/on-boot.service.tmpl > /etc/systemd/system/on-boot.service
envsubst '${HOMELAB_DIR}' < ./scripts/on-shutdown.service.tmpl > /etc/systemd/system/on-shutdown.service
systemctl daemon-reload
sudo systemctl enable on-boot.service
sudo systemctl enable on-shutdown.service
echo "Systemd services completed."

# Setup Alertmanager configuration
echo "Generating Alertmanager configuration from template..."
envsubst < ./alertmanager/alertmanager.yml.tmpl > ./alertmanager/alertmanager.yml
echo "Alertmanager configuration completed."

echo "Setup script finished."

exit 0