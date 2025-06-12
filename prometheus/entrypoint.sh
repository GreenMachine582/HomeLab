#!/bin/sh
envsubst < /etc/alertmanager/alertmanager.yml.tmpl > /etc/alertmanager/alertmanager.yml
/bin/alertmanager --config.file=/etc/alertmanager/alertmanager.yml
