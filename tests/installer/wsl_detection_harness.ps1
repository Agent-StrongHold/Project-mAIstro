# Test harness for get.ps1's WSL distro detection (#354).
#
# Runs the real get.ps1 functions — dot-sourced from the repo, with only the
# process boundary (wsl.exe, GitHub API, reboot) scripted — under both
# PowerShell editions:
#
#   parser   feed one captured `wsl -l -v` fixture through
#            ConvertTo-WslDistroRows twice: once as plain lines, once
#            re-encoded the way wsl.exe actually reaches PowerShell
#            (UTF-16LE bytes decoded with a single-byte codepage, i.e.
#            NUL-padded mojibake). Asserts the parsed rows.
#   scenario script wsl.exe with a captured table and drive Invoke-Main
#            end-to-end, asserting install/reboot/handoff decisions.
#   List     print every case as "<mode>:<case>" (used by the Windows E2E
#            runner and pytest to enumerate without duplicating the list).
#
# 5.1-compatible on purpose: it must also run under Windows PowerShell.
param(
    [ValidateSet('List', 'parser', 'scenario')]
    [string]$Mode = 'List',
    [string]$Case = '',
    [string]$GetPs1 = '',
    [string]$Fixtures = ''
)

$ErrorActionPreference = 'Stop'

# --- shared helpers ---------------------------------------------------------

# Reproduce what PowerShell sees when wsl.exe writes UTF-16LE to a redirected
# pipe and the host decodes it with a single-byte codepage: every UTF-16LE
# byte becomes one char, so ASCII text arrives NUL-padded and non-ASCII text
# arrives as codepage mojibake. Codepage 437 is the classic US-OEM decoder.
# Note the transformation is LOSSY for non-ASCII content (that is the point):
# the parser must still recover rows structurally — the default marker, the
# name, and the trailing version digit are ASCII and always survive, while
# localized state text may not, which is fine because nothing matches on it.
function ConvertTo-WslMojibakeLines {
    param([AllowNull()][string]$Table)
    if (-not $Table) { return $null }
    $utf16Bytes = [System.Text.Encoding]::Unicode.GetBytes($Table)
    $asSingleByte = [System.Text.Encoding]::GetEncoding(437).GetString($utf16Bytes)
    return ($asSingleByte -split "\r?\n")
}

function Fail {
    param([string]$Message)
    Write-Output "RESULT $Mode$(if ($Case) { ":${Case}" }) failed: $Message"
    exit 1
}

if (-not $GetPs1) { Fail 'harness setup error: -GetPs1 is required' }

# --- captured `wsl -l -v` variants and their expected rows ------------------

$script:ParserExpectations = @{
    # NameLossy / StateLossy: that field is non-ASCII, so the utf16-mojibake
    # variant cannot round-trip it (single-byte decoders destroy it); the
    # variant asserts only the fields that survive. The plain variant — a host
    # that decoded the UTF-16LE bytes correctly — always asserts every field.
    'english-default-and-second' = @(
        [pscustomobject]@{ Name = 'Ubuntu-22.04'; State = 'Running'; Version = 2; Default = $true },
        [pscustomobject]@{ Name = 'Debian-10'; State = 'Stopped'; Version = 1; Default = $false }
    )
    'english-single-wsl1-default-stopped' = @(
        [pscustomobject]@{ Name = 'Ubuntu-18.04'; State = 'Stopped'; Version = 1; Default = $true }
    )
    'english-no-default-multiple' = @(
        [pscustomobject]@{ Name = 'Debian-10'; State = 'Stopped'; Version = 1; Default = $false },
        [pscustomobject]@{ Name = 'Ubuntu-20.04'; State = 'Stopped'; Version = 1; Default = $false }
    )
    'english-docker-desktop-trio' = @(
        [pscustomobject]@{ Name = 'Ubuntu'; State = 'Running'; Version = 2; Default = $true },
        [pscustomobject]@{ Name = 'docker-desktop'; State = 'Running'; Version = 2; Default = $false },
        [pscustomobject]@{ Name = 'docker-desktop-data'; State = 'Running'; Version = 2; Default = $false }
    )
    'german-headers-wsl1-and-wsl2' = @(
        [pscustomobject]@{ Name = 'Ubuntu'; State = 'Läuft'; Version = 2; Default = $true; StateLossy = $true },
        [pscustomobject]@{ Name = 'Debian'; State = 'Gestoppt'; Version = 1; Default = $false }
    )
    'french-headers-single-default' = @(
        [pscustomobject]@{ Name = 'Ubuntu'; State = 'Running'; Version = 2; Default = $true }
    )
    'japanese-headers-default-running' = @(
        [pscustomobject]@{ Name = 'Ubuntu'; State = '実行中'; Version = 2; Default = $true; StateLossy = $true }
    )
    'chinese-headers-no-default' = @(
        [pscustomobject]@{ Name = 'Ubuntu'; State = '已停止'; Version = 2; Default = $false; StateLossy = $true },
        [pscustomobject]@{ Name = 'Debian'; State = '正在运行'; Version = 2; Default = $false; StateLossy = $true }
    )
    'unicode-distro-name-multiword' = @(
        [pscustomobject]@{ Name = 'Ubuntu'; State = 'Running'; Version = 2; Default = $true },
        [pscustomobject]@{ Name = 'Тестовый дистр'; State = 'Stopped'; Version = 2; Default = $false; NameLossy = $true }
    )
    'installing-state-fresh' = @(
        [pscustomobject]@{ Name = 'Ubuntu'; State = 'Installing'; Version = 2; Default = $true }
    )
    'no-distros-banner' = @()
    'no-distros-banner-localized' = @()
    'empty-output' = @()
}

