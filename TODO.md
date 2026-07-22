# Homelab TODO

Open tasks only. Completed tasks are tracked via git history — this file holds only pending work.

Node roles, ports, and playbook commands are in [CLAUDE.md](./CLAUDE.md), [NODES.md](./NODES.md), and [docs/NETWORK.md](./docs/NETWORK.md). Polyrepo migration design is in [docs/repo_split_brief.md](./docs/repo_split_brief.md).

---

## Phase 3 — Bootstrap Remaining Nodes

### Milestone A — `homelab-observe`

Branch `wip/observe` contains the role and playbook. No merge conflicts with master expected (entirely new files).

- [x] **A1** — Merge `wip/observe` into master
- [ ] **A2** — Run Phase 3 bootstrap:
  ```bash
  ansible-playbook playbooks/bootstrap_node.yml --limit homelab-observe --ask-pass --ask-become-pass
  ```
- [ ] **A3** — Deploy the observability stack:
  ```bash
  /opt/deploy-service-venv/bin/deploy-service deploy homelab-observe-services --config /opt/homelab/services.yml
  ```
- [ ] **A4** — Verify services are live (from a LAN client or Tailscale):
  - Grafana: `http://ip_observe:3000`
  - Prometheus: `http://ip_observe:9090`
  - Loki (push endpoint): `http://ip_observe:3100`
  - Alertmanager: `http://ip_observe:9093`
  - ntfy: `http://ip_observe:8085`
  - Uptime Kuma: `http://ip_observe:3001`
  - Portainer: `http://ip_observe:9000`

---

### Milestone B — `homelab-svc-01`

Branch `wip/svc` contains the roles and playbook. One conflict on merge: `TODO.md` changed in both branches — resolve by keeping the master version.

- [ ] **B1** — Merge `wip/svc` into master (manually resolve `TODO.md` conflict — keep master version)
- [ ] **B2** — Create `docker-compose.svc02.yml` and `docker-compose.svc03.yml`
  Mirror `docker-compose.svc01.yml` structure: named network, named volumes, Portainer Agent on port 9001.
  - `svc02`: GreenTechHub (Django), PostgreSQL, Redis, Celery worker
  - `svc03`: Jellyfin, optional Sonarr/Radarr/Prowlarr
- [ ] **B3** — Run Phase 3 bootstrap:
  ```bash
  ansible-playbook playbooks/bootstrap_node.yml --limit homelab-svc-01 --ask-pass --ask-become-pass
  ```
- [ ] **B4** — Deploy the Camunda + n8n stacks (now via `deploy-service`, not Ansible — see Milestone D):
  ```bash
  /opt/deploy-service-venv/bin/deploy-service deploy camunda-platform --config /opt/homelab/services.yml
  /opt/deploy-service-venv/bin/deploy-service deploy n8n-automation --config /opt/homelab/services.yml
  ```
  Then deploy the remaining Ansible-managed leftovers (discord-gateway + portainer-agent):
  ```bash
  ansible-playbook playbooks/deploy_svc.yml --limit homelab-svc-01 --tags discord_gateway
  ```
- [ ] **B5** — Verify: Camunda (:8088), Elasticsearch (:9200), n8n (:5678)
- [ ] **B6** — Review discord-gateway (keep or remove):
  - **Keep**: if Discord slash-command automation (`/deploy`, `/status`) is wanted
  - **Remove**: drop from `docker-compose.svc01.yml`, delete `roles/discord_gateway/`, remove `vault_discord_public_key` and `vault_n8n_webhook_secret` from `vault.yml.example`
  - See context in git log for prior discussion
- [ ] **B7** — Once `camunda-platform` is live (post-D1 deploy-verify), bootstrap-lock signaling is ready to implement — design fully resolved (auth, BPMN mechanism, stale-lock timeout) in [docs/repo_split_brief.md](./docs/repo_split_brief.md) §9. Both halves (`bootstrap_node.yml` pre_tasks/post_tasks, and the Camunda BPMN dual-correlation gate) land together, not separately.

---

## Phase 4 — Polyrepo Migration

See [docs/repo_split_brief.md](./docs/repo_split_brief.md) for full design rationale, `services.yml` schema, and `deploy-service` CLI spec.

**Current status:** `homelab-edge-services` is live (Phase 4 complete for edge). `homelab-observe-services` repo is created, tagged `v0.1.0`, with compose/configs extracted, docs migrated, and registered in `services.yml` (Milestone C1–C4 done). `deploy-service` now actually executes `pre_hook`/`post_hook`. Remaining: C5 (deploy-verify — blocked on Phase 3 Milestone A being live, no real node yet), C6 (retire from HomeLab repo). svc-01 splits: `camunda-platform` and `n8n-automation` extracted and registered in `services.yml` (D1/D2 done, deploy-verify blocked on Milestone B); `discord-gateway` (D3) still open, gated on the B6 keep/remove decision.

