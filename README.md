# Homelab

![Ansible](https://img.shields.io/badge/Ansible-EE0000?logo=ansible&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker_Compose-2496ED?logo=docker&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry_Pi-C51A4A?logo=raspberrypi&logoColor=white)
![Tailscale](https://img.shields.io/badge/Tailscale-579DFF?logo=tailscale&logoColor=white)
![Self-hosted](https://img.shields.io/badge/self--hosted-homelab-4A90D9)
![Status](https://img.shields.io/badge/status-polyrepo_migration_in_progress-yellow)

A Raspberry Pi homelab managed entirely through Ansible. Manual intervention is limited to the one-time bootstrap 
(Phase 1); all subsequent deployments and updates are automated.

**⚠️ This repo is mid-migration to a polyrepo layout** — see [Polyrepo Migration](#-polyrepo-migration) below and [docs/repo_split_brief.md](./docs/repo_split_brief.md) for the full design and status.

**See [BOOTSTRAP.md](./BOOTSTRAP.md) to get started.**

**Quick links:** [🏗️ Architecture Overview](#-architecture-overview) · [🗂️ Repo Structure](#-repo-structure) · [🔀 Polyrepo Migration](#-polyrepo-migration) · [🌐 Network](#-network) · [🔒 Security](#-security) · [💾 Backup Strategy](#-backup-strategy) · [📊 Monitoring & Alerting](#-monitoring--alerting)

<details>
<summary>Full outline</summary>

<!-- TOC -->
* [Homelab](#homelab)
  * [🏗️ Architecture Overview](#-architecture-overview)
    * [Deployment Phases](#deployment-phases)
  * [🗂️ Repo Structure](#-repo-structure)
  * [🔀 Polyrepo Migration](#-polyrepo-migration)
  * [🌐 Network](#-network)
  * [🔒 Security](#-security)
    * [User Model](#user-model)
    * [Defense in Depth](#defense-in-depth)
  * [💾 Backup Strategy](#-backup-strategy)
  * [📊 Monitoring & Alerting](#-monitoring--alerting)
<!-- TOC -->

</details>

---

## 🏗️ Architecture Overview

The homelab is organised into four node roles. Full hardware and service details are in [NODES.md](./NODES.md).

| Node                | Role                                          | Status          |
|---------------------|-----------------------------------------------|-----------------|
| `homelab-edge`      | Internet edge, DNS, ingress, Ansible control  | Active          |
| `homelab-observe`   | Monitoring, logging, alerting                 | Pending Phase 3 |
| `homelab-svc-01`    | Orchestration, databases (Camunda stack)      | Pending Phase 3 |
| `homelab-svc-02`    | User-facing application workloads             | Future          |
| `homelab-svc-03`    | Media server (Jellyfin)                       | Future          |

> See [TODO.md](./TODO.md) for exact bootstrap status — `homelab-observe`'s role is merged but not yet bootstrapped (Milestone A); `homelab-svc-01`'s role is still on an unmerged branch (Milestone B).

### Deployment Phases

```
Phase 1:  PC ────────────────► homelab-edge        (bootstrap from PC, one-time)
Phase 2:  homelab-edge ──────► itself              (edge self-deploys its services)
Phase 3:  homelab-edge ──────► other nodes         (edge deploys observe + svc nodes)
Phase 4:  GitHub push ──► n8n/Camunda ──► edge     (automated deploys via automation endpoint)
```

After Phase 1, all deployments are driven by Ansible playbooks running on the edge node. On push to `master`, a minimal
GitHub Actions workflow POSTs to an n8n or Camunda endpoint, which SSHes to the edge as the `deploy` user and runs
`ansible-playbook` directly. The edge is the sole Ansible control node — GitHub never connects directly to any homelab node.

---

## 🗂️ Repo Structure

```text
homelab/
  README.md                   # This file
  BOOTSTRAP.md                # Step-by-step bootstrap guide (Phases 1–4)
  NODES.md                    # Hardware and service details per node
  TODO.md                     # Open tasks — authoritative source for what's actually done vs pending

  inventories/
    bootstrap.ini              # Phase 1: bootstrap edge from PC
    prod.yml                   # All nodes, production groups
    group_vars/
      all/
        main.yml                # Common: timezone, NTP, users, node IP placeholders, SSH port (EDIT_BEFORE_USE)
        overrides.yml.example   # Template for real IPs/subnet (gitignored once copied to overrides.yml)
        vault.yml.example       # Template for Ansible Vault secrets — commit this, never vault.yml itself
      edge.yml                  # Edge-specific: Tailscale subnet, firewall rules
      observe.yml                # Observability: retention, alert endpoints
      # svc.yml (service nodes: Docker daemon config, resource limits) lives on
      # the unmerged `wip/svc` branch — pending Milestone B
    host_vars/
      homelab-edge.yml          # Cloudflare tunnel ID, Pi-hole upstream
      homelab-observe.yml       # Prometheus scrape targets, Loki config
      # homelab-svc-01.yml, -02.yml, -03.yml don't exist yet — svc-01 host_vars
      # live on the unmerged `wip/svc` branch (Milestone B); svc-02/03 are unstarted

  playbooks/
    bootstrap_edge.yml        # Phase 1: edge setup, Infisical bring-up + full provision/seed, Semaphore — single pass
    bootstrap_node.yml        # Phase 3: bootstrap a new node
    deploy_edge.yml           # Phase 2: deploy edge services
    apply_firewall.yml        # Update UFW rules after provisioning a node/service
    resolve_node_ips.yml      # Shared preamble: resolves observe/svc IPs live from Infisical
    update_all.yml            # OS updates, Docker image pulls
    backup.yml                # Database backups, config exports
    rollback.yml              # Revert to previous Docker images
    healthcheck.yml           # Verify all services are healthy

  roles/
    base_hardening/           # SSH hardening, sysctl
    docker/                   # Docker install and daemon config
    docker_compose/           # Docker Compose plugin
    tailscale/                # Tailscale install and config
    firewall/                 # ufw rules
    fail2ban/                 # SSH + HTTP jails (templates/jail.conf.j2)
    unbound/                  # Recursive DNS resolver, Pi-hole upstream (edge)
    alloy/                    # Grafana Alloy (logs → Loki)
    users/                    # System user creation (admin, homelab, deploy)
    infisical/                # Infisical .env rendering + seed (secrets manager, Tailscale-only)
    semaphore/                # Semaphore .env rendering (Ansible web UI, Tailscale-only)

  # svc-01 roles (camunda, cadvisor, node_exporter, greentechhub, jellyfin) and
  # playbooks/deploy_svc.yml exist on the unmerged `wip/svc` branch — pending
  # Milestone B (TODO.md), not yet on master.

  # Docker Compose stacks (at repo root, deployed per-node)
  docker-compose.edge.yml     # Infisical (+ Postgres, Redis), Semaphore (+ Postgres) — bootstrap tier only
                              # homelab-edge-services (separate repo): cloudflared, Caddy, Pi-hole, pihole-exporter, node-exporter, portainer-agent
                              # homelab-observe-services (separate repo): Prometheus, Loki, Grafana, Alertmanager, ntfy, Uptime Kuma, Portainer
                              # camunda-platform (separate repo): Camunda 8, Elasticsearch
                              # n8n-automation (separate repo): n8n
                              # authentik-sso (separate repo, in progress): Authentik server/worker/Redis + own Postgres
  docker-compose.svc01.yml    # discord-gateway, Portainer Agent — remaining leftovers not yet split out (Milestone D3, gated on TODO.md B6)

  # Jinja2 templates live inside each role at roles/<role>/templates/
  # Key templates:
  #   roles/alloy/templates/config.alloy.j2
  #   roles/infisical/templates/env.j2
  #   roles/semaphore/templates/env.j2
  #   roles/fail2ban/templates/jail.conf.j2

  scripts/
    deploy.sh                 # Restricted-sudo entrypoint for the `deploy` user (Phase 4)
    backup_databases.sh       # Thin wrapper around playbooks/backup.yml
    test_connectivity.sh      # LAN ping, Tailscale, SSH, HTTP endpoints, DNS checks

  docs/
    NETWORK.md                # IP assignments, firewall rules, Tailscale ACLs
    TROUBLESHOOTING.md        # Common issues and recovery procedures
    repo_split_brief.md       # Polyrepo migration design brief (active, in-progress)

  .github/
    workflows/
      deploy.yml              # On push to master: POST to n8n/Camunda deploy endpoint
```

---

## 🔀 Polyrepo Migration

This repo is being split into a polyrepo — see [docs/repo_split_brief.md](./docs/repo_split_brief.md) for the full design and [TODO.md](./TODO.md) for the live checklist. Current status:

| Split | Status |
|---|---|
| `homelab-edge-services` (cloudflared, Caddy, Pi-hole, exporters) | ✅ Live |
| `homelab-observe-services` (Prometheus, Loki, Grafana, Alertmanager, ntfy, Uptime Kuma, Portainer) | ✅ Extracted, tagged `v0.1.0`, registered in `services.yml` — end-to-end deploy verification still pending `homelab-observe` going live |
| `camunda-platform` (Camunda 8, Elasticsearch) | ✅ Extracted, registered in `services.yml` — end-to-end deploy verification still pending `homelab-svc-01` going live |
| `n8n-automation` (n8n) | ✅ Extracted, registered in `services.yml` — end-to-end deploy verification still pending `homelab-svc-01` going live |
| `discord-gateway` (out of `homelab-svc-01`) | ⏳ Not started — gated on the keep/remove decision in `TODO.md` B6 |
| `authentik-sso` (Authentik SSO, own repo + bundled Postgres) | 🚧 In progress — repo created, `docker-compose.yml` written; not yet registered in `services.yml` or deployed |

---

## 🌐 Network

IP assignments, firewall rules, DNS, Tailscale ACLs, and traffic flow diagrams are in [docs/NETWORK.md](./docs/NETWORK.md).

**Summary:**

| Node              | IP var        | Tailscale IP |
|-------------------|---------------|--------------|
| `homelab-edge`    | `ip_edge`     | 100.x.x.1    |
| `homelab-observe` | `ip_observe`  | 100.x.x.2    |
| `homelab-svc-01`  | `ip_svc_01`   | 100.x.x.3    |
| `homelab-svc-02`  | `ip_svc_02`   | 100.x.x.4    |
| `homelab-svc-03`  | `ip_svc_03`   | 100.x.x.5    |

> Real IP values are defined in `inventories/group_vars/all/overrides.yml` (gitignored) — `main.yml` only holds `EDIT_BEFORE_USE` placeholders.

- Internal DNS served by Pi-hole on `homelab-edge` (LAN only, port 53 firewalled)
- External traffic enters via Cloudflare Tunnel — no router port forwards required
- Tailscale is installed on every node individually; each node remains accessible over VPN even if `homelab-edge` is down

---

## 🔒 Security

### User Model

Three separate system users are created by the bootstrap playbook:

| User      | Purpose                   | SSH Key        | Sudo                             |
|-----------|---------------------------|----------------|----------------------------------|
| `admin`   | Manual maintenance        | `homelab-edge` | Yes (password)                   |
| `homelab` | Ansible automation        | `homelab`      | Yes (passwordless)               |
| `deploy`  | Webhook-triggered deploys | `deploy`       | `scripts/deploy.sh` only         |

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

## 💾 Backup Strategy

| Data                    | Method                | Destination               | Frequency |
|-------------------------|-----------------------|---------------------------|-----------|
| PostgreSQL databases    | `pg_dump`             | `/mnt/nvme/backups`       | Daily     |
| Infisical / Semaphore DBs (edge) | `pg_dump` \| `gzip` | `/opt/backups/postgres` (homelab-edge) | Daily |
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

## 📊 Monitoring & Alerting

Full stack reference (Prometheus, Loki, Grafana, Alertmanager, Uptime Kuma) is in [homelab-observe-services/docs/MONITORING.md](https://github.com/GreenMachine582/homelab-observe-services/blob/master/docs/MONITORING.md).

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

**Infisical & Semaphore (LAN via Caddy, Tailscale HTTPS via Caddy, or Tailscale direct — see [docs/NETWORK.md](./docs/NETWORK.md)):**

| Service   | URL                                          | Notes                                                                          |
|-----------|----------------------------------------------|--------------------------------------------------------------------------------|
| Infisical | `https://homelab-edge.<tailnet>.ts.net:8443` | or `http://<edge-tailscale-ip>:8222` (non-browser) |
| Semaphore | `https://homelab-edge.<tailnet>.ts.net:8444` | or `http://<edge-tailscale-ip>:3010` (non-browser) |
