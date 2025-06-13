#!/bin/sh
export $(cat .env | xargs)

# This script sets up the Alertmanager configuration by substituting environment variables
envsubst < ./alertmanager/alertmanager.yml.tmpl > ./alertmanager/alertmanager.yml

# Copy the event notification scripts to the appropriate directories
DST_ON_SHUTDOWN="/lib/systemd/system-shutdown/on-shutdown.sh"
cp ./on-shutdown.sh "$DST_ON_SHUTDOWN"
chmod +x "$DST_ON_SHUTDOWN"