---

## Bootstrap Playbook Review

`bootstrap_edge.yml` and `bootstrap_node.yml` share a large common base but have drifted in role order, firewall approach, and observability setup. Resolve before bootstrapping real nodes (Milestones A and B) so any fixes land in both playbooks at the same time.

### ~~Milestone F — Align bootstrap_edge.yml and bootstrap_node.yml~~ ✅

All resolved and committed to master:

- **F1** ✅ — Role order corrected in `bootstrap_node.yml`: `users → base_hardening → docker → docker_compose → tailscale`
- **F2** ✅ — `roles/docker_compose` added to both bootstrap playbooks (`roles/docker` installs Engine only; plugin is separate)
- **F3** ✅ — Node-exporter inline task added to `bootstrap_edge.yml`; edge now observable from Phase 1 completion
- **F4** ✅ — Replaced inline `community.general.ufw` tasks in `bootstrap_node.yml` with `include_role: firewall`
- **F5** ✅ — Alloy stays in deploy playbooks (Option A); alloy deferral comment added to both bootstrap playbooks
- **F6** — Deferred (no functional benefit until a third bootstrap type is added)

---

### Milestone C — `homelab-observe-services`

> **Prep** (can start before Phase 3 completes):

- [x] **C1** — Create GitHub repo `GreenMachine582/homelab-observe-services`
  - **Description:** `Observability stack for homelab-observe — Prometheus, Loki, Grafana, Alertmanager, ntfy, Uptime Kuma`
  - **Topics:** `homelab`, `self-hosted`, `prometheus`, `grafana`, `loki`, `docker-compose`
  - **Default branch:** `master`
  - **Visibility:** private (contains service configs with volume paths and hostnames)
  - **After first commit, tag:** `v0.1.0` ✅ tagged

> **Migration** (after Phase 3 is live and stable):

- [x] **C2** — Extract compose + config files into new repo:
  - `docker-compose.observe.yml` → `docker-compose.yml`
  - `roles/observe_services/templates/` → `configs/` (rendered to plain files, no Jinja2)
  - Add `.env.example` listing any Infisical-sourced secrets
