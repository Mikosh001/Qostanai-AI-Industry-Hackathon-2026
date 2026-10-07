param([string]$Python = '', [switch]$Stop)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
if (!$Python) {
    $Python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (!(Test-Path -LiteralPath $Python)) { $Python = Join-Path $projectRoot '..\..\work\sergek-venv\Scripts\python.exe' }
}
if (!(Test-Path -LiteralPath $Python)) { throw 'Run scripts\Setup-Dev.ps1 or supply -Python.' }
if ($Stop) { & $Python lab\start.py --stop } else { & $Python lab\start.py }
if ($LASTEXITCODE) { throw 'Inspect the local lab logs.' }
