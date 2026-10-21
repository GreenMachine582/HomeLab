# scripts/laptop/pc.ps1
# Wake and control the main PC from the laptop while both are on the home LAN,
# until the wol-relay Pi exists. start sends Wake-on-LAN; every other command
# runs pc-control.ps1 on the PC over Windows OpenSSH (port 2222), which only
# accepts this key from the home LAN. See docs/REMOTE_ACCESS.md "From the home LAN".
#
#   powershell -ExecutionPolicy Bypass -File scripts\laptop\pc.ps1 start
#   powershell -ExecutionPolicy Bypass -File scripts\laptop\pc.ps1 wsl-open
#
# Config: ~\.homelab\pc.json, e.g.
#   { "mac": "AA-BB-CC-DD-EE-FF", "user": "chad", "key": "~/.ssh/pc-lan" }

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('start', 'status', 'wsl-open', 'wsl-close', 'sleep', 'restart', 'shutdown')]
    [string]$Command
)

$ErrorActionPreference = 'Stop'
$config = Get-Content (Join-Path $HOME '.homelab\pc.json') -Raw | ConvertFrom-Json
$Mac = $config.mac.ToUpper() -replace '[:\.]', '-'
$Key = $config.key -replace '^~', $HOME

# The laptop's IPv4 address and prefix on the interface with the default route.
function Get-LocalLan {
    $cfg = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
        Select-Object -First 1
    if (-not $cfg) { throw 'No network with a default route.' }
    $cfg.IPv4Address | Select-Object -First 1
}

function ConvertTo-UInt32([string]$Ip) {
    $b = ([System.Net.IPAddress]::Parse($Ip)).GetAddressBytes()
    [Array]::Reverse($b)
    [BitConverter]::ToUInt32($b, 0)
}

function ConvertFrom-UInt32([uint32]$N) {
    $b = [BitConverter]::GetBytes($N)
    [Array]::Reverse($b)
    ([System.Net.IPAddress]$b).IPAddressToString
}

# By MAC only (no DHCP reservation, no names): ping every address so the ARP
# table fills, even if the PC drops pings, then look the MAC up in it.
function Find-Pc {
    $hit = Get-NetNeighbor -AddressFamily IPv4 -LinkLayerAddress $Mac -ErrorAction SilentlyContinue |
        Where-Object { $_.State -in 'Reachable', 'Stale', 'Delay', 'Probe', 'Permanent' } | Select-Object -First 1
    if ($hit) { return $hit.IPAddress }

    $lan = Get-LocalLan
    if ($lan.PrefixLength -lt 22) { throw "LAN /$($lan.PrefixLength) is too big to sweep." }
    $mask = [uint32]([math]::Pow(2, 32) - [math]::Pow(2, 32 - $lan.PrefixLength))
    $net = (ConvertTo-UInt32 $lan.IPAddress) -band $mask
    $count = [math]::Pow(2, 32 - $lan.PrefixLength)
    $pings = for ($i = 1; $i -lt $count - 1; $i++) {
        (New-Object System.Net.NetworkInformation.Ping).SendPingAsync((ConvertFrom-UInt32 ($net + $i)), 500)
    }
    try { [System.Threading.Tasks.Task]::WaitAll([System.Threading.Tasks.Task[]]$pings) } catch { }

    $hit = Get-NetNeighbor -AddressFamily IPv4 -LinkLayerAddress $Mac -ErrorAction SilentlyContinue |
        Where-Object { $_.State -notin 'Unreachable', 'Incomplete' } | Select-Object -First 1
    if ($hit) { return $hit.IPAddress }
    return $null
}

function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMs = 2000) {
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

function Send-MagicPacket {
    $macBytes = $Mac -split '-' | ForEach-Object { [Convert]::ToByte($_, 16) }
    $packet = [byte[]](@(0xFF) * 6 + ($macBytes * 16))
    $lan = Get-LocalLan
    $mask = [uint32]([math]::Pow(2, 32) - [math]::Pow(2, 32 - $lan.PrefixLength))
    $broadcast = ConvertFrom-UInt32 (((ConvertTo-UInt32 $lan.IPAddress) -band $mask) -bor (-bnot $mask -band [uint32]::MaxValue))
    $udp = New-Object System.Net.Sockets.UdpClient
    try {
        $udp.EnableBroadcast = $true
        foreach ($target in @($broadcast, '255.255.255.255')) {
            foreach ($port in @(9, 7)) { [void]$udp.Send($packet, $packet.Length, $target, $port) }
        }
    } finally {
        $udp.Close()
    }
}

if ($Command -eq 'start') {
    Send-MagicPacket
    Write-Output "Wake-on-LAN sent to $Mac. Waiting for Windows to answer on 2222 (up to 3 minutes)..."
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        $ip = Find-Pc
        if ($ip -and (Test-TcpPort $ip 2222)) {
            Write-Output "pc: up at $ip. Next: pc.ps1 wsl-open"
            exit 0
        }
        Start-Sleep -Seconds 5
    }
    Write-Output 'pc: no answer. Is the laptop on the home LAN, and is Wake-on-LAN set up (PC prep)?'
    exit 1
}

$ip = Find-Pc
if (-not $ip) {
    Write-Output "pc: $Mac not found on this network. This only works from the home LAN, with the PC on."
    exit 1
}
# The IP changes, so pin the host key to a fixed alias instead.
& ssh -p 2222 -i $Key -o IdentitiesOnly=yes -o HostKeyAlias=dev-pc-lan -o ConnectTimeout=10 "$($config.user)@$ip" $Command
exit $LASTEXITCODE
