param([string]$Python = 'python', [switch]$SkipGuard)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $Python -m venv .venv
    if ($LASTEXITCODE) { throw 'Python 3.12 x64 is required' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r backend\requirements-build.lock.txt
if ($LASTEXITCODE) { throw 'Python dependencies failed' }
& npm.cmd ci
if ($LASTEXITCODE) { throw 'Node dependencies failed' }
& '.\.venv\Scripts\python.exe' scripts\download_models.py
if ($LASTEXITCODE) { throw 'Model validation failed' }
& npm.cmd run build
if ($LASTEXITCODE) { throw 'UI build failed' }
if (!$SkipGuard) {
    & dotnet publish guard\Sergek.Guard.csproj -c Release -r win-x64 --self-contained true -o build\guard
    if ($LASTEXITCODE) { throw '.NET 8 SDK is required for the guard' }
}
Write-Host 'Ready: npm.cmd run desktop'
