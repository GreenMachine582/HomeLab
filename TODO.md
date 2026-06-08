# Homelab TODO

Validation and remediation tasks identified by cross-referencing all documentation (README, BOOTSTRAP.md, NODES.md, docs/NETWORK.md) against the actual files in the repo.

Completed tasks are tracked via git history and commit messages, not here — this file holds only
open work.

---

## Repo Hygiene

- [ ] **#30 — Create `docker-compose.svc02.yml` and `docker-compose.svc03.yml`**
  `homelab-svc-02` (GreenTechHub/Django/Redis/Celery) and `homelab-svc-03` (Jellyfin) have roles and
  `host_vars/` files but no compose files. Mirror the structure of `docker-compose.svc01.yml`:
  named network, volumes, Portainer Agent on port 9001.

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

---

## Post-Phase 3 Review

- [ ] **#34 — Review discord-gateway after Phase 3 is deployed**
  discord-gateway handles INBOUND Discord slash commands routed to n8n — a different
  concern from curl/ntfy (which are outbound notifications). Retained for now.
  After Phase 3 (svc-01 running), decide:
  - Keep: if slash-command automation (e.g. `/deploy`, `/status`) is wanted
  - Remove: drop `discord-gateway` from `docker-compose.svc01.yml`, delete
    `roles/camunda/templates/discord_gateway/`, remove `vault_discord_public_key`
    and `vault_n8n_webhook_secret` from vault.yml
  If retained, review integration with the curl/ntfy outbound notification architecture.

- [ ] **#35 — Add deploy start/end notifications to n8n Phase 4 workflow**
  Playbooks should not own notification logic — n8n already has full deploy context (git SHA,
  triggering commit, branch). Implement in the n8n workflow that handles the GitHub Actions webhook:
  - **Start node**: POST to ntfy (primary) || Discord webhook (fallback) before SSHing to edge
  - **Success branch**: notify with commit SHA and elapsed time on clean playbook exit
  - **Failure branch**: notify with exit code / last task on non-zero exit; use higher priority
  
  Message format suggestion:
  - Start:   `🚀 Deploy started — master@abc1234`
  - Success: `✅ Deploy complete — master@abc1234 (42s)`
  - Failure: `❌ Deploy failed — master@abc1234 — check Ansible output`

  ntfy topic and Discord webhook already available (`vault_ntfy_token`, `vault_discord_alerts_webhook`).
  **Prerequisite:** Phase 3 (ntfy on homelab-observe) and Phase 4 (n8n webhook wired) must be live.
