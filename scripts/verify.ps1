$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)
$pythonTask = Join-Path (Get-Location) '.venv\Scripts\python.exe'
& $pythonTask -m ruff check src tests scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonTask -m mypy src\auditabr
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonTask -m pytest -q
exit $LASTEXITCODE
