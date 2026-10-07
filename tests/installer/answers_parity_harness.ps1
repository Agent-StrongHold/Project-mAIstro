# Test harness for get.ps1's unattended answers-file support (#409).
#
# Runs the real get.ps1 functions -- dot-sourced from the repo, with only the
# process boundary (wsl.exe, GitHub API, reboot) scripted -- under both
# shipping PowerShell editions:
#
#   unit:<name>    pure functions and preflight decisions: Windows->WSL path
#                  translation, POSIX single-quoting, and every
#                  Assert-AnswersPreflight verdict (unbound, empty, missing,
#                  directory, SkipWizard conflict, valid file).
#   handoff:<name> end-to-end through Invoke-Main with a usable distro:
#                  -AnswersFile must reach the get.sh handoff as
#                  `bash -s -- --answers-file '<wsl-path>'`, survive
#                  Get-PassthroughArgs (elevation relaunch / reboot resume),
#                  and a plain run must keep the bare `| bash` pipe.
#   blocked:<name> the exit-1 preflight paths, driven through the REAL
#                  get.ps1 in a child process (exit cannot be observed
#                  in-process): every problem is reported in one failure,
#                  before any mutation, with no false positives.
#
# List mode prints every case as "<kind>:<name>" (the Windows E2E runner and
# pytest enumerate from this; the lists must not drift apart).
#
# ASCII-only on purpose: it must parse identically under Windows PowerShell
# 5.1 and PowerShell 7.
param(
    [ValidateSet('List', 'unit', 'handoff', 'blocked')]
    [string]$Mode = 'List',
    [string]$Case = '',
    [string]$GetPs1 = '',
    # Optional answers fixture to run the handoff leg with (path must be valid
    # on THIS host). When omitted, a minimal v1 file is generated in the temp
    # directory. The pytest supervision passes the repo's smoke fixture so
    # both platform legs consume literally the same file.
    [string]$Fixture = ''
)

$ErrorActionPreference = 'Stop'

function Fail {
    param([string]$Message)
    Write-Output "RESULT $Mode$(if ($Case) { ":${Case}" }) failed: $Message"
    exit 1
}

if (-not $GetPs1) { Fail 'harness setup error: -GetPs1 is required' }

function New-TempDirectory {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
    New-Item -ItemType Directory -Path $path | Out-Null
    return $path
}

function Write-TempAnswersFile {
    param([string]$Directory, [string]$Name = 'answers-v1.yaml')
    $path = Join-Path $Directory $Name
    # Minimal v1 answers: names and flags only, never secrets (SPEC-180).
    $body = @(
        'schema_version: "1"',
        'install_mode: preview',
        'features: []',
        'dry_run: true',
        'container_runtime: docker',
        'users_intent: skip',
        'stack_bringup: none'
    ) -join "`n"
    [System.IO.File]::WriteAllText($path, $body + "`n")
    return $path
}

# True when running on Windows (the only place /mnt/<drive> translation can
# apply; on non-Windows hosts the answers file is already in distro space).
function Test-OnWindows {
    return [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
}

# --- Mode: List --------------------------------------------------------------

if ($Mode -eq 'List') {
    Write-Output 'unit:translate'
    Write-Output 'unit:bash-quoting'
    Write-Output 'unit:preflight-unbound-is-noop'
    Write-Output 'unit:preflight-empty-explicit'
    Write-Output 'unit:preflight-missing-collects-all'
    Write-Output 'unit:preflight-accepts-file'
    Write-Output 'handoff:plain-still-uses-simple-pipe'
    Write-Output 'handoff:forwards-answers-file'
    Write-Output 'blocked:missing-and-conflict-collect-both'
    Write-Output 'blocked:directory'
    Write-Output 'blocked:valid-file-conflict-only'
    exit 0
}

if (-not $Case) { Fail "harness setup error: -Case is required for -Mode $Mode" }

# --- scripted process boundary ----------------------------------------------

$script:WslCalls = @()
$script:InstallCalls = 0
$script:RebootRequested = $false

function Reset-ScriptedWorld {
    $script:WslCalls = @()
    $script:InstallCalls = 0
    $script:RebootRequested = $false
}

function wsl.exe {
    $argLine = ($args -join ' ')
    $script:WslCalls += $argLine
    $global:LASTEXITCODE = 0
    if ($argLine -like '*--install*') {
        $script:InstallCalls += 1
        return
    }
    if ($argLine -like '*bash -lc*') {
        return 'apt-get simulated'
    }
    # Usability probe (`-d <name> -u root -- true`): every distro is usable.
    return
}

# Dot-source get.ps1 for real, minus its entrypoint call. Everything below
# that redefines a function is overriding the dot-sourced one.
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
        Fail "expected no 'wsl --install' call, got $($script:InstallCalls)"
    }
    if ($script:RebootRequested) { Fail 'unexpected Restart-Computer' }
}

