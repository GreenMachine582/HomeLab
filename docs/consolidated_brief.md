# Homelab Consolidated Brief — Hardware Expansion, Topology v2 & Unified Roadmap (v1)

> **Status:** Active planning brief. Consolidates and supersedes the *roadmap/status* portions of
> [`repo_split_brief.md`](./repo_split_brief.md) (v10) and [`topology_data_brief.md`](./topology_data_brief.md) (v6),
> and re-baselines `TODO.md`. Design rationale in those briefs is **unchanged unless explicitly
> reconciled in §7** — this document adds two new x86 devices, finalizes stateful-service placement,
> and merges the three parallel task tracks (TODO milestones A–G, repo-split Phases 1–5, topology
> Steps 1–7) into one staged roadmap (§8) with a full task-ID reconciliation table (§9).

---

## 1. Purpose & Inputs

Three things changed since the briefs were written:

1. **Two x86 devices are being folded in** — a reclaimed desktop PC (i5-7400/16GB) and a convertible
   laptop (m3-7Y30/4GB). Both are Win11-ineligible and will run headless Debian.
2. **The shared data tier gets a dedicated device.** `topology_data_brief.md` §7 left "device for
   `homelab-data-services`" open, recommending rpi-03/NVMe. **Decision: confirmed** — rpi-03 (Pi 5,
   8GB, 2TB NVMe) becomes the dedicated queue/DB node. Elasticsearch stays co-located with Camunda
   on the heavy service node (it is already a deliberate data-tier exception, brief §4).
3. **Camunda/n8n/Authentik retarget to the PC.** Milestone B (bootstrap `homelab-svc-01`) was never
   completed — nothing is live on rpi-03 — so retargeting costs zero migration work.

Inputs: `repo_split_brief.md` v10, `topology_data_brief.md` v6, `TODO.md`, `NODES.md`, and the
hardware assessment below.

---

## 2. Incoming Hardware

### 2.1 pc-01 — reclaimed desktop (svc-heavy)

| Component | Spec | Notes |
|---|---|---|
| CPU | Intel i5-7400, 4C/4T, 3.0–3.5 GHz | Kaby Lake, amd64. Several times rpi-05-class throughput |
| iGPU | Intel HD 630 | Quick Sync (H.264 + HEVC 8/10-bit) via VAAPI → Jellyfin HW transcode |
| RAM | 16 GB DDR4 (8 GB 2133 + 8 GB 2400) | Mixed sticks run together at 2133 — irrelevant for server duty |
| Storage | 240 GB SATA SSD + 1 TB BarraCuda HDD | SSD: OS + Docker; HDD: media + cross-node backup target |
| Board / NIC | MSI H110M Gaming (Killer E2500 GbE) | `alx` driver, works out of the box on modern kernels |
| PSU | Thermaltake Litepower Gen 2 750W | Budget unit, aged; fine at ~30 W load but least-trusted part |
| dGPU | Gigabyte RX 580 8GB | **Pull it** — see prep tasks |

**Prep tasks (Stage 2):** enable IGD/primary-display in BIOS *before* removing the RX 580, confirm
`/dev/dri` appears; pull the card (sell/shelf — Polaris has no ROCm support, poor LLM card); Debian
13 netinstall (no DE) on the SSD; expect ~20–30 W idle at wall (~AU$50–80/yr at ~30c/kWh).

### 2.2 laptop-01 — convertible laptop (svc-light)

| Component | Spec | Notes |
|---|---|---|
| CPU | Intel m3-7Y30, 2C/4T, 1.0–2.6 GHz | Kaby Lake-Y, 4.5 W fanless, amd64 |
| iGPU | Intel HD 615 | Same-gen Quick Sync — media fallback node if ever needed |
| RAM | 4 GB (soldered) | Hard ceiling — light-duty node only |
| Storage | 119 GB SSD | OS + Docker + app volumes; no bulk storage |
| Battery | Built-in | Free mini-UPS |

**Prep tasks (Stage 2):** Debian 13 netinstall; `HandleLidSwitch=ignore` in `/etc/systemd/logind.conf`; mask sleep/suspend/hibernate
targets; cap battery charge ~60–80 % if firmware supports it.

---

## 3. Target Topology (`topology.yml` v2)

### 3.1 Device table

