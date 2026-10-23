# Exercise real command builders without launching processes or writing registry.
param([Parameter(Mandatory = $true)][string]$GetPs1)
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($GetPs1, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw 'get.ps1 failed to parse' }
foreach ($name in @('Invoke-Elevated', 'Register-Resume')) {
    $functions = @($ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true))
    if ($functions.Count -ne 1) { throw "Expected one production function: $name" }
    . ([scriptblock]::Create($functions[0].Extent.Text))
}

function Save-StableCopy { return 'C:\Test User\maistro\get.ps1' }
function Get-PassthroughArgs {
    param([switch]$IncludeResume)
    $result = @('-Version', 'v1.0.0', '-AnswersFile', 'C:\Test User\answers.yaml')
    if ($IncludeResume) { $result += '-Resume' }
    return $result
}
function Write-InfoMsg { param([string]$Message) }
function Start-Process {
    param([string]$FilePath, [string[]]$ArgumentList, [string]$Verb)
    $script:Launch = @{ FilePath = $FilePath; Arguments = $ArgumentList; Verb = $Verb }
}
function New-Item {
    param([string]$Path, [switch]$Force)
    $script:CreatedPath = $Path
}
function New-ItemProperty {
    param([string]$Path, [string]$Name, [string]$Value, [string]$PropertyType, [switch]$Force)
    $script:ResumeEntry = @{ Path = $Path; Name = $Name; Value = $Value; Type = $PropertyType }
}

Invoke-Elevated
if ($script:Launch.FilePath -ne 'powershell.exe' -or $script:Launch.Verb -ne 'RunAs') {
    throw 'Elevation target or verb changed'
}
$expected = '-NoProfile -File "C:\Test User\maistro\get.ps1" -Version v1.0.0 -AnswersFile "C:\Test User\answers.yaml"'
if (($script:Launch.Arguments -join ' ') -cne $expected) { throw 'Unexpected elevation arguments' }

Register-Resume -ScriptPath 'C:\Test User\maistro\get.ps1'
$runOnce = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
if ($script:CreatedPath -ne $runOnce -or $script:ResumeEntry.Path -ne $runOnce) {
    throw 'Resume registry destination changed'
}
if ($script:ResumeEntry.Name -ne 'MaistroInstallResume' -or $script:ResumeEntry.Type -ne 'String') {
    throw 'Resume registry entry contract changed'
}
if ($script:ResumeEntry.Value -cne ('powershell.exe ' + $expected + ' -Resume')) {
    throw 'Unexpected resume arguments'
}
Write-Output 'RESULT relaunch-policy ok'
