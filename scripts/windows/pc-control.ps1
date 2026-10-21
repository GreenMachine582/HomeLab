# scripts/windows/pc-control.ps1
# Forced command for the PC's Windows OpenSSH (port 2222). Every key in
# administrators_authorized_keys runs this script and nothing else; the
# requested action arrives in SSH_ORIGINAL_COMMAND and must be on the
# allow-list below. Installed to C:\HomeLab by Install-PcControl.ps1 (re-run it
# to update); see docs/REMOTE_ACCESS.md "From the home LAN".
#
# -DryRun prints what would run instead of running it (for local testing).

param([switch]$DryRun)

$ErrorActionPreference = 'Stop'
# wsl.exe prints UTF-16 unless told otherwise.
$env:WSL_UTF8 = '1'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Distro = (Get-Content (Join-Path $Root 'pc-control.json') -Raw | ConvertFrom-Json).distro
$WslTask = 'HomeLab WSL'
$SleepTask = 'HomeLab Sleep'
$Action = "$env:SSH_ORIGINAL_COMMAND".Trim()

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format s) [$env:SSH_CLIENT] $Message"
    if ($DryRun) { Write-Host "log: $line"; return }
    Add-Content -Path (Join-Path $Root 'pc-control.log') -Value $line
}

function Invoke-Step([scriptblock]$Step) {
    if ($DryRun) { Write-Host "would run: $Step"; return }
    & $Step
}

# The task holds WSL open; wsl.exe answers only while some Windows process does.
function Get-WslState {
    $running = @(& wsl.exe --list --running --quiet 2>$null) | ForEach-Object { "$_".Trim() }
    if ($running -contains $Distro) { 'running' } else { 'stopped' }
}

switch -CaseSensitive ($Action) {
    'status' {
        Write-Log 'status'
        Write-Output "pc: up ($env:COMPUTERNAME)"
        $task = Get-ScheduledTask -TaskName $WslTask -ErrorAction SilentlyContinue
        $taskState = if ($task) { $task.State } else { 'not installed' }
        Write-Output "wsl ${Distro}: $(Get-WslState) (task: $taskState)"
    }
    'wsl-open' {
        Write-Log 'wsl-open'
        Invoke-Step { Start-ScheduledTask -TaskName $WslTask }
        if ($DryRun) { break }
        # Wait for the services ssh dev-wsl needs, up to about 90 seconds.
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 3
            $states = @(& wsl.exe -d $Distro --exec systemctl is-active tailscaled ssh 2>$null)
            if ($LASTEXITCODE -eq 0 -and ($states | Where-Object { "$_".Trim() -eq 'active' }).Count -eq 2) {
                Write-Output "wsl ${Distro}: ready (tailscaled and ssh active)"
                exit 0
            }
        }
        Write-Output "wsl ${Distro}: task started, but tailscaled/ssh not confirmed active. Try ssh dev-wsl in a minute."
        exit 1
    }
    'wsl-close' {
        Write-Log 'wsl-close'
        Invoke-Step { Stop-ScheduledTask -TaskName $WslTask }
        # Only this distro: wsl --shutdown would also stop docker-desktop.
        Invoke-Step { & wsl.exe --terminate $Distro | Out-Null }
        Write-Output "wsl ${Distro}: stopped"
    }
    'sleep' {
        Write-Log 'sleep'
        # From a task, so it outlives this SSH session and the reply gets out first.
        Invoke-Step { Start-ScheduledTask -TaskName $SleepTask }
        Write-Output 'pc: sleeping in about 5 seconds'
    }
    'restart' {
        Write-Log 'restart'
        Invoke-Step { & shutdown.exe /r /t 60 /c 'HomeLab pc-control: restart' }
        Write-Output 'pc: restarting in 60 seconds (WSL is not started afterwards; run wsl-open)'
    }
    'shutdown' {
        Write-Log 'shutdown'
        Invoke-Step { & shutdown.exe /s /t 60 /c 'HomeLab pc-control: shutdown' }
        Write-Output 'pc: shutting down in 60 seconds'
    }
    default {
        Write-Log "refused: '$Action'"
        Write-Output "refused: '$Action'. Allowed: status, wsl-open, wsl-close, sleep, restart, shutdown"
        exit 2
    }
}
