@echo off
title NetPulse Server
cd /d "%~dp0"

echo ================================================
echo   NetPulse - Network Monitoring
echo ================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Run: powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
  pause
  exit /b 1
)

echo Starting server on http://localhost:8000 ...
echo (close this window or press Ctrl+C to stop)
echo.

start "" http://localhost:8000

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

pause
