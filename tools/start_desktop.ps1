<#
.SYNOPSIS
    Start Sodam for personal use without an installer.

.DESCRIPTION
    Validates local runtime paths, confirms that the requested Ollama model is
    installed, and starts the desktop child with temporary SODAM environment
    variables. It never downloads, installs, or removes software or models.
#>

[CmdletBinding(SupportsShouldProcess)]
[OutputType([System.Diagnostics.Process])]
param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory)]
    [string]$PythonPath,
    [Parameter(Mandatory)]
    [string]$FfmpegPath,
    [Parameter(Mandatory)]
    [string]$SttModelPath,
    [string]$DesktopExecutable,
    [string]$OllamaExecutable,
    [string]$QwenModel = "qwen3.6:35b-a3b-agent-64k"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail-Input {
    param([Parameter(Mandatory)][string]$Action)
    throw "SODAM_LAUNCHER_INPUT: $Action"
}

function Fail-Runtime {
    param([Parameter(Mandatory)][string]$Action)
    throw "SODAM_LAUNCHER_RUNTIME: $Action"
}

function Resolve-ExistingFile {
    param(
        [Parameter(Mandatory)][string]$Value,
        [Parameter(Mandatory)][string]$Action
    )
    if ([string]::IsNullOrWhiteSpace($Value) -or -not (Test-Path -LiteralPath $Value -PathType Leaf)) {
        Fail-Input $Action
    }
    return [System.IO.Path]::GetFullPath($Value)
}

function Resolve-ExistingDirectory {
    param(
        [Parameter(Mandatory)][string]$Value,
        [Parameter(Mandatory)][string]$Action
    )
    if ([string]::IsNullOrWhiteSpace($Value) -or -not (Test-Path -LiteralPath $Value -PathType Container)) {
        Fail-Input $Action
    }
    return [System.IO.Path]::GetFullPath($Value)
}

function Test-ChildPath {
    param(
        [Parameter(Mandatory)][string]$Parent,
        [Parameter(Mandatory)][string]$Child
    )
    $parentPrefix = $Parent.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $parentPrefix = $parentPrefix + [System.IO.Path]::DirectorySeparatorChar
    return $Child.StartsWith($parentPrefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Resolve-OllamaExecutable {
    param([string]$Value)
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return Resolve-ExistingFile $Value "Ollama 실행 파일을 확인하세요."
    }
    $command = Get-Command ollama -CommandType Application -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        Fail-Runtime "Ollama를 설치하거나 -OllamaExecutable 경로를 지정하세요."
    }
    return $command.Path
}

function Confirm-OllamaModel {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$Model
    )
    if ([string]::IsNullOrWhiteSpace($Model)) {
        Fail-Input "Qwen 모델 tag를 지정하세요."
    }
    $listOutput = & $Executable list 2>$null
    if ($LASTEXITCODE -ne 0) {
        Fail-Runtime "Ollama 실행 상태를 확인하세요."
    }
    $match = [regex]::Escape($Model)
    if (-not (($listOutput -join [Environment]::NewLine) -match ("(?m)^" + $match + "\s"))) {
        Fail-Runtime ("Ollama 모델이 없습니다. 다음 명령을 실행하세요: ollama pull " + $Model)
    }
}

$resolvedRepositoryRoot = Resolve-ExistingDirectory $RepositoryRoot "Sodam repository 또는 portable root를 확인하세요."
$runnerPath = Join-Path $resolvedRepositoryRoot "tools/run_local.py"
$backendPath = Join-Path $resolvedRepositoryRoot "backend"
if (-not (Test-Path -LiteralPath $runnerPath -PathType Leaf) -or -not (Test-Path -LiteralPath $backendPath -PathType Container)) {
    Fail-Input "backend resource가 완전한 Sodam root를 지정하세요."
}

$resolvedPythonPath = Resolve-ExistingFile $PythonPath "Python 실행 파일 경로를 지정하세요."
$resolvedFfmpegPath = Resolve-ExistingFile $FfmpegPath "FFmpeg 실행 파일 경로를 지정하세요."
$resolvedSttModelPath = Resolve-ExistingDirectory $SttModelPath "faster-whisper 모델 경로를 지정하세요."
if ([string]::IsNullOrWhiteSpace($DesktopExecutable)) {
    $DesktopExecutable = Join-Path $resolvedRepositoryRoot "apps/desktop/src-tauri/target/debug/sodam-desktop.exe"
}
$resolvedDesktopExecutable = Resolve-ExistingFile $DesktopExecutable "Sodam desktop 실행 파일을 확인하세요."
if (-not (Test-ChildPath $resolvedRepositoryRoot $resolvedDesktopExecutable)) {
    Fail-Input "desktop 실행 파일은 Sodam root 하위에 있어야 합니다."
}

$resolvedOllamaExecutable = Resolve-OllamaExecutable $OllamaExecutable
Confirm-OllamaModel $resolvedOllamaExecutable $QwenModel

$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $resolvedDesktopExecutable
$startInfo.WorkingDirectory = $resolvedRepositoryRoot
$startInfo.UseShellExecute = $false
$startInfo.Environment["SODAM_REPOSITORY_ROOT"] = $resolvedRepositoryRoot
$startInfo.Environment["SODAM_PYTHON"] = $resolvedPythonPath
$startInfo.Environment["SODAM_FFMPEG"] = $resolvedFfmpegPath
$startInfo.Environment["SODAM_MODEL_PATH"] = $resolvedSttModelPath

if (-not $PSCmdlet.ShouldProcess("Sodam desktop", "Start")) {
    Write-Output "Sodam desktop launch validated."
    return
}

try {
    $process = [System.Diagnostics.Process]::Start($startInfo)
} catch {
    Fail-Runtime "Sodam desktop를 시작할 수 없습니다."
}
if ($null -eq $process) {
    Fail-Runtime "Sodam desktop를 시작할 수 없습니다."
}
Write-Output ("Sodam desktop started. PID=" + $process.Id)
return $process
