@echo off
title NetPulse - Stop
echo Stopping NetPulse (port 8000)...

set FOUND=0
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
  taskkill /F /PID %%a >nul 2>&1
  set FOUND=1
)

if "%FOUND%"=="1" (echo Stopped.) else (echo Nothing was running on port 8000.)
timeout /t 2 >nul