| Device | Hostname (MagicDNS) | Arch | host_roles | Hardware | Status |
|---|---|---|---|---|---|
| rpi-01 | `homelab-edge` | arm64 | `[edge]` | Pi 4B | **Live** (unchanged) |
| rpi-02 | `homelab-observe` | arm64 | `[observe]` | Pi 4B | Bootstrap pending (Milestone A) |
| rpi-03 | `homelab-data-01` | arm64 | `[data]` *(new tag)* | Pi 5 8GB + 2TB NVMe | **Re-roled** — was `homelab-svc-01`, never bootstrapped |
| pc-01 | `homelab-svc-01` | amd64 | `[svc, media]` *(media new)* | i5-7400 / 16GB / 240G SSD + 1T HDD | New — pending reclaim |
| laptop-01 | `homelab-svc-02` | amd64 | `[svc]` | m3-7Y30 / 4GB / 119G SSD | New — pending prep |

Draft `topology.yml`:

```yaml
devices:
  rpi-01:
    hostname: homelab-edge
    arch: arm64
    host_roles: [edge]
    lan_ip: 192.168.1.10        # protocol-exceptional only (Pi-hole :53)
  rpi-02:
    hostname: homelab-observe
    arch: arm64
    host_roles: [observe]
  rpi-03:
    hostname: homelab-data-01
    arch: arm64
    host_roles: [data]
    notes: "Pi 5 8GB, 2TB NVMe — shared Postgres/Redis tier"
  pc-01:
    hostname: homelab-svc-01
    arch: amd64
    host_roles: [svc, media]
    notes: "i5-7400, 16GB, 240GB SSD + 1TB HDD, HD630 QSV, RX 580 removed"
  laptop-01:
    hostname: homelab-svc-02
    arch: amd64
    host_roles: [svc]
    notes: "m3-7Y30, 4GB soldered, 119GB SSD, USB-C GbE, HD615 QSV, lid-closed headless"
```

### 3.2 Hostname policy & rename map

Hostname remains the device's sole canonical identity (topology brief §3.5), and **hostnames follow
role, not silicon** — consumers only ever see `ADDR_<REPO>` / `device:` keys, so keeping role-shaped
names minimizes downstream churn:

| Identity | Old holder | New holder | Migration note |
|---|---|---|---|
| `homelab-svc-01` | rpi-03 (declared, never live) | pc-01 | Remove any stale Tailscale machine entry for rpi-03 under this name **before** pc-01 joins the tailnet |
| `homelab-data-01` | — | rpi-03 | New identity; new `data` host_role |
| `homelab-svc-02` | (planned Pi 5, never bought) | laptop-01 | Supersedes the planned svc-02 Pi purchase |
| `homelab-svc-03` | (future Jellyfin node) | **retired** | Media role folds into pc-01 as `media` host_role — see §7.3 |

New `host_roles` to wire into the parameterized bootstrap (topology brief §3.3):
`data` → ufw allows 5432/6379 from tailnet + LAN node IPs only, NVMe mount, DB kernel tuning;
`media` → `/dev/dri` render group, HDD mount, optional VAAPI package set.

---

## 4. Service Placement Map

| Repo (services.yml) | Device | Notes |
|---|---|---|
| `homelab-edge-services` | rpi-01 | Unchanged (live). cloudflared, Caddy, Pi-hole, exporters |
| *(bootstrap tier: Infisical, Semaphore)* | rpi-01 | Unchanged — Ansible-managed, never `deploy-service` |
| `homelab-observe-services` | rpi-02 | Unchanged. Prometheus/Loki/Grafana/Alertmanager/ntfy/Uptime Kuma |
| `homelab-data-services` *(new, G7)* | **rpi-03** | Postgres 16 + Redis 7 on NVMe. Ports bound to Tailscale + localhost |
| `camunda-platform` | **pc-01** | Zeebe + Operate + Tasklist + **Elasticsearch stays here** (data-tier exception preserved — version-locked, single consumer, own snapshots) |
| `n8n-automation` | **pc-01** | Postgres/Redis via `requires:` → data tier (G8). Queue-mode option later: broker on rpi-03, workers on pc-01 |
| `authentik-sso` | **pc-01** | Bundled Postgres/Redis for now (`COMPOSE_PROFILES=local-infra`); flips to data tier in G8 with zero repo changes |
| `discord-gateway` *(if kept, B6)* | pc-01 | Target is now amd64 — ghcr CI can build single-arch; buildx multi-arch optional for portability |
| `greentechhub` *(new repo, was B2/svc-02)* | **laptop-01** | Django + Celery worker; Postgres/Redis via `requires:` from day one. Flower optional |
| `jellyfin-media` *(new repo, was svc-03)* | **pc-01** | QSV via `/dev/dri`; library on 1 TB HDD; Sonarr/Radarr/Prowlarr optional later |
| `homelab-host-agents` *(new, G6)* | every device | node-exporter + portainer-agent, once per device |

