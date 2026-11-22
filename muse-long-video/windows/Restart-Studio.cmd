@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1"
if errorlevel 1 exit /b 1
call studio\Open-Muse-Review.cmd
if errorlevel 1 pause
