# ============================================================================
# Set the GITHUB_TOKEN environment variable securely for opencode's GitHub MCP.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\set_github_token.ps1
#
# The token is read with a hidden prompt (never echoed, never written to disk
# in plain text) and stored as a *user* environment variable.
# ============================================================================
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== NetPulse / opencode - GitHub token setup ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Create a token first (classic, scopes: repo, read:org, workflow):" -ForegroundColor Yellow
Write-Host "  https://github.com/settings/tokens/new" -ForegroundColor Gray
Write-Host ""

$secure = Read-Host "Paste your GitHub token (input hidden)" -AsSecureString
if (-not $secure -or $secure.Length -eq 0) {
    Write-Host "No token entered. Aborted." -ForegroundColor Red
    exit 1
}

$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

$token = $token.Trim()
if ($token.Length -lt 20) {
    Write-Host "That does not look like a GitHub token. Aborted." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Verifying token against api.github.com ..." -ForegroundColor Cyan
try {
    $headers = @{
        Authorization          = "Bearer $token"
        "User-Agent"           = "netpulse-setup"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
    $me = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $headers -TimeoutSec 20
    Write-Host ("  ✅ Token valid - logged in as: {0} ({1})" -f $me.login, $me.name) -ForegroundColor Green
} catch {
    Write-Host ("  ❌ Token verification failed: {0}" -f $_.Exception.Message) -ForegroundColor Red
    Write-Host "     Check the token scopes/expiry and try again." -ForegroundColor Yellow
    exit 1
}

# verify MCP endpoint accepts it
try {
    $r = Invoke-WebRequest -Uri "https://api.githubcopilot.com/mcp/" -Method POST `
        -Headers @{ Authorization = "Bearer $token"; Accept = "application/json, text/event-stream" } `
        -ContentType "application/json" -TimeoutSec 20 -UseBasicParsing `
        -Body '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
    Write-Host ("  ✅ GitHub MCP endpoint responded HTTP {0}" -f $r.StatusCode) -ForegroundColor Green
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 200) {
        Write-Host "  ✅ GitHub MCP endpoint OK" -ForegroundColor Green
    } else {
        Write-Host ("  ⚠️ MCP endpoint returned HTTP {0} (may need Copilot access)" -f $code) -ForegroundColor Yellow
    }
}

[Environment]::SetEnvironmentVariable("GITHUB_TOKEN", $token, "User")
Write-Host ""
Write-Host "✅ GITHUB_TOKEN saved as a USER environment variable." -ForegroundColor Green
Write-Host ""
Write-Host "Next: fully quit and restart opencode so it picks up the variable." -ForegroundColor Cyan
Write-Host ""
$token = $null
