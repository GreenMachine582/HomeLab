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
    * [1.10 Configure Bootstrap Inventory](#110-configure-bootstrap-inventory)
    * [1.11 Run the Bootstrap Playbook (Part 1)](#111-run-the-bootstrap-playbook-part-1)
    * [What the Bootstrap Playbooks Do](#what-the-bootstrap-playbooks-do)
    * [First-run Infisical Setup](#first-run-infisical-setup)
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

If mDNS is not available, check your router's DHCP lease table or use a network scanner. You'll need this IP in [step 1.10](#110-configure-bootstrap-inventory).

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

> - `vault_infisical_encryption_key` — generate with `openssl rand -hex 16`
> - `vault_infisical_bootstrap_client_*` / `vault_infisical_runtime_client_*` — leave as `"changeme"` for now; filled in after [First-run Infisical Setup](#first-run-infisical-setup)

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

### 1.10 Configure Bootstrap Inventory

Edit `inventories/bootstrap.ini` and replace `EDIT_BEFORE_USE` with the DHCP IP found in step 1.3:

```ini
homelab-edge ansible_host=192.168.x.x ansible_user=admin ...
```

> **Re-running after bootstrap:** If the node has already been bootstrapped and SSH is on the non-standard port, add `ansible_port=2189` (or your `ssh_port` value) to the host line before running.

Verify Ansible can reach the node:

```bash
ansible -i inventories/bootstrap.ini edge_bootstrap -m ping
```

Expected:

```
homelab-edge | SUCCESS => {
    "changed": false,
    "ping": "pong"
}
```

---

### 1.11 Run the Bootstrap Playbook (Part 1)

Phase 1 is split into two playbooks around Infisical's first-run checkpoint —
its org/admin/project/identities can't be created until Infisical itself is up
and running, which only happens partway through bootstrap. Part 1 gets it
running and hands off to a manual setup step; [Part
2](#first-run-infisical-setup) finishes the job. See [What the Bootstrap
Playbooks Do](#what-the-bootstrap-playbooks-do) for the full breakdown.

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

**Expected duration:** 12–18 minutes (the Infisical bring-up — pulling images
and waiting for its API port — adds a few minutes over a pre-Infisical
bootstrap; most of that time is image pulls and container start/health-wait).

Part 1 ends with a debug message pointing you at [First-run Infisical
Setup](#first-run-infisical-setup) — complete that, then run
`bootstrap_edge_part2.yml` to finish Phase 1.

---

### What the Bootstrap Playbooks Do

Phase 1 is split into two playbooks around Infisical's first-run checkpoint —
its org, admin account, project, environment, and machine identities can't be
created until Infisical itself is up, which only happens partway through
bootstrap (see [First-run Infisical Setup](#first-run-infisical-setup) for why
this can't be automated away). Part 1 gets the node — and Infisical — running
and hands off to that manual setup; Part 2 seeds Infisical and brings up
Semaphore once the identities it needs exist.

#### Part 1 — `bootstrap_edge.yml`

| Task                       | Detail                                     |
|----------------------------|--------------------------------------------|
| Set hostname               | `homelab-edge`                             |
| Create `homelab` user      | Ansible automation, passwordless sudo      |
| Create `deploy` user       | Webhook/SSH trigger, restricted sudo       |
| Install Docker             |                                            |
| Install Tailscale          | Brought up here (not Phase 2) — `tailscale_up: true` — so Infisical (and, once Part 2 brings it up, Semaphore) is reachable over the tailnet by the end of Phase 1. See the [Mode](./docs/NETWORK.md#mode) note in NETWORK.md. |
| Install Ansible            | Edge becomes a control node                |
| Install Git                |                                            |
| Clone repo                 | `/opt/homelab`, owned by `homelab`         |
| Copy files to node         | `overrides.yml`, `homelab` SSH key pair — **`vault.yml`/`.vault_pass` are deliberately NOT copied** (they live only on the WSL/PC control host; see [Secrets](./CLAUDE.md#secrets) and `semaphore_infisical_implementation.md` Task 2). Phase 2+ resolves application secrets from Infisical at runtime instead (`roles/infisical/tasks/lookup.yml`) |
| Register SSH host key      | Edge's own key added to `/home/homelab/.ssh/known_hosts` — required for Phase 2 self-deploy |
| Harden SSH                 | Key-only auth, no root login, port changed to `ssh_port` via async restart; subsequent tasks reconnect on new port automatically |
| Bring up Infisical         | Renders `/opt/infisical/.env` (node-generated secrets), starts `infisical-db`/`infisical-redis`/`infisical`, waits for the API port (8222) to accept connections |
| Configure firewall         | UFW default-deny inbound; allow `ssh_port`/tcp, 53/udp+tcp (Pi-hole DNS, LAN only), 8222/tcp + 3010/tcp (Infisical/Semaphore, **Tailscale CGNAT range only** — `100.64.0.0/10`); SSH reachability verified before play completes. Port 80 (Caddy) opened in Phase 2. |
| Enable unattended upgrades |                                            |

**Sudo rules created:**

```
# /etc/sudoers.d/homelab
homelab ALL=(ALL) NOPASSWD:ALL

# /etc/sudoers.d/deploy
deploy ALL=(ALL) NOPASSWD: /usr/bin/ansible-playbook
```

Part 1 ends here: Infisical is running and reachable over Tailscale, but has
no org/admin/project/identities yet — and the firewall now restricts ports
8222/3010 to the Tailscale CGNAT range. Complete [First-run Infisical
Setup](#first-run-infisical-setup) steps 1–5 (entirely manual — through
Infisical's UI), then continue with Part 2.

#### Part 2 — `bootstrap_edge_part2.yml`

| Task               | Detail                                                                 |
|--------------------|------------------------------------------------------------------------|
| Seed Infisical     | **Gated** — authenticates as the `bootstrap` machine identity (created in First-run Infisical Setup step 5) and pushes every `[seed → ...]` secret from the WSL-local `vault.yml` into its mapped `/production/<folder>/<KEY>` path — additive, existing keys untouched — but only if that identity is actually configured (`vault_infisical_bootstrap_client_*` ≠ `"changeme"`); otherwise skips with instructions, as a safety net for running Part 2 too early. Reaches Infisical over the edge's **Tailscale IP** (`tailscale ip -4`), since Part 1's firewall step already restricted port 8222 to the Tailscale CGNAT range — the LAN IP (`ansible_host`) the original single-pass flow used can no longer reach it. |
| Bring up Semaphore | Renders `/opt/semaphore/.env` (node-generated Postgres password + the `runtime` identity's credentials for its own Ansible secret lookups), starts `semaphore-db`/`semaphore` |

Part 2 finishes Phase 1 — Infisical is seeded and Semaphore is up and
reachable over Tailscale. Its closing debug message reminds you to revoke the
`bootstrap` identity (step 8 below) before moving on to Phase 2.

---

### First-run Infisical Setup

**Why this exists:** Infisical's seed step needs a *bootstrap machine identity*
(`vault_infisical_bootstrap_client_id/secret`) with write access to push
application secrets from `vault.yml` into it. But a machine identity is
something Infisical itself mints — it cannot exist before Infisical has an
org, an admin account, a project, and an environment to grant it access to.
Nothing in Ansible can automate a system into having created its own
credentials before it existed; this first-run setup is an inherently manual,
one-time runbook done through Infisical's UI (or its REST API directly, if you
prefer scripting it).

This is why Phase 1 is split into two playbooks around this checkpoint (see
[What the Bootstrap Playbooks Do](#what-the-bootstrap-playbooks-do)):

1. **Part 1** — `ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge.yml` brings Infisical up (and locks the firewall down to its steady state) but stops there — it can't seed Infisical or bring up Semaphore yet, since `vault_infisical_bootstrap_client_*`/`vault_semaphore_admin_*` are still `"changeme"` placeholders and the identities they'd need don't exist. Its closing `debug` message points you here.
2. **You complete this runbook** (steps 1–6) — entirely manual, through Infisical's UI; nothing in Ansible can mint Infisical's own first credentials before Infisical exists to mint them.
3. **Part 2** — `ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge_part2.yml` (run in step 6 below) seeds Infisical from `vault.yml` using the `bootstrap` identity and brings Semaphore up using the `runtime` identity — both created in step 5. (`seed.yml` still gates on `vault_infisical_bootstrap_client_*` ≠ `"changeme"` as a safety net and will skip with instructions if you run Part 2 before finishing steps 1–5.)

**Before you start:** confirm you can reach the edge node over Tailscale —
`tailscale status` should list `homelab-edge`, then browse to
`http://<edge-tailscale-ip>:8222` (find the IP in the Tailscale admin console
or via `tailscale status`). Infisical does **not** get a Pi-hole hostname or
Caddy route — Tailscale is the only path in (see
[docs/NETWORK.md](./docs/NETWORK.md#tailscale-only-service-access-infisical--semaphore)).

1. **Create the org and admin account** — Infisical's first-run setup wizard
   walks you through both. Use a strong, unique password; this account has
   full control over every secret in the homelab.

2. **Create the project** — name it `homelab` (the slug must match
   `infisical_seed_project_slug` in `roles/infisical/defaults/main.yml`).

3. **Create the environment** — within the `homelab` project, add a
   `production` environment (must match `infisical_seed_environment`).

4. **Create the folders** — under the `production` environment, create these
   nine folders (they must match the "Secret naming convention" block at the
   top of `vault.yml.example` exactly — the seed task, Infisical lookups, and
   this runbook all have to agree on the layout):
   ```
   /camunda  /n8n  /discord  /cloudflare  /pihole  /grafana
   /ntfy     /greentechhub   /deploy
   ```

5. **Create two machine identities** (Access Control → Identities → Create
   identity → Universal Auth):

   | Identity    | Access level                                  | Used by                                  |
   |-------------|-----------------------------------------------|------------------------------------------|
   | `bootstrap` | Write access to the `homelab` project (all folders, `production` env) | The Phase 1 seed task — once, from WSL    |
   | `runtime`   | **Read-only** access to the same scope        | Semaphore's environment, for Ansible secret lookups during normal operation |

   For each identity, create a Universal Auth client secret and copy the
   **Client ID** and **Client Secret** immediately — the secret is shown only
   once. Keep the two identities' credentials separate; do not reuse one pair
   for both roles.

6. **Write the credentials into the vault and run Part 2:**
   ```bash
   ansible-vault edit inventories/group_vars/all/vault.yml
   ```
   Replace the four `"changeme"` placeholders:
   ```yaml
   vault_infisical_bootstrap_client_id: "<bootstrap identity client ID>"
   vault_infisical_bootstrap_client_secret: "<bootstrap identity client secret>"
   vault_infisical_runtime_client_id: "<runtime identity client ID>"
   vault_infisical_runtime_client_secret: "<runtime identity client secret>"
   ```
   Save, verify the vault re-encrypted (`head -1 ...vault.yml` → `$ANSIBLE_VAULT;`), then run Part 2:
   ```bash
   ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge_part2.yml
   ```
   This authenticates as the bootstrap identity, pushes every `[seed → ...]`
   secret from `vault.yml` into its mapped `/production/<folder>/<KEY>` path
   (additive — existing keys are never touched), then renders and brings up
   Semaphore with the runtime identity's credentials.

7. **Now run Phase 2** — `deploy_edge.yml` resolves its application secrets
   (`cloudflare/TUNNEL_TOKEN`, `pihole/WEB_PASSWORD`) from Infisical via the
   runtime identity you just created, so this is the first point it can
   succeed. See [Phase 2](#phase-2-edge--self-deploy) for both ways to run it
   (SSH into the edge, or directly from your PC/WSL):
   ```bash
   ansible-playbook playbooks/deploy_edge.yml --limit homelab-edge
   ```

8. **Revoke the bootstrap identity** — once the seed summary reports success
   (Infisical UI → Access Control → Identities → `bootstrap` → disable or
   delete it). It has write access to every secret in the homelab; there is no
   reason for it to remain active between seed runs. Re-enable it only for a
   deliberate re-seed (e.g. after rebuilding Infisical from a backup).

> **Re-seeding is safe and idempotent.** The seed task only creates keys that
> don't already exist (`status == 404`); anything already in Infisical is left
> untouched. Adding a brand-new service later just means adding its
> `vault_<service>_<field>` entries to `vault.yml`, its mapping to
> `_infisical_seed_map` in `roles/infisical/tasks/seed.yml`, its folder in
> Infisical, and re-running:
> ```bash
> ansible-playbook -i inventories/bootstrap.ini playbooks/bootstrap_edge_part2.yml --tags infisical,seed
> ```

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
- Re-asserts Tailscale in subnet-router mode (already brought up and joined during Phase 1 — see [What the Bootstrap Playbooks Do](#what-the-bootstrap-playbooks-do); idempotent here, a no-op once joined)
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
