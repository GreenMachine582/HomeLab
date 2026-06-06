# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

Infrastructure-as-code for a 4-node Raspberry Pi homelab. Everything is deployed via Ansible from `homelab-edge`, which acts as both the internet edge and the Ansible control node. No manual configuration after Phase 1 bootstrap.

## Architecture

### Node Roles

Node IPs are defined in `inventories/group_vars/all/overrides.yml` (gitignored — never committed). `main.yml` holds `EDIT_BEFORE_USE` placeholders; `overrides.yml` overrides them with real values and is automatically copied to the edge node during Phase 1. `inventories/prod.yml` uses YAML inventory format and references IPs via Jinja2 (`ansible_host: "{{ ip_edge }}"`, `ansible_port: "{{ ssh_port }}"`) — update IPs in `overrides.yml` only.

| Node              | IP var        | Role                                                                                    |
|-------------------|---------------|-----------------------------------------------------------------------------------------|
| `homelab-edge`    | `ip_edge`     | Internet edge, DNS (Pi-hole), reverse proxy (Caddy, LAN only), Cloudflare Tunnel, Ansible control |
| `homelab-observe` | `ip_observe`  | Prometheus, Loki, Grafana, Alertmanager, ntfy, discord-gateway, Uptime Kuma, Portainer |
| `homelab-svc-01`  | `ip_svc_01`   | Camunda 8, Elasticsearch, n8n, PostgreSQL, 2TB NVMe                                    |
| `homelab-svc-02`  | `ip_svc_02`   | GreenTechHub (Django), Redis, Celery (planned)                                          |
| `homelab-svc-03`  | `ip_svc_03`   | Jellyfin media server (future)                                                          |

### Deployment Phases

1. **Phase 1** — PC → `homelab-edge` via `inventories/bootstrap.ini` (one-time, uses `admin` user)
2. **Phase 2** — `homelab-edge` deploys itself via `inventories/prod.yml`
3. **Phase 3** — `homelab-edge` deploys all other nodes
4. **Phase 4** — GitHub Actions → POST to n8n/Camunda webhook → n8n SSHes to edge as `deploy` user → runs `ansible-playbook`. GitHub never connects directly to the homelab.

### Docker Compose Split

Services are split across four compose files by concern:

- `docker-compose.edge.yml` — cloudflared, Caddy, Pi-hole, Unbound, node-exporter, pihole-exporter, portainer-agent (runs on `homelab-edge`)
- `docker-compose.svc01.yml` — Camunda, Elasticsearch, n8n, discord-gateway, Portainer Agent (runs on `homelab-svc-01`)
- `docker-compose.observe.yml` — Prometheus, Loki, Grafana, Alertmanager, ntfy, Portainer Server (runs on `homelab-observe`)

### Ansible Structure

- `inventories/bootstrap.ini` — Phase 1 only; connects as `admin`
- `inventories/prod.yml` — Phase 2+; connects as `homelab` (passwordless sudo); YAML format supports Jinja2 so `ansible_host`/`ansible_port` resolve from `group_vars/all/main.yml`
- `inventories/group_vars/all/main.yml` — applied to all nodes (users, SSH, Docker config, observability agents); IPs are `EDIT_BEFORE_USE` placeholders
- `inventories/group_vars/all/overrides.yml` — gitignored; holds real IPs/subnet overriding `main.yml` placeholders (copy from `overrides.yml.example`)
- `inventories/group_vars/all/vault.yml` — Ansible Vault encrypted; never committed in plaintext (auto-loaded alongside `main.yml`)
- `inventories/group_vars/edge.yml`, `observe.yml`, `svc.yml` — group-specific vars
- `inventories/host_vars/<node>.yml` — per-node overrides

### Three System Users

- `admin` — manual SSH access, passworded sudo
- `homelab` — Ansible automation, passwordless sudo, in `docker` group
- `deploy` — webhook/CI triggered deploys, restricted sudo to `/usr/bin/ansible-playbook` only

### Secrets

All secrets live in `inventories/group_vars/all/vault.yml` (Ansible Vault). The vault password file is `.vault_pass` (gitignored). Reference secrets in playbooks/vars as `{{ vault_* }}`.

## Key Commands

### Ansible (run from `homelab-edge` at `/opt/homelab` as `homelab` user)

`ansible.cfg` sets the default inventory (`prod.yml`) and vault password file — no `-i` or `--vault-password-file` flags needed for Phase 2+ commands.

```bash
# Test connectivity (Phase 1 bootstrap inventory — from PC, uses admin user)
ansible -i inventories/bootstrap.ini edge_bootstrap -m ping

# Phase 1: Bootstrap the edge node from your PC
ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge.yml

# Phase 2: Deploy edge services (run on edge as homelab user)
ansible-playbook playbooks/deploy_edge.yml --limit homelab-edge

# Phase 3: Bootstrap and deploy other nodes
ansible-playbook playbooks/bootstrap_node.yml --limit homelab-observe --ask-pass --ask-become-pass
ansible-playbook playbooks/deploy_observe.yml
ansible-playbook playbooks/deploy_svc.yml --tags camunda

# Update firewall rules (after adding services or once ip_observe is set)
ansible-playbook playbooks/apply_firewall.yml --limit homelab-edge

# OS package upgrades + Docker image pulls across all nodes
ansible-playbook playbooks/update_all.yml

# Pull and restart containers (opt-in)
ansible-playbook playbooks/update_all.yml --tags docker,restart

# Health check all services
ansible-playbook playbooks/healthcheck.yml

# Vault operations
ansible-vault edit inventories/group_vars/all/vault.yml
ansible-vault view inventories/group_vars/all/vault.yml
```

