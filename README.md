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
  * [Security](#security)
    * [User Model](#user-model)
    * [Defense in Depth](#defense-in-depth)
  * [Backup Strategy](#backup-strategy)
  * [Monitoring & Alerting](#monitoring--alerting)
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

IP assignments, firewall rules, DNS, Tailscale ACLs, and traffic flow diagrams are in [docs/NETWORK.md](./docs/NETWORK.md).

**Summary:**

| Node              | Local IP      | Tailscale IP |
|-------------------|---------------|--------------|
| `homelab-edge`    | 192.168.1.10  | 100.x.x.1    |
| `homelab-observe` | 192.168.1.11  | 100.x.x.2    |
| `homelab-svc-01`  | 192.168.1.20  | 100.x.x.3    |
| `homelab-svc-02`  | 192.168.1.21  | 100.x.x.4    |
| `homelab-svc-03`  | 192.168.1.22  | 100.x.x.5    |

- Internal DNS served by Pi-hole on `homelab-edge` (LAN only, port 53 firewalled)
- External traffic enters via Cloudflare Tunnel — no router port forwards required
- Tailscale is installed on every node individually; each node remains accessible over VPN even if `homelab-edge` is down

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

1. **Network perimeter** — no open router ports; Cloudflare Tunnel handles all external ingress; UPnP disabled
2. **Edge node** — fail2ban (SSH: 3 failures; HTTP: 10 failures); Pi-hole blocks malicious domains; Cloudflare Tunnel 
rate-limits and filters before traffic reaches the homelab
3. **All nodes** — SSH key-only, no root login, no password auth; ufw default-deny inbound; unattended security updates
4. **Secrets** — all credentials in Ansible Vault, encrypted at rest; no hardcoded values in playbooks or templates
5. **Tailscale VPN** — per-node ACLs restrict inter-node communication; admin access requires Tailscale login with MFA
6. **Monitoring** — Alertmanager notifies on failed SSH attempts; Uptime Kuma alerts on service downtime

Secrets are stored in `inventories/group_vars/all/vault.yml`. See `inventories/group_vars/all/vault.yml.example` for required variable names.

---

## Backup Strategy

| Data                    | Method                | Destination               | Frequency |
|-------------------------|-----------------------|---------------------------|-----------|
| PostgreSQL databases    | `pg_dump`             | `/mnt/nvme/backups`       | Daily     |
| Elasticsearch snapshots | Snapshot API          | `/mnt/nvme/elasticsearch` | Daily     |
| All configuration       | Git (Ansible repo)    | GitHub                    | On commit |
| Grafana dashboards      | JSON in repo          | GitHub                    | On commit |
| Pi-hole config          | `custom.list` in repo | GitHub                    | On commit |

Run backups on demand:

```bash
ansible-playbook playbooks/backup.yml
```

For disaster recovery procedures see [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md#disaster-recovery).

---

## Monitoring & Alerting

Full stack reference (Prometheus, Loki, Grafana, Alertmanager, Uptime Kuma) is in [docs/MONITORING.md](./docs/MONITORING.md).

**Alert channels:**

| Severity | Condition                                          | Channel       |
|----------|----------------------------------------------------|---------------|
| Critical | Node down, disk < 5%, crash loop                   | Discord / SMS |
| Warning  | CPU/memory > 80%, disk < 10%, SSL expiry           | Discord       |
| Info     | Updates available, backup done, new Tailscale node | Discord       |

**Key service endpoints (internal):**

| Service      | URL                                      |
|--------------|------------------------------------------|
| Grafana      | `http://grafana.homelab.local:3000`      |
| Prometheus   | `http://prometheus.homelab.local:9090`   |
| Alertmanager | `http://alertmanager.homelab.local:9093` |
| Uptime Kuma  | `http://uptime.homelab.local:3001`       |
| Portainer    | `http://portainer.homelab.local:9000`    |
