# 🏞️ Running the cluster at the remote site

The nodes live at a remote site. The main PC (WSL, the Ansible controller) stays at home and manages them over
**Tailscale**. The site router can't reserve DHCP addresses, so nodes get **static IPs** from Ansible. Because the
node IPs change, the cluster is **reset and rebuilt** at the site; it's empty, so nothing is lost.

> [!NOTE]
> **Status: moved.** The pre-move checklist was done at home on 14 Oct 2026 (Argon, Wake-on-LAN, power alerts,
> Tailscale policy, break-glass), and the cluster now runs at the site. The move steps below are kept as the runbook
> for moving or rebuilding it.

**Quick links:** [🔑 Access paths](#-access-paths) · [🏠 Before leaving home](#-before-leaving-home) ·
[🚚 At the site](#-at-the-site) · [🧮 Site LAN](#-site-lan) · [🖥️ Router UI](#️-router-ui) ·
[🆘 Break-glass](#-break-glass-when-tailscale-is-down) · [📌 Still open](#-still-open)

---

## 🔑 Access paths

| Situation                       | How you get in                                                                        |
|---------------------------------|----------------------------------------------------------------------------------------|
| Normal                          | Tailscale MagicDNS: Ansible (`<node>.<tailnet>.ts.net`), kubectl (`k8s-api` → laptop-01's Tailscale IP) |
| Device not on the tailnet       | laptop-01's **subnet route** to the site LAN (router UI, a freshly imaged node). Approve it in the console per use, then disable it ([Router UI](#️-router-ui)) |
| Tailscale down for the node     | **Break-glass certificate**: RDP to the site PC, SSH over the LAN with a 1-hour cert   |
| laptop-01 off                   | `playbooks/wake.yml` (Wake-on-LAN from a Pi); the Pis also do this after every boot     |
| Node hung                       | Argon button (Pis) / site power cycle; Pis boot by themselves, then wake laptop-01     |

---

## 🏠 Before leaving home

<details>
<summary>The pre-move checklist (done 14 Oct 2026)</summary>

1. **`overrides.yml`**:
   - `tailscale_tailnet`: the probe then tries MagicDNS names first.
   - `home_lan_subnet`: the site must never advertise this.
   - `mac_laptop_01`: laptop-01's wired NIC, for Wake-on-LAN (step 6).
   - `tailscale_admin_login`: optional; your login email, which turns on the policy's built-in tests.
2. **Admin OAuth client**: separate from the nodes' client, and it never leaves the controller.
   - Tailscale admin console → **Settings → OAuth clients** (newer consoles: **Settings → Trust credentials**, type
     OAuth). Description: `homelab-admin (controller)`.
   - Scopes: **General → Policy File: Write** and **Devices → Core: Write**. Nothing else.
   - Devices: Core write asks for tags: pick `tag:homelab`.
   - Generate, then copy the client ID and the secret (`tskey-client-…`). The secret is shown only once.
   - `ansible-vault edit inventories/group_vars/all/vault.yml` and add `vault_tailscale_admin_oauth_client_id` and
     `vault_tailscale_admin_oauth_client_secret` (see `vault.yml.example`).
   - If removing the stale devices fails with 403, delete them in the console once by hand. They predate
     `tag:homelab`, so the client may not be allowed to manage them.
3. **Tailscale policy** (`tailscale/policy.hujson.j2`). It also removes the stale `homelab-edge`, `homelab-observe`
   and `homelab-svc-01` devices.
   ```bash
   ansible-playbook playbooks/tailscale_admin.yml                  # validate + diff, changes nothing
   ansible-playbook playbooks/tailscale_admin.yml -e confirm=true  # apply
   ```
   Apply it now, not only at the site: the dry run changes nothing. If a stale device fails with 403, delete it in the
   console (step 2). The policy:
   - only admins tag nodes as `tag:homelab`;
   - your own devices can reach each other;
   - admins reach nodes on `ssh_port`, 22 and 6443;
   - the site route is admins-only and never auto-approved: you approve it per use;
   - nodes can't connect to your devices.
4. **Break-glass CA**: creates `.ssh/homelab-user-ca`. Back it up offline next to the age key.
   ```bash
   ansible-playbook playbooks/controller.yml -K --tags ssh_ca
   ansible-playbook playbooks/bootstrap.yml           # installs the CA public key on the nodes
   ```
   Test it at home: `ssh-keygen -t ed25519 -f /tmp/bg`, then `scripts/sign-breakglass.sh +5m` (paste `/tmp/bg.pub`
   and save the output as `/tmp/bg-cert.pub`), then `ssh -i /tmp/bg -p <ssh_port> admin@<node>`.
5. **Argon cases**: `bootstrap.yml` installs the power-button and fan daemon (`argon_case` in host_vars). Then set
   each case's **power jumper to "always on"**, so a Pi boots by itself when power returns. That's a physical
   setting on the case board.
6. **laptop-01 power** (it has no AC power-on in its BIOS, tested 14 Oct):
   - BIOS: Network → **Wake on LAN = AC Only**.
   - `overrides.yml`: `mac_laptop_01` (its wired NIC, `ip -br link`). Then `bootstrap.yml --tags wol,laptop`.
   - What happens in an outage:
     - **Power cut:** the Pis die at once. laptop-01 runs on its battery and posts **🔋 Site power lost**.
     - **Power back:** if laptop-01 was still running, it posts **🔌 Site power restored**.
     - **Long outage:** at `laptop_shutdown_battery_percent` (15%) it posts **🪫** and shuts down cleanly, so Wake-on-LAN
       stays armed.
     - **Power back after that:** the Pis boot by themselves (Argon always-on). rpi-03 sends magic packets until
       laptop-01 answers SSH (about 2 minutes), then posts **⏰ Wake** (or **❌** after 10 minutes).
   - The site router is usually down during a cut too, so the alerts arrive once its internet is back. They carry the
     time the event happened.
   - Wake on demand from home: `ansible-playbook playbooks/wake.yml` (polls until SSH is up).
   - Test: `sudo poweroff` laptop-01 with AC connected, then `wake.yml`. Unplug the charger for 30 seconds to see the
     power alerts.
7. **Don't reset the cluster yet.** `cluster_reset.yml` is step 5 at the site, right before `cluster.yml`. Until then,
   the old control plane fails to start on its new address; that's harmless, since the cluster is empty.
8. **Check everything over Tailscale only**, so nothing depends on the home LAN: `cluster_status.yml` reaches every
   node, and `tailscale status` on the PC shows them online.
9. **Back up** `.ssh/homelab-user-ca` and its passphrase offline, next to the age key.
10. **Shut down cleanly**, then unplug once the LEDs are off:
    ```bash
    ansible k8s -b -m community.general.shutdown
    ```

</details>

---

## 🚚 At the site

<details>
<summary>Rebuilding at the site</summary>

1. Plug in. The Pis boot by themselves (Argon always-on) and rpi-03 wakes laptop-01: expect **⏰ Wake** in Discord
   within a few minutes. That's the first real-world wake test. If it doesn't come, run `wake.yml` or press the
   laptop's power button. Nodes take a DHCP address from the site router and come back on Tailscale by themselves.
   Check with `ansible-playbook playbooks/cluster_status.yml`, or `tailscale status` on the PC.
2. Find out the site LAN (router UI, see [Router UI](#️-router-ui)): subnet, gateway, and the **DHCP pool range**.
   Pick static addresses **outside the pool**. Current values are under [Site LAN](#-site-lan).
3. **`overrides.yml`**:
   ```yaml
   lan_subnet: "<site subnet>/24"       # must not overlap home_lan_subnet
   lan_gateway: "<site router>"
   ip_laptop_01: "<static>"
   ip_rpi_03: "<static>"
   node_network_static: true
   tailscale_subnet_router: true        # laptop-01 advertises lan_subnet
   k8s_api_client_ip: "<laptop-01's Tailscale 100.x IP>"
   ```
4. Apply the node changes:
   ```bash
   ansible-playbook playbooks/bootstrap.yml
   ```
   This sets the static IPs (each node reboots once, and the play reconnects over Tailscale), turns the laptop's Wi-Fi
   off, advertises the subnet route (it stays unapproved until you approve it), and re-applies UFW for the new
   `lan_subnet`.
5. Push the policy again, because it now includes the site route, then rebuild the cluster:
   ```bash
   ansible-playbook playbooks/tailscale_admin.yml -e confirm=true
   ansible-playbook playbooks/controller.yml -K                       # k8s-api → Tailscale IP
   ansible-playbook playbooks/cluster_reset.yml                       # type "reset"
   ansible-playbook playbooks/cluster.yml
   ansible-playbook playbooks/cluster_status.yml -e connectivity_test=true
   kubectl get nodes -o wide                                          # from home, over the tailnet
   ```

</details>

---

## 🧮 Site LAN

| What                  | Range                          | Notes                                                        |
|-----------------------|--------------------------------|--------------------------------------------------------------|
| Router DHCP pool      | `192.168.50.30–192.168.50.239` | Shrunk from `.2–.254` on 21 Oct 2026. The router can't reserve |
| Node static IPs       | `.10`, `.11`, `.12`, `.21`     | `ip_*` in `overrides.yml`, set by `roles/node_network`       |
| Cilium LB-IPAM pool   | `192.168.50.240–192.168.50.250`| homelab-cluster `infrastructure/configs/cilium/`             |
| Gateway               | `192.168.50.240`               | `*.home.green-tech-hub.com` (Cloudflare record, DNS only)    |

Keep new static addresses below `.30` and LoadBalancer IPs at `.240` and above.

---

## 🖥️ Router UI

The router UI is reached from home over laptop-01's subnet route. The policy doesn't auto-approve the route, so it's
off until you turn it on:

1. Tailscale admin console → **Machines** → laptop-01 → **Edit route settings**: approve the `lan_subnet` route.
2. On the home PC, browse to `http://<lan_gateway>`. The router sees laptop-01's LAN address, so it treats this as a
   local login.
3. When you're done, untick the route again in the same dialog.

SSH tunnels (`ssh -L`) through a node don't work: the nodes have `AllowTcpForwarding no` (`base_hardening`,
`ssh_allow_tcp_forwarding`), so the route is the only way in and the console is the single on/off switch. The
fallback, if Tailscale is down, is the RDP PC at the site.

---

## 🆘 Break-glass, when Tailscale is down

1. RDP to the site PC, then `ssh-keygen -t ed25519 -f breakglass` (Windows has OpenSSH).
2. Copy `breakglass.pub` to the home PC (RDP clipboard), then run `scripts/sign-breakglass.sh`, which is valid for
   one hour by default.
3. Paste the certificate back as `breakglass-cert.pub`, then `ssh -i breakglass -p <ssh_port> admin@<node LAN IP>`.
   UFW allows SSH from the site LAN.
4. Afterwards, delete both files on the site PC. The certificate expires by itself.

---

## 📌 Still open

- **Outside monitoring:** nothing alerts if the whole site goes silent. The external Uptime Kuma at home is in the
  backlog and is now a priority.
- **Backups:** the backup drive at the site (M4, waiting for hardware) isn't off-site. The etcd snapshots and dumps also get copied home (etcd
  snapshot fetch: `playbooks/etcd_fetch.yml`, see `K8S_CLUSTER.md`).
