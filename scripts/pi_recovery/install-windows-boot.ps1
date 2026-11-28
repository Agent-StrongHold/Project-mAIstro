# Optional Windows/WSL enrollment. Run manually with explicit Administrator approval.
# Installs a task only: never runs it, reboots, shuts down WSL, or replaces a task.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$WindowsUser,
    [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$Distro = 'Ubuntu',
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z_][a-z0-9_-]*$')][string]$WslUser,
    [Parameter(Mandatory=$true)][ValidatePattern('^/[^"\r\n]+/cli\.py$')][string]$CliPath,
    [string]$TaskName = 'Maistro-Pi-WSL'
)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run from Administrator PowerShell after reviewing the installation.'
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "Task $TaskName already exists. Preserve it; review migration separately."
}
$wsl = Join-Path $env:WINDIR 'System32\wsl.exe'
if (-not (Test-Path $wsl)) { throw 'wsl.exe is unavailable.' }
$arguments = "-d `"$Distro`" -u `"$WslUser`" --exec /usr/bin/python3 `"$CliPath`" start --boot"
$action = New-ScheduledTaskAction -Execute $wsl -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT30S'
# S4U stores no password. WindowsUser MUST own the selected WSL distribution.
$runAs = New-ScheduledTaskPrincipal -UserId $WindowsUser -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $runAs `
    -Settings $settings -Description 'Saved Pi recovery through WSL; no interrupted-job replay.'
Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null
$saved = Get-ScheduledTask -TaskName $TaskName
if ($saved.Principal.LogonType -ne 'S4U' -or $saved.Actions.Execute -ne $wsl -or $saved.Actions.Arguments -ne $arguments) {
    throw 'Registered task differs from the requested boot contract; inspect before proceeding.'
}
# Never write host identities/receipts into the repository beside this script.
$state = Join-Path $env:LOCALAPPDATA 'PiRecovery'
New-Item -ItemType Directory -Force -Path $state | Out-Null
$receipt = Join-Path $state (([Guid]::NewGuid().ToString()) + '.json')
[ordered]@{
    task = $TaskName; user = $saved.Principal.UserId; logonType = [string]$saved.Principal.LogonType
    action = $saved.Actions.Execute; arguments = $saved.Actions.Arguments
    testedActualReboot = $false; startedNow = $false
} | ConvertTo-Json | Set-Content -Encoding UTF8 $receipt
Write-Host "Installed only. No reboot or Pi launch performed. Receipt: $receipt"
