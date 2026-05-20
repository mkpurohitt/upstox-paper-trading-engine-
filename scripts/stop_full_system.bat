@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\stop_full_system.ps1"
exit /b %ERRORLEVEL%
