<#
.SYNOPSIS
    Safely install manifest-declared local model files outside this repository.
.DESCRIPTION
    The public Install-SodamModels function validates every manifest field before
    creating a target directory. Callers can inject a downloader for tests; the
    default HTTPS downloader is never invoked unless the function is called.
#>
[CmdletBinding()]
param(
    [string]$Profile,
    [string]$ModelHome,
    [string]$ManifestPath
)

Set-StrictMode -Version Latest
$script:RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script:DefaultManifestPath = Join-Path $script:RepositoryRoot 'models\manifest.json'

function Assert-ExactProperties {
    param(
        [Parameter(Mandatory)] [object]$Value,
        [Parameter(Mandatory)] [string[]]$Expected,
        [Parameter(Mandatory)] [string]$Label
    )

    if ($Value -isnot [pscustomobject]) {
        throw "$Label must be a JSON object."
    }
    $actual = @($Value.PSObject.Properties.Name)
    if ($actual.Count -ne $Expected.Count -or (Compare-Object $actual $Expected)) {
        throw "$Label must contain exactly: $($Expected -join ', ')."
    }
}

function Assert-SafeLeafFilename {
    param([Parameter(Mandatory)] [string]$Filename)

    if (
        -not $Filename -or
        $Filename -ne [System.IO.Path]::GetFileName($Filename) -or
        $Filename.StartsWith('.') -or
        $Filename.Contains('..') -or
        $Filename.Contains('/') -or
        $Filename.Contains('\')
    ) {
        throw 'Manifest filename must be a safe non-hidden leaf filename.'
    }
}

function Get-ManifestProfile {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$RequestedProfile
    )

    try {
        $manifestText = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
        $manifest = $manifestText | ConvertFrom-Json
    }
    catch {
        throw "Manifest could not be read as UTF-8 JSON: $($_.Exception.Message)"
    }

    Assert-ExactProperties -Value $manifest -Expected @('schema_version', 'profiles') -Label 'Manifest'
    if ($manifest.schema_version -ne '1') {
        throw 'Manifest schema_version must be the string 1.'
    }
    if ($manifest.profiles -isnot [System.Array]) {
        throw 'Manifest profiles must be an array.'
    }

    $seenProfiles = @{}
    $selected = $null
    foreach ($profile in @($manifest.profiles)) {
        Assert-ExactProperties -Value $profile -Expected @('name', 'files') -Label 'Manifest profile'
        if (
            $profile.name -isnot [string] -or
            -not $profile.name -or
            $profile.name -ne $profile.name.Trim() -or
            $seenProfiles.ContainsKey($profile.name)
        ) {
            throw 'Manifest profile names must be unique non-blank trimmed strings.'
        }
        $seenProfiles[$profile.name] = $true
        if ($profile.files -isnot [System.Array]) {
            throw 'Manifest profile files must be an array.'
        }
        foreach ($file in @($profile.files)) {
            Assert-ExactProperties -Value $file -Expected @('filename', 'url', 'sha256') -Label 'Manifest file'
            if ($file.filename -isnot [string]) {
                throw 'Manifest filename must be a string.'
            }
            Assert-SafeLeafFilename -Filename $file.filename
            if ($file.url -isnot [string]) {
                throw 'Manifest URL must be a string.'
            }
            $uri = $null
            if (-not [System.Uri]::TryCreate($file.url, [System.UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne 'https') {
                throw 'Manifest URL must be an absolute https URL.'
            }
            if ($file.sha256 -isnot [string] -or $file.sha256 -cnotmatch '^[0-9a-f]{64}$') {
                throw 'Manifest sha256 must be 64 lowercase hexadecimal characters.'
            }
        }
        if ($profile.name -eq $RequestedProfile) {
            $selected = $profile
        }
    }

    if ($null -eq $selected) {
        throw "Requested model profile was not found: $RequestedProfile"
    }
    if (@($selected.files).Count -eq 0) {
        throw "Requested model profile has no files: $RequestedProfile"
    }
    return $selected
}

function Install-SodamModels {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string]$Profile,
        [Parameter(Mandatory)] [string]$ModelHome,
        [string]$ManifestPath,
        [scriptblock]$DownloadFile
    )

    $ErrorActionPreference = 'Stop'
    if (-not $Profile -or $Profile -ne $Profile.Trim()) {
        throw 'Profile must be a non-blank trimmed string.'
    }
    if (-not [System.IO.Path]::IsPathRooted($ModelHome) -or $ModelHome -match '^[A-Za-z]:[^\\/]') {
        throw 'ModelHome must be an absolute path.'
    }

    try {
        $repositoryRoot = $script:RepositoryRoot
        $modelHomeFull = [System.IO.Path]::GetFullPath($ModelHome)
        if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
            $ManifestPath = $script:DefaultManifestPath
        }
        $manifestFull = [System.IO.Path]::GetFullPath($ManifestPath)
    }
    catch {
        throw "Path normalization failed: $($_.Exception.Message)"
    }

    $separator = [System.IO.Path]::DirectorySeparatorChar
    if (
        $modelHomeFull.Equals($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $modelHomeFull.StartsWith($repositoryRoot + $separator, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        throw 'ModelHome must be outside the repository root.'
    }
    if (-not (Test-Path -LiteralPath $manifestFull -PathType Leaf)) {
        throw "Manifest path does not exist: $manifestFull"
    }

    $selected = Get-ManifestProfile -Path $manifestFull -RequestedProfile $Profile
    $targets = @()
    $seenFilenames = @{}
    foreach ($file in @($selected.files)) {
        if ($seenFilenames.ContainsKey($file.filename)) {
            throw "Selected profile has duplicate filename: $($file.filename)"
        }
        $seenFilenames[$file.filename] = $true
        $target = [System.IO.Path]::GetFullPath((Join-Path $modelHomeFull $file.filename))
        if ([System.IO.Path]::GetDirectoryName($target) -ne $modelHomeFull) {
            throw 'Manifest filename resolved outside ModelHome.'
        }
        if (Test-Path -LiteralPath $target) {
            throw "Refusing to overwrite an existing model file: $target"
        }
        $targets += [pscustomobject]@{ File = $file; Target = $target }
    }

    if ($null -eq $DownloadFile) {
        $DownloadFile = {
            param([string]$Url, [string]$Destination)
            Invoke-WebRequest -Uri $Url -OutFile $Destination -ErrorAction Stop
        }
    }

    New-Item -ItemType Directory -Path $modelHomeFull -Force | Out-Null
    $installed = @()
    foreach ($targetSpec in $targets) {
        $temporary = Join-Path $modelHomeFull ('.' + $targetSpec.File.filename + '.' + [guid]::NewGuid().ToString('N') + '.partial')
        try {
            & $DownloadFile ([string]$targetSpec.File.url) $temporary
            if (-not (Test-Path -LiteralPath $temporary -PathType Leaf)) {
                throw "Downloader did not create a file: $temporary"
            }
            $sha256 = [System.Security.Cryptography.SHA256]::Create()
            try {
                $hashBytes = $sha256.ComputeHash([System.IO.File]::ReadAllBytes($temporary))
                $actualHash = ([System.BitConverter]::ToString($hashBytes) -replace '-', '').ToLowerInvariant()
            }
            finally {
                $sha256.Dispose()
            }
            if ($actualHash -cne $targetSpec.File.sha256) {
                throw "SHA-256 mismatch for $($targetSpec.File.filename)"
            }
            if (Test-Path -LiteralPath $targetSpec.Target) {
                throw "Refusing to overwrite an existing model file: $($targetSpec.Target)"
            }
            Move-Item -LiteralPath $temporary -Destination $targetSpec.Target -ErrorAction Stop
            $installed += $targetSpec.Target
        }
        catch {
            if (Test-Path -LiteralPath $temporary) {
                Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            }
            throw
        }
    }

    return [pscustomobject]@{
        profile = $selected.name
        model_home = $modelHomeFull
        installed_files = @($installed)
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $result = Install-SodamModels -Profile $Profile -ModelHome $ModelHome -ManifestPath $ManifestPath
    $result | ConvertTo-Json -Compress
}
