# Homelab
![GitHub release](https://img.shields.io/github/v/release/GreenMachine582/HomeLab?include_prereleases)
![GitHub deployments](https://img.shields.io/github/deployments/GreenMachine582/HomeLab/Production)

<!-- TOC -->
* [Homelab](#homelab)
  * [One-Time Manual Setup (Required)](#one-time-manual-setup-required)
    * [1. Establish Initial SSH Access to the Edge Node](#1-establish-initial-ssh-access-to-the-edge-node)
      * [On your PC (Windows – PowerShell)](#on-your-pc-windows--powershell)
      * [Copy the public key to the edge node](#copy-the-public-key-to-the-edge-node)
      * [Verify access](#verify-access)
    * [2. Generate a GitHub SSH Key and Add It to GitHub](#2-generate-a-github-ssh-key-and-add-it-to-github)
      * [On the edge node](#on-the-edge-node)
      * [Add the key to GitHub](#add-the-key-to-github)
      * [Verify GitHub access (as homelab)](#verify-github-access-as-homelab)
    * [3. Prepare WSL for Ansible (One Time)](#3-prepare-wsl-for-ansible-one-time)
* [Tier-0 Bootstrap (Run from WSL / Ubuntu)](#tier-0-bootstrap-run-from-wsl--ubuntu)
      * [Copy the SSH key into WSL](#copy-the-ssh-key-into-wsl)
      * [Change to the Ansible project directory](#change-to-the-ansible-project-directory)
      * [Load environment variables](#load-environment-variables)
      * [Run the Edge Base bootstrap](#run-the-edge-base-bootstrap)
      * [Run the Edge Services bootstrap](#run-the-edge-services-bootstrap)
  * [Tier-1 Bootstrap (Project Control – Run from Edge)](#tier-1-bootstrap-project-control--run-from-edge)
      * [Run the Edge Control bootstrap](#run-the-edge-control-bootstrap)
<!-- TOC -->

---

## One-Time Manual Setup (Required)

These steps are intentionally **not automated**.
They establish **initial trust and credentials** so Ansible can take over safely and repeatably.

Once completed, **all further configuration is handled by Ansible**.

---

### 1. Establish Initial SSH Access to the Edge Node

This step allows Ansible to connect to the edge node for the first time.

#### On your PC (Windows – PowerShell)

Generate an SSH key for accessing the edge node (if you don’t already have one):

```powershell
ssh-keygen -t ed25519 -f .ssh/homelab-edge
```

This creates:

* `.ssh/homelab-edge` (private key)
* `.ssh/homelab-edge.pub` (public key)

#### Copy the public key to the edge node

Replace the hostname or IP address as required:

```powershell
type .ssh/homelab-edge.pub | ssh matt@homelab-edge "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

#### Verify access

```powershell
ssh -i .ssh/homelab-edge matt@homelab-edge
```

> ℹ️ Use `puttygen` (PuTTYgen) to convert the private key to `.ppk` format if using PuTTY.

---

### 2. Generate a GitHub SSH Key and Add It to GitHub

This key is used by the edge node to securely pull repositories and run automated deployments.

#### On the edge node

> ⚠️ Don't add a passphrase to this key, as it will be used for automated access.

```bash
cd ~/.ssh
ssh-keygen -t ed25519 -f github -C "your_email@example.com"
```

Start the SSH agent and add the key:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/github
```

Display the public key:

```bash
cat ~/.ssh/github.pub
```

---

#### Add the key to GitHub

**Recommended:** add this as a **Deploy Key** on the HomeLab repository.

1. Go to **GitHub → Repository → Settings → Deploy Keys**
2. Click **Add deploy key**
3. Paste the public key
4. Give it a clear name (e.g. `homelab-edge`)
5. Enable **Read access** (or Write only if required)
6. Save

---

#### Verify GitHub access (as homelab)

```bash
ssh -T git@github.com
```

Expected output:

```
Hi <github-username>! You've successfully authenticated, but GitHub does not provide shell access.
```

Exit the edge node:

```bash
exit
```

---

### 3. Prepare WSL for Ansible (One Time)

This is only required on the **machine running Ansible** (your PC via WSL).

1. Install **Ubuntu** from the Microsoft Store if not already installed.
2. Launch Ubuntu.
3. Run the following:
    ```bash
    sudo apt update
    sudo apt install -y ansible python3-pip ssh expect
    ```
4. Verify:
    ```bash
    ansible --version
    ```

---

## Tier-0 Bootstrap (Run from WSL / Ubuntu)

This stage bootstraps the edge node with **base OS configuration, users, security, and runtimes**.

> ⚠️ Run this _once per WSL session_:
> 
```bash
eval "$(ssh-agent -s)"
```

### 1. Copy the SSH key into WSL
```bash
cp /mnt/c/Users/Chad/OneDrive/Desktop/Python-Projects/HomeLab/.ssh/homelab-edge ~/.ssh/
chmod 600 ~/.ssh/homelab-edge
```

---

### 2. Change to the Ansible project directory

```bash
cd /mnt/c/Users/Chad/OneDrive/Desktop/Python-Projects/HomeLab/ansible
```

#### Load environment variables

```bash
set -a
source .env.secret
set +a
expect ./load_ssh_key.sh "$SSH_KEY"
```

#### Run the Edge Base bootstrap

```bash
ANSIBLE_CONFIG=./ansible.cfg ansible-playbook -i inventory_pc.yml bootstrap/edge-base.yml
```

---

### 3. Run the Edge Services bootstrap

```bash
ANSIBLE_CONFIG=./ansible.cfg ansible-playbook -i inventory_pc.yml bootstrap/edge-services.yml
```

This installs:

* Firewall (UFW)
* Fail2ban
* Docker
* Ansible runtime
* Clone repo

---

## Tier-1 Bootstrap (Project Control – Run from Edge)

This stage prepares **project-level state**, including repositories and control scripts.

### Run the Edge Control bootstrap

```bash
ssh matt@homelab-edge
```
```bash
sudo su homelab
cd ~/homelab/ansible
ANSIBLE_CONFIG=./ansible.cfg ansible-playbook -i inventory.yml bootstrap/edge-control.yml
```

---

## 5. Setup the Project
> Ensure you have an M.2 drive installed and formatted with `ext4` filesystem.
 
> ⚠️ Run all commands as root
### 5.1 Mount the M.2 drive
1. Identify:
```bash
lsblk -o NAME,PARTUUID,FSTYPE,SIZE,MOUNTPOINT,LABEL
```
2. Mount:
```bash
mkdir /mnt/m2drive
mount /dev/<name> /mnt/m2drive
```
4. Make it persistent:
```bash
nano /etc/fstab
```
Add:
```
PARTUUID=<part_id> /mnt/m2drive ext4 defaults 0 2
```
5. Test:
```bash
df -h /mnt/m2drive
```
---
### 5.2 Update the Docker configuration
1. Change Docker's global volume storage location:
```bash
mkdir -p /mnt/m2drive/docker
mkdir -p /etc/docker
nano /etc/docker/daemon.json
```
Add the following content to the file:
```json
{
  "data-root": "/mnt/m2drive/docker"
}
```
2. Then restart Docker service to apply the changes:
```bash
systemctl restart docker
```
---
