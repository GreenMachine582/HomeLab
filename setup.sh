#!/bin/sh
export $(cat .env | xargs)

# This script sets up the Alertmanager configuration by substituting environment variables
envsubst < ./alertmanager/alertmanager.yml.tmpl > ./alertmanager/alertmanager.yml
