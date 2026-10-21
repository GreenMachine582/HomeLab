# scripts/windows/Install-PcControl.ps1
# Sets up the PC side of remote power/WSL control: Windows OpenSSH on 2222
# (home LAN only), pc-control.ps1 as the forced command for the given keys,
# and the "HomeLab WSL" / "HomeLab Sleep" tasks. Idempotent: re-run it to
# update pc-control.ps1 or add a key. See docs/REMOTE_ACCESS.md "From the home LAN".
#
# In admin PowerShell, from the repo:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\Install-PcControl.ps1 `
#     -PublicKey (Get-Content <path to the laptop's pc-lan.pub>)

#Requires -RunAsAdministrator

param(
    # Lines from .pub files. Each becomes a forced-command entry; existing
    # entries for other keys are kept.
    [string[]]$PublicKey = @(),
    [string]$Distro = 'Ubuntu',
    # The Windows account that owns the distro and receives the SSH logins.
    [string]$WindowsUser = $env:USERNAME,
    # Home LAN in CIDR form. Default: the subnet of the interface with the default route.
    [string]$LanCidr = '',
    # Register "HomeLab WSL" with a stored password instead of S4U (if WSL won't start under S4U).
    [switch]$StoredPassword
)

$ErrorActionPreference = 'Stop'
$Root = 'C:\HomeLab'
$SshDir = 'C:\ProgramData\ssh'
$SshdConfig = Join-Path $SshDir 'sshd_config'
$AdminKeys = Join-Path $SshDir 'administrators_authorized_keys'
# SIDs, so this works on non-English Windows: Administrators, SYSTEM, Users.
$Admins = '*S-1-5-32-544'
$System = '*S-1-5-18'
$Users = '*S-1-5-32-545'

function Get-LanCidr {
    $cfg = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
        Select-Object -First 1
    if (-not $cfg) { throw 'No interface with a default route; pass -LanCidr.' }
    $addr = $cfg.IPv4Address | Select-Object -First 1
    $bytes = ([System.Net.IPAddress]::Parse($addr.IPAddress)).GetAddressBytes()
    [Array]::Reverse($bytes)
    $mask = [uint32]([math]::Pow(2, 32) - [math]::Pow(2, 32 - $addr.PrefixLength))
    $net = [BitConverter]::GetBytes([BitConverter]::ToUInt32($bytes, 0) -band $mask)
    [Array]::Reverse($net)
    "$(([System.Net.IPAddress]$net).IPAddressToString)/$($addr.PrefixLength)"
}

# Sets a global sshd option: replaces its first (possibly commented) line
# before any Match block, or adds it at the top.
function Set-SshdOption([string[]]$Lines, [string]$Key, [string]$Value) {
    $matchAt = [array]::FindIndex($Lines, [Predicate[string]] { param($l) $l -match '^\s*Match\s' })
    if ($matchAt -lt 0) { $matchAt = $Lines.Count }
    for ($i = 0; $i -lt $matchAt; $i++) {
        if ($Lines[$i] -match "^\s*#?\s*$Key\s") {
            $Lines[$i] = "$Key $Value"
            return , $Lines
        }
    }
    return , (@("$Key $Value") + $Lines)
}

if (-not $LanCidr) { $LanCidr = Get-LanCidr }
Write-Host "Home LAN: $LanCidr"

# ── C:\HomeLab: admins write, users read, so nothing unelevated (WSL included) can rewrite the forced command ──
New-Item -ItemType Directory -Force -Path $Root | Out-Null
& icacls $Root /inheritance:r /grant "${Admins}:(OI)(CI)F" "${System}:(OI)(CI)F" "${Users}:(OI)(CI)RX" | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot 'pc-control.ps1') -Destination $Root -Force
@{ distro = $Distro } | ConvertTo-Json | Set-Content -Path (Join-Path $Root 'pc-control.json') -Encoding UTF8
Write-Host "Installed $Root\pc-control.ps1 (distro $Distro)"

