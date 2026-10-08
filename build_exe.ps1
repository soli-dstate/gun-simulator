# Builds dist\GunSimulator.exe. Run from the project root:  .\build_exe.ps1
# (Exit codes are checked explicitly: PyInstaller logs to stderr, which
# $ErrorActionPreference = "Stop" would wrongly treat as a failure.)
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q -e ".[dev,build]"
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }
.\.venv\Scripts\python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "tests failed; not building" }
.\.venv\Scripts\pyinstaller --noconfirm --clean gun_sim.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host "`nBuilt: $PSScriptRoot\dist\GunSimulator.exe"
