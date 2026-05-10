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
    * [1.8 Create Ansible Vault and Override Config](#18-create-ansible-vault-and-override-config)
    * [1.9 Configure Bootstrap Inventory](#19-configure-bootstrap-inventory)
    * [1.10 Run the Bootstrap Playbook](#110-run-the-bootstrap-playbook)
    * [What the Bootstrap Playbook Does](#what-the-bootstrap-playbook-does)
  * [Phase 2: Edge → Self-Deploy](#phase-2-edge--self-deploy)
  * [Phase 3: Edge → Other Nodes](#phase-3-edge--other-nodes)
    * [3.1 Deploy Observe Node](#31-deploy-observe-node)
    * [3.2 Deploy Service Nodes](#32-deploy-service-nodes)
  * [Phase 4: Automated Deployments](#phase-4-automated-deployments)
    * [How It Works](#how-it-works)
    * [4.1 Create the Deploy Script](#41-create-the-deploy-script)
    * [4.2 Configure the Automation Endpoint (n8n or Camunda)](#42-configure-the-automation-endpoint-n8n-or-camunda)
    * [4.3 GitHub Workflow](#43-github-workflow)
    * [4.4 Manual Trigger](#44-manual-trigger)
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

If mDNS is not available, check your router's DHCP lease table or use a network scanner. You'll need this IP in [step 1.9](#19-configure-bootstrap-inventory).

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
ssh-copy-id -i .ssh/homelab-edge.pub admin@homelab-edge.local
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
ssh admin@homelab-edge.local
exit
```

If the connection succeeds without a password prompt, the key is installed correctly. The agent stays active for the rest of your terminal session.

---

### 1.8 Create Ansible Vault and Override Config

Create a vault password file:

```bash
printf "your-strong-vault-password" > .vault_pass
chmod 600 .vault_pass
```

Create the vault:

```bash
EDITOR=nano ansible-vault create inventories/group_vars/all/vault.yml
```

Populate it using `inventories/group_vars/all/vault.yml.example` as a reference. Save and exit (`:wq` in Vim).

Create the local config:

```bash
cp inventories/group_vars/all/overrides.yml.example \
   inventories/group_vars/all/overrides.yml
```

Edit `overrides.yml` and fill in your actual IPs and `lan_subnet`. These override the `EDIT_BEFORE_USE` placeholders in `main.yml` and are automatically copied to the edge node by the bootstrap playbook.

---

### 1.9 Configure Bootstrap Inventory

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

### 1.10 Run the Bootstrap Playbook

Make sure the SSH key is loaded in `ssh-agent` (step 1.7) before running.

```bash
ansible-playbook -i inventories/bootstrap.ini \
  playbooks/bootstrap_edge.yml
```

No password prompts — the SSH key passphrase is handled by `ssh-agent` and the `admin` sudo password is read from the vault (`vault_admin_become_password`).

**Pre-flight checks run before anything touches the node:**
- Verifies all required local files exist: `.ssh/homelab-github`, `.ssh/homelab`, `.vault_pass`, `vault.yml`, `overrides.yml`
- Asserts all required variables are defined (`ssh_port`, `vault_github_org`, `homelab_repo_path`, etc.)

**Post-firewall validation:**
After UFW is enabled, the playbook probes `ssh_port` from your PC (via `wait_for`) and fails immediately if SSH is unreachable — so a misconfigured firewall is caught before the play reports success.

**Expected duration:** 10–15 minutes.

---

### What the Bootstrap Playbook Does

The `bootstrap_edge.yml` playbook fully configures the edge node:

| Task                       | Detail                                     |
|----------------------------|--------------------------------------------|
| Set hostname               | `homelab-edge`                             |
| Create `homelab` user      | Ansible automation, passwordless sudo      |
| Create `deploy` user       | Webhook/SSH trigger, restricted sudo       |
| Install Docker             |                                            |
| Install Ansible            | Edge becomes a control node                |
| Install Git                |                                            |
| Clone repo                 | `/opt/homelab`, owned by `homelab`         |
| Copy secrets to node       | `vault.yml`, `overrides.yml`, `.vault_pass`, `homelab` SSH key pair — edge can run Phase 2+ without manual file transfer |
| Register SSH host key      | Edge's own key added to `/home/homelab/.ssh/known_hosts` — required for Phase 2 self-deploy |
| Harden SSH                 | Key-only auth, no root login, port changed to `ssh_port` via async restart; subsequent tasks reconnect on new port automatically |
| Configure firewall         | UFW default-deny inbound; allow `ssh_port`/tcp, 80/tcp (Caddy), 53/any (LAN); SSH reachability verified before play completes |
| Enable unattended upgrades |                                            |
| Install Tailscale          | Not started yet; configured in Phase 2     |

**Sudo rules created:**

```
# /etc/sudoers.d/homelab
homelab ALL=(ALL) NOPASSWD:ALL

# /etc/sudoers.d/deploy
deploy ALL=(ALL) NOPASSWD: /usr/bin/ansible-playbook
```

---

## Phase 2: Edge → Self-Deploy

**Goal:** The edge node deploys its own services using Ansible running locally.

SSH into the edge node, or run from the PC targeting the edge via the production inventory.

```bash
ssh -p <ssh_port> admin@homelab-edge.local
```

```bash
sudo su - homelab 
```

```bash
cd /opt/homelab
ansible-playbook playbooks/deploy_edge.yml --limit homelab-edge
```

> `ansible.cfg` sets the default inventory (`prod.yml`) and vault password file — no `-i` or `--vault-password-file` flags needed.

**What `deploy_edge.yml` does:**

- Pulls latest repo from GitHub
- Deploys fail2ban (SSH and Pi-hole jails)
- Starts Tailscale in subnet-router mode
- Ships logs via Grafana Alloy (→ Loki once Phase 3 is up)
- Renders edge service configs (cloudflared, Pi-hole custom DNS, Caddy reverse proxy)
- Pulls and starts Docker Compose stack:
  - `cloudflared` (Cloudflare Tunnel — external ingress)
  - Pi-hole + Unbound (DNS with DNSSEC)
  - Caddy (LAN reverse proxy for `*.homelab.local`)
  - `node-exporter` and `pihole-exporter` (metrics)
  - Portainer Agent

> **Firewall note:** UFW rules are applied by `bootstrap_edge.yml` (Phase 1) and persist. To update rules after adding new services run: `ansible-playbook playbooks/apply_firewall.yml --limit homelab-edge`

**Verify the deployment:**

```bash
docker ps
systemctl status tailscaled
nslookup grafana.homelab.local 127.0.0.1   # Test Pi-hole DNS resolution
```

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
HTTP POST → n8n or Camunda webhook endpoint (running on homelab-svc-01/svc-02)
    ↓
n8n/Camunda workflow SSHes to homelab-edge as `deploy` user
    ↓
scripts/deploy.sh pulls latest repo + runs Ansible playbooks
    ↓
Ansible deploys to all target nodes
```

GitHub only needs to reach the n8n or Camunda endpoint — it never connects directly to the edge or any other node. All 
Ansible execution stays inside the homelab.

---

### 4.1 Create the Deploy Script

`scripts/deploy.sh` is already in the repo. It runs on the edge node when called by the automation endpoint:

```bash
#!/bin/bash
set -euo pipefail

cd /opt/homelab
git pull origin master

ansible-playbook -i inventories/prod.ini \
  playbooks/deploy_edge.yml \
  --vault-password-file .vault_pass

ansible-playbook -i inventories/prod.ini \
  playbooks/deploy_observe.yml \
  --vault-password-file .vault_pass

ansible-playbook -i inventories/prod.ini \
  playbooks/deploy_svc.yml \
  --vault-password-file .vault_pass
```

Ensure it is executable:

```bash
chmod +x scripts/deploy.sh
```

---

### 4.2 Configure the Automation Endpoint (n8n or Camunda)

**Option A — n8n (recommended for simplicity):**

1. Create a new workflow triggered by **Webhook** node
2. Validate the incoming request (check a shared secret header set by the GitHub workflow)
3. Add an **SSH** node pointing to `homelab-edge`, user `deploy`, using the `deploy` private key
4. Command: `/opt/homelab/scripts/deploy.sh`

**Option B — Camunda:**

1. Deploy a BPMN process with a message start event
2. Expose a REST endpoint via Camunda's API that receives the GitHub POST
3. Use a service task to SSH to the edge and run `scripts/deploy.sh`

Either way, store the `deploy` private key as a credential inside n8n/Camunda — it never touches GitHub.

---

### 4.3 GitHub Workflow

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

### 4.4 Manual Trigger

For ad-hoc deployments, SSH to the edge as `deploy` and run the script directly:

```bash
ssh deploy@homelab-edge
/opt/homelab/scripts/deploy.sh
```

The `deploy` user's sudo is restricted to `ansible-playbook` only. Deployments work even if GitHub or the automation 
endpoint is unavailable.