Per repo-split brief §7 ("default to own repo"), `greentechhub` and `jellyfin-media` are **own
repos** — the old B2 plan of `docker-compose.svc02.yml`/`svc03.yml` inside HomeLab is superseded (§9).

---

## 5. Resource Allocations

### 5.1 pc-01 — `homelab-svc-01` (16 GB RAM, 4C/4T)

| Workload | RAM budget | Notes |
|---|---|---|
| OS + host agents + Docker | ~1 GB | |
| Elasticsearch | 2 GB heap → ~3 GB container | `mem_limit: 3g`; can grow to 4 GB heap if Operate/Optimize demand |
| Zeebe + Operate + Tasklist | ~3.5 GB | The stack that was miserable in a Pi's 8 GB gets room here |
| n8n (main) | ~0.5 GB | |
| Authentik server + worker (+ bundled PG/Redis until G8) | ~1.5 GB | Drops ~0.5 GB after G8 |
| Jellyfin | ~1.5 GB | Transcode is QSV (GPU), not CPU/RAM-bound |
| discord-gateway (if kept) | ~0.1 GB | |
| **Headroom** | **~5 GB** | Burst, page cache, future services |

Disk: 240 GB SSD → OS + `/var/lib/docker` + ES data + app volumes. 1 TB HDD → `/srv/media` +
`/srv/backups` (cross-node dump target, §6.4).

### 5.2 rpi-03 — `homelab-data-01` (8 GB RAM, 2 TB NVMe)

| Workload | RAM budget | Notes |
|---|---|---|
| OS + host agents + Docker | ~0.75 GB | |
| Postgres 16 | `shared_buffers` 1.5–2 GB, `mem_limit: 3g` | Serves n8n, Authentik (post-G8), GreenTechHub, future apps |
| Redis 7 | `maxmemory` 512 MB–1 GB | ACL-per-service (open item, §10) |
| **Headroom** | **~3 GB** | WAL bursts, `pg_dump`, connection overhead |

Disk: NVMe → Postgres data, Redis persistence, WAL, local dump staging. The earlier idea of a USB
SSD for the data node is void — the NVMe already on rpi-03 is strictly better.

### 5.3 laptop-01 — `homelab-svc-02` (4 GB RAM)

| Workload | RAM budget | Notes |
|---|---|---|
| OS + host agents + Docker | ~0.6 GB | No DE installed |
| GreenTechHub (Django + gunicorn) | ~0.7 GB | |
| Celery worker | ~0.5 GB | Concurrency 2; DB/broker are remote (data tier) |
| **Headroom** | **~2 GB** | One more small app max; ES/JVM workloads never land here |

### 5.4 rpi-01 / rpi-02

Unchanged from `NODES.md`. rpi-02 gains scrape targets for three new devices (generated per-device
from `topology.yml`, brief §5.5 — no per-repo duplication).

---

## 6. Connections & Network

### 6.1 Connection matrix

