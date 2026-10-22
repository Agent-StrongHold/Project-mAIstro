# Windows E2E runner for get.ps1's WSL distro detection (#354).
#
# Runs every parser fixture and install/reboot scenario from
# wsl_detection_harness.ps1 under the requested PowerShell interpreter
# (powershell.exe = Windows PowerShell 5.1, pwsh = PowerShell 7+), so the
# detection layer is exercised on a real Windows host with both shipping
# interpreters. wsl.exe itself is scripted at the process boundary: a real
# WSL2 install is not hermetic on hosted runners. Exits nonzero if any case
# fails; intended for the windows-detection-e2e job in
# .github/workflows/release-installer.yml.
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
$fixtureDir = Join-Path (Join-Path $testsDir 'fixtures') 'wsl-list'
$harness = Join-Path $PSScriptRoot 'wsl_detection_harness.ps1'
$getPs1 = Join-Path $repoRoot 'get.ps1'

$cases = @()
Get-ChildItem -LiteralPath $fixtureDir -Filter '*.txt' |
    Sort-Object Name |
    ForEach-Object { $cases += , @('parser', $_.BaseName) }

$listing = & $PowerShell -NoProfile -NonInteractive -File $harness -Mode List -GetPs1 $getPs1 -Fixtures $fixtureDir
if ($LASTEXITCODE -ne 0) { throw "harness -Mode List failed under $PowerShell" }
foreach ($line in $listing) {
    if ($line -like 'scenario:*') {
        $cases += , @('scenario', $line.Substring('scenario:'.Length))
    }
}
if ($cases.Count -eq 0) { throw 'no cases enumerated; fixtures or harness missing?' }

$failed = 0
foreach ($case in $cases) {
    & $PowerShell -NoProfile -NonInteractive -File $harness -Mode $case[0] -Case $case[1] -GetPs1 $getPs1 -Fixtures $fixtureDir
    if ($LASTEXITCODE -ne 0) {
        $failed += 1
        Write-Host "FAIL $($case[0])/$($case[1])"
    } else {
        Write-Host "PASS $($case[0])/$($case[1])"
    }
}

if ($failed -gt 0) { throw "$failed of $($cases.Count) case(s) failed under $PowerShell" }
Write-Host "windows detection e2e ($PowerShell): all $($cases.Count) cases passed"
