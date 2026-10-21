# 🏞️ Operating the remote site

The nodes live at a remote site. The main PC (WSL, the Ansible controller) stays at home and manages them over
**Tailscale**. The site router can't reserve DHCP addresses, so the nodes get **static IPs** from Ansible
(`roles/node_network`, `node_network_static: true`).

This doc covers how the site works day to day, the one-time setup that makes remote management possible, and how
to move the cluster to another site.

**Quick links:** [🔑 Access paths](#-access-paths) · [🧮 Site LAN](#-site-lan) · [🖥️ Router UI](#️-router-ui) ·
[🔌 Power and wake-up](#-power-and-wake-up) · [🆘 Break-glass](#-break-glass-when-tailscale-is-down) ·
[🧰 One-time setup](#-one-time-setup) · [🚚 Moving to another site](#-moving-to-another-site) ·
[📌 Still open](#-still-open)

---

## 🔑 Access paths

| Situation                   | How you get in |
|-----------------------------|----------------|
| Normal                      | Tailscale MagicDNS: Ansible to `<node>.<tailnet>.ts.net`, kubectl via `k8s-api` → laptop-01's Tailscale IP (`k8s_api_client_ip`) |
| A device not on the tailnet | laptop-01's **subnet route** to the site LAN (router UI, a freshly imaged node, `*.home` services from home). Approve it in the console per use, then disable it ([Router UI](#️-router-ui)) |
| Tailscale down on a node    | **Break-glass certificate**: RDP to the site PC, then SSH over the LAN with a one-hour cert ([Break-glass](#-break-glass-when-tailscale-is-down)) |
| laptop-01 off               | `playbooks/wake.yml` (Wake-on-LAN from a Pi). The Pis also do this after every boot |
| A node hung                 | The Argon button (Pis), or a site power cycle. The Pis boot by themselves, then wake laptop-01 |

---

## 🧮 Site LAN

Current site: `192.168.50.0/24`. The values are in `overrides.yml` (`lan_subnet`, `lan_gateway`, `ip_*`).

| What                  | Range                          | Set by |
|-----------------------|--------------------------------|--------|
| Router DHCP pool      | `192.168.50.30–192.168.50.239` | The router (shrunk from `.2–.254` on 21 Oct 2026). It can't reserve addresses |
| Node static IPs       | `.10`, `.11`, `.12`, `.21`     | `ip_*` in `overrides.yml`, applied by `roles/node_network` |
| Cilium LB-IPAM pool   | `192.168.50.240–192.168.50.250`| homelab-cluster `infrastructure/configs/cilium/` |
| Gateway               | `192.168.50.240`               | homelab-cluster `infrastructure/configs/gateway/`, and the Cloudflare `*.home` record (DNS only) |

> [!TIP]
> Keep new static addresses below `.30`, and LoadBalancer IPs at `.240` and above.

---

## 🖥️ Router UI

The router UI is reached from home over laptop-01's subnet route. The Tailscale policy never auto-approves the
route, so it's off until you turn it on:

1. Tailscale admin console → **Machines** → laptop-01 → **Edit route settings**: approve the `lan_subnet` route.
2. On the home PC, browse to `http://<lan_gateway>`. The router sees laptop-01's LAN address, so it treats this as a
   local login.
3. When you're done, untick the route again in the same dialog.

> [!NOTE]
> SSH tunnels (`ssh -L`) through a node don't work. The nodes have `AllowTcpForwarding no` (`base_hardening`,
> `ssh_allow_tcp_forwarding`), so the route is the only way in, and the console is its single on/off switch. If
> Tailscale is down, the fallback is the RDP PC at the site.

---

## 🔌 Power and wake-up

laptop-01 has no AC power-on in its BIOS (tested 14 Oct 2026). The Pis' Argon cases have their power jumper on
**always on**, so they boot by themselves when power returns.

| Event | What happens | Discord |
|---|---|---|
| Power cut | The Pis die at once. laptop-01 runs on its battery | 🔋 Site power lost |
| Power back, laptop-01 still up | Nothing to do | 🔌 Site power restored |
| Long outage | At `laptop_shutdown_battery_percent` (15%), laptop-01 shuts down cleanly, so Wake-on-LAN stays armed | 🪫 |
| Power back after that | The Pis boot. rpi-03 sends magic packets until laptop-01 answers SSH (about 2 minutes) | ⏰ Wake, or ❌ after 10 minutes |

- The site router is usually down during a cut too, so alerts arrive once its internet is back. They carry the
  time the event happened.
- To wake it on demand from home: `ansible-playbook playbooks/wake.yml`, which polls until SSH is up.
- After a power cut, run `cluster_status.yml`. If the Pis are NotReady, check the `k8s-api` hosts line (see
  [K8S_CLUSTER.md › Troubleshooting](./K8S_CLUSTER.md#-troubleshooting)).

---

## 🆘 Break-glass, when Tailscale is down

1. RDP to the site PC, then `ssh-keygen -t ed25519 -f breakglass` (Windows has OpenSSH).
2. Copy `breakglass.pub` to the home PC (RDP clipboard), then run `scripts/sign-breakglass.sh`. The certificate is
   valid for one hour by default.
3. Paste the certificate back as `breakglass-cert.pub`, then `ssh -i breakglass -p <ssh_port> admin@<node LAN IP>`.
   UFW allows SSH from the site LAN.
4. Afterwards, delete both files on the site PC. The certificate expires by itself.

---

## 🧰 One-time setup

Done once per controller and tailnet (14 Oct 2026). Repeat only for a new controller, a new tailnet, or a lost
CA.

<details>
<summary>🔐 <b>Admin OAuth client</b>: separate from the nodes' client, and it never leaves the controller</summary>

1. Tailscale admin console → **Settings → OAuth clients** (newer consoles: **Settings → Trust credentials**, type
   OAuth). Description: `homelab-admin (controller)`.
2. Scopes: **General → Policy File: Write** and **Devices → Core: Write**. Nothing else. Core write asks for tags:
   pick `tag:homelab`.
3. Generate, then copy the client ID and the secret (`tskey-client-…`). The secret is shown only once.
4. Run `ansible-vault edit inventories/group_vars/all/vault.yml` and add `vault_tailscale_admin_oauth_client_id` and
   `vault_tailscale_admin_oauth_client_secret` (see `vault.yml.example`).

</details>

<details>
<summary>📜 <b>Tailscale policy</b> (<code>tailscale/policy.hujson.j2</code>)</summary>

```bash
ansible-playbook playbooks/tailscale_admin.yml                  # validate + diff, changes nothing
ansible-playbook playbooks/tailscale_admin.yml -e confirm=true  # apply
```

The policy:
- lets only admins tag nodes as `tag:homelab`
- lets your own devices reach each other
- lets admins reach the nodes on `ssh_port`, 22 and 6443
- lets WSL on the main PC (`tag:dev-wsl`) reach the nodes the same way, since controller traffic leaves as that tag
  once WSL runs its own `tailscaled`, and lets admins reach WSL on 22 ([REMOTE_ACCESS.md](./REMOTE_ACCESS.md))
- makes the site route admins-only, never auto-approved (you approve it per use)
- stops nodes from connecting to your devices

Optional `overrides.yml` value: `tailscale_admin_login` (your login email), which turns on the policy's built-in
tests. If removing stale devices fails with 403, delete them in the console once by hand.

</details>

<details>
<summary>🆘 <b>Break-glass CA</b></summary>

```bash
ansible-playbook playbooks/controller.yml -K --tags ssh_ca   # creates .ssh/homelab-user-ca
ansible-playbook playbooks/bootstrap.yml                     # installs the CA public key on the nodes
```

Back up `.ssh/homelab-user-ca` and its passphrase offline, next to the age key. To test it:
1. `ssh-keygen -t ed25519 -f /tmp/bg`.
2. Run `scripts/sign-breakglass.sh +5m`, paste `/tmp/bg.pub`, and save the output as `/tmp/bg-cert.pub`.
3. `ssh -i /tmp/bg -p <ssh_port> admin@<node>`.

</details>

<details>
<summary>🔌 <b>Power: Argon cases and laptop-01 Wake-on-LAN</b></summary>

- **Argon cases:** `bootstrap.yml` installs the power-button and fan daemon (`argon_case` in host_vars). Set each
  case's **power jumper to "always on"** on the case board.
- **laptop-01:**
  - BIOS: Network → **Wake on LAN = AC Only**.
  - `overrides.yml`: `mac_laptop_01`, its wired NIC (`ip -br link`).
  - Then run `bootstrap.yml --tags wol,laptop`.
- **Test:** `sudo poweroff` laptop-01 with AC connected, then run `wake.yml`. Unplug the charger for 30 seconds to see
  the power alerts.

</details>

---

## 🚚 Moving to another site

A new site usually means a new subnet. The node IPs then change, and with them the API certificate and the etcd peer
URLs, so the cluster is **reset and rebuilt**. Flux then restores everything in git: Cilium's full settings, the
Gateway, the tunnel and the apps.

> [!CAUTION]
> Anything not in git or a backup is lost: local PV data on rpi-03, and in-cluster state that isn't declared. Back
> up PV data first (M6+). Run `etcd_fetch.yml` too, though a rebuild doesn't restore etcd.

<details>
<summary>🏠 <b>Before leaving the old site</b></summary>

1. **Check that everything is managed over Tailscale only**, so nothing depends on the old LAN: `cluster_status.yml`
   reaches every node, and `tailscale status` on the PC shows them online.
2. **Back up:** run `etcd_fetch.yml`, and copy any PV data off rpi-03.
3. **Don't reset the cluster yet.** `cluster_reset.yml` runs at the new site, right before `cluster.yml`.
4. **Shut down cleanly**, then unplug once the LEDs are off:
   ```bash
   ansible k8s -b -m community.general.shutdown
   ```

</details>

<details>
<summary>🚚 <b>At the new site</b></summary>

1. **Plug in.** The Pis boot by themselves and rpi-03 wakes laptop-01 (expect **⏰ Wake**). The nodes take DHCP
   addresses and come back on Tailscale by themselves. Check with `cluster_status.yml`, or `tailscale status` on the PC.
2. **Learn the LAN** (router UI): the subnet, the gateway and the **DHCP pool**. Shrink the pool if you can, to leave
   room for statics and LoadBalancer IPs.
3. **`overrides.yml`:**
   ```yaml
   lan_subnet: "<site subnet>/24"       # must not overlap home_lan_subnet
   lan_gateway: "<site router>"
   ip_laptop_01: "<static>"             # and ip_rpi_01/02/03, all outside the DHCP pool
   node_network_static: true
   tailscale_subnet_router: true        # laptop-01 advertises lan_subnet
   k8s_api_client_ip: "<laptop-01's Tailscale 100.x IP>"
   ```
4. **Apply the node changes:**
   ```bash
   ansible-playbook playbooks/bootstrap.yml
   ```
   This sets the static IPs (each node reboots once, and the play reconnects over Tailscale), turns the laptop's
   Wi-Fi off, advertises the new subnet route (unapproved until you approve it), and re-applies UFW for the new
   `lan_subnet`.
5. **Update the site-specific values elsewhere** in PRs, before Flux comes back:
   - homelab-cluster: the LB-IPAM pool (`infrastructure/configs/cilium/lb-ipam-pool.yaml`), the Gateway's
     `spec.addresses`, and Cilium's `k8sServiceHost` (laptop-01's new LAN IP) in the HelmRelease.
   - HomeLab: `gateway_lan_ip` in `cluster_status.yml`.
   - Cloudflare: the `*.home` A record → the new Gateway IP (homelab-cluster `docs/M4_PLATFORM.md`, "Cloudflare
     setup").
   - The [Site LAN](#-site-lan) table above.
6. **Rebuild:**
   ```bash
   ansible-playbook playbooks/tailscale_admin.yml -e confirm=true     # the policy includes the new site route
   ansible-playbook playbooks/controller.yml -K                       # k8s-api → Tailscale IP
   ansible-playbook playbooks/cluster_reset.yml                       # type "reset"
   ansible-playbook playbooks/cluster.yml
   ansible-playbook playbooks/flux_bootstrap.yml                      # Flux restores everything from git
   ansible-playbook playbooks/cluster_status.yml -e connectivity_test=true
   ```
   If the Gateway stays `Programmed: False`, restart `deploy/cilium-operator` once. It only checks for the Gateway API
   CRDs when it starts.

</details>

---

## 📌 Still open

- **Outside monitoring:** nothing alerts if the whole site goes silent. An external Uptime Kuma at home is in the
  backlog, as a priority.
- **Backups:** the backup drive at the site (M4, waiting for hardware) isn't off-site. etcd snapshots are also
  fetched home with `etcd_fetch.yml` (see [K8S_CLUSTER.md](./K8S_CLUSTER.md#-etcd-backups)).
