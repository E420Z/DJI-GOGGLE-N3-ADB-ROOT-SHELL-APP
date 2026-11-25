# Launch the N3 ROOT app on Windows.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 app\main.py
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python app\main.py
} else {
    throw "Python 3.12 not found. Install it from python.org."
}
