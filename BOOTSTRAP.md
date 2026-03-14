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
  * [Phase 1: PC → Edge (Bootstrap)](#phase-1-pc--edge-bootstrap)
    * [1.1 Prepare Your PC](#11-prepare-your-pc)
    * [1.2 Move the Repo into the WSL Filesystem](#12-move-the-repo-into-the-wsl-filesystem)
    * [1.3 Find the Edge Node IP](#13-find-the-edge-node-ip)
    * [1.4 Generate SSH Keys](#14-generate-ssh-keys)
    * [1.5 Add GitHub Deploy Key](#15-add-github-deploy-key)
    * [1.6 Copy SSH Key to Edge Node](#16-copy-ssh-key-to-edge-node)
    * [1.7 Verify SSH Access](#17-verify-ssh-access)
    * [1.8 Create Ansible Vault](#18-create-ansible-vault)
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

- [ ] All Raspberry Pis flashed with **Raspberry Pi OS Lite (64-bit)**
- [ ] Edge node connected to the network (Ethernet recommended for bootstrap)
- [ ] Static DHCP reservations configured on router (recommended)

### Accounts

- [ ] GitHub account with access to this repository
- [ ] Cloudflare account (for Cloudflare Tunnel)
- [ ] Tailscale account

### Files

- [ ] This repository cloned on your PC
- [ ] Ansible Vault password chosen and stored securely (password manager recommended)

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

If mDNS is not available, check your router's DHCP lease table or use a network scanner. You'll need this IP in step 1.8.

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

Enter the default `admin` password when prompted. This is the only time a password is used for SSH.

---

### 1.7 Verify SSH Access

```bash
eval "$(ssh-agent -s)"
ssh-add .ssh/homelab-edge
ssh admin@homelab-edge.local
exit
```

If the connection succeeds without a password prompt (other than the key passphrase), the key is installed correctly.

---

### 1.8 Create Ansible Vault

Create a vault password file:

```bash
printf "your-strong-vault-password" > .vault_pass
chmod 600 .vault_pass
```

Create the vault:

```bash
ansible-vault create secrets/vault.yml --vault-password-file .vault_pass
```

Populate it using `secrets/vault.yml.example` as a reference. Save and exit (`:wq` in Vim).

> Keep `.vault_pass` out of version control. It is listed in `.gitignore` by default.

---

### 1.9 Configure Bootstrap Inventory

Edit `inventories/bootstrap.ini`:

```ini
[edge_bootstrap]
homelab-edge ansible_host=192.168.1.x ansible_user=admin ansible_ssh_private_key_file=~/.ssh/homelab-edge

[edge_bootstrap:vars]
ansible_python_interpreter=/usr/bin/python3
```

Replace `192.168.1.x` with the IP found in step 1.3.

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

```bash
ansible-playbook -i inventories/bootstrap.ini \
  playbooks/bootstrap_edge.yml \
  --vault-password-file .vault_pass \
  --ask-become-pass
```

Enter the `admin` sudo password when prompted. This is the last manual password entry.

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
| Harden SSH                 | Key-only auth, no root login               |
| Configure firewall         | ufw default-deny; allow 22 (any), 53 (LAN) |
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
cd /opt/homelab

ansible-playbook -i inventories/prod.ini \
  playbooks/deploy_edge.yml \
  --limit homelab-edge \
  --vault-password-file .vault_pass
```

**What `deploy_edge.yml` does:**

- Applies `base_hardening` role
- Configures firewall rules
- Deploys fail2ban
- Starts Tailscale in subnet-router mode
- Deploys Docker Compose stack:
  - `cloudflared` (Cloudflare Tunnel)
  - Pi-hole + Unbound (DNS)
  - `node-exporter` (metrics)
  - Grafana Alloy (logs → Loki, will forward once Loki is up in Phase 3)
- Populates Pi-hole `custom.list` with `.homelab.local` DNS entries
- Sets up log rotation and health checks

**Verify the deployment:**

```bash
docker ps
systemctl status tailscaled
dig @localhost example.com          # Test DNS resolution
dig @localhost grafana.homelab.local # Test internal hostname resolution
```

---

## Phase 3: Edge → Other Nodes

**Goal:** Deploy the observe node and service nodes from the edge.

All commands run on `homelab-edge` (or from your PC via the production inventory).

### 3.1 Deploy Observe Node

Prerequisites: `homelab-observe` has the base OS installed and is reachable via SSH from the edge node.

```bash
# Bootstrap the observe node
ansible-playbook -i inventories/prod.ini \
  playbooks/bootstrap_node.yml \
  --limit homelab-observe \
  --ask-pass --ask-become-pass

# Deploy the monitoring stack
ansible-playbook -i inventories/prod.ini \
  playbooks/deploy_observe.yml \
  --vault-password-file .vault_pass
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
ansible-playbook -i inventories/prod.ini \
  playbooks/bootstrap_node.yml \
  --limit homelab-svc-01

# Deploy the Camunda stack
ansible-playbook -i inventories/prod.ini \
  playbooks/deploy_svc.yml \
  --tags camunda \
  --vault-password-file .vault_pass
```

For `svc-02` (when provisioned):

```bash
ansible-playbook -i inventories/prod.ini \
  playbooks/bootstrap_node.yml \
  --limit homelab-svc-02

ansible-playbook -i inventories/prod.ini \
  playbooks/deploy_svc.yml \
  --tags greentechhub \
  --vault-password-file .vault_pass
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
