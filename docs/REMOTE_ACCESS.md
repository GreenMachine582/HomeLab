# 💻 Remote access to WSL

From your laptop, anywhere, SSH into WSL on the main PC (the Ansible controller). Only your approved tailnet devices
can reach it, and every login needs **your SSH key and a TOTP code**. No ports are open to the internet and no
router changes are needed.

> [!NOTE]
> **The PC is off by default.** It's woken, WSL is started, and both are stopped again **on demand**: by you today,
> and later from the laptop through a Wake-on-LAN relay on the PC's LAN (a Pi Zero W, not bought yet). Nothing
> shuts down automatically. See
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
| Power | PC off by default; woken, started and stopped on demand, never at boot and never automatically | The PC only runs while you want it to, and a dropped session never kills your work |

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
| **With the relay** | `ssh -t wol-relay pc-start` | `ssh -t wol-relay wsl-open`, which starts the on-demand task "HomeLab WSL" ([Relay design](#️-relay-design-pi-zero-w-not-bought-yet)) |

**Stopping** is also explicit: `wsl-close`, `pc-shutdown`, `pc-sleep` or `pc-restart` through the relay (today: by
hand). A dropped, expired or closed SSH session never shuts down the PC or WSL.

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

Once the relay exists (all from offsite, not just the LAN):

- [ ] `pc-start` wakes the PC from a **full shutdown** and from **sleep**.
- [ ] `wsl-open` reports WSL ready, and `ssh dev-wsl` works with no Windows login.
- [ ] `wsl-close`, `pc-sleep`, `pc-restart` and `pc-shutdown` each do what they say.
- [ ] A dropped or closed SSH session leaves the PC and WSL running.
- [ ] The Pi's trigger key is refused for anything outside `pc-control.ps1`'s allow-list (e.g. `ssh … whoami`).
- [ ] The PC is still found after its IP address changes.
- [ ] After a power cut, the relay rejoins the tailnet by itself and does **not** wake the PC.
- [ ] A hung Pi reboots itself (hardware watchdog).

---

## ❓ Open questions

1. **The on-demand task with a passwordless account:** "HomeLab WSL" needs "run whether logged on or not". Add a
   password to the account, or use a dedicated local account. Decide after testing.
2. **Tailscale on both Windows and WSL:** keep the Windows client only if Windows itself must be on the tailnet (for
   example for break-glass RDP). Under WSL's **mirrored** networking mode the two clients can conflict, and WSL's sshd
   would also listen on the PC's LAN address. NAT mode (the default) keeps both apart. Check `networkingMode` in
   `%UserProfile%\.wslconfig`.
3. **Break-glass desktop access:** built-in Windows RDP allowed only from the Tailscale interface, or none at all.

4. **Relay: `wsl.exe` from a Windows OpenSSH session.** `wsl-open` checks WSL is ready with short
   `wsl.exe --exec systemctl is-active` calls. Run the test below. If Windows refuses `wsl.exe` in an SSH session,
   `wsl-open` only starts the task and the laptop retries `ssh dev-wsl`.

<details>
<summary><b>Test <code>wsl.exe</code> over Windows SSH</b></summary>

On the PC, in **admin PowerShell**, run a throwaway Windows OpenSSH server on 2222:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
(Get-Content C:\ProgramData\ssh\sshd_config) -replace '^#?Port 22$','Port 2222' | Set-Content C:\ProgramData\ssh\sshd_config
New-NetFirewallRule -Name sshd-2222-test -DisplayName "sshd 2222 (test)" -Direction Inbound -Protocol TCP -LocalPort 2222 -RemoteAddress LocalSubnet -Action Allow
Start-Service sshd
ipconfig    # note the PC's IPv4 address for the test
```

From the laptop, on the **same LAN**:

```bash
ssh -p 2222 <winuser>@<pc ip> "hostname"                                         # sshd answers
ssh -p 2222 <winuser>@<pc ip> "wsl.exe -l -v"                                    # the session can see the distro
ssh -p 2222 <winuser>@<pc ip> "wsl.exe -d <Distro> --exec systemctl is-active tailscaled ssh"
ssh -p 2222 <winuser>@<pc ip> "wsl.exe -l --running"                             # still running after that call?
```

- **Pass:** your distro is listed, and the `systemctl` line prints `active` or `inactive` for each service.
- **Fail:** `Access is denied`, or an empty list.
- No password on your account (Windows Hello only)? Password login won't work: put the laptop's public key in
  `C:\ProgramData\ssh\administrators_authorized_keys` first (see [Relay design](#️-relay-design-pi-zero-w-not-bought-yet)
  for its permissions).

Clean up:

```powershell
Stop-Service sshd; Set-Service sshd -StartupType Manual; Remove-NetFirewallRule -Name sshd-2222-test
```

</details>

**Relay decisions (settled):**

- **Finding the PC:** by its **MAC address** only. There's no router access, so no DHCP reservations; the MAC is
  needed for Wake-on-LAN anyway. Each command looks up the PC's current IP with `arp-scan --localnet`.
- **Windows account:** admin, so the Pi's key goes in `C:\ProgramData\ssh\administrators_authorized_keys`.
- **Ansible to the relay:** TOTP is skipped **only from the home LAN** (`Match User <relay user> Address
  <home_lan_subnet>` → key only). Over the tailnet it's key + TOTP.
- **No automatic shutdown:** the laptop stops WSL and the PC explicitly. A dropped session never shuts anything down.
- **Relay reboots never wake the PC** (`wol_wake_at_boot: false`), and the Pi is kept always on
  ([Keeping the relay on](#keeping-the-relay-on)).

---

## 🛰️ Relay design (Pi Zero W, not bought yet)

The design so far. Nothing here is built yet; [open question 4](#-open-questions) is waiting on its test.

```text
Laptop
  │  ssh -t wol-relay <command> ── tailnet ACL: admins → tag:wol-relay:22; key + TOTP
  ▼
wol-relay (Pi Zero W, tag:wol-relay, home LAN, Wi-Fi)
  │  pc-start: Wake-on-LAN magic packets → PC's MAC; poll until Windows answers on 2222
  │  others:   find the PC's IP by MAC (arp-scan), then
  │            ssh -i ~/.ssh/pc-trigger -p 2222 <winuser>@<pc ip> <action>   (LAN only)
  ▼
Windows OpenSSH (port 2222) → pc-control.ps1 (forced command, allow-listed actions only)
  │  wsl-open / wsl-close / sleep / restart / shutdown
  ▼
Laptop: ssh dev-wsl ── key + TOTP
```

### The six commands

Run from the laptop as `ssh -t wol-relay <command>`:

| Command | What it does | How |
|---|---|---|
| `pc-start` | Wake the PC | Wake-on-LAN to the PC's MAC, then poll until Windows answers on 2222. Never touches Windows itself |
| `pc-shutdown` | Shut down | `shutdown /s /t 60` |
| `pc-restart` | Restart | `shutdown /r /t 60`. WSL isn't started afterwards: run `wsl-open` |
| `pc-sleep` | Sleep | `rundll32 powrprof.dll,SetSuspendState 0,1,0`. Needs hibernation off (`powercfg /h off`), or it hibernates instead. `pc-start` wakes it |
| `wsl-open` | Start WSL and keep it running | Starts the on-demand task "HomeLab WSL", waits until `tailscaled` and `sshd` are active, reports |
| `wsl-close` | Stop WSL cleanly | Stops the task, then `wsl.exe --terminate <Distro>` |

Typical session: `pc-start`, `wsl-open`, `ssh dev-wsl` … then `wsl-close` and `pc-shutdown` (or `pc-sleep`).

> [!TIP]
> Each `ssh wol-relay` asks for a TOTP code. Reuse one connection for a run of commands with this in the laptop's
> `~/.ssh/config`:
>
> ```text
> Host wol-relay
>   ControlMaster auto
>   ControlPath ~/.ssh/cm-%r@%h:%p
>   ControlPersist 10m
> ```
>
> `ssh dev-wsl` still asks separately.

### The pieces

- **Is the relay up?** From the laptop: `tailscale ping wol-relay`, or `tailscale status`.
- **The relay:**
  - Raspberry Pi OS Lite 32-bit (ARMv6), on Wi-Fi. Tailscale tagged `tag:wol-relay`, joined by hand
    (`tailscale up`, then approve), the same way as WSL.
  - The same key + TOTP sshd as WSL, through a shared role extracted from `controller.yml`, plus the home-LAN
    key-only exception for Ansible.
  - Its own `oob` inventory group, outside every Kubernetes group. It never joins the cluster.
  - The six commands in `/usr/local/bin`, sharing one helper: find the PC's IP by MAC (`arp-scan --localnet`), then
    call `pc-control` with the trigger key. `pc-start` reuses the Wake-on-LAN logic in `roles/wake_on_lan`.
  - A trigger keypair generated on the Pi, so the private key never leaves it.
- **Windows:**
  - OpenSSH Server on **port 2222**, key-only, with its firewall rule limited to `-RemoteAddress LocalSubnet`. Not
    22: WSL's localhost forwarding would clash with a Windows sshd on 22.
  - The Pi's key in `C:\ProgramData\ssh\administrators_authorized_keys` (admin account) as
    `restrict,from="<home LAN CIDR>",command="powershell -NoProfile -File C:\HomeLab\pc-control.ps1" ssh-ed25519 …`.
    The file must be readable only by Administrators and SYSTEM, or sshd ignores it:
    `icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"`.
  - `pc-control.ps1` reads the requested action from `$env:SSH_ORIGINAL_COMMAND` and runs only `wsl-open`,
    `wsl-close`, `sleep`, `restart` or `shutdown`. Anything else is refused and logged to `C:\HomeLab\pc-control.log`.
  - The **"HomeLab WSL"** task: no trigger (started only by `wsl-open`), runs `wsl.exe -d <Distro> --exec sleep
    infinity` as the distro owner with "run whether logged on or not".
  - `pc-control.ps1` lives in the repo under `scripts/windows/`, and `controller.yml` copies it to `C:\HomeLab`
    through `/mnt/c`. The task, OpenSSH Server and firewall rule are set up by hand, because they need your Windows
    password.

### Keeping the relay on

The Pi has no case and no power button: it runs whenever it has power, and boots by itself when power returns.

- **Power:** its own always-on USB supply. **Never a USB port on the PC**: it goes dead when the PC is off.
- **Hangs:** the hardware watchdog (`RuntimeWatchdogSec=15` in systemd) reboots a hung Pi.
- **Wi-Fi:** power-save off on `wlan0`, or a dozing Pi Zero W drops off the tailnet. Tailscale reconnects by itself
  after a reboot.
- **SD card:** journald capped, to limit wear and corruption from power cuts. Optional: raspi-config's read-only
  overlay for more protection, at the cost of harder updates.
- **Updates:** `unattended-upgrades` for security fixes, rebooting at 04:00 when needed. A reboot never wakes the PC.
- **Placement:** somewhere ventilated, off anything conductive. A case is cheap and recommended, but not required.

### PC prep for Wake-on-LAN

- **BIOS:** turn on Wake on LAN / "Power On by PCI-E", and turn ErP / deep sleep off.
- **NIC:** "Wake on Magic Packet" on, and allow it to wake the PC (Device Manager → the adapter → Power Management).
- **Windows:** Fast Startup off; hibernation off (`powercfg /h off`) so `pc-sleep` sleeps rather than hibernates.
- **Network:** wired Ethernet. Record the PC's MAC address (`getmac /v`): the relay finds and wakes the PC by it.
