#requires -Version 5.1
<#
.SYNOPSIS
  maistro-engine Windows bootstrapper.

.DESCRIPTION
  install.sh / get.sh need bash, which may be absent on Windows 10. This
  native entrypoint requires an administrator-approved PowerShell setup that
  permits this script to run; it is not a zero-setup guarantee for a fresh
  Windows installation. It enables WSL2, installs an Ubuntu distro
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

.PARAMETER AnswersFile
  Path to a maistro-install answers YAML file (schema v1; templates in
  docs/install/examples/) for fully unattended installs. This is the Windows
  twin of `get.sh -- --answers-file`: the same one schema is validated,
  translated to the distro's /mnt view of the Windows filesystem, and
  forwarded to install.sh inside WSL, exactly as on Unix. Validated before
  any mutation (no WSL setup, no elevation prompt, no reboot), and the path
  survives the elevation relaunch and the post-reboot resume. The answers
  file carries names and flags only — never API keys or passwords (SPEC-180);
  secrets stay in the 0600 .env or a pre-staged credentials file referenced
  by the MAISTRO_BOOTSTRAP_CREDENTIALS_FILE environment variable, never in
  command history.

.PARAMETER Repo
  GitHub "owner/repo" to install from (default: Agent-StrongHold/Project-mAIstro).

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

.NOTES
  Prerequisite: PowerShell script execution must be permitted by your
  administrator-approved setup. A fresh Windows client may use Restricted,
  which prevents .ps1 scripts from running. Inspect the policies read-only
  with Get-ExecutionPolicy -List before running any example below. Group
  Policy takes precedence; elevation alone does not remove that restriction.
  If execution is disallowed, stop and ask your administrator for approved
  setup instructions, including any signing requirements. Do not work around
  the restriction. These examples do not change execution policy.

.EXAMPLE
  Get-ExecutionPolicy -List
  # If execution is disallowed, stop and obtain administrator-approved setup instructions.
  Invoke-WebRequest -UseBasicParsing -Uri https://raw.githubusercontent.com/Agent-StrongHold/Project-mAIstro/main/get.ps1 -OutFile .\get.ps1
  Get-Content .\get.ps1
  # Review the downloaded script and run it only if you trust its contents.
  .\get.ps1

.EXAMPLE
  .\get.ps1 -AutoInstallDeps

.EXAMPLE
  .\get.ps1 -Version v1.0.0

.EXAMPLE
  .\get.ps1 -AutoInstallDeps -AnswersFile $env:USERPROFILE\answers-v1-smoke.yaml
  Fully unattended: WSL setup is auto-confirmed and the feature/deployment
  choices come from the v1 answers file — the same file `get.sh --
  --answers-file` consumes on Unix.

.EXAMPLE
  .\get.ps1 -Channel dev
