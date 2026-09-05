<#!
.SYNOPSIS
    Start the non-installed Sodam Tk UI.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$PythonPath = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
    [string]$HermesCommand,
    [string]$HermesPython,
    [string]$HermesRoot,
    [string]$HermesVersion = '0.19.0',
    [string]$ResultRoot = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $repositoryRoot 'tools\simple_gui.py'

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "SODAM_GUI_INPUT: Python 실행 파일을 확인하세요: $PythonPath"
}
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "SODAM_GUI_INPUT: UI 파일을 확인하세요: $scriptPath"
}

$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$cliArgs = @('-B', $scriptPath, '--python-path', $PythonPath, '--hermes-version', $HermesVersion)
if ($ResultRoot) { $cliArgs += @('--result-root', $ResultRoot) }
if ($HermesCommand) { $cliArgs += @('--hermes-command', $HermesCommand) }
if ($HermesPython) { $cliArgs += @('--hermes-python', $HermesPython) }
if ($HermesRoot) { $cliArgs += @('--hermes-root', $HermesRoot) }

if ($PSCmdlet.ShouldProcess($scriptPath, 'Start Sodam simple GUI')) {
    Push-Location $repositoryRoot
    try {
        & $PythonPath @cliArgs
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
