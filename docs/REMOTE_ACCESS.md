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
[🔧 Setup](#-setup) · [🪟 Windows and WSL on the tailnet](#-windows-and-wsl-on-the-tailnet) ·
[🖥️ Starting WSL on demand](#️-starting-wsl-on-demand) ·
[🚶 Day to day](#-day-to-day) · [🛡️ If the laptop is stolen or hacked](#️-if-the-laptop-is-stolen-or-hacked) ·
[🧪 Tests](#-tests) · [❓ Open questions](#-open-questions) · [🛰️ Relay design](#️-relay-design-pi-zero-w-not-bought-yet)

---

## 🗺️ How it works

```text
Laptop (on the tailnet as you: IdP login with MFA, device approved)
  │  ssh <user>@dev-wsl ── tailnet ACL: only admins' devices reach :22
  ▼
Main PC (woken on demand)
  ├─ Windows: Tailscale client as tag:dev-pc ── your devices reach only dev_pc_ports; answers MagicDNS for WSL
  └─ WSL (started on demand), systemd, tailscaled as dev-wsl (tag:dev-wsl)
       │  sshd: SSH key, then TOTP code, every login
       │
       │  Ansible / kubectl, leaving as tag:dev-wsl
       ▼
     Homelab nodes (tag:homelab)
```

| Layer | What | Why |
|---|---|---|
| Network | Tailnet ACL `autogroup:admin → tag:dev-wsl:22`, **device approval** on. Windows (`tag:dev-pc`): only `dev_pc_ports` from your devices | Nothing but your own approved, signed-in devices can open a connection, and Windows exposes only the dev ports you chose |
| Login | OpenSSH in WSL: `AuthenticationMethods publickey,keyboard-interactive`, PAM `pam_google_authenticator` | A fresh second factor on every login; a stolen key alone gets nowhere |
| Policy | `tailscale/policy.hujson.j2`, pushed by `tailscale_admin.yml` | Policy as code; console edits get overwritten |
| WSL setup | `controller.yml --tags dev_wsl`; you run `tailscale up` and the TOTP enrolment | WSL is the controller, so you join it by hand and the TOTP secret never touches Ansible |
| Power | PC off by default; woken, started and stopped on demand, never at boot and never automatically | The PC only runs while you want it to, and a dropped session never kills your work |
| Detection & response | Login alerts on every SSH login (dev-wsl now, the relay later), and a [removal checklist](#️-if-the-laptop-is-stolen-or-hacked) | A login you didn't make stands out, and a lost laptop is cut off from your phone in minutes |

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
- [ ] **Node key expiry** is on for the laptop (never "Disable key expiry"), and the tailnet's key expiry is set to
  **30 days** (Settings → Device management). A stolen laptop then drops off the tailnet by itself; the cost is a
  monthly IdP + MFA re-auth.
- [ ] The laptop is on the tailnet, signed in as you (an admin), and approved.
- [ ] The laptop has **full-disk encryption** and locks itself when idle.
- [ ] An authenticator app on your phone (any TOTP app).
- [ ] You can sign in to the **Tailscale admin console and your IdP from your phone**. That's how you cut off a lost
  laptop ([checklist](#️-if-the-laptop-is-stolen-or-hacked)).
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

- Checks WSL is in **NAT** networking mode (`wslinfo --networking-mode`) and stops if it's mirrored
  ([why](#-windows-and-wsl-on-the-tailnet)).
- Sets `[boot] systemd=true` in `/etc/wsl.conf`. This **doesn't start WSL**, at boot or ever. It only makes systemd
  WSL's init, so whenever WSL does start, `tailscaled` and `sshd` come up with it. If systemd wasn't already running,
  the play stops and asks you to run `wsl --shutdown` from Windows, reopen WSL, and run it again.
- Installs and starts `tailscaled`. It never creates an auth key.
- Installs `openssh-server` and `libpam-google-authenticator`. Writes `/etc/ssh/sshd_config.d/00-dev-wsl.conf` (key
  then TOTP, only `dev_wsl_user`, no root, no passwords; sessions dropped about 3 minutes after the laptop goes
  silent; no agent forwarding or tunnels) and swaps the password prompt in `/etc/pam.d/sshd` for the TOTP prompt.
- Starts **login alerts**: every accepted SSH login posts to Discord as `dev-wsl` (the nodes' `on-ssh-success`
  watcher).
- Ends with a list of whatever manual steps are still missing (steps 3–6), and warns if MagicDNS names stop
  resolving in WSL.

`dev_wsl_user` defaults to the user running the play; set it in `overrides.yml` if your WSL login differs.

</details>

<details>
<summary><b>3. Join WSL to the tailnet</b></summary>

```bash
sudo tailscale up --hostname=dev-wsl --advertise-tags=tag:dev-wsl --accept-dns=false
```

- Open the login link and sign in as yourself. Then approve `dev-wsl` in the admin console.
- `--accept-dns=false` leaves WSL's DNS alone (`k8s_client` manages `/etc/hosts`, and WSL generates
  `resolv.conf`). MagicDNS names keep resolving through the Windows client. Step 7 confirms it.
- No `--ssh`: sshd answers on 22, not Tailscale SSH.

</details>

<details>
<summary><b>4. Add the laptop's key</b></summary>

On the laptop, make a key **with a strong, unique passphrase**, used only for dev-wsl. One key per destination
means you can revoke one without the other:

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
  # the agent forgets the key after an hour
  AddKeysToAgent 1h
  ForwardAgent no
```

Keep the TOTP secret and scratch codes off the laptop's disk (your password manager is fine).

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
<summary><b>6. Tag the Windows client</b></summary>

In **admin PowerShell** on the PC:

```powershell
tailscale up --advertise-tags=tag:dev-pc --hostname=dev-pc --unattended --reset
```

Sign in as yourself, then approve the device in the admin console if asked.

- `--hostname=dev-pc` gives Windows a stable tailnet name (otherwise it's the computer name).
- `--unattended` keeps the client running with **no one signed in to Windows**, which is the normal state after a
  remote wake. Without it, MagicDNS for WSL and your dev ports vanish until someone logs in.
- `--reset` is needed because Windows' `tailscale up` otherwise insists you restate every flag set before.
  Afterwards, re-tick **Use Tailscale DNS** in the tray menu if it's off (WSL depends on it). Set `dev_pc_ports` to the dev ports your devices should reach, and
push the policy again (step 1). See [🪟 Windows and WSL on the tailnet](#-windows-and-wsl-on-the-tailnet).

</details>

<details>
<summary><b>7. Check Ansible still reaches the nodes</b></summary>

```bash
ansible-playbook playbooks/cluster_status.yml
```

If this fails right after step 3, the `tag:dev-wsl → tag:homelab` rule isn't live. Re-run step 1. If node names
don't resolve, the Windows client or its DNS setting is off.

</details>

---

## 🪟 Windows and WSL on the tailnet

The PC runs **two** Tailscale nodes, and both stay on:

| Node | What | Carries |
|---|---|---|
| `dev-pc` (`tag:dev-pc`) | The Windows Tailscale client, in unattended mode | Windows apps' tailnet traffic (local dev work), and **MagicDNS for WSL** |
| `dev-wsl` (`tag:dev-wsl`) | `tailscaled` inside WSL | WSL's tailnet traffic: Ansible, kubectl, and your SSH into WSL |

- **NAT networking mode is required.** WSL's default NAT mode runs it as its own small VM with its own network
  stack, so the two clients never meet. **Mirrored** mode shares the PC's interfaces, where they clash and WSL's sshd
  would also listen on the LAN. `controller.yml --tags dev_wsl` checks this and stops on mirrored.
- **DNS goes through Windows.** WSL runs with `--accept-dns=false` and resolves through Windows, whose client answers
  MagicDNS. That's how Ansible finds `<node>.<tailnet>.ts.net`. If the Windows client is off, WSL loses those names.
- **Windows is tagged** so it leaves `autogroup:self`. Untagged, every one of your devices (a stolen laptop included)
  could reach **every** port on Windows: SMB, RDP, dev servers, and later the relay's sshd on 2222. Tagged:
  - your devices reach only `dev_pc_ports` (`group_vars/all/main.yml`, e.g. `[8096]`; empty means nothing);
  - Windows keeps reaching the nodes (`ssh_port`, 22, 6443) and, when you approve it, the site route. WSL's site
    LAN traffic also goes out through Windows, since WSL doesn't accept routes.
- The policy's `tests` check that SMB (445), RDP (3389) and 2222 stay closed unless you list them.

---

## 🖥️ Starting WSL on demand

Nothing starts WSL at boot, and the PC isn't kept awake. Two things have to happen before `ssh dev-wsl` works:

1. **The PC is on.** Turn Fast Startup off (it gets in the way of Wake-on-LAN). No never-sleep power plan.
2. **WSL is running and stays running.** WSL stops shortly after its last Windows-side process (`wsl.exe`) exits,
   and an incoming SSH session doesn't count as one. So something has to hold WSL open while you're connected.

| | Wake the PC | Start WSL and hold it open |
|---|---|---|
| **Today** | You: at the PC, or Chrome Remote Desktop | Open a WSL terminal and leave it open (or run `wsl.exe -d <Distro> --exec sleep infinity` in a minimised window) |
| **With the relay** | `ssh wol-relay pc-start` | `ssh wol-relay wsl-open`, which starts the on-demand task "HomeLab WSL" ([Relay design](#️-relay-design-pi-zero-w-not-bought-yet)) |

`<Distro>` is the WSL distro's name from `wsl -l -v` (the default here is `Ubuntu`).

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

With the relay, a full session is:

```bash
ssh wol-relay pc-start      # wake the PC          (key + TOTP)
ssh wol-relay wsl-open      # start WSL            (key + TOTP)
ssh dev-wsl                 # work                 (key + TOTP)
ssh wol-relay wsl-close     # stop WSL             (key + TOTP)
ssh wol-relay pc-shutdown   # or pc-sleep          (key + TOTP)
```

Every connection asks for a code. That's deliberate: there's no connection sharing (`ControlMaster`), because a
lingering shared connection would let malware on the laptop run commands without one.

---

## 🛡️ If the laptop is stolen or hacked

### What an attacker needs

| Scenario | They have | They still need |
|---|---|---|
| **Stolen** (off or locked) | Tailnet membership (until removed or its key expires), the encrypted key files | The laptop's disk-encryption/login password, each key's passphrase, **and** a TOTP code from your phone |
| **Hacked** (malware while you use it) | Anything you type (passphrases), a loaded agent, any open session | TOTP codes are single-use, so a captured code can't be replayed, but an **open session can be ridden**. Hence the short agent lifetime, no connection sharing, login alerts, and the limits on what each login can reach |

### Blast radius

What a successful login can reach, so you know what to rotate:

- **dev-wsl** is the homelab's Ansible controller: `vault.yml` and `.vault_pass`, the nodes' SSH key, the kubeconfig,
  the SOPS age key, and the break-glass CA (passphrase-protected). `sudo` in WSL keeps its password; never make it
  NOPASSWD.
- **Windows:** WSL interop lets anything in WSL run Windows programs as your (admin) Windows account and read all of
  `C:`. **Known risk, kept on deliberately**: disabling it (`[interop] enabled=false`) would break Windows tools
  from WSL day to day. Over the tailnet, Windows itself exposes only `dev_pc_ports`.
- **The relay:** only the six commands. The laptop's login there has no shell and no sudo
  ([Relay design](#the-pieces)).

### Response checklist

From your phone, as soon as you notice:

1. **Tailscale admin console → remove the laptop.** It loses tailnet access at once. Its open SSH sessions stall,
   and sshd drops them within about 3 minutes (`ClientAliveInterval 60`, `ClientAliveCountMax 3`).
2. **Your IdP:** sign out all sessions and change the password.
3. **Look for logins you didn't make:** the login alerts, and `journalctl -u ssh` / `last` on dev-wsl and the relay.

Back at the PC:

4. Remove the laptop's keys from `~/.ssh/authorized_keys` on dev-wsl and the relay. Re-enrol TOTP
   (`google-authenticator`) only if the phone was lost too.
5. **If anyone got in**, treat everything dev-wsl holds as exposed and rotate it: the vault password and its
   secrets, the nodes' SSH key, cluster credentials, the age key, the Tailscale OAuth clients, and the Cloudflare
   token (homelab-cluster `docs/SECRETS.md` has the recreate steps). Check Windows too, given interop.
6. A replacement laptop gets **new** keys, then device approval as usual.

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
- [ ] **Removal drill:** with a session open, remove the laptop in the admin console. It can't reach `dev-wsl:22`,
  and the open session drops within a few minutes. Then re-add the laptop.
- [ ] `ssh -A dev-wsl` gets no forwarded agent (`ssh-add -l` inside says it can't connect).
- [ ] Every login to dev-wsl posts a Discord alert naming `dev-wsl`.
- [ ] `wslinfo --networking-mode` in WSL prints `nat`.
- [ ] From the laptop, Windows answers only on `dev_pc_ports`: `nc -zv dev-pc <port>` works for a listed port, and
  445 / 3389 time out.
- [ ] With both clients up, `ssh <node>.<tailnet>.ts.net` from WSL still resolves and connects.

Once the relay exists (all from offsite, not just the LAN):

- [ ] `pc-start` wakes the PC from a **full shutdown** and from **sleep**.
- [ ] `wsl-open` reports WSL ready, and `ssh dev-wsl` works with no Windows login.
- [ ] `wsl-close`, `pc-sleep`, `pc-restart` and `pc-shutdown` each do what they say.
- [ ] A dropped or closed SSH session leaves the PC and WSL running.
- [ ] The Pi's trigger key is refused for anything outside `pc-control.ps1`'s allow-list (e.g. `ssh … whoami`).
- [ ] `ssh wol-relay` with no command, `ssh wol-relay bash` and `ssh wol-relay whoami` are all refused (the `pc`
  user only runs the six commands).
- [ ] The relay's admin user is refused over the tailnet, even with its key.
- [ ] Windows sshd on 2222 refuses password logins.
- [ ] The removal drill above also cuts off the relay.
- [ ] The PC is still found after its IP address changes.
- [ ] After a power cut, the relay rejoins the tailnet by itself and does **not** wake the PC.
- [ ] A hung Pi reboots itself (hardware watchdog).

---

## ❓ Open questions

1. **The on-demand task with a passwordless account:** "HomeLab WSL" needs "run whether logged on or not". Add a
   password to the account, or use a dedicated local account. Decide after testing.
2. ~~Tailscale on both Windows and WSL~~ **Settled:** both stay on, Windows tagged `tag:dev-pc`, WSL in NAT mode.
   See [🪟 Windows and WSL on the tailnet](#-windows-and-wsl-on-the-tailnet).
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
- **Ansible to the relay:** a separate admin user, key-only and accepted **only from the home LAN**. The laptop's
  `pc` user (key + TOTP over the tailnet) can only run the six commands, so a stolen or hacked laptop never reaches
  a shell or sudo on the Pi.
- **No automatic shutdown:** the laptop stops WSL and the PC explicitly. A dropped session never shuts anything down.
- **Relay reboots never wake the PC** (`wol_wake_at_boot: false`), and the Pi is kept always on
  ([Keeping the relay on](#keeping-the-relay-on)).

---

## 🛰️ Relay design (Pi Zero W, not bought yet)

The design so far. Nothing here is built yet; [open question 4](#-open-questions) is waiting on its test.

```text
Laptop
  │  ssh wol-relay <command> ── tailnet ACL: admins → tag:wol-relay:22; user pc, key + TOTP
  ▼
wol-relay (Pi Zero W, tag:wol-relay, home LAN, Wi-Fi) → pc-dispatch (the six commands only)
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

Run from the laptop as `ssh wol-relay <command>`:

| Command | What it does | How |
|---|---|---|
| `pc-start` | Wake the PC | Wake-on-LAN to the PC's MAC, then poll until Windows answers on 2222. Never touches Windows itself |
| `pc-shutdown` | Shut down | `shutdown /s /t 60` |
| `pc-restart` | Restart | `shutdown /r /t 60`. WSL isn't started afterwards: run `wsl-open` |
| `pc-sleep` | Sleep | `rundll32 powrprof.dll,SetSuspendState 0,1,0`. Needs hibernation off (`powercfg /h off`), or it hibernates instead. `pc-start` wakes it |
| `wsl-open` | Start WSL and keep it running | Starts the on-demand task "HomeLab WSL", waits until `tailscaled` and `sshd` are active, reports |
| `wsl-close` | Stop WSL cleanly | Stops the task, then `wsl.exe --terminate <Distro>`. **Never `wsl --shutdown`**: that stops every distro, including `docker-desktop` |

Typical session: [Day to day](#-day-to-day). Every command asks for a TOTP code, with no connection sharing on
purpose.

The laptop's `~/.ssh/config` gets its own key for the relay, the same way as dev-wsl:

```text
Host wol-relay
  HostName wol-relay
  User pc
  IdentityFile ~/.ssh/wol-relay
  IdentitiesOnly yes
  # the agent forgets the key after an hour
  AddKeysToAgent 1h
  ForwardAgent no
```

### The pieces

- **Is the relay up?** From the laptop: `tailscale ping wol-relay`, or `tailscale status`.
- **The relay:**
  - Raspberry Pi OS Lite 32-bit (ARMv6), on Wi-Fi. Tailscale tagged `tag:wol-relay`, joined by hand
    (`tailscale up`, then approve), the same way as WSL.
  - The same key + TOTP sshd as WSL, through a shared role extracted from `controller.yml`.
  - **Two users:**
    - **`pc`**, for the laptop: key + TOTP, and its `authorized_keys` entry is
      `restrict,command="/usr/local/bin/pc-dispatch" ssh-ed25519 …`. `pc-dispatch` reads `$SSH_ORIGINAL_COMMAND` and
      runs only the six commands; anything else is refused and logged. No shell, no sudo, no forwarding.
    - **An admin user**, for Ansible: key-only, accepted **only from the home LAN** (`AllowUsers pc
      <admin>@<home_lan_subnet>`). Raspberry Pi OS's passwordless-sudo file is removed, so sudo needs a password
      (`oob.yml -K`).
  - Its own `oob` inventory group, outside every Kubernetes group. It never joins the cluster.
  - The six commands in `/usr/local/bin`, sharing one helper: find the PC's IP by MAC (`arp-scan --localnet`), then
    call `pc-control` with the trigger key. `pc-start` reuses the Wake-on-LAN logic in `roles/wake_on_lan`.
  - **The trigger key** is generated on the Pi and never leaves it. Even if the Pi is compromised, Windows only lets
    that key run `pc-control.ps1`'s allow-list, and only from the home LAN.
- **Windows:**
  - OpenSSH Server on **port 2222**, with its firewall rule limited to `-RemoteAddress LocalSubnet`. Not 22: WSL's
    localhost forwarding would clash with a Windows sshd on 22. In `C:\ProgramData\ssh\sshd_config`:
    `PasswordAuthentication no`, `AllowUsers <winuser>`, `AllowTcpForwarding no`. Keep the service **stopped
    (Manual)** until the relay exists.
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

### To build

Security items this doc relies on that aren't in the playbooks yet:

- [x] **dev-wsl sshd** (`controller.yml --tags dev_wsl`): `ClientAliveInterval 60`, `ClientAliveCountMax 3`,
  `AllowAgentForwarding no`, `PermitTunnel no`, `LoginGraceTime 30`. TCP forwarding stays on for dev port-forwards.
- [x] **Login alerts on dev-wsl**, reusing `roles/base_hardening`'s `on-ssh-success` watcher (Discord).
- [ ] **Relay:** the `pc` user with `pc-dispatch`, the LAN-only admin user, the same sshd extras and login alerts
  as dev-wsl, and removal of the passwordless-sudo file.
- [ ] **Windows:** `pc-control.ps1` and the sshd settings above.
