@echo off
title NetPulse - Public Access
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "START_PUBLIC.ps1"
pause
