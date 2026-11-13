param([switch]$WithOCR, [string]$PythonExe)
$ErrorActionPreference = 'Stop'
$skillRoot = Split-Path $PSScriptRoot -Parent
if (-not $PythonExe) {
    $PythonExe = & py -3.12 -c 'import sys; print(sys.executable)' 2>$null
    if ($LASTEXITCODE -ne 0) { $PythonExe = & py -3.11 -c 'import sys; print(sys.executable)' 2>$null }
}
if (-not $PythonExe) { throw 'Install Python 3.11 or 3.12, or pass -PythonExe with its full path.' }
& $PythonExe -c 'import sys; assert (3,11) <= sys.version_info[:2] <= (3,12), "Python 3.11/3.12 required"'
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python version' }
$envDir = Join-Path $skillRoot '.venv'
& $PythonExe -m venv $envDir
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
$venvPython = Join-Path $envDir 'Scripts/python.exe'
$requirements = Join-Path $skillRoot 'requirements.txt'
if ($WithOCR) { $requirements = Join-Path $skillRoot 'requirements-ocr.txt' }
& $venvPython -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; no success state recorded' }
& $venvPython (Join-Path $PSScriptRoot 'review.py') --help
if ($LASTEXITCODE -ne 0) { throw 'CLI smoke check failed' }
Write-Output ('WorkBuddy Python: ' + $venvPython)
