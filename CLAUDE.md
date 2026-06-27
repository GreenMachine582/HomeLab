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

- `docker-compose.edge.yml` — cloudflared, Caddy, Pi-hole, Unbound, node-exporter, pihole-exporter, portainer-agent, Infisical (+ Postgres, Redis), Semaphore (+ Postgres) (runs on `homelab-edge`)
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

### Roles

| Role | Scope | Runs on |
|---|---|---|
| `base_hardening` | SSH hardening, sysctl, kernel params, boot/SSH notifications | all nodes |
| `users` | Creates the three system users (admin, homelab, deploy) with SSH keys and sudo rules | all nodes |
| `docker` | Docker Engine install and daemon config (`/etc/docker/daemon.json`) | all nodes |
| `docker_compose` | Docker Compose plugin install (separate from Docker Engine) | all nodes |
| `firewall` | UFW rules from `ufw_rules` + `ufw_rules_extra` in group/host vars | all nodes |
| `fail2ban` | SSH + HTTP jails rendered from `group_vars/edge.yml` jail definitions | edge |
| `tailscale` | Tailscale install; mints auth key via OAuth client at deploy time | all nodes |
| `alloy` | Grafana Alloy log shipper (systemd journal → Loki) | all nodes |
| `node_exporter` | Prometheus node exporter (port 9100) | all nodes |
| `cadvisor` | Container metrics exporter (port 8080) | svc nodes |
| `unbound` | Unbound recursive resolver as host systemd service (port 5335); Pi-hole upstream | edge |
| `edge_services` | cloudflared, Caddy, Pi-hole config templates | edge |
| `infisical` | Self-hosted secrets manager — node-generated `.env`, container bring-up, additive seed from `vault.yml`, runtime lookup helper (`tasks/lookup.yml`) used by `deploy_edge.yml` (Tailscale-only) | edge |
| `semaphore` | Web UI over this repo's playbooks — read-only repo bind mount + writable workspace volume (Tailscale-only) | edge |
| `observe_services` | Prometheus, Loki, Grafana, Alertmanager, ntfy, Uptime Kuma | observe |
| `camunda` | Camunda 8, Elasticsearch, n8n, discord-gateway (env templates) | svc-01 |
| `greentechhub` | GreenTechHub Django app, Redis, Celery | svc-02 |
| `jellyfin` | Jellyfin media server | svc-03 |

### Three System Users

- `admin` — manual SSH access, passworded sudo
- `homelab` — Ansible automation, passwordless sudo, in `docker` group
- `deploy` — webhook/CI triggered deploys, restricted sudo to `/usr/bin/ansible-playbook` only

### Secrets

`inventories/group_vars/all/vault.yml` (Ansible Vault) lives **only on the WSL/PC control host** — it is never copied to any node, not even `homelab-edge` (see "Important Constraints"). The vault password file is `.vault_pass` (gitignored, also WSL-only). It still backs Phase 1 bootstrap (`bootstrap_edge.yml`, run from WSL — a single pass, see below) and every Stage 3+ playbook (`deploy_observe.yml`, `deploy_svc.yml`, `healthcheck.yml`, `update_all.yml`, `backup.yml`, `rollback.yml`, `apply_firewall.yml`), which still read `{{ vault_* }}` directly — converting these is **deferred**, see `docs/TROUBLESHOOTING.md` "Vault → Infisical conversion status".

`deploy_edge.yml` (Phase 2 — runs on `homelab-edge` itself, which never receives `vault.yml`) is the first **converted** playbook: it resolves its application secrets (`cloudflare/TUNNEL_TOKEN`, `pihole/WEB_PASSWORD`) at runtime from Infisical via `roles/infisical/tasks/lookup.yml`, authenticating with a node-local, read-only Universal Auth identity. That identity is created via Infisical's REST API during Phase 1 bootstrap, and its credentials are written *directly* — the moment they're minted — to `/home/homelab/.infisical_runtime_auth.yml` (`roles/infisical/tasks/bootstrap_instance.yml`); they never exist as `vault_*` values and never round-trip through `vault.yml` at all. This is the reference implementation for the rest of the `secret_backend: infisical | vault` helper abstraction, which remains **deferred** for Stage 3+ roles.

