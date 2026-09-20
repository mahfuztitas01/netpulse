# ============================================================================
# NetPulse Cloudflare tunnel launcher with automatic restart + log rotation.
# Used by the Windows Scheduled Task "NetPulse-Tunnel".
#
# NOTE: a quick tunnel gets a NEW public URL each time it restarts. Check
#       cf.err.log for the current URL, or run START_PUBLIC.bat.
# ============================================================================
$ErrorActionPreference = "Continue"

$root = "C:\Users\titas\Documents\Default Project\netpulse"
$cf   = Join-Path $root "tools\cloudflared.exe"
$err  = Join-Path $root "cf.err.log"
$out  = Join-Path $root "cf.out.log"
$maxBytes = 5MB

Set-Location $root

function Rotate-If-Big([string]$path) {
    try {
        if (Test-Path $path) {
            $f = Get-Item $path
            if ($f.Length -gt $maxBytes) {
                $archive = "$path.old"
                Remove-Item $archive -Force -ErrorAction SilentlyContinue
                Move-Item $path $archive -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
}

if (-not (Test-Path $cf)) { exit 1 }

while ($true) {
    Rotate-If-Big $err
    Rotate-If-Big $out
    try {
        & $cf tunnel --url http://localhost:8000 --no-autoupdate 2>&1 |
            Out-File -FilePath $err -Append -Encoding utf8
    } catch {}
    Start-Sleep -Seconds 10
}
