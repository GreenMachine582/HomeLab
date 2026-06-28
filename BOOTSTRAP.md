# Bootstrap Guide

Step-by-step instructions to bring the homelab up from scratch. After Phase 1 all work is done by Ansible — manual 
steps are kept to the absolute minimum.

**Estimated time:** 2–3 hours for a full deployment (Phases 1–4).

<!-- TOC -->
* [Bootstrap Guide](#bootstrap-guide)
  * [Prerequisites](#prerequisites)
    * [Hardware](#hardware)
    * [Accounts](#accounts)
    * [Files](#files)
  * [Phase 0: Flash the SD Card](#phase-0-flash-the-sd-card)
    * [0.1 Download and Install RPi Imager](#01-download-and-install-rpi-imager)
    * [0.2 Select OS and Storage](#02-select-os-and-storage)
    * [0.3 Configure OS Customisation](#03-configure-os-customisation)
    * [0.4 Flash and Boot](#04-flash-and-boot)
  * [Phase 1: PC → Edge (Bootstrap)](#phase-1-pc--edge-bootstrap)
    * [1.1 Prepare Your PC](#11-prepare-your-pc)
    * [1.2 Move the Repo into the WSL Filesystem](#12-move-the-repo-into-the-wsl-filesystem)
    * [1.3 Find the Edge Node IP](#13-find-the-edge-node-ip)
    * [1.4 Generate SSH Keys](#14-generate-ssh-keys)
    * [1.5 Add GitHub Deploy Key](#15-add-github-deploy-key)
    * [1.6 Copy SSH Key to Edge Node](#16-copy-ssh-key-to-edge-node)
    * [1.7 Load SSH Key into Agent](#17-load-ssh-key-into-agent)
    * [1.8 Set Up Tailscale OAuth Client](#18-set-up-tailscale-oauth-client)
    * [1.9 Create Ansible Vault and Override Config](#19-create-ansible-vault-and-override-config)
    * [1.10 Run the Bootstrap Playbook](#110-run-the-bootstrap-playbook)
    * [What the Bootstrap Playbook Does](#what-the-bootstrap-playbook-does)
  * [Phase 2: Edge → Self-Deploy](#phase-2-edge--self-deploy)
  * [Phase 3: Edge → Other Nodes](#phase-3-edge--other-nodes)
    * [3.1 Deploy Observe Node](#31-deploy-observe-node)
    * [3.2 Deploy Service Nodes](#32-deploy-service-nodes)
  * [Phase 4: Automated Deployments](#phase-4-automated-deployments)
    * [How It Works](#how-it-works)
    * [4.1 Configure the Automation Endpoint (n8n or Camunda)](#41-configure-the-automation-endpoint-n8n-or-camunda)
    * [4.2 GitHub Workflow](#42-github-workflow)
    * [4.3 Manual Trigger](#43-manual-trigger)
<!-- TOC -->

---

## Prerequisites

### Hardware

- [ ] All Raspberry Pis flashed with **Raspberry Pi OS Lite (64-bit)** — see [Phase 0](#phase-0-flash-the-sd-card)
- [ ] Edge node powered on and connected to WiFi (or Ethernet)
- [ ] Static DHCP reservations configured on router (recommended — can be done after initial boot)

### Accounts

- [ ] GitHub account with access to this repository
- [ ] Cloudflare account (for Cloudflare Tunnel)
- [ ] Tailscale account

### Files

- [ ] This repository cloned on your PC
- [ ] Ansible Vault password chosen and stored securely (password manager recommended)

---

## Phase 0: Flash the SD Card

**Goal:** Write Raspberry Pi OS to the SD card and pre-configure the OS so the Pi boots ready for SSH — no keyboard or monitor needed.

> Repeat for each node. The steps below use `homelab-edge` as the example; swap the hostname for other nodes.

---

### 0.1 Download and Install RPi Imager

Download **Raspberry Pi Imager** (v1.8+) from [raspberrypi.com/software](https://www.raspberrypi.com/software/) and install it on your PC or Mac.

---

### 0.2 Select OS and Storage

1. Open RPi Imager
2. **Choose Device** → select your Raspberry Pi model (e.g. Raspberry Pi 4)
3. **Choose OS** → *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (64-bit)**
4. **Choose Storage** → select your SD card (double-check the size — this will be erased)
5. Click **Next**

---

### 0.3 Configure OS Customisation

When prompted *"Would you like to apply OS customisation settings?"* click **Edit Settings**.

**General tab:**

| Field                   | Value                                                           |
|-------------------------|-----------------------------------------------------------------|
| Hostname                | `homelab-edge`                                                  |
| Username                | `admin`                                                         |
| Password                | A strong temporary password (you'll use this once in step 1.6) |
| Configure wireless LAN  | ✅ Enabled                                                      |
| SSID                    | Your WiFi network name                                          |
| Password                | Your WiFi password                                              |
| Wireless LAN country    | Your country code (e.g. `US`, `GB`)                             |
| Set locale              | Your timezone and keyboard layout                               |

> **No static IP here.** The Pi will obtain a DHCP address over WiFi at first boot. You'll discover the address in step 1.3 and configure a static reservation (or Ansible-managed static IP) later.

**Services tab:**

| Field          | Value                          |
|----------------|--------------------------------|
| Enable SSH     | ✅ Enabled                     |
| Authentication | **Use password authentication** |

> Password auth is only needed for the initial `ssh-copy-id` in step 1.6. Ansible will disable it and enforce key-only auth during the bootstrap playbook.

Click **Save**, then **Yes** to apply the settings.

---

### 0.4 Flash and Boot

1. Confirm the write prompt — RPi Imager will erase and flash the card
2. Eject the SD card safely once writing and verification complete
3. Insert the SD card into the Pi and apply power
4. Allow 60–90 seconds for first boot (the Pi expands the filesystem on first start)
5. Confirm the Pi has joined the network:
   ```bash
   ping homelab-edge.local
   ```
   If mDNS (`homelab-edge.local`) doesn't resolve, check your router's DHCP lease table for the IP.

> **Ethernet alternative:** If you plug in Ethernet instead of (or as well as) WiFi, the Pi will prefer Ethernet. Either works for bootstrap — WiFi is expected at this stage and the IP will change once static DHCP is configured.

---

## Phase 1: PC → Edge (Bootstrap)

**Goal:** Convert `homelab-edge` from a fresh OS install into the Ansible control node for the entire homelab.

This is the only phase that requires manual work from your PC. Everything from Phase 2 onwards runs on the edge node.

---

### 1.1 Prepare Your PC

**Windows (WSL recommended):**

```powershell
wsl --install -d Ubuntu-22.04
```

Inside Ubuntu, install the required tools:

```bash
sudo apt update
sudo apt install -y ansible python3-pip sshpass git
```

Verify:

```bash
ansible --version   # Expect 2.14+
python3 --version   # Expect 3.10+
```

**macOS / Linux:** Install Ansible via your package manager or `pip install ansible`.

---

### 1.2 Move the Repo into the WSL Filesystem

> **Windows only.** Windows-mounted paths (including OneDrive) do not support the file permissions required by SSH and 
Ansible Vault.

```bash
cp -r /mnt/c/Users/<your-user>/path/to/homelab ~/homelab
cd ~/homelab
```

Verify you are in the WSL filesystem:

```bash
pwd
# Expected: /home/<wsl-user>/homelab
```

---

### 1.3 Find the Edge Node IP

```bash
ping homelab-edge.local
```

If mDNS is not available, check your router's DHCP lease table or use a network scanner. You'll need this IP in [step 1.9](#19-create-ansible-vault-and-override-config) (`ip_edge` in `overrides.yml`).

---

### 1.4 Generate SSH Keys

From the repo root:

```bash
mkdir -p .ssh

ssh-keygen -t ed25519 -f .ssh/homelab-edge   -C "homelab-edge"
ssh-keygen -t ed25519 -f .ssh/homelab        -C "homelab"
ssh-keygen -t ed25519 -f .ssh/deploy         -C "deploy"
ssh-keygen -t ed25519 -f .ssh/homelab-github -C "homelab-repo"
```

**Passphrase guidance:**

| Key              | Passphrase | Reason                                        |
|------------------|------------|-----------------------------------------------|
| `homelab-edge`   | **Yes**    | Used for interactive admin login              |
| `homelab`        | No         | Used by Ansible automation (non-interactive)  |
| `deploy`         | No         | Used by webhook/SSH trigger (non-interactive) |
| `homelab-github` | No         | Used by edge to clone the repo                |

Set correct permissions:

```bash
chmod 600 .ssh/homelab-edge .ssh/homelab .ssh/deploy .ssh/homelab-github
chmod 644 .ssh/*.pub
```

Verify:

```bash
ls -la .ssh/
# Private keys: -rw-------
# Public keys:  -rw-r--r--
```

---

### 1.5 Add GitHub Deploy Key

Display the key:

```bash
cat .ssh/homelab-github.pub
```

Add it to GitHub:

1. Go to **Repository → Settings → Deploy Keys → Add deploy key**
2. Name: `homelab-edge`
3. Paste the public key
4. Access: **Read-only**
5. Save

This allows the edge node to clone and pull the repo without a personal access token.

---

### 1.6 Copy SSH Key to Edge Node

```bash
ssh-copy-id -i .ssh/homelab-edge.pub admin@<ip_edge>
```

Enter the `admin` password when prompted. This is the only time a password is used for SSH.

---

### 1.7 Load SSH Key into Agent

Load the key into `ssh-agent` once so Ansible doesn't prompt for the passphrase on every task:

```bash
eval "$(ssh-agent -s)"
ssh-add .ssh/homelab-edge
```

Verify the connection:

```bash
ssh admin@<ip_edge>
```
```bash
exit
```

If the connection succeeds without a password prompt, the key is installed correctly. The agent stays active for the rest of your terminal session.

---

### 1.8 Set Up Tailscale OAuth Client

Tailscale needs three things configured in the admin console **before** you populate the vault — you'll need the OAuth credentials in the next step.

**Step 1 — Create the device tag** (`login.tailscale.com/admin/acls/visual/tags`):

1. Click **Add tag**
2. Name it `homelab` (Tailscale prefixes it automatically as `tag:homelab`)
3. Set owner to yourself or `autogroup:admin`
4. Save

**Step 2 — Create an access rule** (`login.tailscale.com/admin/acls/visual/general-access-rules`):

1. Click **Add rule**
2. Source: `autogroup:admin` and `tag:homelab`
3. Destination: `tag:homelab` (nodes in the homelab tag can reach each other)
4. Save

**Step 3 — Create OAuth credentials** (`login.tailscale.com/admin/settings/trust-credentials`):

1. Click **Add credentials**
2. Under **Scopes**, enable **Auth Keys (write)**
3. Under **Tags**, select `tag:homelab`
4. Click **Create** and copy the **Client ID** and **Client secret** immediately — the secret is only shown once

> Tag scopes cannot be changed after creation. If you forget to select `tag:homelab`, delete the credential and create a new one.

You will need the Client ID and Client secret in §1.9.

---

### 1.9 Create Ansible Vault and Override Config

Create a vault password file:

```bash
printf "your-strong-vault-password" > .vault_pass
chmod 600 .vault_pass
```

Point Ansible at it via an environment variable (add to `~/.bashrc` / `~/.zshrc` so it persists across sessions):

```bash
echo 'export ANSIBLE_VAULT_PASSWORD_FILE=~/homelab/.vault_pass' >> ~/.bashrc
source ~/.bashrc
```

Create the vault:

```bash
EDITOR=nano ansible-vault create inventories/group_vars/all/vault.yml
```

Populate it using `inventories/group_vars/all/vault.yml.example` as a reference. Save and exit (`:wq` in Vim).

> - `vault_infisical_admin_email` / `vault_infisical_admin_password` — **set these to REAL values now, not `"changeme"`.** Unlike everything else in this block, the bootstrap playbook's one-shot `POST /v1/admin/bootstrap` call (see [What the Bootstrap Playbook Does](#what-the-bootstrap-playbook-does)) uses these to create Infisical's actual admin account — they become real, permanent login credentials, and the playbook's preflight will refuse to run if they're still placeholders. Use a strong, unique password; this account has full control over every secret in the homelab.
> - `vault_infisical_encryption_key` — generate with `openssl rand -hex 16`. This one is also REAL-value-required and PERMANENT (a changed key can't decrypt the existing Postgres volume).
> - `vault_semaphore_admin_*` — yours to set directly; Semaphore comes up at the end of the same bootstrap run.
>
> Notice what's *not* in this list: there are no `vault_infisical_bootstrap_client_*`/`vault_infisical_runtime_client_*` placeholders to fill in, before the run or after. The bootstrap playbook provisions Infisical's one machine identity (read-only `runtime`) via its REST API and writes its credentials straight to a node-local file the instant they're minted — nothing is ever printed for you to copy into this vault. See [What the Bootstrap Playbook Does](#what-the-bootstrap-playbook-does) and [Secrets](./CLAUDE.md#secrets).

> **If you created vault.yml by copying `vault.yml.example` directly** (instead of using `ansible-vault create`), encrypt it now:
> ```bash
> ansible-vault encrypt inventories/group_vars/all/vault.yml
> ```

Verify the vault is encrypted before continuing — the file should start with `$ANSIBLE_VAULT;`:

```bash
head -1 inventories/group_vars/all/vault.yml
```

Create the local config:

```bash
cp inventories/group_vars/all/overrides.yml.example \
   inventories/group_vars/all/overrides.yml
```

Edit `overrides.yml` and fill in your actual IPs and `lan_subnet`. These override the `EDIT_BEFORE_USE` placeholders in `main.yml` and are automatically copied to the edge node by the bootstrap playbook.

---

### 1.10 Run the Bootstrap Playbook

One playbook, one pass, zero manual steps in between. It brings Infisical up
and fully provisions **and seeds** it via its REST API (org, admin account,
`homelab` project, `production` environment, the nine application folders, the
read-only `runtime` machine identity, and every application secret from
`vault.yml`), configures the firewall, and brings Semaphore online — reading
its own Infisical runtime credentials straight from the node-local file the
provisioning step just wrote. Nothing is printed for you to transcribe
anywhere. See [What the Bootstrap Playbook
Does](#what-the-bootstrap-playbook-does) for the full breakdown.

Make sure the SSH key is loaded in `ssh-agent` (step 1.7) before running.

```bash
ansible-playbook -i inventories/bootstrap.ini \
  playbooks/bootstrap_edge.yml
```

No password prompts — the SSH key passphrase is handled by `ssh-agent` and the `admin` sudo password is read from the vault (`vault_admin_become_password`).

**Pre-flight checks run before anything touches the node:**
- Verifies all required local files exist: `.ssh/homelab-github`, `.ssh/homelab`, `.vault_pass`, `vault.yml`, `overrides.yml`
- Asserts all required variables are defined (`ssh_port`, `github_org`, `homelab_repo_path`, etc.)

**Post-firewall validation:**
After UFW is enabled, the playbook probes `ssh_port` from your PC (via `wait_for`) and fails immediately if SSH is unreachable — so a misconfigured firewall is caught before the play reports success.

**Expected duration:** 12–18 minutes (the Infisical bring-up — pulling images,
provisioning via its REST API, seeding every application secret, and waiting
for its API port — adds several minutes over a pre-Infisical bootstrap; most
of that time is image pulls and container start/health-wait).

The playbook ends with a debug message confirming Infisical is up, fully
provisioned, fully seeded, and that Semaphore is online too — see [What the
Bootstrap Playbook Does](#what-the-bootstrap-playbook-does) for the full
breakdown of what just happened. Nothing is printed for you to copy anywhere;
Phase 1 is simply done. Continue straight to [Phase
2](#phase-2-edge--self-deploy).

---

### What the Bootstrap Playbook Does

One playbook, one pass — `bootstrap_edge.yml`. Infisical's org, admin account,
project, environment, folders, its one machine identity, and every application
secret are all provisioned **and seeded** automatically via its REST API (see
"Provision and seed Infisical" below) — there is no manual setup step, no
credential hand-off, and (unlike an earlier design) no second playbook to run
afterward.

| Task                       | Detail                                     |
|----------------------------|--------------------------------------------|
| Set hostname               | `homelab-edge`                             |
| Create `homelab` user      | Ansible automation, passwordless sudo      |
| Create `deploy` user       | Webhook/SSH trigger, restricted sudo       |
| Install Docker             |                                            |
| Install Tailscale          | Brought up here (not Phase 2) — `tailscale_up: true` — so Infisical and Semaphore are reachable over the tailnet by the end of Phase 1. See the [Mode](./docs/NETWORK.md#mode) note in NETWORK.md. |
| Install Ansible            | Edge becomes a control node                |
| Install Git                |                                            |
| Clone repo                 | `/opt/homelab`, owned by `homelab`         |
| Copy files to node         | `overrides.yml`, `homelab` SSH key pair — **`vault.yml`/`.vault_pass` are deliberately NOT copied** (they live only on the WSL/PC control host; see [Secrets](./CLAUDE.md#secrets)). Phase 2+ resolves application secrets from Infisical at runtime instead (`roles/infisical/tasks/lookup.yml`) |
| Register SSH host key      | Edge's own key added to `/home/homelab/.ssh/known_hosts` — required for Phase 2 self-deploy |
| Harden SSH                 | Key-only auth, no root login; port changed to `ssh_port` via async restart only if sshd is not already listening there (probe-first, idempotent on re-runs); subsequent tasks reconnect on new port automatically |
| Bring up Infisical         | Renders `/opt/infisical/.env` (node-generated secrets), starts `infisical-db`/`infisical-redis`/`infisical`, waits for the API port (8222) to accept connections |
| Provision and seed Infisical | Drives Infisical's REST API (`roles/infisical/tasks/bootstrap_instance.yml`) — in one pass, over loopback, before the firewall locks the port down — to create the org, admin account, `homelab` project, `production` environment, the nine application folders, and the read-only `runtime` machine identity; push every `[seed → ...]` application secret from the WSL-local `vault.yml` into its mapped `/production/<folder>/<KEY>` path (additive — existing keys untouched); and write the `runtime` identity's freshly-minted credentials straight to `/home/homelab/.infisical_runtime_auth.yml`. All of it authenticated with the one-shot bootstrap call's own instance-admin token — no separate write-capable identity is ever created, persisted, printed, or revoked. See that task's header comment for the full rationale. |
| Configure firewall         | UFW default-deny inbound; allow `ssh_port`/tcp, 53/udp+tcp (Pi-hole DNS, LAN only), 8222/tcp + 3010/tcp (Infisical/Semaphore, **Tailscale CGNAT range only** — `100.64.0.0/10`); SSH reachability verified before play completes. Port 80 (Caddy) opened in Phase 2. |
| Bring up Semaphore         | Renders `/opt/semaphore/.env` — node-generated Postgres password, `vault_semaphore_admin_*`, and the `runtime` identity's credentials loaded straight from `/home/homelab/.infisical_runtime_auth.yml` (never `vault.yml`, which never holds them) — then starts `semaphore-db`/`semaphore` |
| Enable unattended upgrades |                                            |

**Sudo rules created:**

```
# /etc/sudoers.d/homelab
homelab ALL=(ALL) NOPASSWD:ALL

# /etc/sudoers.d/deploy
deploy ALL=(ALL) NOPASSWD: /usr/bin/ansible-playbook
```

**How Infisical goes from a bare container to fully seeded with zero clicks:**
the obvious blocker — "an admin account is the one thing that can't exist
before Infisical does" — turns out to have a built-in escape hatch: `POST
/v1/admin/bootstrap` (Infisical's own "Programmatic Provisioning" /
[automated bootstrapping](https://infisical.com/docs/self-hosting/guides/automated-bootstrapping)
guide). It's a single unauthenticated, one-shot call that creates the admin
account **and** the organization **and** returns an instance-admin Bearer
token, all at once — and it refuses to run again once an instance is
initialised (which doubles as the playbook's freshness check: a 200 means "go
ahead and provision everything", anything else means "already done, skip").
`bootstrap_instance.yml` drives that token through the rest of the REST API to
provision the project/environment/folders/identity — and, because that token
already has *more* write access than any project-scoped identity could, to
push every application secret from `vault.yml` into Infisical immediately too,
in the same breath. Only the read-only `runtime` identity ever gets created
and persisted — nothing write-capable is ever minted, printed, copied, or left
lying around to revoke. See `bootstrap_instance.yml`'s header comment for the
complete "why no bootstrap identity" reasoning.

| Identity  | Access level                                       | Used by                                                          |
|-----------|----------------------------------------------------|------------------------------------------------------------------|
| `runtime` | **Read-only** access to the `homelab` project (all folders, `production` env) | `deploy_edge.yml` and Semaphore — both read it from `/home/homelab/.infisical_runtime_auth.yml`, never `vault.yml` |

The playbook ends with Infisical running, fully provisioned, fully seeded, and
Semaphore online — all reachable over Tailscale (the firewall restricts ports
8222/3010 to the Tailscale CGNAT range). Confirm with `tailscale status`
(should list `homelab-edge`), then browse to `http://<edge-tailscale-ip>:8222`
for Infisical and `http://<edge-tailscale-ip>:3010` for Semaphore. Neither
service gets a Pi-hole hostname or Caddy route — Tailscale is the only path in
(see [docs/NETWORK.md](./docs/NETWORK.md#tailscale-only-service-access-infisical--semaphore)).

Now run Phase 2 — `deploy_edge.yml` resolves its application secrets
(`cloudflare/TUNNEL_TOKEN`, `pihole/WEB_PASSWORD`) from Infisical via the
`runtime` identity that's already in place, so this is the first point it can
succeed. See [Phase 2](#phase-2-edge--self-deploy) for both ways to run it
(SSH into the edge, or directly from your PC/WSL):
```bash
ansible-playbook playbooks/deploy_edge.yml --limit homelab-edge
```

> ⚠️ **This automation needs live verification** against the deployed
> Infisical version — `bootstrap_instance.yml` carries an "API has moved
> across releases" caveat for every endpoint path/payload/response-field it
> touches (bootstrap, project/environment/folder/identity creation, Universal
> Auth, and the v3 raw-secrets routes for the seed). If the playbook fails
> partway through provisioning, see
> [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) for how to wipe
> Infisical's volumes and retry against a clean instance.

> **Re-seeding is safe and idempotent**, and re-running the whole playbook is
> too. The seed only creates keys that don't already exist (`status == 404`);
> anything already in Infisical is left untouched, and the one-shot bootstrap
> call's own non-200 response on a re-run skips the entire
> provision-and-seed block (Infisical's already initialised — nothing to do).
> Adding a brand-new service later just means adding its
> `vault_<service>_<field>` entries to `vault.yml`, its mapping to
> `_infisical_seed_map` in `roles/infisical/tasks/bootstrap_instance.yml`, its
> folder to `infisical_seed_folders` (`roles/infisical/defaults/main.yml`) and
> Infisical itself — then re-seeding via the Infisical web UI directly
> (Tailscale-reachable, trivial for occasional one-offs) rather than re-running
> a playbook whose provisioning half is now permanently a no-op.

---

## Phase 2: Edge → Self-Deploy

**Goal:** The edge node deploys its own services using Ansible running locally.

**Option A — SSH into the edge node:**

```bash
ssh -p <ssh_port> admin@<ip_edge>
```

```bash
sudo su - homelab
```

```bash
cd /opt/homelab
ansible-playbook playbooks/deploy_edge.yml --limit homelab-edge
```

**Option B — run directly from your PC/WSL:**

`prod.yml` connects as `homelab` via `ansible_ssh_private_key_file: ~/.ssh/homelab`
— on the edge that resolves to `/home/homelab/.ssh/homelab` (copied there
during Phase 1), but on your PC/WSL the same literal path resolves to
`~/.ssh/homelab`, not the repo-relative `~/homelab/.ssh/homelab` where the key
was generated (step 1.4). Symlink it in once so both environments resolve the
same path:

```bash
ln -s ~/homelab/.ssh/homelab     ~/.ssh/homelab
ln -s ~/homelab/.ssh/homelab.pub ~/.ssh/homelab.pub
```

Then, from the repo root:

```bash
ansible-playbook playbooks/deploy_edge.yml --limit homelab-edge
```

> `ansible.cfg` sets the default inventory (`prod.yml`) — no `-i` flag needed. Re-run either option anytime (e.g. after pulling new changes, or recovering from a partial failure) — `deploy_edge.yml` is idempotent.

**What `deploy_edge.yml` does:**

- Pulls latest repo from GitHub
- Resolves application secrets (`cloudflare/TUNNEL_TOKEN`, `pihole/WEB_PASSWORD`) from Infisical at runtime via `roles/infisical/tasks/lookup.yml` — this node never has `vault.yml`; see [Secrets](./CLAUDE.md#secrets)
- Deploys fail2ban (SSH and Pi-hole jails)
- Re-asserts Tailscale in subnet-router mode (already brought up and joined during Phase 1 — see [What the Bootstrap Playbook Does](#what-the-bootstrap-playbook-does); idempotent here, a no-op once joined)
- Installs and configures Unbound as a host systemd service (port 5335, DNSSEC-validating recursive resolver)
- Ships logs via Grafana Alloy (→ Loki once Phase 3 is up)
- Renders edge service configs (cloudflared, Pi-hole custom DNS, Caddy reverse proxy)
- Pulls and starts Docker Compose stack:
  - `cloudflared` (Cloudflare Tunnel — external ingress)
  - Pi-hole (DNS, port 53 — upstream is Unbound on the host via `host.docker.internal#5335`)
  - Caddy (LAN reverse proxy for `*.homelab.local`)
  - `node-exporter` and `pihole-exporter` (metrics)
  - Portainer Agent

> **Firewall note:** UFW rules are applied by `bootstrap_edge.yml` (Phase 1) and persist. To update rules after adding new services run: `ansible-playbook playbooks/apply_firewall.yml --limit homelab-edge`

**Direct access (no DNS required):**

| Service | URL | Notes |
|---|---|---|
| Pi-hole admin | `http://<ip_edge>:8080/admin` | Password = `vault_pihole_web_password` |
| Portainer Agent | `http://<ip_edge>:9001` | Portainer Server connects here in Phase 3 |
| node-exporter metrics | `http://<ip_edge>:9100/metrics` | Scraped by Prometheus in Phase 3 |
| pihole-exporter metrics | `http://<ip_edge>:9617/metrics` | Scraped by Prometheus in Phase 3 |

---

## Phase 3: Edge → Other Nodes

**Goal:** Deploy the observe node and service nodes from the edge.

All commands run on `homelab-edge` (or from your PC via the production inventory).

### 3.1 Deploy Observe Node

Prerequisites: `homelab-observe` has the base OS installed and is reachable via SSH from the edge node.

```bash
# Bootstrap the observe node
ansible-playbook playbooks/bootstrap_node.yml \
  --limit homelab-observe \
  --ask-pass --ask-become-pass

# Deploy the monitoring stack
ansible-playbook playbooks/deploy_observe.yml
```

**What gets deployed:**

- Tailscale (ACL: accessible from edge and admin devices only)
- Docker Compose stack:
  - Prometheus (scrapes all `node-exporter` instances)
  - Loki (receives logs from all Grafana Alloy agents)
  - Grafana (pre-configured dashboards and data sources)
  - Alertmanager (routes alerts by severity)
  - Uptime Kuma (HTTP endpoint monitoring)
  - Portainer + Agent (Docker GUI for all nodes)
- Edge's Alloy agent begins forwarding logs to Loki
- Prometheus begins scraping edge's `node-exporter`

---

### 3.2 Deploy Service Nodes

```bash
# Bootstrap svc-01
ansible-playbook playbooks/bootstrap_node.yml \
  --limit homelab-svc-01 \
  --ask-pass --ask-become-pass

# Deploy the Camunda stack
ansible-playbook playbooks/deploy_svc.yml --tags camunda
```

For `svc-02` (when provisioned):

```bash
ansible-playbook playbooks/bootstrap_node.yml \
  --limit homelab-svc-02 \
  --ask-pass --ask-become-pass

ansible-playbook playbooks/deploy_svc.yml --tags greentechhub
```

> Use Docker Compose profiles on `svc-01` to bring up databases before dependent services:
> ```bash
> docker compose --profile databases up -d
> # Wait for health checks to pass, then:
> docker compose --profile camunda up -d
> ```

---

## Phase 4: Automated Deployments

**Goal:** Deployments trigger automatically on push to `master`, without a self-hosted runner on the edge.

---

### How It Works

```
git push → master
    ↓
.github/workflows/deploy.yml  (runs on GitHub's hosted runners)
    ↓
HTTP POST → n8n or Camunda webhook endpoint (running on homelab-svc-01)
    ↓
n8n/Camunda workflow SSHes to homelab-edge as `deploy` user
    ↓
deploy user runs: git pull + ansible-playbook directly
    ↓
Ansible deploys to all target nodes
```

GitHub only needs to reach the n8n or Camunda endpoint — it never connects directly to the edge or any other node. All
Ansible execution stays inside the homelab. No deploy script is needed — the `deploy` user's restricted sudo allows
`ansible-playbook` directly.

---

### 4.1 Configure the Automation Endpoint (n8n or Camunda)

**Option A — n8n (recommended for simplicity):**

1. Create a new workflow triggered by **Webhook** node
2. Validate the incoming request (check `X-Deploy-Secret` header matches `vault_deploy_webhook_secret`)
3. Add an **SSH** node pointing to `homelab-edge`, port `{{ ssh_port }}`, user `deploy`, using the `deploy` private key
4. Commands:
   ```bash
   cd /opt/homelab
   sudo ansible-playbook playbooks/deploy_edge.yml
   sudo ansible-playbook playbooks/deploy_observe.yml
   sudo ansible-playbook playbooks/deploy_svc.yml
   ```
   > `deploy_edge.yml` pulls the latest repo at the start via `become_user: homelab`. No separate `git pull` needed.

**Option B — Camunda:**

1. Deploy a BPMN process with a message start event
2. Expose a REST endpoint via Camunda's API that receives the GitHub POST
3. Use a service task to SSH to the edge and run the same `ansible-playbook` commands above

Either way, store the `deploy` private key as a credential inside n8n/Camunda — it never touches GitHub.

---

### 4.2 GitHub Workflow

`.github/workflows/deploy.yml` runs on GitHub's own hosted runners (no self-hosted runner needed):

```yaml
name: Deploy

on:
  push:
    branches: [master]

jobs:
  trigger:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger deploy endpoint
        run: |
          curl -X POST \
            -H "Content-Type: application/json" \
            -H "X-Deploy-Secret: ${{ secrets.DEPLOY_SECRET }}" \
            -d '{"ref": "${{ github.ref }}"}' \
            ${{ secrets.DEPLOY_ENDPOINT_URL }}
```

Add two secrets in **Repository → Settings → Secrets and variables → Actions**:

| Secret                | Value                                              |
|-----------------------|----------------------------------------------------|
| `DEPLOY_ENDPOINT_URL` | URL of your n8n webhook or Camunda REST endpoint   |
| `DEPLOY_SECRET`       | Shared secret; validate this in n8n/Camunda        |

No Ansible Vault password, no SSH keys, and no homelab IPs are stored in GitHub.

---

### 4.3 Manual Trigger

For ad-hoc deployments without going through GitHub or n8n, SSH to the edge as `deploy` and run playbooks directly:

```bash
ssh -p <ssh_port> -i .ssh/deploy deploy@homelab-edge

cd /opt/homelab

# Run whichever playbooks are needed
sudo ansible-playbook playbooks/deploy_edge.yml
sudo ansible-playbook playbooks/deploy_observe.yml
sudo ansible-playbook playbooks/deploy_svc.yml
```

The `deploy` user's sudo is restricted to `/usr/bin/ansible-playbook` only — no shell, no root access. The git pull happens automatically inside `deploy_edge.yml` via `become_user: homelab`. Deployments work even if GitHub or the automation endpoint is unavailable.
