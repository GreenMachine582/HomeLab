#!/bin/sh
mkdir -p /var/lib/grafana/dashboards
curl -sSL "https://grafana.com/api/dashboards/1860/revisions/36/download" \
  -o /var/lib/grafana/dashboards/node_exporter_full.json
