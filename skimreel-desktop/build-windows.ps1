$ErrorActionPreference = "Stop"
$desktopDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $desktopDir
$helperSource = Join-Path $rootDir "local-helper\skimreel_helper.py"
$deno = (Get-Command deno -ErrorAction Stop).Source
$helperDir = Join-Path $desktopDir "build\helper"
$toolsDir = Join-Path $desktopDir "build\tools"

New-Item -ItemType Directory -Force -Path $helperDir, $toolsDir | Out-Null
py -3.9 -m PyInstaller --onefile --name SkimReelYouTube --collect-all yt_dlp --distpath $helperDir --workpath (Join-Path $desktopDir "build\pyinstaller") --specpath (Join-Path $desktopDir "build") $helperSource
if ($LASTEXITCODE -ne 0) { throw "Could not package the existing YouTube helper." }
Copy-Item -LiteralPath $deno -Destination (Join-Path $toolsDir "deno.exe") -Force
$ytdlp = Join-Path $toolsDir "yt-dlp.exe"
Invoke-WebRequest -Uri "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" -OutFile $ytdlp
if (-not (Test-Path -LiteralPath $ytdlp)) { throw "Could not download the current official yt-dlp executable." }
Write-Output "Bundled YouTube helper, Deno, and yt-dlp into $desktopDir\build."
