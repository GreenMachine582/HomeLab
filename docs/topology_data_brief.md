# Homelab Topology & Shared Data Tier — Planning Brief (v4)

> Companion to [repo_split_brief.md](./repo_split_brief.md). That brief answers *how services are packaged and deployed*; this one answers *where they run* and *where their state lives*. It builds on the decided items there (central `services.yml`, `deploy-service` on edge, bootstrap-tier circularity, cloudflared rolling constraint) and changes none of them.

**Status:** §6 step 1 fully implemented — `topology.yml` created with the 3 real devices; `deploy-service` resolves `device:` against it (`target_node:` fallback preserved); all 4 `services.yml` entries migrated to `device:`; `inventories/prod.yml` is now generated from `topology.yml` via `scripts/generate_inventory.py` rather than hand-edited. Steps 2-7 not started — see `TODO.md` Milestone G.
**Origin repo:** https://github.com/GreenMachine582/HomeLab

**Changelog from v3:**
- **`scripts/generate_inventory.py` created** — derives `inventories/prod.yml` from `topology.yml` (static connection-defaults block plus one group per `host_roles` value, `ansible_host: "{{ ip_<suffix> }}"` per device). `inventories/prod.yml` swapped to the generated output; diff against the hand-written version showed only the expected difference (commented-out `svc-02`/`svc-03` placeholder hints, superseded by "add to `topology.yml`, regenerate"). `CLAUDE.md`'s "Adding a New Node" step 2 updated to match — §6 step 1 is now complete end-to-end.

**Changelog from v2:**
- **`topology.yml` created** at repo root with the 3 real devices (`rpi-01`/`rpi-02`/`rpi-03`), matching §3.1's example exactly. `svc-02`/`svc-03` deliberately omitted — no hardware yet.
- **`deploy-service` resolves `device:`** (`deploy_service/topology.py`, wired into `cli.py`) — falls back to `target_node:` unchanged, so nothing already deployed breaks. A new `--topology` CLI flag mirrors `--inventory`'s override pattern.
- **`services.yml`'s 4 entries migrated** from `target_node:` to `device:`, proving the mechanism end-to-end.
- `host_roles` consumption by `bootstrap_node.yml` (§3.3) is explicitly **not** part of this pass — tracked separately in `TODO.md` Milestone G.

**Changelog from v1:**
- **Placement layer dropped.** v1 introduced `placements:` (edge/observe/data/apps/media) as an indirection between repos and devices. Challenged and removed — `services.yml` now maps repo → device directly; devices carry `host_roles:` tags for bootstrap. Rationale in §3.4.
- **Co-residency analysis added (§5)** — what actually breaks when two stacks (e.g. edge + observe) land on one device, and the structural fixes.
- **Host-agents tier added (§5.4)** — node-exporter/portainer-agent become per-*device* concerns, resolving both the co-residency duplication and an existing double-definition on edge.
- **Authentik-sso reconciliation verified against the real repo (§4).** The "no service repo may declare a `postgres:`/`redis:` container" rule initially read as a conflict with `authentik-sso`'s bundled Postgres+Redis (recorded in `repo_split_brief.md`'s v7-v9 changelog). Checked against the actual `authentik-sso` repo rather than assumed: it already implements the transition pattern this brief needs — bundled containers gated behind a `local-infra` Compose profile, opt-out today, ready to point at `homelab-data-services` with a one-line env change once that stack exists. No repo change needed there; see §4.

---

## 🎯 1. Goals

1. **Topology portability.** Moving between shapes — several RPis (today), one PC, cloud VMs, or a mix — is a data change in one place, not edits across inventories, host_vars, Infisical `/prod/network/*`, and NODES.md.
2. **Safe co-residency.** Any subset of stacks must be able to share a device without bootstrap, deploy, or rollback conflicts. "One stack per Pi" must be a choice, not a load-bearing assumption.
3. **One data tier.** Service repos don't ship Postgres/Redis, and no service reaches into another service's store.
4. **Devices as data, not repos.** Devices declared once, in one file, in the HomeLab repo.

## ❓ 2. The problem today

Node identity is smeared across six hand-synced places:

| Place | What it knows |
|---|---|
| `services.yml` | `target_node: homelab-svc-01` hardcoded per entry |
| `inventories/prod.yml` | hostname → `{{ ip_* }}` binding, group membership |
| `group_vars/all/main.yml` + `overrides.yml` | the actual `ip_*` values |
| `host_vars/homelab-*.yml` | per-node service config |
| Infisical `/prod/network/IP_*` | the same IPs again, injected as env into service stacks |
| `NODES.md` | prose copy of all of the above |

