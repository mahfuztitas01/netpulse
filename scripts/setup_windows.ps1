<#
.SYNOPSIS
    NetPulse - automated setup for Windows (local development / testing).

.DESCRIPTION
    Creates a virtual environment, installs dependencies, generates a .env with a
    random SECRET_KEY, and prints how to start the server.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
#>
[CmdletBinding()]
param(
    [switch]$Run
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Info($m) { Write-Host "[setup] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[warn]  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[error] $m" -ForegroundColor Red; exit 1 }

# ---- 1. Python ----
$python = $null
foreach ($candidate in @("py", "python")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $python = $candidate; break }
}
if (-not $python) { Fail "Python not found. Install Python 3.11/3.12 from python.org and re-run." }
$pyVersion = & $python --version 2>&1
Info "Using $pyVersion ($python)"

# ---- 2. virtualenv ----
if (-not (Test-Path ".venv")) {
    Info "Creating virtual environment .venv ..."
    & $python -m venv .venv
} else {
    Info ".venv already exists"
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { Fail "venv python not found at $venvPy" }

# ---- 3. dependencies ----
Info "Installing dependencies (this can take a minute)..."
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt --quiet
Info "Dependencies installed"

# ---- 4. .env ----
if (-not (Test-Path ".env")) {
    Info "Generating .env with a random SECRET_KEY ..."
    $secret = & $venvPy -c "import secrets; print(secrets.token_urlsafe(48))"
    $adminPw = & $venvPy -c "import secrets; print(secrets.token_urlsafe(12))"
    $content = Get-Content ".env.example" -Raw
    $content = $content -replace "SECRET_KEY=change-me-to-a-long-random-string", "SECRET_KEY=$secret"
    $content = $content -replace "FIRST_ADMIN_PASSWORD=change-me-strong-password", "FIRST_ADMIN_PASSWORD=$adminPw"
    Set-Content -Path ".env" -Value $content -Encoding UTF8
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Green
    Write-Host "   Admin password (SAVE IT NOW):  $adminPw" -ForegroundColor Green
    Write-Host "   Config file:                   $root\.env" -ForegroundColor Green
    Write-Host "  ============================================================" -ForegroundColor Green
    Write-Host ""
} else {
    Info ".env already exists - keeping it"
}

# ---- 5. quick self-test ----
Info "Running import self-test ..."
$env:PYTHONPATH = "."
& $venvPy -c "from app.main import app; print('  app import OK ->', app.title)"

Write-Host ""
Info "Setup complete."
Write-Host ""
Write-Host "  Start the server:" -ForegroundColor White
Write-Host "    .\.venv\Scripts\Activate.ps1" -ForegroundColor Gray
Write-Host "    uvicorn app.main:app --reload --port 8000" -ForegroundColor Gray
Write-Host "  Then open:  http://localhost:8000" -ForegroundColor White
Write-Host ""

if ($Run) {
    Info "Starting server (Ctrl+C to stop)..."
    & $venvPy -m uvicorn app.main:app --reload --port 8000
}
