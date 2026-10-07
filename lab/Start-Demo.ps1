param([string]$Python = '', [string]$Executable = '')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
if (!$Python) {
    $Python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (!(Test-Path -LiteralPath $Python)) { $Python = Join-Path $projectRoot '..\..\work\sergek-venv\Scripts\python.exe' }
}
if (!(Test-Path -LiteralPath $Python)) { throw 'Run scripts\Setup-Dev.ps1 first.' }
if (!$Executable) { $Executable = Join-Path $projectRoot 'release-v1.4.3\win-unpacked\Sergek Proctor.exe' }
if (!(Test-Path -LiteralPath $Executable)) { $Executable = Join-Path $env:LOCALAPPDATA 'Programs\Sergek Proctor\Sergek Proctor.exe' }
if (!(Test-Path -LiteralPath $Executable)) { throw 'Install Sergек 1.4.3 or build the Windows package first.' }
# Standard UAC authorizes Windows protection; student sees no teacher password.
# The student application is interactive. SW_HIDE suppresses Electron's first
# window even after BrowserWindow.show(); only lab helpers run hidden.
& $Python lab\launcher.py --python $Python --executable $Executable
if ($LASTEXITCODE) { throw 'Independent local demo startup failed. Inspect the launcher log.' }
