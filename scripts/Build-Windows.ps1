param([string]$Python = '', [string]$Dotnet = 'dotnet', [switch]$Installer)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
if (!$Python) { $Python = Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (!(Test-Path -LiteralPath $Python)) { throw 'Run Setup-Dev.ps1 first or supply -Python.' }
& $Python scripts\download_models.py
if ($LASTEXITCODE) { throw 'Model verification failed' }
& $Dotnet publish guard\Sergek.Guard.csproj -c Release -r win-x64 --self-contained true -o build\guard
if ($LASTEXITCODE) { throw 'Guard build failed' }
& '.\build\guard\Sergek.Guard.exe' --self-test
if ($LASTEXITCODE) { throw 'Guard rule test failed' }
& '.\build\guard\Sergek.Guard.exe' --self-test-windows
if ($LASTEXITCODE) { throw 'Window classification regression failed' }
& $Python -m PyInstaller --noconfirm --name sergek-backend --distpath build\backend-dist --workpath build\pyinstaller --specpath build --paths . --collect-all mediapipe --collect-all onnxruntime --collect-all cv2 --collect-all sounddevice --collect-all _sounddevice_data --hidden-import win32crypt backend\run.py
if ($LASTEXITCODE) { throw 'Backend build failed' }
# Only copy generated contents into this project's verified build directory.
$backendTarget = Join-Path $projectRoot 'build\backend'
New-Item -ItemType Directory -Path $backendTarget -Force | Out-Null
Copy-Item -Path '.\build\backend-dist\sergek-backend\*' -Destination $backendTarget -Recurse -Force
& npm.cmd run build
if ($LASTEXITCODE) { throw 'UI build failed' }
if ($Installer) { & npm.cmd run installer } else { & npm.cmd run package }
if ($LASTEXITCODE) { throw 'Windows packaging failed' }
