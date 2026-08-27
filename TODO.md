# Homelab TODO

Open tasks only. Completed tasks are tracked via git history — this file holds only pending work.

Node roles, ports, and playbook commands are in [CLAUDE.md](./CLAUDE.md), [NODES.md](./NODES.md), and [docs/NETWORK.md](./docs/NETWORK.md). The staged roadmap below follows [docs/consolidated_brief.md](./docs/consolidated_brief.md) §8 — design rationale for the polyrepo migration is in [docs/repo_split_brief.md](./docs/repo_split_brief.md), and for the device/topology model in [docs/topology_data_brief.md](./docs/topology_data_brief.md).

## Stage 0 — Done (baseline)

Mechanism built in-place (`deploy-service` + `services.yml` + Infisical injection + hooks executing); `homelab-edge-services` live (edge Phase 4 complete); observe/camunda/n8n repos extracted, registered, retired from monorepo; Authentik repo + compose + docs; bootstrap playbooks aligned; `topology.yml` v1 + resolver + inventory generation + `device:` migration; `ADDR_<REPO>` injection implemented additively.

## Stage 1 — Done (observe live)

`homelab-observe` bootstrapped and `homelab-observe-services` deployed; all endpoints
(Grafana, Prometheus, Loki, Alertmanager, ntfy, Uptime Kuma, Portainer) verified live.
Along the way: root-caused and fixed a stuck-transport bug blocking Alertmanager→Discord
delivery (`/-/reload` can't clear it, only a full restart), removed the permanently-false
`ContainerDown` alert (no cAdvisor deployed anywhere to supply the metric it depended on),
and added Alertmanager self-monitoring (`AlertmanagerNotificationsFailing` → ntfy fallback,
since a Discord-outage alert can't rely on Discord).

## Stage 2 — Hardware intake & topology v2 *(blocked on PC reclaim)*

- [ ] pc-01 prep: enable IGD/primary-display in BIOS, pull the RX 580, Debian 13 netinstall, verify `/dev/dri` + `alx` NIC
- [ ] laptop-01 prep: Debian 13 netinstall (no DE), `HandleLidSwitch=ignore`, mask sleep/suspend/hibernate targets, cap battery charge, USB-C GbE adapter
- [ ] `topology.yml` v2: add pc-01/laptop-01, re-role rpi-03 → `homelab-data-01`, add `data`/`media` host_roles; regenerate + swap inventory
- [ ] Clear the stale `homelab-svc-01` Tailscale machine entry before pc-01 joins the tailnet
- [ ] Wire `host_roles` into `bootstrap_node.yml` (base + per-tag roles/firewall) — now required for `data`/`media` tags, not just co-residency
- [ ] Update `services.yml` `device:` values (camunda-platform/n8n-automation/authentik-sso → pc-01)

## Stage 3 — svc-heavy live on pc-01 *(was Milestone B + D1/D2 verify + E2–E5)*

- [ ] Merge `wip/svc` into master (keep master's TODO.md — this file — then re-baseline against it)
- [ ] Bootstrap pc-01
- [ ] Deploy-verify `camunda-platform`, `n8n-automation`
- [ ] discord-gateway keep/remove decision
- [ ] Extract + deploy `discord-gateway` (amd64 image) *if kept*
- [ ] Bootstrap-lock signaling — Ansible + Camunda BPMN sides land together; endpoint targets pc-01 (`{{ ip_svc_01 }}` reconciled to resolve from `topology.yml`)
- [ ] Authentik: proxy outpost on `homelab-edge-services`, `group_vars/edge.yml` update, `services.yml` entry, deploy-verify

## Stage 4 — Data tier on rpi-03 *(was G7; needs Stage 2, not Stage 3)*

- [ ] Re-bootstrap rpi-03 as `homelab-data-01` (`data` host_role, NVMe layout)
- [ ] Decide Redis isolation: ACL users vs DB indexes
- [ ] Create `homelab-data-services` repo (Postgres 16 + Redis 7, Tailscale-bound)
- [ ] Implement `requires:` provisioning; prove with a throwaway service
- [ ] Backup job: nightly dumps → pc-01 `/srv/backups` + failure alert to ntfy

## Stage 5 — Co-residency & host agents *(was G5, G6)*

- [ ] Drop `container_name:` across service repos; add port-collision pre-flight; role-prefix group_vars
- [ ] Extract `homelab-host-agents`; deploy once per device (5 devices); drop bootstrap-compose duplicate
- [ ] Confirm which node-exporter is actually running on edge today (superseded by the host-agents extraction)

## Stage 6 — Consumers onto data tier *(was G8)*

- [ ] n8n: add `requires:` block, redeploy
- [ ] Authentik: blank `COMPOSE_PROFILES`, point at data tier via `requires:` (zero repo changes)
- [ ] Optional: n8n queue mode (Redis broker on data tier, workers on pc-01)

## Stage 7 — Addressing & cleanup *(was G9, G10)*

- [ ] Verification gates: tailnet ping mesh + in-container MagicDNS resolution (Pi-hole/edge is the suspect device; fallback is pre-decided)
- [ ] Migrate remaining `IP_*` consumers (edge Caddyfile) to `ADDR_<REPO>`; delete `/prod/network/IP_*`
- [ ] Drop `target_node:` fallback; add no-embedded-DB lint; collapse NODES.md tables; retire moved host_vars

## Stage 8 — Applications & media *(was B2/svc-02/svc-03 + #35)*

- [ ] `greentechhub` repo (Django/Celery), `requires:` from day one, deploy → laptop-01
- [ ] `jellyfin-media` repo: QSV (`/dev/dri`), library on 1 TB HDD, deploy → pc-01
- [ ] Optional: *arr stack alongside Jellyfin
- [ ] Deploy start/end notifications in the n8n Phase-4 workflow (ntfy + Discord) — prereqs: Stage 1 (ntfy) + webhook wiring

## Open decisions

See [docs/consolidated_brief.md](./docs/consolidated_brief.md) §10 for full context.

- Redis isolation (ACL vs DB indexes) — needed before Stage 4
- discord-gateway keep/remove — Stage 3 gate
- BottleBot: still get built? If so, device = laptop-01 headroom
- PSU trust on pc-01 (Litepower Gen 2) — replace preemptively or on first symptom
- Media library growth — 1 TB HDD is a starting point, H110M has 4× SATA + spare bays
- Port pre-flight scope, DNS-level service names — deferred, unchanged
- NODES.md / CLAUDE.md refresh — at Stage 2, alongside `topology.yml` v2