And services consume raw node IPs (`IP_OBSERVE`, `IP_SVC_01` in the edge/observe stacks), coupling service config to physical topology.

## 🗺️ 3. Design: devices as data, repos map straight to devices

### 3.1 `topology.yml` (new, HomeLab repo root)

Single source of truth for devices. Everything else — Ansible inventory, deploy-service targeting, address injection, NODES.md content — derives from it.

```yaml
# topology.yml — the ONLY file that changes when hardware changes.
devices:
  rpi-01:
    hostname: homelab-edge          # Tailscale MagicDNS name
    arch: arm64
    host_roles: [edge]              # consumed by bootstrap only (§3.3)
    lan_ip: 192.168.1.10            # only where LAN-only paths need it (Pi-hole :53)
  rpi-02:
    hostname: homelab-observe
    arch: arm64
    host_roles: [observe]
  rpi-03:
    hostname: homelab-svc-01
    arch: arm64
    host_roles: [svc]
    notes: "Pi 5 8GB + NVMe"
```

### 3.2 `services.yml` maps repo → device

```yaml
repos:
  homelab-observe-services:
    repo: github.com/GreenMachine582/homelab-observe-services
    device: rpi-02                   # was: target_node: homelab-observe
    ...
  n8n-automation:
    device: rpi-03
    requires:                        # §4
      postgres: {database: n8n}
```

`deploy-service` resolves `device → hostname` (MagicDNS) for SSH and addressing. Collapsing three Pis onto one PC is: add the PC to `devices:`, point each repo's `device:` at it — a handful of lines, two files, both in the HomeLab repo.

### 3.3 `host_roles` — what bootstrap needs, and nothing more

Bootstrap still needs to know *what kind of host* to prepare: `edge` pulls in Unbound + the edge firewall set; `observe`/`svc` pull in their firewall sets and Docker tuning. That's a property **of the device**, so it lives on the device as tags — not as a separate mapping layer. `bootstrap_node.yml` becomes one parameterized playbook: apply base roles, then the union of role-specific roles/rules for every tag on the device. Inventory groups are generated per tag from `topology.yml` (a device with `[edge, observe]` appears in both groups).

### 3.4 Do you need placements at all? (resolved: no)

v1's placement layer (`repo → placement → device`) bought one thing: rebinding a placement moved several repos at once. Honest accounting at this scale:

| | With placements | Without |
|---|---|---|
| Collapse 3 Pis → 1 PC | edit 5 placement lines in topology.yml | edit ~6 `device:` lines in services.yml |
| Files touched | 1 | 2 (topology for the new device, services for bindings) |
| Indirections to hold in your head | repo→placement→device | repo→device |
| Stable name for addressing | placement name | repo name (§3.5 — strictly better) |
| Bootstrap grouping | placement doubles as group | `host_roles` tags (needed anyway) |

The layer saves a few lines per topology change — an event that happens a few times a year at most — at the permanent cost of a second lookup everywhere. And its addressing role was actually wrong: things don't need to know "where observe *stuff* is", they need to know "where *Prometheus* is" (§3.5). Placements only start paying rent at tens of repos. **Dropped.** If repo count ever grows past that, YAML anchors in `services.yml` (`device: *big-box`) recover 90% of the benefit with zero schema.

### 3.5 Addressing: per-repo, via MagicDNS — `IP_*` deprecated

`deploy-service` injects, for any repo that asks, `ADDR_<REPO>` = the MagicDNS hostname of the device that repo is bound to (e.g. `ADDR_OBSERVE_SERVICES=homelab-observe`). Identical whether the target is a Pi, a PC, or a cloud VM, and **automatically correct when repos co-reside** — no config edit when observe moves onto the edge box.

- Caddy's routes stop consuming `IP_SVC_01` and route to `ADDR_CAMUNDA_PLATFORM`, `ADDR_N8N_AUTOMATION` — per-repo is what a reverse proxy actually means anyway.
- Prometheus scrape targets are generated from topology per **device** (§5.5), not per repo.
- Infisical `/prod/network/IP_*` paths are deleted once migrated. `lan_ip` in `topology.yml` covers the genuinely-LAN paths (Pi-hole :53 advertisement).

> **Grounding in the real repo:** today's `services.yml` already injects `IP_OBSERVE`, `IP_SVC_01`, `IP_SVC_02`, `IP_SVC_03`, `IP_EDGE`, and `TAILNET` per-repo as Infisical-sourced secrets (`homelab-edge-services` and `homelab-observe-services` entries) — this is more advanced than `repo_split_brief.md`'s own §6.2 schema examples show (those only illustrate `TUNNEL_TOKEN`/`PIHOLE_WEB_PASSWORD`). Migration step 6 below has real, named env vars to replace, not a hypothetical pattern.