| From → To | Port/Proto | Path & control |
|---|---|---|
| n8n, GreenTechHub, Authentik (post-G8) → `homelab-data-01` | 5432 (Postgres), 6379 (Redis) | Via Tailscale hostname injected as `PG_HOST`/`REDIS_HOST` by `requires:`; bound to tailnet + localhost; ufw allows tailnet only |
| Zeebe ↔ Elasticsearch | 9200 | **Localhost-only on pc-01** — never crosses the network (the "keep elastic with svc-heavy" decision) |
| Prometheus (rpi-02) → all devices | 9100 (node-exporter) + service exporters | Targets generated per-device from `topology.yml` |
| Loki push ← all devices (alloy) | 3100 | Unchanged pattern |
| Portainer (rpi-02) → portainer-agent | 9001 | Via `homelab-host-agents`, one per device |
| cloudflared / Caddy (rpi-01) → services | 80/443 → app ports | External ingress unchanged: Cloudflare Tunnel only, no open router ports; Authentik forward-auth per E2 (LAN-bypass Caddy pattern) |
| `deploy-service` (rpi-01) → all devices | SSH over Tailscale | Resolves `device:` → hostname via `topology.yml` |
| `bootstrap_node.yml` → Zeebe | 8080 REST | Bootstrap-lock messages (B7) now target **pc-01** — see §7.5 |
| ntfy / Alertmanager (rpi-02) → phone/Discord | — | Unchanged |

### 6.2 Addressing

`ADDR_<REPO>` injection (topology brief §3.5) proceeds as designed and **gains urgency**: the edge
Caddyfile still consumes Infisical `IP_*` secrets, and pc-01 replacing rpi-03 behind the
`homelab-svc-01` name means `IP_SVC_01` changes value at cutover. Migrating consumers to
`ADDR_CAMUNDA_PLATFORM` etc. (G9) before/at Stage 3 avoids a stale-IP class of breakage entirely.
Both G9 verification gates (LAN-direct `tailscale ping` mesh; MagicDNS resolution inside containers,
Pi-hole-on-edge being the suspect device) are unchanged.

### 6.3 Architecture mix

The fleet is now **arm64 + amd64**. Upstream images used are all multi-arch (Postgres, Redis,
Prometheus stack, Jellyfin, n8n, Authentik, Camunda/ES on amd64). Rules: `arch:` in `topology.yml`
is authoritative; custom builds (`discord-gateway`, future BottleBot) must publish an image matching
their target device's arch — single-arch amd64 is acceptable while their `device:` is pc-01/laptop-01;
switch CI to buildx multi-arch only if a repo ever retargets to a Pi.

### 6.4 Backups (in-house, no off-site)