# ── OpenSSH Server ──
if ((Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0').State -ne 'Installed') {
    Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null
}
# sshd writes its default config on first start.
if (-not (Test-Path $SshdConfig)) { Start-Service sshd; Stop-Service sshd }

$lines = [string[]](Get-Content $SshdConfig)
$before = $lines -join "`n"
# Not 22: WSL's localhost forwarding uses it.
$lines = Set-SshdOption $lines 'Port' '2222'
$lines = Set-SshdOption $lines 'PasswordAuthentication' 'no'
$lines = Set-SshdOption $lines 'AllowUsers' $WindowsUser.ToLower()
$lines = Set-SshdOption $lines 'AllowTcpForwarding' 'no'
if (($lines -join "`n") -ne $before) {
    Set-Content -Path $SshdConfig -Value $lines -Encoding ASCII
    Write-Host 'Updated sshd_config'
}

# ── Keys: forced command, home LAN only ──
$existing = @()
if (Test-Path $AdminKeys) { $existing = @(Get-Content $AdminKeys | Where-Object { $_.Trim() }) }
$entries = foreach ($key in $PublicKey | Where-Object { $_.Trim() }) {
    $parts = $key.Trim() -split '\s+'
    if ($parts[0] -notmatch '^(ssh-|ecdsa-|sk-)') { throw "Not a public key line: $key" }
    # Drop any older entry for the same key, whatever its options.
    $existing = @($existing | Where-Object { $_ -notmatch [regex]::Escape($parts[1]) })
    "restrict,from=`"$LanCidr`",command=`"powershell -NoProfile -ExecutionPolicy Bypass -File $Root\pc-control.ps1`" $($parts -join ' ')"
}
if ($PublicKey.Count -gt 0) {
    Set-Content -Path $AdminKeys -Value (@($existing) + @($entries)) -Encoding ASCII
    Write-Host "Added $(@($entries).Count) key(s) to $AdminKeys"
}
if (Test-Path $AdminKeys) {
    # sshd ignores the file unless only Administrators and SYSTEM can touch it.
    & icacls $AdminKeys /inheritance:r /grant "${Admins}:F" "${System}:F" | Out-Null
}

# ── Firewall: 2222 from the home LAN only; the capability's own rule for 22 stays off ──
Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue | Disable-NetFirewallRule
Remove-NetFirewallRule -Name 'HomeLab-sshd-2222' -ErrorAction SilentlyContinue
# An explicit CIDR rather than LocalSubnet, which would also cover the Tailscale adapter's range.
New-NetFirewallRule -Name 'HomeLab-sshd-2222' -DisplayName 'HomeLab sshd 2222 (home LAN)' -Direction Inbound `
    -Protocol TCP -LocalPort 2222 -RemoteAddress $LanCidr -Action Allow | Out-Null

# Automatic: after a remote wake no one is logged in.
Set-Service sshd -StartupType Automatic
Restart-Service sshd
Write-Host 'sshd listening on 2222 (home LAN only)'

# ── Tasks ──
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
# No trigger: started only by pc-control.ps1 wsl-open. It holds WSL open.
$wslAction = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument "-d $Distro --exec sleep infinity"
if ($StoredPassword) {
    $cred = Get-Credential -UserName "$env:USERDOMAIN\$WindowsUser" -Message 'Password for the HomeLab WSL task'
    Register-ScheduledTask -TaskName 'HomeLab WSL' -Action $wslAction -Settings $settings -Force `
        -User $cred.UserName -Password $cred.GetNetworkCredential().Password -RunLevel Limited | Out-Null
} else {
    # S4U: runs while logged off without storing a password.
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$WindowsUser" -LogonType S4U -RunLevel Limited
    Register-ScheduledTask -TaskName 'HomeLab WSL' -Action $wslAction -Settings $settings -Principal $principal `
        -Force | Out-Null
}
$sleepAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument '-NoProfile -Command "Start-Sleep -Seconds 5; rundll32.exe powrprof.dll,SetSuspendState 0,1,0"'
$sleepPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount
Register-ScheduledTask -TaskName 'HomeLab Sleep' -Action $sleepAction -Settings $settings -Principal $sleepPrincipal `
    -Force | Out-Null
Write-Host 'Registered tasks: HomeLab WSL, HomeLab Sleep'

# Sleep, not hibernate, and no Fast Startup (it breaks Wake-on-LAN from shutdown).
& powercfg.exe /hibernate off
Write-Host 'Hibernation and Fast Startup off'

Write-Host ''
Write-Host 'Done. BIOS and NIC Wake-on-LAN settings are manual: see "PC prep for Wake-on-LAN" in docs/REMOTE_ACCESS.md.'