#>
[CmdletBinding()]
param(
    [string]$Version = '',
    [ValidateSet('stable', 'dev')]
    [string]$Channel = 'stable',
    [string]$Branch = '',
    # Validated (and translated to a WSL /mnt path) by Assert-AnswersPreflight
    # before anything is installed; forwarded to get.sh inside the distro as
    # `--answers-file` — the same argv contract as the Unix one-liner (#409).
    [string]$AnswersFile = '',
    # SECURITY-REVIEW: -Repo selects external GitHub content and crosses into
    # the WSL shell handoff; preserve argument boundaries when changing it.
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [ValidateScript({
        $owner, $name = $_ -split '/', 2
        $owner -notin @('.', '..') -and $name -notin @('.', '..')
    })]
    [string]$Repo = 'Agent-StrongHold/Project-mAIstro',
    [string]$Distro = 'Ubuntu',
    [switch]$RequireRelease,
    [switch]$AutoInstallDeps,
    [switch]$Resume,
    [switch]$SkipWizard,
    [switch]$NoStart,
    [switch]$NoCli,
    [switch]$NoOpen,
    # Production code never passes this; tests shrink it so the reboot
    # decision in Wait-DistroUsable can be exercised quickly.
    [ValidateRange(1, [int]::MaxValue)]
    [int]$DistroWaitTimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'

# Set when -Distro was passed explicitly. An explicitly requested distro is
# the user's choice: it is never silently substituted (Invoke-Main), and it
# survives the elevation relaunch and the post-reboot resume (see
# Get-PassthroughArgs). The default name, in contrast, is only a fallback for
# machines that have no distro yet.
$script:DistroWasExplicit = $PSBoundParameters.ContainsKey('Distro')

# Set when -AnswersFile was passed explicitly (even as an empty string, which
# the preflight rejects: an unattended run must fail loudly, not fall back to
# interactive prompting mid-install).
$script:AnswersFileWasBound = $PSBoundParameters.ContainsKey('AnswersFile')
# Resolved by Assert-AnswersPreflight before any mutation: the validated
# Windows-side path and its translation into the distro (see the function for
# the exact rules). Empty means "no answers file in play".
$script:AnswersFileResolved = ''
$script:AnswersFileWsl = ''

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

# --- unattended answers file (issue #409) -----------------------------------
#
# -AnswersFile is the Windows twin of get.sh's `-- --answers-file` passthrough:
# one versioned answers schema (InstallAnswersV1, schema_version "1"; templates
# in docs/install/examples/), consumed by maistro-install inside the distro
# exactly as on Unix. The file carries names and flags only — never API keys or
# passwords (SPEC-180); secrets stay in the 0600 .env or a pre-staged bootstrap
# credentials file referenced by MAISTRO_BOOTSTRAP_CREDENTIALS_FILE.

# POSIX single-quote a value for the bash -lc payload: every ' becomes '\''
# (close the quoted span, an escaped quote, reopen). Keeps a path with spaces
# or quotes one argument once bash splits the command string.
function ConvertTo-BashSingleQuoted {
    param([string]$Value)
    return "'" + $Value.Replace("'", "'\''") + "'"
}

# Translate a Windows path to where the distro's automounter mounts it (drvfs
# default: /mnt/<drive>/...). Pure string translation on purpose: the preflight
# runs before any distro exists, so wslpath(1) is not available yet. UNC paths
# return $null — shares are not automounted, and the preflight turns that into
# an actionable error instead of a mid-install failure. POSIX-absolute input
# passes through unchanged: unreachable from a Windows user (Resolve-Path
# always returns a drive-qualified path there), but it keeps the contract
# testable on non-Windows hosts, where the same answers file is already valid
# inside the distro.
function ConvertTo-WslPath {
    param([string]$WindowsPath)
    if ($WindowsPath -match '^([A-Za-z]):[\\/](.*)$') {
        $rest = $Matches[2] -replace '[\\/]', '/'
        return "/mnt/$($Matches[1].ToLowerInvariant())/$rest"
    }
    if ($WindowsPath -match '^/') { return $WindowsPath }
    return $null
}

# Validate -AnswersFile BEFORE any mutation: no WSL setup, no elevation
# prompt, no download, not even a saved copy of this script. Every problem is
# collected and reported in one failure — an unattended run must not dribble
# findings out one reboot at a time. install.sh repeats the conflict and
# existence checks at its own boundary (the common mutation point for both
# entrypoints); doing it here too is what keeps a bad path from ever reaching
# `wsl --install` or a reboot.
function Assert-AnswersPreflight {
    $script:AnswersFileResolved = ''
    $script:AnswersFileWsl = ''
    if (-not $script:AnswersFileWasBound) { return $true }

    $problems = @()
    $resolved = $null
    if ([string]::IsNullOrWhiteSpace($AnswersFile)) {
        $problems += "-AnswersFile was given an empty path. Pass the path to a v1 answers file (template: docs/install/examples/answers-v1-minimal.yaml), or omit the parameter to install interactively."
    } else {
        try {
            $resolved = (Resolve-Path -LiteralPath $AnswersFile -ErrorAction Stop).ProviderPath
        } catch {
            $problems += "answers file not found: $AnswersFile (cwd: $(Get-Location)). Pass the path to a v1 answers file (template: docs/install/examples/answers-v1-minimal.yaml), or drop -AnswersFile to install interactively."
        }
    }
    if ($resolved -and -not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        $problems += "answers path '$resolved' is not a file. Pass the YAML file itself (template: docs/install/examples/answers-v1-minimal.yaml)."
    }
    if ($SkipWizard) {
        $problems += "-AnswersFile conflicts with -SkipWizard: a skipped questionnaire never reads the answers file, so the install would silently ignore it. Remove one of the two (install.sh fails the same combination on Unix)."
    }
    if ($resolved -and (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        $script:AnswersFileWsl = ConvertTo-WslPath -WindowsPath $resolved
        if (-not $script:AnswersFileWsl) {
            $problems += "answers path '$resolved' is not a Windows drive path (UNC shares are not mounted inside the distro). Copy the file to a local drive (e.g. $env:TEMP) and pass that path."
        }
    }

    if ($problems.Count -gt 0) {
        foreach ($problem in $problems) { Write-ErrMsg $problem }
        Write-ErrMsg "Nothing was installed. Combine -AnswersFile with -AutoInstallDeps for a fully unattended run."
        return $false
    }
    $script:AnswersFileResolved = $resolved
    return $true
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
    if ($Repo -ne 'Agent-StrongHold/Project-mAIstro') { $argList += @('-Repo', $Repo) }
    # -Distro must survive the elevation relaunch and the post-reboot resume
    # whenever it was explicit (or already substituted): otherwise a relaunch
    # back into default-parameter land could adopt a different distro than
    # the one this run committed to.
    if ($script:DistroWasExplicit -or $Distro -ne 'Ubuntu') { $argList += @('-Distro', $Distro) }
    if ($AutoInstallDeps) { $argList += '-AutoInstallDeps' }
    # The answers file must survive the elevation relaunch and the post-reboot
    # resume: losing it there would turn an unattended install interactive
    # mid-flight — the exact failure -AnswersFile exists to prevent. Carry the
    # RESOLVED path; the relaunched run re-validates and re-translates it.
    if ($script:AnswersFileWsl) { $argList += @('-AnswersFile', $script:AnswersFileResolved) }
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

# --- WSL distro table -------------------------------------------------------
#
# The default distribution's row in `wsl -l -v` begins with "* " (e.g.
# `* Ubuntu    Running    2`). Ignoring that marker makes an existing, usable
# default distro look absent, which used to push get.ps1 into the install and
# reboot path on machines that were already set up. The column headers and
# the "no installed distributions" banner are localized, so rows are
# recognized structurally — a data row ends in the WSL version (1 or 2), a
# header does not — instead of by matching header text.

# First property whose name matches $Pattern, or $null. Used for the JSON
# listing below, whose member names have shifted across WSL builds.
function Get-JsonObjectMember {
    param([psobject]$Object, [string]$Pattern)
    if ($null -eq $Object) { return $null }
    $member = $Object.PSObject.Properties | Where-Object { $_.Name -match $Pattern } | Select-Object -First 1
    if ($member) { return $member.Value }
    return $null
}

# Machine-readable `wsl --list --json` output, where the installed WSL
# provides it. The JSON schema has moved across builds (bare distribution
# arrays vs. wrapper objects, name/default member spellings), so any shape we
# cannot confidently map returns $null — meaning "no machine-readable
# answer", never "no distributions" — and the caller falls back to the text
# table. A half-trusted table must not win over the parseable fallback.
function ConvertFrom-WslListJson {
    param([AllowNull()][string]$JsonText)
    if (-not $JsonText) { return $null }
    try {
        $parsed = ConvertFrom-Json -InputObject $JsonText
    } catch {
        return $null
    }
    if (-not $parsed) { return $null }

    $distributions = $parsed
    $defaultName = $null
    if ($parsed -isnot [array]) {
        # Wrapper form: { "Distributions": [...], "Default...": "Ubuntu" }.
        $wrapped = Get-JsonObjectMember -Object $parsed -Pattern '(?i)distributions'
        if (-not $wrapped -or $wrapped -is [string]) { return $null }
        $distributions = $wrapped
        $defaultName = Get-JsonObjectMember -Object $parsed -Pattern '(?i)^default'
    }

    $rows = @()
    foreach ($item in @($distributions)) {
        if ($item -isnot [pscustomobject]) { return $null }
        $name = Get-JsonObjectMember -Object $item -Pattern '(?i)^(distribution)?name$'
        if (-not $name) { return $null }
        $state = Get-JsonObjectMember -Object $item -Pattern '(?i)(state|status)'
        $versionValue = Get-JsonObjectMember -Object $item -Pattern '(?i)version'
        $version = 0
        if (-not [int]::TryParse("$versionValue", [ref]$version)) { $version = 0 }
        $isDefault = $false
        if ($defaultName -and "$defaultName" -ieq "$name") { $isDefault = $true }
        $flag = Get-JsonObjectMember -Object $item -Pattern '(?i)default'
        if ($flag -is [bool] -and $flag) { $isDefault = $true }
        $rows += [pscustomobject]@{
            Name = [string]$name
            State = [string]$state
            Version = $version
            Default = [bool]$isDefault
        }
    }
    if (-not $rows) { return $null }
    return ,$rows
}

# Normalize the text table into the same rows: NUL bytes stripped, default
# marker (`* `) recognized, whitespace collapsed, localized headers and
# banners skipped, and the name preserved verbatim (including non-ASCII
# names, which `wsl --import` allows). Accepts one string per console line,
# the way PowerShell hands over native output, and also a single multi-line
# string, the way captured/mocked input arrives.
function ConvertTo-WslDistroRows {
    param([AllowNull()][object[]]$Lines)
    $rows = [System.Collections.Generic.List[object]]::new()
    if (-not $Lines) { return $rows.ToArray() }

    # wsl.exe writes UTF-16LE to a redirected pipe. A host decoding those
    # bytes with a single-byte codepage (Windows PowerShell's OEM default)
    # shows ASCII padded with NUL bytes; strip the NULs and any stray BOM and
    # the original table text survives regardless of which decoder ran.
    $text = [string]::Join("`n", @($Lines))
    foreach ($line in ($text -split "\r?\n")) {
        $line = ($line -replace "`0", '') -replace "^\uFEFF", ''
        $trimmed = $line.Trim()
        if (-not $trimmed) { continue }
        $isDefault = $trimmed.StartsWith('*')
        if ($isDefault) { $trimmed = $trimmed.Substring(1).TrimStart() }
        $tokens = [regex]::Split($trimmed, '\s+')
        # <name> [more name words] <state> <version>
        if ($tokens.Count -lt 3) { continue }
        $version = $tokens[$tokens.Count - 1]
        # The trailing version digit is what separates a data row from a
        # localized header or banner line; both end in words.
        if ($version -ne '1' -and $version -ne '2') { continue }
        if ($tokens.Count -eq 3) {
            $name = $tokens[0]
        } else {
            $name = [string]::Join(' ', $tokens[0..($tokens.Count - 3)])
        }
        if (-not $name) { continue }
        $rows.Add([pscustomobject]@{
            # State text is locale-dependent and informational only; usability
            # is decided by the `wsl -d <name> -- true` probe, never by it.
            Name = $name
            State = $tokens[$tokens.Count - 2]
            Version = [int]$version
            Default = [bool]$isDefault
        })
    }
    return $rows.ToArray()
}

function Get-WslDistroTable {
    # Prefer the machine-readable listing where the installed WSL has one;
    # the text table is the universal fallback.
    if (-not (Test-WslInstalled)) { return @() }
    $jsonText = [string]::Join("`n", @(& wsl.exe --list --json 2>$null))
    if ($jsonText) {
        $rows = ConvertFrom-WslListJson -JsonText ($jsonText -replace "`0", '')
        if ($rows) { return $rows }
    }
    return ConvertTo-WslDistroRows -Lines @(& wsl.exe -l -v 2>$null)
}

function Get-WslDistroState {
    param([string]$Name)
    foreach ($row in @(Get-WslDistroTable)) {
        # Exact, case-insensitive: a prefix match would answer a request for
        # "Ubuntu" with the unrelated "Ubuntu-24.04" distro.
        if ($row.Name -ieq $Name) { return $row }
    }
    return $null
}

function Get-WslDefaultDistroName {
    $default = @(Get-WslDistroTable) | Where-Object { $_.Default } | Select-Object -First 1
    if ($default) { return [string]$default.Name }
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
    # Unattended answers (#409): forwarded as a get.sh passthrough argument —
    # the same argv contract as `get.sh -- --answers-file <path>` on Unix —
    # translated to the distro's /mnt view of the Windows filesystem, and
    # single-quoted so a path with spaces or quotes stays one argument.
    $bashArgs = ''
    if ($script:AnswersFileWsl) {
        $bashArgs = " -s -- --answers-file $(ConvertTo-BashSingleQuoted -Value $script:AnswersFileWsl)"
    }
    # Secrets never travel on argv or in the answers file (SPEC-180). The
    # secure channel for first-run credentials is a pre-staged 0600 file
    # referenced by environment variable; when it lives on the Windows side,
    # its path needs the same translation to be reachable inside the distro.
    if ($env:MAISTRO_BOOTSTRAP_CREDENTIALS_FILE) {
        $credsWsl = ConvertTo-WslPath -WindowsPath $env:MAISTRO_BOOTSTRAP_CREDENTIALS_FILE
        if (-not $credsWsl) { $credsWsl = $env:MAISTRO_BOOTSTRAP_CREDENTIALS_FILE }
        $envAssignments += "MAISTRO_BOOTSTRAP_CREDENTIALS_FILE=$(ConvertTo-BashSingleQuoted -Value $credsWsl)"
    }
    # Checksum verification of the fetched install.sh (SPEC-072726-3439
    # Phase 5): forward the manifest URL so get.sh verifies before executing.
    if ($env:MAISTRO_SHA256SUMS_URL) { $envAssignments += "MAISTRO_SHA256SUMS_URL=$($env:MAISTRO_SHA256SUMS_URL)" }
    $exports = ($envAssignments | ForEach-Object { "export $_;" }) -join ' '

    # Fetch get.sh from the ref being installed, so the bootstrapper and the
    # tree it lays down are the same revision. -s reads the script from stdin;
    # everything after `--` is handed to it verbatim (its own options end
    # there, so --answers-file lands in get.sh's install.sh passthrough).
    $getShUrl = "https://raw.githubusercontent.com/$Repo/$($script:Ref)/get.sh"
    $innerCmd = "$exports curl -fsSL $getShUrl | bash$bashArgs"

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

    # Validate the unattended answers contract before ANY mutation — no
    # release lookup, no elevation prompt, no `wsl --install`, no reboot.
    if (-not (Assert-AnswersPreflight)) { exit 1 }

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

    # A machine that already has a usable WSL2 default distro must never be
    # pushed through `wsl --install` (and the reboot that can follow) just
    # because its name differs from our default. Without this, a box set up
    # with e.g. Debian first sat through an unnecessary install and the
    # feature-enable reboot loop. An explicitly requested -Distro is exempt:
    # the user asked for that name specifically.
    if (-not $script:DistroWasExplicit) {
        $existingDefault = Get-WslDefaultDistroName
        if ($existingDefault -and $existingDefault -ine $Distro -and (Test-DistroUsable -Name $existingDefault)) {
            Write-WarnMsg "No '$Distro' distro found, but existing default '$existingDefault' is usable."
            Write-WarnMsg "Installing into '$existingDefault' instead of creating a new distro (pass -Distro <name> to override)."
            $script:Distro = $existingDefault
            Invoke-LinuxInstall
            return
        }
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

    if (Wait-DistroUsable -Name $Distro -TimeoutSeconds $DistroWaitTimeoutSeconds) {
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
