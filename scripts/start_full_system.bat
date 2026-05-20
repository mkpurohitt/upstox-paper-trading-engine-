@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\start_full_system.ps1"
exit /b %ERRORLEVEL%