$script:ScenarioNames = @(
    'existing-default-usable',
    'rerun-twice-idempotent',
    'existing-nondefault-usable',
    'adopt-existing-default',
    'explicit-distro-preserved',
    'fresh-install-no-distros',
    'install-stuck-reboots',
    'json-table-preferred',
    'json-unmapped-falls-back',
    'exact-name-match'
)

if ($Mode -eq 'List') {
    foreach ($name in ($script:ParserExpectations.Keys | Sort-Object)) {
        Write-Output "parser:$name"
    }
    foreach ($name in $script:ScenarioNames) {
        Write-Output "scenario:$name"
    }
    exit 0
}

if (-not $Case) { Fail "harness setup error: -Case is required for -Mode $Mode" }

# --- scripted process boundary (scenarios) ----------------------------------

$script:WslCalls = @()
$script:InstallCalls = 0
$script:RebootRequested = $false
$script:TextListAsked = $false
# Captured `wsl -l -v` table the stub hands out (plain text; mojibake'd at emit).
$script:ListTableRaw = ''
# Table handed out after `wsl --install` ran; $null keeps the first table.
$script:PostInstallTableRaw = $null
# Captured `wsl --list --json` payload; empty means "installed WSL has no
# machine-readable listing" (the common case today).
$script:JsonText = ''
# Exit code of the `wsl -d <name> -u root -- true` usability probe.
$script:ProbeExitCode = 0
# Probe exit once a `wsl --install` has run (the distro becoming usable);
# $null keeps $ProbeExitCode in force.
$script:PostInstallProbeExit = $null

function Reset-ScriptedWorld {
    $script:WslCalls = @()
    $script:InstallCalls = 0
    $script:RebootRequested = $false
    $script:TextListAsked = $false
    $script:ListTableRaw = ''
    $script:PostInstallTableRaw = $null
    $script:JsonText = ''
    $script:ProbeExitCode = 0
    $script:PostInstallProbeExit = $null
}

function wsl.exe {
    $argLine = ($args -join ' ')
    $script:WslCalls += $argLine
    $global:LASTEXITCODE = 0
    if ($argLine -like '--list --json') {
        if ($script:JsonText) { return ConvertTo-WslMojibakeLines -Table $script:JsonText }
        $global:LASTEXITCODE = 1
        return
    }
    if ($argLine -like '*-l -v') {
        $script:TextListAsked = $true
        $table = $script:ListTableRaw
        if ($script:InstallCalls -gt 0 -and $null -ne $script:PostInstallTableRaw) {
            $table = $script:PostInstallTableRaw
        }
        if (-not $table) {
            $global:LASTEXITCODE = 1
            return
        }
        return ConvertTo-WslMojibakeLines -Table $table
    }
    if ($argLine -like '*--install*') {
        $script:InstallCalls += 1
        return
    }
    # Usability probe. NOTE: this stub is a PowerShell function, and function
    # parameter binding strips the `--` end-of-parameters token, so the call
    # get.ps1 makes as `-d <name> -u root -- true` arrives here as
    # `-d <name> -u root true`. Match both spellings.
    if ($argLine -like '*-- true' -or $argLine -like '-d * true') {
        if ($script:InstallCalls -gt 0 -and $null -ne $script:PostInstallProbeExit) {
            $global:LASTEXITCODE = $script:PostInstallProbeExit
        } else {
            $global:LASTEXITCODE = $script:ProbeExitCode
        }
        return
    }
    return
}

