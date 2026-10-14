# Bootstrap script for Windows
# Run: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
$toolkit = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $toolkit

Write-Host "Installing Workstation Toolkit..." -ForegroundColor Cyan

# Check Python
try {
    $py = python --version 2>&1
    Write-Host "  Python: $py" -ForegroundColor Green
} catch {
    Write-Host "  Python not found. Install from python.org or winget install Python" -ForegroundColor Red
    exit 1
}

# Install uv if missing
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host "  Installing uv..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -UseBasicParsing | Invoke-Expression
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

# Create venv and install
Set-Location $root
python -m venv .venv
& .\.venv\Scripts\pip install -e ".[dev]"

Write-Host "  Installed. Activate with: .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
Write-Host "  Run: python -m workstation diagnose" -ForegroundColor Gray