### 3.6 NODES.md

Becomes hardware notes plus "see `topology.yml`". Optionally a script regenerates its tables from topology.

## 🛢️ 4. Design: one platform data stack

*(Unchanged from v1 except placement references → device references.)*

New repo **`homelab-data-services`** (Postgres 16 + Redis 7, one deployment unit), registered in `services.yml` with a `device:` binding like any other stack. Ports bound to Tailscale interface + localhost only.

**Isolation rules:** one database + one role per service, role owns only its DB; Redis ACL users with key-prefix restrictions; **no service repo may declare a `postgres:`/`redis:` container** — enforced by a deploy-service compose lint; cross-service data flows via APIs, never shared tables.

> **`authentik-sso` is the reference implementation of this transition, not an exception to it.** It bundles its own `postgres`/`redis` containers today (per `repo_split_brief.md`'s v7-v9 changelog and its "each service repo owns its own backup" principle, §10.7) — but both are gated behind a `local-infra` Compose profile (`docker-compose.yml:81,91`), and `authentik-server`/`worker`'s dependency on them is `required: false` (`docker-compose.yml:34-38,66-70`). `.env.example:16` documents the toggle directly: `COMPOSE_PROFILES=local-infra` (default, bundled containers start) vs. blank (bundled containers skip; point `AUTHENTIK_POSTGRESQL__HOST`/`AUTHENTIK_REDIS__HOST` at a shared instance instead) — and the comment already names `homelab-data-services` as that future shared instance. Nothing in `authentik-sso` needs to change for it to comply with this rule; only `homelab-data-services` needs to exist and the `requires:`/secret-path wiring needs adding on the consuming side (§6 step 5).

**Provisioning (`requires:` block):** on deploy, deploy-service idempotently creates role/DB (admin creds from Infisical `/prod/data/ADMIN_*`), generates and stores per-service credentials at `/prod/data/<service>/…` on first run, and injects `PG_HOST` (= the data stack's device hostname), `PG_PORT/DATABASE/USER/PASSWORD` and Redis equivalents. Service repos stay standalone-runnable via `.env.example`.

**Exceptions (deliberate):** Infisical's Postgres+Redis and Semaphore's Postgres stay bootstrap-tier (circular — credentials live *in* Infisical; matches repo_split_brief §10). Camunda's Elasticsearch stays in `camunda-platform` (version-locked, single consumer, own snapshot mechanism).

**Portability:** same box → `PG_HOST` resolves locally, nothing changes. Cloud managed DB → `homelab-data-services` entry gains `external: {host, port, sslmode}`; deploy-service skips the stack and injects the endpoint. Backups consolidate to one per-DB `pg_dump` job in the data repo.

## 🖇️ 5. Co-residency: what happens when edge + observe share a device

The concrete question: bind `homelab-edge-services` and `homelab-observe-services` to the same box — do bootstrap, deploy, and rollback conflict? Audit against the actual composes:

### 5.1 What's already safe

- **Deploy & rollback:** separate compose projects, separate checkouts (`/srv/services/<repo>`), separate networks (`edge_net` vs the observe net — no cross-network traffic by design), project-prefixed volumes, per-repo `git` rollback. Structurally independent; the existing `global-deploy-lock` already serializes concurrent deploys. **No conflict.**
- **Published ports, today's pair:** edge claims 53, 80, 443, 8080, 8443, 8444, 9001, 9100, 9617; observe claims 3000, 3001, 3100, 9000, 9090, 9093 (+ ntfy). No overlap between the two stacks *except the agents below*. But this is luck, not design — see §5.3.

### 5.2 What breaks: bootstrap variable collisions

If one host sits in both the `edge` and `observe` inventory groups, `group_vars/edge.yml` and `group_vars/observe.yml` both apply. Any same-named variable (a `firewall_rules:` list is the classic) resolves by Ansible's group-precedence order — **one silently wins, the other's rules never land**. Fixes, both required:

1. Role-prefix every group var (`edge_firewall_rules`, `observe_retention_days`) so nothing collides by accident.
2. The firewall role applies the **union** of rule sets for every `host_role` on the device, rather than reading a single variable.

Base roles (hardening, docker, tailscale, fail2ban) are idempotent — running the parameterized `bootstrap_node.yml` (§3.3) once per device with multiple tags is safe.

### 5.3 What breaks: port and container-name uniqueness

- **`container_name:` is global per Docker daemon.** The edge compose hardcodes `container_name: node-exporter`, `caddy`, etc. If a co-resident stack declares the same name, `docker compose up` fails outright. Fix: **drop `container_name:` from all service repos** — compose's project prefix already namespaces, and nothing should depend on bare container names across projects (§3.5 addressing doesn't).
- **Port collisions must be checked, not hoped away.** Add a deploy-service pre-flight: union the published ports of every repo bound to the target device (parse the compose files), fail with a named conflict *before* touching the running stack. Cheap to build, converts a co-residency footgun into a lint error.

### 5.4 What breaks: duplicated host agents → new **host-agents tier**

`node-exporter` and `portainer-agent` are per-**device** concerns (they answer "what is this machine doing"), but they're currently packaged per-**stack** — the edge repo ships both. Co-residency makes this concrete: observe's device also needs a node-exporter, so edge+observe on one box means two containers fighting over :9100. (This is already latent on edge alone: repo_split_brief §10.2 lists node-exporter in the bootstrap compose *and* it exists in `homelab-edge-services` — a double-definition to resolve regardless.)

Fix: pull host agents out of service repos into a **`homelab-host-agents`** stack (node-exporter, portainer-agent; later alloy/cadvisor) that deploy-service deploys **once per device** — every device gets it, no repo "owns" it. Deduplication by construction: a device hosts exactly one agent set no matter how many stacks land on it. Portainer-agent note: on the device where Portainer Server itself runs, the agent is redundant (server uses the local socket) — the host-agents entry can skip it there via a device flag.

### 5.5 What silently degrades: monitoring self-reference

Prometheus scrape targets generated per **device** (from `topology.yml`) rather than per repo means: when edge and observe collapse onto one box, the target list shrinks from two node-exporters to one automatically — no duplicate-target noise, no stale config. Same for Uptime Kuma monitors. The current `IP_*`-placeholder approach would instead scrape the same box twice under two names.

### 5.6 Residual (accepted) risks

- **Resource contention** — Prometheus+Loki+Grafana beside Caddy/Pi-hole on a Pi 4 is tight on RAM. A topology concern, not a config one; `notes:` on the device and per-service compose `mem_limit`s are the mitigation.
- **Blast radius** — one device rebooting takes both ingress and monitoring down together. That's the trade you're explicitly choosing when co-residing; alerting via ntfy/Discord still needs the box up. Worth keeping observe separate from edge *if* you have the hardware — but the design no longer *requires* it.

## 🌿 6. Migration plan

Each step independently shippable; `target_node:` keeps working until step 7.

1. **`topology.yml` + resolver.** Encode current layout; teach deploy-service `device:` (fallback `target_node:`); generate inventory from topology, diff against hand-written `prod.yml`, swap when identical.
2. **De-collide the stacks.** Remove `container_name:` from service repos; add the port-collision pre-flight; role-prefix group vars. (All safe on today's one-stack-per-device layout — this step just makes co-residency *legal*.)
3. **Extract `homelab-host-agents`.** Move node-exporter + portainer-agent out of `homelab-edge-services` (and the bootstrap-compose duplicate); deploy once per device.
4. **Stand up `homelab-data-services`**, then implement `requires:` provisioning; prove with a throwaway service.
5. **Migrate n8n and authentik-sso to shared Postgres.** Both are ready: n8n needs a `requires:` block added; `authentik-sso` needs no repo change at all — it already gates its bundled containers behind `COMPOSE_PROFILES=local-infra` (see §4) and just needs `COMPOSE_PROFILES=` blank plus `AUTHENTIK_POSTGRESQL__HOST`/`AUTHENTIK_REDIS__HOST` pointed at the new stack's device hostname, wired via `requires:`. Future apps (BottleBot, greentechhub) use `requires:` from day one.
6. **Replace `IP_*` with `ADDR_<REPO>`/generated targets**; delete `/prod/network/IP_*` from Infisical once green.
7. **Cleanup:** drop `target_node:` fallback, add the no-embedded-DB lint, collapse NODES.md tables, retire moved host_vars.

## 📝 7. Open items

- **Which device gets `homelab-data-services` first?** rpi-03/NVMe recommended.
- **Redis isolation:** ACL users (recommended) vs. DB indexes — decide before step 4.
- **Inventory generation:** committed-generated file (recommended — diffable) vs. dynamic plugin.
- **Bootstrap-compose node-exporter vs. edge-services node-exporter** — confirm which is actually running on edge today; step 3 supersedes both.
- **Port pre-flight scope:** published ports only, or also host-network / `pid: host` clashes? Start with published ports.