# Dot-source get.ps1 for real, minus its entrypoint call. Everything below
# this line that redefines a function is overriding the dot-sourced one.
$source = (Get-Content -Raw -LiteralPath $GetPs1) -replace '(?m)^Invoke-Main\s*$', ''
$scriptBlock = [scriptblock]::Create($source)

function Install-Overrides {
    # Dot-invoked (`. Install-Overrides`): defines the stubs in the caller's
    # scope, so they override the dot-sourced get.ps1 functions.
    function Invoke-RestMethod {
        param([string]$Uri, [hashtable]$Headers, [switch]$UseBasicParsing, [int]$TimeoutSec)
        return [pscustomobject]@{ tag_name = 'v9.8.7' }
    }
    function Save-StableCopy {
        return (Join-Path ([System.IO.Path]::GetTempPath()) 'maistro-get-copy.ps1')
    }
    function Register-Resume {
        param([string]$ScriptPath)
    }
    function Test-WindowsBuild { return $true }
    function Test-Virtualization { }
    function Test-Admin { return $true }
    function Confirm-Action {
        param([string]$Prompt)
        return $true
    }
    function Restart-Computer {
        $script:RebootRequested = $true
    }
}

function Assert-NoInstallAndNoReboot {
    if ($script:InstallCalls -ne 0) {
        Fail "expected no 'wsl --install' call, got $($script:InstallCalls): $($script:WslCalls -join ' ; ')"
    }
    if ($script:RebootRequested) { Fail 'unexpected Restart-Computer' }
}

function Test-HandoffRan {
    return @($script:WslCalls | Where-Object { $_ -like '*bash -lc*' }).Count -gt 0
}

function Assert-LinuxInstallRan {
    param([string]$Because)
    if (-not (Test-HandoffRan)) { Fail "$Because (no bash -lc handoff in wsl calls)" }
}

function Assert-NoLinuxInstall {
    param([string]$Because)
    if (Test-HandoffRan) { Fail "$Because (unexpected bash -lc handoff)" }
}

function Assert-LinuxHandoff {
    param([string]$DistroName)
    $last = $script:WslCalls[-1]
    if ($last -notlike '*bash -lc*') { Fail "expected a bash -lc handoff as the last wsl call, got: $last" }
    if ($last -notlike '*-d ' + $DistroName + ' *') { Fail "handoff targeted wrong distro, expected ${DistroName}: $last" }
    if ($last -notlike '*export MAISTRO_VERSION=v9.8.7;*') { Fail "handoff does not pin the resolved release: $last" }
    if ($last -notlike '*raw.githubusercontent.com/Agent-StrongHold/Project-mAIstro/v9.8.7/get.sh*') {
        Fail "handoff does not fetch get.sh from the resolved ref: $last"
    }
}

# --- Mode: parser -----------------------------------------------------------

