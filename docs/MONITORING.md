# Monitoring

Reference for the observability stack running on `homelab-observe`: Prometheus, Loki, Grafana, Alertmanager, and Uptime Kuma.

All configuration is managed by Ansible. Do not edit config files directly on nodes — changes will be overwritten on the next deploy. Edit the relevant template in `templates/` and re-run `deploy_observe.yml`.

<!-- TOC -->
* [Monitoring](#monitoring)
  * [Stack Overview](#stack-overview)
  * [Prometheus](#prometheus)
    * [Scrape Targets](#scrape-targets)
    * [Adding a New Scrape Target](#adding-a-new-scrape-target)
    * [Retention](#retention)
    * [Alert Rules](#alert-rules)
  * [Loki](#loki)
    * [Log Sources](#log-sources)
    * [Retention](#retention-1)
    * [Querying Logs in Grafana](#querying-logs-in-grafana)
  * [Grafana](#grafana)
    * [Dashboards](#dashboards)
    * [Data Sources](#data-sources)
    * [Adding a Dashboard](#adding-a-dashboard)
    * [Credentials](#credentials)
  * [Alertmanager](#alertmanager)
    * [Routing](#routing)
    * [Configuring Notification Channels](#configuring-notification-channels)
    * [Silencing an Alert](#silencing-an-alert)
    * [Inhibition Rules](#inhibition-rules)
  * [Uptime Kuma](#uptime-kuma)
    * [Monitors](#monitors)
    * [Notifications](#notifications)
  * [Tuning & Maintenance](#tuning--maintenance)
    * [Checking Stack Health](#checking-stack-health)
    * [Redeploying the Observability Stack](#redeploying-the-observability-stack)
    * [Storage Pressure](#storage-pressure)
<!-- TOC -->

---

## Stack Overview

| Service      | Port  | Purpose                                      |
|--------------|-------|----------------------------------------------|
| Prometheus   | 9090  | Metrics collection and storage               |
| Loki         | 3100  | Log aggregation                              |
| Grafana      | 3000  | Dashboards, data source queries              |
| Alertmanager | 9093  | Alert routing and notification               |
| Uptime Kuma  | 3001  | HTTP/HTTPS endpoint availability monitoring  |
| Portainer    | 9000  | Docker management UI across all nodes        |

All services run as Docker containers on `homelab-observe` (192.168.1.11). Deployed and configured by `playbooks/deploy_observe.yml`.

---

## Prometheus

### Scrape Targets

Configured in `templates/prometheus/prometheus.yml.j2`. Targets are scraped every 15 seconds by default.

| Target                    | Node              | Port  | Metrics               |
|---------------------------|-------------------|-------|-----------------------|
| `node-exporter` (edge)    | `homelab-edge`    | 9100  | Host: CPU, mem, disk, net |
| `node-exporter` (observe) | `homelab-observe` | 9100  | Host metrics          |
| `node-exporter` (svc-01)  | `homelab-svc-01`  | 9100  | Host metrics          |
| `node-exporter` (svc-02)  | `homelab-svc-02`  | 9100  | Host metrics          |
| `node-exporter` (svc-03)  | `homelab-svc-03`  | 9100  | Host metrics          |
| `cAdvisor` (svc-01)       | `homelab-svc-01`  | 8080  | Container metrics     |
| `cAdvisor` (svc-02)       | `homelab-svc-02`  | 8080  | Container metrics     |
| `cAdvisor` (svc-03)       | `homelab-svc-03`  | 8080  | Container metrics     |
| Pi-hole exporter          | `homelab-edge`    | 9617  | DNS queries, blocks   |

### Adding a New Scrape Target

1. Add the target to `templates/prometheus/prometheus.yml.j2` under `scrape_configs`
2. Re-run the observe deploy:
   ```bash
   ansible-playbook -i inventories/prod.ini playbooks/deploy_observe.yml --tags prometheus --vault-password-file .vault_pass
   ```

### Retention

Default retention is **30 days**. Adjust in `group_vars/observe.yml`:

```yaml
prometheus_retention: "30d"
```

Monitor `/var/lib/docker/volumes/prometheus_data` disk usage — on an SD card this fills quickly. Consider reducing retention or moving to a USB SSD.

### Alert Rules

Alert rules are defined in `templates/prometheus/alerts.yml.j2`. Rules are loaded by Prometheus and forwarded to Alertmanager on firing.

| Alert                  | Condition                              | Severity |
|------------------------|----------------------------------------|----------|
| `NodeDown`             | `node-exporter` unreachable > 2 min    | critical |
| `DiskSpaceCritical`    | Disk usage > 95%                       | critical |
| `DiskSpaceWarning`     | Disk usage > 90%                       | warning  |
| `ContainerCrashLoop`   | Container restart count > 3 in 10 min  | critical |
| `HighCPU`              | CPU > 80% for 5 min                    | warning  |
| `HighMemory`           | Memory > 80% for 5 min                 | warning  |
| `SSLCertExpiring`      | Certificate expiry < 7 days            | warning  |
| `BackupMissing`        | Backup job not completed in 25 hours   | warning  |

---

## Loki

### Log Sources

Grafana Alloy runs on every node and ships logs to Loki on `homelab-observe:3100`. Alloy config is in `templates/alloy/config.alloy.j2`.

| Source            | Log paths                                              |
|-------------------|--------------------------------------------------------|
| Docker containers | `/var/lib/docker/containers/*/*-json.log`              |
| Systemd (all)     | Journal: `tailscaled`, `ssh`, `ufw`, `fail2ban`        |
| Ansible runs      | `/opt/homelab/logs/ansible.log` (on edge)              |

### Retention

Default retention is **14 days**. Adjust in `group_vars/observe.yml`:

```yaml
loki_retention: "336h"   # 14 days in hours
```

### Querying Logs in Grafana

Use LogQL in the Grafana Explore view (data source: Loki):

```logql
# All logs from a specific container
{container="camunda-zeebe"}

# Error logs across all containers on svc-01
{host="homelab-svc-01"} |= "error"

# fail2ban ban events
{job="systemd"} |= "Ban"

# Ansible run output
{job="ansible"} | logfmt | level = "error"
```

---

## Grafana

Access: `http://grafana.homelab.local:3000`

Dashboards are pre-imported by Ansible from JSON files in `templates/grafana/dashboards/`. Do not save changes to dashboards directly in the UI — export the JSON and commit it to the repo, then redeploy.

### Dashboards

| Dashboard           | Description                                                      |
|---------------------|------------------------------------------------------------------|
| Homelab Overview    | All nodes: CPU, memory, disk, network, container status, uptime heatmap |
| Node Detail         | Per-node drilldown: load average, I/O wait, disk IOPS, top processes |
| Container Metrics   | cAdvisor: CPU/memory per container, restart count, network I/O   |
| Pi-hole Analytics   | DNS queries/sec, blocked domains (top 10), query types           |
| Application Logs    | Loki: error log aggregation, log volume by service, full-text search |
| Camunda Metrics     | Active instances, job queue depth, incident count (future)       |

### Data Sources

Configured in `templates/grafana/datasources.yml.j2`:

| Name       | Type       | URL                              |
|------------|------------|----------------------------------|
| Prometheus | Prometheus | `http://prometheus:9090`         |
| Loki       | Loki       | `http://loki:3100`               |

Both use Docker internal networking — no host port exposure required between containers.

### Adding a Dashboard

1. Build and test the dashboard in the Grafana UI
2. Export as JSON: **Dashboard → Share → Export → Save to file**
3. Place JSON in `templates/grafana/dashboards/`
4. Re-run observe deploy:
   ```bash
   ansible-playbook -i inventories/prod.ini playbooks/deploy_observe.yml --tags grafana --vault-password-file .vault_pass
   ```

### Credentials

Grafana admin credentials are stored in `secrets/vault.yml` under `vault_grafana_admin_password`. Set on first deploy; change via the Grafana UI afterwards.

---

## Alertmanager

Config template: `templates/alertmanager/alertmanager.yml.j2`

### Routing

Alerts are routed by severity:

| Severity | Channel              | Repeat interval |
|----------|----------------------|-----------------|
| critical | PagerDuty / SMS      | 1 hour          |
| warning  | Slack `#homelab-alerts` | 4 hours      |
| info     | Slack `#homelab-info`   | 12 hours     |

### Configuring Notification Channels

Channel credentials are stored in `secrets/vault.yml`. Add or change channels in `templates/alertmanager/alertmanager.yml.j2`, then redeploy:

```bash
ansible-playbook -i inventories/prod.ini playbooks/deploy_observe.yml --tags alertmanager --vault-password-file .vault_pass
```

Supported receivers (add as needed): Slack, email, PagerDuty, Gotify, Discord (via webhook), Pushover.

### Silencing an Alert

To silence a firing alert during maintenance, use the Alertmanager UI at `http://alertmanager.homelab.local:9093`. Silences created in the UI are temporary and not stored in config — for recurring maintenance windows, add a time-based inhibition rule to the template.

### Inhibition Rules

Inhibit downstream alerts when a node is already known to be down — prevents alert spam:

```yaml
inhibit_rules:
  - source_match:
      alertname: NodeDown
    target_match_re:
      alertname: "HighCPU|HighMemory|ContainerCrashLoop"
    equal: [instance]
```

This is included in the default `alertmanager.yml.j2`.

---

## Uptime Kuma

Access: `http://uptime.homelab.local:3001`

HTTP/HTTPS checks every 60 seconds. Alerts fire after 2 consecutive failures.

### Monitors

| Monitor           | Endpoint                                  |
|-------------------|-------------------------------------------|
| Edge health       | `http://homelab-edge/health`              |
| Pi-hole admin     | `http://homelab-edge/admin`               |
| Grafana           | `http://homelab-observe:3000/api/health`  |
| Alertmanager      | `http://homelab-observe:9093/-/healthy`   |
| Camunda           | `http://homelab-svc-01:8081`              |
| GreenTechHub      | `http://homelab-svc-02:8000/health`       |
| Jellyfin          | `http://homelab-svc-03:8096/health`       |

> Uptime Kuma monitor configuration is not currently managed by Ansible — configure monitors manually after first deploy. This is a known gap; a future playbook task will import monitor config via the Uptime Kuma API.

### Notifications

Configure notification channels in the Uptime Kuma UI. Recommended: mirror Alertmanager channels (Slack `#homelab-alerts`) so both systems agree on what is down.

---

## Tuning & Maintenance

### Checking Stack Health

```bash
# Verify all containers are running on homelab-observe
ssh admin@homelab-observe
docker ps

# Check Prometheus targets are all UP
# http://prometheus.homelab.local:9090/targets

# Check Alertmanager is receiving rules
# http://alertmanager.homelab.local:9093/#/alerts
```

### Redeploying the Observability Stack

Full redeploy (safe to run at any time — idempotent):

```bash
ansible-playbook -i inventories/prod.ini playbooks/deploy_observe.yml --vault-password-file .vault_pass
```

Tag-specific redeploy (faster):

```bash
ansible-playbook -i inventories/prod.ini playbooks/deploy_observe.yml --tags grafana --vault-password-file .vault_pass
```

Available tags: `prometheus`, `loki`, `grafana`, `alertmanager`, `uptime-kuma`, `portainer`.

### Storage Pressure

If `homelab-observe` is running low on disk, in order of impact:

1. Reduce Loki retention in `group_vars/observe.yml` (quickest win — logs are large)
2. Reduce Prometheus retention
3. Move Docker volumes to a USB SSD (`/mnt/ssd/docker`)

Monitor disk on observe via the Homelab Overview dashboard or:

```bash
ssh admin@homelab-observe
df -h /var/lib/docker
```