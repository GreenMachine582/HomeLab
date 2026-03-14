# Homelab

A Raspberry Pi homelab managed entirely through Ansible. Manual intervention is limited to the one-time bootstrap 
(Phase 1); all subsequent deployments and updates are automated.

**See [BOOTSTRAP.md](./BOOTSTRAP.md) to get started.**

<!-- TOC -->
* [Homelab](#homelab)
  * [Architecture Overview](#architecture-overview)
    * [Deployment Phases](#deployment-phases)
  * [Repo Structure](#repo-structure)
  * [Network](#network)
    * [IP Assignments](#ip-assignments)
    * [DNS](#dns)
    * [External Access](#external-access)
  * [Security](#security)
    * [User Model](#user-model)
    * [Defense in Depth](#defense-in-depth)
    * [Secret Management](#secret-management)
  * [Backup Strategy](#backup-strategy)
    * [What Is Backed Up](#what-is-backed-up)
    * [Running the Backup Playbook](#running-the-backup-playbook)
    * [Disaster Recovery](#disaster-recovery)
  * [Monitoring & Alerting](#monitoring--alerting)
    * [Alert Rules](#alert-rules)
    * [Grafana Dashboards](#grafana-dashboards)
    * [Uptime Kuma Monitors](#uptime-kuma-monitors)
<!-- TOC -->

---

## Architecture Overview

The homelab is organised into four node roles. Full hardware and service details are in [NODES.md](./NODES.md).

| Node                | Role                                          | Status   |
|---------------------|-----------------------------------------------|----------|
| `homelab-edge`      | Internet edge, DNS, ingress, Ansible control  | Active   |
| `homelab-observe`   | Monitoring, logging, alerting                 | Active   |
| `homelab-svc-01`    | Orchestration, databases (Camunda stack)      | Active   |
| `homelab-svc-02`    | User-facing application workloads             | Planned  |
| `homelab-svc-03`    | Media server (Jellyfin)                       | Future   |

### Deployment Phases

```
Phase 1:  PC ────────────────► homelab-edge        (bootstrap from PC, one-time)
Phase 2:  homelab-edge ──────► itself              (edge self-deploys its services)
Phase 3:  homelab-edge ──────► other nodes         (edge deploys observe + svc nodes)
Phase 4:  GitHub push ──► n8n/Camunda ──► edge     (automated deploys via automation endpoint)
```

After Phase 1, all deployments are driven by Ansible playbooks running on the edge node. On push to `master`, a minimal 
GitHub Actions workflow POSTs to an n8n or Camunda endpoint, which SSHes to the edge as the `deploy` user and runs 
`scripts/deploy.sh`. The edge is the sole Ansible control node — GitHub never connects directly to any homelab node.

---

## Repo Structure

```text
homelab/
  README.md                   # This file
  BOOTSTRAP.md                # Step-by-step bootstrap guide (Phases 1–4)
  NODES.md                    # Hardware and service details per node

  inventories/
    bootstrap.ini             # Phase 1: bootstrap edge from PC
    prod.ini                  # All nodes, production groups
    staging.ini               # Future: staging environment

  group_vars/
    all.yml                   # Common: timezone, NTP, users
    edge.yml                  # Edge-specific: Tailscale subnet, firewall rules
    observe.yml               # Observability: retention, alert endpoints
    svc.yml                   # Service nodes: Docker daemon config, resource limits

  host_vars/
    homelab-edge.yml          # Cloudflare tunnel ID, Pi-hole upstream
    homelab-observe.yml       # Prometheus scrape targets, Loki config
    homelab-svc-01.yml        # Camunda: Elasticsearch heap, DB config
    homelab-svc-02.yml        # GreenTechHub: Django config, Redis
    homelab-svc-03.yml        # Jellyfin: media paths, transcoding settings

  playbooks/
    bootstrap_edge.yml        # Phase 1: initial edge setup
    bootstrap_node.yml        # Phase 3: bootstrap a new node
    deploy_edge.yml           # Phase 2: deploy edge services
    deploy_observe.yml        # Phase 3: deploy monitoring stack
    deploy_svc.yml            # Phase 3: deploy service workloads
    update_all.yml            # OS updates, Docker image pulls
    backup.yml                # Database backups, config exports
    rollback.yml              # Revert to previous Docker images
    healthcheck.yml           # Verify all services are healthy

  roles/
    base_hardening/           # SSH hardening, firewall, fail2ban, sysctl
    docker/                   # Docker install and daemon config
    docker_compose/           # Docker Compose plugin
    tailscale/                # Tailscale install and config
    firewall/                 # ufw/nftables rules
    fail2ban/                 # SSH + HTTP jails
    node_exporter/            # Prometheus node exporter
    cadvisor/                 # Container metrics (svc nodes)
    alloy/                    # Grafana Alloy (logs → Loki)
    edge_services/            # cloudflared, Pi-hole, Unbound
    observe_services/         # Prometheus, Loki, Grafana, Alertmanager, Uptime Kuma
    camunda/                  # Camunda 8 stack
    greentechhub/             # Django application
    jellyfin/                 # Media server

  compose/
    edge.yml                  # Edge services
    observe.yml               # Observability stack
    camunda.yml               # Camunda 8 + dependencies
    greentechhub.yml          # Django + Redis + Celery
    jellyfin.yml              # Media server

  templates/
    cloudflared/config.yml.j2
    pihole/custom.list.j2
    prometheus/
      prometheus.yml.j2
      alerts.yml.j2
    alertmanager/alertmanager.yml.j2
    grafana/
      datasources.yml.j2
      dashboards/
    loki/loki.yml.j2
    postgres/postgresql.conf.j2
    elasticsearch/elasticsearch.yml.j2
    alloy/config.alloy.j2

  secrets/
    vault.yml                 # Ansible Vault: passwords, API keys, certificates
    vault.yml.example         # Template — commit this, never vault.yml itself

  scripts/
    backup_databases.sh       # Manual database backup
    test_connectivity.sh      # Verify Tailscale mesh
    deploy.sh                 # Pull latest repo + run specified playbook

  docs/
    NETWORK.md                # IP assignments, firewall rules, Tailscale ACLs
    MONITORING.md             # Grafana dashboard guide, alert tuning
    TROUBLESHOOTING.md        # Common issues and recovery procedures

  .github/
    workflows/
      deploy.yml              # On push to master: POST to n8n/Camunda deploy endpoint
      test.yml                # Ansible lint, YAML validation on pull request
```

---

## Network

### IP Assignments

| Node              | Local IP       | Tailscale IP  | Role                      |
|-------------------|----------------|---------------|---------------------------|
| `homelab-edge`    | 192.168.1.10   | 100.x.x.1     | Edge, DNS, reverse proxy  |
| `homelab-observe` | 192.168.1.11   | 100.x.x.2     | Monitoring                |
| `homelab-svc-01`  | 192.168.1.20   | 100.x.x.3     | Camunda, databases        |
| `homelab-svc-02`  | 192.168.1.21   | 100.x.x.4     | GreenTechHub              |
| `homelab-svc-03`  | 192.168.1.22   | 100.x.x.5     | Jellyfin                  |

Static DHCP reservations should be configured on your router. These IPs are also referenced in `host_vars/`.

### DNS

Pi-hole runs on `homelab-edge` and handles **internal DNS only**. Its responsibilities are:

- Resolving `.homelab.local` hostnames so nodes can address each other by name
- Ad-blocking and DNSSEC validation for LAN clients
- Forwarding upstream queries to Unbound (recursive, DNSSEC)

Port 53 is firewalled to LAN only — Pi-hole is never exposed externally. External DNS for public hostnames is managed 
entirely by Cloudflare.

### External Access

Cloudflare Tunnel (`cloudflared`) handles all inbound public traffic. It connects outbound from the edge node to 
Cloudflare's edge — no ports need to be forwarded on the router, and Pi-hole plays no part in this path. DNS resolution 
for public hostnames happens at Cloudflare before requests reach the homelab.

TLS terminates at Cloudflare. Configure tunnel hostnames in `host_vars/homelab-edge.yml`.

---

## Security

### User Model

Three separate system users are created by the bootstrap playbook:

| User      | Purpose                   | SSH Key        | Sudo                             |
|-----------|---------------------------|----------------|----------------------------------|
| `admin`   | Manual maintenance        | `homelab-edge` | Yes (password)                   |
| `homelab` | Ansible automation        | `homelab`      | Yes (passwordless)               |
| `deploy`  | Webhook-triggered deploys | `deploy`       | `/usr/bin/ansible-playbook` only |

Separation ensures a webhook or script compromise cannot escalate beyond running approved playbooks.

### Defense in Depth

1. **Network perimeter** — only ports 80/443 forwarded to edge (or eliminated entirely with Cloudflare Tunnel); UPnP disabled.
2. **Edge node** — fail2ban (SSH: ban after 3 failures; HTTP: ban after 10); Pi-hole blocks malicious domains; 
Cloudflare Tunnel rate-limits and filters traffic at the edge before it reaches the homelab.
3. **All nodes** — SSH key-only, no root login, no password auth; ufw default-deny inbound; unattended security updates.
4. **Secrets** — all credentials in Ansible Vault, encrypted at rest; no hardcoded values in playbooks or templates.
5. **Tailscale VPN** — MagicDNS for internal discovery; ACLs restrict node-to-node communication; admin access requires Tailscale login with MFA.
6. **Monitoring** — Alertmanager notifies on failed SSH attempts (from fail2ban logs); Uptime Kuma alerts on downtime.

### Secret Management

Secrets stored in `secrets/vault.yml` (Ansible Vault, never committed unencrypted):

- Database passwords (PostgreSQL, Elasticsearch)
- API keys (Cloudflare, Tailscale)
- Application secrets (Django secret key, Camunda admin credentials)
- SSL/TLS certificates (where not using Let's Encrypt)

See `secrets/vault.yml.example` for required variable names.

---

## Backup Strategy

### What Is Backed Up

| Data                    | Method                          | Destination                  | Frequency |
|-------------------------|---------------------------------|------------------------------|-----------|
| PostgreSQL databases    | `pg_dump`                       | `/mnt/nvme/backups`          | Daily     |
| Elasticsearch snapshots | Snapshot API                    | `/mnt/nvme/elasticsearch`    | Daily     |
| All configuration       | Git (Ansible repo)              | GitHub                       | On commit |
| Grafana dashboards      | Exported JSON in repo           | GitHub                       | On commit |
| Pi-hole config          | `custom.list` in repo           | GitHub                       | On commit |

### Running the Backup Playbook

```bash
ansible-playbook playbooks/backup.yml --vault-password-file .vault_pass
```

Tasks performed:

- SSH to `svc-01`, run `pg_dump` for each database
- Compress: `gzip /mnt/nvme/backups/*.sql`
- Rotate: retain last 7 days
- Sync to external storage (configure one):
  - rsync to local NAS
  - rclone to Backblaze B2
  - Tailscale + rsync to a remote machine

### Disaster Recovery

**Edge node SD card failure:**
1. Flash a new SD card with RPi OS Lite (64-bit)
2. Run `bootstrap_edge.yml` from your PC (see BOOTSTRAP.md)
3. Run `deploy_edge.yml` from the edge
4. Pi-hole `custom.list` and all config restore from the Git repo automatically
5. Re-authenticate Cloudflare Tunnel if credentials have expired

**Database corruption on `svc-01`:**
1. Stop the affected service: `docker compose stop postgres`
2. Restore from the latest backup:
   ```bash
   docker exec -i postgres psql -U <db-user> < /mnt/nvme/backups/<dump>.sql
   ```
3. Restart and verify data integrity

**Complete rebuild:**
- Re-run all bootstrap and deploy playbooks in order (Phases 1–3)
- Restore databases from the most recent backup
- Maximum data loss equals the backup interval (default: 24 hours)

---

## Monitoring & Alerting

### Alert Rules

| Severity | Condition                            | Channel       |
|----------|--------------------------------------|---------------|
| Critical | Node down (no heartbeat > 2 min)     | Discord / SMS |
| Critical | Disk < 5%                            | Discord / SMS |
| Critical | Container crash loop (> 3 in 10 min) | Discord / SMS |
| Warning  | CPU or memory > 80% for 5 min        | Discord       |
| Warning  | Disk < 10%                           | Discord       |
| Warning  | SSL certificate expiring < 7 days    | Discord       |
| Info     | Package updates available            | Discord       |
| Info     | Backup completed                     | Discord       |
| Info     | New node joined Tailscale            | Discord       |

### Grafana Dashboards

All dashboards are pre-imported by the `deploy_observe.yml` playbook from JSON files in `templates/grafana/dashboards/`.

| Dashboard           | Contents                                                |
|---------------------|---------------------------------------------------------|
| Homelab Overview    | CPU, memory, disk, network, container status, uptime    |
| Node Detail         | Per-node load, I/O wait, disk IOPS, top processes       |
| Container Metrics   | cAdvisor: CPU/memory/restarts/network per container     |
| Pi-hole Analytics   | DNS queries/sec, blocked domains, query types           |
| Application Logs    | Loki: error aggregation, log volume by service, search  |
| Camunda Metrics     | Active instances, job queue, incidents (future)         |

### Uptime Kuma Monitors

HTTP checks every 60 seconds against internal endpoints:

| Service       | Endpoint                                    |
|---------------|---------------------------------------------|
| Edge health   | `http://homelab-edge/health`                |
| Pi-hole admin | `http://homelab-edge/admin`                 |
| Grafana       | `http://homelab-observe:3000/api/health`    |
| Camunda       | `http://homelab-svc-01:8081`                |
| GreenTechHub  | `http://homelab-svc-02:8000/health`         |
| Jellyfin      | `http://homelab-svc-03:8096/health`         |

Notifications are routed via Alertmanager. Configure channels (Discord) in `templates/alertmanager/alertmanager.yml.j2`.
