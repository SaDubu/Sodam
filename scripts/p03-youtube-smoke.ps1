param(
    [string]$Url = 'https://www.youtube.com/watch?v=KR3BMu3muSY'
)

$ErrorActionPreference = 'Stop'
$job = 'D:\AI-Legion\Sodam-data\tmp\jobs\p03-youtube-smoke'
$runtime = 'D:\AI-Legion\Sodam-runtime\Scripts\python.exe'
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$env:Path = "$machinePath;$userPath"
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

New-Item -ItemType Directory -Force -Path $job | Out-Null
$source = Get-ChildItem -LiteralPath $job -File -Filter 'source.*' |
    Select-Object -First 1
if ($null -eq $source) {
    & $runtime -m yt_dlp -f 'bestaudio/best' -o "$job\source.%(ext)s" $Url
    if ($LASTEXITCODE -ne 0) {
        throw "yt-dlp failed with exit code $LASTEXITCODE"
    }
    $source = Get-ChildItem -LiteralPath $job -File -Filter 'source.*' |
        Select-Object -First 1
}
if ($null -eq $source) {
    throw 'No source media was available for the P03 smoke test.'
}

& $runtime -B tools/run_local.py $source.FullName --mode smoke
exit $LASTEXITCODE
