FROM grafana/grafana:latest

# Create dashboards directory and download public dashboard
RUN mkdir -p /var/lib/grafana/dashboards && \
    curl -sSL "https://grafana.com/api/dashboards/1860/revisions/36/download" \
    -o /var/lib/grafana/dashboards/node_exporter_full.json

# Copy provisioning config
COPY provisioning /etc/grafana/provisioning
