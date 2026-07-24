# Homelab Repo Split — Planning Brief (v9)

> **This is an active design brief, not an operations reference.** It documents the in-progress polyrepo migration strategy (`deploy-service`, `services.yml`, service repo splits). For day-to-day operations, see [README.md](../README.md), [BOOTSTRAP.md](../BOOTSTRAP.md), or [NETWORK.md](./NETWORK.md).

**Status:** `homelab-edge-services` live (§8 Phase 4 underway — edge complete). `homelab-observe-services` extracted and registered, deploy-verify pending live node. `camunda-platform` and `n8n-automation` extracted and registered (svc-01 split, Milestone D1/D2) — deploy-verify pending `homelab-svc-01` bootstrap (Milestone B). `authentik-sso` created and compose written (Milestone E0/E1, bundled Postgres) — not yet tagged, registered in `services.yml`, or deployed. Remaining Phase 4: `discord-gateway` (D3), gated on the keep/remove decision. Phase 5 cleanup in progress.
**Origin repo:** https://github.com/GreenMachine582/HomeLab
**Purpose of this doc:** Final design reference ahead of implementation.

**Changelog from v8:**
- **`authentik-sso` repo created** (`GreenMachine582/authentik-sso`, `main` branch) with `docker-compose.yml` (server, worker, Redis, bundled `postgres:16-alpine`) and `scripts/postdeploy.sh` (verifies Authentik's own `AUTHENTIK_BOOTSTRAP_*` automated setup succeeded) — confirms the bundled-Postgres direction from v8. Milestone E0/E1 done; E2-E6 remain.

**Changelog from v7:**
- **`camunda-platform` and `n8n-automation` extracted and registered** in `services.yml` (svc-01 split, Milestone D1/D2) — deploy-verify pending `homelab-svc-01` bootstrap.
- **Authentik will bundle its own Postgres container, for now** in `authentik-sso` (§5), superseding this doc's earlier draft wording ("reuses the existing svc-01 PostgreSQL instance, no bundled container") — self-contained, matching the "each service repo owns its own backup" principle (§10.7) already applied to every other split repo. A pragmatic starting point while Authentik work is just getting underway, not a final architectural commitment — may move to a shared instance later if that proves more efficient.
- **`deploy-service`'s `type: image` deployment path is implemented** (`deploy_service/cli.py`, `compose.py`) — the CLI no longer hard-exits on it; this was the last blocker noted for Milestone D3 (discord-gateway).

**Changelog from v6:**
- **Small/new-service repo default made explicit (§7).** A service defaults to its own repo unless it demonstrably shares deploy/upgrade/rollback/backup cadence with an existing repo — size alone isn't a reason to cluster. First applied to `authentik-sso` (§5), which gets its own repo rather than folding into `docker-compose.svc01.yml`.

**Quick links:** [🎯 Goal](#-1-goal) · [❓ Why](#-2-why-context-from-prior-discussion) · [🗂️ Repo Structure](#-3-current-repo-structure-for-reference) · [✅ What Stays](#-4-what-stays-in-the-bootstraparchitecture-repo) · [📦 What Moves](#-5-what-moves-to-service-repos) · [🔄 Redeploy Mechanism](#-6-metadata-driven-redeploy--schema-revised-again-and-deploy-service-design) · [🖧 Clustering](#-7-clustering-by-node-role-vs-per-service-repos-resolved-heuristic) · [🌿 Branch Plan](#-8-branch-plan-revised-sequencing) · [✂️ Edge Compose Split](#-10-edge-node-compose-split-in-detail) · [📝 Open Items](#-9-remaining-open-items-for-the-repo-owner-to-confirm)

<details>
<summary>Full outline</summary>

<!-- TOC -->
* [Homelab Repo Split — Planning Brief (v9)](#homelab-repo-split--planning-brief-v9)
  * [🎯 1. Goal](#-1-goal)
  * [❓ 2. Why (context from prior discussion)](#-2-why-context-from-prior-discussion)
  * [🗂️ 3. Current repo structure (for reference)](#-3-current-repo-structure-for-reference)
  * [✅ 4. What stays in the bootstrap/architecture repo](#-4-what-stays-in-the-bootstraparchitecture-repo)
  * [📦 5. What moves to service repos](#-5-what-moves-to-service-repos)
  * [🔄 6. Metadata-driven redeploy — schema (revised again) and `deploy-service` design](#-6-metadata-driven-redeploy--schema-revised-again-and-deploy-service-design)
    * [6.1 Service classification (replaces the universal "image_tag" assumption)](#61-service-classification-replaces-the-universal-image_tag-assumption)
    * [6.2 Schema (revised)](#62-schema-revised)
    * [6.3 `deploy-service` — CLI design](#63-deploy-service--cli-design)
    * [6.4 Decided / confirmed items](#64-decided--confirmed-items)
    * [6.5 Scheduling design — maintenance window, serialization, and dependencies](#65-scheduling-design--maintenance-window-serialization-and-dependencies)
  * [🖧 7. Clustering by node role vs. per-service repos (resolved heuristic)](#-7-clustering-by-node-role-vs-per-service-repos-resolved-heuristic)
  * [🌿 8. Branch plan (revised sequencing)](#-8-branch-plan-revised-sequencing)
  * [✂️ 10. Edge node compose split in detail](#-10-edge-node-compose-split-in-detail)
    * [10.1 The two tiers today](#101-the-two-tiers-today)
    * [10.2 The bootstrap compose (`docker-compose.bootstrap-edge.yml`)](#102-the-bootstrap-compose-docker-composebootstrap-edgeyml)
    * [10.3 The `homelab-edge-services` compose](#103-the-homelab-edge-services-compose)
    * [10.4 Network topology change](#104-network-topology-change)
    * [10.5 Phase 1 bootstrap scope change](#105-phase-1-bootstrap-scope-change)
    * [10.6 Cloudflared rolling-deploy constraint](#106-cloudflared-rolling-deploy-constraint)
    * [10.7 Roles retired after Phase 4 completion](#107-roles-retired-after-phase-4-completion)
  * [📝 9. Remaining open items for the repo owner to confirm](#-9-remaining-open-items-for-the-repo-owner-to-confirm)
<!-- TOC -->

</details>

---

## 🎯 1. Goal

The current `HomeLab` repo mixes bootstrap/architecture concerns (network, users, hardening, secrets handling) with per-service deployment detail (compose files, service-specific playbooks/scripts) in one place. This is becoming overwhelming to navigate and reason about.

**Target end state:**
- `HomeLab` repo becomes **bootstrap + architecture only**: one-time node bootstrap, cross-cutting config (SSH port, network, users, firewall, Tailscale), the generic redeploy mechanism, and a `services.yml`-style metadata registry.
- Each service (or small cluster of services) moves to **its own repo**, owning its own `docker-compose.yml`, env override file, and any service-specific install/update scripts.
- Service repos do **not** use Ansible. Docker Compose + a thin shell hook (pre/post deploy scripts) is enough, since bootstrap already handles host-level prerequisites (Docker install, users, firewall, hardening).
- `deploy-service`, a standalone Python tool living in the bootstrap repo and running on `homelab-edge`, driven by the `services.yml` metadata registry, handles "pull/checkout → layer `.env` → run hooks → deploy (compose or image, per service type) → healthcheck" for any service, reaching other nodes over SSH via Tailscale. Ansible invokes it rather than reimplementing its logic.

This was always the intended direction (polyrepo-by-service); this branch is the point of executing it.

---

## ❓ 2. Why (context from prior discussion)

- Single-repo-per-service gives independent versioning/tagging, smaller diffs, and the option to make a service (e.g. BottleBot) shareable/standalone without dragging in homelab secrets or infra.
- Cross-cutting changes (SSH port, subnet, base hardening) stay cheap because they live in the bootstrap repo and apply on a bootstrap release — this was the main cost of polyrepo and it's already mitigated by design.
- Ansible's value (idempotency, templating, host-level orchestration) is mostly needed at *node bootstrap* time, not at *service deploy* time. Once a node has Docker + users + firewall configured, deploying a service really is just a pull and a compose up. Ansible in service repos would be redundant weight.
- Considered Flux/Argo CD as prior art for the "metadata-driven, many-repos-one-control-plane" pattern — both are Kubernetes-native and not directly usable on a plain-Docker-Compose fleet, so they're a conceptual reference only, not an adoptable tool. Homelab already runs Camunda + n8n, which is a more direct fit for owning the webhook → lookup → trigger logic than introducing a new orchestrator.

---

## 🗂️ 3. Current repo structure (for reference)

```
homelab/
  README.md, BOOTSTRAP.md, NODES.md, TODO.md, CLAUDE.md
  ansible.cfg
  inventories/            # bootstrap.ini, prod.yml
  group_vars/             # all/main.yml, all/vault.yml, edge.yml, observe.yml, svc.yml
  host_vars/              # per-node: edge, observe, svc-01, svc-02, svc-03
  playbooks/              # bootstrap_*, deploy_*, update_all, backup, rollback, healthcheck
  roles/                  # alloy, base_hardening, docker, docker_compose, fail2ban, firewall,
                          #  infisical, semaphore, tailscale, unbound, users
  docker-compose.edge.yml
  docker-compose.svc01.yml
  secrets/vault.yml(.example)
  scripts/                # backup_databases.sh, test_connectivity.sh
  docs/                   # NETWORK.md, TROUBLESHOOTING.md
  discord-gateway/
  .github/workflows/      # deploy.yml, test.yml
```

Node roles today: `homelab-edge` (active), `homelab-observe` (active), `homelab-svc-01` (active — Camunda 8 + Elasticsearch via `camunda-platform`, n8n via `n8n-automation`, discord-gateway still Ansible-managed), `homelab-svc-02` (planned), `homelab-svc-03` (future, Jellyfin).

> **Current state (post-edge-split, post-observe-split, post-svc01-split):** `roles/edge_services/`, `roles/observe_services/`, and `roles/camunda/` have all been deleted; `docker-compose.edge.yml` now contains only Infisical + Semaphore (bootstrap tier), `docker-compose.observe.yml`/`docs/MONITORING.md` are gone (migrated to `homelab-observe-services`), and Camunda/Elasticsearch/n8n are gone from `docker-compose.svc01.yml` (migrated to `camunda-platform`/`n8n-automation`, leaving only discord-gateway + portainer-agent there). The network appliance services run in `homelab-edge-services`. The compose file rename (`docker-compose.edge.yml` → `docker-compose.bootstrap-edge.yml`) remains deferred — the service strip achieves the same isolation without requiring a reference update across bootstrap roles.

---

## ✅ 4. What stays in the bootstrap/architecture repo

- `inventories/`, `group_vars/`, `host_vars/` — shared node config, IPs, secrets handling
- `playbooks/bootstrap_*`, `playbooks/healthcheck.yml`, `playbooks/rollback.yml` (mechanism, not service-specific content)
- `roles/base_hardening`, `roles/docker`, `roles/docker_compose`, `roles/tailscale`, `roles/firewall`, `roles/fail2ban`, `roles/users`, `roles/node_exporter`, `roles/cadvisor`, `roles/alloy` — these are host-level/cross-cutting, not service-specific
- **`roles/infisical`, `roles/semaphore`** — the bootstrap control plane; these are prerequisites for `deploy-service` itself and cannot be managed by it (circular dependency). Deployed during Phase 1 bootstrap and never touched by `deploy-service`. See §10 for detail.
- The **new generic redeploy mechanism** — see §6 — implemented as a standalone `deploy-service` tool, with Ansible invoking it rather than performing deploy logic itself
- The **services metadata registry** (`services.yml`, kept central — see §6/§9)
- **`docker-compose.bootstrap-edge.yml`** (renamed from `docker-compose.edge.yml`, narrowed to bootstrap-tier services only — see §10)
- `secrets/vault.yml(.example)`, `docs/NETWORK.md`, `docs/TROUBLESHOOTING.md` (platform-wide, stays central)
- Top-level docs: README, BOOTSTRAP.md, NODES.md, TODO.md

This is effectively a **platform engineering repo**: it owns node bootstrap, cross-cutting config, and the deployment control plane, but no service content.

## 📦 5. What moves to service repos

Decided/concrete moves:

| Current content | New home |
|---|---|
| Network appliance tier of `docker-compose.edge.yml` + `roles/edge_services/` (see note below) | `homelab-edge-services` (clustered — see §7 and §10) |
| `docker-compose.observe.yml` + `roles/observe_services/` + `docs/MONITORING.md` | `homelab-observe-services` (clustered — see §7) |
| Camunda 8 + Elasticsearch | `camunda-platform` |
| n8n | `n8n-automation` |
| `discord-gateway/` | `discord-gateway` |
| `scripts/backup_databases.sh` | Moves with whichever repo owns the data it backs up; cross-service backup orchestration (if any) stays central |
| BottleBot | Own repo from day one — proof-of-concept for the whole pattern, and the **first service migrated** under the revised sequencing in §8 |
| Authentik SSO (server, worker, Redis, own Postgres for now) | `authentik-sso` — own repo from day one (created, `docker-compose.yml` written; TODO.md Milestone E0/E1 done, E2-E6 remain). Bundles its own Postgres container for now — self-contained, like every other split repo (see §10.7 "each service repo owns its own backup"); may move to a shared instance later if that proves more efficient. See §7 for why this doesn't cluster into `camunda-platform`/`n8n-automation` despite being small. |

> **Edge compose note:** `docker-compose.edge.yml` currently holds two distinct tiers that must be split before anything moves. Only the **network appliance tier** goes to `homelab-edge-services` (cloudflared, Caddy, Pi-hole, pihole-exporter, node-exporter, portainer-agent). 
The **bootstrap tooling tier** (Infisical stack, Semaphore stack) stays in the HomeLab repo in a renamed `docker-compose.bootstrap-edge.yml`. `roles/edge_services/` is retired post-migration (its Jinja2 templates become plain config files in `homelab-edge-services/`). 
`playbooks/deploy_edge.yml` is retired and replaced by `deploy-service deploy homelab-edge-services`. See §10 for the full breakdown.

Service repos contain only: `docker-compose.yml`, `.env.example`, `scripts/`, `configs/`, `docs/`, optionally a `Makefile` for local dev. No Ansible, no inventories, no host vars — they should be runnable anywhere via `git clone && docker compose up -d`.

---

## 🔄 6. Metadata-driven redeploy — schema (revised again) and `deploy-service` design

Lives in the bootstrap repo as `services.yml`, kept **central** (decided — see §9 for reasoning). Read by `deploy-service`, a standalone Python tool that Ansible invokes rather than reimplements (`- command: deploy-service deploy bottlebot`). This keeps deploy logic out of Ansible entirely and makes it independently testable/runnable.

### 6.1 Service classification (replaces the universal "image_tag" assumption)

v2 assumed every service should roll back via Docker image tags. That only makes sense for services where *you* build and push an image. Most of this homelab doesn't — it runs stock containers with mounted config. Classifying services into three types fixes this:

| Type | Examples | Builds an image? | Deploy mechanism | Rollback mechanism |
|---|---|---|---|---|
| Pure upstream images | Grafana, Prometheus, Loki, Pi-hole, n8n/Camunda (if kept on stock images) | No | `git pull` → `docker compose pull` → `up -d` | Revert the version pin in compose (`image: grafana/grafana:10.4.2`), redeploy |
| Config-only stacks | `homelab-observe-services`, `homelab-edge-services` as a whole | No | Same as above, at the repo/stack level | `git checkout` previous tag of the *config repo* → redeploy — config is what changes, not an image |
| Custom applications | BottleBot, discord-gateway | Yes | CI builds → pushes to a registry → `deploy-service` pulls the built image | Pull and run the previous image tag from the registry |

**Confirmed:** discord-gateway is a custom build, so it sits in this row alongside BottleBot — both get `deployment.type: image` and registry-based rollback in `services.yml`.

This means `rollback: image_tag` as a blanket default (v2) is replaced by an explicit per-repo `deployment.type` and `rollback.strategy`, so the deploy engine knows exactly what to do per service rather than assuming one mechanism fits all.

### 6.2 Schema (revised)

**Config-only / upstream-image repo (most of the homelab):**
```yaml
repos:
  observe:
    repo: github.com/GreenMachine582/homelab-observe-services
    target_node: homelab-observe
    deployment:
      type: compose
    deploy:
      compose_files: [docker-compose.yml]
    rollback:
      strategy: git
    services: [grafana, prometheus, loki, alertmanager, uptime-kuma]
```

**Config-only repo with Infisical-sourced secrets (edge services — see §10):**
```yaml
repos:
  homelab-edge-services:
    repo: github.com/GreenMachine582/homelab-edge-services
    target_node: homelab-edge
    deployment:
      type: compose
    deploy:
      compose_files: [docker-compose.yml]
      # MUST be rolling — cloudflared is the remote-access lifeline.
      # deploy-service must enforce `up -d --remove-orphans` and never
      # call `docker compose down` for this stack (dropping cloudflared
      # would cut the Cloudflare Tunnel and SSH access mid-session).
      strategy: rolling
    secrets:
      infisical:
        # deploy-service reads /home/homelab/.infisical_runtime_auth.yml
        # (written by Phase 1 bootstrap), calls the Infisical API at
        # http://localhost:8222, fetches each path, and injects the result
        # as the named env var before running docker compose up.
        # Secrets are never written to the service repo or to disk.
        - path: /prod/cloudflare/TUNNEL_TOKEN
          env: TUNNEL_TOKEN
        - path: /prod/pihole/WEB_PASSWORD
          env: PIHOLE_WEB_PASSWORD
    rollback:
      strategy: git
    services: [cloudflared, caddy, pihole, pihole-exporter, node-exporter, portainer-agent]
```

**Custom application repo (builds and pushes an image):**
```yaml
repos:
  bottlebot:
    repo: github.com/GreenMachine582/BottleBot
    ref: master                      # or a pinned tag, e.g. v1.2.3
    target_node: homelab-svc-02
    path: /srv/services/bottlebot

    deployment:
      type: image
      image: ghcr.io/greenmachine582/bottlebot

    env:
      inherit: [edge]
      overrides: [bottlebot.env]   # injected at deploy time, never committed

    deploy:
      compose_files: [docker-compose.yml]
      pre_hook: [scripts/predeploy.sh]
      post_hook: [scripts/postdeploy.sh]

    healthchecks:
      - http://localhost:8080/health

    rollback:
      strategy: image
      registry: ghcr.io
      keep: 5
```

GitHub Container Registry (`ghcr.io`) is the natural choice for any service in the "custom application" row — free for public images, integrates directly with GitHub Actions, immutable tags, no extra infrastructure to stand up. Only services that actually build a custom image need this; everything else in the config-only/upstream row never touches a registry at all.

### 6.3 `deploy-service` — CLI design

Runtime: **Python** (decided). Runs **only on `homelab-edge`** (decided) — consistent with Ansible's existing control-node pattern, and necessary because other nodes aren't guaranteed to have Ansible installed. Reaches target nodes over **SSH via Tailscale**, matching the existing Tailscale-only routing approach already used elsewhere in the homelab.

Draft interface:

```
deploy-service deploy <repo> [--ref <tag>] [--dry-run]
    Reads the named repo's entry from services.yml, pulls/checks out the
    given ref (default: latest per the registry entry), layers env files,
    runs pre_hook, performs the deploy (compose pull+up for type=compose,
    or pull image + compose up for type=image), runs post_hook, then
    polls healthchecks. --dry-run prints the planned actions without
    executing them.

deploy-service rollback <repo> [--to <tag>] [--dry-run]
    Mechanism depends on the repo's rollback.strategy:
      - strategy: git    → checks out the previous (or --to) git tag of
                           the config repo and redeploys
      - strategy: image  → pulls and runs the previous (or --to) image
                           tag from the registry, no git operation needed

deploy-service status [<repo>]
    Reports currently deployed ref/tag per repo (or all repos), and last
    deploy/rollback timestamp. Useful for confirming what's actually
    running before deciding whether to roll back.
```

Rationale for shape: `deploy <repo>` and `rollback <repo>` as separate verbs (rather than one command with a `--rollback` flag) keeps the dangerous operation explicit and easy to grep for in logs. `--dry-run` is included from the start given this tool will eventually be triggered by a webhook with no human in the loop — a planning mode is cheap to add now and far more useful before that point than after an incident. `status` is a small addition but closes the loop on "what's actually deployed right now," which `services.yml` alone (a declared intent, not observed state) can't answer.

This CLI is intentionally **orchestrator-agnostic** — it doesn't know or care whether it was invoked by n8n, Camunda, or a human typing the command directly. That's what keeps the Camunda-vs-n8n question (§6.4) safely deferrable.

### 6.4 Decided / confirmed items

- **Registry stays central** (`services.yml` in the bootstrap repo), not distributed as self-describing manifests inside each service repo. `edge → registry → repo` is simpler to operate than `repo → manifest → edge` at this scale.
- **Deployment trigger auth is layered, not a single shared secret.** Rotation of a header secret is dropped as the primary mechanism for now. Auth is instead three gates, each catching a different failure mode:
  1. **Origin whitelisting, checked by the automation itself, not the network/ingress layer.** Camunda (or whatever receives the webhook first) inspects the request's source — GitHub's published webhook IP ranges for CI-triggered deploys, plus localhost/Tailscale-internal addresses for manual triggers — and rejects anything else *in-process*, before a process instance is even created. This is deliberately not a Caddy ACL or firewall rule: an in-process check shows up natively in Camunda's process/audit history, where a network-layer drop wouldn't, and it keeps the whole auth model in one place to reason about rather than split across infra and application layers.
  2. **Approval gate (Camunda)** — a request from a whitelisted origin starts a process that sits at a human approval step (BPMN user task) before `deploy-service` is ever invoked. A passing origin check gets you a pending approval, not a deploy.
  3. **Scheduling constraints** — see the dedicated breakdown below.

  Net effect: no single secret carries all the weight. A request still needs to clear origin check, human approval, and scheduling before anything runs.
- **Camunda replaces n8n as the deploy trigger/approval front door.** Confirmed direction: Camunda natively models approval gates (BPMN user tasks), which n8n would only support via workarounds. n8n may still sit behind Camunda for the actual outbound call to `deploy-service` if that's convenient, but Camunda becomes what receives the webhook and gates the deploy. Because `deploy-service` is orchestrator-agnostic (§6.3), this can be finalized at any point without changing the tool itself.

### 6.5 Scheduling design — maintenance window, serialization, and dependencies

Camunda 8's native primitives map cleanly onto both scheduling requirements and the dependency idea, without needing custom infrastructure:

**Maintenance window.** Modeled as a condition check at (or just after) the approval user task — when the approver submits the form, a gateway evaluates whether the current time falls inside the allowed window (configurable centrally, e.g. a cron-style range in `services.yml` or a Camunda process variable, rather than hardcoded per-process). **Decided: an approval expires after 5 business days (configurable) if it hasn't executed by then** — handled via a non-interrupting timer boundary event on the approval task. If the timer fires before the deploy has run (e.g. it's still waiting for a maintenance window or was blocked by the serialization lock), the approval lapses and the request needs re-approval rather than firing against a possibly-stale `ref` weeks later.

**Serialization (one deploy at a time).** Best mapped to Zeebe's native message correlation behavior rather than a custom lock file: if a deploy process is started via a message with a fixed correlation key (e.g. `"global-deploy-lock"`), a second deploy request with the same key won't start a new instance while one is already active — Zeebe rejects the correlation outright. **Decided: a concurrent/duplicate request is rejected, not queued**, and the rejection response includes the reason (deploy already in progress, including which service/ref is currently running) so it's both actionable for whoever sent the request and auditable in Camunda's history rather than a silent drop.

**Service dependencies — considered, dropped.** A `depends_on` field in `services.yml` was sketched in an earlier round, but services in this homelab are deliberately built to run independently — no shared startup ordering or runtime calls between them at deploy time — so there's no actual dependency to encode. Removed from the schema. The real cross-service concern is host-level state during bootstrap, which the bootstrap lock below already covers.

**Bootstrap lock.** The same serialization mechanism extends naturally to a second use: block service deploys to a node while an Ansible bootstrap run is in progress (or has just started) on that node, since bootstrap changes host-level state (users, firewall, Docker itself) that a concurrent service deploy could race against. This can use the identical message-correlation-key pattern, scoped per-node (e.g. `"bootstrap-lock-homelab-svc-01"`) rather than globally — so a bootstrap run on `svc-01` blocks deploys to `svc-01` specifically without affecting deploys elsewhere. Concretely, the bootstrap playbook would need to publish a "bootstrap started" / "bootstrap finished" message around its run, which Camunda's deploy process checks (or subscribes to) before proceeding — a small addition to the existing bootstrap playbooks, not a new subsystem.

---

## 🖧 7. Clustering by node role vs. per-service repos (resolved heuristic)

Raised directly by the repo owner: some services are too small to justify their own repo, and clustering by node role may be more appropriate in places. Validated and refined.

**Primary heuristic — "deployment unit":** a repo should represent a set of services that are deployed together, upgraded together, rolled back together, and backed up together. If all four are true for a group of services, they belong in one repo regardless of individual size.

**Secondary lens — lifecycle/sharing intent:** kept alongside the primary heuristic, not replaced by it, because deployment-unit alone doesn't fully capture sharing potential. A service could be co-deployed today but still warrant its own repo if it has independent versioning needs or could plausibly be open-sourced or run standalone later (BottleBot is the clear example — it has no operational coupling to anything else in the homelab).

**Default for new/small services:** because service repos are lightweight by design (§5 — no Ansible, just a compose file plus optional hooks), the default for any new service, however small, is its own repo — a single container is not, by itself, a reason to cluster. Clustering is the exception, reserved for services that actually pass the deployment-unit test above. Example: Authentik SSO (`authentik-sso`, §5) is one Compose stack (server, worker, Redis, own Postgres for now) but gets its own repo rather than folding into `camunda-platform` or `n8n-automation`, because it shares no deploy/upgrade/rollback cadence with either, and other services will come to depend on it for auth — an independent deploy/rollback path matters more here than the small size would otherwise suggest.

**Applying both lenses, the resolved split:**
- **`homelab-edge-services`** (clustered): Caddy, Cloudflared, Pi-hole, Unbound — operationally "one appliance," same deploy/upgrade/rollback/backup cycle, no independent lifecycle or sharing intent.
- **`homelab-observe-services`** (clustered): Grafana, Prometheus, Loki, Alertmanager, Uptime Kuma, ntfy — same reasoning, one appliance.
- **svc-01 splits further rather than clustering**: `camunda-platform`, `n8n-automation`, `discord-gateway` as separate repos, since they have different upgrade cadences, backup requirements, and failure domains — they fail the "deployment unit" test even though they currently live in one compose file.
- **BottleBot**: separate repo, no clustering — proof-of-concept for the whole pattern.
- **`authentik-sso`**: separate repo despite being small — see "Default for new/small services" above.

This resolves the original open question from v1: the schema in §6 already supports this via `repos:` → nested `services:`, so no further schema work is needed to accommodate clustering.

---

## 🌿 8. Branch plan (revised sequencing)

**Sequencing reversed from v1** based on validation: build and prove `deploy-service` + `services.yml` *before* moving any repo content. This means the existing deploy paths (Ansible/Phase 4) keep working untouched while the new mechanism is built and proven, so rollback to the current state is trivial at every stage rather than only at the end.

1. **Phase 1 — build the mechanism, in place.** Build `deploy-service` and `services.yml` inside the existing `HomeLab` monorepo, without moving anything yet. Confirm the webhook auth (custom headers, validated by n8n) and secrets injection path work end-to-end against a no-op or trivial target. Also in this phase: rename `docker-compose.edge.yml` → `docker-compose.bootstrap-edge.yml` and strip the network appliance services from it (they'll exist temporarily in neither compose until `homelab-edge-services` is stood up in Phase 4 — on a live node, coordinate this rename with a deploy window). Update `roles/infisical`, `roles/semaphore`, and `bootstrap_edge.yml` to reference the new filename.
2. **Phase 2 — convert one service.** Extract BottleBot into its own repo (it's new, has no production dependents, and was always going to be standalone).
3. **Phase 3 — prove the mechanism against it.** Deploy BottleBot through `deploy-service` end-to-end: webhook → (Camunda or n8n, per §6.4) → `deploy-service` → pull/layer-env/hooks/compose-up/healthcheck. BottleBot is a "custom application" per §6.1, so confirm its image-based rollback works by deliberately rolling back to a previous `ghcr.io` tag at least once.
4. **Phase 4 — convert the rest, one at a time.** ✅ `homelab-edge-services` (network appliance tier — live). ✅ `homelab-observe-services` (extracted, registered; deploy-verify pending live node). ✅ `camunda-platform` / `n8n-automation` (extracted, registered; deploy-verify pending `homelab-svc-01` bootstrap). Remaining: `discord-gateway`, gated on the B6 keep/remove decision — independent of the other splits.
   > Note: the `docker-compose.edge.yml` → `docker-compose.bootstrap-edge.yml` rename described in Phase 1 was intentionally deferred — the appliance service strip achieves the same isolation without requiring a filename change and reference update across bootstrap roles. The rename can be revisited in Phase 5.
5. **Phase 5 — retire the old path.** Once all services are migrated and stable, remove the old direct `ansible-playbook`-driven deploy logic for services (bootstrap-level Ansible roles stay, per §4). Specifically: delete `roles/edge_services/`, delete `playbooks/deploy_edge.yml`, update `playbooks/update_all.yml` and `playbooks/backup.yml` to cover bootstrap-tier services only (Infisical, Semaphore).
6. **Throughout:** keep README/BOOTSTRAP.md/NODES.md updated as structure stabilizes, rather than as a single end-of-migration step.

This order means nothing is moved out of the working monorepo until there's a proven replacement for it.

---

## ✂️ 10. Edge node compose split in detail

The current `docker-compose.edge.yml` bundles two tiers that have different owners after the split. This section records exactly what goes where and the implications for bootstrap sequencing.

### 10.1 The two tiers today

| Container(s) | Tier | After split |
|---|---|---|
| `cloudflared` | Network appliance | ✅ `homelab-edge-services` |
| `caddy` | Network appliance | ✅ `homelab-edge-services` |
| `pihole`, `pihole-exporter` | Network appliance | ✅ `homelab-edge-services` |
| `portainer-agent` | Network appliance | ✅ `homelab-edge-services` |
| `node-exporter` | Network appliance | ✅ `homelab-edge-services` |
| `infisical`, `infisical-db`, `infisical-redis` | Bootstrap control plane | `docker-compose.edge.yml` (stays) |
| `semaphore`, `semaphore-db` | Bootstrap control plane | `docker-compose.edge.yml` (stays) |

Infisical and Semaphore are prerequisites for `deploy-service` — Infisical supplies secrets and Semaphore provides the UI that drives deployments. Managing them via `deploy-service` would be circular. They must remain bootstrap-resident.

### 10.2 The bootstrap compose (`docker-compose.bootstrap-edge.yml`)

Stays in the HomeLab repo. Managed solely by Ansible (`roles/infisical`, `roles/semaphore`, `roles/node_exporter`). `deploy-service` never touches this file.

Services:
- `node-exporter` — host metrics; `pid: host` mount; managed by `roles/node_exporter`
- `infisical-db`, `infisical-redis`, `infisical` — secrets manager; env from `/opt/infisical/.env` (node-generated, mode 0600)
- `semaphore-db`, `semaphore` — automation UI; env from `/opt/semaphore/.env`; repo mounted read-only at `/repo` (`.:/repo:ro`), writable workspace at `semaphore_workspace:/tmp/workspace`

Networks after split:
- `infisical_net` — infisical ↔ its db/redis (isolated)
- `semaphore_net` — semaphore ↔ its db (isolated)
- `bootstrap_net` — replaces the old `edge_net` for semaphore↔infisical communication (semaphore calls the Infisical API at `http://infisical:8080`)

The old `edge_net` bridge no longer exists after the split. Services in the bootstrap compose and the services compose run in separate Docker networks by design — they don't need to talk to each other at the container level.

### 10.3 The `homelab-edge-services` compose

Lives in its own repo. Managed by `deploy-service`. First deployed via `deploy-service deploy homelab-edge-services` during Phase 4 of §8.

Services:
- `cloudflared` — Cloudflare Tunnel; needs `TUNNEL_TOKEN` from Infisical
- `caddy` — LAN reverse proxy; static `Caddyfile` (no more Jinja2 templating)
- `pihole` — DNS server; needs `PIHOLE_WEB_PASSWORD` from Infisical; `cap_add: NET_ADMIN`
- `pihole-exporter` — Pi-hole Prometheus metrics
- `node-exporter` — host Prometheus metrics (port 9100)
- `portainer-agent` — connects to Portainer Server on homelab-observe

Config files (Caddyfile, cloudflared config, pihole custom DNS lists) become static files in the repo, not Ansible templates. Values that were previously `group_vars` inputs to Jinja2 (caddy routes, cloudflared ingress rules, pihole custom DNS) move into the service repo as committed config.

### 10.4 Network topology change

The current `edge_net` bridge connects node-exporter, cloudflared, caddy, pihole, AND infisical/semaphore in one flat network. This is cleaned up as part of Phase 1's compose rename:

- `bootstrap-edge` compose gets `bootstrap_net` (replaces `edge_net` for semaphore↔infisical)
- `homelab-edge-services` compose gets its own `edge_net` (isolated; the name can be reused since it's a different compose project)
- No cross-compose container-name DNS resolution needed — the two tiers don't communicate at the Docker network level

### 10.5 Phase 1 bootstrap scope change

After the rename + strip, `bootstrap_edge.yml` no longer invokes `roles/edge_services` at the end. Phase 1 ends with: system hardening → Docker → users → firewall → Tailscale → **Infisical + Semaphore** (and Unbound, which is systemd not Docker). The network appliance layer (cloudflared, Caddy, Pi-hole) comes up for the first time when `deploy-service deploy homelab-edge-services` runs in Phase 4.

Consequence: between Phase 1 and Phase 4, the edge node has no Cloudflare Tunnel active and no Pi-hole DNS. This is fine during initial setup (bootstrap uses direct SSH; no LAN clients depend on Pi-hole yet), but on a **live rebuilt node** Phase 4 should be run immediately after Phase 1 to restore DNS and tunnel access.

### 10.6 Cloudflared rolling-deploy constraint

Cloudflared maintains the Cloudflare Tunnel. If it exits, all remote access via the tunnel is severed immediately. `deploy-service` **must** use `docker compose up -d --remove-orphans` for any stack containing cloudflared — never `docker compose down`. This is enforced by the `strategy: rolling` field in the `services.yml` entry (§6.2) and must be a hard invariant in `deploy-service`'s compose implementation, not just documentation. A deploy that accidentally calls `compose down` on the edge stack would cut SSH access mid-session.

### 10.7 Roles retired after Phase 4 completion

| Role / playbook | Retirement trigger | Replacement |
|---|---|---|
| `roles/edge_services/` | `homelab-edge-services` stable | ✅ Deleted — templates are now static config files in `homelab-edge-services` |
| `playbooks/deploy_edge.yml` | All services migrated (Phase 5) | Retained for now — calls `deploy-service deploy homelab-edge-services`; Semaphore "Deploy Edge" template references it |
| `playbooks/update_all.yml` (service sections) | All services migrated | Narrows to bootstrap-tier only (Infisical, Semaphore image updates) |
| `playbooks/backup.yml` (service sections) | All services migrated | Narrows to bootstrap-tier DBs; each service repo owns its own backup |

`roles/infisical` and `roles/semaphore` are **not** retired — they are permanent bootstrap roles.

---

## 📝 9. Remaining open items for the repo owner to confirm

- ~~Camunda's role in the standard deploy path~~ — **resolved in direction**: Camunda becomes the deploy trigger/approval front door, replacing n8n in that specific role.
- ~~`deploy-service` language/runtime~~ — **closed**: Python.
- ~~`deploy-service` CLI interface~~ — **closed**: see §6.3 for the drafted `deploy` / `rollback` / `status` interface.
- ~~`deploy-service` execution location~~ — **closed**: runs only on `homelab-edge`, reaches other nodes over SSH via Tailscale.
- ~~Image registry/build path~~ — **closed**: `ghcr.io` for the "custom application" row (BottleBot, discord-gateway). Everything else never touches a registry.
- ~~Webhook header secret + rotation~~ — **dropped**: superseded by the three-gate auth model in §6.4.
- ~~Origin whitelist enforcement point~~ — **closed**: in-process, inside the automation (Camunda) itself, not at the network/Caddy layer — chosen specifically for unified audit visibility.
- ~~Scheduling mechanism~~ — **closed in design**: maintenance window via a gateway check (and optionally a timer boundary event for approval expiry) on the approval user task; serialization via Zeebe message correlation keys, which provide mutual exclusion as an engine guarantee rather than a custom lock. See §6.5.
- ~~Queue vs. reject behavior for a second concurrent deploy~~ — **closed**: rejected outright, with the reason (which service/ref is currently running) returned for both the requester and the audit trail.
- ~~Approval expiry behavior~~ — **closed**: expires after 5 business days (configurable), via a timer boundary event on the approval task — re-approval required after that.
- ~~`depends_on`~~ — **dropped**: services run independently by design, so there's nothing to encode. See §6.5.
- ~~Small/new-service repo default~~ — **closed**: a service defaults to its own repo unless it demonstrably shares deploy/upgrade/rollback/backup cadence with an existing repo — size alone isn't a reason to cluster. See §7.
- **Bootstrap-lock signaling — fully resolved**, implementation gated on `camunda-platform` being deployed and live:
  - **Ansible side** (`bootstrap_node.yml`): two `ansible.builtin.uri` tasks — "bootstrap started" in `pre_tasks`, "bootstrap finished" in `post_tasks`, both `ignore_errors: true`. Endpoint: Zeebe REST API at `http://{{ ip_svc_01 }}:8080/v1/message/publication`. Correlation key: `"bootstrap-lock-{{ inventory_hostname }}"` (e.g. `"bootstrap-lock-homelab-svc-01"`). **Auth: none at the app level** — both `homelab-edge` and `homelab-svc-01` are already-trusted internal nodes on the Tailscale-only network, the same trust boundary already relied on for Infisical/Semaphore; no bearer token or Keycloak/Identity stack needed for a call between nodes that already trust each other.
  - **`bootstrap_edge.yml`**: explicitly excluded — Phase 1 runs before Camunda exists, and a first bootstrap has no concurrent deploys to race against. A comment in the playbook documents this.
  - **Camunda BPMN side**: no new query surface. The deploy process gains a second Zeebe message-correlation gate — alongside the existing global `"global-deploy-lock"` gate from §6.5 — dynamically keyed to `"bootstrap-lock-<target-node>"`. Zeebe's existing "a second correlation on the same key is rejected outright" behavior, already relied on for deploy-vs-deploy exclusion, handles bootstrap-vs-deploy exclusion identically — no Operate/REST query gateway, no new mechanism, just a second correlation attempt at the same point in the flow. Design and implementation deferred until `camunda-platform` is live (see Milestone D1) and a BPMN process is actually deployed to it — the Ansible tasks above are inert until the BPMN side is wired.
  - **Stale-lock timeout**: a timer boundary event on the bootstrap-lock process instance (~30-60 minutes — bootstrap runs are minutes, not the 5-business-day approval-expiry window from §6.5) auto-releases the lock if "bootstrap finished" never arrives, so a crashed or interrupted bootstrap run can't permanently block future deploys to that node.
  - Both sides land together — no partial implementation beforehand.