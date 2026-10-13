# Bootstrapping Kubernetes nodes

Runbook for `playbooks/bootstrap.yml`: takes a freshly installed node to a hardened, key-only host on the tailnet. Part
of milestone M1 in the Kubernetes migration; containerd and kubeadm follow in M2.

Everything runs from **WSL on the main PC**, in the `~/homelab` clone. It's the only Ansible controller.

## Nodes

| Inventory name | Role                    | OS                              | Install user |
|----------------|-------------------------|---------------------------------|--------------|
| `laptop-01`    | Control plane (amd64)   | Debian 13                       | see below    |
| `rpi-03`       | Data node, Pi 5 + NVMe  | Raspberry Pi OS Lite (trixie)   | see below    |

Groups in [`inventories/k8s.yml`](../inventories/k8s.yml): `k8s` → `k8s_control_plane`, `k8s_workers`, plus
`k8s_data` for the database node. They're deliberately not called `data`/`svc`, so the legacy group vars never apply.

## Before the first run

1. **Branch and collections**
   ```bash
   cd ~/homelab && git fetch && git switch k8s/bootstrap-nodes
   ansible-galaxy collection install -r requirements.yml
   sudo apt install sshpass          # needed for the first, password-based login
   ```
2. **Node IPs**: add these to `inventories/group_vars/all/overrides.yml` (gitignored), and pin them with router DHCP
   reservations:
   ```yaml
   lan_subnet: "<LAN CIDR>"
   ip_laptop_01: "<laptop-01 IP>"
   ip_rpi_03: "<rpi-03 IP>"
   ```
3. **Vault values used**, in `inventories/group_vars/all/vault.yml`:
   - `vault_admin_ssh_pubkey`: contents of `.ssh/homelab-edge.pub` (your interactive admin key)
   - `vault_homelab_ssh_pubkey`: contents of `.ssh/homelab.pub` (the Ansible key)
   - `vault_tailscale_oauth_client_id` / `_secret`: OAuth client with Auth Keys (write) and Devices (read), tag
     `tag:homelab`
   - `vault_discord_alerts_webhook`: boot/shutdown/SSH-login notifications

   `vault_deploy_ssh_pubkey` isn't used by k8s nodes.
4. **Install user**: the playbook first logs in as `bootstrap_user` (default `admin`) with a password and needs `sudo`.
   - If you created a different user, set `bootstrap_user` in `host_vars/<node>.yml`.
   - **Root** (`bootstrap_user: root`, used by laptop-01): Debian refuses root password logins over SSH by default.
     Allow it once on the console; the playbook deletes this file again after hardening:
     ```bash
     echo 'PermitRootLogin yes' > /etc/ssh/sshd_config.d/99-bootstrap-root.conf && systemctl restart ssh
     ```
     The playbook installs `sudo` itself (Debian leaves it out when a root password is set).
   - A non-root user needs sudo. Debian only grants that if the **root password was left blank** during install.
     Otherwise fix it on the console: `su -`, then `apt install sudo && usermod -aG sudo <user>`.
5. **Pi storage**: on the Pi, run `lsblk`. If `/` is on `nvme0n1`, the Pi boots from the NVMe, so leave
   `nvme_enabled: false` in `host_vars/rpi-03.yml`. `roles/nvme_storage` also refuses any partitioned or mounted device.
6. **Tailscale**: no existing tailnet device may already be named `laptop-01` or `rpi-03`. The role stops if one is.

## Run

```bash
ansible-inventory --graph                               # k8s groups and hosts
ansible-playbook playbooks/bootstrap.yml --syntax-check
ansible-playbook playbooks/bootstrap.yml --limit laptop-01
```

It prompts once, hidden, for the install user's password, if any targeted node is still fresh. Then do the same with
`--limit rpi-03`, which also renames the Pi from `homelab-data-01`.

`--check` doesn't work on a fresh node: the `users` role can't add keys for users that don't exist yet. Use
`--check --diff` on re-runs.

## What it does

1. **Probe** (runs locally), per node:
   - **Where:** TCP-probes these endpoints in order and uses the first that answers. This is the same order
     `bootstrap_edge.yml` uses. The tailnet entries only appear once `tailscale_tailnet` is set in `overrides.yml`, and
     the `fallback_ssh_port` entries only when it differs from `ssh_port`.
     1. `<node>.<tailnet>.ts.net:<ssh_port>`
     2. `<LAN IP>:<ssh_port>`
     3. `<node>.<tailnet>.ts.net:<fallback_ssh_port>`
     4. `<LAN IP>:<fallback_ssh_port>`

     A fresh node answers on `fallback_ssh_port` (22); a hardened one on `ssh_port`.
   - **Who:** tries `ssh -i ~/homelab/.ssh/homelab homelab@<endpoint>`. If that works, the node is hardened and Ansible
     connects as `homelab`. Otherwise it records the host key and connects as `bootstrap_user` with the password.
2. **Hostname**: set to the inventory name, and `/etc/hosts` updated to match.
3. **`users`**: creates `admin` (your key, sudo with password) and `homelab` (Ansible key, passwordless sudo).
4. **`base_hardening`**: package upgrades, chrony, unattended upgrades, sysctls, auditd, Discord notifications. It also
   moves sshd to `ssh_port` and switches it to **key-only with no root login** and asserts the effective `sshd -T` matches. The play then
   reconnects as `homelab` with the key.
5. **`nvme_storage`**: `k8s_data` nodes, only when `nvme_enabled: true`.
6. **`laptop_power`**: laptop-01 only. The lid switch is ignored, and the battery charge is capped at 80% if the
   firmware allows it.
7. **`tailscale`**: installs it from the Debian repo, then joins the tailnet with a freshly minted, tagged auth key.
8. **`firewall`**: UFW default-deny inbound; SSH allowed from the LAN and the tailnet. A 5-minute auto-rollback guards
   against lockout.

## Verify

```bash
ssh -p <ssh_port> -i .ssh/homelab homelab@<laptop-01 IP> hostname    # → laptop-01, no password
ssh -p <ssh_port> -o PubkeyAuthentication=no admin@<laptop-01 IP>    # → Permission denied (publickey)
ssh -p <ssh_port> -i .ssh/homelab homelab@<laptop-01 IP> ping -c2 <rpi-03 IP>   # nodes reach each other (M1 exit)
ansible-playbook playbooks/bootstrap.yml --limit laptop-01        # re-run: probe says "hardened", no prompt
```