if ($Mode -eq 'parser') {
    if (-not $Fixtures) { Fail 'harness setup error: -Fixtures is required for parser mode' }
    $fixturePath = Join-Path $Fixtures "$Case.txt"
    if (-not (Test-Path -LiteralPath $fixturePath)) { Fail "fixture not found: $fixturePath" }
    if (-not $script:ParserExpectations.ContainsKey($Case)) { Fail "no expectation registered for fixture '$Case'" }
    # The parser under test is the production one in get.ps1.
    $source = (Get-Content -Raw -LiteralPath $GetPs1) -replace '(?m)^Invoke-Main\s*$', ''
    . ([scriptblock]::Create($source))
    $expected = @($script:ParserExpectations[$Case])
    $tableText = [System.IO.File]::ReadAllText($fixturePath)

    $variants = @{
        plain = @($tableText -split "\r?\n")
        'utf16-mojibake' = @(ConvertTo-WslMojibakeLines -Table $tableText)
    }

    foreach ($variantName in $variants.Keys) {
        $rows = @(ConvertTo-WslDistroRows -Lines $variants[$variantName])
        if ($rows.Count -ne $expected.Count) {
            Fail "variant '$variantName': expected $($expected.Count) rows, got $($rows.Count) ($(($rows | ForEach-Object { $_.Name }) -join ', '))"
        }
        for ($i = 0; $i -lt $expected.Count; $i++) {
            $row = $rows[$i]
            $want = $expected[$i]
            # NameLossy/StateLossy fields are non-ASCII and cannot survive the
            # single-byte utf16-mojibake decode; only the lossless plain
            # variant asserts them.
            $nameComparable = -not ($variantName -eq 'utf16-mojibake' -and $want.NameLossy)
            $stateComparable = -not ($variantName -eq 'utf16-mojibake' -and $want.StateLossy)
            if ($nameComparable -and $row.Name -cne $want.Name) { Fail "variant '$variantName' row ${i}: Name '$($row.Name)' != '$($want.Name)'" }
            if ($stateComparable -and $row.State -cne $want.State) { Fail "variant '$variantName' row ${i}: State '$($row.State)' != '$($want.State)'" }
            if ($row.Version -ne $want.Version) { Fail "variant '$variantName' row ${i}: Version $($row.Version) != $($want.Version)" }
            if ($row.Default -ne $want.Default) { Fail "variant '$variantName' row ${i}: Default $($row.Default) != $($want.Default)" }
        }
    }
    Write-Output "RESULT parser:${Case} ok"
    exit 0
}

# --- Mode: scenario ---------------------------------------------------------

if ($script:ScenarioNames -notcontains $Case) { Fail "unknown scenario '$Case'" }

Reset-ScriptedWorld

