# Launch the N3 ROOT app on Windows.
#
# Prefers the pywebview UI (app/webapp.py). If pywebview is missing or the web
# front-end is not present, falls back to the classic Tk app (app/main.py).
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$python = $null
foreach ($cand in @("py", "python", "python3")) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) { $python = $cand; break }
}
if (-not $python) {
    throw "Python 3.12 not found. Install it from python.org."
}

$launch = { param($script)
    if ($python -eq "py") { & py -3.12 $script } else { & $python $script }
}

$hasWebview = $false
try {
    if ($python -eq "py") {
        & py -3.12 -c "import webview" 2>$null
    } else {
        & $python -c "import webview" 2>$null
    }
    $hasWebview = ($LASTEXITCODE -eq 0)
} catch { $hasWebview = $false }

if ($hasWebview -and (Test-Path "app\web\index.html")) {
    & $launch "app\webapp.py"
    if ($LASTEXITCODE -eq 0) { exit 0 }
    Write-Host "web UI failed, falling back to the classic app..." -ForegroundColor Yellow
}

& $launch "app\main.py"