### Docker Compose

```bash
# Start a specific stack
docker compose -f docker-compose.edge.yml up -d
docker compose -f docker-compose.observe.yml up -d

# Pull and recreate without killing the tunnel
docker compose pull && docker compose up -d --remove-orphans
```

## Configuration Patterns

### Template Files

Config files are rendered by Ansible roles from Jinja2 templates. Templates live inside the role that uses them at `roles/<role>/templates/` — not a top-level `templates/` directory. Do not edit rendered outputs directly; they will be overwritten on the next deploy.

Key templates and their data sources:
- `roles/alloy/templates/config.alloy.j2` ← `inventories/group_vars/all.yml` (`alloy_loki_endpoint`, `alloy_scrape_systemd_units`)
- `roles/edge_services/templates/caddy/Caddyfile.j2` ← `inventories/group_vars/edge.yml` (`caddy_routes`)
- `roles/edge_services/templates/cloudflared/config.yml.j2` ← `inventories/group_vars/edge.yml` (`cloudflared_ingress`)
- `roles/edge_services/templates/pihole/custom.list.j2` ← `inventories/group_vars/edge.yml` (`pihole_custom_dns`)
- `roles/observe_services/templates/prometheus/prometheus.yml.j2` ← `inventories/group_vars/observe.yml` (`prometheus_scrape_targets`)
- `roles/observe_services/templates/alertmanager/alertmanager.yml.j2` ← `inventories/group_vars/observe.yml` (`alertmanager_receivers`, `alertmanager_routes`)
- `roles/observe_services/templates/loki/loki.yml.j2` ← `inventories/group_vars/observe.yml` (`loki_retention`)
- `roles/camunda/templates/elasticsearch/elasticsearch.yml.j2` ← `inventories/host_vars/homelab-svc-01.yml`
- `roles/camunda/templates/postgres/postgresql.conf.j2` ← `inventories/host_vars/homelab-svc-01.yml`

> Legacy `envsubst` templates (`alertmanager/alertmanager.yml.tmpl`, `fail2ban/fail2ban.conf.tmpl`) and shell scripts (`deploy_homelab.sh`, `setup.sh`) are from the old approach and will be removed once Ansible roles are complete.

### Adding a New Node

1. Add `ip_svc_0x` to `inventories/group_vars/all/overrides.yml` (the gitignored file with real IPs) — `main.yml` keeps its `EDIT_BEFORE_USE` placeholder
2. Uncomment (or add) the host entry in `inventories/prod.yml` with `ansible_host: "{{ ip_svc_0x }}"` — no manual IP sync needed
3. Create `inventories/host_vars/<hostname>.yml` with node-specific overrides
4. Uncomment/add to relevant `inventories/group_vars/` file if needed
5. Add Prometheus scrape target in `inventories/group_vars/observe.yml` (`prometheus_scrape_targets`)

### CI/CD (GitHub Actions)

`.github/workflows/deploy.yml` triggers on push to `master` (and `workflow_dispatch`). It POSTs to an n8n or Camunda webhook endpoint — GitHub never connects directly to the homelab.

Required GitHub secrets (`Settings → Secrets and variables → Actions`):

| Secret | Value |
|---|---|
| `DEPLOY_ENDPOINT_URL` | n8n webhook URL or Camunda REST endpoint |
| `DEPLOY_SECRET` | Shared secret; validated by n8n/Camunda before executing |

**Flow:** GitHub POST → n8n/Camunda validates `X-Deploy-Secret` header → SSHes to `homelab-edge` as `deploy` user → runs `ansible-playbook` against `inventories/prod.yml`.

The `deploy` user has sudo restricted to `/usr/bin/ansible-playbook` only. No shell scripts, no root access, no homelab credentials stored in GitHub.

## Important Constraints

- **Never use `docker compose down`** in the deploy script — it would kill `cloudflared` and drop the SSH tunnel mid-session. Use `docker compose up -d --remove-orphans` instead.
- **`old homelab/`** is an archived copy of the previous repo structure — do not edit files there.
- `inventories/group_vars/all/vault.yml` and `overrides.yml` are gitignored — never committed. Both must exist on the edge node at `/opt/homelab/inventories/group_vars/all/` for Phase 2+ to work. `bootstrap_edge.yml` copies them automatically from the PC during Phase 1.
- SSH port is non-standard, controlled by `ssh_port` in `inventories/group_vars/all/overrides.yml`. Applied to `sshd_config`, UFW rules, and fail2ban jails — change it in one place.
- **Firewall rules are not applied by `deploy_edge.yml`** — they are set during Phase 1 and persist. To update UFW rules (e.g. after provisioning a new node or adding a service) run `playbooks/apply_firewall.yml`.