switch ($Case) {
    'existing-default-usable' {
        # #354 regression: the default distro row leads with "* " and must be
        # detected, so a set-up machine goes straight to the Linux install.
        $script:ListTableRaw = "* Ubuntu                 Running         2`n" +
            "  docker-desktop         Running         2"
        . $scriptBlock
        . Install-Overrides
        Invoke-Main
        Assert-LinuxInstallRan 'existing default distro was not used'
        Assert-NoInstallAndNoReboot
        Assert-LinuxHandoff 'Ubuntu'
    }
    'rerun-twice-idempotent' {
        # Definition of done: re-running get.ps1 on a configured machine takes
        # the same no-install/no-reboot path every time.
        $script:ListTableRaw = "* Ubuntu                 Running         2"
        . $scriptBlock
        . Install-Overrides
        for ($round = 1; $round -le 2; $round++) {
            $script:WslCalls = @()
            Invoke-Main
            Assert-LinuxInstallRan "round ${round}: Linux install never ran"
            Assert-NoInstallAndNoReboot
        }
    }
    'existing-nondefault-usable' {
        # The requested distro exists but is not the default (no "* " row) —
        # the marker must not be required to find it.
        $script:ListTableRaw = "  Ubuntu                 Stopped         2"
        . $scriptBlock
        . Install-Overrides
        Invoke-Main
        Assert-LinuxInstallRan 'non-default registered distro was not used'
        Assert-NoInstallAndNoReboot
        Assert-LinuxHandoff 'Ubuntu'
    }
    'adopt-existing-default' {
        # No 'Ubuntu' anywhere, but an existing usable WSL2 default: use it,
        # never install over the user's machine.
        $script:ListTableRaw = "* Debian-12              Running         2"
        . $scriptBlock
        . Install-Overrides
        Invoke-Main
        Assert-LinuxInstallRan 'existing default was not adopted'
        if ($Distro -cne 'Debian-12') { Fail "distro was not switched to the adopted default (still '$Distro')" }
        Assert-NoInstallAndNoReboot
        Assert-LinuxHandoff 'Debian-12'
    }
    'explicit-distro-preserved' {
        # An explicitly requested -Distro wins over the existing default and
        # is the one that gets installed.
        $script:ListTableRaw = "* Ubuntu                 Running         2"
        $script:PostInstallTableRaw = "* Debian                 Installing      2"
        . $scriptBlock -Distro 'Debian'
        . Install-Overrides
        Invoke-Main
        if ($script:InstallCalls -ne 1) { Fail "expected exactly one 'wsl --install' call for the explicit distro, got $($script:InstallCalls)" }
        if (($script:WslCalls | Where-Object { $_ -like '*--install*' }) -notlike '*-d Debian') {
            Fail "explicit distro not preserved; install calls: $($script:WslCalls -join ' ; ')"
        }
        Assert-LinuxInstallRan 'install into the explicitly requested distro never completed'
        if ($script:RebootRequested) { Fail 'reboot requested although the distro became usable' }
        if ($Distro -cne 'Debian') { Fail "explicit -Distro mutated (now '$Distro')" }
        Assert-LinuxHandoff 'Debian'
    }
    'fresh-install-no-distros' {
        # Empty machine (localized "no distributions" banner on stdout):
        # install the requested distro and finish without a reboot.
        $script:ListTableRaw = "Windows Subsystem for Linux has no installed distributions."
        $script:ProbeExitCode = 1
        $script:PostInstallTableRaw = "* Ubuntu                 Running         2"
        $script:PostInstallProbeExit = 0
        . $scriptBlock
        . Install-Overrides
        Invoke-Main
        if ($script:InstallCalls -ne 1) { Fail "expected one 'wsl --install' on a fresh machine, got $($script:InstallCalls)" }
        Assert-LinuxInstallRan 'fresh install never completed'
        if ($script:RebootRequested) { Fail 'reboot requested although the fresh install became usable' }
        Assert-LinuxHandoff 'Ubuntu'
    }
    'install-stuck-reboots' {
        # The one legitimate reboot: after `wsl --install`, the distro never
        # becomes usable within the wait window.
        $script:ListTableRaw = "Windows Subsystem for Linux has no installed distributions."
        $script:ProbeExitCode = 1
        $script:PostInstallTableRaw = "* Ubuntu                 Installing      2"
        . $scriptBlock -DistroWaitTimeoutSeconds 2
        . Install-Overrides
        Invoke-Main
        if ($script:InstallCalls -ne 1) { Fail "expected one 'wsl --install', got $($script:InstallCalls)" }
        if (-not $script:RebootRequested) { Fail 'stuck install did not request the reboot' }
        Assert-NoLinuxInstall 'Linux install ran although the distro never became usable'
    }
    'json-table-preferred' {
        # Where the installed WSL offers machine-readable listing, it wins and
        # the text table is never consulted.
        $script:JsonText = '[{"Name":"Ubuntu","State":"Running","Version":2,"Default":true},' +
            '{"Name":"Debian","State":"Stopped","Version":1,"Default":false}]'
        . $scriptBlock
        . Install-Overrides
        Invoke-Main
        if ($script:TextListAsked) { Fail 'text table was consulted although JSON listing was available' }
        Assert-LinuxInstallRan 'JSON-listed distro was not used'
        Assert-NoInstallAndNoReboot
        Assert-LinuxHandoff 'Ubuntu'
    }
    'json-unmapped-falls-back' {
        # A JSON payload we cannot confidently map must fall back to the text
        # table, not be mistaken for "no distributions".
        $script:JsonText = '{"Distributions": "not-a-list"}'
        $script:ListTableRaw = "* Ubuntu                 Running         2"
        . $scriptBlock
        . Install-Overrides
        Invoke-Main
        if (-not $script:TextListAsked) { Fail 'unmapped JSON did not fall back to the text table' }
        Assert-LinuxInstallRan 'fallback table was not used'
        Assert-NoInstallAndNoReboot
        Assert-LinuxHandoff 'Ubuntu'
    }
    'exact-name-match' {
        # Name lookup is exact: "Ubuntu" must not match "Ubuntu-22.04", and
        # the case-insensitive exact name must find the default row.
        $script:ListTableRaw = "* Ubuntu-22.04           Running         2`n" +
            "  Debian                 Stopped         1"
        . $scriptBlock
        . Install-Overrides
        $prefix = Get-WslDistroState -Name 'Ubuntu'
        if ($null -ne $prefix) { Fail "prefix leak: 'Ubuntu' matched '$($prefix.Name)'" }
        $exact = Get-WslDistroState -Name 'ubuntu-22.04'
        if ($null -eq $exact) { Fail 'case-insensitive exact name did not match' }
        if ($exact.Name -cne 'Ubuntu-22.04' -or -not $exact.Default) {
            Fail "wrong row for 'ubuntu-22.04': Name=$($exact.Name) Default=$($exact.Default)"
        }
        $defaultName = Get-WslDefaultDistroName
        if ($defaultName -cne 'Ubuntu-22.04') { Fail "default distro '$defaultName' != 'Ubuntu-22.04'" }
    }
    default {
        Fail "scenario '$Case' has no implementation"
    }
}

Write-Output "RESULT scenario:$Case ok"
exit 0
