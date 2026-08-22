# Nodes Reference

Per-node hardware specifications and deployed services.

**Quick links:** [🟩 `homelab-edge`](#-homelab-edge--rpi-4-model-b) · [🟨 `homelab-observe`](#-homelab-observe--rpi-4-model-b) · [🟦 `homelab-data-01`](#-homelab-data-01--rpi-5-model-b-planned) · [🟦 `homelab-svc-01`](#-homelab-svc-01--pc-01-desktop-planned) · [🟦 `homelab-svc-02`](#-homelab-svc-02--laptop-01-planned)

<details>
<summary>Full outline</summary>

<!-- TOC -->
* [Nodes Reference](#nodes-reference)
  * [🟩 `homelab-edge` — RPi 4 Model B](#-homelab-edge--rpi-4-model-b)
    * [Host-Level Services](#host-level-services)
    * [Dockerized Services](#dockerized-services)
  * [🟨 `homelab-observe` — RPi 4 Model B](#-homelab-observe--rpi-4-model-b)
    * [Host-Level Services](#host-level-services-1)
    * [Dockerized Services](#dockerized-services-1)
    * [Metrics Scope](#metrics-scope)
  * [🟦 `homelab-data-01` — RPi 5 Model B *(Planned)*](#-homelab-data-01--rpi-5-model-b-planned)
    * [Host-Level Services](#host-level-services-2)
    * [Dockerized Services](#dockerized-services-2)
    * [Resource Allocation (Guidance)](#resource-allocation-guidance)
    * [Deployment Notes](#deployment-notes)
  * [🟦 `homelab-svc-01` — pc-01 Desktop *(Planned)*](#-homelab-svc-01--pc-01-desktop-planned)
    * [Host-Level Services](#host-level-services-3)
    * [Dockerized Services](#dockerized-services-3)
    * [Resource Allocation (Guidance)](#resource-allocation-guidance-1)
    * [Deployment Notes](#deployment-notes-1)
  * [🟦 `homelab-svc-02` — laptop-01 *(Planned)*](#-homelab-svc-02--laptop-01-planned)
    * [Dockerized Services](#dockerized-services-4)
    * [Resource Allocation (Guidance)](#resource-allocation-guidance-2)
    * [Routing](#routing)
    * [Deployment](#deployment)
<!-- TOC -->

</details>

---

## 🟩 `homelab-edge` — RPi 4 Model B

**Storage:** 32GB Ultra microSDHC UHS-I (consider USB SSD for `/var/lib/docker` if I/O becomes a bottleneck)

**Role:** Internet edge, DNS, ingress, security boundary, and Ansible control node.

**Network:**

| Property      | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| Local IP      | `ip_edge`                                                             |
| Tailscale IP  | 100.x.x.1                                                             |
| Port forwards | None — Cloudflare Tunnel connects outbound; no router forwards needed |

### Host-Level Services

| Service             | Purpose                                                                                    |
|---------------------|--------------------------------------------------------------------------------------------|
| Tailscale           | Subnet-router mode; exposes homelab to VPN                                                 |
| ufw / nftables      | Firewall: allow `ssh_port` (any), 53 (LAN only), 8443/8444 (Tailscale CGNAT — Caddy HTTPS for Infisical/Semaphore), 8222/3010 (Tailscale CGNAT — direct non-browser access); 80/443 not needed with Cloudflare Tunnel |
| fail2ban            | SSH (3 failures) and HTTP (10 failures) banning                                   |
| SSH hardening       | Key-only, no root, no password auth                                               |
| Unattended upgrades | Automatic security patches                                                        |
| Ansible             | Control node for all playbooks; triggered by deploy user via SSH                  |

### Dockerized Services

| Service         | Purpose                                                                                                                                                            |
|-----------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `cloudflared`   | Cloudflare Tunnel — outbound connection to Cloudflare; routes `*.yourdomain.com` to internal services; TLS terminates at Cloudflare; no open router ports required |
| Pi-hole         | **Internal DNS only** — resolves `.homelab.local` hostnames to node IPs via `custom.list`; ad-blocking for LAN clients; port 53 firewalled to LAN                  |
| Unbound         | Recursive DNS upstream for Pi-hole; DNSSEC validation                                                                                                              |
| `node-exporter` | Host metrics for Prometheus                                                                                                                                        |
| Grafana Alloy   | Log shipping to Loki on `homelab-observe`                                                                                                                          |
| Infisical (+ Postgres, Redis) | Self-hosted secrets manager — canonical store for application secrets (seeded from `vault.yml` during Phase 1, see `roles/infisical`). **Tailscale-only**: no Pi-hole DNS entry; Caddy HTTPS on port 8443 at `homelab-edge.<tailnet>.ts.net:8443` (browser); direct port 8222 for non-browser clients — both firewalled to the Tailscale CGNAT range |
| Semaphore (+ Postgres) | Web UI over the playbooks in this repo, with the repo bind-mounted read-only and a separate writable workspace volume (`roles/semaphore`). **Tailscale-only**: no Pi-hole DNS entry; Caddy HTTPS on port 8444 at `homelab-edge.<tailnet>.ts.net:8444` (browser); direct port 3010 for non-browser clients — both firewalled to the Tailscale CGNAT range |

**Pi-hole DNS mappings** (source: `pihole_custom_dns` in `group_vars/edge.yml`):

| Hostname                     | Resolves to              |
|------------------------------|--------------------------|
| `grafana.homelab.local`      | `ip_observe` (port 3000) |
| `prometheus.homelab.local`   | `ip_observe` (port 9090) |
| `alertmanager.homelab.local` | `ip_observe` (port 9093) |
| `uptime.homelab.local`       | `ip_observe` (port 3001) |
| `portainer.homelab.local`    | `ip_observe` (port 9000) |
| `camunda.homelab.local`      | `ip_svc_01` (port 8080)  |
| `authentik.homelab.local`    | `ip_svc_01` (port 9000)  |
| `n8n.homelab.local`          | `ip_svc_01` (port 5678)  |
| `greentechhub.homelab.local` | `ip_svc_02` (port 8000)  |
| `jellyfin.homelab.local`     | `ip_svc_01` (port 8096)  |

Clients access services directly at `http://<hostname>:<port>`. Internal traffic travels over Tailscale (encrypted) so a separate TLS layer is not required.

> 🔒 Infisical and Semaphore are deliberately absent from this table — see the Dockerized Services rows above for their Tailscale-only access URLs, and [docs/NETWORK.md](./docs/NETWORK.md) for the firewall rules that enforce it.

---

## 🟨 `homelab-observe` — RPi 4 Model B

**Storage:** 32GB Ultra microSDHC UHS-I A1 (consider USB SSD if Prometheus/Loki data grows)

**Role:** Observability and management plane.

**Network:**

| Property     | Value         |
|--------------|---------------|
| Local IP     | `ip_observe`  |
| Tailscale IP | 100.x.x.2     |
| Public ports | None          |

ACL: accessible from edge node and admin devices only. Tailscale runs directly on this node — reachable over VPN even if `homelab-edge` is down.

### Host-Level Services

| Service             | Purpose                                                           |
|---------------------|---------------------------------------------------------------------|
| Tailscale           | Direct VPN node; independent of edge; own Tailscale IP (100.x.x.2) |
| ufw / nftables      | Firewall: allow `ssh_port`, service ports (LAN / VPN only)       |
| SSH hardening       | Key-only, no root, no password auth                               |
| Unattended upgrades | Automatic security patches                                        |

### Dockerized Services

| Service      | Configuration                                                             |
|--------------|---------------------------------------------------------------------------|
| Prometheus   | Scrapes all `node-exporter` and `cAdvisor` instances; 30-day retention    |
| Loki         | Receives logs from all Grafana Alloy agents; 14-day retention             |
| Grafana      | Pre-configured dashboards (see README); data sources: Prometheus, Loki    |
| Alertmanager | Routes: Discord (critical/warning/info webhooks); rules: node down, high CPU/mem, disk |
| Uptime Kuma  | HTTP/HTTPS endpoint monitoring; notification channels configured manually in the UI (not managed by `setup_monitors.py`) |
| Portainer    | Docker management UI; agents on edge, homelab-data-01, svc-01, svc-02     |

### Metrics Scope

- `node-exporter` on all nodes
- `cAdvisor` on `svc-*` and `data-*` nodes (container metrics)
- Pi-hole exporter (DNS queries, blocked domains)
- Future: Camunda exporter

---

## 🟦 `homelab-data-01` — RPi 5 Model B *(Planned)*

**Storage:** 64GB Extreme Pro microSDXC UHS-I A2 + 2TB NVMe (mounted at `/mnt/nvme`; Docker data dir: `/mnt/nvme/docker`)

**Role:** Dedicated shared data tier — Postgres + Redis, serving `n8n-automation`, `authentik-sso` (post data-tier migration), `greentechhub`, and future apps. This is the same rpi-03 hardware originally planned for `homelab-svc-01`; that identity moves to pc-01 instead (see [docs/consolidated_brief.md](./docs/consolidated_brief.md) §7.1).

**Network:**

| Property     | Value         |
|--------------|---------------|
| Local IP     | `ip_data_01`  |
| Tailscale IP | 100.x.x.3     |
| Public ports | None          |

ACL: accessible from edge node, svc nodes, and admin devices only. Tailscale runs directly on this node — reachable over VPN even if `homelab-edge` is down.

### Host-Level Services

| Service             | Purpose                                                                     |
|---------------------|-------------------------------------------------------------------------------|
| Tailscale           | Direct VPN node; independent of edge; own Tailscale IP (100.x.x.3)           |
| ufw / nftables      | Firewall: allow `ssh_port`, 5432 (Postgres), 6379 (Redis) — tailnet + LAN node IPs only |
| SSH hardening       | Key-only, no root, no password auth                                           |
| Unattended upgrades | Automatic security patches                                                    |

### Dockerized Services

**`homelab-data-services`** (separate repo, deployed via `deploy-service`):

| Component  | Notes                                                                 |
|------------|------------------------------------------------------------------------|
| Postgres 16 | `shared_buffers` 1.5–2GB, `mem_limit: 3g`; data on NVMe                |
| Redis 7     | `maxmemory` 512MB–1GB; isolation scheme (ACL users vs. DB indexes) is an open decision — see `TODO.md` |

**Observability:**

| Service          | Purpose               |
|------------------|------------------------|
| `node-exporter`  | Host metrics           |
| `cAdvisor`       | Container metrics      |
| Grafana Alloy    | Log shipping to Loki   |

### Resource Allocation (Guidance)

| Component                   | Allocation | Notes                                         |
|------------------------------|------------|------------------------------------------------|
| OS + host agents + Docker    | ~0.75GB    |                                                  |
| Postgres 16                  | ~3GB       | `shared_buffers` 1.5–2GB, `mem_limit: 3g`       |
| Redis 7                      | ~1GB       | `maxmemory` 512MB–1GB                           |
| **Headroom**                  | **~3GB**   | WAL bursts, `pg_dump`, connection overhead      |

### Deployment Notes

```bash
/opt/deploy-service-venv/bin/deploy-service deploy homelab-data-services --config /opt/homelab/services.yml
```

Backups: nightly per-DB `pg_dump` + Redis RDB snapshot → NVMe staging → pushed to `pc-01:/srv/backups` over Tailscale (cross-node, so a dead NVMe ≠ dead databases). Failure alerts via ntfy.

---

## 🟦 `homelab-svc-01` — pc-01 Desktop *(Planned)*

**Hardware:** Intel i5-7400 (4C/4T, 3.0–3.5GHz, amd64), 16GB DDR4, Intel HD 630 iGPU (Quick Sync H.264/HEVC via VAAPI)

**Storage:** 240GB SATA SSD (OS + Docker + app volumes) + 1TB BarraCuda HDD (`/srv/media`, `/srv/backups` — cross-node backup target)

**Role:** Orchestration, SSO, and media — heavy compute plus Quick Sync hardware transcoding. Takes over the `homelab-svc-01` identity from the never-bootstrapped rpi-03 plan (see [docs/consolidated_brief.md](./docs/consolidated_brief.md) §7.4).

**Network:**

| Property     | Value         |
|--------------|---------------|
| Local IP     | `ip_svc_01`   |
| Tailscale IP | 100.x.x.4     |
| Public ports | None          |

ACL: accessible from edge node and admin devices only. Tailscale runs directly on this node — reachable over VPN even if `homelab-edge` is down.

### Host-Level Services

| Service             | Purpose                                                           |
|---------------------|-------------------------------------------------------------------|
| Tailscale           | Direct VPN node; independent of edge; own Tailscale IP (100.x.x.4) |
| ufw / nftables      | Firewall: allow `ssh_port`, 8080 (LAN / VPN only). Elasticsearch (9200) is localhost-only, never exposed on the network — Zeebe talks to it over `localhost` |
| SSH hardening       | Key-only, no root, no password auth                               |
| Unattended upgrades | Automatic security patches                                        |

### Dockerized Services

**`camunda-platform`** (separate repo, deployed via `deploy-service` — not Ansible):

| Component            | Notes                                                                        |
|-----------------------|-------------------------------------------------------------------------------|
| `camunda-orchestration` | Camunda 8 Run distribution (Zeebe, Operate, Tasklist bundled in one image), port 8088 |
| Elasticsearch          | Backs the orchestration cluster; localhost-only (never crosses the network); heap configurable via `.env` |

**`n8n-automation`** (separate repo, deployed via `deploy-service`): `n8n`, port 5678. Postgres/Redis via `requires:` → `homelab-data-01` (once migrated, see `TODO.md` Stage 6).

**`authentik-sso`** (separate repo, deployed via `deploy-service`; 🚧 in progress — created, not yet deployed): Authentik server + worker + Redis + its own bundled Postgres for now (`COMPOSE_PROFILES=local-infra`), port 9000. Flips to `homelab-data-01` in Stage 6 with zero repo changes.

**`jellyfin-media`** (new repo, deployed via `deploy-service`): Jellyfin, QSV hardware transcode via `/dev/dri` (HD 630), library on the 1TB HDD (`/srv/media`). Optional Sonarr/Radarr/Prowlarr later.

**`discord-gateway`** *(conditional — pending the B6 keep/remove decision)*: if kept, extracted to its own repo and deployed via `deploy-service` as an amd64 image (single-arch is fine while targeting pc-01/laptop-01 — see `docs/consolidated_brief.md` §6.3), replacing the old Ansible-deployed `docker-compose.svc01.yml` path. `portainer-agent` stays host-level (Portainer server on `homelab-observe` connects here).

**Observability:**

| Service          | Purpose                            |
|------------------|------------------------------------|
| `node-exporter`  | Host metrics                       |
| `cAdvisor`       | Container metrics                  |
| Grafana Alloy    | Log shipping to Loki               |

### Resource Allocation (Guidance)

| Component                                            | Allocation | Notes                                             |
|-------------------------------------------------------|------------|----------------------------------------------------|
| OS + host agents + Docker                              | ~1GB       |                                                      |
| Elasticsearch                                          | ~3GB       | 2GB heap → ~3GB container; can grow to 4GB heap     |
| Zeebe + Operate + Tasklist                              | ~3.5GB     |                                                      |
| n8n (main)                                              | ~0.5GB     |                                                      |
| Authentik server + worker (+ bundled PG/Redis until Stage 6) | ~1.5GB | Drops ~0.5GB after Stage 6                          |
| Jellyfin                                                | ~1.5GB     | Transcode is QSV (GPU), not CPU/RAM-bound           |
| discord-gateway (if kept)                               | ~0.1GB     |                                                      |
| **Headroom**                                             | **~5GB**   | Burst, page cache, future services                  |

### Deployment Notes

```bash
/opt/deploy-service-venv/bin/deploy-service deploy camunda-platform --config /opt/homelab/services.yml
/opt/deploy-service-venv/bin/deploy-service deploy n8n-automation --config /opt/homelab/services.yml
/opt/deploy-service-venv/bin/deploy-service deploy jellyfin-media --config /opt/homelab/services.yml
# discord-gateway: only once extracted (D3), conditional on the B6 keep/remove decision
/opt/deploy-service-venv/bin/deploy-service deploy discord-gateway --config /opt/homelab/services.yml
```

BIOS/OS prep before this node can be bootstrapped: enable IGD/primary-display, pull the RX 580 dGPU (sold/shelved — no ROCm support), Debian 13 netinstall (no DE) on the SSD. See `TODO.md` Stage 2.

---

## 🟦 `homelab-svc-02` — laptop-01 *(Planned)*

**Hardware:** Intel m3-7Y30 (2C/4T, 1.0–2.6GHz, amd64, fanless), 4GB RAM (soldered — hard ceiling), Intel HD 615 iGPU

**Storage:** 119GB SSD (OS + Docker + app volumes; no bulk storage)

**Role:** Light-duty, user-facing application workloads. Takes over the `homelab-svc-02` identity from a planned-but-never-bought Pi 5 (see [docs/consolidated_brief.md](./docs/consolidated_brief.md) §7.2).

**Network:**

| Property     | Value         |
|--------------|---------------|
| Local IP     | `ip_svc_02`   |
| Tailscale IP | 100.x.x.5     |
| Public ports | None          |

Wi-Fi is the only onboard NIC — a USB-C GbE adapter is required; no homelab node runs on Wi-Fi. Tailscale runs directly on this node — reachable over VPN even if `homelab-edge` is down. Built-in battery doubles as a free mini-UPS; lid-closed headless operation (`HandleLidSwitch=ignore`, sleep/suspend/hibernate masked).

### Dockerized Services

**`greentechhub`** (separate repo, deployed via `deploy-service` — not Ansible):

| Service         | Notes                                                       |
|-----------------|---------------------------------------------------------------|
| GreenTechHub    | Django / Gunicorn application server                          |
| Celery worker   | Async task processing; concurrency 2                           |
| Flower          | Celery monitoring (optional)                                   |

Postgres/Redis: provided by `homelab-data-01` via `requires:` from day one (no local DB container — this node's 4GB ceiling rules out hosting its own).

**Observability:**

| Service          | Purpose               |
|------------------|------------------------|
| `node-exporter`  | Host metrics           |
| `cAdvisor`       | Container metrics      |
| Grafana Alloy    | Log shipping to Loki   |

### Resource Allocation (Guidance)

| Component                        | Allocation | Notes                                          |
|------------------------------------|------------|--------------------------------------------------|
| OS + host agents + Docker          | ~0.6GB     | No DE installed                                   |
| GreenTechHub (Django + gunicorn)   | ~0.7GB     |                                                    |
| Celery worker                      | ~0.5GB     | Concurrency 2; DB/broker are remote (data tier)   |
| **Headroom**                         | **~2GB**   | One more small app max; ES/JVM-class workloads never land here |

### Routing

- **Internal:** Pi-hole resolves `greentechhub.homelab.local` → `ip_svc_02`; access via `http://greentechhub.homelab.local:8000`
- **External:** Cloudflare Tunnel routes `yourdomain.com` → `svc-02:8000`

### Deployment

Configuration and secrets live in the `greentechhub` repo itself (its own `secrets.yml`, auto-discovered by `deploy-service` — see `docs/repo_split_brief.md` §6.2), not `host_vars`/Ansible Vault.

```bash
/opt/deploy-service-venv/bin/deploy-service deploy greentechhub --config /opt/homelab/services.yml
```
