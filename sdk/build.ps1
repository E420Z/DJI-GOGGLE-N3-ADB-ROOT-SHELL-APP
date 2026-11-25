# Build an N3 SDK app .so (aarch64, freestanding, no imports).
# Usage:
#   powershell -ExecutionPolicy Bypass -File build.ps1
#   powershell -ExecutionPolicy Bypass -File build.ps1 -Src ..\mods\n3menu\mod.c -Out dist\n3menu.so
param(
    [string]$Src = "template\mod.c",
    [string]$Out = "dist\n3hello.so"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$natartos = Join-Path $here "include"
if (-not (Test-Path $natartos)) {
    $natartos = Join-Path (Split-Path -Parent (Split-Path -Parent $here)) "natartos-src\include"
}

$zig = $env:ZIG
if (-not $zig) {
    $cmd = Get-Command zig -ErrorAction SilentlyContinue
    if ($cmd) { $zig = $cmd.Source }
}
if (-not $zig) {
    $cand = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\Lib\site-packages\ziglang\zig.exe"
    if (Test-Path $cand) { $zig = $cand }
}
if (-not $zig -or -not (Test-Path $zig)) { throw "zig not found (set ZIG=... or install ziglang)" }
if (-not (Test-Path $natartos)) { throw "natartos include not found: $natartos" }

$srcPath = if ([System.IO.Path]::IsPathRooted($Src)) { $Src } else { Join-Path $here $Src }
$outPath = if ([System.IO.Path]::IsPathRooted($Out)) { $Out } else { Join-Path $here $Out }
$outDir = Split-Path -Parent $outPath
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

Write-Host "cc $srcPath -> $outPath"
& $zig cc -target aarch64-linux-gnu -shared -fPIC -nostdlib `
    -fno-builtin -fno-stack-protector -fno-omit-frame-pointer -O2 `
    -I $here -I $natartos `
    "-Wl,-soname,$(Split-Path -Leaf $outPath)" `
    -o $outPath $srcPath (Join-Path $here "n3app.c")

if ($LASTEXITCODE -ne 0) { throw "build failed ($LASTEXITCODE)" }
Write-Host ("ok: {0} bytes" -f (Get-Item $outPath).Length)