# Runs the REAL get.ps1 in a child process (the same interpreter this harness
# runs under) and captures its exit code and output. Used for the preflight
# exit-1 paths, which cannot be observed in-process. These cases never reach
# wsl.exe or the network: the preflight is the first statement of Invoke-Main.
function Invoke-GetPs1Child {
    param([string[]]$ScriptArgs)
    $exe = (Get-Process -Id $PID).Path
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    $quoted = ($ScriptArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
    $argumentList = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$GetPs1`" $quoted"
    $child = Start-Process -FilePath $exe -ArgumentList $argumentList -Wait -PassThru `
        -NoNewWindow -RedirectStandardOutput $out -RedirectStandardError $err
    $stdout = [System.IO.File]::ReadAllText($out)
    $stderr = [System.IO.File]::ReadAllText($err)
    Remove-Item -LiteralPath $out, $err -Force
    return [pscustomobject]@{
        ExitCode = $child.ExitCode
        Output   = ($stdout + "`n" + $stderr)
    }
}

# --- Mode: unit --------------------------------------------------------------

if ($Mode -eq 'unit') {
    Reset-ScriptedWorld
    . $scriptBlock
    . Install-Overrides

    switch ($Case) {
        'translate' {
            $cases = @(
                @{ In = 'C:\Users\me\answers.yaml'; Want = '/mnt/c/Users/me/answers.yaml' },
                @{ In = 'd:/X/y.yaml';              Want = '/mnt/d/X/y.yaml' },
                @{ In = 'Z:\';                      Want = '/mnt/z/' },
                @{ In = '\\srv\share\answers.yaml'; Want = $null },
                @{ In = '/tmp/answers.yaml';        Want = '/tmp/answers.yaml' },
                @{ In = 'answers.yaml';             Want = $null },
                @{ In = '';                         Want = $null }
            )
            foreach ($entry in $cases) {
                $got = ConvertTo-WslPath -WindowsPath $entry.In
                if ($got -cne $entry.Want) {
                    Fail "translate '$($entry.In)': expected '$($entry.Want)', got '$got'"
                }
            }
        }
        'bash-quoting' {
            $cases = @(
                @{ In = '/mnt/c/answers.yaml';                  Want = "'/mnt/c/answers.yaml'" },
                @{ In = '/mnt/c/my answers/a.yaml';             Want = "'/mnt/c/my answers/a.yaml'" },
                @{ In = "/mnt/c/o'brien/a.yaml";                Want = "'/mnt/c/o'\''brien/a.yaml'" }
            )
            foreach ($entry in $cases) {
                $got = ConvertTo-BashSingleQuoted -Value $entry.In
                if ($got -cne $entry.Want) {
                    Fail "quote '$($entry.In)': expected '$($entry.Want)', got '$got'"
                }
            }
        }
        'preflight-unbound-is-noop' {
            $script:AnswersFileWasBound = $false
            $AnswersFile = 'C:\whatever\answers.yaml'
            if (-not (Assert-AnswersPreflight)) { Fail 'preflight rejected an unbound -AnswersFile' }
            if ($script:AnswersFileWsl -ne '') { Fail 'unbound preflight must not set the WSL path' }
        }
        'preflight-empty-explicit' {
            $script:AnswersFileWasBound = $true
            $AnswersFile = ''
            if (Assert-AnswersPreflight) { Fail 'preflight accepted an explicit empty path' }
            if ($script:AnswersFileWsl -ne '') { Fail 'rejected preflight must leave the WSL path empty' }
        }
        'preflight-missing-collects-all' {
            $script:AnswersFileWasBound = $true
            $AnswersFile = Join-Path (New-TempDirectory) 'definitely-missing.yaml'
            $SkipWizard = $true
            if (Assert-AnswersPreflight) { Fail 'preflight accepted a missing answers file' }
            if ($SkipWizard -ne $true) { Fail 'SkipWizard state was clobbered' }
        }
        'preflight-accepts-file' {
            $script:AnswersFileWasBound = $true
            $AnswersFile = Write-TempAnswersFile -Directory (New-TempDirectory)
            if (-not (Assert-AnswersPreflight)) { Fail 'preflight rejected a valid answers file' }
            if ($script:AnswersFileResolved -cne $AnswersFile) {
                Fail "resolved path '$($script:AnswersFileResolved)' != input '$AnswersFile'"
            }
            if (-not $script:AnswersFileWsl) { Fail 'valid file must produce a WSL path' }
            if (Test-OnWindows) {
                if ($script:AnswersFileWsl -notlike '/mnt/*') {
                    Fail "on Windows the translated path must live under /mnt, got '$($script:AnswersFileWsl)'"
                }
            } elseif ($script:AnswersFileWsl -cne $AnswersFile) {
                Fail "off-Windows the POSIX path must pass through, got '$($script:AnswersFileWsl)'"
            }
            if ([System.IO.Path]::GetFileName($script:AnswersFileWsl) -ne (Split-Path -Leaf $AnswersFile)) {
                Fail 'translation lost the file name'
            }
        }
        default { Fail "unknown unit case '$Case'" }
    }
    Assert-NoInstallAndNoReboot
    if ($script:WslCalls.Count -ne 0) { Fail "unit case called wsl.exe: $($script:WslCalls -join ' ; ')" }
    Write-Output "RESULT ${Mode}:${Case} ok"
    exit 0
}

# --- Mode: handoff -----------------------------------------------------------

if ($Mode -eq 'handoff') {
    Reset-ScriptedWorld
    . $scriptBlock
    . Install-Overrides
    # A ready default distro: Invoke-Main goes straight to Invoke-LinuxInstall.
    # Defined after the dot-source so it wins over the real implementation.
    function Get-WslDistroTable {
        return @([pscustomobject]@{ Name = 'Ubuntu'; State = 'Running'; Version = 2; Default = $true })
    }

    switch ($Case) {
        'plain-still-uses-simple-pipe' {
            $script:AnswersFileWasBound = $false
            Invoke-Main
            $last = $script:WslCalls[-1]
            if ($last -notlike '*bash -lc*') { Fail "expected the bash -lc handoff, got: $last" }
            if ($last -like '*-s --*') { Fail "answers pipe syntax leaked into a plain run: $last" }
            if ($last -notlike '*| bash') { Fail "plain run must keep the bare '| bash' pipe: $last" }
        }
        'forwards-answers-file' {
            $tmpDir = New-TempDirectory
            if ($Fixture) {
                if (-not (Test-Path -LiteralPath $Fixture)) { Fail "fixture not found: $Fixture" }
                $AnswersFile = (Resolve-Path -LiteralPath $Fixture).ProviderPath
            } else {
                $AnswersFile = Write-TempAnswersFile -Directory $tmpDir
            }
            $script:AnswersFileWasBound = $true

            Invoke-Main
            Assert-NoInstallAndNoReboot
            $last = $script:WslCalls[-1]
            if ($last -notlike '*bash -lc*') { Fail "expected the bash -lc handoff, got: $last" }
            if ($last -notlike '*curl -fsSL https://raw.githubusercontent.com/Agent-StrongHold/Project-mAIstro/v9.8.7/get.sh | bash -s -- --answers-file*') {
                Fail "handoff does not fetch get.sh from the resolved ref and pass --answers-file: $last"
            }
            if (-not $script:AnswersFileWsl) { Fail 'Invoke-Main left no WSL answers path' }
            $expectedQuoted = ConvertTo-BashSingleQuoted -Value $script:AnswersFileWsl
            if ($last -notlike "*--answers-file $expectedQuoted") {
                Fail "handoff does not forward the translated path single-quoted: $last"
            }
            if (Test-OnWindows) {
                if ($script:AnswersFileWsl -notlike '/mnt/*') {
                    Fail "translated path must live under /mnt on Windows: $($script:AnswersFileWsl)"
                }
            } elseif ($script:AnswersFileWsl -cne $AnswersFile) {
                Fail "off-Windows the POSIX path must pass through: $($script:AnswersFileWsl)"
            }
            # The elevation relaunch and the post-reboot resume both rebuild the
            # command line from Get-PassthroughArgs; losing -AnswersFile there
            # would turn the unattended install interactive mid-flight.
            $passthrough = Get-PassthroughArgs -IncludeResume
            $found = $false
            for ($i = 0; $i -lt $passthrough.Count; $i++) {
                if ($passthrough[$i] -eq '-AnswersFile') {
                    if ($passthrough[$i + 1] -ne $script:AnswersFileResolved) {
                        Fail "passthrough carries the wrong answers path: $($passthrough[$i + 1])"
                    }
                    $found = $true
                }
            }
            if (-not $found) { Fail 'Get-PassthroughArgs lost -AnswersFile (resume would go interactive)' }
            Write-Output "RESULT ${Mode}:${Case} ok forwarded=$($script:AnswersFileWsl)"
            exit 0
        }
        default { Fail "unknown handoff case '$Case'" }
    }
    Write-Output "RESULT ${Mode}:${Case} ok"
    exit 0
}

# --- Mode: blocked -----------------------------------------------------------

if ($Mode -eq 'blocked') {
    Reset-ScriptedWorld
    $tmpDir = New-TempDirectory
    $missing = Join-Path $tmpDir 'definitely-missing.yaml'

    switch ($Case) {
        'missing-and-conflict-collect-both' {
            $child = Invoke-GetPs1Child -ScriptArgs @(
                '-AutoInstallDeps', '-SkipWizard', '-AnswersFile', $missing
            )
            if ($child.ExitCode -ne 1) { Fail "expected exit 1, got $($child.ExitCode): $($child.Output)" }
            if ($child.Output -notlike '*answers file not found*') {
                Fail "missing-file problem not reported: $($child.Output)"
            }
            if ($child.Output -notlike '*-SkipWizard*never reads the answers file*') {
                Fail "conflict problem not reported alongside the missing file: $($child.Output)"
            }
            if ($child.Output -notlike '*Nothing was installed*') {
                Fail 'failure is missing the actionable footer'
            }
        }
        'directory' {
            $child = Invoke-GetPs1Child -ScriptArgs @('-AutoInstallDeps', '-AnswersFile', $tmpDir)
            if ($child.ExitCode -ne 1) { Fail "expected exit 1, got $($child.ExitCode): $($child.Output)" }
            if ($child.Output -notlike '*is not a file*') {
                Fail "directory problem not reported: $($child.Output)"
            }
        }
        'valid-file-conflict-only' {
            $answers = Write-TempAnswersFile -Directory $tmpDir
            $child = Invoke-GetPs1Child -ScriptArgs @('-AutoInstallDeps', '-SkipWizard', '-AnswersFile', $answers)
            if ($child.ExitCode -ne 1) { Fail "expected exit 1, got $($child.ExitCode): $($child.Output)" }
            if ($child.Output -notlike '*-SkipWizard*never reads the answers file*') {
                Fail "conflict not reported for a valid file: $($child.Output)"
            }
            if ($child.Output -like '*not found*' -or $child.Output -like '*is not a file*') {
                Fail "false-positive problems for a valid file: $($child.Output)"
            }
        }
        default { Fail "unknown blocked case '$Case'" }
    }
    Write-Output "RESULT ${Mode}:${Case} ok"
    exit 0
}

Fail "unknown mode '$Mode'"
