param(
    [string]$Source = 'D:\AI-Legion\Sodam-data\tmp\jobs\p06-local-source\source.f251.webm'
)

$ErrorActionPreference = 'Stop'
$repository = 'D:\AI-Legion\Sodam'
$runtime = 'D:\AI-Legion\Sodam-runtime\Scripts\python.exe'
$ffmpegBin = 'C:\Users\sow20\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin'
$env:Path = "$ffmpegBin;$env:Path"
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
& $runtime -B "$repository\scripts\p06-export-whisper-transcript.py" $Source
exit $LASTEXITCODE
