# Windows E2E runner for get.ps1's unattended answers-file support (#409).
#
# Runs every unit, handoff, and blocked case from answers_parity_harness.ps1
# under the requested PowerShell interpreter (powershell.exe = Windows
# PowerShell 5.1, pwsh = PowerShell 7+), so the answers contract is exercised
# on a real Windows host with both shipping interpreters. wsl.exe, the GitHub
# API, and reboot are scripted at the process boundary; the preflight exit-1
# paths run the real get.ps1 in a child process and never reach wsl.exe or
# the network. Exits nonzero if any case fails; intended for the
# windows-detection-e2e job in .github/workflows/release-installer.yml.
#
# ASCII-only on purpose: it must parse identically under Windows PowerShell
# 5.1 with or without a BOM.
param(
    [ValidateSet('powershell.exe', 'pwsh')]
    [string]$PowerShell = 'pwsh'
)

$ErrorActionPreference = 'Stop'

$testsDir = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $testsDir
$harness = Join-Path $PSScriptRoot 'answers_parity_harness.ps1'
$getPs1 = Join-Path $repoRoot 'get.ps1'

$cases = @()
$listing = & $PowerShell -NoProfile -NonInteractive -File $harness -Mode List -GetPs1 $getPs1
if ($LASTEXITCODE -ne 0) { throw "harness -Mode List failed under $PowerShell" }
foreach ($line in $listing) {
    $sep = $line.IndexOf(':')
    if ($sep -lt 1) { throw "unexpected harness listing line: $line" }
    $cases += , @($line.Substring(0, $sep), $line.Substring($sep + 1))
}
if ($cases.Count -eq 0) { throw 'no cases enumerated; harness missing?' }

$failed = 0
foreach ($case in $cases) {
    & $PowerShell -NoProfile -NonInteractive -File $harness -Mode $case[0] -Case $case[1] -GetPs1 $getPs1
    if ($LASTEXITCODE -ne 0) {
        $failed += 1
        Write-Host "FAIL $($case[0])/$($case[1])"
    } else {
        Write-Host "PASS $($case[0])/$($case[1])"
    }
}

if ($failed -gt 0) { throw "$failed of $($cases.Count) case(s) failed under $PowerShell" }
Write-Host "answers parity e2e ($PowerShell): all $($cases.Count) cases passed"