Infisical (self-hosted, edge-only, Tailscale-only — see [docs/NETWORK.md](./docs/NETWORK.md#tailscale-only-service-access-infisical--semaphore)) is the long-term canonical store for *application* secrets. Phase 1 bootstrap seeds it additively (create-if-absent, never overwrite/rotate/delete) from the `[seed → /production/<folder>/<KEY>]` entries in `vault.yml` — see the "Secret naming convention" block at the top of `inventories/group_vars/all/vault.yml.example` and `roles/infisical/tasks/bootstrap_instance.yml` (which now owns the seed inline — see "Important Constraints" for why it folded in there rather than staying a separate, separately-authenticated step). `vault.yml` remains both the WSL-side source Ansible reads from for unconverted roles *and* the seed/fallback source for Infisical.

Semaphore (web UI over this repo's playbooks, edge-only, Tailscale-only) reads secrets for its own Ansible runs from Infisical via the same **read-only** Universal Auth "runtime" machine identity `deploy_edge.yml` uses — loaded straight from the same node-local `/home/homelab/.infisical_runtime_auth.yml` file (`roles/semaphore/tasks/main.yml`, via `include_vars`), never from `vault.yml`. There is **no separate write-capable "bootstrap" identity** at all: Phase 1 bootstrap provisions the org, admin account, project, environment, folders, and this one read-only identity — and seeds every application secret — entirely via Infisical's `POST /v1/admin/bootstrap` "Programmatic Provisioning" API and the instance-admin token that one-shot call hands back (`roles/infisical/tasks/bootstrap_instance.yml`). See that task's header for the full "why a persisted write-capable identity would be pure ceremony with a needlessly larger blast radius" rationale — and `BOOTSTRAP.md` § Phase 1 for the (now genuinely zero-manual-step, single-pass) runbook.

## Key Commands

### Ansible (run from `homelab-edge` at `/opt/homelab` as `homelab` user)

`ansible.cfg` sets the default inventory (`prod.yml`) — no `-i` flag needed for Phase 2+ commands. It deliberately does **not** set `vault_password_file`: that file is cloned to every node, but `.vault_pass`/`vault.yml` never leave the WSL/PC control host (see "Secrets" below), and Ansible aborts at startup if a *configured* vault password file is missing — even for playbooks needing no vault content. On the WSL/PC side, set `ANSIBLE_VAULT_PASSWORD_FILE` in your shell profile instead (see `BOOTSTRAP.md` § 1.9) — no `--vault-password-file` flag needed there either, and nodes simply run with no vault password configured, which is what they need.

```bash
# Test connectivity (Phase 1 bootstrap inventory — from PC, uses admin user)
ansible -i inventories/bootstrap.ini edge_bootstrap -m ping

# Phase 1: Bootstrap the edge node from your PC — one pass, zero manual steps.
# Base system, Infisical (fully provisioned AND seeded via its REST API — org,
# admin, project, environment, folders, read-only runtime identity, every
# application secret), firewall, and Semaphore all come up in this single run.
# Nothing is printed for you to copy anywhere — see BOOTSTRAP.md § Phase 1.
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

# Vault operations — run from WSL/PC, NOT the edge: vault.yml and .vault_pass
# live there ONLY (never copied to any node — see "Secrets" below)
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
- `roles/infisical/templates/env.j2` ← node-generated secrets (idempotent: read back from `/opt/infisical/.env` if present, else `openssl rand -hex 32`) + `vault_infisical_encryption_key`
- `roles/semaphore/templates/env.j2` ← node-generated Postgres password + `vault_semaphore_admin_*` + the read-only Infisical "runtime" identity's credentials, loaded via `include_vars` from the same node-local `/home/homelab/.infisical_runtime_auth.yml` file `deploy_edge.yml` reads (never `vault.yml` — see "Secrets")

> Legacy `envsubst` templates (`alertmanager/alertmanager.yml.tmpl`, `fail2ban/fail2ban.conf.tmpl`) are from the old approach — do not edit them; they will be removed once all Ansible roles are complete.

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
- `inventories/group_vars/all/vault.yml` and `overrides.yml` are gitignored — never committed. **Only `overrides.yml` is copied** to the edge node (by `bootstrap_edge.yml`, into `/opt/homelab/inventories/group_vars/all/`); `vault.yml` and `.vault_pass` deliberately never leave the WSL/PC control host — see "Secrets" above and `semaphore_infisical_implementation.md` Task 2. Phase 2 (`deploy_edge.yml`) instead resolves its application secrets from Infisical at runtime via `roles/infisical/tasks/lookup.yml`.
- SSH port is non-standard, controlled by `ssh_port` in `inventories/group_vars/all/overrides.yml`. Applied to `sshd_config`, UFW rules, and fail2ban jails — change it in one place. The `base_hardening` role probes the target port before touching `sshd_config`, so re-runs are idempotent (port directive is skipped if sshd already answers on `ssh_port`). For a port migration: set `ssh_old_port` to the previous port so UFW keeps it open alongside the new one; once the new port is confirmed, set `ssh_old_port_cleanup: true` to remove the old UFW rule.
- **Firewall rules are not applied by `deploy_edge.yml`** — they are set during Phase 1 and persist. To update UFW rules (e.g. after provisioning a new node or adding a service) run `playbooks/apply_firewall.yml`.
- **Infisical and Semaphore are deliberately Tailscale-only** — no Pi-hole hostname, no Caddy vhost; UFW scopes ports 8222/3010 to `tailscale_cgnat_range` (`100.64.0.0/10`, `inventories/group_vars/all/main.yml`). Do not add LAN-reachable routes for either — they hold/wield every secret and this repo's playbooks respectively.
- **Phase 1 bootstrap (`bootstrap_edge.yml`) is a single pass — there is no Part 2, and no manual checkpoint of any kind inside it.** An earlier design seeded Infisical and brought up Semaphore in a separate `bootstrap_edge_part2.yml`, gated on a write-capable "bootstrap" machine identity whose freshly-minted credentials had to be printed by Part 1, copied into `vault.yml` by hand, and re-encrypted before Part 2 could run (because Ansible can't safely write to the encrypted vault file itself). That whole mechanism is gone: the one-shot `POST /v1/admin/bootstrap` call's own instance-admin token already has full write access, so `roles/infisical/tasks/bootstrap_instance.yml` uses *that* token to provision **and seed** everything immediately, in the same play — no separate identity is ever created, persisted, printed, copied, or revoked. Only the read-only "runtime" identity gets created, and its credentials are written straight to a node-local file (`/home/homelab/.infisical_runtime_auth.yml`) the moment they're minted — never anywhere near `vault.yml`. Don't "fix" this by re-introducing a split, a printed-credential step, or a persisted write-capable identity — that would be reintroducing the exact ceremony this design eliminated. See `roles/infisical/tasks/bootstrap_instance.yml`'s header for the full rationale.
