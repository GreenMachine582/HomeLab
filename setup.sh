#!/bin/sh
export $(cat .env | xargs)

# This script sets up the Alertmanager configuration by substituting environment variables
envsubst < ./alertmanager/alertmanager.yml.tmpl > ./alertmanager/alertmanager.yml

# Copy the event notification scripts to the appropriate directories
rm /lib/systemd/system-shutdown/on-shutdown.sh
xcopy ./on-shutdown.sh /lib/systemd/system-shutdown/on-shutdown.sh
chmod +x /lib/systemd/system-shutdown/on-shutdown.sh
