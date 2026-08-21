#requires -Version 5.1
<#
.SYNOPSIS
  maistro-engine Windows bootstrapper.

.DESCRIPTION
  install.sh / get.sh need bash; a fresh Windows 10 box has none. This script
  is the native entrypoint: it enables WSL2, installs an Ubuntu distro
  (handling the Windows feature-enable reboot WSL2 sometimes requires), then
  hands off to the existing Linux installer (get.sh -> install.sh) running
  inside that distro. Re-run this script after a requested reboot, or just
  leave it — it registers a one-time logon task and resumes itself.

  Runs the Linux side as root inside WSL to skip the interactive "create a
  UNIX username" first-run prompt and the docker group dance; this distro is
  treated as a single-purpose runtime for the engine, not a general dev box.

.PARAMETER Version
  Release tag to install, e.g. v1.0.0 or v1.0.0-rc1 (a bare 1.0.0 is
  normalized to v1.0.0). Wins over -Channel and -Branch. Default: unset, which
  means "latest published release" (see -Channel).

.PARAMETER Channel
  'stable' (default) resolves the latest published release tag via the GitHub
  API; 'dev' installs the 'develop' branch, for contributors.

.PARAMETER Branch
  maistro-engine branch to install. Default: unset — an explicit branch is a
  development override, not the normal path. Ignored when -Version is given.

.PARAMETER RequireRelease
  Fail instead of falling back to a branch when no release tag can be
  resolved.

.PARAMETER Repo
  GitHub "owner/repo" to install from (default: BlakeMatthews-dev/maistro-engine).

.PARAMETER Distro
  WSL distro name to install/use (default: Ubuntu).

.PARAMETER AutoInstallDeps
  Skip confirmation prompts (WSL install, reboot) and the runtime-choice
  prompt inside install.sh. Maps to MAISTRO_AUTO_INSTALL_DEPS=1.

.PARAMETER SkipWizard
.PARAMETER NoStart
.PARAMETER NoCli
.PARAMETER NoOpen
  Passed straight through to install.sh as MAISTRO_SKIP_WIZARD / *_START_STACK
  / *_INSTALL_CLI / *_OPEN_BROWSER.

.EXAMPLE
  irm https://raw.githubusercontent.com/BlakeMatthews-dev/maistro-engine/main/get.ps1 | iex

.EXAMPLE
  .\get.ps1 -AutoInstallDeps

.EXAMPLE
  .\get.ps1 -Version v1.0.0

.EXAMPLE
  .\get.ps1 -Channel dev