Off-site was considered and **declined**. Compensating layout, per repo-split brief §10.7 ("each
service repo owns its backup"):

- `homelab-data-services` owns nightly per-DB `pg_dump` + Redis RDB snapshot → NVMe staging →
  pushed to `pc-01:/srv/backups` (1 TB HDD) over Tailscale. Cross-node, so a dead NVMe ≠ dead databases.
- `camunda-platform` owns ES snapshots → `/srv/backups` locally, mirrored to rpi-03 NVMe (cross-node
  in the other direction).
- Bootstrap-tier DBs (Infisical, Semaphore) stay in `playbooks/backup.yml` as designed.
- Alertmanager rule: backup-job failure → ntfy, wired into the existing observe stack.

---

## 7. Reconciliations (decisions changed or resolved)

1. **Data-tier device (topology brief §7 open item) → RESOLVED: rpi-03.** Its 8 GB + 2 TB NVMe is
   the best storage in the fleet and Milestone B never went live, so it's free without migration.
2. **svc-02 hardware → CHANGED: laptop-01, not a new Pi 5.** The planned Pi purchase is cancelled.
3. **svc-03 node → RETIRED: media folds into pc-01** as a `media` host_role. Rationale: QSV + the
   1 TB HDD live there; a fourth-node purchase is unnecessary. Accepted trade-off: heavy-svc and
   media share one blast radius (same class of accepted risk as topology brief §5.6).
4. **Milestone B retargeted.** B3/B4/B5 now bootstrap **pc-01** and deploy-verify D1/D2 there.
   B2 is **superseded** — no `docker-compose.svc02/svc03.yml` in HomeLab; own repos instead (§4).
5. **Bootstrap-lock endpoint (repo-split brief §9).** The Zeebe REST endpoint moves with Camunda to
   pc-01. Reconcile the hardcoded `{{ ip_svc_01 }}` to resolve from `topology.yml` (hostname, or
   deploy-time-resolved Tailscale IP per the pre-decided G9 fallback). Correlation-key scheme
   (`bootstrap-lock-<hostname>`) unchanged and now covers five nodes.
6. **`arch:` field earns its keep** (was uniformly arm64) — see §6.3.
7. **Elasticsearch placement re-affirmed** as a data-tier exception co-located with Zeebe (was §4 of
   topology brief; unchanged, now explicit for the new hardware).
8. **`notes:`-driven RAM caution shifts.** The §5.6 "tight on Pi 4 RAM" co-residency risk now mainly
   applies to laptop-01 (4 GB soldered): enforce `mem_limit` on everything scheduled there; never
   place JVM/ES-class workloads on it.

No other decision in either brief is altered: three-gate deploy auth, `deploy-service` CLI, ghcr,
clustering heuristic, `requires:` provisioning, MagicDNS-canonical addressing, and the placements-
layer rejection all stand.

---

## 8. Unified Roadmap

Stages replace the parallel numbering (TODO Phases 3–4, repo-split Phases 1–5, topology Steps 1–7).
Each stage is independently shippable; hardware-blocked stages are marked. Stage 1 has no dependency
on the new hardware and should proceed immediately.

### Stage 0 — Done (baseline)

Mechanism built in-place (`deploy-service` + `services.yml` + Infisical injection + hooks executing);
`homelab-edge-services` live (edge Phase 4 complete); observe/camunda/n8n repos extracted, registered,
retired from monorepo (C1–C4, C6, D1/D2 extract); Authentik repo + compose + docs (E0, E1, E6);
bootstrap playbooks aligned (F1–F5, F6 deferred); `topology.yml` v1 + resolver + inventory generation
+ `device:` migration (G1–G4); `ADDR_<REPO>` injection implemented additively (G9 partial).

### Stage 1 — Observe live *(done)*

| Task | From | Status |
|---|---|---|
| Merge `wip/observe` → master | A1 | ✅ done |
| Bootstrap rpi-02 (`bootstrap_node.yml --limit homelab-observe`) | A2 | ✅ done |
| Deploy `homelab-observe-services` via deploy-service | A3 + C5 | ✅ done — C5's deploy-verify **is** this deploy; verify both post_hooks (`setup_monitors`, `setup_portainer` within token window) |
| Verify endpoints (Grafana/Prom/Loki/AM/ntfy/Kuma/Portainer) | A4 | ✅ done — along the way, root-caused/fixed a stuck-transport bug blocking Alertmanager→Discord delivery, removed the permanently-false `ContainerDown` alert, added Alertmanager self-monitoring (`AlertmanagerNotificationsFailing` → ntfy) |

### Stage 2 — Hardware intake & topology v2 *(pc-01/laptop-01 prep blocked on hardware; data-tier topology slice done)*

| Task | From | Status |
|---|---|---|
| pc-01 prep: BIOS iGPU, pull RX 580, Debian netinstall, verify `/dev/dri` + `alx` NIC | new | ☐ open |
| laptop-01 prep: Debian netinstall, lid/suspend config, GbE adapter, charge cap | new | ☐ open |
| `topology.yml`: re-role rpi-03 → `homelab-data-01`, add `data` host_role; regenerate + swap inventory | G1 rev | ✅ done |
| `topology.yml`: add pc-01/laptop-01, add `media` host_role | G1 rev | ☐ open — blocked on hardware |
| Clear stale `homelab-svc-01` Tailscale entry before pc-01 joins | new | ☐ open |
| Wire `data` host_role into `bootstrap_node.yml` (valid-nodes check; firewall via `inventories/group_vars/data.yml`) | TODO (pre-G5) | ✅ done |
| Wire `media` host_role into `bootstrap_node.yml` | TODO (pre-G5) | ☐ open — blocked on pc-01 |
| Update `services.yml` `device:` values for camunda/n8n → pc-01 | new | ✅ done — fails loudly rather than misdeploying, since pc-01 isn't in `topology.yml` yet |
| Add `authentik-sso` entry to `services.yml`, targeting pc-01 | new | ☐ open — repo isn't registered in `services.yml` yet |

### Stage 3 — svc-heavy live on pc-01 *(was Milestone B + D1/D2 verify + E2–E5)*

| Task | From | Status |
|---|---|---|
| Merge `wip/svc` → master (keep master's TODO.md; then re-baseline TODO against this brief) | B1 | ☐ open |
| Bootstrap pc-01 | B3 (retargeted) | ☐ open |
| Deploy-verify `camunda-platform`, `n8n-automation` | B4/B5, D1/D2 verify | ☐ open |
| discord-gateway keep/remove decision | B6 | ☐ open — decision gate |
| Extract + deploy `discord-gateway` (amd64 image) *if kept* | D3 | ☐ conditional |
| Bootstrap-lock signaling, both halves together; endpoint per §7.5 | B7 | ☐ open — design resolved |
| Authentik: outpost on edge, group_vars, `services.yml` entry, deploy-verify | E2–E5 | ☐ open |

### Stage 4 — Data tier on rpi-03 *(was G7; needs Stage 2, not Stage 3)*

| Task | From | Status |
|---|---|---|
| Re-bootstrap rpi-03 as `homelab-data-01` (data host_role, NVMe layout) | new | ☐ open — `roles/nvme_storage` + `host_vars/homelab-data-01.yml` ready; blocked on hardware reachability |
| Decide Redis isolation: ACL users vs DB indexes | open item | ✅ resolved — ACL, implemented in `provision.py::provision_redis()` |
| Create `homelab-data-services` repo (Postgres 16 + Redis 7, Tailscale-bound) | G7 | ✅ done — scaffolded, registered in `services.yml`; not deployable yet (`secrets.yml` pending, node not bootstrapped) |
| Implement `requires:` provisioning; prove with throwaway service | G7 | ✅ implemented + unit-tested (`provision.py`, `test_provision.py`) — ☐ still needs proving against a live deploy, blocked on node bootstrap |
| Backup job: nightly dumps → pc-01 `/srv/backups` + failure alert | §6.4 | ✅ local half done (`homelab-data-services/scripts/backup.sh`: dump + NVMe staging + ntfy) — ☐ remote push to pc-01 wired via `BACKUP_REMOTE_HOST`, inactive until pc-01 exists |

### Stage 5 — Co-residency & host agents *(was G5, G6)*

| Task | From | Status |
|---|---|---|
| Drop `container_name:` across service repos; port-collision pre-flight; role-prefix group_vars | G5 | ☐ open |
| Extract `homelab-host-agents`; deploy once per device (5 devices); drop bootstrap-compose duplicate | G6 | ☐ open |
| Confirm which node-exporter actually runs on edge today (superseded by G6) | open item | ☐ open |

### Stage 6 — Consumers onto data tier *(was G8)*

| Task | From | Status |
|---|---|---|
| n8n: add `requires:` block, redeploy | G8 | ☐ open |
| Authentik: blank `COMPOSE_PROFILES`, point at data tier via `requires:` (zero repo changes) | G8 | ☐ open |
| Optional: n8n queue mode (Redis broker on data tier, workers on pc-01) | conversation | ☐ optional |

### Stage 7 — Addressing & cleanup *(was G9, G10)*

| Task | From | Status |
|---|---|---|
| Verification gates: tailnet ping mesh + in-container MagicDNS (Pi-hole edge suspect; fallback pre-decided) | G9 | ☐ open |
| Migrate remaining `IP_*` consumers (edge Caddyfile) to `ADDR_<REPO>`; delete `/prod/network/IP_*` | G9 | ☐ open — urgency raised, §6.2 |
| Drop `target_node:` fallback; no-embedded-DB lint; collapse NODES.md; retire moved host_vars | G10 | ☐ open |

### Stage 8 — Applications & media *(was B2/svc-02/svc-03 + #35)*

| Task | From | Status |
|---|---|---|
| `greentechhub` repo (Django/Celery), `requires:` from day one, deploy → laptop-01 | B2 superseded | ☐ open |
| `jellyfin-media` repo: QSV (`/dev/dri`), library on 1 TB HDD, deploy → pc-01 | B2/svc-03 superseded | ☐ open |
| Optional *arr stack alongside Jellyfin | old svc-03 | ☐ optional |
| Deploy start/end notifications in n8n Phase-4 workflow (ntfy + Discord) | #35 | ☐ open — prereqs: Stage 1 (ntfy) + webhook wiring |

**Dependency notes:** Stage 1 ⟂ everything (do now). Stage 4 needs Stage 2 only — the data tier does
not wait for Camunda. Stage 6 needs Stages 3+4. Stage 7's gates need all five devices on the tailnet
(post 2/3/4). Stage 8 apps need Stage 4 (`requires:`); Jellyfin technically only needs Stage 3's
bootstrapped pc-01 and may be pulled earlier if wanted.

---

## 9. Task Reconciliation Table (old ID → disposition)

| Old ID | Was | Disposition |
|---|---|---|
| A1 | Merge wip/observe | ✅ Done (Stage 0) |
| A2–A4 | Observe bootstrap/deploy/verify | → Stage 1, ✅ done |
| B1 | Merge wip/svc | → Stage 3, open |
| B2 | Create svc02/svc03 compose files in HomeLab | **Superseded** — own repos `greentechhub`, `jellyfin-media` (Stage 8) |
| B3–B5 | Bootstrap + deploy svc-01 (rpi-03) | **Retargeted** to pc-01 → Stage 3 |
| B6 | discord-gateway keep/remove | → Stage 3, decision gate |
| B7 | Bootstrap-lock signaling | → Stage 3; endpoint reconciled (§7.5) |
| C1–C4, C6 | observe-services extraction | ✅ Done (Stage 0) |
| C5 | observe deploy-verify | → Stage 1 (merged with A3) |
| D1, D2 | camunda/n8n extraction | ✅ Done (Stage 0); deploy-verify → Stage 3 |
| D3 | discord-gateway split | → Stage 3, conditional on B6; amd64 image note (§6.3) |
| E0, E1, E6 | Authentik repo/compose/docs | ✅ Done (Stage 0) |
| E2–E5 | Outpost, vars, registry entry, verify | → Stage 3; device is now pc-01 |
| F1–F5 (F6) | Bootstrap playbook alignment | ✅ Done (F6 stays deferred) |
| G1–G4 | topology.yml, resolver, device:, inventory gen | ✅ Done (Stage 0); **G1 revised** in Stage 2 (new devices, re-role) |
| G5 | De-collide co-residency | → Stage 5 |
| G6 | homelab-host-agents | → Stage 5 |
| G7 | homelab-data-services | → Stage 4; device resolved = rpi-03 |
| G8 | n8n + Authentik to shared tier | → Stage 6 |
| G9 | ADDR_<REPO> / delete IP_* | Partially done (Stage 0); remainder → Stage 7, urgency raised |
| G10 | Cleanup | → Stage 7 |
| host_roles wiring | Pre-G5 prerequisite | → Stage 2 (pulled earlier — needed for `data`/`media` tags) |
| #35 | Deploy notifications in n8n | → Stage 8 |
| repo-split Phases 1–5 | Mechanism-first sequencing | Phase 1 ✅, Phase 4 partially ✅ (per Stage 0); Phases 2–3 (BottleBot proof) unscheduled — mechanism was proven via edge instead; Phase 5 cleanup absorbed into Stages 5/7 |
| topology Steps 1–7 | Migration plan | Step 1 ✅; Steps 2–7 = Stages 5, 5, 4, 6, 7, 7 respectively |

---

## 10. Open Items

1. ~~**Redis isolation** (ACL users vs DB indexes)~~ — **Resolved: ACL users.**
   `deploy_service/provision.py::provision_redis()` already implements per-service ACL users with
   key-prefix restriction, and `homelab-data-services`'s README documents it as the working
   default. This was carried as an open decision gate longer than it should have been — the
   implementation had already settled it.
2. **discord-gateway keep/remove** (B6) — Stage 3 gate (carried over).
3. **BottleBot** — Phases 2–3 of the repo-split plan named it the proof-of-concept extraction; the
   mechanism got proven on real services instead. Decide whether BottleBot still gets built, and if
   so its device (laptop-01 headroom fits).
4. **PSU trust** — Litepower Gen 2 is the weakest component on pc-01; replace preemptively or on
   first symptom? (Cheap at ~30 W loads either way.)
5. **Media library growth** — 1 TB HDD is a starting point; H110M has 4× SATA and the case has spare
   bays, so expansion is a drop-in when needed.
6. **Port pre-flight scope** and **DNS-level service names** — deferred as per topology brief §7,
   unchanged.
7. **`NODES.md` / `CLAUDE.md` refresh** — both still describe the three-Pi + planned-Pi world; update
   at Stage 2 alongside `topology.yml` v2 (NODES.md collapse itself remains a G10/Stage 7 task).
