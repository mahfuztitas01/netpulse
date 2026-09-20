# ============================================================================
# NetPulse + Cloudflare public tunnel
# Starts the server (if not already running) and a public HTTPS tunnel,
# then prints the public URL.
# ============================================================================
$ErrorActionPreference = "Continue"
$root = "C:\Users\titas\Documents\Default Project\netpulse"
Set-Location $root

$py  = Join-Path $root ".venv\Scripts\python.exe"
$cf  = Join-Path $root "tools\cloudflared.exe"
$err = Join-Path $root "cf.err.log"
$out = Join-Path $root "cf.out.log"

Write-Host "=== NetPulse + Public Tunnel ===" -ForegroundColor Cyan

# ---- 1. server ----
$listening = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0
if (-not $listening) {
    Write-Host "Starting NetPulse server..."
    Start-Process -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000" -WindowStyle Hidden
    Start-Sleep -Seconds 5
} else {
    Write-Host "NetPulse server already running."
}

# ---- 2. tunnel ----
$cfRunning = (Get-Process cloudflared -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0
if (-not $cfRunning) {
    if (-not (Test-Path $cf)) {
        Write-Host "[ERROR] cloudflared not found at $cf" -ForegroundColor Red
        exit 1
    }
    Write-Host "Starting Cloudflare tunnel..."
    Remove-Item $err, $out -Force -ErrorAction SilentlyContinue
    Start-Process -FilePath $cf -ArgumentList "tunnel","--url","http://localhost:8000","--no-autoupdate" -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    Start-Sleep -Seconds 18
} else {
    Write-Host "Tunnel already running."
}

# ---- 3. show URL ----
$url = $null
if (Test-Path $err) {
    $url = (Get-Content $err -Raw -ErrorAction SilentlyContinue |
            Select-String -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -AllMatches).Matches.Value |
            Select-Object -Unique -First 1
}

Write-Host ""
if ($url) {
    Write-Host "  PUBLIC URL : $url" -ForegroundColor Green
} else {
    Write-Host "  Public URL not detected yet. Check cf.err.log" -ForegroundColor Yellow
}
Write-Host "  LOCAL URL  : http://localhost:8000"
Write-Host "  LAN URL    : http://$((Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -like '*Wi-Fi*' } | Select-Object -First 1).IPAddress):8000"
Write-Host ""
Write-Host "Note: a quick-tunnel URL changes every time it restarts."
Write-Host ""
Start-Process $url
