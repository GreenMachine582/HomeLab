# Nodes Reference

Per-node hardware specifications and deployed services.

<!-- TOC -->
* [Nodes Reference](#nodes-reference)
  * [🟩 `homelab-edge` — RPi 4 Model B](#-homelab-edge--rpi-4-model-b)
    * [Host-Level Services](#host-level-services)
    * [Dockerized Services](#dockerized-services)
  * [🟨 `homelab-observe` — RPi 4 Model B](#-homelab-observe--rpi-4-model-b)
    * [Dockerized Services](#dockerized-services-1)
    * [Metrics Scope](#metrics-scope)
  * [🟥 `homelab-svc-01` — RPi 5 Model B](#-homelab-svc-01--rpi-5-model-b)
    * [Dockerized Services](#dockerized-services-2)
    * [Resource Allocation (Guidance)](#resource-allocation-guidance)
    * [Deployment Notes](#deployment-notes)
  * [🟦 `homelab-svc-02` — RPi 5 Model B *(Planned)*](#-homelab-svc-02--rpi-5-model-b-planned)
    * [Dockerized Services](#dockerized-services-3)
    * [Routing](#routing)
    * [Deployment](#deployment)
  * [🟦 `homelab-svc-03` — *(Future)* Jellyfin / Media Node](#-homelab-svc-03--future-jellyfin--media-node)
    * [Dockerized Services](#dockerized-services-4)
    * [Routing](#routing-1)
    * [Future Enhancements](#future-enhancements)
<!-- TOC -->

---

## 🟩 `homelab-edge` — RPi 4 Model B

**Storage:** 32GB Ultra microSDHC UHS-I (consider USB SSD for `/var/lib/docker` if I/O becomes a bottleneck)

**Role:** Internet edge, DNS, ingress, security boundary, and Ansible control node.

**Network:**

| Property      | Value                                                                 |
|---------------|-----------------------------------------------------------------------|
| Local IP      | 192.168.1.10                                                          |
| Tailscale IP  | 100.x.x.1                                                             |
| Port forwards | None — Cloudflare Tunnel connects outbound; no router forwards needed |

### Host-Level Services

| Service             | Purpose                                                                           |
|---------------------|-----------------------------------------------------------------------------------|
| Tailscale           | Subnet-router mode; exposes homelab to VPN                                        |
| ufw / nftables      | Firewall: allow 22 (any), 53 (LAN only); 80/443 not needed with Cloudflare Tunnel |
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

**Pi-hole DNS mappings** (`pihole/custom.list`):

| Hostname                     | Resolves to                |
|------------------------------|----------------------------|
| `grafana.homelab.local`      | `192.168.1.11` (port 3000) |
| `prometheus.homelab.local`   | `192.168.1.11` (port 9090) |
| `alertmanager.homelab.local` | `192.168.1.11` (port 9093) |
| `uptime.homelab.local`       | `192.168.1.11` (port 3001) |
| `portainer.homelab.local`    | `192.168.1.11` (port 9000) |
| `camunda.homelab.local`      | `192.168.1.20` (port 8080) |
| `greentechhub.homelab.local` | `192.168.1.21` (port 8000) |
| `jellyfin.homelab.local`     | `192.168.1.22` (port 8096) |

Clients access services directly at `http://<hostname>:<port>`. Internal traffic travels over Tailscale (encrypted) so a separate TLS layer is not required.

---

## 🟨 `homelab-observe` — RPi 4 Model B

**Storage:** 32GB Ultra microSDHC UHS-I A1 (consider USB SSD if Prometheus/Loki data grows)

**Role:** Observability and management plane.

**Network:**

| Property     | Value         |
|--------------|---------------|
| Local IP     | 192.168.1.11  |
| Tailscale IP | 100.x.x.2     |
| Public ports | None          |

ACL: accessible from edge node and admin devices only. Tailscale runs directly on this node — reachable over VPN even if `homelab-edge` is down.

### Host-Level Services

| Service             | Purpose                                                           |
|---------------------|-------------------------------------------------------------------|
| Tailscale           | Direct VPN node; independent of edge; own Tailscale IP (100.x.x.2) |
| ufw / nftables      | Firewall: allow 22, service ports (LAN / VPN only)               |
| SSH hardening       | Key-only, no root, no password auth                               |
| Unattended upgrades | Automatic security patches                                        |

### Dockerized Services

| Service      | Configuration                                                             |
|--------------|---------------------------------------------------------------------------|
| Prometheus   | Scrapes all `node-exporter` and `cAdvisor` instances; 30-day retention    |
| Loki         | Receives logs from all Grafana Alloy agents; 14-day retention             |
| Grafana      | Pre-configured dashboards (see README); data sources: Prometheus, Loki    |
| Alertmanager | Routes: Email, Slack (configurable); rules: node down, high CPU/mem, disk |
| Uptime Kuma  | HTTP/HTTPS endpoint monitoring; notifications: Slack                      |
| Portainer    | Docker management UI; agents on edge, svc-01, svc-02, svc-03              |

### Metrics Scope

- `node-exporter` on all nodes
- `cAdvisor` on `svc-*` nodes (container metrics)
- Pi-hole exporter (DNS queries, blocked domains)
- Future: Camunda exporter, PostgreSQL exporter

---

## 🟥 `homelab-svc-01` — RPi 5 Model B

**Storage:** 64GB Extreme Pro microSDXC UHS-I A2 + 2TB NVMe (mounted at `/mnt/nvme`; Docker data dir: `/mnt/nvme/docker`)

**Role:** Orchestration, databases, and heavy workloads.

**Network:**

| Property     | Value         |
|--------------|---------------|
| Local IP     | 192.168.1.20  |
| Tailscale IP | 100.x.x.3     |
| Public ports | None          |

ACL: accessible from edge node and admin devices only. Tailscale runs directly on this node — reachable over VPN even if `homelab-edge` is down.

### Host-Level Services

| Service             | Purpose                                                           |
|---------------------|-------------------------------------------------------------------|
| Tailscale           | Direct VPN node; independent of edge; own Tailscale IP (100.x.x.3) |
| ufw / nftables      | Firewall: allow 22, 8080, 5432, 9200 (LAN / VPN only)           |
| SSH hardening       | Key-only, no root, no password auth                               |
| Unattended upgrades | Automatic security patches                                        |

### Dockerized Services

**Camunda 8 stack:**

| Component     | Notes                                                                                     |
|---------------|-------------------------------------------------------------------------------------------|
| Zeebe         | Workflow engine                                                                           |
| Operate       | Workflow monitoring UI                                                                    |
| Tasklist      | User task UI                                                                              |
| Optimize      | Analytics                                                                                 |
| Identity      | IAM                                                                                       |
| WebModeler    | Browser-based BPMN modelling                                                              |
| Keycloak      | Identity provider for Camunda                                                             |
| Connectors    | Outbound connector runtime                                                                |
| Elasticsearch | Required by Camunda components; heap: 2GB; data: `/mnt/nvme/elasticsearch`                |
| PostgreSQL    | Camunda metadata; shared instance for future apps; daily `pg_dump` to `/mnt/nvme/backups` |

**Observability:**

| Service          | Purpose                            |
|------------------|------------------------------------|
| `node-exporter`  | Host metrics                       |
| `cAdvisor`       | Container metrics                  |
| Grafana Alloy    | Log shipping to Loki               |

### Resource Allocation (Guidance)

| Component       | Allocation                 |
|-----------------|----------------------------|
| OS + monitoring | ~2GB RAM reserved          |
| Elasticsearch   | 2GB heap                   |
| PostgreSQL      | 1GB `shared_buffers`       |
| Zeebe           | 2–3GB heap                 |
| Remaining       | Operate, Tasklist, workers |

### Deployment Notes

Use Docker Compose profiles to bring up databases before dependent services:

```bash
docker compose --profile databases up -d
# Wait for health checks, then:
docker compose --profile camunda up -d
```

---

## 🟦 `homelab-svc-02` — RPi 5 Model B *(Planned)*

**Storage:** USB SSD or NVMe recommended (for database and application data)

**Role:** User-facing application workloads.

**Network:**

| Property     | Value         |
|--------------|---------------|
| Local IP     | 192.168.1.21  |
| Tailscale IP | 100.x.x.4     |
| Public ports | None          |

Tailscale runs directly on this node — reachable over VPN even if `homelab-edge` is down.

### Dockerized Services

| Service         | Notes                                                     |
|-----------------|-----------------------------------------------------------|
| GreenTechHub    | Django / Gunicorn application server                      |
| PostgreSQL      | Separate instance from `svc-01`, or remote connection     |
| Redis           | Sessions, cache, Celery broker                            |
| Celery worker   | Async task processing                                     |
| Flower          | Celery monitoring (optional)                              |
| `node-exporter` | Host metrics                                              |
| `cAdvisor`      | Container metrics                                         |
| Grafana Alloy   | Log shipping to Loki                                      |

### Routing

- **Internal:** Pi-hole resolves `greentechhub.homelab.local` → `192.168.1.21`; access via `http://greentechhub.homelab.local:8000`
- **External:** Cloudflare Tunnel routes `yourdomain.com` → `svc-02:8000`

### Deployment

Configuration lives in `host_vars/homelab-svc-02.yml`; secrets in Ansible Vault.

```bash
ansible-playbook playbooks/deploy_svc.yml --tags greentechhub --vault-password-file .vault_pass
```

---

## 🟦 `homelab-svc-03` — *(Future)* Jellyfin / Media Node

**Hardware:** RPi 5, or x86 mini-PC for better transcoding performance

**Storage:** 4TB+ HDD or SSD for media

**Network:**

| Property     | Value         |
|--------------|---------------|
| Local IP     | 192.168.1.22  |
| Tailscale IP | 100.x.x.5     |
| Public ports | None          |

Tailscale runs directly on this node — reachable over VPN even if `homelab-edge` is down.

### Dockerized Services

| Service                    | Notes                                                                                          |
|----------------------------|------------------------------------------------------------------------------------------------|
| Jellyfin                   | Media server; hardware acceleration via V4L2 (RPi) or VAAPI/NVENC (x86); media at `/mnt/media` |
| Sonarr / Radarr / Prowlarr | Optional media management                                                                      |
| `node-exporter`            | Host metrics                                                                                   |
| Grafana Alloy              | Log shipping to Loki                                                                           |

### Routing

- **Internal:** Pi-hole resolves `jellyfin.homelab.local` → `192.168.1.22`; access via `http://jellyfin.homelab.local:8096`
- **External:** Cloudflare Tunnel routes `jellyfin.yourdomain.com` → `svc-03:8096`

### Future Enhancements

- Dedicated NAS node for media storage
- Off-site backup to Backblaze B2
