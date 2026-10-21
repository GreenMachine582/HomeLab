# 💻 Remote access to WSL

From your laptop, anywhere, SSH into WSL on the main PC (the Ansible controller). Only your approved tailnet devices
can reach it, and every login needs **your SSH key and a TOTP code**. No ports are open to the internet and no
router changes are needed.

> [!NOTE]
> **Scope today:** the main PC has to be **on**. Waking it remotely needs a Wake-on-LAN relay on its LAN (a Pi Zero
> W, not bought yet), and shutting down when idle only makes sense once it can be woken again. Both are under
> [⏭️ Later](#️-later-wake-on-lan-and-idle-shutdown).

**Quick links:** [🗺️ How it works](#️-how-it-works) · [✅ Prerequisites](#-prerequisites) ·
[🔧 Setup](#-setup) · [🖥️ Keeping the PC reachable](#️-keeping-the-pc-reachable) ·
[🚶 Day to day](#-day-to-day) · [🧪 Tests](#-tests) · [❓ Open questions](#-open-questions) ·
[⏭️ Later](#️-later-wake-on-lan-and-idle-shutdown)

---

## 🗺️ How it works

```text
Laptop (on the tailnet as you: IdP login with MFA, device approved)
  │  ssh <user>@dev-wsl ── tailnet ACL: only admins' devices reach :22
  ▼
Main PC (on) → WSL, systemd, tailscaled as dev-wsl (tag:dev-wsl)
  │  sshd: SSH key, then TOTP code, every login
  │
  │  Ansible / kubectl, leaving as tag:dev-wsl
  ▼
Homelab nodes (tag:homelab)
```

| Layer | What | Why |
|---|---|---|
| Network | Tailnet ACL `autogroup:admin → tag:dev-wsl:22`, **device approval** on | Nothing but your own approved, signed-in devices can open a connection |
| Login | OpenSSH in WSL: `AuthenticationMethods publickey,keyboard-interactive`, PAM `pam_google_authenticator` | A fresh second factor on every login; a stolen key alone gets nowhere |
| Policy | `tailscale/policy.hujson.j2`, pushed by `tailscale_admin.yml` | Policy as code; console edits get overwritten |
| WSL setup | `controller.yml --tags dev_wsl`; you run `tailscale up` and the TOTP enrolment | WSL is the controller, so you join it by hand and the TOTP secret never touches Ansible |

> [!NOTE]
> **Why not Tailscale SSH check mode?** On this plan, check mode re-asks at most every 12h (`checkPeriod` other than
> the default is Premium/Enterprise only). Tailscale SSH also replaces sshd and skips its PAM stack, so it can't be
> stacked with TOTP. Tailscale stays the network layer only.

> [!IMPORTANT]
> Once WSL runs its own `tailscaled`, Ansible and kubectl traffic to the nodes leaves as `tag:dev-wsl`, not as you.
> The policy allows `tag:dev-wsl → tag:homelab` on SSH and 6443 for this reason. Don't remove that rule while
> `dev-wsl` is on the tailnet.

---

## ✅ Prerequisites

- [ ] **Device approval** is on: admin console → Settings → Device management.
- [ ] The laptop is on the tailnet, signed in as you (an admin), and approved.
- [ ] An authenticator app on your phone (any TOTP app).
- [ ] Keep your current access method (Chrome Remote Desktop) until every [test](#-tests) passes.

---

## 🔧 Setup

<details>
<summary><b>1. Push the policy</b></summary>

The policy adds `tag:dev-wsl`, lets admins reach it on 22, and adds `tests` that Tailscale runs on every validate.

```bash
ansible-playbook playbooks/tailscale_admin.yml                  # validate + diff
ansible-playbook playbooks/tailscale_admin.yml -e confirm=true  # apply
```

</details>

<details>
<summary><b>2. Set up WSL</b></summary>

```bash
ansible-playbook playbooks/controller.yml --tags dev_wsl -K
```

- Sets `[boot] systemd=true` in `/etc/wsl.conf`. If systemd wasn't already running, the play stops and asks you to
  run `wsl --shutdown` from Windows, reopen WSL, and run it again.
- Installs and starts `tailscaled`. It never creates an auth key.
- Installs `openssh-server` and `libpam-google-authenticator`. Writes `/etc/ssh/sshd_config.d/00-dev-wsl.conf` (key
  then TOTP, only `dev_wsl_user`, no root, no passwords) and swaps the password prompt in `/etc/pam.d/sshd` for the
  TOTP prompt.
- Ends with a list of whatever manual steps are still missing (steps 3–5).

`dev_wsl_user` defaults to the user running the play; set it in `overrides.yml` if your WSL login differs.

</details>

<details>
<summary><b>3. Join WSL to the tailnet</b></summary>

```bash
sudo tailscale up --hostname=dev-wsl --advertise-tags=tag:dev-wsl --accept-dns=false
```

- Open the login link and sign in as yourself. Then approve `dev-wsl` in the admin console.
- `--accept-dns=false` leaves WSL's DNS alone (`k8s_client` manages `/etc/hosts`, and WSL generates
  `resolv.conf`). Step 6 confirms the node names still resolve.
- No `--ssh`: sshd answers on 22, not Tailscale SSH.

</details>

<details>
<summary><b>4. Add the laptop's key</b></summary>

On the laptop, make a key **with a passphrase** just for this:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/dev-wsl -C "laptop → dev-wsl"
```

Append `~/.ssh/dev-wsl.pub` to `~/.ssh/authorized_keys` in WSL (mode `600`, `~/.ssh` mode `700`). Then on the
laptop, in `~/.ssh/config`:

```text
Host dev-wsl
  HostName dev-wsl
  User <user>
  IdentityFile ~/.ssh/dev-wsl
  IdentitiesOnly yes
```

</details>

<details>
<summary><b>5. Enrol TOTP</b></summary>

In WSL, as `dev_wsl_user` (not with sudo):

```bash
google-authenticator -t -d -f -r 3 -R 30 -w 3
```

Time-based, no code reuse, at most 3 logins per 30 seconds, and a window of 3 codes for clock drift. Scan the QR
code with your authenticator app and store the **emergency scratch codes** in your password manager. The secret
lives only in `~/.google_authenticator`.

</details>

<details>
<summary><b>6. Check Ansible still reaches the nodes</b></summary>

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
ssh dev-wsl
```

1. Unlock the key (its passphrase, or your SSH agent).
2. Enter the current code from your authenticator app when asked for `Verification code:`.

---

## 🧪 Tests

All of these must pass before you retire Chrome Remote Desktop:

- [ ] A new device shows **Needs approval** and can't reach anything until you approve it.
- [ ] `ssh dev-wsl` asks for the TOTP code every time, and a wrong code is refused.
- [ ] Without the key (`ssh -o PubkeyAuthentication=no dev-wsl`) you're refused before the TOTP prompt.
- [ ] `ssh root@dev-wsl` and any other user are refused.
- [ ] `cluster_status.yml` from WSL still reaches every node.
- [ ] After the PC reboots, WSL is back on the tailnet and sshd answers, without anyone logging in to Windows.
- [ ] After you remove the laptop from the tailnet, it can't reach `dev-wsl:22`. Existing sessions are **not** killed
  automatically, so end them by hand.

---

## ❓ Open questions

1. **Task Scheduler with a passwordless account:** add a password, or use a dedicated local account. Decide after
   testing.
2. **Tailscale on both Windows and WSL:** keep the Windows client only if Windows itself must be on the tailnet (for
   example for break-glass RDP). Under WSL's **mirrored** networking mode the two clients can conflict, and WSL's sshd
   would also listen on the PC's LAN address. NAT mode (the default) keeps both apart. Check `networkingMode` in
   `%UserProfile%\.wslconfig`.
3. **Break-glass desktop access:** built-in Windows RDP allowed only from the Tailscale interface, or none at all.

---

## ⏭️ Later: wake-on-LAN and idle shutdown

On hold until a **Pi Zero W** is bought for the PC's LAN:

- **`wol-relay`:** Raspberry Pi OS Lite 32-bit (ARMv6), on Wi-Fi. An Ansible role installs Tailscale tagged
  `tag:wol-relay`, the same key + TOTP sshd as WSL, `wakeonlan`, `unattended-upgrades`, and a templated `wake-pc`
  script. It sits in its own `oob` inventory group, outside every Kubernetes group, and never joins the cluster.
- **Day to day then:** `ssh wol-relay`, then `wake-pc`, wait about 90 seconds, then `ssh dev-wsl`.
- **Idle watchdog in WSL:** a systemd timer that, once there have been no SSH sessions for 30 minutes (after a
  20-minute boot grace period), runs `shutdown.exe /s /t 120`. A flag file `/etc/idle-shutdown.disabled` turns it
  off for long jobs. It waits for the relay because, without Wake-on-LAN, a PC that shut itself down stays off.
- **PC prep for WoL:** turn on Wake on LAN in the BIOS, turn off ErP, enable "Wake on Magic Packet" on the NIC, use
  wired Ethernet, and record the MAC address for `wol_target_mac`.
