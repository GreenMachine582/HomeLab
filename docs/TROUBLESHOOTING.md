# Troubleshooting

Common issues, diagnostic commands, and recovery procedures. Organised by area.

<!-- TOC -->
* [Troubleshooting](#troubleshooting)
  * [General Diagnostics](#general-diagnostics)
  * [SSH & Connectivity](#ssh--connectivity)
    * [Cannot SSH to a node](#cannot-ssh-to-a-node)
    * [Ansible cannot reach a node](#ansible-cannot-reach-a-node)
  * [Ansible](#ansible)
    * [Playbook fails mid-run](#playbook-fails-mid-run)
    * [Vault decryption error](#vault-decryption-error)
    * ["sudo: a password is required" during bootstrap](#sudo-a-password-is-required-during-bootstrap)
  * [Docker & Containers](#docker--containers)
    * [A container is not running](#a-container-is-not-running)
    * [Container is in a crash loop](#container-is-in-a-crash-loop)
    * [Docker daemon not starting](#docker-daemon-not-starting)
    * [Redeploying a single service](#redeploying-a-single-service)
  * [DNS (Pi-hole & Unbound)](#dns-pi-hole--unbound)
    * [DNS resolution not working for a LAN client](#dns-resolution-not-working-for-a-lan-client)
    * [Unbound not resolving upstream](#unbound-not-resolving-upstream)
    * [A `.homelab.local` hostname is missing](#a-homelablocal-hostname-is-missing)
  * [Tailscale](#tailscale)
    * [Node not appearing in Tailscale admin console](#node-not-appearing-in-tailscale-admin-console)
    * [Cannot reach a node over Tailscale](#cannot-reach-a-node-over-tailscale)
  * [Infisical & Semaphore](#infisical--semaphore)
    * [Bootstrap playbook reports Infisical already initialised — nothing provisioned or seeded](#bootstrap-playbook-reports-infisical-already-initialised--nothing-provisioned-or-seeded)
    * [Bootstrap instance/seed step fails with an authentication or 4xx/5xx error](#bootstrap-instanceseed-step-fails-with-an-authentication-or-4xx5xx-error)
    * [Vault → Infisical conversion status](#vault--infisical-conversion-status)
    * [Outstanding hardening tasks (not yet implemented)](#outstanding-hardening-tasks-not-yet-implemented)
  * [Cloudflare Tunnel](#cloudflare-tunnel)
    * [External services not reachable](#external-services-not-reachable)
  * [Monitoring Stack](#monitoring-stack)
    * [Grafana showing no data](#grafana-showing-no-data)
    * [Alertmanager not sending notifications](#alertmanager-not-sending-notifications)
  * [Databases](#databases)
    * [PostgreSQL not starting](#postgresql-not-starting)
    * [Restoring a PostgreSQL backup](#restoring-a-postgresql-backup)
    * [Elasticsearch heap pressure](#elasticsearch-heap-pressure)
  * [Automated Deploys (Phase 4)](#automated-deploys-phase-4)
    * [Deploy not triggering after a push to main](#deploy-not-triggering-after-a-push-to-main)
    * [Manual deploy fallback](#manual-deploy-fallback)
  * [Disaster Recovery](#disaster-recovery)
    * [Edge node SD card failure](#edge-node-sd-card-failure)
    * [Any other node failure](#any-other-node-failure)
    * [Complete homelab loss](#complete-homelab-loss)
<!-- TOC -->

---

## General Diagnostics

Quick health check across all nodes:

```bash
# From homelab-edge
ansible all -m ping

# Check all Docker services on a node
ssh admin@<node>
docker ps -a

# Check systemd services
systemctl status tailscaled
systemctl status docker

# Check disk space
df -h

# Check memory
free -h

# Check recent logs (last 100 lines, all units)
journalctl -n 100 --no-pager
```

Run the healthcheck playbook for a full sweep:

```bash
ansible-playbook playbooks/healthcheck.yml
```

---

## SSH & Connectivity

### Cannot SSH to a node

**Check 1 — Is the node reachable?**
```bash
ping 192.168.1.<x>
```

If no ping response: check the node is powered on, Ethernet is connected, and the router shows a DHCP lease.

**Check 2 — Is SSH running?**
```bash
ssh -v admin@192.168.1.<x>
```

Verbose output will indicate whether the connection is refused (service down) or timing out (network issue).

**Check 3 — Is fail2ban blocking you?**
```bash
# SSH in from a different IP or via console, then:
sudo fail2ban-client status sshd
sudo fail2ban-client set sshd unbanip <your-ip>
```

**Check 4 — Are you using the right key?**
```bash
ssh -i .ssh/homelab-edge admin@homelab-edge.local
```

### Ansible cannot reach a node

```bash
# Test connectivity
ansible <node> -m ping

# Run with verbose output
ansible-playbook playbooks/healthcheck.yml -vvv
```

Common causes: wrong IP in `host_vars/`, SSH key not deployed to the node, firewall blocking `ssh_port` from edge.

---

## Ansible

### Playbook fails mid-run

Ansible is idempotent — re-running a playbook is always safe. Fix the underlying issue and re-run:

```bash
ansible-playbook playbooks/<playbook>.yml
```

To resume from a specific task after a failure:

```bash
ansible-playbook playbooks/<playbook>.yml \
  --start-at-task "Task name here"
```

### Vault decryption error

```
ERROR! Decryption failed (no vault secrets would decrypt)
```

Cause: wrong `.vault_pass` file or the vault was created with a different password.

```bash
# Test vault access
ansible-vault view inventories/group_vars/all/vault.yml
```

If access fails, the password is wrong. If the vault file is lost or corrupted, recreate it from `inventories/group_vars/all/vault.yml.example` — the vault is gitignored and cannot be restored from git.

### "sudo: a password is required" during bootstrap

The bootstrap playbook uses the `admin` user whose sudo password is read from the vault (`vault_admin_become_password`). If that variable is missing or wrong, add it to the vault and retry:

```bash
ansible-vault edit inventories/group_vars/all/vault.yml
ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge.yml
```

After bootstrap, subsequent playbooks use the `homelab` user with passwordless sudo.

---

## Docker & Containers

### A container is not running

```bash
# Check status and exit code
docker ps -a

# View container logs
docker logs <container-name> --tail 50

# Inspect the container for error details
docker inspect <container-name>
```

Common causes: port conflict, missing environment variable, volume permissions, out of memory (OOM kill).

**OOM kill** — check with:
```bash
journalctl -k | grep -i "oom\|killed"
```

If a container is being OOM-killed, reduce its memory allocation in the Compose file or free up memory by stopping unused containers.

### Container is in a crash loop

```bash
docker logs <container-name> --tail 100
```

Check logs for the actual error before restarting. A crash loop usually indicates a configuration or dependency issue — restarting without fixing the root cause will loop indefinitely.

If a dependency is not ready (e.g. Camunda waiting for Elasticsearch):

```bash
# Start dependencies first
docker compose --profile databases up -d

# Wait for health checks
docker compose ps

# Then start the dependent service
docker compose --profile camunda up -d
```

### Docker daemon not starting

```bash
systemctl status docker
journalctl -u docker --no-pager -n 50
```

Common cause on RPi: SD card I/O errors. Check:
```bash
dmesg | grep -i "i/o error\|mmcblk"
```

If SD card errors appear, the card may be failing. Follow the edge node disaster recovery procedure.

### Redeploying a single service

Do not use `docker compose up` manually — Ansible manages Compose files. To redeploy a single service:

```bash
ansible-playbook playbooks/deploy_<node>.yml \
  --tags <service-tag>
```

---

## DNS (Pi-hole & Unbound)

### DNS resolution not working for a LAN client

**Check 1 — Is Pi-hole running?**
```bash
ssh admin@homelab-edge
docker ps | grep pihole
```

**Check 2 — Test resolution directly against Pi-hole**
```bash
dig @<ip_edge> grafana.homelab.local
dig @<ip_edge> example.com
```

If `grafana.homelab.local` fails but `example.com` resolves, the `custom.list` entry is missing or Pi-hole needs to be reloaded:

```bash
docker exec pihole pihole restartdns
```

**Check 3 — Is the client using Pi-hole as its DNS server?**

The client's DNS must point to `ip_edge`. Check DHCP config on the router.

### Unbound not resolving upstream

```bash
# Test Unbound directly
dig @127.0.0.1 -p 5335 example.com

# Check Unbound logs
docker logs unbound --tail 50
```

If Unbound is failing, Pi-hole will fall back to its configured upstream (if any). Check `host_vars/homelab-edge.yml` for the Unbound port config.

### A `.homelab.local` hostname is missing

Hostnames are defined in `templates/pihole/custom.list.j2`. If a hostname is missing:

1. Add it to the template
2. Redeploy:
   ```bash
   ansible-playbook playbooks/deploy_edge.yml --tags pihole
   ```

---

## Tailscale

> See [NETWORK.md](./NETWORK.md#tailscale) for firewall rules, ACL policy, and Tailscale access URLs for Infisical/Semaphore.

### Node not appearing in Tailscale admin console

```bash
systemctl status tailscaled
journalctl -u tailscaled --no-pager -n 50
```

Common cause: auth key expired. Re-authenticate:

```bash
sudo tailscale up --authkey=<new-key>
```

Update the key in `inventories/group_vars/all/vault.yml` and re-run the deploy playbook to keep it in sync.

### Cannot reach a node over Tailscale

**Check 1 — Is the node connected?**
```bash
tailscale status
```

All nodes should appear with a direct connection. If a node is missing, SSH to it over LAN and check:

```bash
ssh admin@192.168.1.<x>
systemctl status tailscaled
journalctl -u tailscaled --no-pager -n 50
```

**Check 2 — Has the auth key expired?**

```bash
sudo tailscale up --authkey=<new-key>
```

Update the key in `inventories/group_vars/all/vault.yml` and re-run the node's deploy playbook to keep it in sync.

**Check 3 — ACL blocking the connection?**

Review ACLs in the Tailscale admin console. See `docs/NETWORK.md` for the recommended ACL policy. Remember that each node has its own Tailscale IP — ensure ACL rules reference node IPs or tags directly, not just the subnet route.

---

## Infisical & Semaphore

Both run on `homelab-edge`, **Tailscale-only** (no Pi-hole hostname — see [NETWORK.md](./NETWORK.md#tailscale) for firewall rules and access URLs).
Browser access: `https://homelab-edge.<tailnet>.ts.net:8443` (Infisical) / `:8444` (Semaphore).
Direct non-browser access: `http://<edge-tailscale-ip>:8222` / `:3010`.
If you can't reach either path, start with the [Tailscale](#tailscale) checks above — connectivity issues here are almost always "the requesting device isn't on the tailnet" or "ACL/firewall blocks the port," not the containers themselves.

### Bootstrap playbook reports Infisical already initialised — nothing provisioned or seeded

This is expected on every run after the first — not a failure. The entire
provision-and-seed block (`roles/infisical/tasks/bootstrap_instance.yml`) is
gated on the one-shot `POST /v1/admin/bootstrap` call's own result: a fresh,
uninitialised instance returns `200` with an instance-admin token, and in that
single pass the play provisions the org, admin account, project, environment,
folders, and read-only `runtime` identity; seeds every `[seed → ...]`
application secret from `vault.yml` into its mapped
`/production/<folder>/<KEY>` path; and writes the `runtime` identity's
freshly-minted credentials straight to `/home/homelab/.infisical_runtime_auth.yml`.
Once that's happened, the same call returns a non-`200` status
("already initialised") and the **entire** block is skipped — there's nothing
left to provision, and there's no longer an admin token available to
authenticate a re-seed with (the one-shot call only returns one the first
time). A `debug` message in `bootstrap_instance.yml` confirms the skip and
explains why; see that file's header comment for the full "why this is gated
on the bootstrap call's own result" rationale.

**Need to add a brand-new application secret later?** The playbook's
provisioning-and-seed block is now permanently a no-op against an initialised
instance, so re-running it won't pick up new entries you add to
`_infisical_seed_map`. Add the secret directly via the Infisical web UI
instead — it's Tailscale-reachable at `http://<edge-tailscale-ip>:8222`,
trivial for occasional one-offs. See [What the Bootstrap Playbook
Does](../BOOTSTRAP.md#what-the-bootstrap-playbook-does) for the full
"adding a new service" checklist (vault entry, seed-map entry, folder, etc.).

### Bootstrap instance/seed step fails with an authentication or 4xx/5xx error

```bash
# From the edge node — confirm the API is actually up
curl -sf http://127.0.0.1:8222/api/status

# Re-run just the provision-and-seed step with verbose output (only does
# anything against a FRESH/uninitialised instance — see the skip behavior above)
cd /opt/homelab
ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge.yml \
  --tags infisical,bootstrap -vvv
```

Likely causes:
- **Project/environment/folder slug mismatch** — `infisical_seed_project_slug` / `infisical_seed_environment` / `infisical_seed_folders` (`roles/infisical/defaults/main.yml`, default `homelab` / `production` / the nine folders in the "Secret naming convention" block in `vault.yml.example`) drive *both* what `bootstrap_instance.yml` provisions and what the lookup tasks expect — they should always agree by construction now. A mismatch here would mean one of those defaults was edited without the other, or Infisical's instance was provisioned by some other means.
- **API shape drift** — `bootstrap_instance.yml`'s endpoint paths, payload shapes, and response field paths (the one-shot bootstrap call, project/environment/folder/identity creation, Universal Auth attach + client-secret generation, and the `/v3/secrets/raw/...` seed routes) are all version-pinned assumptions, flagged with a `⚠️` comment at the top of that file. Check them against the deployed Infisical version's API reference if errors mention unexpected fields or 404s on routes that should exist.
- **Mid-run failure leaves a half-provisioned instance** — because the whole block runs at most once (gated on the one-shot bootstrap call returning `200`), a failure partway through (e.g. folders created but identity creation fails) can't simply be retried with a second `ansible-playbook` run — the next attempt sees an already-initialised instance and skips everything, then fails at Semaphore with a confusing error. The bootstrap playbook will now `fail:` immediately at the Infisical step with the exact recovery command. Recovery: re-run Phase 1 with `--extra-vars infisical_reset=true`:
  ```bash
  ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge.yml \
    --extra-vars infisical_reset=true
  ```
  This stops and removes the Infisical containers and their named volumes, removes any stale credentials file, then re-provisions everything from scratch in the same pass. `/opt/infisical/.env` is **not** wiped — its encryption key and DB/Redis passwords carry over to the fresh Postgres container automatically. See `roles/infisical/tasks/bootstrap_instance.yml` and `playbooks/bootstrap_edge.yml` for the full rationale.

The application-secret seed itself is **additive and idempotent** — on a
successful run it never overwrites or deletes an existing key, so retrying
(against a fresh instance) after a fix is always safe.

### Vault → Infisical conversion status

`vault.yml` currently serves two roles: a `[bootstrap]` source for secrets
Ansible needs directly (read before Infisical can exist), and a `[seed →
/production/<folder>/<KEY>]` source that the Phase 1 seed task pushes into
Infisical once.

**One playbook has been converted as a reference implementation:**
`deploy_edge.yml` (Phase 2) resolves `cloudflare/TUNNEL_TOKEN` and
`pihole/WEB_PASSWORD` from Infisical at runtime via `roles/infisical/tasks/lookup.yml`,
using the read-only `runtime` machine identity provisioned during Phase 1
(`/home/homelab/.infisical_runtime_auth.yml`). See [CLAUDE.md §"Secrets"](../CLAUDE.md#secrets)
for the full design rationale.

**Everything else remains unconverted** — Stage 1 (`bootstrap_edge.yml`, run
from WSL where `vault.yml` lives) and every Stage 3+ playbook
(`deploy_svc.yml`, `healthcheck.yml`, `update_all.yml`,
`backup.yml`, `rollback.yml`, `apply_firewall.yml`) still resolve every
`{{ vault_<service>_<field> }}` lookup straight from the vault, exactly as
before this migration. The full `secret_backend` helper abstraction mentioned
in `vault.yml.example` (a `vault | infisical` toggle so *any* role could read
from either, generalizing the pattern `roles/infisical/tasks/lookup.yml`
establishes) is **deferred, not implemented** — converting the Camunda stack's
lookups (and others) to go through Infisical at runtime is intentionally out of
scope for this change. Until that lands:

- `vault.yml` remains the source of truth for every unconverted role, and the
  WSL-side seed/fallback source for Infisical
- Infisical holds a parallel, additive copy of application secrets — useful as
  a browsable secret store, an emergency fallback if `vault.yml`/`.vault_pass`
  are lost, the live runtime source for `deploy_edge.yml`/Semaphore, and the
  foundation for the eventual full conversion
- Adding a new application secret means adding it to `vault.yml` **and** to
  `_infisical_seed_map` in `roles/infisical/tasks/bootstrap_instance.yml`
  (plus its folder in Infisical) if you want it seeded too — the two are not
  auto-synced, and (per the section above) the seed only actually *runs*
  against a fresh, uninitialised instance, so an existing instance needs the
  secret added by hand via the Infisical UI. If a converted role (currently
  only `deploy_edge.yml`) needs to read it at runtime, also add its
  `<folder>/<KEY>` path to that play's `infisical_lookup_keys`

### Outstanding hardening tasks (not yet implemented)

These were in scope for the original Infisical/Semaphore design but explicitly
deferred. Tracked here so they have a permanent home.

1. **Disaster-recovery test** — the full `deploy → seed → backup → destroy →
   restore → verify decrypt → verify deploy` rehearsal has not been run against
   live infrastructure. The procedure is documented above under
   [Restoring a PostgreSQL backup](#restoring-a-postgresql-backup); run it once
   on the first real bootstrap and record whether it passes.

2. **Infisical audit logging → Loki** — Infisical's audit log should be shipped
   to Loki via the existing `alloy` role so secret access and edits are
   observable, with Alertmanager rules for unexpected machine-identity auth or
   bulk reads. Not started; requires Infisical-side audit-log config, an `alloy`
   scrape addition, and new Alertmanager rules.

3. **Negative connectivity test** — a script asserting that Infisical (port 8222)
   and Semaphore (port 3010) are unreachable from outside the Tailscale network.
   The UFW enforcement (`tailscale_cgnat_range` source rules) is in place; nothing
   automatically verifies it. Add to `scripts/test_connectivity.sh`.

---

## Cloudflare Tunnel

### External services not reachable

**Check 1 — Is `cloudflared` running?**
```bash
ssh admin@homelab-edge
docker logs cloudflared --tail 50
```

Look for `Connection registered` messages. If the tunnel is disconnected, check the credentials:

```bash
docker exec cloudflared cloudflared tunnel info
```

**Check 2 — Tunnel credentials expired or rotated**

Re-authenticate the tunnel:

1. Log in on the edge node:
   ```bash
   docker exec -it cloudflared cloudflared tunnel login
   ```
2. Update the credentials file path in `host_vars/homelab-edge.yml`
3. Redeploy:
   ```bash
   ansible-playbook playbooks/deploy_edge.yml --tags cloudflared
   ```

**Check 3 — Hostname not configured in tunnel**

Verify the public hostname mapping in `host_vars/homelab-edge.yml` matches what is configured in the Cloudflare dashboard under **Zero Trust → Tunnels**.

---

## Monitoring Stack

### Grafana showing no data

**Check 1 — Are Prometheus and Loki running?**
```bash
ssh admin@homelab-observe
docker ps | grep -E "prometheus|loki"
```

**Check 2 — Are scrape targets healthy?**

Open `http://prometheus.homelab.local:9090/targets` — all targets should show `UP`. A `DOWN` target means `node-exporter` on that node is not reachable from `homelab-observe`.

Fix: ensure the node is running `node-exporter` and port 9100 is open in its firewall:

```bash
ansible-playbook playbooks/deploy_<node>.yml --tags node-exporter
```

**Check 3 — Are Alloy agents shipping logs?**

On the affected node:
```bash
docker logs alloy --tail 50
```

Look for connection errors to `homelab-observe:3100`.

### Alertmanager not sending notifications

```bash
# Check Alertmanager is receiving alerts from Prometheus
# http://alertmanager.homelab.local:9093/#/alerts

# Check Alertmanager logs
ssh admin@homelab-observe
docker logs alertmanager --tail 50
```

Common cause: incorrect Slack webhook URL or API key in `inventories/group_vars/all/vault.yml`. Update the vault and redeploy:

```bash
ansible-vault edit inventories/group_vars/all/vault.yml
deploy-service deploy homelab-observe-services
```

---

## Databases

### PostgreSQL not starting

```bash
ssh admin@homelab-svc-01
docker logs postgres --tail 50
```

Common causes: data directory permissions, out of disk space on NVMe, or a previous unclean shutdown requiring recovery.

Check disk:
```bash
df -h /mnt/nvme
```

If disk is full, clear old backups:
```bash
ls -lh /mnt/nvme/backups/
rm /mnt/nvme/backups/<old-dump>.sql.gz
```

### Restoring a PostgreSQL backup

```bash
# Stop the affected service first
docker compose stop <service>

# Restore
docker exec -i postgres psql -U <db-user> -d <db-name> < /mnt/nvme/backups/<dump>.sql

# Restart
docker compose start <service>

# Verify
docker exec -it postgres psql -U <db-user> -d <db-name> -c "\dt"
```

**Edge node (Infisical / Semaphore):** these each have their own dedicated
Postgres container (no shared `postgres`) and their dumps are gzip-compressed
straight off `pg_dump` into `{{ postgres_backup_dir }}` (`/opt/backups/postgres`
— see `playbooks/backup.yml`), so the restore pipes through `gunzip` first:

```bash
docker compose stop infisical          # or: semaphore

gunzip -c /opt/backups/postgres/infisical_<date>.sql.gz \
  | docker exec -i infisical-db psql -U infisical -d infisical

docker compose start infisical
docker exec -it infisical-db psql -U infisical -d infisical -c "\dt"
```

> **Restoring Infisical also requires `vault_infisical_encryption_key` to be
> the exact value used when the backup was taken** — it's a permanent,
> non-rotatable key (see the comment above it in `vault.yml.example`); a
> mismatched key leaves every secret in the restored database permanently
> undecryptable. If Infisical itself is unrecoverable, fall back to wiping it
> and re-running the bootstrap playbook
> (`ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge.yml`):
> its one-shot `POST /v1/admin/bootstrap` call detects the fresh, empty
> instance and automatically re-provisions everything from scratch — org,
> admin, project, environment, folders, the read-only `runtime` identity —
> re-seeds every application secret straight from `vault.yml` (the canonical
> fallback source), and writes fresh runtime credentials to the node-local
> file. Nothing is printed for you to copy anywhere; the instance is
> immediately usable. See [What the Bootstrap Playbook
> Does](../BOOTSTRAP.md#what-the-bootstrap-playbook-does).

### Elasticsearch heap pressure

If Camunda components are slow or Elasticsearch is logging GC pressure:

```bash
docker logs elasticsearch --tail 50 | grep -i "gc\|heap"
```

Adjust heap in `host_vars/homelab-svc-01.yml`:

```yaml
elasticsearch_heap: "2g"   # Increase if RAM allows; do not exceed 50% of available RAM
```

Redeploy:
```bash
ansible-playbook playbooks/deploy_svc.yml --tags camunda
```

---

## Automated Deploys (Phase 4)

### Deploy not triggering after a push to main

**Check 1 — Did the GitHub workflow run?**

Check **Repository → Actions** in GitHub. If the workflow did not run, check the `deploy.yml` trigger configuration.

**Check 2 — Did the workflow reach the endpoint?**

Check the workflow run log for the `curl` step. A non-2xx response indicates the n8n/Camunda endpoint rejected the request — verify the `DEPLOY_SECRET` header matches what the automation workflow expects.

**Check 3 — Did n8n/Camunda execute the SSH step?**

Check the n8n execution log or Camunda history for the deploy workflow. Look for SSH errors or a failed `deploy.sh` run.

**Check 4 — Did `deploy.sh` succeed?**

On `homelab-edge`, check the Ansible log:
```bash
tail -n 100 /opt/homelab/logs/ansible.log
```

### Manual deploy fallback

If the automated pipeline is broken, deploy manually at any time:

```bash
ssh -p <ssh_port> deploy@homelab-edge
cd /opt/homelab
sudo ansible-playbook playbooks/deploy_edge.yml
deploy-service deploy homelab-observe-services
sudo ansible-playbook playbooks/deploy_svc.yml
```

---

## Disaster Recovery

### Edge node SD card failure

The edge node is the Ansible control node and runs DNS, the Cloudflare Tunnel, and Pi-hole. While it is down:

- **Other nodes remain accessible** — each node has its own Tailscale connection, so you can still SSH to `homelab-observe`, `svc-01`, etc. directly over VPN
- **LAN SSH also works** — connect directly to `ip_observe`, `ip_svc_01` etc. from any device on the same network
- **Internal DNS is down** — `.homelab.local` hostnames won't resolve; use IPs directly until the edge is restored
- **External services are down** — Cloudflare Tunnel runs on the edge; public hostnames will be unreachable
- **Infisical and Semaphore are down** — both run only on the edge. `deploy_edge.yml` cannot run during this window either: it executes locally on the edge *and* depends on Infisical for its runtime secret lookups (see [Vault → Infisical conversion status](#vault--infisical-conversion-status)). There is no automatic fallback to `vault.yml` for converted lookups — recovery is via re-bootstrapping (below), which brings Infisical back up before Phase 2 runs. (Stage 3+ playbooks are unaffected by Infisical being down — they still read `{{ vault_* }}` directly from the WSL-side `vault.yml`.)

**Recovery steps:**

1. Flash a new SD card with RPi OS Lite (64-bit)
2. Boot the edge node and find its IP (check router DHCP)
3. From your PC, run the bootstrap playbook (see `BOOTSTRAP.md` Phase 1):
   ```bash
   ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge.yml
   ```
   This single pass brings Infisical (and Semaphore) back up, and handles
   either recovery path automatically — no credentials to copy anywhere
   either way:
   - **If you still have a usable Postgres backup** (and
     `vault_infisical_encryption_key` is unchanged — see the callout above),
     restore it first (see [Restoring a PostgreSQL
     backup](#restoring-a-postgresql-backup)) so Infisical comes back with its
     existing org/project/folders/identity intact. The one-shot
     `POST /v1/admin/bootstrap` call (`roles/infisical/tasks/bootstrap_instance.yml`)
     detects the non-empty instance, skips provisioning and seeding entirely
     (confirmed by a `debug` message), and leaves the existing node-local
     runtime credentials file untouched — Semaphore and Phase 2+ keep working
     with no further action.
   - **Otherwise**, let the playbook run through against the fresh, empty
     instance: the bootstrap call returns `200`, and in one pass it
     re-provisions everything from scratch via the REST API (org, admin,
     project, environment, folders, the read-only `runtime` identity),
     re-seeds every application secret straight from `vault.yml` (the
     canonical fallback source for every seeded secret), and writes fresh
     runtime credentials to `/home/homelab/.infisical_runtime_auth.yml` —
     which the same play's Semaphore step then reads to come back up
     authenticated. See [What the Bootstrap Playbook
     Does](../BOOTSTRAP.md#what-the-bootstrap-playbook-does).
4. Run Phase 2 to restore edge services:
   ```bash
   ansible-playbook playbooks/deploy_edge.yml
   ```
5. Re-authenticate Cloudflare Tunnel if credentials have expired
6. Pi-hole `custom.list` and all config restore from the Git repo automatically

### Any other node failure

Since the edge node is intact, recovery is straightforward:

1. Flash a new SD card / reinstall OS on the failed node
2. From the edge node, bootstrap and redeploy:
   ```bash
   ansible-playbook playbooks/bootstrap_node.yml --limit <node>
   ansible-playbook playbooks/deploy_<role>.yml
   ```
3. Restore databases if needed (see [Databases](#databases) above)

### Complete homelab loss

1. Recover the edge node first (see above)
2. Redeploy all nodes in order: observe → svc-01 → svc-02 → svc-03
3. Restore databases from the most recent off-site backup
4. Maximum data loss equals the backup interval (default: 24 hours)

All configuration is in the Git repo — the only unrecoverable data is database content not yet backed up.