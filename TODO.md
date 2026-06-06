# Homelab TODO

Validation and remediation tasks identified by cross-referencing all documentation (README, BOOTSTRAP.md, NODES.md, docs/NETWORK.md) against the actual files in the repo.

---

## Design Decisions (blockers for downstream tasks)

- [x] **#1 — Resolve Phase 4 deployment architecture**
  **Decision: Option A — n8n/Camunda webhook. GitHub never connects to the homelab.**
  - Created `.github/workflows/deploy.yml` — POSTs to webhook with `X-Deploy-Secret` header; triggers on push to `master` and `workflow_dispatch`
  - GitHub secrets required: `DEPLOY_ENDPOINT_URL`, `DEPLOY_SECRET`
  - `deploy` user on edge SSHes from n8n/Camunda and runs `ansible-playbook` (sudo restricted to that binary only)
  - Updated `CLAUDE.md` to reflect correct Phase 4 flow
  - **Still needed:** delete/archive `deploy_homelab.sh` and `setup.sh` once Ansible roles replace their functions (tracked in #11)

- [x] **#2 — Resolve Portainer placement (observe vs svc-01)**
  **Decision: Portainer Server on `homelab-observe`, Portainer Agent on all other Docker hosts.**
  - `docker-compose.observe.yml` — added Portainer Server (ports 9000 HTTP, 9443 HTTPS)
  - `docker-compose.svc01.yml` — replaced Portainer Server with Portainer Agent (port 9001)
  - `docker-compose.edge.yml` — added Portainer Agent (port 9001)
  - `group_vars/observe.yml` — added port 9443 UFW rule
  - `group_vars/svc.yml` — added port 9001 UFW rule (from 192.168.1.11 only)
  - `group_vars/edge.yml` — added port 9001 UFW rule (from 192.168.1.11 only)
  - **Still needed:** add Portainer Agent to compose files for svc-02 and svc-03 when those nodes are provisioned

---

## Missing Ansible Infrastructure (biggest gap)

- [x] **#3 — Create `playbooks/` directory**
  All 9 playbooks created:
  - `playbooks/bootstrap_edge.yml` — Phase 1 from PC; sets hostname, users, Docker, Ansible, repo clone, SSH hardening, ufw
  - `playbooks/bootstrap_node.yml` — Phase 3 any new node; users, Docker, Tailscale, node-exporter
  - `playbooks/deploy_edge.yml` — Phase 2 edge self-deploy; hardening, firewall, fail2ban, Tailscale, edge_services role, Alloy
  - `playbooks/deploy_observe.yml` — Phase 3 monitoring stack; hardening, Tailscale, observe_services role, Alloy; health checks for Grafana + Prometheus
  - `playbooks/deploy_svc.yml` — Phase 3 service nodes; tagged camunda/greentechhub/jellyfin; when: conditions per hostname
  - `playbooks/update_all.yml` — serial=1 OS upgrades + docker image pulls; --tags restart to opt-in to container restarts
  - `playbooks/backup.yml` — pg_dump via docker exec for Camunda (svc-01) and GreenTechHub (svc-02); cleanup old backups
  - `playbooks/rollback.yml` — interactive pause + git checkout + compose up for target node + tag
  - `playbooks/healthcheck.yml` — container status, Tailscale, HTTP endpoints (Grafana, Prometheus, Camunda, etc.), DNS resolution, tunnel status

  All playbooks reference roles from Task #4 — will fail until roles are created.

- [x] **#4 — Create `roles/` directory structure**
  All roles referenced in README don't exist. Required:
  - `roles/base_hardening/` — SSH hardening, firewall, fail2ban, sysctl
  - `roles/docker/` — Docker install and daemon config
  - `roles/docker_compose/` — Docker Compose plugin
  - `roles/tailscale/` — Tailscale install and config
  - `roles/firewall/` — ufw rules
  - `roles/fail2ban/` — SSH + HTTP jails
  - `roles/node_exporter/` — Prometheus node exporter
  - `roles/cadvisor/` — Container metrics (svc nodes)
  - `roles/alloy/` — Grafana Alloy log shipper
  - `roles/edge_services/` — cloudflared, Pi-hole, Unbound
  - `roles/observe_services/` — Prometheus, Loki, Grafana, Alertmanager, Uptime Kuma
  - `roles/camunda/`
  - `roles/greentechhub/`
  - `roles/jellyfin/`

  Old partial roles in `old homelab/ansible/roles/` (base_hardening, docker, fail2ban, ssh_common, tailscale, ufw, users) for reference.

- [x] **#5 — Create Jinja2 templates for all roles**
  Templates live inside each role's `templates/` subdirectory (standard Ansible convention), not a top-level `templates/` dir:
  - `roles/alloy/templates/config.alloy.j2` — systemd journal scraping, optional Ansible log file, Loki remote write
  - `roles/edge_services/templates/cloudflared/config.yml.j2` — renders `cloudflared_ingress` from `group_vars/edge.yml`
  - `roles/edge_services/templates/pihole/custom.list.j2` — renders `pihole_custom_dns` list
  - `roles/observe_services/templates/prometheus/prometheus.yml.j2` — renders all `prometheus_scrape_targets` from `group_vars/observe.yml`
  - `roles/observe_services/templates/prometheus/alerts.yml.j2` — node/disk/container alert rules
  - `roles/observe_services/templates/alertmanager/alertmanager.yml.j2` — Discord receivers from `alertmanager_receivers`; replaces legacy `alertmanager/alertmanager.yml.tmpl`
  - `roles/observe_services/templates/loki/loki.yml.j2` — TSDB schema, retention from `loki_retention`
  - `roles/observe_services/templates/grafana/datasources.yml.j2` — renders `grafana_datasources` list
  - `roles/camunda/templates/elasticsearch/elasticsearch.yml.j2` — cluster name, single-node discovery
  - `roles/camunda/templates/postgres/postgresql.conf.j2` — memory tuning from `host_vars/homelab-svc-01.yml`

  Also added two template rendering tasks to `roles/camunda/tasks/main.yml` (elasticsearch.yml and postgresql.conf) that were missing from the role.

- [x] **#6 — Create `scripts/` directory**
  No `scripts/deploy.sh` needed — n8n/Camunda calls `ansible-playbook` directly via SSH as the `deploy` user. Created:
  - `scripts/backup_databases.sh` — thin wrapper around `playbooks/backup.yml`; supports `--node svc-01` to limit scope; logs to `logs/backup-<timestamp>.log`
  - `scripts/test_connectivity.sh` — checks LAN ping, Tailscale peers, SSH ports, all service HTTP endpoints, Pi-hole DNS resolution, and cloudflared container status; exits non-zero if any check fails

---

## Docker Compose Gaps

- [x] **#7 — Add Pi-hole + Unbound to `docker-compose.edge.yml`**
  Added pihole, unbound, and pihole-exporter services. Unbound gets fixed IP 172.20.0.2 on a dedicated
  `pihole_net` (172.20.0.0/29); Pi-hole is 172.20.0.3 and also joins `edge_net`. Pi-hole admin exposed
  on port 8080 (not 80 — Caddy owns that); UFW rule in `group_vars/edge.yml` updated to 8080 accordingly.
  pihole-exporter on port 9617 matches the existing Prometheus scrape target in `group_vars/observe.yml`.

- [x] **#8 — Add Loki to `docker-compose.observe.yml`**
  Added grafana/loki:latest on port 3100 (monitoring_net + LAN-accessible for Alloy agents). Config
  mounted from ./loki/loki.yml — rendered by the existing Ansible task in roles/observe_services/tasks/main.yml.
  loki_data volume added for persistence. Template already had correct retention (336h) and alertmanager ruler URL.

- [x] **#9 — Add Uptime Kuma to `docker-compose.observe.yml`**
  Added louislam/uptime-kuma:latest on port 3001 (monitoring_net), uptime_kuma_data volume for persistence.
  Added ntfy vars to group_vars/observe.yml (ntfy_port: 8085, ntfy_base_url, ntfy_config_path).

- [x] **#10 — Delete legacy `docker-compose.yml`**
  Deleted. Before removal, two fixes were made to the new split files:
  - `docker-compose.svc01.yml`: added missing `extra_hosts: host.docker.internal:host-gateway` to n8n (needed for n8n to call back to host services)
  - `docker-compose.observe.yml`: fixed alertmanager volume path bug (`/config/alertmanager/alertmanager.yml` → `/config/alertmanager.yml` to match the `--config.file` command arg)

- [x] **#11 — Archive or delete `deploy_homelab.sh` and `setup.sh`**
  Both scripts deleted. All functions replaced by Ansible roles (hardening, fail2ban, systemd, Docker).

---

## Data Inconsistencies

- [x] **#12 — Fix Camunda port (8080 vs 8088)**
  8088 is correct — confirmed by `docker-compose.svc01.yml` (maps 8088:8088) and old `camunda/.env`
  (CAMUNDA_ORCHESTRATION_PORT=8088). Fixed in `host_vars/homelab-svc-01.yml` (`camunda_port` and
  `ufw_rules_extra`) as part of task #23. cAdvisor stays on 8080 — no conflict.

- [x] **#13 — Fix repo path (`/opt/homelab` vs `/root/homelab`)**
  `group_vars/all.yml` sets `homelab_repo_path: /opt/homelab` (owned by `homelab` user — correct per BOOTSTRAP.md). `deploy_homelab.sh` hard-codes `/root/homelab` and runs as root. Fixed `deploy_homelab.sh`: all `/root/homelab` → `/opt/homelab`; also corrected SSH key path `/root/.ssh/github` → `/home/homelab/.ssh/github`.

- [N/A] **#14 — Generate missing `deploy` SSH key pair**
  Removed. SSH keys are generated on the operator's PC during Phase 1 (BOOTSTRAP.md § 1.4) and
  never stored in the repo — tracking this here would encourage committing key material.

- [x] **#15 — Remove `.env-github`**
  Old GitHub Actions direct-SSH credentials (CF Access client ID/secret, Discord bot token, old SERVER_PRIVATE_KEY
  path). Superseded by n8n webhook approach — GitHub never SSHes directly anymore. Vault keys migrated:
  vault_cloudflare_api_token, vault_shoutrrr_discord_alerts, vault_github_ssh_key_passphrase — all in vault.yml.example.
  File confirmed deleted (gitignored by `.env*` pattern; not present on disk).

---

## Documentation Alignment (do last)

- [x] **#16 — Align README repo structure with actual file layout**
  Replaced `compose/` dir with actual `docker-compose.*.yml` files at root. Replaced top-level `templates/`
  dir with inline comments listing key role templates. Removed `inventories/staging.ini`. Updated `scripts/`
  to list only the two scripts that exist. Fixed Phase 4 description to say `ansible-playbook` directly,
  not `scripts/deploy.sh`.

- [x] **#17 — Update BOOTSTRAP.md Phase 4 section**
  Removed §4.1 "Create the Deploy Script" entirely (no such script). Renumbered §4.2→4.1, §4.3→4.2, §4.4→4.3.
  Updated flow diagram to show `deploy user runs ansible-playbook directly`. Updated Options A & B to show
  actual `ansible-playbook` commands instead of `scripts/deploy.sh`. Updated manual trigger to show the
  full command sequence. GitHub secrets table was already correct.

- [x] **#18 — Clean up `.gitignore`**
  Done. `.gitignore` now contains only IaC-relevant entries: `.ssh/`, `.env*`, `.vault_pass`, `*.ppk`, `*.secret`,
  `inventories/group_vars/all/vault.yml`, `inventories/group_vars/all/overrides.yml`, `.idea/`, `.claudeignore`,
  `logs/`, `*.log`, `n8n-recovery-codes.txt`. All Python/Django/Scrapy/Celery boilerplate removed.

- [x] **#19 — Validate `inventories/group_vars/all/vault.yml.example` is complete**
  Audited all `vault_*` references across all branches against vault.yml.example. Changes made:
  - Added `vault_ntfy_token` (was missing; needed by notification scripts TODO #21)
  - Kept `vault_shoutrrr_discord_alerts` — shoutrrr on edge node is Discord fallback when
    homelab-observe is unreachable; scripts try ntfy first, fall back to shoutrrr
  - Removed `vault_github_ssh_key_passphrase` (no passphrase-protected key in current setup)
  - Added inline comments clarifying `vault_cloudflare_api_token` (future use, not yet wired)
    and `vault_deploy_webhook_secret` (used by n8n directly, not Ansible)
  - Added note that `vault_admin_become_password` is wired via `bootstrap.ini`
  Branch sync note: `wip/observe` and `wip/svc` still carry `vault_tailscale_auth_key` in their
  copies of `main.yml` and `vault.yml.example` (pre-#24). Resolve when rebasing those branches
  onto master after wip/edge merges.

---

## Old Homelab Migration (identified by audit)

- [x] **#20 — Migrate service configs from `old homelab/` to proper locations**
  - `discord-gateway/` (app.py, Dockerfile, data/webhook_map.json) — already present at repo root; application
    code stays here (compose does `build: ./discord-gateway`), not in roles.
  - `ntfy/config/server.yml` — converted to `roles/observe_services/templates/ntfy/server.yml.j2` (Jinja2
    template parameterised on `ntfy_base_url`; adds `behind-proxy: true`, `auth-default-access: deny-all`).
    Render task added to `roles/observe_services/tasks/main.yml` under [ntfy] tag.
    Ansible overwrites the static file on first deploy.

- [x] **#25 — Move base_hardening to an earlier, isolated stage**
  `base_hardening` is a groundbreaking change (SSH port, kernel params) — if it fails it should fail fast, before any service setup. Split `deploy_edge.yml` into two plays: Play 1 (hardening only) then Play 2 (firewall, fail2ban, Tailscale, services). If hardening fails, services never start and the failure point is unambiguous. Bootstrap playbooks are already structured correctly (base_hardening is first role).

- [x] **#26 — Separate SSH port change from firewall (flush handlers immediately)**
  Currently `base_hardening` changes `sshd_config` but defers the restart to the end of the play (via handler). UFW default-deny is applied first, leaving a window where sshd hasn't restarted on the new port. Fix: add `meta: flush_handlers` immediately after the SSH harden loop in the role, followed by a `wait_for` check that sshd is listening on the new port. If sshd fails to bind, the play stops before the firewall is touched.
  Also changed the `Restart ssh` handler to `state: restarted` (full restart required to rebind sockets on a new port; existing sessions survive in their child processes).

- [x] **#27 — Single source of truth for IP addresses (prod.ini → prod.yml)**
  `inventories/prod.ini` duplicated the IP addresses already defined in `group_vars/all/main.yml` and had to be kept in sync manually (INI format does not support Jinja2). Replaced with `inventories/prod.yml` (YAML inventory format). `ansible_host: "{{ ip_edge }}"` and `ansible_port: "{{ ssh_port }}"` resolve from group_vars at connection time — no manual sync. Updated all references across playbooks, scripts, and docs. `prod.ini` confirmed deleted.

- [x] **#24 — Automate Tailscale auth key renewal**
  Replaced static `vault_tailscale_auth_key` with OAuth client credentials that never expire.
  The tailscale role now mints a fresh auth key at deploy time via the Tailscale API — no static
  tskey-auth-* stored anywhere. Key is skipped entirely if the node is already connected.
  - `roles/tailscale/tasks/main.yml`: added status check → OAuth API call → `tailscale up` sequence;
    API call and `tailscale up` are skipped when `tailscale status` returns 0 (already connected)
  - `inventories/group_vars/all/main.yml`: removed `tailscale_auth_key` mapping (no longer needed)
  - `inventories/group_vars/all/vault.yml.example`: replaced `vault_tailscale_auth_key` with
    `vault_tailscale_oauth_client_id` + `vault_tailscale_oauth_client_secret`
  - OAuth client scope required: **Devices → Auth Keys (write)**
  - Minted keys: `reusable: true`, `preauthorized: true`, `expirySeconds: 0`

- [x] **#21 — Add notification scripts to `roles/base_hardening/`**
  All three scripts and systemd units implemented as Jinja2 templates; shoutrrr installed on every
  node as the Discord fallback when homelab-observe is unreachable.
  - `on-boot.sh` / `on-boot.service` — oneshot at boot (After=network-online.target)
  - `on-shutdown.sh` / `on-shutdown.service` — oneshot at shutdown (Before=shutdown.target)
  - `on-ssh-success.sh` / `on-ssh-success.service` — persistent daemon watching journalctl -fu ssh
  - shoutrrr (client binary) used for both channels — one tool, consistent interface:
    `shoutrrr → ntfy+http (self-hosted, primary) || shoutrrr → discord (fallback)`
  - ntfy URL constructed in main.yml: `ntfy+http://token@ip_observe:8085/homelab`
  - shoutrrr binary installed to `/usr/local/bin/shoutrrr` via `get_url` (ARM64/amd64 auto-detected)
  - Scripts deploy to `{{ notify_script_dir }}` (`/usr/local/lib/homelab/notify/`), mode 0700
  - New vars in `group_vars/all/main.yml`: `notify_script_dir`, `notify_ntfy_shoutrrr_url`,
    `notify_discord_shoutrrr_url`, `shoutrrr_version`
  - `Reload systemd` handler added to `roles/base_hardening/handlers/main.yml`

- [x] **#22 — Add fail2ban jail template to `roles/fail2ban/`**
  Created `roles/fail2ban/templates/jail.conf.j2` rendering port, logpath, backend, maxretry, bantime,
  findtime per jail. Replaced inline `ansible.builtin.copy` task with `ansible.builtin.template`.
  Updated `group_vars/edge.yml` jail definitions to include port/logpath/backend (sshd uses `ssh_port`,
  pihole uses http,https). Added `ssh_port: 2189` to `group_vars/all.yml` (shared by SSH hardening role).

- [x] **#23 — Extract `.env` values into `host_vars/` and `inventories/group_vars/all/vault.yml`**
  Split all svc-01 service env vars by sensitivity. Also resolves #12 (Camunda port).
  Non-secret vars → `host_vars/homelab-svc-01.yml`: n8n (host/port/protocol/flags), camunda (version,
  endpoints, domains), discord-gateway (n8n URL, webhook path, map file). Fixed camunda_port 8080→8088.
  Secrets → `inventories/group_vars/all/vault.yml.example`: vault_n8n_{user,password,owner_email,owner_password,encryption_key},
  vault_discord_public_key, vault_n8n_webhook_secret, vault_camunda_license_key.
  6 Jinja2 templates created in roles/camunda/templates/{camunda,n8n,discord_gateway}/{env,env.secrets}.j2.
  roles/camunda/tasks/main.yml updated: 2 inline copy tasks replaced with 6 template tasks (0644 for .env,
  0640 + no_log for .env.secrets). Ansible now fully owns all svc-01 env files.

---

## Repo Hygiene (identified 2026-06-06)

- [ ] **#28 — Commit the work backlog**
  Nearly all work from previous sessions is uncommitted. Untracked: `CLAUDE.md`, `TODO.md`,
  `inventories/group_vars/observe.yml`, `inventories/group_vars/svc.yml`, all five `host_vars/` files,
  `playbooks/backup.yml`, `playbooks/bootstrap_node.yml`, `playbooks/deploy_observe.yml`,
  `playbooks/deploy_svc.yml`, `playbooks/rollback.yml`, `roles/cadvisor/`, `roles/camunda/`,
  `roles/greentechhub/`, `roles/jellyfin/`, `roles/node_exporter/`, `roles/observe_services/`, `scripts/`.
  Also staged but not committed: `roles/docker_compose/tasks/main.yml`.
  A re-clone of the repo would lose everything above. Commit in logical chunks by concern.

- [ ] **#29 — Clean up orphaned git index entry**
  `ansible/bootstrap/edge-deploy.yml` shows as `AD` in `git status` — it was staged but then deleted from
  disk, at a path (`ansible/bootstrap/`) that doesn't exist in the current repo structure. Run:
  `git rm --cached ansible/bootstrap/edge-deploy.yml` to remove it from the index.

- [ ] **#30 — Create `docker-compose.svc02.yml` and `docker-compose.svc03.yml`**
  `homelab-svc-02` (GreenTechHub/Django/Redis/Celery) and `homelab-svc-03` (Jellyfin) have roles and
  `host_vars/` files but no compose files. Per #2, Portainer Agent also needs adding to both when provisioned.
  Mirror the structure of `docker-compose.svc01.yml`: named network, volumes, Portainer Agent on port 9001.

- [ ] **#31 — Add `defaults/main.yml` to roles missing it**
  Ansible best practice: every role declares its variables and defaults in `defaults/main.yml` (lowest
  precedence — safely overridden by group_vars/host_vars). The following have only `tasks/main.yml` and
  rely entirely on upstream vars with no self-documentation or safe fallbacks:
  `roles/firewall/`, `roles/users/`, `roles/edge_services/`, `roles/observe_services/`, `roles/camunda/`,
  `roles/greentechhub/`, `roles/jellyfin/`, `roles/node_exporter/`, `roles/cadvisor/`.

- [ ] **#32 — Document `roles/users/` and `roles/docker_compose/` in CLAUDE.md**
  Both roles exist in `roles/` but are absent from CLAUDE.md's role list under Task #4.
  `roles/users/` handles the three system users (admin, homelab, deploy) — distinct from `base_hardening`.
  `roles/docker_compose/` installs the Docker Compose plugin — distinct from `roles/docker/`.
  Add both to the role list and clarify their scope.

---

## Identity & Access (Authentik)

- [ ] **#33 — Add Authentik identity provider**
  Authentik provides SSO and forward-auth for all externally-exposed services. Design decisions and
  required changes across the stack:

  **Node placement:**
  - Authentik server + worker → `homelab-svc-01` (PostgreSQL already present; add Redis to svc-01 compose)
  - Authentik proxy outpost → `homelab-edge` (lightweight ~50MB; Caddy talks to it over the local Docker network)

  **Pi-hole — circular dependency mitigation:**
  Pi-hole is the LAN DNS server AND a service protected by Authentik. If Pi-hole is down, DNS for
  `auth.homelab.local` fails and all Authentik redirects break — locking users out of everything.
  Mitigation: apply a LAN bypass in Caddy so LAN clients never hit Authentik at all.
  - Add `auth.homelab.local → {{ ip_edge }}` to `pihole_custom_dns` in `group_vars/edge.yml`
  - Add `auth.yourdomain.com` to `cloudflared_ingress` in `group_vars/edge.yml` (external Authentik UI)

  **Caddy — LAN bypass pattern:**
  LAN clients are trusted; Authentik is only enforced for external (cloudflared) traffic.
  ```
  @lan remote_ip {{ lan_subnet }}
  handle @lan    { reverse_proxy ... }          # no auth
  handle         { forward_auth authentik-outpost:9000 {
                     uri /outpost.goauthentik.io/auth/caddy
                     copy_headers X-authentik-username X-authentik-groups X-authentik-email
                   }
                   reverse_proxy ... }
  ```
  Update `caddy_routes` data structure in `group_vars/edge.yml` to use `lan_bypass: true/false`
  per route (replaces a simple `auth: true/false` flag — all protected routes also bypass for LAN).

  **Files to create/update:**
  - `roles/authentik/` — new role (tasks + templates for Authentik config file)
  - `docker-compose.svc01.yml` — add `authentik-server`, `authentik-worker`, `redis`
  - `docker-compose.edge.yml` — add `authentik-outpost` container
  - `roles/edge_services/templates/caddy/Caddyfile.j2` — add LAN bypass + forward_auth blocks
  - `inventories/group_vars/edge.yml` — add `authentik_outpost_url`; update `caddy_routes` structure;
    add `auth.homelab.local` to `pihole_custom_dns`; add Authentik ingress to `cloudflared_ingress`
  - `inventories/group_vars/all/vault.yml` + `vault.yml.example` — add:
    `vault_authentik_secret_key`, `vault_authentik_postgres_password`
  - `CLAUDE.md` — update `homelab-svc-01` row to include Authentik; add `roles/authentik/` to role list
  - `BOOTSTRAP.md` — Phase 3 will need an Authentik deploy step once the role exists

  **Access model summary:**

  | Client   | Route                  | Auth enforced?              |
  |----------|------------------------|-----------------------------|
  | LAN      | `*.homelab.local`      | No — LAN subnet trusted     |
  | External | `*.yourdomain.com`     | Yes — Authentik forward-auth|
  | Pi-hole  | LAN only (UFW blocks)  | No — never externally exposed|