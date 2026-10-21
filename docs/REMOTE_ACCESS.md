# 💻 Remote access to WSL

From your laptop, anywhere, SSH into WSL on the main PC (the Ansible controller) over **Tailscale SSH**. Every new
session needs a browser re-auth with your identity provider's MFA. No ports are open to the internet, no router
changes are needed, and no SSH keys live on the laptop.

> [!NOTE]
> **Scope today:** the main PC has to be **on**. Waking it remotely needs a Wake-on-LAN relay on its LAN (a Pi Zero
> W, not bought yet), and shutting down when idle only makes sense once it can be woken again. Both are under
> [⏭️ Later](#️-later-wake-on-lan-and-idle-shutdown).

**Quick links:** [🗺️ How it works](#️-how-it-works) · [✅ Prerequisites](#-prerequisites) ·
[🔧 Setup](#-setup) · [🖥️ Keeping the PC reachable](#️-keeping-the-pc-reachable) ·
[🚶 Day to day](#-day-to-day) · [🧪 Tests](#-tests) · [🧯 Fallback](#-fallback) ·
[❓ Open questions](#-open-questions) · [⏭️ Later](#️-later-wake-on-lan-and-idle-shutdown)

---

## 🗺️ How it works

```text
Laptop (Tailscale, approved device, you as admin)
  │  ssh <user>@dev-wsl ── check mode → browser re-auth + IdP MFA, every session
  ▼
Main PC (on) → WSL, systemd, tailscaled as dev-wsl (tag:dev-wsl)
  │  Ansible / kubectl, leaving as tag:dev-wsl
  ▼
Homelab nodes (tag:homelab)
```

| Area | Decision | Why |
|---|---|---|
| Auth gate | Tailscale SSH **check mode**, `checkPeriod: "always"` | Re-auth with MFA on every new session, and nothing is exposed publicly |
| Device trust | Tailscale **device approval** on | A new device can't send traffic until you approve it |
| Policy | `tailscale/policy.hujson.j2`, pushed by `tailscale_admin.yml` | Policy as code; console edits get overwritten |
| WSL install | `controller.yml --tags dev_wsl` installs `tailscaled`; you run `tailscale up` | WSL is the controller, so you join it to the tailnet by hand and Ansible can't lock you out |

> [!IMPORTANT]
> Once WSL runs its own `tailscaled`, Ansible and kubectl traffic to the nodes leaves as `tag:dev-wsl`, not as you.
> The policy allows `tag:dev-wsl → tag:homelab` on SSH and 6443 for this reason. Don't remove that rule while
> `dev-wsl` is on the tailnet.

---

## ✅ Prerequisites

- [ ] Your Tailscale plan supports check mode with `checkPeriod: "always"`. If it doesn't, see
  [🧯 Fallback](#-fallback).
- [ ] Your identity provider (the login behind Tailscale) enforces MFA and asks for it again, rather than silently
  reusing a session.
- [ ] **Device approval** is on: admin console → Settings → Device management.
- [ ] The laptop is on the tailnet, signed in as you (an admin), and approved.
- [ ] Keep your current access method (Chrome Remote Desktop) until every [test](#-tests) passes.

---

## 🔧 Setup

<details>
<summary><b>1. Push the policy</b></summary>

The policy adds `tag:dev-wsl`, the check-mode SSH rule, and `tests` / `sshTests` that Tailscale runs on every
validate. `dev_wsl_user` defaults to the user running the playbook; set it in `overrides.yml` if your WSL login
differs.

```bash
ansible-playbook playbooks/tailscale_admin.yml                  # validate + diff
ansible-playbook playbooks/tailscale_admin.yml -e confirm=true  # apply
```

</details>

<details>
<summary><b>2. Install tailscaled in WSL</b></summary>

```bash
ansible-playbook playbooks/controller.yml --tags dev_wsl -K
```

This sets `[boot] systemd=true` in `/etc/wsl.conf`. If systemd wasn't already running, the play stops and asks you
to run `wsl --shutdown` from Windows, reopen WSL, and run it again. The second run installs and starts
`tailscaled`. It never creates an auth key.

</details>

<details>
<summary><b>3. Join WSL to the tailnet</b></summary>

```bash
sudo tailscale up --hostname=dev-wsl --advertise-tags=tag:dev-wsl --ssh --accept-dns=false
```

- Open the login link and sign in as yourself. Then approve `dev-wsl` in the admin console.
- `--accept-dns=false` leaves WSL's DNS alone (`k8s_client` manages `/etc/hosts`, and WSL generates
  `resolv.conf`). Check that MagicDNS names still resolve: `getent hosts laptop-01.<tailnet>.ts.net`.
- You don't need an OpenSSH server in WSL. Tailscale SSH answers on port 22 over the tailnet.

</details>

<details>
<summary><b>4. Check Ansible still reaches the nodes</b></summary>

```bash
ansible-playbook playbooks/cluster_status.yml
```

If this fails right after step 3, the `tag:dev-wsl → tag:homelab` rule isn't live. Re-run step 1.

</details>

---

## 🖥️ Keeping the PC reachable

- **Power:** set the Windows power plan to never sleep or hibernate, and turn Fast Startup off.
- **WSL after a reboot (e.g. Windows Update):** WSL only runs once something starts it. Add a Task Scheduler task:
  - **Trigger:** At startup.
  - **Action:** `wsl.exe -d <Distro> --exec sleep infinity`.
  - **Run as:** the Windows user who owns the distro, with **"Run whether user is logged on or not"**. SYSTEM can't
    see per-user distros.

> [!WARNING]
> "Run whether user is logged on or not" needs a stored account password. A passwordless Windows Hello account may
> block it. Either give the account a password (Hello still works for signing in locally) or use a dedicated local
> account. See [Open questions](#-open-questions).

---

## 🚶 Day to day

```bash
ssh <user>@dev-wsl
```

1. Tailscale prints a re-auth link. Open it and sign in with MFA.
2. The session opens. Every new session asks again.

---

## 🧪 Tests

All of these must pass before you retire Chrome Remote Desktop:

- [ ] A new device shows **Needs approval** and can't reach anything until you approve it.
- [ ] `ssh <user>@dev-wsl` prompts for re-auth and MFA every time.
- [ ] `ssh root@dev-wsl` is refused, and so is any device or user that isn't an admin.
- [ ] `cluster_status.yml` from WSL still reaches every node.
- [ ] After the PC reboots, WSL is back on the tailnet without anyone logging in to Windows.
- [ ] After you revoke access, new sessions are blocked. Existing sessions are **not** killed automatically, so end
  them by hand.

---

## 🧯 Fallback

If `checkPeriod: "always"` isn't available, or you want a separate second factor:

- Run OpenSSH in WSL with PAM TOTP (`libpam-google-authenticator`).
- Use Tailscale only as the network: keep the `tcp:22` ACL, and turn Tailscale SSH off (`tailscale set --ssh=false`)
  and remove the policy's `ssh` rule.

---

## ❓ Open questions

1. **Task Scheduler with a passwordless account:** add a password, or use a dedicated local account. Decide after
   testing.
2. **Tailscale on both Windows and WSL:** keep the Windows client only if Windows itself must be on the tailnet (for
   example for break-glass RDP). Under WSL's **mirrored** networking mode the two clients can conflict; NAT mode (the
   default) keeps them apart. Check `networkingMode` in `%UserProfile%\.wslconfig`.
3. **Break-glass desktop access:** built-in Windows RDP allowed only from the Tailscale interface, or none at all.

---

## ⏭️ Later: wake-on-LAN and idle shutdown

On hold until a **Pi Zero W** is bought for the PC's LAN:

- **`wol-relay`:** Raspberry Pi OS Lite 32-bit (ARMv6), on Wi-Fi. An Ansible role installs Tailscale tagged
  `tag:wol-relay` behind its own check-mode SSH rule, plus `wakeonlan`, `unattended-upgrades`, and a templated
  `wake-pc` script. It sits in its own `oob` inventory group, outside every Kubernetes group, and never joins the
  cluster.
- **Day to day then:** `ssh wol-relay`, then `wake-pc`, wait about 90 seconds, then `ssh dev-wsl`.
- **Idle watchdog in WSL:** a systemd timer that, once there have been no SSH sessions for 30 minutes (after a
  20-minute boot grace period), runs `shutdown.exe /s /t 120`. A flag file `/etc/idle-shutdown.disabled` turns it
  off for long jobs. It waits for the relay because, without Wake-on-LAN, a PC that shut itself down stays off.
- **PC prep for WoL:** turn on Wake on LAN in the BIOS, turn off ErP, enable "Wake on Magic Packet" on the NIC, use
  wired Ethernet, and record the MAC address for `wol_target_mac`.
