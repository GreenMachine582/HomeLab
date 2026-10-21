# scripts/laptop/Test-RemoteAccess.ps1
# Runs the automatic checks from docs/REMOTE_ACCESS.md "Tests" from the laptop,
# then lists the ones you have to do by hand. Needs the laptop on the tailnet,
# the PC awake and WSL running.
#
#   powershell -ExecutionPolicy Bypass -File scripts\laptop\Test-RemoteAccess.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\laptop\Test-RemoteAccess.ps1 -DevPcPorts 8096,3000

param(
    # Must match dev_pc_ports in inventories/group_vars/all/main.yml.
    [int[]]$DevPcPorts = @(8096),
    [string]$WslHost = 'dev-wsl',
    [string]$PcHost = 'dev-pc'
)

$script:Pass = 0
$script:Fail = 0

function Write-Result([bool]$Ok, [string]$Label) {
    if ($Ok) {
        Write-Host "  [PASS] $Label" -ForegroundColor Green
        $script:Pass++
    } else {
        Write-Host "  [FAIL] $Label" -ForegroundColor Red
        $script:Fail++
    }
}

# Test-NetConnection waits ~20s on every closed port; a plain connect with a
# short timeout is enough, and a tailnet ACL drop looks like a timeout anyway.
function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMs = 3000) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $wait = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $wait.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($wait)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

Write-Host 'Tailnet' -ForegroundColor White
$status = $null
try {
    $status = (& tailscale status --json | Out-String) | ConvertFrom-Json
} catch {
    Write-Result $false 'tailscale status --json (is Tailscale running on the laptop?)'
}
if ($status) {
    $peers = @($status.Peer.PSObject.Properties | ForEach-Object { $_.Value })
    foreach ($want in @(@{ Name = $WslHost; Tag = 'tag:dev-wsl' }, @{ Name = $PcHost; Tag = 'tag:dev-pc' })) {
        $peer = $peers | Where-Object { $_.DNSName -like "$($want.Name).*" } | Select-Object -First 1
        Write-Result ([bool]$peer -and $peer.Online) "$($want.Name) is online"
        Write-Result ([bool]$peer -and (@($peer.Tags) -contains $want.Tag)) "$($want.Name) carries $($want.Tag)"
    }
}

Write-Host 'Ports over the tailnet' -ForegroundColor White
Write-Result (Test-TcpPort $WslHost 22) "${WslHost}:22 is open"
foreach ($port in $DevPcPorts) {
    Write-Result (Test-TcpPort $PcHost $port) "${PcHost}:$port is open (dev_pc_ports)"
}
# SMB, RDP and the future relay sshd must stay closed unless listed.
foreach ($port in @(445, 3389, 2222) | Where-Object { $DevPcPorts -notcontains $_ }) {
    Write-Result (-not (Test-TcpPort $PcHost $port)) "${PcHost}:$port is closed"
}

Write-Host 'SSH login methods' -ForegroundColor White
# Without the key the server must offer nothing else: no password, no TOTP-only path.
$out = & ssh -o BatchMode=yes -o PubkeyAuthentication=no -o ConnectTimeout=10 $WslHost exit 2>&1 | Out-String
Write-Result ($out -match 'Permission denied \(publickey\)') "$WslHost refuses logins without the key"

Write-Host ''
Write-Host "$script:Pass passed, $script:Fail failed" -ForegroundColor $(if ($script:Fail) { 'Red' } else { 'Green' })

Write-Host ''
Write-Host 'By hand (see docs/REMOTE_ACCESS.md "Tests"):' -ForegroundColor White
@(
    "ssh $WslHost asks for a TOTP code every time, and a wrong code is refused",
    "ssh root@$WslHost is refused",
    "ssh -A $WslHost, then ssh-add -l inside, can't reach an agent",
    'Each login posts a Discord alert naming dev-wsl',
    'Removal drill: remove the laptop in the admin console, the open session drops, then re-add it',
    'A new device shows Needs approval'
) | ForEach-Object { Write-Host "  [ ] $_" }

exit $(if ($script:Fail) { 1 } else { 0 })