#>
[CmdletBinding()]
param(
    [string]$Version = '',
    [ValidateSet('stable', 'dev')]
    [string]$Channel = 'stable',
    [string]$Branch = '',
    [string]$Repo = 'BlakeMatthews-dev/maistro-engine',
    [string]$Distro = 'Ubuntu',
    [switch]$RequireRelease,
    [switch]$AutoInstallDeps,
    [switch]$Resume,
    [switch]$SkipWizard,
    [switch]$NoStart,
    [switch]$NoCli,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'

# Branch installed when the stable channel has no release to resolve — the same
# choice get.sh makes, for the same reason (ADR-073126-c4e1 §2 makes `main` the
# only branch a final release tag may point at).
$script:NoReleaseFallbackBranch = 'main'

# Resolved by Resolve-InstallRef and used for every raw.githubusercontent.com
# fetch in this script, so the get.ps1/get.sh pair and the source tree all come
# from one ref instead of three.
$script:RefKind = ''
$script:Ref = ''

function Write-InfoMsg { param([string]$Message) Write-Host "[maistro] $Message" -ForegroundColor Cyan }
function Write-OkMsg { param([string]$Message) Write-Host "[ok] $Message" -ForegroundColor Green }
function Write-WarnMsg { param([string]$Message) Write-Host "[warn] $Message" -ForegroundColor Yellow }
function Write-ErrMsg { param([string]$Message) Write-Host "[error] $Message" -ForegroundColor Red }

function Confirm-Action {
    param([string]$Prompt)
    if ($AutoInstallDeps) {
        Write-InfoMsg "$Prompt -> auto-confirmed (-AutoInstallDeps)"
        return $true
    }
    $reply = Read-Host "$Prompt [y/N]"
    return $reply -match '^[Yy]'
}

# `1.0.0` and `v1.0.0` name the same release to a human; only one is a real ref.
function Format-VersionTag {
    param([string]$Value)
    if ($Value -like 'v*') { return $Value }
    return "v$Value"
}

# Latest published release tag, or $null when there is none / the API is
# unreachable. /releases/latest excludes prereleases and drafts by design: an
# rc must be asked for by name, never handed to someone who ran the one-liner.
function Get-LatestReleaseTag {
    $uri = "https://api.github.com/repos/$Repo/releases/latest"
    $headers = @{ 'Accept' = 'application/vnd.github+json'; 'User-Agent' = 'maistro-get' }
    $token = if ($env:MAISTRO_GITHUB_TOKEN) { $env:MAISTRO_GITHUB_TOKEN } else { $env:GITHUB_TOKEN }
    if ($token) { $headers['Authorization'] = "Bearer $token" }
    try {
        $release = Invoke-RestMethod -Uri $uri -Headers $headers -UseBasicParsing -TimeoutSec 20
    } catch {
        # A 404 here means "no releases yet", which is an expected answer, not
        # a failure — the caller decides what to do about it.
        return $null
    }
    if ($release -and $release.tag_name) { return [string]$release.tag_name }
    return $null
}

# Decide what to install once, up front. Explicit beats implicit: -Version wins
# over -Branch wins over -Channel. Mirrors resolve_ref() in get.sh — the two
# entrypoints must agree, or a Windows user and a Linux user running "the same"
# command get different code.
function Resolve-InstallRef {
    if ($Version) {
        $script:RefKind = 'tag'
        $script:Ref = Format-VersionTag -Value $Version
        Write-InfoMsg "Installing release $($script:Ref) (requested explicitly)."
        return
    }
    if ($Branch) {
        $script:RefKind = 'branch'
        $script:Ref = $Branch
        Write-WarnMsg "Installing branch '$Branch' — a branch moves. Use -Version vX.Y.Z for a reproducible install."
        return
    }
    if ($Channel -eq 'dev') {
        $script:RefKind = 'branch'
        $script:Ref = 'develop'
        Write-WarnMsg "Channel 'dev': installing the 'develop' branch. Unreleased code — expect breakage."
        return
    }

    $tag = Get-LatestReleaseTag
    if ($tag) {
        $script:RefKind = 'tag'
        $script:Ref = $tag
        Write-InfoMsg "Installing latest release $tag."
        return
    }

    if ($RequireRelease) {
        Write-ErrMsg "No published release found for $Repo and -RequireRelease was set. Nothing installed."
        exit 1
    }
    $script:RefKind = 'branch'
    $script:Ref = $script:NoReleaseFallbackBranch
    Write-WarnMsg "No published release found for $Repo (the GitHub API returned none, or was unreachable)."
    Write-WarnMsg "Falling back to the '$($script:Ref)' branch, which is where release tags are cut from."
    Write-WarnMsg "This is NOT a pinned install: '$($script:Ref)' moves. To pin, re-run with -Version vX.Y.Z"
    Write-WarnMsg "once a release exists, or with -RequireRelease to fail instead of falling back."
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Guarantees a copy of this script exists on disk: needed both for the
# elevation relaunch and for the post-reboot RunOnce hook, since a script
# fetched via `irm | iex` has no $PSCommandPath to point those at.
function Save-StableCopy {
    $destDir = Join-Path $env:LOCALAPPDATA 'maistro'
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    $dest = Join-Path $destDir 'get.ps1'
    if ($PSCommandPath -and (Test-Path -LiteralPath $PSCommandPath)) {
        Copy-Item -LiteralPath $PSCommandPath -Destination $dest -Force
    } else {
        # $script:Ref, not $Branch: after Resolve-InstallRef this is the tag
        # being installed, so the saved copy (which the elevation relaunch and
        # the post-reboot resume both execute) is the same revision as the
        # source tree it will go on to install.
        $ref = if ($script:Ref) { $script:Ref } else { $script:NoReleaseFallbackBranch }
        $url = "https://raw.githubusercontent.com/$Repo/$ref/get.ps1"
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    }
    return $dest
}

function Get-PassthroughArgs {
    param([switch]$IncludeResume)
    $argList = @()
    # Pass the RESOLVED ref, not the raw parameters: a resume that re-resolves
    # "latest release" could land on a different release than the one the user
    # started installing before the reboot.
    if ($script:RefKind -eq 'tag') {
        $argList += @('-Version', $script:Ref)
    } elseif ($script:Ref) {
        $argList += @('-Branch', $script:Ref)
    }
    if ($RequireRelease) { $argList += '-RequireRelease' }
    if ($Repo -ne 'BlakeMatthews-dev/maistro-engine') { $argList += @('-Repo', $Repo) }
    if ($Distro -ne 'Ubuntu') { $argList += @('-Distro', $Distro) }
    if ($AutoInstallDeps) { $argList += '-AutoInstallDeps' }
    if ($SkipWizard) { $argList += '-SkipWizard' }
    if ($NoStart) { $argList += '-NoStart' }
    if ($NoCli) { $argList += '-NoCli' }
    if ($NoOpen) { $argList += '-NoOpen' }
    if ($IncludeResume) { $argList += '-Resume' }
    return $argList
}

function Invoke-Elevated {
    $scriptPath = Save-StableCopy
    $passthrough = Get-PassthroughArgs
    $quoted = $passthrough | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
    $fullArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$scriptPath`"") + $quoted
    Write-InfoMsg "Elevation is required to enable WSL2. Requesting an admin prompt..."
    Start-Process -FilePath 'powershell.exe' -ArgumentList $fullArgs -Verb RunAs
}

# RunOnce fires once at the next interactive logon, with the logged-on user's
# normal (non-elevated) token — fine here, since only the initial Windows
# feature-enable step needs admin, not resuming into an already-enabled WSL2.
function Register-Resume {
    param([string]$ScriptPath)
    $passthrough = Get-PassthroughArgs -IncludeResume
    $quoted = $passthrough | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
    $argStr = ($quoted -join ' ')
    $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" $argStr"
    New-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Force | Out-Null
    New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' `
        -Name 'MaistroInstallResume' -Value $cmd -PropertyType String -Force | Out-Null
}

function Test-WindowsBuild {
    $build = [System.Environment]::OSVersion.Version.Build
    if ($build -lt 19041) {
        Write-ErrMsg "Windows build $build detected; WSL2 needs build 19041 (Windows 10 version 2004) or newer."
        Write-ErrMsg "Open Settings > Update & Security > Windows Update, install all updates, reboot, then re-run this script."
        return $false
    }
    Write-OkMsg "Windows build $build supports WSL2."
    return $true
}

# Advisory only, like the macOS arm64 manifest check: VirtualizationFirmwareEnabled
# is unreliable on some builds/VMs, so an inconclusive read does not block setup —
# `wsl --install` will fail with a clear message if virtualization is really off.
function Test-Virtualization {
    try {
        $cpu = Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1
        if ($null -eq $cpu.VirtualizationFirmwareEnabled) {
            Write-WarnMsg "Could not determine virtualization firmware state; continuing."
            return
        }
        if ($cpu.VirtualizationFirmwareEnabled) {
            Write-OkMsg "Virtualization is enabled in firmware."
        } else {
            Write-WarnMsg "Virtualization (Intel VT-x / AMD-V) appears disabled in BIOS/UEFI firmware."
            Write-WarnMsg "If WSL2 install fails below, reboot into BIOS/UEFI setup and enable it, then re-run."
        }
    } catch {
        Write-WarnMsg "Could not query virtualization state; continuing."
    }
}

function Test-WslInstalled {
    return [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue)
}

# `wsl -l -v` rows are UTF-16 and sometimes carry embedded NUL bytes when
# captured through the pipeline; strip them before matching.
function Get-WslDistroState {
    param([string]$Name)
    if (-not (Test-WslInstalled)) { return $null }
    $raw = & wsl.exe -l -v 2>$null
    if (-not $raw) { return $null }
    foreach ($line in $raw) {
        $clean = ($line -replace "`0", '').Trim()
        if ($clean -like "$Name*") { return $clean }
    }
    return $null
}

function Test-DistroUsable {
    param([string]$Name)
    if (-not (Get-WslDistroState -Name $Name)) { return $false }
    try {
        & wsl.exe -d $Name -u root -- true 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

# `wsl --install -d <distro>` can spend a couple of minutes downloading the
# rootfs on a fresh box; poll rather than judging "needs a reboot" off one
# early check, which would otherwise reboot machines that just needed longer.
function Wait-DistroUsable {
    param([string]$Name, [int]$TimeoutSeconds = 180)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-DistroUsable -Name $Name) { return $true }
        Start-Sleep -Seconds 5
    }
    return $false
}

# Runs get.sh (the existing, already-supported Linux/macOS installer) inside
# the WSL distro as root. Env-var assignments must be `export`ed inside the
# command string rather than prefixed before `curl`, since a leading
# `VAR=val cmd1 | cmd2` only scopes VAR to cmd1 in POSIX shells — and it's
# cmd2 (the piped-in get.sh) that needs to see these.
function Invoke-LinuxInstall {
    Write-InfoMsg "Bootstrapping $Distro (curl/git) and running the engine installer as root..."
    & wsl.exe -d $Distro -u root -- bash -lc 'apt-get update -qq && apt-get install -y -qq curl ca-certificates git'

    # Hand get.sh the already-resolved ref rather than re-resolving inside WSL:
    # two resolutions can disagree (a release published between them), and the
    # Windows side is where the user's -Version/-Channel intent was expressed.
    $envAssignments = @("MAISTRO_REPO=$Repo")
    if ($script:RefKind -eq 'tag') {
        $envAssignments += "MAISTRO_VERSION=$($script:Ref)"
    } else {
        $envAssignments += "MAISTRO_BRANCH=$($script:Ref)"
    }
    if ($AutoInstallDeps) { $envAssignments += 'MAISTRO_AUTO_INSTALL_DEPS=1' }
    if ($SkipWizard) { $envAssignments += 'MAISTRO_SKIP_WIZARD=1' }
    if ($NoStart) { $envAssignments += 'MAISTRO_START_STACK=0' }
    if ($NoCli) { $envAssignments += 'MAISTRO_INSTALL_CLI=0' }
    if ($NoOpen) { $envAssignments += 'MAISTRO_OPEN_BROWSER=0' }
    # Checksum verification of the fetched install.sh (SPEC-072726-3439
    # Phase 5): forward the manifest URL so get.sh verifies before executing.
    if ($env:MAISTRO_SHA256SUMS_URL) { $envAssignments += "MAISTRO_SHA256SUMS_URL=$($env:MAISTRO_SHA256SUMS_URL)" }
    $exports = ($envAssignments | ForEach-Object { "export $_;" }) -join ' '

    # Fetch get.sh from the ref being installed, so the bootstrapper and the
    # tree it lays down are the same revision.
    $getShUrl = "https://raw.githubusercontent.com/$Repo/$($script:Ref)/get.sh"
    $innerCmd = "$exports curl -fsSL $getShUrl | bash"

    & wsl.exe -d $Distro -u root -- bash -lc $innerCmd
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        Write-ErrMsg "The installer exited with code $exitCode inside $Distro."
        Write-ErrMsg "Re-run manually: wsl -d $Distro -u root -- bash -lc `"$innerCmd`""
        exit $exitCode
    }

    Write-OkMsg "Done. The Conductor UI should have opened automatically."
    Write-Host ""
    Write-Host "If it didn't, open: http://localhost:8101" -ForegroundColor Cyan
}

function Invoke-Main {
    Write-Host ""
    Write-Host "maistro-engine Windows installer" -ForegroundColor Cyan
    Write-Host "bootstraps WSL2, then hands off to the Linux installer" -ForegroundColor Cyan
    Write-Host ""

    # Before anything is fetched or saved: Save-StableCopy, Get-PassthroughArgs
    # and Invoke-LinuxInstall all read $script:Ref.
    Resolve-InstallRef
    Write-Host ("{0,-8}{1}" -f "$($script:RefKind):", $script:Ref)
    Write-Host ""

    if (Test-DistroUsable -Name $Distro) {
        Write-OkMsg "$Distro is ready."
        Invoke-LinuxInstall
        return
    }

    if (-not (Test-Admin)) {
        Invoke-Elevated
        return
    }

    if (-not (Test-WindowsBuild)) { exit 1 }
    Test-Virtualization

    if (-not $Resume) {
        if (-not (Confirm-Action "Install WSL2 + $Distro now (required for Docker on Windows)?")) {
            Write-ErrMsg "WSL2 is required. Re-run this script when ready, or pass -AutoInstallDeps."
            exit 1
        }
    }

    $scriptPath = Save-StableCopy
    Register-Resume -ScriptPath $scriptPath

    Write-InfoMsg "Running: wsl --install -d $Distro (this can take a few minutes)..."
    & wsl.exe --install -d $Distro

    if (Wait-DistroUsable -Name $Distro) {
        Write-OkMsg "$Distro is ready (no reboot needed)."
        Invoke-LinuxInstall
        return
    }

    Write-WarnMsg "WSL2 needs a restart to finish enabling."
    Write-WarnMsg "Setup will resume automatically the next time you log in (registered via RunOnce)."
    if (-not $AutoInstallDeps) {
        if (-not (Confirm-Action "Reboot now?")) {
            Write-InfoMsg "Reboot manually when ready; setup resumes automatically at your next logon."
            exit 0
        }
    }
    Restart-Computer -Force
}

Invoke-Main
