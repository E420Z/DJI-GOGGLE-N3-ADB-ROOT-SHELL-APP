param(
    [string]$Page = "",
    [string]$Out = "",
    [int]$Width = 1360,
    [int]$Height = 880
)

# Headless Edge screenshot of the static web UI (the same Chromium engine
# WebView2 uses). Mock mode is forced so the page renders without the Python
# host. Usage:
#   powershell -File app/tools/ui_shot.ps1 -Page connection -Out shot.png
$ErrorActionPreference = "Continue"

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Out) { $Out = Join-Path $root "app\state\web_shot.png" }
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edge)) { throw "Edge not found at $edge" }

$index = Join-Path $root "app\web\index.html"
if (-not (Test-Path $index)) { throw "missing UI: $index" }

$url = "file:///" + ($index -replace '\\', '/' -replace ' ', '%20') + "?mock=1"
if ($Page) { $url += "&page=$Page" }

$profile = Join-Path $env:TEMP ("n3shot-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
Remove-Item $Out -Force -ErrorAction SilentlyContinue

# Edge writes its progress line to stderr, so ignore the exit code and check
# for the output file instead.
& $edge --headless=new --disable-gpu --hide-scrollbars --no-first-run `
    --user-data-dir="$profile" `
    --window-size="$Width,$Height" --virtual-time-budget=4000 `
    --allow-file-access-from-files --screenshot="$Out" $url 2>$null | Out-Null

if (-not (Test-Path $Out)) { throw "screenshot failed: $Out" }
Remove-Item $profile -Recurse -Force -ErrorAction SilentlyContinue
"$Out  $((Get-Item $Out).Length) bytes  ${Width}x${Height}  page=$Page"
