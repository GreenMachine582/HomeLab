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
  * [Cloudflare Tunnel](#cloudflare-tunnel)
    * [External services not reachable](#external-services-not-reachable)
  * [Monitoring Stack](#monitoring-stack)
    * [Grafana showing no data](#grafana-showing-no-data)
    * [Alertmanager not sending notifications](#alertmanager-not-sending-notifications)
  * [Databases](#databases)
    * [PostgreSQL not starting](#postgresql-not-starting)
    * [Restoring a PostgreSQL backup](#restoring-a-postgresql-backup)
    * [Elasticsearch heap pressure](#elasticsearch-heap-pressure)
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
ansible -i inventories/prod.ini all -m ping

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
ansible-playbook -i inventories/prod.ini playbooks/healthcheck.yml
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
ansible -i inventories/prod.ini <node> -m ping

# Run with verbose output
ansible-playbook -i inventories/prod.ini playbooks/healthcheck.yml -vvv
```

Common causes: wrong IP in `host_vars/`, SSH key not deployed to the node, firewall blocking port 22 from edge.

---

## Ansible

### Playbook fails mid-run

Ansible is idempotent — re-running a playbook is always safe. Fix the underlying issue and re-run:

```bash
ansible-playbook -i inventories/prod.ini playbooks/<playbook>.yml
```

To resume from a specific task after a failure:

```bash
ansible-playbook -i inventories/prod.ini playbooks/<playbook>.yml \
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
ansible-playbook -i inventories/prod.ini playbooks/deploy_<node>.yml \
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
dig @192.168.1.10 grafana.homelab.local
dig @192.168.1.10 example.com
```

If `grafana.homelab.local` fails but `example.com` resolves, the `custom.list` entry is missing or Pi-hole needs to be reloaded:

```bash
docker exec pihole pihole restartdns
```

**Check 3 — Is the client using Pi-hole as its DNS server?**

The client's DNS must point to `192.168.1.10`. Check DHCP config on the router.

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
   ansible-playbook -i inventories/prod.ini playbooks/deploy_edge.yml --tags pihole
   ```

---

## Tailscale

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
   ansible-playbook -i inventories/prod.ini playbooks/deploy_edge.yml --tags cloudflared
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
ansible-playbook -i inventories/prod.ini playbooks/deploy_<node>.yml --tags node-exporter
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
ansible-playbook -i inventories/prod.ini playbooks/deploy_observe.yml --tags alertmanager
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
ansible-playbook -i inventories/prod.ini playbooks/deploy_svc.yml --tags camunda
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
ssh deploy@homelab-edge
/opt/homelab/scripts/deploy.sh
```

---

## Disaster Recovery

### Edge node SD card failure

The edge node is the Ansible control node and runs DNS, the Cloudflare Tunnel, and Pi-hole. While it is down:

- **Other nodes remain accessible** — each node has its own Tailscale connection, so you can still SSH to `homelab-observe`, `svc-01`, etc. directly over VPN
- **LAN SSH also works** — connect directly to `192.168.1.11`, `.20` etc. from any device on the same network
- **Internal DNS is down** — `.homelab.local` hostnames won't resolve; use IPs directly until the edge is restored
- **External services are down** — Cloudflare Tunnel runs on the edge; public hostnames will be unreachable

**Recovery steps:**

1. Flash a new SD card with RPi OS Lite (64-bit)
2. Boot the edge node and find its IP (check router DHCP)
3. From your PC, run the bootstrap playbook (see `BOOTSTRAP.md` Phase 1):
   ```bash
   ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge.yml
   ```
4. Run Phase 2 to restore edge services:
   ```bash
   ansible-playbook -i inventories/prod.ini playbooks/deploy_edge.yml
   ```
5. Re-authenticate Cloudflare Tunnel if credentials have expired
6. Pi-hole `custom.list` and all config restore from the Git repo automatically

### Any other node failure

Since the edge node is intact, recovery is straightforward:

1. Flash a new SD card / reinstall OS on the failed node
2. From the edge node, bootstrap and redeploy:
   ```bash
   ansible-playbook -i inventories/prod.ini playbooks/bootstrap_node.yml --limit <node> --ask-pass --ask-become-pass
   ansible-playbook -i inventories/prod.ini playbooks/deploy_<role>.yml
   ```
3. Restore databases if needed (see [Databases](#databases) above)

### Complete homelab loss

1. Recover the edge node first (see above)
2. Redeploy all nodes in order: observe → svc-01 → svc-02 → svc-03
3. Restore databases from the most recent off-site backup
4. Maximum data loss equals the backup interval (default: 24 hours)

All configuration is in the Git repo — the only unrecoverable data is database content not yet backed up.