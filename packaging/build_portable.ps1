# Builds a portable Windows copy of the app in dist\VetClinic, zips it to dist\VetClinic.zip
# and, when Inno Setup is installed, wraps it into the installer dist\VetClinic-Setup.exe.
# The copy bundles the embeddable Python, uses SQLite and keeps all clinic data in VetClinic\data.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_portable.ps1

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repo = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $repo "dist"
$out = Join-Path $dist "VetClinic"
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"

# Match the venv's Python so the installed wheels are compatible.
$version = (& $venvPython -c "import platform; print(platform.python_version())").Trim()
$short = (& $venvPython -c "import sys; print(f'{sys.version_info[0]}{sys.version_info[1]}')").Trim()
Write-Host "Building with Python $version"

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force $out, "$out\python", "$out\app", "$out\data", "$out\.streamlit" | Out-Null

# 1. Embeddable Python (cached in dist\ between builds)
$embedZip = Join-Path $dist "python-$version-embed-amd64.zip"
if (-not (Test-Path $embedZip)) {
    Invoke-WebRequest -UseBasicParsing "https://www.python.org/ftp/python/$version/python-$version-embed-amd64.zip" -OutFile $embedZip
}
Expand-Archive $embedZip -DestinationPath "$out\python"
Set-Content -Encoding ascii "$out\python\python$short._pth" @"
python$short.zip
.
Lib\site-packages
import site
"@

# 2. Runtime packages (no test tools; no Postgres driver since the portable copy uses SQLite)
$reqs = Join-Path $dist "requirements-runtime.txt"
Get-Content (Join-Path $repo "requirements.txt") |
    Where-Object { $_ -notmatch '^\s*(pytest|psycopg2)' } |
    Set-Content -Encoding ascii $reqs
# Pin every sub-dependency to the version in the venv, i.e. the versions the app was tested with.
# Without this pip picks the newest releases (e.g. a newer starlette/uvicorn that logged ASGI errors).
$constraints = Join-Path $dist "constraints-runtime.txt"
& $venvPython -m pip freeze --exclude-editable --disable-pip-version-check |
    Where-Object { $_ -match '^[A-Za-z0-9_.\-]+==' } |
    Set-Content -Encoding ascii $constraints
& $venvPython -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: `
    --target "$out\python\Lib\site-packages" -r $reqs -c $constraints
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 3. App code, without local data and caches
foreach ($dir in "core", "ui", "models") {
    robocopy (Join-Path $repo "src\$dir") "$out\app\src\$dir" /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "copying src\$dir failed" }
}

# 4. Streamlit settings: only reachable from this computer, no telemetry, no developer menu
Set-Content -Encoding ascii "$out\.streamlit\config.toml" @"
[server]
address = "localhost"
port = 8501
headless = true
runOnSave = false
fileWatcherType = "none"
enableStaticServing = true

[browser]
gatherUsageStats = false

[client]
toolbarMode = "minimal"

"@
# Theme and bundled font from the repo's config (its [server] lines are already covered above)
Get-Content -Encoding utf8 (Join-Path $repo ".streamlit\config.toml") |
    Where-Object { $_ -notmatch '^\s*(\[server\]|enableStaticServing)' } |
    Add-Content -Encoding ascii "$out\.streamlit\config.toml"

# 5. Launcher
Set-Content -Encoding ascii "$out\Start VetClinic.bat" @"
@echo off
chcp 65001 >nul
title Vet Clinic Assistant
cd /d "%~dp0"
set "VETCLINIC_DATABASE_URL=sqlite:///data/vetclinic.db"
set "VETCLINIC_BACKUP_DIR=%~dp0data\backups"
if exist "clinic-name.txt" set /p VETCLINIC_NAME=<clinic-name.txt

echo Starting Vet Clinic Assistant... the browser will open in a few seconds.
echo Keep this window open while you use the app. Close it to stop the app.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for(`$i=0;`$i -lt 90;`$i++){try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501/_stcore/health -TimeoutSec 5 | Out-Null; Start-Process http://localhost:8501; break}catch{Start-Sleep 1}}"
python\python.exe -m streamlit run app\src\ui\app.py
pause
"@

Set-Content -Encoding utf8 "$out\README.txt" @"
Vet Clinic Assistant
====================

Start:  double-click "Start VetClinic.bat". Your browser opens the app.
        Keep the black window open while you work; close it to stop the app.

Data:   everything is stored in the "data" folder (database, attachments, backups).
        Download a backup from the Backup page regularly and keep it on another device.

Clinic name on receipts: create a file "clinic-name.txt" next to the launcher
        containing the name on one line.

Update: replace the "app" and "python" folders with the new version.
        Never replace or delete the "data" folder.
"@

# 6. Zip
$zip = Join-Path $dist "VetClinic.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Push-Location $dist
try { tar -a -c -f VetClinic.zip VetClinic } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "zip failed" }
Write-Host "Done: $zip ($([math]::Round((Get-Item $zip).Length / 1MB)) MB)"

# 7. Installer (needs Inno Setup 6: winget install JRSoftware.InnoSetup --scope user)
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q (Join-Path $PSScriptRoot "installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "installer build failed" }
    $setup = Join-Path $dist "VetClinic-Setup.exe"
    Write-Host "Done: $setup ($([math]::Round((Get-Item $setup).Length / 1MB)) MB)"
} else {
    Write-Host "Inno Setup not found; skipped VetClinic-Setup.exe"
}
