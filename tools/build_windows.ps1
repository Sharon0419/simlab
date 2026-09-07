$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Run python -m venv .venv and install requirements-dev.txt first.'
}
$releaseVersion = & $pythonExe -c 'from simlab import __version__; print(__version__)'
if ($releaseVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid release version.' }
$releaseRoot = Join-Path $projectRoot 'dist'
$bundleFolder = Join-Path $releaseRoot 'SimLab'
$targetExe = Join-Path $bundleFolder 'SimLab.exe'
$running = Get-Process SimLab -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $targetExe }
if ($running) { throw 'Close the running SimLab window before rebuilding this folder.' }
& $pythonExe -m PyInstaller --noconfirm --windowed --onedir --distpath $releaseRoot --name SimLab --add-data 'simlab/data;simlab/data' --exclude-module tkinter --exclude-module matplotlib main.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
# Python 3.10 can contribute an older VC runtime at the bundle root. Qt 6.11
# ships a newer compatible runtime; use that same version before Python loads.
$qtRuntime = Join-Path $projectRoot '.venv\Lib\site-packages\PySide6'
$bundleRuntime = Join-Path $bundleFolder '_internal'
foreach ($runtimeName in @('VCRUNTIME140.dll', 'VCRUNTIME140_1.dll')) {
    $runtimeSource = Join-Path $qtRuntime $runtimeName
    if (Test-Path -LiteralPath $runtimeSource) {
        Copy-Item -LiteralPath $runtimeSource -Destination (Join-Path $bundleRuntime $runtimeName) -Force
    }
}
# Qt expects Windows' unversioned ICU exports. PyInstaller may discover an
# unrelated ICU 78 on PATH whose exports carry version suffixes. Use the OS ICU.
foreach ($icuName in @('icuuc.dll', 'icuin.dll', 'icudt78.dll')) {
    $icuPath = Join-Path $bundleRuntime $icuName
    if (Test-Path -LiteralPath $icuPath) { Remove-Item -LiteralPath $icuPath }
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'README.md') -Destination (Join-Path $bundleFolder 'README.md') -Force
& $pythonExe tools\make_demo.py (Join-Path $bundleFolder 'examples')
if ($LASTEXITCODE -ne 0) { throw 'Example generation failed.' }
Write-Output "Built $bundleFolder\SimLab.exe"
