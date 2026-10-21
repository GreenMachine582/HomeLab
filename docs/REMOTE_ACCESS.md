# 💻 Remote access to WSL

From your laptop, anywhere, SSH into WSL on the main PC (the Ansible controller). Only your approved tailnet devices
can reach it, and every login needs **your SSH key and a TOTP code**. No ports are open to the internet and no
router changes are needed.

> [!NOTE]
> **The PC is off by default.** It's woken and WSL is started **on demand**: by you today, and later by a
> Wake-on-LAN relay on its LAN (a Pi Zero W, not bought yet) that also shuts it down when idle. See
> [🖥️ Starting WSL on demand](#️-starting-wsl-on-demand) and [🛰️ Relay design](#️-relay-design-pi-zero-w-not-bought-yet).

**Quick links:** [🗺️ How it works](#️-how-it-works) · [✅ Prerequisites](#-prerequisites) ·
[🔧 Setup](#-setup) · [🖥️ Starting WSL on demand](#️-starting-wsl-on-demand) ·
[🚶 Day to day](#-day-to-day) · [🧪 Tests](#-tests) · [❓ Open questions](#-open-questions) ·
[🛰️ Relay design](#️-relay-design-pi-zero-w-not-bought-yet)

---

## 🗺️ How it works

```text
Laptop (on the tailnet as you: IdP login with MFA, device approved)
  │  ssh <user>@dev-wsl ── tailnet ACL: only admins' devices reach :22
  ▼
Main PC (woken on demand) → WSL (started on demand), systemd, tailscaled as dev-wsl (tag:dev-wsl)
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
| Power | PC off by default; woken and WSL started on demand, never at boot | The PC only runs while it's in use |

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

- Sets `[boot] systemd=true` in `/etc/wsl.conf`. This **doesn't start WSL**, at boot or ever. It only makes systemd
  WSL's init, so whenever WSL does start, `tailscaled` and `sshd` come up with it. If systemd wasn't already running,
  the play stops and asks you to run `wsl --shutdown` from Windows, reopen WSL, and run it again.
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

## 🖥️ Starting WSL on demand

Nothing starts WSL at boot, and the PC isn't kept awake. Two things have to happen before `ssh dev-wsl` works:

1. **The PC is on.** Turn Fast Startup off (it gets in the way of Wake-on-LAN). No never-sleep power plan.
2. **WSL is running and stays running.** WSL stops shortly after its last Windows-side process (`wsl.exe`) exits,
   and an incoming SSH session doesn't count as one. So something has to hold WSL open while you're connected.

| | Wake the PC | Start WSL and hold it open |
|---|---|---|
| **Today** | You: at the PC, or Chrome Remote Desktop | Open a WSL terminal and leave it open (or run `wsl.exe -d <Distro> --exec sleep infinity` in a minimised window) |
| **With the relay** | `wake-pc` on the Pi sends Wake-on-LAN | `wake-pc` runs `start-wsl.ps1` on Windows, which starts the on-demand task "HomeLab WSL" ([Relay design](#️-relay-design-pi-zero-w-not-bought-yet)) |

> [!WARNING]
> The relay's task has to run with **"Run whether user is logged on or not"**, because no one logs in after a remote
> wake. That needs a stored account password, which a passwordless Windows Hello account may block. It has to run
> as the Windows user who owns the distro, since SYSTEM can't see per-user distros. See
> [Open questions](#-open-questions).

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
- [ ] WSL starts only on demand: after a reboot, `dev-wsl` stays offline until something starts WSL, then
  `tailscaled` and `sshd` come up without any manual step inside WSL.
- [ ] After you remove the laptop from the tailnet, it can't reach `dev-wsl:22`. Existing sessions are **not** killed
  automatically, so end them by hand.

Once the relay exists:

- [ ] `wake-pc` wakes the PC from a **full shutdown**, tested from offsite, not just the LAN.
- [ ] `wake-pc` reports WSL ready, and `ssh dev-wsl` works with no Windows login.
- [ ] The PC shuts itself down after the idle period, and doesn't while an SSH session is open.
- [ ] The Pi's trigger key can't run anything on Windows except `start-wsl.ps1`.
- [ ] After a power cut, the relay rejoins the tailnet by itself and does **not** wake the PC.

---

## ❓ Open questions

1. **The on-demand task with a passwordless account:** "HomeLab WSL" needs "run whether logged on or not". Add a
   password to the account, or use a dedicated local account. Decide after testing.
2. **Tailscale on both Windows and WSL:** keep the Windows client only if Windows itself must be on the tailnet (for
   example for break-glass RDP). Under WSL's **mirrored** networking mode the two clients can conflict, and WSL's sshd
   would also listen on the PC's LAN address. NAT mode (the default) keeps both apart. Check `networkingMode` in
   `%UserProfile%\.wslconfig`.
3. **Break-glass desktop access:** built-in Windows RDP allowed only from the Tailscale interface, or none at all.

**Relay (decide before building it):**

4. **`wsl.exe` from a Windows OpenSSH session:** `start-wsl.ps1` checks WSL is ready with short
   `wsl.exe --exec systemctl is-active` calls. If Windows refuses `wsl.exe` in an SSH session, drop the check and let
   the laptop retry `ssh dev-wsl`.
5. **Finding the PC on the LAN:** DHCP reservations on the home router for the PC and the Pi, or discover the PC
   another way (mDNS `<pc>.local`).
6. **Windows account type:** an admin account reads keys from `C:\ProgramData\ssh\administrators_authorized_keys`;
   a standard account uses its own `~\.ssh\authorized_keys`.
7. **Ansible to the relay:** should the controller skip TOTP when it comes from the PC's LAN IP only
   (`Match User <user> Address <pc ip>/32` → `AuthenticationMethods publickey`)? Without it, every Ansible run on
   the relay needs a TOTP code.
8. **Idle rules:** are 30 min idle after a 20 min boot grace right, and should someone signed in at the console block
   the shutdown?
9. **Disable flag:** a Windows file (`C:\HomeLab\idle-shutdown.disabled`) or `/etc/idle-shutdown.disabled` in WSL.
10. **Relay reboots:** should the Pi ever wake the PC on its own after a power cut? Proposed: no
    (`wol_wake_at_boot: false`).

---

## 🛰️ Relay design (Pi Zero W, not bought yet)

The design so far. Nothing here is built yet; settle the [relay open questions](#-open-questions) first.

```text
Laptop
  │  ssh -t wol-relay wake-pc ── tailnet ACL: admins → tag:wol-relay:22; key + TOTP
  ▼
wol-relay (Pi Zero W, tag:wol-relay, home LAN, Wi-Fi)
  │  1. Wake-on-LAN magic packets → main PC; poll its LAN IP until Windows answers on 2222
  │  2. ssh -i ~/.ssh/pc-trigger -p 2222 <winuser>@<pc ip>   (LAN only, key forced to one script)
  ▼
Windows OpenSSH (port 2222) → start-wsl.ps1
  │  starts the on-demand task "HomeLab WSL", waits until tailscaled and sshd are active, reports back
  ▼
Laptop: ssh dev-wsl ── key + TOTP
```

- **Is the relay up?** From the laptop: `tailscale ping wol-relay`, or `tailscale status`.
- **The relay:**
  - Raspberry Pi OS Lite 32-bit (ARMv6), on Wi-Fi. Tailscale tagged `tag:wol-relay`, joined by hand
    (`tailscale up`, then approve), the same way as WSL.
  - The same key + TOTP sshd as WSL, through a shared role extracted from `controller.yml`.
  - Its own `oob` inventory group, outside every Kubernetes group. It never joins the cluster.
  - `roles/wake_on_lan`, generalised so it can target the PC: the target list, ports and subnet become variables,
    and the nodes' behaviour doesn't change.
  - A trigger keypair generated on the Pi, so the private key never leaves it.
  - `unattended-upgrades`, a small journald, and nothing else.
- **Windows:**
  - OpenSSH Server on **port 2222**, key-only, with its firewall rule scoped to the Pi's IP. Not 22: WSL's localhost
    forwarding would clash with a Windows sshd on 22.
  - The Pi's key in `authorized_keys` as
    `restrict,from="<pi ip>",command="powershell -NoProfile -File C:\HomeLab\start-wsl.ps1" ssh-ed25519 …`, so it
    can run that one script and nothing else.
  - The **"HomeLab WSL"** task: no trigger (started only by `start-wsl.ps1`), runs `wsl-session.ps1` as the distro
    owner with "run whether logged on or not".
  - `start-wsl.ps1` and `wsl-session.ps1` live in the repo under `scripts/windows/`, and `controller.yml` copies them
    to `C:\HomeLab` through `/mnt/c`. The task, OpenSSH Server and firewall rule are set up by hand, because they need
    your Windows password.
- **Idle shutdown, on the Windows side:**
  - `wsl-session.ps1` holds WSL open with `wsl.exe -d <Distro> --exec sleep infinity`.
  - Every 5 minutes it counts SSH sessions into WSL.
  - After a 20-minute boot grace period, once it has been idle for 30 minutes, with no one at the console and no
    disable flag, it runs `shutdown /s /t 120`.
  - It logs each decision to `C:\HomeLab\wsl-session.log`.
- **PC prep for Wake-on-LAN:**
  - BIOS: turn on Wake on LAN / "Power On by PCI-E", and turn ErP / deep sleep off.
  - NIC: "Wake on Magic Packet" on, and allow it to wake the PC.
  - Use wired Ethernet, and record the PC's MAC address.
