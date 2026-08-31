<#
.SYNOPSIS
    Read-only policy inspection for Git-tracked Sodam repository files.
.DESCRIPTION
    Reports policy violations without changing files, the Git index, or the
    working tree. Tests can inject the list of Git paths instead of invoking Git.
#>
[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [long]$MaxFileBytes = 10MB
)

Set-StrictMode -Version Latest
$script:DefaultRepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script:ProhibitedExtensions = @(
    '.gguf', '.safetensors', '.ckpt', '.onnx', '.pt', '.pth', '.bin',
    '.mp4', '.mkv', '.mov', '.webm', '.mp3', '.wav', '.m4a', '.aac',
    '.flac', '.ogg', '.sqlite', '.db', '.parquet'
)
$script:SecretPatterns = @(
    '(?i)-----BEGIN\s+(?:[A-Z ]+\s+)?PRIVATE KEY-----',
    '(?i)\bsk-[A-Za-z0-9]{20,}\b',
    '(?im)\bapi[_-]?key\b\s*[:=]\s*["'']?[^\s"'']{8,}',
    '(?im)\bpassword\b\s*[:=]\s*["'']?[^\s"'']{8,}',
    '\bAKIA[0-9A-Z]{16}\b'
)

function Get-DefaultGitPaths {
    param([Parameter(Mandatory)] [string]$RepositoryRoot)

    $tracked = @(& git -C $RepositoryRoot ls-files)
    if ($LASTEXITCODE -ne 0) {
        throw 'git ls-files failed.'
    }
    $staged = @(& git -C $RepositoryRoot diff --cached --name-only)
    if ($LASTEXITCODE -ne 0) {
        throw 'git diff --cached --name-only failed.'
    }
    return @($tracked + $staged)
}

function Add-RepositoryViolation {
    param(
        [Parameter(Mandatory)] [AllowEmptyCollection()] [System.Collections.ArrayList]$Violations,
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Reason
    )

    [void]$Violations.Add([pscustomobject]@{ path = $Path; reason = $Reason })
}

function Test-SodamRepositoryClean {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string]$RepositoryRoot,
        [long]$MaxFileBytes = 10MB,
        [scriptblock]$GitPathProvider
    )

    $ErrorActionPreference = 'Stop'
    if ($MaxFileBytes -le 0) {
        throw 'MaxFileBytes must be a positive integer.'
    }
    try {
        $root = [System.IO.Path]::GetFullPath($RepositoryRoot)
    }
    catch {
        throw "RepositoryRoot could not be normalized: $($_.Exception.Message)"
    }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw 'RepositoryRoot must be an existing directory.'
    }

    if ($null -eq $GitPathProvider) {
        $GitPathProvider = ${function:Get-DefaultGitPaths}
    }
    if ($GitPathProvider -isnot [scriptblock]) {
        throw 'GitPathProvider must be a scriptblock or null.'
    }

    $provided = @(& $GitPathProvider $root)
    $paths = @(
        $provided |
            Where-Object { $_ -is [string] -and $_ } |
            ForEach-Object { [string]$_ } |
            Sort-Object -Unique
    )
    $violations = [System.Collections.ArrayList]::new()
    $rootPrefix = $root + [System.IO.Path]::DirectorySeparatorChar

    foreach ($relativePath in $paths) {
        if ([System.IO.Path]::IsPathRooted($relativePath) -or $relativePath -match '(^|[\\/])\.\.([\\/]|$)') {
            Add-RepositoryViolation -Violations $violations -Path $relativePath -Reason 'unsafe_path'
            continue
        }
        try {
            $fullPath = [System.IO.Path]::GetFullPath((Join-Path $root $relativePath))
        }
        catch {
            Add-RepositoryViolation -Violations $violations -Path $relativePath -Reason 'unsafe_path'
            continue
        }
        if (-not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            Add-RepositoryViolation -Violations $violations -Path $relativePath -Reason 'unsafe_path'
            continue
        }
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            Add-RepositoryViolation -Violations $violations -Path $relativePath -Reason 'missing_regular_file'
            continue
        }

        $normalized = $relativePath.Replace('\\', '/').ToLowerInvariant()
        $extension = [System.IO.Path]::GetExtension($fullPath).ToLowerInvariant()
        if ($normalized.StartsWith('models/') -and $normalized -ne 'models/manifest.json') {
            Add-RepositoryViolation -Violations $violations -Path $relativePath -Reason 'unexpected_models_path'
        }
        if ($script:ProhibitedExtensions -contains $extension) {
            Add-RepositoryViolation -Violations $violations -Path $relativePath -Reason ('prohibited_extension:' + $extension)
        }

        $length = (Get-Item -LiteralPath $fullPath).Length
        if ($length -gt $MaxFileBytes) {
            Add-RepositoryViolation -Violations $violations -Path $relativePath -Reason 'file_exceeds_size_limit'
        }
        if (($script:ProhibitedExtensions -contains $extension)) {
            continue
        }

        try {
            $utf8 = [System.Text.UTF8Encoding]::new($false, $true)
            $content = [System.IO.File]::ReadAllText($fullPath, $utf8)
        }
        catch {
            continue
        }
        foreach ($pattern in $script:SecretPatterns) {
            if ([System.Text.RegularExpressions.Regex]::IsMatch($content, $pattern)) {
                Add-RepositoryViolation -Violations $violations -Path $relativePath -Reason 'secret_pattern'
                break
            }
        }
    }

    return [pscustomobject]@{
        is_clean = ($violations.Count -eq 0)
        checked_files = $paths.Count
        violations = @($violations)
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
        $RepositoryRoot = $script:DefaultRepositoryRoot
    }
    $report = Test-SodamRepositoryClean -RepositoryRoot $RepositoryRoot -MaxFileBytes $MaxFileBytes
    $report | ConvertTo-Json -Compress -Depth 3
    if (-not $report.is_clean) {
        exit 1
    }
}