- [x] **C3** — Move `docs/MONITORING.md` to the new repo; add link from HomeLab `README.md`
- [x] **C4** — Add `observe` entry to `services.yml` (done — includes `pre_hook: [scripts/predeploy.sh]` and the full Infisical secrets list: network IPs, Grafana admin password, Discord webhooks)
  > **Hook gap resolved:** `deploy-service` previously declared but never executed `pre_hook`/`post_hook` from `services.yml`. Implemented in `deploy-service/deploy_service/compose.py` (`run_hooks()`, invoked via `bash <script>` so the executable bit doesn't matter) and wired into `cli.py`'s deploy sequence: clone/pull → `pre_hook` → compose deploy → `post_hook`. `clone_or_pull()` now also does `git reset --hard` before every pull, since hooks like `homelab-observe-services`'s `scripts/predeploy.sh` (envsubst) mutate tracked config files in place. This also fixes `homelab-edge-services`'s previously silently-skipped `post_hook` (pihole password).
- [ ] **C5** — Deploy via `deploy-service` and verify end-to-end:
  ```bash
  deploy-service deploy homelab-observe-services
  ```
  > `deploy-service` was extended with remote (SSH) execution and GitHub PAT auth
  > for private repos to make this possible, but the run has not yet been verified
  > against the real `homelab-observe` node — still open.
- [x] **C6** — Retire from HomeLab repo: remove `roles/observe_services/`, `docker-compose.observe.yml`, `playbooks/deploy_observe.yml`; update `CLAUDE.md` role table and `NODES.md`
  > Done ahead of C5 verification per explicit instruction (to reduce having two
  > parallel deploy paths). If C5 verification surfaces a problem with
  > `deploy-service`, the removed files are recoverable from git history.

---

### Milestone D — svc-01 splits

Three repos; tackle in order (each depends on the prior being stable). For each, the pattern is: create repo → extract → register in `services.yml` → verify → retire from HomeLab repo.

#### D1 — `camunda-platform` ✅ (extracted, verification blocked on hardware)

- [x] Create `GreenMachine582/camunda-platform`
  - **Description:** `Camunda 8 + Elasticsearch workflow engine on homelab-svc-01`
  - **Topics:** `homelab`, `camunda`, `bpmn`, `elasticsearch`, `docker-compose`, `self-hosted`
  - **Default branch:** `master`
- [x] Extract Camunda + Elasticsearch into a standalone, env-driven `docker-compose.yml`; `roles/camunda/` deleted. (Postgres was briefly included as a shared instance, then dropped — repo owner is adding it to a different repo instead to keep this one simpler.)
- [x] Add to `services.yml` (type: compose, target_node: homelab-svc-01, `pre_hook: scripts/predeploy.sh`)
- [ ] Verify via `deploy-service deploy camunda-platform` — blocked on Milestone B (svc-01 not bootstrapped yet)
- [x] Retire: removed Camunda/ES sections from `docker-compose.svc01.yml` and all of `roles/camunda/`

#### D2 — `n8n-automation` ✅ (extracted, verification blocked on hardware)

- [x] Create `GreenMachine582/n8n-automation`
  - **Description:** `n8n workflow automation on homelab-svc-01`
  - **Topics:** `homelab`, `n8n`, `automation`, `workflows`, `docker-compose`, `self-hosted`
  - **Default branch:** `master`
- [x] Extract n8n into a standalone, env-driven `docker-compose.yml`
- [x] Add to `services.yml` (type: compose, target_node: homelab-svc-01)
- [ ] Verify via `deploy-service deploy n8n-automation` — blocked on Milestone B (svc-01 not bootstrapped yet)
- [x] Retire: removed n8n section from `docker-compose.svc01.yml`; n8n's env-rendering tasks in `roles/camunda/templates/n8n/` deleted along with the rest of that role

#### D3 — `discord-gateway` *(only if kept after B6)*

- [ ] Create `GreenMachine582/discord-gateway`
  - **Description:** `Inbound Discord slash-command gateway, routing to n8n on homelab-svc-01`
  - **Topics:** `homelab`, `discord`, `webhook`, `docker-compose`, `self-hosted`
  - **Default branch:** `master` | **Initial image tag:** `v0.1.0` (pushed to `ghcr.io/greenmachine582/discord-gateway`)
  - **CI:** GitHub Actions — build + push image to `ghcr.io` on tag push
- [ ] Extract `discord-gateway/` directory from HomeLab repo root
- [ ] Add to `services.yml` as type: image:
  ```yaml
  discord-gateway:
    repo: github.com/GreenMachine582/discord-gateway
    target_node: homelab-svc-01
    deployment:
      type: image
      image: ghcr.io/greenmachine582/discord-gateway
    rollback:
      strategy: image
      keep: 5
  ```
- [ ] Verify via `deploy-service deploy discord-gateway`
- [ ] Retire: remove `discord-gateway/` from HomeLab repo; remove from `docker-compose.svc01.yml`

---

## Identity & Access

### Milestone E — Authentik SSO

Authentik provides SSO and forward-auth for externally-exposed services. See current design in [CLAUDE.md](./CLAUDE.md) (architecture) and [docs/NETWORK.md](./docs/NETWORK.md) (Caddy LAN bypass pattern).

**Prerequisite:** Phase 3 complete (svc-01 running PostgreSQL).

- [ ] **E1** — Create `roles/authentik/` (tasks + templates for Authentik config)
- [ ] **E2** — Add Authentik server + worker + Redis to `docker-compose.svc01.yml`
  - Uses the existing svc-01 PostgreSQL instance
- [ ] **E3** — Add Authentik proxy outpost to `homelab-edge-services`:
  - New container in `homelab-edge-services/docker-compose.yml`
  - Update `configs/caddy/Caddyfile` with LAN bypass + forward_auth blocks:
    ```caddyfile
    @lan remote_ip {{ lan_subnet }}
    handle @lan    { reverse_proxy ... }
    handle         { forward_auth authentik-outpost:9000 {
                       uri /outpost.goauthentik.io/auth/caddy
                       copy_headers X-authentik-username X-authentik-groups X-authentik-email
                     }
                     reverse_proxy ... }
    ```
- [ ] **E4** — Update `inventories/group_vars/edge.yml`:
  - Add `authentik_outpost_url`
  - Update `caddy_routes` structure with `lan_bypass: true/false` per route
  - Add `auth.homelab.local` to `pihole_custom_dns`
  - Add `auth.yourdomain.com` to `cloudflared_ingress`
- [ ] **E5** — Add to `inventories/group_vars/all/vault.yml.example`:
  - `vault_authentik_secret_key`
  - `vault_authentik_postgres_password`
- [ ] **E6** — Update `CLAUDE.md` (add `roles/authentik/`, update svc-01 services list) and `BOOTSTRAP.md` (add Authentik deploy step to Phase 3)

---

## Post-Phase 3

- [ ] **#35** — Add deploy start/end notifications to the n8n Phase 4 workflow
  Notification logic belongs in n8n (not in playbooks) — n8n already has full deploy context (git SHA, branch, triggering commit). Implement in the workflow that handles the GitHub Actions webhook:
  - **Start node:** POST to ntfy (primary) and Discord webhook (fallback) before SSHing to edge
  - **Success branch:** notify with commit SHA and elapsed time
  - **Failure branch:** notify with exit code / last task; higher priority
  - ntfy topic and Discord webhook available via `vault_ntfy_token` / `vault_discord_alerts_webhook`
  - **Prerequisite:** Phase 3 (ntfy on homelab-observe) and Phase 4 webhook wiring must be live
