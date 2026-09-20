# ============================================================================
# NetPulse launcher with automatic restart.
# Used by the Windows Scheduled Task "NetPulse" so the server
#   - starts automatically at boot / logon
#   - restarts itself if it ever crashes
# ============================================================================
$ErrorActionPreference = "Continue"

$root = "C:\Users\titas\Documents\Default Project\netpulse"
$py   = Join-Path $root ".venv\Scripts\python.exe"
$log  = Join-Path $root "server.log"
$maxBytes = 10MB

Set-Location $root

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    try { Add-Content -Path $log -Value $line -ErrorAction SilentlyContinue } catch {}
}

function Rotate-If-Big {
    try {
        if (Test-Path $log) {
            $f = Get-Item $log
            if ($f.Length -gt $maxBytes) {
                Remove-Item "$log.old" -Force -ErrorAction SilentlyContinue
                Move-Item $log "$log.old" -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
}

if (-not (Test-Path $py)) {
    Write-Log "ERROR: python not found at $py"
    exit 1
}

Write-Log "=== NetPulse launcher started ==="

while ($true) {
    Rotate-If-Big
    Write-Log "starting uvicorn on 0.0.0.0:8000"
    try {
        & $py -m uvicorn app.main:app --host 0.0.0.0 --port 8000 2>&1 |
            Out-File -FilePath $log -Append -Encoding utf8
    } catch {
        Write-Log ("uvicorn error: " + $_.Exception.Message)
    }
    Write-Log "server exited; restarting in 10 seconds"
    Start-Sleep -Seconds 10
}
